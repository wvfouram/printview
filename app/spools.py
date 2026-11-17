"""Spool tracker and filament prices.

Bambu spools with an RFID tag: the AMS reports how much is left (percent of the spool weight) when
"Estimate remaining filament" is on, so nothing needs typing in.
Other spools: you type in how many grams are on the spool once, and every print takes off what it used.
If a slot suddenly shows a different filament type or color, the old number is dropped and it asks again.
"""
import json
import os
import threading
import time

EXTERNAL = 254


def mapping_to_slot(m):
    """AMS mapping value from a print start -> the slot number the status uses."""
    try:
        m = int(m)
    except (TypeError, ValueError):
        return None
    if m in (254, 255):
        return EXTERNAL
    if m < 0:
        return None
    if m >= 128:                    # AMS HT: unit id 128+ with one tray
        return m * 4
    return m


def _type_key(t):
    return (t or "").strip().upper()


class Spools:
    def __init__(self, printer, settings, data_dir):
        self.printer, self.settings = printer, settings
        self.path = os.path.join(data_dir, "spools.json")
        self._lock = threading.Lock()
        try:
            with open(self.path) as f:
                self.slots = {str(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.slots = {}

    def _save(self):
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.slots, f)
        os.replace(self.path + ".tmp", self.path)

    # ---------------------------------------------------------------- prices
    def price_per_kg(self, ftype):
        prices = self.settings.get("prices") or {}
        t = _type_key(ftype)
        if t in prices:
            return prices[t]
        base = t.split("-")[0].split(" ")[0]          # PLA Matte / PLA-S -> PLA
        return prices.get(base)

    def cost(self, filaments):
        """filaments: [{"type", "g"}] -> money, or None if no price is known for any of them."""
        total, known = 0.0, False
        for f in filaments or []:
            p = self.price_per_kg(f.get("type"))
            if p is not None and f.get("g"):
                total += f["g"] / 1000 * p
                known = True
        return round(total, 2) if known else None

    # ---------------------------------------------------------------- what's loaded
    def _trays(self):
        ams = self.printer.status().get("ams") or {}
        out = [dict(t) for t in ams.get("trays") or []]
        if ams.get("external"):
            e = dict(ams["external"])
            e.update(unit="Ext", tray=1, empty=not e.get("type"))
            out.append(e)
        return out

    def _matches(self, rec, tray):
        return rec and _type_key(rec.get("type")) == _type_key(tray.get("type")) and \
            (rec.get("color") or "").lower() == (tray.get("color") or "").lower()

    def view(self):
        rows = []
        with self._lock:
            for t in self._trays():
                rec = self.slots.get(str(t["slot"]))
                row = {"slot": t["slot"], "unit": t.get("unit"), "tray": t.get("tray"), "type": t.get("type") or "",
                       "color": t.get("color"), "empty": bool(t.get("empty")), "left_g": None, "full_g": None, "source": None}
                if not row["empty"]:
                    rem, weight = t.get("remain"), t.get("weight") or 1000
                    if rem is not None and rem >= 0 and t.get("rfid"):
                        row.update(left_g=round(weight * rem / 100), full_g=weight, source="rfid")
                    elif self._matches(rec, t):
                        row.update(left_g=round(rec["grams"]), full_g=rec.get("full") or 1000, source="manual",
                                   set_at=rec.get("set"))
                rows.append(row)
        return rows

    def set(self, slot, grams, full=None):
        slot = int(slot)
        t = next((x for x in self._trays() if x["slot"] == slot), None)
        if not t or t.get("empty"):
            raise ValueError("no spool in that slot")
        grams = max(0.0, min(5000.0, float(grams)))
        with self._lock:
            self.slots[str(slot)] = {"grams": grams, "full": int(full or max(1000, grams)), "type": t.get("type"),
                                     "color": t.get("color"), "set": int(time.time())}
            self._save()
        return self.view()

    def consume(self, slot, grams):
        if slot is None or not grams:
            return
        with self._lock:
            rec = self.slots.get(str(slot))
            if not rec:
                return
            t = next((x for x in self._trays() if x["slot"] == slot), None)
            if t is not None and not self._matches(rec, t):
                self.slots.pop(str(slot), None)         # a different spool is in there now
            else:
                rec["grams"] = max(0.0, rec["grams"] - grams)
            self._save()

    def left(self, slot):
        return next((r["left_g"] for r in self.view() if r["slot"] == slot), None)

    def check(self, filaments):
        """filaments: [{"type", "g", "slot"}] -> warnings for spools that won't have enough."""
        need = {}
        for f in filaments or []:
            if f.get("slot") is not None and f.get("g"):
                need[f["slot"]] = need.get(f["slot"], 0) + f["g"]
        rows = {r["slot"]: r for r in self.view()}
        warn = []
        for slot, g in need.items():
            r = rows.get(slot)
            if not r or r["left_g"] is None:
                continue
            if r["left_g"] < g * 1.05 + 5:                  # 5 % plus a little for purges
                where = "External spool" if slot == EXTERNAL else f"AMS {r['unit']} slot {r['tray']}"
                warn.append(f"{where} ({r['type']}) has about {r['left_g']} g left, this print needs about {round(g)} g")
        return warn
