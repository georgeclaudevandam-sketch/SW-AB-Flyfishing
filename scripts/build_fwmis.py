#!/usr/bin/env python3
"""Download every lake, river and creek on Alberta's Eastern Slopes from the
Government of Alberta FWMIS public service, with the fish species recorded in
each waterbody, and write map-ready files to data/water/.

Source: Fish and Wildlife Internet Mapping Tool (FWIMT) public service
https://geospatial.alberta.ca/titan/rest/services/biota/fwimt_pub_species_inventory/MapServer
  layer 33  FWMIS Lakes/Ponds/Reservoirs        (SPECIES_PRES)
  layer 34  FWMIS River and Stream              (SPECIES_PRES)
  layer 32  Fish Culture Stocking               (stocking records)
SPECIES_PRES is the historic list of species sampled anywhere in the waterbody.

Run:  python3 scripts/build_fwmis.py
"""
import json, math, os, sys, time, urllib.parse, urllib.request
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
    if not s:
        return None
    small = {"of", "the", "and", "de", "la"}
    words = s.strip().lower().split()
    return " ".join(w if (k and w in small) else w[:1].upper() + w[1:] for k, w in enumerate(words))


def codes(s):
    return sorted({c.strip().upper() for c in (s or "").replace(";", ",").split(",") if c.strip()})


def bbox_of(coords):
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def r5(c):
    return [round(c[0], 5), round(c[1], 5)]


def main():
    os.makedirs(OUT, exist_ok=True)
    wb = {}  # WB_ID -> record

    def rec(wid, kind, a):
        r = wb.get(wid)
        if not r:
            r = wb[wid] = {"id": wid, "kind": kind, "name": title(a.get("OFFICIAL_NM")), "alt": title(a.get("COMMON_NM")),
                           "species": set(), "order": 0, "huc": a.get("HUC_8"), "geom": []}
        r["species"].update(codes(a.get("SPECIES_PRES")))
        if not r["name"]:
            r["name"] = title(a.get("OFFICIAL_NM"))
        return r

    # ---- streams: every named stream, plus unnamed ones with fish records
    sf = ["WB_ID", "OFFICIAL_NM", "COMMON_NM", "SPECIES_PRES", "STR_ORDER", "Feature_Type", "HUC_8"]
    for f in fetch(34, "OFFICIAL_NM IS NOT NULL OR SPECIES_PRES IS NOT NULL", sf):
        a = f["attributes"]
        wid = a.get("WB_ID")
        if wid is None:
            continue
        r = rec(f"s{int(wid)}", "stream", a)
        try:
            r["order"] = max(r["order"], int(a.get("STR_ORDER") or 0))
        except ValueError:
            pass
        for p in (f.get("geometry") or {}).get("paths", []):
            if len(p) > 1:
                r["geom"].append([r5(c) for c in p])

    # ---- lakes: every named lake, plus unnamed ones with fish records
    lf = ["WB_ID", "OFFICIAL_NM", "COMMON_NM", "SPECIES_PRES", "Feature_Type", "HUC_8"]
    for f in fetch(33, "OFFICIAL_NM IS NOT NULL OR SPECIES_PRES IS NOT NULL", lf):
        a = f["attributes"]
        wid = a.get("WB_ID")
        if wid is None:
            continue
        r = rec(f"l{int(wid)}", "lake", a)
        for ring in (f.get("geometry") or {}).get("rings", []):
            if len(ring) > 3:
                r["geom"].append([r5(c) for c in ring])

    # ---- stocking records, joined by waterbody id
    stock = defaultdict(lambda: defaultdict(set))
    try:
        sfields = layer_fields(32)
        print("stocking fields:", sfields, file=sys.stderr)
        idf = next((x for x in sfields if x.upper() in ("WTB_ID", "WB_ID")), None)
        spf = next((x for x in sfields if x.upper() == "SPEC_CODE"), None)
        dtf = next((x for x in sfields if "DATE" in x.upper()), None)
        if idf and spf:
            for f in fetch(32, "1=1", [idf, spf] + ([dtf] if dtf else []), geometry=False, batch=500):
                a = f["attributes"]
                if a.get(idf) is None or not a.get(spf):
                    continue
                yr = None
                if dtf and isinstance(a.get(dtf), (int, float)):
                    yr = time.gmtime(a[dtf] / 1000).tm_year
                stock[int(a[idf])][a[spf].strip().upper()].add(yr)
    except SystemExit as e:
        print("stocking skipped:", e, file=sys.stderr)

    # ---- write index + chunks
    index, chunks, all_codes = [], defaultdict(list), defaultdict(int)
    for r in wb.values():
        if not r["geom"]:
            continue
        pts = [c for part in r["geom"] for c in part]
        bb = bbox_of(pts)
        if r["kind"] == "lake":
            ring = max(r["geom"], key=len)
            cx = sum(c[0] for c in ring) / len(ring); cy = sum(c[1] for c in ring) / len(ring)
        else:
            longest = max(r["geom"], key=len)
            cx, cy = longest[len(longest) // 2]
        num = int(r["id"][1:])
        st = {}
        if r["kind"] == "lake" and num in stock:
            st = {k: sorted(y for y in v if y) for k, v in stock[num].items()}
        sp = sorted(r["species"])
        for c in sp:
            all_codes[c] += 1
        key = f"{math.floor(cx / CHUNK_DEG)}_{math.floor(cy / CHUNK_DEG)}"
        item = {"id": r["id"], "k": r["kind"][0], "n": r["name"], "sp": sp, "c": [round(cx, 4), round(cy, 4)],
                "b": [round(v, 4) for v in bb], "ch": key}
        if r["alt"] and r["alt"] != r["name"]:
            item["a"] = r["alt"]
        if r["order"]:
            item["o"] = r["order"]
        if r["huc"]:
            item["h"] = r["huc"]
        if st:
            item["st"] = st
        index.append(item)
        chunks[key].append({"id": r["id"], "g": r["geom"]})

    for f in os.listdir(OUT):
        if f.startswith("c_") and f.endswith(".json"):
            os.remove(os.path.join(OUT, f))
    for key, feats in chunks.items():
        with open(os.path.join(OUT, f"c_{key}.json"), "w") as fh:
            json.dump(feats, fh, separators=(",", ":"))
    index.sort(key=lambda x: (x["n"] or "~", x["id"]))
    meta = {"source": BASE, "layers": {"lakes": 33, "streams": 34, "stocking": 32},
            "built": time.strftime("%Y-%m-%d", time.gmtime()), "chunkDeg": CHUNK_DEG,
            "chunks": sorted(chunks), "codes": dict(sorted(all_codes.items(), key=lambda kv: -kv[1])),
            "count": len(index)}
    with open(os.path.join(OUT, "index.json"), "w") as fh:
        json.dump({"meta": meta, "items": index}, fh, separators=(",", ":"))
    print(json.dumps({k: meta[k] for k in ("built", "count", "codes")}, indent=1))
    print(f"lakes {sum(1 for i in index if i['k']=='l')}, streams {sum(1 for i in index if i['k']=='s')}, chunks {len(chunks)}")


if __name__ == "__main__":
    main()
