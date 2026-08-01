#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
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
import json
import os
import base64
import render_green
import render_hole
import config
import distribution
from config import HOLES, NAME as COURSE, ADDRESS as ADDR, COURSE_DIR

GREENS = {}    # hole -> (svg, summary)
LAYOUTS = {}   # hole -> (svg, info)
_TREES = None  # lazily loaded trees_lidar.json; see _tree_markers()

# Young players (juniors, and men especially) play the BACK tee, so show the
# LONGER of the two configured tees as the big main yardage and the shorter as
# the small one, with FULL tee names (e.g. "Black", not "BLA").
# One answer, from config.py -- render_hole.py and fetch_hole_elev.py must agree with the headline or a
# card mixes two tees. See the note beside BACK_I there.
BACK_I, BACK_NAME = config.BACK_I, config.BACK_NAME
FRONT_I, FRONT_NAME = config.FRONT_I, config.FRONT_NAME

ROOT = os.path.dirname(os.path.abspath(__file__))

def _data_uri(path):
    """Base64 data URI so raster assets print reliably in every book.

    A missing optional asset used to vanish SILENTLY, so a fresh clone (these assets are
    gitignored) built a visibly different book than this machine does, and the "byte-reproducible"
    claim held only for someone who happened to have the same local files. Say so instead."""
    if not os.path.exists(path):
        print(f"  note: optional asset {os.path.basename(path)} not present -- omitting it from "
              f"the book (output will differ from a build that has it)")
        return ""
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    with open(path, "rb") as f:
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode()

IG_QR = _data_uri(os.path.join(ROOT, "lucaswu.golf_qr_small.png"))


DISTRIBUTABLE, _DIST_LABEL, _DIST_WHY = distribution.distribution_status(config.COURSE)


def sharing_line():
    """The licence sentence -- and for a book that may NOT be shared, a licence that says so.

    distribution.py has always known Poppy Ridge is personal-use only, and legal/03 has always printed
    it, but the BOOK carried the same free-to-share CC BY-NC-ND line as a distributable one. The verdict
    lived in the policy and the paperwork while the artifact invited the opposite, and a PDF that leaves
    this machine carries no trace of either. That course was rebuilt in 2025 with no post-construction
    survey, so its greens are deliberately blank -- and a reader who receives the file cannot know that.

    Asks distribution.py rather than re-testing build_mode, for the same reason gen_provenance does: one
    rule, so the page and the paperwork cannot disagree.
    """
    if DISTRIBUTABLE:
        return ("This book: free to share, not for sale &mdash; "
                "CC&nbsp;BY-NC-ND&nbsp;4.0.")
    return ("<b>This copy is for personal use only &mdash; please do not share or redistribute "
            "it</b>, because its greens are blank for want of trustworthy survey data and a reader "
            "elsewhere cannot know that. Not for sale. All rights reserved.")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tee_color(name):
    """Print-legible ink color matching the tee NAME (a "Black" tee prints in black,
    not gold). White/yellow get a readable dark substitute since they'd vanish on paper.

    Every ink here clears 4.5:1 on white at the 7pt this prints at. The old gold (#b8860b, 3.25:1)
    did not, and it is not a rare case: it is the DEFAULT, so it inked every tee whose name is not a
    colour -- Championship, Middle, Forward, Blu/Wht, Wht/Grn -- which is the back-tee name on the
    headline of every Merion card. Darkened while keeping the hue: a Gold tee still prints gold."""
    return {
        "black":  "#111111",
        "blue":   "#1c4e8a",
        "white":  "#555555",
        "red":    "#b02418",
        "gold":   "#8f6809",
        "green":  "#2b6a2b",
        "orange": "#a44f16",
        "silver": "#6b7683",
        "yellow": "#856a00",
    }.get((name or "").strip().lower(), "#8f6809")   # default: the house gold

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
      yardage &amp; handicap (<b>HCP</b> = men&rsquo;s stroke index) are <b>facts</b> from the published scorecard. This course was <b>rebuilt in
      2025 with new greens</b>, and accurate post-construction green-surface data is not yet publicly
      available &mdash; so rather than print slope maps that could be wrong, the greens are left <b>blank
      to mark your own read</b>. (Our other books compute slope from public-domain USGS 3DEP elevation;
      that data does not yet reflect this rebuilt course, so we do not use it here.)''' + _naip_line() + ''' <b>No proprietary
      data, images, artwork, layout or trade dress from any commercial green-reading product was used,
      copied or referenced.</b> Not affiliated with, endorsed or sponsored by any course, club, association
      or product; course names &amp; trademarks belong to their owners and are used only to identify the
      course &mdash; if a course would prefer not to be included, contact the maker for removal. Provided
      <b>free and as-is, with no warranty of any kind</b>; use at your own risk. Confirm materials/equipment
      rules with your Committee before competition. <b>lucasgreenbook.org</b> &middot; contact/removal <b>info@lucasgreenbook.org</b>.
      &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. ''' + sharing_line() + '''</div>
  </div>
