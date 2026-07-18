#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Green-book generator (course-agnostic engine).

Reads the course selected by config.py (env COURSE=<slug>, default the first one)
and writes greenbook.html into that course's folder. Everything drawn is from
free/open data:
  * Yardage / par / handicap  = official scorecard (verified) -- facts.
  * Green + hole geometry     = OpenStreetMap contributors (ODbL).
  * Slope / contours / arrows = our own computation over public USGS LiDAR.
Not affiliated with, and not derived from, any commercial green-book product.
"""
import math
import os
import base64
import render_green
import render_hole
import config
from config import HOLES, NAME as COURSE, ADDRESS as ADDR, COURSE_DIR

GREENS = {}    # hole -> (svg, summary)
LAYOUTS = {}   # hole -> (svg, info)

# Young players (juniors, and men especially) play the BACK tee, so show the
# LONGER of the two configured tees as the big main yardage and the shorter as
# the small one, with FULL tee names (e.g. "Black", not "BLA").
_ftot = sum(HOLES[h][config.FI] for h in HOLES)
_stot = sum(HOLES[h][config.SI] for h in HOLES)
if _stot >= _ftot:
    BACK_I, BACK_NAME, FRONT_I, FRONT_NAME = config.SI, config.SECONDARY, config.FI, config.FEATURED
else:
    BACK_I, BACK_NAME, FRONT_I, FRONT_NAME = config.FI, config.FEATURED, config.SI, config.SECONDARY

ROOT = os.path.dirname(os.path.abspath(__file__))

def _data_uri(path):
    """Base64 data URI so raster assets print reliably in every book."""
    if not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    with open(path, "rb") as f:
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode()

IG_QR = _data_uri(os.path.join(ROOT, "lucaswu.golf_qr_small.png"))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tee_color(name):
    """Print-legible ink color matching the tee NAME (a "Black" tee prints in black,
    not gold). White/yellow get a readable dark substitute since they'd vanish on paper."""
    return {
        "black":  "#111111",
        "blue":   "#1c4e8a",
        "white":  "#555555",
        "red":    "#b02418",
        "gold":   "#b8860b",
        "green":  "#2b6a2b",
        "orange": "#c8641e",
        "silver": "#6b7683",
        "yellow": "#a98600",
    }.get((name or "").strip().lower(), "#b8860b")   # default: the house gold

# ---------------------------------------------------------------------------
# PANELS
# ---------------------------------------------------------------------------
def yardage_hole_panel(hole, sheet_label):
    """Yardage-mode card: verified facts only (par/hcp + every tee's yardage) plus a
    BLANK green to sketch the read. Used when accurate green-surface data isn't
    available yet (e.g. a course rebuilt after the latest public LiDAR)."""
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    feat = row[BACK_I]
    trows = "".join(f'<tr><td>{esc(t)}</td><td>{row[2+i]}</td></tr>' for i, t in enumerate(config.TEES))
    lines = "".join('<div class="nl"></div>' for _ in range(5))
    return f'''<div class="panel hole ycard">
  <div class="sheettab">{esc(sheet_label)}</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain" style="color:{tee_color(BACK_NAME)}">{feat}</span><span class="ylab" style="color:{tee_color(BACK_NAME)}">{esc(BACK_NAME)}</span></div>
  </div>
  <table class="ytab"><tr class="th"><td>Tee</td><td>Yards to green</td></tr>{trows}</table>
  <div class="ynotehd">Read &amp; notes</div>
  <div class="ynote">{lines}</div>
</div>'''

def yardage_guide_panel():
    return '''<div class="panel guide">
  <div class="gtitle">How to use this book</div>
  <div class="legrow"><span><b>Yardages</b> to the green for every tee are on each hole card &mdash;
    from the official scorecard. The big number is the <b>featured tee</b>.</span></div>
  <div class="legrow"><span>Use the <b>Read &amp; notes</b> lines to jot the pin, the slope you see, and how the
    ball rolls. Pair this with the printed <b>course aerial</b> to see fairways, bunkers, trees, greens &amp; tees.</span></div>
  <div class="legrow"><span>Green break arrows aren&rsquo;t printed &mdash; see &ldquo;About&rdquo; below for why (this course was
    rebuilt in 2025).</span></div>
  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> yardage book for junior golfers, <b>not for sale</b>. Par,
      yardage &amp; handicap are <b>facts</b> from the published scorecard. This course was <b>rebuilt in
      2025 with new greens</b>, and accurate post-construction green-surface data is not yet publicly
      available &mdash; so rather than print slope maps that could be wrong, the greens are left <b>blank
      to mark your own read</b>. (Our other books compute slope from public-domain USGS 3DEP elevation;
      that data does not yet reflect this rebuilt course, so we do not use it here.) <b>No proprietary
      data, images, artwork, layout or trade dress from any commercial green-reading product was used,
      copied or referenced.</b> Not affiliated with, endorsed or sponsored by any course, club, association
      or product; course names &amp; trademarks belong to their owners and are used only to identify the
      course &mdash; if a course would prefer not to be included, contact the maker for removal. Provided
      <b>free and as-is, with no warranty of any kind</b>; use at your own risk. Confirm materials/equipment
      rules with your Committee before competition. <b>lucasgreenbook.org</b> &middot; contact/removal <b>info@lucasgreenbook.org</b>.
      &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. This book: free to share, not for sale &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
  </div>
</div>'''

def hole_panel(hole, sheet_label):
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    gsvg, s = GREENS[hole]
    lsvg, i = LAYOUTS[hole]
    others = " / ".join(f"{lbl[:3]}{row[idx]}" for lbl, idx in config.OTHERS)
    return f'''<div class="panel hole">
  <div class="sheettab">{esc(sheet_label)}</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain" style="color:{tee_color(BACK_NAME)}">{row[BACK_I]}</span><span class="ylab" style="color:{tee_color(BACK_NAME)}">{esc(BACK_NAME)}</span>
      <span class="yalt">{row[FRONT_I]} {esc(FRONT_NAME)}</span></div>
  </div>
  <div class="body">
    <div class="lay"><div class="minilab">HOLE</div>{lsvg}</div>
    <div class="grn"><div class="minilab">GREEN</div>{gsvg}</div>
  </div>
  <div class="foot"><span>feeds <b>{esc(s['feeds'])}</b> ({esc(s['conf'])}) &middot; {s['tilt_pct']}%</span>
    <span>{s['depth_yd']}yd deep &middot; {i['bunkers']}B {i['waters']}W &middot; {esc(others)}</span></div>
</div>'''

