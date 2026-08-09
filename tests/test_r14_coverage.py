#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
lidar_coverage.py's remaining default-to-pass paths: exit 0 while meaning "not verified".

The module's original defect was that it computed a verdict, printed it, and discarded it -- fixed by
report_or_exit() and its two independent acknowledgement keys. What the keyed stop cannot do is notice
a verdict that never became a finding in the first place, and six such paths were left. Every one is
LATENT on today's corpus (the fixtures here are synthetic for that reason), and every one has the same
shape as the original: an unanswerable question answered "fine".

  I-1  one stray XY point balloons a tile's header bbox until it vouches for the whole county, so a
       green 4 km outside the real data reads as covered. The repo has been bitten by this exact
       junk-coordinate class before, in tools/lidar_dates.py (a junk gps_time).
  I-2  an entirely UNREADABLE dem_hd/ printed the same words as a genuinely empty one.
  I-3  a meta with no green_id was dropped from the population, so it appeared in neither the
       numerator nor the denominator of the cross-check.
  I-4  the fallback test was an allowlist of badness: a `source` that was missing, null, or spoke any
       third vocabulary read as "came from the point cloud".
  I-5  zero hole centreline ways was indistinguishable from every hole covered, and the half of the
       check that governs whether trees appear was silent about not having run.
  I-6  a malformed course.json raised JSONDecodeError out of uncovered_holes(), which also leaked the
       file handle it opened.