</div>'''


def _tree_markers(hole):
    """LiDAR tree markers on one hole, or [] -- cached; see the note at the footer that uses it."""
    global _TREES
    if _TREES is None:
        try:
            _TREES = render_hole._lidar_trees() or {}
        except Exception:
            _TREES = {}
    return _TREES.get(str(hole)) or []


def _course_has_trees():
    """True when SOME hole has markers. A course with no tree layer at all draws none anywhere, and
    marking all 18 holes "no tree data" would be noise rather than a caveat."""
    _tree_markers(1)
    return any(_TREES.values())


def green_honesty(hole, s):
    """The green label and the slope phrase, for BOTH editions.

    These three caveats are the honesty rule made concrete on a card:
      * a green rebuilt AFTER the flight -> say the data predates the rebuild;
      * a green fed by the coarser 1 m seamless DEM -> say so;
      * a green the honesty gate refused to read -> print NO slope at all.
    They lived only inside hole_panel(), so the ENLARGED coach edition -- a book actually handed to
    a person -- printed none of them, and reported "0.0%" for a green the engine had declined to
    read. One rule, one implementation.

    Returns (label, slope_phrase). slope_phrase is None when no slope may be printed.
    """
    outdated = hole in set(config.COURSE.get("greens_possibly_outdated", []))
    coarse = 'seamless' in str(s.get('source', '')).lower()
    if outdated:
        label = 'GREEN &middot; pre-rebuild data'
    elif coarse:
        label = 'GREEN &middot; 1 m data'
    else:
        label = 'GREEN'
    if s.get('insufficient'):
        return label, None
    tilt = (f'{s["tilt_pct"]}% <b>&#9888;</b>' if outdated else f'{s["tilt_pct"]}%')
    # A green whose plane fit and whose own arrows point opposite ways has no fall direction the data
    # supports, and render_green refuses to name one. Print the measured tilt, which is still true,
    # but NOT inside "feeds ..." -- "feeds no clear fall" would read as a direction.
    if s["feeds"] == render_green.NO_CLEAR_FALL:
        return label, f'<b>no clear fall</b> ({esc(s["conf"])}) &middot; {tilt}'
    return label, f'feeds <b>{esc(s["feeds"])}</b> ({esc(s["conf"])}) &middot; {tilt}'


def _hole_elev():
    """{hole: change_ft} measured by fetch_hole_elev.py, or {} when it has not been run.

    Optional by design: a course without it simply prints no elevation line, the same way a green
    with no usable surface prints no read."""
    p = os.path.join(config.COURSE_DIR, "hole_elev.json")
    if not os.path.isfile(p):
        return {}                      # stage not run for this course: print no elevation line
    try:
        with open(p) as f:
            rec = json.load(f)
    except Exception as e:
        # NOT silent. A blanket `except` here swallowed a NameError (json was never imported) and
        # every card lost its elevation line with no message at all -- the exact silent-fallback
        # failure this project keeps having to dig out.
        print(f"  ! {p} exists but could not be read ({type(e).__name__}: {e}); "
              f"no elevation line will print")
        return {}
    return {int(k): v.get("change_ft") for k, v in (rec.get("holes") or {}).items()
            if v.get("change_ft") is not None}


HOLE_ELEV = _hole_elev()


def elev_phrase(hole):
    """"green 37 ft above" / "green 12 ft below" / "" when unmeasured or level.

    The MEASUREMENT, never a "plays like +12 yd". Turning elevation into an effective yardage needs a
    ball-flight model LiDAR cannot supply, and a printed "plays" figure would be the confident-but-
    unsupported number this book exists not to print.

    Under 3 ft reads as level rather than as a precise small number, and that floor is MEASURED, not
    just argued. tools/verify_elevation.py compares every recorded height against the 3DEP seamless
    DEM -- a different product, delivered in metres, fetched over the network rather than read off
    disk -- and across 177 holes the two disagree by a median 0.80 ft and a worst 1.77 ft. So a
    printed "green 2 ft above" would sit inside the gap between two honest sources; 3 ft is about
    1.7x the worst of them. 26 of the 177 holes fall in the 2-4 ft band where that gap decides whether
    anything prints at all, which is exactly why the floor cannot be lowered to look more precise."""
    ft = HOLE_ELEV.get(hole)
    if ft is None or abs(ft) < 3:
        return ""
    return f'green <b>{abs(round(ft))} ft {"above" if ft > 0 else "below"}</b>'


def carry_phrase(info):
    """"carry 172 / 212 / 245" -- the near edge of each bunker window a tee shot must clear."""
    cs = info.get("carries") or []
    if not cs:
        return ""
    return "carry <b>" + " / ".join(str(a) for a, _b in cs) + "</b>"


def playline_html(hole, info):
    """The second footer row: tee-to-green height, then the carries off the tee. "" when neither.

    ONE definition, called by both the pocket card and the enlarged card. The two editions have now
    drifted three times -- the green honesty rules lived only inside hole_panel(), then the footer, then
    this row, which the enlarged edition's own legend described while its cards printed nothing. Each
    time the fix was to copy the content across, which just resets the clock. A shared helper makes this
    particular divergence impossible instead.

    Both phrases are omitted entirely when unmeasured, never shown as a blank or a zero. It gets its OWN
    full-width line rather than a third column in the flex footer: as a third span the row wrapped
    mid-phrase and left "&middot; 1.8%" and "carry / 95" orphaned.
    """
    extras = " &middot; ".join(x for x in (elev_phrase(hole), carry_phrase(info)) if x)
    return f'<div class="playline">{extras}</div>' if extras else ''


def hole_panel(hole, sheet_label):
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    gsvg, s = GREENS[hole]
    lsvg, i = LAYOUTS[hole]
    others = " / ".join(f"{lbl[:3]}{row[idx]}" for lbl, idx in config.OTHERS)
    grnlab, slope = green_honesty(hole, s)
    lead = (f'green <b>{esc(s["feeds"])}</b> &middot; no slope printed' if slope is None else slope)
    playline = playline_html(hole, i)          # shared with the enlarged edition -- see playline_html

    # Trees are found by height above ground in the point cloud, so a hole the survey does not reach
    # draws NONE -- and on the map that is indistinguishable from a links hole that genuinely has none,
    # while the guide card's legend promises "trees". Said on the hole's own card, beside the bunker and
    # water counts it belongs with, because that is where the reader is looking at the blank corridor.
    # Monarch Bay 1, 17 and 18 are the case: zero markers each, and exactly the three holes
    # lidar_coverage.py reports as centreline outside the point data. They are the only zero-tree holes
    # in the corpus, so the blank is the survey's edge and not open ground.
    #
    # NOT on the guide card, where the other per-hole data caveats live: that panel is full. A single
    # extra row there overflowed monarch-bay's card by 20 px and clipped the legal notice and the
    # contact line, and trimming 33 characters of existing wording did not buy the line back. Derived
    # from the shipped tree data, so it cannot go stale and needs no extra pipeline stage -- which also
    # means it cannot prove WHY a hole is empty, hence "no tree data" rather than a coverage claim.
    notrees = ""
    if not _tree_markers(hole) and _course_has_trees():
        notrees = ' &middot; <b>no tree data</b>'
    foot = (f'<span>{lead}</span>'
            f'<span>{s["depth_yd"]}yd deep &middot; {i["bunkers"]}B {i["waters"]}W{notrees}'
            f' &middot; {esc(others)}</span>')
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
    <div class="grn"><div class="minilab">{grnlab}</div>{gsvg}</div>
  </div>
  <div class="foot">{foot}</div>
  {playline}
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
    badge_text, badge_stroke, badge_fill, badge_size = (
        _cover_badge()[k] for k in ("badge_text", "badge_stroke", "badge_fill", "badge_size"))
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
  <rect x="70" y="426" width="210" height="18" rx="9" fill="none" stroke="{badge_stroke}" stroke-width="0.8"/>
  <text x="175" y="438" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="{badge_size}" letter-spacing="1.0" fill="{badge_fill}">{badge_text}</text>
  <text x="175" y="462" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="8" letter-spacing="3" fill="#7f9484">JUNIOR GOLF EDITION</text>
  <text x="175" y="474" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="6.2" letter-spacing="0.5" fill="#6f8676">&#169; 2026 Lucas Wu &#183; Lucas Green Book&#8482;</text>
</svg></div>'''


