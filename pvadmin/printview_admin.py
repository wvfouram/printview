#!/usr/bin/env python3
"""PrintView Admin: a real desktop app for the Raspberry Pi (GTK 3).

Full owner control of PrintView from the Pi's own desktop, no codes needed (it only talks to PrintView on
this Pi, so whoever is logged in to the Pi is the admin):
  Live      camera, status, pause / resume / stop, light, speed, temperatures, start next in queue
  Queue     print queue (reorder, remove, start next) and scheduled prints (cancel)
  Files     the printer's SD card: download, delete, add to queue, refresh
  Videos    timelapses: play, redo, delete-free "add a video" from any folder on the Pi
  People    who's on the web link: kick anyone (master users too), kick everyone, freeze
  Codes     change the general and the master code
  System    Pi temperature / memory / disk, logs, restart, and one-button update from GitHub
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import http.client

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango  # noqa: E402

HOME = os.path.expanduser("~")
APP = "http://127.0.0.1:8080"
OWNER = "http://127.0.0.1:8091"
SPEEDS = ["Silent", "Standard", "Sport", "Ludicrous"]


def find_dirs():
    for app_dir, cam_dir in ((f"{HOME}/printwatch", f"{HOME}/camview"), (f"{HOME}/printview", f"{HOME}/printview/camview")):
        if os.path.isfile(os.path.join(app_dir, "docker-compose.yml")):
            return app_dir, cam_dir
    return f"{HOME}/printview", f"{HOME}/printview/camview"


APP_DIR, CAM_DIR = find_dirs()

CSS = b"""
window, .bg { background: #0b0c0e; color: #f2f0eb; }
headerbar { background: #141619; border-bottom: 1px solid #2a2e34; color: #f2f0eb; }
headerbar .title { font-weight: 700; }
stacksidebar, stacksidebar list { background: #101215; }
stacksidebar row { padding: 12px 18px; color: #9097a1; font-weight: 600; }
stacksidebar row:selected { background: #24282d; color: #f2f0eb; border-left: 3px solid #ffb224; }
.card { background: #141619; border: 1px solid #2a2e34; border-radius: 16px; padding: 16px; }
.h { color: #9097a1; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
.big { font-size: 46px; font-weight: 300; }
.mu { color: #9097a1; }
.ok { color: #34d399; } .bad { color: #ff5d55; } .ac { color: #ffb224; }
button { background: #1c1f23; color: #f2f0eb; border: 1px solid #353a41; border-radius: 10px; padding: 8px 14px; font-weight: 600; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none; background-image: none; }
button:hover { background: #24282d; }
button:disabled { opacity: .4; }
button.pri { background: #ffb224; color: #1a1206; border-color: transparent; }
button.go { background: #34d399; color: #06180f; border-color: transparent; }
button.danger { background: #2b1514; color: #ff5d55; border-color: rgba(255,93,85,0.3); }
entry, spinbutton, combobox button { background: #1c1f23; color: #f2f0eb; border: 1px solid #353a41; border-radius: 10px; }
progressbar trough { background: #24282d; min-height: 8px; border-radius: 99px; }
progressbar progress { background: #ffb224; min-height: 8px; border-radius: 99px; }
list, row { background: transparent; }
row { border-bottom: 1px solid #22262b; padding: 6px 4px; }
textview, textview text { background: #08090a; color: #cfd3d8; font-family: monospace; font-size: 11px; }
.cam { background: #000; border-radius: 14px; }
"""


# ------------------------------------------------------------------ talking to PrintView
_cookie = {"v": None}


def env_value(key):
    try:
        for line in open(os.path.join(APP_DIR, ".env")):
            k, _, v = line.strip().partition("=")
            if k == key:
                return v.strip()
    except OSError:
        pass
    return ""


def cookie():
    pin = env_value("APP_PIN")
    if not pin:
        return ""
    if _cookie["v"] is None:
        try:
            req = urllib.request.Request(APP + "/api/login", json.dumps({"pin": pin}).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                m = re.search(r"pw_auth=([^;]+)", r.headers.get("Set-Cookie") or "")
                _cookie["v"] = "pw_auth=" + m.group(1) if m else ""
        except Exception:
            _cookie["v"] = ""
    return _cookie["v"]


def call(path, body=None, base=APP, timeout=15, raw=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if base == APP and cookie():
        req.add_header("Cookie", cookie())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            return b if raw else json.loads(b or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        raise RuntimeError(msg or f"HTTP {e.code}")
    except urllib.error.URLError:
        raise RuntimeError("PrintView isn't answering")


def bg(fn, done=None, err=None):
    """Run fn() off the UI thread, then done(result) / err(message) on it."""
    def run():
        try:
            r = fn()
            if done:
                GLib.idle_add(done, r)
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(err or (lambda m: None), str(e))
    threading.Thread(target=run, daemon=True).start()


def mins(m):
    if m is None or m < 0:
        return "--"
    m = int(m)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def deg(v, t):
    if v is None:
        return "--"
    return f"{round(v)}°" + (f" / {round(t)}°" if t else "")


def clean(name):
    return re.sub(r"(?i)(\.gcode)?\.3mf$", "", os.path.basename(str(name or "")))


# ------------------------------------------------------------------ small UI helpers
def lab(text="", cls=None, xalign=0, wrap=False):
    w = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        w.set_line_wrap(True)
    for c in (cls or "").split():
        w.get_style_context().add_class(c)
    return w


def btn(text, cb, cls=None):
    b = Gtk.Button(label=text)
    for c in (cls or "").split():
        b.get_style_context().add_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def card(title=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.get_style_context().add_class("card")
    if title:
        box.pack_start(lab(title.upper(), "h"), False, False, 0)
    return box


def row(*widgets, spacing=8, expand_first=False):
    r = Gtk.Box(spacing=spacing)
    for i, w in enumerate(widgets):
        r.pack_start(w, expand_first and i == 0, expand_first and i == 0, 0)
    return r


def page():
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.set_border_width(18)
    sw.add(box)
    return sw, box


def clear(box):
    for c in box.get_children():
        box.remove(c)


class Admin(Gtk.Window):
    def __init__(self):
        super().__init__(title="PrintView Admin")
        self.set_default_size(1320, 860)
        self.status = None
        self.toast_id = None
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        hb = Gtk.HeaderBar(title="PrintView Admin", show_close_button=True)
        self.conn = lab("Connecting...", "mu")
        hb.pack_end(self.conn)
        hb.pack_end(btn("Open website", lambda: subprocess.Popen(["xdg-open", APP])))
        self.set_titlebar(hb)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main = Gtk.Box()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        side = Gtk.StackSidebar(stack=self.stack)
        side.set_size_request(190, -1)
        main.pack_start(side, False, False, 0)
        main.pack_start(self.stack, True, True, 0)
        outer.pack_start(main, True, True, 0)
        self.toastl = lab("", "ac")
        self.toastl.set_margin_top(6)
        self.toastl.set_margin_bottom(6)
        outer.pack_start(self.toastl, False, False, 0)
        self.add(outer)

        self.build_live()
        self.build_queue()
        self.build_files()
        self.build_videos()
        self.build_people()
        self.build_codes()
        self.build_system()
        self.stack.connect("notify::visible-child-name", lambda *_: self.on_page())

        self.cam_etag = None
        GLib.timeout_add(1500, self.poll_status)
        GLib.timeout_add(1000, self.poll_cam)
        self.poll_status()
        self.connect("destroy", Gtk.main_quit)

    # ---------------------------------------------------------------- shared
    def toast(self, msg, bad=False):
        self.toastl.set_text(msg)
        ctx = self.toastl.get_style_context()
        ctx.remove_class("bad" if not bad else "ac")
        ctx.add_class("bad" if bad else "ac")
        if self.toast_id:
            GLib.source_remove(self.toast_id)
        self.toast_id = GLib.timeout_add(5000, lambda: (self.toastl.set_text(""), setattr(self, "toast_id", None))[0] or False)

    def act(self, fn, ok_msg=None, then=None):
        bg(fn, lambda r: (ok_msg and self.toast(ok_msg), then and then(r)), lambda m: self.toast(m, True))

    def confirm(self, title, text, yes, fn, danger=False):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=title)
        d.format_secondary_text(text)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        b = d.add_button(yes, Gtk.ResponseType.OK)
        b.get_style_context().add_class("danger" if danger else "pri")
        if d.run() == Gtk.ResponseType.OK:
            fn()
        d.destroy()

    def cmd(self, action, extra=None, msg="Sent"):
        body = {"action": action}
        body.update(extra or {})
        self.act(lambda: call("/api/cmd", body), msg)

    def on_page(self):
        name = self.stack.get_visible_child_name()
        loaders = {"queue": self.load_queue, "files": self.load_files, "videos": self.load_videos,
                   "people": self.load_people, "system": self.load_system}
        if name in loaders:
            loaders[name]()

    # ---------------------------------------------------------------- Live
    def build_live(self):
        sw, box = page()
        top = Gtk.Box(spacing=16)
        self.cam = Gtk.Image()
        self.cam.get_style_context().add_class("cam")
        self.cam.set_size_request(760, 428)
        camf = Gtk.EventBox()
        camf.add(self.cam)
        top.pack_start(camf, False, False, 0)

        st = card()
        self.l_state = lab("--", "ac")
        self.l_job = lab("No active print", "mu")
        self.l_job.set_ellipsize(Pango.EllipsizeMode.END)
        self.l_pct = lab("--%", "big")
        self.pbar = Gtk.ProgressBar()
        self.l_left = lab("--")
        self.l_eta = lab("", "mu")
        self.l_layer = lab("Layer --")
        self.l_noz = lab("Nozzle --")
        self.l_bed = lab("Bed --")
        self.l_watch = lab("", "mu")
        for w in (self.l_state, self.l_job, self.l_pct, self.pbar, row(self.l_left, self.l_eta), self.l_layer, self.l_noz, self.l_bed, self.l_watch):
            st.pack_start(w, False, False, 0)
        self.b_pause = btn("Pause", self.toggle_pause, "pri")
        self.b_stop = btn("Stop", lambda: self.confirm("Stop this print?", "It can't be resumed.", "Stop print",
                                                       lambda: self.cmd("stop", {"confirm": "STOP"}, "Stopping..."), True), "danger")
        st.pack_start(row(self.b_pause, self.b_stop), False, False, 4)
        self.b_next = btn("Start next", self.start_next, "go")
        self.b_next.set_no_show_all(True)
        st.pack_start(self.b_next, False, False, 0)
        top.pack_start(st, True, True, 0)
        box.pack_start(top, False, False, 0)

        ctl = card("Controls")
        self.b_light = btn("Light", lambda: self.cmd("light_off" if (self.status or {}).get("printer", {}).get("light") else "light_on", None, "Light"))
        sp = Gtk.Box(spacing=6)
        self.speed_btns = []
        for i, n in enumerate(SPEEDS):
            b = btn(n, (lambda lv=i + 1, nn=n: self.cmd("speed", {"level": lv}, "Speed: " + nn)))
            self.speed_btns.append(b)
            sp.pack_start(b, False, False, 0)
        ctl.pack_start(row(self.b_light, lab("   Speed", "mu"), sp), False, False, 0)
        self.sp_noz = Gtk.SpinButton.new_with_range(0, 300, 5)
        self.sp_bed = Gtk.SpinButton.new_with_range(0, 110, 5)
        ctl.pack_start(row(lab("Nozzle", "mu"), self.sp_noz, btn("Set", lambda: self.cmd("temp", {"target": "nozzle", "value": int(self.sp_noz.get_value())}, "Nozzle set"), "pri"),
                           lab("    Bed", "mu"), self.sp_bed, btn("Set", lambda: self.cmd("temp", {"target": "bed", "value": int(self.sp_bed.get_value())}, "Bed set"), "pri"),
                           btn("Cool down", lambda: (self.cmd("temp", {"target": "nozzle", "value": 0}, "Cooling"), self.cmd("temp", {"target": "bed", "value": 0}, "Cooling")), "danger")),
                       False, False, 0)
        box.pack_start(ctl, False, False, 0)
        self.stack.add_titled(sw, "live", "Live")
        self.temps_set = False

    def toggle_pause(self):
        st = ((self.status or {}).get("printer") or {}).get("state")
        self.cmd("resume" if st == "PAUSE" else "pause", None, "Resuming..." if st == "PAUSE" else "Pausing...")

    def start_next(self):
        q = (self.status or {}).get("queue") or {}
        nx = q.get("next")
        if not nx:
            return
        self.confirm("Start the next print?", clean(nx["name"]) + "\n\nMake sure the plate is clear.", "Start",
                     lambda: self.act(lambda: call("/api/queue/next", {}), "Starting " + clean(nx["name"])))

    def poll_cam(self):
        if self.stack.get_visible_child_name() != "live" or not self.is_visible():
            return True

        def get():
            req = urllib.request.Request(APP + "/snapshot.jpg")
            if self.cam_etag:
                req.add_header("If-None-Match", self.cam_etag)
            if cookie():
                req.add_header("Cookie", cookie())
            try:
                with urllib.request.urlopen(req, timeout=6) as r:
                    return r.read(), r.headers.get("ETag")
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return None, self.cam_etag
                raise

        def show(res):
            data, etag = res
            self.cam_etag = etag
            if data:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
                w = max(320, self.cam.get_allocated_width())
                self.cam.set_from_pixbuf(pb.scale_simple(w, int(w * pb.get_height() / pb.get_width()), GdkPixbuf.InterpType.BILINEAR))
        bg(get, show)
        return True

    def poll_status(self):
        bg(lambda: call("/api/status", timeout=6), self.render, lambda m: (self.conn.set_text("● " + m), self.conn.get_style_context().add_class("bad")))
        return True

    def render(self, s):
        self.status = s
        nm = (s.get("name") or "").strip()
        self.get_titlebar().set_title((nm + " Admin") if nm else "PrintView Admin")
        p = s.get("printer") or {}
        ok = p.get("connected")
        self.conn.set_text("● Connected" if ok else "● Printer offline")
        ctx = self.conn.get_style_context()
        ctx.remove_class("bad" if ok else "ok")
        ctx.add_class("ok" if ok else "bad")
        state = p.get("state") or "--"
        act = state in ("RUNNING", "PAUSE", "PREPARE")
        self.l_state.set_text({"RUNNING": "PRINTING", "PAUSE": "PAUSED", "PREPARE": "PREPARING", "FINISH": "FINISHED", "FAILED": "STOPPED"}.get(state, state))
        self.l_job.set_text(p.get("job") or ("Print" if act else "No active print"))
        has = p.get("percent") is not None and state != "IDLE"
        self.l_pct.set_text(f"{p.get('percent')}%" if has else "--%")
        self.pbar.set_fraction((p.get("percent") or 0) / 100 if has else 0)
        pr = s.get("predict") or {}
        self.l_left.set_text((mins(pr.get("remaining_min") or p.get("remaining_min")) + " left") if act else "")
        self.l_eta.set_text(("   done at " + time.strftime("%-I:%M %p", time.localtime(pr["done_at"]))) if act and pr.get("done_at") else "")
        self.l_layer.set_text(f"Layer {p.get('layer')} / {p.get('total_layers')}" if p.get("total_layers") else "Layer --")
        self.l_noz.set_text("Nozzle " + deg(p.get("nozzle"), p.get("nozzle_target")))
        self.l_bed.set_text("Bed " + deg(p.get("bed"), p.get("bed_target")))
        d = s.get("detector") or {}
        self.l_watch.set_text("Spaghetti watch: " + ("off" if not d.get("enabled") else "failure flagged" if d.get("acted") else "watching" if state == "RUNNING" else "idle"))
        self.b_pause.set_label("Resume" if state == "PAUSE" else "Pause")
        self.b_pause.set_sensitive(bool(ok) and state in ("RUNNING", "PAUSE"))
        self.b_stop.set_sensitive(bool(ok) and act)
        self.b_light.set_label("Light: on" if p.get("light") else "Light: off")
        for i, b in enumerate(self.speed_btns):
            c = b.get_style_context()
            (c.add_class if p.get("speed_level") == i + 1 else c.remove_class)("pri")
        if not self.temps_set and p.get("nozzle_target") is not None:
            self.sp_noz.set_value(p.get("nozzle_target") or 0)
            self.sp_bed.set_value(p.get("bed_target") or 0)
            self.temps_set = True
        q = s.get("queue") or {}
        free = ok and state in ("IDLE", "FINISH", "FAILED")
        if q.get("next") and free:
            self.b_next.set_label("Start next: " + clean(q["next"]["name"]) + (f"  (+{q['count'] - 1} more)" if q.get("count", 0) > 1 else ""))
            self.b_next.show()
        else:
            self.b_next.hide()
        if self.stack.get_visible_child_name() == "queue" and q.get("count") != getattr(self, "_qc", None):
            self._qc = q.get("count")
            self.load_queue()
        return False

    # ---------------------------------------------------------------- Queue
    def build_queue(self):
        sw, box = page()
        c = card("Print queue")
        c.pack_start(lab("Add files in the Files page (or on the website). Nothing starts by itself.", "mu", wrap=True), False, False, 0)
        self.qbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c.pack_start(self.qbox, False, False, 0)
        c.pack_start(row(btn("Start next", self.start_next, "go"), btn("Refresh", self.load_queue)), False, False, 0)
        box.pack_start(c, False, False, 0)
        s = card("Scheduled prints")
        self.sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        s.pack_start(self.sbox, False, False, 0)
        box.pack_start(s, False, False, 0)
        self.stack.add_titled(sw, "queue", "Queue")

    def load_queue(self):
        def show(r):
            q, sch = r
            clear(self.qbox)
            items = q.get("items") or []
            if not items:
                self.qbox.pack_start(lab("The queue is empty.", "mu"), False, False, 0)
            for i, x in enumerate(items):
                up = btn("↑", lambda xid=x["id"]: self.act(lambda: call(f"/api/queue/{xid}/move", {"delta": -1}), then=lambda _: self.load_queue()))
                dn = btn("↓", lambda xid=x["id"]: self.act(lambda: call(f"/api/queue/{xid}/move", {"delta": 1}), then=lambda _: self.load_queue()))
                up.set_sensitive(i > 0)
                dn.set_sensitive(i < len(items) - 1)
                rm = btn("Remove", lambda xid=x["id"]: self.act(lambda: call(f"/api/queue/{xid}/remove", {}), "Removed", lambda _: self.load_queue()), "danger")
                sp = x["body"].get("speed")
                self.qbox.pack_start(row(lab(f"{i + 1}.  {clean(x['name'])}   ·   plate {x['plate']}" + (f"   ·   {SPEEDS[sp - 1]}" if sp and sp != 2 else "")), up, dn, rm, expand_first=True), False, False, 0)
            clear(self.sbox)
            jobs = [j for j in (sch.get("items") or []) if j["status"] == "waiting" or time.time() - (j.get("done") or j["at"]) < 86400]
            if not jobs:
                self.sbox.pack_start(lab("Nothing scheduled.", "mu"), False, False, 0)
            for j in jobs:
                when = time.strftime("%a %b %-d, %-I:%M %p", time.localtime(j["at"]))
                w = [lab(f"{clean(j['name'])}   ·   {when}   ·   {j['status']}" + (f"  ({j['msg']})" if j.get("msg") else ""))]
                if j["status"] == "waiting":
                    w.append(btn("Cancel", lambda jid=j["id"]: self.act(lambda: call(f"/api/schedule/{jid}/cancel", {}), "Cancelled", lambda _: self.load_queue()), "danger"))
                self.sbox.pack_start(row(*w, expand_first=True), False, False, 0)
            self.qbox.show_all()
            self.sbox.show_all()
        bg(lambda: (call("/api/queue"), call("/api/schedule")), show, lambda m: self.toast(m, True))

    # ---------------------------------------------------------------- Files
    def build_files(self):
        sw, box = page()
        c = card("Files on the printer's SD card")
        c.pack_start(row(btn("Refresh", lambda: self.load_files(True)), lab("  To pick filaments for a multi-color print, use the website.", "mu")), False, False, 0)
        self.fbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c.pack_start(self.fbox, False, False, 0)
        box.pack_start(c, False, False, 0)
        self.stack.add_titled(sw, "files", "Files")

    def load_files(self, refresh=False):
        def show(r):
            clear(self.fbox)
            files = r if isinstance(r, list) else r.get("list") or []
            if not files:
                self.fbox.pack_start(lab("No sliced files on the SD card.", "mu"), False, False, 0)
            for f in files:
                q = btn("Add to queue", lambda ff=f: self.act(lambda: call("/api/queue", {"path": ff["path"], "plate": 1, "use_ams": True, "ams_mapping": [],
                                                                                           "timelapse": False, "bed_leveling": True, "flow_cali": False,
                                                                                           "vibration_cali": True}), "Added to the queue"))
                dl = btn("Download", lambda ff=f: self.download(ff))
                de = btn("Delete", lambda ff=f: self.confirm("Delete " + ff["title"] + "?", "It's removed from the SD card (a copy is kept on the Pi).", "Delete",
                                                            lambda: self.act(lambda: call("/api/files/delete", {"path": ff["path"]}), "Deleted", lambda _: self.load_files(True)), True), "danger")
                l = lab(f"{f['title']}\n{f.get('date', '')}   ·   {f['size'] / 1e6:.1f} MB")
                l.set_ellipsize(Pango.EllipsizeMode.END)
                self.fbox.pack_start(row(l, q, dl, de, expand_first=True), False, False, 0)
            self.fbox.show_all()
        self.toast("Reading the SD card...")
        bg(lambda: call("/api/files" + ("?refresh=1" if refresh else ""), timeout=90), show, lambda m: self.toast(m, True))

    def download(self, f):
        d = Gtk.FileChooserDialog(title="Save file", parent=self, action=Gtk.FileChooserAction.SAVE)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        d.set_current_name(os.path.basename(f["path"]))
        d.set_current_folder(os.path.join(HOME, "Downloads") if os.path.isdir(os.path.join(HOME, "Downloads")) else HOME)
        if d.run() == Gtk.ResponseType.OK:
            dest = d.get_filename()

            def get():
                req = urllib.request.Request(APP + "/api/files/download?path=" + urllib.parse.quote(f["path"]))
                if cookie():
                    req.add_header("Cookie", cookie())
                with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as out:
                    shutil.copyfileobj(r, out, 1 << 20)
                return dest
            self.toast("Downloading " + f["title"] + "...")
            bg(get, lambda p: self.toast("Saved to " + p), lambda m: self.toast(m, True))
        d.destroy()

    # ---------------------------------------------------------------- Videos
    def build_videos(self):
        sw, box = page()
        c = card("Timelapses made by the Pi")
        self.vprog = Gtk.ProgressBar()
        self.vprog.set_no_show_all(True)
        c.pack_start(row(btn("Add a video from this Pi...", self.add_video, "pri"), btn("Refresh", self.load_videos)), False, False, 0)
        c.pack_start(self.vprog, False, False, 0)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c.pack_start(self.vbox, False, False, 0)
        box.pack_start(c, False, False, 0)
        self.stack.add_titled(sw, "videos", "Videos")

    def load_videos(self):
        def show(r):
            clear(self.vbox)
            items = r.get("items") or []
            if not items:
                self.vbox.pack_start(lab("No timelapses yet.", "mu"), False, False, 0)
            busy = False
            for x in items:
                when = time.strftime("%b %-d, %-I:%M %p", time.localtime(x.get("t") or 0))
                info = f"{clean(x.get('job') or x['id'])}\n{when}   ·   " + (f"{x['frames']} layers" if x.get("frames") else "added video") + (f"   ·   {x['mb']} MB" if x.get("mb") else "")
                w = [lab(info)]
                if x.get("rendering"):
                    pr = x.get("progress") or {}
                    w.append(lab(f"Making video {round(pr.get('pct') or 0)}%", "ac"))
                    busy = True
                elif x.get("queued"):
                    w.append(lab("Queued", "mu"))
                    busy = True
                elif x.get("video"):
                    w.append(btn("Play", lambda xid=x["id"]: self.play(xid)))
                    w.append(btn("Save a copy...", lambda xx=x: self.save_video(xx)))
                if x.get("frames") and not x.get("rendering") and not x.get("queued"):
                    w.append(btn("Redo" if x.get("video") else "Make video", lambda xid=x["id"]: self.act(lambda: call(f"/api/timelapse/{xid}/render", {}), "Making the video...", lambda _: self.load_videos())))
                self.vbox.pack_start(row(*w, expand_first=True), False, False, 0)
            self.vbox.show_all()
            if busy and self.stack.get_visible_child_name() == "videos":
                GLib.timeout_add(4000, lambda: (self.load_videos(), False)[1])
        bg(lambda: call("/api/timelapse"), show, lambda m: self.toast(m, True))

    def video_file(self, tid):
        return os.path.join(APP_DIR, "data", "timelapse", tid, "timelapse.mp4")

    def play(self, tid):
        p = self.video_file(tid)
        if os.access(p, os.R_OK):
            subprocess.Popen(["xdg-open", p])
        else:
            subprocess.Popen(["xdg-open", f"{APP}/api/timelapse/{tid}/timelapse.mp4"])

    def save_video(self, x):
        d = Gtk.FileChooserDialog(title="Save video", parent=self, action=Gtk.FileChooserAction.SAVE)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        d.set_current_name(clean(x.get("job") or x["id"]) + ".mp4")
        d.set_current_folder(os.path.join(HOME, "Videos") if os.path.isdir(os.path.join(HOME, "Videos")) else HOME)
        if d.run() == Gtk.ResponseType.OK:
            dest = d.get_filename()
            self.act(lambda: shutil.copyfile(self.video_file(x["id"]), dest), "Saved to " + dest)
        d.destroy()

    def add_video(self):
        d = Gtk.FileChooserDialog(title="Pick a video", parent=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        flt = Gtk.FileFilter()
        flt.set_name("Videos (.mp4, .mov, .m4v)")
        for pat in ("*.mp4", "*.MP4", "*.mov", "*.MOV", "*.m4v"):
            flt.add_pattern(pat)
        d.add_filter(flt)
        d.set_current_folder(HOME)
        path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
        d.destroy()
        if not path:
            return
        size = os.path.getsize(path)
        self.vprog.show()
        self.vprog.set_fraction(0)

        def up():
            c = http.client.HTTPConnection("127.0.0.1", 8080, timeout=600)
            c.putrequest("POST", "/api/timelapse/import?name=" + urllib.parse.quote(os.path.basename(path)))
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(size))
            if cookie():
                c.putheader("Cookie", cookie())
            c.endheaders()
            sent = 0
            with open(path, "rb") as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    c.send(b)
                    sent += len(b)
                    GLib.idle_add(self.vprog.set_fraction, sent / max(1, size))
            r = c.getresponse()
            j = json.loads(r.read() or b"{}")
            if r.status != 200 or not j.get("ok"):
                raise RuntimeError(j.get("error") or f"HTTP {r.status}")
            return j

        def done(j):
            self.vprog.hide()
            self.toast(f"Added {j['name']} ({j['mb']} MB)")
            self.load_videos()
        bg(up, done, lambda m: (self.vprog.hide(), self.toast("Couldn't add it: " + m, True)))

    # ---------------------------------------------------------------- People
    def build_people(self):
        sw, box = page()
        c = card("Who's logged in on the web link")
        self.frz = Gtk.Switch()
        self.frz.connect("notify::active", lambda s, *_: None if self._frz_set else self.act(lambda: call("/admin/freeze", {"frozen": s.get_active()}, OWNER),
                                                                                        "Frozen" if s.get_active() else "Unfrozen"))
        self._frz_set = False
        c.pack_start(row(lab("Freeze everyone on the general code (view only)"), self.frz, expand_first=True), False, False, 0)
        c.pack_start(row(btn("Kick everyone on the general code", lambda: self.kick_all("general"), "danger"),
                         btn("Kick everyone on the master code", lambda: self.kick_all("master"), "danger"),
                         btn("Kick everyone", lambda: self.kick_all("all"), "danger")), False, False, 0)
        self.pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c.pack_start(self.pbox, False, False, 0)
        c.pack_start(btn("Refresh", self.load_people), False, False, 0)
        box.pack_start(c, False, False, 0)
        self.stack.add_titled(sw, "people", "People")

    def kick_all(self, role):
        what = {"general": "everyone on the general code", "master": "everyone on the master code", "all": "everyone"}[role]
        self.confirm("Kick " + what + "?", "They're logged out of the web link right away.", "Kick",
                     lambda: self.act(lambda: call("/admin/kick_all", {"role": role}, OWNER), "Kicked " + what, lambda _: self.load_people()), True)

    def load_people(self):
        def show(r):
            self._frz_set = True
            self.frz.set_active(bool(r.get("frozen")))
            self._frz_set = False
            clear(self.pbox)
            rows = r.get("sessions") or []
            if not rows:
                self.pbox.pack_start(lab("Nobody is logged in.", "mu"), False, False, 0)
            for x in rows:
                seen = x.get("seen_s", 0)
                seen_t = "now" if seen < 60 else f"{seen // 60} min ago" if seen < 3600 else f"{seen // 3600} h ago"
                l = lab(f"{x['role'].upper()}   ·   {x.get('device') or '?'}   ·   {x.get('ip') or ''}   ·   seen {seen_t}")
                if x["role"] == "master":
                    l.get_style_context().add_class("ac")
                k = btn("Kick", lambda sid=x["id"]: self.act(lambda: call("/admin/kick", {"id": sid}, OWNER), "Kicked", lambda _: self.load_people()), "danger")
                self.pbox.pack_start(row(l, k, expand_first=True), False, False, 0)
            self.pbox.show_all()
        bg(lambda: call("/admin/state", base=OWNER), show, lambda m: self.toast(m, True))

    # ---------------------------------------------------------------- Codes
    def build_codes(self):
        sw, box = page()
        c = card("Web link codes")
        c.pack_start(lab("Changing a code logs out everyone who's using the old one.", "mu"), False, False, 0)
        self.e_gen = Gtk.Entry(placeholder_text="New general code (4 to 32 letters or numbers)")
        self.e_mas = Gtk.Entry(placeholder_text="New master code (4 to 32 letters, numbers, _ or -)")
        c.pack_start(row(lab("General code   "), self.e_gen, btn("Change", lambda: self.set_code("/admin/code", self.e_gen, "General code changed"), "pri"), expand_first=False), False, False, 0)
        c.pack_start(row(lab("Master code     "), self.e_mas, btn("Change", lambda: self.set_code("/admin/master_code", self.e_mas, "Master code changed"), "pri")), False, False, 0)
        self.e_gen.set_width_chars(36)
        self.e_mas.set_width_chars(36)
        box.pack_start(c, False, False, 0)
        self.stack.add_titled(sw, "codes", "Codes")

    def set_code(self, path, entry, msg):
        code = entry.get_text().strip()
        if not code:
            return self.toast("Type the new code first", True)
        self.act(lambda: call(path, {"code": code}, OWNER), msg, lambda _: entry.set_text(""))

    # ---------------------------------------------------------------- System
    def build_system(self):
        sw, box = page()
        c = card("This Pi")
        self.l_pi = lab("", wrap=True)
        c.pack_start(self.l_pi, False, False, 0)
        box.pack_start(c, False, False, 0)
        u = card("Update and restart")
        u.pack_start(lab("Update downloads the newest PrintView from GitHub and restarts it (a minute or two). "
                         "Wait for any timelapse video being made to finish first. Your printer.py settings are kept.", "mu", wrap=True), False, False, 0)
        self.b_upd = btn("Update PrintView", lambda: self.confirm("Update PrintView?", "It restarts when done.", "Update", self.update), "pri")
        self.b_rst = btn("Restart PrintView", lambda: self.confirm("Restart PrintView?", "Takes about 15 seconds.", "Restart", self.restart))
        u.pack_start(row(self.b_upd, self.b_rst, btn("PrintView logs", lambda: self.logs("printwatch")), btn("Web link logs", lambda: self.logs("camview"))), False, False, 0)
        self.tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        tsw = Gtk.ScrolledWindow()
        tsw.set_size_request(-1, 360)
        tsw.add(self.tv)
        u.pack_start(tsw, True, True, 0)
        box.pack_start(u, True, True, 0)
        self.stack.add_titled(sw, "system", "System")

    def load_system(self):
        def info():
            t = "--"
            try:
                t = f"{int(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000:.1f} °C"
            except Exception:
                pass
            mem = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) // 1024
            du = shutil.disk_usage(os.path.join(APP_DIR, "data") if os.path.isdir(os.path.join(APP_DIR, "data")) else HOME)
            up = float(open("/proc/uptime").read().split()[0])
            dk = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}: {{.Status}}"], capture_output=True, text=True, timeout=10).stdout
            dk = "\n".join(l for l in dk.splitlines() if l.split(":")[0] in ("printwatch", "camview"))
            return (f"CPU temperature: {t}\nMemory: {mem['MemTotal'] - mem['MemAvailable']} MB used of {mem['MemTotal']} MB\n"
                    f"Storage: {du.free / 1e9:.0f} GB free of {du.total / 1e9:.0f} GB\nUp for {int(up // 86400)} days {int(up % 86400 // 3600)} h\n\n{dk}\n\n"
                    f"PrintView folder: {APP_DIR}\nWeb link folder: {CAM_DIR}")
        bg(info, self.l_pi.set_text, lambda m: self.l_pi.set_text(m))

    def logs(self, name):
        bg(lambda: subprocess.run(["docker", "logs", "--tail", "300", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20).stdout,
           self.show_text, lambda m: self.show_text("Couldn't read logs: " + m))

    def show_text(self, text):
        self.tv.get_buffer().set_text(text)
        GLib.idle_add(lambda: self.tv.scroll_to_iter(self.tv.get_buffer().get_end_iter(), 0, False, 0, 1) and False)

    def run_script(self, script, *args):
        self.b_upd.set_sensitive(False)
        self.b_rst.set_sensitive(False)
        self.show_text("")

        def go():
            p = subprocess.Popen(["bash", "-c", script, "pv", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                GLib.idle_add(self.append, line)
            return p.wait()

        def done(code):
            self.b_upd.set_sensitive(True)
            self.b_rst.set_sensitive(True)
            self.toast("Done" if code == 0 else "Something went wrong, see the log", code != 0)
            self.load_system()
        bg(go, done)

    def append(self, line):
        b = self.tv.get_buffer()
        b.insert(b.get_end_iter(), line)
        self.tv.scroll_to_iter(b.get_end_iter(), 0, False, 0, 1)
        return False

    def update(self):
        self.run_script(UPDATE_SH, APP_DIR, CAM_DIR)

    def restart(self):
        self.run_script('cd "$1" && docker compose restart && cd "$2" && docker compose restart && echo "== ALL DONE"', APP_DIR, CAM_DIR)


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
cp "$S"/camview/camview.py "$S"/camview/page.html "$CAM_DIR/"
mkdir -p "$HOME/pvadmin" && cp "$S"/pvadmin/*.py "$HOME/pvadmin/"
grep -q 'c 81:' "$APP_DIR/docker-compose.yml" || sed -i 's|      - "c 188:\* rmw".*|&\n      - "c 81:* rmw"              # video* (USB webcam)|' "$APP_DIR/docker-compose.yml"
grep -q 'c 116:' "$APP_DIR/docker-compose.yml" || sed -i 's|      - "c 81:\* rmw".*|&\n      - "c 116:* rmw"             # sound devices (USB webcam mic)|' "$APP_DIR/docker-compose.yml"
rm -rf "$T"
echo "== Rebuilding and restarting PrintView (a minute or two)"
cd "$APP_DIR" && docker compose up -d --build 2>&1 | grep -v "^ *=>" || true
echo "== Restarting the web link"
cd "$CAM_DIR" && docker compose restart 2>&1 || true
echo "== ALL DONE (reopen PrintView Admin to load its newest version)"
'''


if __name__ == "__main__":
    w = Admin()
    w.show_all()
    w.b_next.hide()
    Gtk.main()
