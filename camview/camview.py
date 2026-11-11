"""PrintWatch public web link. Separate from the phone app.

https://<pi>.ts.net:10000/<key>  -> live camera for anyone with the link.
Enter the access code there to unlock full control in the browser. Control requests are passed to
PrintWatch's own local API on the Pi (127.0.0.1:8080), so the phone app is never touched.

The master code (MASTER_CODE) opens the command center: freeze everyone on the general code,
change the general code, and see who is logged in. Master browsers are never frozen.

Files in ./data: key (link secret; delete + restart for a new link), sessions.json (logged-in browsers),
state.json (freeze switch + general code set from the command center, which overrides ACCESS_CODE).
"""
import hashlib, hmac, json, os, secrets, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.environ.get("APP", "http://127.0.0.1:8080")
PORT = int(os.environ.get("PORT", "8090"))
MASTER = os.environ.get("MASTER_CODE", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = "/data"
os.makedirs(DATA, exist_ok=True)

KEYF = os.path.join(DATA, "key")
if not os.path.exists(KEYF) or not open(KEYF).read().strip():
    open(KEYF, "w").write(secrets.token_urlsafe(12))
KEY = open(KEYF).read().strip()
BASE = "/" + KEY
SESSION_DAYS = 30

# ---------------------------------------------------------------- state (freeze + general code)
STATEF = os.path.join(DATA, "state.json")
try:
    _state = json.load(open(STATEF))
except Exception:
    _state = {}
_state.setdefault("frozen", False)
_state.setdefault("code", None)


def _save_state():
    tmp = STATEF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_state, f)
    os.replace(tmp, STATEF)


def general_code():
    return (_state.get("code") or os.environ.get("ACCESS_CODE", "")).strip()


def tag_for(role):
    """Sessions die when their code changes."""
    code = MASTER if role == "master" else general_code()
    return hashlib.sha256((role + ":" + code).encode()).hexdigest()[:16]

# API calls allowed through (everything the phone app uses, minus phone pairing)
BLOCKED = ("/api/pair", "/api/remote", "/api/login", "/api/camview", "/api/bed/")
# What anyone with the link (no code, or frozen) may read. Nothing that changes anything.
READ_ONLY = ("/api/status", "/api/job", "/api/job/plate.png")
_rlock = threading.Lock()
_rcache = [b"", 0.0]

# ---------------------------------------------------------------- sessions
SESSF = os.path.join(DATA, "sessions.json")
_slock = threading.Lock()
try:
    _sessions = {k: v for k, v in json.load(open(SESSF)).items()
                 if v.get("role") in ("general", "master") and v.get("tag") == tag_for(v["role"])
                 and v.get("exp", 0) > time.time()}
except Exception:
    _sessions = {}


def _save_sessions():
    tmp = SESSF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_sessions, f)
    os.replace(tmp, SESSF)


_last_save = [0.0]


def new_session(role, ip, ua):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with _slock:
        _sessions[tok] = {"exp": now + SESSION_DAYS * 86400, "tag": tag_for(role), "role": role,
                          "id": secrets.token_hex(4), "ip": ip, "ua": ua[:300], "created": now, "seen": now}
        _save_sessions()
    return tok


def session(tok, ip=None):
    """The session for this cookie (or None). Also records last activity."""
    if not tok:
        return None
    with _slock:
        s = _sessions.get(tok)
        if not s or s["exp"] <= time.time() or s.get("tag") != tag_for(s.get("role")):
            return None
        s["seen"] = time.time()
        if ip:
            s["ip"] = ip
        if time.time() - _last_save[0] > 30:
            _last_save[0] = time.time()
            _save_sessions()
        return dict(s)


def drop_role(role):
    with _slock:
        for k in [k for k, v in _sessions.items() if v.get("role") == role]:
            del _sessions[k]
        _save_sessions()


def device(ua):
    ua = ua or ""
    os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                ("Mac OS X", "Mac"), ("CrOS", "Chromebook"), ("Linux", "Linux")) if k in ua), "Unknown device")
    br = next((n for k, n in (("Edg/", "Edge"), ("SamsungBrowser", "Samsung Internet"), ("Firefox", "Firefox"),
                               ("OPR/", "Opera"), ("Chrome", "Chrome"), ("Safari", "Safari")) if k in ua), "browser")
    return f"{br} on {os_}"


def end_session(tok):
    with _slock:
        if _sessions.pop(tok, None):
            _save_sessions()


