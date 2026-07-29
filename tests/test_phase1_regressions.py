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


EXPECT_MIN_HOLES = 190          # 198 built; a floor that tolerates one course being absent
EXPECT_MIN_LABELS = 700         # ~823 to-green labels across the corpus
EXPECT_MIN_PAIRS = 600          # ~726 rows carrying BOTH gutter numbers at 1x, ~682 at 2x


def _assert_examined(holes, labels, errors, what, min_labels=None):
    """Corpus tests must prove they looked at something.

    Every corpus test used to swallow per-hole render failures with `except Exception: continue`
    and assert nothing about coverage, so making render_hole raise turned the whole file into
    "5 passed in 0.04s" -- a green suite that had examined nothing at all."""
    assert not errors, f"{what}: {len(errors)} hole(s) failed to render: {errors[:5]}"
    assert holes >= EXPECT_MIN_HOLES, f"{what}: only examined {holes} holes (expected >= {EXPECT_MIN_HOLES})"
    floor = EXPECT_MIN_LABELS if min_labels is None else min_labels
    assert labels >= floor, f"{what}: only saw {labels} labels (expected >= {floor})"


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
    slug = CORPUS[0] if CORPUS else None
    if slug is None:
        pytest.skip("needs a course dir for config import")
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
    os.environ["COURSE"] = CORPUS[0] if CORPUS else "x"
    if not CORPUS:
        pytest.skip("needs a course dir for config import")
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


def test_lidar_selection_prefers_coverage_over_recency():
    """Round-1 finding: picking the NEWEST project chose CA_SanJoaquin_2021_A21 (published 2023,
    90% of the bbox) over CA_UpperSouthAmerican_Eldorado_2019_B19 (2021, 100%), leaving the greens
    outside the clip with no ground returns. Replayed offline against recorded TNM shapes."""
    os.environ["COURSE"] = CORPUS[0] if CORPUS else "x"
    if not CORPUS:
        pytest.skip("needs a course dir for config import")
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
    # call the ENGINE's selection, not a copy of it: the first version of this test re-implemented
    # the four lines it was checking and so could not have failed
    chosen, scored, _newest = fetch_lidar.choose_project(projects)
    assert scored["CA_Eldorado_2019_B19"] > scored["CA_SanJoaquin_2021_A21"]
    assert chosen == "CA_Eldorado_2019_B19", "coverage must outrank the newer partial project"

    # and the tie-break still prefers the newer project when coverage is equal
    items[1]["boundingBox"] = full
    projects = {}
    for it in items:
        projects.setdefault(fetch_lidar._project_of(it), []).append(it)
    chosen, _s, _n = fetch_lidar.choose_project(projects)
    assert chosen == "CA_SanJoaquin_2021_A21", "equal coverage must fall through to recency"


def test_digitized_guard_refuses_malformed_cache(tmp_path):
    """Rounds 1-2: 'could not read the previous file' became 'nothing to preserve', which erased
    hand-digitized greens that exist in exactly one untracked file. Valid-JSON-wrong-shape was the
    same hole (a misspelled 'elements' key took bay-view's digitized greens 2 -> 0)."""
    slug = CORPUS[0] if CORPUS else None
    if slug is None:
        pytest.skip("needs a course dir for config import")
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
    _assert_examined(nholes, labels, errors, "from-tee sweep")
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
                     min_labels=EXPECT_MIN_PAIRS)
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
    os.environ["COURSE"] = CORPUS[0] if CORPUS else "x"
    if not CORPUS:
        pytest.skip("needs a course dir for config import")
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
    assert max(labels) <= render_green.SLOPE_LABEL_MAX_PCT, \
        f"printed an unputtable slope: {sorted(labels)}"


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
    slug = CORPUS[0]
    html = os.path.join(ROOT, "courses", slug, "greenbook.html")
    keep = open(html, "rb").read() if os.path.exists(html) else None
    try:
        env = dict(os.environ, COURSE=slug)
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
    assert r.returncode == 0, f"Rule 4.3 scale gate failed:\n{r.stdout[-2000:]}"
    # "0 greens measured ... PASS" was reachable, so require evidence of the measurement too
    assert "PASS" in r.stdout, r.stdout[-2000:]
    n = int(re.search(r"(\d+) greens measured", r.stdout).group(1))
    assert n >= 190, f"only {n} greens measured"


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
    if not glob.glob(os.path.join(ROOT, "courses", "*", "greenbook_coach.html")):
        pytest.skip("no coach edition built locally (COACH=1); the record cannot be regenerated")
    r = subprocess.run([sys.executable, "tools/gen_disclaimers.py", "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_provenance_doc_matches_the_build_artifacts():
    """legal/03 documented 8 of 12 books, named the wrong dataset for one, and carried project-name
    'years' wrong by 2-12 years. It is now generated from the artifacts; this fails if it drifts."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_provenance.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True)
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
