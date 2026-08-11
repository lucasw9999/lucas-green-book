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
`test_r16_wetland.py::test_a_wetland_the_played_line_reaches_is_never_printed_as_no_water` asserts
that a reachable wetland is counted and filled. That is the right invariant and it cannot see this
defect twice over: it is satisfied vacuously by a course whose cache holds no wetland, and where a
card has other water it is satisfied by that other water -- `water_hazards >= len(near)` does not ask
WHICH polygon supplied the number. So the arms here ask the two questions it does not:

  * is the class in the file the cards are drawn from AT ALL, on a course whose ground has it
    (`test_merions_hand_mapped_marsh_is_in_the_cache_its_cards_are_drawn_from`); and
  * is that polygon the REASON its cards print water -- withdrawing it must take the footer W down and
    the blue ink off every card it reaches, leave every card it is nowhere near untouched, and move a
    card's number and its map together or not at all
    (`test_removing_the_marsh_takes_down_the_water_on_exactly_the_cards_it_reaches`).

The second is a mutation test and it is what makes the first honest. A card that prints `1W` over a
pond it always had would satisfy any presence check; requiring the number and the ink to MOVE when the
polygon is withdrawn is what ties them to this hazard rather than to the neighbourhood.

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
One hole lies 34.6 m from the drawn centreline with the caps included and 265.9 m from its PLAYED
length, because the whole of that approach is behind its tee. A ball struck from that tee travels away
from the marsh, so that card prints `0W` correctly and keeps printing it.

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


def test_every_merion_card_a_wetland_reaches_prints_it_as_water_and_fills_it_blue():
    """Reachable wetland must be BOTH counted in the footer and filled on the map, per card.

    Both halves, separately, because either alone lets the other regress: a card can print a number
    over blank ground and it can draw blue under a zero. The shipped defect had neither.
    """
    cfg, rh = _merion()
    wet, reach = _reach(cfg, rh)
    if not reach:
        pytest.fail("no merion card is reached by a drawn wetland -- see the arm above")
    fill = _water_fill(rh)
    assert fill, "cannot read the renderer's water fill; a colour-blind count would pass vacuously"
    bad = []
    for hn, d in sorted(reach.items()):
        svg, info = rh.render_hole(hn, cfg.HOLES)
        if info["waters"] < 1 or info["water_hazards"] < 1 or svg.count(fill) < 1:
            bad.append((hn, round(d, 2), info["waters"], info["water_hazards"], svg.count(fill)))
    assert not bad, (
        "%d merion card(s) are reached by a drawn wetland and do not print it as water -- "
        "(hole, metres off the played length, printed W, counted area hazards, blue fills): %s"
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
    reach, so a hole can be admitted by the fraction alone -- one merion card is, at 13.0 m off its
    centreline with the marsh sitting beside the green it putts to and 142.3 m from its played length,
    which is the greenside hazard on that hole and over-warning is the side this book takes. Asserting
    a direction there would mean respelling the selector inside the test, and a test carrying its own
    copy of the drawing rule cannot disagree with the engine about anything.

    The withdrawal is in memory -- `render_hole.load` is monkeypatched, `courses/` is never touched.
    """
    cfg, rh = _merion()
    wet, reach = _reach(cfg, rh)
    if not reach:
        pytest.fail("no merion card is reached by a drawn wetland -- see the first arm")
    fill = _water_fill(rh)
    assert fill, "cannot read the renderer's water fill; a colour-blind count would pass vacuously"

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
        with_marsh[hn] = (info["waters"], svg.count(fill))

    kept = [g for g in course if (g.get("type"), g.get("id")) not in drop]
    assert len(kept) == len(course) - len(wet_here), "the withdrawal removed the wrong number of ways"
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(rh, "load", lambda: (kept, geom))
        without = {}
        for hn in sorted(cfg.HOLE_NUMS):
            svg, info = rh.render_hole(hn, cfg.HOLES)
            without[hn] = (info["waters"], svg.count(fill))
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
        "%d merion card(s) print the same water with the marsh and without it, so its ink and its "
        "footer W are not coming from the hazard the card is reached by -- (hole, metres off the "
        "played length, W without/with, blue fills without/with): %s" % (len(silent), silent))
    assert not collateral, (
        "%d merion card(s) the marsh cannot reach under ANY half of the selector changed when it was "
        "withdrawn -- water has been painted onto a hole the golfer cannot reach it from, the "
        "over-draw direction of the same rule -- (hole, metres off the centreline with end caps, "
        "W without/with, blue fills without/with): %s" % (len(collateral), collateral))
    assert not disagree, (
        "%d merion card(s) moved their footer W without moving their blue ink, or the reverse -- the "
        "number under the map must describe the map -- (hole, W without/with, blue fills "
        "without/with): %s" % (len(disagree), disagree))
