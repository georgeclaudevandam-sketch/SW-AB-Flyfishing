"""Back of each wall map: the water-specific regulation tables for the zone(s), laid out like the
Alberta Guide to Sportfishing Regulations (one table for lakes, one for rivers and streams), plus the zone defaults."""
import re
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import BaseDocTemplate, Frame as PFrame, PageTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, CondPageBreak
from common import REGS, ITEMS, MM, SP, listing_ids

LIMIT_COLS = ["Trout Total", "CTTR", "RNTR", "BKTR", "BNTR", "LKTR", "DLVR", "MNWH", "WALL", "SAUG", "WALL + SAUG", "NRPK", "YLPR", "LKWH", "BURB", "GOLD", "CISC"]
COL_HEAD = {"Trout Total": "Trout<br/>total", "WALL + SAUG": "WALL +<br/>SAUG"}
MON = {"JAN": "Jan.", "FEB": "Feb.", "MAR": "Mar.", "APR": "Apr.", "MAY": "May", "JUNE": "June", "JUNE.": "June", "JUN": "June", "JULY": "July",
       "JUL": "July", "AUG": "Aug.", "SEPT": "Sept.", "SEP": "Sept.", "OCT": "Oct.", "NOV": "Nov.", "DEC": "Dec."}
GREEN = colors.HexColor("#1f4d2b")
OPEN_BG = colors.HexColor("#e8f3e6")
CLOSED_BG = colors.HexColor("#f6e3e1")
RULE = colors.HexColor("#9aa79c")


def season_text(t):
    t = re.sub(r"\s+", " ", t.strip())
    t = re.sub(r"\b(JAN|FEB|MAR|APR|MAY|JUNE?|JULY?|AUG|SEPT?|OCT|NOV|DEC)\.?(?=\s|\d|,|$)", lambda m: MON.get(m.group(1), m.group(1)), t, flags=re.I)
    t = re.sub(r"\bOPEN\b", "OPEN", t, flags=re.I)
    t = re.sub(r"\bCLOSED\b", "CLOSED", t, flags=re.I)
    t = re.sub(r"\bALL YEAR\b", "all year", t, flags=re.I)
    t = re.sub(r"\bTO\b", "to", t)
    t = re.sub(r"\bBETWEEN SUNRISE AND SUNSET\b", "between sunrise and sunset", t, flags=re.I)
    t = re.sub(r"\bFROM\b|\bFRIDAY\b|\bSUNDAY\b|\bAFTER SUNSET THE FOLLOWING\b|\bSUNSET\b|\bSUNRISE\b|\bALL DAY\b|\bAND\b",
               lambda m: m.group(0).lower(), t)
    return t


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_back(path, *a, **k):
    """Largest type size (up to 9.5 pt) at which everything fits on one A1 page."""
    from pypdf import PdfReader
    for fs in (9.5, 9, 8.5, 8, 7.5, 7, 6.6, 6.2, 5.8):
        _build(path, fs, *a, **k)
        if len(PdfReader(path).pages) == 1:
            return fs
    return fs


