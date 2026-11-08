"""Live data streams for the phone app's "Data streams" screen.

Three channels, each a short rolling buffer of text lines:
  uno  - Arduino <-> Pi serial (bed relay)
  p1s  - Pi <-> printer MQTT (commands sent, reports received)
  web  - web link / browser <-> Pi requests
Clients poll with ?since=<seq> and get only new lines.
"""
import collections
import itertools
import threading
import time

KEEP = 300                 # lines kept per channel
MAX_LEN = 400              # longer lines are cut


class Streams:
    def __init__(self):
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._ch = {name: collections.deque(maxlen=KEEP) for name in ("uno", "p1s", "web")}

    def add(self, channel: str, text: str):
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + f" ...(+{len(text) - MAX_LEN})"
        with self._lock:
            self._ch[channel].append((next(self._seq), time.time(), text))

    def since(self, seq: int, limit: int = 200) -> dict:
        out, last = {}, seq
        with self._lock:
            for name, dq in self._ch.items():
                rows = [r for r in dq if r[0] > seq][-limit:]
                out[name] = [{"n": n, "t": round(t, 2), "s": s} for n, t, s in rows]
                if rows:
                    last = max(last, rows[-1][0])
        return {"seq": last, "streams": out}


STREAMS = Streams()
