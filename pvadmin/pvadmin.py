#!/usr/bin/env python3
"""PrintView Admin: the full PrintView website with owner powers, only on the Pi itself.

Listens on 127.0.0.1:8095 (never on the network), so whoever is logged in to the Pi desktop is the admin.
It serves the same page as the web link, but every request goes straight to PrintView on this Pi, as the
owner: no codes, every tab, plus an Admin tab to kick anyone (master users too), change both codes,
add videos from the Pi's folders, see logs, and update + restart PrintView.
"""
import http.client
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
PORT = int(os.environ.get("PVADMIN_PORT", "8095"))
APP = ("127.0.0.1", 8080)          # PrintView app
OWNER = ("127.0.0.1", 8091)        # camview owner port (/admin/*)


def find_dirs():
    """Supports both layouts: ~/printwatch + ~/camview (older installs) and ~/printview (git installs)."""
    for app_dir, cam_dir in ((f"{HOME}/printwatch", f"{HOME}/camview"), (f"{HOME}/printview", f"{HOME}/printview/camview")):
        if os.path.isfile(os.path.join(app_dir, "docker-compose.yml")):
            return app_dir, cam_dir
    return f"{HOME}/printview", f"{HOME}/printview/camview"


APP_DIR, CAM_DIR = find_dirs()


def env_value(key):
    try:
        for line in open(os.path.join(APP_DIR, ".env")):
            k, _, v = line.strip().partition("=")
            if k == key:
                return v.strip()
    except OSError:
        pass
    return ""


_cookie = {"v": ""}


