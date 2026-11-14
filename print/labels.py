"""Label placement for the wall maps: point labels and text curved along lines, with collision avoidance.
All coordinates are paper millimetres; text sizes are in points."""
import math
from shapely.geometry import LineString, Polygon, box
from shapely.strtree import STRtree
from reportlab.pdfbase.pdfmetrics import stringWidth

PT = 25.4 / 72  # mm per point


class Occupancy:
    """Placed label shapes in a uniform grid hash for fast overlap tests."""

    def __init__(self, cell=8.0):
        self.cell = cell
        self.grid = {}

    def _cells(self, b):
        c = self.cell
        for i in range(int(b[0] // c), int(b[2] // c) + 1):
            for j in range(int(b[1] // c), int(b[3] // c) + 1):
                yield (i, j)

    def hits(self, g):
        b = g.bounds
        seen = set()
        for k in self._cells(b):
            for idx, o in self.grid.get(k, ()):
                if idx in seen:
                    continue
                seen.add(idx)
                if o.intersects(g):
                    return True
        return False

    def add(self, g):
        idx = id(g)
        for k in self._cells(g.bounds):
            self.grid.setdefault(k, []).append((idx, g))


def text_w(txt, font, size):
    return stringWidth(txt, font, size) * PT


def resample(path):
    """Cumulative distances for a polyline [(x, y), ...]."""
    d = [0.0]
    for i in range(1, len(path)):
        d.append(d[-1] + math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]))
    return d


def at(path, cum, s):
    """Point and segment index at distance s along path."""
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = max(1, hi)
    a, b = path[seg - 1], path[seg]
    L = cum[seg] - cum[seg - 1] or 1e-9
    t = (s - cum[seg - 1]) / L
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def runs_chars(runs):
    """[(text, font, colour), ...] -> [(char, font, colour), ...]"""
    return [(ch, f, c) for t, f, c in runs for ch in t]


def runs_w(runs, size):
    return sum(stringWidth(t, f, size) for t, f, c in runs) * PT


def glyph_layout(path, cum, s0, chars, size, win, bend=28, total=75):
    """Per-character (x, y, angle) for text starting at distance s0 along path, angle from a chord over +-win mm.
    Returns None if the bend is too sharp."""
    pos = []
    s = s0
    angs = []
    for ch, font, col in chars:
        w = stringWidth(ch, font, size) * PT
        mid = s + w / 2
        a = at(path, cum, max(0, mid - win)); b = at(path, cum, min(cum[-1], mid + win))
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        p = at(path, cum, mid)
        pos.append((p, ang, w))
        angs.append(ang)
        s += w
    # bend limits
    for i in range(1, len(angs)):
        d = abs((angs[i] - angs[i - 1] + math.pi) % (2 * math.pi) - math.pi)
        if d > math.radians(bend):
            return None
    tot = abs((angs[-1] - angs[0] + math.pi) % (2 * math.pi) - math.pi)
    if tot > math.radians(total):
        return None
    out = []
    for (p, ang, w), (ch, font, col) in zip(pos, chars):
        # glyph origin = centre point moved back half a width along the angle, and down to the baseline
        h = size * PT * 0.33
        x = p[0] - math.cos(ang) * w / 2 + math.sin(ang) * h
        y = p[1] - math.sin(ang) * w / 2 - math.cos(ang) * h
        out.append((x, y, math.degrees(ang), ch, font, col))
    return out


def line_candidates(path, runs, size, step=3.0, offset=0.0, smax=None):
    """Yield (score, s0, glyphs, shape) for labels along a polyline. offset > 0 puts the text beside the line."""
    cum = resample(path)
    L = cum[-1]
    chars = [c for c in runs_chars(runs)]
    if not "".join(c[0] for c in chars).strip():
        return []
    tw = runs_w(runs, size)
    if L < tw * 1.05:
        return []
    # reading direction: flip the path if the label would read right-to-left
    out = []
    win = max(1.2, size * PT * 0.9)
    s = 0.02 * L
    while s + tw <= L * 0.98:
        a = at(path, cum, s); b = at(path, cum, s + tw)
        rev = b[0] < a[0]
        p2, c2, s2 = (path, cum, s) if not rev else (path[::-1], resample(path[::-1]), L - s - tw)
        g = glyph_layout(p2, c2, s2, chars, size, win, *((14, 40) if offset else (28, 75)))
        if g:
            # straightness score: distance of chord midpoint from path midpoint
            m = at(path, cum, s + tw / 2)
            ch = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            dev = math.hypot(m[0] - ch[0], m[1] - ch[1])
            centre = abs((s + tw / 2) - L / 2) / L
            if offset:
                ang = math.radians(g[len(g) // 2][2])
                nx, ny = -math.sin(ang) * offset, math.cos(ang) * offset
                g = [(x + nx, y + ny) + tuple(rest) for x, y, *rest in g]
            sub = [at(p2, c2, s2 + k * tw / 8) for k in range(9)]
            if offset:
                ang = math.radians(g[len(g) // 2][2])
                sub = [(x - math.sin(ang) * offset, y + math.cos(ang) * offset) for x, y in sub]
            shape = LineString(sub).buffer(size * PT * 0.55, cap_style=2)
            out.append((dev * 2 + centre, s, g, shape))
        s += step
    return out


def point_shape(x, y, w, h, pos, gap):
    """Rectangle for a point label at one of 8 positions around (x, y). Returns (shape, text x, baseline y, anchor)."""
    dx = {"E": gap, "W": -gap - w, "N": -w / 2, "S": -w / 2, "NE": gap * 0.7, "NW": -gap * 0.7 - w, "SE": gap * 0.7, "SW": -gap * 0.7 - w, "C": -w / 2}[pos]
    dy = {"E": -h / 2, "W": -h / 2, "N": gap, "S": -gap - h, "NE": gap * 0.5, "NW": gap * 0.5, "SE": -gap * 0.5 - h, "SW": -gap * 0.5 - h, "C": -h / 2}[pos]
    x0, y0 = x + dx, y + dy
    return box(x0, y0, x0 + w, y0 + h), x0, y0 + h * 0.22
