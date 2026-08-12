#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
`natural=wetland` was fetched by nothing and drawn by nothing, on a course whose wetland is the
hazard.

THE DEFECT, as it shipped. `fetch_osm.main()`'s course query asked for water areas, watercourses,
wood, scrub, forest, tree rows and bare rock, and never for `natural=wetland`. So `census` could not
bucket a wetland, `_check_response` could not miss one, and `render_hole`'s water selector could not
draw one -- the single occurrence of the word in the engine was a `VOLATILE_KINDS` entry for a key
nothing could ever produce. Callippe Preserve Golf Course is built on hand-mapped seasonal wetland:
**12** `natural=wetland` ways inside its fetch box, 1,812-10,866 m2, and **16 of its 18** holes have
one within `CORRIDOR_M['water']` (45 m) of the drawn centreline. **Nine** shipped cards printed `0W`
over one -- holes 2, 3, 5, 6, 7, 8, 9, 11 and 12, the nearest wetland 0.0-5.1 m from the played line
-- while the nearest blue mark the map DID draw on those holes was 66-216 m away. The book's second
rule is never omit a hazard the golfer can reach.

A BLANKET ADMIT IS ALSO WRONG, and that is the hard half. Two polygons in this corpus carry
`natural=wetland` and are not hazards a card should paint:

  * monarch-bay `way/114224114` -- **1,745,827 m2** (431.46 acres, its own `acres` tag), **90.9% of
    monarch-bay's entire fetch box** and **12.9x** the course's whole greens+fairways+tees footprint,
    imported from California's Farmland Mapping and Monitoring Program and carrying that program's
    own class label: `description=other land`. It comes 23.5 m from hole 15's centreline, 30.9 from
    14's and 33.2 from 13's, so admitting it paints three cards blue over dry shoreline.
  * the-reserve `way/82590918` -- a genuine 7,025 m2 `wetland=marsh` from NHD (`gnis:ftype=SwampMarsh`).
    Admitted, and it reaches no card: its nearest approach is 94.5 m, twice the water corridor. It is
    here because a marker-based refusal keyed on `source` alone would have thrown it away.

WHAT THE PREDICATE DECIDES, and it is a tag test so it can be graded by truth table: a
`natural=wetland` way is wet ground a card draws unless it carries a land-classification dataset's
OWN label for the same polygon -- `description`, `landuse`, `attribution` or `acres` -- and does not
carry a `wetland=*` subtype affirming wetness. Callippe's twelve carry no such tag at all (one carries
`salt=no`/`tidal=no`, which is an assertion ABOUT the wetland, not a competing classification). The
FMMP tile carries four of them and no subtype.

