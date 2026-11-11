"""Per-printer failure model, trained on the Pi from your labeled prints.

Features: pooled activations from the Obico network's last layers (it already
runs every 10 s, so features cost nothing extra). On top of that we fit a
class-balanced logistic regression on YOUR camera, bed, lighting and filaments.

Honest accuracy: grouped cross-validation by print (a print is never in both
train and test), then we replay the exact trigger rule the live detector uses
and count caught failures, detection delay and false alarms. The same replay
is run for Obico's stock algorithm on the same prints for comparison.
"""
import json
import logging
import os
import threading
import time

import numpy as np

from .detector import PARAMS as OBICO, Prediction, SENSITIVITY, INTERVAL_S

log = logging.getLogger("trainer")

MIN_FAILED = 3          # failed prints needed before the model can go live
MIN_GOOD = 3
MAX_PER_PRINT = 150     # cap frames per print in the training matrix (RAM on the Pi)
BOUNDARY_SKIP = 2       # frames just before the marked failure start are ambiguous; leave out
WARMUP_TICKS = 6        # 1 minute at the start of a print
EWM_ALPHA = 0.5
SENS_OFFSET = {"low": 0.08, "medium": 0.0, "high": -0.08}


# ------------------------------------------------------------------ math
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logreg(X, y, l2=1e-2, iters=400, lr=0.05):
    mu = X.mean(0)
    sd = X.std(0) + 1e-6
    Z = (X - mu) / sd
    n, d = Z.shape
    pos = max(y.mean(), 1e-6)
    sw = np.where(y == 1, 0.5 / pos, 0.5 / (1 - pos)).astype(np.float32)
    w = np.zeros(d, np.float32)
    b = 0.0
    mw = np.zeros_like(w); vw = np.zeros_like(w); mb = vb = 0.0
    for t in range(1, iters + 1):  # Adam, full batch
        p = _sigmoid(Z @ w + b)
        g = (p - y) * sw / n
        gw = Z.T @ g + l2 * w
        gb = float(g.sum())
        mw = 0.9 * mw + 0.1 * gw; vw = 0.999 * vw + 0.001 * gw * gw
        mb = 0.9 * mb + 0.1 * gb; vb = 0.999 * vb + 0.001 * gb * gb
        c1, c2 = 1 - 0.9 ** t, 1 - 0.999 ** t
        w -= lr * (mw / c1) / (np.sqrt(vw / c2) + 1e-8)
        b -= lr * (mb / c1) / (np.sqrt(vb / c2) + 1e-8)
    return {"w": w, "b": np.float32(b), "mu": mu.astype(np.float32), "sd": sd.astype(np.float32)}


def _auc(s, y):
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return None
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return round(float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))), 3)


def predict(params, X):
    return _sigmoid(((X - params["mu"]) / params["sd"]) @ params["w"] + params["b"])


def smooth(ps):
    s, out = 0.0, []
    for i, p in enumerate(ps):
        s = p if i == 0 else EWM_ALPHA * p + (1 - EWM_ALPHA) * s
        out.append(s)
    return np.array(out)


def first_trigger(ps, T, start=0):
    """Live rule: smoothed score >= T on two consecutive checks, after warm-up."""
    s = smooth(ps)
    for i in range(max(start, WARMUP_TICKS, 1), len(s)):
        if s[i] >= T and s[i - 1] >= T:
            return i
    return None


def obico_trigger(pos):
    """Replay Obico's stock pause rule (medium sensitivity) on stored per-frame scores."""
    pred = Prediction()
    for i, p in enumerate(pos):
        pred.update([(p, None)])
        if pred.is_failing(SENSITIVITY["medium"], OBICO["ESCALATING_FACTOR"]):
            return i
    return None


# ------------------------------------------------------------------ model
class CustomModel:
    def __init__(self, params, threshold, dim, report):
        self.params, self.threshold, self.dim, self.report = params, float(threshold), int(dim), report

    def score(self, emb):
        if emb.shape[0] != self.dim:
            return None
        return float(predict(self.params, emb[None].astype(np.float32))[0])

    def save(self, path):
        np.savez(path + ".tmp.npz", threshold=self.threshold, dim=self.dim, **self.params)
        os.replace(path + ".tmp.npz", path)
        with open(path + ".json", "w") as f:
            json.dump(self.report, f)

    @classmethod
    def load(cls, path):
        try:
            z = np.load(path)
            with open(path + ".json") as f:
                report = json.load(f)
            params = {k: z[k] for k in ("w", "b", "mu", "sd")}
            return cls(params, float(z["threshold"]), int(z["dim"]), report)
        except (OSError, ValueError, KeyError):
            return None


