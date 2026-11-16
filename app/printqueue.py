"""Print queue: files lined up to print one after another. Nothing starts by itself: when the printer is
free you press "Start next" (web link or app) and the top job starts. Kept in data/queue.json."""
import json
import os
import threading
import time
import uuid

IDLE = ("IDLE", "FINISH", "FAILED")


class PrintQueue:
    def __init__(self, printer, data_dir, start_fn, events=None):
        self.printer, self.start_fn, self.events = printer, start_fn, events
        self.path = os.path.join(data_dir, "queue.json")
        self._lock = threading.Lock()
        try:
            with open(self.path) as f:
                self.items = json.load(f)
        except (OSError, ValueError):
            self.items = []

    def _save(self):
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.items, f)
        os.replace(self.path + ".tmp", self.path)

    def list(self):
        with self._lock:
            return [dict(i) for i in self.items]

    def add(self, body):
        if not str(body.get("path", "")).strip():
            raise ValueError("no file chosen")
        body = {k: v for k, v in body.items() if k != "at"}
        it = {"id": uuid.uuid4().hex[:10], "name": os.path.basename(str(body["path"])), "plate": int(body.get("plate", 1)),
              "body": body, "added": int(time.time())}
        with self._lock:
            if len(self.items) >= 50:
                raise ValueError("the queue is full (50)")
            self.items.append(it)
            self._save()
        if self.events:
            self.events.add("cmd", f"Queued {it['name']}")
        return it

    def remove(self, qid):
        with self._lock:
            n = len(self.items)
            self.items = [i for i in self.items if i["id"] != qid]
            self._save()
            return len(self.items) != n

    def move(self, qid, delta):
        with self._lock:
            ids = [i["id"] for i in self.items]
            if qid not in ids:
                return False
            a = ids.index(qid)
            b = max(0, min(len(ids) - 1, a + int(delta)))
            self.items.insert(b, self.items.pop(a))
            self._save()
            return True

    def start_next(self):
        st = self.printer.status()
        if not st.get("connected"):
            raise ValueError("printer offline")
        if st.get("state") not in IDLE:
            raise ValueError("the printer is busy")
        with self._lock:
            if not self.items:
                raise ValueError("the queue is empty")
            it = self.items[0]
        if not self.start_fn(it["body"]):
            raise ValueError("the printer didn't accept the start")
        with self._lock:
            self.items = [i for i in self.items if i["id"] != it["id"]]
            self._save()
        if self.events:
            self.events.add("start", f"Started next in queue: {it['name']}")
        return it

    def status(self):
        with self._lock:
            nxt = self.items[0] if self.items else None
            return {"count": len(self.items), "next": {"id": nxt["id"], "name": nxt["name"], "plate": nxt["plate"]} if nxt else None}