WHAT IT CANNOT DECIDE, stated rather than implied:

  * merion `way/675572836`, a 151 m2 `wetland=marsh`, is ADMITTED -- it carries no import marker. It
    is 2.48 m from green 285240132 and 10.22 m from hole 17's PLAYED LENGTH, and it took merion 14, 16
    and 17 from 0W to 1W when merion was re-fetched. An audit note offered it as a
    counter-example on the grounds that its centroid sits inside a green; measured, the two polygons
    do not intersect at all (0.0 m2 of overlap, 2.48 m apart). What lands inside the green is the
    MEAN OF ITS VERTICES, which is not a property of the shape -- re-noding the ring moves it, and
    this project already replaced one vertex-fraction test for exactly that reason (see
    render_hole.frac_len_within). A greenside wet hollow a junior can reach is what rule 2 is about,
    so it is drawn. Over-warning is the chosen side.

    HOLE 15 IS NOT IN THAT LIST AND MUST NOT BE ADDED. The marsh is 34.57 m from hole 15's OSM
    centreline, CLOSER than hole 14's 39.43 m, so the list reads as if it had missed one -- and two
    readings of this marsh have now made that mistake. Measured through the engine, both halves of the
    `waters` selector refuse hole 15: the boundary-length fraction inside 45 m is 0.2469 against the 0.35
    bar (hole 14's is 0.3582), and over the PLAYED length the marsh is 265.91 m away, because its nearest
    approach lies at arc 0.0 -- at the tee, behind the line, where a struck ball travels away from it.

    TWO AXES, NAMED, because they are not interchangeable. Both are nearest-EDGE distances on
    geo.mlat/mlon: against the raw OSM centreline WITH END CAPS it is h14 39.43, h15 34.57, h16 13.02,
    h17 9.62; against the DRAWN PLAYED LINE as `any_within` clips it, h14 39.43, h15 265.91, h16 142.29,
    h17 10.22. They coincide on hole 14 and diverge by 132x on hole 15.
  * a MIS-TAGGED SMALL wetland with no import provenance is indistinguishable from a real one here,
    and is drawn. That is the same direction the renderer already errs in for a seasonally dry
    channel: `is_visible_watercourse` excludes piped, hidden and not-water reaches but deliberately
    NOT intermittent ones, so a channel that is dry in August still prints blue and counts W -- 34 of
    the 43 corpus ways carrying `intermittent=yes` are drawn today, on 5 of the 12 courses.

AND THE TREE WAIVER IN THE SAME MODULE. `render_hole._lidar_trees` read `ALLOW_OSM_TREES` with a bare
`os.environ.get`, so `=0`, `=false` and `=no` -- every spelling a person reaches for to DISABLE it --
are non-empty strings, therefore truthy, therefore waived the guard, and then the NOTE it prints
("ALLOW_OSM_TREES set") was false about what the operator wrote. What that guard prevents, in its own
words: 25 markers instead of 5086 on Merion, so a tree-lined corridor printed as open ground while the
legend still promised trees. Routed through `lidar_coverage._env_on`, the same object every other
waiver in the engine reads, rather than an eighth hand-written vocabulary.

NOTHING HERE WRITES UNDER `courses/`. The tag tables are literals, the fetch tests read source text,
and the corpus arms only READ the caches and render in memory.
"""
import ast
import contextlib
import io
import json
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from conftest import corpus_slugs                                    # noqa: E402

# The spellings that must be OFF and ON whatever `lidar_coverage._env_on` grows to recognise. Only the
# CORE of each is written here on purpose: the vocabulary itself has one home and is graded there, so
# freezing a second copy in this file is how the two drift -- this repo has already paid for five
# hand-copied ones. What this file pins instead is that ALLOW_OSM_TREES is read through THAT vocabulary,
# whatever it currently is, by requiring the guard's behaviour to track `_env_on` value for value.
OFF_CORE = ("", "0", "false", "FALSE", "False", "no", "No", "NO")
ON_CORE = ("1", "true", "TRUE", "yes", "Yes", "2")
# Values that have moved between the two sides, or that a shell or an editor produces by accident. Not
# classified here -- driven through `_env_on` and required to agree with the guard either way.
VOCABULARY_PROBES = OFF_CORE + ON_CORE + ("off", "OFF", "0 ", " 0", "0\n", "none", "disable", "-1")

WATER_CORRIDOR_M = 45.0          # asserted against render_hole.CORRIDOR_M['water'] below


# ---------------------------------------------------------------------------------------------
# The corpus wetland inventory, by TAGS -- never by way id or course slug.
#
# Every dict below is the verbatim tag set of a real `natural=wetland` way returned by Overpass for
# one of this corpus's twelve fetch boxes (one live query, 2026-08-09, all twelve boxes in one union).
# The way ids and courses are named in comments so a reader can go and look, and are NOT read by any
# assertion: a predicate that keyed on an id or a slug would be a fake fix.
# ---------------------------------------------------------------------------------------------
CALLIPPE_WETLAND_TAGS = (
    {"natural": "wetland"},                                    # way/785697154  1,885 m2
    {"natural": "wetland"},                                    # way/785697155  3,064 m2
    {"natural": "wetland"},                                    # way/785697156  2,854 m2
    {"natural": "wetland"},                                    # way/785697157  5,506 m2
    {"natural": "wetland"},                                    # way/785697158  6,101 m2
    {"natural": "wetland"},                                    # way/785697159  4,704 m2
    {"natural": "wetland"},                                    # way/785697160  6,480 m2
    {"natural": "wetland"},                                    # way/786406320  1,812 m2
    {"natural": "wetland"},                                    # way/786406321  6,450 m2
    {"natural": "wetland"},                                    # way/786406322  4,103 m2
    {"natural": "wetland"},                                    # way/786406323 10,866 m2
    # the one that carries anything else -- and what it carries is an assertion ABOUT the wetland
    # (not salt, not tidal), which is evidence FOR it being surveyed rather than classified
    {"natural": "wetland", "salt": "no", "tidal": "no"},        # way/785697151  5,423 m2
)

# monarch-bay way/114224114: 1,745,827 m2 = 431.46 acres, 90.9% of monarch-bay's fetch box.
FMMP_TILE_TAGS = {
    "FMMP_modified": "no", "FMMP_reviewed": "no", "acres": "431.460542194",
    "addr:county": "Alameda", "attribution": "Farmland Mapping and Monitoring Program",
    "description": "other land", "natural": "wetland",
    "source": "http://www.consrv.ca.gov/dlrp/fmmp/products/Pages/DownloadGISdata.aspx",
}

# the-reserve way/82590918: a real 7,025 m2 marsh from NHD, admitted, reaching no card (94.5 m).
NHD_MARSH_TAGS = {
    "gnis:fcode": "46600", "gnis:ftype": "SwampMarsh", "natural": "wetland",
    "nhd:com_id": "153039928", "nhd:fdate": "Wed Mar 28 00:00:00 PDT 2007",
    "source": "NHD", "wetland": "marsh",
}

# merion way/675572836: 151 m2, hand-mapped, 2.48 m from a green -- ADMITTED. See the module docstring.
MERION_MARSH_TAGS = {"natural": "wetland", "wetland": "marsh"}


def _osm_module():
    """fetch_osm and render_hole, imported together so the shared predicates are ONE object.

    `fetch_osm` holds `from render_hole import ...` at module level and tests/conftest.py drops
    `render_hole` (not `fetch_osm`) for every test in this directory, so importing them separately can
    leave fetch_osm bound to a previous copy of render_hole and turn an identity assertion into a
    comparison of two copies of one function. Same helper shape as test_r14_census._osm_module.
    """
    for m in ("config", "fetch_osm", "render_hole"):
        sys.modules.pop(m, None)
    try:
        import fetch_osm
        import render_hole
    except ImportError as e:                                    # pragma: no cover - env-dependent
        pytest.skip("fetch_osm/render_hole needs %r" % (getattr(e, "name", None) or e,))
    except SystemExit as e:                                     # pragma: no cover - env-dependent
        pytest.skip("cannot bind a course: %s" % e)
    return fetch_osm, render_hole


def _engine(slug):
    """(config, render_hole) bound to `slug`, for the corpus arms."""
    os.environ["COURSE"] = slug
    for m in ("config", "render_hole"):
        sys.modules.pop(m, None)
    import config
    import render_hole
    return config, render_hole


def _way(i, tags, geometry=None):
    return {"type": "way", "id": i, "tags": dict(tags),
            "geometry": list(geometry) if geometry else
            [{"lat": 37.62, "lon": -121.86}, {"lat": 37.6201, "lon": -121.8601},
             {"lat": 37.6201, "lon": -121.86}, {"lat": 37.62, "lon": -121.86}]}


# =============================================================================================
# 1. THE PREDICATE, by truth table
# =============================================================================================

def test_the_wetland_predicate_admits_hand_mapped_marsh_and_refuses_a_land_classification_tile():
    """One tag test, graded on the tags of every wetland this corpus actually holds.

    The three properties an audit note offered as candidate discriminators were each MEASURED before
    this table was written, and two of them do not work:

      * `wetland=*` SUBTYPE is ANTI-CORRELATED with the admit set. None of callippe's twelve carries
        one; both the polygons offered as counter-examples do (`wetland=marsh`). A subtype test would
        refuse the twelve and admit the tile.
      * OVERLAP WITH A GREEN OR FAIRWAY separates nothing. All 15 corpus wetlands overlap 0.0 m2 of
        green and 0.0 m2 of fairway, the FMMP tile included -- it lies BESIDE monarch-bay, not over it.
      * AREA separates the tile (1,745,827 m2 against a largest admit of 10,866) but nothing else, and
        an area cap alone would be inconsistent with how this engine already treats water: it draws
        `natural=water` polygons of 327,633 m2 (copper-valley) and 1,655,248 m2 (the-reserve) because
        those really are water. Size is a symptom of a landcover tile, not the reason it is wrong.

    What is left, and what is decisive, is that the tile carries the importing dataset's OWN label for
    the same polygon -- `description=other land`, `attribution=Farmland Mapping and Monitoring
    Program`, `acres=431.460542194` -- i.e. its tags say it is not wetland. The `wetland=*` escape
    keeps a polygon that a dataset positively classified AS wet, which is the rule-2 direction.
    """
    _, rh = _osm_module()
    for i, tags in enumerate(CALLIPPE_WETLAND_TAGS):
        assert rh.is_drawn_wetland(_way(1000 + i, tags)) is True, (
            "a hand-mapped wetland carrying only %s is refused -- these are the twelve callippe "
            "polygons nine shipped cards printed 0W over" % (tags,))
    assert rh.is_drawn_wetland(_way(2, FMMP_TILE_TAGS)) is False, (
        "the 431-acre farmland-classification tile is admitted; it paints monarch-bay 13, 14 and 15 "
        "blue over dry shoreline while its own tags say `description=other land`")
    assert rh.is_drawn_wetland(_way(3, NHD_MARSH_TAGS)) is True, (
        "a real NHD SwampMarsh is refused -- a refusal keyed on `source` alone would do this, and it "
        "is the omission direction rule 2 forbids")
    assert rh.is_drawn_wetland(_way(4, MERION_MARSH_TAGS)) is True, (
        "merion's 151 m2 greenside marsh is refused. It carries no import marker; it is 10.22 m from "
        "hole 17's played line (9.62 m from the centreline with end caps); when in doubt this book warns")

    # not our business: anything that is not natural=wetland at all
    for tags in ({"natural": "water"}, {"waterway": "stream"}, {"golf": "green"},
                 {"landuse": "meadow"}, {}):
        assert rh.is_drawn_wetland(_way(5, tags)) is False, (
            "%s is not a wetland and must not be answered for by this predicate" % (tags,))

    # the escape hatch is real: a classified polygon that ALSO asserts wetness is kept
    assert rh.is_drawn_wetland(_way(6, {"natural": "wetland", "wetland": "marsh",
                                        "description": "seasonal"})) is True, (
        "a polygon whose own subtype says `marsh` is refused because it also carries free text -- "
        "that turns a hazard into an omission on the strength of a note")
    # ...and each land-class key refuses on its own, so dropping one is a visible change
    for key, val in (("description", "other land"), ("landuse", "farmland"),
                     ("attribution", "Farmland Mapping and Monitoring Program"),
                     ("acres", "12.5")):
        assert rh.is_drawn_wetland(_way(7, {"natural": "wetland", key: val})) is False, (
            "`%s` no longer marks a land-classification polygon, so the FMMP tile is one tag edit "
            "from being drawn again" % key)


def test_the_fetch_and_the_renderer_share_one_definition_of_a_drawn_wetland():
    """Same rule the watercourse predicate is held to: the census is what says a lost one was lost.

    If the census counted a WIDER set than the map draws, a reply could delete a real marsh and gain a
    farmland tile without moving the number -- the defect already fixed twice on the water path (areas
    vs lines, then drawn lines vs culverts), reappearing one class over.
    """
    fo, rh = _osm_module()
    assert fo.is_drawn_wetland is rh.is_drawn_wetland, (
        "fetch_osm and render_hole hold different is_drawn_wetland objects, so the guard's unit and "
        "the drawn class can drift apart")
    assert fo.is_visible_watercourse is rh.is_visible_watercourse, \
        "the watercourse predicate stopped being shared while this change was made"


# =============================================================================================
# 2. THE FETCH ASKS FOR IT
# =============================================================================================

def _query_strings(path, func="main"):
    """Every string literal in `func`, as source text -- the Overpass queries it builds."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == func:
            out = []
            for n in ast.walk(fn):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    out.append(n.value)
                elif isinstance(n, ast.JoinedStr):
                    out.append("".join(p.value for p in n.values
                                       if isinstance(p, ast.Constant)
                                       and isinstance(p.value, str)))
            return out
    raise AssertionError("no %s() in %s" % (func, path))


def test_the_course_fetch_asks_overpass_for_the_wetland_the_cards_draw():
    """A class nothing requests is a class nothing can draw, and no guard can notice it is absent.

    Read off the query text rather than the network: what shipped was a query listing seven landcover
    classes and not this one, and the whole corpus's caches therefore hold zero wetland elements. Both
    passes are checked -- a wetland mapped as a MULTIPOLYGON RELATION is invisible the same way the 18
    valley-hi fairway relations were, and `_flatten_relations` can only flatten what was asked for.
    """
    qs = " ".join(_query_strings(os.path.join(ROOT, "fetch_osm.py")))
    assert 'way["natural"="wetland"]' in qs, (
        "fetch_osm.main() does not ask Overpass for wetland WAYS, so census() can never bucket one "
        "and render_hole can never draw one")
    assert 'relation["natural"="wetland"]' in qs, (
        "fetch_osm.main() does not ask for wetland RELATIONS, so a multipolygon marsh arrives as "
        "nothing at all -- the shape 18 valley-hi fairways went missing in")
    # the classes that were already there must still be, or this change traded one omission for another
    for clause in ('way["natural"="water"]', 'way["waterway"]', 'way["golf"]', 'way["building"]',
                   'way["natural"="wood"]', 'way["natural"="scrub"]', 'way["natural"="tree_row"]',
                   'way["landuse"="forest"]', 'node["natural"="tree"]'):
        assert clause in qs, "the course query lost %s" % clause


def _stub_fetch(tmp_path, monkeypatch, replies):
    """fetch_osm bound to `tmp_path` as its course dir, answering from `replies` instead of the wire.

    Keyed by a substring of the query, longest first, so `way["golf"="green"]` cannot be answered by
    the entry for `way["golf"]`. Nothing here reaches Overpass and nothing here writes under courses/.
    """
    import urllib.parse
    import urllib.request
    for m in ("config", "fetch_osm", "render_hole"):
        sys.modules.pop(m, None)
    import config
    import fetch_osm
    monkeypatch.setattr(config, "COURSE_DIR", str(tmp_path))
    seen = []

    class _R:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode()

    def _urlopen(req, timeout=None):
        q = urllib.parse.unquote(getattr(req, "full_url", None) or str(req))
        seen.append(q)
        for needle in sorted(replies, key=len, reverse=True):
            if needle in q:
                return _R(replies[needle])
        raise AssertionError("no canned reply for:\n%s" % q)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return fetch_osm, seen


def test_every_cache_the_fetch_commits_records_the_box_it_was_fetched_with(tmp_path, monkeypatch):
    """`tools/check_osm_bbox.py` cannot check a fetch box nothing recorded, and it was reading a NUMBER
    A PERSON CAN EDIT instead.

    The gate asks whether every hole's drawing corridor lies inside the box the cards' geometry was
    fetched with, and it took that box from `course.json`. Reproduced by the agent that fixed the gate
    side: a narrow declaration reported 15 holes drawing from outside the box, worst 164 m short at
    hole 17, and exit 1; widening ONLY the declaration -- `osm_geom.json` byte-identical, never
    re-fetched -- turned the same gate green over the same narrow cache. The declaration is the half of
    the remedy that costs nothing.

    So the writer records what it queried. All three files, because a cache annotated in one file and
    not another is a fetch box half established, and on the COMMIT path, because that is where this
    project puts anything that must not be left half-done.

    The SHAPE is a contract with another module and is asserted as one -- key name, four numbers, and
    `[south, west, north, east]`, which is course.json's order, Overpass's bbox-filter order and the
    order fetch_osm unpacks it in. A box recorded in a different order would be measured against with
    confidence, which is worse than no box.
    """
    def _ring(la, lo, d=0.0004):
        return [{"lat": la, "lon": lo}, {"lat": la, "lon": lo + d},
                {"lat": la + d, "lon": lo + d}, {"lat": la, "lon": lo}]

    def way(i, tags, la=38.20, lo=-121.30):
        return {"type": "way", "id": i, "tags": dict(tags), "geometry": _ring(la, lo)}

    # 18 greens, each with its OWN hole line running to it. One shared ring would leave every hole
    # bound to one green and _check_bindings refuses that before anything is written -- correctly.
    greens, holes = [], []
    for i in range(18):
        la, lo = 38.20 + i * 0.003, -121.30 + i * 0.003
        greens.append({"type": "way", "id": 400 + i, "tags": {"golf": "green"},
                       "geometry": _ring(la, lo)})
        holes.append({"type": "way", "id": 500 + i,
                      "tags": {"golf": "hole", "ref": str(i + 1)},
                      "geometry": [{"lat": la - 0.0020, "lon": lo - 0.0020},
                                   {"lat": la + 0.0002, "lon": lo + 0.0002}]})
    geom = {"version": 0.6, "elements": greens + holes}
    course = {"version": 0.6, "elements":
              [way(100 + i, {"golf": "tee"}, 38.20 + i * 0.003, -121.30 + i * 0.003)
               for i in range(4)]
              + [way(200, {"building": "yes"}), way(201, {"natural": "wetland"})]}
    rel = {"version": 0.6, "elements":
           [{"type": "relation", "id": 777, "tags": {"golf": "fairway"},
             "members": [{"type": "way", "ref": 900, "role": "outer"}]},
            {"type": "way", "id": 900, "geometry": _ring(38.20, -121.30)}]}

    fo, seen = _stub_fetch(tmp_path, monkeypatch, {
        'way["golf"="green"]': geom, 'relation["golf"]': rel, 'way["golf"]': course})
    fo.main()
    assert len(seen) == 3, "main() must make the geometry, course and relation passes: %s" % len(seen)

    declared = list(fo.config.COURSE["osm_bbox"])
    for name in ("osm_geom.json", "osm_course.json", "osm_relations.json"):
        p = os.path.join(str(tmp_path), name)
        assert os.path.exists(p), "main() did not commit %s" % name
        with open(p, encoding="utf-8") as fh:
            cache = json.load(fh)
        box = cache.get("query_bbox")
        assert isinstance(box, list) and len(box) == 4, (
            "%s records query_bbox as %r. tools/check_osm_bbox.py refuses anything that is not four "
            "numbers, and then measures the corridors against course.json's editable declaration "
            "instead" % (name, box))
        assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box), \
            "%s records a non-numeric query_bbox: %r" % (name, box)
        assert box == declared, (
            "%s records query_bbox %r but this course declares %r. Those must agree on a cache the "
            "fetch just wrote; a disagreement is the widened-but-never-re-fetched state the gate "
            "reports as drift" % (name, box, declared))
        # SWNE, not NESW or WSEN: the order is the contract, and a swapped box measures a real corridor
        # against the wrong ground with full confidence
        assert box[0] < box[2] and box[1] < box[3], (
            "%s records query_bbox %r, whose south is not below its north or whose west is not west "
            "of its east -- it is not [south, west, north, east]" % (name, box))
        # ...and the key must not have displaced anything a consumer reads
        assert isinstance(cache.get("elements"), list) and cache["elements"], \
            "%s lost its elements to the annotation" % name
    # one spelling of the key and of the order, called from both commit paths
    assert fo.QUERY_BBOX_KEY == "query_bbox", (
        "fetch_osm names the key %r; tools/check_osm_bbox.py reads 'query_bbox' and a mismatch leaves "
        "that gate red with no visible cause" % fo.QUERY_BBOX_KEY)
    src = open(os.path.join(ROOT, "fetch_osm.py"), encoding="utf-8").read()
    assert src.count("_stamped(") >= 3, (
        "the stamp is no longer reached from both commit paths through one helper -- two spellings of "
        "'the box we queried' is how one file ends up annotated and the other not")