def _build(path, fs, title, subtitle, zones, gridref, in_map, page_w=594, page_h=841, footer="", tags=None):
    F = "Carlito"
    st = {
        "cell": ParagraphStyle("cell", fontName=F, fontSize=fs, leading=fs * 1.12),
        "cellb": ParagraphStyle("cellb", fontName=F + "-Bold", fontSize=fs * 1.03, leading=fs * 1.15),
        "head": ParagraphStyle("head", fontName=F + "-Bold", fontSize=fs, leading=fs * 1.08, textColor=colors.white, alignment=TA_CENTER),
        "headl": ParagraphStyle("headl", fontName=F + "-Bold", fontSize=fs, leading=fs * 1.08, textColor=colors.white),
        "h1": ParagraphStyle("h1", fontName=F + "-Bold", fontSize=fs * 1.9, leading=fs * 2.2, textColor=GREEN, spaceBefore=4, spaceAfter=3),
        "note": ParagraphStyle("note", fontName=F, fontSize=fs * 1.08, leading=fs * 1.3),
        "noteb": ParagraphStyle("noteb", fontName=F + "-Bold", fontSize=fs * 1.1, leading=fs * 1.32),
    }
    u = fs / 6.6  # column widths grow with the type
    margin = 14
    head_h = 34
    gap = 8
    ncol = 2
    cw = (page_w - 2 * margin - gap * (ncol - 1)) / ncol
    frames = [PFrame((margin + i * (cw + gap)) * MM, (margin + 8) * MM, cw * MM, (page_h - 2 * margin - head_h - 8) * MM,
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id=f"c{i}") for i in range(ncol)]

    def page(c, doc):
        c.saveState()
        c.setFillColor(GREEN)
        c.rect(margin * MM, (page_h - margin - head_h + 6) * MM, (page_w - 2 * margin) * MM, (head_h - 6) * MM, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(F + "-Bold", 30)
        c.drawString((margin + 8) * MM, (page_h - margin - 16) * MM, title)
        c.setFont(F, 13)
        c.drawString((margin + 8) * MM, (page_h - margin - 24) * MM, subtitle)
        c.setFillColor(colors.HexColor("#333333"))
        c.setFont(F, 7)
        c.drawString(margin * MM, (margin + 2) * MM, footer)
        c.restoreState()

    doc = BaseDocTemplate(path, pagesize=(page_w * MM, page_h * MM), leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0,
                          title=title, author="Eastern Slopes Trout Map")
    doc.addPageTemplates([PageTemplate(id="p", frames=frames, onPage=page)])
    story = []
    m = REGS.get("meta") or {}
    eff = m.get("effective") or ["", ""]
    # which listings are drawn on this map, and where
    where = {}
    for it in ITEMS:
        if not in_map(it):
            continue
        for li in listing_ids(it):
            where.setdefault(li, []).append(gridref(*it["c"]))
    intro = (f"<b>Water-specific regulations</b> for {', '.join(zones)} from the <b>Alberta Guide to Sportfishing Regulations</b> "
             f"({esc(eff[0])} to {esc(eff[1])}), as published at albertaregulations.ca and read by the Eastern Slopes Trout Map. "
             "Each water listed here is marked <b>†</b> on the map; <b>Map</b> gives its grid square (letters along the top and bottom "
             "edges, numbers down the sides). Waters not listed follow the zone defaults at the end. Limits are the possession and size "
             "limits per angler: <b>0 fish</b> / <b>0 trout</b> means catch and release; <b>over 35 cm</b> means only fish longer than 35 cm may be kept. "
             "Bull trout and Arctic grayling are catch and release everywhere in these zones. Regulations change and corrections are published "
             "during the year: always check the current guide and My Wild Alberta advisories and closures before you fish.")
    story.append(Paragraph(intro, st["note"]))
    story.append(Spacer(1, 2 * MM))
    codes = sorted({k for L in REGS["list"] if L["zone"] in zones for s in L["sec"] for r in s["rows"] for k in (r.get("l") or {})},
                   key=lambda k: LIMIT_COLS.index(k) if k in LIMIT_COLS else 99)
    key = []
    for k in codes:
        if k in ("Trout Total",):
            key.append("<b>Trout total</b>: all trout species combined")
        elif k == "WALL + SAUG":
            key.append("<b>WALL + SAUG</b>: walleye and sauger combined")
        else:
            nm = SP[k]["name"] if k in SP else {"SAUG": "Sauger", "GOLD": "Goldeye", "CISC": "Cisco"}.get(k, k)
            key.append(f"<b>{k}</b> {esc(nm.lower())}")
    story.append(Paragraph("Columns: " + " · ".join(key) + ". Seasons in <font backColor='#e8f3e6'>&nbsp;green&nbsp;</font> are open; "
                           "<font backColor='#f6e3e1'>&nbsp;red&nbsp;</font> are closed.", st["note"]))
    story.append(Spacer(1, 3 * MM))

    for z in zones:
        for kind, label in (("lake", "Lakes"), ("stream", "Rivers and streams")):
            Ls = [(i, L) for i, L in enumerate(REGS["list"]) if L["zone"] == z and L["kind"] == kind]
            if not Ls:
                continue
            Ls.sort(key=lambda x: x[1]["name"].lower())
            cols = [c for c in LIMIT_COLS if any(c in (r.get("l") or {}) for _, L in Ls for s in L["sec"] for r in s["rows"])]
            head = [Paragraph("Waterbody", st["headl"]), Paragraph("Map", st["head"]),
                    Paragraph("Location" if kind == "lake" else "Section", st["headl"]), Paragraph("Open season", st["headl"]),
                    Paragraph("Bait", st["headl"])] + [Paragraph(COL_HEAD.get(c, c), st["head"]) for c in cols]
            fixed = [30 * u, 8 * u, 46 * u if kind == "stream" else 30 * u, 30 * u, 17 * u]
            rest = cw - sum(fixed)
            lw = max(9.0 * u, min(14.0 * u, rest / max(1, len(cols))))
            widths = [w * MM for w in fixed] + [lw * MM] * len(cols)
            if sum(widths) > cw * MM:  # shrink the section column if needed
                widths[2] -= sum(widths) - cw * MM
            elif sum(widths) < cw * MM:
                widths[2] += cw * MM - sum(widths)
            data = [head]
            style = [("BACKGROUND", (0, 0), (-1, 0), GREEN), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("LEFTPADDING", (0, 0), (-1, -1), 1.6), ("RIGHTPADDING", (0, 0), (-1, -1), 1.6),
                     ("TOPPADDING", (0, 0), (-1, -1), 0.9), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.9),
                     ("LINEBELOW", (0, 0), (-1, 0), 0.6, GREEN)]
            band = False
            for li, L in Ls:
                first_row_of_listing = len(data)
                refs = sorted(set(where.get(li, [])))
                ref = ", ".join(refs[:3]) + ("…" if len(refs) > 3 else "") if refs else "–"
                firstL = True
                for s in L["sec"]:
                    rows = s["rows"] or [{"s": {"t": "(no season given)", "open": []}}]
                    firstS = True
                    for r in rows:
                        t = r["s"].get("t") or ""
                        is_open = bool(r["s"].get("open"))
                        lim = r.get("l") or {}
                        notes = "; ".join(r.get("n") or [])
                        line = [Paragraph(esc(L["name"]), st["cellb"]) if firstL else "",
                                Paragraph(ref, st["cell"]) if firstL else "",
                                Paragraph(esc(s.get("d") or ""), st["cell"]) if firstS else "",
                                Paragraph(esc(season_text(t)) + (f"<br/><i>{esc(notes)}</i>" if notes else ""), st["cell"]),
                                Paragraph(esc(r.get("b") or ""), st["cell"])] + [Paragraph(esc(lim.get(c, "")), st["cell"]) for c in cols]
                        data.append(line)
                        rr = len(data) - 1
                        style.append(("BACKGROUND", (3, rr), (3, rr), OPEN_BG if is_open else CLOSED_BG))
                        if firstS and not firstL:
                            style.append(("LINEABOVE", (2, rr), (-1, rr), 0.25, RULE))
                        firstL = False
                        firstS = False
                if band:
                    style.append(("BACKGROUND", (0, first_row_of_listing), (2, len(data) - 1), colors.HexColor("#f3f5f2")))
                    style.append(("BACKGROUND", (4, first_row_of_listing), (-1, len(data) - 1), colors.HexColor("#f3f5f2")))
                band = not band
                style.append(("LINEABOVE", (0, first_row_of_listing), (-1, first_row_of_listing), 0.5, RULE))
            t = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
            t.setStyle(TableStyle(style))
            story.append(CondPageBreak(40 * MM))
            story.append(Paragraph(f"{z} {label}", st["h1"]))
            story.append(t)
            story.append(Spacer(1, 4 * MM))

    # zone defaults
    for z in zones:
        d = REGS["defaults"].get(z) or {}
        block = [Paragraph(f"{z} defaults: waters not listed above", st["h1"])]
        for kind, label in (("lake", "Lakes"), ("stream", "Rivers and streams")):
            rows = d.get(kind) or []
            data = [[Paragraph(label, st["headl"]), Paragraph("Limits and rules", st["headl"])]]
            sty = [("BACKGROUND", (0, 0), (-1, 0), GREEN), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                   ("LEFTPADDING", (0, 0), (-1, -1), 1.6), ("RIGHTPADDING", (0, 0), (-1, -1), 1.6),
                   ("TOPPADDING", (0, 0), (-1, -1), 0.9), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.9)]
            for r in rows:
                data.append([Paragraph(esc(season_text(r["s"]["t"])), st["cell"]), Paragraph(esc("; ".join(r.get("n") or [])) or "–", st["cell"])])
                sty.append(("BACKGROUND", (0, len(data) - 1), (0, len(data) - 1), OPEN_BG if r["s"].get("open") else CLOSED_BG))
                sty.append(("LINEABOVE", (0, len(data) - 1), (-1, len(data) - 1), 0.25, RULE))
            tb = Table(data, colWidths=[42 * u * MM, (cw - 42 * u) * MM])
            tb.setStyle(TableStyle(sty))
            block += [tb, Spacer(1, 2 * MM)]
        story.append(KeepTogether(block))
    if tags:
        story.append(CondPageBreak(30 * MM))
        story.append(Paragraph("Numbered roads and trails on the map", st["h1"]))
        story.append(Paragraph("Roads and trails too short or too crowded for their name at this scale carry a small number on the map instead.", st["note"]))
        story.append(Spacer(1, 1.5 * MM))
        per = 3
        rows = [[]]
        hdr = []
        for k in range(per):
            hdr += [Paragraph("No.", st["head"]), Paragraph("Name", st["headl"]), Paragraph("Type", st["headl"]), Paragraph("Map", st["head"])]
        data = [hdr]
        n = (len(tags) + per - 1) // per
        for i in range(n):
            line = []
            for k in range(per):
                j = i + k * n
                if j < len(tags):
                    num, name, kind, ref = tags[j]
                    line += [Paragraph(f"<b>{num}</b>", st["cell"]), Paragraph(esc(name), st["cell"]), Paragraph(kind, st["cell"]), Paragraph(ref, st["cell"])]
                else:
                    line += ["", "", "", ""]
            data.append(line)
        cwk = cw / per
        widths = [7 * u, cwk - 7 * u - 11 * u - 8 * u, 11 * u, 8 * u] * per
        tb = Table(data, colWidths=[w * MM for w in widths], repeatRows=1)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GREEN), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 1.4), ("RIGHTPADDING", (0, 0), (-1, -1), 1.4),
                                ("TOPPADDING", (0, 0), (-1, -1), 0.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f5f2")])]))
        story.append(tb)
    story.append(Spacer(1, 3 * MM))
    story.append(Paragraph("Read from the guide's zone pages and ES Lakes / Rivers tables by the map's data build (scripts/build_regs.py). "
                           "Where the guide adds time conditions (e.g. sunrise to sunset, weekend only) they are part of the season text. "
                           "This is a reading aid, not the legal text: the published guide, its corrections and in-season closures govern.", st["note"]))
    doc.build(story)
