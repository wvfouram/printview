"""PrintWatch: camera, controls and spaghetti detection for a Bambu P1S in LAN mode."""
import asyncio
import hashlib
import re
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from aiohttp import web

from .timelapse import Timelapse
from .hms import HMS
from .predict import Predictor
from .bedctl import BedControl
from .streams import STREAMS
from .camera import BambuCamera
from .dataset import Dataset
from .detector import DetectionLoop
from .printer import BambuPrinter
from . import sdcard as sd
from . import remote as rm
from .store import Events, Notifier, Settings
from .trainer import Trainer

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("printwatch")

STATIC = Path(__file__).parent / "static"


def env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"Missing {name} - set it in .env")
    return v


# ------------------------------------------------------------------ wiring
def build_app():
    ip = env("PRINTER_IP", required=True)
    serial = env("PRINTER_SERIAL", required=True).strip().upper()
    code = env("ACCESS_CODE", required=True).strip()
    data_dir = env("DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)

    camera = BambuCamera(ip, code, int(env("CAMERA_PORT", "6000")))
    printer = BambuPrinter(ip, serial, code, int(env("MQTT_PORT", "8883")))
    settings = Settings(os.path.join(data_dir, "settings.json"))
    events = Events(os.path.join(data_dir, "events.json"))
    notifier = Notifier(env("NTFY_URL"), env("NTFY_TOKEN"))
    card = sd.SDCard(ip, code, os.path.join(data_dir, "sdcache"))
    dataset = Dataset(data_dir, float(env("DATASET_MAX_GB", "3")))
    trainer = Trainer(dataset, os.path.join(data_dir, "custom_model.npz"), events)
    detector = DetectionLoop(env("MODEL_PATH", "/models/failure.onnx"),
                             camera, printer, settings, events, notifier, data_dir, dataset, trainer)

    def on_state(old, new, snap):
        detector.on_printer_state(old, new, snap.get("job") or "")
        if old is None:
            return  # first report after startup, not a real transition
        job = snap.get("job") or "Print"
        if new == "FINISH":
            events.add("done", f"Finished: {job}")
            if settings.get("notify_finish"):
                frame, _, _ = camera.latest()
                notifier.send("Print finished", job, tags="white_check_mark", image=frame)
        elif new == "FAILED":
            events.add("fail", f"Failed/stopped: {job}")
            if settings.get("notify_finish"):
                notifier.send("Print failed or stopped", job, priority="high", tags="x")
        elif new == "PAUSE":
            events.add("pause", "Paused")
        elif new == "RUNNING" and old == "PAUSE":
            events.add("resume", "Resumed")
        elif new == "RUNNING":
            events.add("start", f"Started: {job}")

    printer.on_change(on_state)

    app = web.Application(middlewares=[stream_middleware, remote_middleware, auth_middleware])
    app["remote_port"] = int(env("REMOTE_PORT", "8443")) if env("REMOTE", "on") != "off" else 0
    app["remote_host"] = (env("REMOTE_HOST") or "").strip()
    app["devices"] = rm.Devices(os.path.join(data_dir, "devices.json"))
    app["throttle"] = rm.Throttle()
    app["upnp"] = rm.UPnP(app["remote_port"]) if app["remote_port"] and env("UPNP", "on") != "off" else None
    if app["remote_port"]:
        app["cert"] = rm.ensure_cert(data_dir)
    app["hms"] = HMS(data_dir)
    app["predict"] = Predictor(printer, data_dir)
    app["timelapse"] = Timelapse(camera, printer, data_dir, events)
    app["bedctl"] = BedControl(printer, env("BED_PORT", "/dev/ttyACM0"), data_dir, env("BED_CONTROL", "on") != "off")
    app["camera"], app["printer"], app["settings"] = camera, printer, settings
    app["events"], app["notifier"], app["detector"] = events, notifier, detector
    app["dataset"], app["trainer"] = dataset, trainer
    app["sd"], app["job_hint"] = card, {}
    app["pin"] = (env("APP_PIN") or "").strip()
    app["secret"] = load_secret(data_dir)

    app.router.add_get("/", index)
    app.router.add_get("/login", login_page)
    app.router.add_post("/api/login", login)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/timelapse", api_tl_list)
    app.router.add_post("/api/timelapse/{tid}/render", api_tl_render)
    app.router.add_get("/api/timelapse/{tid}/timelapse.mp4", api_tl_video)
    app.router.add_get("/api/stream", api_stream)
    app.router.add_post("/api/cmd", api_cmd)
    app.router.add_post("/api/settings", api_settings)
    app.router.add_get("/snapshot.jpg", snapshot)
    app.router.add_get("/detection.jpg", detection_jpg)
    app.router.add_get("/stream.mjpg", mjpeg)
    app.router.add_post("/api/pair", api_pair)
    app.router.add_get("/api/remote", api_remote)
    app.router.add_post("/api/remote/forget", api_remote_forget)
    app.router.add_get("/api/ping", lambda r: web.json_response({"ok": True, "remote": bool(r.get("remote"))}))
    app.router.add_get("/api/files", api_files)
    app.router.add_post("/api/upload", api_upload)
    app.router.add_get("/api/files/download", api_file_download)
    app.router.add_post("/api/files/delete", api_file_delete)
    app.router.add_get("/api/files/info", api_file_info)
    app.router.add_get("/api/files/plate.png", api_file_plate)
    app.router.add_post("/api/print", api_print_start)
    app.router.add_get("/api/job", api_job)
    app.router.add_get("/api/job/plate.png", api_job_plate)
    app.router.add_get("/api/timelapses", api_timelapses)
    app.router.add_get("/api/timelapses/thumb", api_timelapse_thumb)
    app.router.add_get("/api/timelapses/download", api_timelapse_download)
    app.router.add_get("/api/pa", api_pa)
    app.router.add_post("/api/pa", api_pa_cmd)
    app.router.add_get("/api/streams", api_streams)
    app.router.add_get("/api/bed", api_bed)
    app.router.add_post("/api/bed/{what}", api_bed_cmd)
    app.router.add_get("/api/camview/{what}", api_camview)
    app.router.add_post("/api/camview/{what}", api_camview)
    app.router.add_get("/train", train_page)
    app.router.add_get("/api/train", api_train_status)
    app.router.add_post("/api/train", api_train_now)
    app.router.add_get("/api/prints", api_prints)
    app.router.add_get("/api/prints/{pid}", api_print)
    app.router.add_post("/api/prints/{pid}/label", api_label)
    app.router.add_post("/api/prints/{pid}/delete", api_delete)
    app.router.add_get("/api/prints/{pid}/frame/{i}", api_frame)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.router.add_get("/manifest.webmanifest", lambda r: web.FileResponse(
        STATIC / "manifest.webmanifest", headers={"Content-Type": "application/manifest+json"}))
    app.router.add_get("/sw.js", lambda r: web.FileResponse(
        STATIC / "sw.js", headers={"Content-Type": "text/javascript", "Cache-Control": "no-cache"}))

    async def on_startup(_):
        camera.start()
        printer.start()
        app["bedctl"].start()
        detector.start()
        if app["upnp"]:
            app["upnp"].start()
        log.info("PrintWatch up - printer %s (%s)", ip, serial[-4:].rjust(len(serial), "*"))

    app.on_startup.append(on_startup)
    return app


def load_secret(data_dir):
    p = os.path.join(data_dir, ".secret")
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        s = secrets.token_hex(32)
        with open(p, "w") as f:
            f.write(s)
        return s


# ------------------------------------------------------------------ auth (optional PIN)
OPEN_PATHS = ("/login", "/api/login", "/manifest.webmanifest", "/sw.js", "/static/")


def auth_token(app):
    return hmac.new(app["secret"].encode(), app["pin"].encode(), hashlib.sha256).hexdigest()


QUIET = ("/api/streams", "/snapshot.jpg", "/stream.mjpg", "/api/stream")   # not logged: the stream view itself, video


@web.middleware
async def stream_middleware(request, handler):
    """Log requests to the 'web' data stream: who (web link / phone / browser), what, result, time."""
    t0 = time.time()
    status = 500
    try:
        resp = await handler(request)
        status = resp.status
        return resp
    except web.HTTPException as e:
        status = e.status
        raise
    finally:
        if not request.path.startswith(QUIET):
            peer = request.remote or "?"
            who = "web link" if peer in ("127.0.0.1", "::1") and not request.get("remote") else \
                  "phone (away)" if request.get("remote") else "home " + peer
            STREAMS.add("web", f"{who} > Pi  {request.method} {request.path_qs[:120]}  -> {status}  {int((time.time() - t0) * 1000)} ms")


@web.middleware
async def remote_middleware(request, handler):
    """Requests on the remote (HTTPS) port must carry a paired device key."""
    app = request.app
    sock = request.transport.get_extra_info("sockname") if request.transport else None
    is_remote = bool(app["remote_port"] and sock and sock[1] == app["remote_port"])
    request["remote"] = is_remote
    if not is_remote:
        return await handler(request)
    ip = request.remote or "?"
    if ip in ("127.0.0.1", "::1"):  # via Tailscale Funnel: use the real caller
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or ip
    if app["throttle"].is_blocked(ip):
        raise web.HTTPForbidden(text="blocked")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.query.get("k", "")
    if not app["devices"].check(token):
        app["throttle"].fail(ip)
        raise web.HTTPUnauthorized(text="pair this phone on your home Wi-Fi first")
    if request.path in ("/api/pair", "/api/remote/forget"):
        raise web.HTTPForbidden(text="only from home Wi-Fi")
    return await handler(request)


@web.middleware
async def auth_middleware(request, handler):
    app = request.app
    if request.get("remote") or not app["pin"] or request.path.startswith(OPEN_PATHS):
        return await handler(request)
    if hmac.compare_digest(request.cookies.get("pw_auth", ""), auth_token(app)):
        return await handler(request)
    if request.path.startswith("/api/") or request.path.endswith((".jpg", ".mjpg")):
        raise web.HTTPUnauthorized()
    raise web.HTTPFound("/login")


async def login_page(request):
    return web.FileResponse(STATIC / "login.html")


async def login(request):
    app = request.app
    try:
        body = await request.json()
    except ValueError:
        body = {}
    await asyncio.sleep(0.4)  # slow down guessing
    if not app["pin"] or hmac.compare_digest(str(body.get("pin", "")), app["pin"]):
        resp = web.json_response({"ok": True})
        if app["pin"]:
            resp.set_cookie("pw_auth", auth_token(app), max_age=60 * 60 * 24 * 365,
                            httponly=True, samesite="Strict")
        return resp
    return web.json_response({"ok": False}, status=403)


# ------------------------------------------------------------------ pages / api
async def index(request):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def full_status(app):
    return {
        "t": int(time.time()),
        "printer": app["printer"].status(),
        "camera": app["camera"].status(),
        "detector": app["detector"].status(),
        "settings": app["settings"].data,
        "training": {"trained": app["trainer"].model is not None,
                     "summary": (app["trainer"].report or {}).get("message"),
                     "review": app["dataset"].counts()["review"]},
        "notify": app["notifier"].enabled,
        "events": app["events"].list(15),
        "bedctl": app["bedctl"].status(),
        "timelapse": app["timelapse"].status(),
        "hms": app["hms"].status(app["printer"]),
        "predict": app["predict"].status(),
    }


async def api_tl_list(request):
    tl = request.app["timelapse"]
    return web.json_response({"status": tl.status(), "items": tl.list()})


async def api_tl_render(request):
    if request.get("remote"):
        return web.json_response({"error": "not from the web link"}, status=403)
    ok = request.app["timelapse"].render(request.match_info["tid"])
    return web.json_response({"ok": ok}, status=200 if ok else 404)


async def api_tl_video(request):
    p = request.app["timelapse"].video_path(request.match_info["tid"])
    if not p:
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Content-Type": "video/mp4"})


async def api_status(request):
    return web.json_response(full_status(request.app))


async def api_stream(request):
    """Server-sent events: status every second."""
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    try:
        while True:
            await resp.write(f"data: {json.dumps(full_status(request.app))}\n\n".encode())
            await asyncio.sleep(1)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


COMMANDS = {
    "pause": lambda p, b: p.pause(),
    "resume": lambda p, b: p.resume(),
    "stop": lambda p, b: p.stop(),
    "light_on": lambda p, b: p.light(True),
    "light_off": lambda p, b: p.light(False),
    "refresh": lambda p, b: p.pushall(),
    "speed": lambda p, b: p.set_speed(b.get("level")),
    "fan": lambda p, b: p.set_fan(b.get("fan"), b.get("percent", 0)),
    "temp": lambda p, b: p.set_temp(b.get("target"), b.get("value", 0)),
    "home": lambda p, b: p.home(),
    "jog": lambda p, b: p.jog(str(b.get("axis", "")), b.get("mm", 0)),
    "motors_off": lambda p, b: p.motors_off(),
    "ams_load": lambda p, b: p.ams_load(b.get("tray")),
    "ams_unload": lambda p, b: p.ams_unload(),
    "ams_resume": lambda p, b: p.ams_control("resume"),
    "ams_reset": lambda p, b: p.ams_control("reset"),
    "gcode": lambda p, b: p.console(b.get("gcode", "")),
    "extrude": lambda p, b: p.extrude(b.get("mm", 0)),
    "skip": lambda p, b: p.skip_objects(b.get("objects") or []),
    "ams_setting": lambda p, b: p.ams_setting(b.get("slot"), str(b.get("type", "PLA")), str(b.get("color", "")),
                                              b.get("min", 190), b.get("max", 230), str(b.get("idx", ""))),
    "ams_rfid": lambda p, b: p.ams_read_rfid(b.get("slot")),
    "ams_dry": lambda p, b: p.ams_dry(b.get("unit", 129), bool(b.get("on", True)), str(b.get("filament", "PLA")),
                                      b.get("temp", 55), b.get("hours", 4), bool(b.get("rotate", True))),
    "ams_options": lambda p, b: p.ams_user_setting(b.get("startup_read"), b.get("tray_read"), b.get("remain_calc")),
    "option": lambda p, b: p.print_option(str(b.get("name")), b.get("value")),
    "calibrate": lambda p, b: p.calibrate(b.get("bed"), b.get("vibration"), b.get("motor")),
}
LOGGED = {"pause": "Pause", "resume": "Resume", "stop": "Stop", "speed": "Speed change", "home": "Home",
          "ams_load": "AMS load", "ams_unload": "AMS unload", "gcode": "G-code", "skip": "Skip objects",
          "calibrate": "Calibration", "ams_setting": "AMS slot setting", "ams_dry": "AMS drying"}


async def api_cmd(request):
    body = await request.json()
    action = body.get("action")
    if action not in COMMANDS:
        return web.json_response({"ok": False, "error": "unknown action"}, status=400)
    printer = request.app["printer"]
    if action == "stop" and body.get("confirm") != "STOP":
        return web.json_response({"ok": False, "error": "stop needs confirmation"}, status=400)
    if action == "gcode" and not str(body.get("gcode", "")).strip():
        return web.json_response({"ok": False, "error": "empty G-code"}, status=400)
    if action == "ams_unload" and printer.busy:
        return web.json_response({"ok": False, "error": "can't unload while printing"}, status=409)
    try:
        ok = COMMANDS[action](printer, body)
    except PermissionError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=409)
    except (ValueError, TypeError) as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    if action in LOGGED:
        detail = ""
        if action == "speed":
            detail = f": {['', 'Silent', 'Standard', 'Sport', 'Ludicrous'][int(body.get('level'))]}"
        elif action == "gcode":
            detail = f": {str(body.get('gcode', '')).strip().splitlines()[0][:40]}"
        request.app["events"].add("cmd", f"{LOGGED[action]}{detail} sent from app" if ok
                                  else f"{LOGGED[action]} failed: printer offline")
    return web.json_response({"ok": bool(ok), "error": None if ok else "printer not connected"},
                             status=200 if ok else 503)


