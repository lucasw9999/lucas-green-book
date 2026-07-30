#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Regression tests for every defect three adversarial review rounds found in the yardage-tick and
tree work. Each test names the defect it locks down, so a future change that reintroduces one fails
here instead of on a card in a junior's pocket.

Design notes:
  * Pure-function tests (synthetic geometry, source scans) always run.
  * Corpus tests need per-course data, which is gitignored -- they SKIP on a fresh clone rather
    than fail. That keeps the suite honest: a skip is visibly not a pass.
  * These are checks on the RENDERED OUTPUT wherever possible. Several of the bugs below were
    originally "verified" with a script that re-implemented the code under test, and the circular
    check could not fail. Measuring the artifact is the point.

Run:  python3 -m pytest tests/ -q

MUTATION TESTING NOTE: clear __pycache__ before each run. A stale
__pycache__/<module>.cpython-*.pyc can be imported in place of restored source, which makes a
mutation test report the OPPOSITE of the truth -- it cost an hour here, first appearing to show that
the contour test could not detect a broken interpolation when in fact it could. Always confirm the
mutation applied (assert the old string was present) AND that the module you import reflects it.
"""
import glob
import json
import math
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIMIT_IN_PER_5YD = 0.375        # USGA Clarification 4.3a/1 scale cap: 3/8 in : 5 yd == 1:480
DIGIT_EM = 0.556                # Helvetica/Arial Bold digit advance
R_LAT = 111320.0


def _courses():
    """Course slugs that have the geometry needed to render a hole map.

    Underscore-prefixed folders are scratch (staging, the cold-build test) and are skipped so a
    transient directory cannot silently widen or narrow what the corpus tests measure."""
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        # require EVERY file render_hole.load() reads. Requiring only osm_geom.json admitted
        # half-built dirs whose holes then failed to render and were silently swallowed.
        need = ("osm_geom.json", "osm_course.json")
        if all(os.path.exists(os.path.join(ROOT, "courses", slug, f)) for f in need):
            out.append(slug)
    return out


# Floors are derived from the corpus actually present, never hardcoded to this machine's 12 courses.
# Absolute floors (190 holes / 700 labels) made the suite FAIL for anyone who had built one or two
# courses -- punishing a user for having less data, which is the same defect as the fresh-clone
# failures fixed in 8ea982f and dd57ca2.
_EXPECTED_HOLES = None


def expected_holes():
    """Total holes across the present corpus. Computed lazily and cached: computing it at import
    time would depend on CORPUS and _engine being defined above it, which is a needless ordering
    constraint in a file that other people will edit."""
    global _EXPECTED_HOLES
    if _EXPECTED_HOLES is None:
        n = 0
        for slug in CORPUS:
            try:
                cfg, _rh = _engine(slug)
                n += len(cfg.HOLE_NUMS)
            except Exception:
                pass
        _restore_course(CORPUS[0] if CORPUS else None)
        _EXPECTED_HOLES = n
    return _EXPECTED_HOLES


# Calibrated against the WEAKEST real course, not the corpus average. bay-view -- which is also the
# course a_course() picks -- runs 3.94 labels/hole and only 2.22 PAIRS/hole, because render_hole
# legitimately drops the from-tee number where the OSM centreline does not reach the back tee (7 of
# its 18 holes). Floors of 3.0 and 2.5 therefore failed the suite for anyone whose only built course
# was bay-view: the same machine-pinned-calibration defect as the five absolute floors removed in
# 40623b4, one level down.
MIN_LABELS_PER_HOLE = 2.5               # weakest real course: 3.94
MIN_PAIRS_PER_HOLE = 1.5                # weakest real course: 2.22


def _assert_examined(holes, labels, errors, what, per_hole=MIN_LABELS_PER_HOLE):
    """Corpus tests must prove they looked at something.

    Every corpus test used to swallow per-hole render failures with `except Exception: continue`
    and assert nothing about coverage, so making render_hole raise turned the whole file into
    "5 passed in 0.04s" -- a green suite that had examined nothing at all."""
    assert not errors, f"{what}: {len(errors)} hole(s) failed to render: {errors[:5]}"
    want = expected_holes()
    assert want > 0, "no holes discoverable in the corpus -- nothing could be examined"
    assert holes == want, \
        f"{what}: examined {holes} holes but {want} are present -- holes were skipped"
    floor = int(per_hole * expected_holes())
    assert labels >= floor, f"{what}: only saw {labels} labels over {holes} holes (expected >= {floor})"


def _restore_course(prev):
    """Point COURSE back at something that exists after a synthetic course is torn down."""
    if prev is not None:
        os.environ["COURSE"] = prev
    elif CORPUS:
        os.environ["COURSE"] = CORPUS[0]
    else:
        os.environ.pop("COURSE", None)
    for m in ("config", "render_hole", "render_green", "fetch_trees"):
        sys.modules.pop(m, None)


def _engine(slug):
    """Import config/render_hole bound to one course (they read the COURSE env var at import)."""
    for m in ("config", "render_hole", "render_green"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config
    import render_hole
    return config, render_hole


def _mlon(lat):
    return 111320.0 * math.cos(math.radians(lat))


CORPUS = _courses()
needs_corpus = pytest.mark.skipif(not CORPUS, reason="per-course data is gitignored; nothing to measure")


@pytest.fixture(autouse=True)
def _bind_a_course():
    """Bind COURSE for every test.

    Nine test sites import render_green or config without binding COURSE, so they inherited whatever
    an earlier test left -- or, run singly, config.py's hardcoded default. That default happens to be
    built on this machine, so the crash was invisible here: on a tree without
    the-reserve-at-spanos-park, `pytest -k contours_join` died with SystemExit and looked like a real
    defect. Binding it here makes single-test and randomised-order runs behave like a full run."""
    if CORPUS and not os.environ.get("COURSE"):
        os.environ["COURSE"] = CORPUS[0]
    yield


def a_course():
    """One built course, or SKIP.

    Bare `CORPUS[0]` raised IndexError on a fresh clone -- a FAILING suite for a stranger who had
    done nothing wrong. That happened four separate times in this file (8ea982f, dd57ca2, and twice
    more), so the indexing lives here once, guarded, instead of at every call site."""
    if not CORPUS:
        pytest.skip("per-course data is gitignored; nothing to measure")
    return CORPUS[0]


# ---------------------------------------------------------------------------
# Pure-function / source tests -- always run
# ---------------------------------------------------------------------------
def test_no_homoglyphs_in_printed_strings():
    """Round 1: two U+0434 CYRILLIC SMALL LETTER DE shipped as 'yd' on the instruction card of
    all 11 books. Only the em-dash is allowed to be non-ASCII in the engine sources."""
    allowed = {0x2014}          # EM DASH
    bad = []
    for f in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        src = open(f, encoding="utf-8").read()
        for i, ch in enumerate(src):
            if ord(ch) > 127 and ord(ch) not in allowed:
                bad.append((os.path.basename(f), src[:i].count("\n") + 1, hex(ord(ch))))
    assert not bad, f"non-ASCII characters that would print as homoglyphs: {bad}"


def test_overpass_reply_validation_refuses_destructive_replies(tmp_path):
    """Round 3 follow-up: Overpass signals a timeout with HTTP 200 + a remark + a short element
    list. It parses and has the right shape, so it used to be written straight over a good cache,
    silently rebinding holes to the wrong greens."""
    slug = a_course()
    os.environ["COURSE"] = slug
    for m in ("config", "fetch_osm"):
        sys.modules.pop(m, None)
    import fetch_osm

    good = {"version": 0.6, "elements": [
        {"type": "way", "id": i, "tags": {"golf": "green"}, "geometry": [{"lat": 1.0, "lon": 2.0}]}
        for i in range(20)]}
    cache = tmp_path / "osm_geom.json"
    cache.write_text(json.dumps(good))

    fetch_osm._check_response(good, str(cache), "osm_geom.json")      # complete -> accepted

    # Each case must isolate ONE guard. Previously every case was also short, so the shrink check
    # caught them all and the remark and shape checks were dead weight the test could not detect.
    destructive = {
        # remark present, element list FULL -> only the remark check can refuse this
        "remark, no shrink":  {"version": 0.6, "remark": "runtime error: Query timed out",
                               "elements": good["elements"]},
        # right length, wrong type -> only the shape check can refuse this
        "elements not a list": {"version": 0.6, "elements": "x" * 20},
        "elements missing":    {"version": 0.6},
        # no remark, correct shape, collapsed count -> only the shrink check can refuse this
        "silent partial":      {"version": 0.6, "elements": good["elements"][:3]},
        "silent empty":        {"version": 0.6, "elements": []},
    }
    for name, reply in destructive.items():
        with pytest.raises(SystemExit):
            fetch_osm._check_response(reply, str(cache), "osm_geom.json")
        assert json.loads(cache.read_text()) == good, f"{name}: cache must be left untouched"


def test_lidar_project_grouping_has_no_title_fallback():
    """PR #14 fixed grouping by title: TNM titles carry the per-tile ID, so every tile became its
    own 'project', coverage collapsed to one tile and most greens went unfed. The fallback that
    caused it must not come back -- an unexpected URL has to stop the run."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    import fetch_lidar

    ok = {"downloadURL": "https://x/Projects/CA_UpperSouthAmerican_Eldorado_2019_B19/LAZ/a.laz",
          "title": "USGS_LPC_CA_Eldorado_2019_B19_64992142.laz"}
    assert fetch_lidar._project_of(ok) == "CA_UpperSouthAmerican_Eldorado_2019_B19"
    for bad in ({"downloadURL": "https://x/LAZ/a.laz", "title": "USGS_LPC_..._649.laz"},
                {"title": "USGS_LPC_..._649.laz"}):
        with pytest.raises(SystemExit):
            fetch_lidar._project_of(bad)


def test_lidar_legacy_bucket_is_not_treated_as_one_project():
    """USGS nests older surveys under a BUCKET, not a project:
        .../Projects/CA_AlamedaCounty_2021_B21/LAZ/...        (modern)
        .../Projects/legacy/ARRA_CA_SANFRANCOAST_2010/LAZ/... (older)
    Taking the segment straight after "Projects" made every legacy survey one pseudo-project called
    "legacy". Measured live on the Monarch Bay bbox: 19 tiles from ARRA_CA_SANFRANCOAST_2010,
    CA_ALAMEDACO_2006 and CA_SANFRANBAY_2004 collapsed into a single 19-tile "legacy" whose
    footprint then BEAT the real 2021 survey on coverage -- so a rebuild would have mixed three
    surveys flown years apart into one green surface."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    import fetch_lidar

    mk = lambda u: {"downloadURL": u, "title": "USGS_LPC_x_000267.laz"}
    got = {fetch_lidar._project_of(mk(u)) for u in (
        "https://x/Projects/legacy/ARRA_CA_SANFRANCOAST_2010/LAZ/a.laz",
        "https://x/Projects/legacy/CA_ALAMEDACO_2006/LAZ/b.laz",
        "https://x/Projects/CA_AlamedaCounty_2021_B21/LAZ/c.laz")}
    assert got == {"ARRA_CA_SANFRANCOAST_2010", "CA_ALAMEDACO_2006",
                   "CA_AlamedaCounty_2021_B21"}, got
    assert "legacy" not in got, "the bucket must never be a project name"


def test_lidar_recency_uses_the_survey_year_not_the_publication_date():
    """TNM lists ARRA_CA_SANFRANCOAST_2010 with publicationDate 2023-04-13 -- thirteen years after
    the flight. Ranking recency by publicationDate therefore made decade-old elevation look like the
    newest data available, which is the same class of error as commit cf95110 (a USGS project name is
    not a flight date)."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    import fetch_lidar

    assert fetch_lidar.survey_year("CA_AlamedaCounty_2021_B21") == 2021
    assert fetch_lidar.survey_year("ARRA_CA_SANFRANCOAST_2010") == 2010
    assert fetch_lidar.survey_year("CA_ALAMEDACO_2006") == 2006

    # USGS dates many projects with a FISCAL-YEAR QUARTER CODE, not a full year. Matching only
    # 4-digit years returned 0 for those, and 0 ranked them below every dated survey -- which
    # INVERTED the rule this function exists to implement. Verified live: Merion's PA_17County_D24
    # (2024) lost to PA_STATEWIDE_S_2006_2008, so the commit meant to stop us printing a 2006 green
    # as current would have fetched one. Affected Merion, Philadelphia and Copper Valley.
    assert fetch_lidar.survey_year("PA_17County_D24") == 2024
    assert fetch_lidar.survey_year("CA_FEMALevee_D23") == 2023
    assert fetch_lidar.survey_year("CA_SierraNevada_B22") == 2022
    # and an undated project is UNKNOWN, not ancient -- returning 0 made it lose to everything
    assert fetch_lidar.survey_year("no_year_here") is None

    # equal coverage -> the newer SURVEY wins, even though the older one publishes later
    S, W, N, E = fetch_lidar.S, fetch_lidar.W, fetch_lidar.N, fetch_lidar.E
    full = dict(minX=W - 0.01, maxX=E + 0.01, minY=S - 0.01, maxY=N + 0.01)
    projects = {
        "ARRA_CA_SANFRANCOAST_2010": [dict(publicationDate="2023-04-13", boundingBox=full)],
        "CA_AlamedaCounty_2021_B21": [dict(publicationDate="2022-01-01", boundingBox=full)],
    }
    chosen, _s, _n = fetch_lidar.choose_project(projects)
    assert chosen == "CA_AlamedaCounty_2021_B21", \
        f"picked {chosen}: a 2023 publication of 2010 data outranked a 2021 survey"

    # the real Merion case, at equal coverage: a fiscal-year-coded 2024 survey must beat a 2008 one
    projects = {
        "PA_STATEWIDE_S_2006_2008": [dict(publicationDate="2010-01-01", boundingBox=full)],
        "PA_17County_D24": [dict(publicationDate="2025-01-01", boundingBox=full)],
    }
    chosen, _s, _n = fetch_lidar.choose_project(projects)
    assert chosen == "PA_17County_D24", f"picked {chosen}: a 2024 survey must beat a 2008 one"

    # an undated project must not be preferred over a dated one purely by coverage...
    projects = {
        "mystery_project": [dict(publicationDate="2025-01-01", boundingBox=full)],
        "CA_Foo_2019": [dict(publicationDate="2020-01-01", boundingBox=full)],
    }
    chosen, _s, _n = fetch_lidar.choose_project(projects)
    assert chosen == "CA_Foo_2019", f"picked {chosen}: prefer a survey whose date we actually know"


def test_lidar_selection_prefers_green_coverage_over_recency():
    """Round-1 finding: picking the NEWEST project chose CA_SanJoaquin_2021_A21 (published 2023, 90%
    of the bbox) over CA_UpperSouthAmerican_Eldorado_2019_B19 (2021, 100%), "leaving the greens
    outside the clip with no ground returns."

    The harm named in that finding is about GREENS; bbox coverage was only a proxy for it, and a bad
    one -- see test_project_choice_is_judged_on_the_greens_not_the_bounding_box, where a quarter of
    Monarch Bay's bbox is open water and the proxy vetoed the 2021 survey the book is built on. So
    this test now states the finding in its own terms: a newer survey that leaves greens unfed must
    lose; a newer survey that feeds every green must win even though it covers less of the rectangle,
    because the area beyond the greens is not what the green surfaces are built from.

    Replayed offline against recorded TNM shapes."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    import fetch_lidar

    S, W, N, E = fetch_lidar.S, fetch_lidar.W, fetch_lidar.N, fetch_lidar.E
    full = dict(minX=W - 0.01, maxX=E + 0.01, minY=S - 0.01, maxY=N + 0.01)
    clip = dict(minX=W - 0.01, maxX=E + 0.01, minY=S + (N - S) * 0.1, maxY=N + 0.01)
    items = [
        dict(downloadURL="https://x/Projects/CA_Eldorado_2019_B19/LAZ/a.laz",
             publicationDate="2021-01-01", boundingBox=full),
        dict(downloadURL="https://x/Projects/CA_SanJoaquin_2021_A21/LAZ/b.laz",
             publicationDate="2023-01-01", boundingBox=clip),
    ]
    projects = {}
    for it in items:
        projects.setdefault(fetch_lidar._project_of(it), []).append(it)

    # greens spread across the bbox, most of them BELOW the clip's south edge, so the newer project
    # genuinely cannot feed them -- the situation the round-1 finding described
    cents = [(W + (E - W) * 0.5, S + (N - S) * f) for f in (0.01, 0.02, 0.03, 0.04, 0.05, 0.5)]
    real = fetch_lidar._green_centroids
    fetch_lidar._green_centroids = lambda: cents
    try:
        assert fetch_lidar._green_coverage([items[1]], cents) < fetch_lidar.GREEN_COVERAGE_GOOD
        # call the ENGINE's selection, not a copy of it: the first version of this test
        # re-implemented the four lines it was checking and so could not have failed
        chosen, scored, _newest = fetch_lidar.choose_project(projects)
        assert scored["CA_Eldorado_2019_B19"] > scored["CA_SanJoaquin_2021_A21"]
        assert chosen == "CA_Eldorado_2019_B19", \
            "a newer survey that leaves most greens unfed must not win on recency"

        # the tie-break still prefers the newer project when both feed every green
        items[1]["boundingBox"] = full
        projects = {}
        for it in items:
            projects.setdefault(fetch_lidar._project_of(it), []).append(it)
        chosen, _s, _n = fetch_lidar.choose_project(projects)
        assert chosen == "CA_SanJoaquin_2021_A21", "equal coverage must fall through to recency"

        # and the case the bbox proxy got wrong: the newer survey feeds every green while covering
        # less of the rectangle. It must win now -- this is the Monarch Bay situation in miniature.
        items[1]["boundingBox"] = dict(minX=W - 0.01, maxX=W + (E - W) * 0.55,
                                       minY=S - 0.01, maxY=N + 0.01)
        projects = {}
        for it in items:
            projects.setdefault(fetch_lidar._project_of(it), []).append(it)
        chosen, scored, _n = fetch_lidar.choose_project(projects)
        assert scored["CA_SanJoaquin_2021_A21"] < scored["CA_Eldorado_2019_B19"], \
            "the newer survey should cover less of the BBOX in this case"
        assert fetch_lidar._green_coverage(projects["CA_SanJoaquin_2021_A21"], cents) == 1.0
        assert chosen == "CA_SanJoaquin_2021_A21", \
            "a newer survey that feeds every green must win despite less bbox coverage"
    finally:
        fetch_lidar._green_centroids = real


def test_digitized_guard_refuses_malformed_cache(tmp_path):
    """Rounds 1-2: 'could not read the previous file' became 'nothing to preserve', which erased
    hand-digitized greens that exist in exactly one untracked file. Valid-JSON-wrong-shape was the
    same hole (a misspelled 'elements' key took bay-view's digitized greens 2 -> 0)."""
    slug = a_course()
    os.environ["COURSE"] = slug
    for m in ("config", "fetch_osm"):
        sys.modules.pop(m, None)
    import fetch_osm

    p = tmp_path / "osm_geom.json"
    dig = {"type": "way", "id": -16, "tags": {"golf": "green", "_digitized": "yes"},
           "geometry": [{"lat": 1.0, "lon": 2.0}]}

    assert fetch_osm._digitized_of(str(p)) == []                      # absent -> quiet []
    p.write_text(json.dumps({"version": 0.6, "elements": [dig]}))
    assert len(fetch_osm._digitized_of(str(p))) == 1                  # intact -> preserved

    for name, body in [
        ("truncated", '{"version":0.6,"elem'),
        ("empty", ""),
        ("html error page", "<html>500</html>"),
        ("no elements key", '{"version":0.6}'),
        ("misspelled key", '{"version":0.6,"elemnts":[]}'),
        ("elements a dict", '{"elements":{"a":1}}'),
        ("elements null", '{"elements":null}'),
        ("elements of strings", '{"elements":["a"]}'),
        ("top level a list", '[{"id":1}]'),
    ]:
        p.write_text(body)
        before = p.read_bytes()
        with pytest.raises(SystemExit):
            fetch_osm._digitized_of(str(p))
        assert p.read_bytes() == before, f"{name}: must not modify the file"


# ---------------------------------------------------------------------------
# Synthetic-geometry tick tests -- run on a bare clone, and each gate is isolated
# ---------------------------------------------------------------------------
YD = 0.9144

# Two holes, each built so that EXACTLY ONE of the two suppression rules is load-bearing. The
# corpus version of this test could not fail: on real geometry every overshooting tick is also
# within 25 yd of the tee, so deleting either rule alone left the output byte-identical.
#   A: centerline 300 yd, card 182 -> the 200 crossing sits 100 yd from the tee (near-tee gate
#      passes) but is longer than the card, so ONLY the card bound can suppress it.
#   B: centerline 210 yd, card 400 -> the 200 crossing sits 10 yd from the tee, and 200 < card,
#      so ONLY the near-tee gate can suppress it.
SYNTH = {
    1: dict(line_yd=300.0, card=182, must=[100, 150], must_not=[200, 250, 300]),
    2: dict(line_yd=210.0, card=400, must=[100, 150], must_not=[200]),
}


@pytest.fixture(scope="module")
def synth_engine(tmp_path_factory):
    """A course whose geometry is authored, not downloaded: straight north-running centerlines
    ending on a green centred at the origin, so every tick position is known in closed form."""
    slug = "_synth_ticks"                       # leading _ keeps it out of the corpus scan
    cdir = os.path.join(ROOT, "courses", slug)
    os.makedirs(cdir, exist_ok=True)
    lat0, lon0 = 40.0, -75.0
    dl = lambda m: m / R_LAT                    # metres -> degrees of latitude (due north)
    dg = lambda m: m / _mlon(lat0)
    els, holes, hole_cols = [], {}, ["par", "mens_hcp", "Card"]
    for hn, spec in SYNTH.items():
        # each hole gets its own lane so greens cannot be confused between holes
        lon = lon0 + dg(400.0 * (hn - 1))
        els.append(dict(type="way", id=1000 + hn, tags={"golf": "green"}, geometry=[
            dict(lat=lat0 + dl(dy), lon=lon + dg(dx))
            for dx, dy in ((-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10))]))
        L = spec["line_yd"] * YD
        els.append(dict(type="way", id=2000 + hn, tags={"golf": "hole", "ref": str(hn)},
                        geometry=[dict(lat=lat0 + dl(L), lon=lon), dict(lat=lat0, lon=lon)]))
        holes[str(hn)] = [4, hn, spec["card"]]
    json.dump(dict(elements=els), open(os.path.join(cdir, "osm_geom.json"), "w"))
    json.dump(dict(elements=[]), open(os.path.join(cdir, "osm_course.json"), "w"))
    json.dump(dict(slug=slug, name="Synthetic", address="", location={"lat": lat0, "lon": lon0},
                   par=8, holes_count=len(SYNTH), green_speed="",
                   tees=[dict(name="Card", yards=sum(s["card"] for s in SYNTH.values()),
                              rating=70.0, slope=113)],
                   featured_tee="Card", hole_cols=hole_cols, holes=holes,
                   osm_bbox=[lat0 - 0.01, lon0 - 0.01, lat0 + 0.02, lon0 + 0.02],
                   sources={}),
              open(os.path.join(cdir, "course.json"), "w"))
    prev = os.environ.get("COURSE")
    try:
        yield _engine(slug)
    finally:
        for f in ("osm_geom.json", "osm_course.json", "course.json"):
            fp = os.path.join(cdir, f)
            if os.path.exists(fp):
                os.remove(fp)
        if os.path.isdir(cdir):
            os.rmdir(cdir)
        # MUST restore: this dir is now gone, and a stale COURSE pointing at it makes config raise
        # SystemExit in every later test that shells out to a tool.
        _restore_course(prev)


def _ticks(svg):
    """(to_green_yd, y) for every gutter tick label the card prints."""
    return [(int(n), float(y)) for y, n in
            re.findall(r'<text x="9" y="([0-9.]+)"[^>]*>(\d+)</text>', svg)]


def test_tick_radius_never_exceeds_the_card_yardage(synth_engine):
    """Round 3: castlewood-hill h4 printed '200 to green' on a hole its own card lists as 182 yd,
    because the radius bound was gated on the from-tee value, which is None wherever the drawn
    centerline overshoots the back tee. Isolated here by hole 1, whose 200 crossing is a legal
    100 yd from the tee -- so only the card bound can stop it."""
    config, render_hole = synth_engine
    bad = []
    for hn, spec in SYNTH.items():
        svg, _ = render_hole.render_hole(hn, config.HOLES)
        for yd, _y in _ticks(svg):
            if yd > spec["card"]:
                bad.append((hn, yd, spec["card"]))
    assert not bad, f"tick further from the green than the hole is long: {bad}"


def test_no_tick_is_printed_within_25_yd_of_the_tee(synth_engine):
    """The near-tee gate: a '200 to green' row 10 yd off the tee is clutter, not information.
    Isolated by hole 2, where 200 is well inside the 400-yd card so the card bound cannot fire.
    Arc-from-tee is computed from the authored geometry, sharing no code with the engine."""
    config, render_hole = synth_engine
    bad = []
    for hn, spec in SYNTH.items():
        svg, _ = render_hole.render_hole(hn, config.HOLES)
        for yd, _y in _ticks(svg):
            # the line runs due north to a green at the origin, so a point at radius R sits R
            # metres up the lane and (L - R) along the line from the tee
            arc_from_tee_yd = spec["line_yd"] - yd
            if arc_from_tee_yd < 25.0:
                bad.append((hn, yd, round(arc_from_tee_yd, 1)))
    assert not bad, f"tick printed too close to the tee to be useful: {bad}"


def test_the_ticks_that_should_print_do_print(synth_engine):
    """Guards the two tests above from passing vacuously: both would be satisfied by an engine
    that drew no ticks at all. Hole 1 must show 100/150 and hole 2 must show 100/150."""
    config, render_hole = synth_engine
    for hn, spec in SYNTH.items():
        svg, _ = render_hole.render_hole(hn, config.HOLES)
        got = sorted(yd for yd, _y in _ticks(svg))
        assert got == sorted(spec["must"]), f"hole {hn}: expected ticks {spec['must']}, got {got}"


# ---------------------------------------------------------------------------
# Corpus tests -- measured on the real rendered output
# ---------------------------------------------------------------------------
@needs_corpus
def test_no_tick_exceeds_its_hole_yardage():
    """Artifact gate for the same defect on the REAL corpus. This cannot isolate either rule (see
    the synthetic pair above -- on real geometry both fire together), so it exists to catch a
    violation in the shipped books, not to prove the rules work."""
    bad, holes, labels, errors = [], 0, 0, []
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception as e:
                errors.append((slug, hn, repr(e)[:120])); continue
            holes += 1
            card = config.HOLES[hn][2]
            for t in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg):
                labels += 1
                if int(t) > card:
                    bad.append((slug, hn, int(t), card))
    _assert_examined(holes, labels, errors, "tick-vs-card sweep")
    assert not bad, f"ticks further from the green than the hole is long: {bad}"


