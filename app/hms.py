"""Bambu HMS / print_error codes -> plain-English text.

The printer only reports numbers. Bambu's own code list (the one Bambu Studio uses) is
downloaded from e.bambulab.com, cached in the data folder and refreshed once a day.
"""
import json
import os
import threading
import time
import urllib.request

URL = "https://e.bambulab.com/query.php?lang=en"
LEVELS = {1: "Fatal", 2: "Serious", 3: "Warning", 4: "Info"}


class HMS:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "hms_codes.json")
        self.hms, self.err, self.ver = {}, {}, None
        self._load()
        threading.Thread(target=self._refresh_loop, daemon=True, name="hms").start()

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.hms = {e["ecode"].upper(): e["intro"] for e in d["device_hms"]["en"]}
            self.err = {e["ecode"].upper(): e["intro"] for e in d["device_error"]["en"]}
            self.ver = d["device_hms"].get("ver")
        except (OSError, ValueError, KeyError):
            pass

    def _refresh_loop(self):
        while True:
            try:
                if not self.hms or time.time() - os.path.getmtime(self.path) > 86400:
                    req = urllib.request.Request(URL, headers={"User-Agent": "PrintWatch"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        d = json.load(r)["data"]
                    if d["device_hms"]["en"]:
                        tmp = self.path + ".tmp"
                        with open(tmp, "w") as f:
                            json.dump(d, f)
                        os.replace(tmp, self.path)
                        self._load()
            except Exception:
                pass
            time.sleep(3600 if not self.hms else 6 * 3600)

    @staticmethod
    def _wiki(code16):
        return "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/" + "_".join(
            code16[i:i + 4] for i in range(0, 16, 4))

    def decode(self, hms_list, print_error):
        out = []
        for h in hms_list or []:
            try:
                attr, code = int(h.get("attr", 0)), int(h.get("code", 0))
            except (TypeError, ValueError):
                continue
            c = f"{attr:08X}{code:08X}"
            lvl = (code >> 16) & 0xFFFF
            out.append({"code": "_".join(c[i:i + 4] for i in range(0, 16, 4)),
                        "text": self.hms.get(c) or "Unknown HMS code (not in Bambu's list yet)",
                        "level": LEVELS.get(lvl, "Notice"), "url": self._wiki(c)})
        try:
            pe = int(print_error or 0)
        except (TypeError, ValueError):
            pe = 0
        if pe:
            c = f"{pe:08X}"
            out.insert(0, {"code": c[:4] + "_" + c[4:],
                           "text": self.err.get(c) or "Unknown print error code",
                           "level": "Print error", "url": None})
        return out

    def status(self, printer):
        p = printer.raw() if hasattr(printer, "raw") else {}
        return {"items": self.decode(p.get("hms"), p.get("print_error")),
                "db": len(self.hms), "ver": self.ver}
