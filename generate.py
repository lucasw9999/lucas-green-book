#!/usr/bin/env python3
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

# ---------------------------------------------------------------------------
# BLANK GREEN TEMPLATE (no invented data -- a canvas to record real reads)
# ---------------------------------------------------------------------------
def green_template_svg(hole, par):
    VW, VH = 244, 300
    if par == 3:
        gw, gh = 168, 182
    elif par == 5:
        gw, gh = 198, 226
    else:
        gw, gh = 182, 208
    gx0 = (VW - gw) / 2.0
    gy0 = 28.0
    cid = f"g{hole}"

    def XY(u, v):
        return (gx0 + u * gw, gy0 + v * gh)

    def r_theta(t):
        # gentle, generic rounded green -- identical for every hole so it reads
        # clearly as a BLANK template, not a specific surveyed shape
        return 0.44 * (1 + 0.06 * math.cos(2 * t) + 0.04 * math.cos(3 * t + 0.6))

    def inside(u, v):
        dx, dy = u - 0.5, v - 0.5
        r = math.hypot(dx, dy)
        return r <= r_theta(math.atan2(dy, dx)) if r > 1e-6 else True

    # outline path (smooth)
    N = 72
    pts = [XY(0.5 + r_theta(2*math.pi*k/N)*math.cos(2*math.pi*k/N),
              0.5 + r_theta(2*math.pi*k/N)*math.sin(2*math.pi*k/N)) for k in range(N)]
    d = f"M {(pts[0][0]+pts[-1][0])/2:.1f},{(pts[0][1]+pts[-1][1])/2:.1f} "
    for i in range(N):
        cx, cy = pts[i]
        nx_, ny_ = pts[(i + 1) % N]
        d += f"Q {cx:.1f},{cy:.1f} {(cx+nx_)/2:.1f},{(cy+ny_)/2:.1f} "
    d += "Z"

    # faint dot grid to sketch the real break on
    dots = []
    step = 0.092
    u = step
    while u < 1:
        v = step
        while v < 1:
            if inside(u, v):
                x, y = XY(u, v)
                dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1" fill="#a9c39a"/>')
            v += step
        u += step
    dotg = f'<g clip-path="url(#{cid})">{"".join(dots)}</g>'

    # neutral centre reference cross (a pencil anchor, not a claim)
    cxp, cyp = XY(0.5, 0.5)
    cross = (f'<line x1="{cxp-5:.1f}" y1="{cyp:.1f}" x2="{cxp+5:.1f}" y2="{cyp:.1f}" stroke="#9bb58c" stroke-width="0.7"/>'
             f'<line x1="{cxp:.1f}" y1="{cyp-5:.1f}" x2="{cxp:.1f}" y2="{cyp+5:.1f}" stroke="#9bb58c" stroke-width="0.7"/>')

    return f'''<svg viewBox="0 0 {VW} {VH}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
  <defs><clipPath id="{cid}"><path d="{d}"/></clipPath></defs>
  <text x="{VW/2:.0f}" y="16" font-size="8" text-anchor="middle" fill="#999">BACK</text>
  <path d="{d}" fill="#eef5e2" stroke="#3f6b34" stroke-width="2"/>
  {dotg}
  {cross}
  <text x="{VW/2:.0f}" y="{gy0+gh+16:.0f}" font-size="9" text-anchor="middle" fill="#333">&#9650; FRONT / approach &#9650;</text>
  <text x="{VW/2:.0f}" y="{gy0+gh+27:.0f}" font-size="6.4" text-anchor="middle" fill="#aa7">draw the slope you see here</text>
</svg>'''

