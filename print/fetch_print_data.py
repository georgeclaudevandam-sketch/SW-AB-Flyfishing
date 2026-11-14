#!/usr/bin/env python3
"""Download the line work for the printed wall maps (ES1, ES2 + ES3) and save it to print/data/.

Runs in GitHub Actions (the Government of Alberta and Overpass servers are reachable there).
  zones.json      Fish Management Zones ES1-ES3 (fisheries_regulations MapServer layer 4), full detail
  ab_roads.json   Government of Alberta access_facility_roads layer 0 (every road class, with attributes)
  ab_trails.json  Government of Alberta designated and provincial trails (every line layer)
  osm.json        OpenStreetMap: roads, tracks, trails, hiking routes, places, peaks, passes, campgrounds,
                  trailheads, protected areas, glaciers and the provincial / international border
Every file stores [lon, lat] rounded to 5 decimals.
"""
import gzip, json, os, sys, time, urllib.parse, urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "sw-ab-flyfishing-print-build/1.0 (GitHub Actions)", "Accept": "*/*"}
FMZ = "https://geospatial.alberta.ca/titan/rest/services/fisheries/fisheries_regulations/MapServer/4/query"
ROADS = "https://geospatial.alberta.ca/titan/rest/services/transportation/access_facility_roads/MapServer/0"
TRAILS = "https://geospatial.alberta.ca/mimas/rest/services/recreation/alberta_designated_and_provincial_trails/MapServer"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
ZONES = ["ES1", "ES2", "ES3"]


