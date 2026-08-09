#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Does the OSM fetch box actually cover what the cards DRAW?

Overpass returns a way whole if any one of its nodes is inside the query box, so a hole centreline
that pokes past the edge still arrives complete -- and that is exactly what makes this gap invisible.
The features BESIDE that stretch are a different matter: a bunker lying entirely outside the box is
never downloaded at all, the card simply does not draw it, and the footer's bunker count agrees with
the map because it is counted FROM the map. Nothing anywhere disagrees.

It is not hypothetical. valley-hi's box was ~46 m too tight at hole 16, and outside it OSM held:
  * a bunker 17 m from hole 16's centreline and another 14 m from hole 17's -- both well inside the
    corridor the map draws, so two cards were missing a hazard that exists on the ground;
  * the real green for hole 16, 1.3 m from the one that had been hand-traced from NAIP because OSM
    "had none" -- 33 vertices against the tracing's 17;
  * the real centreline for hole 17, 3 vertices and 360 yd against a 358 yd card, where the book was
    using a hand-drawn 2-point line of 220 yd. That short line is why hole 17 alone refused its
    from-tee yardages AND its elevation: it starts 98.6 m from any tee.

So a tight box does not just drop scenery. It can silently invite a hand-traced replacement for
geometry OSM already had, and then look like a data-availability problem rather than a query problem.

What is checked: every printed hole's drawing corridor must lie inside the box THE CACHE WAS FETCHED
WITH, at the WIDEST half-width render_hole selects any feature class on -- render_hole.DRAW_CORRIDOR_M,
currently the 68 m OSM tree-node radius. Reported in metres of overshoot per hole, worst first.

THE BOX IT MEASURED WAS THE DECLARED ONE, NOT THE FETCHED ONE, AND THAT IS THE WHOLE POINT OF THE
TOOL. `config.COURSE["osm_bbox"]` is a number in course.json; the cache is a file beside it; nothing
tied the two together, and this tool printed its verdict in the words "inside the FETCHED box".
Reproduced on a copy of valley-hi under /tmp: narrowing osm_bbox gave "15 hole(s) draw from outside the
fetched box (worst 164 m short at hole 17)" and exit 1, then widening ONLY course.json's osm_bbox --
osm_geom.json byte-identical, md5 f56a589a07c024aadcab1d0f786df357 before and after -- gave "every
hole's 68 m drawing corridor is inside the fetched box" and exit 0, over the same narrow cache. The
printed remedy is "WIDEN osm_bbox AND RE-FETCH", so the tool graded the half of its own instruction
that costs nothing and could not see the half that matters. The docstring below recorded that re-fetch
as deferred for months precisely BECAUSE an aborted fetch has permanently stripped irreplaceable
geometry here before -- so "the box was widened, was it re-fetched?" is the question most worth asking
and the one nothing could answer.

WHAT CLOSES IT, and it takes both halves:
  * A FETCH MUST RECORD THE BOX IT QUERIED. fetch_osm.py has to write the top-level key
    QUERY_BBOX_KEY below -- `"query_bbox": [south, west, north, east]`, course.json's own order, which
    is also Overpass's `(S,W,N,E)` filter order and the order fetch_osm already unpacks it in -- into
    every cache it commits (osm_geom.json at minimum; osm_course.json and osm_relations.json for the
    same reason). It is a sibling of Overpass's own version/generator/osm3s keys, so nothing that reads
    `["elements"]` notices it.
  * THIS GATE MEASURES THAT KEY when it is there, and says plainly that it CANNOT VERIFY the fetch box
    when it is not. It does not pass in silence: no cache on disk records one today (over all 11 built
    caches the only non-`elements` keys are version, generator and osm3s), so `--all` stops with
    ALLOW_UNRECORDED_FETCH_BOX named as the way through until fetch_osm.py starts recording. A declared
    box that DISAGREES with a recorded one is the "widened but never re-fetched" state itself, and it is
    exit 1 with no key at all.

THIS CHECK USED TO ASK FOR 45 m, from a `CORRIDOR_M = 45.0` of its own commented "render_hole's drawing
buffer". 45 is one of eight per-class radii and was never the widest, so the pre-flight could pass a
course whose drawn corridor reached 23 m of ground the fetch never requested -- which is precisely the
failure this tool exists to catch, since a feature outside the box is never downloaded, the card does
not draw it, and the footer is counted FROM the map. The number is now derived from render_hole's own
named set rather than kept here.