@needs_corpus
def test_from_tee_labels_are_bounded_and_ordered():
    """Round 2: the from-tee number was card_total - yd while yd had become a straight-line radius,
    mixing two measures (max +54 yd wrong). It must now be >= 30, <= the hole's card yardage, and
    increase monotonically as the to-green number does.

    Bounds and ordering are NOT sufficient -- card_total - yd satisfies all three, which is how the
    original bug survived. So the VALUE is also checked against an independently computed
    along-the-line position (dense sampling, no code shared with the engine)."""
    bad, nholes, labels, errors = [], 0, 0, []
    worst_value_err = 0.0
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        geom = json.load(open(os.path.join(ROOT, "courses", slug, "osm_geom.json")))["elements"]
        greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        holes = [e for e in geom if (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry")]
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception as e:
                errors.append((slug, hn, repr(e)[:120])); continue
            nholes += 1
            card = config.HOLES[hn][2]
            rights = [int(x) for x in re.findall(r'<text x="91"[^>]*>(\d+)</text>', svg)]
            lefts = [int(x) for x in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg)]
            for r in rights:
                if r < 30 or r > card:
                    bad.append((slug, hn, "out of range", r, card))
            if rights != sorted(rights, reverse=True):
                bad.append((slug, hn, "from-tee not monotonic", rights, card))
            if lefts != sorted(lefts):
                bad.append((slug, hn, "to-green not monotonic", lefts, card))

            # --- value check, independent of the engine ---
            pairs = re.findall(r'<text x="9" y="([0-9.]+)"[^>]*>(\d+)</text>', svg)
            rmap = dict(re.findall(r'<text x="91" y="([0-9.]+)"[^>]*>(\d+)</text>', svg))
            if not rmap:
                continue
            cand = [h for h in holes if (h.get("tags") or {}).get("ref") == str(hn)]
            if not cand:
                continue
            line = max(cand, key=lambda h: len(h["geometry"]))["geometry"]
            g, _gend, tend = render_hole.match_green(line, greens)
            gla = sum(p["lat"] for p in g["geometry"]) / len(g["geometry"])
            glo = sum(p["lon"] for p in g["geometry"]) / len(g["geometry"])
            la0 = sum(p["lat"] for p in line) / len(line)
            lo0 = sum(p["lon"] for p in line) / len(line)
            em = lambda la, lo: ((lo - lo0) * _mlon(la0), (la - la0) * R_LAT)
            same = (abs(line[0]["lat"] - tend["lat"]) < 1e-9 and abs(line[0]["lon"] - tend["lon"]) < 1e-9)
            ordered = line if same else list(reversed(line))
            pts = [em(p["lat"], p["lon"]) for p in ordered]
            seg = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                   for i in range(len(pts) - 1)]
            arc = sum(seg) or 1.0
            gc = em(gla, glo)
            for y, ln in pairs:
                if y not in rmap:
                    continue
                target = int(ln) * 0.9144
                best = None                      # dense sample the polyline for the radius crossing
                for i in range(len(pts) - 1):
                    base = sum(seg[:i])
                    for k in range(401):
                        f = k / 400.0
                        px = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
                        py = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
                        d = math.hypot(px - gc[0], py - gc[1])
                        if best is None or abs(d - target) < best[0]:
                            best = (abs(d - target), base + seg[i] * f)
                if best is None:
                    continue
                expect = card * best[1] / arc          # card yardage scaled by position on the line
                err = abs(int(rmap[y]) - expect)
                worst_value_err = max(worst_value_err, err)
                labels += 1
                # 2 yd covers dense-sampling granularity + rounding. Was 8 yd, which left 8.9x
                # headroom over the true worst error (0.9 yd) -- a tolerance that loose would have
                # accepted a real regression as noise.
                if err > 2.0:
                    bad.append((slug, hn, "from-tee value wrong", int(rmap[y]), round(expect, 1)))
    # this sweep counts rows carrying BOTH gutter numbers, so it needs the PAIRS floor -- using the
    # labels floor demanded 2.5/hole from a population that runs 2.22/hole on bay-view
    _assert_examined(nholes, labels, errors, "from-tee sweep", per_hole=MIN_PAIRS_PER_HOLE)
    assert not bad, (f"from-tee label violations (worst value error {worst_value_err:.1f} yd): "
                     f"{bad[:8]}{' ...' if len(bad) > 8 else ''}")


@needs_corpus
@pytest.mark.parametrize("font_scale", [1.0, 2.0])
def test_gutter_numbers_never_overprint(font_scale):
    """Round 2: the two gutter numbers had no horizontal guard, so at the 2x coach scale the brown
    number -- painted second WITH a white halo -- erased digits of the to-green yardage
    (monarch-bay h16 printed '1(498'). 25 rows on 5 holes."""
    bad, holes, labels, errors = [], 0, 0, []
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES, font_scale=font_scale)
            except Exception as e:
                errors.append((slug, hn, repr(e)[:120])); continue
            holes += 1
            rights = {y: n for y, _f, n in
                      re.findall(r'<text x="91" y="([0-9.]+)" font-size="([0-9.]+)"[^>]*>(\d+)</text>', svg)}
            for y, f, n in re.findall(r'<text x="9" y="([0-9.]+)" font-size="([0-9.]+)"[^>]*>(\d+)</text>', svg):
                if y not in rights:
                    continue
                FSN = float(f)
                left_end = 9 + DIGIT_EM * FSN * len(n)
                right_start = 91 - DIGIT_EM * FSN * len(rights[y])
                labels += 1
                if left_end > right_start:
                    bad.append((slug, hn, n, rights[y], round(left_end - right_start, 2)))
    # A None floor here let the 2x sweep pass on ZERO examined pairs -- the exact scale the
    # overprint bug occurred at. Both scales pair roughly the same number of rows (the 2x scale
    # drops marks, not the gutter numbers), so floor both.
    _assert_examined(holes, labels, errors, f"overprint sweep @{font_scale}x",
                     per_hole=MIN_PAIRS_PER_HOLE)
    assert not bad, f"overlapping gutter numbers at font_scale={font_scale}: {bad}"