def test_no_stored_cache_records_a_fetch_box_that_disagrees_with_its_declaration():
    """A recorded box that contradicts `course.json` means the widening happened and the re-fetch did
    not, which is the state the gate reports as drift and refuses to waive. Swept over the caches on
    disk so a course re-fetched with a stale declaration is caught here as well as there.

    Anti-vacuous: at least one cache must record a box, or this test is asserting nothing. Courses
    fetched before this round record none and are skipped rather than failed -- they are the gate's
    "unrecorded" verdict, which is its own finding with its own key, not this one.
    """
    recorded = 0
    for slug in _corpus():
        declared = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("osm_bbox")
        for name in ("osm_geom.json", "osm_course.json", "osm_relations.json"):
            p = os.path.join(ROOT, "courses", slug, name)
            if not os.path.exists(p):
                continue
            box = json.load(open(p)).get("query_bbox")
            if box is None:
                continue
            recorded += 1
            assert [float(v) for v in box] == [float(v) for v in declared], (
                "%s/%s was fetched with %r but course.json now declares %r -- the declaration was "
                "widened and the cache was never re-fetched, so the cards may draw from ground the "
                "fetch never requested" % (slug, name, box, declared))
    assert recorded, (
        "no cache under courses/ records the box it was fetched with, so this test proves nothing. "
        "Re-fetch a course with the current fetch_osm.py rather than deleting this bar")


