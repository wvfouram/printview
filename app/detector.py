"""Local spaghetti detection using Obico's open-source failure-detection model.

Model: Obico (The Spaghetti Detective) ONNX weights, run on the Pi CPU.
Scoring: a port of Obico's own algorithm (EWM of per-frame confidence sum vs
rolling baselines) with Obico's tuned hyperparameters, evaluated every 10 s.
"""
import io
import json
import logging
import os
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

log = logging.getLogger("detector")

BOX_THRESH = 0.08          # Obico ml_api threshold for a box to count
DRAW_THRESH = 0.2          # Obico visualization threshold
NMS_THRESH = 0.45
INTERVAL_S = 10            # Obico's params are tuned for 10 s between frames

PARAMS = {                 # Obico FD_1ST_GEN_PARAMS
    "EWM_SPAN": 12,
    "ROLLING_WIN_SHORT": 310,
    "ROLLING_WIN_LONG": 7200,
    "THRESHOLD_LOW": 0.38,
    "THRESHOLD_HIGH": 0.78,
    "INIT_SAFE_FRAME_NUM": 30,
    "ROLLING_MEAN_SHORT_MULTIPLE": 3.8,
    "ESCALATING_FACTOR": 1.75,
}

SENSITIVITY = {"low": 0.8, "medium": 1.0, "high": 1.2}


# --------------------------------------------------------------------------- model
class FailureModel:
    """Obico network. One forward pass gives failure boxes AND a feature vector."""

    def __init__(self, path: str, threads: int = 3):
        import onnx
        import onnxruntime as ort
        self.ort = ort
        self.opts = ort.SessionOptions()
        self.opts.intra_op_num_threads = threads   # leave a core free for the web app
        model = onnx.load(path)
        dims = model.graph.input[0].type.tensor_type.shape.dim
        self.in_h, self.in_w = int(dims[2].dim_value or 416), int(dims[3].dim_value or 416)
        self.input_name = model.graph.input[0].name
        self.det_outputs = [o.name for o in model.graph.output][:2]
        self.feat_outputs = []
        try:
            self.feat_outputs = self._pick_feature_tensors(model)
        except Exception:  # noqa: BLE001
            log.exception("feature discovery failed - custom training disabled")
        del model.graph.output[:]
        model.graph.output.extend(self._vi(n) for n in self.det_outputs + self.feat_outputs)
        self.session = ort.InferenceSession(model.SerializeToString(), self.opts,
                                            providers=["CPUExecutionProvider"])
        self.feature_dim = None
        if self.feat_outputs:
            _, f = self.detect(Image.new("RGB", (self.in_w, self.in_h)))
            self.feature_dim = int(f.shape[0])
            log.info("feature tensors %s -> %d dims", self.feat_outputs, self.feature_dim)

    @staticmethod
    def _vi(name):
        import onnx
        return onnx.helper.make_empty_tensor_value_info(name)

    def _pick_feature_tensors(self, model):
        """Find the last wide activation at stride 32 and stride 16 (the layers that feed the head)."""
        existing = {o.name for o in model.graph.output}
        inits = {i.name for i in model.graph.initializer}
        cands = []
        for node in model.graph.node:
            if node.op_type in ("Constant", "Shape", "Gather", "Unsqueeze", "Concat", "Reshape", "Cast"):
                continue
            for o in node.output:
                if o and o not in existing and o not in inits:
                    cands.append(o)
        probe = type(model)()
        probe.CopyFrom(model)
        del probe.graph.output[:]
        probe.graph.output.extend(self._vi(n) for n in cands)
        sess = self.ort.InferenceSession(probe.SerializeToString(), self.opts, providers=["CPUExecutionProvider"])
        outs = sess.run(None, {self.input_name: np.zeros((1, 3, self.in_h, self.in_w), np.float32)})
        picked = []
        for stride in (32, 16):
            h, w = self.in_h // stride, self.in_w // stride
            last = None
            for name, arr in zip(cands, outs):
                if isinstance(arr, np.ndarray) and arr.ndim == 4 and arr.shape[2:] == (h, w) \
                        and arr.shape[1] >= 64 and arr.dtype == np.float32:
                    last = name
            if last:
                picked.append(last)
        return picked

    def detect(self, img: Image.Image):
        """Returns (detections, features). detections: [(confidence, (x1,y1,x2,y2) normalized)]."""
        x = img.convert("RGB").resize((self.in_w, self.in_h), Image.BILINEAR)
        x = np.asarray(x, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        outs = self.session.run(None, {self.input_name: x})
        boxes, confs = outs[0], outs[1]
        boxes = boxes[0, :, 0, :]              # [N, 4] x1,y1,x2,y2
        conf = confs[0].max(axis=1)            # single class: "failure"
        keep = conf > BOX_THRESH
        boxes, conf = boxes[keep], conf[keep]
        idx = _nms(boxes, conf, NMS_THRESH)
        dets = [(float(conf[i]), tuple(float(v) for v in boxes[i])) for i in idx]
        feats = [np.concatenate([t.mean(axis=(2, 3))[0], t.max(axis=(2, 3))[0]]) for t in outs[2:]]
        return dets, (np.concatenate(feats).astype(np.float32) if feats else None)


def _nms(boxes, confs, thresh):
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)
    order = confs.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= thresh]
    return keep