@needs_corpus
def test_to_green_label_is_a_true_straight_line_distance():
    """Rounds 1-2: the label first meant a straight-line distance but the tick sat up to 85 m off
    the drawn line; then the tick was on the line but the label had become a WALKING distance, up
    to +43 yd over what a rangefinder reads. Both properties must hold at once.

    Measured from the SVG, not by re-running the placement helper -- the original verification was
    circular and could not have failed."""
    worst_label = 0.0
    worst_offline = 0.0
    nholes, labels, errors = 0, 0, []
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        geom = json.load(open(os.path.join(ROOT, "courses", slug, "osm_geom.json")))["elements"]
        greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        holes = [e for e in geom if (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry")]
        for hn in config.HOLE_NUMS:
            cand = [h for h in holes if (h.get("tags") or {}).get("ref") == str(hn)]
            if not cand:
                continue
            line = max(cand, key=lambda h: len(h["geometry"]))["geometry"]
            g, _gend, _tend = render_hole.match_green(line, greens)
            gla = sum(p["lat"] for p in g["geometry"]) / len(g["geometry"])
            glo = sum(p["lon"] for p in g["geometry"]) / len(g["geometry"])
            la0 = sum(p["lat"] for p in line) / len(line)
            lo0 = sum(p["lon"] for p in line) / len(line)
            em = lambda la, lo: ((lo - lo0) * _mlon(la0), (la - la0) * R_LAT)
            gc = em(gla, glo)
            lem = [em(p["lat"], p["lon"]) for p in line]
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception as e:
                errors.append((slug, hn, repr(e)[:120])); continue
            nholes += 1
            # recover each tick's drawn position by re-solving the radius from the label itself
            for t in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg):
                yd = int(t)
                labels += 1
                # the point on the polyline at that radius, found independently of render_hole
                target = yd * 0.9144
                best = None
                for i in range(len(lem) - 1):
                    ax, ay = lem[i]
                    bx, by = lem[i + 1]
                    for k in range(201):            # dense sample: no shared code with the engine
                        f = k / 200.0
                        px, py = ax + (bx - ax) * f, ay + (by - ay) * f
                        d = math.hypot(px - gc[0], py - gc[1])
                        if best is None or abs(d - target) < abs(best[0] - target):
                            best = (d, px, py)
                assert best is not None
                worst_label = max(worst_label, abs(best[0] - target) / 0.9144)
                off = min(render_hole.dist_pt_seg(best[1], best[2], lem[i][0], lem[i][1],
                                                  lem[i + 1][0], lem[i + 1][1])
                          for i in range(len(lem) - 1))
                worst_offline = max(worst_offline, off)
    # Both asserts below are satisfied by worst_*=0.0, i.e. by examining nothing at all -- so the
    # coverage floor is what gives them meaning.
    _assert_examined(nholes, labels, errors, "to-green sweep")
    # 1 yd covers the sampling step and the engine's local flat-earth metric vs a geodesic
    assert worst_label < 1.0, f"to-green label off by {worst_label:.2f} yd from the true straight line"
    assert worst_offline < 1.0, f"tick sits {worst_offline:.2f} m off the drawn centerline"


def test_the_dedication_is_always_the_last_card_and_upright():
    """The 9-hole fix: an odd card count needs a blank leaf, and APPENDING it landed the dedication
    one leaf early so the book ended on a blank page. The blank goes BEFORE the last card, and the
    dedication -- as the back cover -- prints upright rather than rotated like every other duplex
    back. Confirmed structurally by review but untested, so a refactor of build_pages could undo it
    and nothing would notice until a book was folded.

    Drives generate.pad_to_leaves / is_upright_back directly -- the first version of this test
    re-implemented both rules, which is the circularity the rest of this file exists to avoid."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "generate"):
        sys.modules.pop(m, None)
    import generate

    for n in (23, 24, 25, 29, 41):
        cards = [f"c{i}" for i in range(n)]
        ded = cards[-1]
        cards = generate.pad_to_leaves(cards, blank="BLANK")
        assert len(cards) % 2 == 0, f"{n}: card count must be whole leaves"
        assert cards[-1] == ded, f"{n}: dedication must remain the final card"
        assert "BLANK" not in cards[-1:], f"{n}: book must not end on a blank"
        # the dedication sits at index len-1, i.e. the BACK of the last leaf, and that back is the
        # one printed upright
        last = len(cards) - 1
        assert last % 2 == 1, f"{n}: dedication must be a leaf BACK, not a front"
        upright = [i for i in range(1, len(cards), 2) if generate.is_upright_back(i, len(cards))]
        assert upright == [last], f"{n}: exactly the dedication prints upright, got {upright}"


def _synth_green(cdir, hole, zfn, insufficient=None, n=60, span_deg=0.0004):
    """Write a synthetic dem_hd surface (npy + json) so the honesty gate can be tested with no
    LiDAR, no network and no course data."""
    import numpy as np
    os.makedirs(os.path.join(cdir, "dem_hd"), exist_ok=True)
    arr = np.fromfunction(lambda r, c: zfn(r, c), (n, n), dtype=float)
    np.save(os.path.join(cdir, "dem_hd", f"hole{hole:02d}.npy"), arr)
    lat0, lon0 = 40.0, -75.0
    d = span_deg
    meta = dict(hole=hole, approach_bearing=0.0,
                bbox=[lon0 - d, lat0 - d, lon0 + d, lat0 + d], W=n, H=n,
                green_id=1, green_center=[lat0, lon0],
                polygon=[[lat0 - d * 0.6, lon0 - d * 0.6], [lat0 - d * 0.6, lon0 + d * 0.6],
                         [lat0 + d * 0.6, lon0 + d * 0.6], [lat0 + d * 0.6, lon0 - d * 0.6],
                         [lat0 - d * 0.6, lon0 - d * 0.6]],
                source="test surface")
    if insufficient is not None:
        meta["insufficient"] = insufficient
    json.dump(meta, open(os.path.join(cdir, "dem_hd", f"hole{hole:02d}.json"), "w"))


@pytest.fixture
def gate_course():
    """A course dir holding only synthetic green surfaces, for honesty-gate tests."""
    slug = "_synth_gate"
    cdir = os.path.join(ROOT, "courses", slug)
    os.makedirs(cdir, exist_ok=True)
    lat0, lon0 = 40.0, -75.0
    json.dump(dict(slug=slug, name="SynthGate", address="",
                   location={"lat": lat0, "lon": lon0}, par=72, green_speed="",
                   tees=[dict(name="Card", yards=100, rating=70.0, slope=113)],
                   featured_tee="Card", hole_cols=["par", "mens_hcp", "Card"],
                   holes={"1": [72, 1, 100]},
                   osm_bbox=[lat0 - 0.01, lon0 - 0.01, lat0 + 0.01, lon0 + 0.01], sources={}),
              open(os.path.join(cdir, "course.json"), "w"))
    prev = os.environ.get("COURSE")
    os.environ["COURSE"] = slug
    for m in ("config", "render_green"):
        sys.modules.pop(m, None)
    try:
        yield cdir
    finally:
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)
        _restore_course(prev)


def test_honesty_gate_blanks_a_green_it_refused_to_read(gate_course):
    """THE most important branch in the engine: the one line that turns insufficient=True into a
    blank green instead of a printed slope read. It had ZERO test coverage and ZERO data coverage
    (0 of 198 built greens are insufficient), so deleting or inverting it left the suite green.

    Both directions are asserted, because a gate that always blanks is as wrong as one that never
    does."""
    import render_green
    tilt = lambda r, c: 100.0 + 0.03 * r           # a clean 3% plane: must be READ
    _synth_green(gate_course, 1, tilt, insufficient=False)
    _synth_green(gate_course, 2, tilt, insufficient=True)

    svg_ok, s_ok = render_green.render(1)
    svg_no, s_no = render_green.render(2)

    assert not s_ok.get("insufficient"), "a good surface must be read"
    assert s_ok["tilt_pct"] > 0, "a 3% plane must report a nonzero tilt"
    assert s_ok["conf"] != "no data"

    assert s_no.get("insufficient") is True, "insufficient=True must survive to the summary"
    assert s_no["tilt_pct"] == 0.0 and s_no["conf"] == "no data", \
        "a refused green must report no slope, not 0.0% dressed as a reading"
    assert s_no["feeds"] in ("not surveyed", "rebuilt since survey")
    # and the drawn card must not carry contour/arrow marks for a green with no data
    assert svg_no.count("<path") <= svg_ok.count("<path")


def test_render_refuses_an_ungated_surface_that_is_mostly_nodata(gate_course):
    """fetch_dem.py -- the 1 m seamless path a BRAND-NEW course uses -- wrote no gate keys at all,
    so meta.get("insufficient") was None (falsy) and an unusable surface printed slope numbers.
    render_green must therefore gate on the surface itself, not only on the producer's verdict."""
    import numpy as np
    import render_green
    # no `insufficient` key at all, and most of the green has no elevation
    holed = lambda r, c: np.where(r < 45, np.nan, 100.0 + 0.03 * r)
    _synth_green(gate_course, 3, holed)
    _svg, s = render_green.render(3)
    assert s.get("insufficient") is True, "a mostly-NoData green must be refused even when ungated"
    assert s["conf"] == "no data"


def test_render_survives_the_real_3dep_nodata_sentinel(gate_course):
    """A single USGS 3DEP NoData value (-3.4028235e38) made the 15 cm contour loop iterate over a
    3.4e38 range: the process was OOM-KILLED with rc=137 and zero bytes of output -- no error, no
    card, nothing to debug. Sentinels must be neutralised before anything measures the surface."""
    import numpy as np
    import render_green
    # the sentinel must land INSIDE the green outline. At (0,0) it sits outside the polygon and
    # outside the eroded core, so it never reaches the measurement and the test cannot detect
    # whether it was neutralised -- which is how this test first survived deleting the guard.
    sentinel = lambda r, c: np.where((r == 30) & (c == 30), -3.4028235e38, 100.0 + 0.03 * r)
    _synth_green(gate_course, 4, sentinel)
    svg, s = render_green.render(4)          # must return, not die
    assert svg and isinstance(s, dict)
    # ONE bad pixel in 3600 must be neutralised, not cost the whole green: asserting only that the
    # numbers are small would be satisfied by a BLANK card, which is how this test first passed
    # while the sentinel was still leaking through to the relief gate.
    assert not s.get("insufficient"), "one NoData pixel must not blank an otherwise good green"
    assert s["tilt_pct"] > 0.0, "the 3% plane must still be read"
    assert s["relief_ft"] < 100.0, f"sentinel leaked into the relief: {s['relief_ft']}"


def test_no_slope_label_claims_an_unputtable_number(gate_course):
    """merion h2 printed "40" beside "5" on a green card whose legend says "Numbers = slope %
    there". The cell was measured correctly -- it is a bank inside the OSM golf=green polygon,
    which includes the collar and surround -- but a 40% putt does not exist, and the label
    placement sorted steepest-first, so it actively PREFERRED the least plausible cells. Across the
    12 books: 1321 labels, 137 above 8%, worst 40.

    Synthetic surface: a putting-plausible 3% plane with a 45% bank across one edge, inside a
    single green outline -- exactly the real geometry."""
    import numpy as np
    import render_green

    # The bank must sit where the label sampler actually looks: inside the ERODED core (the mask
    # is inset, then eroded ~1.5 m) and on the c = 4, 10, 16, ... sampling stride. A bank at the
    # outline edge is never sampled, which is how the first version of this test passed with the
    # ceiling removed.
    def plane_with_bank(r, c):
        base = 100.0 + 0.03 * r
        return np.where(c < 28, base, np.where(c <= 34, base + 1.2 * (c - 28), base + 1.2 * 6))

    _synth_green(gate_course, 5, plane_with_bank, insufficient=False)
    svg, _s = render_green.render(5)
    labels = [int(v) for v in re.findall(
        r'font-size="4\.6"[^>]*font-weight="700">(\d+)</text>', svg)]
    assert labels, "the plane must still produce slope labels"
    # The bound is stated HERE, independently. Reading render_green.SLOPE_LABEL_MAX_PCT meant the
    # test moved with the code: raising the constant to 100 restored merion h2's "40" and the suite
    # stayed green -- the test asserted only "the cap equals itself".
    PUTTING_PLAUSIBLE_MAX_PCT = 12.0     # a built green tops out ~4%; a severe tier face ~8%
    assert max(labels) <= PUTTING_PLAUSIBLE_MAX_PCT, \
        f"printed an unputtable slope: {sorted(labels)}"
    assert render_green.SLOPE_LABEL_MAX_PCT <= PUTTING_PLAUSIBLE_MAX_PCT, \
        f"the cap itself has been raised past putting-plausible: {render_green.SLOPE_LABEL_MAX_PCT}"


def test_the_two_render_modes_are_actually_different(gate_course):
    """The ENLARGED coach edition printed its greens at exactly the pocket scale -- ratio 1.00 on
    all 18 holes -- because build_coach asked for the CONFORMING render (tournament=True), which
    pins the size INLINE in inches so that CSS cannot enlarge a book past the Rule 4.3 cap, and an
    inline style beats the coach stylesheet's width:100%. Four places (the printed card, README,
    PIPELINE.md) asserted the greens were bigger while the print contradicted them.

    So the two modes must stay distinguishable: tournament=True pins the size (the legal cap),
    tournament=False leaves it to the page (the enlarged edition)."""
    import render_green
    _synth_green(gate_course, 6, lambda r, c: 100.0 + 0.03 * r, insufficient=False)

    svg_t, _ = render_green.render(6, tournament=True)
    svg_e, _ = render_green.render(6, tournament=False)
    pinned = re.compile(r'style="width:([0-9.]+)in;height:([0-9.]+)in"')

    assert pinned.search(svg_t), \
        "the conforming render MUST pin its size inline -- that is the Rule 4.3 cap CSS cannot undo"
    assert not pinned.search(svg_e), \
        "the enlarged render must NOT pin an inch size, or the coach card cannot grow past the cap"


@needs_corpus
def test_the_printed_pdf_is_not_older_than_the_html_it_came_from():
    """The book that reaches a golf course is the PDF, and nothing in the repo produced it --
    PIPELINE.md said "headless Chrome --print-to-pdf, or Cmd+P", so every PDF was made by hand at an
    unknown time from an unknown HTML. They drifted: on 2026-07-29 all 12 PDFs dated 12:02 while the
    HTML dated 15:16, so the PRINTED books still carried 40%, 29% and 21% slope labels that the
    engine had already stopped emitting. Verified by rasterising the page: Merion hole 2's green
    printed 5-10-12-40-7 under a legend reading "Numbers = slope % there".

    Every honesty fix in this branch was invisible on paper. That is the worst failure mode this
    project has: the HTML is not the artifact."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import export_pdf
    bad = export_pdf.stale()
    # Only a PROVEN mismatch is a defect. "not exported" and "unverifiable" mean we cannot know,
    # and a test must not assert what it cannot know.
    outdated = [(p, why) for _h, p, why in bad if why.startswith("exported from")]
    unknown = [p for _h, p, why in bad if not why.startswith("exported from")]
    if unknown and not outdated:
        pytest.skip(f"{len(unknown)} book(s) have no recorded source hash (export with "
                    f"tools/export_pdf.py to make staleness checkable)")
    assert not outdated, ("the PRINTED book does not match the engine:\n   " +
                          "\n   ".join(f"{os.path.relpath(p, ROOT)} ({w})" for p, w in outdated) +
                          "\n  Re-export with: python3 tools/export_pdf.py")


def _pdf_numbers(pdf):
    """Every number actually drawn in a PDF, including Type3 glyph runs.

    The book's SVG text becomes Type3 fonts, which do NOT come out of page.get_text("dict") -- a
    plain text scan finds only the 5..45 depth ruler and looks clean. rawdict exposes the glyph
    characters, which is where the slope labels and yardages live."""
    import fitz
    out = []
    with fitz.open(pdf) as d:
        for pg in d:
            for blk in pg.get_text("rawdict")["blocks"]:
                for ln in blk.get("lines", []):
                    for sp in ln.get("spans", []):
                        # Type3 ONLY. The book's SVG text becomes Type3 glyphs; ordinary HTML text
                        # (hole numbers, par, page numbers, scorecard cells) becomes HelveticaNeue.
                        # Mixing the two made the comparison meaningless -- the SVG-text side of the
                        # HTML cannot contain a page number.
                        if "Type3" not in sp.get("font", ""):
                            continue
                        txt = "".join(c.get("c", "") for c in sp.get("chars", []))
                        if re.fullmatch(r"\d{1,3}", txt):
                            out.append(int(txt))
    return out


@pytest.mark.slow          # reads the glyph runs of every shipped PDF
@needs_corpus
def test_every_number_printed_in_a_pdf_exists_in_its_html():
    """The PDF is the artifact; the HTML is not. This test reads the numbers actually DRAWN in each
    shipped PDF and requires every one of them to exist in the HTML it was exported from.

    Its predecessor was a lie by name: "test_no_shipped_pdf_prints_an_unputtable_slope" imported
    fitz, never called it, and re-read the HTML. Proven by replacing Merion's 3.6 MB book with an
    866-byte one-page PDF reading "THIS IS NOT THE BOOK -- 40% slope everywhere": it stayed green.
    Only the card-size test, which genuinely opens the PDF, noticed.

    Subset rather than equality: a page may legitimately draw a number the regex-scan of the HTML
    misses. What must never happen is the PDF printing a number the HTML does not contain -- that is
    precisely the stale-export defect that left a 40% slope label on paper for three commits."""
    try:
        import fitz          # noqa: F401
    except ImportError:
        pytest.skip("pymupdf not installed")
    checked = 0
    for pdf in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        if os.path.basename(os.path.dirname(pdf)).startswith("_"):
            continue
        html = os.path.splitext(pdf)[0] + ".html"
        if not os.path.exists(html):
            continue
        want = {int(v) for v in re.findall(r">(\d{1,3})</text>", open(html, encoding="utf-8").read())}
        if not want:
            continue      # a yardage-mode book (Poppy Ridge) draws no SVG numerals at all
        got = _pdf_numbers(pdf)
        assert len(got) > 100, (
            f"{os.path.relpath(pdf, ROOT)} draws only {len(got)} numbers -- this is not the book")
        extra = sorted(set(got) - want)
        assert not extra, (
            f"{os.path.relpath(pdf, ROOT)} prints {extra}, absent from its HTML -- the PDF is stale "
            f"or was not exported from this book. Re-run tools/export_pdf.py")
        checked += 1
    if checked == 0:
        pytest.skip("no book has both an HTML and an exported PDF here")


@pytest.mark.slow          # reads the glyph runs of every shipped PDF
@needs_corpus
def test_no_shipped_pdf_prints_an_unputtable_slope():
    """The printed slope labels, read from the PDF's own glyph runs. A putting surface has no 40%
    slope; Merion's shipped PDF printed one for three commits while the HTML was already capped.

    The bound is stated HERE, independent of render_green.SLOPE_LABEL_MAX_PCT, so raising the cap in
    the code cannot move the test with it -- the previous version read its ceiling from the module it
    was checking."""
    try:
        import fitz          # noqa: F401
    except ImportError:
        pytest.skip("pymupdf not installed")
    PUTTING_PLAUSIBLE_MAX_PCT = 12
    checked = 0
    for pdf in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        if os.path.basename(os.path.dirname(pdf)).startswith("_"):
            continue
        html = os.path.splitext(pdf)[0] + ".html"
        if not os.path.exists(html):
            continue
        html_slopes = {int(v) for v in re.findall(
            r'font-size="4\.6"[^>]*font-weight="700">(\d+)</text>', open(html, encoding="utf-8").read())}
        if not html_slopes:
            continue      # yardage-mode: the greens are deliberately blank, no slope labels exist
        # slope labels are the 1-2 digit glyph runs; 3-digit runs are hole-map yardages
        small = [v for v in _pdf_numbers(pdf) if v < 100]
        # the depth ruler also prints multiples of 5 up to 45, so only flag a value that is BOTH
        # above the putting bound and present as a slope label in this book's green SVGs
        bad = sorted({v for v in small if v > PUTTING_PLAUSIBLE_MAX_PCT} & html_slopes)
        assert not bad, f"{os.path.relpath(pdf, ROOT)} prints unputtable slope label(s) {bad}"
        assert small, f"{os.path.relpath(pdf, ROOT)} draws no small numbers at all"
        checked += 1
    if checked == 0:
        pytest.skip("no book has both an HTML and an exported PDF here")


HONESTY_CASES = {
    "plain":       (dict(),                                        "GREEN",                        True),
    "outdated":    (dict(_outdated=True),                          "pre-rebuild data",             True),
    "coarse_1m":   (dict(source="USGS 3DEP seamless 1 m @0.5m"),   "1 m data",                     True),
    "insufficient": (dict(insufficient=True),                      "GREEN",                        False),
}


def _fake_summary(**over):
    s = dict(feeds="front-left", conf="firm", tilt_pct=3.1, depth_yd=33, width_yd=25,
             relief_ft=2.4, median_slope=3.0, undul_ft=0.5, scale_max_in=None,
             source="USGS 3DEP LiDAR ground returns @0.4m")
    s.update({k: v for k, v in over.items() if not k.startswith("_")})
    return s


def test_both_editions_print_the_same_honesty_caveats():
    """green_honesty() is the headline fix of 10b8a61 and had ZERO test coverage: reverting it left
    the suite at 30 passed while Monarch Bay's ENLARGED book silently dropped all 6 "1 m data"
    warnings, Philadelphia's dropped all 10 "pre-rebuild data" warnings, and a green the engine had
    REFUSED to read printed "0.0%" again. Both of those courses have distributed coach editions.

    Drives the real card builders -- generate.hole_panel and generate.coach_green_card -- rather
    than green_honesty() alone, because the defect was that one builder did not CALL it."""
    slug = a_course()
    os.environ["COURSE"] = slug
    for m in ("config", "render_green", "render_hole", "generate"):
        sys.modules.pop(m, None)
    import generate

    hole = sorted(generate.HOLES)[0]
    generate.LAYOUTS[hole] = ("<svg></svg>", dict(bunkers=2, waters=0))
    for name, (over, expect_label, expect_slope) in HONESTY_CASES.items():
        s = _fake_summary(**over)
        generate.GREENS[hole] = ("<svg></svg>", s)
        prev = generate.config.COURSE.get("greens_possibly_outdated")
        if over.get("_outdated"):
            generate.config.COURSE["greens_possibly_outdated"] = [hole]
        try:
            pocket = generate.hole_panel(hole, "Front")
            coach = generate.coach_green_card(hole)
        finally:
            if prev is None:
                generate.config.COURSE.pop("greens_possibly_outdated", None)
            else:
                generate.config.COURSE["greens_possibly_outdated"] = prev

        for edition, html in (("pocket", pocket), ("coach", coach)):
            assert expect_label in html, f"{name}/{edition}: missing caveat {expect_label!r}"
            if expect_slope:
                assert "3.1%" in html, f"{name}/{edition}: the tilt figure should print"
            else:
                # the whole point: a refused green must NOT print a tilt, least of all "0.0%"
                assert "3.1%" not in html and "0.0%" not in html, \
                    f"{name}/{edition}: printed a slope for a green the engine refused to read"
                assert "no slope printed" in html, f"{name}/{edition}: must say so explicitly"


def test_fetch_dem_gate_measures_only_the_green_interior():
    """3DEP's exportImage fills out-of-coverage ground with a CONSTANT value, not a NoData marker, so
    the gate has to notice a flat surface. My first version of that check took the relief over the
    WHOLE patch -- which carries a 12 m margin -- so a green sitting on the edge of coverage could be
    entirely zero-filled while the margin outside it held real elevation, the whole-patch range
    looked healthy, and the fabricated green went through. Exactly the case the check exists for."""
    import importlib.util
    import numpy as np
    os.environ["COURSE"] = a_course()
    spec = importlib.util.spec_from_file_location("fd", os.path.join(ROOT, "fetch_dem.py"))
    fd = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(fd)
    except SystemExit:
        pytest.skip("fetch_dem could not import in this environment")

    n = 60
    lat0, lon0, d = 40.0, -75.0, 0.0004
    poly = [[lat0 - d * .6, lon0 - d * .6], [lat0 - d * .6, lon0 + d * .6],
            [lat0 + d * .6, lon0 + d * .6], [lat0 + d * .6, lon0 - d * .6],
            [lat0 - d * .6, lon0 - d * .6]]
    bbox = [lon0 - d, lat0 - d, lon0 + d, lat0 + d]
    interior = np.fromfunction(lambda r, c: (abs(r - 30) < 19) & (abs(c - 30) < 19), (n, n))
    slope = np.fromfunction(lambda r, c: 100.0 + 0.5 * r, (n, n), dtype=float)

    def flat_of(arr):
        nf, ni, rel = fd._green_interior_stats(arr, bbox, n, n, poly)
        return bool(ni and nf < 1.0 and rel < fd.MIN_RELIEF_M)

    assert flat_of(np.where(interior, 0.0, slope)), \
        "green zero-filled with a real margin must still be refused"
    assert flat_of(np.zeros((n, n))), "a wholly constant patch must be refused"
    assert not flat_of(np.fromfunction(lambda r, c: 100.0 + 0.03 * r, (n, n), dtype=float)), \
        "a real 3% green must be read"


CARD_DIV = re.compile(
    r'<div class="card( flip)?" style="left:([\d.]+)in;top:([\d.]+)in"><div class="pageno">(\d+)</div>')


@needs_corpus
def test_duplex_imposition_puts_every_back_behind_its_own_front():
    """A physical property that would ruin every copy and is INVISIBLE in the HTML view.

    The book is printed two-sided and folded, so each leaf's back card must land behind its own
    front. Under long-edge duplex on a portrait sheet the paper flips about the vertical centreline,
    so the back card has to sit at PAGE_W - x_front - CARD_W at the same y. Get that wrong by one
    slot and every green prints behind the WRONG HOLE -- a book that looks perfect on screen and is
    useless on a course. Seven review rounds never checked it.

    Also asserts the top-flip rotation rule: every back is rotated 180 so it reads upright when the
    card is flipped over the top, EXCEPT the last card (the dedication / back cover), which prints
    upright like the front cover."""
    checked = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        slug = os.path.basename(os.path.dirname(f))
        if slug.startswith("_"):
            continue
        cfg, _rh = _engine(slug)
        pos = {int(n): (float(x), float(y), bool(fl))
               for fl, x, y, n in CARD_DIV.findall(open(f, encoding="utf-8").read())}
        if not pos:
            continue
        for L in range(1, len(pos) // 2 + 1):
            fn, bn = 2 * L - 1, 2 * L
            if fn not in pos or bn not in pos:
                continue
            xf, yf, _ = pos[fn]
            xb, yb, _ = pos[bn]
            want = cfg.PAGE_W_IN - xf - cfg.CARD_W_IN
            assert abs(xb - want) < 0.01 and abs(yb - yf) < 0.01, (
                f"{slug} leaf {L}: back card {bn} at x={xb} but must mirror front {fn} "
                f"(x={xf}) to x={want:.3f} -- it would print behind the wrong card")
        rotated = [n for n, (_x, _y, fl) in pos.items() if fl]
        assert all(n % 2 == 0 for n in rotated), f"{slug}: a FRONT card is rotated: {rotated}"
        last = max(pos)
        assert not pos[last][2], f"{slug}: the dedication (card {last}) must print upright"
        assert len(rotated) == len(pos) // 2 - 1, \
            f"{slug}: expected every back but the last rotated, got {len(rotated)} of {len(pos)//2}"
        checked += 1
    assert checked > 0, "no built books to check"


CARD_LIMIT_W_IN, CARD_LIMIT_H_IN = 4.25, 7.0     # USGA Clarification 4.3a/1 book-size limit


@pytest.mark.slow          # opens every shipped PDF
@needs_corpus
def test_printed_card_size_is_measured_from_the_pdf_not_from_config():
    """Rule 4.3 caps the BOOK SIZE at 4.25 x 7 in, as well as the scale. tools/check_scale.py checks
    the size against config.CARD_W_IN -- i.e. it trusts the constant rather than measuring the thing
    that gets printed. That is the same class of error as the scale defect (15 greens printed over
    the cap while every SVG attribute looked correct) and as the stale-PDF defect (the HTML was
    right, the paper was wrong). A wrong @page rule or a scaled export would put a real book over
    the legal size with every check still green.

    Measured from the artifact: the crop ticks are 0.14 x 0.006 in boxes at the four corners of each
    card, so the spacing between opposite ticks IS the printed card size."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    checked = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        if os.path.basename(os.path.dirname(f)).startswith("_"):
            continue
        with fitz.open(f) as d:
            rects = []
            for dr in d[0].get_drawings():
                for it in dr["items"]:
                    if it[0] == "re":
                        r = it[1]
                        if (9.5 < r.width < 11 and r.height < 1.2) or \
                           (r.width < 1.2 and 9.5 < r.height < 11):
                            rects.append(r)
        xs = sorted({round(r.x0, 2) for r in rects if r.width < 1.2})
        ys = sorted({round(r.y0, 2) for r in rects if r.height < 1.2})
        assert len(xs) >= 2 and len(ys) >= 2, f"{os.path.relpath(f, ROOT)}: no crop ticks found"
        w_in, h_in = (xs[1] - xs[0]) / 72.0, (ys[1] - ys[0]) / 72.0
        assert w_in <= CARD_LIMIT_W_IN and h_in <= CARD_LIMIT_H_IN, (
            f"{os.path.relpath(f, ROOT)} prints a {w_in:.3f} x {h_in:.3f} in card, over the "
            f"Rule 4.3 limit of {CARD_LIMIT_W_IN} x {CARD_LIMIT_H_IN} in")
        # and it must match what the engine believes, or one of the two is lying
        cfg, _rh = _engine(os.path.basename(os.path.dirname(f)))
        assert abs(w_in - cfg.CARD_W_IN) < 0.02 and abs(h_in - cfg.CARD_H_IN) < 0.02, (
            f"{os.path.relpath(f, ROOT)}: printed {w_in:.3f}x{h_in:.3f} in but config says "
            f"{cfg.CARD_W_IN}x{cfg.CARD_H_IN} -- the export is not honouring the page rule")
        checked += 1
    if checked == 0:
        pytest.skip("no book has been exported to PDF here (run tools/export_pdf.py)")


@pytest.mark.slow          # re-derives the surface for every green it checks
@needs_corpus
def test_contours_join_equal_height_at_the_stated_interval():
    """The card's legend promises "Contours join equal height (15 cm each)". A broken extraction would
    make a reader misread every tier on every green, and nothing else we check would notice: the
    lines would still look like contours.

    Measured on the REAL corpus, with the surface re-smoothed by an independently written Gaussian
    rather than the engine's: for each interior contour segment, both endpoints must sit at the same
    elevation, and that elevation must land on a multiple of the interval.

    Deliberately not a synthetic-geometry test. Three attempts to predict the contour count on an
    authored patch were wrong, because the engine's Gaussian uses np.convolve(..., 'same'), which
    zero-pads: on a small patch the surface near the edges is dragged toward 0 and no closed form
    describes the in-mask range. Measuring real greens needs no such prediction."""
    import numpy as np
    import render_green

    def my_gauss(a, sig):                     # written independently of render_green.gauss
        r = max(1, int(sig * 3)); x = np.arange(-r, r + 1)
        k = np.exp(-(x * x) / (2 * sig * sig)); k /= k.sum()
        out = np.empty_like(a)
        for j in range(a.shape[1]):
            out[:, j] = np.convolve(a[:, j], k, "same")
        out2 = np.empty_like(out)
        for i in range(a.shape[0]):
            out2[i, :] = np.convolve(out[i, :], k, "same")
        return out2

    def bilerp(z, x, y):
        x0, y0 = int(np.floor(x)), int(np.floor(y))
        x1, y1 = min(x0 + 1, z.shape[1] - 1), min(y0 + 1, z.shape[0] - 1)
        fx, fy = x - x0, y - y0
        return (z[y0, x0] * (1 - fx) * (1 - fy) + z[y0, x1] * fx * (1 - fy) +
                z[y1, x0] * (1 - fx) * fy + z[y1, x1] * fx * fy)

    CONTG = re.compile(r'<g stroke="#3c5a34" stroke-width="0\.5" opacity="0\.55">(.*?)</g>', re.S)
    LINE = re.compile(r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)"/>')
    cint = render_green.CINT_M
    checked = worst_iso = worst_level = 0
    for slug in CORPUS[:3]:
        cfg, _rh = _engine(slug)
        import render_green as rg
        for h in cfg.HOLE_NUMS:
            p = os.path.join(ROOT, "courses", slug, "dem_hd", f"hole{h:02d}.npy")
            if not os.path.exists(p):
                continue
            try:
                svg, summ = rg.render(h, tournament=True)
            except Exception:
                continue
            if summ.get("insufficient"):
                continue
            g = CONTG.search(svg)
            if not g:
                continue
            arr = np.load(p).astype(float)
            arr[~np.isfinite(arr)] = np.nan
            arr[np.abs(arr) > 1e30] = np.nan
            arr = np.where(np.isnan(arr), float(np.nanmedian(arr)), arr)
            z = my_gauss(arr, 3.0)
            H, W = z.shape
            for x1, y1, x2, y2 in LINE.findall(g.group(1)):
                ax, ay, bx, by = map(float, (x1, y1, x2, y2))
                if min(ax, bx) < 10 or min(ay, by) < 10 or max(ax, bx) > W - 11 or max(ay, by) > H - 11:
                    continue      # skip the band where zero-padded smoothing differs from mine
                z1, z2 = bilerp(z, ax, ay), bilerp(z, bx, by)
                checked += 1
                worst_iso = max(worst_iso, abs(z1 - z2))
                mid = (z1 + z2) / 2.0
                worst_level = max(worst_level, abs(mid / cint - round(mid / cint)) * cint)
    assert checked > 2000, f"only {checked} interior contour segments examined"
    # measured on this corpus: 11.8 mm and 5.8 mm. The bounds are a third of the interval, which is
    # loose enough to survive a smoothing difference and tight enough that a real break fails.
    assert worst_iso < cint / 3, \
        f"a contour segment's ends differ by {worst_iso*1000:.1f} mm -- not iso-elevation"
    assert worst_level < cint / 3, \
        f"a contour sits {worst_level*1000:.1f} mm off any {cint*100:.0f} cm level"
    assert abs(cint - 0.15) < 1e-9, f"interval is {cint} m but the legend says 15 cm"


FEEDS_OCTANTS = [(0, "back"), (45, "back-right"), (90, "right"), (135, "front-right"),
                 (180, "front"), (225, "front-left"), (270, "left"), (315, "back-left")]


def test_feeds_label_is_right_in_all_eight_directions(gate_course):
    """"feeds front-left" is the most actionable line on a green card -- the direction putts run
    toward -- and it is stated in the CARD frame, after the map is rotated so the approach points up.
    A sign or rotation error there would swap left for right, or front for back, on every green at
    once, and would look entirely plausible in print.

    Authored planes make the answer known: with the approach bearing due north, a plane falling
    toward bearing B must be labelled by B's octant (0 = back, 90 = right, 180 = front, 270 = left).

    Cross-checked on the real corpus by re-deriving the plane fit independently over the eroded core:
    107 of 108 greens agree exactly; the one difference sits 0.1 degrees from an octant boundary."""
    import numpy as np
    import render_green

    hole = 20
    for bearing, want in FEEDS_OCTANTS:
        th = math.radians(bearing)
        # z = a*E + b*N with downhill (-a,-b) along the bearing; E = c*px_x, N = -r*px_y
        _synth_green(gate_course, hole, lambda r, c: 0.0, insufficient=False)
        meta = json.load(open(os.path.join(gate_course, "dem_hd", f"hole{hole:02d}.json")))
        xmin, ymin, xmax, ymax = meta["bbox"]
        W, H = meta["W"], meta["H"]
        clat = meta["green_center"][0]
        px_x = (xmax - xmin) * _mlon(clat) / W
        px_y = (ymax - ymin) * R_LAT / H
        k = 0.03                                     # a 3% plane: unambiguously "firm"
        z = np.fromfunction(
            lambda r, c: 100.0 - k * math.sin(th) * px_x * c + k * math.cos(th) * px_y * r,
            (H, W), dtype=float)
        np.save(os.path.join(gate_course, "dem_hd", f"hole{hole:02d}.npy"), z)

        _svg, summ = render_green.render(hole)
        assert summ["feeds"] == want, (
            f"a plane falling toward bearing {bearing} deg (approach due north) must read "
            f"{want!r}, got {summ['feeds']!r} -- the card frame is rotated wrongly")
        assert summ["conf"] == "firm", f"a 3% plane should be firm, got {summ['conf']!r}"
        # tilt % is the other number this card prints from the same plane fit, so pin it here where
        # the answer is exact. Cross-checked on the corpus by re-fitting 108 greens with an
        # independent Gaussian and least-squares: worst disagreement 0.05 percentage points, which is
        # the 1-decimal rounding.
        assert abs(summ["tilt_pct"] - 100.0 * k) < 0.15, (
            f"a {100*k:.0f}% plane must print {100*k:.1f}%, got {summ['tilt_pct']}")

    # With the approach due NORTH the card rotation is the identity, so the cases above cannot tell
    # whether the rotation is applied at all -- skipping it entirely still passed them. Repeat with a
    # non-north approach, where the label MUST account for the rotation: a plane falling due north
    # read from a green approached due east feeds to the player's LEFT.
    for appr, bearing, want in ((90.0, 0.0, "left"), (90.0, 90.0, "back"),
                                (180.0, 0.0, "front"), (270.0, 0.0, "right")):
        th = math.radians(bearing)
        _synth_green(gate_course, hole, lambda r, c: 0.0, insufficient=False)
        mp = os.path.join(gate_course, "dem_hd", f"hole{hole:02d}.json")
        meta = json.load(open(mp))
        meta["approach_bearing"] = appr
        json.dump(meta, open(mp, "w"))
        xmin, ymin, xmax, ymax = meta["bbox"]
        W, H = meta["W"], meta["H"]
        px_x = (xmax - xmin) * _mlon(meta["green_center"][0]) / W
        px_y = (ymax - ymin) * R_LAT / H
        k = 0.03
        z = np.fromfunction(
            lambda r, c: 100.0 - k * math.sin(th) * px_x * c + k * math.cos(th) * px_y * r,
            (H, W), dtype=float)
        np.save(os.path.join(gate_course, "dem_hd", f"hole{hole:02d}.npy"), z)
        _svg, summ = render_green.render(hole)
        assert summ["feeds"] == want, (
            f"fall bearing {bearing} deg with approach {appr} deg must read {want!r}, got "
            f"{summ['feeds']!r} -- the fall vector is not being rotated into the card frame")


def test_render_refuses_a_perfectly_flat_surface(gate_course):
    """Out of coverage, 3DEP's exportImage returns a CONSTANT raster rather than any NoData marker.
    The render-time gate claims in its own comment to verify the surface "independently of whoever
    produced it", but it had no minimum-relief test -- blind to the single failure mode that producer
    is documented to have. Demonstrated by zeroing a real green: the card printed
    "feeds back (subtle) - 0.0%", a fabricated read on a green with no measurement at all.

    fetch_dem.py grew MIN_RELIEF_M for this; the renderer needs it too, because 8 surfaces on disk
    predate any producer gate and a future producer may forget again."""
    import numpy as np
    import render_green
    # NB the 0.0 * r is load-bearing: a lambda that ignores r and c makes np.fromfunction return a
    # 0-d array, and the engine then fails at `H, W = arr.shape` -- a broken test surface, not a bug.
    _synth_green(gate_course, 8, lambda r, c: 100.0 + 0.0 * r, insufficient=False)  # perfectly flat
    _svg, s = render_green.render(8)
    assert s.get("insufficient") is True, "a constant surface must be refused, not read"
    assert s["conf"] == "no data" and s["tilt_pct"] == 0.0
    assert "0.0%" not in str(s.get("feeds", "")), "must not dress a zero-fill as a reading"
    # ...but a real, gently sloping green must still be read
    _synth_green(gate_course, 9, lambda r, c: 100.0 + 0.02 * r, insufficient=False)
    _svg2, s2 = render_green.render(9)
    assert not s2.get("insufficient"), "a genuine 2 cm/row green must still be read"


def test_blank_card_depth_is_measured_in_the_approach_frame(gate_course):
    """The "we could not measure this green" card printed depth from the raw LATITUDE extent --
    north-to-south, whatever direction the hole plays -- while the measured card rotates the approach
    to point up first. On an east-west hole those are the depth and the width SWAPPED. Corpus-wide the
    disagreement reached 16 yd (two clubs), and on 36 of 90 greens the old value was closer to the
    width than to the depth.

    Nothing shipped hits it (no built green is blank), but the blank card exists precisely for a
    course with no usable LiDAR, where it would fire on all 18 holes at once."""
    import json as _json
    import render_green
    _synth_green(gate_course, 10, lambda r, c: 100.0 + 0.03 * r, insufficient=False)
    mp = os.path.join(gate_course, "dem_hd", "hole10.json")

    for appr in (0.0, 90.0, 200.0):
        meta = _json.load(open(mp))
        meta["approach_bearing"] = appr
        _json.dump(meta, open(mp, "w"))
        for m in ("render_green",):
            sys.modules.pop(m, None)
        import render_green as rg
        _svg_ok, measured = rg.render(10)
        meta2 = dict(_json.load(open(mp)), insufficient=True)
        _json.dump(meta2, open(mp, "w"))
        sys.modules.pop("render_green", None)
        import render_green as rg2
        _svg_blank, blank = rg2.render(10)
        assert abs(blank["depth_yd"] - measured["depth_yd"]) <= 1, (
            f"approach {appr} deg: blank card says {blank['depth_yd']}yd deep, measured card says "
            f"{measured['depth_yd']}yd -- the blank path is using the wrong axis")
        assert abs(blank["width_yd"] - measured["width_yd"]) <= 1, (
            f"approach {appr} deg: width {blank['width_yd']} vs {measured['width_yd']}")
        meta3 = dict(_json.load(open(mp))); meta3.pop("insufficient", None)
        _json.dump(meta3, open(mp, "w"))


def test_alameda_tile_names_decode_to_the_right_grid_cell():
    """fetch_lidar_alameda.py had ZERO tests and ZERO findings across seven review rounds -- the one
    finder assigned to it died. It decides which LiDAR an entire Alameda course is built from, so an
    off-by-one in its grid arithmetic would feed a course tiles that miss its greens.

    Two things are checked against ground truth read from real tile HEADERS:
      * the grid: names encode the SW corner in THOUSANDS of ftUS on a 3000-ft grid, so a point must
        map to the cell whose header bounds contain it;
      * the units: EPSG:6419 is the METRE variant of California zone 3 (EPSG:6420 is the ftUS one),
        so the transform returns metres and M2FT is load-bearing. Dropping it shifts every index by
        3.28x -- and the module's docstring used to say 6419 was already in feet, inviting exactly
        that "simplification"."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar_alameda"):
        sys.modules.pop(m, None)
    try:
        import fetch_lidar_alameda as fla
    except Exception as e:
        pytest.skip(f"fetch_lidar_alameda not importable here: {type(e).__name__}")

    # EPSG:6419 must be metres; if this ever flips, M2FT becomes wrong
    from pyproj import CRS
    assert CRS.from_user_input("EPSG:6419").axis_info[0].unit_name == "metre", \
        "EPSG:6419 is expected to be the METRE variant; M2FT depends on it"

    # Ground truth from a REAL tile: w6153n2055 in CA_AlamedaCo_3_2021 spans x 6153000..6156000,
    # y 2055000..2058000 ftUS -- read by range-requesting its LAS public header, not assumed. Derive
    # the test coordinate by inverse transform from a point inside that cell rather than guessing a
    # lon/lat (my first attempt guessed one 1585 ft into the neighbouring cell).
    from pyproj import Transformer
    INV = Transformer.from_crs("EPSG:6419", "EPSG:4326", always_xy=True)
    e_ft, n_ft = 6154500.0, 2056500.0                    # centre of the known real cell
    lon, lat = INV.transform(e_ft / fla.M2FT, n_ft / fla.M2FT)

    x, y = fla.T.transform(lon, lat)
    assert abs(x * fla.M2FT - e_ft) < 1.0 and abs(y * fla.M2FT - n_ft) < 1.0, \
        "round trip through EPSG:6419 did not preserve the point -- M2FT or the CRS is wrong"

    names = fla.covering_tiles((lat - 0.0005, lon - 0.0005, lat + 0.0005, lon + 0.0005), pad_ft=0)
    assert "w6153n2055" in names, f"the cell containing the test point was not enumerated: {names}"
    # every name must be a multiple of 3 thousand feet -- the grid step
    for nm in names:
        e, n = nm[1:].split("n")
        assert int(e) % 3 == 0 and int(n) % 3 == 0, f"{nm} is off the 3000-ft grid"
    # and a bbox spanning two cells must enumerate both
    wide = fla.covering_tiles((lat - 0.01, lon - 0.01, lat + 0.01, lon + 0.01), pad_ft=0)
    assert len(wide) > len(names), "a larger bbox must cover more tiles"


def test_gps_time_decodes_to_the_right_calendar_date():
    """tools/lidar_dates.py had ZERO tests, and its output is the "Measured from public USGS 3DEP
    LiDAR flown YYYY-MM-DD" line printed in EVERY book and recorded in legal/03 -- the provenance the
    whole honesty argument rests on. A USGS project NAME is not a date and the LAS header's creation
    date is the DELIVERY date; two of this project's own courses were mislabelled before this decoder
    existed ("Alameda 2021" was flown 2019-08-14).

    Checked against dates computed here from first principles, not from the module: GPS epoch
    1980-01-06, Adjusted Standard GPS time = standard - 1e9, minus 18 leap seconds."""
    import datetime as dt
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import lidar_dates as ld

    EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)
    LEAP = 18            # stated HERE, not read from the module: using ld.LEAP_SECONDS made the test
                         # move with the code, so setting it to 0 left the test green
    assert ld.LEAP_SECONDS == LEAP, f"module uses {ld.LEAP_SECONDS} leap seconds, test expects {LEAP}"
    for target in (dt.datetime(2024, 12, 17, 15, 30, tzinfo=dt.timezone.utc),
                   dt.datetime(2019, 8, 14, 18, 5, tzinfo=dt.timezone.utc),
                   dt.datetime(2020, 4, 15, 20, 0, tzinfo=dt.timezone.utc)):
        standard = (target - EPOCH).total_seconds() + LEAP
        assert ld.gps_to_utc(standard - 1_000_000_000, adjusted=True) == target
        assert ld.gps_to_utc(standard, adjusted=False) == target

    # the 1e9 offset is what distinguishes the two encodings, and confusing them is a ~31-year error
    adj = ld.gps_to_utc(0.0, adjusted=True)
    raw = ld.gps_to_utc(0.0, adjusted=False)
    assert abs((adj - raw).total_seconds() - 1_000_000_000) < 1e-6
    assert adj.year == 2011 and raw.year == 1980, (adj, raw)


def test_lidar_dates_refuses_an_implausible_date_rather_than_inventing_one():
    """The out-of-range fallback used to return its second attempt UNCHECKED, so a tile with corrupt
    gps_time produced a nonsense date -- which --write records into course.json and every book then
    prints as its provenance. Better no date than an invented one."""
    import datetime as dt
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import lidar_dates as ld

    # both interpretations of a wildly wrong value must be rejected, and a value datetime cannot
    # represent at all must come back as None rather than raising OverflowError -- which is what a
    # corrupt tile used to do, crashing the tool with a traceback instead of skipping that tile
    lo = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    hi = dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc)
    for bad in (-5e9, 5e11, 1e18, float("inf")):
        for adj in (True, False):
            got = ld.gps_to_utc(bad, adjusted=adj)
            assert got is None or not (lo < got < hi), \
                f"{bad} (adjusted={adj}) should be rejected, got {got}"
    # Behavioural, not a source-text match: an inspect.getsource assertion still passed when the
    # guard was replaced by `if False:`. Write a real LAZ whose gps_time is corrupt and require
    # tile_dates to return None.
    import laspy
    import numpy as np
    import tempfile
    hdr = laspy.LasHeader(version="1.4", point_format=6)     # format 6 carries gps_time
    hdr.global_encoding.gps_time_type = 1
    las = laspy.LasData(hdr)
    n = 200
    las.x = np.linspace(0, 10, n); las.y = np.linspace(0, 10, n); las.z = np.zeros(n)
    las.gps_time = np.full(n, 5e11)                          # implausible under either reading
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "corrupt.laz")
        las.write(f)
        assert ld.tile_dates(f) is None, \
            "a tile whose gps_time is implausible under BOTH readings must yield no date"


@pytest.mark.slow          # lays both editions out in a browser
@needs_corpus
def test_the_enlarged_edition_really_is_enlarged_in_print():
    """Round 6 found the ENLARGED edition printing its greens at EXACTLY the pocket scale -- ratio
    1.00 on all 18 holes -- while the printed card, README and PIPELINE.md all said they were bigger.
    test_the_two_render_modes_are_actually_different guards the cause (the conforming render pins an
    inch size inline, the enlarged one must not), but nothing measured the EFFECT in print.

    Measured in a browser under print media, per hole, using the scale preserveAspectRatio="meet"
    actually applies -- min(w/vbWidth, h/vbHeight). Taking width alone gives the wrong answer
    whenever height is the limiting dimension, which it is for most greens; that mistake first told
    me the coach type was SMALLER than the pocket type.

    Because stroke widths and font sizes are expressed in the same user units, one ratio governs the
    green, the contour weights and the type together: 1.66x, so a 4.6-unit slope label prints 8.8 pt
    in the pocket book and 14.7 pt in the coach edition. "Bigger but worse" would show up here as a
    ratio near 1."""
    coach = sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook_coach.html")))
    coach = [f for f in coach if not os.path.basename(os.path.dirname(f)).startswith("_")]
    if not coach:
        pytest.skip("no coach edition built (COACH=1 python3 generate.py)")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import export_pdf
    exe = export_pdf._headless_shell()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    import pathlib
    import statistics
    JS = """(sel)=>[...document.querySelectorAll(sel)].map(s=>{
      const bb=s.getBoundingClientRect(); const vb=s.getAttribute('viewBox').split(' ').map(Number);
      const k=Math.min((bb.width/96)/vb[2], (bb.height/96)/vb[3]);
      const card=s.closest('.panel'); const hn=card&&card.querySelector('.hnum');
      return {hole: hn?+hn.textContent:null, k:k};})"""
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception:
            pytest.skip("no browser available")
        pg = b.new_page()
        checked = 0
        try:
            for cf in coach:
                pf = cf.replace("greenbook_coach.html", "greenbook.html")
                if not os.path.exists(pf):
                    continue
                scales = {}
                for tag, f, sel in (("pocket", pf, ".grn svg"), ("coach", cf, ".cmap svg")):
                    pg.goto(pathlib.Path(f).resolve().as_uri())
                    pg.emulate_media(media="print")
                    scales[tag] = {r["hole"]: r["k"] for r in pg.evaluate(JS, sel) if r["hole"]}
                common = sorted(set(scales["pocket"]) & set(scales["coach"]))
                assert len(common) >= 9, f"{cf}: only {len(common)} holes comparable"
                ratios = [scales["coach"][h] / scales["pocket"][h] for h in common]
                med = statistics.median(ratios)
                assert med > 1.3, (
                    f"{os.path.relpath(cf, ROOT)}: enlarged greens print at only {med:.2f}x the "
                    f"pocket scale -- the card claims they are larger than the tournament scale")
                assert min(ratios) > 1.1, (
                    f"{os.path.relpath(cf, ROOT)}: hole {common[ratios.index(min(ratios))]} prints "
                    f"at {min(ratios):.2f}x -- barely enlarged")
                checked += 1
        finally:
            b.close()
    assert checked > 0, "no course had both editions built"


def test_a_hole_never_binds_to_a_distant_green():
    """The worst thing this project can do is print a correctly-computed read of the WRONG putting
    surface, and the binding had no distance cap. A hole whose own green is missing from the OSM
    extract simply attached to the nearest one -- it has happened, bay-view hole 9 to hole 7's green,
    47.8 m away, after a truncated Overpass reply.

    Measured across all 198 built greens: worst legitimate binding 11.1 m (philadelphia h12), median
    2.0 m, and every green bound to exactly one hole. The 40 m cap therefore catches the known
    failure with room to spare and clears the worst real case by 3.6x.

    The cap lives in geo.match_green because this binding was written THREE times -- fetch_dem_hd.py,
    fetch_dem.py and render_hole.py -- so a cap added to one would have left the other two silent."""
    import geo

    def green(lat, lon, r=0.0002):
        return {"id": int(abs(lon) * 1e4), "geometry": [
            {"lat": lat - r, "lon": lon - r}, {"lat": lat - r, "lon": lon + r},
            {"lat": lat + r, "lon": lon + r}, {"lat": lat + r, "lon": lon - r},
            {"lat": lat - r, "lon": lon - r}]}

    lat0, lon0 = 40.0, -75.0
    near_green = green(lat0, lon0)
    # a centerline ending right on that green binds fine
    line = [{"lat": lat0 + 0.002, "lon": lon0}, {"lat": lat0, "lon": lon0}]
    g, gend, tend = geo.match_green(line, [near_green], label="hole 1")
    assert g is near_green and gend["lat"] == lat0 and tend["lat"] == lat0 + 0.002

    # ...and a green 60 m away -- further than the 40 m cap -- must be REFUSED, not used
    far = green(lat0 + 60.0 / geo.R_LAT, lon0)
    with pytest.raises(SystemExit) as e:
        geo.match_green(line[:1] + [{"lat": lat0 - 0.001, "lon": lon0}], [far], label="hole 9")
    assert "bind limit" in str(e.value) or "wrong putting surface" in str(e.value).lower()

    # the cap is stated where the measurement is, and is comfortably above the worst real binding
    assert 11.1 < geo.GREEN_BIND_MAX_M < 47.8, \
        f"the cap must sit between the worst real binding and the known mis-binding, got {geo.GREEN_BIND_MAX_M}"


def test_the_surface_builder_refuses_to_guess_a_zone_or_a_vertical_unit():
    """fetch_trees.py was hard-stopped on two silent guesses in 2912831; fetch_dem_hd.py carried the
    IDENTICAL code and was missed -- and it is the module that actually builds the green surfaces every
    printed slope comes from. A missing course.json "location" defaulted to lon -121.0, silently
    choosing California UTM zone 10 for a Pennsylvania course; and a CRS-less point cloud was assumed
    to be in that zone with metres for Z, which for a US-survey-foot cloud prints every slope 3.28x
    too steep."""
    src = open(os.path.join(ROOT, "fetch_dem_hd.py"), encoding="utf-8").read()
    assert '"lon", -121.0' not in src and "'lon', -121.0" not in src, \
        "fetch_dem_hd still defaults the course longitude -- that silently picks California zone 10"
    assert "src = UTM" not in src, \
        "fetch_dem_hd still assumes a CRS-less cloud is in the course UTM zone with metres for Z"
    # and both stops must be reachable failures, not comments (there are exactly two: the missing
    # location and the missing CRS -- counted, not guessed)
    assert src.count("raise SystemExit") >= 2, "the guards must actually stop the run"


def test_gps_week_time_is_refused_not_turned_into_september_2011():
    """global_encoding bit 0 == 0 means GPS WEEK TIME: seconds since the start of the current GPS
    week, with the week number recorded NOWHERE in the file, so the absolute date is not recoverable.

    The old code treated bit 0 == 0 as raw standard GPS time. That put the value near 1980, failed the
    2000-2040 plausibility window, flipped to the +1e9 interpretation, and landed on
    1980-01-06 + 1e9 s = 2011-09-14 -- INSIDE the window. So every week-time tile silently produced a
    fabricated September-2011 flight date, which --write records into course.json and every book then
    prints as its provenance."""
    import laspy
    import numpy as np
    import tempfile
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import lidar_dates as ld

    def write_tile(path, gtt, gps_values):
        hdr = laspy.LasHeader(version="1.4", point_format=6)
        hdr.global_encoding.gps_time_type = gtt
        las = laspy.LasData(hdr)
        n = len(gps_values)
        las.x = np.linspace(0, 10, n); las.y = np.linspace(0, 10, n); las.z = np.zeros(n)
        las.gps_time = np.asarray(gps_values, dtype="float64")
        las.write(path)
        with laspy.open(path) as f:      # prove the encoding stuck
            assert int(f.header.global_encoding.gps_time_type) == gtt
        return path

    # a real instant: monarch-bay's true flight, 2019-08-14 15:04:01Z
    import datetime as dt
    inst = dt.datetime(2019, 8, 14, 15, 4, 1, tzinfo=dt.timezone.utc)
    standard = (inst - dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)).total_seconds() + 18
    with tempfile.TemporaryDirectory() as td:
        ok = write_tile(os.path.join(td, "adjusted.laz"), 1, [standard - 1e9] * 64)
        got = ld.tile_dates(ok)
        assert got and got[0].date() == inst.date(), f"adjusted time must decode exactly, got {got}"

        # week time: 0..604800 seconds, no week number anywhere
        wk = write_tile(os.path.join(td, "weektime.laz"), 0, [345_600.0] * 64)
        assert ld.tile_dates(wk) is None, \
            "GPS Week Time carries no week number -- the date is not recoverable and must be refused"


@needs_corpus
def test_the_printed_flight_date_spans_every_point_not_just_the_first_few():
    """tools/lidar_dates.py read only the first 2M points of each tile -- 2% of the largest one here --
    so it reported a NARROWER survey than the data holds, and that narrower claim reached print:
    Callippe's book said "flown 2021-06-21", a single day, for a survey that ran 2021-06-21 to
    2021-07-02. Castlewood Valley was wrong the same way. A full scan costs 6-8 s per course.

    This re-derives the span from EVERY point OVER A GREEN, independently of the module, and requires
    each course's printed label to cover it. Dates are the LOCAL flight day, not the UTC day:
    topographic LiDAR is often flown at night, so bay-view's whole survey ran 20:39-21:55 local on
    2020-04-14 while the UTC date is the 15th. The zone is derived here from a CONUS longitude band
    rather than imported, so the test does not inherit the module's own mapping.

    Restricted to points over the greens because the label is: the tile set is chosen by bbox overlap
    with the whole course, so it includes neighbours that feed no green, and folding them in widened
    the claim. The Reserve's t390135.laz spans 2017-12-16..2018-01-21 with no point within 60 m of a
    green, and the book printed "flown 2017-12-15 to 2018-01-21" for greens flown on two days. The
    green geometry and the padding are computed here rather than imported, for the same
    independence reason. See test_flight_date_is_dated_from_the_points_under_the_greens."""
    import datetime as dt
    import laspy
    import numpy as np
    from zoneinfo import ZoneInfo
    EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)

    def zone_of(lat, lon):
        if lat is None or lon is None or not (-125.0 <= lon <= -66.9 and 24.0 <= lat <= 49.5):
            return None
        return ZoneInfo("America/Los_Angeles" if lon < -114 else
                        "America/Denver" if lon < -102 else
                        "America/Chicago" if lon < -87 else "America/New_York")

    checked = 0
    for slug in CORPUS:
        cj = os.path.join(ROOT, "courses", slug, "course.json")
        tiles = sorted(glob.glob(os.path.join(ROOT, "courses", slug, "laz", "*.laz")))
        cfg = json.load(open(cj))
        lab = (cfg.get("lidar_flown") or {}).get("label")
        loc = cfg.get("location") or {}
        tz = zone_of(loc.get("lat"), loc.get("lon"))
        if not tiles or not lab:
            continue
        rings = []
        try:
            for e in json.load(open(os.path.join(ROOT, "courses", slug,
                                                 "osm_geom.json")))["elements"]:
                if e.get("geometry") and (e.get("tags") or {}).get("golf") == "green":
                    rings.append([(q["lon"], q["lat"]) for q in e["geometry"]])
        except Exception:
            pass
        if not rings:
            continue
        lo = hi = None
        # scan until two tiles have actually yielded points over a green; neighbours that cover no
        # green would otherwise use up the budget and the check would silently pass on nothing
        used = 0
        for p in tiles:
            if used >= 2:
                break
            with laspy.open(p) as f:
                if int(getattr(f.header.global_encoding, "gps_time_type", 0)) == 0:
                    continue
                crs = f.header.parse_crs()
                if crs is None:
                    continue
                from pyproj import Transformer
                T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
                per_unit = (crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0) or 1.0
                pad = 30.0 / per_unit
                boxes = []
                for ring in rings:
                    xy = [T.transform(lo_, la_) for lo_, la_ in ring]
                    xs = [c[0] for c in xy]; ys = [c[1] for c in xy]
                    boxes.append((min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad))
                seen = False
                for ch in f.chunk_iterator(2_000_000):
                    t = np.asarray(ch.gps_time)
                    x = np.asarray(ch.x); y = np.asarray(ch.y)
                    sel = np.zeros(len(t), dtype=bool)
                    for x0, x1, y0, y1 in boxes:
                        sel |= (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
                    sel &= t > 0
                    if sel.any():
                        seen = True
                        tv = t[sel]
                        a, b = float(tv.min()), float(tv.max())
                        lo = a if lo is None else min(lo, a)
                        hi = b if hi is None else max(hi, b)
                if seen:
                    used += 1
        if lo is None:
            continue
        def f2d(v):
            u = EPOCH + dt.timedelta(seconds=v + 1e9 - 18)
            return (u.astimezone(tz) if tz else u).date()
        first, last = f2d(lo), f2d(hi)
        # the label must not be NARROWER than what the points show
        assert str(first) in lab, f"{slug}: points start {first} but the label says {lab!r}"
        if last != first:
            assert str(last) in lab, (
                f"{slug}: points run to {last} but the label says {lab!r} -- the book would claim a "
                f"shorter survey than the data")
        checked += 1
    assert checked >= 2, f"only {checked} courses had tiles to check"


def test_the_density_and_coverage_gate_measures_the_green_itself():
    """Two blind spots in the gate that decides whether a green may be read at all.

    nan_frac came from griddata's LINEAR pass, which returns NaN only OUTSIDE the point cloud's convex
    hull -- so it answered "is the green inside the hull?", not "was the green measured?". An INTERIOR
    void is inside the hull and gets spanned by the interpolation: deleting every return in a 6 m
    circle at each green centre (about a quarter of a 450 m^2 green, the footprint of standing water,
    which absorbs 1064 nm and returns nothing) still reported nan_frac=0.0000 and insufficient=False
    while changing 7 of 18 printed reads. The gate now also requires a ground return within 1 m of
    every green node.

    And density divided a PADDED prefilter's point count by the UNPADDED bbox -- which itself includes
    12 m of fairway and bunker -- so the figure was neither a green density nor consistent with its own
    divisor, and gen_provenance publishes it as density "over N greens". It is now counted inside the
    green ring over the ring's true area. Every published figure changed; the corpus worst is 4.7
    pts/m^2 against a 4.0 floor."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_dem_hd"):
        sys.modules.pop(m, None)
    try:
        import fetch_dem_hd as fdh
    except Exception as e:
        pytest.skip(f"fetch_dem_hd not importable: {type(e).__name__}")

    # Ring area, against a square whose area is known in closed form. The square must sit at the
    # BOUND course's location: fetch_dem_hd's TR transformer is module-level and fixed to that
    # course's UTM zone, so a Pennsylvania square projected through California zone 10 measures
    # 1330 m2 instead of 900 -- which is what my first attempt did.
    import config as _cfg
    lat0 = _cfg.COURSE["location"]["lat"]; lon0 = _cfg.COURSE["location"]["lon"]
    side_m = 30.0
    dlat = side_m / R_LAT
    dlon = side_m / _mlon(lat0)
    ring = [{"lat": lat0, "lon": lon0}, {"lat": lat0, "lon": lon0 + dlon},
            {"lat": lat0 + dlat, "lon": lon0 + dlon}, {"lat": lat0 + dlat, "lon": lon0},
            {"lat": lat0, "lon": lon0}]
    got = fdh._ring_area_m2(ring)
    assert abs(got - side_m * side_m) / (side_m * side_m) < 0.02, \
        f"a {side_m}x{side_m} m ring should measure ~{side_m**2} m2, got {got:.1f}"

    # the gate must consider coverage, not only hull membership
    src = open(os.path.join(ROOT, "fetch_dem_hd.py"), encoding="utf-8").read()
    assert "UNCOVERED_MAX" in src and "uncovered > UNCOVERED_MAX" in src, \
        "the insufficient verdict must include the coverage test, not just nan_frac and density"
    assert "cKDTree" in src, "coverage needs a nearest-return query"
    assert 0 < fdh.COVER_R_M <= 2.0 and 0 < fdh.UNCOVERED_MAX <= 0.10


