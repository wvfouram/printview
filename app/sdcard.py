"""The printer's SD card over FTPS (port 990, implicit TLS, user bblp / access code).

Lists sliced .3mf files and timelapses, downloads them, and reads plate info
(thumbnails, filaments, objects) out of a 3MF so the app can start prints,
pick AMS slots and skip objects - all on your LAN.
"""
import ftplib
import hashlib
import logging
import json
import os
import re
import ssl
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

log = logging.getLogger("sdcard")

MODEL_DIRS = ("/", "/cache", "/model")
MODEL_EXT = (".3mf",)
VIDEO_EXT = (".mp4", ".avi")


class ImplicitFTPS(ftplib.FTP_TLS):
    """FTP_TLS with implicit TLS and TLS session reuse on data connections (the printer requires it)."""

    def __init__(self, context):
        super().__init__(context=context, timeout=20)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def _parse_list_line(line):
    # -rw-r--r--    1 root     root      1234567 Oct 20 10:00 my part.gcode.3mf
    parts = line.split(None, 8)
    if len(parts) < 9:
        return None
    is_dir = parts[0].startswith("d")
    try:
        size = int(parts[4])
    except ValueError:
        size = 0
    return {"name": parts[8], "dir": is_dir, "size": size, "date": " ".join(parts[5:8])}


def _when(date):
    """FTP LIST date ('Nov 05 20:13' or 'Nov 05 2025') -> sortable timestamp, newest biggest."""
    import datetime as _dt
    now = _dt.datetime.now()
    for fmt in ("%b %d %H:%M", "%b %d %Y"):
        try:
            d = _dt.datetime.strptime(date, fmt)
        except ValueError:
            continue
        if fmt == "%b %d %H:%M":
            d = d.replace(year=now.year)
            if d > now + _dt.timedelta(days=1):
                d = d.replace(year=now.year - 1)
        return d.timestamp()
    return 0


class SDCard:
    def __init__(self, ip, access_code, cache_dir, port=990):
        self.ip, self.code, self.port = ip, access_code, port
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._lock = threading.Lock()          # the printer only likes one FTP session at a time
        self._list_cache = {}
        self._refreshing = set()
        self._seen_path = os.path.join(cache_dir, "first_seen.json")
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    # -------------------------------------------------------------- connection
    def _connect(self):
        f = ImplicitFTPS(self.ctx)
        f.connect(self.ip, self.port, timeout=15)    # never hang forever on a stalled printer
        f.login("bblp", self.code)
        f.prot_p()
        return f

    def _listdir(self, f, path):
        lines = []
        try:
            f.retrlines(f"LIST {path}", lines.append)
        except ftplib.error_perm:
            return []
        out = []
        for l in lines:
            e = _parse_list_line(l)
            if e and e["name"] not in (".", ".."):
                e["path"] = (path.rstrip("/") + "/" + e["name"]) if path != "/" else "/" + e["name"]
                out.append(e)
        return out

    def _session(self, fn, wait=25):
        """One FTP session at a time; give up instead of queueing forever behind a stuck one."""
        if not self._lock.acquire(timeout=wait):
            raise RuntimeError("SD card busy, try again in a moment")
        try:
            f = self._connect()
            try:
                return fn(f)
            finally:
                try:
                    f.quit()
                except Exception:  # noqa: BLE001
                    f.close()
        finally:
            self._lock.release()

    def _cached(self, key, ttl, fn):
        """Serve the last listing straight away; refresh it in the background when it's old.
        Only a first-ever (or forced) listing makes the caller wait for the printer."""
        hit = self._list_cache.get(key)
        if hit:
            if time.time() - hit[0] >= ttl and key not in self._refreshing:
                self._refreshing.add(key)

                def bg():
                    try:
                        self._list_cache[key] = (time.time(), self._session(fn))
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        self._refreshing.discard(key)
                threading.Thread(target=bg, daemon=True).start()
            return hit[1]
        val = self._session(fn)
        self._list_cache[key] = (time.time(), val)
        return val

    def invalidate(self):
        self._list_cache.clear()

    # -------------------------------------------------------------- listings
    def models(self, refresh=False):
        if refresh:
            self.invalidate()

        def fn(f):
            seen, out = set(), []
            for d in MODEL_DIRS:
                for e in self._listdir(f, d):
                    if e["dir"] or not e["name"].lower().endswith(MODEL_EXT) or e["path"] in seen:
                        continue
                    seen.add(e["path"])
                    e["title"] = re.sub(r"(\.gcode)?\.3mf$", "", e["name"], flags=re.I)
                    out.append(e)
            # newest first. The printer's clock is wrong in LAN-only mode, so files are ordered by when
            # PrintWatch first saw them, with the printer's date only as a tie-break.
            try:
                seen = json.load(open(self._seen_path))
            except (OSError, ValueError):
                seen = {}
            first = not seen
            now = time.time()
            for e in out:
                if e["path"] not in seen:
                    seen[e["path"]] = 0 if first else now
            seen = {p: t for p, t in seen.items() if any(e["path"] == p for e in out)}
            try:
                json.dump(seen, open(self._seen_path, "w"))
            except OSError:
                pass
            out.sort(key=lambda e: (seen.get(e["path"], 0), _when(e.get("date", ""))), reverse=True)
            for e in out:
                if seen.get(e["path"]):
                    e["date"] = time.strftime("%b %d %H:%M", time.localtime(seen[e["path"]]))
            return out
        return self._cached("models", 60, fn)

    def timelapses(self, refresh=False):
        if refresh:
            self.invalidate()

        def fn(f):
            vids = [e for e in self._listdir(f, "/timelapse")
                    if not e["dir"] and e["name"].lower().endswith(VIDEO_EXT)]
            thumbs = {e["name"] for e in self._listdir(f, "/timelapse/thumbnail")}
            for v in vids:
                stem = os.path.splitext(v["name"])[0]
                t = stem + ".jpg"
                v["thumb"] = "/timelapse/thumbnail/" + t if t in thumbs else None
            vids.sort(key=lambda v: v["name"], reverse=True)
            return vids
        return self._cached("timelapses", 30, fn)

    # -------------------------------------------------------------- files
    def _cache_path(self, path, size):
        h = hashlib.sha1(f"{path}:{size}".encode()).hexdigest()[:16]
        ext = ".3mf" if path.lower().endswith(".3mf") else os.path.splitext(path)[1]
        return os.path.join(self.cache_dir, h + ext)

    def fetch(self, path, size=None):
        """Download a file into the cache (once) and return the local path."""
        if size is None:
            size = next((m["size"] for m in self.models() if m["path"] == path), 0)
        local = self._cache_path(path, size)
        if os.path.exists(local):
            return local
        tmp = local + ".part"
        def get(f):
            with open(tmp, "wb") as out:
                f.retrbinary(f"RETR {path}", out.write, blocksize=65536)
        self._session(get, wait=60)
        os.replace(tmp, local)
        self._prune()
        return local

    def read_small(self, path, limit=2_000_000):
        """Read a small file (thumbnails) straight into memory."""
        buf = bytearray()
        def cb(chunk):
            buf.extend(chunk)
            if len(buf) > limit:
                raise ValueError("file too large")
        self._session(lambda f: f.retrbinary(f"RETR {path}", cb))
        return bytes(buf)

    def stream(self, path, on_chunk):
        """Stream a (large) file chunk by chunk, e.g. a timelapse to the phone."""
        self._session(lambda f: f.retrbinary(f"RETR {path}", on_chunk, blocksize=65536), wait=60)

    def upload(self, local, name):
        """Copy a local file onto the root of the printer's SD card."""
        with open(local, "rb") as fp:
            self._session(lambda f: f.storbinary(f"STOR /{name}", fp, blocksize=65536), wait=120)
        self.invalidate()

    def _prune(self, keep_bytes=500_000_000):
        files = sorted((os.path.join(self.cache_dir, n) for n in os.listdir(self.cache_dir)),
                       key=lambda p: os.path.getmtime(p))
        total = sum(os.path.getsize(p) for p in files)
        for p in files:
            if total <= keep_bytes:
                break
            total -= os.path.getsize(p)
            os.remove(p)


