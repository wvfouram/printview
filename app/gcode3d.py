"""Turn a plate's G-code into a compact 3D toolpath for the browser / app viewer.

Binary format (little endian):
  b"PV3D", uint32 n_segments, uint32 n_layers, float32 bbox[6] (minx,miny,minz,maxx,maxy,maxz)
  int16 xyz pairs  [n * 6]   (mm * 50, so 0.02 mm steps, up to 655 mm)
  uint16 layer     [n]
  uint8 feature    [n]       0 outer wall, 1 inner wall, 2 infill, 3 top/bottom, 4 support, 5 other
Only extruding moves are kept. Very large prints are thinned (infill first) to MAX_SEG segments.
"""
import gzip
from array import array
import hashlib
import io
import math
import os
import re
import struct
import zipfile

import numpy as np

MAX_SEG = 1_000_000
SCALE = 50.0
FEAT = [("outer wall", 0), ("inner wall", 1), ("overhang wall", 0), ("sparse infill", 2), ("internal solid infill", 2),
        ("top surface", 3), ("bottom surface", 3), ("bridge", 3), ("support", 4), ("gap infill", 1), ("ironing", 3)]
_num = re.compile(r"([XYZEFIJR])(-?\d*\.?\d+)")
VERSION = 2   # bump when the toolpath output changes, so old cached ones are rebuilt


def _feature(line):
    l = line.lower()
    for k, v in FEAT:
        if k in l:
            return v
    return 5


def build(local_3mf, plate, cache_dir):
    """Returns the PV3D bytes gzipped (cached on disk), or None if the plate has no G-code."""
    st = os.stat(local_3mf)
    key = hashlib.sha1(f"v{VERSION}|{local_3mf}|{plate}|{int(st.st_mtime)}|{st.st_size}".encode()).hexdigest()[:20] + ".pv3d"
    out = os.path.join(cache_dir, key)
    if os.path.exists(out):
        with open(out, "rb") as f:
            return f.read()
    with zipfile.ZipFile(local_3mf) as z:
        name = f"Metadata/plate_{int(plate)}.gcode"
        if name not in z.namelist():
            return None
        with io.TextIOWrapper(z.open(name), encoding="utf-8", errors="replace") as fh:   # streamed, never all in RAM
            res = _walk(fh)
    if res is None:
        return None
    return _pack(*res, out=out, cache_dir=cache_dir)


def _arc(x0, y0, x1, y1, i, j, r, cw):
    """Split a G2 (clockwise) / G3 arc into short straight pieces (about 0.4 mm each)."""
    if i is None and j is None:
        if r is None:
            return [(x0, y0, x1, y1)]
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d == 0 or abs(r) < d / 2:
            return [(x0, y0, x1, y1)]
        h = math.sqrt(r * r - d * d / 4) * (1 if (r > 0) != cw else -1)
        cx, cy = x0 + dx / 2 - h * dy / d, y0 + dy / 2 + h * dx / d
    else:
        cx, cy = x0 + (i or 0.0), y0 + (j or 0.0)
    rad = math.hypot(x0 - cx, y0 - cy)
    if rad < 1e-6:
        return [(x0, y0, x1, y1)]
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw:
        if sweep >= -1e-9:
            sweep -= 2 * math.pi
    elif sweep <= 1e-9:
        sweep += 2 * math.pi
    n = max(2, min(128, int(abs(sweep) * rad / 0.4) + 1))
    out, px, py = [], x0, y0
    for k in range(1, n + 1):
        if k == n:
            qx, qy = x1, y1
        else:
            a = a0 + sweep * k / n
            qx, qy = cx + rad * math.cos(a), cy + rad * math.sin(a)
        out.append((px, py, qx, qy))
        px, py = qx, qy
    return out