FOUR COURSES WERE SHORT AT 68 m, AND ALL FOUR ARE NOW WIDENED AND RE-FETCHED (2026-08-04). What they
read before that, and what it cost:

    castlewood-hill      88 m short (holes 1, 8, 7, 10, 18)            widening cost +24% query area
    castlewood-valley   103 m short (7, 12, 14, 6, 17 and 3 more)      widening cost +42% query area
    copper-valley        39 m short (hole 5)                           widening cost +2% query area
    monarch-bay          41 m short (holes 15, 10, 14)                 widening cost +5% query area

Every figure had grown by the 23 m the corridor grew when this check stopped measuring its own 45 m, and
two courses gained holes that had been just inside the old bar: hill 3 holes -> 5, monarch-bay 1 -> 3.

The deferral was real, not squeamishness: a re-fetch also pulls whatever has moved upstream in OSM since
the cache was made, and an aborted fetch has permanently stripped irreplaceable geometry here before
(see fetch_osm._check_response). So both halves were MEASURED before anything was written -- the widened
box fetched into a scratch directory seeded with the live cache, so every fetch_osm guard ran against the
real baseline -- and the two counts came out:

  * UPSTREAM DRIFT: ZERO on all four. 0 vanished ids, 0 changed geometries or tags, 0 new ids inside the
    OLD box, osm_relations.json identical where one existed. The entire stated cost of re-fetching
    measured to nothing, which is why this was the cheap moment to do it.
  * NEWLY REACHABLE DRAWN FEATURES: 4, every one a golf=tee polygon the narrow box cut off --
    way/692110589 8.5 m off hill 1; way/690850042 and way/690850043 at 2.9 m and 0.5 m off valley 7;
    way/690831855 2.4 m off valley 14. Valley 7's own back tees were outside its fetched box
    (start_at_tee_m 75.2 -> 0.0). No printed figure on any card moved: 0 of 1,028 and 0 of 1,054 visible
    text nodes changed in the two books; the ink moved by +1 and +3 drawn tee polygons and -9 and -3 tree
    markers.
  * NO OMITTED HAZARD, measured rather than assumed: the nearest newly fetched hazard-class feature is a
    stream 83.4 m from valley 17 against a 45 m water corridor, and the 8 new bunkers sit 400-546 m away
    -- they belong to the Hill course. So the shortfall was NOT hiding what valley-hi's 46 m hid.
  * WHAT THE NARROW BOX WAS REALLY COSTING THE PRINTED PAGE -- not a hazard, but 12 tree markers drawn
    on ground no ball can be played from, because fetch_trees' surface/footprint filter cannot exclude a
    polygon the fetch never asked for. hill: 9 markers standing on two houses OSM maps outside the old
    box (3 on hole 1's card, 6 on hole 8's). valley: 3 standing on the newly fetched TEES of holes 6 and
    7 -- caught by test_no_tree_marker_sits_on_a_playing_surface the moment the wider cache landed.
    Re-deriving each layer on the widened cache removed exactly those and nothing else: hill
    10,422 -> 10,413, valley 9,238 -> 9,235, 0 added, every other hole untouched. copper-valley 6,305 and
    monarch-bay 1,439 re-derived BYTE-IDENTICAL, which is the confirmation that their widened boxes
    changed nothing at all.

None of that measurement is evidence any more, and that is the second reason the key above exists: the
caches those four re-fetches produced do not record the boxes they were fetched with either, so the only
proof that the widening was followed by a re-fetch is this note. A re-fetch of any of them now would
leave one behind.

An earlier revision of this note recorded a live Overpass probe with a 120 m-widened box finding no drawn
feature missing, at "28 m short (holes 6, 17, 18, 8, 13)" for hill and "28 m" for valley. Those figures
never matched any bar this tool has used -- at 45 m the shortfalls read 65, 80, 16 and 18 -- so whatever
that probe checked, it did not check this. It is kept here as the reason the measurement above names its
ids, its distances and its date: a stale "already investigated" is worse than no note, because it stops
the next person looking.

test_every_cached_osm_bbox_covers_the_corridor_its_cards_draw now fails on any course whose box stops
short of DRAW_CORRIDOR_M, so this cannot silently return.

