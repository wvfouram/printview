"""Every print becomes training data.

Layout:  <data>/dataset/<print_id>/
            meta.json     job, times, end state, label
            ticks.jsonl   one line per 10 s check: index, time, Obico score, custom score
            emb.f16       float16 feature vectors (one per tick) from the Obico network
            frames/NNNNN.jpg   480 px thumbnails (pruned for old good prints when disk fills)

Labels:  "good"   - whole print was fine
         "failed" - frames from fail_start onward are a failure, before it are fine
         "ignore" - excluded from training (hand in frame, light off, etc.)
         None     - needs review
"""
import json
import logging
import os
import shutil
import threading
import time

import numpy as np

log = logging.getLogger("dataset")
THUMB_W = 480


class Dataset:
    def __init__(self, data_dir: str, max_gb: float = 3.0):
        self.root = os.path.join(data_dir, "dataset")
        os.makedirs(self.root, exist_ok=True)
        self.max_bytes = int(max_gb * 1024 ** 3)
        self.current: str | None = None
        self._n = 0
        self._lock = threading.RLock()
        self._listeners = []
        # anything still "recording" was cut off by a restart
        for pid in os.listdir(self.root):
            m = self.meta(pid)
            if m and m.get("status") == "recording":
                m.update(status="done", end_state="INTERRUPTED", ended=m.get("last_tick") or m["started"])
                self._write_meta(pid, m)

    def on_labeled(self, fn):
        self._listeners.append(fn)

    # ------------------------------------------------------------- paths / io
    def _dir(self, pid):
        if not pid or "/" in pid or ".." in pid:
            raise ValueError("bad print id")
        return os.path.join(self.root, pid)

    def meta(self, pid):
        try:
            with open(os.path.join(self._dir(pid), "meta.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write_meta(self, pid, m):
        p = os.path.join(self._dir(pid), "meta.json")
        with open(p + ".tmp", "w") as f:
            json.dump(m, f)
        os.replace(p + ".tmp", p)

    def frame_path(self, pid, i):
        return os.path.join(self._dir(pid), "frames", f"{int(i):05d}.jpg")

    # ------------------------------------------------------------- recording
    def start_print(self, job: str):
        with self._lock:
            if self.current:
                self.end_print("INTERRUPTED", False)
            base = time.strftime("%Y%m%d-%H%M%S")
            pid, k = base, 1
            while os.path.exists(self._dir(pid)):
                k += 1
                pid = f"{base}-{k}"
            os.makedirs(os.path.join(self._dir(pid), "frames"), exist_ok=True)
            self._write_meta(pid, {"id": pid, "job": job or "Print", "started": time.time(), "ended": None,
                                   "status": "recording", "end_state": None, "label": None, "auto": False,
                                   "fail_start": None, "flagged": False, "n": 0, "dim": None,
                                   "frames_pruned": False, "last_tick": None})
            self.current, self._n = pid, 0
            log.info("recording print %s (%s)", pid, job)
            return pid

    def add_tick(self, img, emb: np.ndarray, p_obico: float, p_custom: float | None):
        with self._lock:
            pid = self.current
            if not pid:
                return
            d = self._dir(pid)
            i = self._n
            try:
                th = img.convert("RGB")
                if th.width > THUMB_W:
                    th = th.resize((THUMB_W, round(th.height * THUMB_W / th.width)))
                th.save(self.frame_path(pid, i), "JPEG", quality=72)
                with open(os.path.join(d, "emb.f16"), "ab") as f:
                    f.write(emb.astype(np.float16).tobytes())
                with open(os.path.join(d, "ticks.jsonl"), "a") as f:
                    f.write(json.dumps({"i": i, "t": round(time.time(), 1), "po": round(p_obico, 4),
                                        "pc": None if p_custom is None else round(p_custom, 4)}) + "\n")
            except OSError as e:
                log.warning("could not record tick: %s", e)
                return
            self._n += 1
            if i == 0 or i % 30 == 0:
                m = self.meta(pid)
                m.update(n=self._n, dim=int(emb.shape[0]), last_tick=time.time())
                self._write_meta(pid, m)

    PHOTOS = "photos"

    def add_photo(self, img, emb: np.ndarray, p_obico: float):
        """A spaghetti picture someone uploaded. All of them live in one entry labeled failed; the trainer
        uses them as extra failure examples (they don't count as failed prints)."""
        with self._lock:
            pid = self.PHOTOS
            d = self._dir(pid)
            os.makedirs(os.path.join(d, "frames"), exist_ok=True)
            m = self.meta(pid) or {"id": pid, "job": "Uploaded spaghetti photos", "started": time.time(),
                                   "ended": time.time(), "status": "done", "end_state": "PHOTOS", "label": "failed",
                                   "auto": False, "fail_start": 0, "flagged": False, "n": 0, "dim": None,
                                   "frames_pruned": False, "last_tick": None, "source": "upload"}
            if m.get("dim") and m["dim"] != int(emb.shape[0]):
                raise ValueError("feature size changed; delete the old uploaded photos first")
            i = m["n"]
            th = img.convert("RGB")
            if th.width > THUMB_W:
                th = th.resize((THUMB_W, round(th.height * THUMB_W / th.width)))
            th.save(self.frame_path(pid, i), "JPEG", quality=80)
            with open(os.path.join(d, "emb.f16"), "ab") as f:
                f.write(emb.astype(np.float16).tobytes())
            with open(os.path.join(d, "ticks.jsonl"), "a") as f:
                f.write(json.dumps({"i": i, "t": round(time.time(), 1), "po": round(p_obico, 4), "pc": None}) + "\n")
            m.update(n=i + 1, dim=int(emb.shape[0]), ended=time.time(), last_tick=time.time(), label="failed", fail_start=0)
            self._write_meta(pid, m)
        for fn in self._listeners:
            fn()
        return m

    def end_print(self, end_state: str, flagged: bool):
        with self._lock:
            pid, self.current = self.current, None
            if not pid:
                return
            m = self.meta(pid)
            m.update(status="done", ended=time.time(), end_state=end_state, n=self._n, flagged=bool(flagged))
            if self._n == 0:
                shutil.rmtree(self._dir(pid), ignore_errors=True)
                return
            if end_state == "FINISH" and not flagged:
                m.update(label="good", auto=True)  # finished cleanly: almost certainly fine
            self._write_meta(pid, m)
            log.info("print %s ended %s (%d frames, label=%s)", pid, end_state, self._n, m["label"])
        threading.Thread(target=self.prune, daemon=True).start()
        if m["label"]:
            for fn in self._listeners:
                fn()

    def mark_flagged(self):
        with self._lock:
            if self.current:
                m = self.meta(self.current)
                m["flagged"] = True
                self._write_meta(self.current, m)

    # ------------------------------------------------------------- browsing / labels
    def list(self):
        out = []
        for pid in sorted(os.listdir(self.root), reverse=True):
            m = self.meta(pid)
            if m:
                if pid == self.current:
                    m["n"] = self._n
                out.append(m)
        return out

    def ticks(self, pid):
        out = []
        try:
            with open(os.path.join(self._dir(pid), "ticks.jsonl")) as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        return out

    def embeddings(self, pid, dim):
        p = os.path.join(self._dir(pid), "emb.f16")
        try:
            a = np.fromfile(p, dtype=np.float16)
        except OSError:
            return None
        n = a.size // dim
        return a[: n * dim].reshape(n, dim).astype(np.float32)

    def set_label(self, pid, label, fail_start=None):
        if label not in ("good", "failed", "ignore", None):
            raise ValueError("bad label")
        with self._lock:
            m = self.meta(pid)
            if not m:
                raise KeyError(pid)
            if m["status"] == "recording":
                raise ValueError("print still recording")
            if label == "failed":
                fail_start = int(fail_start)
                if not 0 <= fail_start < m["n"]:
                    raise ValueError("fail_start out of range")
            m.update(label=label, auto=False, fail_start=fail_start if label == "failed" else None)
            self._write_meta(pid, m)
        for fn in self._listeners:
            fn()
        return m

    def delete(self, pid):
        if pid == self.current:
            raise ValueError("print still recording")
        shutil.rmtree(self._dir(pid), ignore_errors=True)
        for fn in self._listeners:
            fn()

    # ------------------------------------------------------------- disk
    def prune(self):
        """Over budget: drop thumbnails of the oldest good/ignored prints (features are kept)."""
        def size(pid):
            fr = os.path.join(self._dir(pid), "frames")
            try:
                return sum(e.stat().st_size for e in os.scandir(fr))
            except OSError:
                return 0
        try:
            prints = sorted(self.list(), key=lambda m: m["started"])
            total = sum(size(m["id"]) for m in prints)
            for m in prints:
                if total <= self.max_bytes:
                    break
                if m["label"] in ("good", "ignore") and not m.get("frames_pruned") and m["id"] != self.current:
                    s = size(m["id"])
                    shutil.rmtree(os.path.join(self._dir(m["id"]), "frames"), ignore_errors=True)
                    m["frames_pruned"] = True
                    self._write_meta(m["id"], m)
                    total -= s
                    log.info("pruned frames of %s (%.0f MB)", m["id"], s / 1e6)
        except Exception:  # noqa: BLE001
            log.exception("prune failed")

    def counts(self):
        c = {"good": 0, "failed": 0, "ignore": 0, "review": 0, "photos": 0}
        for m in self.list():
            if m["status"] == "recording":
                continue
            if m.get("source") == "upload":
                c["photos"] = m.get("n", 0)
                continue
            c[m["label"] or "review"] += 1
        return c