def _cover_badge():
    """The cover's one-line badge: the Rule 4.3 claim, or a do-not-share mark when it may not be shared.

    A non-distributable book had an identical cover to a distributable one -- "DESIGNED TO CONFORM *
    RULE 4.3 / JUNIOR GOLF EDITION" -- and page 1 is what anyone receiving the PDF sees first. The
    personal-use notice added to the About text sits four cards deep. Poppy Ridge is that book: rebuilt in
    2025 with no post-construction survey, so its greens are deliberately blank and it is personal-use
    only.

    On a blank-green book the Rule 4.3 badge is also beside the point. The rule limits GREEN-READING
    material; a book that prints none conforms trivially, so leading with that claim emphasises the one
    thing the book is not doing. The do-not-share mark is the fact a reader actually needs.
    """
    if DISTRIBUTABLE:
        return dict(badge_text="DESIGNED TO CONFORM &#183; RULE 4.3", badge_stroke="#b9973f",
                    badge_fill="#dcc27f", badge_size="7.0")
    return dict(badge_text="PERSONAL USE ONLY &#183; PLEASE DO NOT SHARE", badge_stroke="#c08a4a",
                badge_fill="#e8b478", badge_size="6.4")


def _naip_line():
    """Credit USDA NAIP where -- and only where -- a course actually used it.

    NAIP is a USDA public-domain work, so no permission or notice is legally required. But the about
    panel enumerates the book's sources, and two books named it nowhere: valley-hi digitized hole
    16's green from NAIP, and poppy-ridge used it as a site reference. A book that lists its sources
    should list all of them.

    Deliberately worded to cover both uses without overstating either -- "traced a green outline"
    would be false for poppy-ridge, whose greens are blank; per-course detail is in legal/03."""
    blob = str(config.COURSE.get("sources", {})).lower()
    if "naip" not in blob:
        return ""
    return (' <b>USDA NAIP</b> aerial imagery (a U.S. Government work, public domain) was used as a '
            'mapping reference for this course.')


def _flown_line():
    """One honest line naming WHEN the elevation under these greens was measured.

    A green map is only as current as the flight beneath it, and a USGS project NAME is not a
    date (four of our courses were mislabelled by 2-12 years). The date is decoded from the LAZ
    point records by tools/lidar_dates.py and stored in course.json as lidar_flown.

    The range is normally narrowed to the points lying OVER the greens; where that was not possible
    tools/lidar_dates.py falls back to the union over whole tiles and records that in `basis`. The
    legal provenance table qualifies such a range, and so must the card: the governing rule is about
    what the BOOK prints, so the book is the one place the caveat must not be missing. A tile can
    span weeks and hold no point within a kilometre of any green -- The Reserve's did, which is how
    a 38-day range came to be printed for greens flown on two days."""
    fl = config.COURSE.get("lidar_flown") or {}
    label = fl.get("label")
    if not label:
        return ""
    # Fail closed: a record with NO basis predates that distinction, and its label WAS the whole-tile
    # union, so silence must read as the weaker claim rather than the stronger one.
    basis = fl.get("basis")
    over_greens = bool(basis) and basis.startswith("points within")
    qual = ("" if over_greens else
            " That range covers whole survey tiles, not only the points over these greens, so it may"
            " be wider than the flight that actually built them.")
    out = ('  <div class="legrow"><span><b>Measured</b> from public USGS 3DEP LiDAR flown '
           f'<b>{esc(label)}</b>.{esc(qual)} Greens rebuilt after that date will not match &mdash; '
           'trust what you see on the ground.</span></div>\n')
    stale = sorted(config.COURSE.get("greens_possibly_outdated", []))
    if stale:
        holes = ", ".join(str(h) for h in stale)
        out += ('  <div class="legrow"><span><b>&#9888; Holes ' + esc(holes) + '</b> were '
                '<b>rebuilt after</b> that survey, so their green maps are marked '
                '<b>&ldquo;pre-rebuild data&rdquo;</b> &mdash; the shapes and tiers may have '
                'changed. Use them as a guide only and trust your own read.</span></div>\n')
    # The other caveat a card can carry needs the same treatment. Six of Monarch Bay's greens print
    # "GREEN - 1 m data" and the phrase appeared NOWHERE else in either edition -- a 12-year-old
    # reading it learns nothing, and the whole point of the label is to tell him to trust that green
    # a little less. Named per hole, exactly like the pre-rebuild wording.
    coarse = sorted(h for h, (_svg, summ) in GREENS.items()
                    if 'seamless' in str(summ.get('source', '')).lower())
    if coarse:
        holes = ", ".join(str(h) for h in coarse)
        out += ('  <div class="legrow"><span><b>Holes ' + esc(holes) + '</b> had no usable point '
                'cloud (tree cover or water), so their greens come from the coarser <b>1 m</b> '
                'national elevation model and are marked <b>&ldquo;1 m data&rdquo;</b>. The tilt is '
                'real, just less sharp &mdash; small tiers may be smoothed away.</span></div>\n')
    # And the same treatment for the TREE layer, which had none. Trees are found by height above
    # ground in the point cloud, so a hole the survey does not reach draws no trees -- indistinguishable
    # on the card from a hole that genuinely has none, while the legend promises "trees". Monarch Bay 1,
    # 17 and 18 are the case: zero markers each, and they are exactly the three holes lidar_coverage.py
    # reports as having centreline outside the point data. They are also the only zero-tree holes in the
    # whole corpus, so the blank is the survey's edge, not open ground.
    #
    # Derived from the shipped tree data rather than from a coverage report, so it cannot go stale
    # against a rebuild and needs no extra pipeline stage. That also means it cannot prove WHY a hole
    # is empty, so the wording claims only what is known: no markers fell here, do not read the blank
    # as clear. Suppressed when a course has no tree data at all -- then every hole is blank and the
    # sentence would be noise rather than a caveat.
    return out