# ---------------------------------------------------------------------------
# PANELS
# ---------------------------------------------------------------------------
def yardage_hole_panel(hole, sheet_label):
    """Yardage-mode card: verified facts only (par/hcp + every tee's yardage) plus a
    BLANK green to sketch the read. Used when accurate green-surface data isn't
    available yet (e.g. a course rebuilt after the latest public LiDAR)."""
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    feat = row[config.FI]
    trows = "".join(f'<tr><td>{esc(t)}</td><td>{row[2+i]}</td></tr>' for i, t in enumerate(config.TEES))
    lines = "".join('<div class="nl"></div>' for _ in range(5))
    return f'''<div class="panel hole ycard">
  <div class="sheettab">{esc(sheet_label)}</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain">{feat}</span><span class="ylab">{esc(config.FEATURED)}</span></div>
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
      rules with your Committee before competition. Contact / removal: <b>lucasruomingwu@gmail.com</b>.
      &copy;&nbsp;2026 Lucas.</div>
  </div>
</div>'''

def hole_panel(hole, sheet_label):
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    feat, sec = row[config.FI], row[config.SI]
    gsvg, s = GREENS[hole]
    lsvg, i = LAYOUTS[hole]
    others = " / ".join(f"{lbl[:3]}{row[idx]}" for lbl, idx in config.OTHERS)
    return f'''<div class="panel hole">
  <div class="sheettab">{esc(sheet_label)}</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain">{feat}</span><span class="ylab">{esc(config.FEATURED)}</span>
      <span class="yalt">{sec} {esc(config.SECONDARY[:3])}</span></div>
  </div>
  <div class="body">
    <div class="lay"><div class="minilab">HOLE</div>{lsvg}</div>
    <div class="grn"><div class="minilab">GREEN</div>{gsvg}</div>
  </div>
  <div class="foot"><span>feeds <b>{esc(s['feeds'])}</b> ({esc(s['conf'])}) &middot; {s['tilt_pct']}%</span>
    <span>{s['depth_yd']}yd deep &middot; {i['bunkers']}B {i['waters']}W &middot; {esc(others)}</span></div>
</div>'''

def layout_hole_panel(hole, sheet_label):
    par, hcp, black, gold, blue, white, green = HOLES[hole]
    svg, i = LAYOUTS[hole]
    return f'''<div class="panel hole">
  <div class="sheettab">{esc(sheet_label)}</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain">{gold}</span><span class="ylab">Gold</span>
      <span class="yalt">{black} Blk</span></div>
  </div>
  <div class="greenbox">{svg}</div>
  <div class="foot"><span>{i['bunkers']} bunkers &middot; {i['waters']} water</span>
    <span>tee &rarr; green</span></div>
  <div class="tees">Blu {blue} &middot; Wht {white} &middot; Grn {green}</div>
</div>'''

def cover_panel():
    parts = config.BRAND.split()
    btop = esc(parts[0].upper()); bmain = esc(" ".join(parts[1:]).upper()) or "GREEN BOOK"
    # Title: split on the em-dash so the club name stays whole on its own line
    # (e.g. "Castlewood Country Club" / "Hill Course"); otherwise wrap ~17 chars.
    raw = COURSE
    if "—" in raw:
        tlines = [p.strip() for p in raw.split("—") if p.strip()]
    else:
        tlines = []; cur = ""
        for w in raw.split():
            if len(cur) + len(w) + 1 <= 17:
                cur = (cur + " " + w).strip()
            else:
                tlines.append(cur); cur = w
        if cur:
            tlines.append(cur)
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
      Contact / removal requests: <b>lucasruomingwu@gmail.com</b>. &copy;&nbsp;2026 Lucas.</div>
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
  <div class="dsign">Crafted by <b>Lucas</b></div>
  <div class="dmail">lucasruomingwu@gmail.com</div>
  {qr}
</div>'''

def notes_panel(title, holes_range):
    lines = "".join(f'<div class="nrow"><b>{h}</b><span></span></div>' for h in holes_range)
    return f'<div class="panel notesp"><div class="gtitle">{esc(title)}</div>{lines}</div>'

def layout_cover():
    return f'''<div class="panel cover">
  <div class="ctop">HOLE&nbsp;LAYOUTS</div>
  <div class="ctitle">{esc(COURSE)}</div>
  <div class="caddr">{esc(ADDR)}</div>
  <div class="cflag">&#9971;</div>
  <div class="cpar">tee &rarr; green &middot; bunkers &amp; water</div>
  <div class="cnote">Sheet 1/3 &middot; Holes 1&ndash;6<br>layouts from OpenStreetMap</div>
