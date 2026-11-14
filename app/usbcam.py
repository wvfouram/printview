"""Second camera: any USB webcam plugged into the Pi (live view only, no timelapse, no AI).

Runs ffmpeg only while someone is watching (stops 30 s after the last request), so it costs nothing
when nobody looks. Frames are scaled to OUT_W wide JPEGs at OUT_FPS so they stay light over the web link.
"""
import glob
import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("usbcam")
OUT_W = int(os.environ.get("USBCAM_WIDTH", "1280"))
OUT_FPS = float(os.environ.get("USBCAM_FPS", "4"))
IDLE_S = 30


def find_device():
    """The USB camera's capture node (Pi 5 has many internal /dev/video* nodes, so go by USB id)."""
    want = os.environ.get("USBCAM_DEVICE", "").strip()
    if want:
        return want if os.path.exists(want) else None
    for p in sorted(glob.glob("/dev/v4l/by-id/usb-*-video-index0")):
        return p
    for n in sorted(glob.glob("/sys/class/video4linux/video*")):     # fallback: first USB-backed node
        try:
            if "/usb" in os.path.realpath(os.path.join(n, "device")) and open(os.path.join(n, "index")).read().strip() == "0":
                return "/dev/" + os.path.basename(n)
        except OSError:
            pass
    return None


class USBCam:
    def __init__(self):
        self.frame, self.frame_id, self.frame_time = b"", 0, 0.0
        self.last_want = 0.0
        self.error = None
        self.device = None
        self._lock = threading.Lock()
        self._proc = None
        threading.Thread(target=self._loop, daemon=True, name="usbcam").start()

    def want(self):
        """Called on every request; starts the camera if it's off."""
        self.last_want = time.time()

    def latest(self):
        self.want()
        with self._lock:
            return self.frame, self.frame_id, self.frame_time

    def status(self):
        return {"present": find_device() is not None, "running": self._proc is not None,
                "device": self.device, "error": self.error,
                "frame_age_s": round(time.time() - self.frame_time, 1) if self.frame_time else None}

    def _cmd(self, dev, native):
        vf = f"fps={OUT_FPS},scale='min({OUT_W},iw)':-2"
        inp = ["-f", "v4l2"]
        if native:      # most 4K webcams only do high resolution at full frame rate as MJPEG
            inp += ["-input_format", "mjpeg", "-video_size", "1920x1080", "-framerate", "30"]
        return ["nice", "-n", "5", "ffmpeg", "-loglevel", "error", "-nostdin", *inp, "-i", dev,
                "-vf", vf, "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]

    def _loop(self):
        native = True
        while True:
            if time.time() - self.last_want > IDLE_S:
                time.sleep(0.5)
                continue
            dev = find_device()
            self.device = dev
            if not dev:
                self.error = "no USB camera found"
                time.sleep(3)
                continue
            try:
                self._proc = subprocess.Popen(self._cmd(dev, native), stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, bufsize=0)
                got = self._read(self._proc)
                err = self._proc.stderr.read().decode(errors="replace").strip()[-200:]
                if not got:
                    self.error = err or "camera gave no picture"
                    native = not native              # try the other mode next time
                    time.sleep(2)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                time.sleep(3)
            finally:
                p, self._proc = self._proc, None
                if p and p.poll() is None:
                    p.kill()

    def _read(self, p):
        buf, got = b"", 0
        while True:
            if time.time() - self.last_want > IDLE_S:
                return got or 1                      # nobody watching: stop
            chunk = p.stdout.read(65536)
            if not chunk:
                return got
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2)
                if s < 0 or e < 0:
                    if s > 0:
                        buf = buf[s:]
                    break
                jpg, buf = buf[s:e + 2], buf[e + 2:]
                with self._lock:
                    self.frame, self.frame_id, self.frame_time = jpg, self.frame_id + 1, time.time()
                got += 1
                self.error = None
            if len(buf) > 8_000_000:
                buf = b""
