#!/usr/bin/env python3
"""Download every lake, river and creek on Alberta's Eastern Slopes from the
Government of Alberta FWMIS public service, with the fish species recorded in
each waterbody, and write map-ready files to data/water/.

Source: Fish and Wildlife Internet Mapping Tool (FWIMT) public service
https://geospatial.alberta.ca/titan/rest/services/biota/fwimt_pub_species_inventory/MapServer
  layer 33  FWMIS Lakes/Ponds/Reservoirs        (SPECIES_PRES)
  layer 34  FWMIS River and Stream              (SPECIES_PRES)
  layer 32  Fish Culture Stocking               (stocking records)
  layer 30  Fish Survey                         (one row per species caught per survey, with location and date)

Streams: species come only from fish survey records located on each stretch (reach)
of the stream, so a long river does not inherit species caught far away.
Lakes: species from survey records in the lake plus the lake's SPECIES_PRES list.

Run:  python3 scripts/build_fwmis.py
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
import parks
from collections import defaultdict

BASE = os.environ.get("FWMIS_BASE") or "https://geospatial.alberta.ca/titan/rest/services/biota/fwimt_pub_species_inventory/MapServer"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "water")
CHUNK_DEG = 0.5          # grid size for geometry chunks
SIMPLIFY = 0.0002        # degrees (~20 m) passed to the server as maxAllowableOffset

# Eastern Slopes study area: Grande Cache south to the US border, BC border east to the foothills.
AREA = [[-120.0, 55.0], [-117.6, 55.0], [-116.6, 54.0], [-115.4, 53.2], [-114.6, 52.4],
        [-114.0, 51.6], [-113.6, 51.0], [-113.5, 50.2], [-113.3, 49.0], [-114.1, 49.0],
        [-114.7, 49.4], [-115.3, 50.3], [-116.4, 51.2], [-117.4, 52.2], [-118.6, 53.0],
        [-120.0, 53.8], [-120.0, 55.0]]
GEOM = json.dumps({"rings": [AREA], "spatialReference": {"wkid": 4326}})


def get(url, params, tries=5):
    data = urllib.parse.urlencode(params).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "eastern-slopes-trout-map/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.loads(r.read().decode("utf-8"))
            if "error" in j:
                raise RuntimeError(j["error"])
            return j
        except Exception as e:
            print(f"  retry {i+1}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    raise SystemExit(f"failed: {url}")


def layer_fields(layer):
    j = get(f"{BASE}/{layer}", {"f": "json"})
    return [f["name"] for f in j.get("fields", [])]


def ids(layer, where):
    j = get(f"{BASE}/{layer}/query", {"where": where, "geometry": GEOM, "geometryType": "esriGeometryPolygon",
                                       "spatialRel": "esriSpatialRelIntersects", "inSR": 4326,
                                       "returnIdsOnly": "true", "f": "json"})
    return sorted(j.get("objectIds") or [])


def fetch(layer, where, fields, geometry=True, batch=250):
    oids = ids(layer, where)
    print(f"layer {layer}: {len(oids)} features", file=sys.stderr)
    out = []
    for i in range(0, len(oids), batch):
        params = {"objectIds": ",".join(map(str, oids[i:i + batch])), "outFields": ",".join(fields),
                  "returnGeometry": "true" if geometry else "false", "outSR": 4326, "f": "json"}
        if geometry:
            params.update({"maxAllowableOffset": SIMPLIFY, "geometryPrecision": 5})
        out += get(f"{BASE}/{layer}/query", params).get("features", [])
        print(f"  {min(i + batch, len(oids))}/{len(oids)}", file=sys.stderr)
    return out


def title(s):
    if not s or s.strip().upper() == "UNNAMED":
        return None
    small = {"of", "the", "and", "de", "la"}
    words = s.strip().lower().split()
    return " ".join(w if (k and w in small) else w[:1].upper() + w[1:] for k, w in enumerate(words))


CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{2,7}$")


def codes(s):
    """Species codes from SPECIES_PRES. Text such as 'NO FISH SAMPLED TO DATE' is not a code."""
    out = set()
    for c in (s or "").replace(";", ",").split(","):
        c = c.strip().upper()
        if CODE_RE.match(c):
            out.add(c)
    return sorted(out)


def bbox_of(coords):
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def r5(c):
    return [round(c[0], 5), round(c[1], 5)]



SNAP_KM = 0.5   # a survey site must lie within this distance of a stream reach to count for it


def seg_dist_km(p, a, b):
    """Distance (km) from point p to segment a-b, using a local flat projection."""
    k = math.cos(math.radians(p[1]))
    ax, ay = (a[0] - p[0]) * 111.32 * k, (a[1] - p[1]) * 110.57
    bx, by = (b[0] - p[0]) * 111.32 * k, (b[1] - p[1]) * 110.57
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def reach_dist_km(p, parts):
    best = 1e9
    for part in parts:
        for i in range(1, len(part)):
            d = seg_dist_km(p, part[i - 1], part[i])
            if d < best:
                best = d
    return best


def add_site(r, lon, lat, yr, codeset, src, method=""):
    """Attach a survey site to waterbody r: to the nearest reach for streams (if within SNAP_KM)."""
    if r["kind"] == "stream":
        best, bi = 1e9, None
        for i, reach in enumerate(r["reaches"]):
            bb = reach["bb"]
            if lon < bb[0] - 0.02 or lon > bb[2] + 0.02 or lat < bb[1] - 0.02 or lat > bb[3] + 0.02:
                continue
            d = reach_dist_km((lon, lat), reach["g"])
            if d < best:
                best, bi = d, i
        if bi is None or best > SNAP_KM:
            return False
        target = r["reaches"][bi]["y"]
    else:
        target = r["y"]
    for c in codeset:
        target[c] = max(target.get(c, 0), yr or 0)
        lo, hi = r["yr"].get(c, (9999, 0))
        r["yr"][c] = (min(lo, yr or 9999), max(hi, yr or 0))
    key = (round(lon, 4), round(lat, 4), src)
    site = r["sites"].setdefault(key, {"y": {}, "n": 0, "m": set()})
    for c in codeset:
        site["y"][c] = max(site["y"].get(c, 0), yr or 0)
    site["n"] += 1
    if method:
        site["m"].add(method)
    return True


def main():
    wb = {}

    def rec(wid, kind, a):
        r = wb.get(wid)
        if not r:
            r = wb[wid] = {"id": wid, "kind": kind, "name": title(a.get("OFFICIAL_NM")), "alt": title(a.get("COMMON_NM")),
                           "pres": set(), "order": 0, "huc": a.get("HUC_8"), "geom": [], "reaches": [],
                           "y": {}, "yr": {}, "sites": {}}
        r["pres"].update(codes(a.get("SPECIES_PRES")))
        return r

    sf = ["WB_ID", "OFFICIAL_NM", "COMMON_NM", "SPECIES_PRES", "STR_ORDER", "HUC_8"]
    for f in fetch(34, "1=1", sf):
        a = f["attributes"]
        if a.get("WB_ID") is None:
            continue
        r = rec(f"s{int(a['WB_ID'])}", "stream", a)
        try:
            o = int(a.get("STR_ORDER") or 0)
        except ValueError:
            o = 0
        r["order"] = max(r["order"], o)
        parts = [[r5(c) for c in p] for p in (f.get("geometry") or {}).get("paths", []) if len(p) > 1]
        if parts:
            r["reaches"].append({"g": parts, "o": o, "y": {}, "bb": bbox_of([c for p in parts for c in p])})

    lf = ["WB_ID", "OFFICIAL_NM", "COMMON_NM", "SPECIES_PRES", "HUC_8"]
    for f in fetch(33, "1=1", lf):
        a = f["attributes"]
        if a.get("WB_ID") is None:
            continue
        r = rec(f"l{int(a['WB_ID'])}", "lake", a)
        for ring in (f.get("geometry") or {}).get("rings", []):
            if len(ring) > 3:
                r["geom"].append([r5(c) for c in ring])
    # Wide rivers also appear in the lake layer as polygons with the same WB_ID.
    # The stream centreline (with per-reach species) represents them, so drop the polygon.
    stream_ids = {k[1:] for k in wb if k[0] == "s"}
    for k in [k for k in wb if k[0] == "l" and k[1:] in stream_ids]:
        del wb[k]
    # Lakes keep their SPECIES_PRES list (undated) - a lake is one body of water.
    for r in wb.values():
        if r["kind"] == "lake":
            for c in r["pres"]:
                r["y"].setdefault(c, 0)

    # ---- fish survey records (layer 30): one row per species per survey
    by_num = {}
    for r in wb.values():
        by_num.setdefault(int(r["id"][1:]), []).append(r)
    stats = defaultdict(int)
    loose = {}
    for f in fetch(30, "SPEC_CODE IS NOT NULL", ["WTB_ID", "SPEC_CODE", "LATITUDE", "LONGITUDE", "TERMINATION_DATE", "SURVEY_TYPE"],
                   geometry=False, batch=1000):
        a = f["attributes"]
        code = (a.get("SPEC_CODE") or "").strip().upper()
        lat, lon = a.get("LATITUDE"), a.get("LONGITUDE")
        if not CODE_RE.match(code) or lat is None or lon is None:
            stats["skipped"] += 1
            continue
        yr = time.gmtime(a["TERMINATION_DATE"] / 1000).tm_year if isinstance(a.get("TERMINATION_DATE"), (int, float)) else 0
        method = (a.get("SURVEY_TYPE") or "").strip()
        ok = False
        for r in by_num.get(int(a["WTB_ID"]) if a.get("WTB_ID") is not None else -1, []):
            ok = add_site(r, lon, lat, yr, {code}, "fwmis", method) or ok
        if ok:
            stats["snapped"] += 1
        else:
            stats["unsnapped"] += 1
            k = (round(lon, 4), round(lat, 4))
            s = loose.setdefault(k, {"y": {}, "n": 0, "m": set(), "src": "fwmis"})
            s["y"][code] = max(s["y"].get(code, 0), yr)
            s["n"] += 1
            if method:
                s["m"].add(method)
    print("survey records:", dict(stats), file=sys.stderr)

    stock = defaultdict(lambda: defaultdict(set))
    try:
        sfields = layer_fields(32)
        idf = next((x for x in sfields if x.upper() in ("WTB_ID", "WB_ID")), None)
        spf = next((x for x in sfields if x.upper() == "SPEC_CODE"), None)
        dtf = next((x for x in sfields if "DATE" in x.upper()), None)
        if idf and spf:
            for f in fetch(32, "1=1", [idf, spf] + ([dtf] if dtf else []), geometry=False, batch=1000):
                a = f["attributes"]
                if a.get(idf) is None or not a.get(spf):
                    continue
                yr = time.gmtime(a[dtf] / 1000).tm_year if dtf and isinstance(a.get(dtf), (int, float)) else None
                stock[int(a[idf])][a[spf].strip().upper()].add(yr)
    except SystemExit as e:
        print("stocking skipped:", e, file=sys.stderr)

    write(wb, stock, loose)


def nm(x):
    return re.sub(r"[^a-z0-9 ]", "", (x or "").lower()).strip()


def merge_parks(wb, loose):
    """Parks Canada records. Sites with coordinates are attached to the reach they lie on,
    on a same-named waterbody inside the park (within SNAP_KM); otherwise they are kept
    as stand-alone survey sites. Lake records without coordinates (Waterton lake index)
    attach to a same-named lake in the park; if none matches they are listed as unmatched."""
    by_name = {}
    for r in wb.values():
        for n in {nm(r["name"]), nm(r["alt"])}:
            if n:
                by_name.setdefault(n, []).append(r)
    unmatched, matched = [], 0
    for p in parks.records():
        base = nm(re.sub(r"\(.*?\)|\baka\b|#\d+", "", p["name"]))
        names = [base] if base.endswith((" lake", " creek", " river", " lakes", " pond")) else \
            [base, base + " lake", base + " creek", base + " river", "lake " + base]
        cands = []
        for n in names:
            for r in by_name.get(n, []):
                if p.get("kind") and r["kind"] != p["kind"]:
                    continue
                pts = [c for g in (r["geom"] or [x for rc in r["reaches"] for x in rc["g"]]) for c in g[::3]]
                if any(parks.in_park(p["park"], c[0], c[1]) for c in pts):
                    cands.append(r)
        cands = list({id(r): r for r in cands}.values())
        src = "pc:" + p["park"]
        if p["sites"]:
            for s in p["sites"]:
                ok = any(add_site(r, s["lon"], s["lat"], s["yr"], s["codes"], src, s.get("method", "")) for r in cands)
                if ok:
                    matched += 1
                    for r in cands:
                        r.setdefault("parks", {})[p["park"]] = p["src"]
                else:
                    k = (round(s["lon"], 4), round(s["lat"], 4))
                    st = loose.setdefault(k, {"y": {}, "n": 0, "m": set(), "src": src, "name": p["name"]})
                    for c in s["codes"]:
                        st["y"][c] = max(st["y"].get(c, 0), s["yr"])
                    st["n"] += 1
        elif p.get("kind") == "lake" and len(cands) == 1:
            r = cands[0]
            yr = max(p["years"]) if p["years"] else 0
            for c in p["species"]:
                r["y"][c] = max(r["y"].get(c, 0), yr)
                lo, hi = r["yr"].get(c, (9999, 0))
                r["yr"][c] = (min(lo, yr), max(hi, yr))
            r.setdefault("parks", {})[p["park"]] = p["src"]
            matched += 1
        else:
            unmatched.append({"park": p["park"], "name": p["name"], "species": sorted(p["species"]), "src": p["src"]})
    print(f"parks: matched {matched}, unmatched {len(unmatched)}", file=sys.stderr)
    return unmatched


def write(wb, stock, loose):
    unmatched = merge_parks(wb, loose)
    index, chunks = [], defaultdict(list)
    all_codes = defaultdict(int)
    for r in wb.values():
        geoms = r["geom"] or [p for rc in r["reaches"] for p in rc["g"]]
        if not geoms:
            continue
        bb = bbox_of([c for part in geoms for c in part])
        if r["kind"] == "lake":
            ring = max(r["geom"], key=len)
            cx = sum(c[0] for c in ring) / len(ring); cy = sum(c[1] for c in ring) / len(ring)
        else:
            longest = max(geoms, key=len)
            cx, cy = longest[len(longest) // 2]
        key = f"{math.floor(cx / CHUNK_DEG)}_{math.floor(cy / CHUNK_DEG)}"
        num = int(r["id"][1:])
        st = {k: sorted(y for y in v if y) for k, v in stock.get(num, {}).items()} if r["kind"] == "lake" else {}
        y = dict(r["y"])
        for rc in r["reaches"]:
            for c, yr in rc["y"].items():
                y[c] = max(y.get(c, 0), yr)
        for c in y:
            all_codes[c] += 1
        sites = [[k[0], k[1], v["y"], v["n"], k[2], sorted(v["m"])] for k, v in r["sites"].items()]
        feat = {"id": r["id"]}
        if r["kind"] == "lake":
            feat["g"] = r["geom"]
        else:
            feat["r"] = [{"g": rc["g"], "o": rc["o"], **({"y": rc["y"]} if rc["y"] else {})} for rc in r["reaches"]]
        if sites:
            feat["s"] = sites
        if y or st or (r["kind"] == "lake" and (r["name"] or r["alt"])):
            item = {"id": r["id"], "k": r["kind"][0], "n": r["name"], "y": y, "c": [round(cx, 4), round(cy, 4)],
                    "b": [round(v, 4) for v in bb], "ch": key}
            if r["alt"] and r["alt"] != r["name"]:
                item["a"] = r["alt"]
            if r["order"]:
                item["o"] = r["order"]
            if r["huc"]:
                item["h"] = r["huc"]
            if st:
                item["st"] = st
            if r["yr"]:
                item["yr"] = {c: [lo if lo != 9999 else 0, hi] for c, (lo, hi) in r["yr"].items()}
            if r["kind"] == "stream" and r["pres"]:
                item["pres"] = sorted(r["pres"])
            if r.get("parks"):
                item["pk"] = r["parks"]
            index.append(item)
        else:
            feat.update({"k": r["kind"][0], "n": r["name"] or r["alt"], "o": r["order"] or None})
        chunks[key].append(feat)

    # Survey sites not on any mapped water, kept as points.
    loose_out = defaultdict(list)
    for (lon, lat), v in loose.items():
        loose_out[f"{math.floor(lon / CHUNK_DEG)}_{math.floor(lat / CHUNK_DEG)}"].append(
            [lon, lat, v["y"], v["n"], v["src"], sorted(v["m"]), v.get("name")])
    for k, pts in loose_out.items():
        chunks[k].append({"id": "pts_" + k, "pts": pts})

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith("c_") and f.endswith(".json"):
            os.remove(os.path.join(OUT, f))
    for key, feats in chunks.items():
        with open(os.path.join(OUT, f"c_{key}.json"), "w") as fh:
            json.dump(feats, fh, separators=(",", ":"))
    index.sort(key=lambda x: (x["n"] or x.get("a") or "~", x["id"]))
    meta = {"source": BASE, "layers": {"lakes": 33, "streams": 34, "stocking": 32, "surveys": 30},
            "built": time.strftime("%Y-%m-%d", time.gmtime()), "chunkDeg": CHUNK_DEG, "snapKm": SNAP_KM,
            "chunks": sorted(chunks), "codes": dict(sorted(all_codes.items(), key=lambda kv: -kv[1])),
            "count": len(index), "total": sum(1 for v in chunks.values() for f in v if not f["id"].startswith("pts_")),
            "parks": {"datasets": parks.DS, "unmatched": unmatched, "banffWatersheds": parks.banff_watersheds()}}
    with open(os.path.join(OUT, "index.json"), "w") as fh:
        json.dump({"meta": meta, "items": index}, fh, separators=(",", ":"))
    print(json.dumps({k: meta[k] for k in ("built", "count", "total")}))


if __name__ == "__main__":
    main()
