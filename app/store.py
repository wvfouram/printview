"""Tiny JSON-backed settings, event log and push notifier."""
import json
import logging
import os
import threading
import time
import urllib.request
from collections import deque

log = logging.getLogger("store")


class Settings:
    DEFAULTS = {"auto_pause": True, "sensitivity": "medium", "notify_finish": True, "use_custom": True}

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
            if k in ("auto_pause", "notify_finish", "use_custom"):
                self.data[k] = bool(v)
            elif k == "sensitivity" and v in ("low", "medium", "high"):
                self.data[k] = v
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

    def _send(self, title, message, priority, tags, image):
        headers = {"Title": title, "Priority": priority}
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