A COURSE THAT COULD NOT BE CHECKED IS NOT A COURSE THAT PASSED, and it used to be indistinguishable from
one. `return 0 if oks else 2` under an `except Exception -> "skip"` in main() and an
`except SystemExit -> "skip"` inside check_course meant ONE passing course spoke for all twelve. Measured
live: `--all` printed "11 course(s) fully covered, 0 with a corridor outside the box, 1 not checked" and
returned 0, and the same arithmetic returns 0 for 1 covered and 11 refused. `--al` -- one character short
of `--all` -- was silently discarded, so with COURSE set it checked ONE course and exited 0.
Every unexamined course now reaches the exit status, keyed the way lidar_coverage.report_or_exit and
tools/verify_elevation.py key theirs, and for their reason: a course can be permanently unexaminable
through nobody's fault (poppy-ridge is built in yardage mode with no OSM cache at all) and an
unconditional refusal would wedge `--all` forever. Three questions, so up to two keys and one refusal
that has none:

    ALLOW_UNCHECKED_OSM_BBOX      this course has no osm_bbox or no cache on disk
    ALLOW_UNRECORDED_FETCH_BOX    no cache records the box it was queried with, so the FETCH is
                                  unverified even where the declared box covers the corridor
    (no key)                      geo.hole_lines REFUSED this cache, or it could not be read at all

The last one gets no waiver deliberately: that is a fault in the data being CHECKED rather than a fact
about the world, exactly the line tools/verify_elevation.py draws at a torn surface pair and surface_io
draws at stamping one. A run that certifies what it could not read is worse than one that reports it.
Neither key waives the other, which is the cost fetch_osm._check_response records for one flag gating
two questions.

Exit codes:  0 every corridor is inside the box the cache records being fetched with, and every course
               was examined (or its gap is acknowledged by name)
             1 at least one hole draws from outside that box -- widen osm_bbox and RE-FETCH -- or the
               declared box and the recorded one disagree, which is a widening with no re-fetch
             2 something could not be checked and was not acknowledged: no cache, no recorded query
               box, a refused cache, or nothing examined at all

Run:  COURSE=<slug> python3 tools/check_osm_bbox.py
      python3 tools/check_osm_bbox.py --all
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import distribution                              # noqa: E402 -- the repo's one "is this a course?"
from lidar_coverage import _env_on               # noqa: E402 -- one spelling of "off"; see the keys

# THE KEY A CACHE MUST CARRY TO PROVE WHICH BOX IT WAS FETCHED WITH, and the contract fetch_osm.py has
# to meet: a top-level `"query_bbox": [south, west, north, east]` beside Overpass's own version,
# generator and osm3s. course.json's order, which is also Overpass's `(S,W,N,E)` bbox-filter order and
# the order fetch_osm already unpacks `config.COURSE["osm_bbox"]` in, so there is no re-ordering step
# anywhere for a reader to get wrong. Read through recorded_query_bbox, which refuses anything that is
# not four numbers -- a box read in the wrong shape is worse than no box, because it would be measured
# against with confidence.
QUERY_BBOX_KEY = "query_bbox"

# The two acknowledgement keys, and they are separate because they are separate questions. See the
# module docstring. Read through lidar_coverage._env_on so that =0, =false and =no waive nothing.
NO_CACHE_ACK = "ALLOW_UNCHECKED_OSM_BBOX"
UNRECORDED_ACK = "ALLOW_UNRECORDED_FETCH_BOX"

# The per-course verdicts. Named constants rather than bare strings because main() partitions on them
# and tests/test_r16_gates.py asserts the partition: a verdict nothing classifies used to fall into
# "skip" and then into exit 0.
OK = "ok"                # every corridor inside the box the cache was fetched with
SHORT = "short"          # a corridor reaches ground the fetch never requested
DRIFT = "drift"          # course.json declares a box the cache was NOT fetched with
NO_CACHE = "nocache"     # no osm_bbox declared, or no osm_geom.json on disk
REFUSED = "refused"      # geo.hole_lines refused this cache, or it could not be read at all

KNOWN_FLAGS = ("--all",)


