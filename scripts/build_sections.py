#!/usr/bin/env python3
"""Split listed rivers into their regulation sections, and give tributaries their parent's section.

Reads data/regs/regs.json (from build_regs.py) and scripts/reg_sections.json (where each section starts and
ends, in the regulation's own words), locates each break on the river, and writes back into regs.json:
  w[id][2] = {listing index: [section indices for each reach of the water, or null]}
  w[id][3] = [listing indices this water gets as a tributary of a listed stream]
plus data/regs/sections_log.json describing how every break was located (or why it couldn't be).

Rivers are measured as distance upstream from their mouth along the FWMIS stream lines (which run downstream).
Tributaries: every stream reach upstream of a confluence with the listed river, stopping at streams that have
their own listing in the zone or are named as exceptions.
"""
import glob, json, math, os, re, sys, urllib.parse, urllib.request
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
AB_ROADS = "https://geospatial.alberta.ca/titan/rest/services/transportation/access_facility_roads/MapServer/0/query"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = {"User-Agent": "sw-ab-flyfishing-data-build/1.0 (GitHub Actions)", "Accept": "*/*"}
LOG = {}


def http(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def mxy(lat):
    return 111320 * math.cos(math.radians(lat)), 110540.0


def dist(a, b):  # [lon, lat]
    kx, ky = mxy(a[1])
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * ky)


def seg_x(p1, p2, p3, p4):
    """Intersection point of segments p1-p2 and p3-p4 (lon/lat, small enough to treat as planar), or None."""
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if d == 0:
        return None
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    if 0 <= t <= 1 and 0 <= u <= 1:
        return [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])]
    return None


def ats(s):
    """'LSD-SEC-TWP-RGE-W#' or 'SEC-TWP-RGE-W#' -> approximate [lon, lat] (same survey model as build_regs.ats)."""
    m = re.match(r"(?:(\d{1,2})-)?(\d{1,2})-(\d{1,3})-(\d{1,2})-W([4-6])$", s)
    lsd, sec, twp, rge, mer = (int(m.group(1)) if m.group(1) else None), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    mile, tw, rw = 1609.344, 9760.0, 9790.0
    row, col = (sec - 1) // 6, (sec - 1) % 6
    ce = col if row % 2 == 0 else 5 - col   # sections: 1-6 east to west, 7-12 west to east, ...
    n = (twp - 1) * tw + row * mile
    w = (rge - 1) * rw + ce * mile
    if lsd:  # legal subdivisions: 1-4 east to west, 5-8 west to east, ... quarter mile each
        lr, lc = (lsd - 1) // 4, (lsd - 1) % 4
        lce = lc if lr % 2 == 0 else 3 - lc
        n += (lr + 0.5) * mile / 4
        w += (lce + 0.5) * mile / 4
    else:
        n += mile / 2
        w += mile / 2
    lat = 49 + n / 111200.0
    lon = {4: -110.0, 5: -114.0, 6: -118.0}[mer] - w / (111320.0 * math.cos(math.radians(lat)))
    return [lon, lat]