def _no_fall_note():
    """Explain the no-clear-fall wording ONLY in a book that actually uses it.

    It is the vocabulary of one green in the corpus today, so putting it on every course's guide card
    would be clutter that describes nothing in that book. Keyed off what was actually rendered."""
    if not any(sm.get("feeds") == render_green.NO_CLEAR_FALL for _svg, sm in GREENS.values()):
        return ''
    return ('  <div class="legrow"><span><b>&ldquo;no clear fall&rdquo;</b> on a green means the '
            'surface is too level for this data to name a side &mdash; the plane through it and the '
            'arrows on it disagree, so no direction is claimed. The measured slope % is still '
            'printed. Read that one with your own eyes.</span></div>\n')


def guide_panel():
    return '''<div class="panel guide">
  <div class="gtitle">How to read a green</div>
  <div class="legrow"><svg width="28" height="14"><line x1="2" y1="7" x2="18" y2="7" stroke="#15271b" stroke-width="1.3"/><polygon points="18,7 14,4.5 14,9.5" fill="#15271b"/></svg>
    <span><b>Arrows</b> point downhill &mdash; the way the ball rolls. Longer = steeper.</span></div>
  <div class="legrow"><span><b>Numbers</b> = slope % at that spot. Ground steeper than
    <b>10%</b> is not putting surface (a bank or bunker face inside the mapped edge), so it is
    shown by colour only and carries no number.</span></div>
  <div class="legrow"><svg width="28" height="14"><path d="M2,11 Q9,3 26,6" stroke="#3c5a34" fill="none" stroke-width="0.9"/><path d="M2,13 Q11,7 26,11" stroke="#3c5a34" fill="none" stroke-width="0.9"/></svg>
    <span><b>Contours</b> join equal height (15&nbsp;cm each). Close = steep.</span></div>
  <div class="legrow"><svg width="28" height="14"><rect x="2" y="3" width="7" height="9" fill="rgb(120,190,120)"/><rect x="10" y="3" width="7" height="9" fill="rgb(232,224,120)"/><rect x="18" y="3" width="7" height="9" fill="rgb(210,90,70)"/></svg>
    <span><b>Colour</b> = steepness: green flat &rarr; yellow &rarr; red (&ge;5%). <b>Numbers</b> = slope % there.
    <b>Print in colour</b> &mdash; over 10% has colour and no number, and bunkers fade into the fairway.</span></div>
  <div class="legrow"><span><b>HOLE</b> map: bunkers (tan), water (blue), <b>trees</b>. <b>Left</b> = to green (straight), <b>right</b> = from the tee (walked) &mdash; on a dogleg they do <b>not</b> add up.</span></div>
  <div class="legrow"><span><b>GREEN</b> is turned so your <b>approach is at the bottom</b>; small <b>N</b> = true north. "feeds" = the low side putts run toward.</span></div>
''' + _no_fall_note() + '''
  <div class="legrow"><span><b>green N ft above/below</b> = the <b>measured</b> height of the green
    against its back tee. It is <b>not</b> a yardage adjustment &mdash; how much club that is worth
    depends on your own ball flight, so <b>you</b> make that call.</span></div>
  <div class="legrow"><span><b>carry N</b> = yd from the back tee to where fairway sand <b>starts</b>,
    along the line. The sand can run well past N &mdash; check the map.</span></div>
''' + _flown_line() + '''  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> green book for junior golfers, <b>not for sale</b>. Hole &amp;
      green shapes, and the <b>carry</b> distances measured from them, are a Produced Work from
      <b>OpenStreetMap</b> data (&copy;&nbsp;OpenStreetMap
      contributors, <b>ODbL&nbsp;1.0</b>, osm.org/copyright); slope, contours, arrows &amp; <b>elevation
      change</b> are computed by the
      maker from <b>public-domain USGS&nbsp;3DEP</b> elevation (a U.S. Government work); par, yardage &amp;
      handicap (<b>HCP</b> = the <b>men&rsquo;s</b> stroke index) are <b>facts</b> from the published scorecard.''' + _naip_line() + ''' Every map is <b>independently created</b>:
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
      Learn more at <b>lucasgreenbook.org</b>; contact / removal requests: <b>info@lucasgreenbook.org</b>. &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. ''' + sharing_line() + '''</div>
  </div>
</div>'''