Everything here is built under tmp_path. courses/ is gitignored, is the only copy of twelve books'
worth of data, and is read only by the corpus-calibration assertions below.
"""
import ast
import contextlib
import glob
import io
import json
import os
import pathlib
import re
import sys
import types
import warnings

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The two source vocabularies the corpus actually records today (measured: 192 metas and 6 of 198).
# Quoted rather than paraphrased, so a fixture cannot outlive the strings the stages write. Both are
# graded against the corpus by test_the_source_fixtures_reproduce_what_the_sidecars_record, because
# "byte-identical to what the stages write" is the whole load-bearing claim of these two literals and
# nothing else was checking it.
#
# SEAMLESS SPELLS OUT the retired figure, and it has to. 9f37857 retired "1 m" as a claim about the
# seamless product -- the arrays measure ~2.7 x 3.4 m source cells -- and
# test_no_runtime_string_or_published_record_names_the_seamless_fallback_as_a_one_metre_product sweeps
# every string literal in the repo's .py files, fixtures included, for exactly that pairing. The 6 metas
# on disk still SAY it, because they were written before the label was corrected and nothing rewrites a
# measured surface's sidecar to fix prose. So this fixture is a RECORD of what the corpus holds, not a
# claim about the product, and that grader exempts it on those terms -- it clears a literal that is
# byte-identical to a `source` value read off courses/*/dem_hd/hole*.json, and nothing else. Hiding the
# digit behind an interpolation was the earlier answer here and it was the wrong one: it left the claim
# exactly as visible to a reader and invisible to the grader.
#
# UNKNOWN_VOCABULARY is the opposite case: it stands for a source string this repo does NOT recognise,
# its exact bytes are irrelevant to every assertion that uses it, and it tripped that grader only
# because the bare word "fallback" sits in the adjacency vocabulary. So it names no product word at all
# -- there is nothing here for the grader to be blind to.
LIDAR = "USGS 3DEP LiDAR ground returns @0.4m"
SEAMLESS = "USGS 3DEP seamless 1 m @0.5m sampling"
UNKNOWN_VOCABULARY = "SRTM void-filled"

LON, LAT = -121.35, 38.05
D = 0.0002


def _corpus():
    """Real (non-scratch) course directories, or [] on a fresh clone where courses/ is absent."""
    return [os.path.dirname(p)
            for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
            if not os.path.basename(os.path.dirname(p)).startswith("_")]


def ring(dlon=0.0, dlat=0.0, scale=1.0):
    """A four-node green ring near (LON, LAT), offset by (dlon, dlat)."""
    r = D * scale
    return [{"lon": LON + dlon - r, "lat": LAT + dlat - r},
            {"lon": LON + dlon + r, "lat": LAT + dlat - r},
            {"lon": LON + dlon + r, "lat": LAT + dlat + r},
            {"lon": LON + dlon - r, "lat": LAT + dlat + r}]


def _write_tile(path, ring_pts, pad=5.0, epsg=26910, extra_xy=()):
    """A LAZ whose HEADER bbox is ring_pts' bbox grown by `pad`, plus any raw `extra_xy` points.

    `extra_xy` is the whole point of this copy: the header bbox is the extent of the points in the
    file, so ONE junk coordinate in native units moves the rectangle the coverage check trusts.
    `epsg=None` writes a tile that declares no CRS at all.
    """
    import laspy
    import numpy as np
    from pyproj import CRS, Transformer
    crs = None if epsg is None else CRS.from_epsg(epsg)
    T = Transformer.from_crs("EPSG:4326", crs or CRS.from_epsg(26910), always_xy=True)
    xy = [T.transform(q["lon"], q["lat"]) for q in ring_pts]
    x0 = min(c[0] for c in xy) - pad
    x1 = max(c[0] for c in xy) + pad
    y0 = min(c[1] for c in xy) - pad
    y1 = max(c[1] for c in xy) + pad
    xs = [x0, x1, x0, x1] + [float(p[0]) for p in extra_xy]
    ys = [y0, y0, y1, y1] + [float(p[1]) for p in extra_xy]
    h = laspy.LasHeader(version="1.4", point_format=6)
    h.global_encoding.gps_time_type = 1
    if crs is not None:
        h.add_crs(crs)
    las = laspy.LasData(h)
    las.x = np.array(xs)
    las.y = np.array(ys)
    las.z = np.zeros(len(xs))
    las.gps_time = np.full(len(xs), 1.32e9)
    las.write(str(path))


def _course(root, rings=(), tiles=(), metas=(), hole_ways=(), course_json=True):
    """A course directory shaped the way lidar_coverage.report() reads one, under tmp_path.

    rings:      [(green_id, ring)]                    -> osm_geom.json golf=green ways
    tiles:      [(name, ring_pts, pad, epsg, extra)]  -> laz/<name>, trailing args optional
    metas:      [dict]                                -> dem_hd/holeNN.json
    hole_ways:  [(ref, [{"lon","lat"}, ...])]         -> osm_geom.json golf=hole centrelines
    course_json: True for a well-formed one naming 18 holes, None for none, or raw text
    """
    root = pathlib.Path(root)
    (root / "laz").mkdir(parents=True, exist_ok=True)
    els = [{"type": "way", "id": gid, "tags": {"golf": "green"}, "geometry": r}
           for gid, r in rings]
    els += [{"type": "way", "id": 900 + i, "tags": {"golf": "hole", "ref": str(ref)},
             "geometry": geom} for i, (ref, geom) in enumerate(hole_ways)]
    (root / "osm_geom.json").write_text(json.dumps({"elements": els}))
    for t in tiles:
        _write_tile(root / "laz" / t[0], *t[1:])
    if metas:
        (root / "dem_hd").mkdir(exist_ok=True)
        for m in metas:
            (root / "dem_hd" / f"hole{int(m['hole']):02d}.json").write_text(json.dumps(m))
    if course_json is True:
        (root / "course.json").write_text(json.dumps(
            {"name": "Synthetic", "location": {"lat": LAT, "lon": LON},
             "holes": {str(i): {"par": 4} for i in range(1, 19)}}))
    elif isinstance(course_json, str):
        (root / "course.json").write_text(course_json)
    return str(root)


def _clean(root, **kw):
    """The fixture every test below starts from: one green, one tile over it, one hole inside it, one
    surface built from the point cloud. A verdict on it must be clean and its exit code 0, so a
    non-zero anywhere else in a test is the defect and not the fixture's shape."""
    kw.setdefault("rings", [(1, ring())])
    kw.setdefault("tiles", [("a.laz", ring(), 5.0, 26910)])
    kw.setdefault("metas", [{"hole": 1, "green_id": 1, "source": LIDAR}])
    kw.setdefault("hole_ways", [("1", [{"lon": LON, "lat": LAT}])])
    return _course(root, **kw)


# Every module this fixture drops from sys.modules, under one rule: importing it reaches the COURSE env
# var -- by reading it itself, or through a chain of module-level sibling imports that ends at one that
# does. NOT A LIST TO EXTEND BY HAND. The rule is re-derived off the engine's own source by
# test_the_course_module_pop_list_is_derived_from_the_engine_and_not_hand_typed below, which refuses a
# name that does not meet it. `lidar_coverage` was listed here and does not meet it; that test's
# docstring has what it cost. Named once and used at both ends of the fixture, so the two spellings
# cannot drift apart the way the entry and its rule did.
_COURSE_MODULES = ("config",)