class River:
    """One FWMIS stream: reaches with distance upstream from the mouth at every vertex."""

    def __init__(self, wid, reaches):
        self.id = wid
        self.reaches = reaches            # list of reach dicts {g: [[ [lon,lat],... ], ...]}
        self.parts = []                   # (reach index, line)
        for k, r in enumerate(reaches):
            for ln in r["g"]:
                if len(ln) >= 2:
                    self.parts.append((k, ln))
        self._measure()

    def _measure(self):
        n = len(self.parts)
        start = defaultdict(list)
        for i, (_, ln) in enumerate(self.parts):
            start[tuple(ln[0])].append(i)
        succ = {}
        for i, (_, ln) in enumerate(self.parts):
            nx = [j for j in start.get(tuple(ln[-1]), []) if j != i]
            if nx:
                succ[i] = nx[0]
        L = [sum(dist(ln[j - 1], ln[j]) for j in range(1, len(ln))) for _, ln in self.parts]
        # Components joined by successor links; the one with the most length holds the mouth.
        comp = list(range(n))

        def find(a):
            while comp[a] != a:
                comp[a] = comp[comp[a]]
                a = comp[a]
            return a
        for i, j in succ.items():
            comp[find(i)] = find(j)
        tot = defaultdict(float)
        for i in range(n):
            tot[find(i)] += L[i]
        main = max(tot, key=tot.get) if tot else None
        dend = {}

        def d_end(i, seen=()):
            if i in dend:
                return dend[i]
            if i in succ and succ[i] not in seen:
                j = succ[i]
                v = d_end(j, seen + (i,)) + L[j]
            elif find(i) == main:
                v = 0.0
            else:
                # Gap (e.g. a lake): continue at the nearest vertex of the main component.
                e = self.parts[i][1][-1]
                best = None
                for j in range(n):
                    if find(j) != main:
                        continue
                    for vi, p in enumerate(self.parts[j][1]):
                        dd = dist(e, p)
                        if best is None or dd < best[0]:
                            best = (dd, j, vi)
                if best is None:
                    v = 0.0
                else:
                    dd, j, vi = best
                    v = d_end(j, seen + (i,)) + sum(dist(self.parts[j][1][q - 1], self.parts[j][1][q]) for q in range(vi + 1, len(self.parts[j][1]))) + dd
            dend[i] = v
            return v
        sys.setrecursionlimit(100000)
        self.vd = []     # per part: distance from mouth at each vertex
        for i, (_, ln) in enumerate(self.parts):
            de = d_end(i)
            ds = [0.0] * len(ln)
            acc = de
            ds[-1] = acc
            for j in range(len(ln) - 2, -1, -1):
                acc += dist(ln[j], ln[j + 1])
                ds[j] = acc
            self.vd.append(ds)

    def reach_mid_d(self):
        out = {}
        for i, (k, ln) in enumerate(self.parts):
            m = len(ln) // 2
            out.setdefault(k, []).append(self.vd[i][m])
        return {k: sorted(v)[len(v) // 2] for k, v in out.items()}

    def nearest(self, p, reaches=None):
        """(metres, d) of the river point nearest p."""
        best = None
        kx, ky = mxy(p[1])
        for i, (k, ln) in enumerate(self.parts):
            if reaches is not None and k not in reaches:
                continue
            for j in range(1, len(ln)):
                a, b = ln[j - 1], ln[j]
                ax, ay = (a[0] - p[0]) * kx, (a[1] - p[1]) * ky
                bx, by = (b[0] - p[0]) * kx, (b[1] - p[1]) * ky
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = max(0, min(1, -(ax * dx + ay * dy) / l2)) if l2 else 0
                dd = math.hypot(ax + t * dx, ay + t * dy)
                if best is None or dd < best[0]:
                    best = (dd, self.vd[i][j - 1] + t * (self.vd[i][j] - self.vd[i][j - 1]))
        return best

    def bbox(self, pad=0.02):
        xs = [p[0] for _, ln in self.parts for p in ln]
        ys = [p[1] for _, ln in self.parts for p in ln]
        return [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]

    def crossings(self, lines, reaches=None):
        """d of each place where any of `lines` crosses the river, clustered within 300 m along the river."""
        ds = []
        lb = [(rl, min(p[0] for p in rl), min(p[1] for p in rl), max(p[0] for p in rl), max(p[1] for p in rl)) for rl in lines]
        for i, (k, ln) in enumerate(self.parts):
            if reaches is not None and k not in reaches:
                continue
            bx = [min(p[0] for p in ln), min(p[1] for p in ln), max(p[0] for p in ln), max(p[1] for p in ln)]
            for rl, x0, y0, x1, y1 in lb:
                if x1 < bx[0] or x0 > bx[2] or y1 < bx[1] or y0 > bx[3]:
                    continue
                for j in range(1, len(ln)):
                    for q in range(1, len(rl)):
                        x = seg_x(ln[j - 1], ln[j], rl[q - 1], rl[q])
                        if x:
                            f = dist(ln[j - 1], x) / max(dist(ln[j - 1], ln[j]), 1e-9)
                            ds.append((self.vd[i][j - 1] + f * (self.vd[i][j] - self.vd[i][j - 1]), x))
        ds.sort()
        cl = []
        for d, x in ds:
            if cl and d - cl[-1][-1][0] < 300:
                cl[-1].append((d, x))
            else:
                cl.append([(d, x)])
        return [(sum(d for d, _ in c) / len(c), c[0][1]) for c in cl]


_RC = {}


def ab_roads(bbox, where):
    key = (tuple(round(x, 3) for x in bbox), where)
    if key not in _RC:
        try:
            _RC[key] = _ab_roads(bbox, where)
        except Exception as e:
            print("roads query failed", where, e, file=sys.stderr)
            _RC[key] = []
    return _RC[key]


def _ab_roads(bbox, where):
    feats, off = [], 0
    while True:
        j = http(AB_ROADS, {"where": where, "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                            "spatialRel": "esriSpatialRelIntersects", "outFields": "HWY_NUMBER,NAME,FEATURE_TYPE", "returnGeometry": "true",
                            "outSR": "4326", "f": "geojson", "resultOffset": str(off), "resultRecordCount": "2000"})
        fs = j.get("features", [])
        feats += fs
        if len(fs) < 2000:
            break
        off += 2000
    lines = []
    for f in feats:
        g = f.get("geometry") or {}
        ls = [g["coordinates"]] if g.get("type") == "LineString" else g.get("coordinates", []) if g.get("type") == "MultiLineString" else []
        for ln in ls:
            lines.append((f["properties"], ln))
    return lines


def overpass(q):
    import time
    for k in range(6):
        try:
            return http(OVERPASS[k % len(OVERPASS)], {"data": q}, timeout=90)
        except Exception as e:
            print("overpass retry", OVERPASS[k % len(OVERPASS)], e, file=sys.stderr)
            time.sleep(5 * (k + 1))
    return {"elements": [], "failed": True}


def resolve(b, R, zone_reaches, ctx):
    """Distance from the mouth (m) of a break, or (None, why)."""
    if b == "head":
        return max(d for k, d in ctx["mid"].items() if k in zone_reaches) + 1, "uppermost mapped stretch in the zone"
    if b == "mouth":
        return -1.0, "mouth"
    if "unresolved" in b:
        return None, "not located: " + b["unresolved"]
    if b.get("mouth"):
        return float(b.get("offset", 0)), f"{b.get('offset', 0)} m above the mouth"
    bb = ctx["bbox"]
    if "road" in b and isinstance(b["road"], str) and not b.get("ats") and not b.get("osm"):
        r = b["road"]
        if r.isdigit():
            lines = [ln for p, ln in ab_roads(bb, f"HWY_NUMBER LIKE '%{r}%'") if re.sub(r"^0+", "", str(p.get("HWY_NUMBER") or "").strip()) == r]
            what = f"Highway {r}"
        else:
            lines = [ln for p, ln in ab_roads(bb, f"UPPER(NAME) LIKE '{r.upper().replace(' ROAD', '')}%'")]
            what = r
        xs = R.crossings(lines, None)
        if len(xs) == 1:
            return xs[0][0], f"{what} crosses at {xs[0][1][1]:.5f}, {xs[0][1][0]:.5f}"
        return None, f"{what}: {len(xs)} crossings" + (" at " + "; ".join(f"{x[1]:.4f},{x[0]:.4f}" for _, x in xs[:5]) if xs else "")
    if "trib" in b:
        hits = []
        for t in ctx["by_name"].get(b["trib"].lower(), []):
            if t.id == R.id:
                continue
            # the tributary's mouth: end of its downstream-most part
            mouth_pt = min(((t.vd[i][-1], ln[-1]) for i, (_, ln) in enumerate(t.parts)), key=lambda x: x[0])[1]
            n = R.nearest(mouth_pt)
            if n and n[0] < 250:
                hits.append((n[1], mouth_pt))
        ds = sorted(set(round(h[0]) for h in hits))
        if len(ds) == 1 or (ds and ds[-1] - ds[0] < 300):
            return hits[0][0], f"mouth of {b['trib']} at {hits[0][1][1]:.5f}, {hits[0][1][0]:.5f}"
        return None, f"{b['trib']}: {len(ds)} confluences found"
    if "lake" in b:
        cands = []
        for lk in ctx["lakes"].get(b["lake"].lower(), []):
            pts = []
            for i, (k, ln) in enumerate(R.parts):
                for j, p in enumerate(ln):
                    if lk["bb"][0] - 0.003 <= p[0] <= lk["bb"][2] + 0.003 and lk["bb"][1] - 0.003 <= p[1] <= lk["bb"][3] + 0.003 and near_poly(p, lk["g"], 150):
                        pts.append((R.vd[i][j], p))
            if pts:
                cands.append(pts)
        if len(cands) != 1:
            return None, f"{b['lake']}: {'not on the river' if not cands else 'several lakes with this name on the river'}"
        pts = sorted(cands[0])
        d, p = (pts[-1] if b.get("end") == "in" else pts[0])
        d += float(b.get("offset", 0))
        return d, f"{b['lake']} {'inlet' if b.get('end') == 'in' else 'outlet'} at {p[1]:.5f}, {p[0]:.5f}" + (f", {b.get('offset')} m" if b.get("offset") else "")
    if "osm" in b or "ats" in b:
        if "osm" in b:
            if b.get("boundary"):
                j = overpass(f'[out:json][timeout:120];relation["name"="{b["osm"]}"]({bb[1]},{bb[0]},{bb[3]},{bb[2]});out geom;')
                lines = [[[pt["lon"], pt["lat"]] for pt in m["geometry"]] for el in j.get("elements", []) for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
                xs = R.crossings(lines, zone_reaches)
                if len(xs) == 1:
                    return xs[0][0], f"{b['osm']} boundary (OpenStreetMap) crosses at {xs[0][1][1]:.5f}, {xs[0][1][0]:.5f}"
                return None, f"{b['osm']} boundary: {len(xs)} crossings"
            tag = '["waterway"="waterfall"]' if b.get("falls") else ""
            j = overpass(f'[out:json][timeout:120];nwr{tag}["name"~"^{re.escape(b["osm"])}",i]({bb[1]},{bb[0]},{bb[3]},{bb[2]});out center;')
            pts = []
            for el in j.get("elements", []):
                c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
                if c:
                    pts.append(([c["lon"], c["lat"]], el.get("tags", {}).get("name", "")))
            if not pts:
                return None, f"{b['osm']}: " + ("OpenStreetMap did not answer" if j.get("failed") else "not found in OpenStreetMap")
            near = [(R.nearest(p, zone_reaches), p, nm) for p, nm in pts]
            near = [(n, p, nm) for n, p, nm in near if n and n[0] < (1500 if b.get("road") else 400)]
            if not near:
                return None, f"{b['osm']}: found in OpenStreetMap but not beside the river"
            if not b.get("road"):
                ds = sorted(n[1] for n, _, _ in near)
                if ds[-1] - ds[0] > 500:
                    return None, f"{b['osm']}: several places beside the river"
                n, p, nm = near[0]
                return n[1], f"{nm} (OpenStreetMap) at {p[1]:.5f}, {p[0]:.5f}"
            ref = near[0][1]
            label = f"{near[0][2]} (OpenStreetMap)"
        else:
            ref = ats(b["ats"])
            label = f"location {b['ats']}"
            if b.get("falls"):
                j = overpass(f'[out:json][timeout:60];node["waterway"="waterfall"](around:2500,{ref[1]},{ref[0]});out;')
                near = [(R.nearest([el["lon"], el["lat"]], zone_reaches), el) for el in j.get("elements", [])]
                near = [(n, el) for n, el in near if n and n[0] < 300]
                if len(near) == 1:
                    n, el = near[0]
                    return n[1], f"waterfall (OpenStreetMap) at {el['lat']:.5f}, {el['lon']:.5f}, near {label}"
                return None, f"{label}: {len(near)} mapped waterfalls on the river within 2.5 km"
            if not b.get("road"):
                n = R.nearest(ref, zone_reaches)
                if n and n[0] < 2500:
                    return n[1], f"river point nearest {label} ({n[0]:.0f} m)"
                return None, f"{label}: river not within 2.5 km"
        # bridge: the road crossing of the river nearest the reference point (within 2.5 km)
        box = [ref[0] - 0.05, ref[1] - 0.03, ref[0] + 0.05, ref[1] + 0.03]
        rl = ab_roads(box, "FEATURE_TYPE IN (2,3,4,5,6,7,8,9,10,14)")
        lines = [ln for p, ln in rl]
        if "osm" in b:
            jb = overpass(f'[out:json][timeout:60];way["bridge"](around:2500,{ref[1]},{ref[0]});out geom;')
            lines += [[[q["lon"], q["lat"]] for q in el["geometry"]] for el in jb.get("elements", []) if el.get("geometry")]
        xs = R.crossings(lines, None)
        xs = sorted(((dist(ref, x), d, x) for d, x in xs))
        xs = [t for t in xs if t[0] < 2500]
        if not xs:
            return None, f"{label}: no road crossing within 2.5 km"
        if len(xs) > 1 and xs[1][0] - xs[0][0] < 400:
            return None, f"{label}: {len(xs)} road crossings at similar distance"
        rn = [p for p, ln in rl if any(dist(q, xs[0][2]) < 60 for q in ln)]
        rname = (", " + " / ".join(sorted({(("Hwy " + str(p.get("HWY_NUMBER")).lstrip("0")) if p.get("HWY_NUMBER") else (p.get("NAME") or "unnamed road")) for p in rn}))) if rn else ""
        return xs[0][1], f"road crossing{rname} nearest {label} at {xs[0][2][1]:.5f}, {xs[0][2][0]:.5f} ({xs[0][0]:.0f} m away)"
    return None, "unknown break " + json.dumps(b)


def near_poly(p, g, m):
    """p inside polygon g (list of rings or multipolygon) or within m metres of its outline."""
    rings = []

    def walk(x):
        if isinstance(x[0][0], (int, float)):
            rings.append(x)
        else:
            for y in x:
                walk(y)
    walk(g)
    ins = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            if (ring[i][1] > p[1]) != (ring[j][1] > p[1]) and p[0] < (ring[j][0] - ring[i][0]) * (p[1] - ring[i][1]) / (ring[j][1] - ring[i][1]) + ring[i][0]:
                ins = not ins
            j = i
    if ins:
        return True
    kx, ky = mxy(p[1])
    for ring in rings:
        for i in range(1, len(ring)):
            a, b = ring[i - 1], ring[i]
            ax, ay = (a[0] - p[0]) * kx, (a[1] - p[1]) * ky
            bx, by = (b[0] - p[0]) * kx, (b[1] - p[1]) * ky
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = max(0, min(1, -(ax * dx + ay * dy) / l2)) if l2 else 0
            if math.hypot(ax + t * dx, ay + t * dy) < m:
                return True
    return False


def main():
    regs = json.load(open(os.path.join(ROOT, "data", "regs", "regs.json")))
    spec = json.load(open(os.path.join(ROOT, "scripts", "reg_sections.json")))
    W, LIST = regs["w"], regs["list"]
    idx = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "water", "index.json")))["items"]}
    streams, lakes = {}, defaultdict(list)
    names = {}
    for fn in glob.glob(os.path.join(ROOT, "data", "water", "c_*.json")):
        for w in json.load(open(fn)):
            it = idx.get(w["id"], {})
            nm = it.get("n") or it.get("a") or w.get("n")
            if w["id"].startswith("s") and w.get("r"):
                streams[w["id"]] = w["r"]
                if nm:
                    names[w["id"]] = nm
            elif w["id"].startswith("l") and nm and w.get("g"):
                xs, ys = [], []

                def walk(x):
                    if isinstance(x[0], (int, float)):
                        xs.append(x[0]); ys.append(x[1])
                    else:
                        for y in x:
                            walk(y)
                walk(w["g"])
                lakes[nm.lower()].append({"id": w["id"], "g": w["g"], "bb": [min(xs), min(ys), max(xs), max(ys)]})
    print("streams", len(streams), file=sys.stderr, flush=True)
    # Global stream graph for tributary walks: reaches ending at each node.
    ends_at = defaultdict(list)          # node -> [(water, reach idx)]
    starts_of = {}                       # (water, reach) -> start nodes
    for wid, rs in streams.items():
        for k, r in enumerate(rs):
            sn = []
            for ln in r["g"]:
                if len(ln) >= 2:
                    ends_at[tuple(ln[-1])].append((wid, k))
                    sn.append(tuple(ln[0]))
            starts_of[(wid, k)] = sn
    rivers = {}

    def river(wid):
        if wid not in rivers:
            rivers[wid] = River(wid, streams[wid])
        return rivers[wid]
    by_name_ids = defaultdict(list)
    for wid, nm in names.items():
        by_name_ids[nm.lower()].append(wid)

    class Names(dict):
        def get(self, k, default=None):
            return [river(w) for w in by_name_ids.get(k, [])] or (default or [])

    # Waters that have their own listing in each zone (tributary walks stop there).
    own = defaultdict(set)
    for wid, v in W.items():
        if len(v) > 1:
            for z, ls in v[1].items():
                if any(i >= 0 for i in ls):
                    own[z].add(wid)
    inherited = defaultdict(dict)   # trib water -> {listing: {reach: [sections]}}
    for li, Lst in enumerate(LIST):
        if Lst["kind"] != "stream":
            continue
        key = f"{Lst['zone']}|{Lst['name']}"
        mains = [wid for wid, v in W.items() if len(v) > 1 and li in v[1].get(Lst["zone"], [])]
        if len(mains) != 1 or mains[0] not in streams:
            continue
        wid = mains[0]
        secs = Lst["sec"]
        sp = spec.get(key)
        if sp is None:
            if len(secs) != 1:
                continue
            t = re.search(r"includ\w* (its )?tributar|and tributar|tributaries includ|all tributar", secs[0]["d"], re.I)
            sp = [{"d": secs[0]["d"], "main": True, "tribs": bool(t), "up": "head", "down": "mouth"}]
            if not t:
                continue          # one section on the mainstem only: nothing to split or inherit
            # A single section that names its own limits ("from Hwy. 3 to ...") is not the whole river: leave it.
            if re.search(r"\b(from|to|upstream|downstream|above|below|hwy|highway|road|rd\.|bridge|falls|confluence|boundary)\b|\d+-\d+-\d+", secs[0]["d"], re.I):
                LOG[key] = {"result": "single section with its own limits; tributaries not inherited", "d": secs[0]["d"]}
                continue
        # Line the spec entries up with the listing's sections by their wording.
        plan = []
        for si, s in enumerate(secs):
            m = [e for e in sp if e["d"].lower()[:40] in s["d"].lower() or s["d"].lower()[:40] in e["d"].lower()]
            plan.append(m[0] if m else None)
        if not any(plan):
            LOG[key] = {"error": "spec does not match the listing sections", "sections": [s["d"] for s in secs]}
            continue
        R = river(wid)
        zs = W[wid][0]
        zone_reaches = {k for k in range(len(R.reaches)) if (zs[k] if isinstance(zs, list) else zs) == Lst["zone"]}
        if not zone_reaches:
            continue
        mid = R.reach_mid_d()
        zx = [p for i, (k, ln) in enumerate(R.parts) if k in zone_reaches for p in ln]
        bb = [min(p[0] for p in zx) - 0.3, min(p[1] for p in zx) - 0.2, max(p[0] for p in zx) + 0.3, max(p[1] for p in zx) + 0.2]
        ctx = {"mid": mid, "bbox": bb, "by_name": Names(), "lakes": lakes}
        log = {"water": wid, "sections": []}
        iv = []
        ok = True
        for si, p in enumerate(plan):
            if not p:
                iv.append(None)
                log["sections"].append({"d": secs[si]["d"], "error": "no spec"})
                ok = False
                continue
            up, upw = resolve(p["up"], R, zone_reaches, ctx)
            dn, dnw = resolve(p["down"], R, zone_reaches, ctx)
            log["sections"].append({"d": secs[si]["d"], "up": upw, "down": dnw, "upD": up and round(up), "downD": dn and round(dn)})
            if up is None or dn is None:
                ok = False
                iv.append(None)
            else:
                iv.append((min(up, dn), max(up, dn), p))
        LOG[key] = log
        print(key, "ok" if ok else "not split", flush=True, file=sys.stderr)
        if not ok:
            # Sections whose ends were both located are still applied; stretches they don't reach show the whole listing.
            log["result"] = "partly split: some breaks could not be located"
            if not any(iv):
                continue

        def cover(d, want):
            hits = [(si, t) for si, t in enumerate(iv) if t and t[2].get(want) and t[0] <= d <= t[1]]
            if not hits:
                return []
            top = max(t[2].get("prio", 0) for _, t in hits)
            return [si for si, t in hits if t[2].get("prio", 0) == top]
        per = []
        for k in range(len(R.reaches)):
            if k not in zone_reaches:
                per.append(None)
                continue
            c = cover(mid.get(k, -1), "main")
            per.append(c[0] if len(c) == 1 else (c or None))
        W[wid] = W[wid] + [{}] if len(W[wid]) == 2 else W[wid]
        W[wid][2][str(li)] = per
        log["mainstem"] = {"reaches": len(zone_reaches), "assigned": sum(1 for x in per if x is not None)}
        # Tributaries: walk upstream from every confluence on the mainstem.
        if not any(t and t[2].get("tribs") for t in iv):
            continue
        excl = {n.lower() for t in iv if t for n in t[2].get("except", [])}
        incl = {n.lower(): si for si, t in enumerate(iv) if t for n in t[2].get("include", [])}
        n_tr = 0
        for i, (k, ln) in enumerate(R.parts):
            if k not in zone_reaches:
                continue
            for j, node in enumerate(ln):
                for (tw, tk) in ends_at.get(tuple(node), []):
                    if tw == wid:
                        continue
                    tname = (names.get(tw) or "").lower()
                    if tname in incl:
                        c = [incl[tname]]
                    else:
                        if tname and tname in excl:
                            continue
                        c = cover(R.vd[i][j], "tribs")
                    if not c or tw in own[Lst["zone"]]:
                        continue
                    # walk upstream from this reach
                    stack, seen = [(tw, tk)], set()
                    while stack:
                        w2, k2 = stack.pop()
                        if (w2, k2) in seen:
                            continue
                        seen.add((w2, k2))
                        if w2 != tw and (w2 in own[Lst["zone"]] or (names.get(w2) or "").lower() in excl):
                            continue
                        z2 = W.get(w2, [None])[0]
                        z2 = (z2[k2] if isinstance(z2, list) and k2 < len(z2) else z2)
                        if z2 is not None and z2 != Lst["zone"]:
                            continue
                        inherited[w2].setdefault(li, {})[k2] = c
                        n_tr += 1
                        for sn in starts_of.get((w2, k2), []):
                            for nb in ends_at.get(sn, []):
                                if nb[0] != wid:
                                    stack.append(nb)
        log["tributary_reaches"] = n_tr
    # Write inherited listings onto the tributary waters that are on the map.
    n_w = 0
    for w2, per_l in inherited.items():
        if w2 not in W:
            continue
        v = W[w2]
        while len(v) < 4:
            v.append({} if len(v) in (1, 2) else [])
        nreach = len(streams.get(w2, []))
        for li, rk in per_l.items():
            z = LIST[li]["zone"]
            if any(i >= 0 for i in v[1].get(z, [])):
                continue   # has its own listing
            v[1].setdefault(z, [])
            if li not in v[1][z]:
                v[1][z].append(li)
            v[2][str(li)] = [(rk[k][0] if len(rk[k]) == 1 else rk[k]) if k in rk else None for k in range(nreach)]
            if li not in v[3]:
                v[3].append(li)
        W[w2] = v
        n_w += 1
    print("waters given a listing as tributaries:", n_w, file=sys.stderr)
    json.dump(regs, open(os.path.join(ROOT, "data", "regs", "regs.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    json.dump(LOG, open(os.path.join(ROOT, "data", "regs", "sections_log.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
