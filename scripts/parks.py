"""Read the Parks Canada fish CSVs in data/parks/raw/ (downloaded by fetch_parks.py)
and turn them into species records per named waterbody, with survey locations
where the dataset gives them. Nothing here is inferred beyond what the files say;
code spellings are normalised to the FWMIS codes using Parks Canada's own data
dictionaries (e.g. RBTR = rainbow trout, CTTR/RBTR hybrid = cutthroat x rainbow)."""
import csv, io, math, os, re

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "parks", "raw")
# Parks Canada spelling -> FWMIS code (same species, per the Parks Canada data dictionaries).
CODE_MAP = {"RBTR": "RNTR", "BRTR": "BNTR", "BUBT": "BURB", "PYWH": "PGWH", "CTTR/RBTR HYBRID": "CRTR"}
PARK_BBOX = {  # lon/lat boxes used only to reject coordinates that fall outside the park
    "Jasper": (-119.3, 52.1, -116.9, 53.5),
    "Waterton": (-114.25, 48.99, -113.65, 49.25),
    "Banff": (-116.7, 50.7, -115.0, 52.2),
}
DS = {
    "jasper": "https://open.canada.ca/data/en/dataset/27fa5915-2e9a-4942-b986-953119c6fae2",
    "waterton_lakes": "https://open.canada.ca/data/en/dataset/aea61195-065b-4848-aba3-fab32c33e54c",
    "waterton_streams": "https://open.canada.ca/data/en/dataset/3732ac14-e30c-4128-b8f0-5b9281c6b719",
    "banff_streams": "https://open.canada.ca/data/en/dataset/07c1c8d0-ad43-4411-bb79-278f9f50fb96",
}


def utm_to_lonlat(zone, e, n):
    """WGS84 / NAD83 UTM (northern hemisphere) to lon/lat."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x = e - 500000.0; m = n / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu) \
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    c1 = ep2 * math.cos(p1) ** 2; t1 = math.tan(p1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2); r1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p1)
    return (zone - 1) * 6 - 180 + 3 + math.degrees(lon), math.degrees(lat)


def in_park(park, lon, lat):
    x0, y0, x1, y1 = PARK_BBOX[park]
    return x0 <= lon <= x1 and y0 <= lat <= y1


def norm_code(c):
    c = (c or "").strip().upper()
    return CODE_MAP.get(c, c) if re.fullmatch(r"[A-Z]{3,5}|CTTR/RBTR HYBRID", c) else None


def read(name_part):
    for f in sorted(os.listdir(RAW)):
        if name_part in f and "dictionary" not in f and f.endswith(".csv"):
            raw = open(os.path.join(RAW, f), "rb").read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
            rows = list(csv.reader(io.StringIO(text)))
            return rows[0], rows[2:]  # row 1 is the French header
    return None, []


def records():
    out = []

    # Jasper: one row per species per survey, UTM zone 11 transect start.
    hdr, rows = read("jasper_np_freshwater_fish_inventory")
    if hdr:
        by = {}
        for r in rows:
            if len(r) < 9:
                continue
            name, code = r[4].strip(), norm_code(r[6])
            if not name or not code:
                continue
            try:
                lon, lat = utm_to_lonlat(11, float(r[7]), float(r[8]))
            except ValueError:
                lon = lat = None
            rec = by.setdefault(name, {"park": "Jasper", "name": name, "species": set(), "points": [], "years": set(), "sites": [], "src": DS["jasper"]})
            rec["species"].add(code)
            yr = int(r[1][:4]) if r[1][:4].isdigit() else 0
            if yr:
                rec["years"].add(yr)
            if lon is not None and in_park("Jasper", lon, lat):
                rec["points"].append((round(lon, 5), round(lat, 5)))
                rec["sites"].append({"lon": round(lon, 5), "lat": round(lat, 5), "yr": yr, "codes": {code}, "method": r[3].strip()})
        out += by.values()

    # Waterton lakes: current (2011) species per lake, no coordinates.
    hdr, rows = read("waterton_lakes_np_freshwater_lake_fish_index")
    if hdr:
        by = {}
        for r in rows:
            if len(r) < 9:
                continue
            name, code = r[1].strip(), norm_code(r[8])
            if not name:
                continue
            rec = by.setdefault(name, {"park": "Waterton", "name": name, "kind": "lake", "species": set(), "points": [], "years": {2011}, "sites": [], "src": DS["waterton_lakes"]})
            if code:
                rec["species"].add(code)
        out += [r for r in by.values() if r["species"]]

    # Waterton streams: electrofishing counts per site, UTM.
    hdr, rows = read("waterton_lakes_np_freshwater_stream_fish_occupancy")
    if hdr:
        cols = {12: "CTTR", 13: "BKTR", 14: "BLTR", 15: "RNTR"}
        by = {}
        for r in rows:
            if len(r) < 17 or not r[2].strip():
                continue
            name = r[2].strip()
            rec = by.setdefault(name, {"park": "Waterton", "name": name, "kind": "stream", "species": set(), "points": [], "years": {2016}, "sites": [], "src": DS["waterton_streams"]})
            found = set()
            for i, code in cols.items():
                try:
                    if float(r[i] or 0) > 0:
                        found.add(code)
                except ValueError:
                    pass
            for part in r[16].split(","):
                m = re.match(r"\s*\d+\s+(.+?)\s*$", part)
                if m and norm_code(m.group(1)):
                    found.add(norm_code(m.group(1)))
            rec["species"] |= found
            try:
                lon, lat = utm_to_lonlat(int(r[3]), float(r[4]), float(r[5]))
                if in_park("Waterton", lon, lat):
                    rec["points"].append((round(lon, 5), round(lat, 5)))
                    if found:
                        rec["sites"].append({"lon": round(lon, 5), "lat": round(lat, 5), "yr": 2016, "codes": found, "method": "Electrofishing"})
            except ValueError:
                pass
        out += [r for r in by.values() if r["species"]]
    return out


def banff_watersheds():
    """Banff stream occupancy is reported per watershed only (no sites)."""
    hdr, rows = read("banff_np_freshwater_stream_fish_occupancy")
    res = {}
    for r in rows:
        if len(r) >= 4 and r[0].strip():
            res.setdefault(r[0].strip(), {})[norm_code(r[1]) or r[1].strip()] = [r[2], r[3]]
    return res