def _walk(fh):
    x = y = z_ = e = 0.0
    rel_e = False
    feat, layer = 5, -1
    pts, lay, fts = array("f"), array("H"), array("B")   # flat arrays: millions of moves stay small
    for line in fh:
        line = line.rstrip("\r\n")
        if not line:
            continue
        c = line[0]
        if c == ";":
            if line.startswith("; FEATURE:"):
                feat = _feature(line)
            elif line.startswith("; CHANGE_LAYER") or line.startswith(";LAYER_CHANGE"):
                layer += 1
            continue
        if line.startswith("M83"):
            rel_e = True
        elif line.startswith("M82"):
            rel_e = False
        elif line.startswith("G92"):
            for k, v in _num.findall(line):
                if k == "E":
                    e = float(v)
        elif line.startswith(("G1 ", "G0 ", "G1\t", "G0\t", "G2 ", "G3 ")):
            code = line.split(";", 1)[0]
            nx, ny, nz, ne = x, y, z_, None
            ci = cj = cr = None
            for k, v in _num.findall(code):
                v = float(v)
                if k == "X":
                    nx = v
                elif k == "Y":
                    ny = v
                elif k == "Z":
                    nz = v
                elif k == "E":
                    ne = v
                elif k == "I":
                    ci = v
                elif k == "J":
                    cj = v
                elif k == "R":
                    cr = v
            extr = ne is not None and ((ne > 0) if rel_e else (ne > e))
            if ne is not None and not rel_e:
                e = ne
            if extr and code.startswith(("G2", "G3")):
                cw = code.startswith("G2")
                for (ax, ay, bx, by) in _arc(x, y, nx, ny, ci, cj, cr, cw):
                    pts.extend((ax, ay, nz, bx, by, nz))
                    lay.append(min(max(layer, 0), 65535))
                    fts.append(feat)
            elif extr and (nx != x or ny != y):
                pts.extend((x, y, nz, nx, ny, nz))
                lay.append(min(max(layer, 0), 65535))
                fts.append(feat)
            x, y, z_ = nx, ny, nz
    if not fts:
        return None
    return pts, lay, fts


def _pack(pts, lay, fts, out, cache_dir):
    p = np.frombuffer(pts, dtype=np.float32).reshape(-1, 6)
    L = np.frombuffer(lay, dtype=np.uint16)
    F = np.frombuffer(fts, dtype=np.uint8)
    if len(p) > MAX_SEG:                      # thin infill first, then everything evenly
        keep = np.ones(len(p), bool)
        inf = np.where(F == 2)[0]
        over = len(p) - MAX_SEG
        if len(inf):
            step = max(1, int(np.ceil(len(inf) / max(1, len(inf) - over))))
            drop = inf[np.arange(len(inf)) % step != 0]
            keep[drop[:over]] = False
        idx = np.where(keep)[0]
        if len(idx) > MAX_SEG:
            idx = idx[np.linspace(0, len(idx) - 1, MAX_SEG).astype(int)]
        p, L, F = p[idx], L[idx], F[idx]
    bb = [float(p[:, [0, 3]].min()), float(p[:, [1, 4]].min()), float(p[:, 2].min()),
          float(p[:, [0, 3]].max()), float(p[:, [1, 4]].max()), float(p[:, 2].max())]
    q = np.clip(np.round(p * SCALE), -32767, 32767).astype("<i2")
    data = (b"PV3D" + struct.pack("<II", len(p), int(L.max()) + 1) + struct.pack("<6f", *bb)
            + q.tobytes() + L.astype("<u2").tobytes() + F.tobytes())
    data = gzip.compress(data, 6)
    os.makedirs(cache_dir, exist_ok=True)
    for old in sorted((os.path.join(cache_dir, n) for n in os.listdir(cache_dir)), key=os.path.getmtime)[:-40]:
        try:
            os.remove(old)                 # keep the newest 40 toolpaths
        except OSError:
            pass
    with open(out + ".tmp", "wb") as f:
        f.write(data)
    os.replace(out + ".tmp", out)
    return data