# =============================================================================================
# 3. THE CENSUS AND THE SHRINK GUARD
# =============================================================================================

def test_the_wetland_census_counts_exactly_the_wetlands_a_card_draws():
    """Drawn in `wetland`, refused in `wetland_undrawn`, and nothing dropped from the accounting.

    Exactly the split `waterway` / `waterway_undrawn` already carries, for the reasons written there:
    letting the refused ones fall through to `other` would make a re-classified landcover tile a
    STRUCTURAL abort, and dropping them entirely is the silence that put 1,529 of the-reserve's 1,530
    buildings in `other`.
    """
    fo, _ = _osm_module()
    drawn = [_way(1 + i, t) for i, t in enumerate(CALLIPPE_WETLAND_TAGS)] \
        + [_way(50, NHD_MARSH_TAGS), _way(51, MERION_MARSH_TAGS)]
    undrawn = [_way(60, FMMP_TILE_TAGS),
               _way(61, {"natural": "wetland", "landuse": "farmland"})]
    c = fo.census(drawn + undrawn)
    assert c["wetland"] == len(drawn), (
        "census says %d drawn wetlands where the card draws %d: %s"
        % (c["wetland"], len(drawn), dict(c)))
    assert c["wetland_undrawn"] == len(undrawn), (
        "the refused wetlands are not in a bucket of their own: %s" % dict(c))
    assert sum(c.values()) == len(drawn) + len(undrawn), (
        "the census does not account for every element it was given (%s) -- a wetland that leaves the "
        "accounting reads as a lost feature of some other kind" % dict(c))
    # a wetland that is ALSO a building or a golf feature is bucketed where it already was
    assert fo.census([_way(70, {"natural": "wetland", "building": "yes"})])["building"] == 1
    assert fo.census([_way(71, {"natural": "wetland", "golf": "water_hazard"})])["water_hazard"] == 1
    # ...and a waterway carrying the tag stays a waterway, which is what the renderer draws it as
    assert fo.census([_way(72, {"natural": "wetland", "waterway": "stream"})])["waterway"] == 1


