"""Bambu printer control + status over local MQTT (LAN mode / Developer Mode).

Broker: printer IP, port 8883, TLS (self-signed), user "bblp", password = access code.
Reports arrive on  device/<serial>/report
Commands go to     device/<serial>/request
"""
import json
import logging
import os
import random
import re
import ssl
import threading
import time

import paho.mqtt.client as mqtt

from .streams import STREAMS

log = logging.getLogger("printer")

PUSHALL_EVERY_S = 600  # P1 series sends deltas; a full refresh now and then keeps state honest


def _merge(dst: dict, src: dict):
    """Deep-merge a status delta. P1 printers send partial updates (e.g. only one AMS tray)."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        elif k == "ams" and isinstance(v, list) and isinstance(dst.get(k), list):
            # list of AMS units: merge by id
            by_id = {u.get("id"): u for u in dst[k] if isinstance(u, dict)}
            for u in v:
                if isinstance(u, dict) and u.get("id") in by_id:
                    _merge_unit(by_id[u["id"]], u)
                else:
                    dst[k].append(u)
        else:
            dst[k] = v


def _merge_unit(dst: dict, src: dict):
    for k, v in src.items():
        if k == "tray" and isinstance(v, list) and isinstance(dst.get("tray"), list):
            trays = {t.get("id"): t for t in dst["tray"] if isinstance(t, dict)}
            for t in v:
                if isinstance(t, dict) and t.get("id") in trays:
                    trays[t["id"]].update(t)
                else:
                    dst["tray"].append(t)
        else:
            dst[k] = v


STAGES = {
    0: "Printing", 1: "Auto bed leveling", 2: "Heatbed preheating", 3: "Sweeping XY mech mode",
    4: "Changing filament", 5: "M400 pause", 6: "Paused: filament runout", 7: "Heating hotend",
    8: "Calibrating extrusion", 9: "Scanning bed surface", 10: "Inspecting first layer",
    11: "Identifying build plate", 12: "Calibrating micro lidar", 13: "Homing toolhead",
    14: "Cleaning nozzle tip", 15: "Checking extruder temperature", 16: "Paused by user",
    17: "Paused: front cover fell", 18: "Calibrating micro lidar", 19: "Calibrating extrusion flow",
    20: "Paused: nozzle temperature malfunction", 21: "Paused: heat bed temperature malfunction",
    22: "Unloading filament", 23: "Paused: skipped step", 24: "Loading filament",
    25: "Calibrating motor noise", 26: "Paused: AMS lost", 27: "Paused: low fan speed (heatbreak)",
    28: "Paused: chamber temperature control error", 29: "Cooling chamber", 30: "Paused by G-code",
    31: "Motor noise showoff", 32: "Paused: nozzle filament covered", 33: "Paused: cutter error",
    34: "Paused: first layer error", 35: "Paused: nozzle clog", 255: "Idle", -1: "Idle",
}

SPEEDS = {1: "Silent", 2: "Standard", 3: "Sport", 4: "Ludicrous"}
FANS = {"part": 1, "aux": 2, "chamber": 3}          # M106 P<n>
LIMITS = {"nozzle": 300, "bed": None}               # nozzle: P1S maximum. bed: no cap here (owner's choice)
MOTION = ("G0", "G1", "G2", "G3", "G28", "G29", "G90", "G91", "G92", "M84", "M18")
ACTIVE = ("RUNNING", "PAUSE", "PREPARE", "SLICING")
PA_REPLIES = ("extrusion_cali_get", "extrusion_cali_set", "extrusion_cali_sel", "extrusion_cali_del")


def _fan_pct(v):
    """Bambu reports fan speed as 0-15 (string); show it as a percent."""
    try:
        return round(int(v) / 15 * 100)
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _options(p):
    """Printer toggles. home_flag bit positions follow Bambu Studio's parser (best effort)."""
    hf = _int(p.get("home_flag"))
    a = p.get("ams") if isinstance(p.get("ams"), dict) else {}
    ip = p.get("ipcam") if isinstance(p.get("ipcam"), dict) else {}
    out = {
        "auto_recovery": bool((hf >> 4) & 1) if hf is not None else None,
        "auto_switch_filament": bool((hf >> 10) & 1) if hf is not None else None,
        "sdcard": {0: "none", 1: "ok", 2: "error", 3: "read-only"}.get((hf >> 8) & 3) if hf is not None else None,
        "ams_startup_read": a.get("power_on_flag"),
        "ams_tray_read": a.get("insert_flag"),
        "ams_remain_calc": a.get("calibrate_remain_flag"),
        "timelapse": (ip.get("timelapse") == "enable") if "timelapse" in ip else None,
    }
    return out