def app_cookie():
    """If the app has a PIN, log in once with it (read from .env on this Pi) and reuse the cookie."""
    pin = env_value("APP_PIN")
    if not pin or _cookie["v"]:
        return _cookie["v"]
    try:
        c = http.client.HTTPConnection(*APP, timeout=10)
        c.request("POST", "/api/login", json.dumps({"pin": pin}), {"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        m = re.search(r"pw_auth=([^;]+)", r.getheader("Set-Cookie") or "")
        _cookie["v"] = "pw_auth=" + m.group(1) if m else ""
    except Exception:
        pass
    return _cookie["v"]


# ------------------------------------------------------------------ update / logs (run on the Pi itself)
_job = {"running": False, "log": "", "ok": None, "t": 0}

UPDATE_SH = r'''
set -e
APP_DIR="$1"; CAM_DIR="$2"
echo "== Downloading the latest PrintView"
T=$(mktemp -d); cd "$T"
curl -fsSL https://github.com/wvfouram/printview/archive/refs/heads/main.tar.gz | tar xz
S="$T/printview-main"
echo "== Copying files"
for f in "$S"/app/*.py; do b=$(basename "$f"); [ "$b" = printer.py ] && continue; cp "$f" "$APP_DIR/app/$b"; done
cp -r "$S"/app/static "$APP_DIR/app/" 2>/dev/null || true
cp "$S"/camview/camview.py "$S"/camview/page.html "$S"/camview/second-slice.html "$S"/camview/slicer_bridge.js "$S"/camview/slicer_early.js "$CAM_DIR/"
mkdir -p "$HOME/pvadmin" && cp "$S"/pvadmin/*.py "$HOME/pvadmin/"
grep -q 'c 81:' "$APP_DIR/docker-compose.yml" || sed -i 's|      - "c 188:\* rmw".*|&\n      - "c 81:* rmw"              # video* (USB webcam)|' "$APP_DIR/docker-compose.yml"
grep -q 'c 116:' "$APP_DIR/docker-compose.yml" || sed -i 's|      - "c 81:\* rmw".*|&\n      - "c 116:* rmw"             # sound devices (USB webcam mic)|' "$APP_DIR/docker-compose.yml"
rm -rf "$T"
echo "== Rebuilding and restarting PrintView (a minute or two)"
cd "$APP_DIR" && docker compose up -d --build 2>&1 | grep -v "^ *=>" || true
echo "== Restarting the web link"
cd "$CAM_DIR" && docker compose restart 2>&1 || true
echo "== ALL DONE"
'''


def run_job(cmd):
    if _job["running"]:
        return False
    _job.update(running=True, log="", ok=None, t=time.time())

    def go():
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                _job["log"] = (_job["log"] + line)[-20000:]
            _job["ok"] = p.wait() == 0
        except Exception as e:  # noqa: BLE001
            _job["log"] += f"\nfailed: {e}"
            _job["ok"] = False
        finally:
            _job["running"] = False
            if _job["ok"] and "ALL DONE" in _job["log"] and cmd[-3:-2] == ["update"]:
                # the update may have brought a new version of this admin app: let systemd start it again
                threading.Timer(4, lambda: os._exit(0)).start()
    threading.Thread(target=go, daemon=True).start()
    return True


def docker_logs(name, n=200):
    try:
        r = subprocess.run(["docker", "logs", "--tail", str(n), name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=20)
        return r.stdout[-60000:]
    except Exception as e:  # noqa: BLE001
        return f"couldn't read logs: {e}"


PASS_REQ = ("Content-Type", "Range", "If-None-Match", "Accept-Encoding", "X-PW")
PASS_RESP = ("Content-Type", "Content-Disposition", "Content-Length", "Content-Encoding", "ETag",
             "Accept-Ranges", "Content-Range", "Cache-Control")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def js(self, code, obj):
        self.send(code, json.dumps(obj))

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def proxy(self, target, path, method):
        """Stream the request and the answer straight through (big uploads, video, live sound)."""
        c = http.client.HTTPConnection(*target, timeout=600)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            c.putrequest(method, path, skip_accept_encoding=True)
            for h in PASS_REQ:
                if self.headers.get(h):
                    c.putheader(h, self.headers[h])
            if target == APP and app_cookie():
                c.putheader("Cookie", app_cookie())
            if method == "POST":
                c.putheader("Content-Length", str(n))
            c.endheaders()
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                c.send(chunk)
                left -= len(chunk)
            r = c.getresponse()
        except Exception:
            return self.js(502, {"ok": False, "error": "PrintView isn't answering"})
        try:
            self.send_response(r.status)
            for h in PASS_RESP:
                if r.getheader(h):
                    self.send_header(h, r.getheader(h))
            if not r.getheader("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            c.close()

    def route(self, method):
        path, _, q = self.path.partition("?")
        full = path + ("?" + q if q else "")
        if path in ("/", "/index.html"):
            try:
                html = open(os.path.join(CAM_DIR, "page.html"), encoding="utf-8").read().replace("__BASE__", "")
            except OSError:
                return self.send(500, "page.html not found in " + CAM_DIR, "text/plain")
            html = html.replace("<script>\n\"use strict\";", "<script>window.PV_ADMIN = true;</script>\n<script>\n\"use strict\";", 1)
            html = html.replace("<title>PrintView</title>", "<title>PrintView Admin</title>", 1).replace("<h1>PrintView</h1>", "<h1>PrintView Admin</h1>", 1)
            return self.send(200, html, "text/html; charset=utf-8")
        if path in ("/slicer", "/slicer/"):
            return self.slicer()
        if path == "/me":
            return self.js(200, {"unlocked": True, "role": "master", "frozen": False})
        if path in ("/login", "/logout"):
            return self.js(200, {"ok": True, "role": "master"})
        if path == "/frame.jpg":
            return self.proxy(APP, "/snapshot.jpg", "GET")
        if path == "/frame2.jpg":
            return self.proxy(APP, "/cam2.jpg", "GET")
        if path.startswith("/admin/"):
            return self.proxy(OWNER, full, method)
        if path.startswith("/api/"):
            return self.proxy(APP, full, method)
        # ---- admin-app-only actions on the Pi itself
        if path == "/pvadmin/info":
            return self.js(200, {"app_dir": APP_DIR, "cam_dir": CAM_DIR, "job": {k: _job[k] for k in ("running", "ok", "t")}})
        if path == "/pvadmin/update" and method == "POST":
            ok = run_job(["bash", "-c", UPDATE_SH, "update", APP_DIR, CAM_DIR])
            return self.js(200 if ok else 409, {"ok": ok, "error": None if ok else "already running"})
        if path == "/pvadmin/restart" and method == "POST":
            ok = run_job(["bash", "-c", f'cd "{APP_DIR}" && docker compose restart && cd "{CAM_DIR}" && docker compose restart && echo "== ALL DONE"'])
            return self.js(200 if ok else 409, {"ok": ok})
        if path == "/pvadmin/job":
            return self.js(200, _job)
        if path == "/pvadmin/logs":
            name = "camview" if "camview" in q else "printwatch"
            return self.js(200, {"name": name, "text": docker_logs(name)})
        return self.send(404, "not found", "text/plain")

    def slicer(self):
        """The same in-browser slicer as the web link, with Send to printer."""
        try:
            html = open(os.path.join(CAM_DIR, "second-slice.html"), "rb").read()
            early = open(os.path.join(CAM_DIR, "slicer_early.js"), "rb").read()
            bridge = open(os.path.join(CAM_DIR, "slicer_bridge.js"), "rb").read()
        except OSError:
            return self.send(404, "The slicer files aren't in " + CAM_DIR + " yet. Run Update.", "text/plain")
        html = html.replace(b"setTimeout(() => { loadEngine().catch((e) => { status(e.message); }); }, 500);",
                            b"window.addEventListener('load', () => setTimeout(() => { loadEngine().catch((e) => { status(e.message); }); }, 500));")
        h = html.find(b"<head>")
        if h >= 0:
            html = html[:h + 6] + b"\n<script>\n" + early + b"\n</script>\n" + html[h + 6:]
        i = html.rfind(b"</body>")
        tail = b"<script>\n" + bridge + b"\n</script>\n"
        html = html[:i] + tail + html[i:] if i >= 0 else html + tail
        return self.send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print(f"PrintView Admin on http://127.0.0.1:{PORT}  (app: {APP_DIR}, web link: {CAM_DIR})", flush=True)
    Server(("127.0.0.1", PORT), H).serve_forever()
