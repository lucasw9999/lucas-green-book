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
import re
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


DISTRIBUTABLE = distribution.is_distributable(config.COURSE)

# THE REASON A BOOK MAY NOT BE SHARED IS STATED IN TWO RECORDS, and nothing tied their WORDS together.
# The left half of each pair is what the card prints; the right half is what distribution.py's own reason
# for the SAME refusal has to claim -- that reason is what tools/gen_provenance.py writes into
# legal/03_PROVENANCE_BY_COURSE.md. The verdict already cannot disagree (both are keyed on the same data
# facts, is_distributable and is_yardage); the two TEXTS still could, which is the same
# claim-published-in-two-records-with-no-cross-check shape as the rest of this file's history.
#
# Each probe is a MINIMAL course record of that class, so the check asks distribution.py what it says
# about the refusal itself and not about whichever course happens to be loaded -- flipping DISTRIBUTABLE
# on a course whose record is fine (which the suite does, to reach the wording) must not trip it.
#
# The printed sentences are quoted verbatim in legal/05_DISCLAIMER_TEXT.md, which is generated FROM the
# books, so they are the half that must not move; if distribution.py rewords a reason so that it no
# longer makes the claim the card is printing, THIS build stops rather than shipping the disagreement.
_REFUSALS = {
    "yardage": (
        {"build_mode": distribution.YARDAGE},
        ("yardage mode", "blank greens"),
        "<b>This copy is for personal use only &mdash; please do not share or redistribute "
        "it</b>, because its greens are blank for want of trustworthy survey data and a reader "
        "elsewhere cannot know that. Not for sale. All rights reserved."),
    "unvouched": (
        {"build_mode": "not-a-documented-build-mode"},
        ("unrecognised build_mode", "unknown"),
        "<b>This copy is for personal use only &mdash; please do not share or redistribute "
        "it</b>, because this course's build record is not one this project can vouch for and a "
        "reader elsewhere cannot know that. Not for sale. All rights reserved."),
}


def _refusal_sentence(kind):
    """The printed reason for one refusal -- once distribution.py still gives that reason for it."""
    probe, must_claim, sentence = _REFUSALS[kind]
    ok, _label, why = distribution.distribution_status(probe)
    missing = [c for c in must_claim if c not in why.lower()]
    if ok or missing:
        raise SystemExit(
            f"generate.py prints a {kind!r} refusal on the card while distribution.py no longer gives "
            f"that reason for it, so the book and legal/03_PROVENANCE_BY_COURSE.md would state "
            f"different reasons for the same verdict.\n"
            f"  the card says:      {sentence}\n"
            f"  distribution.py:    {(why or '(it does not refuse this at all)')!r}\n"
            + (f"  missing claim(s):   {', '.join(repr(m) for m in missing)}\n" if missing else "")
            + f"  Reconcile the two. The card's wording is printed in a shipped book and quoted "
              f"verbatim in legal/05_DISCLAIMER_TEXT.md, so restoring the reason in distribution.py is "
              f"normally the cheaper half; changing the card means rebuilding that book and its PDF.")
    return sentence


def sharing_line():
    """The licence sentence -- and for a book that may NOT be shared, a licence that says so.

    distribution.py has always known Poppy Ridge is personal-use only, and legal/03 has always printed
    it, but the BOOK carried the same free-to-share CC BY-NC-ND line as a distributable one. The verdict
    lived in the policy and the paperwork while the artifact invited the opposite, and a PDF that leaves
    this machine carries no trace of either. That course was rebuilt in 2025 with no post-construction
    survey, so its greens are deliberately blank -- and a reader who receives the file cannot know that.

    Asks distribution.py rather than re-testing build_mode, for the same reason gen_provenance does: one
    rule, so the page and the paperwork cannot disagree.

    THE VERDICT AND THE REASON ARE TWO QUESTIONS, and this printed one reason for all three verdicts
    distribution_status() can return. generate.py used to bind all three of its return values and read
    only the first -- `_DIST_LABEL` and `_DIST_WHY` appeared nowhere else in the file -- so the sentence
    LOOKED as though it printed distribution.py's reason and did not. With `"build_mode": "yardge"`, a
    typo distribution.py's own docstring enumerates as realistic and fails closed on, config.BUILD_MODE
    is "yardge": main() builds the FULL slope book with contours and arrows while every card, the cover
    and this line asserted the greens were blank. The book and legal/03 then gave different reasons for
    the same verdict.

    So the reason is keyed on distribution.is_yardage() -- the DATA fact that decides what the engine
    actually drew, kept separate from the verdict in that module for exactly this purpose -- and blank
    greens are claimed only by the book that has them. The other refusals are typos in a hand-edited
    field, and what they were meant to say is unknown, so the sentence says that instead of guessing.

    THE TWO TEXTS could still drift, which the verdict being shared does not fix: distribution.py holds
    its own reason strings, legal/03 is generated from those, and these sentences were spelled here with
    nothing comparing them. Each refusal is taken from _REFUSALS now, which pairs the printed sentence
    with the claim distribution.py's reason for the same refusal must carry -- see _refusal_sentence().

    The yardage wording is quoted verbatim in legal/05_DISCLAIMER_TEXT.md; changing it invalidates that
    record. test_the_licence_sentence_never_states_a_reason_the_book_contradicts pins both branches.
    """
    if DISTRIBUTABLE:
        return ("This book: free to share, not for sale &mdash; "
                "CC&nbsp;BY-NC-ND&nbsp;4.0.")
    if distribution.is_yardage(config.COURSE):
        return _refusal_sentence("yardage")
    return _refusal_sentence("unvouched")


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

# A rebuild this course's OWN record states, in the PAST tense, with a year: "Course rebuilt 2025",
# "fully rebuilt (Jay Blasi, reopened May 2025)". Past participles only, and the year has to sit inside
# the same clause (no sentence or semicolon between them), because the sentence printed from this is
# past tense too -- "this course WAS rebuilt in YYYY". "the rebuild is expected 2027" and "2021 LiDAR is
# pre-rebuild" must not become a claim that it happened, and neither matches.
_REBUILT_RE = re.compile(r"\b(?:rebuilt|renovated|reconstructed|reopened)\b[^.;]{0,60}?"
                         r"\b((?:19|20)\d{2})\b", re.I)
# The fields of a course record that carry this fact today, in the order they are read. "rebuilt" is the
# explicit one to set on a NEW course; the other two are where the corpus states it in prose.
_REBUILT_FIELDS = ("rebuilt", "_status", "dem_source")


def _rebuild_year():
    """The year THIS course's own record says it was rebuilt, or None if it does not say.

    yardage_guide_panel() hardcoded "(this course was rebuilt in 2025)" and "This course was <b>rebuilt
    in 2025 with new greens</b>". Both print in the shipped book and PDF of the one course built in
    yardage mode, where they are true -- and both would have printed unchanged on the SECOND such
    course, asserting a rebuild, in a year, about a course nothing in this project says was rebuilt at
    all. Latent only because 11 of the 12 records carry no build_mode; the claim was keyed on the build
    MODE, which says "no trustworthy post-construction elevation exists" and says nothing about why.

    So the year comes from a per-course fact, and a record that does not state one prints no claim --
    the card still gives the reason every yardage-mode book supports (no trustworthy post-construction
    green-surface data), which is what build_mode actually means.

    WHY PROSE FIELDS AND NOT ONLY AN EXPLICIT KEY. courses/ is gitignored and hand-edited -- it is the
    only copy of the transcribed scorecards -- and the printed sentence is quoted verbatim in
    legal/05_DISCLAIMER_TEXT.md, which is generated FROM the books. Requiring a new key would mean
    editing a course record and reprinting a book and its PDF to say exactly what they already say. The
    fact is already recorded per course, in that course's own record, in the two fields the corpus uses
    for it ("Course rebuilt 2025 (Jay Blasi)" / "fully rebuilt (Jay Blasi, reopened May 2025) with new
    greens"), so it is read from there. `"rebuilt": 2025` is read first and is the clean way to state it
    on a new course.

    Refuses rather than guesses, twice over: nothing is claimed when no field states a rebuild, and
    nothing is claimed when two fields state DIFFERENT years, because then the record disagrees with
    itself and a printed year would be a choice this code is not entitled to make.
    """
    course = config.COURSE or {}
    years = set()
    for key in _REBUILT_FIELDS:
        val = str(course.get(key) or "")
        if key == "rebuilt" and re.fullmatch(r"\s*(?:19|20)\d{2}\s*", val):
            years.add(val.strip())        # the explicit field may state the bare year
            continue
        years.update(m.group(1) for m in _REBUILT_RE.finditer(val))
    return years.pop() if len(years) == 1 else None