def unknown_args(argv):
    """The arguments this tool does not understand -- EXACT membership, never a prefix or a substring.

    `--al` used to be silently discarded, which turned a corpus-wide gate into a one-course one with no
    word said and exit 0. Spelled the same way in tools/gen_provenance.py and tools/gen_disclaimers.py,
    and all three are held to ONE truth table by tests/test_r16_gates.py, which DISCOVERS every tool
    defining this function rather than listing them -- lidar_coverage._env_on's arrangement.
    The course comes from COURSE in the environment, never from a positional argument, so a bare word is
    unknown too.
    """
    return [a for a in argv if a not in KNOWN_FLAGS]


def recorded_query_bbox(cache):
    """[S, W, N, E] the cache records being FETCHED with, or None if it does not record one.

    None for absent AND for malformed, on purpose: a box that is not four numbers cannot be measured
    against, and guessing at one would put this gate back where it started -- confidently reporting on a
    box nothing established. `cache` is the loaded reply, so this reads the same object geo.hole_lines
    is handed and needs no second pass over the file.
    """
    box = cache.get(QUERY_BBOX_KEY) if isinstance(cache, dict) else None
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box):
        return None
    return [float(v) for v in box]


def _same_box(a, b):
    """Do two boxes name the same ground? Compared with a tolerance far below a metre of latitude."""
    return a is not None and b is not None and \
        all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b))


def corridor_shortfalls(bbox, lines, corridor_m):
    """[(hole, metres_short)] worst first: how much wider `bbox` had to be to cover what is drawn.

    Pulled out of check_course so the box it is handed is VISIBLE -- the whole defect was that the box
    came from course.json while the message said "fetched". A vertex INSIDE the box still draws
    corridor_m around itself, so the margin it needs from every edge is the whole corridor; that is the
    23 m of ground the retired `CORRIDOR_M = 45.0` copy let through.
    """
    import geo
    S, W, N, E = bbox
    bad = []
    for hn, w in sorted(lines.items()):
        worst = 0.0
        for p in w["geometry"]:
            # how far OUTSIDE the box this vertex is, before the corridor is even added
            dlat = max(S - p["lat"], p["lat"] - N, 0.0)
            dlon = max(W - p["lon"], p["lon"] - E, 0.0)
            out = math.hypot(dlon * geo.mlon(p["lat"]), dlat * geo.mlat(p["lat"]))
            # a vertex INSIDE the box still draws corridor_m around itself, so the margin it needs is
            # the corridor; anything less than that from an edge can be missing features too
            edge = min((p["lat"] - S) * geo.mlat(p["lat"]), (N - p["lat"]) * geo.mlat(p["lat"]),
                       (p["lon"] - W) * geo.mlon(p["lat"]), (E - p["lon"]) * geo.mlon(p["lat"]))
            short = max(0.0, corridor_m - edge) if out == 0 else out + corridor_m
            worst = max(worst, short)
        if worst > 0:
            bad.append((hn, round(worst)))
    bad.sort(key=lambda x: -x[1])
    return bad


def evaluate(cache, declared, lines, corridor_m):
    """(status, bad, measured, unverified) for one cache. The decision, with no I/O in it.

    `measured` is the box the shortfalls were actually measured against, so a caller can print it and a
    reader can tell which box answered. `unverified` is a SECOND, INDEPENDENT answer: the empty string
    when the cache records the box it was queried with, otherwise why the fetch box could not be
    established. It is separate from `status` because they are separate questions -- a course whose
    declared box is short AND whose cache records nothing has two findings, and a waiver for either must
    not silence the other. That is lidar_coverage.report_or_exit's two-key rule.

    Ordering, and it decides what a reader is told first:
      * DRIFT beats everything. A declared box the cache was not fetched with means the widening
        happened and the re-fetch did not, which is the one state this tool's own printed remedy passes
        through. Measured against the RECORDED box, because that is where the elements came from.
      * SHORT beats the unverified answer. A corridor outside the declared box is a real finding
        whichever box was queried, and it must not be waivable by the key that covers "we cannot tell
        which box was queried".
    """
    if declared is None:
        return NO_CACHE, [], None, ""
    recorded = recorded_query_bbox(cache)
    if recorded is None:
        bad = corridor_shortfalls(declared, lines, corridor_m)
        why = (f"osm_geom.json records no {QUERY_BBOX_KEY}, so the box it was FETCHED with is unknown; "
               f"measured against course.json's DECLARED box instead")
        return (SHORT if bad else OK), bad, declared, why
    bad = corridor_shortfalls(recorded, lines, corridor_m)
    if not _same_box(declared, recorded):
        return DRIFT, bad, recorded, ""
    return (SHORT if bad else OK), bad, recorded, ""


