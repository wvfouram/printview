import sys
def rep(f, a, b):
    s = open(f).read()
    if b in s: return print("already", f)
    if s.count(a) != 1: print("MISS", f, a[:50]); sys.exit(1)
    open(f, "w").write(s.replace(a, b)); print("ok", f)
rep("app/printer.py", '''    def ams_user_setting(self''', '''    def ams_dry(self, unit: int, on: bool, filament: str = "PLA", temp: int = 55, hours: float = 4,
                rotate: bool = True) -> bool:
        """Start/stop the dryer of an AMS HT / AMS 2 Pro. unit = the AMS number shown in the app (1, 129...)."""
        if self.busy and on:
            raise PermissionError("the printer only allows drying while it is idle")
        temp = max(30, min(70, int(temp)))
        hours = max(1, min(24, int(round(float(hours)))))
        return self._publish({"print": {
            "sequence_id": self._next_seq(), "command": "ams_filament_drying", "ams_id": int(unit) - 1,
            "mode": 1 if on else 0, "filament": str(filament).upper()[:16] if on else "",
            "temp": temp, "cooling_temp": 45, "duration": hours, "humidity": 0,
            "rotate_tray": bool(rotate), "close_power_conflict": False}})

    def ams_user_setting(self''')
rep("app/main.py", '''    "ams_rfid": lambda p, b: p.ams_read_rfid(b.get("slot")),''', '''    "ams_rfid": lambda p, b: p.ams_read_rfid(b.get("slot")),
    "ams_dry": lambda p, b: p.ams_dry(b.get("unit", 129), bool(b.get("on", True)), str(b.get("filament", "PLA")),
                                      b.get("temp", 55), b.get("hours", 4), bool(b.get("rotate", True))),''')
rep("app/main.py", '''"calibrate": "Calibration", "ams_setting": "AMS slot setting"}''', '''"calibrate": "Calibration", "ams_setting": "AMS slot setting", "ams_dry": "AMS drying"}''')