@needs_corpus
def test_every_built_green_records_its_coverage():
    """The gate's inputs must be recorded in the meta, so a printed read can be audited after the
    fact rather than taken on trust. Measured across the corpus: worst uncovered share 0.9%, worst
    in-green density 4.7 pts/m^2 against a 4.0 floor."""
    import json as _json
    checked = 0
    worst_unc = 0.0
    worst_dens = 1e9
    for mf in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "dem_hd", "hole*.json"))):
        if os.path.basename(os.path.dirname(os.path.dirname(mf))).startswith("_"):
            continue
        m = _json.load(open(mf))
        if "seamless" in str(m.get("source", "")).lower():
            continue                       # the 1 m fallback path records its own keys
        assert "uncovered" in m, f"{mf} has no coverage figure -- the gate's input is unrecorded"
        assert m.get("density") is not None and m.get("nan_frac") is not None
        worst_unc = max(worst_unc, float(m["uncovered"]))
        worst_dens = min(worst_dens, float(m["density"]))
        checked += 1
    assert checked >= 150, f"only {checked} point-cloud greens found"
    assert worst_unc <= 0.02, f"worst uncovered share {worst_unc:.3f} exceeds the gate"
    assert worst_dens >= 4.0, f"worst in-green density {worst_dens} is below the gate floor"