@pytest.fixture
def cov(monkeypatch):
    """lidar_coverage bound to a real slug, plus the two things every test here needs of it.

    `verdict(dir)` -> (status, bad, holes, fallback, printed); `code(dir)` -> main()'s exit code, which
    is what `python3 lidar_coverage.py` and an agent gating the fetch step actually see.

    `lidar_coverage` IS NOT DROPPED and must not be, although this is its test module. It reads no
    COURSE at import and imports no config there -- its `import config` is inside main(), so it resolves
    out of sys.modules at call time and sees the config object this fixture just imported and patched.
    Dropping it therefore bought no isolation and cost identity: `fetch_osm.py` and
    `tools/verify_elevation.py` both hold `from lidar_coverage import _env_on` at module level and
    neither is dropped here, so a pop left them on the old function and gave the next import a SECOND
    copy of the file.
    """
    pytest.importorskip("laspy")
    pytest.importorskip("pyproj")
    corpus = _corpus()
    if not corpus:
        pytest.skip("per-course data is gitignored; config.py needs one course to import")
    monkeypatch.setenv("COURSE", os.path.basename(corpus[0]))
    for m in _COURSE_MODULES:
        sys.modules.pop(m, None)
    import config
    import lidar_coverage as lc

    def verdict(course_dir):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status, bad, holes, fb = lc.report(str(course_dir))
        return status, bad, holes, fb, buf.getvalue()

    def code(course_dir):
        monkeypatch.setattr(config, "COURSE_DIR", str(course_dir))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return lc.main()

    try:
        yield types.SimpleNamespace(lc=lc, config=config, verdict=verdict, code=code)
    finally:
        for m in _COURSE_MODULES:
            sys.modules.pop(m, None)


# --- the drop-list above is graded, not hand-typed -----------------------------------------------