# ------------------------------------------------------------------ training
def _load(dataset):
    prints = []
    for m in dataset.list():
        if m["status"] != "done" or m["label"] not in ("good", "failed") or not m.get("dim"):
            continue
        if m.get("source") == "upload":       # uploaded photos: extra failure examples, handled in train()
            continue
        X = dataset.embeddings(m["id"], m["dim"])
        if X is None or len(X) < WARMUP_TICKS + 2:
            continue
        ticks = dataset.ticks(m["id"])
        n = min(len(X), len(ticks)) if ticks else len(X)
        X = X[:n]
        po = np.array([t.get("po", 0.0) for t in ticks[:n]]) if ticks else np.zeros(n)
        y = np.zeros(n, np.float32)
        mask = np.ones(n, bool)
        fs = None
        if m["label"] == "failed":
            fs = min(int(m["fail_start"]), n - 1)
            y[fs:] = 1
            mask[max(0, fs - BOUNDARY_SKIP):fs] = False
        prints.append({"id": m["id"], "job": m["job"], "failed": m["label"] == "failed", "fs": fs,
                       "X": X, "y": y, "mask": mask, "po": po, "dim": m["dim"]})
    if prints:  # only use prints recorded with the current feature size
        dim = max(set(p["dim"] for p in prints), key=lambda d: sum(p["dim"] == d for p in prints))
        prints = [p for p in prints if p["dim"] == dim]
    return prints


def _photos(dataset, dim):
    """Uploaded spaghetti photos as extra failure frames (training only, never scored as prints)."""
    m = dataset.meta(dataset.PHOTOS) if hasattr(dataset, "PHOTOS") else None
    if not m or m.get("dim") != dim or m.get("label") != "failed":
        return None
    X = dataset.embeddings(m["id"], dim)
    return X if X is not None and len(X) else None


def _matrix(prints, rng, extra=None):
    Xs, ys = [], []
    if extra is not None:
        Xs.append(extra); ys.append(np.ones(len(extra), np.float32))
    for p in prints:
        idx = np.where(p["mask"])[0]
        if p["failed"]:  # keep every failure frame, subsample the good part
            fail = idx[p["y"][idx] == 1]
            good = idx[p["y"][idx] == 0]
            if len(good) > MAX_PER_PRINT:
                good = rng.choice(good, MAX_PER_PRINT, replace=False)
            idx = np.concatenate([fail, good])
        elif len(idx) > MAX_PER_PRINT:
            idx = rng.choice(idx, MAX_PER_PRINT, replace=False)
        Xs.append(p["X"][idx]); ys.append(p["y"][idx])
    return np.concatenate(Xs), np.concatenate(ys)


def _evaluate(prints, scores, T, trig):
    caught, delays, false_alarms, missed = 0, [], 0, []
    good_hours = 0.0
    for p, s in zip(prints, scores):
        i = trig(s, T) if T is not None else trig(s)
        if p["failed"]:
            good_hours += p["fs"] * INTERVAL_S / 3600
            if i is not None and i < p["fs"] - BOUNDARY_SKIP:
                false_alarms += 1
                missed.append(p["job"])
            elif i is not None:
                caught += 1
                delays.append(max(0, i - p["fs"]) * INTERVAL_S)
            else:
                missed.append(p["job"])
        else:
            good_hours += len(s) * INTERVAL_S / 3600
            if i is not None:
                false_alarms += 1
    n_failed = sum(p["failed"] for p in prints)
    return {"caught": caught, "failed": n_failed, "missed": missed,
            "median_delay_s": int(np.median(delays)) if delays else None,
            "false_alarms": false_alarms, "good_prints": len(prints) - n_failed,
            "good_hours": round(good_hours, 1)}