def yardage_guide_panel():
    """The yardage-mode legend card. Its rebuild sentence is gated on _rebuild_year() -- see there.

    Both halves of the claim are assembled rather than written out so the two cannot disagree with each
    other: one card cannot say a rebuild explains the missing arrows while the About text below it says
    nothing about a rebuild. Plain-string concatenation, like the _naip_line() and sharing_line() splices
    already here -- NOT an f-string, because splicing a segment out of an f-string is what once printed
    a literal "{qr}" into 12 books.
    """
    year = _rebuild_year()
    if year:
        no_arrows = " (this course was\n    rebuilt in " + year + ")"
        blank_why = ("This course was <b>rebuilt in\n      " + year + " with new greens</b>, and "
                     "accurate post-construction green-surface data is not yet publicly\n"
                     "      available")
        elev_why = "that data does not yet reflect this rebuilt course"
    else:
        no_arrows = ""
        blank_why = ("Accurate post-construction green-surface data for this course is not publicly\n"
                     "      available")
        elev_why = "that data does not describe this course&rsquo;s greens as they are now"
    return '''<div class="panel guide">
  <div class="gtitle">How to use this book</div>
  <div class="legrow"><span><b>Yardages</b> to the green for every tee are on each hole card &mdash;
    from the official scorecard. The big number is the <b>back tee</b>.</span></div>
  <div class="legrow"><span>Use the <b>Read &amp; notes</b> lines to jot the pin, the slope you see, and how the
    ball rolls. Pair this with the printed <b>course aerial</b> to see fairways, bunkers, trees, greens &amp; tees.</span></div>
  <div class="legrow"><span>Green break arrows aren&rsquo;t printed &mdash; see &ldquo;About&rdquo; below for why''' + no_arrows + '''.</span></div>
  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> yardage book for junior golfers, <b>not for sale</b>. Par,
      yardage &amp; handicap (<b>HCP</b> = men&rsquo;s stroke index) are <b>facts</b> from the published scorecard. ''' + blank_why + ''' &mdash; so rather than print slope maps that could be wrong, the greens are left <b>blank
      to mark your own read</b>. (Our other books compute slope from public-domain USGS 3DEP elevation;
      ''' + elev_why + ''', so we do not use it here.)''' + _naip_line() + ''' <b>No proprietary
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
    """LiDAR tree markers on one hole, or [] -- cached; see the note at the footer that uses it.

    A layer that is ABSENT is []: render_hole._lidar_trees() returns {} for that with no exception, and
    a course with no point cloud has no LiDAR canopy to offer -- render_hole then draws whatever OSM
    tree nodes lie in the corridor instead, which is why _drew_trees() and not this function decides
    whether a card owes the "no tree data" caveat. A layer that is UNREADABLE is a STOP.

    The catch here used to be `except Exception: _TREES = {}`, and it could only ever absorb the second
    case: the absent-layer path raises nothing, and the tiles-but-no-layer path raises SystemExit, which
    is not an Exception. So the one thing it caught was a corrupt or truncated trees_lidar.json -- and it
    turned it into zero markers on every hole, which the caveat's gate then reads as "this course has
    no trees" and drops the per-card "no tree data" caveat as noise. A wrecked 126-245 KB canopy record
    printed as a clean, tree-free 18-hole book with nothing anywhere saying the data was missing. It also
    falsified the claim tools/lidar_dates.py used to justify writing that file in place -- that a
    truncated layer "fails loudly at render_hole.py's json.load".
    """
    global _TREES
    if _TREES is None:
        try:
            _TREES = render_hole._lidar_trees() or {}
        except Exception as e:
            raise SystemExit(
                f"trees_lidar.json for {config.SLUG} could not be read ({type(e).__name__}: {e}).\n"
                f"  Drawing no trees would be indistinguishable from a course that has none -- every\n"
                f"  hole prints open ground and the per-card \"no tree data\" caveat is suppressed as\n"
                f"  noise -- so the book is not built from a layer this project cannot parse. Re-run:\n"
                f"    COURSE={config.SLUG} python3 fetch_trees.py") from e
    return _TREES.get(str(hole)) or []


def _drew_trees(hole):
    """Did this hole's map put a tree mark on the paper at all -- of EITHER kind?

    render_hole picks its markers per hole, and it FALLS BACK: `lt = _lidar_trees().get(str(hnum), [])`
    then `if lt: tree_src = lt` `else: tree_src = [(e['lat'], e['lon']) for e in treenodes]`. So the
    LiDAR marker list is not what a hole draws, and keying the "no tree data" caveat on it was wrong in
    both directions:
      * a hole with zero LiDAR markers but OSM tree nodes in its corridor printed "no tree data" beside
        a map that DRAWS trees -- and the mark means "the survey did not reach", the opposite reading;
      * a course with no trees_lidar.json at all drew sparse OSM trees on every hole while the old
        course-level gate was False, so no hole carried the caveat and nothing said the canopy was thin.
    Both were latent only by coincidence of which course has which data: monarch-bay holds the corpus's
    only empty marker lists (holes 1, 17, 18) and has 0 OSM tree nodes, while micke-grove (532 nodes)
    and the-reserve (2462) have no empty-marker hole.

    `info["trees"]` is render_hole's own count of the OSM marks it drew -- tree nodes plus wood/scrub
    polygons plus tree rows -- read from what the renderer published rather than re-derived here.
    Tolerant of a missing key so a caller that hands in a stub layout (the honesty tests do) is not a
    KeyError.

    LAYOUTS is fully populated before any card is built, in both editions: build_deck and build_coach
    each render every hole first, then build the panels.
    """
    if _tree_markers(hole):
        return True
    info = (LAYOUTS.get(hole) or (None, {}))[1] or {}
    return bool(info.get("trees"))


def _book_draws_trees():
    """True when SOME hole in this book drew a tree mark.

    What makes a blank corridor worth a caveat: the same book drew trees elsewhere, so the blank is the
    survey's edge and not open ground. A book that draws none anywhere has nothing to distinguish, and
    marking all 18 holes would be noise rather than a caveat."""
    return any(_drew_trees(h) for h in config.HOLE_NUMS)


def cell_text(cells):
    """"2.7&times;3.4 m" for a measured source cell, or a range when the greens disagree. "" for none.

    ONE spelling of that figure, because it prints in TWO places -- the per-card label and the guide
    card's note -- and a second copy of it is exactly how "1 m" came to be published on six cards and
    in two lines of legal/03 with nothing able to check either against the other. `cells` is the list
    of [E-W, N-S] pairs render_green measured off the arrays it drew.

    A single rounded value collapses to one figure; anything else prints the range rather than a mean,
    because a mean is a number no green carries.
    """
    pairs = [c for c in (cells or []) if c]
    if not pairs:
        return ""
    def band(vals):
        got = sorted({f"{v:.1f}" for v in vals})
        return got[0] if len(got) == 1 else f"{got[0]}&ndash;{got[-1]}"
    return f"{band(c[0] for c in pairs)}&times;{band(c[1] for c in pairs)} m"


def green_honesty(hole, s):
    """The green label and the slope phrase, for BOTH editions.

    These three caveats are the honesty rule made concrete on a card:
      * a green rebuilt AFTER the flight -> say the data predates the rebuild;
      * a green fed by the coarser seamless mosaic -> say so, at the resolution it MEASURES;
      * a green the honesty gate refused to read -> print NO slope at all.
    They lived only inside hole_panel(), so the ENLARGED coach edition -- a book actually handed to
    a person -- printed none of them, and reported "0.0%" for a green the engine had declined to
    read. One rule, one implementation.

    The middle one used to read `GREEN &middot; 1 m data` on all six of monarch-bay's seamless greens,
    and the data is 2.72 m E-W x 3.43 m N-S -- 3DEP's seamless service is a multi-resolution mosaic and
    fetch_dem.py had simply typed "1 m" into the `source` field. Overstating a resolution 2.7x and
    3.4x, about 9x in area, in the one mark whose entire job is to say trust this green LESS. So the
    figure is the one render_green.source_lattice measured off that green's own array, and a green
    whose lattice could not be measured prints the caveat WITHOUT a number rather than a number the
    data does not support.

    Returns (label, slope_phrase). slope_phrase is None when no slope may be printed.
    """
    outdated = hole in set(config.COURSE.get("greens_possibly_outdated", []))
    coarse = 'seamless' in str(s.get('source', '')).lower()
    cell = cell_text([s.get('source_cell_m')])
    if outdated:
        label = 'GREEN &middot; pre-rebuild data'
    elif coarse:
        label = f'GREEN &middot; {cell} data' if cell else 'GREEN &middot; coarse data'
    else:
        label = 'GREEN'
    if s.get('insufficient'):
        return label, None
    # "overall" is doing real work, not decoration. The ONLY definition of a slope percentage in any
    # of the 15 books is the legend's "Black numbers = slope % there" -- per-cell slope, drawn by
    # render_green's slope labels -- and this figure is a DIFFERENT quantity: a least-squares plane over
    # the whole putting surface (render_green.green_summary). Measured over all 198 greens by parsing
    # the shipped SVGs, it prints below every black number on the same card on 134 of them, median
    # 0.5 pp over all 198 and worst 5.3 pp -- copper-valley 6 prints a footer of 0.7% beside black
    # numbers 6,7,8,8,10,10,10, on a green whose median local slope is 4.8% over the whole surface
    # (those seven labelled points median 8). The 4.8% belongs to the SURFACE, not to those labels: this
    # sentence hung it off "black numbers ... whose own", which reads as though the labels themselves
    # average 4.8 and so understates the very gap the example exists to show.
    # On 106 of the 170 greens that carry
    # no (faint) and no no-clear-fall qualifier, so nothing on the card warns the reader either. A
    # junior applying the card's only definition reads copper-valley 6 as dead flat. One word
    # distinguishes the two and adds no legend row -- card space is the binding constraint here, with
    # 1.19 px of clearance on monarch-bay's guide card -- and every figure above is re-derived from the
    # shipped SVGs by test_the_footer_percentage_is_not_read_as_the_legend_s_slope_number.
    tilt = (f'overall {s["tilt_pct"]}% <b>&#9888;</b>' if outdated
            else f'overall {s["tilt_pct"]}%')
    # A green whose plane fit and whose own arrows point opposite ways has no fall direction the data
    # supports, and render_green refuses to name one. Print the measured tilt, which is still true,
    # but NOT inside "feeds ..." -- "feeds no clear fall" would read as a direction.
    # The qualifier prints ONLY when it limits the read. It used to print on all 252 green footers --
    # 220 "(firm)" against 32 "(subtle)" -- so the common case spent a word to say nothing, and the
    # informative case was buried among them. Marking only the exception says strictly more, and it
    # bought back 35 two-line footers (43 -> 8 of 252 measured in-browser), which is card space on the
    # edition that was clipping its own licence line. It is also the only honest reading: a green
    # marked faint is one that a single slope describes badly -- render_green's gate is a plane-fit
    # ADEQUACY test, measured R^2 p05 0.61/median 0.90 on the greens it calls clear against 0.02/0.44
    # on the ones it calls faint -- so the mark says "one word will not carry this green, read the
    # arrows", and that is worth a mark; a green a single tilt does describe needs no adjective.
    # It does NOT say the direction is unreliable: see render_green.green_summary, where 1.2% stands
    # 24x above the worst tilt disagreement two surveys of one green have ever produced here.
    faint = ' (faint)' if s["conf"] == "faint" else ''
    if s["feeds"] == render_green.NO_CLEAR_FALL:
        # "no clear fall (faint)" would say the same thing twice, and the sentinel is the stronger of
        # the two -- the plane and the arrows disagree outright. No qualifier here.
        return label, f'<b>no clear fall</b> &middot; {tilt}'
    return label, f'feeds <b>{esc(s["feeds"])}</b>{faint} &middot; {tilt}'


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
    # Prefer the UNROUNDED figure where the producer records it. The 3 ft floor below is compared
    # against this value, and comparing a threshold against a number already rounded to 0.1 ft let
    # 2.956 ft pass a gate that forbids anything under 3 -- two cards printed "green 3 ft" for a
    # height the floor exists to suppress. Falls back to change_ft for records written before the
    # exact field existed, so an old hole_elev.json still prints rather than going blank.
    return {int(k): (v.get("change_ft_exact") if v.get("change_ft_exact") is not None
                     else v.get("change_ft"))
            for k, v in (rec.get("holes") or {}).items()
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
    disk. It reads the green POLYGON this pipeline reads; at the tee it reads the whole mapped tee ring
    where this pipeline reads the pad inside a 15 m window, so at the tee the comparison carries a
    region difference too, on 55 of 177 pads. That inflates the spread rather than hiding it, which
    makes every figure below an upper bound and this floor conservative -- the reason for trusting the
    spread, not a reason to lower the floor.

    MEASURED by `python3 tools/verify_elevation.py --all` on 2026-08-05, all 171 holes reached, 11
    courses, printed by that tool's own `_print_corpus`: across 171 holes the two disagree by a corpus
    median 0.067 ft, a corpus mean 0.201 ft and a worst 2.46 ft (philadelphia 5). The worst any single
    course medians is 0.62 ft (philadelphia), and the median of the 11 per-course medians is 0.069 ft --
    quoted to three decimals because at two they both read 0.07 and the whole point of naming both is
    that they are not one figure. Two holes exceed 2 ft and none exceeds 3. So a
    printed "green 2 ft above" would still sit inside the spread between two honest sources on those
    holes, and 22 of the 171 fall in the 2-4 ft band where that spread decides whether anything prints
    at all -- which is why the floor is not lowered to look more precise.

    A CORPUS MEDIAN AND A MEDIAN OF PER-COURSE MEDIANS ARE DIFFERENT FIGURES, and this paragraph
    presented one as the other: its "median 0.09 ft" was described as a median across 171 holes and was
    in fact the median of eleven per-course medians. Both are named above now, and both are printed by
    the tool. So was every other figure here re-derived, because the set that stood here reproduced
    nowhere: "mean 0.27 ft" was produced by NO CODE PATH in this project -- a grep found this sentence
    and nothing else -- and the worst hole, the worst per-course median and the counts over 2 and 3 ft
    were all measured before fd39647 moved five tee heights. `_print_corpus` exists so that a figure in
    this paragraph can never again be one nothing computes; graded by
    test_the_print_floors_justification_quotes_only_figures_this_project_can_produce.

    (Those figures were a median 0.80 ft and a worst 4.92 ft until both ends of the measurement were
    moved onto the feature polygons. The docstring quoted "worst 1.77 ft", which was the largest
    per-COURSE median, not the worst hole.)"""
    ft = HOLE_ELEV.get(hole)
    if ft is None or abs(ft) < 3:
        return ""
    # Half away from zero, not Python's round(). change_ft is stored to 0.1 ft, so 17 holes hold a value
    # ending in .5 -- and round() breaks those ties to the EVEN integer, which meant the same .5 went up
    # or down depending on the parity of the number beside it: -21.5 printed 22 while -24.5 printed 24.
    # One measurement, rounded two ways. The .5 is itself an artifact of the first rounding, so the tie is
    # arbitrary either way; what it must not be is arbitrary AND inconsistent.
    n = math.floor(abs(ft) + 0.5)
    return f'green <b>{n} ft {"above" if ft > 0 else "below"}</b>'


def carry_phrase(info):
    """"carry 172 / 212 / 245" -- the near edge of each bunker window a tee shot must clear.

    Plus the one thing the list could not say by ending: render_hole withdraws a carry wherever the sand
    leaves no room to land short of the green (see its `no_landing` block), and on five of the nine
    cards that fires on, an EARLIER carry survives -- so "carry 95 / 164" read as the whole story while a
    closer, uncarryable cluster went unnamed. The mark states that refusal and prints NO number, because
    both edges of the refused window are numbers a player would club against and be wrong: the near one
    invites the lay-up the rule just withdrew, and the far one is
    at or past the green front on four of the nine and short of it by up to 8.75 yd on the other five,
    while the sand COMPLEX behind it -- the greenside sand the carry filter drops, chained across any
    strip of grass narrower than CARRY_MERGE_GAP_YD -- means every one of the nine REACHES at or past
    the green front. The "all nine" belongs to the complex, not to the window edge; this sentence used
    to attach it to the edge, where it was false on five of the nine cards it named. Both figures are
    graded against the corpus by
    test_a_card_that_withholds_a_carry_says_the_sand_reaches_the_green.

    It needs no legend row and gets none. Measured in chrome-headless-shell under print media, adding a
    50-character clause to the carry legrow overflows monarch-bay's guide card by 9.4 px (pocket) and
    10.9 px (enlarged), clipping .abtxt -- the licence and warranty block this project has already
    clipped twice. The phrase makes no measurement claim, so there is nothing for a legend to define.
    """
    cs = info.get("carries") or []
    out = ("carry <b>" + " / ".join(str(a) for a, _b in cs) + "</b>") if cs else ""
    if info.get("sand_to_green"):
        out += (" &middot; " if out else "") + "<b>no carry: sand to the green</b>"
    return out


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


def depth_phrase(s):
    """"37yd deep" -- for BOTH editions. The bank caveat that goes with it is `bank_span`.

    A shared helper because this footer has diverged between the two editions three times
    (green_honesty, then the footer, then the playline) and each fix was a copy that reset the clock."""
    return f'{s["depth_yd"]}yd deep'


# The rounded yard at which a bank is worth a line on the card, for BOTH ends and BOTH editions.
# Named, and cross-checked against the test's own copy, because it is now applied in four places
# (two ends x two editions) and the suite carries an independent re-derivation of it.
#
# 1.0 rather than 0.5: 0.5 is where the bank starts moving the ROUNDED depth, but callippe 7's front
# run measures 0.5013 yd -- 0.13 inch from that boundary -- and the two implementations of this walk
# would then be pinned against each other across a cliff that thin. Measured since, and it is a
# stronger reason than the original: the engine's scanline rasteriser and the test's point-in-pixel
# one produce BIT-IDENTICAL masks on all 198 greens, so the two walks agree to 0.000000 yd at both
# ends and no floor is a flake. 1.0 is kept because it is the resolution the depth itself is printed
# at. The stated cost is the runs just under it going unannounced: front callippe 3 (0.854) and
# philadelphia 11 (0.767); back castlewood-valley 12 (0.995), copper-valley 15 (0.730),
# the-reserve 4 (0.685), copper-valley 13 (0.629), castlewood-hill 12 (0.620), merion 4 (0.588) and
# valley-hi 16 (0.542). castlewood-valley 12 at 0.995 is 0.005 yd under, which is deliberate rather
# than overlooked -- both implementations round it the same way, so it is a stable omission and not a
# coin toss.
BANK_NOTE_MIN_YD = 1.0


def bank_span(s):
    """The footer's bank caveat -- "front 4yd is bank &middot; back 3yd is bank" -- or "".

    ONE definition for both ends and both editions. The depth and the 5-yd ladder are measured from
    where the green polygon crosses the line of play, and at either end that crossing can sit on
    ground this same card's legend disowns: "over 10% is bank or bunker face, not putting surface".
    micke-grove 2 prints 22yd deep and rules rungs at 5/10/15/20 from a front edge with 5.33 yd of
    bank behind it; copper-valley 3 prints 30yd deep with 6.51 yd of bank at the BACK. Nothing on
    either card said so; the bank was visible only as colour, which the legend explains as steepness
    and not as "this is not green".

    THE BACK NOTE MATTERS MORE THAN THE FRONT ONE. A front bank overstates how much green lies in
    front of the pin; a back bank overstates how far back the pin can BE, so a junior clubs long into
    it -- and render_hole already names too-long as the dangerous direction. 21 of 198 greens carry a
    note (9 front, 14 back, 2 both), and the datum itself is deliberately not moved: see
    render_green.bank_run_yd for the three alternatives and what each measured.

    ITS OWN SPAN, and that is measured rather than styled. `.foot` is a wrapping flex row whose spans
    are `white-space: nowrap`, so a span wider than the row does not wrap -- it overflows and the trim
    line cuts it. Appending the back note to the depth span costs 19 characters, and the two cards that
    need BOTH notes have nowhere near that: copper-valley 6 carries the widest footer span in the
    corpus at 296.00 px of 323.00 available (27 px, about six characters) and bay-view 5 has 77. As its
    own span it wraps to a footer line instead, which the green sizing already reserves three of
    (render_green: `3 * 0.125 + 0.125` in) and which HEIGHT binds on 0 of 198 greens, so no green is
    resized. This is why the caveat is not simply concatenated onto depth_phrase.
    """
    notes = [f'{end} {int(round(yd))}yd is bank'
             for end in ("front", "back")
             for yd in (s.get(f"{end}_bank_yd") or 0.0,) if yd >= BANK_NOTE_MIN_YD]
    return f'<span>{" &middot; ".join(notes)}</span>' if notes else ''


def hole_panel(hole, sheet_label):
    row = HOLES[hole]
    par, hcp = row[0], row[1]
    gsvg, s = GREENS[hole]
    lsvg, i = LAYOUTS[hole]
    others = " / ".join(f"{lbl[:3]}{row[idx]}" for lbl, idx in config.OTHERS)
    grnlab, slope = green_honesty(hole, s)
    lead = (f'green <b>{esc(s["feeds"])}</b> &middot; no slope printed' if slope is None else slope)
    playline = playline_html(hole, i)          # shared with the enlarged edition -- see playline_html

    # Trees are found by height above ground in the point cloud, and where that layer is empty for a
    # hole render_hole falls back to OSM tree nodes -- so a hole that ends up drawing NOTHING is
    # indistinguishable on the map from a links hole that genuinely has none, while the guide card's
    # legend promises "trees". Said on the hole's own card, beside the bunker and water counts it
    # belongs with, because that is where the reader is looking at the blank corridor.
    # Keyed on what the hole DREW, not on the LiDAR list: see _drew_trees. Monarch Bay 1, 17 and 18 are
    # the case -- zero markers of either kind each, and exactly the three holes lidar_coverage.py
    # reports as centreline outside the point data. They are the only tree-less holes in the corpus, so
    # the blank is the survey's edge and not open ground.
    #
    # NOT on the guide card, where the other per-hole data caveats live: that panel is full. A single
    # extra row there overflowed monarch-bay's card by 20 px and clipped the legal notice and the
    # contact line, and trimming 33 characters of existing wording did not buy the line back. Derived
    # from what the renderer drew, so it cannot go stale and needs no extra pipeline stage -- which also
    # means it cannot prove WHY a hole is empty, hence "no tree data" rather than a coverage claim.
    notrees = ""
    if not _drew_trees(hole) and _book_draws_trees():
        notrees = ' &middot; <b>no tree data</b>'
    foot = (f'<span>{lead}</span>'
            f'<span>{depth_phrase(s)} &middot; {i["bunkers"]}B {i["waters"]}W{notrees}'
            f' &middot; {esc(others)}</span>'
            f'{bank_span(s)}')
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
    short name on one line and word-wrap only a genuinely long (>30 char) name.

    IT USED TO EMIT A LEADING EMPTY LINE. The greedy fill tests `len(cur) + len(w) + 1 <= 20` with
    `cur = ""` on the first word, so any first word of 20+ characters failed on the empty accumulator
    and the else branch appended it: _title_lines("Rancholascasitasmunicipal Golf Links Course")
    returned ['', 'Rancholascasitasmunicipal', 'Golf Links Course'], and _title_lines("A"*35) returned
    ['', 'AAAA...']. cover_panel() then drew an empty <tspan> and computed both
    `cy0 = 292 - (len(tlines)-1)*dyt/2` and `addr_y` off the inflated line count, shifting the title
    block and the address by half a line each. A blank leading line is not a wrap; a word longer than
    the fill width is its own line. No corpus name reaches this, so it was latent in shared code that
    both covers call."""
    raw = (raw or "").strip()
    if "—" in raw:
        return [p.strip() for p in raw.split("—") if p.strip()] or [raw]
    if len(raw) <= 30:
        return [raw]
    lines, cur = [], ""
    for w in raw.split():
        if not cur or len(cur) + len(w) + 1 <= 20:
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
    would be false for poppy-ridge, whose greens are blank; per-course detail is in legal/03.

    The two uses are decided from DIFFERENT evidence, because they are different claims and one of them
    went stale. Tracing geometry is checkable against the artifact: a NAIP-traced feature carries a
    `_digitized` tag naming NAIP. Using NAIP as a site reference is not in the geometry at all, so it
    can only come from the record, and sources.aerial is where it is recorded.

    Gating the whole thing on "does the word naip appear anywhere in sources" got the credit onto
    exactly the wrong course. valley-hi's sources.geometry still says it digitized hole 16's green from
    NAIP; that was true once, and then check_osm_bbox found its OSM bbox was ~46 m short at hole 16, a
    widened box recovered the REAL green 1.3 m away (33 vertices against the tracing's 17), and the
    tracing was dropped. Zero `_digitized` features remain there -- so the book credited NAIP for
    geometry it no longer contains. Meanwhile bay-view, which holds the corpus's only two NAIP-traced
    greens (ways 900000005 and 900000007), credited nothing at all, because its sources.geometry says
    only "OpenStreetMap contributors (ODbL)".

    Derived from the artifact, the prose cannot drift away from the book again.
    """
    traced = False
    for fn in ("osm_geom.json", "osm_course.json"):
        fp = os.path.join(config.COURSE_DIR, fn)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                els = json.load(fh).get("elements") or []
        except (OSError, ValueError):
            continue
        for e in els:
            if "naip" in str((e.get("tags") or {}).get("_digitized", "")).lower():
                traced = True
                break
        if traced:
            break
    referenced = "naip" in str((config.COURSE.get("sources") or {}).get("aerial") or "").lower()
    if not (traced or referenced):
        return ""
    return (' <b>USDA NAIP</b> aerial imagery (a U.S. Government work, public domain) was used as a '
            'mapping reference for this course.')


def _hole_runs(nums):
    """"10&ndash;18" for a contiguous run, "1, 9, 10&ndash;12" for a mixed list.

    Spelling every hole out cost LINES on the one card that has none to spare. Philadelphia's
    pre-rebuild caveat read "Holes 10, 11, 12, 13, 14, 15, 16, 17, 18" -- 168 rendered characters over
    three lines -- and that book's guide card had 1.19 px of clearance left in the pocket edition and
    9.63 px in the enlarged one, the tightest in the corpus. Collapsing the run to "Holes 10-18" is
    139 characters over two, which measures at +10.5 px pocket and +12.1 px enlarged, loses nothing,
    and turns the binding book back into an ordinary one.

    En dash, not hyphen, to match the thumb-index tabs.
    """
    nums = sorted(set(int(n) for n in nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j+1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if j == i else
                   f"{nums[i]}, {nums[j]}" if j == i + 1 else
                   f"{nums[i]}&ndash;{nums[j]}")
        i = j + 1
    return ", ".join(out)


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
    out = ""
    if label:
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
    # An ABSENT flight date used to return here, which also skipped the two caveats below -- and they
    # have nothing to do with the date. green_honesty() stamps "pre-rebuild data" and the measured
    # source-cell mark on
    # cards without consulting lidar_flown at all, so a course whose owner ran the pipeline but not
    # tools/lidar_dates.py shipped a book with nine cards marked "pre-rebuild data" and a warning
    # triangle, and nothing anywhere saying what that meant. That is precisely the failure the comment
    # below records these caveats being added to end. The date sentence is now the only conditional part.
    stale = sorted(config.COURSE.get("greens_possibly_outdated", []))
    if stale:
        holes = _hole_runs(stale)
        # holes comes from _hole_runs, which is integers and one &ndash; entity -- NOT user text, and
        # esc() would turn that entity's "&" into "&amp;" so the card printed the literal "16&ndash;18".
        out += ('  <div class="legrow"><span><b>&#9888; Holes ' + holes + '</b>: '
                '<b>rebuilt after</b> that survey, marked <b>&ldquo;pre-rebuild data&rdquo;</b> '
                '&mdash; shapes and tiers may have changed. A guide only; trust your own '
                'read.</span></div>\n')
    # The other caveat a card can carry needs the same treatment. Six of Monarch Bay's greens print a
    # coarse-data mark and the phrase appeared NOWHERE else in either edition -- a 12-year-old reading
    # it learns nothing, and the whole point of the label is to tell him to trust that green a little
    # less. Named per hole, exactly like the pre-rebuild wording.
    #
    # It said "the coarser 1 m national model", twice, and the model those greens came from is
    # 2.72 x 3.43 m -- so the figure is now cell_text() over what render_green MEASURED off those
    # arrays, the same one spelling the card label uses.
    #
    # It also has to say the flight date two rows above is not theirs. The seamless mosaic answered
    # here from a separately produced raster, and NOTHING in this build decodes an acquisition date for
    # it -- tools/lidar_dates.py reads LAZ point records, and there is no point cloud on this path. A
    # card that dates its LiDAR and then marks six greens coarse implies a contemporaneity nothing
    # establishes, which is arguably the larger of the two honesty gaps here. Measured in-browser
    # before it was written: the sentence stays three lines in BOTH editions and leaves monarch-bay's
    # guide card -- the tightest in the corpus -- at its existing 1.19 px (pocket) and 1.22 px
    # (enlarged) of clearance, with 40 and 22 characters still spare before a fourth line.
    coarse = sorted(h for h, (_svg, summ) in GREENS.items()
                    if 'seamless' in str(summ.get('source', '')).lower())
    if coarse:
        holes = _hole_runs(coarse)
        cell = cell_text([GREENS[h][1].get('source_cell_m') for h in coarse])
        # cell is entities from cell_text (&times;, &ndash;), NOT user text -- do not esc() it, for the
        # same reason `holes` is not esc()'d. A green whose lattice could not be measured prints the
        # caveat with no figure at all rather than a figure the data does not support.
        scale = ('the coarser <b>' + cell + '</b> national model, marked '
                 '<b>&ldquo;' + cell + ' data&rdquo;</b>') if cell else \
                ('the coarser national model, marked <b>&ldquo;coarse data&rdquo;</b>')
        out += ('  <div class="legrow"><span><b>Holes ' + holes + '</b> had no usable point '   # see above
                'cloud, so their greens use ' + scale + ', from a survey we cannot date '
                '&mdash; tilt is real, small tiers may smooth away.</span></div>\n')
    # And the same treatment for the TREE layer, which had none. Trees are found by height above
    # ground in the point cloud, and where that layer is empty for a hole render_hole draws whatever OSM
    # tree nodes lie in the corridor -- so a hole that ends up drawing NEITHER is indistinguishable on
    # the card from a hole that genuinely has none, while the legend promises "trees". Monarch Bay 1,
    # 17 and 18 are the case: zero marks of either kind each, and they are exactly the three holes
    # lidar_coverage.py reports as having centreline outside the point data. They are also the only
    # tree-less holes in the whole corpus, so the blank is the survey's edge, not open ground.
    #
    # Derived from what the renderer DREW rather than from a coverage report, so it cannot go stale
    # against a rebuild and needs no extra pipeline stage. That also means it cannot prove WHY a hole
    # is empty, so the wording claims only what is known: nothing was drawn here, do not read the blank
    # as clear. Suppressed when a book draws no trees anywhere -- then every hole is blank and the
    # sentence would be noise rather than a caveat.
    return out


def _no_tree_note():
    """Define "no tree data" in the ENLARGED edition, only in a book that prints it.

    It printed on 3 of monarch-bay's 40 enlarged cards with nothing in that book explaining it -- the
    same two-edition drift that left the enlarged guide card without the red ring, the grey ladder and
    the bunker/water key.

    Enlarged only, deliberately, and this is the honest scope: the POCKET edition defines it inline on
    the colour row, unconditionally, so 10 of the 12 pocket books carry six words for a mark they never
    print. Moving that to a conditional row of its own was tried and overflowed monarch-bay's guide
    card -- the book with 1.19 px of clearance and the only book that prints the mark. Six wasted words
    on ten cards is the cheaper error than a clipped licence line, so the pocket half stays inline.
    An earlier draft of this docstring claimed both editions were gated; they are not.

    THE COUNT IS 10, NOT 11, AND IT WAS PUBLISHED WRONG TWICE HERE. Measured over the built corpus: 11
    of the 12 pocket books carry the inline definition -- poppy-ridge's yardage guide card has no colour
    row and carries none -- and exactly 1 of those 11 (monarch-bay) PRINTS the mark. A book that prints
    it is not wasting the words on it, so the waste falls on ten books, and this paragraph named
    monarch-bay as that one book in the same breath as counting it among the eleven. Both figures are
    re-derived from the shipped books by
    test_the_wasted_words_note_counts_the_books_that_actually_waste_them.

    The wording matters more than most: an empty tree layer looks like open ground, and the mark says
    the survey did not reach -- the opposite reading. It is the one caveat whose misreading is the
    dangerous direction.
    """
    if not any(not _drew_trees(h) and _book_draws_trees() for h in config.HOLE_NUMS):
        return ''
    # ONE line: the enlarged guide card has 21.75 px of clearance and a row there costs 12.13 px per
    # line, so a two-line version overflows it. Same wording as the pocket edition's inline copy.
    return ('  <div class="legrow"><span><b>&ldquo;no tree data&rdquo;</b> = a survey gap, not open '
            'ground.</span></div>\n')


def _faint_note():
    """Define "(faint)" ONLY in a book that prints it, same as _no_fall_note.

    The word this replaced -- "(firm)" -- was defined NOWHERE, in either edition, while printing on
    every one of 252 green footers. The only hook a reader had for it was the turf sense, which is
    the wrong one: it is a statement about how well a single slope describes the green -- shallow
    fall, and one plane fitting it badly -- not about how the green is playing that morning. A
    qualifier a reader can only misread is worse than no qualifier, which is why the common case no
    longer prints one at all.

    Keyed off what was actually rendered, so a book whose every green has a clear fall does not carry
    a line explaining a mark it never uses.
    """
    # Keyed on what the card actually PRINTS, not on the internal value. green_honesty() suppresses the
    # mark on a NO_CLEAR_FALL green -- "no clear fall (faint)" would say the same thing twice -- and
    # micke-grove's hole 2 is both its only faint green AND its only no-clear-fall green. So this row
    # shipped on a book containing zero (faint) marks: a legend line explaining a symbol the reader will
    # never see, which is the clutter this function's docstring promises not to add. It also cost 10.5 px
    # on the tightest guide card in the corpus, which had 1.19 px of clearance left.
    if not any(sm.get("conf") == "faint" and sm.get("feeds") != render_green.NO_CLEAR_FALL
               for _svg, sm in GREENS.values()):
        return ''
    # Kept to ONE line on purpose, and to one LINE OF TYPE at that. The first draft ran four lines and
    # pushed the guide card past its own bounds, clipping the licence and contact lines on three books
    # -- the exact fault the coach edition was just fixed for. A caveat that costs the licence text is
    # not a caveat worth printing. The rewrite below is 79 characters against the 83 of the sentence it
    # replaced, and that margin is NOT slack: the wording is set by rendered WIDTH, not by character
    # count, and an 86-character version of the same sentence -- four characters longer than the one it
    # replaced -- wrapped to a third line and overflowed monarch-bay's enlarged guide card by 10.9 px,
    # clipping "info@lucasgreenbook.org" off the printed page. Measured in the browser: this row leaves
    # 1.22 px of headroom there. Re-measure before rewording it.
    return ('  <div class="legrow"><span><b>(faint)</b> after a feed = shallow fall, and no single '
            'slope fits &mdash; read the arrows.</span></div>\n')


def _no_fall_note():
    """Explain the no-clear-fall wording ONLY in a book that actually uses it.

    It is the vocabulary of one green in the corpus today, so putting it on every course's guide card
    would be clutter that describes nothing in that book. Keyed off what was actually rendered."""
    if not any(sm.get("feeds") == render_green.NO_CLEAR_FALL for _svg, sm in GREENS.values()):
        return ''
    return ('  <div class="legrow"><span><b>&ldquo;no clear fall&rdquo;</b> = too level for this data '
            'to name a side: the plane through the green and the arrows on it disagree, so none is '
            'claimed. The <b>measured</b> slope % still prints. Read that one with your own '
            'eyes.</span></div>\n')


def _heat_swatches():
    """The three colour-key rects, drawn the way the MAP draws its heat cells.

    Both halves matter and only the first used to be right. The fill is `render_green.heat_color`
    evaluated, never a copy, so a retuned ramp cannot leave a stale key behind -- but the map
    composites those cells at `render_green.HEAT_OPACITY` under its contours and arrows, and this
    legend drew them at full strength. So every swatch was a deeper, more saturated colour than any
    cell on the map it explains, and matching a patch to the key read one band too FLAT: measured in
    Rec.709 grey, a 2.5% map cell (225,202,134) sat nearest the FLAT swatch and a 5% cell
    (190,122,117) -- the reddest thing the card can draw -- sat nearest the 2.5% swatch. That is the
    same misread the ramp fix was written for, re-entering through the compositing.

    That 5% figure read one level higher in R here and in
    test_the_colour_legend_shows_the_colours_the_map_actually_uses, which was the whole population of
    records holding it. `255 - 0.62*(255 - 150)` is 189.90 for both the flat and the red stop, since
    both have R = 150, so the two rows of that table rounded one number two different ways. Both are
    now derived from heat_color and HEAT_OPACITY by that test and cannot drift again.

    Emitting the opacity keeps both sides on one number: change HEAT_OPACITY and the key follows the
    map. Do not replace it with the pre-composited RGB -- the point is that the key and the map are
    the same colour instruction, not two that currently agree.

    Both renderer names are called OUTSIDE the f-string on purpose. test_the_steepness_colour... reads
    generate.py through _code_only(), which strips string literals, so a heat_color() call interpolated
    inside the format string is invisible to the guard that this legend derives its swatches rather than
    hardcoding them -- and that guard has already been defeated twice elsewhere in this project by a
    name that was present but not in code position.
    """
    op = render_green.HEAT_OPACITY
    cols = [render_green.heat_color(pct) for pct in (0.0, 2.5, 5.0)]
    return "".join(f'<rect x="{x}" y="3" width="7" height="9" fill="{c}" opacity="{op}"/>'
                   for x, c in zip((2, 10, 18), cols))


def guide_panel():
    return '''<div class="panel guide">
  <div class="gtitle">How to read a green</div>
  <div class="legrow"><svg width="28" height="14"><line x1="2" y1="7" x2="18" y2="7" stroke="#15271b" stroke-width="1.3"/><polygon points="18,7 14,4.5 14,9.5" fill="#15271b"/></svg>
    <span><b>Arrows</b> point downhill, the ball&rsquo;s roll. Longer = steeper
    <b>on that green</b>.</span></div>
  <div class="legrow"><span><b>Black numbers</b> = slope % there; over <b>10%</b> is bank or bunker face,
    not putting surface, so it is coloured but not numbered. <b>Grey numbers</b> = yd from the front edge
    <b>down the middle</b>. The <b>red ring</b> is the green's middle, <b>not the pin</b>.</span></div>
  <div class="legrow"><svg width="28" height="14"><path d="M2,11 Q9,3 26,6" stroke="#3c5a34" fill="none" stroke-width="0.9"/><path d="M2,13 Q11,7 26,11" stroke="#3c5a34" fill="none" stroke-width="0.9"/></svg>
    <span><b>Contours</b> join equal height (15&nbsp;cm each). Close = steep. Bar = 5&nbsp;yd.</span></div>
  <div class="legrow"><svg width="28" height="14">''' + _heat_swatches() + '''</svg>
    <span><b>Colour</b> = steepness: green flat &rarr; amber &rarr; red (&ge;5%);
    steeper is always <b>darker</b>, so it reads in black and white too.
    <b>&ldquo;no tree data&rdquo;</b> = a survey gap, not open ground.</span></div>
  <div class="legrow"><span><b>HOLE</b> map: bunkers (tan), water (blue), <b>trees</b>. <b>Left</b> = to green (straight), <b>right</b> = from the tee (walked): on a par 4 or 5 they <b>need not</b> add up.</span></div>
  <div class="legrow"><span><b>GREEN</b> is turned so your <b>approach is at the bottom</b>; small <b>N</b> = true north. "feeds" = the low side putts run toward.</span></div>
