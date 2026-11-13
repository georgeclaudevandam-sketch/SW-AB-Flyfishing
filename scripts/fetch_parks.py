#!/usr/bin/env python3
"""Download Parks Canada fish datasets for Banff, Jasper and Waterton from the
Government of Canada Open Government Portal (CKAN API) into data/parks/raw/.
Licence: Open Government Licence - Canada."""
import json, os, re, sys, urllib.request

DATASETS = {
    "jasper_fish_inventory": "27fa5915-2e9a-4942-b986-953119c6fae2",
    "banff_stream_fish_occupancy": "07c1c8d0-ad43-4411-bb79-278f9f50fb96",
    "banff_lake_fish_index": "20b1a0ec-6415-46f7-80bb-a503c2669379",
    "waterton_lake_fish_index": "aea61195-065b-4848-aba3-fab32c33e54c",
    "waterton_stream_fish_occupancy": "3732ac14-e30c-4128-b8f0-5b9281c6b719",
}
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "parks", "raw")
API = "https://open.canada.ca/data/api/3/action/package_show?id="


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "eastern-slopes-trout-map/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


os.makedirs(OUT, exist_ok=True)
manifest = {}
for key, pid in DATASETS.items():
    try:
        pkg = json.loads(get(API + pid))["result"]
    except Exception as e:
        print(f"{key}: package lookup failed: {e}", file=sys.stderr)
        continue
    manifest[key] = {"id": pid, "title": pkg.get("title"), "files": []}
    for res in pkg.get("resources", []):
        url = res.get("url") or ""
        fmt = (res.get("format") or "").upper()
        lang = res.get("language") or []
        if fmt != "CSV" or (lang and "en" not in lang):
            continue
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", url.rsplit("/", 1)[-1]) or res["id"] + ".csv"
        try:
            data = get(url)
        except Exception as e:
            print(f"{key}: {url} failed: {e}", file=sys.stderr)
            continue
        with open(os.path.join(OUT, name), "wb") as fh:
            fh.write(data)
        manifest[key]["files"].append({"file": name, "name": res.get("name"), "url": url})
        print(f"{key}: {name} ({len(data)} bytes)")
with open(os.path.join(OUT, "manifest.json"), "w") as fh:
    json.dump(manifest, fh, indent=1)
