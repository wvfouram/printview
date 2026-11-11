"""Extra printer details that printer.py doesn't keep: firmware versions + serial numbers of every part
(the printer's "get_version" answer), firmware update flag, what the AMS is doing, and file prepare progress.

Hooks onto the printer's MQTT client without changing printer.py (that file is patched on the Pi).
"""
import json
import threading
import time

REFRESH_S = 6 * 3600
AMS_MAIN = {0: "Idle", 1: "Changing filament", 2: "Reading RFID", 3: "Assist", 4: "Calibrating",
            0x10: "Self check", 0x20: "Debug"}
NAMES = {"ota": "Printer firmware", "mc": "Motion controller", "th": "Toolhead", "ahb": "AMS hub",
         "rv1126": "Main board (Linux)", "xm": "Extension board", "esp32": "Wi-Fi module"}


class DevInfo:
    def __init__(self, printer):
        self.printer = printer
        self.modules = []
        self.got = 0.0
        self._asked = 0.0
        cl = printer.client
        orig = cl.on_message

        def on_message(client, userdata, msg):     # let printer.py do its job, then look for the version answer
            try:
                orig(client, userdata, msg)
            finally:
                try:
                    self._look(msg.payload)
                except Exception:
                    pass

        cl.on_message = on_message
        threading.Thread(target=self._loop, daemon=True, name="devinfo").start()

    def _look(self, raw):
        if b"get_version" not in raw:
            return
        info = json.loads(raw).get("info")
        if not isinstance(info, dict) or info.get("command") != "get_version":
            return
        out = []
        for m in info.get("module") or []:
            if not isinstance(m, dict):
                continue
            n = str(m.get("name") or "")
            if n.startswith("ams/"):
                label = f"AMS {int(n.split('/')[1]) + 1}" if n.split("/")[1].isdigit() else "AMS"
            elif n.startswith("n3f/") or n.startswith("n3s/"):
                label = "AMS HT" if n.startswith("n3s/") else "AMS 2 Pro"
            else:
                label = NAMES.get(n, n)
            out.append({"name": label, "id": n, "sw": m.get("sw_ver") or "", "hw": m.get("hw_ver") or "",
                        "sn": m.get("sn") or ""})
        self.modules, self.got = out, time.time()

    def _loop(self):
        while True:
            time.sleep(15)
            try:
                if not self.printer.connected:
                    continue
                need = (not self.got and time.time() - self._asked > 60) or time.time() - self.got > REFRESH_S
                if need and time.time() - self._asked > 60:
                    self._asked = time.time()
                    self.printer._publish({"info": {"sequence_id": "0", "command": "get_version"}})
            except Exception:
                pass

    def status(self):
        with self.printer._lock:
            p = dict(self.printer.print)
        # firmware update the printer knows about (only when it can reach Bambu's servers)
        up = p.get("upgrade_state") if isinstance(p.get("upgrade_state"), dict) else {}
        new = [{"name": NAMES.get(v.get("name"), v.get("name")), "cur": v.get("cur_ver"), "new": v.get("new_ver")}
               for v in (up.get("new_ver_list") or []) if isinstance(v, dict) and v.get("new_ver") and v.get("new_ver") != v.get("cur_ver")]
        # AMS: main activity + target slot
        a = p.get("ams") if isinstance(p.get("ams"), dict) else {}
        try:
            st = int(p.get("ams_status") or 0)
        except (TypeError, ValueError):
            st = 0
        main = (st >> 8) & 0xFF
        ams = AMS_MAIN.get(main, f"Busy ({main})") if a else None
        try:
            now, tar = int(a.get("tray_now", 255)), int(a.get("tray_tar", 255))
        except (TypeError, ValueError):
            now = tar = 255
        if main == 1 and tar not in (255, 254) and tar != now:
            ams += f" → AMS {tar // 4 + 1} slot {tar % 4 + 1}"
        elif main == 1 and tar == 255 and now != 255:
            ams += " (unloading)"
        try:
            prep = int(float(p.get("gcode_file_prepare_percent")))
        except (TypeError, ValueError):
            prep = None
        if (p.get("gcode_state") not in ("PREPARE", "SLICING")) or prep in (None, 0):
            prep = None if p.get("gcode_state") not in ("PREPARE", "SLICING") else prep
        return {"modules": self.modules, "checked": int(self.got) or None, "updates": new,
                "update_flag": up.get("new_version_state"), "ams_step": ams, "prepare_pct": prep}
