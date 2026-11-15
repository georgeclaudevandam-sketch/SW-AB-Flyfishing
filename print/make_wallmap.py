#!/usr/bin/env python3
"""Printable A1 wall maps of the Eastern Slopes Trout Map: one for Fish Management Zone ES1, one for ES2 + ES3.

Front: shaded relief, lakes and streams coloured by the rarest game species recorded (as on the live map), roads and
trails (all labelled), places, protected areas, zone boundaries, grid, legend, scale, north arrow and sources.
Back: the zone's water-specific regulation tables, laid out like the provincial guide.

  python3 print/make_wallmap.py [ES1|ES2-ES3] [--draft]
Needs print/data/ (from print/fetch_print_data.py, run in GitHub Actions) and Terrarium elevation tiles in $DEM_TILES.
"""
import math, os, sys, time, datetime
from collections import defaultdict
import numpy as np
from PIL import Image
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon, Point, box, shape
from shapely.ops import unary_union, linemerge, polygonize
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.pdfbase.pdfmetrics import stringWidth

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fonts  # noqa: F401  (registers Carlito)
import dem
from common import (ROOT, PDATA, MM, jload, SPECIES, SP, RARITY, SELECTED, REGS, ITEMS, INDEX, OWNER_HIDE, rarest, sp_color,
                    sel_only, all_sp, disp_name, load_zones, year_state, listing_ids, Frame)
from labels import Occupancy, line_candidates, point_shape, runs_w, PT
from back import build_back

PAGE_W, PAGE_H = 594.0, 841.0           # A1 portrait, mm
FX0, FY0, FX1, FY1 = 11.0, 11.0, 583.0, 830.0  # map frame (neatline)
F, FB, FI, FBI = "Carlito", "Carlito-Bold", "Carlito-Italic", "Carlito-BoldItalic"
DEM_TILES = os.environ.get("DEM_TILES", "/tmp/claude-0/dem")
OUTDIR = os.environ.get("OUTDIR", os.path.join(ROOT, "print", "out"))

MAPS = {
    "ES1": {"zones": ["ES1"], "title": "ES1 Eastern Slopes: Waterton to the Bow", "rotate": True, "hide_outside": True,
            "sub": "Fish Management Zone ES1 · Southwest Alberta · Trout, char, grayling and other game fish · Roads, trails and access"},
    "ES2-ES3": {"zones": ["ES2", "ES3"], "title": "ES2 + ES3 Eastern Slopes: Red Deer to the Athabasca",
                "sub": "Fish Management Zones ES2 and ES3 · West-central Alberta · Trout, char, grayling and other game fish · Roads, trails and access"},
}

# ---------- styles ----------
C = HexColor
ROAD = {  # class: (casing width, line width, colour, dash) -- kept light so the fishing waters stand out
    "hwy": (0.50, 0.34, "#c62828", None),
    "major": (0.40, 0.26, "#d9662b", None),
    "paved": (0.30, 0.18, "#e8894a", None),
    "gravel": (0.26, 0.14, "#eb9a5e", (1.2, 0.6)),
    "track": (0.0, 0.10, "#8d6e63", (0.8, 0.5)),
}
LABEL_DROP = 2.0  # points taken off every map label (George: smaller lettering hides less detail)


def shrink(size):
    return max(2.4, size - LABEL_DROP) if size < 8 else size - LABEL_DROP * 1.5


TRAIL_COL = "#8b2f00"
WATER = "#1f78b4"
LAKE_FILL = "#bcdcf0"
ZONE_COL = "#6a1b9a"
PARK_COL = "#2e7d32"


def hexrgb(h, a=1.0):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return Color(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, alpha=a)


def pts2path(c, pts, close=False):
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


def stroke_lines(c, lines, width, col, dash=None, cap=1, alpha=1.0):
    c.setLineWidth(width)
    c.setStrokeColor(hexrgb(col, alpha) if isinstance(col, str) else col)
    c.setDash(list(dash), 0) if dash else c.setDash()
    c.setLineCap(cap)
    c.setLineJoin(1)
    for pts in lines:
        if len(pts) >= 2:
            c.drawPath(pts2path(c, pts), stroke=1, fill=0)
    c.setDash()


def fill_geom(c, g, fill, stroke=None, lw=0.1, alpha=1.0, salpha=1.0, dash=None):
    if g.is_empty:
        return
    polys = [g] if isinstance(g, Polygon) else [x for x in getattr(g, "geoms", []) if isinstance(x, Polygon)]
    for pg in polys:
        p = c.beginPath()
        for ring in [pg.exterior] + list(pg.interiors):
            cs = list(ring.coords)
            p.moveTo(*cs[0])
            for q in cs[1:]:
                p.lineTo(*q)
            p.close()
        if fill:
            c.setFillColor(hexrgb(fill, alpha))
        if stroke:
            c.setStrokeColor(hexrgb(stroke, salpha)); c.setLineWidth(lw)
            c.setDash(list(dash), 0) if dash else c.setDash()
        c.drawPath(p, stroke=1 if stroke else 0, fill=1 if fill else 0, fillMode=0)
        c.setDash()


import re as _re_names
_JUNK = _re_names.compile(r"^(''|\"\"|\d+m|\d+|\d+-\d+-\d+-\d+W\d|LOC\d+|\d{4,}\s.*|.*\bgarbage\b.*)$", _re_names.I)


def good_name(nm):
    nm = (nm or "").strip()
    return bool(nm) and not _JUNK.match(nm)


def geom_lines(g):
    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [list(g.coords)]
    if isinstance(g, (Polygon,)):
        return [list(g.exterior.coords)] + [list(r.coords) for r in g.interiors]
    out = []
    for x in getattr(g, "geoms", []):
        out += geom_lines(x)
    return out