def _top_level_statements(tree):
    """Every node in `tree` that really EXECUTES when the module is imported.

    A function or class BODY does not: config.py reads the env var at module level, and the same read
    inside a `def` happens at call time, which this list is not about. Module-level `if`/`try` bodies
    are kept -- those still run during the import.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield from ast.walk(node)


def _reads_course_env_at_import(tree):
    """Does importing this module read os.environ["COURSE"] -- subscript or .get() -- itself?"""
    for node in _top_level_statements(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            env, keys = node.func.value, node.args
        elif isinstance(node, ast.Subscript):
            env, keys = node.value, [node.slice]
        else:
            continue
        if isinstance(env, ast.Attribute) and env.attr == "environ":
            if any(isinstance(k, ast.Constant) and k.value == "COURSE" for k in keys):
                return True
    return False


def _module_level_local_imports(tree, local):
    """The sibling modules this one imports AT IMPORT TIME. Deferred imports are not this edge."""
    out = set()
    for node in _top_level_statements(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name in local}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module in local:
            out.add(node.module)
    return out


def _course_reaching_modules():
    """(modules whose import reads COURSE, module-level import edges) -- derived off the engine.

    Seeded from the modules that read the env var themselves and closed over module-level imports of
    one another, because `import config` at module level runs config.py's read during YOUR import.
    Nothing here is hand-typed, which is the point: the seed today is config alone.
    """
    local = {os.path.basename(p)[:-len(".py")] for p in glob.glob(os.path.join(ROOT, "*.py"))}
    trees = {}
    for name in sorted(local):
        with open(os.path.join(ROOT, f"{name}.py"), encoding="utf-8") as fh:
            trees[name] = ast.parse(fh.read())
    reach = {n for n, t in trees.items() if _reads_course_env_at_import(t)}
    edges = {n: _module_level_local_imports(t, local) for n, t in trees.items()}
    grew = True
    while grew:
        grew = False
        for name, deps in edges.items():
            if name not in reach and deps & reach:
                reach.add(name)
                grew = True
    return reach, edges


def _engine_modules_this_file_imports_deferred():
    """Every engine module this file imports from INSIDE a function, read off its own source.

    A deferred import is how a test here binds a module to the course it has just set, so this is the
    population the drop-list has to cover -- the analogue of test_r14_deadcode.py's `_bind()` names.
    Third-party imports (laspy, numpy, pyproj) are not engine modules and are filtered out by the same
    ROOT/*.py glob the rule itself is derived from.
    """
    local = {os.path.basename(p)[:-len(".py")] for p in glob.glob(os.path.join(ROOT, "*.py"))}
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Import):
                out |= {a.name for a in node.names if a.name in local}
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module in local:
                out.add(node.module)
    return out


def test_the_course_module_pop_list_is_derived_from_the_engine_and_not_hand_typed():
    """_COURSE_MODULES is a hand-typed list under a written-down rule. Grade the rule, not the list.

    A NAME LISTED HERE THAT DOES NOT MEET THE RULE IS NOT UNTIDY, IT IS A HAZARD. Popping a module that
    other modules already hold a module-level reference to leaves those holders bound to the OLD object;
    the next `import` re-executes the file and makes a SECOND copy, so a test that reads an attribute off
    one copy is not reading the one the code under test calls.

    This list had one such name: `lidar_coverage`, the module this whole file is about. It reads no
    COURSE and imports no config at module level (its `import config` is inside main(), resolved from
    sys.modules at call time), so dropping it isolated nothing -- while `fetch_osm.py:39` and
    `tools/verify_elevation.py:143` both hold `from lidar_coverage import _env_on` at module level and
    neither is dropped here. It cost a real order-dependent failure, latent in default order only
    because this module sorts before its victim:

        tests/test_r15_osm_keys.py::test_every_osm_acknowledgement_key_is_documented_in_the_pipeline
        tests/test_r14_coverage.py
            ::test_only_the_known_point_cloud_vocabulary_counts_as_point_cloud_derived
        tests/test_r15_osm_keys.py
            ::test_fetch_osm_reads_its_acknowledgement_keys_through_the_shared_env_on

    The third id asserts `fetch_osm._env_on is lidar_coverage._env_on` -- the check that stops the
    off-vocabulary drifting into an eighth hand-written copy -- and the fixture above turned it into a
    comparison of two copies of one function.

    WHAT THIS TEST DECIDES:
      * every name in _COURSE_MODULES reaches COURSE when it is imported -- by reading the env var
        itself, or through a chain of module-level sibling imports that ends at one that does;
      * every engine module this file imports inside a function AND that meets the rule is listed, so
        nothing this file fresh-imports is left holding another test's course;
      * the list is CLOSED under that chain: no sibling a listed module imports at module level reaches
        COURSE while sitting outside the list.

    WHAT IT DOES NOT DECIDE. Not tests/conftest.py's suite-wide list, which drops seven names for every
    test in this directory. Not the drop-lists of sibling test modules. And not the whole population
    meeting the rule -- eleven engine modules do, and a file has no business dropping ones it never
    imports. Same shape as test_r14_deadcode.py's grader on purpose: one convention, two lists.
    """
    reach, edges = _course_reaching_modules()
    assert "config" in reach, (
        "no module in this repo was found reading os.environ['COURSE'] at import time, so this grader "
        "derived an empty rule and would pass over any list at all")
    unqualified = [m for m in _COURSE_MODULES if m not in reach]
    assert not unqualified, (
        f"_COURSE_MODULES lists {unqualified} under the rule 'reads the COURSE env var at import "
        f"time', and importing {'them' if len(unqualified) > 1 else 'it'} reads no COURSE: no env read "
        f"of its own, and no module-level import chain that ends at one. Dropping such a module from "
        f"sys.modules gives every module that already holds it a stale reference and the next import a "
        f"second copy of the file -- see this test's docstring for the failure that cost")
    deferred = _engine_modules_this_file_imports_deferred()
    assert deferred, (
        "no deferred engine import found in this file; this half of the grader measures nothing")
    unpopped = sorted((deferred & reach) - set(_COURSE_MODULES))
    assert not unpopped, (
        f"this file fresh-imports {unpopped} inside a function without listing "
        f"{'them' if len(unpopped) > 1 else 'it'} in _COURSE_MODULES, so the module stays in "
        f"sys.modules bound to whichever course imported it first and the next test inherits that "
        f"binding")
    siblings = {d for m in _COURSE_MODULES for d in edges[m]} - set(_COURSE_MODULES)
    leaked = sorted(m for m in siblings if m in reach)
    assert not leaked, (
        f"{leaked} reach COURSE at import time and are imported at module level by a module in "
        f"_COURSE_MODULES, but are not in it -- so popping the listed module drops a course-bound "
        f"import while leaving {leaked} resident, still bound to the previous test's course")


# --- I-1: a junk coordinate must not be allowed to vouch for the neighbourhood -------------------

def test_one_stray_point_cannot_balloon_a_header_bbox_into_a_pass(tmp_path, cov):
    """A green 4 km outside the point data is correctly flagged -- until a SINGLE junk XY point is
    added to the tile, at which point the header rectangle swallows both greens and the module prints
    "all 2 green(s) fall inside the downloaded tiles' header bounding boxes" and exits 0.

    There was no plausibility bound on the rectangle at all. Measured across the 78 real tiles on
    disk, the widest header extent is 3000 native units (a 3000-ft Alameda cell) and the narrowest 41;
    a tile declaring hundreds of thousands of units is not a tile, and refusing to place anything with
    it is the only honest answer -- the greens it really does serve cannot be delimited any more.
    """
    real, far = ring(), ring(dlon=0.045)          # ~4 km east, like Castlewood Hill's 14 and 16
    both = [(1, real), (2, far)]

    honest = _clean(tmp_path / "honest", rings=both)
    status, bad, _h, _f, printed = cov.verdict(honest)
    assert status == "checked" and [g for g, _o, _t in bad] == [2], \
        f"the baseline gap is not being flagged, so this test proves nothing: {status!r} {bad}\n{printed}"
    assert cov.code(honest) == 1, "a green outside every tile footprint is exit 1"

    # ...and now one junk point, in the tile's own native units.
    junk = _clean(tmp_path / "junk", rings=both,
                  tiles=[("a.laz", real, 5.0, 26910, [(700000.0, 4600000.0)])])
    status, bad, _h, _f, printed = cov.verdict(junk)
    assert status != "checked" or bad, (
        f"one junk XY point bought a green 4 km outside the data a clean bill of health: status "
        f"{status!r}, flagged {bad}\n{printed}")
    assert "a.laz" in printed, f"the implausible tile is not named:\n{printed}"
    assert "NOT CHECKED" in printed, (
        f"an implausible header rectangle must read as NOT CHECKED, not as a quiet skip:\n{printed}")
    assert cov.code(junk) != 0, "exit 0 for a tile whose declared extent is junk"

    # The bound has SLACK, deliberately: a tile 3000 units wide is the widest real one on disk, and a
    # bound fitted to that is a tripwire on ordinary future data. 1 km and 3 km tiles must pass.
    for pad in (500.0, 1500.0):
        wide = _clean(tmp_path / f"wide{pad:.0f}", tiles=[("a.laz", ring(), pad, 26910)])
        status, bad, _h, _f, printed = cov.verdict(wide)
        assert (status, bad) == ("checked", []), (
            f"a tile {2 * pad:.0f} units across was refused; the widest real tile on disk is 3000 "
            f"units: {status!r} {bad}\n{printed}")

    # CALIBRATION against the real distribution: every tile of every built course must still place.
    for cd in _corpus():
        boxes, why = cov.lc._footprint_boxes(cd)
        if not glob.glob(os.path.join(cd, "laz", "*.laz")):
            continue
        assert boxes and not why, (
            f"{os.path.basename(cd)}: the plausibility bound refuses a REAL tile -- {why!r}. The "
            f"bound must come from the measured distribution, not be tightened until something real "
            f"trips it.")


# --- I-2 / I-3: a surface that cannot be read or identified is not evidence of anything ----------

def test_an_unreadable_dem_hd_does_not_read_as_an_empty_one(tmp_path, cov):
    """built_surfaces() swallowed OSError/ValueError per file, so an entirely unreadable dem_hd/
    printed the SAME WORDS as a genuinely empty one -- "dem_hd/ holds no green surface to
    cross-check" -- and exited 0. The cross-check that exists precisely to catch the header
    rectangle's blind spot silently declined to run.
    """
    empty = _clean(tmp_path / "empty", metas=[])
    pathlib.Path(empty, "dem_hd").mkdir()
    st_empty, _b, _h, _f, said_empty = cov.verdict(empty)
    assert st_empty == "checked" and cov.code(empty) == 0, \
        f"an EMPTY dem_hd/ is not a finding -- nothing has been built yet: {st_empty!r}\n{said_empty}"
    assert "no green surface to cross-check" in said_empty, said_empty

    unreadable = _clean(tmp_path / "unreadable", metas=[])
    d = pathlib.Path(unreadable, "dem_hd")
    d.mkdir()
    (d / "hole01.json").write_text("{ this is not json")
    (d / "hole02.json").write_bytes(b"\x00\x01\x02")
    status, _b, _h, _f, printed = cov.verdict(unreadable)
    assert printed != said_empty, (
        f"an unreadable dem_hd/ prints the same words as an empty one, so the reader cannot tell "
        f"'nothing to cross-check' from 'I could not read it':\n{printed}")
    assert "hole01.json" in printed and "hole02.json" in printed, \
        f"the files that could not be read are not named:\n{printed}"
    assert status != "checked", f"status {status!r}: two unreadable surfaces are not a clean verdict"
    assert cov.code(unreadable) != 0, "exit 0 although the dem_hd cross-check never ran"


def test_a_surface_that_cannot_be_identified_is_counted_not_dropped(tmp_path, cov):
    """A meta missing `green_id` was dropped from `built` entirely, so it appeared in NEITHER the
    numerator nor the denominator: two readable of three printed "all 2 built green surface(s) came
    from the point cloud" and exited 0. A surface that cannot be identified cannot be cross-checked,
    and the population is the one that EXISTS on disk.
    """
    metas = [{"hole": 1, "green_id": 1, "source": LIDAR},
             {"hole": 2, "green_id": 2, "source": LIDAR},
             {"hole": 3, "source": LIDAR}]                 # no green_id -- unidentifiable
    cdir = _clean(tmp_path / "nogid", metas=metas)
    status, _b, _h, _f, printed = cov.verdict(cdir)
    assert "hole03.json" in printed, (
        f"the surface with no green_id vanished from the report; it is in neither the numerator nor "
        f"the denominator:\n{printed}")
    assert " 3 " in printed or " of 3" in printed, (
        f"the denominator is still the population that PARSED, not the one that exists (three files "
        f"are on disk):\n{printed}")
    assert status != "checked", f"status {status!r} for a surface that could not be identified"
    assert cov.code(cdir) != 0, "exit 0 with an unidentifiable green surface on disk"


# --- I-4: point-cloud-derived must be a POSITIVE test, not an allowlist of badness ---------------

def test_only_the_known_point_cloud_vocabulary_counts_as_point_cloud_derived(tmp_path, cov):
    """`fell_back` was an allowlist of badness -- insufficient, or "seamless" in the source -- so a
    `source` that was missing, null, or spoke any third vocabulary read as "came from the point
    cloud" and exited 0. This is the difference between default-to-pass and default-to-refuse, and
    this project's posture is that refusing is always safer.

    The corpus has exactly two vocabularies (192 metas LiDAR, 6 seamless) and both must keep working:
    the fix is not to distrust everything, it is to trust only what has been read.
    """
    known = {"the point-cloud vocabulary": (LIDAR, 0), "the seamless vocabulary": (SEAMLESS, 1)}
    for label, (src, want) in known.items():
        cdir = _clean(tmp_path / f"k{want}", metas=[{"hole": 1, "green_id": 1, "source": src}])
        status, _b, _h, fb, printed = cov.verdict(cdir)
        assert status == "checked", f"{label} is no longer recognised: {status!r}\n{printed}"
        assert bool(fb) == bool(want), f"{label} classified wrong: fell_back={fb}\n{printed}"
        assert cov.code(cdir) == want, f"{label} must be exit {want}\n{printed}"

    for label, meta in (("a missing source", {"hole": 1, "green_id": 1}),
                        ("a null source", {"hole": 1, "green_id": 1, "source": None}),
                        ("a third vocabulary", {"hole": 1, "green_id": 1,
                                                "source": UNKNOWN_VOCABULARY})):
        cdir = _clean(tmp_path / f"u{abs(hash(label)) % 9999}", metas=[meta])
        status, _b, _h, _f, printed = cov.verdict(cdir)
        assert status != "checked", (
            f"{label} read as 'came from the point cloud': status {status!r}\n{printed}")
        assert cov.code(cdir) != 0, f"exit 0 for {label}"
        assert "hole 1" in printed or "green 1" in printed, \
            f"{label} is not named, so a reader cannot go and look at it:\n{printed}"
        # The cross-check may still say how many surfaces it DID establish -- what it must never do is
        # publish the "all N" claim over a population it could not read.
        ALL = r"all \d+ built green surface\(s\) came from the point cloud"
        assert re.search(ALL, printed) is None, (
            f"{label} was published as a point-cloud surface:\n{printed}")
        assert re.search(r"dem_hd cross-check: 0 of 1 built green surface\(s\) came from the point "
                         r"cloud", printed), (
            f"{label} was counted among the surfaces whose provenance was established:\n{printed}")

    # CALIBRATION: every one of the 198 real metas must classify as one of the two known vocabularies.
    for cd in _corpus():
        built, unidentified = cov.lc.built_surfaces(cd)
        assert not unidentified, \
            f"{os.path.basename(cd)}: real metas read as unidentifiable: {unidentified}"
        unknown = cov.lc.unverified_sources(built)
        assert not unknown, (
            f"{os.path.basename(cd)}: the positive check refuses a REAL source vocabulary: {unknown}. "
            f"Widen the vocabulary from the corpus; do not narrow the check.")


def test_the_source_fixtures_reproduce_what_the_sidecars_record():
    """LIDAR and SEAMLESS claim to be BYTE-IDENTICAL to what the two fetch stages write, and nothing
    graded that claim.

    It is the whole point of those two literals: the test above establishes that both vocabularies keep
    classifying, and that establishes nothing at all if the strings are a paraphrase of what the stages
    actually record. A fixture that has drifted from the artifact it stands in for tests the fixture.

    And it is the reason SEAMLESS may spell a figure the arrays deny -- it is quoting a sidecar, not
    claiming a resolution, and the repo's one-metre guard exempts it on exactly that basis (see the note
    above these constants). An exemption earned by "this is what the corpus records" has to be checked
    against the corpus, or it is earned by assertion.

    Read straight off courses/*/dem_hd/hole*.json rather than through lidar_coverage's classifier, which
    only asks whether a string is recognised, not whether it is this one. NOT VACUOUS: the read has to
    find sidecars, has to find distinct values, and each fixture has to be one of them -- a corpus test
    that passes because it enumerated nothing is the failure this campaign keeps meeting. courses/ is
    gitignored, so a fresh clone skips instead.
    """
    recorded, sidecars = {}, 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "dem_hd", "hole*.json"))):
        if os.path.basename(os.path.dirname(os.path.dirname(p))).startswith("_"):
            continue                                    # a scratch slug, not a real course
        with open(p, encoding="utf-8") as fh:
            src = json.load(fh).get("source")
        sidecars += 1
        if isinstance(src, str):
            recorded.setdefault(src, []).append(os.path.relpath(p, ROOT))
    if not sidecars:
        pytest.skip("per-course green surfaces are gitignored; no sidecar to read a source off")
    assert len(recorded) >= 2, (
        f"{sidecars} sidecar(s) on disk record {len(recorded)} distinct source value(s), so this check "
        f"cannot tell one vocabulary from another and both fixtures below would pass on one string: "
        f"{sorted(recorded)}")
    drifted = [f"{name} = {value!r} is recorded by no sidecar on disk"
               for name, value in (("LIDAR", LIDAR), ("SEAMLESS", SEAMLESS))
               if value not in recorded]
    assert not drifted, (
        "a source fixture is not what the stages write, so the vocabulary test above is grading this "
        "file rather than the pipeline -- and SEAMLESS's exemption from the one-metre guard rests on "
        f"being a verbatim record of a sidecar. The {len(recorded)} value(s) actually recorded across "
        f"{sidecars} sidecar(s) are:\n  "
        + "\n  ".join(f"{v!r} in {len(w)} sidecar(s)" for v, w in sorted(recorded.items()))
        + "\n  " + "\n  ".join(drifted))


# --- I-5: no holes to check is not every hole covered -------------------------------------------

def test_zero_hole_centrelines_is_not_all_holes_covered(tmp_path, cov):
    """uncovered_holes() returns [] both for "every hole is inside the point data" and for "there are
    no hole ways at all", and report() printed nothing about holes on the clean path -- so the verdict
    showed no trace of the half of the check that governs whether trees appear, and exited 0.

    The expectation comes from course.json, the hand-transcribed scorecard: it is the only thing that
    knows the course has holes at all. A directory with no scorecard (the synthetic fixtures this
    module's tests are built from) still gets the printed NOT-CHECKED line, but nothing is downgraded
    on a course nothing claims to have holes.
    """
    covered = _clean(tmp_path / "covered")
    status, _b, holes, _f, printed = cov.verdict(covered)
    assert (status, holes) == ("checked", []) and cov.code(covered) == 0, \
        f"the baseline is not clean: {status!r} {holes}\n{printed}"

    none = _clean(tmp_path / "noholes", hole_ways=[])
    status, _b, holes, _f, printed = cov.verdict(none)
    assert holes == [], holes
    assert "NOT CHECKED" in printed and "hole" in printed, (
        f"zero hole centreline ways printed no trace of itself, so a reader cannot tell it from "
        f"every hole covered:\n{printed}")
    assert status != "checked", (
        f"status {status!r} for a course whose scorecard names 18 holes and whose osm_geom.json holds "
        f"no centreline at all -- the tree half of the check never ran")
    assert cov.code(none) != 0, "exit 0 although no hole centreline was ever checked"

    # No scorecard, so no expectation: the line is still printed, which is what stops it being silent.
    anon = _clean(tmp_path / "anon", hole_ways=[], course_json=None)
    _st, _b, _h, _f, printed = cov.verdict(anon)
    assert "NOT CHECKED" in printed and "hole" in printed, printed


# --- I-6: a malformed scorecard is a named refusal, not a traceback and a leaked handle ----------

def test_a_malformed_course_json_is_a_named_refusal_not_a_traceback(tmp_path, cov):
    """`json.load(open(_cjp))` raised JSONDecodeError straight out of uncovered_holes() -- non-zero,
    so not a silent pass, but a traceback where this module's own convention is a named NOT CHECKED
    status -- and leaked the file handle on every call besides.
    """
    bad = _clean(tmp_path / "badjson", course_json='{"location": {"lat": 38.05,')
    status, _b, holes, _f, printed = cov.verdict(bad)          # must not raise
    assert holes == [], holes
    assert "course.json" in printed and "NOT CHECKED" in printed, \
        f"the malformed scorecard is not reported as a named NOT CHECKED status:\n{printed}"
    assert status != "checked", f"status {status!r} with an unreadable course.json"
    assert cov.code(bad) != 0, "exit 0 with a course.json that cannot be parsed"

    # ...and the handle is closed. CPython drops the file object as soon as json.load returns, so an
    # unclosed one reports itself here and nowhere else.
    good = _clean(tmp_path / "goodjson")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cov.lc.uncovered_holes(good)
    leaks = [str(w.message) for w in caught
             if issubclass(w.category, ResourceWarning) and "course.json" in str(w.message)]
    assert not leaks, f"course.json is opened without a context manager: {leaks}"


# --- the confirmed behaviour: two keys, still independent, and neither hides a finding -----------

def test_the_two_acknowledgement_keys_stay_independent_over_the_new_verdicts(tmp_path, cov,
                                                                            monkeypatch):
    """The keys are verified correct and must stay that way: ALLOW_COVERAGE_GAPS says "these gaps are
    real and I have read them", ALLOW_UNCHECKED_COVERAGE says "build although something was not
    verified". Neither may silence the other's finding, and a verdict that is BOTH -- now reachable,
    since a refused tile or an unreadable meta can sit beside a real gap -- needs both.
    """
    GAPS, UNCHECKED = cov.lc.COVERAGE_GAPS_ACK, cov.lc.UNCHECKED_ACK
    assert GAPS != UNCHECKED, "one flag cannot waive two different questions"

    GAP = ("checked", [(2, 5, 5)], [], {})
    NOT_CHECKED = ("no readable LAZ tiles on disk", [], [], {})
    BOTH = ("1 dem_hd surface file(s) could not be read", [(2, 5, 5)], [], {})

    def run(verdict, keys):
        with monkeypatch.context() as mp:
            mp.setattr(cov.lc, "report", lambda _cd, v=verdict: v)
            for k in (GAPS, UNCHECKED):
                mp.delenv(k, raising=False)
            for k in keys:
                mp.setenv(k, "1")
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    cov.lc.report_or_exit(str(tmp_path))
                return None, buf.getvalue()
            except SystemExit as e:
                return str(e.args[0]), buf.getvalue()

    matrix = [
        (GAP, (), GAPS), (GAP, (GAPS,), None), (GAP, (UNCHECKED,), GAPS),
        (GAP, (GAPS, UNCHECKED), None),
        (NOT_CHECKED, (), UNCHECKED), (NOT_CHECKED, (GAPS,), UNCHECKED),
        (NOT_CHECKED, (UNCHECKED,), None), (NOT_CHECKED, (GAPS, UNCHECKED), None),
        (BOTH, (), UNCHECKED), (BOTH, (GAPS,), UNCHECKED), (BOTH, (UNCHECKED,), GAPS),
        (BOTH, (GAPS, UNCHECKED), None),
    ]
    for verdict, keys, want_key in matrix:
        stopped, printed = run(verdict, keys)
        if want_key is None:
            assert stopped is None, (
                f"verdict {verdict[0]!r} with {keys or 'no key'} must be allowed through: {stopped}")
            # ...and a waiver must never hide the finding it waives.
            assert printed.strip(), f"{keys} waived {verdict[0]!r} in silence: nothing printed"
        else:
            assert stopped is not None and want_key in stopped, (
                f"verdict {verdict[0]!r} with {keys or 'no key'} must stop and name {want_key}: "
                f"{stopped!r}")