def _ams(p):
    a = p.get("ams")
    if not isinstance(a, dict):
        a = {}
    now = _int(a.get("tray_now"))
    trays, units = [], []
    for unit in a.get("ams") or []:
        if not isinstance(unit, dict):
            continue
        uid = _int(unit.get("id")) or 0
        dry = _int(unit.get("dry_time"))
        units.append({"unit": uid + 1,
                      "temp": _num(unit.get("temp")),
                      "humidity_pct": _int(unit.get("humidity_raw")),
                      "humidity_level": _int(unit.get("humidity")),   # 1 (wet) .. 5 (dry) on older AMS
                      "dry_min_left": dry if dry and dry > 0 else 0,
                      "drying": bool(dry and dry > 0)})
        for t in unit.get("tray") or []:
            if not isinstance(t, dict):
                continue
            tid = _int(t.get("id")) or 0
            slot = uid * 4 + tid
            color = (t.get("tray_color") or "")[:6]
            trays.append({"slot": slot, "unit": uid + 1, "tray": tid + 1,
                          "type": t.get("tray_type") or "", "name": t.get("tray_sub_brands") or "",
                          "color": "#" + color if len(color) == 6 else None,
                          "remain": _int(t.get("remain")), "active": slot == now,
                          "empty": not t.get("tray_type"), "idx": t.get("tray_info_idx") or "",
                          "k": _num(t.get("k")), "cali_idx": _int(t.get("cali_idx"))})
    vt = p.get("vt_tray") if isinstance(p.get("vt_tray"), dict) else None
    ext = None
    if vt:
        color = (vt.get("tray_color") or "")[:6]
        ext = {"slot": 254, "type": vt.get("tray_type") or "", "color": "#" + color if len(color) == 6 else None,
               "active": now == 254, "idx": vt.get("tray_info_idx") or "", "k": _num(vt.get("k")),
               "cali_idx": _int(vt.get("cali_idx"))}
    return {"trays": trays, "units": units, "external": ext, "loaded": now if now not in (None, 255) else None,
            "present": bool(trays)}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class BambuPrinter:
    def __init__(self, ip: str, serial: str, access_code: str, port: int = 8883):
        self.ip = ip
        self.port = port
        self.serial = serial
        self.connected = False
        self.error: str | None = None
        self.last_report = 0.0
        self.print: dict = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._listeners = []
        self._last_pushall = 0.0
        self._replies: dict = {}
        self._reply_cv = threading.Condition()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"printwatch-{random.randint(1000, 9999)}",
        )
        self.client.username_pw_set("bblp", access_code)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.client.tls_set_context(ctx)
        self.client.reconnect_delay_set(min_delay=2, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # lifecycle ----------------------------------------------------------
    def start(self):
        self.client.connect_async(self.ip, self.port, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._refresher, name="pushall", daemon=True).start()

    def on_change(self, fn):
        """fn(old_state:str, new_state:str, status:dict) on gcode_state changes."""
        self._listeners.append(fn)

    # mqtt callbacks -----------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.connected = False
            self.error = f"MQTT refused: {reason_code} (check access code / LAN mode)"
            log.warning(self.error)
            return
        self.connected = True
        self.error = None
        log.info("MQTT connected to %s", self.ip)
        client.subscribe(f"device/{self.serial}/report")
        self.pushall()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self.connected:
            log.warning("MQTT disconnected: %s", reason_code)
        self.connected = False
        if reason_code and reason_code.is_failure:
            self.error = f"MQTT disconnected: {reason_code}"

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        STREAMS.add("p1s", "P1S > Pi  " + msg.payload.decode(errors="replace"))
        p = payload.get("print")
        if not isinstance(p, dict):
            return
        if p.get("command") in PA_REPLIES:          # answers to our pressure-advance requests
            with self._reply_cv:
                self._replies[p["command"]] = p
                self._reply_cv.notify_all()
            return
        with self._lock:
            old = self.print.get("gcode_state")
            _merge(self.print, p)
            new = self.print.get("gcode_state")
            self.last_report = time.time()
        if old != new and new is not None:
            log.info("state %s -> %s", old, new)
            snap = self.status()
            for fn in self._listeners:
                try:
                    fn(old, new, snap)
                except Exception:  # noqa: BLE001
                    log.exception("state listener failed")

    def _refresher(self):
        while True:
            time.sleep(30)
            if self.connected and time.time() - self._last_pushall > PUSHALL_EVERY_S:
                self.pushall()

    # commands -----------------------------------------------------------
    def _next_seq(self) -> str:
        self._seq += 1
        return str(self._seq)

    def _publish(self, payload: dict) -> bool:
        if not self.connected:
            return False
        data = json.dumps(payload)
        info = self.client.publish(f"device/{self.serial}/request", data)
        STREAMS.add("p1s", "Pi > P1S  " + data)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def pushall(self):
        self._last_pushall = time.time()
        return self._publish({"pushing": {"sequence_id": self._next_seq(), "command": "pushall"}})

    def _print_cmd(self, command: str) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": command, "param": ""}})

    def pause(self):
        return self._print_cmd("pause")

    def resume(self):
        return self._print_cmd("resume")

    def stop(self):
        return self._print_cmd("stop")

    def light(self, on: bool):
        return self._publish({"system": {
            "sequence_id": self._next_seq(), "command": "ledctrl",
            "led_node": "chamber_light", "led_mode": "on" if on else "off",
            "led_on_time": 500, "led_off_time": 500, "loop_times": 0, "interval_time": 0,
        }})

    # extended controls ---------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.state in ACTIVE

    def gcode(self, lines: str) -> bool:
        lines = "\n".join(l.strip() for l in str(lines).splitlines() if l.strip())
        if not lines:
            return False
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "gcode_line",
                                        "param": lines + "\n"}})

    def set_speed(self, level: int) -> bool:
        if int(level) not in SPEEDS:
            raise ValueError("speed level must be 1-4")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "print_speed",
                                        "param": str(int(level))}})

    def set_fan(self, fan: str, percent: float) -> bool:
        if fan not in FANS:
            raise ValueError("fan must be part, aux or chamber")
        pwm = max(0, min(255, round(float(percent) / 100 * 255)))
        return self.gcode(f"M106 P{FANS[fan]} S{pwm}")

    def set_temp(self, target: str, value: float) -> bool:
        if target not in LIMITS:
            raise ValueError("target must be nozzle or bed")
        v = int(round(float(value)))
        top = LIMITS[target]
        if v < 0 or (top is not None and v > top):
            raise ValueError(f"{target} must be 0-{top} C")
        return self.gcode(("M104 S%d" if target == "nozzle" else "M140 S%d") % v)

    def home(self) -> bool:
        self._guard_motion()
        return self.gcode("G28")

    def jog(self, axis: str, mm: float, speed: int = 3000) -> bool:
        self._guard_motion()
        axis = axis.upper()
        if axis not in ("X", "Y", "Z"):
            raise ValueError("axis must be X, Y or Z")
        mm = max(-100.0, min(100.0, float(mm)))
        f = 900 if axis == "Z" else speed
        # Same sequence Bambu Studio sends for its jog buttons (soft limits on, relative move, restore mode)
        return self.gcode(f"M211 S\nM211 X1 Y1 Z1\nM1002 push_ref_mode\nG91\nG1 {axis}{mm:.1f} F{f}\n"
                          f"M1002 pop_ref_mode\nM211 R")

    def motors_off(self) -> bool:
        self._guard_motion()
        return self.gcode("M18")

    def ams_load(self, tray: int) -> bool:
        tray = int(tray)
        if not (0 <= tray <= 15 or tray == 254):
            raise ValueError("tray must be 0-15 (AMS) or 254 (external spool)")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_change_filament",
                                        "target": tray, "curr_temp": 220, "tar_temp": 220}})

    def ams_unload(self) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_change_filament",
                                        "target": 255, "curr_temp": 220, "tar_temp": 220}})

    def ams_control(self, what: str) -> bool:
        if what not in ("resume", "reset", "pause"):
            raise ValueError("bad AMS command")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_control", "param": what}})

    def console(self, lines: str) -> bool:
        """Raw G-code from the app. Motion commands are refused while a print is active."""
        if self.busy:
            for l in str(lines).splitlines():
                m = re.match(r"\s*([GM])0*(\d+)", l.upper())
                word = f"{m.group(1)}{m.group(2)}" if m else ""
                if word in MOTION:
                    raise PermissionError(f"{word} is blocked while printing")
        return self.gcode(lines)

    def extrude(self, mm: float) -> bool:
        self._guard_motion()
        mm = max(-50.0, min(50.0, float(mm)))
        temp = _num(self.print.get("nozzle_temper")) or 0
        if temp < 170:
            raise PermissionError("heat the nozzle to at least 170\u00b0 first")
        return self.gcode(f"M83\nG0 E{mm:.1f} F900")

    def start_print(self, path: str, plate: int, ams_mapping, use_ams: bool, timelapse: bool,
                    bed_leveling: bool, flow_cali: bool, vibration_cali: bool) -> bool:
        if self.busy:
            raise PermissionError("a print is already running")
        name = path.lstrip("/")
        title = re.sub(r"(\.gcode)?\.3mf$", "", os.path.basename(name), flags=re.I)
        payload = {"print": {
            "sequence_id": self._next_seq(), "command": "project_file",
            "param": f"Metadata/plate_{int(plate)}.gcode",
            "url": f"file:///sdcard/{name}",
            "bed_type": "auto",
            "timelapse": bool(timelapse), "bed_leveling": bool(bed_leveling), "bed_levelling": bool(bed_leveling),
            "flow_cali": bool(flow_cali), "vibration_cali": bool(vibration_cali), "layer_inspect": False,
            "use_ams": bool(use_ams), "ams_mapping": [int(x) for x in ams_mapping] if ams_mapping else [0],
            "subtask_name": title, "profile_id": "0", "project_id": "0", "subtask_id": "0", "task_id": "0",
        }}
        if timelapse:   # the printer's own timelapse recorder is a separate switch; turn it on first
            self._publish({"camera": {"sequence_id": self._next_seq(), "command": "ipcam_timelapse",
                                      "control": "enable"}})
            time.sleep(0.5)
        return self._publish(payload)

    def skip_objects(self, ids) -> bool:
        ids = [int(i) for i in ids]
        if not ids:
            raise ValueError("no objects selected")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "skip_objects",
                                        "obj_list": ids, "timestamp": int(time.time())}})

    def ams_setting(self, slot: int, tray_type: str, color: str, tmin: int, tmax: int, info_idx: str = "") -> bool:
        slot = int(slot)
        if slot == 254:
            ams_id, tray_id = 255, 254       # external spool
        elif 0 <= slot <= 15:
            ams_id, tray_id = slot // 4, slot % 4
        else:
            raise ValueError("bad slot")
        color = (color or "").lstrip("#").upper()
        if not re.fullmatch(r"[0-9A-F]{6}", color):
            raise ValueError("color must be RRGGBB")
        tmin, tmax = int(tmin), int(tmax)
        if not (150 <= tmin <= tmax <= 300):
            raise ValueError("nozzle temps must be 150-300 and min <= max")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_filament_setting",
                                        "ams_id": ams_id, "tray_id": tray_id, "tray_info_idx": info_idx or "",
                                        "tray_color": color + "FF", "nozzle_temp_min": tmin,
                                        "nozzle_temp_max": tmax, "tray_type": tray_type.upper()[:16],
                                        "setting_id": ""}})

    def ams_read_rfid(self, slot: int) -> bool:
        slot = int(slot)
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_get_rfid",
                                        "ams_id": slot // 4, "slot_id": slot % 4}})

    def ams_dry(self, unit: int, on: bool, filament: str = "PLA", temp: int = 55, hours: float = 4,
                rotate: bool = True) -> bool:
        """Start/stop the dryer of an AMS HT / AMS 2 Pro. unit = the AMS number shown in the app (1, 129...)."""
        if self.busy and on:
            raise PermissionError("the printer only allows drying while it is idle")
        temp = max(30, min(85, int(temp)))   # AMS HT goes to 85, AMS 2 Pro to 65
        hours = max(1, min(24, int(round(float(hours)))))
        return self._publish({"print": {
            "sequence_id": self._next_seq(), "command": "ams_filament_drying", "ams_id": int(unit) - 1,
            "mode": 1 if on else 0, "filament": str(filament).upper()[:16] if on else "",
            "temp": temp, "cooling_temp": 45, "duration": hours, "humidity": 0,
            "rotate_tray": bool(rotate), "close_power_conflict": False}})

    def ams_user_setting(self, startup_read: bool, tray_read: bool, remain_calc: bool) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "ams_user_setting",
                                        "ams_id": -1, "startup_read_option": bool(startup_read),
                                        "tray_read_option": bool(tray_read),
                                        "calibrate_remain_flag": bool(remain_calc)}})

    def print_option(self, name: str, value: bool) -> bool:
        if name not in ("auto_recovery", "auto_switch_filament"):
            raise ValueError("unknown option")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "print_option",
                                        name: bool(value)}})

    def calibrate(self, bed: bool, vibration: bool, motor: bool) -> bool:
        if self.busy:
            raise PermissionError("can't calibrate during a print")
        option = (2 if bed else 0) | (4 if vibration else 0) | (8 if motor else 0)
        if not option:
            raise ValueError("pick at least one calibration")
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "calibration",
                                        "option": option}})

    def _guard_motion(self):
        if self.busy:
            raise PermissionError("movement is locked while a print is active")

    # status -------------------------------------------------------------
    @property
    def state(self) -> str:
        return self.print.get("gcode_state") or "UNKNOWN"

    # ---------------------------------------------------------------- pressure advance (K) per slot
    # Same commands Bambu Studio's "Flow Dynamics Calibration" uses to save a result, so a K value you
    # already know goes straight onto a slot with no calibration print.
    def _request(self, payload: dict, cmd: str, timeout: float = 8.0):
        with self._reply_cv:
            self._replies.pop(cmd, None)
        if not self._publish(payload):
            raise RuntimeError("printer not connected")
        end = time.time() + timeout
        with self._reply_cv:
            while cmd not in self._replies:
                left = end - time.time()
                if left <= 0:
                    raise RuntimeError("the printer didn't answer")
                self._reply_cv.wait(left)
            r = self._replies.pop(cmd)
        if str(r.get("result", "")).lower() == "fail":
            raise RuntimeError("printer said: " + str(r.get("reason") or "failed"))
        return r

    def _nozzle(self) -> str:
        d = _num(self.print.get("nozzle_diameter")) or 0.4
        return f"{d:.1f}"

    @staticmethod
    def _slot_ids(slot: int):
        slot = int(slot)
        if slot == 254:
            return 254, 255, 0                 # external spool
        if 0 <= slot <= 15:
            return slot, slot // 4, slot % 4
        raise ValueError("bad slot")

    def _tray(self, slot: int) -> dict:
        for t in _ams(self.print)["trays"] + [_ams(self.print)["external"] or {}]:
            if t and t.get("slot") == int(slot):
                return t
        return {}

    def pa_list(self) -> list:
        if self.print.get("cali_version") is None:
            return []                          # older firmware: no saved list, K lives on each slot
        d = self._nozzle()
        r = self._request({"print": {"sequence_id": self._next_seq(), "command": "extrusion_cali_get",
                                     "filament_id": "", "nozzle_diameter": d}}, "extrusion_cali_get")
        out = []
        for f in r.get("filaments") or []:
            try:
                k = float(f.get("k_value"))
            except (TypeError, ValueError):
                continue
            out.append({"cali_idx": _int(f.get("cali_idx")), "name": f.get("name") or "", "k": round(k, 4),
                        "filament_id": f.get("filament_id") or "", "nozzle": f.get("nozzle_diameter") or d})
        return out

    def pa_set(self, slot: int, k: float, name: str = "") -> dict:
        """Save K for a slot. New firmware: add it to the printer's saved list and assign it to the slot.
        Older firmware: write it straight onto the slot."""
        k = float(k)
        if not 0.0 <= k <= 2.0:
            raise ValueError("K must be between 0 and 2 (usually 0.01-0.1)")
        tray_id, ams_id, slot_id = self._slot_ids(slot)
        if self.print.get("cali_version") is None:
            self._publish({"print": {"sequence_id": self._next_seq(), "command": "extrusion_cali_set",
                                     "tray_id": tray_id, "k_value": k, "n_coef": 1.4}})
            return {"mode": "slot", "k": k}
        t = self._tray(slot)
        fid = t.get("idx") or ""
        if not fid:
            raise ValueError("set this slot's material first (the printer files K values under a material)")
        d = self._nozzle()
        name = (name or f"{t.get('type') or 'Filament'} K{k:.3f}").strip()[:40]
        self._request({"print": {"sequence_id": self._next_seq(), "command": "extrusion_cali_set", "nozzle_diameter": d,
                                 "filaments": [{"tray_id": tray_id, "extruder_id": 0, "nozzle_id": "HS00-" + d,
                                                "nozzle_diameter": d, "ams_id": ams_id, "slot_id": slot_id,
                                                "filament_id": fid, "setting_id": "", "name": name,
                                                "k_value": f"{k:.6f}", "n_coef": "0.0"}]}}, "extrusion_cali_set")
        time.sleep(0.5)
        match = [e for e in self.pa_list() if e["filament_id"] == fid and e["name"] == name and abs(e["k"] - k) < 1e-3]
        if not match:
            raise RuntimeError("saved, but couldn't find it in the printer's list to assign it")
        idx = max(e["cali_idx"] for e in match)
        self.pa_select(slot, idx, fid)
        return {"mode": "table", "k": k, "cali_idx": idx, "name": name}

    def pa_select(self, slot: int, cali_idx: int, filament_id: str = "") -> bool:
        tray_id, ams_id, slot_id = self._slot_ids(slot)
        fid = filament_id or self._tray(slot).get("idx") or ""
        self._request({"print": {"sequence_id": self._next_seq(), "command": "extrusion_cali_sel",
                                 "tray_id": tray_id, "ams_id": ams_id, "slot_id": slot_id, "cali_idx": int(cali_idx),
                                 "filament_id": fid, "nozzle_diameter": self._nozzle()}}, "extrusion_cali_sel")
        self.pushall()
        return True

    def pa_delete(self, cali_idx: int, filament_id: str) -> bool:
        d = self._nozzle()
        self._request({"print": {"sequence_id": self._next_seq(), "command": "extrusion_cali_del", "extruder_id": 0,
                                 "nozzle_id": "HS00-" + d, "filament_id": filament_id, "cali_idx": int(cali_idx),
                                 "nozzle_diameter": d}}, "extrusion_cali_del")
        return True

    def raw(self) -> dict:
        with self._lock:
            return dict(self.print)

    def status(self) -> dict:
        with self._lock:
            p = dict(self.print)
        light = None
        for node in p.get("lights_report") or []:
            if node.get("node") == "chamber_light":
                light = node.get("mode") == "on"
        return {
            "connected": self.connected,
            "error": self.error,
            "state": p.get("gcode_state") or "UNKNOWN",
            "job": p.get("subtask_name") or p.get("gcode_file") or "",
            "percent": p.get("mc_percent"),
            "remaining_min": p.get("mc_remaining_time"),
            "layer": p.get("layer_num"),
            "total_layers": p.get("total_layer_num"),
            "nozzle": p.get("nozzle_temper"),
            "nozzle_target": p.get("nozzle_target_temper"),
            "bed": p.get("bed_temper"),
            "bed_target": p.get("bed_target_temper"),
            "light": light,
            "print_error": p.get("print_error") or 0,
            "stage": STAGES.get(_int(p.get("stg_cur")), None),
            "speed_level": _int(p.get("spd_lvl")),
            "speed_name": SPEEDS.get(_int(p.get("spd_lvl"))),
            "speed_pct": _int(p.get("spd_mag")),
            "fans": {"part": _fan_pct(p.get("cooling_fan_speed")), "aux": _fan_pct(p.get("big_fan1_speed")),
                     "chamber": _fan_pct(p.get("big_fan2_speed")), "heatbreak": _fan_pct(p.get("heatbreak_fan_speed"))},
            "chamber": _num(p.get("chamber_temper")),
            "wifi": p.get("wifi_signal"),
            "nozzle_diameter": p.get("nozzle_diameter"),
            "ams": _ams(p),
            "hms": [f"HMS_{int(h.get('attr', 0)):08X}_{int(h.get('code', 0)):08X}" for h in (p.get("hms") or [])
                    if isinstance(h, dict)],
            "busy": (p.get("gcode_state") or "") in ACTIVE,
            "file": p.get("gcode_file") or "",
            "skipped": [int(x) for x in (p.get("s_obj") or []) if str(x).lstrip("-").isdigit()],
            "options": _options(p),
            "pa_table": p.get("cali_version") is not None,
            "report_age_s": round(time.time() - self.last_report, 1) if self.last_report else None,
        }
