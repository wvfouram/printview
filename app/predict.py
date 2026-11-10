"""Smart finish time: learns how far off the slicer's estimate is on this printer.

Each finished print stores (slicer estimate, real time). The slow/fast ratio of past prints corrects
the printer's countdown at the start of a print; as the print goes on, the ratio measured on this
very print takes over. Paused time is not counted.
"""
import json
import os
import statistics
import threading
import time

KEEP = 40


class Predictor:
    def __init__(self, printer, data_dir):
        self.printer = printer
        self.path = os.path.join(data_dir, "predict.json")
        self.hist = []
        try:
            with open(self.path) as f:
                self.hist = json.load(f)
        except (OSError, ValueError):
            pass
        self.cur = None
        self.out = None
        threading.Thread(target=self._loop, daemon=True, name="predict").start()

    def _save(self):
        try:
            with open(self.path + ".tmp", "w") as f:
                json.dump(self.hist[-KEEP:], f)
            os.replace(self.path + ".tmp", self.path)
        except OSError:
            pass

    def _ratios(self):
        return [h["actual"] / h["slicer"] for h in self.hist if h.get("slicer", 0) > 5 and 0.4 < h["actual"] / h["slicer"] < 3]

    def _loop(self):
        while True:
            time.sleep(2)
            try:
                self._tick()
            except Exception:
                pass

    def _tick(self):
        s = self.printer.status()
        st, pct, rem = s.get("state"), s.get("percent"), s.get("remaining_min")
        now = time.time()
        c = self.cur
        if st in ("RUNNING", "PAUSE") and c is None and pct is not None and rem is not None and rem > 0:
            # first good reading of a new print: the slicer's total = time so far + its countdown
            self.cur = c = {"job": s.get("job") or "", "t0": now, "paused": 0.0, "pause_at": None,
                            "slicer": float(rem) + 0.0, "pct0": pct}
        if c is None:
            self.out = None
            return
        if st == "PAUSE" and c["pause_at"] is None:
            c["pause_at"] = now
        if st != "PAUSE" and c["pause_at"] is not None:
            c["paused"] += now - c["pause_at"]
            c["pause_at"] = None
        if st == "FINISH":
            actual = (now - c["t0"] - c["paused"]) / 60
            if c["pct0"] <= 3 and actual > 3:      # only learn from prints we watched from the start
                self.hist.append({"job": c["job"], "slicer": round(c["slicer"], 1), "actual": round(actual, 1), "t": int(now)})
                self._save()
            self.cur, self.out = None, None
            return
        if st not in ("RUNNING", "PAUSE", "PREPARE", "SLICING"):
            self.cur, self.out = None, None
            return
        if rem is None or pct is None:
            return
        ratios = self._ratios()
        r_hist = statistics.median(ratios) if ratios else 1.0
        spread = statistics.pstdev(ratios) if len(ratios) >= 3 else 0.12
        elapsed = (now - c["t0"] - c["paused"] - ((now - c["pause_at"]) if c["pause_at"] else 0)) / 60
        done_slicer = c["slicer"] - rem                      # slicer-minutes already printed
        r_live = elapsed / done_slicer if done_slicer > 3 else r_hist
        r_live = min(3.0, max(0.4, r_live))
        w = min(1.0, max(0.0, (pct - c["pct0"]) / 40))
        factor = (1 - w) * r_hist + w * r_live
        remaining = max(0.0, rem * factor)
        pm = max(1.0, remaining * (spread * (1 - 0.6 * w)))
        self.out = {"remaining_min": round(remaining, 1), "done_at": int(now + remaining * 60),
                    "pm_min": round(pm), "factor": round(factor, 3), "learned_from": len(ratios)}

    def status(self):
        return self.out or {"learned_from": len(self._ratios())}
