"""Small automatic jobs:
- Quiet hours: during the hours set in Settings, a running print is switched to Silent speed (and the
  chamber light off, if that option is on). When quiet hours end, the speed and light go back.
  Changing the speed yourself during quiet hours is respected: it's only switched once per print.
- After a print: heaters off right away (if the end G-code didn't already), and the chamber light off
  after the minutes set in Settings (never sooner than 3 minutes, so the finish photos are taken in light).
"""
import logging
import threading
import time

log = logging.getLogger("automation")
ACTIVE = ("RUNNING", "PAUSE", "PREPARE", "SLICING")


def _mins(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def in_window(now_min, start, end):
    s, e = _mins(start), _mins(end)
    if s == e:
        return False
    return s <= now_min < e if s < e else (now_min >= s or now_min < e)


class Automation:
    def __init__(self, printer, settings, events):
        self.printer, self.settings, self.events = printer, settings, events
        self.quiet_job = None          # the print quiet hours already switched
        self.restore = None            # {"speed": level, "light": bool} to put back afterwards
        self.light_off_at = None
        printer.on_change(self._on_state)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="automation").start()

    def _on_state(self, old, new, snap):
        if old is None:
            return
        if new in ("FINISH", "FAILED"):
            self.quiet_job, self.restore = None, None
            if self.settings.get("finish_cooldown"):
                threading.Thread(target=self._cooldown, daemon=True).start()
            n = int(self.settings.get("finish_light_off_min") or 0)
            self.light_off_at = time.time() + max(3, n) * 60 if n > 0 else None
        elif new in ACTIVE:
            self.light_off_at = None

    def _cooldown(self):
        time.sleep(20)
        st = self.printer.status()
        if st.get("state") in ACTIVE:
            return
        try:
            if (st.get("nozzle_target") or 0) > 0:
                self.printer.set_temp("nozzle", 0)
            if (st.get("bed_target") or 0) > 0:
                self.printer.set_temp("bed", 0)
        except Exception:  # noqa: BLE001
            pass

    def status(self):
        st = self.settings
        now = time.localtime()
        q = bool(st.get("quiet_on")) and in_window(now.tm_hour * 60 + now.tm_min, st.get("quiet_start"), st.get("quiet_end"))
        return {"quiet_now": q, "quiet_applied": self.quiet_job is not None and self.restore is not None,
                "light_off_at": int(self.light_off_at) if self.light_off_at else None}

    def _loop(self):
        while True:
            time.sleep(20)
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("automation tick")

    def _tick(self):
        st = self.printer.status()
        if not st.get("connected"):
            return
        state = st.get("state")
        if self.light_off_at and time.time() >= self.light_off_at:
            self.light_off_at = None
            if state not in ACTIVE and st.get("light"):
                self.printer.light(False)
                self.events.add("cmd", "Chamber light turned off after the print")
        s = self.settings
        now = time.localtime()
        quiet = bool(s.get("quiet_on")) and in_window(now.tm_hour * 60 + now.tm_min, s.get("quiet_start"), s.get("quiet_end"))
        job = (st.get("job") or "") + "|" + str(st.get("total_layers"))
        printing = state == "RUNNING" and (st.get("layer") or 0) >= 1     # after heating/calibration, which resets speed
        if quiet and printing and self.quiet_job != job:
            self.quiet_job = job
            self.restore = {"speed": st.get("speed_level") or 2, "light": bool(st.get("light"))}
            if (st.get("speed_level") or 2) != 1:
                self.printer.set_speed(1)
            if s.get("quiet_light") and st.get("light"):
                self.printer.light(False)
            self.events.add("cmd", "Quiet hours: switched to Silent" + (" and light off" if s.get("quiet_light") else ""))
        elif not quiet and self.restore and state in ("RUNNING", "PAUSE"):
            r, self.restore = self.restore, None
            if r["speed"] != 1 and st.get("speed_level") == 1:
                self.printer.set_speed(r["speed"])
            if r["light"] and st.get("light") is False:
                self.printer.light(True)
            self.events.add("cmd", "Quiet hours over: speed and light put back")
        elif not quiet and state not in ACTIVE:
            self.quiet_job, self.restore = None, None