def _title_lines(raw):
    """Cover-title lines, shared by the standard AND the enlarged (coach) covers:
    split a two-part name on the em-dash so the club and the course each keep their
    own line (e.g. "Monarch Bay Golf Club" / "Tony Lema Course"); otherwise keep a
    short name on one line and word-wrap only a genuinely long (>30 char) name."""
    raw = (raw or "").strip()
    if "—" in raw:
        return [p.strip() for p in raw.split("—") if p.strip()] or [raw]
    if len(raw) <= 30:
        return [raw]
    lines, cur = [], ""
    for w in raw.split():
        if len(cur) + len(w) + 1 <= 20:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines

def cover_panel():
    parts = config.BRAND.split()
    btop = esc(parts[0].upper()); bmain = esc(" ".join(parts[1:]).upper()) or "GREEN BOOK"
    tlines = _title_lines(COURSE)          # shared with the enlarged (coach) cover
    maxch = max(len(l) for l in tlines)
    fst = max(13.0, min(19.0, 274.0 / (maxch * 0.52)))   # shrink font so the longest line fits
    dyt = fst * 1.22
    cy0 = 292 - (len(tlines) - 1) * dyt / 2
    tspans = "".join(f'<tspan x="175" dy="{0 if k == 0 else dyt:.1f}">{esc(ln)}</tspan>'
                     for k, ln in enumerate(tlines))
    addr_y = cy0 + (len(tlines) - 1) * dyt + 22
    motif = "".join(
        f'<path d="M-20 {30+i*40} C 90 {30+i*40-26}, 200 {30+i*40+30}, 370 {30+i*40-14}" '
        f'fill="none" stroke="#c8a24a" stroke-width="1.1" opacity="0.06"/>' for i in range(13))
    G = "#c8a24a"        # gold
    return f'''<div class="panel cover"><svg viewBox="0 0 350 500" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
  <defs><linearGradient id="cg" x1="0" y1="0" x2="0.35" y2="1">
    <stop offset="0" stop-color="#12492f"/><stop offset="0.55" stop-color="#0a3a24"/><stop offset="1" stop-color="#04170f"/>
  </linearGradient></defs>
  <rect x="0" y="0" width="350" height="500" fill="#0a3521"/>
  <rect x="0" y="0" width="350" height="500" fill="url(#cg)"/>
  {motif}
  <rect x="17" y="17" width="316" height="466" fill="none" stroke="{G}" stroke-width="1.4"/>
  <rect x="21" y="21" width="308" height="458" fill="none" stroke="{G}" stroke-width="0.6" opacity="0.55"/>
  <circle cx="175" cy="110" r="26" fill="none" stroke="{G}" stroke-width="1.4"/>
  <circle cx="175" cy="110" r="21" fill="none" stroke="{G}" stroke-width="0.6" opacity="0.6"/>
  <line x1="171" y1="98" x2="171" y2="124" stroke="{G}" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M171 98 L186 103 L171 109 Z" fill="{G}"/>
  <text x="179" y="176" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="17" letter-spacing="8" font-weight="600" fill="#d7b45c">{btop}</text>
  <text x="175" y="218" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="35" letter-spacing="1.5" font-weight="800" fill="#fbf6ea">{bmain}</text>
  <line x1="118" y1="244" x2="232" y2="244" stroke="{G}" stroke-width="0.9"/>
  <rect x="171" y="240.5" width="7" height="7" fill="{G}" transform="rotate(45 175 244)"/>
  <text x="175" y="{cy0:.1f}" text-anchor="middle" font-family="Georgia,'Times New Roman',serif" font-style="italic" font-size="{fst:.1f}" fill="#f5eddd">{tspans}</text>
  <text x="175" y="{addr_y:.1f}" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="9" letter-spacing="1" fill="#9fb4a3">{esc(ADDR).upper()}</text>
  <rect x="70" y="426" width="210" height="18" rx="9" fill="none" stroke="#b9973f" stroke-width="0.8"/>
  <text x="175" y="438" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="7.0" letter-spacing="1.0" fill="#dcc27f">DESIGNED TO CONFORM &#183; RULE 4.3</text>
  <text x="175" y="462" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="8" letter-spacing="3" fill="#7f9484">JUNIOR GOLF EDITION</text>
  <text x="175" y="474" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="6.2" letter-spacing="0.5" fill="#6f8676">&#169; 2026 Lucas Wu &#183; Lucas Green Book&#8482;</text>
</svg></div>'''


