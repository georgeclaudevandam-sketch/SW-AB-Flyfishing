#!/usr/bin/env python3
"""Build data/regs/regs.json: Alberta sportfishing regulations matched to the map's lakes and streams.

Sources (Government of Alberta, published at albertaregulations.ca):
  - <zone>.html                 default regulations for each watershed unit (lakes and streams)
  - <ZONE>-Lakes.pdf / -Rivers.pdf  waterbody-specific regulation tables
  - fisheries_regulations MapServer layer 4: Fish Management Zone polygons (to place each water in a zone)

Matching is by name inside the zone the water lies in. Lakes listed with a legal land location
(section-township-range-meridian) must also lie within 3 km of it. Where a name is shared by
several waters in a zone and nothing tells them apart, the listing is attached as "possible"
and the map says so. Nothing is inferred from tributary relationships.

Run with RAW=<dir> to read already-downloaded files instead of fetching them.
"""
import glob, html, json, math, os, re, sys, urllib.request, datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAW = os.environ.get("RAW")
BASE = "https://www.albertaregulations.ca/fishingregs/"
FMZ_URL = ("https://geospatial.alberta.ca/titan/rest/services/fisheries/fisheries_regulations/MapServer/4/query?"
           "where=1%3D1&outFields=FISHUNIT_NAME&returnGeometry=true&outSR=4326&maxAllowableOffset=0.0005&geometryPrecision=5&f=geojson")
ZONES = ["ES1", "ES2", "ES3", "ES4", "PP1", "PP2", "NB1", "NB2", "NB3", "NB4"]
MON = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUNE": 6, "JUNE.": 6, "JUN": 6, "JULY": 7, "JUL": 7, "AUG": 8,
       "SEPT": 9, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def get(name, binary=False):
    if RAW:
        p = os.path.join(RAW, name)
        if not os.path.exists(p):
            return None
        return open(p, "rb").read() if binary else open(p, encoding="utf-8", errors="replace").read()
    try:
        req = urllib.request.Request(BASE + name if not name.startswith("http") else name, headers={"User-Agent": "Mozilla/5.0 (map data build)"})
        b = urllib.request.urlopen(req, timeout=120).read()
        return b if binary else b.decode("utf-8", "replace")
    except Exception as e:
        print("fetch failed", name, e, file=sys.stderr)
        return None


def clean(s):
    return " ".join((s or "").split())


# ---------- seasons ----------
DATE = r"(JAN|FEB|MAR|APR|MAY|JUNE?|JULY?|AUG|SEPT?|OCT|NOV|DEC)\.?\s*(\d{1,2})"


def season(text):
    """-> {'t': original text, 'open': [[mmdd, mmdd], ...], 'closed': [[...]], 'cond': bool}"""
    t = clean(text)
    u = t.upper()
    out = {"t": t, "open": [], "closed": []}
    if "ALL YEAR" in u:
        (out["closed"] if u.startswith("CLOSED") else out["open"]).append([101, 1231])
    # Split into OPEN / CLOSED clauses; a bare date range (no word before it) is an open period.
    state = "closed" if u.startswith("CLOSED") else "open"
    for m in re.finditer(r"(OPEN|CLOSED)|" + DATE + r"\s*TO\s*" + DATE, u):
        if m.group(1):
            state = "open" if m.group(1) == "OPEN" else "closed"
            continue
        a = MON[m.group(2)] * 100 + int(m.group(3))
        b = MON[m.group(4)] * 100 + int(m.group(5))
        out[state].append([a, b])
    if re.search(r"SUNRISE|SUNSET|WEEKEND|FRIDAY|THURSDAY|SUNDAY|MONDAY|\d{4}H|ALL DAY", u):
        out["cond"] = True
    if not out["open"] and not out["closed"]:
        out["unparsed"] = True
    return out


# ---------- waterbody tables ----------
def norm_head(h):
    h = clean(h)
    if h.startswith("Bait"):
        return "Bait"
    return h


def bait_legend(h):
    h = clean(h)
    m = re.search(r"l\s*=\s*(.+)", h)
    return m.group(1).strip() if m else None