''' + _faint_note() + _no_fall_note() + '''
  <div class="legrow"><span><b>green N ft above/below</b> = <b>measured</b> height vs the back tee.
    <b>Not</b> a yardage adjustment &mdash; club depends on your ball flight, so <b>you</b>
    decide.</span></div>
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
      product was used, copied, referenced or reverse-engineered</b>, and this book names no such
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
        # [:12], not [:7]. "Championship" is the only tee name in the corpus over 7 characters and it
        # printed as "Champio" in merion's rating/slope table while the same book spells it in full 19
        # other times. Measured in-browser: the column holds 12 characters at this size with the table
        # still inside the card.
        f'<tr><td>{esc(t["name"][:12])}'
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


def _dedication_sharing():
    """The dedication's own two sentences about passing the book on -- conditional, like sharing_line().

    THE BACK COVER OF A PERSONAL-USE BOOK INVITED REDISTRIBUTION TWICE AND FORBADE IT ONCE, and it
    shipped that way. Read out of courses/poppy-ridge-golf-course/greenbook.html in printed order:
    "It's a small personal contribution to junior golf, FREE TO USE AND SHARE. ... Play well, read
    true, and PASS IT ON. ... THIS COPY IS FOR PERSONAL USE ONLY -- PLEASE DO NOT SHARE OR REDISTRIBUTE
    IT". Page 1 of the same book carries "PERSONAL USE ONLY - PLEASE DO NOT SHARE" from _cover_badge().
    So the one card a reader keeps granted the permission the same card, the cover and legal/03 all
    withhold -- verbatim the failure sharing_line()'s docstring says it exists to end.

    It got past the test written to hold that line: the shipped guard asserts the absence of the
    LITERAL "free to share, not for sale", which is the licence sentence's spelling, and the dedication
    worded the same permission its own way.

    The warmth is not the defect and is not removed: a book that may be shared still says so, in these
    exact words. What changes on the book that may not be is the permission, and the reason stays where
    it belongs -- the licence line at the foot of this same card, which says why.

    ONE LINE OF TYPE more than the sentence it replaces, and that is measured, not estimated. In
    chrome-headless-shell under print media on the shipped poppy-ridge back cover, this wording moves
    the gap between the QR block and the .dcopy licence line from 16.22 px to 9.33 px and the crest's
    top clearance from 71.20 to 64.31. The tightest element on that card is unmoved at 2.00 px from the
    trim (its page number); no text on it comes nearer. A two-line-longer draft leaves 2.44 px of that
    QR-to-licence gap, so there is one line here and no more.
    """
    if DISTRIBUTABLE:
        return ('''<p>It is <b>not for sale</b>. It&rsquo;s a small personal contribution to junior golf,
      free to use and share.</p>
    <p>Play well, read true, and pass it on.</p>''')
    return ('''<p>It is <b>not for sale</b>. It&rsquo;s a small personal contribution to junior golf,
      <b>for your own use</b>.</p>
    <p>Play well, read true &mdash; and please keep this copy to yourself; the note below says
      why.</p>''')