def guide_panel():
    return '''<div class="panel guide">
  <div class="gtitle">How to read a green</div>
  <div class="legrow"><svg width="28" height="14"><line x1="2" y1="7" x2="18" y2="7" stroke="#15271b" stroke-width="1.3"/><polygon points="18,7 14,4.5 14,9.5" fill="#15271b"/></svg>
    <span><b>Arrows</b> point downhill &mdash; the way the ball rolls. Longer = steeper.</span></div>
  <div class="legrow"><svg width="28" height="14"><path d="M2,11 Q9,3 26,6" stroke="#3c5a34" fill="none" stroke-width="0.9"/><path d="M2,13 Q11,7 26,11" stroke="#3c5a34" fill="none" stroke-width="0.9"/></svg>
    <span><b>Contours</b> join equal height (15&nbsp;cm each). Close = steep.</span></div>
  <div class="legrow"><svg width="28" height="14"><rect x="2" y="3" width="7" height="9" fill="rgb(120,190,120)"/><rect x="10" y="3" width="7" height="9" fill="rgb(232,224,120)"/><rect x="18" y="3" width="7" height="9" fill="rgb(210,90,70)"/></svg>
    <span><b>Colour</b> = steepness: green flat &rarr; yellow &rarr; red (&ge;5%). <b>Numbers</b> = slope % there.</span></div>
  <div class="legrow"><span><b>HOLE</b> map: fairway (green), rough, <b>trees</b> (dark green), bunkers (tan), water (blue). Edge numbers: <b>left = yд to green</b>, <b>right = yд from the back tee</b>.</span></div>
  <div class="legrow"><span><b>GREEN</b> is turned so your <b>approach is at the bottom</b>; small <b>N</b> = true north. "feeds" = the low side putts run toward.</span></div>
  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> green book for junior golfers, <b>not for sale</b>. Hole &amp;
      green shapes are a Produced Work from <b>OpenStreetMap</b> data (&copy;&nbsp;OpenStreetMap
      contributors, <b>ODbL&nbsp;1.0</b>, osm.org/copyright); slope, contours &amp; arrows are computed by the
      maker from <b>public-domain USGS&nbsp;3DEP</b> elevation (a U.S. Government work); par, yardage &amp;
      handicap are <b>facts</b> from the published scorecard. Every map is <b>independently created</b>:
      <b>no proprietary data, image, symbol set, page layout or trade dress of any commercial green-reading
      product was used, copied, referenced or reverse-engineered</b>, and this book references no third-party
      brand and is not a substitute for any product. Built <b>entirely from remote public data, without
      entering any club or course</b>. Not affiliated with, endorsed or sponsored by any course, club,
      association or product; course names &amp; trademarks belong to their owners and are used only to
      identify the course &mdash; <b>if a course would prefer not to be included, contact the maker for
      removal</b>. This book is <b>designed</b> to fall within the size &amp; scale limits for green-reading
      materials under <b>Rule&nbsp;4.3</b>, but conformance is <b>not guaranteed</b> for every hole &mdash;
      <b>confirm with your Committee before competition; the maker is not responsible for any ruling,
      penalty or disqualification</b>. Provided <b>free and as-is, with no warranty of any kind</b>
      (accuracy, fitness or rules conformance): maps show general tilt &amp; tiers, not exact break, and may
      contain errors &mdash; <b>use at your own risk and trust your own read</b>. To the fullest extent
      permitted by law the maker is not liable for any loss, penalty or damage from use of this book.
      Learn more at <b>lucasgreenbook.org</b>; contact / removal requests: <b>info@lucasgreenbook.org</b>. &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. This book: free to share, not for sale &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
  </div>
</div>'''


def scorecard_panel():
    fl, sl = config.FEATURED, config.SECONDARY
    fi, si = config.FI, config.SI
    rows = []
    for h in range(1, 19):
        r = HOLES[h]
        rows.append(f"<tr><td>{h}</td><td>{r[0]}</td><td>{r[1]}</td><td>{r[fi]}</td><td>{r[si]}</td></tr>")
    op = sum(HOLES[h][0] for h in range(1,10)); ip = sum(HOLES[h][0] for h in range(10,19))
    of = sum(HOLES[h][fi] for h in range(1,10)); iff = sum(HOLES[h][fi] for h in range(10,19))
    os_ = sum(HOLES[h][si] for h in range(1,10)); iss = sum(HOLES[h][si] for h in range(10,19))
    return f'''<div class="panel card">
  <div class="cardtitle">Scorecard &mdash; {esc(fl)} / {esc(sl)}</div>
  <table>
    <tr class="th"><td>H</td><td>Par</td><td>HCP</td><td>{esc(fl[:4])}</td><td>{esc(sl[:4])}</td></tr>
    {''.join(rows[:9])}
    <tr class="sum"><td>Out</td><td>{op}</td><td></td><td>{of}</td><td>{os_}</td></tr>
    {''.join(rows[9:])}
    <tr class="sum"><td>In</td><td>{ip}</td><td></td><td>{iff}</td><td>{iss}</td></tr>
    <tr class="sum tot"><td>Tot</td><td>{op+ip}</td><td></td><td>{of+iff}</td><td>{os_+iss}</td></tr>
  </table>
</div>'''

def tees_panel():
    rows = "".join(
        f'<tr><td>{esc(t["name"][:7])}</td><td>{t["yards"]}</td><td>{t["rating"]}</td><td>{t["slope"]}</td></tr>'
        for t in config.TEE_TABLE)
    return f'''<div class="panel info">
  <div class="cardtitle">Tees &middot; Rating / Slope</div>
  <table class="tt">
    <tr class="th"><td>Tee</td><td>Yds</td><td>Rate</td><td>Slp</td></tr>
    {rows}
  </table>
  <div class="gsmall">All yardages from the official scorecard.</div>
</div>'''

def legend_panel():
    flag = ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<line x1="9" y1="4" x2="9" y2="22" stroke="#b8860b" stroke-width="1.6" stroke-linecap="round"/>'
            '<path d="M9 4 L20 8 L9 12 Z" fill="#b8860b"/></svg>')
    qr = (f'<div class="dqr"><img src="{IG_QR}" alt="@lucaswu.golf"/></div>') if IG_QR else ""
    return f'''<div class="panel dedic">
  <div class="dcrest">{flag}</div>
  <div class="dtitle">For every junior golfer</div>
  <div class="dtext">
    <p>A good green book shouldn&rsquo;t cost more than the round. Every kid who tees it
      up deserves the same honest read as anyone else &mdash; so I built this one and give
      it away.</p>
    <p>It is <b>not for sale</b>. It&rsquo;s a small personal contribution to junior golf,
      free to use and share.</p>
    <p>Play well, read true, and pass it on.</p>
  </div>
  <div class="drule"></div>
  <div class="dsign">Crafted by <b>Lucas Wu</b></div>
  <div class="dmail">lucasgreenbook.org &middot; info@lucasgreenbook.org</div>
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. Free to share, not for sale &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
  {qr}
</div>'''

def notes_panel(title, holes_range):
    lines = "".join(f'<div class="nrow"><b>{h}</b><span></span></div>' for h in holes_range)
    return f'<div class="panel notesp"><div class="gtitle">{esc(title)}</div>{lines}</div>'

# ---- imposition: one-cut 8-page zine ---------------------------------------
PHYS_ORDER = [5, 4, 3, 2, 6, 7, 8, 1]
ROTATED = {0, 1, 2, 3}