def test_one_junk_gps_time_cannot_drag_a_whole_survey_back_eight_years():
    """One junk-but-positive gps_time was enough to set a survey's first date. With adjusted time, 1.0
    decodes to 1980-01-06 + 1e9 s = 2011-09-14, so a single bad value in a 100M-point tile would have
    printed "flown 2011-09-14" for a 2021 survey.

    My first fix was a per-value plausibility window, and this test proved it useless: 2011 IS inside
    the 2000-2040 window and is indistinguishable from a genuine 2011 flight, so no filter on the
    value can reject it. What gives it away is the SPAN -- a real acquisition is days, not a decade --
    so a tile spanning more than two years is refused outright."""
    import datetime as dt
    import laspy
    import numpy as np
    import tempfile
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import lidar_dates as ld

    inst = dt.datetime(2021, 6, 21, 19, 30, tzinfo=dt.timezone.utc)
    standard = (inst - dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)).total_seconds() + 18
    good = standard - 1e9

    hdr = laspy.LasHeader(version="1.4", point_format=6)
    hdr.global_encoding.gps_time_type = 1
    las = laspy.LasData(hdr)
    n = 128
    las.x = np.linspace(0, 10, n); las.y = np.linspace(0, 10, n); las.z = np.zeros(n)
    times = np.full(n, good)
    times[0] = 1.0                     # junk, positive, decodes to 2011-09-14
    times[1] = 0.5
    las.gps_time = times
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "junk.laz")
        las.write(f)
        got = ld.tile_dates(f)
        assert got is None, (
            f"a tile whose gps_time spans {inst.year} back to 2011 is not one acquisition and must "
            f"be refused, got {got}")
        # ...while a clean tile of the same points still dates correctly
        las.gps_time = np.full(n, good)
        f2 = os.path.join(td, "clean.laz")
        las.write(f2)
        ok = ld.tile_dates(f2)
        assert ok and ok[0].date() == inst.date(), f"clean tile should date to {inst.date()}, got {ok}"


def test_course_json_is_written_atomically():
    """course.json is HAND-AUTHORED -- the scorecard transcription, the bbox, the tee table -- and
    nothing regenerates it. tools/lidar_dates.py --write rewrote it in place, so a crash or a full
    disk truncates it, in a directory the project documents as unrecoverable."""
    src = open(os.path.join(ROOT, "tools", "lidar_dates.py"), encoding="utf-8").read()
    assert 'json.dump(j, open(p, "w")' not in src, "course.json must not be written in place"
    assert "os.replace(tmp, p)" in src, "the write must be staged and renamed"


@needs_corpus
def test_each_card_footer_matches_its_own_map():
    """Each hole card prints "5B 1W" directly under its map. A reader checks that against the shapes
    on the same card, so the footer must describe THAT MAP.

    This test replaces one that asserted the wrong property. Wanting the per-hole counts to sum to no
    more than the course total, I changed the count to "features whose nearest hole is this one,
    within 90 m" while drawing still used the 40 m corridor -- and the footer stopped matching its own
    map on 115 of 198 cards. Merion hole 3 printed "2B" beside eight drawn bunkers; 23 cards printed a
    ZERO with the feature drawn; 15 printed more than the map showed. The sum is a number nobody
    computes; the footer under the map is one a 12-year-old reads directly. So the footer counts what
    is drawn, and a bunker between two parallel holes appears on both cards -- it is in play on both.

    Measured on the shipped HTML rather than on the engine's return value, because the defect was
    precisely a disagreement between the two."""
    bad = []
    checked = 0
    for slug in CORPUS:
        f = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not os.path.exists(f):
            continue
        html = open(f, encoding="utf-8").read()
        for panel in re.findall(r'<div class="panel hole">.*?(?=<div class="panel|\Z)', html, re.S):
            m = re.search(r"(\d+)B (\d+)W", panel)
            if not m:
                continue
            checked += 1
            footer = (int(m.group(1)), int(m.group(2)))
            drawn = (panel.count('fill="#efe3b8"'), panel.count('fill="#a9d3ef"'))
            if footer != drawn:
                bad.append((slug, footer, drawn))
    assert checked >= 150, f"only {checked} hole cards examined"
    assert not bad, (f"{len(bad)} of {checked} cards print a count that contradicts their own map "
                     f"(slug, footer, drawn): {bad[:6]}")