# ---------------------------------------------------------------- visitor log (command center only)
# One row per device: same address + same browser are combined, with counts and first/last seen.
VISITF = os.path.join(DATA, "visitors.json")
_vlock = threading.Lock()
try:
    _visitors = json.load(open(VISITF))
except Exception:
    _visitors = {}
_vsave = [0.0]

# ---------------------------------------------------------------- rough location of visitor addresses (city, country)
# Looked up once per address from ip-api.com (free, no key), cached in geo.json. Approximate: it's where the
# internet provider is, often a nearby city. Home-network addresses aren't looked up.
GEOF = os.path.join(DATA, "geo.json")
_geolock = threading.Lock()
try:
    _geo = json.load(open(GEOF))
except Exception:
    _geo = {}
_geoq = []
_geoev = threading.Event()


def _private(ip):
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or ip.startswith("100.")
    except ValueError:
        return True


def geo_want(ip):
    with _geolock:
        if isinstance(_geo.get(ip), dict) or ip in _geoq or _private(ip):
            return
        _geoq.append(ip)
    _geoev.set()


def _geo_worker():
    while True:
        _geoev.wait()
        with _geolock:
            ip = _geoq.pop(0) if _geoq else None
            if not _geoq:
                _geoev.clear()
        if not ip:
            continue
        place = None
        try:
            with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?fields=status,city,regionName,country,lat,lon", timeout=8) as r:
                j = json.loads(r.read())
            if j.get("status") == "success":
                place = {"place": ", ".join(x for x in (j.get("city"), j.get("regionName"), j.get("country")) if x),
                         "lat": j.get("lat"), "lon": j.get("lon")}
        except Exception:
            pass
        with _geolock:
            if place:
                _geo[ip] = place
                try:
                    tmp = GEOF + ".tmp"
                    with open(tmp, "w") as fh:
                        json.dump(_geo, fh)
                    os.replace(tmp, GEOF)
                except OSError:
                    pass
        time.sleep(2)                                # stay well under the free limit (45 a minute)


threading.Thread(target=_geo_worker, daemon=True).start()


def geo_place(ip):
    """(place, lat, lon). Older entries saved without coordinates are looked up again."""
    if _private(ip):
        return "Home network", None, None
    with _geolock:
        g = _geo.get(ip)
    if isinstance(g, dict):
        return g.get("place"), g.get("lat"), g.get("lon")
    return g, None, None


def visit(ip, ua, kind, role=None):
    """kind: open (page load), watch (camera running), ok (right code), bad (wrong code)."""
    key = hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()[:16]
    geo_want(ip)
    now = time.time()
    with _vlock:
        v = _visitors.get(key)
        if not v:
            v = _visitors[key] = {"ip": ip, "ua": ua[:300], "first": now, "last": now, "opens": 0,
                                  "watch_s": 0, "ok": 0, "bad": 0, "role": None}
        if kind == "watch":
            gap = now - v.get("seen_watch", 0)
            if gap < 15:
                v["watch_s"] += gap              # time with the camera open, counted from frame requests
            v["seen_watch"] = now
        elif kind in ("opens", "ok", "bad"):
            v[kind] += 1
        if role:
            v["role"] = role
        v["last"] = now
        if now - _vsave[0] > 20 or kind != "watch":
            _vsave[0] = now
            tmp = VISITF + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(_visitors, fh)
            os.replace(tmp, VISITF)


def visitors_list():
    now = time.time()
    with _vlock:
        rows = [dict(v, id=k) for k, v in _visitors.items()]
    with _glock:
        for r in rows:
            g = _guard.get(r["ip"])
            r["locked_s"] = round(g["until"] - now) if g and g["until"] > now else 0
    for r in rows:
        r["device"] = device(r.get("ua"))
        r["place"], r["lat"], r["lon"] = geo_place(r["ip"])
        if r["lat"] is None:
            geo_want(r["ip"])
        r["watch_min"] = round(r.pop("watch_s", 0) / 60, 1)
        r.pop("seen_watch", None)
    rows.sort(key=lambda r: -r["last"])
    return rows


# ---------------------------------------------------------------- Y-axis exercise (master / phone app only)
# Homes, lifts Z to 20 mm, then runs the toolhead back and forth along Y only, between Y20 and Y236.
# Stops by itself at the end, if a print starts, if the printer goes offline, or from Stop.
EX_X0, EX_X1 = 20, 236
EX_BATCH = 4                                     # back-and-forth pairs sent at a time (~20 s at 100 mm/s)
_ex = {"running": False, "started": None, "ends": None, "passes": 0, "hours": 24, "speed": 100,
       "stopped": None, "reason": ""}
