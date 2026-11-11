"""Clear-plate check: when a print starts, look at the bed and warn if something is still on it.

Two signals, both from the camera:
1. Unchanged since the last print ended. The bed stays where the last print left it until the new print
   homes, so if the bed area looks almost exactly like the photo taken after the last print finished,
   nobody took the part off.
2. Different from your clean plates. Every time you say "the plate was clear" (or a check passes and the
   print then runs fine) that start photo is kept as a clean example. A start photo far from all of them
   (pixels + the detector network's features) is suspicious.
A warning sends a phone notification with the photo; optionally the print is paused.
"""
import io
import json
import logging
import os
import threading
import time

import numpy as np
from PIL import Image, ImageFilter

log = logging.getLogger("platecheck")
STARTS = ("PREPARE", "SLICING", "RUNNING")
IDLE = ("IDLE", "FINISH", "FAILED", "UNKNOWN", None)
MAX_REFS = 30
SAME_T = 7.0        # mean grey difference (0-255) under this = "unchanged since last print"
CLEAN_T = 14.0      # pixel distance to nearest clean plate above this = "looks different"
FEAT_T = 0.10       # feature (cosine) distance above this = "looks different"


def _small(jpeg):
    """Bed area (lower 60 % of the picture) as a small blurred grey image, brightness-normalised."""
    im = Image.open(io.BytesIO(jpeg)).convert("L")
    w, h = im.size
    im = im.crop((int(w * 0.08), int(h * 0.40), int(w * 0.92), h)).resize((128, 64)).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(im, dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-3) * 40 + 128


def _diff(a, b):
    return float(np.mean(np.abs(a - b)))


