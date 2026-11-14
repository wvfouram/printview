"""Live sound from a USB microphone (e.g. the one built into a USB webcam).

One ffmpeg reads the mic only while at least one person is listening, and fans the sound out to every
listener as raw 16 kHz mono 16-bit PCM (simple to play in a browser with Web Audio and on Android with
AudioTrack). About 32 KB/s per listener.
"""
import asyncio
import logging
import os
import re
import subprocess
import threading
import time

log = logging.getLogger("usbaudio")
RATE = 16000
CHUNK = 3200            # 0.1 s of audio


def find_card():
    want = os.environ.get("USBMIC_DEVICE", "").strip()
    if want:
        return want
    try:
        cards = open("/proc/asound/cards").read()
    except OSError:
        return None
    best = None
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(\S+)\s*-\s*(.*)$", cards, re.M):
        num, ident, drv, name = m.groups()
        if drv == "USB-Audio":
            if re.search(r"cam|C960|emeet", name + ident, re.I):
                return f"plughw:{num},0"
            best = best or f"plughw:{num},0"
    return best


class USBAudio:
    def __init__(self):
        self.listeners = set()          # (loop, asyncio.Queue)
        self._lock = threading.Lock()
        self.error = None
        self.running = False
        threading.Thread(target=self._loop, daemon=True, name="usbaudio").start()

    def status(self):
        return {"present": find_card() is not None, "listening": len(self.listeners), "error": self.error}

    def subscribe(self, loop):
        q = asyncio.Queue(maxsize=50)
        with self._lock:
            self.listeners.add((loop, q))
        return (loop, q)

    def unsubscribe(self, sub):
        with self._lock:
            self.listeners.discard(sub)

    def _send(self, data):
        with self._lock:
            subs = list(self.listeners)
        for loop, q in subs:
            def put(q=q, data=data):
                if q.full():
                    try:
                        q.get_nowait()          # slow listener: drop old sound instead of lagging
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(data)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                pass

    def _loop(self):
        while True:
            if not self.listeners:
                time.sleep(0.3)
                continue
            card = find_card()
            if not card:
                self.error = "no USB microphone found"
                time.sleep(3)
                continue
            cmd = ["ffmpeg", "-loglevel", "error", "-nostdin", "-f", "alsa", "-i", card,
                   "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"]
            p = None
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                self.running, got = True, 0
                while self.listeners:
                    data = p.stdout.read(CHUNK)
                    if not data:
                        break
                    got += len(data)
                    self.error = None
                    self._send(data)
                if p.poll() is not None and not got:
                    self.error = p.stderr.read().decode(errors="replace").strip()[-200:] or "microphone gave no sound"
                    time.sleep(3)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                time.sleep(3)
            finally:
                self.running = False
                if p and p.poll() is None:
                    p.kill()