def parse_pdf(data, zone, kind):
    import io, pdfplumber
    waters = []
    cur = None
    head = None
    legend = None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                for r in t:
                    r = [(c if c is None else c.strip()) for c in r]
                    if not r or (r[0] and r[0].startswith(zone + " -")):
                        continue
                    if r[0] == "Waterbody":
                        head = [norm_head(c) for c in r]
                        legend = bait_legend(r[3]) if len(r) > 3 else None
                        continue
                    if head is None or len(r) != len(head):
                        if head is not None and any(r):
                            print("skip row (width)", zone, kind, r[:3], file=sys.stderr)
                        continue
                    if not any(r):
                        continue
                    if r[0]:
                        cur = {"name": clean(r[0]), "sec": []}
                        waters.append(cur)
                    if cur is None:
                        continue
                    if r[1] is not None or not cur["sec"]:
                        det = clean(r[1])
                        same = [s for s in cur["sec"] if s["d"] == det]
                        if same and r[0] is None:
                            sec = same[0]
                        else:
                            sec = {"d": det, "rows": []}
                            cur["sec"].append(sec)
                    else:
                        sec = cur["sec"][-1]
                    if not r[2]:
                        continue
                    row = {"s": season(r[2])}
                    bait = clean(r[3])
                    if bait == "l" and legend:
                        bait = legend
                    if bait:
                        row["b"] = bait
                    lim = {}
                    for h, c in zip(head[4:], r[4:]):
                        c = clean(c)
                        if c:
                            lim[h] = c
                    if lim:
                        row["l"] = lim
                    sec["rows"].append(row)
    for w in waters:
        loc = None
        for s in w["sec"]:
            m = re.search(r"(?:(NE|NW|SE|SW)[- ]?)?(\d{1,2})(?:,\d{1,2})*-(\d{1,3})-(\d{1,2})-W([4-6])", s["d"])
            if m and loc is None:
                loc = ats(int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
        if loc:
            w["at"] = loc
        w["kind"] = kind
        w["zone"] = zone
    return waters


def ats(sec, twp, rge, mer):
    """Approximate centre of an Alberta Township System section (good to about 1-2 km)."""
    # Sections run 1-6 east to west on the bottom row, 7-12 west to east above, and so on.
    row = (sec - 1) // 6
    col = (sec - 1) % 6
    col_from_east = col if row % 2 == 0 else 5 - col
    # A township is six miles plus road allowances; measured against known lakes here: ~9.76 km tall, ~9.79 km wide.
    mile, tw, rw = 1609.344, 9760.0, 9790.0
    north_m = (twp - 1) * tw + (row + 0.5) * mile
    lat = 49 + north_m / 111200.0
    west_m = (rge - 1) * rw + (col_from_east + 0.5) * mile
    lon0 = {4: -110.0, 5: -114.0, 6: -118.0}[mer]
    lon = lon0 - west_m / (111320.0 * math.cos(math.radians(lat)))
    return [round(lat, 4), round(lon, 4)]


# ---------- zone defaults ----------
def parse_defaults(page):
    t = re.sub(r"<[^>]+>", "|", page)
    t = html.unescape(t)
    out = {}
    for kind, a, b in (("lake", "DEFAULT REGULATIONS FOR LAKES", "DEFAULT REGULATIONS FOR STREAMS"), ("stream", "DEFAULT REGULATIONS FOR STREAMS", "Copyright")):
        i = t.find(a)
        j = t.find(b, i + 1)
        if i < 0 or j < 0:
            continue
        block = t[i + len(a):j]
        rows = []
        # Each season heading starts with OPEN or CLOSED; bullets (●) follow it.
        parts = re.split(r"\|\s*((?:OPEN|CLOSED)[^|●]*)", block)
        for k in range(1, len(parts), 2):
            head = clean(parts[k])
            bullets = [clean(x.replace("|", " ")) for x in parts[k + 1].split("●")]
            bullets = [x for x in bullets if x]
            rows.append({"s": season(head), "n": bullets})
        out[kind] = rows
    return out


# ---------- names ----------
def keys(name):
    n = name.lower().replace("’", "'")
    alts = [n]
    m = re.match(r"(.*?)\s*\(([^)]+)\)\s*(.*)", n)
    if m:
        alts = [clean(m.group(1) + " " + m.group(3)), clean(m.group(2) + " " + m.group(3))]
    out = set()
    for a in alts:
        a = re.sub(r"[^a-z0-9' ]", " ", a)
        a = clean(a.replace("mount ", "mt ").replace(" ck", " creek").replace(" r ", " river "))
        out.add(a)
        for s, p in (("lakes", "lake"), ("ponds", "pond"), ("creeks", "creek"), ("reservoirs", "reservoir")):
            if a.endswith(" " + s):
                out.add(a[: -len(s)] + p)
    return out


# ---------- geometry ----------
def pip(x, y, ring):
    ins = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def zone_of(zones, x, y):
    for name, polys, bb in zones:
        if not (bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]):
            continue
        for poly in polys:
            if pip(x, y, poly[0]) and not any(pip(x, y, h) for h in poly[1:]):
                return name
    return None


def dist_m(a, b):
    kx = 111320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110540)