def crop_ticks(x, y, w, h, t=0.14):
    """L-shaped cut ticks just outside each corner of a card, for trimming."""
    segs = []
    for (cx, cy, hx, vy) in [(x, y, -1, -1), (x+w, y, 1, -1), (x, y+h, -1, 1), (x+w, y+h, 1, 1)]:
        hl = cx-t if hx < 0 else cx
        vt = cy-t if vy < 0 else cy
        segs.append(f'<div class="crop" style="left:{hl:.3f}in;top:{cy-0.003:.3f}in;width:{t}in;height:0.006in"></div>')
        segs.append(f'<div class="crop" style="left:{cx-0.003:.3f}in;top:{vt:.3f}in;width:0.006in;height:{t}in"></div>')
    return "".join(segs)

def main():
    yardage = (config.BUILD_MODE == "yardage")
    if not yardage:
        for h in range(1, 19):
            GREENS[h] = render_green.render(h, HOLES[h][3], tournament=True)  # single conforming book
            LAYOUTS[h] = render_hole.render_hole(h, HOLES)
    # flat, ordered deck of cards (cut-and-stack, top-bound)
    panels = [cover_panel(), yardage_guide_panel() if yardage else guide_panel()]
    for h in range(1, 19):
        grp = "Front" if h <= 6 else ("Mid" if h <= 14 else "Finish")
        panels.append(yardage_hole_panel(h, grp) if yardage else hole_panel(h, grp))
    panels += [scorecard_panel(), tees_panel(),
               notes_panel("Notes 1-9", range(1, 10)), legend_panel()]

    def doc(sheets, subtitle):
        return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{esc(subtitle)} &mdash; {esc(COURSE)}</title>
