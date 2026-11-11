"""Per-layer timelapse from the P1S chamber camera.

While a print runs, every new camera frame is kept (small copy for scoring, full JPEG on disk)
until the layer changes. At each layer change the frame where the toolhead blocks the least is
kept: the pixel-median of all that layer's frames erases the moving head, so the frame closest
to that median is the clearest one. Only that frame is saved.

When the print ends the frames are rendered with ffmpeg (low priority):
deflicker -> motion-compensated interpolation to 60 fps -> lanczos upscale -> sharpen -> x264.

Recording only runs when the data drive has at least MIN_FREE_GB free, so it stays off on the
nearly full SD card and turns itself on once PrintWatch runs from the SSD.
"""
import io
import json
import os
import shutil
import subprocess
import threading
import time

import numpy as np
from PIL import Image

MIN_FREE_GB = float(os.environ.get("TIMELAPSE_MIN_FREE_GB", "30"))
MAX_PER_LAYER = 40          # frames considered per layer
SAMPLE_S = 0.4              # don't look at frames faster than this
IN_FPS = 20                 # one layer = one source frame at this rate
OUT_FPS = 60                # after interpolation
OUT_W = 1920
ACTIVE = ("RUNNING", "PAUSE", "PREPARE", "SLICING")


def _thumb(jpeg):
    im = Image.open(io.BytesIO(jpeg))
    im.draft("L", (320, 180))
    return np.asarray(im.convert("L").resize((160, 90)), dtype=np.int16)