_ex_stop = threading.Event()
_exlock = threading.Lock()


def _app(path, body=None, timeout=10):
    req = urllib.request.Request(APP + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}


def _gcode(lines):
    r = _app("/api/cmd", {"action": "gcode", "gcode": lines})
    if not r.get("ok"):
        raise RuntimeError(r.get("error") or "printer refused the move")


def _printer_problem():
    p = (_app("/api/status") or {}).get("printer") or {}
    if not p.get("connected"):
        return "printer went offline"
    if p.get("busy"):
        return "a print is running"
    return None


def _exercise():
    speed = _ex["speed"]
    f = int(speed * 60)
    pair_s = 2 * (EX_X1 - EX_X0) / speed + 0.5    # two strokes plus a little for speeding up / slowing down
    reason = "finished"
    try:
        _gcode(f"G28\nG90\nG1 Z20 F600\nG1 Y{EX_X0} F{f}")
        if _ex_stop.wait(90):                     # homing takes about a minute and a half
            reason = "stopped"
            return
        while time.time() < _ex["ends"]:
            why = _printer_problem()
            if why:
                reason = "stopped: " + why
                return
            _gcode("\n".join(f"G1 Y{EX_X1} F{f}\nG1 Y{EX_X0} F{f}" for _ in range(EX_BATCH)))
            with _exlock:
                _ex["passes"] += EX_BATCH
            if _ex_stop.wait(EX_BATCH * pair_s):
                reason = "stopped"
                return
    except Exception as e:  # noqa: BLE001
        reason = f"stopped: {e}"
    finally:
        try:
            _gcode("M400\nM18 X Y")              # finish the last strokes, then X/Y motors off (Z keeps holding the bed)
        except Exception:
            pass
        with _exlock:
            _ex.update(running=False, stopped=time.time(), reason=reason)


def exercise_state():
    with _exlock:
        e = dict(_ex)
    e["left_s"] = max(0, round(e["ends"] - time.time())) if e["running"] and e["ends"] else 0
    e["range"] = [EX_X0, EX_X1]
    return e


def exercise_cmd(b):
    act = b.get("action")
    if act == "stop":
        _ex_stop.set()
        return {"ok": True}
    if act != "start":
        return {"ok": False, "error": "unknown action"}
    try:
        hours = float(b.get("hours", 24))
        speed = int(b.get("speed", 100))
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad numbers"}
    if not (0.05 <= hours <= 48) or not (20 <= speed <= 500):
        return {"ok": False, "error": "hours 0.05-48, speed 20-500 mm/s"}
    with _exlock:
        if _ex["running"]:
            return {"ok": False, "error": "already running"}
    why = _printer_problem()
    if why:
        return {"ok": False, "error": "can't start: " + why}
    _ex_stop.clear()
    now = time.time()
    with _exlock:
        _ex.update(running=True, started=now, ends=now + hours * 3600, passes=0, hours=hours, speed=speed,
                   stopped=None, reason="")
    threading.Thread(target=_exercise, daemon=True).start()
    return {"ok": True}


# ---------------------------------------------------------------- guessing protection
# Per address: 10 wrong codes -> locked 10 min. After that, every wrong code doubles the lock
# (20 min, 40 min, 80 min ... up to 24 h). A correct code, or a day with no wrong codes, resets it.
# Safety net: 30 wrong codes in an hour from all addresses together pauses every login for an hour.
FREE_TRIES, FIRST_LOCK, MAX_LOCK = 10, 600, 86400
_glock = threading.Lock()
_guard = {}          # ip -> {"fails": n, "strikes": k, "until": t, "last": t}
_all_fails = []
_locked_until = [0.0]


def _wait(sec):
    sec = int(sec + 59) // 60
    return f"{sec} min" if sec < 60 else f"{sec // 60} h {sec % 60} min" if sec % 60 else f"{sec // 60} h"


def login_blocked(ip):
    now = time.time()
    with _glock:
        if now < _locked_until[0]:
            return f"Too many wrong codes from everyone. Logins are paused for {_wait(_locked_until[0] - now)}."
        g = _guard.get(ip)
        if g and now - g["last"] > 86400 and now >= g["until"]:
            _guard.pop(ip, None)
        elif g and now < g["until"]:
            return f"Too many wrong codes. Try again in {_wait(g['until'] - now)}."
    return None


