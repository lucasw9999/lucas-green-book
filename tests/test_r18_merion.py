#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
A hazard can be omitted by a CACHE rather than by the code that draws it, and nothing graded that.

THE DEFECT, as it shipped. `natural=wetland` entered `fetch_osm.main()`'s course query, `census`
learned to bucket it and `render_hole`'s water selector learned to draw it -- and merion's
`osm_course.json` had been fetched BEFORE any of that, so the class was absent from the only file the
cards are drawn from. The engine was correct and the card was still wrong: a 151 m2 `wetland=marsh`
way, measured 2.48 m from the mapped green polygon it sits beside and 10.5 m from the played length of
one hole, was drawn on no card and counted in no footer, and the cards it reaches printed `0W` over
it. The book's second rule is never omit a hazard the golfer can reach, and every existing arm of the
suite was green: a corpus sweep can only measure the wetlands the corpus HOLDS, so a wetland missing
from the cache is invisible to it by construction.

WHAT THIS FILE GRADES, and why it is not the sweep that already exists.
`test_r16_wetland.py::test_a_wetland_the_played_line_reaches_is_never_printed_as_no_hazard` asserts
that a reachable wetland is counted and filled. That is the right invariant and it cannot see this
defect twice over: it is satisfied vacuously by a course whose cache holds no wetland, and where a
card has other wetland it is satisfied by that other wetland -- `wetlands >= len(near)` does not ask
WHICH polygon supplied the number. So the arms here ask the two questions it does not:

  * is the class in the file the cards are drawn from AT ALL, on a course whose ground has it
    (`test_merions_hand_mapped_marsh_is_in_the_cache_its_cards_are_drawn_from`); and
  * is that polygon the REASON its cards mark a hazard -- withdrawing it must take the card's wetland
    count down and the grey ink off every card it reaches, leave every card it is nowhere near
    untouched, and move a card's number and its map together or not at all
    (`test_removing_the_marsh_takes_down_the_water_on_exactly_the_cards_it_reaches`).

The second is a mutation test and it is what makes the first honest. A card that marks a hazard it
always had would satisfy any presence check; requiring the number and the ink to MOVE when the
polygon is withdrawn is what ties them to this hazard rather than to the neighbourhood.

THE CLASS IS NO LONGER DRAWN AS WATER, and this file was re-pointed rather than relaxed. When it was
written, a drawn wetland took the pond blue and the footer's W, so both arms measured `info["waters"]`
and the water fill. That ink was a false description: callippe Preserve holds ONE `natural=water`
polygon and its shipped book printed 39 W across 18 cards, with 2,309 of its 7,507 tree markers
standing inside what the card called a pond. Wetland now takes the not-water grey
(`render_hole.PENALTY_FILL`) and is counted under `info["wetlands"]`, and the footer names the class in
words instead of adding to the W. Every assertion below asserts what it always did -- a reachable marsh
is DRAWN and is COUNTED, and the number and the map move together -- against the ink and the key the
class actually uses. Nothing was weakened: a marsh inked blue again would fail both arms for a missing
grey fill, and each arm additionally refuses to run if the two inks are ever the same hex.
The name of the mutation arm still says "water" because it is what a reader searching git for this
defect will look for; its docstring and its assertions say wetland.

NO HOLE NUMBER, COUNT OR DISTANCE IS TYPED IN ANY ASSERTION HERE. Which holes the marsh reaches is
derived from the OSM centrelines and the mapped wetland polygon at test time, against the renderer's
own `CORRIDOR_M['water']`, because a hand-typed hole list goes stale the moment the geometry moves --
this repo has already paid for several. Every figure quoted in this docstring is a plan measurement off
the OSM centrelines and the mapped OSM polygons in merion's own cache; nothing here reads elevation,
and no number here comes from the scorecard.

