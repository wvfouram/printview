"""Tiny JSON-backed settings, event log and push notifier."""
import json
import logging
import os
import threading
import time
import urllib.request
from collections import deque

log = logging.getLogger("store")


def _hhmm(v):
    """'22:30' -> minutes after midnight, or None."""
    try:
        h, m = str(v).strip().split(":")
        h, m = int(h), int(m)
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None
    except (ValueError, TypeError):
        return None


class Settings:
    DEFAULTS = {"auto_pause": True, "sensitivity": "medium", "notify_finish": True, "use_custom": True,
                "plate_check": True, "plate_pause": False,
                "first_layer_grace": 2,          # spaghetti watch ignores this many first layers
                "plate_check_next": True,        # "Start next" looks at the plate first
                "quiet_on": False, "quiet_start": "22:00", "quiet_end": "07:00", "quiet_light": False,
                "finish_cooldown": True, "finish_light_off_min": 10,
                "tl_overlay": True, "public_stats": True,
                "currency": "$", "printer_name": "",
                "prices": {"PLA": 20, "PETG": 20, "ABS": 22, "ASA": 25, "TPU": 35, "PLA-CF": 32, "PETG-CF": 32,
                           "PA": 45, "PA-CF": 60, "PC": 35, "PVA": 50, "HIPS": 25}}
    BOOLS = ("auto_pause", "notify_finish", "use_custom", "plate_check", "plate_pause", "plate_check_next",
             "quiet_on", "quiet_light", "finish_cooldown", "tl_overlay", "public_stats")

    def __init__(self, path):
        self.path = path
        self.data = dict(self.DEFAULTS)
        try:
            with open(path) as f:
                self.data.update({k: v for k, v in json.load(f).items() if k in self.DEFAULTS})
        except (OSError, ValueError):
            pass

    def get(self, k):
        return self.data.get(k, self.DEFAULTS.get(k))

    def update(self, changes: dict):
        for k, v in changes.items():
            try:
                if k in self.BOOLS:
                    self.data[k] = bool(v)
                elif k == "sensitivity" and v in ("low", "medium", "high"):
                    self.data[k] = v
                elif k == "first_layer_grace":
                    self.data[k] = max(0, min(10, int(v)))
                elif k == "finish_light_off_min":
                    v = int(v)
                    self.data[k] = 0 if v <= 0 else max(3, min(240, v))   # never before the finish photos are taken
                elif k in ("quiet_start", "quiet_end") and _hhmm(v) is not None:
                    self.data[k] = "%02d:%02d" % divmod(_hhmm(v), 60)
                elif k == "printer_name" and isinstance(v, str):
                    self.data[k] = " ".join(v.split())[:40]
                elif k == "currency" and isinstance(v, str):
                    self.data[k] = v.strip()[:3] or "$"
                elif k == "prices" and isinstance(v, dict):
                    pr = dict(self.get("prices"))
                    for t, x in v.items():
                        t = str(t).strip().upper()[:16]
                        if not t:
                            continue
                        if x in (None, ""):
                            pr.pop(t, None)
                        else:
                            pr[t] = round(max(0.0, min(10000.0, float(x))), 2)
                    self.data[k] = pr
            except (ValueError, TypeError):
                continue
        try:
            with open(self.path, "w") as f:
                json.dump(self.data, f)
        except OSError:
            log.warning("could not save settings")
        return self.data


class Events:
    def __init__(self, path, maxlen=60):
        self.path = path
        self.items = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        try:
            with open(path) as f:
                self.items.extend(json.load(f))
        except (OSError, ValueError):
            pass

    def add(self, kind, text):
        log.info("event [%s] %s", kind, text)
        with self._lock:
            self.items.appendleft({"t": int(time.time()), "kind": kind, "text": text})
            try:
                with open(self.path, "w") as f:
                    json.dump(list(self.items), f)
            except OSError:
                pass

    def list(self, n=20):
        with self._lock:
            return list(self.items)[:n]


class Notifier:
    """Optional phone push via ntfy (https://ntfy.sh or your own ntfy server).

    Set NTFY_URL=https://ntfy.sh/<long-random-topic> and subscribe to that topic
    in the ntfy phone app. Leave unset to disable.
    """

    def __init__(self, url: str | None, token: str | None = None):
        self.url = (url or "").strip() or None
        self.token = token

    @property
    def enabled(self):
        return self.url is not None

    def send(self, title, message, priority="default", tags="", image: bytes | None = None):
        if not self.url:
            return
        threading.Thread(target=self._send, args=(title, message, priority, tags, image), daemon=True).start()

    name_fn = None      # the printer's name from Settings, put in front of every alert title

    def _send(self, title, message, priority, tags, image):
        try:
            name = (self.name_fn() or "").strip() if self.name_fn else ""
        except Exception:  # noqa: BLE001
            name = ""
        if name:
            title = f"{name}: {title}"
        title = title.encode("latin-1", "replace").decode("latin-1")
        headers = {"Title": title, "Priority": priority}
        open_url = (os.environ.get("OPEN_URL") or "").strip()
        if open_url:
            headers["Actions"] = f"view, Open PrintView, {open_url}"
            headers["Click"] = open_url
        if tags:
            headers["Tags"] = tags
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if image:
            headers["Message"] = message
            headers["Filename"] = "printer.jpg"
            body, method = image, "PUT"
        else:
            body, method = message.encode(), "POST"
        try:
            req = urllib.request.Request(self.url, data=body, headers=headers, method=method)
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy send failed: %s", e)
