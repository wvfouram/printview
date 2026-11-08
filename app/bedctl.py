"""Bed heat workaround: an Arduino Uno moves a servo that connects / disconnects the bed's
heater control wire (the main board's bed output is stuck on).

The Pi decides, the Uno only moves the servo:
  closed (servo 1880 us) = control wire connected = bed heats
  open   (servo 2020 us) = disconnected = bed off

Every second the Pi sends the wanted state ("C" or "O") and "G" (status request).
The Uno opens by itself on power-up, and if it hears nothing for 5 s.

Decision, from the printer's own bed reading (MQTT):
  heat when bed < target - HYST, stop when bed > target + HYST, at least MIN_DWELL_S between moves.
Forced open (no dwell) when: target 0, printer data stale, Uno not answering, bed >= HARD_MAX_C,
or the bed doesn't warm while heating (that one latches until Reset).
"""
import glob
import json
import logging
import logging.handlers
import os
import threading
import time

from .streams import STREAMS

log = logging.getLogger("bedctl")

HARD_MAX_C = 105.0          # bed at or above this -> open and latch
TARGET_CAP_C = 100.0        # highest target we heat toward (5 C under HARD_MAX_C)
HYST_C = 0.5                # heat below target-HYST, stop above target+HYST
MIN_DWELL_S = 10.0          # least time between servo moves (connector wear)
STALE_S = 10.0              # printer data older than this -> open
REFRESH_AFTER_S = 5.0       # ask the printer for a full report when data gets this old
NO_RISE_S = 180.0           # heating this long ...
NO_RISE_MIN_C = 2.0         # ... must raise the bed at least this much
UNO_TIMEOUT_S = 3.0         # no status reply this long -> Uno not responding
SERVO_MIN_US, SERVO_MAX_US = 1880, 2020   # anything the Uno reports outside this = glitch -> latch
LEAD_S_DEFAULT = 12.0       # stop heating this many seconds early (bed keeps rising after the cut)
LEAD_S_MAX = 60.0
SLOPE_WINDOW_S = 20.0       # how far back to look when measuring how fast the bed is rising
# Bed model fitted from a 30 min recording of the real P1S bed (Nov 2026): the heater responds after
# MODEL_DELAY_S, ramps with MODEL_TAU_S, full power adds MODEL_HEAT °C/s, and the bed loses
# MODEL_LOSS x (bed - ambient) °C/s. Each second the controller simulates the next PREDICT_S seconds
# and switches early so the bed coasts onto the target instead of past it.
MODEL_DELAY_S = 6
MODEL_TAU_S = 5.0
MODEL_HEAT = 0.275
MODEL_LOSS = 0.0013
MODEL_AMBIENT = 25.0
PREDICT_S = 90
PRED_MARGIN_C = 0.15        # predicted peak/low may stray this far from the target before switching
BAUD = 115200
BOOT_WAIT_S = 3.0           # opening the port resets the Uno


