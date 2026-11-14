"""Shared data, projection and regulation logic for the printed wall maps (print/make_wallmap.py)."""
import gzip, json, math, os
from collections import defaultdict
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, LineString, box
from shapely.ops import unary_union

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PDATA = os.path.join(ROOT, "print", "data")
MM = 72 / 25.4  # points per mm


def jload(p):
    if p.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


SPECIES = jload(os.path.join(ROOT, "data", "species.json"))
SP = {s["code"]: s for s in SPECIES}
RARITY = [s["code"] for s in SPECIES]
# Game species only (the species list of the live map: trout, char, grayling, whitefish and other sport fish).
# Non-game fish (minnows, suckers, sculpins ...) are left off the printed maps.
SELECTED = [s["code"] for s in SPECIES]
NAMES = jload(os.path.join(ROOT, "data", "species_names.json"))
REGS = jload(os.path.join(ROOT, "data", "regs", "regs.json"))
INDEX = jload(os.path.join(ROOT, "data", "water", "index.json"))
ITEMS = INDEX["items"]
OWNER_HIDE = {"l3470"}


def rarest(sp):
    for c in RARITY:
        if c in sp:
            return c
    return sp[0] if sp else None


def sp_color(c):
    return SP[c]["color"] if c in SP else "#666666"


def sel_only(sp):
    return [c for c in sp if c in SELECTED]


def all_sp(it):
    s = set((it.get("y") or {}).keys())
    s.update((it.get("st") or {}).keys())
    return sorted(s)


def disp_name(it):
    return it.get("n") or it.get("a") or ""


# ---------------- zones ----------------
def ring_poly(rings):
    """Even-odd polygon from ArcGIS rings."""
    g = None
    for r in rings:
        if len(r) < 4:
            continue
        p = Polygon(r).buffer(0)
        g = p if g is None else g.symmetric_difference(p)
    return g


def load_zones():
    z = jload(os.path.join(PDATA, "zones.json.gz"))
    return {k: ring_poly(v) for k, v in z.items()}


# ---------------- regulations (port of app.js regParts / regStatus, for a whole year) ----------------
def in_range(md, r):
    return r[0] <= md <= r[1] if r[0] <= r[1] else (md >= r[0] or md <= r[1])


def rows_ever_open(rows):
    return any((r["s"].get("open") or []) for r in rows)


def side_sec(L, sec):
    import re
    return L["kind"] == "lake" and re.match(r"^(tributar|outlet|inlet|all tributar)", sec.get("d") or "", re.I)


def reg_parts(it, reach=None):
    w = REGS["w"].get(it["id"])
    if not w:
        return []
    if isinstance(w[0], list):
        zs = [w[0][reach]] if reach is not None else list(dict.fromkeys(w[0]))
    else:
        zs = [w[0]]
    zs = [z for z in zs if z]
    kind = "lake" if it["k"] == "l" else "stream"
    split = (w[2] if len(w) > 2 else None) or {}
    via = (w[3] if len(w) > 3 else None) or []
    out = []
    for z in zs:
        ls = ((w[1] if len(w) > 1 else None) or {}).get(z, [])
        sure = [i for i in ls if i >= 0]
        maybe = [REGS["list"][-1 - i] for i in ls if i < 0]
        d = (REGS["defaults"].get(z) or {}).get(kind)
        any_ = False
        for li in sure:
            L = REGS["list"][li]
            sp = split.get(str(li))
            v = li in via
            if sp and reach is not None:
                a = sp[reach] if reach < len(sp) else None
                if a is None:
                    if not v:
                        out.append({"zone": z, "L": L, "li": li})
                        any_ = True
                    continue
                out.append({"zone": z, "L": L, "li": li, "secs": a if isinstance(a, list) else [a], "via": v})
                any_ = True
            else:
                out.append({"zone": z, "L": L, "li": li, "split": bool(sp), "via": v})
                any_ = True
        if not any_:
            for L in maybe:
                out.append({"zone": z, "L": L, "possible": True})
            out.append({"zone": z, "def": d, "possible": bool(maybe)})
    return out