def dedication_panel():
    """The LAST card: the dedication, which prints upright as the back cover.

    NOT a legend. This was called legend_panel() while building `<div class="panel dedic">` -- "For
    every junior golfer", "Crafted by Lucas Wu", the copyright and licence line -- and the book's
    actual legend card is guide_panel(). pad_to_leaves() and is_upright_back() both already call this
    card "the dedication", and its enlarged counterpart is coach_dedic_card(), so the name was the one
    thing still pointing a reader at the wrong function. The fossil had a measurable trace: `.legend
    ol` and `.legend li` shipped in the stylesheet of all 12 pocket books and no element in any book
    carried class="legend".
    """
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
    # ONE f-string for the whole card. Splicing the two conditional sentences in with `+` broke it
    # once already: the segment holding {qr} stopped being an f-string, and all 12 pocket books printed
    # the literal text "{qr}" where the Instagram code and its caption belong. Bound to locals instead.
    share = _dedication_sharing()
    licence = sharing_line()
    return f'''<div class="panel dedic">
  <div class="dcrest">{flag}</div>
  <div class="dtitle">For every junior golfer</div>
  <div class="dtext">
    <p>A good green book shouldn&rsquo;t cost more than the round. Every kid who tees it
      up deserves the same honest read as anyone else &mdash; so I built this one and give
      it away.</p>
    {share}
  </div>
  <div class="drule"></div>
  <div class="dsign">Crafted by <b>Lucas Wu</b></div>
  <div class="dweb"><div class="dwebtag">VISIT</div><div class="dweburl">lucasgreenbook.org</div></div>
  {qr}
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. {licence}</div>
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


def write_book(out, html):
    """Write a finished book into courses/<slug>/ the way everything else there writes: stage, rename, sweep.

    THE TWO BOOKS WERE THE ONLY ARTIFACTS THIS PROJECT WROTE UNDER courses/<slug>/ IN PLACE. Both
    writers were

        with open(out, "w", encoding="utf-8") as _f: _f.write(doc(sheets_html, config.BRAND))

    and Python evaluates open() FIRST, so the previous good book was truncated to 0 bytes before doc()
    had been called at all -- and then stayed incomplete for the whole 4.24-6.80 MB write, which is many
    buffer flushes. ENOSPC, SIGKILL, a closed lid or a power loss anywhere in that window leaves a
    truncated or empty greenbook.html and the last good one is gone. courses/ is gitignored: no copy in
    history, none on a remote, none anywhere.

    THE REMEDY LOOP THEN CERTIFIES THE WRECK, which is what makes this worse than lost work.
    tools/export_pdf.py --check reports WRONG_SOURCE and prints "Re-run: python3 tools/export_pdf.py";
    Chromium parses truncated HTML happily and prints whatever sheets it got; write_stamp records the
    wreck's html digest beside the short PDF's; the next --check prints "all N PDF(s) match the HTML
    they were exported from". The sheets a torn write loses are the LAST ones, and the last card is the
    back cover -- where the copyright, trademark and licence block lives. So a book missing its licence
    passes every gate in the pipeline.

    export_pdf.py makes this exact argument for the PDF it prints FROM this file -- "Playwright's writer
    opens its destination `wb` ... writing in place truncates a good book first: interrupt it and the
    printable artifact is gone" -- and stages for it. The writer feeding it did not. Same three lines as
    fetch_trees.write_layer, with the stage removed in a `finally` either way.

    DOT-PREFIXED, like export_pdf.staged_pdf and surface_io.staged_names, for the reason export_pdf
    states: the suite's `courses/*/*` read-only snapshot exempts a leading dot as OS litter or a stage,
    and glob (which is how every tool here enumerates books) does not match one either. A leftover
    `greenbook.html.part` would read as course data nothing has ever seen; `.greenbook.html.part` reads
    as what it is.

    `html` is a finished string, not a callable, so the document is rendered BEFORE anything is opened:
    a failure while building it cannot touch the destination at all.

    encoding="utf-8" explicitly. Without it Python uses the platform default, while the document it is
    writing declares <meta charset="utf-8"> -- and every book contains 18 en-dashes (U+2013) from the
    thumb-index tabs, generated unconditionally by _deck_thirds. On a cp1252 machine those become byte
    0x96, which utf-8 cannot decode, so all 18 tabs render as replacement characters; under an ASCII
    locale the build dies with UnicodeEncodeError. Declaring one encoding and writing another is a bug
    that cannot reproduce on the author's machine.
    """
    tmp = os.path.join(os.path.dirname(out), f".{os.path.basename(out)}.part")
    try:
        with open(tmp, "w", encoding="utf-8") as _f:
            _f.write(html)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):     # a no-op once the rename above has happened
            os.remove(tmp)
    return out


def build_deck():
    """(panels, n_leading, n_holes) -- the flat, ordered card deck for this course.

    Extracted from main() because it had a SECOND implementation. The iOS reader in the companion repo
    needs the same deck to map a hole to a page, and app/tools/course_worker.py hand-rewrote this loop
    -- then drifted from it. It shipped the tab labels this engine deliberately abandoned ("Front" for
    holes 1-6, when "Front" means 1-9 in golf and the same book's scorecard splits Out 1-9 / In 10-18),
    a notes panel headed "Notes 1-9" over all eighteen holes, and `range(1, 19)` where the engine had
    already moved to config.HOLE_NUMS so a nine-hole course works.

    Worse than the wrong labels: the app derives its hole-to-page map from its own copy of this list, so
    any panel added here shifts the app's mapping silently and the reader shows a green beside the wrong
    hole. One deck, one implementation, so that cannot happen.

    Renders the greens and layouts as a side effect, into GREENS/LAYOUTS, exactly as before -- the panel
    builders read those module dicts.
    """
    yardage = (config.BUILD_MODE == "yardage")
    if not yardage:
        for h in config.HOLE_NUMS:
            GREENS[h] = render_green.render(h, tournament=True)  # single conforming book
            LAYOUTS[h] = render_hole.render_hole(h, HOLES)
    # flat, ordered deck of cards (cut-and-stack, top-bound)
    leading = [cover_panel(), yardage_guide_panel() if yardage else guide_panel()]
    # The corner tab is a THUMB INDEX -- which third of the cut deck this card is in -- and it used to
    # read "Front" / "Mid" / "Finish". "Front" means holes 1-9 in golf, universally, and it was being
    # used here for 1-6 while the SAME BOOK's scorecard splits Out 1-9 / In 10-18. So one book grouped
    # its own holes two ways and a junior looking under "Front" for hole 8 found it tabbed "Mid".
    # Literal ranges cannot collide with a golf term, state the grouping instead of naming it, and make
    # the uneven split visible rather than surprising.
    thirds = _deck_thirds(config.HOLE_NUMS)
    holes = []
    for h in config.HOLE_NUMS:
        grp = next(lbl for lo, hi, lbl in thirds if lo <= h <= hi)
        holes.append(yardage_hole_panel(h, grp) if yardage else hole_panel(h, grp))
    trailing = [scorecard_panel(), tees_panel(),
                notes_panel(f"Notes {config.HOLE_NUMS[0]}-{config.HOLE_NUMS[-1]}"
                            if config.NHOLES <= 18 else "Notes",
                            config.HOLE_NUMS), dedication_panel()]
    return leading + holes + trailing, len(leading), len(holes)


def main():
    panels, _n_leading, _n_holes = build_deck()

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
  /* #767676 = 4.54:1 on white, the contrast this project adopted for .foot/.yalt/.playline.
     .minilab was #9a9a9a (2.81:1) and it carries the two marks that tell a junior to trust a
     green LESS -- the pre-rebuild mark and the measured-source-cell mark. Their wording is
     deliberately NOT quoted here: this comment is embedded in every book's stylesheet, so a copy of a
     label in it goes stale in 15 shipped artifacts at once, which is what happened when the coarse
     mark stopped naming a resolution tier and started naming a measurement (see green_honesty).
     So the least legible text
     on the card was the text that most needed reading. .dcopy (the back-cover licence line) was
     the same grey; .gsmall sat at 4.48:1, marginally under. Darkening changes no metrics, so no
     card's layout moves. */
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 5.5pt; color: #767676; letter-spacing: .5px; z-index: 2; }}
  /* flex-wrap + nowrap spans: the footer is too long to fit one line on a 5-tee course (three
     "other" tees make the right span 44 characters), and without these it broke MID-PHRASE --
     monarch-bay orphaned "3.1%" on its own line and split "Gol403 / Gre338 /" from "Red288".
     The same fault the playline had. Wrapping BETWEEN the two spans is fine; inside one is not. */
  /* #999 was 2.85:1 on white -- below the 4.5:1 needed at this size, and this row carries the
     feed direction, the tilt %, the green depth and the bunker count. Secondary, not faint. */
  .foot {{ display: flex; flex-wrap: wrap; justify-content: space-between; font-size: 7.5pt;
           color: #767676; margin-top: 1px; }}
  .foot span {{ white-space: nowrap; }}
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
  .dcopy {{ position: absolute; bottom: 0.14in; left: 0.3in; right: 0.3in; font-size: 6pt; color: #767676; letter-spacing: .2px; line-height: 1.3; }}
  .dqr {{ margin-top: 10px; }}
  .dqr img {{ width: 0.92in; height: auto; display: block; margin: 0 auto; }}
  .dqrcap {{ font-size: 6.4pt; color: #767676; margin-top: 3px; letter-spacing: .2px; }}
  .dqrcap b {{ color: #c13584; }}

  .gtitle, .cardtitle {{ font-size: 11pt; font-weight: 800; color: #2b6a2b;
    border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; margin-bottom: 3px; }}
  .legrow {{ display: flex; gap: 4px; align-items: flex-start; font-size: 6.6pt;
    line-height: 1.2; margin-bottom: 3px; }}
  .legrow svg {{ flex: none; }}
  .gsub {{ font-size: 7.6pt; color: #444; margin-bottom: 3px; }}
  .guide ul {{ margin: 0; padding-left: 14px; font-size: 7.7pt; line-height: 1.28; }}
  .guide li {{ margin-bottom: 3px; }}
  .gsmall {{ font-size: 6.7pt; color: #767676; margin-top: auto; padding-top: 3px; }}

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
    # Staged and renamed -- see write_book(), which carries the encoding note that used to live here
    # and the reason a book may not be written over itself.
    write_book(out, doc(sheets_html, config.BRAND))
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
    """The enlarged edition's page 1 -- including the do-not-share mark when the book may not be shared.

    IT HAD NO PATH TO THAT MARK AT ALL. cover_panel() reads _cover_badge(); this one hardcoded
    "ENLARGED PRACTICE EDITION" with no DISTRIBUTABLE branch, so an enlarged book whose About text and
    back cover both say "personal use only" said nothing on the page anyone receiving the PDF sees
    first -- which is the whole argument _cover_badge()'s own docstring makes for putting it there.
    build_coach refuses only BUILD_MODE == "yardage", and DISTRIBUTABLE is False for an unrecognised
    build_mode too, so `"build_mode": "yardge"` reaches this cover.

    The mark is taken FROM _cover_badge() rather than spelled again, so the two covers cannot drift.
    Its Rule 4.3 half deliberately does NOT come across: this edition is printed past the scale cap on
    purpose and its own guide card says so, so the badge here stays the enlarged-practice one.
    """
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
    # Its own line UNDER the enlarged badge, at y=474 -- the exact baseline the pocket cover gives its
    # own lowest line. Measured in chrome-headless-shell under print media by injecting this cover into
    # a built enlarged deck's page 1 (no enlarged deck in the corpus is non-distributable, so there is
    # no artifact to read it off): 180.20 px wide of the 336 px card, 77.90 px clear each side, and its
    # bottom 3.80 px above the inner gold frame at 459.84 -- the same 3.80 px the pocket cover's
    # copyright line sits at. At y=476 it was 1.88 px, tighter than anything else either cover prints.
    # It prints only on a book that may not be shared, so the three distributed enlarged decks are
    # byte-identical either way.
    share_mark = ""
    if not DISTRIBUTABLE:
        b = _cover_badge()
        share_mark = ('<text x="175" y="474" text-anchor="middle" '
                      'font-family="Helvetica,Arial,sans-serif" font-size="6.4" letter-spacing="1.0" '
                      f'fill="{b["badge_fill"]}">{b["badge_text"]}</text>')
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
  <text x="175" y="458" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="6.6" letter-spacing="1.0" fill="#dcc27f">ENLARGED PRACTICE EDITION</text>{share_mark}
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
  <div class="foot"><span>{i['bunkers']} bunkers &middot; {i['waters']} water{'' if (_drew_trees(hole) or not _book_draws_trees()) else ' &middot; <b>no tree data</b>'}</span><span>course layout</span></div>
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
    <span>{depth_phrase(s)}</span>{bank_span(s)}</div>
</div>'''