WHAT THE MEASUREMENT SAYS ABOUT REACH, because "inside the corridor" is not one number.
`render_hole`'s water selector is an OR: mostly-inside-the-corridor (a boundary-length fraction) or
reaching the PLAYED length at all. Nearest-edge distance measured WITH the end caps -- the half-disc
behind the tee and past the green -- is a third thing again, and it is the loosest of the three. On
this marsh the three disagree, and the disagreement is load-bearing here: the played-length metric
decides which cards MUST gain water, and the end-cap metric bounds which cards must not move at all.

HOLE 15 IS THE CASE THAT SITS BETWEEN THEM, and it is NOT GUARDED BY THIS FILE. Measured from the OSM
geometry in merion's cache: the marsh's nearest edge is **34.57 m** from hole 15's drawn centreline
with the end caps included -- which is INSIDE the 45 m water corridor -- and **265.91 m** from its
PLAYED length. Its boundary-length fraction in the corridor is **0.2469** against the 0.35 bar, so
today both halves of the selector refuse it and the card prints `0W`. That is the right answer: the
WHOLE polygon lies behind the tee, spanning **-42.60 m to -24.08 m** along the tee-to-green axis, with
its nearest point **33.17 m** behind the first vertex on the first segment's own axis (t = **-0.1426**
of that 232.60 m segment, the same per-segment parameterisation `dist_to_line` uses). A ball struck
from that tee travels away from the marsh.

BUT NOTHING HERE REQUIRES IT TO STAY 0W, and an earlier version of this file's commit message claimed
it did. Because 34.57 m is inside the corridor, hole 15 is not in the mutation arm's `far` band; it
falls in the middle band, which is deliberately unasserted in direction (see that arm's docstring for
why). Demonstrated rather than asserted: with the `waters` boundary-length bar lowered 0.35 -> 0.20 in
a throwaway copy of the engine, hole 15 paints 1W and one blue fill and all three arms here still
report `3 passed`. That is the intended latitude -- over-drawing a hazard a golfer cannot reach is the
over-warning direction this book deliberately prefers, and pinning hole 15 to `0W` would convert a
safe future change into a test failure. What this file owes the reader is an honest account of what it
does and does not guard, which is what the paragraph above is -- and
`test_the_unguarded_holes_figures_are_measured_and_its_band_is_really_unguarded` keeps that account
from going stale, by re-deriving every figure in it and re-checking that the band really is open.

