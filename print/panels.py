"""Title block and legend of the wall maps."""
import datetime, math
from reportlab.lib.colors import white, black
from shapely.geometry import box
from make_wallmap import (hexrgb, stroke_lines, fill_geom, geom_lines, ROAD, TRAIL_COL, WATER, LAKE_FILL, ZONE_COL, PARK_COL,
                          F, FB, FI, FBI, PT)
from common import SPECIES, SP, RARITY, REGS, INDEX, sel_only, all_sp
from reportlab.pdfbase.pdfmetrics import stringWidth


def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if stringWidth(t, font, size) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def para(c, x, y, text, size_pt, width, font=F, col="#222222", lead=1.22):
    sz = size_pt * PT
    c.setFont(font, sz); c.setFillColor(hexrgb(col))
    for ln in wrap(text, font, sz, width):
        c.drawString(x, y, ln)
        y -= sz * lead
    return y


def panel_bg(c, x0, y0, x1, y1):
    c.setFillColor(hexrgb("#ffffff", 0.95)); c.setStrokeColor(hexrgb("#37474f")); c.setLineWidth(0.3)
    c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=1)


def heading(c, x, y, text, w):
    c.setFillColor(hexrgb("#1f4d2b")); c.setFont(FB, 9 * PT); c.drawString(x, y, text)
    c.setStrokeColor(hexrgb("#1f4d2b")); c.setLineWidth(0.2); c.line(x, y - 1.0, x + w, y - 1.0)
    return y - 5.0