def test_a_lost_wetland_reaches_the_hazard_waiver_and_a_lost_landcover_tile_does_not():
    """Drawn hazard ink, so it is graded as drawn hazard ink -- by name, with no rarity exemption.

    `wetland` shipped in `VOLATILE_KINDS` for a key nothing could produce. Now that a card draws it in
    the same blue as a pond and counts it in the footer's W, it belongs where `water` is: a hazard kind
    with no tolerance and no rarity floor, because a course with one wetland is the course where
    losing it is invisible. The REFUSED ones are the mirror of `waterway_undrawn` -- volatile, not a
    hazard, because a mapper re-classifying a landcover tile is an OSM improvement and nothing draws
    or measures it.
    """
    fo, _ = _osm_module()
    assert "wetland" in fo.HAZARD_KINDS, (
        "wetland is not a hazard kind, so losing the only wetland on a course is waived by the tree "
        "flag or by nothing at all: %s" % sorted(fo.HAZARD_KINDS))
    assert "wetland" not in fo.VOLATILE_KINDS, (
        "wetland is still listed as churning, which hands a rare one a free loss: %s"
        % sorted(fo.VOLATILE_KINDS))
    assert "wetland_undrawn" in fo.VOLATILE_KINDS and "wetland_undrawn" not in fo.HAZARD_KINDS, (
        "the refused wetlands are graded as hazard ink or as structure; a re-classified landcover "
        "tile is neither: volatile=%s hazard=%s"
        % ("wetland_undrawn" in fo.VOLATILE_KINDS, "wetland_undrawn" in fo.HAZARD_KINDS))

    import tempfile
    keys = ("ALLOW_SHRINK", "ALLOW_HAZARD_SHRINK", "ALLOW_STRUCTURAL_SHRINK", "ALLOW_REBIND")
    held = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        with tempfile.TemporaryDirectory() as td:
            base = [_way(100 + i, {"golf": "green"}) for i in range(18)] \
                + [_way(200 + i, {"golf": "hole"}) for i in range(18)]
            wet = [_way(300 + i, {"natural": "wetland"}) for i in range(3)]
            tiles = [_way(400 + i, FMMP_TILE_TAGS) for i in range(3)]

            p = os.path.join(td, "osm_course.json")
            with open(p, "w") as fh:
                json.dump({"version": 0.6, "elements": base + wet + tiles}, fh)

            # an unchanged reply is silent
            fo._check_response({"version": 0.6, "elements": base + wet + tiles}, p,
                               "osm_course.json")
            # one wetland of three lost -> the HAZARD waiver, by name, with the counts
            with pytest.raises(SystemExit) as ei:
                fo._check_response({"version": 0.6, "elements": base + wet[:2] + tiles}, p,
                                   "osm_course.json")
            msg = str(ei.value)
            assert "wetland 3 -> 2" in msg, (
                "a lost wetland was accepted, or aborted without naming the loss: %s" % msg)
            assert "ALLOW_HAZARD_SHRINK" in msg, (
                "a lost wetland is drawn hazard ink; the abort must name the hazard waiver: %s" % msg)
            # ...and that waiver names what it accepted rather than just changing the exit code
            os.environ["ALLOW_HAZARD_SHRINK"] = "1"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                fo._check_response({"version": 0.6, "elements": base + wet[:2] + tiles}, p,
                                   "osm_course.json")
            out = buf.getvalue()
            assert "ALLOW_HAZARD_SHRINK" in out and "wetland 3 -> 2" in out, (
                "spending the hazard waiver over a lost wetland printed %r -- courses/ is gitignored, "
                "so this line is the only record the loss leaves" % out)
            # ...and an explicit off does not waive it
            os.environ["ALLOW_HAZARD_SHRINK"] = "0"
            with pytest.raises(SystemExit):
                fo._check_response({"version": 0.6, "elements": base + wet[:2] + tiles}, p,
                                   "osm_course.json")
            os.environ.pop("ALLOW_HAZARD_SHRINK", None)

            # a REFUSED wetland going away is not a hazard loss: 3 -> 2 of a rare volatile kind is
            # inside the rarity exemption, and nothing draws it
            fo._check_response({"version": 0.6, "elements": base + wet + tiles[:2]}, p,
                               "osm_course.json")
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# =============================================================================================
# 4. THE CARD
# =============================================================================================

def _mlat_mlon(la0):
    import geo
    return geo.mlat(la0), geo.mlon(la0)