NOTHING HERE WRITES UNDER `courses/`. Both arms read the caches and render in memory; the mutation arm
withdraws the polygon from an in-memory element list by monkeypatching `render_hole.load`, never from a
file.
"""
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from conftest import corpus_slugs                                    # noqa: E402

# The one course this file is about. Named, not derived: the omission is a property of THIS cache, and
# a sweep that quietly found no course to measure is the failure mode the whole file is about. Every
# hole number, distance and count is derived; only the slug is written down.
SLUG = "merion-golf-club"

# The blue a card fills water with, read off the renderer rather than spelled here -- see
# `_water_fill`. A literal would let the ink change colour and leave this file asserting about a
# colour nothing draws.
_FILL_ATTR = 'fill="%s"'


def _engine(slug):
    """(config, render_hole) bound to `slug`. Same shape as test_r16_wetland._engine, same reason.

    conftest drops the course-bound modules after every test in this directory, so re-importing here
    is what binds them to `slug` rather than to whatever the previous test left.
    """
    os.environ["COURSE"] = slug
    for m in ("config", "render_hole"):
        sys.modules.pop(m, None)
    try:
        import config
        import render_hole
    except SystemExit as e:                                     # pragma: no cover - env-dependent
        pytest.skip("cannot bind %s: %s" % (slug, e))
    return config, render_hole


def _merion():
    """(config, render_hole) for merion, or a skip. `courses/` is gitignored -- a clone has no corpus."""
    if SLUG not in corpus_slugs():
        pytest.skip("%s is not built here; courses/ is gitignored" % SLUG)
    return _engine(SLUG)


def _water_fill(rh):
    """The fill attribute a card writes for AREA WATER, read out of the renderer's own source.

    Derived, not typed, and this is not pedantry: the inks in this engine move -- the penalty-area
    ink was lightened in this same campaign -- and a frozen `fill="#a9d3ef"` in a test file would
    keep counting a colour no card writes and report zero blue on a page full of it. So the colour
    comes from the one statement that writes it, and a change to that statement's SHAPE fails here
    rather than passing quietly.

    Scoped to the `water_svg` assignment on purpose. A regex over the whole function would match the
    first fill of any kind (rough, fairway, wood) and silently grade the wrong ink.
    """
    import inspect
    import re
    src = inspect.getsource(rh.render_hole)
    stmt = next((ln for ln in src.splitlines() if re.match(r"\s*water_svg\s*=", ln)), None)
    if not stmt:
        return None
    m = re.search(r'fill="(#[0-9a-fA-F]{3,8})"', stmt)
    return _FILL_ATTR % m.group(1) if m else None


def _wetland_fill(rh):
    """The fill attribute a card writes for DRAWN WETLAND, read out of the renderer's own source.

    The sibling of _water_fill and derived for the same reason, but it has to resolve a NAMED CONSTANT
    rather than a literal: wetland is drawn in the not-water grey, and that ink is
    `render_hole.PENALTY_FILL` because the guide cards' legend swatch is generated from it. So the
    statement reads `fill="{PENALTY_FILL}"` and the hex has to come from the module, which is the whole
    point -- a hex typed here would be a third copy of a value the legend and the map already share.

    Scoped to the `wet_svg` assignment, as _water_fill is scoped to `water_svg`: a regex over the whole
    function would match the penalty-area statement one line up, which writes the SAME ink for a
    different class, and this file would then be unable to tell a marsh from a barranca.
    """
    import inspect
    import re
    src = inspect.getsource(rh.render_hole)
    stmt = next((ln for ln in src.splitlines() if re.match(r"\s*wet_svg\s*=", ln)), None)
    if not stmt:
        return None
    m = re.search(r'fill="\{([A-Za-z_][A-Za-z_0-9]*)\}"', stmt)
    if not m:
        m = re.search(r'fill="(#[0-9a-fA-F]{3,8})"', stmt)
        return _FILL_ATTR % m.group(1) if m else None
    ink = getattr(rh, m.group(1), None)
    return _FILL_ATTR % ink if isinstance(ink, str) else None


def _projector(line):
    """(em, line_em) -- a local metres projection centred on this centreline, and the line in it.

    The same construction render_hole uses for its own corridor tests, so distances here are in the
    frame the drawing rule is expressed in.
    """
    import geo
    la0 = sum(q["lat"] for q in line) / len(line)
    lo0 = sum(q["lon"] for q in line) / len(line)
    mla, mlo = geo.mlat(la0), geo.mlon(la0)

    def em(la, lo):
        return ((lo - lo0) * mlo, (la - la0) * mla)
    return em, [em(q["lat"], q["lon"]) for q in line]


def _dist_to_played_line(pt, line_em):
    """Metres from a point to the PLAYED stretch of a centreline; inf when it sees none of it.

    Written here rather than imported from the engine, deliberately: a test measuring reach with the
    renderer's own selector cannot disagree with it. Projections falling behind the first vertex or
    past the last are dropped -- a hazard in those end caps is not on the hole, which is the
    distinction this file's docstring turns on and the reason one merion card prints `0W` correctly.
    """
    x, y = pt
    best, n = float("inf"), len(line_em) - 1
    for i in range(n):
        ax, ay = line_em[i]
        bx, by = line_em[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            continue
        t = ((x - ax) * dx + (y - ay) * dy) / L2
        if (i == 0 and t < 0.0) or (i == n - 1 and t > 1.0):
            continue
        t = max(0.0, min(1.0, t))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def _reach(cfg, rh):
    """(wetlands, {hole: metres}) -- the drawn wetlands in merion's cache and the holes they reach.

    "Reach" is nearest boundary point to the PLAYED length, under the renderer's own water corridor.
    Both halves derived at call time so neither a hole list nor a distance is frozen in this file.
    """
    import geo
    course, geom = rh.load()
    wet = [g for g in course if rh.is_drawn_wetland(g) and (g.get("geometry") or [])]
    loc = cfg.COURSE.get("location") or {}
    lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
    corridor = rh.CORRIDOR_M["water"]
    reach = {}
    for hn in sorted(cfg.HOLE_NUMS):
        hole = lines.get(hn)
        if hole is None or not wet:
            continue
        em, line_em = _projector(hole["geometry"])
        d = min(min(_dist_to_played_line(em(p["lat"], p["lon"]), line_em) for p in g["geometry"])
                for g in wet)
        if d < corridor:
            reach[hn] = d
    return wet, reach


def test_merions_hand_mapped_marsh_is_in_the_cache_its_cards_are_drawn_from():
    """The class the query asks for and the cards draw must be IN the file the cards are drawn from.

    This is the omission, stated at the only level it is visible at. `is_drawn_wetland` admits this
    polygon, `fetch_osm.main()` asks Overpass for the class and `census` buckets it as a hazard -- and
    for as long as the cache predated all three, every one of those was satisfied while the marsh
    appeared on no card. Nothing in the suite failed, because a corpus sweep measures the wetlands the
    corpus holds.

    Reachability is asserted with it, in the same arm and on purpose: a polygon sitting in the cache
    120 m from every played line would satisfy a bare presence check and prove nothing about rule 2.
    What has to be true is that the file holds the hazard AND that some card owes it ink.
    """
    cfg, rh = _merion()
    wet, reach = _reach(cfg, rh)
    assert wet, (
        "merion's osm_course.json holds no `natural=wetland` way that render_hole.is_drawn_wetland "
        "admits. Its ground has one -- a hand-mapped marsh beside a green -- so this is a cache "
        "fetched before the class entered fetch_osm.main()'s query, not a course without wetland. "
        "Re-fetch the course; the cards cannot draw a hazard that is not in the file they read.")
    assert reach, (
        "merion's cache holds %d drawn wetland(s) but none comes within %g m of any hole's PLAYED "
        "length, so no card owes it ink and this file measures nothing. Check the centrelines."
        % (len(wet), rh.CORRIDOR_M["water"]))


def test_every_merion_card_a_wetland_reaches_prints_it_as_a_hazard_and_fills_it_grey():
    """Reachable wetland must be BOTH counted on the card and filled on the map, per card.

    Both halves, separately, because either alone lets the other regress: a card can print a number
    over blank ground and it can draw ink under a zero. The shipped defect had neither.

    THE CLASS MOVED OFF THE BLUE AND THE RULE DID NOT. This test was `..._prints_it_as_water_and_fills_it_
    blue` and read `info["waters"]`, `info["water_hazards"]` and the water fill. Marsh is not water: merion's
    way 675572836 is a 151 m^2 `wetland=marsh`, and drawing it in the pond blue is what let callippe ship 39
    W over a course holding ONE `natural=water` polygon. So the count is `info["wetlands"]` and the ink is
    the not-water grey. What is asserted is what was asserted before -- reachable wetland is counted and
    drawn -- and it is no weaker: a marsh that went back to being inked blue would fail here for a missing
    grey fill, which is the direction that shipped.
    """
    cfg, rh = _merion()
    wet, reach = _reach(cfg, rh)
    if not reach:
        pytest.fail("no merion card is reached by a drawn wetland -- see the arm above")
    fill = _wetland_fill(rh)
    assert fill, "cannot read the renderer's wetland fill; a colour-blind count would pass vacuously"
    assert fill != _water_fill(rh), (
        "the renderer writes the SAME fill for wetland and for open water, so this file cannot tell a "
        "marsh from a pond and neither can a reader. That sharing is the defect: one ink may mean only "
        "one thing in the legend -- see render_hole.holds_open_water")
    bad = []
    for hn, d in sorted(reach.items()):
        svg, info = rh.render_hole(hn, cfg.HOLES)
        if info["wetlands"] < 1 or svg.count(fill) < 1:
            bad.append((hn, round(d, 2), info["wetlands"], svg.count(fill), info["waters"]))
    assert not bad, (
        "%d merion card(s) are reached by a drawn wetland and do not print it as a hazard -- "
        "(hole, metres off the played length, counted wetlands, grey fills, printed W): %s"
        % (len(bad), bad))


def _dist_with_end_caps(pt, line_em):
    """Metres from a point to the centreline with the END CAPS INCLUDED -- the loosest of the three.

    The complement of `_dist_to_played_line`: every segment's projection is clamped rather than
    dropped, so the half-disc behind the tee and past the green counts. This is the metric the
    renderer's own boundary-length fraction is built on, and it is used here for one purpose only --
    to bound what may NOT move. A hazard further than the water corridor from the centreline under
    even this measure cannot be admitted by any half of the selector, so its card must be untouched.
    """
    x, y = pt
    best = float("inf")
    for i in range(len(line_em) - 1):
        ax, ay = line_em[i]
        bx, by = line_em[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def _beyond_corridor(cfg, rh, wet):
    """Holes no half of the water selector can reach: nearest edge past the corridor WITH end caps."""
    import geo
    _course, geom = rh.load()
    loc = cfg.COURSE.get("location") or {}
    lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
    corridor = rh.CORRIDOR_M["water"]
    out = {}
    for hn in sorted(cfg.HOLE_NUMS):
        hole = lines.get(hn)
        if hole is None or not wet:
            continue
        em, line_em = _projector(hole["geometry"])
        d = min(min(_dist_with_end_caps(em(p["lat"], p["lon"]), line_em) for p in g["geometry"])
                for g in wet)
        if d >= corridor:
            out[hn] = d
    return out


def test_removing_the_marsh_takes_down_the_water_on_exactly_the_cards_it_reaches():
    """The mutation arm: the marsh must be the REASON those cards print water, not a bystander.

    Withdraw the drawn wetlands from the element list the renderer reads, re-render every hole, and
    compare. Three things must hold, and no existing arm asks any of them.

      * ON EVERY CARD THE MARSH REACHES OVER THE PLAYED LENGTH, the footer W falls and the blue ink
        count falls. A card that printed the same number either way was never counting this hazard,
        which is exactly the state the cache defect left merion's cards in -- and a presence check
        cannot tell the two apart.
      * ON EVERY CARD NO HALF OF THE SELECTOR CAN REACH, nothing moves at all. The bound used is the
        LOOSEST distance available -- nearest edge to the centreline with the end caps included -- so
        this is the over-draw direction of the same rule: the fix must not paint blue on a hole the
        marsh is nowhere near.
      * ON EVERY CARD, THE NUMBER AND THE MAP MOVE TOGETHER. Whatever a card does, its footer W and
        its count of blue fills must both move or both stay. This is the invariant that needs no
        threshold at all, and it is the one that catches a card printing a number over blank ground or
        drawing blue under a zero.

    THE THREE BANDS ARE NOT THE SAME BAND, and the middle one is deliberately left unasserted in
    direction. `render_hole`'s water selector is an OR of a boundary-length fraction and a played-length
    reach, so a hole can be admitted by the fraction alone. TWO merion cards sit in that middle band and
    they sit at opposite ends of it, which is why naming only one of them misleads:

      * hole 16 is admitted by the fraction (1.0000) at 13.0 m off its centreline and 142.3 m from its
        played length -- the marsh is 2.48 m from the green it putts to, so this is its greenside
        hazard, and over-warning is the side this book takes.
      * HOLE 15 IS REFUSED BY BOTH HALVES TODAY and prints `0W`, at 34.57 m off its centreline with the
        end caps included, 265.91 m from its played length, fraction 0.2469 against the 0.35 bar. Being
        inside the 45 m corridor is exactly what keeps it OUT of the `far` band above, so THIS ARM DOES
        NOT REQUIRE IT TO KEEP PRINTING `0W`. Measured, not assumed: lower the `waters` bar to 0.20 in
        a throwaway copy of the engine and hole 15 paints 1W and one blue fill while all three arms
        here still pass. That latitude is deliberate and must not be closed -- painting an unreachable
        hazard is the over-warning direction, and a guard forbidding it would fail the safe change.

    Asserting a direction in the middle band would mean respelling the selector inside the test, and a
    test carrying its own copy of the drawing rule cannot disagree with the engine about anything.

    The withdrawal is in memory -- `render_hole.load` is monkeypatched, `courses/` is never touched.
    """
    cfg, rh = _merion()
    wet, reach = _reach(cfg, rh)
    if not reach:
        pytest.fail("no merion card is reached by a drawn wetland -- see the first arm")
    fill = _wetland_fill(rh)
    assert fill, "cannot read the renderer's wetland fill; a colour-blind count would pass vacuously"
    assert fill != _water_fill(rh), (
        "the renderer writes the SAME fill for wetland and for open water, so withdrawing the marsh would "
        "be graded against the pond ink as well -- one ink may mean only one thing in the legend")

    # The withdrawal set is derived from THIS element list, not from `_reach`'s. `rh.load()` re-reads
    # the cache and returns fresh dicts every call, so Python object identity does not survive between
    # the two loads and filtering on it silently removed nothing at all -- the mutation arm then
    # compared a card against itself and could only ever pass.
    course, geom = rh.load()
    wet_here = [g for g in course if rh.is_drawn_wetland(g) and (g.get("geometry") or [])]
    assert len(wet_here) == len(wet), "the two loads of the cache disagree on how many wetlands it holds"
    drop = {(g.get("type"), g.get("id")) for g in wet_here}
    assert len(drop) == len(wet_here), "two drawn wetlands share one (type, id); cannot withdraw cleanly"
    far = _beyond_corridor(cfg, rh, wet_here)

    with_marsh = {}
    for hn in sorted(cfg.HOLE_NUMS):
        svg, info = rh.render_hole(hn, cfg.HOLES)
        with_marsh[hn] = (info["wetlands"], svg.count(fill))

    kept = [g for g in course if (g.get("type"), g.get("id")) not in drop]
    assert len(kept) == len(course) - len(wet_here), "the withdrawal removed the wrong number of ways"
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(rh, "load", lambda: (kept, geom))
        without = {}
        for hn in sorted(cfg.HOLE_NUMS):
            svg, info = rh.render_hole(hn, cfg.HOLES)
            without[hn] = (info["wetlands"], svg.count(fill))
    finally:
        monkey.undo()

    silent, collateral, disagree = [], [], []
    for hn in sorted(cfg.HOLE_NUMS):
        w_on, f_on = with_marsh[hn]
        w_off, f_off = without[hn]
        if (w_on != w_off) != (f_on != f_off):
            disagree.append((hn, (w_off, w_on), (f_off, f_on)))
        if hn in reach and (w_on <= w_off or f_on <= f_off):
            silent.append((hn, round(reach[hn], 2), (w_off, w_on), (f_off, f_on)))
        if hn in far and (w_on, f_on) != (w_off, f_off):
            collateral.append((hn, round(far[hn], 1), (w_off, w_on), (f_off, f_on)))
    assert not silent, (
        "%d merion card(s) count the same wetland with the marsh and without it, so its ink and its "
        "footer mark are not coming from the hazard the card is reached by -- (hole, metres off the "
        "played length, wetlands without/with, grey fills without/with): %s" % (len(silent), silent))
    assert not collateral, (
        "%d merion card(s) the marsh cannot reach under ANY half of the selector changed when it was "
        "withdrawn -- hazard ink has been painted onto a hole the golfer cannot reach it from, the "
        "over-draw direction of the same rule -- (hole, metres off the centreline with end caps, "
        "wetlands without/with, grey fills without/with): %s" % (len(collateral), collateral))
    assert not disagree, (
        "%d merion card(s) moved their wetland count without moving their hazard ink, or the reverse -- "
        "the marks under the map must describe the map -- (hole, wetlands without/with, grey fills "
        "without/with): %s" % (len(disagree), disagree))


# =============================================================================================
# THE ACCOUNT THIS FILE GIVES OF WHAT IT DOES NOT GUARD IS ITSELF GRADED
# =============================================================================================

def _axis_figures(cfg, rh, hn, wet):
    """Every figure this file publishes about the unguarded hole, re-measured from the cache.

    One helper so the prose and the grader cannot drift by measuring two different things. The frame is
    the renderer's own: `match_green` picks which end of the centreline is the tee, exactly as
    `render_hole` does, so "behind the tee" here means what it means on the card.
    """
    import geo
    course, geom = rh.load()
    greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    loc = cfg.COURSE.get("location") or {}
    line = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))[hn]["geometry"]
    _green, green_end, tee_end = rh.match_green(line, greens)
    em, line_em = _projector(line)
    tee = em(tee_end["lat"], tee_end["lon"])
    grn = em(green_end["lat"], green_end["lon"])
    ux, uy = grn[0] - tee[0], grn[1] - tee[1]
    chord = math.hypot(ux, uy) or 1.0
    ux, uy = ux / chord, uy / chord
    pts = [em(p["lat"], p["lon"]) for g in wet for p in g["geometry"]]

    caps = min(_dist_with_end_caps(p, line_em) for p in pts)
    played = min(_dist_to_played_line(p, line_em) for p in pts)
    frac = min(rh.frac_len_within([em(p["lat"], p["lon"]) for p in g["geometry"]], line_em,
                                 rh.CORRIDOR_M["water"]) for g in wet)
    along = [((p[0] - tee[0]) * ux + (p[1] - tee[1]) * uy) for p in pts]
    # the nearest point, and where it lands on the FIRST segment's own axis -- the per-segment
    # parameterisation `dist_to_line` uses, which is why its sign is what the played-length clip reads
    near = min(pts, key=lambda p: _dist_with_end_caps(p, line_em))
    ax, ay = line_em[0]
    bx, by = line_em[1]
    dx, dy = bx - ax, by - ay
    seg0 = math.hypot(dx, dy) or 1.0
    t0 = ((near[0] - ax) * dx + (near[1] - ay) * dy) / (dx * dx + dy * dy)
    return {"caps": caps, "played": played, "frac": frac,
            "axis_min": min(along), "axis_max": max(along),
            "seg0": seg0, "t0": t0, "behind": t0 * seg0}


def test_the_unguarded_holes_figures_are_measured_and_its_band_is_really_unguarded():
    """The module docstring names a hole this file does NOT guard. Re-derive the case it makes.

    THIS EXISTS BECAUSE THE CLAIM IT GRADES WAS ONCE WRONG IN THE OTHER DIRECTION. A tracked record for
    this work stated that the mutation arm "requires" hole 15 to keep printing `0W`. It does not, and the
    reason is a measured distance: 34.57 m is INSIDE the 45 m corridor, so that hole is not in the arm's
    `far` band. Overstating a guard is the same defect class as a stale published figure -- both are a
    record claiming something the build does not do -- and this repo already grades its published figures
    by re-deriving them rather than trusting the sentence. So this arm does that for the account above.

    TWO HALVES, because the sentence makes two kinds of claim:

      * THE FIGURES. Every distance, fraction and offset the docstring publishes for that hole is
        re-measured from the OSM geometry in merion's cache and must agree to the precision printed. A
        typo, a re-noded polygon or a moved centreline fails here instead of quietly misinforming.
      * THE BAND. The hole must genuinely still be OUTSIDE the set the mutation arm constrains. If a
        later change widened that band to cover it, the docstring's "not guarded" would silently become
        false -- so the membership is asserted, not described.

    IT DOES NOT ASSERT THAT THE HOLE PRINTS `0W`, deliberately, and that omission is the point. Pinning
    it would forbid the over-warning direction this book prefers. The honest guard is on the ACCOUNT,
    not on the outcome.

    The hole number is read out of the prose being graded rather than typed, so this arm cannot end up
    measuring a different hole than the paragraph describes.
    """
    import re
    cfg, rh = _merion()
    doc = sys.modules[__name__].__doc__
    # Matched against a whitespace-FLATTENED copy. The figures sit mid-paragraph, so re-wrapping the
    # prose moves newlines through them -- one pattern already broke that way while being written. The
    # grader must fail on a wrong NUMBER, never on a reflow.
    flat = re.sub(r"\s+", " ", doc)
    m = re.search(r"HOLE (\d+) IS THE CASE THAT SITS BETWEEN THEM", flat)
    assert m, "the module docstring no longer names the unguarded hole in the expected shape"
    hn = int(m.group(1))
    wet, _reach_map = _reach(cfg, rh)
    assert wet, "no drawn wetland in the cache; see the first arm"

    def pub(pattern, what):
        got = re.search(pattern, flat)
        assert got, "the module docstring no longer publishes %s in the expected shape" % what
        return float(got.group(1))

    want = {
        "caps": pub(r"nearest edge is \*\*([\d.]+) m\*\*", "the end-cap distance"),
        "played": pub(r"\*\*([\d.]+) m\*\* from its PLAYED length", "the played-length distance"),
        "frac": pub(r"fraction in the corridor is \*\*([\d.]+)\*\*", "the boundary-length fraction"),
        "axis_min": pub(r"\*\*(-[\d.]+) m to -[\d.]+ m\*\*", "the near end of the axis extent"),
        "axis_max": pub(r"\*\*-[\d.]+ m to (-[\d.]+) m\*\*", "the far end of the axis extent"),
        "behind": -pub(r"nearest point \*\*([\d.]+) m\*\* behind the first vertex",
                       "the offset behind the tee"),
        "t0": pub(r"t = \*\*(-[\d.]+)\*\*", "the first-segment t"),
        "seg0": pub(r"of that ([\d.]+) m segment", "the first segment length"),
    }
    got = _axis_figures(cfg, rh, hn, wet)
    wrong = []
    for k, w in want.items():
        places = len(str(w).split(".")[1]) if "." in str(w) else 0
        if round(got[k], places) != round(w, places):
            wrong.append("%s: docstring says %s, measured %.4f" % (k, w, got[k]))
    assert not wrong, (
        "the module docstring's figures for hole %d no longer match the cache -- re-measure the prose "
        "rather than the other way round: %s" % (hn, wrong))

    # THE BAND. Inside the corridor is precisely what keeps this hole out of the constrained set.
    corridor = rh.CORRIDOR_M["water"]
    assert got["caps"] < corridor, (
        "hole %d is %.2f m from the centreline with the end caps included, which is NOT inside the %g m "
        "corridor -- so it now falls in the band the mutation arm constrains, and the module docstring's "
        "account of it as unguarded has become false" % (hn, got["caps"], corridor))
    assert hn not in _beyond_corridor(cfg, rh, wet), (
        "hole %d is now in the mutation arm's `far` band, so that arm DOES require it not to move. The "
        "module docstring says the opposite. Reconcile them -- and note that closing this latitude "
        "forbids the over-warning direction this book prefers" % hn)