def annotate(img: Image.Image, dets) -> bytes:
    img = img.convert("RGB")
    w, h = img.size
    d = ImageDraw.Draw(img)
    for conf, (x1, y1, x2, y2) in dets:
        if conf < DRAW_THRESH:
            continue
        d.rectangle([x1 * w, y1 * h, x2 * w, y2 * h], outline=(255, 70, 40), width=max(2, w // 300))
        d.text((x1 * w + 4, y1 * h + 2), f"{conf:.2f}", fill=(255, 70, 40))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


# --------------------------------------------------------------------------- scoring
class Prediction:
    def __init__(self):
        self.current_p = 0.0
        self.current_frame_num = 0
        self.lifetime_frame_num = 0
        self.ewm_mean = 0.0
        self.rolling_mean_short = 0.0
        self.rolling_mean_long = 0.0

    def reset_for_new_print(self):  # Obico keeps the long baseline across prints
        self.current_p = 0.0
        self.current_frame_num = 0
        self.ewm_mean = 0.0
        self.rolling_mean_short = 0.0

    def update(self, dets):
        p = sum(c for c, _ in dets)
        alpha = 2 / (PARAMS["EWM_SPAN"] + 1)
        self.current_p = p
        self.current_frame_num += 1
        self.lifetime_frame_num += 1
        self.ewm_mean = p * alpha + self.ewm_mean * (1 - alpha)
        self.rolling_mean_short = _roll(p, self.rolling_mean_short, self.current_frame_num, PARAMS["ROLLING_WIN_SHORT"])
        self.rolling_mean_long = _roll(p, self.rolling_mean_long, self.lifetime_frame_num, PARAMS["ROLLING_WIN_LONG"])

    def adjusted(self, sensitivity: float, escalating: float = 1.0) -> float:
        return (self.ewm_mean - self.rolling_mean_long) * sensitivity / escalating

    def is_failing(self, sensitivity: float, escalating: float = 1.0) -> bool:
        if self.current_frame_num < PARAMS["INIT_SAFE_FRAME_NUM"]:
            return False
        adj = self.adjusted(sensitivity, escalating)
        if adj < PARAMS["THRESHOLD_LOW"]:
            return False
        if adj > PARAMS["THRESHOLD_HIGH"]:
            return True
        return adj > (self.rolling_mean_short - self.rolling_mean_long) * PARAMS["ROLLING_MEAN_SHORT_MULTIPLE"]

    def to_dict(self):
        return dict(self.__dict__)

    def load(self, d):
        for k, v in d.items():
            if k in self.__dict__:
                setattr(self, k, v)


def _roll(p, mean, count, win):
    return mean + (p - mean) / float(win if win <= count else count + 1)


# --------------------------------------------------------------------------- loop
class DetectionLoop:
    """Every 10 s while printing: grab a frame, score it, record it, warn, then auto-pause.

    Until your own model is trained, Obico's stock algorithm decides.
    Once trained (and enabled), your model decides; Obico only adds warnings.
    """

    def __init__(self, model_path, camera, printer, settings, events, notifier, data_dir, dataset, trainer):
        self.camera, self.printer, self.settings = camera, printer, settings
        self.events, self.notifier = events, notifier
        self.dataset, self.trainer = dataset, trainer
        self.state_path = os.path.join(data_dir, "detector_state.json")
        self.model = None
        self.error = None
        self.pred = Prediction()
        self.last_run = 0.0
        self.last_infer_ms = None
        self.last_detection_jpeg: bytes | None = None
        self.last_detection_time = 0.0
        self.warned = False
        self.acted = False
        self.flagged = False
        self.resume_grace_until = 0.0
        self.ticks_since_resume = 0
        self.custom_p = None
        self.custom_s = None
        self.custom_prev = None
        self.custom_hits = 0
        try:
            with open(self.state_path) as f:
                self.pred.load(json.load(f))
        except (OSError, ValueError):
            pass
        if not os.path.exists(model_path):
            self.error = f"model not found at {model_path}"
            log.error(self.error)
            return
        try:
            self.model = FailureModel(model_path)
            log.info("failure model loaded (%dx%d)", self.model.in_w, self.model.in_h)
        except Exception as e:  # noqa: BLE001
            self.error = f"model failed to load: {e}"
            log.exception("model load")

    def start(self):
        threading.Thread(target=self._run, name="detector", daemon=True).start()

    def custom_active(self):
        return bool(self.trainer and self.trainer.model and self.settings.get("use_custom")
                    and self.model and self.model.feature_dim == self.trainer.model.dim)

    def status(self):
        sens = SENSITIVITY.get(self.settings.get("sensitivity"), 1.0)
        warmup_left = max(0, PARAMS["INIT_SAFE_FRAME_NUM"] - self.pred.current_frame_num)
        active = self.custom_active()
        T = self.trainer.threshold(self.settings.get("sensitivity")) if active else None
        return {
            "enabled": self.model is not None,
            "error": self.error,
            "mode": "custom" if active else "obico",
            "score": round(max(0.0, self.pred.adjusted(sens)), 3),
            "warn_at": PARAMS["THRESHOLD_LOW"],
            "pause_at": PARAMS["THRESHOLD_HIGH"],
            "custom_score": None if self.custom_s is None else round(self.custom_s, 3),
            "custom_pause_at": None if T is None else round(T, 3),
            "custom_warn_at": None if T is None else round(T * 0.75, 3),
            "current_p": round(self.pred.current_p, 3),
            "frames_this_print": self.pred.current_frame_num,
            "warmup_s": (max(0, 6 - self.pred.current_frame_num) if active else warmup_left) * INTERVAL_S,
            "warned": self.warned,
            "acted": self.acted,
            "infer_ms": self.last_infer_ms,
            "has_detection_image": self.last_detection_jpeg is not None,
            "recording": self.dataset.current if self.dataset else None,
        }

    def _save(self):
        try:
            with open(self.state_path, "w") as f:
                json.dump(self.pred.to_dict(), f)
        except OSError:
            pass

    def on_printer_state(self, old, new, job=""):
        """Called on gcode_state transitions."""
        if new == "RUNNING" and old != "PAUSE":
            self.pred.reset_for_new_print()
            self.warned = self.acted = self.flagged = False
            self.custom_s = self.custom_prev = self.custom_p = None
            f = (self.printer.status().get("file") or "") if self.printer else ""
            cali = any(k in (job + " " + f).lower() for k in ("auto_cali", "/usr/etc/print/", "calibration"))
            if self.dataset and not cali:      # calibration runs never go into the training data
                self.dataset.start_print(job)
        elif new == "RUNNING" and old == "PAUSE":
            # resumed: give it a minute and clear short-term memory so it doesn't re-pause on stale readings
            self.pred.ewm_mean = 0.0
            self.custom_s = self.custom_prev = None
            self.warned = self.acted = False
            self.resume_grace_until = time.time() + 60
        elif new in ("FINISH", "FAILED", "IDLE") and self.dataset and self.dataset.current:
            self.dataset.end_print(new, self.flagged)

    def _run(self):
        if self.model is None:
            return
        while True:
            time.sleep(INTERVAL_S)
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("detection tick failed")

    def _tick(self):
        if self.printer.state != "RUNNING" or time.time() < self.resume_grace_until:
            return
        jpeg, _, t = self.camera.latest()
        if not jpeg or time.time() - t > 30:
            return
        img = Image.open(io.BytesIO(jpeg))
        img.load()
        t0 = time.time()
        dets, feats = self.model.detect(img)
        self.last_infer_ms = int((time.time() - t0) * 1000)
        self.pred.update(dets)
        self.last_run = time.time()
        if self.pred.lifetime_frame_num % 30 == 0:
            self._save()

        # your own model
        self.custom_p = None
        if feats is not None and self.trainer and self.trainer.model:
            self.custom_p = self.trainer.model.score(feats)
            if self.custom_p is not None:
                self.custom_prev = self.custom_s
                self.custom_s = self.custom_p if self.custom_s is None else 0.5 * self.custom_p + 0.5 * self.custom_s
        if feats is not None and self.dataset:
            self.dataset.add_tick(img, feats, sum(c for c, _ in dets), self.custom_p)

        sens_name = self.settings.get("sensitivity")
        sens = SENSITIVITY.get(sens_name, 1.0)
        obico_warn = self.pred.is_failing(sens)
        obico_pause = self.pred.is_failing(sens, PARAMS["ESCALATING_FACTOR"])
        if self.custom_active() and self.custom_s is not None:
            T = self.trainer.threshold(sens_name)
            warm = self.pred.current_frame_num > 6
            failing_pause = warm and self.custom_prev is not None and self.custom_s >= T and self.custom_prev >= T
            failing_warn = warm and (self.custom_s >= T * 0.75 or obico_pause)
        else:
            failing_pause, failing_warn = obico_pause, obico_warn

        if any(c >= DRAW_THRESH for c, _ in dets):
            self.last_detection_jpeg = annotate(img, dets)
            self.last_detection_time = time.time()

        if failing_pause and not self.acted:
            self.acted = self.flagged = True
            if self.dataset:
                self.dataset.mark_flagged()
            snap = annotate(img, dets)
            self.last_detection_jpeg, self.last_detection_time = snap, time.time()
            if self.settings.get("auto_pause"):
                ok = self.printer.pause()
                self.events.add("detect", "Spaghetti detected - print paused" if ok else "Spaghetti detected - PAUSE FAILED")
                self.notifier.send("Print paused: spaghetti detected",
                                   "PrintWatch paused your print. Check the camera.", priority="urgent",
                                   tags="warning", image=snap)
            else:
                self.events.add("detect", "Spaghetti detected (auto-pause off)")
                self.notifier.send("Spaghetti detected", "Auto-pause is off. Check your print now.",
                                   priority="urgent", tags="warning", image=snap)
        elif failing_warn and not self.warned and not self.acted:
            self.warned = self.flagged = True
            if self.dataset:
                self.dataset.mark_flagged()
            snap = annotate(img, dets)
            self.last_detection_jpeg, self.last_detection_time = snap, time.time()
            self.events.add("warn", "Possible failure - keep an eye on it")
            self.notifier.send("Possible print failure", "Something looks off. Take a look.",
                               priority="high", tags="eyes", image=snap)