def _dist_to_played_line(pt, line_em):
    """Metres from a point to the PLAYED stretch of a centreline, inf if it sees none of it.

    Written here rather than imported: the test's model of "how far is this from the hole" must not be
    the engine's own, or the test cannot disagree with it. Projections falling behind the first vertex
    or past the last do not count -- water in those end caps is not on the hole.
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


def _corpus():
    slugs = corpus_slugs()
    if not slugs:
        pytest.skip("per-course data is gitignored; nothing to measure")
    return slugs


def test_the_water_corridor_this_file_measures_against_is_the_renderers_own():
    """A test carrying its own copy of a threshold cannot notice the engine changing it."""
    _, rh = _osm_module()
    assert rh.CORRIDOR_M["water"] == WATER_CORRIDOR_M, (
        "render_hole draws water at %s m, this file measures at %s"
        % (rh.CORRIDOR_M["water"], WATER_CORRIDOR_M))


def test_a_wetland_the_played_line_reaches_is_never_printed_as_no_hazard():
    """THE RULE: never omit a hazard the golfer can reach. Swept over every cache on disk.

    Every `natural=wetland` polygon a card should draw and whose boundary comes within the water
    corridor of the played line must be COUNTED on the card and FILLED on the map. The count and the
    fill are checked separately because the shipped defect had neither and either one alone would let
    the other regress -- a card can print a number over blank ground, and it can draw ink and print a
    zero.

    THE COUNT AND THE FILL BOTH MOVED CLASS, and the rule did not. This test was
    `..._is_never_printed_as_no_water` and it read `info["water_hazards"]` and `fill="#a9d3ef"`: marsh was
    drawn in the water blue and counted in the footer's W. That was a false description a reader found on
    the ground -- callippe holds ONE `natural=water` polygon and its book printed 39 W across 18 cards,
    with 2,309 tree markers standing in the blue. So the ink is now render_hole.PENALTY_FILL, the not-water
    grey, and the count is `info["wetlands"]`. What this test asserts is unchanged and is the part that
    matters: a reachable marsh is DRAWN and is COUNTED. Only the ink and the key it is counted under moved,
    and the requirement got no weaker -- a wetland drawn in the water blue would now FAIL here, because the
    grey fill would be missing.

    BOTH INK CONSTANTS ARE READ FROM THE ENGINE, never frozen here, for test_r18_merion's stated reason:
    a hex typed into a test file is a second copy of a value that has already been retuned once.

    A course whose cache holds no wetland contributes nothing and that is not silently a pass: the
    witness count below refuses to let this test claim anything if the corpus stopped holding a
    reachable wetland at all.
    """
    omitted, reachable, examined, errors = [], 0, 0, []
    for slug in _corpus():
        cfg, rh = _engine(slug)
        import geo
        fill = 'fill="%s"' % rh.PENALTY_FILL
        try:
            course, geom = rh.load()
            loc = cfg.COURSE.get("location") or {}
            lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
        except Exception as e:                                   # pragma: no cover - env-dependent
            errors.append((slug, repr(e)[:120]))
            continue
        wet = [g for g in course if rh.is_drawn_wetland(g) and (g.get("geometry") or [])]
        if not wet:
            continue
        for hn in cfg.HOLE_NUMS:
            hole = lines.get(hn)
            if hole is None:
                errors.append((slug, hn, "no centreline"))
                continue
            line = hole["geometry"]
            la0 = sum(q["lat"] for q in line) / len(line)
            lo0 = sum(q["lon"] for q in line) / len(line)
            mla, mlo = _mlat_mlon(la0)

            def em(la, lo, _mla=mla, _mlo=mlo, _la0=la0, _lo0=lo0):
                return ((lo - _lo0) * _mlo, (la - _la0) * _mla)
            line_em = [em(q["lat"], q["lon"]) for q in line]
            near = []
            for g in wet:
                d = min(_dist_to_played_line(em(p["lat"], p["lon"]), line_em)
                        for p in g["geometry"])
                if d < WATER_CORRIDOR_M:
                    near.append((g.get("id"), round(d, 2)))
            if not near:
                continue
            reachable += len(near)
            try:
                svg, info = rh.render_hole(hn, cfg.HOLES)
            except Exception as e:                              # pragma: no cover - env-dependent
                errors.append((slug, hn, repr(e)[:120]))
                continue
            examined += 1
            if info["wetlands"] < len(near) or svg.count(fill) < len(near):
                omitted.append((slug, hn, sorted(near, key=lambda r: r[1]),
                                info["wetlands"], svg.count(fill), info["waters"]))
    assert not errors, "%d failure(s) gathering the corpus: %s" % (len(errors), errors[:5])
    assert reachable >= 12, (
        "only %d wetland/hole pairs come within %g m of a played line in the whole corpus -- the "
        "witness found nothing to check, so this test proves nothing. Callippe alone had 12 wetlands "
        "on 16 of its 18 holes before this round; if its cache has not been re-fetched, re-fetch it "
        "rather than deleting this bar" % (reachable, WATER_CORRIDOR_M))
    assert not omitted, (
        "%d card(s) omit wetland the played line reaches -- (course, hole, [(way, metres off the "
        "played line)], counted wetlands, drawn not-water fills, printed W): %s"
        % (len(omitted), omitted[:8]))


def _renode(pts, k):
    """`k`-1 extra vertices ON each edge: the identical outline, differently clicked."""
    out = []
    for a, b in zip(pts, pts[1:]):
        out.append(a)
        for i in range(1, k):
            f = i / k
            out.append({"lat": a["lat"] + (b["lat"] - a["lat"]) * f,
                        "lon": a["lon"] + (b["lon"] - a["lon"]) * f})
    out.append(pts[-1])
    return out


def test_a_re_noded_wetland_polygon_does_not_change_what_the_card_prints():
    """A wetland runs the same selector water does, so it inherits the same invariant.

    The selector is an OR of `frac_len_within(...) >= 0.35` and a segment reach test, both closed-form
    over the boundary, so inserting vertices ON the boundary must move nothing. This is not a
    hypothetical class: a VERTEX-fraction test moved the printed water count on four corpus cards at
    one noding density and a different four at another, which is why the length measure exists. A
    wetland admitted through a different code path would not be covered by that test, since it selects
    on `natural=water` and golf tags only.

    THE TUPLE HAD TO FOLLOW THE INK, or this test would have gone quietly vacuous about its own subject.
    It compared `(waters, water_hazards, count of fill="#a9d3ef")`, which is what a wetland used to move.
    Wetland is now drawn in the not-water grey and counted under `wetlands` (render_hole.holds_open_water
    is the split), so re-noding one CANNOT move any of those three -- the assertion would have held for a
    reason that has nothing to do with noding, on a test named for wetland. The wetland keys are measured
    now, and the water keys are KEPT alongside: re-noding a marsh must move nothing at all, so the
    stronger tuple is the honest one and it also catches a marsh leaking back into the blue.
    """
    moved, added, examined = [], 0, 0
    marked = [0, 0]                        # [wetlands counted, grey fills drawn] over the WHOLE corpus
    for slug in _corpus():
        cfg, rh = _engine(slug)
        grey = 'fill="%s"' % rh.PENALTY_FILL
        try:
            course, _ = rh.load()
        except Exception as e:                                  # pragma: no cover - env-dependent
            pytest.skip("%s: %r" % (slug, e))
        if not any(rh.is_drawn_wetland(g) and len(g.get("geometry") or []) > 1 for g in course):
            continue

        def shot(hn, _rh=rh, _cfg=cfg, _grey=grey):
            svg, info = _rh.render_hole(hn, _cfg.HOLES)
            return (info["wetlands"], svg.count(_grey),
                    info["waters"], info["water_hazards"], svg.count('fill="#a9d3ef"'))
        plain = {hn: shot(hn) for hn in cfg.HOLE_NUMS}
        for p in plain.values():
            marked[0] += p[0]
            marked[1] += p[1]
        orig = rh.load
        try:
            for k in (2, 5):
                def patched(_k=k):
                    c, g = orig()
                    out = []
                    for e in c:
                        pts = e.get("geometry") or []
                        if rh.is_drawn_wetland(e) and len(pts) > 1:
                            e = dict(e, geometry=_renode(pts, _k))
                        out.append(e)
                    return out, g
                rh.load = patched
                grew = sum(len(e.get("geometry") or []) for e in patched()[0]) \
                    - sum(len(e.get("geometry") or []) for e in course)
                added += grew
                for hn in cfg.HOLE_NUMS:
                    got = shot(hn)
                    examined += 1
                    if got != plain[hn]:
                        moved.append((slug, hn, "k=%d" % k, plain[hn], got))
        finally:
            rh.load = orig
    if not examined:
        pytest.skip("no cache on disk holds a drawn wetland yet")
    assert added > examined, (
        "the re-noding inserted only %d vertices over %d renderings -- it is not re-noding anything"
        % (added, examined))
    # ...and the perturbation has to be able to MOVE the keys it grades, or "nothing moved" says nothing.
    # Counted over the WHOLE corpus and not the last course examined: the-reserve holds a drawn wetland
    # that reaches no card, so it enters this loop and contributes zero marks, and a per-course witness
    # taken from whichever course happened to be last is the vacuous check this bar exists to refuse.
    # Measured: callippe draws 29 wetland marks over 14 cards and merion 3 over 3.
    assert marked[0] >= 12 and marked[1] >= 12, (
        "the corpus counted %d wetland(s) and drew %d not-water fill(s) across every card of every course "
        "that holds a drawn wetland, so the two keys this test was re-pointed at are near zero and the "
        "comparison proves little. 32 and 32 were measured; re-measure rather than lowering this"
        % (marked[0], marked[1]))
    assert not moved, (
        "%d card(s) print something different when the SAME wetland is re-noded -- (course, hole, "
        "noding, before, after) with the tuple being (wetlands, grey fills, waters, water_hazards, "
        "blue fills): %s" % (len(moved), moved[:8]))


def _tile_beside(line, standoff_m, span_m):
    """A rectangle lying `standoff_m` off `line`'s chord and `span_m` deep and long.

    The FMMP tile's own shape is 223 nodes and lives in OSM, not in this repository; what is
    reproduced here are the two measured properties that make it reach a card -- it comes 23.5 m from
    monarch-bay hole 15's centreline, and it is 1,745,827 m2, i.e. roughly 1,320 m on a side. A
    rectangle at that standoff and that scale exercises the same selector branch (the reach half of
    `waters`) on whatever course is built here, which is what this test is for. It is not a claim
    about the tile's outline.
    """
    import geo
    la0 = sum(p["lat"] for p in line) / len(line)
    lo0 = sum(p["lon"] for p in line) / len(line)
    mla, mlo = geo.mlat(la0), geo.mlon(la0)
    (ax, ay), (bx, by) = ((line[0]["lon"] - lo0) * mlo, (line[0]["lat"] - la0) * mla), \
                         ((line[-1]["lon"] - lo0) * mlo, (line[-1]["lat"] - la0) * mla)
    ux, uy = bx - ax, by - ay
    L = math.hypot(ux, uy) or 1.0
    ux, uy = ux / L, uy / L
    px, py = uy, -ux                                    # unit normal to the chord
    ring = []
    for along, out in ((-span_m / 2, standoff_m), (span_m / 2, standoff_m),
                       (span_m / 2, standoff_m + span_m), (-span_m / 2, standoff_m + span_m),
                       (-span_m / 2, standoff_m)):
        x = ax + ux * (L / 2 + along) + px * out
        y = ay + uy * (L / 2 + along) + py * out
        ring.append({"lat": la0 + y / mla, "lon": lo0 + x / mlo})
    return ring


def test_a_land_classification_tile_paints_no_card_even_where_it_reaches_one():
    """The refusal, wired all the way to the card rather than only to the predicate.

    Two arms over the SAME geometry, and both are needed: with the FMMP tile's tags it must change no
    card, and with the tags stripped to a bare `natural=wetland` it must change at least one. Without
    the second arm a predicate that refused every wetland would pass this, and without the first the
    fix would be untested where it matters -- on the page.

    THE KEY IT WATCHES IS `wetlands` AND NOT `water_hazards`, because that is where an admitted wetland
    now lands: the class is drawn in the not-water grey and counted separately from the footer's W (see
    render_hole.holds_open_water). Watching `water_hazards` would have made the SECOND arm impossible to
    satisfy -- a bare `natural=wetland` cannot move a water count any more -- so this test would have
    started failing honestly, which is how the re-point was found rather than assumed.
    """
    hit = []
    for slug in _corpus():
        cfg, rh = _engine(slug)
        import geo
        try:
            _, geom = rh.load()
            loc = cfg.COURSE.get("location") or {}
            lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
        except Exception as e:                                  # pragma: no cover - env-dependent
            pytest.skip("%s: %r" % (slug, e))
        hn = cfg.HOLE_NUMS[0]
        ring = _tile_beside(lines[hn]["geometry"], 23.5, 1320.0)
        orig = rh.load

        def marks(_rh=rh, _cfg=cfg):
            """Both halves of "this tile reached the paper": the count AND the ink."""
            out = {}
            for h in _cfg.HOLE_NUMS:
                svg, info = _rh.render_hole(h, _cfg.HOLES)
                out[h] = (info["wetlands"], svg.count('fill="%s"' % _rh.PENALTY_FILL))
            return out
        try:
            base = marks()
            tile = {"type": "way", "id": -9001, "tags": dict(FMMP_TILE_TAGS), "geometry": ring}
            rh.load = lambda _o=orig, _t=tile: (_o()[0] + [_t], _o()[1])
            tagged = marks()
            bare = dict(tile, tags={"natural": "wetland"})
            rh.load = lambda _o=orig, _b=bare: (_o()[0] + [_b], _o()[1])
            stripped = marks()
        finally:
            rh.load = orig
        assert tagged == base, (
            "%s: a farmland-classification tile put hazard ink or a hazard count on hole(s) %s -- those "
            "cards would mark dry shoreline as ground a ball is lost in"
            % (slug, [h for h in base if tagged[h] != base[h]]))
        painted = [h for h in base if stripped[h] != base[h]]
        assert painted, (
            "%s: the same shape with a bare natural=wetland tag also changed nothing, so this course "
            "cannot witness the refusal -- widen the fixture rather than deleting the case" % slug)
        hit.append((slug, painted))
    assert hit, "no course was examined, so this test proves nothing"


# =============================================================================================
# 5. THE TREE WAIVER IN THE SAME MODULE
# =============================================================================================

def _bare_allow_reads(path):
    """Every `os.environ[...]`/.get() read of an ALLOW_ key in `path`, by AST.

    By AST and not by regex: this file's own prose names the pattern it forbids, and a text scan over
    the module would also hit the sentence in a docstring that describes it.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "get" and isinstance(n.func.value, ast.Attribute) \
                and n.func.value.attr == "environ":
            args = n.args
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) \
                and n.value.attr == "environ":
            args = [n.slice]
        else:
            continue
        for a in args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                    and a.value.startswith("ALLOW_"):
                out.append((a.value, n.lineno))
    return out