class PlateCheck:
    def __init__(self, printer, camera, detector, notifier, events, settings, data_dir):
        self.printer, self.camera, self.detector = printer, camera, detector
        self.notifier, self.events, self.settings = notifier, events, settings
        self.dir = os.path.join(data_dir, "platecheck")
        os.makedirs(os.path.join(self.dir, "clean"), exist_ok=True)
        self.result = self._load("last.json") or None
        self._pending_ok = None
        printer.on_change(self._on_state)

    # ---------------------------------------------------------------- files
    def _p(self, *a):
        return os.path.join(self.dir, *a)

    def _load(self, name):
        try:
            with open(self._p(name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save(self, name, obj):
        with open(self._p(name + ".tmp"), "w") as f:
            json.dump(obj, f)
        os.replace(self._p(name + ".tmp"), self._p(name))

    def _frame(self, max_age=8):
        jpeg, _, t = self.camera.latest()
        return jpeg if jpeg and time.time() - t < max_age else None

    def _feat(self, jpeg):
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
            _, f = self.detector.model.detect(img)
            if f is None:
                return None
            f = np.asarray(f, np.float32)
            return f / (np.linalg.norm(f) + 1e-6)
        except Exception:  # noqa: BLE001
            return None

    def _refs(self):
        out = []
        d = self._p("clean")
        for n in sorted(os.listdir(d)):
            if n.endswith(".jpg"):
                try:
                    with open(os.path.join(d, n), "rb") as f:
                        jp = f.read()
                    fe = os.path.join(d, n[:-4] + ".npy")
                    out.append((n, _small(jp), np.load(fe) if os.path.exists(fe) else None))
                except Exception:  # noqa: BLE001
                    pass
        return out

    def add_clean(self, jpeg):
        """Keep a photo as an example of a clear plate."""
        name = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        with open(self._p("clean", name + ".jpg"), "wb") as f:
            f.write(jpeg)
        fe = self._feat(jpeg)
        if fe is not None:
            np.save(self._p("clean", name + ".npy"), fe)
        refs = sorted(n for n in os.listdir(self._p("clean")) if n.endswith(".jpg"))
        for n in refs[:-MAX_REFS]:
            for ext in (".jpg", ".npy"):
                try:
                    os.remove(self._p("clean", n[:-4] + ext))
                except OSError:
                    pass
        return len(refs[-MAX_REFS:])

    # ---------------------------------------------------------------- printer events
    def _on_state(self, old, new, snap):
        if old is None:
            return
        if new in ("FINISH", "FAILED"):
            threading.Thread(target=self._grab_end, daemon=True).start()
            if new == "FINISH" and self._pending_ok:      # the check passed and the print went fine
                jp, self._pending_ok = self._pending_ok, None
                try:
                    self.add_clean(jp)
                except Exception:  # noqa: BLE001
                    pass
            return
        if new in STARTS and old in IDLE:
            if self.settings.get("plate_check") is False:
                return
            threading.Thread(target=self._check, args=(snap.get("job") or "",), daemon=True).start()

    def _grab_end(self):
        time.sleep(90)                                  # let the end G-code park the toolhead and drop the bed
        jp = self._frame()
        if jp:
            with open(self._p("end.jpg"), "wb") as f:
                f.write(jp)

    def _check(self, job):
        time.sleep(1.5)
        jp = self._frame()
        if not jp:
            return
        with open(self._p("start.jpg"), "wb") as f:
            f.write(jp)
        cur = _small(jp)
        reasons, scores = [], {}
        # 1. same as when the last print ended?
        try:
            if os.path.exists(self._p("end.jpg")) and time.time() - os.path.getmtime(self._p("end.jpg")) < 14 * 86400:
                with open(self._p("end.jpg"), "rb") as f:
                    d_end = _diff(cur, _small(f.read()))
                scores["vs_last_end"] = round(d_end, 1)
                if d_end < SAME_T:
                    reasons.append("the bed looks the same as when the last print finished, so the part may still be on it")
        except Exception:  # noqa: BLE001
            pass
        # 2. far from every clean plate?
        refs = self._refs()
        if len(refs) >= 2:
            d_px = min(_diff(cur, r[1]) for r in refs)
            scores["vs_clean_px"] = round(d_px, 1)
            fe = self._feat(jp)
            fd = [1 - float(fe @ r[2]) for r in refs if fe is not None and r[2] is not None and r[2].shape == fe.shape]
            if fd:
                scores["vs_clean_ai"] = round(min(fd), 3)
            if d_px > CLEAN_T and (not fd or min(fd) > FEAT_T):
                reasons.append("the bed doesn't look like your clear plates")
        scores["clean_examples"] = len(refs)
        ok = not reasons
        self.result = {"t": int(time.time()), "job": job, "ok": ok, "reasons": reasons, "scores": scores,
                       "learning": len(refs) < 2, "answered": None}
        self._save("last.json", self.result)
        log.info("plate check %s %s", "OK" if ok else "WARN", scores)
        if ok:
            self._pending_ok = jp
            return
        self._pending_ok = None
        msg = "Something may still be on the build plate: " + "; ".join(reasons) + "."
        if self.events:
            self.events.add("warn", "Plate check: " + msg)
        paused = False
        if self.settings.get("plate_pause"):
            try:
                paused = bool(self.printer.pause())
            except Exception:  # noqa: BLE001
                paused = False
        if self.notifier:
            self.notifier.send("Check the build plate" + (" (print paused)" if paused else ""),
                               (job + ": " if job else "") + msg + (" The print is paused." if paused else
                               " The print is still starting."), priority="high", tags="warning", image=jp)

    # ---------------------------------------------------------------- feedback / api
    def answer(self, was_clear: bool):
        """You tell it whether the plate really was clear on the last check (it learns from 'clear')."""
        if not self.result:
            raise ValueError("no check yet")
        if was_clear and os.path.exists(self._p("start.jpg")):
            with open(self._p("start.jpg"), "rb") as f:
                self.add_clean(f.read())
        self.result["answered"] = "clear" if was_clear else "not clear"
        self._save("last.json", self.result)
        return self.result

    def save_now_clean(self):
        jp = self._frame()
        if not jp:
            raise ValueError("no camera picture right now")
        return self.add_clean(jp)

    def photo(self):
        p = self._p("start.jpg")
        return p if os.path.exists(p) else None

    def status(self):
        r = dict(self.result or {})
        r["clean_examples"] = len([n for n in os.listdir(self._p("clean")) if n.endswith(".jpg")])
        r["enabled"] = self.settings.get("plate_check") is not False
        r["pause"] = bool(self.settings.get("plate_pause"))
        return r
