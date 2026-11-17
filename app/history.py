"""Print history: every print that ends gets a record and a final photo from the camera.

Each record also gets, when the print's file can be found on the SD card:
  filament used (grams and meters, per filament, cut down to how far a failed print got), its cost,
  which AMS slot it came from (taken off that spool), the slicer's time estimate next to the real time
  (pauses left out), and why it failed. You can add a note and a 1-5 star rating afterwards.
"""
import json
import logging
import os
import threading
import time

from .spools import EXTERNAL, mapping_to_slot

log = logging.getLogger("history")
KEEP = 2000


class History:
    def __init__(self, printer, camera, data_dir, timelapse=None, resolver=None, spools=None, cause_fn=None):
        self.printer, self.camera, self.timelapse = printer, camera, timelapse
        self.resolver, self.spools, self.cause_fn = resolver, spools, cause_fn
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
        threading.Thread(target=self._watch, daemon=True, name="history").start()

    def _save(self):
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.items[-KEEP:], f)
        os.replace(self.path + ".tmp", self.path)

    # ---------------------------------------------------------------- while printing
    def _watch(self):
        """Keep the last percent / layer seen and the printer's first time estimate."""
        while True:
            time.sleep(5)
            c = self.cur
            if not c:
                continue
            st = self.printer.status()
            if st.get("state") == "RUNNING":
                if st.get("percent") is not None:
                    c["pct"] = st["percent"]
                if st.get("layer"):
                    c["layer"] = st["layer"]
                if c.get("printer_est_min") is None and (st.get("layer") or 0) >= 1 and st.get("remaining_min"):
                    # first estimate once it's really printing (after heating and calibration)
                    c["printer_est_min"] = st["remaining_min"] + round((time.time() - c["start"]) / 60)

    def _resolve(self, c):
        if not self.resolver:
            return
        for wait in (20, 60, 180):
            time.sleep(wait)
            if self.cur is not c:
                return
            try:
                info = self.resolver(c["job"])
            except Exception as e:  # noqa: BLE001
                log.info("couldn't find the print's file yet: %s", e)
                continue
            if info:
                c["file"] = info
                return

    def _on_state(self, old, new, snap):
        if old is None:
            return
        c = self.cur
        if new == "RUNNING" and old != "PAUSE":
            self.cur = {"job": snap.get("job") or "Print", "start": time.time(), "layers": snap.get("total_layers"),
                        "pause_s": 0.0, "paused_at": None, "pct": 0, "layer": 0}
            threading.Thread(target=self._resolve, args=(self.cur,), daemon=True).start()
            return
        if c and new == "PAUSE" and not c.get("paused_at"):
            c["paused_at"] = time.time()
            return
        if c and new == "RUNNING" and old == "PAUSE" and c.get("paused_at"):
            c["pause_s"] += time.time() - c["paused_at"]
            c["paused_at"] = None
            return
        if new in ("FINISH", "FAILED") and c:
            self.cur = None
            if c.get("paused_at"):
                c["pause_s"] += time.time() - c["paused_at"]
            threading.Thread(target=self._finish, args=(c, new, snap), daemon=True).start()

    def _finish(self, c, new, snap):
        hid = time.strftime("%Y%m%d-%H%M%S")
        jpeg, _, t = self.camera.latest()
        photo = None
        if jpeg and time.time() - t < 30:
            photo = hid + ".jpg"
            with open(os.path.join(self.dir, photo), "wb") as f:
                f.write(jpeg)
        done = new == "FINISH"
        cause = None
        if not done and self.cause_fn:
            try:
                cause = self.cause_fn()
            except Exception:  # noqa: BLE001
                cause = None
        frac = 1.0 if done else max(0.0, min(1.0, (c.get("pct") or 0) / 100))
        total_min = (time.time() - c["start"]) / 60
        rec = {"id": hid, "job": c["job"], "start": int(c["start"]), "end": int(time.time()),
               "minutes": round(total_min), "print_minutes": round(total_min - c["pause_s"] / 60),
               "paused_minutes": round(c["pause_s"] / 60), "result": "done" if done else "failed",
               "cause": cause, "percent": 100 if done else c.get("pct"),
               "layers": c.get("layers"), "photo": photo, "timelapse": None,
               "note": "", "stars": None}
        f = c.get("file")
        fil = []
        if f:
            rec["file"], rec["plate"] = f.get("path"), f.get("plate")
            if f.get("seconds"):
                rec["est_minutes"] = round(f["seconds"] / 60)
            mapping, use_ams = f.get("mapping"), f.get("use_ams", True)
            for x in f.get("filaments") or []:
                slot = None
                if not use_ams:
                    slot = EXTERNAL
                elif mapping and 0 < x.get("id", 0) <= len(mapping):
                    slot = mapping_to_slot(mapping[x["id"] - 1])
                elif x.get("slot") is not None:
                    slot = x["slot"]
                g = round((x.get("used_g") or 0) * frac, 1)
                m = round((x.get("used_m") or 0) * frac, 2)
                fil.append({"type": x.get("type"), "color": x.get("color"), "g": g, "m": m, "slot": slot})
        if rec.get("est_minutes") is None and c.get("printer_est_min"):
            rec["est_minutes"] = c["printer_est_min"]
            rec["est_source"] = "printer"
        if fil:
            rec["filaments"] = fil
            rec["grams"] = round(sum(x["g"] for x in fil), 1)
            rec["meters"] = round(sum(x["m"] for x in fil), 2)
            if self.spools:
                rec["cost"] = self.spools.cost(fil)
                for x in fil:
                    self.spools.consume(x["slot"], x["g"])
        if self.timelapse:
            time.sleep(5)                                   # the timelapse closes its job on the same event
            try:
                lst = self.timelapse.list()
                if lst and lst[0].get("job") == c["job"]:
                    rec["timelapse"] = lst[0]["id"]
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self.items.append(rec)
            self._save()

    # ---------------------------------------------------------------- api
    def list(self, n=100):
        with self._lock:
            return list(reversed(self.items[-n:]))

    def note(self, hid, note=None, stars=None):
        with self._lock:
            for it in self.items:
                if it["id"] == hid:
                    if note is not None:
                        it["note"] = str(note).strip()[:1000]
                    if stars is not None:
                        s = int(stars)
                        it["stars"] = s if 1 <= s <= 5 else None
                    self._save()
                    return it
        raise ValueError("no such print")

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

    def full_stats(self, since=0, currency="$"):
        """Everything for the stats page."""
        with self._lock:
            it = [i for i in self.items if i["end"] >= since]
        done = [i for i in it if i["result"] == "done"]
        failed = [i for i in it if i["result"] != "done"]
        hrs = sum(i.get("print_minutes", i["minutes"]) for i in it) / 60
        grams = sum(i.get("grams") or 0 for i in it)
        cost = [i["cost"] for i in it if i.get("cost") is not None]
        months = {}
        for i in it:
            k = time.strftime("%Y-%m", time.localtime(i["end"]))
            m = months.setdefault(k, {"month": k, "prints": 0, "done": 0, "hours": 0.0, "grams": 0.0, "cost": 0.0})
            m["prints"] += 1
            m["done"] += i["result"] == "done"
            m["hours"] += i.get("print_minutes", i["minutes"]) / 60
            m["grams"] += i.get("grams") or 0
            m["cost"] += i.get("cost") or 0
        for m in months.values():
            m["hours"], m["grams"], m["cost"] = round(m["hours"], 1), round(m["grams"]), round(m["cost"], 2)
        files = {}
        for i in it:
            f = files.setdefault(i["job"], {"job": i["job"], "prints": 0, "done": 0, "grams": 0.0})
            f["prints"] += 1
            f["done"] += i["result"] == "done"
            f["grams"] += i.get("grams") or 0
        top = sorted(files.values(), key=lambda f: (-f["prints"], f["job"]))[:10]
        for f in top:
            f["grams"] = round(f["grams"])
        causes = {}
        for i in failed:
            k = i.get("cause") or "Stopped (no reason recorded)"
            causes[k] = causes.get(k, 0) + 1
        est = [i for i in done if i.get("est_minutes") and i.get("print_minutes")]
        acc = None
        if est:
            ratios = [i["print_minutes"] / i["est_minutes"] for i in est]
            acc = {"prints": len(est), "avg_pct": round(sum(ratios) / len(ratios) * 100),
                   "avg_off_min": round(sum(i["print_minutes"] - i["est_minutes"] for i in est) / len(est)),
                   "recent": [{"job": i["job"], "end": i["end"], "est": i["est_minutes"], "real": i["print_minutes"]}
                              for i in reversed(est[-15:])]}
        by_type = {}
        for i in it:
            for f in i.get("filaments") or []:
                t = (f.get("type") or "?").upper()
                by_type[t] = round(by_type.get(t, 0) + f["g"], 1)
        return {"prints": len(it), "done": len(done), "failed": len(failed),
                "success_pct": round(len(done) * 100 / len(it)) if it else None,
                "hours": round(hrs, 1), "grams": round(grams), "meters": round(sum(i.get("meters") or 0 for i in it), 1),
                "cost": round(sum(cost), 2) if cost else None, "currency": currency,
                "months": sorted(months.values(), key=lambda m: m["month"], reverse=True)[:12],
                "top_files": top, "fail_causes": sorted(({"cause": k, "count": v} for k, v in causes.items()),
                                                        key=lambda x: -x["count"]),
                "estimate": acc, "by_type": by_type,
                "rated": [{"job": i["job"], "stars": i["stars"]} for i in it if i.get("stars")][-50:]}