def test_render_hole_reads_its_tree_waiver_through_the_shared_env_on():
    """`=0`, `=false` and `=no` WAIVED the guard, and then the NOTE lied about what was set.

    `if not os.environ.get("ALLOW_OSM_TREES")` -- a non-empty string is truthy, so every spelling a
    person reaches for to explicitly DISABLE the waiver turned it on, and the next line printed
    "NOTE: ALLOW_OSM_TREES set" over an operator who had written 0. What the guard prevents, in its
    own words: 25 markers instead of 5086 on Merion, so a tree-lined corridor printed as open ground
    while the legend still promised trees.

    IDENTITY, not a re-spelling: the helper must be the SAME OBJECT lidar_coverage defines, because a
    copy satisfies every behavioural table written here and can still drift. Eight hand-written copies
    of one off-vocabulary is how narrowing a tuple turns an explicit off into a waiver in one module
    and nowhere else.
    """
    import lidar_coverage
    _, rh = _osm_module()
    bare = _bare_allow_reads(os.path.join(ROOT, "render_hole.py"))
    assert not bare, (
        "render_hole.py reads %d acknowledgement key(s) for bare truthiness: %s. A non-empty string "
        "is truthy, so ALLOW_X=0 / =false / =no WAIVE the guard they name" % (len(bare), bare))
    with open(os.path.join(ROOT, "render_hole.py"), encoding="utf-8") as fh:
        defines = [n.name for n in ast.walk(ast.parse(fh.read()))
                   if isinstance(n, ast.FunctionDef)]
    assert "_env_on" not in defines, (
        "render_hole.py now defines its own _env_on -- import lidar_coverage's, as fetch_osm.py and "
        "tools/verify_elevation.py do")
    assert getattr(rh, "_env_on", None) is lidar_coverage._env_on, (
        "render_hole._env_on is not lidar_coverage._env_on, so the two spellings of 'off' can drift")