def login_failed(ip):
    """Records a wrong code and returns the message to show."""
    now = time.time()
    with _glock:
        _all_fails[:] = [t for t in _all_fails if now - t < 3600] + [now]
        if len(_all_fails) >= 30:
            _locked_until[0] = now + 3600
        g = _guard.setdefault(ip, {"fails": 0, "strikes": 0, "until": 0.0, "last": now})
        g["last"] = now
        if g["strikes"] == 0:
            g["fails"] += 1
            left = FREE_TRIES - g["fails"]
            if left > 0:
                return f"Wrong code. {left} tr{'y' if left == 1 else 'ies'} left."
        g["strikes"] += 1
        lock = min(MAX_LOCK, FIRST_LOCK * 2 ** (g["strikes"] - 1))
        g["until"] = now + lock
        return f"Wrong code. Locked for {_wait(lock)}."


def login_ok(ip):
    with _glock:
        _guard.pop(ip, None)


# ---------------------------------------------------------------- camera (shared by every viewer)
_flock = threading.Lock()
_frame = [b"", 0.0, ""]   # jpeg, fetched at, etag


def frame():
    with _flock:  # one fetch per second no matter how many people watch
        if time.time() - _frame[1] > 1.0:
            try:
                with urllib.request.urlopen(APP + "/snapshot.jpg", timeout=5) as r:
                    _frame[0] = r.read()
            except Exception:
                _frame[0] = b""
            _frame[1] = time.time()
            _frame[2] = '"' + hashlib.md5(_frame[0]).hexdigest()[:16] + '"' if _frame[0] else ""
        return _frame[0], _frame[2]


