"""Print history: every print that ends gets a record and a final photo from the camera."""
import json
import os
import threading
import time

KEEP = 500


class History:
    def __init__(self, printer, camera, data_dir, timelapse=None):
        self.camera, self.timelapse = camera, timelapse
        self.dir = os.path.join(data_dir, "history")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "history.json")
        self._lock = threading.Lock()
        try:
            with open(self.path) as f:
                self.items = json.load(f)
        except (OSError, ValueError):
            self.items = []
        self.cur = None
        printer.on_change(self._on_state)

    def _save(self):
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.items[-KEEP:], f)
        os.replace(self.path + ".tmp", self.path)

    def _on_state(self, old, new, snap):
        if old is None:
            return
        if new == "RUNNING" and old != "PAUSE":
            self.cur = {"job": snap.get("job") or "Print", "start": time.time(), "layers": snap.get("total_layers")}
            return
        if new in ("FINISH", "FAILED") and self.cur:
            c, self.cur = self.cur, None
            hid = time.strftime("%Y%m%d-%H%M%S")
            jpeg, _, t = self.camera.latest()
            photo = None
            if jpeg and time.time() - t < 30:
                photo = hid + ".jpg"
                with open(os.path.join(self.dir, photo), "wb") as f:
                    f.write(jpeg)
            tl = None
            if self.timelapse:
                lst = self.timelapse.list()
                if lst and lst[0].get("job") == c["job"]:
                    tl = lst[0]["id"]
            rec = {"id": hid, "job": c["job"], "start": int(c["start"]), "end": int(time.time()),
                   "minutes": round((time.time() - c["start"]) / 60), "result": "done" if new == "FINISH" else "failed",
                   "layers": c.get("layers"), "photo": photo, "timelapse": tl}
            with self._lock:
                self.items.append(rec)
                self._save()

    def list(self, n=100):
        with self._lock:
            return list(reversed(self.items[-n:]))

    def photo_path(self, name):
        if "/" in name or ".." in name or not name.endswith(".jpg"):
            return None
        p = os.path.join(self.dir, name)
        return p if os.path.exists(p) else None

    def stats(self, since):
        it = [i for i in self.items if i["end"] >= since]
        done = [i for i in it if i["result"] == "done"]
        return {"prints": len(it), "done": len(done), "failed": len(it) - len(done),
                "hours": round(sum(i["minutes"] for i in it) / 60, 1)}