def _trees_guard(rh, tmp_path, monkeypatch, value):
    """Run `_lidar_trees` against a course dir with LAZ and no trees_lidar.json. -> (raised, stdout)."""
    monkeypatch.setattr(rh, "DIR", str(tmp_path), raising=False)
    import config
    monkeypatch.setattr(config, "COURSE_DIR", str(tmp_path))
    os.makedirs(os.path.join(tmp_path, "laz"), exist_ok=True)
    with open(os.path.join(tmp_path, "laz", "t.laz"), "wb") as fh:
        fh.write(b"LASF")
    if value is None:
        monkeypatch.delenv("ALLOW_OSM_TREES", raising=False)
    else:
        monkeypatch.setenv("ALLOW_OSM_TREES", value)
    rh._LIDAR_TREES = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rh._lidar_trees()
        return False, buf.getvalue()
    except SystemExit:
        return True, buf.getvalue()
    finally:
        rh._LIDAR_TREES = None


def test_an_explicit_off_does_not_waive_the_sparse_tree_guard_and_no_note_claims_it_did(
        tmp_path, monkeypatch):
    """The behaviour behind the identity: run the guard through the off-vocabulary and the on one.

    The NOTE is graded too, in both directions. A waiver that is spent must say so (every other key in
    this project prints a WARNING or a NOTE), and a waiver that is NOT spent must not print a line
    saying it was -- which is the half that was false: `ALLOW_OSM_TREES=0` both waived the guard and
    announced itself as set.

    The vocabulary is NOT re-listed here beyond a core that cannot move. The last loop drives a spread
    of values -- including the ones that have migrated between the two sides, and the trailing
    whitespace a heredoc leaves -- through `_env_on` itself and requires the guard to agree with it
    value for value. That pins "this key reads the shared vocabulary" without keeping a second copy of
    what the vocabulary says, which is the failure mode the shared helper exists to prevent.
    """
    import lidar_coverage
    _, rh = _osm_module()
    raised, out = _trees_guard(rh, tmp_path, monkeypatch, None)
    assert raised, "the guard does not fire at all with LAZ present and no trees_lidar.json"
    assert "ALLOW_OSM_TREES set" not in out, "the NOTE printed with the key unset: %r" % out

    for v in OFF_CORE:
        raised, out = _trees_guard(rh, tmp_path, monkeypatch, v)
        assert raised, (
            "ALLOW_OSM_TREES=%r WAIVED the guard. That is the spelling an operator uses to disable it, "
            "and the cost is a tree-lined corridor printed as open ground under a legend that "
            "promises trees" % v)
        assert "ALLOW_OSM_TREES set" not in out, (
            "ALLOW_OSM_TREES=%r did not waive the guard but the build printed %r" % (v, out))
    for v in ON_CORE:
        raised, out = _trees_guard(rh, tmp_path, monkeypatch, v)
        assert not raised, "ALLOW_OSM_TREES=%r did not waive the guard" % v
        assert "ALLOW_OSM_TREES set" in out, (
            "ALLOW_OSM_TREES=%r waived the guard and printed %r -- a waiver changes the exit code, it "
            "must never hide the finding" % (v, out))

    for v in VOCABULARY_PROBES:
        monkeypatch.setenv("ALLOW_OSM_TREES", v)
        want_on = lidar_coverage._env_on("ALLOW_OSM_TREES")
        raised, out = _trees_guard(rh, tmp_path, monkeypatch, v)
        assert raised is (not want_on), (
            "ALLOW_OSM_TREES=%r: the shared vocabulary reads it as %s, the guard behaved as %s. This "
            "key is not being read through lidar_coverage._env_on"
            % (v, "ON" if want_on else "OFF", "OFF" if raised else "ON"))
        assert ("ALLOW_OSM_TREES set" in out) is want_on, (
            "ALLOW_OSM_TREES=%r: the printed NOTE disagrees with what the key means (%r)" % (v, out))


# =============================================================================================
# 6. THE FIGURES THIS FILE PUBLISHES ARE DERIVED, NOT TYPED
# =============================================================================================

def test_the_wetland_figures_in_this_file_are_measured_against_the_caches_on_disk():
    """The module docstring publishes counts. Re-derive them, so a stale sentence fails rather than
    reassures.

    Only the figures this file can measure WITHOUT the wire are graded: the number of drawn wetlands
    callippe's cache holds and how many of its holes have one inside the water corridor. The
    off-corpus figures (areas, the FMMP tile's acreage, merion's 2.48 m) are recorded with their
    method in the docstring and are not re-measurable here.
    """
    import re
    slugs = _corpus()
    doc = sys.modules[__name__].__doc__
    m = re.search(r"\*\*(\d+)\*\* `natural=wetland` ways inside its fetch box", doc)
    assert m, "the module docstring no longer states callippe's wetland count in the expected shape"
    want_n = int(m.group(1))
    m2 = re.search(r"\*\*(\d+) of its 18\*\* holes have\s+one within", re.sub(r"\s+", " ", doc)) \
        or re.search(r"\*\*(\d+) of its 18\*\* holes", re.sub(r"\s+", " ", doc))
    assert m2, "the module docstring no longer states how many callippe holes a wetland reaches"
    want_holes = int(m2.group(1))

    callippe = [s for s in slugs if s.startswith("callippe")]
    if not callippe:
        pytest.skip("callippe is not built here")
    cfg, rh = _engine(callippe[0])
    import geo
    course, geom = rh.load()
    wet = [g for g in course if rh.is_drawn_wetland(g) and (g.get("geometry") or [])]
    assert len(wet) == want_n, (
        "this file says callippe holds %d drawn wetlands; its cache holds %d. Re-fetch it, or "
        "re-measure the sentence" % (want_n, len(wet)))
    loc = cfg.COURSE.get("location") or {}
    lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
    n = 0
    for hn in cfg.HOLE_NUMS:
        line = lines[hn]["geometry"]
        la0 = sum(q["lat"] for q in line) / len(line)
        lo0 = sum(q["lon"] for q in line) / len(line)
        mla, mlo = _mlat_mlon(la0)
        line_em = [((q["lon"] - lo0) * mlo, (q["lat"] - la0) * mla) for q in line]
        # the UNCLIPPED distance, which is what "within the corridor" means as a property of the
        # ground -- the played-line clip is a drawing rule and is measured separately above
        best = min(min(math.hypot(*_nearest(((p["lon"] - lo0) * mlo, (p["lat"] - la0) * mla),
                                            line_em))
                       for p in g["geometry"]) for g in wet)
        if best < WATER_CORRIDOR_M:
            n += 1
    assert n == want_holes, (
        "this file says a wetland lies within %g m of %d of callippe's 18 holes; the cache measures "
        "%d" % (WATER_CORRIDOR_M, want_holes, n))


def _nearest(pt, line_em):
    """(dx, dy) from `pt` to the nearest point of the polyline, end caps included."""
    x, y = pt
    best = None
    for i in range(len(line_em) - 1):
        ax, ay = line_em[i]
        bx, by = line_em[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        v = (x - (ax + t * dx), y - (ay + t * dy))
        if best is None or math.hypot(*v) < math.hypot(*best):
            best = v
    return best
