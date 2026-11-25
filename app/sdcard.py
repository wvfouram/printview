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
import struct
import zipfile
import zlib

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

    def adopt(self, local, path):
        """Keep a file the Pi just copied to the card as the local cache copy, so previews and
        plate info for it show straight away without downloading it back from the printer."""
        dst = self._cache_path(path, os.path.getsize(local))
        os.replace(local, dst)
        self._prune()

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

    # ---------------------------------------------------------- small reads
    def read_range(self, path, offset, length):
        """Read `length` bytes starting at `offset` without downloading the whole file (FTP REST)."""
        def get(f):
            f.voidcmd("TYPE I")
            conn = f.transfercmd(f"RETR {path}", rest=offset)
            buf = bytearray()
            try:
                while len(buf) < length:
                    chunk = conn.recv(min(65536, length - len(buf)))
                    if not chunk:
                        break
                    buf.extend(chunk)
            finally:
                conn.close()
            try:
                f.sock.settimeout(5)
                f.voidresp()          # 226, or 426 because we stopped early: both fine
            except Exception:  # noqa: BLE001
                pass
            return bytes(buf)
        return self._session(get, wait=20)

    def thumb(self, path, size):
        """Picture of the sliced plate, read straight out of the file on the printer: only the zip index
        and the picture are fetched (about 100 KB), not the whole file. Cached on the Pi."""
        tdir = os.path.join(self.cache_dir, "thumbs")
        os.makedirs(tdir, exist_ok=True)
        key = os.path.join(tdir, hashlib.sha1(f"{path}:{size}".encode()).hexdigest()[:16] + ".png")
        if os.path.exists(key):
            return open(key, "rb").read()
        local = self._cache_path(path, size)
        if os.path.exists(local):
            png = plate_png(local, 0)
        else:
            png = self._remote_plate_png(path, size)
        if png:
            with open(key, "wb") as f:
                f.write(png)
        return png

    def _remote_plate_png(self, path, size):
        if size < 22:
            return None
        tail_len = min(size, 65536 + 22)
        tail = self.read_range(path, size - tail_len, tail_len)
        e = tail.rfind(b"PK\x05\x06")
        if e < 0:
            return None
        cd_size, cd_off = struct.unpack("<II", tail[e + 12:e + 20])
        if cd_off >= size - tail_len:
            cd = tail[cd_off - (size - tail_len):][:cd_size]
        else:
            cd = self.read_range(path, cd_off, cd_size)
        entries, p = {}, 0
        while p + 46 <= len(cd) and cd[p:p + 4] == b"PK\x01\x02":
            method, = struct.unpack("<H", cd[p + 10:p + 12])
            csize, usize = struct.unpack("<II", cd[p + 20:p + 28])
            nl, xl, cl = struct.unpack("<HHH", cd[p + 28:p + 34])
            lo, = struct.unpack("<I", cd[p + 42:p + 46])
            name = cd[p + 46:p + 46 + nl].decode("utf-8", "replace")
            if csize == 0xFFFFFFFF or lo == 0xFFFFFFFF:   # zip64: read its extra field
                x = cd[p + 46 + nl:p + 46 + nl + xl]
                q = 0
                while q + 4 <= len(x):
                    hid, hl = struct.unpack("<HH", x[q:q + 4])
                    if hid == 1:
                        vals = list(struct.unpack("<" + "Q" * (hl // 8), x[q + 4:q + 4 + (hl // 8) * 8]))
                        if usize == 0xFFFFFFFF and vals:
                            usize = vals.pop(0)
                        if csize == 0xFFFFFFFF and vals:
                            csize = vals.pop(0)
                        if lo == 0xFFFFFFFF and vals:
                            lo = vals.pop(0)
                    q += 4 + hl
            entries[name] = (method, csize, lo)
            p += 46 + nl + xl + cl
        sliced = sorted(int(m.group(1)) for m in (re.match(r"Metadata/plate_(\d+)\.gcode$", n) for n in entries) if m)
        nums = sliced or sorted(int(m.group(1)) for m in (re.match(r"Metadata/plate_(\d+)\.png$", n) for n in entries) if m)
        idx = nums[0] if nums else 1
        ent = next((entries[n] for n in (f"Metadata/plate_{idx}.png", f"Metadata/plate_no_light_{idx}.png", f"Metadata/top_{idx}.png") if n in entries), None)
        if not ent or ent[1] > 8_000_000:
            return None
        method, csize, lo = ent
        hdr = self.read_range(path, lo, 30)
        nl, xl = struct.unpack("<HH", hdr[26:30])
        data = self.read_range(path, lo + 30 + nl + xl, csize)
        if method == 0:
            return data
        if method == 8:
            return zlib.decompress(data, -15)
        return None

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

    def delete(self, path):
        self._session(lambda f: f.delete(path))
        self.invalidate()

    def upload(self, local, name):
        """Copy a local file onto the root of the printer's SD card.
        The printer can take a long time to confirm a big file after the last byte arrives, so wait up to
        5 minutes for its reply, and if it still doesn't answer, check the file's size on the card instead."""
        size = os.path.getsize(local)

        def put(f):
            f.voidcmd("TYPE I")
            with open(local, "rb") as fp:
                conn = f.transfercmd(f"STOR /{name}")
                try:
                    while True:
                        buf = fp.read(65536)
                        if not buf:
                            break
                        conn.sendall(buf)
                    try:
                        conn.unwrap()
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    conn.close()
            f.sock.settimeout(300)
            try:
                f.voidresp()
            except (TimeoutError, OSError):
                return False
            return True

        confirmed = self._session(put, wait=600)
        self.invalidate()
        if not confirmed:
            def check(f):
                f.voidcmd("TYPE I")
                return f.size(f"/{name}")
            got = None
            for _ in range(6):
                try:
                    got = self._session(check, wait=120)
                    if got == size:
                        return
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(10)
            raise RuntimeError(f"the printer didn't confirm the file ({got or 0} of {size} bytes on the card)")

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
    """Picture of one plate. index 0 = the first plate that has a picture (a file sliced from only
    plate 3, say, has no plate_1 picture)."""
    with zipfile.ZipFile(local_path) as z:
        names = z.namelist()
        if index == 0:   # the plate that's actually sliced (a project file has pictures of every plate)
            sliced = sorted(int(m.group(1)) for m in (re.match(r"Metadata/plate_(\d+)\.gcode$", n) for n in names) if m)
            nums = sliced or sorted(int(m.group(1)) for m in (re.match(r"Metadata/plate_(\d+)\.png$", n) for n in names) if m)
            index = nums[0] if nums else 1
        for n in (f"Metadata/plate_{index}.png", f"Metadata/plate_no_light_{index}.png", f"Metadata/top_{index}.png"):
            if n in names:
                return z.read(n)
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