PAGE_FILE = os.path.join(HERE, "page.html")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 20                                 # drop connections that stall (slow-drip attacks)

    # ------------------------------------------------------------ helpers
    def ip(self):
        # Tailscale Funnel adds the real caller's address as the LAST entry; anything before it was
        # sent by the visitor and can be faked, so it's ignored.
        if self.client_address[0] in ("127.0.0.1", "::1"):
            parts = [p.strip() for p in (self.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
            if parts:
                return parts[-1][:64]
        return self.client_address[0]

    def cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "pw_s":
                return v
        return ""

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, code, obj, extra=None):
        self.send(code, json.dumps(obj), "application/json", extra)

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        n = max(0, min(n, 64_000))              # never read an unbounded or negative-length body
        return self.rfile.read(n) if n else b""

    def end_headers(self):
        # Browser protections on every response: only load things from this page, never in a frame.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    # ------------------------------------------------------------ routing
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        path, _, query = self.path.partition("?")
        if path != BASE and not path.startswith(BASE + "/"):
            return self.send(404, "not found")
        sub = path[len(BASE):] or "/"

        if method == "GET" and sub in ("/", ""):
            visit(self.ip(), self.headers.get("User-Agent") or "", "opens")
            html = open(PAGE_FILE, encoding="utf-8").read().replace("__BASE__", BASE)
            return self.send(200, html, "text/html; charset=utf-8")
        if method == "GET" and sub == "/frame.jpg":
            visit(self.ip(), self.headers.get("User-Agent") or "", "watch")
            f, etag = frame()
            if not f:
                return self.send(503, "no frame")
            if self.headers.get("If-None-Match") == etag:   # same picture as last time: send nothing
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(f)))
            self.end_headers()
            self.wfile.write(f)
            return
        if method == "GET" and sub == "/me":
            s = session(self.cookie(), self.ip())
            return self.json(200, {"unlocked": bool(s), "role": s and s["role"], "frozen": _state["frozen"]})
        if method == "POST" and sub == "/login":
            return self.login()
        if method == "POST" and sub == "/logout":
            end_session(self.cookie())
            return self.json(200, {"ok": True}, {"Set-Cookie": f"pw_s=; Path={BASE}; Max-Age=0; Secure; HttpOnly; SameSite=Strict"})

        # Read-only view: no code (or frozen) can still see status, AMS and the current job, never change them.
        s = session(self.cookie(), self.ip())
        view_only = not s or (s["role"] != "master" and _state["frozen"])
        if view_only and method == "GET" and sub in READ_ONLY:
            return self.read_only(sub)
        if not s:
            return self.json(401, {"ok": False, "error": "locked"})
        if method == "POST" and self.headers.get("X-PW") != "1":   # blocks cross-site form posts
            return self.json(403, {"ok": False, "error": "bad request"})
        if sub.startswith("/admin/"):
            if s["role"] != "master":
                return self.json(403, {"ok": False, "error": "master code only"})
            return self.admin(method, sub, s)
        if s["role"] != "master" and _state["frozen"]:
            return self.json(423, {"ok": False, "error": "Controls are frozen by the owner"})
        if method == "POST" and sub == "/api/cmd" and s["role"] != "master":
            data = self.body()
            try:
                act = json.loads(data or b"{}").get("action")
            except ValueError:
                act = None
            if act == "gcode":
                return self.json(403, {"ok": False, "error": "Raw G-code needs the master code"})
            return self.proxy(method, sub, data)
        if method == "POST" and sub == "/api/upload":
            return self.upload_proxy(query)
        if sub.startswith("/api/") and not sub.startswith(BLOCKED):
            return self.proxy(method, sub + ("?" + query if query else ""))
        if method == "GET" and sub == "/detection.jpg":
            return self.proxy(method, sub)
        return self.send(404, "not found")

    def read_only(self, sub):
        """Status is cached for a second so lots of viewers cost the printer app one request a second.
        Viewers never get SD card file names/paths or past prints (activity log, training history)."""
        if sub == "/api/job/plate.png":
            return self.proxy("GET", sub)
        if sub == "/api/job":
            try:
                with urllib.request.urlopen(APP + "/api/job", timeout=60) as r:
                    j = json.loads(r.read())
            except Exception:
                return self.json(502, {"ok": False, "error": "PrintWatch isn't answering"})
            if not isinstance(j, dict):
                j = {"found": False}
            j.pop("path", None)
            return self.json(200, j)
        with _rlock:
            if time.time() - _rcache[1] > 1.0:
                try:
                    with urllib.request.urlopen(APP + "/api/status", timeout=6) as r:
                        j = json.loads(r.read())
                    for k in ("events", "training"):
                        j.pop(k, None)
                    pr = j.get("printer") or {}
                    pr.pop("file", None)                  # SD card file path of the current job
                    _rcache[0] = json.dumps(j).encode()
                except Exception:
                    _rcache[0] = b""
                _rcache[1] = time.time()
            body = _rcache[0]
        if not body:
            return self.json(502, {"ok": False, "error": "PrintWatch isn't answering"})
        return self.send(200, body, "application/json")

    def login(self):
        ip = self.ip()
        msg = login_blocked(ip)
        if msg:
            return self.json(429, {"ok": False, "error": msg})
        try:
            code = str(json.loads(self.body() or b"{}").get("code", "")).strip()
        except ValueError:
            code = ""
        time.sleep(0.8)  # slow down guessing
        role = None
        if MASTER and hmac.compare_digest(code.encode(), MASTER.encode()):
            role = "master"
        elif general_code() and hmac.compare_digest(code.encode(), general_code().encode()):
            role = "general"
        ua = self.headers.get("User-Agent") or ""
        if not role:
            visit(ip, ua, "bad")
            return self.json(403, {"ok": False, "error": login_failed(ip)})
        visit(ip, ua, "ok", role)
        login_ok(ip)
        tok = new_session(role, ip, self.headers.get("User-Agent") or "")
        cookie = f"pw_s={tok}; Path={BASE}; Max-Age={SESSION_DAYS * 86400}; Secure; HttpOnly; SameSite=Strict"
        return self.json(200, {"ok": True, "role": role}, {"Set-Cookie": cookie})

    def admin(self, method, sub, me):
        if method == "GET" and sub == "/admin/state":
            now = time.time()
            with _slock:
                rows = [{"id": v["id"], "role": v["role"], "device": device(v.get("ua")), "ip": v.get("ip"),
                         "seen_s": round(now - v.get("seen", now)), "since": v.get("created"), "me": bool(me) and v["id"] == me["id"]}
                        for v in _sessions.values() if v["exp"] > now and v.get("tag") == tag_for(v.get("role"))]
            rows.sort(key=lambda r: (r["role"] != "master", r["seen_s"]))
            return self.json(200, {"frozen": _state["frozen"], "code_custom": bool(_state.get("code")),
                                   "sessions": rows})
        try:
            b = json.loads(self.body() or b"{}")
        except ValueError:
            b = {}
        if method == "POST" and sub == "/admin/freeze":
            _state["frozen"] = bool(b.get("frozen"))
            _save_state()
            return self.json(200, {"ok": True, "frozen": _state["frozen"]})
        if method == "POST" and sub == "/admin/code":
            code = str(b.get("code", "")).strip()
            if not (4 <= len(code) <= 32) or not code.isalnum():
                return self.json(400, {"ok": False, "error": "Use 4 to 32 letters or numbers"})
            if code == MASTER:
                return self.json(400, {"ok": False, "error": "Can't be the same as the master code"})
            _state["code"] = code
            _save_state()
            drop_role("general")   # everyone on the old code is logged out
            return self.json(200, {"ok": True})
        if sub == "/admin/exercise":
            if method == "GET":
                return self.json(200, exercise_state())
            r = exercise_cmd(b)                  # body was read above
            return self.json(200 if r.get("ok") else 400, r)
        if method == "GET" and sub == "/admin/visitors":
            return self.json(200, {"visitors": visitors_list()})
        if method == "POST" and sub == "/admin/visitors/clear":
            with _vlock:
                _visitors.clear()
                with open(VISITF, "w") as fh:
                    json.dump(_visitors, fh)
            return self.json(200, {"ok": True})
        if method == "POST" and sub == "/admin/kick":
            sid = str(b.get("id", ""))
            with _slock:
                for k in [k for k, v in _sessions.items() if v["id"] == sid and v["role"] == "general"]:
                    del _sessions[k]
                _save_sessions()
            return self.json(200, {"ok": True})
        return self.send(404, "not found")

    def upload_proxy(self, query):
        """Stream a print file (up to 500 MB) straight through to PrintView without holding it in memory."""
        import http.client
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 500 * 1024 * 1024:
            return self.json(413, {"ok": False, "error": "File too big (500 MB max)"})
        host, port = APP.split("//", 1)[1].split(":")
        c = http.client.HTTPConnection(host, int(port), timeout=300)
        try:
            c.putrequest("POST", "/api/upload?" + query)
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(n))
            c.endheaders()
            left = n
            while left:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                c.send(chunk)
                left -= len(chunk)
            r = c.getresponse()
            return self.send(r.status, r.read().decode(errors="replace"), "application/json")
        except Exception:
            return self.json(502, {"ok": False, "error": "Upload didn't reach PrintView"})
        finally:
            c.close()

    def proxy(self, method, sub, data=None):
        if data is None and method == "POST":
            data = self.body()
        req = urllib.request.Request(APP + sub, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if sub.startswith("/api/files/gcode3d") and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            req.add_header("Accept-Encoding", "gzip")      # pass the gzipped toolpath straight through
        try:
            r = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            r = e
        except Exception:
            return self.json(502, {"ok": False, "error": "PrintWatch isn't answering"})
        try:
            self.send_response(r.status if hasattr(r, "status") else r.code)
            for h in ("Content-Type", "Content-Disposition", "Content-Length", "Content-Encoding"):
                if r.headers.get(h):
                    self.send_header(h, r.headers[h])
            self.send_header("Cache-Control", "no-store")
            if not r.headers.get("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            while True:  # stream (timelapse downloads can be big)
                chunk = r.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            r.close()

    def log_message(self, *a):
        pass


class Owner(H):
    """Owner port: only on the Pi itself (127.0.0.1:8091). PrintWatch forwards the phone app's
    command center here, so the paired app has master powers without a code."""

    def route(self, method):
        path = self.path.partition("?")[0]
        if path.startswith("/admin/"):
            return self.admin(method, path, None)
        return self.send(404, "not found")


class Server(ThreadingHTTPServer):
    """At most MAX_CONN connections at once; extras are closed straight away instead of piling up."""
    daemon_threads = True
    MAX_CONN = 64

    def __init__(self, *a, **k):
        self._slots = threading.BoundedSemaphore(self.MAX_CONN)
        super().__init__(*a, **k)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


threading.Thread(target=Server(("127.0.0.1", int(os.environ.get("OWNER_PORT", "8091"))), Owner).serve_forever,
                 daemon=True).start()

if not general_code():
    print("WARNING: no ACCESS_CODE set", flush=True)
if not MASTER:
    print("WARNING: no MASTER_CODE set, command center is off", flush=True)
print("link path: " + BASE, flush=True)
Server(("127.0.0.1", PORT), H).serve_forever()