def scorecard_panel():
    # BACK first, then FRONT -- not FEATURED/SECONDARY. config.BACK_I exists precisely because the
    # book is built on ONE tee, and FEATURED is only whichever of the pair course.json happens to
    # name first: on 6 of 12 courses it is the FORWARD tee. So the scorecard led with White 6015 on
    # callippe while every hole card headlined Black 6749, and the reader had to notice the title had
    # swapped order relative to the cards to find the column their book is actually built on.
    # Same drift the BACK_I comment in config.py describes, in the one panel that had not been moved.
    fl, sl = config.BACK_NAME, config.FRONT_NAME
    fi, si = config.BACK_I, config.FRONT_I
    nums = config.HOLE_NUMS
    def row(h):
        r = HOLES[h]
        return f"<tr><td>{h}</td><td>{r[0]}</td><td>{r[1]}</td><td>{r[fi]}</td><td>{r[si]}</td></tr>"
    def tot(hs):
        return (sum(HOLES[h][0] for h in hs), sum(HOLES[h][fi] for h in hs), sum(HOLES[h][si] for h in hs))
    head = (f'<tr class="th"><td>H</td><td>Par</td><td>HCP</td>'
            f'<td>{esc(fl[:4])}</td><td>{esc(sl[:4])}</td></tr>')
    if len(nums) <= 9:
        # single nine (a 9-hole course): holes then one Total row -- no front/back split
        tp, tf, ts = tot(nums)
        table = (head + "".join(row(h) for h in nums) +
                 f'<tr class="sum tot"><td>Tot</td><td>{tp}</td><td></td><td>{tf}</td><td>{ts}</td></tr>')
    else:
        front = [h for h in nums if h <= 9]; back = [h for h in nums if h > 9]
        op, of, os_ = tot(front); ip, iff, iss = tot(back)
        table = (head + "".join(row(h) for h in front) +
                 f'<tr class="sum"><td>Out</td><td>{op}</td><td></td><td>{of}</td><td>{os_}</td></tr>' +
                 "".join(row(h) for h in back) +
                 f'<tr class="sum"><td>In</td><td>{ip}</td><td></td><td>{iff}</td><td>{iss}</td></tr>' +
                 f'<tr class="sum tot"><td>Tot</td><td>{op+ip}</td><td></td><td>{of+iff}</td><td>{os_+iss}</td></tr>')
    return f'''<div class="panel card">
  <div class="cardtitle">Scorecard &mdash; {esc(fl)} / {esc(sl)}</div>
  <table>
    {table}
  </table>
</div>'''

def tees_panel():
    """Every published tee with its length and rating -- and a mark on the ones this book cannot break
    down hole by hole.

    A tee appears here from course.json's `tees` list, but per-hole yardages come from `hole_cols`, and the
    two are not always the same set. philadelphia lists a Green tee at 5819 yd with a 69.3/128 rating and
    has no Green column; the-reserve lists two COMBINATION tees (Blu/Wht, Wht/Grn) that by nature have
    none. Nothing printed is false -- these are published facts about real tees -- but a junior who plays
    one of them would search all 18 cards for a yardage that is not in the book, and philadelphia's Green
    is also outside the four tees its sources cross-verified. So say which rows the book supports.
    """
    def cell(v):
        return "&mdash;" if v is None or v == "" else esc(v)
    per_hole = set(config.TEES)
    unbacked = [t for t in config.TEE_TABLE if t.get("name") not in per_hole]
    rows = "".join(
        f'<tr><td>{esc(t["name"][:7])}'
        + ("<sup>&dagger;</sup>" if t.get("name") not in per_hole else "")
        + f'</td><td>{cell(t["yards"])}</td><td>{cell(t.get("rating"))}</td><td>{cell(t.get("slope"))}</td></tr>'
        for t in config.TEE_TABLE)
    note = ("" if not unbacked else
            " <b>&dagger;</b> published tee with <b>no hole-by-hole yardages in this book</b> &mdash; "
            "the scorecard pages cover the other tees.")
    return f'''<div class="panel info">
  <div class="cardtitle">Tees &middot; Rating / Slope</div>
  <table class="tt">
    <tr class="th"><td>Tee</td><td>Yds</td><td>Rate</td><td>Slp</td></tr>
    {rows}
  </table>
  <div class="gsmall">{_scorecard_claim()} Rating &amp; slope as published for the
    course &mdash; see the provenance record for each course's source.{note}</div>
</div>'''


def _scorecard_claim():
    """How the tees card may describe where its yardages came from -- per course, not one boast.

    The card said "Yardages from the official scorecard." on every book. Only 4 of 11 courses record an
    official or printed club scorecard; the other 7 record third-party aggregators -- BlueGolf, NCGA,
    GolfLink, Wikipedia, Golfify. For those, "official" is a claim about provenance the record does not
    support, printed beside the very numbers it is vouching for.

    The same book already says the honest version two cards away: the guide card credits "facts from the
    PUBLISHED scorecard". So this is not a hard question about what is true, only about which of two
    wordings a given course has earned. Derived from sources.scorecard, which is the field the provenance
    record is built from, so the card and legal/03 cannot disagree.

    Aggregator data is not less honest -- bay-view's own source note records that a third-party record
    was WRONG and was corrected against the club's card -- which is exactly why the distinction is worth
    printing rather than papering over.
    """
    src = str((config.COURSE.get("sources") or {}).get("scorecard") or "").lower()
    official = ("official" in src) or ("printed scorecard" in src)
    return ("Yardages from the <b>official</b> scorecard." if official else
            "Yardages from <b>published</b> scorecard data.")