class BedControl:
    def __init__(self, printer, port: str, data_dir: str, enabled: bool = True):
        self.printer = printer
        self.port_cfg = port
        self.enabled = enabled
        self._lock = threading.Lock()
        self._ser = None
        self.port = None
        self.uno_ok = False
        self.uno_last = 0.0
        self.uno_status = {}              # parsed last reply
        self.state = "open"               # what we last asked the Uno for
        self.reason = "starting"
        self.fault = None                 # latched fault text (needs Reset)
        self.alert = None                 # current non-latched cut-off text
        self._last_move = 0.0
        self._heat_start = None           # (time, bed temp) when heating began
        self._last_refresh = 0.0
        self.manual = None                # ("open"|"close", until_time) from the test buttons
        self._hist = []                   # (time, bed temp) for the rise rate
        self._opened_at = 0.0             # when we last opened the port (the Uno restarts then)
        self._last_x = None               # Uno glitch counter last seen
        self._last_u = None               # Uno uptime last seen
        self._peak = None                 # (target, cut temp, slope at cut, peak so far) after an early stop
        self._u_hist = [0] * MODEL_DELAY_S   # relay on/off for the last few seconds (heater delay)
        self._h = 0.0                        # modelled heater output 0..1
        self._model_t = None
        self.predicted = None                # (peak if switched off now, low if left off)
        self._lead_file = os.path.join(data_dir, "bedctl_lead.json")
        try:
            self.lead_s = float(json.load(open(self._lead_file)).get("lead_s", LEAD_S_DEFAULT))
        except Exception:  # noqa: BLE001
            self.lead_s = LEAD_S_DEFAULT
        self.lines = []                   # last raw lines for the page
        # raw log file, rotating
        self.raw = logging.getLogger("bedctl.raw")
        self.raw.propagate = False
        self.raw.setLevel(logging.INFO)
        try:
            h = logging.handlers.RotatingFileHandler(os.path.join(data_dir, "bedctl.log"),
                                                     maxBytes=5_000_000, backupCount=2)
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.raw.addHandler(h)
        except OSError as e:
            log.warning("bed log file: %s", e)

    # ------------------------------------------------------------------ public
    def start(self):
        if self.enabled:
            threading.Thread(target=self._run, name="bedctl", daemon=True).start()

    def reset(self):
        with self._lock:
            self.fault = None
            self._heat_start = None
        self._note("# reset by user")

    def test(self, what: str, seconds: float = 60.0):
        """Manual test from the home page. 'close' still obeys every cut-off."""
        if what not in ("open", "close", "auto"):
            raise ValueError("open, close or auto")
        with self._lock:
            self.manual = None if what == "auto" else (what, time.time() + max(5.0, min(600.0, seconds)))
        self._note(f"# manual test: {what}")

    def status(self) -> dict:
        p = self.printer.print
        with self._lock:
            m = self.manual
            return {
                "enabled": self.enabled,
                "port": self.port,
                "uno": self.uno_ok,
                "uno_age_s": round(time.time() - self.uno_last, 1) if self.uno_last else None,
                "uno_status": dict(self.uno_status),
                "state": self.state,
                "reason": self.reason,
                "fault": self.fault,
                "alert": self.alert,
                "bed": _num(p.get("bed_temper")),
                "bed_target": _num(p.get("bed_target_temper")),
                "manual": m[0] if m and m[1] > time.time() else None,
                "hard_max": HARD_MAX_C,
                "lead_s": round(self.lead_s, 1),
                "predicted": self.predicted,
                "rate_c_per_min": round(self._slope() * 60, 1) if self._slope() is not None else None,
            }

    def log_lines(self):
        with self._lock:
            return list(self.lines)

    # ------------------------------------------------------------------ internals
    def _note(self, line: str):
        self.raw.info(line)
        STREAMS.add("uno", line.replace("> ", "Pi > Uno  ", 1) if line.startswith("> ") else
                    line.replace("< ", "Uno > Pi  ", 1) if line.startswith("< ") else line)
        with self._lock:
            self.lines.append(time.strftime("%H:%M:%S ") + line)
            del self.lines[:-50]

    def _find_port(self):
        if self.port_cfg and os.path.exists(self.port_cfg):
            return self.port_cfg
        for pat in ("/dev/serial/by-id/*rduino*", "/dev/ttyACM*", "/dev/ttyUSB*"):
            hits = sorted(glob.glob(pat))
            if hits:
                return hits[0]
        return None

    def _open(self):
        import serial
        port = self._find_port()
        if not port:
            return False
        try:
            s = serial.Serial(port, BAUD, timeout=0.2, write_timeout=1)
        except Exception as e:  # noqa: BLE001
            self._note(f"# can't open {port}: {e}")
            return False
        self._note(f"# opened {port}, waiting {BOOT_WAIT_S:.0f} s for the Uno to restart")
        time.sleep(BOOT_WAIT_S)
        s.reset_input_buffer()
        self._ser, self.port = s, port
        self._opened_at = time.time()
        self._last_x = self._last_u = None
        return True

    def _close(self, why):
        if self._ser:
            self._note(f"# port closed: {why}")
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
        self._ser = None
        self.uno_ok = False

    def _send(self, text):
        self._ser.write((text + "\n").encode())
        self._note("> " + text)

    def _read(self):
        buf = b""
        while True:
            line = self._ser.readline()
            if not line:
                break
            buf = line
            txt = line.decode(errors="replace").strip()
            if not txt:
                continue
            self._note("< " + txt)
            if txt.startswith("BOOT") and time.time() - self._opened_at > 10:
                self._latch("Uno restarted by itself (power dip?)")
            if txt.startswith("P:"):
                st = {}
                for part in txt.split():
                    if ":" in part:
                        k, v = part.split(":", 1)
                        st[k] = v
                self._check_uno(st)
                with self._lock:
                    self.uno_status = st
                    self.uno_last = time.time()
                    self.uno_ok = True
        return buf

    def _check_uno(self, st):
        """Anything impossible from the Uno locks heating off until Reset."""
        try:
            pos = int(st.get("P", ""))
        except ValueError:
            pos = None
        if pos is None or not SERVO_MIN_US <= pos <= SERVO_MAX_US:
            self._latch(f"Uno reported servo position {st.get('P')} (allowed {SERVO_MIN_US}-{SERVO_MAX_US})")
        try:
            x = int(st.get("X", "0"))
            u = int(st.get("U", "0"))
        except ValueError:
            x, u = None, None
        if x is not None and self._last_x is not None and x > self._last_x:
            self._latch(f"Uno caught {x - self._last_x} memory/timer glitch(es) and snapped open (power dip?)")
        if u is not None and self._last_u is not None and u + 2 < self._last_u and time.time() - self._opened_at > 10:
            self._latch("Uno restarted by itself (power dip?)")
        self._last_x, self._last_u = x, u

    def _slope(self):
        """Bed rise rate in °C/s over the last SLOPE_WINDOW_S, or None."""
        h = self._hist
        if len(h) < 2 or h[-1][0] - h[0][0] < SLOPE_WINDOW_S * 0.5:
            return None
        (t0, b0), (t1, b1) = h[0], h[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else None

    def _learn(self, bed, tgt):
        """After an early stop, watch the peak and nudge the lead time so the next peak lands on target."""
        if not self._peak:
            return
        p_tgt, cut_bed, slope, peak = self._peak
        if p_tgt != tgt:
            self._peak = None
            return
        if bed > peak:
            self._peak = (p_tgt, cut_bed, slope, bed)
            return
        if bed < peak - 0.5:                      # it has turned over: peak is final
            err = peak - p_tgt                    # + = overshoot, - = stopped short
            if slope and slope > 0.02:
                self.lead_s = max(0.0, min(LEAD_S_MAX, self.lead_s + 0.5 * err / slope))
                try:
                    json.dump({"lead_s": self.lead_s}, open(self._lead_file, "w"))
                except OSError:
                    pass
                self._note(f"# peak {peak:.1f} for target {p_tgt:.0f} ({err:+.1f}), lead now {self.lead_s:.1f} s")
            self._peak = None

    def _model_step(self, now):
        """Advance the heater model by the seconds since the last call, using the relay states we sent."""
        if self._model_t is None:
            self._model_t = now
            return
        steps = int(min(30, max(0, round(now - self._model_t))))
        for _ in range(steps):
            self._u_hist.append(1 if self.state == "close" else 0)
            u = self._u_hist.pop(0)
            self._h += (u - self._h) / MODEL_TAU_S
        if steps:
            self._model_t = now

    def _predict(self, bed, on_now):
        """Simulate ahead from the measured bed temp. Returns (peak, low) over PREDICT_S seconds,
        with the relay held at on_now from here on."""
        q = list(self._u_hist)
        h, t = self._h, bed
        peak = low = bed
        for _ in range(PREDICT_S):
            q.append(1 if on_now else 0)
            u = q.pop(0)
            h += (u - h) / MODEL_TAU_S
            t += MODEL_HEAT * h - MODEL_LOSS * (t - MODEL_AMBIENT)
            peak, low = max(peak, t), min(low, t)
        return peak, low

    def _decide(self):
        """Returns (state, reason, alert). Updates latched fault."""
        now = time.time()
        p = self.printer.print
        bed = _num(p.get("bed_temper"))
        target = _num(p.get("bed_target_temper")) or 0.0
        age = now - self.printer.last_report if self.printer.last_report else 1e9

        if age > REFRESH_AFTER_S and now - self._last_refresh > REFRESH_AFTER_S and self.printer.connected:
            self._last_refresh = now
            try:
                self.printer.pushall()
            except Exception:  # noqa: BLE001
                pass

        self._model_step(now)
        if bed is not None and age <= STALE_S:
            self._hist.append((now, bed))
            while self._hist and now - self._hist[0][0] > SLOPE_WINDOW_S:
                self._hist.pop(0)
        with self._lock:
            fault, manual = self.fault, self.manual
        if manual and manual[1] <= now:
            manual = None
            with self._lock:
                self.manual = None

        if fault:
            return "open", "fault: " + fault, None
        if bed is not None and bed >= HARD_MAX_C:
            self._latch(f"bed reached {bed:.1f} °C (limit {HARD_MAX_C:.0f})")
            return "open", "over-temperature", None
        if not self.printer.connected or age > STALE_S:
            return "open", "printer data stale", f"no fresh printer data for {age:.0f} s" if age < 1e8 else "no printer data"
        if bed is None:
            return "open", "no bed reading", "printer isn't reporting the bed temperature"
        if not self.uno_ok:
            return "open", "Uno not responding", "Uno not responding"

        if manual:
            want = manual[0]
            reason = f"manual test ({want})"
        else:
            tgt = min(target, TARGET_CAP_C)
            if tgt <= 0:
                return "open", "target 0", None
            peak_off, low_off = self._predict(bed, False)       # what happens if the relay is off from now
            self.predicted = (round(peak_off, 1), round(low_off, 1))
            if self.state == "close":
                want = "open" if peak_off >= tgt + PRED_MARGIN_C else "close"
            else:
                want = "close" if low_off <= tgt - PRED_MARGIN_C else "open"
            if bed >= tgt + 1.0:
                want = "open"
            reason = (f"bed {bed:.1f} °C, target {tgt:.0f}" + (" (capped)" if target > TARGET_CAP_C else "") +
                      f", predicted {peak_off:.1f} max / {low_off:.1f} min if off")

        # heating but not warming -> latch
        if self.state == "close":
            if self._heat_start is None:
                self._heat_start = (now, bed)
            elif now - self._heat_start[0] > NO_RISE_S:
                if bed - self._heat_start[1] < NO_RISE_MIN_C:
                    self._latch(f"heated {NO_RISE_S/60:.0f} min but bed only rose {bed - self._heat_start[1]:.1f} °C")
                    return "open", "no heating", None
                self._heat_start = (now, bed)
        else:
            self._heat_start = None

        # dwell (safety cut-offs above skip this)
        if want == "close" and self.state != "close" and now - self._last_move < MIN_DWELL_S:
            return self.state, reason + f" (waiting {MIN_DWELL_S - (now - self._last_move):.0f} s)", None
        return want, reason, None

    def _latch(self, why):
        with self._lock:
            if not self.fault:
                self.fault = why
                log.warning("bed fault: %s", why)
        self._note("# FAULT: " + why)

    def _run(self):
        while True:
            if not self._ser and not self._open():
                with self._lock:
                    self.state, self.reason, self.alert = "open", "no Uno on USB", "Uno not connected"
                time.sleep(2)
                continue
            try:
                state, reason, alert = self._decide()
                if state != self.state:
                    self._last_move = time.time()
                    self._heat_start = None
                self._send("C" if state == "close" else "O")
                self._send("G")
                t_end = time.time() + 0.9
                while time.time() < t_end:
                    self._read()
                if self.uno_last and time.time() - self.uno_last > UNO_TIMEOUT_S:
                    self.uno_ok = False
                with self._lock:
                    self.state, self.reason, self.alert = state, reason, alert
            except Exception as e:  # noqa: BLE001  (unplugged, I/O error...)
                self._close(str(e) or e.__class__.__name__)
                with self._lock:
                    self.state, self.reason, self.alert = "open", "USB link lost", "Uno disconnected"
                time.sleep(1)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