def check_course(slug):
    """(status, bad, unverified) for one course, printing what it found. See evaluate() for the rules."""
    for m in ("config", "render_hole", "render_green"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config                                   # noqa: E402
    import geo                                      # noqa: E402
    # The corridor half-width comes from the engine that DRAWS it, never from a second copy here. This
    # module carried `CORRIDOR_M = 45.0` commented "render_hole.in_corridor's drawing buffer", and 45
    # was never the widest of render_hole's eight per-class radii -- OSM tree nodes reach 68 m -- so this
    # pre-flight could pass a course whose drawn corridor took in 23 m of ground the fetch never
    # requested. render_hole.DRAW_CORRIDOR_M is the max of its named set, so widening any one class
    # widens this check with it. Imported after COURSE is bound, because render_hole reads config at
    # import time.
    import render_hole                              # noqa: E402
    corridor_m = render_hole.DRAW_CORRIDOR_M

    bbox = config.COURSE.get("osm_bbox")
    geom_p = os.path.join(config.COURSE_DIR, "osm_geom.json")
    if not bbox or not os.path.isfile(geom_p):
        print(f"{slug}: no osm_bbox or no geometry on disk -- NOT CHECKED")
        return NO_CACHE, [], ""
    with open(geom_p, encoding="utf-8") as fh:
        cache = json.load(fh)
    loc = config.COURSE.get("location") or {}
    try:
        lines = geo.hole_lines(cache["elements"], loc.get("lat"), loc.get("lon"))
    except SystemExit as e:
        # A REFUSAL, not a skip. geo.hole_lines refuses a cache it cannot resolve into holes, and that
        # used to be printed as "cannot resolve hole lines" and then counted as "not checked" -- which
        # exit 0 could survive. It is our own data disagreeing with itself, so it has no waiver.
        print(f"{slug}: geo.hole_lines REFUSED this cache -- {str(e).splitlines()[0]}")
        return REFUSED, [], ""

    status, bad, measured, unverified = evaluate(cache, bbox, lines, corridor_m)
    if unverified:
        print(f"{slug}: {unverified}")
    if status == DRIFT:
        print(f"{slug}: course.json declares osm_bbox {bbox} but osm_geom.json records being fetched "
              f"with {measured} -- the box was WIDENED AND NEVER RE-FETCHED, so every feature beside "
              f"the widened strip is still missing from the cards drawn off this cache")
    if not bad:
        if status != DRIFT:
            which = "DECLARED box" if unverified else "box the cache records being fetched with"
            print(f"{slug}: every hole's {corridor_m:g} m drawing corridor is inside the {which}")
        return status, bad, unverified
    print(f"{slug}: {len(bad)} hole(s) draw from outside the measured box "
          f"(worst {bad[0][1]} m short at hole {bad[0][0]})")
    for hn, m in bad:
        print(f"    hole {hn:2d}: needs {m} m more box to cover its corridor")
    return status, bad, unverified


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # REFUSED BEFORE ANYTHING IS ENUMERATED. `--al` used to be discarded, so a corpus-wide gate quietly
    # became a one-course one and still exited 0.
    stray = unknown_args(argv)
    if stray:
        print(f"unknown argument(s): {' '.join(stray)}\n"
              f"usage: check_osm_bbox.py --all      (every built course)\n"
              f"       COURSE=<slug> python3 tools/check_osm_bbox.py      (one course)")
        return 2
    if "--all" in argv:
        # distribution.course_slugs is this repo's ONE spelling of "a course, or somebody's scratch?"
        # -- the same rule gen_provenance, gen_disclaimers and the test suite ask. The local glob it
        # replaces was a fourth copy, and that helper's own docstring already names this tool.
        slugs = distribution.course_slugs(ROOT)
        if not slugs:
            print("no course data present (courses/ is gitignored, and `_`-prefixed scratch "
                  "directories are not courses) -- nothing to check.")
            return 2
    else:
        slug = os.environ.get("COURSE")
        if not slug:
            print("set COURSE=<slug>, or pass --all")
            return 2
        slugs = [slug]

    res = {}
    for s in slugs:
        try:
            res[s] = check_course(s)
        except (Exception, SystemExit) as e:
            # THE LAST-RESORT NET, and it is no longer where a passing verdict comes from. What reaches
            # here is a course this tool could not process at all -- an unreadable cache, a course.json
            # config refuses -- which is the loudest form of "not checked" and is recorded as exactly
            # that. It used to be recorded as "skip" and then discarded by `return 0 if oks else 2`.
            print(f"{s}: could not check ({type(e).__name__}: {e})")
            res[s] = (REFUSED, [], "")

    by = {}
    for s, (st, _bad, _why) in res.items():
        by.setdefault(st, []).append(s)
    oks, shorts, drifted = sorted(by.get(OK, [])), sorted(by.get(SHORT, [])), sorted(by.get(DRIFT, []))
    nocache, refused = sorted(by.get(NO_CACHE, [])), sorted(by.get(REFUSED, []))
    unverified = sorted(s for s, (_st, _b, why) in res.items() if why)
    unclassified = sorted(set(by) - {OK, SHORT, DRIFT, NO_CACHE, REFUSED})
    assert not unclassified, f"check_course returned a verdict main() does not classify: {unclassified}"

    print(f"\n{len(oks)} course(s) fully covered, {len(shorts) + len(drifted)} with a corridor outside "
          f"the box that was fetched, {len(nocache)} with no cache, {len(refused)} refused, "
          f"{len(unverified)} whose FETCH box is unrecorded")
    if drifted:
        print("RE-FETCH (osm_bbox was widened and the cache was not): " + ", ".join(drifted))
    if shorts:
        print("WIDEN osm_bbox AND RE-FETCH: " + ", ".join(shorts))
        print("  A tight box drops features beside the stretch that pokes out, and the card cannot\n"
              "  tell you: the footer counts what the map has, not what the course has.")
    if shorts or drifted:
        return 1

    # Everything below is "could not be checked", and each stop names its own key. Asked separately and
    # every time: an early return once let one acknowledgement silence a finding it was never given for.
    stop = False
    if refused:
        print(f"REFUSED, and no key waives this: {', '.join(refused)}\n"
              f"  A cache geo.hole_lines will not resolve into holes is our own data disagreeing with\n"
              f"  itself, and nothing here can bound what its cards draw. Fix the cache (re-run\n"
              f"  fetch_osm.py for that course) and run this again.")
        stop = True
    if nocache and not _env_on(NO_CACHE_ACK):
        print(f"NOT CHECKED -- no osm_bbox or no cache on disk: {', '.join(nocache)}\n"
              f"  Nothing here says those courses' cards draw only ground the fetch requested, and\n"
              f"  exit 0 is documented as saying exactly that. A course built in yardage mode with no\n"
              f"  OSM geometry can never be checked here (poppy-ridge is that case), so set\n"
              f"  {NO_CACHE_ACK}=1 once you have read why each one is empty.")
        stop = True
    if unverified and not _env_on(UNRECORDED_ACK):
        print(f"FETCH BOX UNVERIFIED -- the cache does not record the box it was queried with: "
              f"{', '.join(unverified)}\n"
              f"  Those corridors were measured against course.json's DECLARED box, which is a number\n"
              f"  a person can edit; the cache is what the cards are drawn from. Widening the\n"
              f"  declaration alone turns this gate green over an unchanged cache -- measured -- so a\n"
              f"  pass here would be a pass for the half of the remedy that costs nothing.\n"
              f"  fetch_osm.py must write a top-level \"{QUERY_BBOX_KEY}\": [south, west, north, east]\n"
              f"  into each cache it commits. Until it does, set {UNRECORDED_ACK}=1 to accept that the\n"
              f"  RE-FETCH half of this check is not being performed.")
        stop = True
    if not oks:
        print("nothing was checked -- treat as UNKNOWN, not as coverage")
        stop = True
    if stop:
        return 2
    if nocache:
        print(f"WARNING: {NO_CACHE_ACK} set -- {len(nocache)} course(s) accepted with no OSM cache to "
              f"check: {', '.join(nocache)}")
    if unverified:
        print(f"WARNING: {UNRECORDED_ACK} set -- {len(unverified)} course(s) measured against a DECLARED "
              f"box with nothing on disk proving it is the box they were fetched with: "
              f"{', '.join(unverified)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