def legend_panel():
    flag = ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<line x1="9" y1="4" x2="9" y2="22" stroke="#b8860b" stroke-width="1.6" stroke-linecap="round"/>'
            '<path d="M9 4 L20 8 L9 12 Z" fill="#b8860b"/></svg>')
    # The caption is not decoration. This QR is an INSTAGRAM code and it sits directly under
    # "VISIT lucasgreenbook.org", so a reader -- a twelve-year-old -- scans it expecting the website
    # and lands on a social profile. The only thing distinguishing them was the logo baked into the
    # image. `.dqrcap` was defined for this, complete with an Instagram-purple rule for its <b>, and
    # never emitted; the caption had clearly been intended and was lost.
    qr = (f'<div class="dqr"><img src="{IG_QR}" alt="@lucaswu.golf"/>'
          f'<div class="dqrcap">Instagram <b>@lucaswu.golf</b></div></div>') if IG_QR else ""
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
  <div class="dweb"><div class="dwebtag">VISIT</div><div class="dweburl">lucasgreenbook.org</div></div>
  {qr}
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. Free to share, not for sale &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
</div>'''

def notes_panel(title, holes_range):
    lines = "".join(f'<div class="nrow"><b>{h}</b><span></span></div>' for h in holes_range)
    return f'<div class="panel notesp"><div class="gtitle">{esc(title)}</div>{lines}</div>'

# ---- imposition helpers ---------------------------------------------------
def crop_ticks(x, y, w, h, t=0.14):
    """L-shaped cut ticks just outside each corner of a card, for trimming."""
    segs = []
    for (cx, cy, hx, vy) in [(x, y, -1, -1), (x+w, y, 1, -1), (x, y+h, -1, 1), (x+w, y+h, 1, 1)]:
        hl = cx-t if hx < 0 else cx
        vt = cy-t if vy < 0 else cy
        segs.append(f'<div class="crop" style="left:{hl:.3f}in;top:{cy-0.003:.3f}in;width:{t}in;height:0.006in"></div>')
        segs.append(f'<div class="crop" style="left:{cx-0.003:.3f}in;top:{vt:.3f}in;width:0.006in;height:{t}in"></div>')
    return "".join(segs)

def pad_to_leaves(cards, blank='<div class="panel"></div>'):
    """Pad an odd card list to whole duplex leaves by inserting the blank BEFORE the last card.

    The final card is Lucas's dedication and prints upright as the back cover, so APPENDING the
    blank would land the dedication a leaf early and end the book on a blank page. Module-level so
    the layout test can call this rather than re-implement it."""
    if len(cards) % 2:
        return cards[:-1] + [blank] + cards[-1:]
    return list(cards)


def is_upright_back(card_index, ncards):
    """True for the one duplex BACK that must not be rotated 180: the dedication / back cover."""
    return card_index == ncards - 1


def _deck_thirds(nums):
    """[(lo, hi, "lo-hi")] for the three thumb-index groups, derived from the holes present.

    Derived rather than hardcoded so a 9-hole book gets 1-3 / 4-6 / 7-9 and an 18-hole one 1-6 / 7-12 /
    13-18, instead of the old 6/8/4 which came from two hand-written branches."""
    n = len(nums)
    if n == 0:
        return []
    cut = [nums[0] - 1] + [nums[min((i + 1) * n // 3, n) - 1] for i in range(3)]
    out, seen = [], set()
    for i in range(3):
        lo, hi = cut[i] + 1, cut[i + 1]
        if hi < lo or (lo, hi) in seen:
            continue
        seen.add((lo, hi))
        out.append((lo, hi, f"{lo}\u2013{hi}"))
    return out


def main():
    yardage = (config.BUILD_MODE == "yardage")
    if not yardage:
        for h in config.HOLE_NUMS:
            GREENS[h] = render_green.render(h, tournament=True)  # single conforming book
            LAYOUTS[h] = render_hole.render_hole(h, HOLES)
    # flat, ordered deck of cards (cut-and-stack, top-bound)
    panels = [cover_panel(), yardage_guide_panel() if yardage else guide_panel()]
    # The corner tab is a THUMB INDEX -- which third of the cut deck this card is in -- and it used to
    # read "Front" / "Mid" / "Finish". "Front" means holes 1-9 in golf, universally, and it was being
    # used here for 1-6 while the SAME BOOK's scorecard splits Out 1-9 / In 10-18. So one book grouped
    # its own holes two ways and a junior looking under "Front" for hole 8 found it tabbed "Mid".
    # Literal ranges cannot collide with a golf term, state the grouping instead of naming it, and make
    # the uneven split visible rather than surprising.
    thirds = _deck_thirds(config.HOLE_NUMS)
    for h in config.HOLE_NUMS:
        grp = next(lbl for lo, hi, lbl in thirds if lo <= h <= hi)
        panels.append(yardage_hole_panel(h, grp) if yardage else hole_panel(h, grp))
    panels += [scorecard_panel(), tees_panel(),
               notes_panel(f"Notes {config.HOLE_NUMS[0]}-{config.HOLE_NUMS[-1]}"
                           if config.NHOLES <= 18 else "Notes",
                           config.HOLE_NUMS), legend_panel()]

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
  .yalt {{ display: block; font-size: 7.5pt; color: #767676; }}   /* front tee: secondary to the back tee, but it IS a yardage -- 4.5:1 */
  .body {{ flex: 1; min-height: 0; display: flex; gap: 1px; margin: 1px 0 0; }}
  .lay {{ flex: 1.6; min-width: 0; position: relative; }}
  .grn {{ flex: 2.4; min-width: 0; position: relative; }}
  .lay svg {{ width: 100%; height: 100%; }}
  /* GREEN: never force a size -- render_green sizes it in inches to hold the Rule 4.3
     scale cap. max-* can only shrink, so it can never enlarge past the legal scale. */
  .grn svg {{ max-width: 100%; max-height: 100%; }}
  .ytab {{ width: 100%; border-collapse: collapse; font-size: 11pt; margin-top: 4px; }}
  .ytab td {{ border: 1px solid #d7d7d7; padding: 3px 8px; }}
  .ytab tr td:first-child {{ text-align: left; font-weight: 600; color: #2b6a2b; }}
  .ytab tr td:last-child {{ text-align: right; font-weight: 700; }}
  .ytab .th td {{ background: #2b6a2b; color: #fff; font-size: 8pt; font-weight: 700; text-align: center; }}
  .ynotehd {{ font-size: 8pt; font-weight: 700; color: #2b6a2b; margin: 7px 0 3px; }}
  .ynote {{ flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 2px; }}
  .ynote .nl {{ border-bottom: 1px solid #cfcfcf; height: 1px; }}
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 5.5pt; color: #9a9a9a; letter-spacing: .5px; z-index: 2; }}
  /* flex-wrap + nowrap spans: the footer is too long to fit one line on a 5-tee course (three
     "other" tees make the right span 44 characters), and without these it broke MID-PHRASE --
     monarch-bay orphaned "3.1%" on its own line and split "Gol403 / Gre338 /" from "Red288".
     The same fault the playline had. Wrapping BETWEEN the two spans is fine; inside one is not. */
  /* #999 was 2.85:1 on white -- below the 4.5:1 needed at this size, and this row carries the
     feed direction, the tilt %, the green depth and the bunker count. Secondary, not faint. */
  .foot {{ display: flex; flex-wrap: wrap; justify-content: space-between; font-size: 7.5pt;
           color: #767676; margin-top: 1px; }}}}
  .foot span {{{{ white-space: nowrap; }}}}
  .playline {{ font-size: 7.5pt; color: #666; margin-top: 0.5px; white-space: nowrap; overflow: hidden; }}
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
  .dweb {{ margin-top: 8px; }}
  .dwebtag {{ font-size: 4.5pt; letter-spacing: 2px; color: #b8860b; font-weight: 700; margin-bottom: 1.5px; }}
  .dweburl {{ font-size: 7pt; font-weight: 600; color: #2b6a2b; letter-spacing: .5px; }}
  .dcopy {{ position: absolute; bottom: 0.14in; left: 0.3in; right: 0.3in; font-size: 6pt; color: #9a9a9a; letter-spacing: .2px; line-height: 1.3; }}
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
        cards = pad_to_leaves(cards)      # blank goes BEFORE the dedication -- see the helper
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
                is_last = is_upright_back(2*L+1, len(cards))
                backs.append(card_div(xb, yb, 2*L+2, cards[2*L+1], not is_last))
            pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; FRONT &middot; PRINT AT 100% &mdash; do not scale or fit to page</div>{"".join(fronts)}</div>')
            pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; BACK (duplex, flip on LONG edge) &middot; PRINT AT 100%</div>{"".join(backs)}</div>')
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
    playline = playline_html(hole, i)          # the SAME row the pocket card prints, by construction
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
  {playline}
</div>'''