def test_multipolygon_relations_become_drawable_features(tmp_path):
    """On many courses the fairways are mapped as MULTIPOLYGON RELATIONS, not ways, and the course
    query only asked for way[...]. Measured live against Overpass: valley-hi has 18 fairway relations
    and 0 fairway ways, monarch-bay 36, the-reserve 18 -- so those books drew NO fairway at all while
    every card set's legend promises "fairway (green)". The largest feature of a golf hole was missing
    from the map.

    Three things had to be right, and each was wrong in turn.

    1. Adding relation[...] to the main query is not sufficient: under `out geom` Overpass answers a
       relation with bounds and tags only, so the reply held 18 fairways with no geometry that every
       consumer skipped.
    2. The recurse-down form `(._;>;); out geom;` does return member geometry, but it pulls every
       member NODE and does not complete -- four attempts against valley-hi returned 504, 504, 429,
       504. The working form asks for relation BODIES (tags + member refs) and separately for the
       member WAYS with inline geometry, then joins them by way id: 1.3 s on the same bbox.
    3. The flattened rings have to be WRITTEN BACK. fetch() saves osm_course.json before the relation
       pass runs, so appending to the in-memory dict alone left the file unchanged -- the printed
       feature counts said 18 fairways while the file every consumer reads had none. Caught by
       diffing the written file's counts against its backup: identical, no 'fairway' key at all.

    This tests the normalisation and the write-back, offline."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_osm"):
        sys.modules.pop(m, None)
    import fetch_osm

    ring = [{"lat": 40.0, "lon": -75.0}, {"lat": 40.0, "lon": -74.999},
            {"lat": 40.001, "lon": -74.999}, {"lat": 40.0, "lon": -75.0}]
    inner = [{"lat": 40.0005, "lon": -74.9995}, {"lat": 40.0006, "lon": -74.9994},
             {"lat": 40.0007, "lon": -74.9995}, {"lat": 40.0005, "lon": -74.9995}]
    # the shape the working query returns: relation bodies (member refs, NO geometry) plus the member
    # ways with inline geometry
    els = [
        {"type": "relation", "id": 555, "tags": {"golf": "fairway"}, "members": [
            {"type": "way", "ref": 11, "role": "outer"},
            {"type": "way", "ref": 12, "role": "outer"},
            {"type": "way", "ref": 13, "role": "inner"},
        ]},
        {"type": "way", "id": 11, "geometry": ring},
        {"type": "way", "id": 12, "geometry": ring},
        {"type": "way", "id": 13, "geometry": inner},
        # the shape Overpass returns for a relation with no members resolved: bounds and tags only
        {"type": "relation", "id": 556, "tags": {"golf": "fairway"}, "bounds": {}},
    ]
    out = fetch_osm._flatten_relations(els)

    assert all(e.get("type") != "relation" for e in out), "no relation may survive flattening"
    fw = [e for e in out if (e.get("tags") or {}).get("golf") == "fairway"]
    assert len(fw) == 2, f"expected the 2 OUTER rings as separate ways, got {len(fw)}"
    assert all(e.get("geometry") for e in fw), "a flattened ring must carry geometry"
    assert all(e["tags"]["golf"] == "fairway" for e in fw), "the relation's tags must be inherited"
    assert len({e["id"] for e in fw}) == 2, "each ring needs its own id"
    assert all(e.get("_from_relation") == 555 for e in fw), "keep the trace back to the relation"
    # the inner ring must NOT become fairway -- filling a hole in the polygon is worse than omitting
    assert not any(len(e.get("geometry") or []) and e["geometry"][0]["lat"] == 40.0005 for e in fw), \
        "inner rings must be skipped"

    # a member way whose geometry never arrived must be reported, not silently dropped -- silence is
    # how the fairways went missing in the first place
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fetch_osm._flatten_relations([els[0], els[1]])       # way 12 absent
    assert "WARNING" in buf.getvalue(), \
        f"a missing outer ring must warn; got: {buf.getvalue()!r}"

    # and main() must write osm_course.json AFTER appending the flattened rings
    src = open(os.path.join(ROOT, "fetch_osm.py"), encoding="utf-8").read()
    i = src.index("_flatten_relations(rel['elements'])")
    tail = src[i:i + 900]
    assert "os.replace" in tail and "osm_course.json" in tail, \
        ("the flattened rings must be written back to osm_course.json; appending to the in-memory "
         "dict alone left every consumer reading a file with no fairways")

    # And the QUERY must actually retrieve member geometry. Checking the whole file for a substring
    # was a weak test -- the forms appear in explanatory comments too, so gutting the real query still
    # passed. Look only at the query text between the relation selector and its final out statement.
    assert 'relation["golf"]' in src, "the course fetch must ask for golf relations"
    i = src.index('relation["golf"]')
    j = src.index("out geom;", i)
    query = src[i:j]
    assert "out body;" in query and "way(r);" in query, (
        "the relation query must fetch relation bodies (tags + member refs) AND their member ways "
        "with geometry, or every fairway arrives without geometry and is skipped. Query was:\n"
        + query)
    assert "(._;>;)" not in query, (
        "the recurse-down form pulls every member node and times out on real course bboxes -- "
        "four attempts against valley-hi returned 504, 504, 429, 504. Query was:\n" + query)


def _synthetic_laz(path, epsg, ring_lonlat, near_utc, far_utc, far_offset_m=2000.0,
                   near_offset_m=0.0):
    """A tiny LAZ whose points carry known gps_times: some at a green, some far away."""
    import datetime as dt

    import laspy
    import numpy as np
    from pyproj import CRS, Transformer

    gps_epoch = dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)
    to_gps = lambda d: (d - gps_epoch).total_seconds() + 18 - 1e9   # noqa: E731 - adjusted std GPS
    crs = CRS.from_epsg(epsg)
    per_unit = (crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0) or 1.0
    T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    cx = sum(T.transform(lo, la)[0] for lo, la in ring_lonlat) / len(ring_lonlat)
    cy = sum(T.transform(lo, la)[1] for lo, la in ring_lonlat) / len(ring_lonlat)

    h = laspy.LasHeader(version="1.4", point_format=6)
    h.global_encoding.gps_time_type = 1            # adjusted standard GPS time
    h.add_crs(crs)
    las = laspy.LasData(h)
    n = 100
    off_near, off_far = near_offset_m / per_unit, far_offset_m / per_unit
    las.x = np.concatenate([np.full(n, cx + off_near), np.full(n, cx + off_far)])
    las.y = np.concatenate([np.full(n, cy), np.full(n, cy + off_far)])
    las.z = np.zeros(2 * n)
    las.gps_time = np.concatenate([np.full(n, to_gps(near_utc)), np.full(n, to_gps(far_utc))])
    las.write(str(path))
    return str(path)


def test_derived_artifacts_are_not_older_than_their_inputs():
    """The pipeline is a chain -- osm_geom/osm_course -> dem_hd -> trees_lidar -> greenbook.html --
    and re-running one stage without the ones downstream leaves a book built from mixed vintages.

    That happened, and only the cold-build test caught it. Re-fetching OSM to recover the fairways
    changed which polygons trees may sit on; the books were rebuilt but fetch_trees.py was not, so 7
    courses drew trees that the new fairways should have dropped. Micke Grove was the measurable
    case: 5,657 markers committed against 5,642 on a fresh run, exactly the 15 markers now falling on
    newly-visible fairway.

    Nothing printed was untrue -- those trees are really there -- but the artifacts no longer matched
    their inputs, and byte-for-byte reproducibility is the property that makes the provenance claims
    checkable. mtime is a weak signal (a copied or freshly checked-out tree rewrites it), so this
    reports rather than asserts unless the ordering is violated by a wide margin."""
    SLACK = 120          # seconds; tolerate same-run jitter between stages
    chain = [
        ("osm_course.json", "trees_lidar.json"),
        ("osm_geom.json", "trees_lidar.json"),
        ("osm_geom.json", "greenbook.html"),
        ("trees_lidar.json", "greenbook.html"),
    ]
    problems = []
    checked = 0
    for slug in CORPUS:
        cdir = os.path.join(ROOT, "courses", slug)
        for src, derived in chain:
            sp, dp = os.path.join(cdir, src), os.path.join(cdir, derived)
            if not (os.path.isfile(sp) and os.path.isfile(dp)):
                continue
            checked += 1
            lag = os.path.getmtime(sp) - os.path.getmtime(dp)
            if lag > SLACK:
                problems.append(f"{slug}: {derived} is {lag / 60:.0f} min older than {src}")
    assert checked, "no course has both an input and a derived artifact to compare"
    assert not problems, (
        "derived artifacts predate their inputs -- re-run the downstream stages:\n  "
        + "\n  ".join(problems)
        + "\n  (osm -> fetch_dem_hd.py -> fetch_trees.py -> generate.py -> tools/export_pdf.py)")


def test_no_green_is_bound_to_two_holes():
    """geo.match_green caps how FAR a hole may reach for a green (40 m, after bay-view hole 9 bound
    to hole 7's green 47.8 m away). It cannot catch the NEAR case, and the near case is likelier: if
    a hole's own green drops out of the OSM extract while a neighbour's green sits inside the cap,
    both holes bind there, both cards print that surface, and one is a confident read of the wrong
    putting green. match_green is called once per hole and has no view of the others.

    Measured across all 11 built courses: 0 greens bound to more than one hole, worst legitimate bind
    11.1 m -- so the guard only ever fires on a real fault."""
    for m in ("geo",):
        sys.modules.pop(m, None)
    import geo

    g1 = {"id": 101, "geometry": [{"lat": 1.0, "lon": 2.0}]}
    g2 = {"id": 102, "geometry": [{"lat": 1.0, "lon": 2.001}]}
    geo.assert_one_green_per_hole({1: g1, 2: g2}, label="t")          # distinct -> quiet

    with pytest.raises(SystemExit) as e:
        geo.assert_one_green_per_hole({7: g1, 9: g1}, label="bay-view")
    msg = str(e.value)
    assert "hole 7" in msg and "hole 9" in msg and "101" in msg, msg
    assert "wrong putting surface" in msg, "the message must say what the consequence is"

    # greens with no id must still be told apart by identity, not silently collapsed
    a, b = {"geometry": []}, {"geometry": []}
    geo.assert_one_green_per_hole({1: a, 2: b})
    with pytest.raises(SystemExit):
        geo.assert_one_green_per_hole({1: a, 2: a})

    # and the builders must actually call it, or the invariant is unenforced
    for mod in ("fetch_dem_hd.py", "fetch_dem.py"):
        src = open(os.path.join(ROOT, mod), encoding="utf-8").read()
        assert "assert_one_green_per_hole" in src, f"{mod} never checks for a shared green"

    # fetch_dem.py used to name a local list `geo`, shadowing the module; it worked only because
    # `import geo` sat inside the loop. Moving that import to the top -- the obvious tidy-up -- would
    # have made geo.match_green() an AttributeError on a list from the second hole onward.
    fd = open(os.path.join(ROOT, "fetch_dem.py"), encoding="utf-8").read()
    assert "for p in geo]" not in fd, "a local named `geo` is shadowing the geo module again"

    # the real corpus must satisfy it
    for slug in CORPUS:
        seen = {}
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
            gid, hn = meta.get("green_id"), meta.get("hole")
            if gid is None:
                continue
            assert gid not in seen, f"{slug}: green {gid} bound to holes {seen[gid]} and {hn}"
            seen[gid] = hn


def test_each_tee_column_carries_the_right_tee_name():
    """A card prints a yardage under a TEE NAME, and a junior picks their tee by that name. Two
    separate structures have to agree for that to be true: `hole_cols` names the per-hole yardage
    columns, and `tees` carries each set's total with its rating and slope. Nothing checked that the
    column called "White" really is the White column.

    The mapping is not positional, which is what makes this worth asserting: Philadelphia's per-hole
    columns correspond to declared tee sets 0, 1, 2 and 4, and The Reserve's to 0, 1, 2, 4 and 6,
    because both courses declare COMBO tees (Blu/Wht, Wht/Grn) that have a scorecard total but no
    per-hole column. Mapping column i to tees[i] would therefore print "Green" over the Gold
    yardages at Philadelphia. Measured across the corpus: 51 name-to-column pairs, all consistent.

    Also checks featured_tee/secondary_tee -- the two names printed on every hole card -- actually
    name per-hole columns, since config.py resolves them with TEES.index() and would otherwise be
    reading a yardage from the wrong column."""
    pairs = 0
    problems = []
    for slug in CORPUS:
        with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as f:
            j = json.load(f)
        holes = j.get("holes") or {}
        cols = (j.get("hole_cols") or [])[2:]
        tees = j.get("tees") or []
        if not holes or not cols:
            continue
        ks = sorted(holes, key=lambda x: int(x))
        ncol = min(len(holes[k]) for k in ks) - 2
        if len(cols) != ncol:
            problems.append(f"{slug}: hole_cols names {len(cols)} column(s), rows carry {ncol}")
            continue
        declared = {t.get("name"): t.get("yards") for t in tees}
        for i, name in enumerate(cols):
            total = sum(holes[k][2 + i] for k in ks)
            if name not in declared:
                problems.append(f"{slug}: column {name!r} is absent from the tee table")
            elif isinstance(declared[name], int):
                pairs += 1
                if total != declared[name]:
                    problems.append(
                        f"{slug}: column {name!r} sums to {total} but the tee table says "
                        f"{declared[name]} -- one of the two printed numbers is wrong")
        for field in ("featured_tee", "secondary_tee"):
            v = j.get(field)
            if v is not None and v not in cols:
                problems.append(f"{slug}: {field}={v!r} is not one of the per-hole columns {cols}")
    assert not problems, "tee labelling disagrees with the tee table:\n  " + "\n  ".join(problems)
    assert pairs >= 20, f"only {pairs} tee/column pairs checked -- the corpus should offer far more"


def test_one_shared_rule_decides_what_may_be_distributed():
    """legal/03_PROVENANCE_BY_COURSE.md marks each course Distributed or Personal, and its own legend
    defines Personal as *do not distribute*; legal/00_SUMMARY_AND_VERDICT.md names Poppy Ridge as
    personal-use only. That rule lived inside tools/gen_provenance.py, where it decided a table
    column and nothing else -- so when a second publisher appeared (the iOS app's exporter) it
    bundled every course it found, Poppy Ridge included, and would have shipped a book the project's
    own legal record says must not be distributed.

    It now lives in distribution.py and both the generator and any publisher ask it, so the two
    cannot drift. An App Store build, a web download and a handed-out printout are all
    distribution."""
    for m in ("distribution",):
        sys.modules.pop(m, None)
    import distribution

    ok, label, why = distribution.distribution_status({"slug": "x"})
    assert ok is True and label == "Distributed" and why == ""
    ok2, label2, why2 = distribution.distribution_status({"slug": "y", "build_mode": "yardage"})
    assert ok2 is False and label2 == "Personal" and why2, "a Personal course needs a stated reason"
    assert distribution.is_distributable({"slug": "x"}) is True
    assert distribution.is_distributable({"slug": "y", "build_mode": "yardage"}) is False
    assert distribution.is_distributable({}) is True, \
        "an ordinary course with no build_mode is distributable; this documents the default"

    # It must FAIL CLOSED, because this decides whether a book may be handed out.
    # None means the course record could not be read -- an exact == "yardage" test answered
    # "Distributed" for that, i.e. took a publish decision on no information at all.
    assert distribution.is_distributable(None) is False, \
        "an unreadable course record must not resolve to publishable"
    # ...and the mode must be normalised. "YARDAGE" and " yardage" both answered "Distributed",
    # so a stray capital or space in a HAND-EDITED course.json would have shipped a personal-use
    # book. course.json is hand-edited: it holds the scorecard transcription.
    for variant in ("YARDAGE", " yardage", "Yardage", "yardage\n", "\tYardage "):
        assert distribution.is_distributable({"build_mode": variant}) is False, \
            f"build_mode={variant!r} must still read as Personal"

    # the generator must consult it rather than re-deriving the rule
    src = open(os.path.join(ROOT, "tools", "gen_provenance.py"), encoding="utf-8").read()
    assert "distribution.distribution_status" in src, \
        "gen_provenance.py must use the shared rule, or the record can disagree with what ships"
    assert 'status = "Personal" if' not in src, "the inline copy of the rule must be gone"

    # and the real corpus must agree with the record: every course the generator calls Personal
    # really is in yardage mode, and vice versa
    if not CORPUS:
        return
    doc = os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")
    if not os.path.isfile(doc):
        return
    rows = [ln for ln in open(doc, encoding="utf-8")
            if ln.startswith("| ") and not ln.startswith("| Course |")]
    n_personal_doc = sum(1 for ln in rows if "| Personal |" in ln)
    n_personal_data = 0
    for slug in sorted({os.path.basename(os.path.dirname(p))
                        for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))}):
        if slug.startswith("_"):
            continue
        with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as f:
            if not distribution.is_distributable(json.load(f)):
                n_personal_data += 1
    assert n_personal_doc == n_personal_data, (
        f"the record marks {n_personal_doc} course(s) Personal but the shared rule says "
        f"{n_personal_data}")


def test_a_present_tile_is_not_assumed_to_cover_the_greens(tmp_path):
    """Nothing checked that a downloaded tile's DATA reaches the greens. A tile can be present,
    correctly named, and hold no points where a green is -- and the green then silently falls back to
    the 1 m seamless DEM even though 0.4 m LiDAR for it exists.

    Castlewood Hill shipped holes 14 and 16 that way. Measured: both greens fall in grid cell
    w6153n2055; the copy on disk (CA_AlamedaCo_1_2021, 30,648,617 bytes) has a data footprint of only
    x 6153000..6153470 -- a 470-ft strip of a 3000-ft cell -- while the greens sit at x 6155652 and
    x 6155938, some 2,200-2,500 ft east of that edge, and the next tile east starts at x 6156000.
    CA_AlamedaCo_3_2021 holds a 689,926,608-byte copy of the same cell, 22x larger, which was skipped
    as "cached" for sharing a filename.

    The check reads each tile's HEADER bbox, which records the extent of the points actually in the
    file rather than the nominal grid cell -- that distinction is the whole bug. It reports rather
    than refuses: a bayside green over water genuinely has no returns, and the 1 m fallback with a
    "1 m data" label is the honest outcome. What it stops is the silent version."""
    pytest.importorskip("laspy")
    pytest.importorskip("pyproj")
    import lidar_coverage as lc

    lon, lat = -121.35, 38.05
    d = 0.0002

    def ring(dlon=0.0, dlat=0.0, scale=1.0):
        r = d * scale
        return [{"lon": lon + dlon - r, "lat": lat + dlat - r},
                {"lon": lon + dlon + r, "lat": lat + dlat - r},
                {"lon": lon + dlon + r, "lat": lat + dlat + r},
                {"lon": lon + dlon - r, "lat": lat + dlat + r}]

    (tmp_path / "laz").mkdir()
    # green 1 sits inside the tile's data. Green 2 is 3 km away, like Castlewood Hill's 14 and 16.
    # Green 3 is the PARTIAL case -- its centroid is inside the data but its edges run past it, which
    # is what Monarch Bay's green 689151368 looks like (29 of 95 nodes uncovered). A check that only
    # tested centroids would call green 3 covered and print a read for ground it never measured.
    (tmp_path / "osm_geom.json").write_text(json.dumps({"elements": [
        {"type": "way", "id": 1, "tags": {"golf": "green"}, "geometry": ring()},
        {"type": "way", "id": 2, "tags": {"golf": "green"}, "geometry": ring(dlon=0.035)},
        {"type": "way", "id": 3, "tags": {"golf": "green"}, "geometry": ring(scale=4.0)},
    ]}))

    # with no tiles at all the check must stay quiet rather than claim everything is missing
    assert lc.uncovered_greens(str(tmp_path)) == []

    def write_tile(path, ring_pts, pad_m):
        """A LAZ whose points span ring_pts' bbox grown by pad_m -- so its HEADER footprint does."""
        import laspy
        import numpy as np
        from pyproj import CRS, Transformer
        crs = CRS.from_epsg(26910)
        T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        xy = [T.transform(q["lon"], q["lat"]) for q in ring_pts]
        x0 = min(c[0] for c in xy) - pad_m; x1 = max(c[0] for c in xy) + pad_m
        y0 = min(c[1] for c in xy) - pad_m; y1 = max(c[1] for c in xy) + pad_m
        h = laspy.LasHeader(version="1.4", point_format=6)
        h.global_encoding.gps_time_type = 1
        h.add_crs(crs)
        las = laspy.LasData(h)
        las.x = np.array([x0, x1, x0, x1]); las.y = np.array([y0, y0, y1, y1])
        las.z = np.zeros(4)
        las.gps_time = np.full(4, 1.32e9)
        las.write(str(path))

    write_tile(tmp_path / "laz" / "a.laz", ring(), 5.0)

    bad = lc.uncovered_greens(str(tmp_path))
    by_id = {gid: (o, t) for gid, o, t in bad}
    assert set(by_id) == {2, 3}, (
        f"flagged {sorted(by_id)}; expected green 2 (3 km away) and green 3 (partially outside), "
        f"with green 1 inside the tile's data")
    assert by_id[2][0] == by_id[2][1], f"green 2 is wholly outside: {by_id[2]}"
    assert 0 < by_id[3][0] < by_id[3][1], (
        f"green 3 is PARTIALLY outside: {by_id[3]}. Its centroid is inside the data, so a check that "
        f"sampled only the centroid would pass it -- and print a read for unmeasured ground.")

    # the footprint must come from the tile HEADER, i.e. where the points are -- not from a
    # nominal cell. A header covering only a sliver must not vouch for the whole neighbourhood.
    foot = lc.tile_footprints(str(tmp_path / "laz"))
    assert len(foot) == 1
    _name, _crs, x0, x1, y0, y1 = foot[0]
    assert (x1 - x0) < 150 and (y1 - y0) < 150, \
        (f"footprint {x1 - x0:.0f}x{y1 - y0:.0f} m is not the extent of the points written -- a "
         f"nominal 3000-ft cell would be ~914 m, which is exactly the wrong answer")

    # HOLE centrelines are checked too, not just greens. The greens-only check flagged Castlewood
    # Hill's holes 14 and 16 but not 15 and 17, whose centrelines run through the same gap -- and the
    # centreline is where fetch_trees.py looks for canopy returns, so those holes lose their trees
    # with nothing said. Measured: 9 of 11 courses have every centreline node inside the data.
    els = json.loads((tmp_path / "osm_geom.json").read_text())["elements"]
    els.append({"type": "way", "id": 90, "tags": {"golf": "hole", "ref": "7"},
                "geometry": [{"lon": lon, "lat": lat},                    # inside
                             {"lon": lon + 0.035, "lat": lat}]})          # 3 km away, outside
    els.append({"type": "way", "id": 91, "tags": {"golf": "hole", "ref": "8"},
                "geometry": [{"lon": lon, "lat": lat}]})                  # wholly inside
    (tmp_path / "osm_geom.json").write_text(json.dumps({"elements": els}))
    hb = lc.uncovered_holes(str(tmp_path))
    assert [r for r, _o, _t in hb] == ["7"], \
        f"expected only hole 7 flagged, got {hb} -- hole 8 is entirely inside the data"
    assert hb[0][1] == 1 and hb[0][2] == 2, f"hole 7 has 1 of 2 nodes outside, got {hb[0]}"

    # and it must REPORT, not raise: a green over water legitimately has no returns
    status, out, holes_out = lc.report(str(tmp_path))
    assert status == "checked" and out == bad and holes_out == hb

    # "nothing flagged" must never be reported as "verified covered" when NOTHING WAS CHECKED. With
    # zero tiles on disk this printed "all 1 green(s) sit inside the downloaded tiles' data" and
    # exited 0 -- asserting a coverage it had not looked at. Poppy Ridge reaches that path today (no
    # LAZ at all), as would any course built purely on the 1 m seamless DEM.
    empty = tmp_path / "empty"
    (empty / "laz").mkdir(parents=True)
    (empty / "osm_geom.json").write_text(json.dumps({"elements": [
        {"type": "way", "id": 1, "tags": {"golf": "green"}, "geometry": ring()}]}))
    st, bad0, _ = lc.report(str(empty))
    assert bad0 == [], bad0
    assert st != "checked", \
        f"status {st!r}: with no tiles on disk the check must say so, not imply coverage"
    assert "tile" in st.lower(), st

    # ...and the same when the greens cannot be placed
    nogeom = tmp_path / "nogeom"
    (nogeom / "laz").mkdir(parents=True)
    write_tile(nogeom / "laz" / "a.laz", ring(), 5.0)
    st2, _, _ = lc.report(str(nogeom))
    assert st2 != "checked" and "green" in st2.lower(), st2

    # both fetchers must run the check, or a missing tile copy goes unnoticed again
    for mod in ("fetch_lidar.py", "fetch_lidar_alameda.py"):
        src = open(os.path.join(ROOT, mod), encoding="utf-8").read()
        assert "lidar_coverage.report" in src, f"{mod} never verifies its tiles against the greens"
        # ...and both must sweep stale .part files. A transfer killed outright leaves one that no
        # exception handler runs to remove; observed for real when a Merion fetch was killed mid-tile
        # and left a 26 MB .part sitting in laz/. It is never valid data -- a .part is only renamed
        # into place after its size is checked against TNM.
        assert '*.part' in src and "os.remove(stale)" in src, \
            f"{mod} must remove stale partial downloads before deciding what is cached"


def test_flight_date_is_dated_from_the_points_under_the_greens(tmp_path):
    """The printed flight range was the union over WHOLE LAZ tiles, and the tile set is chosen by
    bbox overlap with the entire course -- so it routinely includes neighbours that cover no green.

    Measured at The Reserve: t390135.laz spans 2017-12-16..2018-01-21 and holds NO point within 60 m
    of any green (its nearest green is 1336 m from its earliest point and 1382 m from its latest),
    while the three tiles that do feed greens span only 2017-12-16..2017-12-17. The book printed
    "flown 2017-12-15 to 2018-01-21" -- 38 days -- for greens flown on two. That line is the one
    claim the whole honesty argument rests on, so it has to describe the returns the surfaces were
    actually built from.

    Uses real synthetic LAZ tiles so the gps_time decode is exercised, not mocked."""
    pytest.importorskip("laspy")
    pytest.importorskip("pyproj")
    import datetime as dt

    os.environ["COURSE"] = a_course()
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    for m in ("config", "lidar_dates"):
        sys.modules.pop(m, None)
    try:
        import lidar_dates as ld
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    lon, lat = -121.35, 38.05
    d = 0.0002
    ring = [(lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d)]
    near = dt.datetime(2017, 12, 16, 20, 0, tzinfo=dt.timezone.utc)
    far = dt.datetime(2018, 1, 21, 20, 0, tzinfo=dt.timezone.utc)

    # metric CRS: half the points sit on the green, half 2 km away on a much later day
    f = _synthetic_laz(tmp_path / "mixed.laz", 26910, ring, near, far)

    whole = ld.tile_dates(f)
    assert whole is not None
    assert whole[0].date() == near.date() and whole[1].date() == far.date(), \
        "without green geometry the whole-tile range should still span both days"
    assert whole[2] is False, "no rings supplied -> nothing is known to be over a green"

    over = ld.tile_dates(f, [ring])
    assert over is not None
    first, last, is_near, npts = over
    assert is_near is True and npts == 100, (is_near, npts)
    assert first.date() == near.date() and last.date() == near.date(), \
        (f"dated {first.date()}..{last.date()}; the 2018-01-21 points are 2 km from the green and "
         f"must not widen the range -- this is The Reserve's 38-day label")

    # a tile that covers NO green must report near=False so the caller can exclude it entirely
    far_ring = [(lon + 0.5 + a, lat + 0.5 + b) for a, b in
                ((-d, -d), (d, -d), (d, d), (-d, d))]
    none_over = ld.tile_dates(f, [far_ring])
    assert none_over[2] is False, "a tile with no points over a green must say so"

    # The pad must be converted into the CRS's own units. Callippe's tiles are in US survey feet, so
    # treating 30 as feet shrinks the collar to 9.1 m and drops points genuinely on the green's
    # collar. Use a TINY ring so the pad -- not the green's own extent -- decides: a point 20 m out
    # is inside a 30 m collar and outside a 9.1 m one.
    tiny = 0.00002
    small_ring = [(lon - tiny, lat - tiny), (lon + tiny, lat - tiny),
                  (lon + tiny, lat + tiny), (lon - tiny, lat + tiny)]
    ft = _synthetic_laz(tmp_path / "ftus.laz", 2227, small_ring, near, far, near_offset_m=20.0)
    r = ld.tile_dates(ft, [small_ring])
    assert r[2] is True and r[3] == 100, \
        (f"found {r[3]} points 20 m from the green in a ftUS tile; the {ld.GREEN_PAD_M:g} m pad was "
         f"probably not converted from metres")
    assert r[0].date() == near.date() and r[1].date() == near.date()

    # and a non-feeding tile must be dropped from the range, not folded into it
    src = open(os.path.join(ROOT, "tools", "lidar_dates.py"), encoding="utf-8").read()
    i = src.index("if rings and not near:")
    block = src[i:src.index("nfeed += 1", i)]      # scoped structurally, not by a character budget
    assert "continue" in block and "NOT counted" in block, \
        "a tile with no points over a green must be excluded from the printed flight range"


def test_project_choice_is_judged_on_the_greens_not_the_bounding_box(tmp_path):
    """Ranking surveys by how much of the rectangular bbox they cover punished exactly the surveys
    we want. Monarch Bay is on San Francisco Bay, so about a quarter of its bbox is open water that
    no land survey covers: CA_AlamedaCounty_2021_B21 scored 74.9% and was excluded by the 95% gate,
    while ARRA_CA_SANFRANCOAST_2010 scored 100% and won. A rebuild would have fetched 2010 elevation
    for a course whose book is built on the 2021 survey (flown 2019-08-14).

    Coverage is now measured over the GREENS -- the thing the LiDAR exists to build -- and the gate
    is a substantial majority rather than near-completeness, because the two failure modes are not
    symmetric: a green the survey misses falls back to the 1 m seamless DEM and its card says
    "1 m data", whereas a decade-old survey silently prints stale slope as current.

    Built from synthetic geometry so it does not need the network."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    try:
        import fetch_lidar as fl
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    assert fl.GREEN_COVERAGE_GOOD <= 0.9, \
        (f"the gate is {fl.GREEN_COVERAGE_GOOD}; Monarch Bay's 2021 survey reaches 18 of 20 greens "
         f"(0.90), so a gate above that re-excludes it")

    S, W, N, E = fl.S, fl.W, fl.N, fl.E
    mx, my = (W + E) / 2, (S + N) / 2
    # ten greens in the WEST half of the bbox; the east half stands in for open water
    cents = [(W + (mx - W) * (i + 0.5) / 10, my) for i in range(10)]

    def tile(x0, x1, y0, y1):
        return {"downloadURL": "https://x/Projects/P/LAZ/t.laz",
                "boundingBox": {"minX": x0, "maxX": x1, "minY": y0, "maxY": y1}}

    # recent survey: land only -- all 10 greens, but only half the bbox
    recent = [tile(W, mx, S, N)]
    # old survey: the whole bbox, water included
    old = [tile(W, E, S, N)]

    assert fl._green_coverage(recent, cents) == 1.0
    assert fl._green_coverage(old, cents) == 1.0
    assert fl._coverage(recent) < 0.6, "the land-only survey should score poorly on the bbox"
    assert fl._coverage(old) > 0.95

    # choose_project reads the bound course's real greens; substitute the synthetic ones. If it
    # stopped consulting them at all it would fall back to bbox coverage and the assertions below
    # would fail, which is the point.
    real_cents = fl._green_centroids
    fl._green_centroids = lambda: cents
    try:
        picked, scored, _ = fl.choose_project({"CA_New_2021_B21": recent,
                                               "ARRA_CA_OLD_2010": old})
        assert picked == "CA_New_2021_B21", \
            (f"picked {picked}: the newer survey covers every green and lost on bbox coverage "
             f"alone -- this is the Monarch Bay regression")

        # a recent survey that misses MOST greens must still lose to the old one that covers them
        clip = [tile(W, W + (mx - W) * 0.2, S, N)]
        assert fl._green_coverage(clip, cents) < fl.GREEN_COVERAGE_GOOD
        picked2, _, _ = fl.choose_project({"CA_New_2021_B21": clip, "ARRA_CA_OLD_2010": old})
        assert picked2 == "ARRA_CA_OLD_2010", \
            f"picked {picked2}: a survey reaching only 20% of the greens must not win on recency"

        # an undated project must not be treated as ancient, and must not crash the ranking
        picked3, _, _ = fl.choose_project({"CA_Unnamed_Survey": old, "CA_New_2021_B21": recent})
        assert picked3 == "CA_New_2021_B21", picked3

        # SAME survey year, both above the floor: the tie-break must use the metric we ranked by.
        # It used bbox coverage, so a survey feeding every green (greens 1.00, bbox 0.62) lost to one
        # missing a green but filling the rectangle (greens 0.90, bbox 0.95) -- the same
        # bbox-over-greens mistake the ranking was changed to stop making.
        wide = [tile(W + (E - W) * 0.06, E, S, N)]
        narrow = [tile(W, W + (E - W) * 0.62, S, N)]
        spread = [(W + (E - W) * 0.6 * (i + 0.5) / 10, my) for i in range(10)]
        fl._green_centroids = lambda: spread
        gn, gw = fl._green_coverage(narrow, spread), fl._green_coverage(wide, spread)
        bn, bw = fl._coverage(narrow), fl._coverage(wide)
        assert gn > gw and bn < bw, (gn, gw, bn, bw)   # the conflict this test needs
        assert gw >= fl.GREEN_COVERAGE_GOOD, "both must clear the floor or the tie-break never runs"
        picked4, _, _ = fl.choose_project({"CA_Narrow_2021_B21": narrow, "CA_Wide_2021_B21": wide})
        assert picked4 == "CA_Narrow_2021_B21", \
            f"picked {picked4}: same year, so the tie-break must prefer the survey feeding more greens"
    finally:
        fl._green_centroids = real_cents


def test_sub_project_copies_of_one_tile_get_distinct_files(tmp_path):
    """One geographic cell can appear in several sub-projects of the same USGS project, flown
    separately, each holding only the points in its own footprint. The download urls differ only in
    the sub-project directory, so naming the local file by url basename gave both copies the SAME
    name: the first downloaded, the second reported "cached" and thrown away.

    Measured live at Callippe: 8 of 20 cells have two copies, and the two copies of w6168n2055 have
    different bounding boxes (CA_AlamedaCo_3_2021 reaches west to -121.85963, CA_AlamedaCo_1_2021
    east to -121.84912), so they are complementary strips -- 190,503,168 bytes of ground returns
    dropped on the floor for that one cell.

    Also asserts the cache is matched by SIZE, not by name: existing courses were fetched under an
    older naming scheme, and re-downloading a copy that is already on disk under another name stores
    it twice, which inflates the pts/m2 the legal provenance table publishes."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar"):
        sys.modules.pop(m, None)
    try:
        import fetch_lidar as fl
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    base = "USGS_LPC_CA_X_2021_B21_w6168n2055.laz"
    root = "https://x/Projects/CA_X_2021_B21"
    tiles = [{"downloadURL": f"{root}/CA_XCo_3_2021/LAZ/{base}", "sizeInBytes": 190503168},
             {"downloadURL": f"{root}/CA_XCo_1_2021/LAZ/{base}", "sizeInBytes": 91675672},
             {"downloadURL": f"{root}/CA_XCo_1_2021/LAZ/USGS_LPC_CA_X_2021_B21_w6162n2052.laz",
              "sizeInBytes": 317568432}]
    laz = tmp_path / "laz"
    laz.mkdir()

    todo, cached = fl.plan_downloads(tiles, str(laz))
    assert cached == 0
    names = [n for _, n in todo]
    assert len(names) == 3, f"every copy must be planned, got {names}"
    assert len(set(names)) == 3, f"two copies of one cell collided on one filename: {names}"
    # the two copies of the same cell must map to different files, and both must still be findable
    same = sorted(n for _, n in todo if "w6168n2055" in n)
    assert len(same) == 2 and same[0] != same[1], same
    assert all(n.lower().endswith(".laz") for n in names), names

    # size-based cache matching: write the two cell copies under the OTHER one's name
    for _, n in todo:
        want = next(t["sizeInBytes"] for t, nn in todo if nn == n)
        (laz / n).write_bytes(b"\0" * want)
    todo2, cached2 = fl.plan_downloads(tiles, str(laz))
    assert cached2 == 3 and not todo2, f"already-present copies re-scheduled: {todo2}"

    # a file of the wrong size must NOT satisfy the cache -- that is a truncated download
    (laz / same[0]).write_bytes(b"\0" * 12345)
    todo3, _ = fl.plan_downloads(tiles, str(laz))
    assert len(todo3) == 1, f"a truncated tile must be re-fetched, got {todo3}"

    # a duplicate URL in the TNM listing is ONE file, not two copies of a cell. Grouping by basename
    # gave the second entry a __CoN name and downloaded the identical tile twice, doubling its points
    # -- which inflates the pts/m2 the legal provenance table publishes. Live TNM returns no
    # duplicates today (10/40/9 urls, 0 repeats across three courses), so this is a latent guard
    # against an API that has already surprised us with a 200-item cap and fiscal-year codes.
    dupe = tmp_path / "dupe"
    dupe.mkdir()
    one = {"downloadURL": f"{root}/CA_XCo_1_2021/LAZ/{base}", "sizeInBytes": 91675672}
    todo_d, cached_d = fl.plan_downloads([one, dict(one)], str(dupe))
    assert len(todo_d) == 1, f"the same url twice must yield one download, got {[n for _, n in todo_d]}"
    assert cached_d == 0

    # nor may a file of the RIGHT size but a different cell. Sizes within one course's laz/ are all
    # distinct in practice (the only duplicates on disk are the same tile shared by two neighbouring
    # courses), but accepting a cross-cell match would silently drop a tile we need.
    other = tmp_path / "other"
    other.mkdir()
    (other / "USGS_LPC_CA_X_2021_B21_w9999n9999.laz").write_bytes(b"\0" * 317568432)
    todo4, cached4 = fl.plan_downloads([tiles[2]], str(other))
    assert cached4 == 0 and len(todo4) == 1, \
        f"a same-size file for a DIFFERENT cell must not count as cached: {todo4}, {cached4}"

    # and the suffix must remain strippable by the provenance generator
    suffixed = [n for n in names if "__Co" in n]
    assert suffixed, names
    for n in suffixed:
        assert re.search(r"__Co\d+\.laz$", n), \
            f"{n} does not match tools/gen_provenance.py's __Co<digits> strip"

    # The Alameda fetcher writes the same kind of name and must obey the same rule. It used to use
    # the sub-project's last 9 characters (`__Co_3_2021`), which the strip below does not match, so
    # gen_provenance.py published "CA_AlamedaCounty_2021_B21_w6162n2049__Co_3" as a book's LiDAR
    # project in the legal record.
    def strip_like_gen_provenance(name):
        stem = re.sub(r"\.laz$", "", name)[len("USGS_LPC_"):]
        for pat in (r"__Co\d+$", r"_w\d+n\d+$", r"_\d{2}[A-Z]{3}\d+$", r"_\d+$"):
            stem = re.sub(pat, "", stem)
        return stem

    assert strip_like_gen_provenance(
        "USGS_LPC_CA_AlamedaCounty_2021_B21_w6162n2049__Co3.laz") == "CA_AlamedaCounty_2021_B21"
    assert strip_like_gen_provenance(
        "USGS_LPC_CA_AlamedaCounty_2021_B21_w6162n2049__Co_3_2021.laz") != "CA_AlamedaCounty_2021_B21", \
        "this is the naming that broke the legal record; the assertion below guards against it"
    ala = open(os.path.join(ROOT, "fetch_lidar_alameda.py"), encoding="utf-8").read()
    # scope to the FILENAME construction: sub[-9:] is fine in a progress label, not in a filename
    fnlines = [ln.strip() for ln in ala.splitlines()
               if re.match(r"fn\s*=", ln.strip()) and "laz" in ln]
    assert fnlines, "could not find the tile filename construction in fetch_lidar_alameda.py"
    joined = " ".join(fnlines)
    assert "__Co{tok}" in joined, f"expected a __Co<digits> suffix, got: {joined}"
    assert "sub[-9:]" not in joined, \
        f"the sub-project slice in a FILENAME is what broke the provenance strip: {joined}"


def test_a_network_failure_is_not_mistaken_for_a_missing_lidar_tile():
    """head_size() swallowed every exception and returned -1, so a transient timeout looked exactly
    like an authoritative "this tile is not in this sub-project". The caller printed "edge of
    coverage, skip" and main() then exited 0 having downloaded half a course -- and a green with no
    ground returns under it is precisely what the honesty gate now has to catch. A gap invented by a
    network wobble is indistinguishable, after the fact, from the edge of a survey.

    Now: an authoritative 403/404/410 means ABSENT, anything else means UNKNOWN, and UNKNOWN stops
    the run instead of silently shrinking the coverage."""
    import urllib.error
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar_alameda"):
        sys.modules.pop(m, None)
    try:
        import fetch_lidar_alameda as fla
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    assert fla.ABSENT != fla.UNKNOWN, "the two outcomes must be distinguishable"

    real = fla.urllib.request.urlopen
    try:
        # an authoritative 404 -> ABSENT, and no retrying
        calls = {"n": 0}

        def four_oh_four(*a, **k):
            calls["n"] += 1
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        fla.urllib.request.urlopen = four_oh_four
        assert fla.head_size("https://x/t.laz") == fla.ABSENT
        assert calls["n"] == 1, "a 404 is authoritative; it must not be retried"

        # a timeout -> UNKNOWN, after retrying
        calls["n"] = 0

        def timeout(*a, **k):
            calls["n"] += 1
            raise TimeoutError("timed out")
        fla.urllib.request.urlopen = timeout
        assert fla.head_size("https://x/t.laz", tries=2) == fla.UNKNOWN
        assert calls["n"] == 2, "a network error must be retried before giving up"

        # a 5xx is also UNKNOWN, not absent
        fla.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None))
        assert fla.head_size("https://x/t.laz", tries=1) == fla.UNKNOWN
    finally:
        fla.urllib.request.urlopen = real

    # and an UNKNOWN must abort the run rather than shrink the tile set
    src = open(os.path.join(ROOT, "fetch_lidar_alameda.py"), encoding="utf-8").read()
    i = src.index("if unknown:")
    assert "raise SystemExit" in src[i:i + 400], \
        "an undetermined tile must stop the fetch, not be treated as the edge of the survey"