async def api_settings(request):
    body = await request.json()
    return web.json_response(request.app["settings"].update(body))


async def snapshot(request):
    frame, fid, _ = request.app["camera"].latest()
    if not frame:
        raise web.HTTPServiceUnavailable(text="no camera frame yet")
    etag = f'"{fid}"'
    if request.headers.get("If-None-Match") == etag:
        raise web.HTTPNotModified()
    return web.Response(body=frame, content_type="image/jpeg",
                        headers={"Cache-Control": "no-cache", "ETag": etag})


async def detection_jpg(request):
    d = request.app["detector"]
    if not d.last_detection_jpeg:
        raise web.HTTPNotFound()
    return web.Response(body=d.last_detection_jpeg, content_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


async def mjpeg(request):
    """Standard MJPEG stream - works in browsers, VLC, Home Assistant, etc."""
    cam = request.app["camera"]
    boundary = "frame"
    resp = web.StreamResponse(headers={
        "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    last = -1
    try:
        while True:
            frame, fid, _ = cam.latest()
            if frame and fid != last:
                last = fid
                await resp.write(
                    f"--{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n".encode()
                    + frame + b"\r\n")
            await asyncio.sleep(0.1)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


# ------------------------------------------------------------------ training / labeling
async def train_page(request):
    return web.FileResponse(STATIC / "train.html", headers={"Cache-Control": "no-cache"})


async def api_train_status(request):
    return web.json_response(request.app["trainer"].status())


async def api_train_now(request):
    request.app["trainer"].start_now()
    await asyncio.sleep(0.2)
    return web.json_response(request.app["trainer"].status())


async def api_prints(request):
    ds = request.app["dataset"]
    out = []
    for m in ds.list():
        m = dict(m)
        m["thumb"] = None if m.get("frames_pruned") or not m["n"] else max(0, m["n"] // 2)
        out.append(m)
    return web.json_response(out)


async def api_print(request):
    ds = request.app["dataset"]
    pid = request.match_info["pid"]
    try:
        m = ds.meta(pid)
    except ValueError:
        raise web.HTTPBadRequest()
    if not m:
        raise web.HTTPNotFound()
    ticks = await asyncio.get_running_loop().run_in_executor(None, ds.ticks, pid)
    return web.json_response({"meta": m, "ticks": ticks})


async def api_label(request):
    body = await request.json()
    try:
        m = request.app["dataset"].set_label(request.match_info["pid"], body.get("label"), body.get("fail_start"))
    except KeyError:
        raise web.HTTPNotFound()
    except (ValueError, TypeError) as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": True, "meta": m})


async def api_delete(request):
    try:
        request.app["dataset"].delete(request.match_info["pid"])
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def api_frame(request):
    try:
        p = request.app["dataset"].frame_path(request.match_info["pid"], int(request.match_info["i"]))
    except ValueError:
        raise web.HTTPBadRequest()
    if not os.path.exists(p):
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "max-age=86400"})


# ------------------------------------------------------------------ pressure advance (K) per slot
async def api_pa(request):
    p = request.app["printer"]
    try:
        entries = await _run(p.pa_list)
    except Exception as e:  # noqa: BLE001
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    st = p.status()
    return web.json_response({"ok": True, "table": st.get("pa_table"), "nozzle": p._nozzle(), "entries": entries})


async def api_pa_cmd(request):
    b = await request.json()
    p = request.app["printer"]
    act = b.get("action")
    try:
        if act == "set":
            r = await _run(p.pa_set, int(b.get("slot")), float(b.get("k")), str(b.get("name") or ""))
            request.app["events"].add("cmd", f"K {r['k']:.3f} saved to slot {int(b.get('slot')) % 4 + 1 if int(b.get('slot')) != 254 else 'ext'}")
        elif act == "select":
            r = await _run(p.pa_select, int(b.get("slot")), int(b.get("cali_idx")), str(b.get("filament_id") or ""))
        elif act == "delete":
            r = await _run(p.pa_delete, int(b.get("cali_idx")), str(b.get("filament_id") or ""))
        else:
            return web.json_response({"ok": False, "error": "unknown action"}, status=400)
    except (ValueError, TypeError) as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:  # noqa: BLE001
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    return web.json_response({"ok": True, "result": r})


# ------------------------------------------------------------------ data streams (phone app)
async def api_streams(request):
    try:
        since = int(request.query.get("since", "0"))
    except ValueError:
        since = 0
    return web.json_response(STREAMS.since(since))


# ------------------------------------------------------------------ bed servo (Arduino) workaround
async def api_bed(request):
    b = request.app["bedctl"]
    return web.json_response({**b.status(), "log": b.log_lines()})


async def api_bed_cmd(request):
    """Test buttons and fault reset: home network page only (not the remote port, not the web link)."""
    if request.get("remote"):
        raise web.HTTPForbidden(text="home network only")
    b = request.app["bedctl"]
    what = request.match_info["what"]
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if what == "reset":
        b.reset()
    elif what == "test":
        try:
            b.test(str(body.get("mode", "")), float(body.get("seconds", 60)))
        except (ValueError, TypeError) as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
    else:
        raise web.HTTPNotFound()
    return web.json_response({"ok": True, **b.status()})


# ------------------------------------------------------------------ public web link (camview) command center
CAMVIEW_OWNER = os.environ.get("CAMVIEW_OWNER", "http://127.0.0.1:8091")


async def api_camview(request):
    """The phone app's command center for the public web link: freeze, change code, who's logged in.
    Forwards to camview's owner port, which only listens on the Pi itself."""
    import aiohttp
    what = request.match_info["what"]
    if what not in ("state", "freeze", "code", "kick", "exercise"):
        raise web.HTTPNotFound()
    data = await request.read() if request.method == "POST" else None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.request(request.method, f"{CAMVIEW_OWNER}/admin/{what}", data=data,
                                 headers={"Content-Type": "application/json"}) as r:
                return web.Response(body=await r.read(), status=r.status, content_type="application/json")
    except Exception:  # noqa: BLE001
        return web.json_response({"ok": False, "error": "The web link isn't running on the Pi"}, status=502)


# ------------------------------------------------------------------ SD card / jobs / timelapses
def _run(fn, *a):
    return asyncio.get_running_loop().run_in_executor(None, fn, *a)


def _sd_error(e):
    log.warning("sd card: %s", e)
    return web.json_response({"ok": False, "error": f"SD card: {e}"}, status=502)


UPLOAD_MAX = 500 * 1024 * 1024


async def api_upload(request):
    """Raw file body; ?name=part.gcode.3mf. Saved to the printer's SD card, ready in Print from SD."""
    name = os.path.basename((request.query.get("name") or "").replace("\\", "/")).strip()
    name = re.sub(r'[^\w .()+\-]', "_", name)[:120]
    if not re.search(r"\.(3mf|gcode)$", name, re.I):
        return web.json_response({"ok": False, "error": "Only .gcode.3mf, .3mf or .gcode files"}, status=400)
    tmpdir = os.path.join(env("DATA_DIR", "/data"), "uploads")
    os.makedirs(tmpdir, exist_ok=True)
    tmp = os.path.join(tmpdir, "incoming.part")
    size = 0
    try:
        with open(tmp, "wb") as out:
            async for chunk in request.content.iter_chunked(65536):
                size += len(chunk)
                if size > UPLOAD_MAX:
                    return web.json_response({"ok": False, "error": "File too big (500 MB max)"}, status=413)
                out.write(chunk)
        if size < 100:
            return web.json_response({"ok": False, "error": "Empty file"}, status=400)
        await _run(request.app["sd"].upload, tmp, name)
    except Exception as e:  # noqa: BLE001
        return web.json_response({"ok": False, "error": f"Upload failed: {e}"}, status=502)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    request.app["events"].add("cmd", f"Uploaded {name} ({size // 1024} KB)")
    return web.json_response({"ok": True, "name": name, "path": "/" + name, "size": size})


async def _known_file(app, path):
    files = await _run(app["sd"].models)
    return next((f for f in files if f["path"] == path), None)


async def api_file_download(request):
    path = request.query.get("path", "")
    try:
        f = await _known_file(request.app, path)
        if not f:
            raise web.HTTPNotFound()
        local = await _run(request.app["sd"].fetch, path, f.get("size"))
    except web.HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    return web.FileResponse(local, headers={"Content-Type": "application/octet-stream",
                                            "Content-Disposition": f'attachment; filename="{f["name"]}"'})


async def api_file_delete(request):
    b = await request.json()
    path = str(b.get("path") or "")
    if request.app["printer"].status().get("busy") and path.endswith(os.path.basename(request.app["printer"].status().get("file") or "\0")):
        return web.json_response({"ok": False, "error": "That file is printing right now"}, status=409)
    try:
        if not await _known_file(request.app, path):
            return web.json_response({"ok": False, "error": "File not found on the SD card"}, status=404)
        await _run(request.app["sd"].delete, path)
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    request.app["events"].add("cmd", f"Deleted {os.path.basename(path)} from the SD card")
    return web.json_response({"ok": True})


async def api_files(request):
    try:
        files = await _run(request.app["sd"].models, request.query.get("refresh") == "1")
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    return web.json_response(files)


async def _plates(app, path):
    local = await _run(app["sd"].fetch, path)
    return local, await _run(sd.parse_3mf, local)


async def api_file_info(request):
    path = request.query.get("path", "")
    try:
        _, plates = await _plates(request.app, path)
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    return web.json_response({"path": path, "plates": plates})


async def api_file_plate(request):
    path, idx = request.query.get("path", ""), int(request.query.get("plate", "1"))
    try:
        local, _ = await _plates(request.app, path)
        png = await _run(sd.plate_png, local, idx)
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    if not png:
        raise web.HTTPNotFound()
    return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=3600"})


async def api_print_start(request):
    b = await request.json()
    p = request.app["printer"]
    try:
        ok = p.start_print(str(b.get("path", "")), int(b.get("plate", 1)), b.get("ams_mapping") or [],
                           bool(b.get("use_ams", True)), bool(b.get("timelapse", False)),
                           bool(b.get("bed_leveling", True)), bool(b.get("flow_cali", True)),
                           bool(b.get("vibration_cali", True)))
    except PermissionError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=409)
    except (ValueError, TypeError) as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    if ok:
        request.app["job_hint"].update(path=b.get("path"), plate=int(b.get("plate", 1)), t=time.time())
        request.app["events"].add("cmd", f"Print started from app: {os.path.basename(str(b.get('path')))}")
    return web.json_response({"ok": bool(ok), "error": None if ok else "printer not connected"},
                             status=200 if ok else 503)


async def _current_job(app):
    """Find the running job's 3MF on the SD card so we can show its plate and objects."""
    st = app["printer"].status()
    job = (st.get("job") or "").strip()
    hint = app["job_hint"]
    path, plate = None, None
    if hint.get("path") and job and job in os.path.basename(hint["path"]):
        path, plate = hint["path"], hint.get("plate")
    if not path and job:
        files = await _run(app["sd"].models)
        for f in files:
            if f["title"] == job or f["name"] == job:
                path = f["path"]
                break
    if not path:
        return None
    local, plates = await _plates(app, path)
    m = re.search(r"plate_(\d+)", st.get("file") or "")
    if m:
        plate = int(m.group(1))
    sliced = [pl for pl in plates if pl["sliced"]]
    if plate is None and len(sliced) == 1:
        plate = sliced[0]["index"]
    pl = next((x for x in plates if x["index"] == plate), sliced[0] if sliced else None)
    return {"path": path, "local": local, "plate": pl, "skipped": st.get("skipped") or [], "job": job}


async def api_job(request):
    try:
        j = await _current_job(request.app)
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    if not j or not j["plate"]:
        return web.json_response({"found": False})
    pl = j["plate"]
    objs = [dict(o, skipped=o["id"] in j["skipped"]) for o in pl["objects"]]
    return web.json_response({"found": True, "path": j["path"], "plate": pl["index"], "objects": objs,
                              "filaments": pl["filaments"], "seconds": pl["seconds"], "weight_g": pl["weight_g"]})


async def api_job_plate(request):
    try:
        j = await _current_job(request.app)
        png = await _run(sd.plate_png, j["local"], j["plate"]["index"]) if j and j["plate"] else None
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    if not png:
        raise web.HTTPNotFound()
    return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=600"})


async def api_timelapses(request):
    try:
        vids = await _run(request.app["sd"].timelapses, request.query.get("refresh") == "1")
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    return web.json_response(vids)


def _sd_path_ok(path, prefix):
    return path.startswith(prefix) and ".." not in path


async def api_timelapse_thumb(request):
    path = request.query.get("path", "")
    if not _sd_path_ok(path, "/timelapse/"):
        raise web.HTTPBadRequest()
    try:
        data = await _run(request.app["sd"].read_small, path)
    except Exception as e:  # noqa: BLE001
        return _sd_error(e)
    return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


async def api_timelapse_download(request):
    path = request.query.get("path", "")
    if not _sd_path_ok(path, "/timelapse/"):
        raise web.HTTPBadRequest()
    size = next((v["size"] for v in await _run(request.app["sd"].timelapses) if v["path"] == path), None)
    name = os.path.basename(path)
    ctype = "video/mp4" if name.lower().endswith(".mp4") else "video/x-msvideo"
    resp = web.StreamResponse(headers={"Content-Type": ctype,
                                       "Content-Disposition": f'attachment; filename="{name}"'})
    if size:
        resp.content_length = size
    await resp.prepare(request)
    loop = asyncio.get_running_loop()
    q = asyncio.Queue(maxsize=32)
    cancelled = threading.Event()

    def chunk(data):
        if cancelled.is_set():
            raise ConnectionAbortedError("phone disconnected")
        asyncio.run_coroutine_threadsafe(asyncio.wait_for(q.put(data), 60), loop).result()

    def worker():
        try:
            request.app["sd"].stream(path, chunk)
        except Exception as e:  # noqa: BLE001
            log.info("timelapse transfer ended: %s", e)
        finally:
            if not cancelled.is_set():
                asyncio.run_coroutine_threadsafe(q.put(None), loop).result()

    fut = loop.run_in_executor(None, worker)
    try:
        while True:
            data = await q.get()
            if data is None:
                break
            await resp.write(data)
    except (ConnectionResetError, asyncio.CancelledError):
        cancelled.set()
        while not q.empty():
            q.get_nowait()
    await fut
    return resp


# ------------------------------------------------------------------ remote access
def _remote_info(app):
    up = app["upnp"]
    host = app["remote_host"] or (up.external_ip if up else None)
    return {"enabled": bool(app["remote_port"]), "port": app["remote_port"], "host": host,
            "fingerprint": app["cert"][2] if app["remote_port"] else None,
            "upnp": None if not up else {"mapped": up.mapped, "error": up.error, "external_ip": up.external_ip,
                                         "lan_ip": up.lan_ip},
            "cgnat": bool(host and rm.cgnat(host)),
            "devices": app["devices"].public()}


async def api_pair(request):
    """Give this phone a key for remote access. Only on the home network."""
    if request.get("remote") or not rm.is_private(request.remote or ""):
        raise web.HTTPForbidden(text="pair from your home Wi-Fi")
    app = request.app
    if not app["remote_port"]:
        return web.json_response({"ok": False, "error": "remote access is turned off on the Pi"}, status=400)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    token = app["devices"].pair(str(body.get("name", "phone")))
    app["events"].add("cmd", f"Phone paired for remote access: {str(body.get('name', 'phone'))[:30]}")
    return web.json_response({"ok": True, "token": token, **_remote_info(app)})


async def api_remote(request):
    info = _remote_info(request.app)
    if request.get("remote"):
        info.pop("devices", None)
    return web.json_response(info)


async def api_remote_forget(request):
    if request.get("remote") or not rm.is_private(request.remote or ""):
        raise web.HTTPForbidden()
    body = await request.json()
    request.app["devices"].remove(str(body.get("id", "")))
    return web.json_response({"ok": True})


def main():
    import ssl
    app = build_app()

    async def serve():
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, env("HOST", "0.0.0.0"), int(env("PORT", "8080"))).start()
        log.info("home network: http://<pi>:%s", env("PORT", "8080"))
        if app["remote_port"]:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(app["cert"][0], app["cert"][1])
            await web.TCPSite(runner, "0.0.0.0", app["remote_port"], ssl_context=ctx).start()
            log.info("remote access: https port %d (paired phones only), cert sha256 %s...",
                     app["remote_port"], app["cert"][2][:16])
        while True:
            await asyncio.sleep(3600)

    asyncio.run(serve())


if __name__ == "__main__":
    main()
