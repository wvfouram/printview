"""Scheduled prints: start a print from the SD card at a set time.

Jobs are kept in data/schedule.json. At the start time the printer must be idle (or finished);
if it is busy the job waits up to WAIT_MIN minutes for it to free up, then gives up.
"""
import json
import os
import threading
import time
import uuid

WAIT_MIN = 60
IDLE = ("IDLE", "FINISH", "FAILED")


class Scheduler:
    def __init__(self, printer, data_dir, start_fn, events=None, notify=None):
        self.printer, self.start_fn, self.events, self.notify = printer, start_fn, events, notify
        self.path = os.path.join(data_dir, "schedule.json")
        self._lock = threading.Lock()
        try:
            with open(self.path) as f:
                self.jobs = json.load(f)
        except (OSError, ValueError):
            self.jobs = []
        threading.Thread(target=self._loop, daemon=True, name="schedule").start()

    def _save(self):
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.jobs[-50:], f)
        os.replace(self.path + ".tmp", self.path)

    def list(self):
        with self._lock:
            return sorted(self.jobs, key=lambda j: j["at"], reverse=True)[:30]

    def add(self, body, at):
        at = float(at)
        if at < time.time() - 60:
            raise ValueError("that time has already passed")
        if at > time.time() + 14 * 86400:
            raise ValueError("schedule at most 14 days ahead")
        if not str(body.get("path", "")).strip():
            raise ValueError("no file chosen")
        job = {"id": uuid.uuid4().hex[:10], "at": at, "body": body, "status": "waiting",
               "name": os.path.basename(str(body.get("path"))), "msg": ""}
        with self._lock:
            self.jobs.append(job)
            self._save()
        if self.events:
            self.events.add("cmd", f"Scheduled {job['name']} for {time.strftime('%a %H:%M', time.localtime(at))}")
        return job

    def cancel(self, jid):
        with self._lock:
            for j in self.jobs:
                if j["id"] == jid and j["status"] == "waiting":
                    j["status"], j["msg"] = "cancelled", ""
                    self._save()
                    return True
        return False

    def next_up(self):
        w = [j for j in self.jobs if j["status"] == "waiting"]
        return min(w, key=lambda j: j["at"]) if w else None

    def _loop(self):
        while True:
            time.sleep(10)
            try:
                self._tick()
            except Exception:
                pass

    def _tick(self):
        now = time.time()
        with self._lock:
            due = [j for j in self.jobs if j["status"] == "waiting" and j["at"] <= now]
        for j in due:
            st = self.printer.status()
            if not st.get("connected"):
                msg = "printer offline"
            elif st.get("state") in IDLE:
                try:
                    ok = self.start_fn(j["body"])
                    msg = "" if ok else "printer didn't accept the start"
                except Exception as e:  # noqa: BLE001
                    ok, msg = False, str(e)
                with self._lock:
                    j["status"] = "started" if ok else "failed"
                    j["msg"] = msg
                    j["done"] = now
                    self._save()
                if self.events:
                    self.events.add("start" if ok else "fail",
                                    f"Scheduled print {'started' if ok else 'failed'}: {j['name']}" + (f" ({msg})" if msg else ""))
                if self.notify:
                    self.notify("Scheduled print started" if ok else "Scheduled print failed", j["name"] + (f": {msg}" if msg else ""))
                continue
            else:
                msg = "printer busy, waiting"
            if now - j["at"] > WAIT_MIN * 60:
                with self._lock:
                    j["status"], j["msg"], j["done"] = "failed", f"{msg} for {WAIT_MIN} min, gave up", now
                    self._save()
                if self.notify:
                    self.notify("Scheduled print skipped", f"{j['name']}: {j['msg']}")
            else:
                j["msg"] = msg