def test_on_playing_surface_classifies_buildings_and_greens(tmp_path):
    """Unit test for the classifier the corpus scan can only observe second-hand. Two live
    subtleties: `building=no` means NOT a building (it must not become a surface at all), and a
    building hit must report 'building', not 'golf' -- conflating them overstated the golf-surface
    drop count 16x on valley-hi.

    Drives load_playing_surfaces() against real osm_*.json files. The first version of this test
    built the surface tuples itself, which duplicated the very kind/`building=no` logic it claimed
    to check: mutating the engine to report a building as 'golf', to treat `building=no` as a
    building, or to drop the footprint clause entirely all left the suite green."""
    slug = "_synth_trees"
    cdir = os.path.join(ROOT, "courses", slug)
    os.makedirs(cdir, exist_ok=True)
    lat0, lon0 = 40.0, -75.0
    box = lambda dx, dy, r=0.0005: [
        dict(lat=lat0 + dy + sy * r, lon=lon0 + dx + sx * r)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))]
    els = [
        dict(type="way", id=1, tags={"building": "yes"},       geometry=box(0.000, 0.0)),
        dict(type="way", id=2, tags={"golf": "green"},         geometry=box(0.004, 0.0)),
        dict(type="way", id=3, tags={"building": "no"},        geometry=box(0.008, 0.0)),
        dict(type="way", id=4, tags={"leisure": "pitch"},      geometry=box(0.012, 0.0)),
    ]
    try:
        json.dump(dict(elements=els), open(os.path.join(cdir, "osm_course.json"), "w"))
        json.dump(dict(elements=[]), open(os.path.join(cdir, "osm_geom.json"), "w"))
        json.dump(dict(slug=slug, name="SynthTrees", address="",
                       location={"lat": lat0, "lon": lon0}, par=72, green_speed="",
                       tees=[dict(name="Card", yards=100, rating=70.0, slope=113)],
                       featured_tee="Card", hole_cols=["par", "mens_hcp", "Card"],
                       holes={"1": [72, 1, 100]},
                       osm_bbox=[lat0 - 0.01, lon0 - 0.01, lat0 + 0.01, lon0 + 0.01], sources={}),
                  open(os.path.join(cdir, "course.json"), "w"))
        prev = os.environ.get("COURSE")
        os.environ["COURSE"] = slug          # bind explicitly; do not inherit another test's course
        for m in ("config", "fetch_trees"):
            sys.modules.pop(m, None)
        import fetch_trees

        surfaces = fetch_trees.load_playing_surfaces()
        kinds = sorted(k for *_rest, k in surfaces)
        assert kinds == ["building", "golf"], f"expected one building + one green, got {kinds}"

        at = lambda dx: fetch_trees.on_playing_surface(lon0 + dx, lat0, surfaces)
        assert at(0.000) == "building", "a roof must report 'building', not 'golf'"
        assert at(0.004) == "golf", "a green must report 'golf'"
        assert at(0.008) is False, "building=no means NOT a building -- not a surface at all"
        assert at(0.012) is False, "a non-golf, non-building polygon is not a playing surface"
        assert at(0.050) is False, "outside every polygon"
    finally:
        for f in ("osm_course.json", "osm_geom.json", "course.json"):
            fp = os.path.join(cdir, f)
            if os.path.exists(fp):
                os.remove(fp)
        if os.path.isdir(cdir):
            os.rmdir(cdir)
        _restore_course(prev)