def train(dataset):
    t0 = time.time()
    rng = np.random.default_rng(0)
    prints = _load(dataset)
    nf = sum(p["failed"] for p in prints)
    ng = len(prints) - nf
    base = {"trained_at": int(time.time()), "failed_prints": nf, "good_prints": ng,
            "need_failed": max(0, MIN_FAILED - nf), "need_good": max(0, MIN_GOOD - ng)}
    if nf < MIN_FAILED or ng < MIN_GOOD:
        return None, {**base, "ok": False, "message": "Not enough labeled prints yet"}

    photos = _photos(dataset, prints[0]["dim"])
    base["photos"] = 0 if photos is None else int(len(photos))

    # grouped, stratified folds: a print never appears in both train and test
    k = min(5, nf)
    folds = [[] for _ in range(k)]
    for group in ([p for p in prints if p["failed"]], [p for p in prints if not p["failed"]]):
        order = rng.permutation(len(group))
        for j, o in enumerate(order):
            folds[j % k].append(group[o])
    oof = {}
    for f in range(k):
        train_set = [p for g, fold in enumerate(folds) if g != f for p in fold]
        X, y = _matrix(train_set, rng, photos)
        params = fit_logreg(X, y)
        for p in folds[f]:
            oof[p["id"]] = predict(params, p["X"])
    scores = [oof[p["id"]] for p in prints]

    # threshold: best trade-off on held-out scores (a false alarm costs 1.5x a miss),
    # ties go to the higher (safer) threshold
    trig = lambda s, T: first_trigger(s, T)  # noqa: E731
    best = None
    for T in np.round(np.arange(0.40, 0.975, 0.025), 3):
        r = _evaluate(prints, scores, T, trig)
        obj = r["caught"] - 1.5 * r["false_alarms"]
        if best is None or obj >= best[0]:
            best = (obj, float(T), r)
    _, T, cv = best
    cv["frame_auc"] = _auc(np.concatenate([s[p["mask"]] for p, s in zip(prints, scores)]),
                           np.concatenate([p["y"][p["mask"]] for p in prints]))
    obico = _evaluate(prints, [p["po"] for p in prints], None, obico_trigger)

    X, y = _matrix(prints, rng, photos)
    final = fit_logreg(X, y)
    report = {**base, "ok": True, "threshold": round(T, 3), "cv": cv, "obico": obico,
              "frames": int(len(X)), "seconds": round(time.time() - t0, 1),
              "message": f"Caught {cv['caught']}/{cv['failed']} failures, {cv['false_alarms']} false alarms"}
    log.info("trained in %.1fs: %s (obico: %d/%d, %d false)", report["seconds"], report["message"],
             obico["caught"], obico["failed"], obico["false_alarms"])
    return CustomModel(final, T, prints[0]["dim"], report), report


class Trainer:
    """Background training; retrains automatically a little after labels change."""

    def __init__(self, dataset, model_path, events):
        self.dataset, self.path, self.events = dataset, model_path, events
        self.model = CustomModel.load(model_path)
        self.report = self.model.report if self.model else None
        self.running = False
        self.error = None
        self._timer = None
        self._lock = threading.Lock()
        dataset.on_labeled(self.schedule)

    def schedule(self, delay=20):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self.run)
            self._timer.daemon = True
            self._timer.start()

    def run(self):
        with self._lock:
            if self.running:
                return
            self.running = True
        try:
            model, report = train(self.dataset)
            self.report = report
            self.error = None
            if model:
                model.save(self.path)
                self.model = model
                self.events.add("train", "Model retrained: " + report["message"])
            elif self.model is None:
                pass
        except Exception as e:  # noqa: BLE001
            log.exception("training failed")
            self.error = str(e)
        finally:
            self.running = False

    def start_now(self):
        threading.Thread(target=self.run, daemon=True).start()

    def threshold(self, sensitivity):
        if not self.model:
            return None
        return float(np.clip(self.model.threshold + SENS_OFFSET.get(sensitivity, 0.0), 0.3, 0.98))

    def status(self):
        return {"trained": self.model is not None, "running": self.running, "error": self.error,
                "report": self.report, "counts": self.dataset.counts(),
                "min_failed": MIN_FAILED, "min_good": MIN_GOOD}
