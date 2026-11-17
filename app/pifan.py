"""Pi fan page: PrintView only writes what you want; the helper on the Pi (pvadmin/pvfan.py, a small
system service, since a Docker container can't control the Pi's fan) does the rest."""
import json
import os
import time

MODES = ("auto", "quiet", "cool", "max", "manual")


class PiFan:
    def __init__(self, data_dir):
        self.want_p = os.path.join(data_dir, "pifan.json")
        self.status_p = os.path.join(data_dir, "pifan_status.json")

    def want(self):
        try:
            with open(self.want_p) as f:
                w = json.load(f)
        except (OSError, ValueError):
            w = {}
        return {"mode": w.get("mode") if w.get("mode") in MODES else "auto", "pct": int(w.get("pct", 50))}

    def set(self, mode, pct=None):
        if mode not in MODES:
            raise ValueError("unknown fan mode")
        w = self.want()
        w["mode"] = mode
        if pct is not None:
            w["pct"] = max(0, min(100, int(pct)))
        with open(self.want_p + ".tmp", "w") as f:
            json.dump(w, f)
        os.replace(self.want_p + ".tmp", self.want_p)
        return self.status()

    def status(self):
        try:
            with open(self.status_p) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        helper = bool(st) and time.time() - st.get("t", 0) < 30
        out = self.want()
        out.update(helper=helper, found=st.get("found") if helper else None, temp=st.get("temp") if helper else None,
                   rpm=st.get("rpm") if helper else None, now_pct=st.get("pct") if helper else None,
                   safety=bool(st.get("safety")) if helper else False)
        return out