class Timelapse:
    def __init__(self, camera, printer, data_dir, events=None):
        self.camera, self.printer, self.events = camera, printer, events
        self.root = os.path.join(data_dir, "timelapse")
        os.makedirs(self.root, exist_ok=True)
        self.job_dir = None
        self.layer = None
        self.count = 0
        self.cands = []           # (thumb, jpeg) for the current layer
        self.ref = []             # last kept thumbs (helps when a layer has few frames)
        self.base = None          # median view of the first layer (empty-ish bed)
        self.rendering = None
        self.render_q = []
        self.msg = ""
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="timelapse").start()
        threading.Thread(target=self._render_loop, daemon=True, name="tl-render").start()

    # ------------------------------------------------------------ status / api
    def free_gb(self):
        try:
            return shutil.disk_usage(self.root).free / 1e9
        except OSError:
            return 0.0

    def ready(self):
        return self.free_gb() >= MIN_FREE_GB

    def list(self):
        out = []
        for name in sorted(os.listdir(self.root), reverse=True):
            d = os.path.join(self.root, name)
            if not os.path.isdir(d):
                continue
            meta = self._meta(d)
            vid = os.path.join(d, "timelapse.mp4")
            out.append({"id": name, "job": meta.get("job", ""), "frames": meta.get("frames", 0),
                        "video": os.path.exists(vid),
                        "mb": round(os.path.getsize(vid) / 1e6, 1) if os.path.exists(vid) else None,
                        "bytes": os.path.getsize(vid) if os.path.exists(vid) else None,
                        "t": meta.get("t") or int(os.path.getmtime(d)),
                        "rendering": self.rendering == name, "queued": name in self.render_q})
        return out

    def status(self):
        free = self.free_gb()
        return {"ready": free >= MIN_FREE_GB, "free_gb": round(free, 1), "need_gb": MIN_FREE_GB,
                "recording": self.job_dir is not None, "frames": self.count, "layer": self.layer,
                "rendering": self.rendering, "msg": self.msg}

    def thumb_path(self, tid):
        if "/" in tid or ".." in tid:
            return None
        fr = os.path.join(self.root, tid, "frames")
        try:
            names = sorted(n for n in os.listdir(fr) if n.endswith(".jpg"))
        except OSError:
            return None
        return os.path.join(fr, names[len(names) * 3 // 4]) if names else None

    def video_path(self, tid, web=False):
        """web=True: a light 720p copy for streaming over the web link (made in the background the
        first time it's asked for; until then the full video is served)."""
        if "/" in tid or ".." in tid:
            return None
        p = os.path.join(self.root, tid, "timelapse.mp4")
        if not os.path.exists(p):
            return None
        if web:
            w = os.path.join(self.root, tid, "timelapse_web.mp4")
            if os.path.exists(w):
                return w
            self._make_web(tid)
        return p

    def _make_web(self, tid):
        with self._lock:
            busy = getattr(self, "_web_busy", set())
            self._web_busy = busy
            if tid in busy:
                return
            busy.add(tid)

        def run():
            d = os.path.join(self.root, tid)
            tmp = os.path.join(d, "web.tmp.mp4")
            try:
                r = subprocess.run(["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error",
                                    "-i", os.path.join(d, "timelapse.mp4"), "-vf", "scale='min(1280,iw)':-2",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-maxrate", "3M",
                                    "-bufsize", "6M", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                                    "-threads", "2", tmp], capture_output=True, text=True)
                if r.returncode == 0:
                    os.replace(tmp, os.path.join(d, "timelapse_web.mp4"))
            except Exception:
                pass
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self._web_busy.discard(tid)
        threading.Thread(target=run, daemon=True, name="tl-web").start()

    def render(self, tid):
        if "/" in tid or ".." in tid or not os.path.isdir(os.path.join(self.root, tid)):
            return False
        with self._lock:
            if tid not in self.render_q and tid != self.rendering:
                self.render_q.append(tid)
        return True

    # ------------------------------------------------------------ capture
    def _meta(self, d):
        try:
            with open(os.path.join(d, "meta.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_meta(self, job):
        with open(os.path.join(self.job_dir, "meta.json"), "w") as f:
            json.dump({"job": job, "frames": self.count, "t": int(time.time())}, f)

    def _keep_best(self, job):
        if not self.cands:
            return
        thumbs = np.stack([c[0] for c in self.cands] + self.ref[-3:])
        med = np.median(thumbs, axis=0)
        # where the print is: what has changed since the first layer (grown by a few pixels)
        w = np.ones_like(med, dtype=np.float32)
        if self.base is not None:
            grown = np.abs(med - self.base) > 18
            if grown.mean() > 0.002:
                g = grown.copy()
                for dy, dx in ((0, 3), (0, -3), (3, 0), (-3, 0), (0, 6), (0, -6)):
                    g |= np.roll(grown, (dy, dx), axis=(0, 1))
                w = 0.15 + 4.0 * g            # blocking the print counts much more
        scores = [(np.abs(c[0] - med) * w).mean() for c in self.cands]
        if self.base is None:
            self.base = med
        best = self.cands[int(np.argmin(scores))]
        self.count += 1
        with open(os.path.join(self.job_dir, "frames", f"{self.count:05d}.jpg"), "wb") as f:
            f.write(best[1])
        self.ref = (self.ref + [best[0]])[-6:]
        self.cands = []
        self._save_meta(job)

    def _start(self, job):
        name = time.strftime("%Y-%m-%d_%H%M%S")
        self.job_dir = os.path.join(self.root, name)
        os.makedirs(os.path.join(self.job_dir, "frames"), exist_ok=True)
        self.count, self.cands, self.ref, self.layer, self.base = 0, [], [], None, None
        self._save_meta(job)
        self.msg = f"Recording {job}"

    def _finish(self, job, ok):
        self._keep_best(job)
        d, n = self.job_dir, self.count
        self.job_dir = None
        if n >= 10:
            self.render(os.path.basename(d))
            self.msg = f"Saved {n} layers of {job}, rendering"
        else:
            self.msg = f"{job}: only {n} layers, no video made"

    def _loop(self):
        last_id, last_t = None, 0.0
        while True:
            time.sleep(0.2)
            try:
                s = self.printer.status()
                state, job, layer = s.get("state"), s.get("job") or "Print", s.get("layer")
                if self.job_dir is None:
                    if state == "RUNNING" and layer and self.ready():
                        self._start(job)
                    elif state == "RUNNING" and not self.ready():
                        self.msg = f"Not recording: needs {MIN_FREE_GB:.0f} GB free (SSD)"
                    continue
                if state not in ACTIVE:
                    self._finish(job, state == "FINISH")
                    continue
                if state != "RUNNING" or not layer:
                    continue
                if self.layer is not None and layer != self.layer:
                    self._keep_best(job)
                self.layer = layer
                jpeg, fid, ft = self.camera.latest()
                if not jpeg or fid == last_id or time.time() - ft > 5 or time.time() - last_t < SAMPLE_S:
                    continue
                last_id, last_t = fid, time.time()
                self.cands.append((_thumb(jpeg), jpeg))
                if len(self.cands) > MAX_PER_LAYER:
                    self.cands.pop(0)
            except Exception as e:  # never let the recorder die
                self.msg = f"Recorder error: {e}"
                time.sleep(2)

    # ------------------------------------------------------------ render
    def _render_loop(self):
        while True:
            time.sleep(3)
            with self._lock:
                if not self.render_q:
                    continue
                tid = self.render_q.pop(0)
                self.rendering = tid
            try:
                self._render(tid)
            except Exception as e:
                self.msg = f"Render failed: {e}"
            finally:
                self.rendering = None

    def _render(self, tid):
        d = os.path.join(self.root, tid)
        out, tmp = os.path.join(d, "timelapse.mp4"), os.path.join(d, "render.tmp.mp4")
        vf = ",".join([
            "deflicker=size=5:mode=pm",
            f"minterpolate=fps={OUT_FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
            f"scale={OUT_W}:-2:flags=lanczos",
            "unsharp=5:5:0.5",
            "tpad=stop_mode=clone:stop_duration=3",
        ])
        cmd = ["nice", "-n", "19", "ffmpeg", "-y", "-loglevel", "error",
               "-framerate", str(IN_FPS), "-i", os.path.join(d, "frames", "%05d.jpg"),
               "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "17",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-threads", "3", tmp]
        self.msg = f"Rendering {tid} (this takes a while)"
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "ffmpeg error").strip()[-200:])
        os.replace(tmp, out)
        self._make_web(tid)          # light copy for the web link
        self.msg = f"Video ready: {tid}"
        if self.events:
            self.events.add("done", f"Timelapse ready ({tid})")