def coach_about_card():
    return '''<div class="panel guide">
  <div class="gtitle">Enlarged edition</div>
  <div class="legrow"><span>Each hole = <b>two big cards</b>: the course map, then the green on its
    <b>reverse</b>.</span></div>
  <div class="legrow"><span><b>Arrows</b> downhill = the ball&rsquo;s roll; longer = steeper
    <b>on that green</b>.
    <b>Contours</b> join equal height, <b>15&nbsp;cm each</b>; <b>close = steep</b>. <b>Colour</b>: green
    flat &rarr; amber &rarr; red (&ge;5%). Small <b>N</b> = north. "feeds" = the low side putts run
    toward.</span></div>
  <div class="legrow"><span><b>Black numbers</b> = slope % there; over <b>10%</b> is bank or bunker face,
    not putting surface: coloured, not numbered. <b>Grey numbers</b> = yd from the <b>front edge</b>, down
    the middle. The <b>red ring</b> is the green's middle, <b>not the pin</b>.</span></div>
  <div class="legrow"><span><b>HOLE</b> map: bunkers (tan), water (blue), <b>trees</b>. <b>Left</b> = to
    green (straight), <b>right</b> = from the tee (walked): on a par 4 or 5 they <b>need not</b> add
    up.</span></div>
''' + _faint_note() + _no_fall_note() + _no_tree_note() + '''
  <div class="legrow"><span>Printed <b>larger than tournament scale</b>: a <b>practice aid, NOT a
    conforming competition book under Rule&nbsp;4.3</b>. Use the pocket edition in competition.</span></div>
  <div class="legrow"><span><b>green N ft above/below</b> = measured height vs the back tee, <b>not</b> a
    yardage adjustment. <b>carry N</b> = yd from the back tee to where fairway sand starts; it can run
    past N. <b>Print in colour</b> &mdash; bunkers vanish in black &amp; white.</span></div>
''' + _flown_line() + '''  <div class="abt">
    <div class="abthead">About &amp; legal</div>
    <div class="abtxt">A free, <b>independent</b> green book. Hole &amp; green shapes, and the <b>carry</b>
      distances measured from them, are a
      Produced Work from <b>OpenStreetMap</b> data (&copy;&nbsp;OpenStreetMap contributors, <b>ODbL&nbsp;1.0</b>, osm.org/copyright);
      slope, contours, arrows &amp; <b>elevation change</b> are computed by the maker from
      <b>public-domain USGS&nbsp;3DEP</b> elevation (a U.S. Government work); par,
      yardage &amp; handicap (<b>HCP</b> = men&rsquo;s stroke index) are <b>facts</b> from the published scorecard.''' + _naip_line() + ''' Every map is <b>independently created</b>: <b>no proprietary data, image, symbol
      set, layout or trade dress of any commercial green-reading product was used, copied, referenced or reverse-engineered</b>, and this book is no substitute for any product. Built <b>entirely from remote public data, without entering any club or course</b>.
      Not affiliated with, endorsed or sponsored by any course, club, association or product; names &amp;
      trademarks belong to their owners and identify the course only &mdash; contact the maker for removal.
      Provided <b>free and as-is, with no warranty of any kind</b> (accuracy, fitness or rules
      conformance): maps show general tilt &amp; tiers, not exact break, and may contain errors &mdash;
      <b>use at your own risk and trust your own read</b>. To the fullest extent permitted by law the
      maker is not liable for any loss, penalty, damage, ruling or disqualification from use of this book.
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
  <div class="dcopy">Lucas Green Book&trade; &middot; &copy; 2026 Lucas Wu. Practice aid. ''' + sharing_line() + '''</div>
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
            # the SAME rule the pocket book uses, not a second copy of it: green_honesty, the footer
            # and the playline each drifted between these two code paths before being shared. So did
            # the LEAF PADDING above, which was the last rule still written twice -- the inline copy
            # APPENDED the blank, which pad_to_leaves()' docstring says lands the dedication a leaf
            # early and ends the book on a blank page. Dead only because this deck's card count is
            # always even; the comment claiming one rule sat directly under the second copy of it.
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
  .minilab {{ position: absolute; top: 0; left: 1px; font-size: 7pt; color: #767676; letter-spacing: .5px; z-index: 2; }}
  /* flex-wrap + nowrap spans: the footer is too long to fit one line on a 5-tee course (three
     "other" tees make the right span 44 characters), and without these it broke MID-PHRASE --
     monarch-bay orphaned "3.1%" on its own line and split "Gol403 / Gre338 /" from "Red288".
     The same fault the playline had. Wrapping BETWEEN the two spans is fine; inside one is not. */
  .foot {{ display: flex; flex-wrap: wrap; justify-content: space-between; font-size: 8pt;
           color: #767676; margin-top: 1px; }}
  .foot span {{ white-space: nowrap; }}
  .playline {{ font-size: 8pt; color: #666; margin-top: 0.5px; white-space: nowrap; overflow: hidden; }}
  .cover {{ position: relative; overflow: hidden; padding: 0; }}
  .gtitle, .cardtitle {{ font-size: 12pt; font-weight: 800; color: #2b6a2b; border-bottom: 2px solid #2b6a2b; padding-bottom: 2px; margin-bottom: 4px; }}
  /* 7pt, down from 8. The enlarged edition's premise is that the GREEN MAPS read at arm's length,
     not that the reference legend does -- the pocket book's is 6.6pt. Buying that back is what
     paid for the six caveats this card was missing, and for its About & legal block to stop
     overflowing: at 8pt it clipped the licence line, the warranty disclaimer and the contact
     address off two of the three enlarged books. 7.0 is the largest size the full card fits at. */
  /* margin-bottom 3px, the pocket book's own value: this is row SPACING, not type size, so the 7pt
     legend still reads at arm's length -- which is the whole reason this edition exists. It buys
     the ~16px the restored trespass defence and liability cap need on the two tightest cards. A
     defence that is not printed is worth nothing, however large the type it would have been set in. */
  .legrow {{ display: flex; gap: 4px; align-items: flex-start; font-size: 7pt; line-height: 1.3; margin-bottom: 2px; }}
  .abt {{ margin-top: 4px; border-top: 1.2px solid #cdb96a; padding-top: 3px; }}
  .abthead {{ font-size: 8pt; font-weight: 800; color: #2b6a2b; margin-bottom: 1px; }}
  /* The legal block sat at 6.6pt against the pocket book's 5.15pt, and it ran OFF the card: its last
     lines were sliced through by the trim line, so a cut sheet lost them. This edition exists to make the
     MAPS and the LEGENDS readable for older eyes; enlarging the small print too is what did not fit.
     5.75pt still beats the pocket book's 5.15pt by 12% and leaves the card whole. */
  /* line-height 1.22 -> 1.14 on the small print only. 16 lines x 0.08 x 5.75pt buys back the one
     line the restored Rule 4.3 ruling disclaimer, the trade-dress lead-in and the no-substitute
     clause cost on monarch-bay -- the binding book, which had 9.31 px of clearance against a
     9.35 px line. TYPE SIZE is untouched at 5.75pt, still larger than the pocket book's 5.15,
     which is the reason this edition exists. Leading on legal small print is the cheapest thing
     on this card, and a defence that is not printed is worth nothing however well led. */
  .abtxt {{ font-size: 5.75pt; line-height: 1.14; color: #6b6b6b; text-align: justify; }}
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
  .dcopy {{ position: absolute; bottom: 0.16in; left: 0.3in; right: 0.3in; font-size: 7pt; color: #767676; letter-spacing: .2px; line-height: 1.3; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
  td {{ border: 1px solid #ddd; padding: 1px 3px; text-align: center; }}
  .th td {{ background: #2b6a2b; color: #fff; font-weight: 700; }}
  .sum td {{ background: #eef4ee; font-weight: 700; }}
  .tot td {{ background: #dcebdc; }}
  .tt td {{ font-size: 8.5pt; }}
  .gsmall {{ font-size: 7pt; color: #767676; margin-top: auto; padding-top: 3px; }}
  @media screen {{ body {{ background: #666; padding: 16px; }}
    .sheet {{ background: #fff; margin: 0 auto 20px; box-shadow: 0 2px 12px rgba(0,0,0,.4); }} }}'''
    html = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<title>Enlarged Edition &mdash; {esc(COURSE)}</title><style>{css}</style>'
            f'</head><body>{"".join(pages)}</body></html>')
    out = os.path.join(COURSE_DIR, "greenbook_coach.html")
    write_book(out, html)      # staged and renamed, exactly like the pocket book -- see write_book()
    print(f"Wrote {out} (ENLARGED edition for {coach_name}) "
          f"-> {len(cards)} cards, {len(pages)} PDF pages, {config.PER}/sheet duplex "
          f"(same layout as pocket book; each hole = 2 cards: map front / green back)")

if __name__ == "__main__":
    if os.environ.get("COACH"):
        build_coach(os.environ.get("COACH_NAME", ""))
    else:
        main()