def http(url, data=None, timeout=240, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8"))
            if isinstance(j, dict) and "error" in j:
                raise RuntimeError(j["error"])
            return j
        except Exception as e:
            print(f"  retry {i + 1}: {str(e)[:200]}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError("failed: " + url)


def rnd(c):
    return [round(c[0], 5), round(c[1], 5)]


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".json.gz")
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    print(f"wrote {p} ({os.path.getsize(p) // 1024} KB)", file=sys.stderr)


def esri_paths(g):
    if not g:
        return []
    if "paths" in g:
        return [[rnd(c) for c in p] for p in g["paths"]]
    if "rings" in g:
        return [[rnd(c) for c in p] for p in g["rings"]]
    if "x" in g:
        return [[rnd([g["x"], g["y"]])]]
    return []


def layer_query(layer_url, bbox, simplify=0.00005):
    """Every feature of an ArcGIS layer inside bbox (w, s, e, n), all attributes, geometry in [lon, lat]."""
    meta = http(layer_url, {"f": "json"})
    env = json.dumps({"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3], "spatialReference": {"wkid": 4326}})
    j = http(layer_url + "/query", {"where": "1=1", "geometry": env, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                                     "spatialRel": "esriSpatialRelIntersects", "returnIdsOnly": "true", "f": "json"})
    oids = sorted(j.get("objectIds") or [])
    print(f"{layer_url}: {len(oids)} features", file=sys.stderr)
    feats = []
    for i in range(0, len(oids), 200):
        r = http(layer_url + "/query", {"objectIds": ",".join(map(str, oids[i:i + 200])), "outFields": "*", "returnGeometry": "true",
                                         "outSR": 4326, "maxAllowableOffset": simplify, "geometryPrecision": 5, "f": "json"})
        for f in r.get("features", []):
            a = {k: v for k, v in (f.get("attributes") or {}).items() if v not in (None, "", " ")}
            feats.append({"a": a, "g": esri_paths(f.get("geometry"))})
    return {"fields": [{"name": f["name"], "alias": f.get("alias"), "type": f.get("type"),
                        "domain": f.get("domain")} for f in meta.get("fields") or []],
            "name": meta.get("name"), "geometryType": meta.get("geometryType"), "features": feats}


def overpass(q):
    last = None
    for attempt in range(4):
        for url in OVERPASS:
            try:
                return http(url, {"data": q}, timeout=400, tries=1)
            except Exception as e:
                last = e
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"overpass failed: {last}")


def main():
    # 1. Zones
    z = http(FMZ, {"where": "FISHUNIT_NAME IN ('ES1','ES2','ES3','ES4','PP1','PP2')", "outFields": "*", "returnGeometry": "true",
                   "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.0002, "f": "json"})
    zones = {}
    for f in z.get("features", []):
        nm = f["attributes"].get("FISHUNIT_NAME")
        zones.setdefault(nm, []).extend(esri_paths(f["geometry"]))
    save("zones", zones)
    xs = [c[0] for k in ZONES for r in zones.get(k, []) for c in r]
    ys = [c[1] for k in ZONES for r in zones.get(k, []) for c in r]
    bbox = [min(xs) - 0.25, min(ys) - 0.12, max(xs) + 0.25, max(ys) + 0.12]
    print("bbox", bbox, file=sys.stderr)

    # 2. Government of Alberta roads
    save("ab_roads", layer_query(ROADS, bbox))

    # 3. Government of Alberta designated and provincial trails (every line layer)
    meta = http(TRAILS, {"f": "json"})
    out = {"layers": []}
    for L in meta.get("layers", []):
        if L.get("subLayerIds"):
            continue
        lm = http(f"{TRAILS}/{L['id']}", {"f": "json"})
        if lm.get("type") != "Feature Layer":
            continue
        try:
            d = layer_query(f"{TRAILS}/{L['id']}", bbox)
            d["id"] = L["id"]
            out["layers"].append(d)
        except Exception as e:
            print("trail layer", L, e, file=sys.stderr)
    save("ab_trails", out)

    # 4. OpenStreetMap, in tiles
    osm = {"ways": {}, "nodes": {}, "rels": {}}
    step = 0.5
    w0, s0, e0, n0 = bbox
    y = s0
    while y < n0:
        x = w0
        while x < e0:
            bb = f"{y:.4f},{x:.4f},{min(y + step, n0):.4f},{min(x + step, e0):.4f}"
            q = f"""[out:json][timeout:300];
(
 way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link|unclassified|track|road|path|footway|bridleway|steps)$"]({bb});
 way["highway"~"^(residential|service|living_street)$"]["name"]({bb});
 way["natural"="glacier"]({bb});
 way["boundary"~"^(protected_area|national_park)$"]({bb});
 way["leisure"="nature_reserve"]({bb});
);
out tags geom;
(
 relation["route"~"^(hiking|foot|horse)$"]({bb});
 relation["boundary"~"^(protected_area|national_park)$"]({bb});
 relation["leisure"="nature_reserve"]({bb});
 relation["natural"="glacier"]({bb});
 relation["boundary"="administrative"]["admin_level"~"^(2|4)$"]({bb});
);
out tags bb;
(
 node["place"~"^(city|town|village|hamlet|locality)$"]["name"]({bb});
 node["natural"~"^(peak|saddle|waterfall|glacier|spring|ridge)$"]["name"]({bb});
 node["mountain_pass"="yes"]["name"]({bb});
 node["waterway"="waterfall"]({bb});
 nwr["tourism"~"^(camp_site|alpine_hut|wilderness_hut|viewpoint|information)$"]["name"]({bb});
 nwr["tourism"="camp_site"]({bb});
 node["highway"="trailhead"]({bb});
 nwr["amenity"="parking"]["name"]({bb});
 nwr["amenity"="ranger_station"]({bb});
 nwr["leisure"="slipway"]({bb});
 node["man_made"="tower"]["tower:type"~"observation|fire"]({bb});
 node["waterway"="dam"]["name"]({bb});
 way["waterway"="dam"]({bb});
 node["ford"="yes"]({bb});
 node["barrier"="gate"]({bb});
 node["bridge"]["name"]({bb});
);
out tags center;"""
            j = overpass(q)
            for e in j.get("elements", []):
                t = e.get("tags") or {}
                if e["type"] == "way" and "geometry" in e:
                    osm["ways"][e["id"]] = {"t": t, "g": [rnd([p["lon"], p["lat"]]) for p in e["geometry"]]}
                elif e["type"] == "relation":
                    osm["rels"][e["id"]] = {"t": t, "b": e.get("bounds")}
                else:
                    c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
                    if c.get("lat") is None:
                        continue
                    key = f"{e['type'][0]}{e['id']}"
                    osm["nodes"][key] = {"t": t, "c": rnd([c["lon"], c["lat"]])}
            print(f"osm tile {bb}: ways {len(osm['ways'])} rels {len(osm['rels'])} nodes {len(osm['nodes'])}", file=sys.stderr)
            time.sleep(3)
            x += step
        y += step
    # Relation members (hiking routes take their name onto the ways; boundaries need member way geometry)
    rid = list(osm["rels"].keys())
    members = {}
    for i in range(0, len(rid), 150):
        j = overpass(f"[out:json][timeout:300];relation(id:{','.join(map(str, rid[i:i + 150]))});out body;")
        for r in j.get("elements", []):
            members[r["id"]] = [[m["type"][0], m["ref"], m.get("role", "")] for m in r.get("members", [])]
    for k, v in members.items():
        osm["rels"][k]["m"] = members[k]
    need = sorted({m[1] for k, ms in members.items() for m in ms if m[0] == "w" and m[1] not in osm["ways"]
                   and (osm["rels"][k]["t"].get("boundary") or osm["rels"][k]["t"].get("leisure") or osm["rels"][k]["t"].get("natural"))})
    print("boundary member ways to fetch:", len(need), file=sys.stderr)
    clip = f"{s0 - 1:.4f},{w0 - 1:.4f},{n0 + 1:.4f},{e0 + 1:.4f}"
    for i in range(0, len(need), 400):
        j = overpass(f"[out:json][timeout:300];way(id:{','.join(map(str, need[i:i + 400]))})({clip});out tags geom;")
        for e in j.get("elements", []):
            if "geometry" in e:
                osm["ways"][e["id"]] = {"t": e.get("tags") or {}, "g": [rnd([p["lon"], p["lat"]]) for p in e["geometry"]], "bm": 1}
    osm["bbox"] = bbox
    osm["built"] = time.strftime("%Y-%m-%d")
    save("osm", osm)


if __name__ == "__main__":
    main()