# ------------------------------------------------------------------ 3MF
def parse_3mf(local_path):
    """Plates of a sliced Bambu 3MF: thumbnails, filaments, objects, print time."""
    plates = []
    with zipfile.ZipFile(local_path) as z:
        names = set(z.namelist())
        root = None
        if "Metadata/slice_info.config" in names:
            root = ET.fromstring(z.read("Metadata/slice_info.config"))
        for p in (root.findall("plate") if root is not None else []):
            meta = {m.get("key"): m.get("value") for m in p.findall("metadata")}
            idx = int(meta.get("index", "1"))
            gcode = f"Metadata/plate_{idx}.gcode"
            filaments = []
            for fl in p.findall("filament"):
                filaments.append({"id": int(fl.get("id", "1")), "type": fl.get("type", ""),
                                  "color": (fl.get("color") or "")[:7], "used_g": _f(fl.get("used_g")),
                                  "used_m": _f(fl.get("used_m")), "tray_info_idx": fl.get("tray_info_idx", "")})
            objects = [{"id": int(o.get("identify_id")), "name": o.get("name", "object"),
                        "skipped": o.get("skipped") == "true"}
                       for o in p.findall("object") if (o.get("identify_id") or "").isdigit()]
            plates.append({"index": idx, "sliced": gcode in names,
                           "thumb": f"Metadata/plate_{idx}.png" in names,
                           "seconds": int(_f(meta.get("prediction")) or 0),
                           "weight_g": _f(meta.get("weight")),
                           "nozzle": meta.get("nozzle_diameters") or meta.get("nozzle_diameter"),
                           "filaments": filaments, "objects": objects})
        if not plates:  # unsliced or unusual file: still offer any plate gcode we can see
            for n in sorted(names):
                m = re.match(r"Metadata/plate_(\d+)\.gcode$", n)
                if m:
                    i = int(m.group(1))
                    plates.append({"index": i, "sliced": True, "thumb": f"Metadata/plate_{i}.png" in names,
                                   "seconds": 0, "weight_g": None, "nozzle": None, "filaments": [], "objects": []})
    plates.sort(key=lambda p: p["index"])
    return plates


def plate_png(local_path, index):
    with zipfile.ZipFile(local_path) as z:
        for n in (f"Metadata/plate_{index}.png", f"Metadata/plate_no_light_{index}.png", f"Metadata/top_{index}.png"):
            if n in z.namelist():
                return z.read(n)
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