<style>
  @page {{ size: {config.PAGE_W_IN}in {config.PAGE_H_IN}in; margin: 0; }}
  * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  html, body {{ margin: 0; padding: 0; font-family: "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }}
  .sheet {{ width: {config.PAGE_W_IN}in; height: {config.PAGE_H_IN}in; position: relative; page-break-after: always; }}
  .card {{ position: absolute; width: {config.CARD_W_IN}in; height: {config.CARD_H_IN}in;
    overflow: hidden; outline: 0.4pt solid #e2e2e2; }}
  .card.flip {{ transform: rotate(180deg); }}   /* back of a leaf: reads upright after a TOP flip */
  .crop {{ position: absolute; background: #444; }}
  .sheetnote {{ position: absolute; top: 0.07in; left: 0.12in; font-size: 6pt; color: #a0a0a0; letter-spacing: .3px; }}
  .pageno {{ position: absolute; top: 2px; left: 4px; font-size: 8pt; color: #bbb; z-index: 3; }}
  /* portrait cards, cut apart and bound on the TOP edge -> flips top-to-bottom */
  .panel {{ position: absolute; inset: 0; padding: 0.07in; display: flex; flex-direction: column; }}

  .hole .hhead {{ display: flex; align-items: center; gap: 4px;
    border-bottom: 2px solid #2b6a2b; padding-bottom: 1px; }}
  .hnum {{ font-size: 20pt; font-weight: 800; line-height: 1; color: #2b6a2b; }}
  .hmeta {{ line-height: 1; }}
  .par {{ font-size: 10pt; font-weight: 700; }}
  .si {{ font-size: 7pt; color: #666; }}
  .hyd {{ margin-left: auto; text-align: right; line-height: 1.05; }}
  .ymain {{ font-size: 17pt; font-weight: 800; color: #b8860b; }}
  .ylab {{ font-size: 7pt; color: #b8860b; }}
  .yalt {{ display: block; font-size: 7.5pt; color: #9a9a9a; }}   /* front tee: light gray like the footer, secondary to the back tee */
  .body {{ flex: 1; min-height: 0; display: flex; gap: 1px; margin: 1px 0 0; }}
  .lay {{ flex: 1.6; min-width: 0; position: relative; }}
  .grn {{ flex: 2.4; min-width: 0; position: relative; }}
  .lay svg, .grn svg {{ width: 100%; height: 100%; }}
  .ytab {{ width: 100%; border-collapse: collapse; font-size: 11pt; margin-top: 4px; }}
  .ytab td {{ border: 1px solid #d7d7d7; padding: 3px 8px; }}
  .ytab tr td:first-child {{ text-align: left; font-weight: 600; color: #2b6a2b; }}
  .ytab tr td:last-child {{ text-align: right; font-weight: 700; }}
  .ytab .th td {{ background: #2b6a2b; color: #fff; font-size: 8pt; font-weight: 700; text-align: center; }}
  .ynotehd {{ font-size: 8pt; font-weight: 700; color: #2b6a2b; margin: 7px 0 3px; }}
  .ynote {{ flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 2px; }}
  .ynote .nl {{ border-bottom: 1px solid #cfcfcf; height: 1px; }}
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 5.5pt; color: #9a9a9a; letter-spacing: .5px; z-index: 2; }}
  .foot {{ display: flex; justify-content: space-between; font-size: 7.5pt; color: #999; margin-top: 1px; }}
  .sheettab {{ position: absolute; top: 2px; right: 5px; font-size: 7pt; color: #bbb; }}

  .cover {{ position: relative; overflow: hidden; padding: 0;
    background: linear-gradient(158deg,#0e3f29 0%,#08301f 55%,#04160f 100%); color: #f3ecdd; }}
  .coverbg {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
  .cframe {{ position: absolute; inset: 0.13in; border: 1.4px solid #c8a24a; }}
  .cframe::after {{ content: ""; position: absolute; inset: 3px; border: 0.5px solid rgba(200,162,74,.5); }}
  .coverin {{ position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center; padding: 0.34in 0.24in; }}
  .crest {{ width: 0.46in; height: 0.46in; border: 1.4px solid #c8a24a; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 15pt; color: #e9d9a8; margin-bottom: 11px; }}
  .btop {{ font-size: 10.5pt; letter-spacing: 7px; color: #cda94f; font-weight: 600; text-indent: 7px; }}
  .bmain {{ font-size: 20.5pt; font-weight: 800; letter-spacing: 2px; line-height: 1; margin-top: 3px; color: #fbf6ea; white-space: nowrap; }}
  .cdiv {{ position: relative; width: 46%; height: 1px; background: linear-gradient(90deg,transparent,#c8a24a,transparent); margin: 13px 0; }}
  .cdiv span {{ position: absolute; left: 50%; top: -3px; width: 6px; height: 6px; background: #c8a24a; transform: translateX(-50%) rotate(45deg); }}
  .cchip {{ margin-top: 15px; font-size: 6.2pt; letter-spacing: 1.4px; color: #d8be78;
    border: 0.7px solid #b9973f; border-radius: 11px; padding: 2.5px 9px; }}
  .cedition {{ margin-top: 9px; font-size: 6pt; letter-spacing: 3px; opacity: .5; text-transform: uppercase; }}

  /* back-of-cover: about + legal */
  .abt {{ margin-top: 4px; border-top: 1.2px solid #cdb96a; padding-top: 3px; }}
  .abthead {{ font-size: 7.0pt; font-weight: 800; color: #2b6a2b; margin-bottom: 1px; }}
  .abtxt {{ font-size: 5.15pt; line-height: 1.2; color: #6b6b6b; text-align: justify; }}

  /* last card: dedication / colophon */
  .dedic {{ align-items: center; text-align: center; justify-content: center; padding: 0.26in 0.3in; }}
  .dcrest {{ margin-bottom: 5px; line-height: 0; }}
  .dtitle {{ font-family: Georgia,"Times New Roman",serif; font-style: italic; font-size: 12.5pt; color: #2b6a2b; margin-bottom: 7px; }}
  .dtext {{ font-size: 7.6pt; line-height: 1.36; color: #333; }}
  .dtext p {{ margin: 0 0 5px; }}
  .drule {{ width: 40%; border-top: 1.4px solid #d9b23a; margin: 9px auto 6px; }}
  .dsign {{ font-size: 9pt; color: #1a1a1a; letter-spacing: .4px; }}
  .dmail {{ font-size: 7pt; color: #888; margin-top: 2px; letter-spacing: .3px; }}
  .dcopy {{ font-size: 6pt; color: #9a9a9a; margin-top: 4px; letter-spacing: .2px; line-height: 1.3; }}
  .dqr {{ margin-top: 10px; }}
  .dqr img {{ width: 0.92in; height: auto; display: block; margin: 0 auto; }}
  .dqrcap {{ font-size: 6.4pt; color: #777; margin-top: 3px; letter-spacing: .2px; }}
  .dqrcap b {{ color: #c13584; }}

  .gtitle, .cardtitle {{ font-size: 11pt; font-weight: 800; color: #2b6a2b;
    border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; margin-bottom: 3px; }}
  .legrow {{ display: flex; gap: 4px; align-items: flex-start; font-size: 6.6pt;
    line-height: 1.2; margin-bottom: 3px; }}
  .legrow svg {{ flex: none; }}
  .gsub {{ font-size: 7.6pt; color: #444; margin-bottom: 3px; }}
  .guide ul {{ margin: 0; padding-left: 14px; font-size: 7.7pt; line-height: 1.28; }}
  .guide li {{ margin-bottom: 3px; }}
  .gsmall {{ font-size: 6.7pt; color: #777; margin-top: auto; padding-top: 3px; }}
  .legend ol {{ margin: 0; padding-left: 14px; font-size: 7.8pt; line-height: 1.3; }}
  .legend li {{ margin-bottom: 3px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 7.8pt; }}
  td {{ border: 1px solid #ddd; padding: 0 3px; text-align: center; }}
  .th td {{ background: #2b6a2b; color: #fff; font-weight: 700; }}
  .sum td {{ background: #eef4ee; font-weight: 700; }}
  .tot td {{ background: #dcebdc; }}
  .tt td {{ font-size: 7.6pt; }}
  .notesp .nrow {{ display: flex; align-items: center; border-bottom: 1px solid #ddd;
    padding: 2px 0; font-size: 9pt; }}
  .notesp .nrow b {{ width: 20px; color: #2b6a2b; }}
  .notesp .nrow span {{ flex: 1; }}

  @media screen {{ body {{ background: #666; padding: 16px; }}
    .sheet {{ background: #fff; margin: 0 auto 20px; box-shadow: 0 2px 12px rgba(0,0,0,.4); }} }}
</style></head><body>
{sheets}
</body></html>'''

    def build_pages(cards):
        # DUPLEX for a TOP-bound flip book. Leaf L: front=page(2L+1), back=page(2L+2).
        # Fronts on one PDF page, backs on the next. Back cards are positioned in the
        # column-mirrored slot (so they land behind their front under LONG-edge duplex)
        # and rotated 180 (so they read upright when the card is flipped over the top).
        if len(cards) % 2:
            cards = cards + ['<div class="panel"></div>']     # pad to whole leaves
        nleaves = len(cards) // 2
        lps = config.PER                                       # leaves per sheet
        gx0 = (config.PAGE_W_IN - (config.COLS*config.CARD_W_IN + (config.COLS-1)*config.GUTTER_IN)) / 2
        gy0 = (config.PAGE_H_IN - (config.ROWS*config.CARD_H_IN + (config.ROWS-1)*config.GUTTER_IN)) / 2
        def slot(j):
            r, c = divmod(j, config.COLS)
            return gx0 + c*(config.CARD_W_IN+config.GUTTER_IN), gy0 + r*(config.CARD_H_IN+config.GUTTER_IN), r, c
        def card_div(x, y, num, html, flip):
            cls = "card flip" if flip else "card"
            return (f'<div class="{cls}" style="left:{x:.3f}in;top:{y:.3f}in">'
                    f'<div class="pageno">{num}</div>{html}</div>'
                    + crop_ticks(x, y, config.CARD_W_IN, config.CARD_H_IN))
        pages = []
        nsheets = -(-nleaves // lps)
        for s in range(nsheets):
            fronts, backs = [], []
            for j in range(lps):
                L = s*lps + j
                if L >= nleaves:
                    continue
                x, y, r, c = slot(j)
                fronts.append(card_div(x, y, 2*L+1, cards[2*L], False))
                xb, yb, _, _ = slot(r*config.COLS + (config.COLS-1-c))   # mirror columns
                # last card (Lucas's dedication / back cover) prints UPRIGHT like the
                # front cover -- not rotated like the other duplex backs.
                is_last = (2*L+1 == len(cards)-1)
                backs.append(card_div(xb, yb, 2*L+2, cards[2*L+1], not is_last))
            pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; FRONT</div>{"".join(fronts)}</div>')
            pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; BACK (duplex, flip on LONG edge)</div>{"".join(backs)}</div>')
        return "".join(pages)

    sheets_html = build_pages(panels)
    out = os.path.join(COURSE_DIR, "greenbook.html")
    open(out, "w").write(doc(sheets_html, config.BRAND))
    print(f"Wrote {out} (single conforming build) "
          f"-> cards {config.CARD_W_IN}x{config.CARD_H_IN}in, {config.PER}/sheet duplex")

# ===========================================================================
# COACH EDITION (ENLARGED) -- a special one-off. Each hole is split across TWO
# full-size cards on ONE page: course map on top, green map on bottom (same
# hole). Top-bound flip book: flip up to advance holes; both maps always
# visible. Maps fill a whole card, so they're ~3x larger than the standard
# side-by-side book. Intentionally enlarged PAST the tournament scale -> this
# is a PRACTICE / COACHING aid, not a Rule 4.3 conforming competition book.
# Guarded by env COACH=1 so it never affects the normal build of any course.
# ===========================================================================
def coach_cover_panel(coach_name):
    parts = config.BRAND.split()
    btop = esc(parts[0].upper()); bmain = esc(" ".join(parts[1:]).upper()) or "GREEN BOOK"
    tlines = _title_lines(COURSE)          # exact same title logic as the standard cover
    maxch = max(len(l) for l in tlines)
    fst = max(13.0, min(19.0, 274.0 / (maxch * 0.52)))
    dyt = fst * 1.22
    cy0 = 300 - (len(tlines) - 1) * dyt / 2
    tspans = "".join(f'<tspan x="175" dy="{0 if k == 0 else dyt:.1f}">{esc(ln)}</tspan>'
                     for k, ln in enumerate(tlines))
    addr_y = cy0 + (len(tlines) - 1) * dyt + 20
    # Recipient (e.g. a coach's name) is a PRIVATE, per-gift detail supplied at build time
    # via COACH_NAME -- never hard-coded, so nothing personal ships in the public repo.
    recipient = ""
    if (coach_name or "").strip():
        recipient = (
          '<text x="175" y="400" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" font-size="8.5" letter-spacing="2" fill="#9fb4a3">PREPARED FOR</text>'
          '<text x="175" y="422" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" font-style="italic" font-size="18" fill="#fbf6ea">Coach ' + esc(coach_name) + '</text>')
    motif = "".join(
        f'<path d="M-20 {30+i*40} C 90 {30+i*40-26}, 200 {30+i*40+30}, 370 {30+i*40-14}" '
        f'fill="none" stroke="#c8a24a" stroke-width="1.1" opacity="0.06"/>' for i in range(13))
    G = "#c8a24a"
    return f'''<div class="panel cover"><svg viewBox="0 0 350 500" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
  <defs><linearGradient id="cg" x1="0" y1="0" x2="0.35" y2="1">
    <stop offset="0" stop-color="#12492f"/><stop offset="0.55" stop-color="#0a3a24"/><stop offset="1" stop-color="#04170f"/>
  </linearGradient></defs>
  <rect x="0" y="0" width="350" height="500" fill="#0a3521"/>
  <rect x="0" y="0" width="350" height="500" fill="url(#cg)"/>
  {motif}
  <rect x="17" y="17" width="316" height="466" fill="none" stroke="{G}" stroke-width="1.4"/>
  <rect x="21" y="21" width="308" height="458" fill="none" stroke="{G}" stroke-width="0.6" opacity="0.55"/>
  <text x="175" y="66" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="10" letter-spacing="8" font-weight="700" fill="#d7b45c">ENLARGED</text>
  <circle cx="175" cy="120" r="26" fill="none" stroke="{G}" stroke-width="1.4"/>
  <circle cx="175" cy="120" r="21" fill="none" stroke="{G}" stroke-width="0.6" opacity="0.6"/>
  <line x1="171" y1="108" x2="171" y2="134" stroke="{G}" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M171 108 L186 113 L171 119 Z" fill="{G}"/>
  <text x="179" y="184" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="17" letter-spacing="8" font-weight="600" fill="#d7b45c">{btop}</text>
  <text x="175" y="226" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="35" letter-spacing="1.5" font-weight="800" fill="#fbf6ea">{bmain}</text>
  <line x1="118" y1="252" x2="232" y2="252" stroke="{G}" stroke-width="0.9"/>
  <rect x="171" y="248.5" width="7" height="7" fill="{G}" transform="rotate(45 175 252)"/>
  <text x="175" y="{cy0:.1f}" text-anchor="middle" font-family="Georgia,'Times New Roman',serif" font-style="italic" font-size="{fst:.1f}" fill="#f5eddd">{tspans}</text>
  <text x="175" y="{addr_y:.1f}" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="9" letter-spacing="1" fill="#9fb4a3">{esc(ADDR).upper()}</text>
  {recipient}
  <rect x="60" y="446" width="230" height="18" rx="9" fill="none" stroke="#b9973f" stroke-width="0.8"/>
  <text x="175" y="458" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="6.6" letter-spacing="1.0" fill="#dcc27f">ENLARGED PRACTICE EDITION</text>
</svg></div>'''

def coach_map_card(hole):
    row = HOLES[hole]; par, hcp = row[0], row[1]
    lsvg, i = LAYOUTS[hole]
    return f'''<div class="panel hole">
  <div class="etag">ENLARGED</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain" style="color:{tee_color(BACK_NAME)}">{row[BACK_I]}</span><span class="ylab" style="color:{tee_color(BACK_NAME)}">{esc(BACK_NAME)}</span>
      <span class="yalt">{row[FRONT_I]} {esc(FRONT_NAME)}</span></div>
  </div>
  <div class="cmap"><div class="minilab">HOLE &middot; tee &rarr; green</div>{lsvg}</div>
  <div class="foot"><span>{i['bunkers']} bunkers &middot; {i['waters']} water</span><span>course layout</span></div>
</div>'''

def coach_green_card(hole):
    row = HOLES[hole]; par, hcp = row[0], row[1]
    gsvg, s = GREENS[hole]
    return f'''<div class="panel hole">
  <div class="etag">ENLARGED</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain" style="color:{tee_color(BACK_NAME)}">{row[BACK_I]}</span><span class="ylab" style="color:{tee_color(BACK_NAME)}">{esc(BACK_NAME)}</span></div>
  </div>
  <div class="cmap"><div class="minilab">GREEN &middot; approach at bottom</div>{gsvg}</div>
  <div class="foot"><span>feeds <b>{esc(s['feeds'])}</b> ({esc(s['conf'])}) &middot; {s['tilt_pct']}%</span>
    <span>{s['depth_yd']}yd deep</span></div>
</div>'''

def coach_about_card():
    return '''<div class="panel guide">
  <div class="gtitle">Enlarged edition</div>
  <div class="legrow"><span>This is an <b>enlarged</b> copy: each hole is split onto two big cards &mdash;
    the <b>course map on top</b>, the <b>green on the bottom</b> &mdash; so the greens read easily at a
    glance. Flip up one more page for the green; flip again for the next hole.</span></div>
  <div class="legrow"><span><b>Arrows</b> point downhill (the way the ball rolls; longer = steeper).
    <b>Contours</b> join equal height. <b>Colour</b>: green flat &rarr; yellow &rarr; red (steep).
    "feeds" = the low side putts run toward.</span></div>
  <div class="legrow"><span>Because the greens here are printed <b>larger than the tournament scale</b>,
    this enlarged edition is a <b>practice aid and is NOT a conforming competition book under
    Rule&nbsp;4.3</b> &mdash; use the standard pocket edition for competition.</span></div>
  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> green book. Hole &amp; green shapes are a
      Produced Work from <b>OpenStreetMap</b> data (&copy;&nbsp;OpenStreetMap contributors, <b>ODbL&nbsp;1.0</b>);
      slope, contours &amp; arrows are computed by the maker from <b>public-domain USGS&nbsp;3DEP</b> LiDAR; par,
      yardage &amp; handicap are <b>facts</b> from the published scorecard. <b>No proprietary data, image, symbol
      set, layout or trade dress of any commercial green-reading product was used, copied or referenced.</b>
      Not affiliated with, endorsed or sponsored by any course, club, association or product; names &amp;
      trademarks belong to their owners and identify the course only &mdash; contact the maker for removal.
      Provided <b>as-is, no warranty</b>; maps show general tilt, not exact break &mdash; trust your own read.
      <b>lucasgreenbook.org</b> &middot; contact <b>info@lucasgreenbook.org</b>. &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. This book: free to share, not for sale &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
  </div>
</div>'''

def coach_dedic_card(coach_name):
    flag = ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<line x1="9" y1="4" x2="9" y2="22" stroke="#b8860b" stroke-width="1.6" stroke-linecap="round"/>'
            '<path d="M9 4 L20 8 L9 12 Z" fill="#b8860b"/></svg>')
    title = f"For Coach {esc(coach_name)}" if (coach_name or "").strip() else "For your coach"
    return f'''<div class="panel dedic">
  <div class="dcrest">{flag}</div>
  <div class="dtitle">{title}</div>
  <div class="dtext">
    <p>Thank you for the time, the patience, and the lessons that go past the golf.</p>
    <p>This enlarged green book is a small thank-you &mdash; every green on the course, big and
      clear, so the reads are easy to see.</p>
    <p>With gratitude,</p>
  </div>
  <div class="drule"></div>
  <div class="dsign">from <b>Lucas Wu</b></div>
  <div class="dmail">lucasgreenbook.org &middot; info@lucasgreenbook.org</div>
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. Practice aid, free to share &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
</div>'''

def build_coach(coach_name=""):
    # coach_name is PRIVATE (a specific person) -> default empty; pass it at build time via
    # COACH_NAME so no real name is ever committed. Empty -> generic "your coach" wording.
    # ENLARGED edition: SAME print imposition as the normal book (4-up, duplex,
    # top-flip, last card upright like the cover) -- to save paper. The ONLY
    # difference vs. normal: each hole is TWO cards (course map = leaf FRONT,
    # green = leaf BACK), so you "flip up one more page" to the green. Map
    # wording/numbers are rendered ~2x bigger (font_scale) for older eyes.
    for h in range(1, 19):
        GREENS[h] = render_green.render(h, HOLES[h][3], tournament=True)
        LAYOUTS[h] = render_hole.render_hole(h, HOLES, font_scale=2.0)
    # deck: leaf0 = [cover, enlarged-about]; leaf h = [hole h map, hole h green];
    # then back matter. Holes land one-per-leaf (map front / green back).
    cards = [coach_cover_panel(coach_name), coach_about_card()]
    for h in range(1, 19):
        cards.append(coach_map_card(h))
        cards.append(coach_green_card(h))
    # scorecard = front of the LAST leaf, dedication = its back (upright via is_last).
    # Drop the separate tee rating/slope card so there is NO trailing blank page:
    # 40 cards -> 20 leaves -> exactly 5 duplex sheets, all full.
    cards += [scorecard_panel(), coach_dedic_card(coach_name)]

    # ---- identical imposition to main()'s build_pages ----
    if len(cards) % 2:
        cards = cards + ['<div class="panel"></div>']
    nleaves = len(cards) // 2
    lps = config.PER
    gx0 = (config.PAGE_W_IN - (config.COLS*config.CARD_W_IN + (config.COLS-1)*config.GUTTER_IN)) / 2
    gy0 = (config.PAGE_H_IN - (config.ROWS*config.CARD_H_IN + (config.ROWS-1)*config.GUTTER_IN)) / 2
    def slot(j):
        r, c = divmod(j, config.COLS)
        return gx0 + c*(config.CARD_W_IN+config.GUTTER_IN), gy0 + r*(config.CARD_H_IN+config.GUTTER_IN), r, c
    def card_div(x, y, num, html, flip):
        cls = "card flip" if flip else "card"
        return (f'<div class="{cls}" style="left:{x:.3f}in;top:{y:.3f}in">'
                f'<div class="pageno">{num}</div>{html}</div>'
                + crop_ticks(x, y, config.CARD_W_IN, config.CARD_H_IN))
    pages = []
    nsheets = -(-nleaves // lps)
    for s in range(nsheets):
        fronts, backs = [], []
        for j in range(lps):
            L = s*lps + j
            if L >= nleaves:
                continue
            x, y, r, c = slot(j)
            fronts.append(card_div(x, y, 2*L+1, cards[2*L], False))
            xb, yb, _, _ = slot(r*config.COLS + (config.COLS-1-c))
            is_last = (2*L+1 == len(cards)-1)   # last card prints UPRIGHT like the front cover
            backs.append(card_div(xb, yb, 2*L+2, cards[2*L+1], not is_last))
        pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; FRONT</div>{"".join(fronts)}</div>')
        pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; BACK (duplex, flip on LONG edge)</div>{"".join(backs)}</div>')

    CW, CH = config.CARD_W_IN, config.CARD_H_IN
    css = f'''
  @page {{ size: {config.PAGE_W_IN}in {config.PAGE_H_IN}in; margin: 0; }}
  * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  html, body {{ margin: 0; padding: 0; font-family: "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }}
  .sheet {{ width: {config.PAGE_W_IN}in; height: {config.PAGE_H_IN}in; position: relative; page-break-after: always; }}
  .card {{ position: absolute; width: {CW}in; height: {CH}in; overflow: hidden; outline: 0.4pt solid #e2e2e2; }}
  .card.flip {{ transform: rotate(180deg); }}   /* duplex back: reads upright after a TOP flip */
  .crop {{ position: absolute; background: #444; }}
  .pageno {{ position: absolute; top: 2px; left: 4px; font-size: 8pt; color: #ccc; z-index: 3; }}
  .sheetnote {{ position: absolute; top: 0.07in; left: 0.12in; font-size: 6pt; color: #a0a0a0; letter-spacing: .3px; }}
  .panel {{ position: absolute; inset: 0; padding: 0.08in; display: flex; flex-direction: column; }}
  .etag {{ position: absolute; top: 3px; right: 6px; font-size: 6.5pt; letter-spacing: 1.5px; font-weight: 700; color: #b8860b; }}
  /* hole header -- a touch larger than the pocket book for older eyes */
  .hole .hhead {{ display: flex; align-items: center; gap: 5px; border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; }}
  .hnum {{ font-size: 23pt; font-weight: 800; line-height: 1; color: #2b6a2b; }}
  .hmeta {{ line-height: 1; }}
  .par {{ font-size: 12pt; font-weight: 700; }}
  .si {{ font-size: 8pt; color: #666; }}
  .hyd {{ margin-left: auto; text-align: right; line-height: 1.05; }}
  .ymain {{ font-size: 19pt; font-weight: 800; color: #b8860b; }}
  .ylab {{ font-size: 8pt; color: #b8860b; }}
  .yalt {{ display: block; font-size: 8.5pt; color: #9a9a9a; }}   /* front tee: light gray */
  .cmap {{ flex: 1; min-height: 0; position: relative; margin: 2px 0; }}
  .cmap svg {{ width: 100%; height: 100%; }}
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 7pt; color: #9a9a9a; letter-spacing: .5px; z-index: 2; }}
  .foot {{ display: flex; justify-content: space-between; font-size: 8pt; color: #999; margin-top: 1px; }}
  .cover {{ position: relative; overflow: hidden; padding: 0; }}
  .gtitle, .cardtitle {{ font-size: 12pt; font-weight: 800; color: #2b6a2b; border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; margin-bottom: 4px; }}
  .legrow {{ display: flex; gap: 4px; align-items: flex-start; font-size: 8pt; line-height: 1.3; margin-bottom: 5px; }}
  .abt {{ margin-top: 4px; border-top: 1.2px solid #cdb96a; padding-top: 3px; }}
  .abthead {{ font-size: 8pt; font-weight: 800; color: #2b6a2b; margin-bottom: 1px; }}
  .abtxt {{ font-size: 6.6pt; line-height: 1.28; color: #6b6b6b; text-align: justify; }}   /* legal, slightly bigger for older eyes */
  .dedic {{ align-items: center; text-align: center; justify-content: center; padding: 0.28in 0.3in; }}
  .dcrest {{ margin-bottom: 6px; line-height: 0; }}
  .dtitle {{ font-family: Georgia,"Times New Roman",serif; font-style: italic; font-size: 16pt; color: #2b6a2b; margin-bottom: 9px; }}
  .dtext {{ font-size: 10pt; line-height: 1.42; color: #333; }}
  .dtext p {{ margin: 0 0 7px; }}
  .drule {{ width: 40%; border-top: 1.4px solid #d9b23a; margin: 11px auto 7px; }}
  .dsign {{ font-size: 12pt; color: #1a1a1a; }}
  .dmail {{ font-size: 9pt; color: #6f8676; margin-top: 6px; letter-spacing: .3px; }}
  .dcopy {{ font-size: 7pt; color: #9a9a9a; margin-top: 5px; letter-spacing: .2px; line-height: 1.3; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
  td {{ border: 1px solid #ddd; padding: 1px 3px; text-align: center; }}
  .th td {{ background: #2b6a2b; color: #fff; font-weight: 700; }}
  .sum td {{ background: #eef4ee; font-weight: 700; }}
  .tot td {{ background: #dcebdc; }}
  .tt td {{ font-size: 8.5pt; }}
  .gsmall {{ font-size: 7pt; color: #777; margin-top: auto; padding-top: 3px; }}
  @media screen {{ body {{ background: #666; padding: 16px; }}
    .sheet {{ background: #fff; margin: 0 auto 20px; box-shadow: 0 2px 12px rgba(0,0,0,.4); }} }}'''
    html = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<title>Enlarged Edition &mdash; {esc(COURSE)}</title><style>{css}</style>'
            f'</head><body>{"".join(pages)}</body></html>')
    out = os.path.join(COURSE_DIR, "greenbook_coach.html")
    open(out, "w").write(html)
    print(f"Wrote {out} (ENLARGED edition for {coach_name}) "
          f"-> {len(cards)} cards, {len(pages)} PDF pages, {config.PER}/sheet duplex "
          f"(same layout as pocket book; each hole = 2 cards: map front / green back)")

if __name__ == "__main__":
    if os.environ.get("COACH"):
        build_coach(os.environ.get("COACH_NAME", ""))
    else:
        main()