def year_state(it, reach=None):
    """'open' if every applicable rule opens at some time of year, 'closed' if none ever opens,
    'part' if some do, 'unknown' if no provincial rule applies (national parks, outside zones)."""
    w = REGS["w"].get(it["id"])
    if reach is None and w and len(w) > 2 and w[2]:
        n = len(list(w[2].values())[0])
        st = {year_state(it, k) for k in range(n)} - {"unknown"}
        return "unknown" if not st else (st.pop() if len(st) == 1 else "part")
    states = []
    for p in reg_parts(it, reach):
        L = p.get("L")
        if L and p.get("secs"):
            states.append(any(L["sec"][si]["rows"] and rows_ever_open(L["sec"][si]["rows"]) for si in p["secs"] if si < len(L["sec"])))
        elif L:
            for sc in L["sec"]:
                if not side_sec(L, sc) and sc["rows"]:
                    states.append(rows_ever_open(sc["rows"]))
        elif p.get("def"):
            states.append(rows_ever_open(p["def"]))
    if not states:
        return "unknown"
    return "open" if all(states) else ("part" if any(states) else "closed")


def listing_ids(it):
    """Regulation listings (indices into REGS['list']) that name this water directly."""
    w = REGS["w"].get(it["id"])
    if not w or len(w) < 2 or not w[1]:
        return []
    via = (w[3] if len(w) > 3 else None) or []
    return sorted({i for z, ls in w[1].items() for i in ls if i >= 0 and i not in via})


# ---------------- projection / page ----------------
class Frame:
    """Transverse Mercator centred on the map; paper coordinates in mm from the page's bottom-left corner."""

    def __init__(self, lon0, lat0, scale, fx0, fy0, fx1, fy1, cx=None, cy=None):
        self.scale = scale
        self.fwd = Transformer.from_crs("EPSG:4326", f"+proj=tmerc +lon_0={lon0} +lat_0={lat0} +k=1 +x_0=0 +y_0=0 +ellps=GRS80 +units=m", always_xy=True)
        self.inv_t = Transformer.from_crs(f"+proj=tmerc +lon_0={lon0} +lat_0={lat0} +k=1 +x_0=0 +y_0=0 +ellps=GRS80 +units=m", "EPSG:4326", always_xy=True)
        self.fx0, self.fy0, self.fx1, self.fy1 = fx0, fy0, fx1, fy1
        self.cx = (fx0 + fx1) / 2 if cx is None else cx
        self.cy = (fy0 + fy1) / 2 if cy is None else cy
        self.k = 1000.0 / scale  # mm per metre
        self.lon0, self.lat0 = lon0, lat0

    def p(self, lon, lat):
        x, y = self.fwd.transform(lon, lat)
        return self.cx + x * self.k, self.cy + y * self.k

    def pts(self, coords):
        xs, ys = self.fwd.transform([c[0] for c in coords], [c[1] for c in coords])
        return [(self.cx + x * self.k, self.cy + y * self.k) for x, y in zip(xs, ys)]

    def inv(self, px, py):
        return self.inv_t.transform((px - self.cx) / self.k, (py - self.cy) / self.k)

    def box(self):
        return box(self.fx0, self.fy0, self.fx1, self.fy1)

    def lonlat_bbox(self, pad=0.05):
        import numpy as np
        xs = list(np.linspace(self.fx0, self.fx1, 30)) + [self.fx1] * 30 + list(np.linspace(self.fx1, self.fx0, 30)) + [self.fx0] * 30
        ys = [self.fy0] * 30 + list(np.linspace(self.fy0, self.fy1, 30)) + [self.fy1] * 30 + list(np.linspace(self.fy1, self.fy0, 30))
        lo, la = self.inv_t.transform([(x - self.cx) / self.k for x in xs], [(y - self.cy) / self.k for y in ys])
        return min(lo) - pad, min(la) - pad, max(lo) + pad, max(la) + pad

    def geom(self, g):
        """Project a shapely geometry (lon/lat) to paper mm."""
        from shapely.ops import transform
        import numpy as np

        def f(x, y, z=None):
            X, Y = self.fwd.transform(np.asarray(x), np.asarray(y))
            return self.cx + np.asarray(X) * self.k, self.cy + np.asarray(Y) * self.k
        return transform(f, g)