@needs_corpus
def test_no_tree_marker_sits_on_a_building():
    """Phase 1's goal: 1107 markers project-wide (53 on Merion's clubhouse roof) were drawn as
    trees. Class-6 filtering alone is not enough -- most tiles are unclassified, so a roof arrives
    as class 1 and only the OSM footprint identifies it.

    NOTE this is an ARTIFACT gate: it reads the trees_lidar.json already on disk, so it proves the
    shipped books are clean but CANNOT fail if the filtering code regresses (the file is only
    rewritten by a LAZ re-run). test_on_playing_surface_classifies_buildings_and_greens covers the
    code path itself."""
    def pip(x, y, poly):
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
                inside = not inside
            j = i
        return inside

    total_on_building = 0
    checked = 0
    for slug in CORPUS:
        tp = os.path.join(ROOT, "courses", slug, "trees_lidar.json")
        cp = os.path.join(ROOT, "courses", slug, "osm_course.json")
        if not (os.path.exists(tp) and os.path.exists(cp)):
            continue
        trees = json.load(open(tp))
        blds = []
        for e in json.load(open(cp))["elements"]:
            if (e.get("tags") or {}).get("building") not in (None, "no") and e.get("geometry"):
                poly = [(p["lon"], p["lat"]) for p in e["geometry"]]
                xs = [c[0] for c in poly]
                ys = [c[1] for c in poly]
                blds.append((min(xs), min(ys), max(xs), max(ys), poly))
        for pts in trees.values():
            for la, lo in pts:
                checked += 1
                for x0, y0, x1, y1, poly in blds:
                    if x0 <= lo <= x1 and y0 <= la <= y1 and pip(lo, la, poly):
                        total_on_building += 1
                        break
    if not checked:
        pytest.skip("no tree data built")
    assert total_on_building == 0, f"{total_on_building} of {checked} tree markers sit on a building"


@pytest.mark.slow
@pytest.mark.slow          # rebuilds one book from source, then measures it in a browser
@needs_corpus
def test_rule_4_3_holds_for_a_book_BUILT_FROM_THE_CURRENT_CODE():
    """The sibling test below measures greenbook.html ALREADY ON DISK, so it cannot fail for a code
    regression -- changing render_green's legal ceiling from 0.36 to 0.45 left the whole suite green
    while the next real build went to 1:435, over the Rule 4.3 limit. Since the scale computation is
    this project's worst historical defect, close the loop: generate a book from the current source,
    then measure THAT."""
    import subprocess
    slug = a_course()
    html = os.path.join(ROOT, "courses", slug, "greenbook.html")
    keep = open(html, "rb").read() if os.path.exists(html) else None
    keep_times = (os.path.getatime(html), os.path.getmtime(html)) if keep is not None else None
    try:
        # COACH must be cleared: with it set, generate.py writes greenbook_coach.html and this test
        # then measures the STALE greenbook.html, passing over a real cap violation. Demonstrated by
        # raising render_green's legal ceiling to 0.45 -- plain run fails, COACH=1 run passes. The
        # documented workflow uses that env var, so the guard on this project's worst historical
        # defect was one exported variable away from useless.
        env = {k: v for k, v in os.environ.items() if k != "COACH"}
        env["COURSE"] = slug
        b = subprocess.run([sys.executable, "generate.py"], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        assert b.returncode == 0, f"build failed:\n{b.stdout[-1500:]}{b.stderr[-1500:]}"
        r = subprocess.run([sys.executable, "tools/check_scale.py", slug], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode == 2 and "SKIP:" in r.stdout:
            pytest.skip("no browser installed; the rendered-layout measurement cannot run here")
        assert r.returncode == 0, f"a freshly built book breaks Rule 4.3:\n{r.stdout[-2000:]}"
        assert "PASS" in r.stdout, r.stdout[-2000:]
        n = int(re.search(r"(\d+) greens measured", r.stdout).group(1))
        assert n >= 9, f"only {n} greens measured in the fresh build"
    finally:
        if keep is not None:                     # leave the committed book exactly as it was
            open(html, "wb").write(keep)
            # ...including its mtime. Restoring only the CONTENT made the HTML newer than its PDF,
            # which then tripped the PDF-staleness gate -- one of my tests failing another.
            os.utime(html, keep_times)


@pytest.mark.slow          # ~11 s: launches a browser to lay out every book
@needs_corpus
def test_every_green_conforms_to_rule_4_3_scale_cap():
    """The critical defect: render_green computed a legal size but emitted it as an SVG width=
    presentation attribute, which has zero CSS specificity, so the book stylesheet overrode it and
    15 of 198 greens printed over the 3/8 in : 5 yd cap (worst 1:392, 22% over) while three
    documents asserted the cap held."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_scale.py")],
                       cwd=ROOT, capture_output=True, text=True)
    if "no built books found" in r.stdout:
        pytest.skip("no built books to measure")
    if r.returncode == 2 and "SKIP:" in r.stdout:
        pytest.skip("no browser installed; the rendered-layout measurement cannot run here")
    # The gate's own limit must equal the one stated HERE. Without this the tests only checked
    # rc == 0 and "PASS", so doubling LIMIT_IN_PER_5YD in the tool to 0.750 left the whole suite
    # green -- the guard on this project's worst historical defect, disabled by editing one number.
    # tests/…:39 already declared the cap and it was dead code: one declaration, zero uses.
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import check_scale
    assert abs(check_scale.LIMIT_IN_PER_5YD - LIMIT_IN_PER_5YD) < 1e-9, (
        f"the gate enforces {check_scale.LIMIT_IN_PER_5YD} in per 5 yd but USGA Clarification "
        f"4.3a/1 caps it at {LIMIT_IN_PER_5YD} (3/8 in : 5 yd = 1:480)")
    # and the worst value it MEASURED must be inside that cap, read out of its own output
    worst = max(float(v) for v in re.findall(r"([0-9.]+) in/5yd", r.stdout)) if \
        re.search(r"in/5yd", r.stdout) else 0.0
    assert 0 < worst <= LIMIT_IN_PER_5YD, (
        f"worst measured green is {worst} in per 5 yd against a {LIMIT_IN_PER_5YD} cap")
    assert r.returncode == 0, f"Rule 4.3 scale gate failed:\n{r.stdout[-2000:]}"
    # "0 greens measured ... PASS" was reachable, so require evidence of the measurement too
    assert "PASS" in r.stdout, r.stdout[-2000:]
    n = int(re.search(r"(\d+) greens measured", r.stdout).group(1))
    # Derived, not hardcoded: ">= 190" was the fifth instance in this file of a floor pinned to
    # this machine's 12-course corpus, each of which made the suite fail for a user with less data.
    want = 0
    for hj in glob.glob(os.path.join(ROOT, "courses", "*", "dem_hd", "hole*.json")):
        cdir = os.path.dirname(os.path.dirname(hj))
        if not os.path.basename(cdir).startswith("_") and \
                os.path.exists(os.path.join(cdir, "greenbook.html")):
            want += 1
    assert n == want, f"measured {n} greens but {want} surfaces belong to a built book"


# ---------------------------------------------------------------------------
# Course-data integrity -- catches transcription errors before they reach a card
# ---------------------------------------------------------------------------
def _check_course(j, label):
    """The five checks a course.json must satisfy. Every one of these has been violated in
    practice: par that did not sum, a handicap column that was not a permutation, and a tee whose
    rating ROSE as its yardage fell (Micke Grove's Red row was a women's rating, which would
    inflate a boy's handicap differential by ~5 strokes)."""
    holes = j["holes"]
    nums = sorted(int(k) for k in holes)
    cols = j["hole_cols"][2:]
    errs = []
    # No default: `j.get("par", 72)` invented a 72 target for a file that omits par, which is
    # simply wrong for a 9-hole book (par 35) and would report a phantom mismatch.
    if "par" not in j:
        errs.append(f"{label}: no 'par' key -- the per-hole sum has nothing to check against")
    elif sum(holes[str(h)][0] for h in nums) != j["par"]:
        errs.append(f"{label}: per-hole pars sum to "
                    f"{sum(holes[str(h)][0] for h in nums)}, not par={j['par']}")
    if sorted(holes[str(h)][1] for h in nums) != list(range(1, len(nums) + 1)):
        errs.append(f"{label}: mens_hcp is not a permutation of 1..{len(nums)}")
    for h in nums:
        if len(holes[str(h)]) != len(j["hole_cols"]):
            errs.append(f"{label}: hole {h} has {len(holes[str(h)])} values, hole_cols has {len(j['hole_cols'])}")
    by_name = {t["name"]: t for t in j.get("tees", [])}
    for i, name in enumerate(cols):
        if name not in by_name:
            errs.append(f"{label}: hole_cols names tee {name!r} which is absent from 'tees'")
            continue
        tot = sum(holes[str(h)][2 + i] for h in nums)
        if by_name[name].get("yards") is not None and tot != by_name[name]["yards"]:
            errs.append(f"{label}: {name} rows sum to {tot} but 'tees' says {by_name[name]['yards']}")
    rated = [(t["yards"], t["rating"], t["name"]) for t in j.get("tees", [])
             if t.get("rating") is not None and t.get("yards") is not None]
    rated.sort(reverse=True)
    # A forward tee may legitimately carry a women's course rating, which is higher than the men's
    # rating of a longer tee. That is real data, not a transcription error, so it needs an explicit
    # opt-out per tee ("rating_is_womens": true) rather than a silent pass.
    womens = {t["name"] for t in j.get("tees", []) if t.get("rating_is_womens")}
    for a, b in zip(rated, rated[1:]):
        if b[1] > a[1] and b[2] not in womens and a[2] not in womens:
            errs.append(f"{label}: {b[2]} ({b[0]}yd) rates {b[1]} above {a[2]} ({a[0]}yd) at {a[1]} "
                        f"-- a women's rating in a men's column? If it IS one, set "
                        f"\"rating_is_womens\": true on that tee.")
    return errs


def test_example_template_is_self_consistent():
    """The template a stranger copies must itself pass every check a real course must -- it was
    shipped once with per-hole rows summing to 7020 against a declared 6800."""
    p = os.path.join(ROOT, "examples", "course.json")
    if not os.path.exists(p):
        pytest.skip("no examples/course.json")
    errs = _check_course(json.load(open(p)), "examples/course.json")
    assert not errs, "template is inconsistent: " + "; ".join(errs)


@needs_corpus
def test_every_built_course_is_self_consistent():
    """Same checks against every course actually built here."""
    errs = []
    for slug in CORPUS:
        errs += _check_course(json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))), slug)
    assert not errs, "course data inconsistencies: " + "; ".join(errs)


@needs_corpus
def test_disclaimer_record_matches_what_the_books_print():
    """legal/05 calls itself "verbatim" and its entire value is being the exact printed words. It had
    drifted: it described SIX distributed green books when there are twelve, both quoted versions
    ended "(c) 2026 Lucas." while every real book prints the trademark and the CC BY-NC-ND line, its
    own intro promised a coach-edition variant it never contained, and it predated the NAIP credit.
    It is now generated from the built books, so this test is what keeps it honest."""
    import subprocess
    rows = [l for l in open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
            .splitlines() if l.startswith("| ") and not l.startswith("| Course |")
            and not l.startswith("|--")]
    built = len([d for d in glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))
                 if not os.path.basename(os.path.dirname(d)).startswith("_")])
    if len(rows) > built:
        pytest.skip(f"legal/03 documents {len(rows)} courses but {built} are built here; "
                    "the generated legal docs describe the full corpus, so a mismatch on a partial "
                    "one is expected rather than a defect")
    if not glob.glob(os.path.join(ROOT, "courses", "*", "greenbook_coach.html")):
        pytest.skip("no coach edition built locally (COACH=1); the record cannot be regenerated")
    r = subprocess.run([sys.executable, "tools/gen_disclaimers.py", "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@needs_corpus
def test_provenance_doc_matches_the_build_artifacts():
    """legal/03 documented 8 of 12 books, named the wrong dataset for one, and carried project-name
    'years' wrong by 2-12 years. It is now generated from the artifacts; this fails if it drifts.

    Corpus-gated: without course data the regenerated table is empty, so this used to report the
    committed 12-row table as STALE and fail the suite on a fresh clone -- for someone who had done
    nothing wrong. The generator now exits 2 for "nothing to check" as well."""
    import subprocess
    rows = [l for l in open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
            .splitlines() if l.startswith("| ") and not l.startswith("| Course |")
            and not l.startswith("|--")]
    built = len([d for d in glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))
                 if not os.path.basename(os.path.dirname(d)).startswith("_")])
    if len(rows) > built:
        pytest.skip(f"legal/03 documents {len(rows)} courses but {built} are built here; "
                    "the generated legal docs describe the full corpus, so a mismatch on a partial "
                    "one is expected rather than a defect")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_provenance.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 2:
        pytest.skip(r.stdout.strip())
    assert r.returncode == 0, r.stdout + r.stderr


@needs_corpus
def test_every_built_course_appears_in_the_provenance_doc():
    """A book must never ship undocumented: PIPELINE step 7 requires a legal/03 row per course."""
    p = os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")
    if not os.path.exists(p):
        pytest.skip("no provenance doc")
    # anchor to the start of a table ROW: the club name also appears inside the scorecard column,
    # so a bare substring search would pass even with the row deleted.
    rows = [l.split("|")[1].strip() for l in open(p, encoding="utf-8").read().splitlines()
            if l.startswith("| ") and not l.startswith("|---")]
    missing = []
    for slug in CORPUS:
        name = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("name", slug)
        if not any(r == name for r in rows):
            missing.append(name)
    assert not missing, f"courses built but absent as a legal/03 row: {missing}"


def test_vertical_unit_comes_from_the_crs_not_its_name():
    """Latent, high blast radius: the Z unit was inferred by substring-matching the CRS NAME for
    'foot'/'ftus'. That works on full WKT (all current tiles) but silently fails for a bare EPSG
    code -- which is exactly what course.json's lidar_crs override supplies. EPSG:2227 and 6420 are
    US survey foot, so Z stayed unscaled and every slope would print 3.28x too steep."""
    import geo
    feet = 0.30480060960121924           # pyproj's ftUS factor: ONE ULP above the literal 1200/3937
    assert feet != 1200 / 3937, "the two differ by 1 ULP -- see the note below"
    for code in ("EPSG:2227", "EPSG:6420", "EPSG:2926"):
        got = geo.vertical_scale(code)
        assert abs(got - feet) < 1e-9, f"{code} must resolve to US survey feet"
        assert "foot" not in str(code).lower(), "the old name-matching heuristic would have missed this"
    # Because pyproj's factor is 1 ULP off the old hard-coded 1200/3937, a ftUS course's dem_hd
    # .npy is NOT byte-identical across the change: every sample moves, by at most 2.8e-14 m. An
    # earlier commit message claimed byte-identity, but it was measured on merion -- a METRIC
    # course, where the factor is 1.0 either way, so the check could not have detected a
    # difference. Re-measured on bay-view (ftUS): 0 of 18 printed greens change. The claim should
    # have read "identical to float tolerance", and only for the metric courses byte-exactly.
    for code in ("EPSG:26910", "EPSG:26918", "EPSG:6419"):
        assert abs(geo.vertical_scale(code) - 1.0) < 1e-9, f"{code} is metric"


def test_vertical_unit_refuses_rather_than_assuming_metres():
    """A CRS whose vertical unit is not a LENGTH must stop the build, not silently scale Z.

    EPSG:4326's axis unit is 'degree', whose conversion factor is 0.0174533 (degrees to radians).
    Taken as a vertical scale that shrinks every elevation 57x -- a green that reads nearly flat
    rather than an error. Found while writing this test."""
    import geo
    for bad in ("EPSG:4326", "EPSG:4269", "not-a-crs"):
        with pytest.raises(SystemExit):
            geo.vertical_scale(bad)


@pytest.mark.skipif(not os.environ.get("COLD_BUILD"),
                    reason="set COLD_BUILD=1 to run: needs network and reprocesses ~300 MB of LiDAR")
def test_cold_build_reproduces_an_existing_book_byte_for_byte():
    """End-to-end determinism. Every other test checks one stage; this one runs the whole pipeline
    from nothing but course.json + the cached LAZ tiles (fresh OSM fetch, fresh 0.4 m green
    surfaces, fresh trees, fresh book) and requires the result to match the committed book EXACTLY.

    That is the property that makes the provenance claims checkable: same inputs -> same book. It
    also catches cross-stage breakage that per-stage tests cannot -- a stage-order dependency, or
    OSM having drifted from the cached copy.

    Verified 2026-07-29 on micke-grove-golf-links: 37/837 OSM elements identical, all 18 dem_hd
    surfaces byte-identical, 5657 tree markers, greenbook.html identical at 4,334,614 bytes.

    Run:  COLD_BUILD=1 python3 -m pytest tests/ -q -k cold_build
    """
    import subprocess, shutil, hashlib, json
    ref = "micke-grove-golf-links"
    cold = "_coldtest"
    src, dst = os.path.join(ROOT, "courses", ref), os.path.join(ROOT, "courses", cold)
    if not os.path.exists(os.path.join(src, "greenbook.html")):
        pytest.skip(f"{ref} is not built here")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    try:
        j = json.load(open(os.path.join(src, "course.json")))
        j["slug"] = cold
        json.dump(j, open(os.path.join(dst, "course.json"), "w"), indent=2)
        os.symlink(os.path.join(src, "laz"), os.path.join(dst, "laz"))
        env = {**os.environ, "COURSE": cold}
        for stage in ("fetch_osm.py", "fetch_dem_hd.py", "fetch_trees.py", "generate.py"):
            r = subprocess.run([sys.executable, os.path.join(ROOT, stage)], cwd=ROOT,
                               env=env, capture_output=True, text=True)
            assert r.returncode == 0, f"{stage} failed:\n{r.stdout[-1500:]}{r.stderr[-1500:]}"
        a = open(os.path.join(src, "greenbook.html"), encoding="utf-8").read()
        b = open(os.path.join(dst, "greenbook.html"), encoding="utf-8").read()
        assert a == b, (f"cold build differs from the committed book "
                        f"({len(a)} vs {len(b)} bytes) -- the pipeline is not reproducible")
    finally:
        shutil.rmtree(dst, ignore_errors=True)