def draw_title(m, x0, y0, x1, y1):
    c = m.c
    panel_bg(c, x0, y0, x1, y1)
    pad = 6
    x, y = x0 + pad, y1 - pad - 9
    c.setFillColor(hexrgb("#1f4d2b")); c.rect(x0, y1 - 26, x1 - x0, 26, stroke=0, fill=1)
    c.setFillColor(white); c.setFont(FB, 30 * PT); c.drawString(x, y1 - 14, "Eastern Slopes Trout Map")
    c.setFont(F, 15 * PT); c.drawString(x, y1 - 22, m.cfg["title"])
    y = y1 - 32
    y = para(c, x, y, m.cfg["sub"], 8.5, x1 - x0 - 2 * pad, F, "#333333")
    # left column: scale, north arrow, notes; right: locator
    lx = x
    colw = (x1 - x0) * 0.60
    yy = y - 3
    c.setFillColor(black); c.setFont(FB, 12 * PT); c.drawString(lx, yy, f"Scale 1:{m.scale:,}")
    c.setFont(F, 7 * PT); c.drawString(lx + 52, yy, "1 cm on the map = %s km on the ground" % (f"{m.scale / 100000:g}"))
    yy -= 8
    # scale bar in km
    km_mm = 1e6 / m.scale  # mm per km
    total = 40 if m.scale <= 400000 else 50
    step = 5 if total == 40 else 10
    bx = lx
    for i in range(0, total, step):
        c.setFillColor(black if (i // step) % 2 == 0 else white); c.setStrokeColor(black); c.setLineWidth(0.2)
        c.rect(bx + i * km_mm, yy, step * km_mm, 1.6, stroke=1, fill=1)
    c.setFont(F, 6.5 * PT); c.setFillColor(black)
    for i in range(0, total + 1, step):
        c.drawCentredString(bx + i * km_mm, yy - 3.0, str(i))
    c.drawString(bx + total * km_mm + 2.5, yy - 0.2, "kilometres")
    yy -= 7.5
    mi_mm = km_mm * 1.609344
    tmi = 25 if total == 40 else 30
    smi = 5
    for i in range(0, tmi, smi):
        c.setFillColor(black if (i // smi) % 2 == 0 else white)
        c.rect(bx + i * mi_mm, yy, smi * mi_mm, 1.2, stroke=1, fill=1)
    c.setFillColor(black)
    for i in range(0, tmi + 1, smi):
        c.drawCentredString(bx + i * mi_mm, yy - 2.8, str(i))
    c.drawString(bx + tmi * mi_mm + 2.5, yy - 0.2, "miles")
    yy -= 9
    # north arrow and declination
    try:
        from pygeomag import GeoMag
        g = GeoMag(coefficients_file="wmm/WMM_2025.COF")
        lon_c, lat_c = m.zone_ll.centroid.x, m.zone_ll.centroid.y
        now = datetime.date.today()
        dec = g.calculate(glat=lat_c, glon=lon_c, alt=0, time=now.year + (now.timetuple().tm_yday / 365.25)).d
    except Exception:
        dec, lat_c, lon_c = None, 0, 0
    ax, ay = lx + 8, yy - 20
    rot = getattr(m, "rot", 0.0) or 0.0
    def ray(deg, L):
        a = math.radians(deg - rot)  # deg clockwise from true north; the map is turned rot deg counter-clockwise
        return ax + math.sin(a) * L, ay + math.cos(a) * L
    c.setStrokeColor(black); c.setFillColor(black); c.setLineWidth(0.3)
    tip = ray(0, 19)
    c.line(ax, ay, *ray(0, 18))
    l, r = ray(-9.6, 13.2), ray(9.6, 13.2)
    p = c.beginPath(); p.moveTo(*l); p.lineTo(*tip); p.lineTo(*r); p.close(); c.drawPath(p, stroke=0, fill=1)
    nx, ny = ray(0, 21)
    c.setFont(FB, 9 * PT); c.drawCentredString(nx, ny, "N")
    if dec is not None:
        mx, my = ray(dec, 16)
        c.setDash(0.8, 0.5); c.line(ax, ay, mx, my); c.setDash()
        c.setFont(F, 6 * PT); c.drawString(mx + 0.8, my - 0.8, "MN")
    c.setFont(F, 6.6 * PT)
    tx = lx + 20
    if abs(rot) > 0.01:
        turn = (f"The map is turned {abs(rot):.1f}° {'anticlockwise' if rot > 0 else 'clockwise'} to fit the zone on the sheet, "
                f"so true north (N) points {abs(rot):.1f}° {'left' if rot > 0 else 'right'} of straight up. ")
    else:
        turn = f"True north is up along the centre meridian ({abs(m.fr.lon0):.2f}°W). "
    txt = (turn + f"Magnetic north (MN) is about {dec:.1f}° east of true north "
           f"at the centre of the zone ({datetime.date.today().year}, World Magnetic Model 2025) and is decreasing by about 0.1° a year."
           if dec is not None else turn)
    para(c, tx, ay + 16, txt, 6.6, colw - 26)
    yy = ay - 6
    yy = para(c, lx, yy, "Projection: transverse Mercator centred on the zone, NAD83 / WGS84 coordinates. Graticule every 15' of latitude and "
              "longitude; the lettered columns and numbered rows in the margins name each grid square (used in the regulation tables on the back).", 6.6, colw - 4)
    yy -= 2
    built = (INDEX.get("meta") or {}).get("built", "")
    eff = (REGS.get("meta") or {}).get("effective") or ["", ""]
    yy = para(c, lx, yy, f"Printed {datetime.date.today().isoformat()}. Fish data built {built}; regulations {eff[0]} to {eff[1]}; roads and trails "
              f"{m.osm.get('built', '')}.", 6.6, colw - 4, FB)
    yy -= 2
    src = ("Sources: Fish records, lakes and streams: Government of Alberta FWMIS (Fish and Wildlife Management Information System) and Parks Canada open data. "
           "Regulations: Alberta Guide to Sportfishing Regulations (albertaregulations.ca). Fish Management Zones: Government of Alberta fisheries regulations service. "
           "Roads: OpenStreetMap contributors (ODbL) and Government of Alberta access roads. Trails: Government of Alberta designated and provincial trails, "
           "OpenStreetMap contributors. Places, parks and glaciers: OpenStreetMap contributors. Relief: AWS Terrain Tiles (USGS, NRCan CDEM and other open elevation data).")
    yy = para(c, lx, yy, src, 6.0, colw - 4, F, "#444444")
    yy -= 1.5
    disc = ("A fish record means the species was caught at that place in that year, not that it is there today. Roads and trails change: gates, washouts, "
            "seasonal and OHV closures, and private land are not all shown. Always check current regulations, closures and access before you go.")
    para(c, lx, yy, disc, 6.0, colw - 4, FI, "#444444")
    # locator map (right column)
    lx0, ly0 = x0 + colw + 10, y0 + pad + 6
    lx1, ly1 = x1 - pad, y - 4
    draw_locator(m, lx0, ly0, lx1, ly1)


def draw_locator(m, x0, y0, x1, y1):
    c = m.c
    zs = m.zones_all
    from shapely.ops import unary_union
    allg = unary_union(list(zs.values()))
    b = allg.bounds
    # simple equirectangular with cos(lat) scaling
    lat_c = (b[1] + b[3]) / 2
    kx = math.cos(math.radians(lat_c))
    w, h = (b[2] - b[0]) * kx, (b[3] - b[1])
    s = min((x1 - x0) / w, (y1 - y0 - 8) / h)
    ox = x0 + ((x1 - x0) - w * s) / 2
    oy = y0 + 6

    def tr(g):
        from shapely.ops import transform
        return transform(lambda X, Y, Z=None: (ox + (X - b[0]) * kx * s, oy + (Y - b[1]) * s), g)
    for z, g in sorted(zs.items()):
        gm = tr(g)
        on = z in m.cfg["zones"]
        fill_geom(c, gm, ZONE_COL if on else "#e0e0e0", stroke="#616161", lw=0.15, alpha=0.75 if on else 1)
        p = gm.representative_point()
        c.setFillColor(white if on else hexrgb("#424242")); c.setFont(FB if on else F, (8 if on else 6) * PT)
        c.drawCentredString(p.x, p.y - 1, z)
    # map frame outline on the locator
    fr = m.fr
    import numpy as np
    pts = []
    for (px, py) in [(fr.fx0, fr.fy0), (fr.fx1, fr.fy0), (fr.fx1, fr.fy1), (fr.fx0, fr.fy1), (fr.fx0, fr.fy0)]:
        pts.append(fr.inv(px, py))
    from shapely.geometry import LineString
    ln = tr(LineString(pts))
    stroke_lines(c, [list(ln.coords)], 0.35, "#c62828")
    # towns for orientation
    for nm, lon, lat in (("Calgary", -114.07, 51.05), ("Lethbridge", -112.84, 49.69), ("Red Deer", -113.81, 52.27), ("Edmonton", -113.49, 53.55),
                         ("Hinton", -117.57, 53.4), ("Banff", -115.57, 51.18), ("Pincher Creek", -113.95, 49.49)):
        x, y = ox + (lon - b[0]) * kx * s, oy + (lat - b[1]) * s
        if x0 < x < x1 and y0 < y < y1:
            c.setFillColor(black); c.circle(x, y, 0.5, stroke=0, fill=1)
            c.setFont(F, 5.5 * PT); c.drawString(x + 1, y + 0.6, nm)
    c.setFont(F, 6 * PT); c.setFillColor(hexrgb("#333333"))
    c.drawString(x0, y0 + 1, "Fish Management Zones; red outline: this map")


def sw_line(c, x, y, cw, lw, col, dash, halo=None, length=11):
    if halo:
        stroke_lines(c, [[(x, y), (x + length, y)]], halo[0], halo[1], cap=0)
    if cw:
        stroke_lines(c, [[(x, y), (x + length, y)]], cw, "#ffffff", cap=0)
    stroke_lines(c, [[(x, y), (x + length, y)]], lw, col, dash, cap=0)


def draw_legend(m, x0, y0, x1, y1, f=1.3):
    c = m.c
    panel_bg(c, x0, y0, x1, y1)
    c.saveState()
    c.translate(x0 * (1 - f), y1 * (1 - f)); c.scale(f, f)
    x1 = x0 + (x1 - x0) / f
    y0 = y1 - (y1 - y0) / f
    _legend(m, c, x0, y0, x1, y1)
    c.restoreState()


def _legend(m, c, x0, y0, x1, y1):
    pad = 5
    x, y = x0 + pad, y1 - pad - 4
    W = x1 - x0 - 2 * pad
    c.setFillColor(hexrgb("#1f4d2b")); c.setFont(FB, 14 * PT); c.drawString(x, y, "Legend")
    y -= 7
    # species
    y = heading(c, x, y, "Game fish recorded (lake or stretch of stream coloured by the rarest one)", W)
    present = set()
    for it in m.byid.values():
        if m.in_frame_ll(*it["c"]):
            present.update(sel_only(all_sp(it)))
    sp = [s for s in SPECIES if s["code"] in present]
    colw = W / 2
    for i, s in enumerate(sp):
        cx = x + (i % 2) * colw
        cy = y - (i // 2) * 4.3
        stroke_lines(c, [[(cx, cy + 0.9), (cx + 7, cy + 0.9)]], 1.1, s["color"], cap=0)
        c.setFont(FB, 7 * PT); c.setFillColor(hexrgb(s["color"])); c.drawString(cx + 9, cy, s["code"])
        c.setFont(F, 7 * PT); c.setFillColor(black); c.drawString(cx + 18, cy, s["name"])
    y -= ((len(sp) + 1) // 2) * 4.3 + 1
    y = para(c, x, y, "Rarest first, in this order: " + ", ".join(s["code"] for s in sp) + ". Codes in colour beside a water name list every game "
             "species recorded there. Non-game fish and survey sites are not shown.", 6.6, W)
    y -= 2
    y = heading(c, x, y, "Lakes and streams", W)
    rows = [
        (lambda xx, yy: sw_line(c, xx, yy + 0.9, 0, 0.55, "#1f6f8b", None, halo=(0.95, "#ffffff")), "Stream stretch with a game-fish record (colour = rarest species; width = stream size)"),
        (lambda xx, yy: (sw_line(c, xx, yy + 0.9, 0, 0.55, "#1f6f8b", None), stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.25, "#ffffff", (0.5, 0.6), cap=0)),
         "Stretch closed to angling all year (striped)"),
        (lambda xx, yy: sw_line(c, xx, yy + 0.9, 0, 0.24, WATER, None), "Stream with no game-fish record"),
        (lambda xx, yy: (c.setFillColor(hexrgb("#c0392b", 0.55)), c.setStrokeColor(hexrgb("#c0392b")), c.setLineWidth(0.22), c.roundRect(xx + 1, yy - 0.6, 9, 3, 1, stroke=1, fill=1)),
         "Lake with game fish (colour = rarest species)"),
        (lambda xx, yy: (c.setFillColor(hexrgb(LAKE_FILL)), c.setStrokeColor(hexrgb(WATER)), c.setLineWidth(0.1), c.roundRect(xx + 1, yy - 0.6, 9, 3, 1, stroke=1, fill=1)),
         "Lake with no game-fish record"),
        (lambda xx, yy: (c.setFont(FI, 6.5 * PT), c.setFillColor(hexrgb("#0b4f7c")), c.drawString(xx, yy, "Name †")), "Water with its own listing in the regulations (see tables on the back); others follow the zone default"),
    ]
    for f, t in rows:
        f(x, y)
        y = para(c, x + 14, y, t, 6.8, W - 14) - 0.8
    y -= 1
    y = heading(c, x, y, "Roads (all named roads are labelled)", W)
    for cl, t in (("hwy", "Highway, paved (number in red shield)"), ("major", "Secondary highway, paved (number in white shield)"),
                  ("paved", "Other paved road"), ("gravel", "Gravel, dirt or unknown surface road"),
                  ("track", "Track: unimproved, often 4x4 or OHV only; may be gated")):
        cw, lw, col, dash = ROAD[cl]
        sw_line(c, x, y + 0.9, cw, lw, col, dash, halo=(lw + 0.25, "#ffffff") if cl == "track" else None)
        y = para(c, x + 14, y, t, 6.8, W - 14) - 0.8
    c.setFillColor(hexrgb("#7f1d00")); c.setFont(F, 6 * PT); c.drawString(x, y, "Road name")
    y = para(c, x + 14, y, "Road name or number along the road", 6.8, W - 14) - 1.6
    y = heading(c, x, y, "Trails (all named trails are labelled)", W)
    sw_line(c, x, y + 0.9, 0.55, 0.30, TRAIL_COL, (0.9, 0.45))
    y = para(c, x + 14, y, "Trail, path or bridle path (OpenStreetMap)", 6.8, W - 14) - 0.8
    stroke_lines(c, [[(x, y + 0.9), (x + 11, y + 0.9)]], 0.75, "#ffd54f", alpha=0.75)
    sw_line(c, x, y + 0.9, 0.55, 0.30, TRAIL_COL, (0.9, 0.45))
    y = para(c, x + 14, y, "Alberta designated or provincial trail (Government of Alberta), yellow underlay", 6.8, W - 14) - 0.8
    c.setFillColor(hexrgb(TRAIL_COL)); c.setFont(FI, 6 * PT); c.drawString(x, y, "Trail name")
    y = para(c, x + 14, y, "Trail name along the trail", 6.8, W - 14) - 1.6
    y = heading(c, x, y, "Places and access", W)
    items = [("city", "Town"), ("village", "Village"), ("hamlet", "Hamlet"), ("peak", "Peak, elevation in m"), ("pass", "Pass or saddle"),
             ("camp", "Campground or campsite"), ("hut", "Hut or cabin"), ("trailhead", "Trailhead"), ("parking", "Named parking / staging area"),
             ("gate", "Gate"), ("ford", "Ford"), ("launch", "Boat launch"), ("ranger", "Ranger station"), ("lookout", "Fire lookout or tower"),
             ("falls", "Waterfall"), ("dam", "Dam"), ("view", "Viewpoint"), ("info", "Information")]
    colw = W / 2
    for i, (k, t) in enumerate(items):
        cx = x + (i % 2) * colw
        cy = y - (i // 2) * 4.2
        m.symbol(k, cx + 3, cy + 0.9)
        c.setFillColor(black); c.setFont(F, 6.8 * PT); c.drawString(cx + 7, cy, t)
    y -= ((len(items) + 1) // 2) * 4.2 + 1
    y = heading(c, x, y, "Boundaries and areas", W)
    for f, t in (
        (lambda xx, yy: (stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 1.6, ZONE_COL, alpha=0.25), stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.55, ZONE_COL, (3.0, 1.4), cap=0)),
         ("Fish Management Zone shown on this map (nothing is shown outside it)" if getattr(m, "cfg", {}).get("hide_outside") else "Fish Management Zone shown on this map (area outside it is paler)")),
        (lambda xx, yy: stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.35, ZONE_COL, (2.0, 1.2), cap=0, alpha=0.8), "Other Fish Management Zone boundary"),
        (lambda xx, yy: (c.setFillColor(hexrgb("#4caf50", 0.12)), c.setStrokeColor(hexrgb(PARK_COL)), c.setLineWidth(0.18), c.setDash(1.5, 0.8), c.rect(xx + 1, yy - 0.6, 9, 3, stroke=1, fill=1), c.setDash()),
         "National park, provincial park or protected area (national parks: Parks Canada fishing permit and rules)"),
        (lambda xx, yy: (c.setFillColor(hexrgb("#f4fbff")), c.setStrokeColor(hexrgb("#7fb3d5")), c.setLineWidth(0.1), c.rect(xx + 1, yy - 0.6, 9, 3, stroke=1, fill=1)), "Glacier or permanent snow"),
        (lambda xx, yy: stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.3, "#212121", (2.2, 0.8, 0.4, 0.8), cap=0), "Provincial boundary"),
        (lambda xx, yy: stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.4, "#000000", (3, 1, 0.5, 1, 0.5, 1), cap=0), "International boundary"),
        (lambda xx, yy: stroke_lines(c, [[(xx, yy + 0.9), (xx + 11, yy + 0.9)]], 0.12, "#37474f", alpha=0.6), "Graticule, every 15' (grid squares A1, B2 ...)"),
    ):
        f(x, y)
        y = para(c, x + 14, y, t, 6.8, W - 14) - 0.8
    y -= 1
    y = heading(c, x, y, "Zone default regulations (waters not listed on the back)", W)
    for z in m.cfg["zones"]:
        d = REGS["defaults"].get(z) or {}
        for kind, lab in (("stream", "streams"), ("lake", "lakes")):
            rows = d.get(kind) or []
            seasons = "; ".join(r["s"]["t"].replace("OPEN ", "open ").replace("CLOSED ", "closed ") for r in rows)
            y = para(c, x, y, f"{z} {lab}: {seasons}.", 6.6, W, F) - 0.4
    para(c, x, y - 0.6, "Limits for these defaults are in the tables on the back. Bull trout and Arctic grayling: catch and release.", 6.6, W, FI)