def coach_green_card(hole):
    row = HOLES[hole]; par, hcp = row[0], row[1]
    gsvg, s = GREENS[hole]
    # same honesty rules as the pocket card -- this edition used to print none of them
    grnlab, slope = green_honesty(hole, s)
    clead = (f'green <b>{esc(s["feeds"])}</b> &middot; no slope printed' if slope is None else slope)
    return f'''<div class="panel hole">
  <div class="etag">ENLARGED</div>
  <div class="hhead">
    <div class="hnum">{hole}</div>
    <div class="hmeta"><div class="par">PAR {par}</div><div class="si">HCP {hcp}</div></div>
    <div class="hyd"><span class="ymain" style="color:{tee_color(BACK_NAME)}">{row[BACK_I]}</span><span class="ylab" style="color:{tee_color(BACK_NAME)}">{esc(BACK_NAME)}</span></div>
  </div>
  <div class="cmap"><div class="minilab">{grnlab} &middot; approach at bottom</div>{gsvg}</div>
  <div class="foot"><span>{clead}</span>
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
    "feeds" = the low side putts run toward. <b>Print in colour</b> &mdash; ground over 10% is shown
    by colour only, and bunkers all but vanish in black &amp; white.</span></div>
''' + _no_fall_note() + '''
  <div class="legrow"><span>Because the greens here are printed <b>larger than the tournament scale</b>,
    this enlarged edition is a <b>practice aid and is NOT a conforming competition book under
    Rule&nbsp;4.3</b> &mdash; use the standard pocket edition for competition.</span></div>
  <div class="legrow"><span><b>green N ft above/below</b> = measured height vs the back tee, <b>not</b> a
    yardage adjustment. <b>carry N</b> = yd to where fairway sand starts; it can run past N.</span></div>
''' + _flown_line() + '''  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> green book. Hole &amp; green shapes, and the <b>carry</b>
      distances measured from them, are a
      Produced Work from <b>OpenStreetMap</b> data (&copy;&nbsp;OpenStreetMap contributors, <b>ODbL&nbsp;1.0</b>, osm.org/copyright);
      slope, contours, arrows &amp; <b>elevation change</b> are computed by the maker from
      <b>public-domain USGS&nbsp;3DEP</b> LiDAR; par,
      yardage &amp; handicap (<b>HCP</b> = men&rsquo;s stroke index) are <b>facts</b> from the published scorecard. <b>No proprietary data, image, symbol
      set, layout or trade dress of any commercial green-reading product was used, copied or referenced.</b>
      Not affiliated with, endorsed or sponsored by any course, club, association or product; names &amp;
      trademarks belong to their owners and identify the course only &mdash; contact the maker for removal.
      Provided <b>as-is, no warranty</b>; maps show general tilt, not exact break &mdash; trust your own read.
      <b>lucasgreenbook.org</b> &middot; contact <b>info@lucasgreenbook.org</b>. &copy;&nbsp;2026 Lucas Wu &middot; Lucas Green Book&trade;. ''' + sharing_line() + '''</div>
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
  <div class="dweb"><div class="dwebtag">VISIT</div><div class="dweburl">lucasgreenbook.org</div></div>
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. Practice aid, free to share &mdash; CC&nbsp;BY-NC-ND&nbsp;4.0.</div>
</div>'''