</div>'''

def layout_guide():
    return '''<div class="panel guide">
  <div class="gtitle">Reading a layout</div>
  <div class="legrow"><svg width="28" height="14"><rect x="3" y="9" width="6" height="3" rx="1" fill="#7fb069" stroke="#4a7a3a" stroke-width="0.5"/></svg>
    <span><b>Green box</b> = a tee (bottom of each hole).</span></div>
  <div class="legrow"><svg width="28" height="14"><ellipse cx="8" cy="7" rx="6" ry="3.5" fill="#efe3b8" stroke="#c9b477"/></svg>
    <span><b>Tan</b> = fairway/greenside bunkers.</span></div>
  <div class="legrow"><svg width="28" height="14"><rect x="2" y="3" width="14" height="9" fill="#a9d3ef" stroke="#5b9bd0"/></svg>
    <span><b>Blue</b> = water / lateral hazard.</span></div>
  <div class="legrow"><svg width="28" height="14"><circle cx="8" cy="7" r="3" fill="none" stroke="#c0392b"/></svg>
    <span><b>Red ring</b> on the green = pin; write in today's spot.</span></div>
  <div class="legrow"><span>Small ticks on the dashed line are <b>100/150/200 yd</b> to the green centre. Tee at bottom, green at top.</span></div>
  <div class="gsmall">Geometry: OpenStreetMap (ODbL). Yardages: NCGA. Hazard shapes are
    contributor-mapped from aerials &mdash; accurate to a few metres, not surveyed.</div>
</div>'''

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
  .yalt {{ display: block; font-size: 7.5pt; color: #444; }}
  .greenbox {{ flex: 1; min-height: 0; margin: 1px 0; }}
  .body {{ flex: 1; min-height: 0; display: flex; gap: 1px; margin: 1px 0 0; }}
  .lay {{ flex: 1.6; min-width: 0; position: relative; }}
  .grn {{ flex: 2.4; min-width: 0; position: relative; }}
  .lay svg, .grn svg {{ width: 100%; height: 100%; }}
  .ytees {{ font-size: 7pt; color: #444; text-align: center; padding: 2px 0 1px; border-bottom: 1px solid #e3e3e3; }}
  .ytees b {{ color: #b8860b; }}
  .ytab {{ width: 100%; border-collapse: collapse; font-size: 11pt; margin-top: 4px; }}
  .ytab td {{ border: 1px solid #d7d7d7; padding: 3px 8px; }}
  .ytab tr td:first-child {{ text-align: left; font-weight: 600; color: #2b6a2b; }}
  .ytab tr td:last-child {{ text-align: right; font-weight: 700; }}
  .ytab .th td {{ background: #2b6a2b; color: #fff; font-size: 8pt; font-weight: 700; text-align: center; }}
  .ynotehd {{ font-size: 8pt; font-weight: 700; color: #2b6a2b; margin: 7px 0 3px; }}
  .ynote {{ flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 2px; }}
  .ynote .nl {{ border-bottom: 1px solid #cfcfcf; height: 1px; }}
  .ygreen {{ flex: 1; min-height: 0; position: relative; margin-top: 2px; }}
  .ygreen svg {{ width: 100%; height: 100%; }}
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 5.5pt; color: #9a9a9a; letter-spacing: .5px; z-index: 2; }}
  .tees {{ font-size: 7pt; color: #666; text-align: center; }}
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
  .cover .ctitle {{ font-family: Georgia,"Times New Roman",serif; font-style: italic; font-size: 12.5pt;
    line-height: 1.22; margin: 2px 10px; color: #f6efe0; font-weight: 500; }}
  .cover .caddr {{ font-size: 6.7pt; letter-spacing: .8px; opacity: .62; margin-top: 5px; text-transform: uppercase; }}
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

if __name__ == "__main__":
    main()