def main():
    meta = {"source": BASE, "built": datetime.date.today().isoformat()}
    idx = get("index.html") or ""
    m = re.search(r"effective from ([A-Z][a-z]+ \d+, \d{4}) to ([A-Z][a-z]+ \d+, \d{4})", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", idx))))
    if m:
        meta["effective"] = [m.group(1), m.group(2)]
        meta["until"] = datetime.datetime.strptime(m.group(2), "%B %d, %Y").date().isoformat()
    defaults, listings = {}, []
    for z in ZONES:
        page = get(z.lower() + ".html")
        if page:
            defaults[z] = parse_defaults(page)
        for kind, f in (("lake", "Lakes"), ("stream", "Rivers")):
            data = get(f"{z}-{f}.pdf", binary=True)
            if data:
                listings += parse_pdf(data, z, kind)
    print("listings", len(listings), file=sys.stderr)

    fmz = json.loads(get(FMZ_URL) if not RAW else open(os.path.join(RAW, "fmz.geojson")).read())
    zones = []
    for f in fmz["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        xs = [c[0] for p in polys for c in p[0]]
        ys = [c[1] for p in polys for c in p[0]]
        zones.append((f["properties"]["FISHUNIT_NAME"], polys, (min(xs), min(ys), max(xs), max(ys))))

    # The map's waters: zone of each lake (centroid) and of each stream reach (middle vertex).
    waters = []
    idx = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "water", "index.json")))["items"]}
    for fn in sorted(glob.glob(os.path.join(ROOT, "data", "water", "c_*.json"))):
        for w in json.load(open(fn)):
            if w["id"][0] not in "sl":
                continue
            it = idx.get(w["id"], {})
            names = [n for n in (it.get("n"), it.get("a"), w.get("n")) if n]
            if not names and not it:
                continue
            if w["id"][0] == "l":
                c, bb = it.get("c"), it.get("b")
                if not c or not bb:
                    ring = w["g"][0]
                    while isinstance(ring[0][0], list):
                        ring = ring[0]
                    c = [sum(v[0] for v in ring) / len(ring), sum(v[1] for v in ring) / len(ring)]
                    bb = [min(v[0] for v in ring), min(v[1] for v in ring), max(v[0] for v in ring), max(v[1] for v in ring)]
                waters.append({"id": w["id"], "kind": "lake", "names": names, "at": [c[1], c[0]], "bb": bb, "z": [zone_of(zones, c[0], c[1])]})
            else:
                zs = []
                for rc in w.get("r", []):
                    part = rc["g"][len(rc["g"]) // 2]
                    v = part[len(part) // 2]
                    zs.append(zone_of(zones, v[0], v[1]))
                waters.append({"id": w["id"], "kind": "stream", "names": names, "z": zs})
    print("waters", len(waters), file=sys.stderr)

    # Index waters by (zone, kind, name key). Wide rivers are also lake polygons: let streams match lake rows too? No:
    # the regulations list rivers in the Rivers table, and the map's river polygons share the stream WB_ID.
    by = {}
    for w in waters:
        for z in set(w["z"]):
            if not z:
                continue
            for k in set().union(set(), *(keys(n) for n in w["names"])):
                by.setdefault((z, w["kind"], k), []).append(w)

    out_list, match, unmatched = [], {}, []
    for L in listings:
        cands = []
        lk = keys(L["name"])
        if re.search(r"(lakes|ponds)$", L["name"].lower()):
            lk |= {p + " " + k for k in list(lk) for p in ("upper", "lower", "middle", "east", "west", "north", "south", "little", "big")}
        for k in lk:
            cands += by.get((L["zone"], L["kind"], k), [])
        seen = set()
        cands = [c for c in cands if not (c["id"] in seen or seen.add(c["id"]))]
        how = "name"
        if L["kind"] == "lake" and L.get("at"):
            # distance from the listed section to the lake's bounding box
            def dbox(p, c):
                b = c["bb"]
                return dist_m(p, [min(max(p[0], b[1]), b[3]), min(max(p[1], b[0]), b[2])])
            near = sorted(((dbox(L["at"], c), k, c) for k, c in enumerate(cands)), key=lambda t: t[:2])
            near = [(d, c) for d, k, c in near]
            near = [c for d, c in near if d < 3000]
            if near:
                cands, how = near[:1] if not re.search(r"(lakes|ponds)$", L["name"].lower()) else near, "name+location"
            elif cands:
                cands, how = [], "far"
        if not cands:
            unmatched.append((L["zone"], L["kind"], L["name"], how))
        li = len(out_list)
        entry = {k: L[k] for k in ("name", "zone", "kind", "sec")}
        if L.get("at"):
            entry["at"] = L["at"]
        out_list.append(entry)
        sure = len(cands) == 1 or how == "name+location"
        for c in cands:
            match.setdefault(c["id"], {})
            match[c["id"]].setdefault(L["zone"], []).append(li if sure else -1 - li)  # negative = one of several same-named waters

    # Per water: zone(s) and listing(s).  w: {id: [zones-per-reach or zone, {zone: [listing idx]}]}
    W = {}
    for w in waters:
        zs = w["z"]
        z = zs[0] if len(set(zs)) == 1 else zs
        if z is None or (isinstance(z, list) and not any(z)):
            continue
        W[w["id"]] = [z, match.get(w["id"], {})] if w["id"] in match else [z]
    res = {"meta": meta, "defaults": defaults, "list": out_list, "w": W}
    os.makedirs(os.path.join(ROOT, "data", "regs"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "data", "regs", "regs.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    json.dump(sorted(unmatched), open(os.path.join(ROOT, "data", "regs", "unmatched.json"), "w"), indent=0, ensure_ascii=False)
    amb = sum(1 for v in match.values() for l in v.values() for i in l if i < 0)
    print(f"listings {len(out_list)}, unmatched {len(unmatched)}, waters with listing {len(match)}, possible-only links {amb}, waters zoned {len(W)}", file=sys.stderr)


if __name__ == "__main__":
    main()