def build_coach(coach_name=""):
    if config.BUILD_MODE == "yardage":
        # There is nothing to enlarge: yardage mode exists precisely because no trustworthy green
        # surface is available, so the pocket book prints blank greens. Say so instead of dying on
        # a missing dem_hd file.
        raise SystemExit(f"{config.SLUG} is a yardage-mode course (no green surfaces), so there is\n"
                         f"  no enlarged green to render. Build the pocket book instead:\n"
                         f"    COURSE={config.SLUG} python3 generate.py")
    # coach_name is PRIVATE (a specific person) -> default empty; pass it at build time via
    # COACH_NAME so no real name is ever committed. Empty -> generic "your coach" wording.
    # ENLARGED edition: SAME print imposition as the normal book (4-up, duplex,
    # top-flip, last card upright like the cover) -- to save paper. The ONLY
    # difference vs. normal: each hole is TWO cards (course map = leaf FRONT,
    # green = leaf BACK), so you "flip up one more page" to the green. Map
    # wording/numbers are rendered ~2x bigger (font_scale) for older eyes.
    for h in config.HOLE_NUMS:
        # tournament=False is the ENLARGED render. This used to ask for the conforming, size-capped
        # render and then rely on the coach stylesheet to stretch it -- but render_green sets the
        # size INLINE in inches (deliberately, so CSS cannot enlarge a book past the Rule 4.3 cap),
        # and an inline style beats a stylesheet. So the "ENLARGED" edition printed its greens at
        # exactly the pocket scale, ratio 1.00 on all 18 holes, while the card, README and
        # PIPELINE.md all said they were bigger.
        GREENS[h] = render_green.render(h, tournament=False)
        LAYOUTS[h] = render_hole.render_hole(h, HOLES, font_scale=2.0)
    # deck: leaf0 = [cover, enlarged-about]; leaf h = [hole h map, hole h green];
    # then back matter. Holes land one-per-leaf (map front / green back).
    cards = [coach_cover_panel(coach_name), coach_about_card()]
    for h in config.HOLE_NUMS:
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
            # the SAME rule the pocket book uses, not a second copy of it: green_honesty, the footer
            # and the playline each drifted between these two code paths before being shared, and this
            # was the last rule still written twice.
            is_last = is_upright_back(2*L+1, len(cards))
            backs.append(card_div(xb, yb, 2*L+2, cards[2*L+1], not is_last))
        pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; FRONT &middot; PRINT AT 100% &mdash; do not scale or fit to page</div>{"".join(fronts)}</div>')
        pages.append(f'<div class="sheet"><div class="sheetnote">Sheet {s+1} &middot; BACK (duplex, flip on LONG edge) &middot; PRINT AT 100%</div>{"".join(backs)}</div>')

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
  .yalt {{ display: block; font-size: 8.5pt; color: #767676; }}   /* front tee: secondary, still a yardage */
  .cmap {{ flex: 1; min-height: 0; position: relative; margin: 2px 0; }}
  .cmap svg {{ width: 100%; height: 100%; }}
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 7pt; color: #9a9a9a; letter-spacing: .5px; z-index: 2; }}
  /* flex-wrap + nowrap spans: the footer is too long to fit one line on a 5-tee course (three
     "other" tees make the right span 44 characters), and without these it broke MID-PHRASE --
     monarch-bay orphaned "3.1%" on its own line and split "Gol403 / Gre338 /" from "Red288".
     The same fault the playline had. Wrapping BETWEEN the two spans is fine; inside one is not. */
  .foot {{ display: flex; flex-wrap: wrap; justify-content: space-between; font-size: 8pt;
           color: #767676; margin-top: 1px; }}}}
  .foot span {{{{ white-space: nowrap; }}}}
  .playline {{ font-size: 8pt; color: #666; margin-top: 0.5px; white-space: nowrap; overflow: hidden; }}
  .cover {{ position: relative; overflow: hidden; padding: 0; }}
  .gtitle, .cardtitle {{ font-size: 12pt; font-weight: 800; color: #2b6a2b; border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; margin-bottom: 4px; }}
  .legrow {{ display: flex; gap: 4px; align-items: flex-start; font-size: 8pt; line-height: 1.3; margin-bottom: 5px; }}
  .abt {{ margin-top: 4px; border-top: 1.2px solid #cdb96a; padding-top: 3px; }}
  .abthead {{ font-size: 8pt; font-weight: 800; color: #2b6a2b; margin-bottom: 1px; }}
  /* The legal block sat at 6.6pt against the pocket book's 5.15pt, and it ran OFF the card: its last
     lines were sliced through by the trim line, so a cut sheet lost them. This edition exists to make the
     MAPS and the LEGENDS readable for older eyes; enlarging the small print too is what did not fit.
     5.9pt still beats the pocket book by 15% and leaves the card whole. */
  .abtxt {{ font-size: 5.75pt; line-height: 1.22; color: #6b6b6b; text-align: justify; }}
  .dedic {{ align-items: center; text-align: center; justify-content: center; padding: 0.28in 0.3in; }}
  .dcrest {{ margin-bottom: 6px; line-height: 0; }}
  .dtitle {{ font-family: Georgia,"Times New Roman",serif; font-style: italic; font-size: 16pt; color: #2b6a2b; margin-bottom: 9px; }}
  .dtext {{ font-size: 10pt; line-height: 1.42; color: #333; }}
  .dtext p {{ margin: 0 0 7px; }}
  .drule {{ width: 40%; border-top: 1.4px solid #d9b23a; margin: 11px auto 7px; }}
  .dsign {{ font-size: 12pt; color: #1a1a1a; }}
  .dweb {{ margin-top: 10px; }}
  .dwebtag {{ font-size: 5.5pt; letter-spacing: 2.5px; color: #b8860b; font-weight: 700; margin-bottom: 2px; }}
  .dweburl {{ font-size: 9pt; font-weight: 600; color: #2b6a2b; letter-spacing: .6px; }}
  .dcopy {{ position: absolute; bottom: 0.16in; left: 0.3in; right: 0.3in; font-size: 7pt; color: #9a9a9a; letter-spacing: .2px; line-height: 1.3; }}
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