# ---------- the map ----------
class WallMap:
    def __init__(self, key, draft=False):
        self.key, self.cfg, self.draft = key, MAPS[key], draft
        self.zones_all = load_zones()
        self.zone_ll = unary_union([self.zones_all[z] for z in self.cfg["zones"]])
        self.setup_frame()
        self.occ = Occupancy(6.0)
        self.labels = []   # ('curve', glyphs, size, halo) | ('text', x, y, runs, size, halo, angle)
        self.symbols = []
        self.stats = defaultdict(int)

    # ----- frame, scale, grid -----
    def setup_frame(self):
        b = self.zone_ll.bounds
        lon0, lat0 = round((b[0] + b[2]) / 2, 2), round((b[1] + b[3]) / 2, 2)
        fr = Frame(lon0, lat0, 1, 0, 0, 1, 1, 0, 0)
        fw, fh = FX1 - FX0, FY1 - FY0
        rot = 0.0
        if self.cfg.get("rotate"):
            from shapely import affinity
            zm = fr.geom(self.zone_ll)  # mm at 1:1 (= metres x 1000)
            best = None
            for a in np.arange(-90, 90.01, 0.5):
                b2 = affinity.rotate(zm, a, origin=(0, 0)).bounds
                need = max((b2[2] - b2[0]) / (fw - 6), (b2[3] - b2[1]) / (fh - 6))
                if best is None or need < best[0] - 1e-9 or (abs(need - best[0]) < 1e-9 and abs(a) < abs(best[1])):
                    best = (need, a)
            rot = float(best[1])
            fr = Frame(lon0, lat0, 1, 0, 0, 1, 1, 0, 0, rot=rot)
        self.rot = rot
        zp = fr.geom(self.zone_ll)  # in "mm at 1:1"... k = 1000 mm/m; we just need metres
        zb = zp.bounds
        wm, hm = (zb[2] - zb[0]) / 1000, (zb[3] - zb[1]) / 1000  # metres
        pad = 6 if self.cfg.get("rotate") else 8
        need = max(wm / (fw - pad) * 1000, hm / (fh - pad) * 1000)
        step = 5000 if self.cfg.get("rotate") else 25000
        scale = int(math.ceil(need / step) * step)
        self.scale = scale
        # centre the zone in the frame
        mx, my = (zb[0] + zb[2]) / 2 / 1000, (zb[1] + zb[3]) / 2 / 1000  # metres from projection origin
        k = 1000.0 / scale
        cx = (FX0 + FX1) / 2 - mx * k
        cy = (FY0 + FY1) / 2 - my * k
        self.fr = Frame(lon0, lat0, scale, FX0, FY0, FX1, FY1, cx, cy, rot=rot)
        self.zone_mm = self.fr.geom(self.zone_ll).buffer(0)
        self.frame_box = box(FX0, FY0, FX1, FY1)
        self.llb = self.fr.lonlat_bbox()
        print(f"{self.key}: scale 1:{scale:,}  rotation {rot}  lon0 {lon0} lat0 {lat0}  bbox {self.llb}", file=sys.stderr)
        # grid: 15' cells, letters west->east, numbers north->south
        self.gd = 0.25
        w, s, e, n = self.llb
        self.g_w = math.floor(w / self.gd) * self.gd
        self.g_n = math.ceil(n / self.gd) * self.gd
        self.g_e = math.ceil(e / self.gd) * self.gd
        self.g_s = math.floor(s / self.gd) * self.gd

    def gridref(self, lon, lat):
        i = int((lon - self.g_w) // self.gd)
        j = int((self.g_n - lat) // self.gd)
        return f"{self.col_letter(i)}{j + 1}"

    @staticmethod
    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    def in_frame_ll(self, lon, lat):
        x, y = self.fr.p(lon, lat)
        return FX0 <= x <= FX1 and FY0 <= y <= FY1

    def inside_zone(self, x, y):
        return self.zone_prep.contains(Point(x, y))

    # ----- data -----
    def load(self):
        from shapely.prepared import prep
        self.zone_prep = prep(self.zone_mm.buffer(2))
        import glob
        self.osm = {"ways": {}, "nodes": {}, "rels": {}, "built": ""}
        for p in sorted(glob.glob(os.path.join(PDATA, "osm*.json.gz"))):
            o = jload(p)
            for k in ("ways", "nodes"):
                self.osm[k].update(o[k])
            for rid, r in o["rels"].items():
                if rid not in self.osm["rels"] or ("m" in r and "m" not in self.osm["rels"][rid]):
                    self.osm["rels"][rid] = r
            self.osm["built"] = max(self.osm["built"], o.get("built", ""))
        for p, d in (("ab_roads", {"features": []}), ("ab_trails", {"layers": []})):
            if not os.path.exists(os.path.join(PDATA, p + ".json.gz")):
                print("missing", p, file=sys.stderr)
        opt = lambda n, d: jload(os.path.join(PDATA, n)) if os.path.exists(os.path.join(PDATA, n)) else d
        self.ab_roads = opt("ab_roads.json.gz", {"features": [], "fields": []})
        self.ab_trails = opt("ab_trails.json.gz", {"layers": []})
        # supplementary strips (north end of ES3, east edge of ES1); drop features already present
        rx = opt("ab_roads_x.json.gz", None)
        if rx:
            if not self.ab_roads["features"]:
                self.ab_roads["fields"] = rx["fields"]
            have = {f["a"].get("OBJECTID") for f in self.ab_roads["features"]}
            self.ab_roads["features"] += [f for f in rx["features"] if f["a"].get("OBJECTID") not in have or f["a"].get("OBJECTID") is None]
        tx = opt("ab_trails_x.json.gz", None)
        if tx:
            have = {f["a"].get("OBJECTID") for L in self.ab_trails["layers"] for f in L["features"]}
            for L in tx["layers"]:
                L["features"] = [f for f in L["features"] if f["a"].get("OBJECTID") not in have]
                have |= {f["a"].get("OBJECTID") for f in L["features"]}
                self.ab_trails["layers"].append(L)
        w, s, e, n = self.llb
        self.byid = {it["id"]: it for it in ITEMS}
        d = INDEX["meta"]["chunkDeg"]
        self.chunks = {}
        for ch in INDEX["meta"]["chunks"]:
            x, y = map(int, ch.split("_"))
            if x * d > e or (x + 1) * d < w or y * d > n or (y + 1) * d < s:
                continue
            self.chunks[ch] = jload(os.path.join(ROOT, "data", "water", f"c_{ch}.json"))

    def P(self, coords):
        return self.fr.pts(coords)

    # ----- obstacles: legend panels -----
    def add_panel(self, x0, y0, x1, y1):
        g = box(x0, y0, x1, y1)
        self.occ.add(g)
        self.panels.append((x0, y0, x1, y1))

    # ----- draw -----
    def render(self):
        os.makedirs(OUTDIR, exist_ok=True)
        self.front = os.path.join(OUTDIR, f"_front_{self.key}.pdf")
        c = rl_canvas.Canvas(self.front, pagesize=(PAGE_W * MM, PAGE_H * MM), pageCompression=1)
        c.setTitle(f"{self.cfg['title']} (wall map)")
        c.setAuthor("Eastern Slopes Trout Map")
        c.scale(MM, MM)
        self.c = c
        self.panels = []
        self.layout_panels()
        t = time.time()
        c.saveState()
        if self.cfg.get("hide_outside"):
            clip = c.beginPath()
            zc = self.zone_mm.intersection(self.frame_box)
            for pg in ([zc] if isinstance(zc, Polygon) else list(zc.geoms)):
                for ring in [pg.exterior] + list(pg.interiors):
                    cs = list(ring.coords)
                    clip.moveTo(*cs[0])
                    for q in cs[1:]:
                        clip.lineTo(*q)
                    clip.close()
            c.clipPath(clip, stroke=0, fill=0, fillMode=0)
        else:
            clip = c.beginPath(); clip.rect(FX0, FY0, FX1 - FX0, FY1 - FY0); c.clipPath(clip, stroke=0, fill=0)
        self.draw_relief(); print("relief", round(time.time() - t), file=sys.stderr)
        self.draw_areas()
        self.draw_trails()
        self.draw_roads(); print("roads", round(time.time() - t), file=sys.stderr)
        self.draw_water(); print("water", round(time.time() - t), file=sys.stderr)
        if not self.cfg.get("hide_outside"):
            self.draw_outside_fade()
        self.draw_boundaries()
        self.draw_graticule()
        self.draw_points()
        self.place_labels(); print("labels", round(time.time() - t), file=sys.stderr)
        self.flush_labels()
        c.restoreState()
        if self.cfg.get("hide_outside"):
            stroke_lines(c, geom_lines(self.zone_mm.boundary), 0.6, ZONE_COL, cap=1)
        self.draw_frame()
        self.draw_panels()
        c.showPage()
        c.save()

    # relief
    def draw_relief(self):
        dpmm = 3.0 if self.draft else 6.0
        W, H = int((FX1 - FX0) * dpmm), int((FY1 - FY0) * dpmm)
        fr = self.fr

        def inv(jj, ii):
            px = FX0 + (jj + 0.5) / dpmm
            py = FY1 - (ii + 0.5) / dpmm
            return fr.inv(px, py)
        zooms = [10, 11] if self.scale <= 400000 else [10]
        elev = dem.relief(DEM_TILES, zooms, inv, W, H, fr.scale / 1000 / dpmm)
        self.elev = (elev, dpmm)
        img = dem.image(elev, fr.scale / 1000 / dpmm, exag=2.0 if self.scale < 400000 else 2.6)
        # 90 % density: blend 10 % white
        a = np.asarray(img, dtype=np.float32)
        a = a * 0.9 + 255 * 0.1
        img = Image.fromarray(a.clip(0, 255).astype(np.uint8))
        p = os.path.join(OUTDIR, f"_relief_{self.key}.jpg")
        img.save(p, quality=88, optimize=True)
        self.c.drawImage(p, FX0, FY0, FX1 - FX0, FY1 - FY0)

    def elev_at(self, x, y):
        e, d = self.elev
        j = int((x - FX0) * d); i = int((FY1 - y) * d)
        if 0 <= i < e.shape[0] and 0 <= j < e.shape[1]:
            return float(e[i, j])
        return None

    # protected areas, glaciers
    def osm_rel_polys(self, pred):
        out = []
        ways = self.osm["ways"]
        for rid, r in self.osm["rels"].items():
            t = r["t"]
            if not pred(t):
                continue
            segs = [ways[str(m[1])]["g"] for m in r.get("m", []) if m[0] == "w" and str(m[1]) in ways and m[2] in ("outer", "")]
            if not segs:
                continue
            polys = list(polygonize(unary_union([LineString(s) for s in segs if len(s) > 1])))
            if polys:
                out.append((t, unary_union(polys), segs))
        for wid, w in ways.items():
            t = w["t"]
            if w.get("bm") or not pred(t):
                continue
            g = w["g"]
            if len(g) > 3 and g[0] == g[-1]:
                out.append((t, Polygon(g).buffer(0), [g]))
        return out

    def draw_areas(self):
        c = self.c
        fb = self.frame_box.buffer(20)
        is_park = lambda t: t.get("boundary") in ("national_park", "protected_area") or t.get("leisure") == "nature_reserve"
        self.parks = []
        for t, g, segs in self.osm_rel_polys(is_park):
            nm = t.get("name") or ""
            gm = self.fr.geom(g).buffer(0).intersection(fb)
            if gm.is_empty or gm.area < 4:
                continue
            nat = t.get("boundary") == "national_park" or "National Park" in nm
            self.parks.append((nm, gm, nat))
        self.parks.sort(key=lambda x: -x[1].area)
        for nm, gm, nat in self.parks:
            fill_geom(c, gm, "#4caf50", alpha=0.07 if nat else 0.09)
        for nm, gm, nat in self.parks:
            lines = geom_lines(gm.boundary if not gm.is_empty else gm)
            stroke_lines(c, lines, 0.55 if nat else 0.35, PARK_COL, None, alpha=0.30)
            stroke_lines(c, lines, 0.18, PARK_COL, (1.5, 0.8), alpha=0.9)
        is_gl = lambda t: t.get("natural") == "glacier"
        for t, g, segs in self.osm_rel_polys(is_gl):
            gm = self.fr.geom(g).buffer(0)
            fill_geom(c, gm, "#f4fbff", stroke="#7fb3d5", lw=0.08, alpha=0.85)
            if t.get("name"):
                self.glaciers = getattr(self, "glaciers", []) + [(t["name"], gm)]

    # water
    def draw_water(self):
        c = self.c
        lakes_nofish, lakes_fish, base, fish, closed = [], [], defaultdict(list), [], []
        self.water_labels = []
        fb = self.frame_box.buffer(5)
        for ch, arr in self.chunks.items():
            for f in arr:
                if "pts" in f:
                    continue
                it = self.byid.get(f["id"])
                if f["id"] in OWNER_HIDE:
                    continue
                if it is None:  # water with no fish records
                    if f.get("k") == "l" and f.get("g"):
                        lakes_nofish.append((f, None))
                    elif f.get("r"):
                        for r in f["r"]:
                            o = r.get("o") or f.get("o") or 1
                            if o >= 3 or (o >= 2 and self.scale <= 400000):
                                for part in r["g"]:
                                    base[o].append(part)
                    continue
                if it["k"] == "l":
                    sp = sel_only(all_sp(it))
                    (lakes_fish if sp else lakes_nofish).append((f, it))
                    continue
                for ri, r in enumerate(f.get("r") or []):
                    sp = sel_only(sorted((r.get("y") or {}).keys()))
                    o = r.get("o") or it.get("o") or 1
                    if sp:
                        st = year_state(it, ri) if REGS["w"].get(it["id"]) else "unknown"
                        fish.append((o, r["g"], sp_color(rarest(sp)), st == "closed"))
                    else:
                        for part in r["g"]:
                            base[o].append(part)
        W = lambda o: [0, 0.08, 0.10, 0.14, 0.19, 0.26, 0.34, 0.40, 0.46][min(o, 8)]
        WF = lambda o: [0, 0.26, 0.30, 0.36, 0.44, 0.52, 0.62, 0.70, 0.80][min(o, 8)]
        # lakes without game fish
        for f, it in lakes_nofish:
            for ring in [f["g"][0]] if f.get("g") else []:
                pts = self.P(ring)
                if len(pts) > 2:
                    c.setFillColor(hexrgb(LAKE_FILL)); c.setStrokeColor(hexrgb(WATER)); c.setLineWidth(0.08)
                    c.drawPath(pts2path(c, pts, True), stroke=1, fill=1)
        for o in sorted(base):
            stroke_lines(c, [self.P(g) for g in base[o]], W(o), WATER, alpha=0.85)
        # stretches with game fish: white halo then colour, wider streams on top
        fish.sort(key=lambda x: x[0])
        for o, g, col, cl in fish:
            stroke_lines(c, [self.P(p) for p in g], WF(o) + 0.25, "#ffffff", alpha=0.95)
        for o, g, col, cl in fish:
            stroke_lines(c, [self.P(p) for p in g], WF(o), col)
        for o, g, col, cl in fish:
            if cl:
                stroke_lines(c, [self.P(p) for p in g], max(0.15, WF(o) * 0.4), "#ffffff", (0.6, 0.6), cap=0)
        self.stats["fish_reaches"] = len(fish)
        for f, it in lakes_fish:
            sp = sel_only(all_sp(it))
            col = sp_color(rarest(sp))
            pts = self.P(f["g"][0])
            if len(pts) < 3:
                continue
            c.setFillColor(hexrgb("#ffffff")); c.setStrokeColor(hexrgb("#ffffff")); c.setLineWidth(0.5)
            c.drawPath(pts2path(c, pts, True), stroke=1, fill=0)
            c.setFillColor(hexrgb(col, 0.8)); c.setStrokeColor(hexrgb(col)); c.setLineWidth(0.35)
            c.drawPath(pts2path(c, pts, True), stroke=1, fill=1)
            # tiny lakes: a dot so they can be seen
            pg = Polygon(pts)
            if pg.area < 1.2:
                x, y = pg.centroid.x, pg.centroid.y
                c.setFillColor(hexrgb(col)); c.setStrokeColor(white); c.setLineWidth(0.15)
                c.circle(x, y, 0.75, stroke=1, fill=1)
            if year_state(it) == "closed":
                c.setStrokeColor(black); c.setLineWidth(0.15); c.setDash(0.4, 0.4)
                c.drawPath(pts2path(c, pts, True), stroke=1, fill=0); c.setDash()

    # trails
    def trail_feats(self):
        """[(name, pts_mm, kind, source)] kind: 'trail' | 'designated'"""
        out = []
        rel_name = {}
        for rid, r in self.osm["rels"].items():
            t = r["t"]
            if t.get("route") in ("hiking", "foot", "horse") and t.get("name"):
                for m in r.get("m", []):
                    if m[0] == "w":
                        rel_name.setdefault(str(m[1]), t["name"])
        for wid, w in self.osm["ways"].items():
            t = w["t"]
            hw = t.get("highway")
            if hw not in ("path", "footway", "bridleway", "steps"):
                continue
            nm = t.get("name") or rel_name.get(wid) or ""
            if hw in ("footway", "steps") and not nm:
                pts = self.P([w["g"][0], w["g"][-1]])
                if not (self.inside_zone(*pts[0]) or self.inside_zone(*pts[1])):
                    continue
            out.append((nm, w["g"], "trail", "osm"))
        for L in self.ab_trails.get("layers", []):
            for f in L["features"]:
                a = f["a"]
                nm = a.get("name") or a.get("NAME") or a.get("trail_name") or a.get("TRAIL_NAME") or ""
                for g in f["g"]:
                    out.append((nm, g, "designated", "ab"))
        return out

    def draw_trails(self):
        c = self.c
        self.trail_named = defaultdict(list)
        osm_lines, ab_lines = [], []
        self.cities = self.urban_circles()
        for nm, g, kind, src in self.trail_feats():
            pts = self.P(g)
            if src == "osm" and self.urban(*pts[0]) and self.urban(*pts[-1]):
                continue
            if src == "ab":
                ab_lines.append(pts)
            else:
                osm_lines.append(pts)
            if good_name(nm):
                self.trail_named[nm].append(pts)
        stroke_lines(c, ab_lines, 0.75, "#ffd54f", alpha=0.75)   # designated trail highlight under the dashes
        stroke_lines(c, osm_lines + ab_lines, 0.55, "#ffffff", alpha=0.7)
        stroke_lines(c, osm_lines + ab_lines, 0.30, TRAIL_COL, (0.9, 0.45), cap=0)
        self.stats["trails"] = len(osm_lines) + len(ab_lines)

    # roads
    def road_class(self, t):
        hw = t.get("highway", "")
        sf = (t.get("surface") or "").lower()
        paved = sf in ("paved", "asphalt", "concrete", "chipseal", "concrete:plates", "paving_stones")
        unpaved = sf in ("gravel", "unpaved", "dirt", "compacted", "ground", "fine_gravel", "earth", "mud", "sand", "grass", "pebblestone", "rock")
        if hw in ("motorway", "trunk", "motorway_link", "trunk_link"):
            return "hwy"
        if hw in ("primary", "primary_link"):
            return "hwy" if not unpaved else "gravel"
        if hw in ("secondary", "secondary_link"):
            return "major" if not unpaved else "gravel"
        if hw == "track":
            return "track"
        if paved:
            return "paved"
        return "gravel"

    def draw_roads(self):
        """Road lines from the Government of Alberta access roads (every class); OpenStreetMap supplies the highways
        outside Alberta and the local road names that the provincial layer lacks. Labels merge both sources by name."""
        c = self.c
        by = defaultdict(list)
        named = defaultdict(list)
        ncls = {}
        self.shields = defaultdict(list)
        prio = {"hwy": 0, "major": 1, "paved": 2, "gravel": 3, "track": 4}

        def add_name(nm, cl, pts):
            nm = (nm or "").strip()
            if not good_name(nm):
                return
            k = nm.lower()
            named[k].append(pts)
            if k not in ncls or prio[cl] < prio[ncls[k][1]]:
                ncls[k] = (nm, cl)
        have_ab = bool(self.ab_roads.get("features"))
        for wid, w in self.osm["ways"].items():
            t = w["t"]
            hw = t.get("highway")
            if hw not in ("motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
                          "secondary_link", "unclassified", "track", "road"):
                continue
            cl = self.road_class(t)
            pts = self.P(w["g"])
            if not have_ab or cl in ("hwy", "major"):
                by[cl].append(pts)
            ref = (t.get("ref") or "").split(";")[0].strip()
            nm = t.get("name") or ""
            add_name(nm, cl, pts)
            if ref and _re_names.match(r"^\d{1,3}[A-Z]?$", ref) and hw in ("motorway", "trunk", "primary", "secondary", "tertiary") and cl != "track":
                self.shields[ref].append(pts)
            elif ref and not nm:
                add_name(ref, cl, pts)
        for cl, pts, nm, hwy in self.ab_roads_extra():
            by[cl].append(pts)
            add_name(nm, cl, pts)
            if hwy and _re_names.match(r"^\d{1,3}[A-Z]?$", hwy):
                self.shields[hwy].append(pts)
        self.road_named = {(ncls[k][0], ncls[k][1]): v for k, v in named.items()}
        order = ["track", "gravel", "paved", "major", "hwy"]
        for cl in order:  # casings
            cw, lw, col, dash = ROAD[cl]
            if cw:
                stroke_lines(c, by[cl], cw, "#ffffff", cap=1)
        for cl in order:
            cw, lw, col, dash = ROAD[cl]
            if cl == "track":
                stroke_lines(c, by[cl], lw + 0.22, "#ffffff", alpha=0.7)
            stroke_lines(c, by[cl], lw, col, dash, cap=0 if dash else 1)
        for cl in order:
            self.stats["roads_" + cl] = len(by[cl])

    # access_facility_roads FEATURE_TYPE (codes read from the data: 6 divided highway, 8 and 9 paved, 3 urban paved,
    # 5 and 4 and 7 gravel or dirt roads, 10 / 14 / 2 truck trails, 12 winter roads)
    AB_CLASS = {6: "paved", 8: "paved", 9: "paved", 3: "paved", 5: "gravel", 4: "gravel", 7: "gravel", 10: "track", 14: "track", 2: "track", 12: "track"}

    def ab_roads_extra(self):
        out = []
        w, s, e, n = self.llb
        for f in self.ab_roads.get("features", []):
            a = f["a"]
            ft = a.get("FEATURE_TYPE")
            cl = self.AB_CLASS.get(ft, "track")
            if a.get("ROAD_CLASS") == "URBAN" and cl != "paved":
                continue
            hwy = a.get("HWY_NUMBER")
            if hwy and cl == "paved":
                try:
                    num = int("".join(ch for ch in str(hwy) if ch.isdigit()) or 999)
                except ValueError:
                    num = 999
                cl = "hwy" if (num < 100 or a.get("ROAD_CLASS") == "PRIMARY") else "major"
            for g in f["g"]:
                if not g:
                    continue
                if not any(w <= q[0] <= e and s <= q[1] <= n for q in (g[0], g[-1], g[len(g) // 2])):
                    continue
                pts = self.P(g)
                nm = a.get("NAME") or ""
                if nm and nm.isupper():
                    nm = " ".join(x.capitalize() if not any(ch.isdigit() for ch in x) else x for x in nm.split())
                    nm = nm.replace(" Rd", " Road").replace(" St ", " Street ")
                out.append((cl, pts, nm, str(hwy) if hwy else ""))
        return out

    def draw_outside_fade(self):
        c = self.c
        outside = self.frame_box.difference(self.zone_mm)
        fill_geom(c, outside, "#ffffff", alpha=0.38)

    def draw_boundaries(self):
        c = self.c
        # provincial / international boundaries
        ways = self.osm["ways"]
        prov, intl = [], []
        for rid, r in self.osm["rels"].items():
            t = r["t"]
            if t.get("boundary") != "administrative":
                continue
            lvl = t.get("admin_level")
            for m in r.get("m", []):
                w = ways.get(str(m[1]))
                if m[0] == "w" and w:
                    (intl if lvl == "2" else prov).append(self.P(w["g"]))
        stroke_lines(c, prov, 0.9, "#9e9e9e", alpha=0.5)
        stroke_lines(c, prov, 0.3, "#212121", (2.2, 0.8, 0.4, 0.8), cap=0)
        stroke_lines(c, intl, 1.1, "#9e9e9e", alpha=0.5)
        stroke_lines(c, intl, 0.4, "#000000", (3, 1, 0.5, 1, 0.5, 1), cap=0)
        # other fish management zones (thin) and this map's zones (bold)
        for z, g in self.zones_all.items():
            gm = self.fr.geom(g).buffer(0)
            lines = geom_lines(gm.boundary)
            if z in self.cfg["zones"]:
                stroke_lines(c, lines, 1.6, ZONE_COL, alpha=0.25)
                stroke_lines(c, lines, 0.55, ZONE_COL, (3.0, 1.4), cap=0)
            else:
                stroke_lines(c, lines, 0.35, ZONE_COL, (2.0, 1.2), cap=0, alpha=0.8)

    def draw_graticule(self):
        c = self.c
        lines = []
        lon = self.g_w
        while lon <= self.g_e + 1e-9:
            lines.append(self.P([(lon, la) for la in np.linspace(self.g_s, self.g_n, 60)]))
            lon += self.gd
        lat = self.g_s
        while lat <= self.g_n + 1e-9:
            lines.append(self.P([(lo, lat) for lo in np.linspace(self.g_w, self.g_e, 60)]))
            lat += self.gd
        stroke_lines(c, lines, 0.12, "#37474f", alpha=0.45)

    # points
    def draw_points(self):
        c = self.c
        self.pt_labels = []
        seen_names = set()
        for key, n in self.osm["nodes"].items():
            t = n["t"]
            x, y = self.fr.p(*n["c"])
            if not (FX0 < x < FX1 and FY0 < y < FY1):
                continue
            nm = t.get("name", "")
            inside = self.inside_zone(x, y)
            pl = t.get("place")
            kind = None
            if pl in ("city", "town", "village", "hamlet", "locality"):
                kind = pl
            elif t.get("natural") == "peak":
                kind = "peak"
            elif t.get("mountain_pass") == "yes" or t.get("natural") == "saddle":
                kind = "pass"
            elif t.get("tourism") == "camp_site":
                kind = "camp"
            elif t.get("tourism") in ("alpine_hut", "wilderness_hut"):
                kind = "hut"
            elif t.get("highway") == "trailhead":
                kind = "trailhead"
            elif t.get("amenity") == "parking":
                kind = "parking"
            elif t.get("amenity") == "ranger_station":
                kind = "ranger"
            elif t.get("leisure") == "slipway":
                kind = "launch"
            elif t.get("waterway") == "waterfall" or t.get("natural") == "waterfall":
                kind = "falls"
            elif t.get("man_made") == "tower":
                kind = "lookout"
            elif t.get("tourism") == "viewpoint":
                kind = "view"
            elif t.get("barrier") == "gate":
                kind = "gate"
            elif t.get("ford") == "yes":
                kind = "ford"
            elif t.get("waterway") == "dam":
                kind = "dam"
            elif t.get("tourism") == "information":
                kind = "info"
            if not kind:
                continue
            if kind in ("parking", "info") and (not nm or self.urban(x, y)):
                continue
            if kind == "gate":
                e = self.elev_at(x, y)
                if e is None or e < 1350:
                    continue
            if not inside and kind not in ("city", "town", "village", "peak") and not (kind == "hamlet"):
                continue
            if not inside and kind in ("peak",) and self.scale > 400000:
                continue
            self.symbol(kind, x, y)
            if good_name(nm):
                ele = t.get("ele", "")
                self.pt_labels.append((kind, nm, x, y, ele, inside))
            self.stats["pt_" + kind] += 1

    def symbol(self, kind, x, y):
        c = self.c
        c.setDash()
        if kind in ("city", "town"):
            c.setFillColor(black); c.setStrokeColor(white); c.setLineWidth(0.25)
            c.rect(x - 0.9, y - 0.9, 1.8, 1.8, stroke=1, fill=1)
        elif kind in ("village", "hamlet"):
            c.setFillColor(black); c.setStrokeColor(white); c.setLineWidth(0.2)
            c.circle(x, y, 0.6 if kind == "village" else 0.45, stroke=1, fill=1)
        elif kind == "locality":
            c.setFillColor(hexrgb("#555555")); c.circle(x, y, 0.25, stroke=0, fill=1)
        elif kind == "peak":
            p = c.beginPath(); p.moveTo(x - 0.6, y - 0.45); p.lineTo(x + 0.6, y - 0.45); p.lineTo(x, y + 0.6); p.close()
            c.setFillColor(hexrgb("#3e2723")); c.drawPath(p, stroke=0, fill=1)
        elif kind == "pass":
            c.setStrokeColor(hexrgb("#3e2723")); c.setLineWidth(0.2)
            c.arc(x - 1.0, y - 0.6, x - 0.2, y + 0.6, -60, 120); c.arc(x + 0.2, y - 0.6, x + 1.0, y + 0.6, 120, 120)
        elif kind == "camp":
            p = c.beginPath(); p.moveTo(x - 0.75, y - 0.55); p.lineTo(x + 0.75, y - 0.55); p.lineTo(x, y + 0.65); p.close()
            c.setFillColor(hexrgb("#1b5e20")); c.setStrokeColor(white); c.setLineWidth(0.15); c.drawPath(p, stroke=1, fill=1)
        elif kind == "hut":
            c.setFillColor(hexrgb("#4e342e")); c.setStrokeColor(white); c.setLineWidth(0.15)
            c.rect(x - 0.55, y - 0.55, 1.1, 1.1, stroke=1, fill=1)
        elif kind == "trailhead":
            c.setFillColor(hexrgb(TRAIL_COL)); c.setStrokeColor(white); c.setLineWidth(0.2)
            c.circle(x, y, 0.7, stroke=1, fill=1)
            c.setFillColor(white); c.setFont(FB, 1.2); c.drawCentredString(x, y - 0.42, "T")
        elif kind == "parking":
            c.setFillColor(hexrgb("#1565c0")); c.setStrokeColor(white); c.setLineWidth(0.15)
            c.rect(x - 0.6, y - 0.6, 1.2, 1.2, stroke=1, fill=1)
            c.setFillColor(white); c.setFont(FB, 1.25); c.drawCentredString(x, y - 0.43, "P")
        elif kind == "ranger":
            c.setFillColor(hexrgb("#33691e")); c.rect(x - 0.6, y - 0.6, 1.2, 1.2, stroke=0, fill=1)
            c.setFillColor(white); c.setFont(FB, 1.2); c.drawCentredString(x, y - 0.42, "R")
        elif kind == "launch":
            c.setFillColor(hexrgb("#0d47a1")); c.circle(x, y, 0.6, stroke=0, fill=1)
            c.setFillColor(white); c.setFont(FB, 1.15); c.drawCentredString(x, y - 0.4, "B")
        elif kind == "falls":
            c.setStrokeColor(hexrgb("#0d47a1")); c.setLineWidth(0.25)
            for dx in (-0.35, 0, 0.35):
                c.line(x + dx, y + 0.5, x + dx, y - 0.5)
        elif kind == "lookout":
            p = c.beginPath(); p.moveTo(x - 0.6, y - 0.6); p.lineTo(x + 0.6, y - 0.6); p.lineTo(x, y + 0.7); p.close()
            c.setStrokeColor(hexrgb("#b71c1c")); c.setLineWidth(0.2); c.drawPath(p, stroke=1, fill=0)
            c.setFillColor(hexrgb("#b71c1c")); c.circle(x, y - 0.05, 0.22, stroke=0, fill=1)
        elif kind == "view":
            c.setStrokeColor(hexrgb("#4a148c")); c.setLineWidth(0.18); c.circle(x, y, 0.45, stroke=1, fill=0)
            c.setFillColor(hexrgb("#4a148c")); c.circle(x, y, 0.15, stroke=0, fill=1)
        elif kind == "gate":
            c.setStrokeColor(white); c.setLineWidth(0.55); c.line(x - 0.6, y, x + 0.6, y)
            c.setStrokeColor(black); c.setLineWidth(0.3); c.line(x - 0.55, y, x + 0.55, y)
        elif kind == "ford":
            p = c.beginPath(); p.moveTo(x, y + 0.55); p.lineTo(x + 0.55, y); p.lineTo(x, y - 0.55); p.lineTo(x - 0.55, y); p.close()
            c.setFillColor(hexrgb("#0277bd")); c.setStrokeColor(white); c.setLineWidth(0.12); c.drawPath(p, stroke=1, fill=1)
        elif kind == "dam":
            c.setStrokeColor(black); c.setLineWidth(0.45); c.line(x - 0.7, y, x + 0.7, y)
        elif kind == "info":
            c.setFillColor(hexrgb("#0d47a1")); c.circle(x, y, 0.5, stroke=0, fill=1)
            c.setFillColor(white); c.setFont(FB, 1.0); c.drawCentredString(x, y - 0.35, "i")
        # symbols are obstacles for labels
        self.occ.add(box(x - 0.7, y - 0.7, x + 0.7, y + 0.7))

    # labels
    def try_line_label(self, lines, runs, size, halo, spacing, max_n=99, offset=0.0, require_zone=True, min_len_factor=1.0):
        size = shrink(size)
        """Place labels along a set of polylines (same feature). Returns number placed."""
        # merge into chains
        try:
            ml = linemerge(MultiLineString([LineString(p) for p in lines if len(p) > 1]))
        except Exception:
            return 0
        chains = [ml] if isinstance(ml, LineString) else list(getattr(ml, "geoms", []))
        chains = [ch.intersection(self.frame_box.buffer(-1.5)) for ch in chains]
        flat = []
        for ch in chains:
            flat += [list(x.coords) for x in ([ch] if isinstance(ch, LineString) else getattr(ch, "geoms", [])) if isinstance(x, LineString) and len(x.coords) > 1]
        flat.sort(key=lambda p: -LineString(p).length)
        placed = []
        tw = runs_w(runs, size)
        for path in flat:
            if LineString(path).length < tw * min_len_factor:
                continue
            sp_ = LineString(path).simplify(0.25)
            path = list(sp_.coords) if sp_.length > tw else path
            cands = line_candidates(path, runs, size, step=max(1.2, tw / 6), offset=offset)
            cands.sort(key=lambda x: x[0])
            for score, s0, glyphs, shp in cands:
                if len(placed) >= max_n:
                    break
                ctr = shp.centroid
                if require_zone and not self.inside_zone(ctr.x, ctr.y):
                    continue
                if any(ctr.distance(p) < spacing for p in placed):
                    continue
                if not self.label_ok(shp) or self.occ.hits(shp):
                    continue
                self.occ.add(shp)
                placed.append(ctr)
                self.labels.append(("curve", glyphs, size, halo))
        return len(placed)

    def urban_circles(self):
        km = 1e6 / self.scale
        out = []
        for key, n in self.osm["nodes"].items():
            pl = n["t"].get("place")
            if pl in ("city", "town"):
                x, y = self.fr.p(*n["c"])
                out.append((x, y, (19 if pl == "city" else 4.0) * km))
        return out

    def urban(self, x, y):
        return any((x - cx) ** 2 + (y - cy) ** 2 < r * r for cx, cy, r in self.cities)

    def touches_zone(self, lines):
        for p in lines:
            for q in p[:: max(1, len(p) // 8)] + [p[-1]]:
                if self.inside_zone(*q) and not self.urban(*q):
                    return True
        return False

    def tag_label(self, lines, name, kind, col):
        """Last resort for short or crowded features: a small number on the feature, listed with its name on the back."""
        best = max((p for p in lines if len(p) > 1), key=lambda p: LineString(p).length, default=None)
        if not best:
            return 0
        ln = LineString(best)
        num = len(self.tags) + 1
        for f in (0.5, 0.3, 0.7, 0.1, 0.9):
            p = ln.interpolate(f, normalized=True)
            if not (FX0 < p.x < FX1 and FY0 < p.y < FY1) or not self.inside_zone(p.x, p.y):
                continue
            if self.try_point_label(p.x, p.y, [(str(num), FB, col)], 3.8, True, gap=0.3,
                                    positions=("NE", "SE", "NW", "SW", "E", "W", "N", "S")):
                lon, lat = self.fr.inv(p.x, p.y)
                self.tags.append((num, name, kind, self.gridref(lon, lat)))
                return 1
        return 0

    def fallback_label(self, lines, runs, size, require_zone=True):
        """Horizontal label beside the middle of the longest piece, for features too short or too twisty to label along."""
        best = max((p for p in lines if len(p) > 1), key=lambda p: LineString(p).length, default=None)
        if not best:
            return 0
        ln = LineString(best)
        for f in (0.5, 0.3, 0.7, 0.15, 0.85):
            p = ln.interpolate(f, normalized=True)
            if not (FX0 < p.x < FX1 and FY0 < p.y < FY1):
                continue
            if require_zone and not self.inside_zone(p.x, p.y):
                continue
            if self.try_point_label(p.x, p.y, runs, size, True, gap=0.6):
                return 1
        return 0

    def label_ok(self, shp):
        if not self.frame_box.contains(shp):
            return False
        if self.cfg.get("hide_outside"):
            if not hasattr(self, "zone_lbl"):
                from shapely.prepared import prep
                self.zone_lbl = prep(self.zone_mm.buffer(0.3))
            return self.zone_lbl.contains(shp)
        return True

    def try_point_label(self, x, y, runs, size, halo, gap=1.0, positions=("E", "W", "NE", "SE", "NW", "SW", "N", "S")):
        size = shrink(size)
        w = runs_w(runs, size)
        h = size * PT * 0.95
        for pos in positions:
            shp, tx, ty = point_shape(x, y, w, h, pos, gap)
            if not self.label_ok(shp) or self.occ.hits(shp):
                continue
            self.occ.add(shp)
            self.labels.append(("text", tx, ty, runs, size, halo))
            return True
        return False

    def place_labels(self):
        st = self.stats
        km = 1e6 / self.scale
        self.cities = self.urban_circles()
        sm = 1.0 if self.scale <= 400000 else 0.92
        # 1. towns
        rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "locality": 9}
        pl = sorted([p for p in self.pt_labels if p[0] in rank], key=lambda p: rank[p[0]])
        for kind, nm, x, y, ele, inside in pl:
            size = {"city": 11, "town": 9, "village": 7.5, "hamlet": 6.2, "locality": 5.2}[kind] * sm
            font = FB if kind in ("city", "town", "village") else (F if kind == "hamlet" else FI)
            if self.try_point_label(x, y, [(nm, font, "#111111")], size, True, gap=1.3):
                st["lbl_place"] += 1
            else:
                st["miss_place"] += 1
        # 1b. campgrounds, huts, trailheads and other access points (numbered if there is no room for the name)
        self.tags = []
        self.place_pois(("camp", "trailhead", "hut", "ranger", "launch"), sm, tag=True)
        # 2. national / provincial park names (large, green italic) at a point inside the area
        for nm, gm, nat in self.parks:
            if not nm:
                continue
            g = gm.intersection(self.frame_box.buffer(-10))
            if g.is_empty or g.area < 150:
                continue
            p = g.representative_point()
            size = (11 if nat else 6.5) * sm
            if not self.try_point_label(p.x, p.y, [(nm, FBI if nat else FI, PARK_COL)], size, True, positions=("C", "N", "S")):
                # try along the boundary
                self.try_line_label(geom_lines(g.boundary), [(nm, FI, PARK_COL)], 5.0 * sm, True, 200, 1, offset=1.6, require_zone=False)
        # 3. highway shields
        for ref, lines in self.shields.items():
            self.place_shields(ref, lines)
        # 3c. lakes (short labels; the fishing waters come first)
        self.place_water_labels(sm, "lakes")
        # 4. road names (all named roads in the zone)
        rprio = {"hwy": 0, "major": 1, "paved": 2, "gravel": 3, "track": 4}
        import re as _re
        for (nm, cl), lines in sorted(self.road_named.items(), key=lambda kv: (rprio[kv[0][1]], -sum(LineString(p).length for p in kv[1] if len(p) > 1))):
            if not self.touches_zone(lines):
                continue
            if cl not in ("hwy", "major") and _re.search(r"\s(NW|NE|SW|SE)$", nm):
                continue  # city streets (Calgary, Airdrie, Chestermere quadrants)
            size = {"hwy": 5.6, "major": 5.2, "paved": 4.8, "gravel": 4.6, "track": 4.3}[cl] * sm
            col = "#7f1d00" if cl != "track" else "#4e342e"
            n = self.try_line_label(lines, [(nm, FB if cl in ("hwy", "major") else F, col)], size, True, 110, 6, offset=0)
            if not n:
                n = self.try_line_label(lines, [(nm, F, col)], size * 0.85, True, 110, 3, offset=0)
            if not n:
                n = self.fallback_label(lines, [(nm, F, col)], size * 0.85)
                st["lbl_road_fallback"] += n
            if not n:
                n = self.tag_label(lines, nm, "Road", col)
                st["lbl_road_tag"] += n
            st["lbl_road" if n else "miss_road"] += 1
            if not n:
                self.missed.append(("road", nm))
        # 5. trail names
        for nm, lines in sorted(self.trail_named.items(), key=lambda kv: -sum(LineString(p).length for p in kv[1] if len(p) > 1)):
            if not self.touches_zone(lines):
                continue
            size = 4.4 * sm
            n = self.try_line_label(lines, [(nm, FI, TRAIL_COL)], size, True, 90, 5, offset=0)
            if not n:
                n = self.try_line_label(lines, [(nm, FI, TRAIL_COL)], size * 0.85, True, 90, 3, offset=0, min_len_factor=0.9)
            if not n:
                n = self.fallback_label(lines, [(nm, FI, TRAIL_COL)], size * 0.85)
                st["lbl_trail_fallback"] += n
            if not n:
                n = self.tag_label(lines, nm, "Trail", TRAIL_COL)
                st["lbl_trail_tag"] += n
            st["lbl_trail" if n else "miss_trail"] += 1
            if not n:
                self.missed.append(("trail", nm))
        # 6. waters: lakes then streams (name + species codes)
        self.place_water_labels(sm, "streams")
        # 7. peaks, passes and other points
        self.place_pois(("peak", "pass", "lookout", "falls", "dam", "view", "parking", "info"), sm)
        for nm, gm in getattr(self, "glaciers", []):
            p = gm.representative_point()
            if self.inside_zone(p.x, p.y):
                self.try_point_label(p.x, p.y, [(nm, FI, "#4f83a8")], 3.9 * sm, True, positions=("C", "N", "S", "E", "W"))

    def place_pois(self, kinds, sm, tag=False):
        st = self.stats
        order = {k: i for i, k in enumerate(kinds)}
        pk = [p for p in self.pt_labels if p[0] in order and p[5]]
        num = lambda e: float(e) if e.replace(".", "", 1).isdigit() else 0
        pk.sort(key=lambda p: (order[p[0]], -num(str(p[4]).split()[0].replace(",", ".") if p[4] else "0")))
        done = getattr(self, "poi_done", {})
        self.poi_done = done
        for kind, nm, x, y, ele, inside in pk:
            if any(abs(x - a) < 12 and abs(y - b) < 12 for a, b in done.get(nm.lower(), [])):
                continue  # same place mapped twice (point and area)
            done.setdefault(nm.lower(), []).append((x, y))
            col = {"peak": "#3e2723", "pass": "#3e2723", "camp": "#1b5e20", "hut": "#4e342e", "trailhead": TRAIL_COL, "falls": "#0d47a1",
                   "launch": "#0d47a1", "dam": "#263238", "ranger": "#33691e"}.get(kind, "#333333")
            if nm.isupper():
                nm = nm.title()
            runs = [(nm, FI if kind in ("peak", "pass") else (FB if kind == "camp" else F), col)]
            if kind == "peak" and ele:
                e = str(ele).split()[0].replace(",", ".")
                try:
                    runs.append((f" {round(float(e)):,}".replace(",", " "), F, col))
                except ValueError:
                    pass
            size = {"peak": 4.4, "pass": 4.2, "camp": 4.4}.get(kind, 4.1) * sm
            if self.try_point_label(x, y, runs, size, True, gap=1.0):
                st["lbl_" + kind] += 1
            elif self.try_point_label(x, y, [(nm, runs[0][1], col)], size * 0.85, True, gap=0.9):
                st["lbl_" + kind] += 1
            elif tag and self.try_point_label(x, y, [(str(len(self.tags) + 1), FB, col)], 4.2, True, gap=0.8):
                lon, lat = self.fr.inv(x, y)
                self.tags.append((len(self.tags) + 1, nm, {"camp": "Campground", "hut": "Hut", "trailhead": "Trailhead",
                                                            "ranger": "Ranger station", "launch": "Boat launch"}.get(kind, kind), self.gridref(lon, lat)))
                st["tag_" + kind] += 1
            else:
                st["miss_" + kind] += 1
                if kind in ("camp", "trailhead", "hut"):
                    self.missed.append((kind, nm))

    def place_shields(self, ref, lines):
        try:
            ml = linemerge(MultiLineString([LineString(p) for p in lines if len(p) > 1]))
        except Exception:
            return
        chains = [ml] if isinstance(ml, LineString) else list(ml.geoms)
        placed = []
        txt = ref if not ref.isdigit() else ref
        size = shrink(5.2 if len(ref) <= 3 else 4.6)
        w = stringWidth(txt, FB, size) * PT + 1.4
        h = size * PT + 0.9
        for ch in sorted(chains, key=lambda g: -g.length):
            L = ch.length
            d = 25.0
            while d < L:
                p = ch.interpolate(d)
                d += 12
                if not (FX0 + 4 < p.x < FX1 - 4 and FY0 + 4 < p.y < FY1 - 4):
                    continue
                if any(p.distance(q) < 140 for q in placed):
                    continue
                shp = box(p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2)
                if self.occ.hits(shp) or not self.label_ok(shp):
                    continue
                self.occ.add(shp)
                placed.append(p)
                major = ref.isdigit() and int(ref) < 100
                self.labels.append(("shield", p.x, p.y, txt, size, w, h, major))

    def place_water_labels(self, sm, part="all"):
        st = self.stats
        lake_items, stream_items = [], []
        for ch, arr in self.chunks.items():
            for f in arr:
                it = self.byid.get(f.get("id"))
                if not it or it["id"] in OWNER_HIDE:
                    continue
                sp = sel_only(all_sp(it))
                if it["k"] == "l":
                    lake_items.append((f, it, sp))
                else:
                    stream_items.append((f, it, sp))
        # also name the bigger lakes without game fish records
        nofish = []
        for ch, arr in self.chunks.items():
            for f in arr:
                if f.get("k") == "l" and f.get("g") and f.get("n") and f["id"] not in self.byid:
                    nofish.append(f)

        def code_runs(sp):
            out = []
            for i, cd in enumerate(sorted(sp, key=lambda c: RARITY.index(c) if c in RARITY else 99)):
                out.append((("" if i == 0 else " ") + cd, FB, sp_color(cd)))
            return out

        def lake_area(f):
            try:
                return Polygon(self.P(f["g"][0])).area
            except Exception:
                return 0
        lake_items.sort(key=lambda x: (-len(x[2]) > 0, -lake_area(x[0])))
        if part == "streams":
            lake_items, nofish = [], []
        for f, it, sp in lake_items:
            pts = self.P(f["g"][0])
            pg = Polygon(pts) if len(pts) > 2 else None
            if pg is None or pg.is_empty:
                continue
            x, y = pg.representative_point().x, pg.representative_point().y
            if not self.inside_zone(x, y) or not (FX0 < x < FX1 and FY0 < y < FY1):
                continue
            nm = disp_name(it)
            dag = " †" if listing_ids(it) else ""
            size = (5.0 if pg.area > 12 else 4.4) * sm
            runs = ([(nm + dag, FI, "#0b4f7c")] if nm else []) + ([(" " if nm else "", F, "#000")] if sp else []) + code_runs(sp)
            if not runs:
                continue
            r = math.sqrt(max(pg.area, 0.3) / math.pi)
            if pg.area > 60 and self.try_point_label(x, y, runs, size, True, positions=("C",)):
                st["lbl_lake"] += 1
                continue
            if self.try_point_label(pg.centroid.x, pg.centroid.y, runs, size, True, gap=r + 0.5):
                st["lbl_lake"] += 1
            elif nm and sp and self.try_point_label(pg.centroid.x, pg.centroid.y, code_runs(sp), size * 0.9, True, gap=r + 0.4):
                st["lbl_lake_codes"] += 1
            else:
                st["miss_lake"] += 1
        for f in sorted(nofish, key=lambda f: -lake_area(f)):
            pts = self.P(f["g"][0])
            if len(pts) < 3:
                continue
            pg = Polygon(pts)
            if pg.area < 2:
                continue
            p = pg.representative_point()
            if not self.inside_zone(p.x, p.y):
                continue
            if self.try_point_label(p.x, p.y, [(f["n"], FI, "#0b4f7c")], 4.2 * sm, True, gap=math.sqrt(pg.area / math.pi) + 0.4):
                st["lbl_lake_nofish"] += 1
        if part == "lakes":
            return
        # streams: by order, name + codes along the stream, repeated on long rivers
        stream_items.sort(key=lambda x: -(x[1].get("o") or 1))
        for f, it, sp in stream_items:
            nm = disp_name(it)
            if not nm and not sp:
                continue
            lines = [self.P(p) for r in f.get("r") or [] for p in r["g"]]
            o = it.get("o") or 1
            size = (6.0 if o >= 6 else 5.2 if o >= 5 else 4.6 if o >= 3 else 4.2) * sm
            dag = " †" if listing_ids(it) else ""
            runs = ([(nm + dag, FI, "#0b4f7c")] + ([("  ", F, "#000")] if sp else []) if nm else []) + (code_runs(sp) if sp else [])
            n = self.try_line_label(lines, runs, size, True, 130 if o >= 5 else 160, 6, offset=size * PT * 0.25 + 0.6)
            if not n and sp:
                n = self.try_line_label(lines, [(nm + dag, FI, "#0b4f7c")], size, True, 150, 3, offset=size * PT * 0.25 + 0.6)
                # codes on their own
                n2 = self.try_line_label(lines, code_runs(sp), size * 0.9, True, 150, 2, offset=size * PT * 0.25 + 0.6)
                n = n or n2
            if not n:
                n = self.fallback_label(lines, runs, size * 0.9)
            st["lbl_stream" if n else "miss_stream"] += 1
        # streams without game fish: names of the bigger ones
        for ch, arr in self.chunks.items():
            for f in arr:
                if f.get("k") == "s" and f.get("n") and f["id"] not in self.byid and (f.get("o") or 1) >= 3:
                    lines = [self.P(p) for r in f.get("r") or [] for p in r["g"]]
                    self.try_line_label(lines, [(f["n"], FI, "#0b4f7c")], 4.2 * sm, True, 160, 2, offset=1.4)

    def flush_labels(self):
        c = self.c
        for L in self.labels:
            if L[0] == "curve":
                _, glyphs, size, halo = L
                sz = size * PT
                for pass_ in ((0, 1) if halo else (1,)):
                    for x, y, ang, ch, font, col in glyphs:
                        c.saveState()
                        c.translate(x, y); c.rotate(ang)
                        t = c.beginText(0, 0)
                        t.setFont(font, sz)
                        if pass_ == 0:
                            t.setTextRenderMode(1)
                            c.setStrokeColor(white); c.setLineWidth(sz * 0.18); c.setLineJoin(1)
                        else:
                            t.setTextRenderMode(0)
                            c.setFillColor(hexrgb(col))
                        t.textOut(ch)
                        c.drawText(t)
                        c.restoreState()
            elif L[0] == "text":
                _, x, y, runs, size, halo = L
                sz = size * PT
                for pass_ in ((0, 1) if halo else (1,)):
                    c.saveState()
                    t = c.beginText(x, y)
                    for txt, font, col in runs:
                        t.setFont(font, sz)
                        if pass_ == 0:
                            t.setTextRenderMode(1)
                            c.setStrokeColor(white); c.setLineWidth(sz * 0.18); c.setLineJoin(1)
                        else:
                            t.setTextRenderMode(0)
                            t.setFillColor(hexrgb(col))
                        t.textOut(txt)
                    c.drawText(t)
                    c.restoreState()
            elif L[0] == "shield":
                _, x, y, txt, size, w, h, major = L
                c.setFillColor(hexrgb("#c62828" if major else "#ffffff")); c.setStrokeColor(hexrgb("#c62828")); c.setLineWidth(0.22)
                c.roundRect(x - w / 2, y - h / 2, w, h, 0.5, stroke=1, fill=1)
                c.setFillColor(white if major else hexrgb("#c62828")); c.setFont(FB, size * PT)
                c.drawCentredString(x, y - size * PT * 0.33, txt)

    # ----- frame, margins, panels -----
    def draw_frame(self):
        c = self.c
        c.setStrokeColor(black); c.setLineWidth(0.35); c.rect(FX0, FY0, FX1 - FX0, FY1 - FY0, stroke=1, fill=0)
        c.setLineWidth(0.15); c.rect(FX0 - 3.5, FY0 - 3.5, FX1 - FX0 + 7, FY1 - FY0 + 7, stroke=1, fill=0)
        # graticule ticks + labels + grid letters/numbers in the margin
        c.setFont(F, 2.1)
        c.setFillColor(black)
        i = 0
        lon = self.g_w
        while lon < self.g_e - 1e-9:
            for edge_y, dy in ((FY1, 1), (FY0, -1)):
                # where the meridian crosses the edge
                xs = [self.fr.p(lon, la) for la in np.linspace(self.g_s, self.g_n, 400)]
                best = min(xs, key=lambda q: abs(q[1] - edge_y))
                if FX0 < best[0] < FX1:
                    c.setLineWidth(0.2); c.line(best[0], edge_y, best[0], edge_y + 2.5 * dy)
                    d, m = int(abs(lon)), round((abs(lon) - int(abs(lon))) * 60)
                    c.setFont(F, 2.0); c.drawCentredString(best[0], edge_y + (3.2 if dy > 0 else -4.8), f"{d}°{m:02d}'W")
            i += 1
            lon += self.gd
        # letters inside the outer margin band (between neatline and outer line)
        i = 0
        lon = self.g_w
        while lon < self.g_e - 1e-9:
            for edge_y, off in ((FY1, 1.0), (FY0, -3.0)):
                xs2 = [self.fr.p(lon + self.gd / 2, la) for la in np.linspace(self.g_s, self.g_n, 400)]
                b2 = min(xs2, key=lambda q: abs(q[1] - edge_y))
                if FX0 + 2 < b2[0] < FX1 - 2:
                    c.setFont(FB, 3.0); c.setFillColor(hexrgb("#37474f"))
                    c.drawCentredString(b2[0], edge_y + (4.6 if off > 0 else -7.4), self.col_letter(i))
            i += 1
            lon += self.gd
        j = 0
        lat = self.g_n
        while lat > self.g_s + 1e-9:
            for edge_x, dx in ((FX0, -1), (FX1, 1)):
                ys = [self.fr.p(lo, lat) for lo in np.linspace(self.g_w, self.g_e, 400)]
                best = min(ys, key=lambda q: abs(q[0] - edge_x))
                if FY0 < best[1] < FY1:
                    c.setStrokeColor(black); c.setLineWidth(0.2); c.line(edge_x, best[1], edge_x + 2.5 * dx, best[1])
                    d, m = int(lat), round((lat - int(lat)) * 60)
                    c.saveState(); c.translate(edge_x + (4.4 if dx > 0 else -3.0), best[1]); c.rotate(90)
                    c.setFillColor(black); c.setFont(F, 2.0); c.drawCentredString(0, 0, f"{d}°{m:02d}'N"); c.restoreState()
                ys2 = [self.fr.p(lo, lat - self.gd / 2) for lo in np.linspace(self.g_w, self.g_e, 400)]
                b2 = min(ys2, key=lambda q: abs(q[0] - edge_x))
                if FY0 + 2 < b2[1] < FY1 - 2:
                    c.setFillColor(hexrgb("#37474f")); c.setFont(FB, 3.0)
                    c.drawCentredString(edge_x + (8.4 if dx > 0 else -8.2), b2[1] - 1.0, str(j + 1))
            j += 1
            lat -= self.gd
        # fold marks (A1 folds to A4 panels: 2 across, 4 down)
        c.setStrokeColor(hexrgb("#9e9e9e")); c.setLineWidth(0.2)
        for x in (PAGE_W / 2,):
            c.line(x, 1.5, x, 6.0); c.line(x, PAGE_H - 1.5, x, PAGE_H - 6.0)
        for k in (1, 2, 3):
            y = PAGE_H * k / 4
            c.line(1.5, y, 6.0, y); c.line(PAGE_W - 1.5, y, PAGE_W - 6.0, y)
        c.setFont(F, 1.8); c.setFillColor(hexrgb("#9e9e9e"))
        c.drawString(PAGE_W / 2 + 1.2, 2.2, "fold")

    def layout_panels(self):
        """Put the title block and the legend against the frame edges where they cover the least of the zone."""
        tw, th = 188.0, 160.0
        lw, lh = 188.0, 322.0
        zone = self.zone_mm.buffer(3)

        def spots(w, h):
            out = []
            for y in np.arange(FY0, FY1 - h + 0.1, 5.0):
                out.append((FX0, y, FX0 + w, y + h))
                out.append((FX1 - w, y, FX1, y + h))
            for x in np.arange(FX0, FX1 - w + 0.1, 5.0):
                out.append((x, FY0, x + w, FY0 + h))
                out.append((x, FY1 - h, x + w, FY1))
            return out
        best = None
        for tb in spots(tw, th):
            to = box(*tb).intersection(zone).area
            if best and to > best[0]:
                continue
            for lb in spots(lw, lh):
                if box(*lb).intersects(box(*tb).buffer(4)):
                    continue
                tot = to + box(*lb).intersection(zone).area
                if best is None or tot < best[0]:
                    best = (tot, tb, lb)
        self.title_box, self.legend_box = best[1], best[2]
        print("panels", [round(v) for v in self.title_box], [round(v) for v in self.legend_box], "overlap", round(best[0]), file=sys.stderr)
        self.add_panel(*self.title_box)
        self.add_panel(*self.legend_box)

    def draw_panels(self):
        from panels import draw_title, draw_legend
        draw_title(self, *self.title_box)
        draw_legend(self, *self.legend_box)


def main():
    keys = [a for a in sys.argv[1:] if not a.startswith("--")] or list(MAPS)
    draft = "--draft" in sys.argv
    from pypdf import PdfWriter, PdfReader
    for key in keys:
        t0 = time.time()
        m = WallMap(key, draft)
        m.missed = []
        m.load()
        m.render()
        print(key, dict(m.stats), file=sys.stderr)
        miss = defaultdict(list)
        for k, n in m.missed:
            miss[k].append(n)
        for k, v in miss.items():
            print(f"unlabelled {k}: {len(v)}: {', '.join(sorted(set(v))[:60])}", file=sys.stderr)
        # back page
        bk = os.path.join(OUTDIR, f"_back_{key}.pdf")
        zones = m.cfg["zones"]
        eff = (REGS.get("meta") or {}).get("effective") or ["", ""]
        build_back(bk, f"{' + '.join(zones)} water-specific fishing regulations",
                   f"Alberta Guide to Sportfishing Regulations, {eff[0]} to {eff[1]} · tables as in the guide · map grid squares refer to the other side",
                   zones, m.gridref, lambda it: m.in_frame_ll(*it["c"]),
                   footer=f"Eastern Slopes Trout Map wall map {key} · back · printed {datetime.date.today().isoformat()} · "
                          "georgeclaudevandam-sketch.github.io/SW-AB-Flyfishing", tags=m.tags)
        out = os.path.join(OUTDIR, f"Eastern-Slopes-Trout-Map_{key}_A1.pdf")
        w = PdfWriter()
        for p in (m.front, bk):
            for pg in PdfReader(p).pages:
                w.add_page(pg)
        w.add_metadata({"/Title": m.cfg["title"] + " (A1 wall map)", "/Author": "Eastern Slopes Trout Map"})
        with open(out, "wb") as f:
            w.write(f)
        print(f"wrote {out} ({os.path.getsize(out) // 1024} KB) in {round(time.time() - t0)} s", file=sys.stderr)


if __name__ == "__main__":
    main()
