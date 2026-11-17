#!/usr/bin/env python3
"""PrintView Pi fan helper: runs on the Pi itself (as root, systemd service "pvfan"), not in Docker.

Controls the fan on the Raspberry Pi 5 FAN header. PrintView writes the wanted mode to
<data>/pifan.json; this reads it every 5 seconds, sets the fan and writes <data>/pifan_status.json.

Modes:
  auto    the Pi's own fan curve (the normal behaviour)
  quiet   off below 60 C, then rising to full at 78 C
  cool    at least 40 %, rising to full at 65 C
  max     always full speed
  manual  a fixed percent you pick
Safety: at 75 C or more the fan always runs full, whatever the mode. If this helper stops, the Pi's
own fan curve takes over again.
"""
import glob
import json
import os
import signal
import sys
import time

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/printwatch/data")
WANT = os.path.join(DATA, "pifan.json")
STATUS = os.path.join(DATA, "pifan_status.json")
ZONE = "/sys/class/thermal/thermal_zone0"
SAFE_C = 75.0


def read(p, default=None):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return default


def write(p, v):
    try:
        with open(p, "w") as f:
            f.write(str(v))
        return True
    except OSError:
        return False


def fan_hwmon():
    for d in glob.glob("/sys/devices/platform/cooling_fan/hwmon/hwmon*"):
        if os.path.exists(os.path.join(d, "pwm1")):
            return d
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(os.path.join(d, "name")) in ("pwmfan", "pwm_fan", "cooling_fan") and os.path.exists(os.path.join(d, "pwm1")):
            return d
    return None


def temp_c():
    v = read(os.path.join(ZONE, "temp"))
    return int(v) / 1000 if v and v.lstrip("-").isdigit() else None


def set_policy(name):
    if read(os.path.join(ZONE, "policy")) != name:
        write(os.path.join(ZONE, "policy"), name)


def curve(mode, t, pct):
    if mode == "max":
        return 100
    if mode == "manual":
        return max(0, min(100, int(pct)))
    if mode == "quiet":
        return 0 if t < 60 else min(100, round(30 + (t - 60) / 18 * 70))
    if mode == "cool":
        return max(40, min(100, round(40 + (t - 45) / 20 * 60)))
    return None


def manual(hw, on):
    """pwm1_enable: 1 = we set the speed, 2 = the Pi's automatic curve. Older kernels without it:
    switch the thermal zone's governor instead."""
    en = os.path.join(hw, "pwm1_enable") if hw else None
    if en and os.path.exists(en):
        want = "1" if on else "2"
        if read(en) != want:
            write(en, want)
    else:
        set_policy("user_space" if on else "step_wise")


def restore(*_):
    manual(fan_hwmon(), False)
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, restore)
    signal.signal(signal.SIGINT, restore)
    os.makedirs(DATA, exist_ok=True)
    while True:
        hw = fan_hwmon()
        t = temp_c()
        try:
            want = json.loads(read(WANT, "{}") or "{}")
        except ValueError:
            want = {}
        mode = want.get("mode") if isinstance(want, dict) and want.get("mode") in ("auto", "quiet", "cool", "max", "manual") else "auto"
        try:
            pct = max(0, min(100, int(want.get("pct", 50))))
        except (TypeError, ValueError, AttributeError):
            pct = 50
        target = None
        if hw and t is not None:
            target = curve(mode, t, pct)
            if target is not None and t >= SAFE_C:
                target = 100
            if target is None:
                manual(hw, False)                # the Pi's own curve
            else:
                manual(hw, True)
                write(os.path.join(hw, "pwm1"), round(target * 255 / 100))
        pwm = read(os.path.join(hw, "pwm1")) if hw else None
        rpm = read(os.path.join(hw, "fan1_input")) if hw else None
        st = {"t": int(time.time()), "mode": mode, "temp": t, "found": bool(hw),
              "pct": round(int(pwm) * 100 / 255) if pwm and pwm.isdigit() else None,
              "rpm": int(rpm) if rpm and rpm.isdigit() else None, "safety": t is not None and t >= SAFE_C and mode != "auto"}
        try:
            with open(STATUS + ".tmp", "w") as f:
                json.dump(st, f)
            os.replace(STATUS + ".tmp", STATUS)
            os.chmod(STATUS, 0o644)
        except OSError:
            pass
        time.sleep(5)


if __name__ == "__main__":
    main()
