#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Round 14's dead-value sweep: five producer lines whose consumer was deliberately replaced by a
later commit, leaving the producer orphaned. Each is harmless dead code, proven two ways:

  * SITE 3 and SITE 5 (fetch_dem.py, fetch_dem_hd.py) have a real callee to poison -- monkeypatch it
    to raise, run the actual production code path, and the dead line's continued existence is a
    hard failure. That is a genuine behavioural discriminator, not a source-text grep.
  * SITE 1, 2 and 4 have no callee to poison -- they are a plain unused binding. For those the only
    honest proof is that a real render is byte-for-byte unchanged, so this file hashes the full
    output of render_hole()/render_green() for every hole of a real corpus course and pins it to a
    constant captured by hand from the unfixed tree. That constant cannot itself go red-then-green
    across the deletion (a truly dead line changes no output, before or after) -- what it guards
    against is a FUTURE edit at the same site accidentally touching something live.

No test here writes anything: render_hole.render_hole(), render_green.render() and
fetch_dem_hd.build_targets() only read files under courses/. fetch_dem.main() additionally has its
network fetch and its write poisoned as a defence-in-depth check on this file's own precondition
(every green already has a good surface, so main() should never reach either).
"""
import glob
import hashlib
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Every module that reads the COURSE env var at import time (directly, or via config/geo at import).
_COURSE_MODULES = ("config", "geo", "surface_io", "fetch_dem", "fetch_dem_hd",
                    "render_hole", "render_green")


@pytest.fixture(autouse=True)
def _isolate_course_binding():
    """Restore COURSE and drop course-bound modules after every test in this file.

    Mirrors tests/test_phase1_regressions.py's _bind_a_course fixture for the same reason it exists
    there: several tests below rebind COURSE and pop config/render_*/fetch_* out of sys.modules, so
    without this, test order would decide which course the NEXT test inherits.
    """
    prev = os.environ.get("COURSE")
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
        for m in _COURSE_MODULES:
            sys.modules.pop(m, None)


def _corpus_slugs():
    """Real (non-scratch) course slugs with the geometry render_hole.load() needs.

    Same rule tests/test_phase1_regressions.py's _courses() uses: underscore-prefixed folders are
    scratch space, not a course, and must not silently join the corpus this file measures against.
    """
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        if all(os.path.exists(os.path.join(ROOT, "courses", slug, f))
               for f in ("osm_geom.json", "osm_course.json")):
            out.append(slug)
    return out


def _bind(slug, *modnames):
    """Fresh-import `modnames` bound to `slug` (config and friends read COURSE at import time)."""
    os.environ["COURSE"] = slug
    for m in _COURSE_MODULES:
        sys.modules.pop(m, None)
    return [importlib.import_module(m) for m in modnames]


def _a_course():
    """One built course, or SKIP -- never IndexError a fresh clone with no courses/ at all."""
    slugs = _corpus_slugs()
    if not slugs:
        pytest.skip("per-course data is gitignored; nothing to measure")
    return slugs[0]


def _course_has_every_surface_good(slug):
    """True when every dem_hd/holeNN.json under `slug` is a good, non-seamless, non-insufficient
    surface -- the precondition test_site5a_* needs so fetch_dem.main() skips every hole via
    keeps_existing_surface() before it can reach the network or a write."""
    metas = sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json")))
    if not metas:
        return False
    for mp in metas:
        try:
            meta = json.load(open(mp))
        except (OSError, ValueError):
            return False
        src = str((meta or {}).get("source", "")).strip()
        if not src or "seamless" in src.lower() or meta.get("insufficient"):
            return False
    return True


def _a_course_with_every_surface_good():
    slugs = _corpus_slugs()
    if not slugs:
        pytest.skip("per-course data is gitignored; nothing to measure")
    for slug in slugs:
        if _course_has_every_surface_good(slug):
            return slug
    pytest.skip("no course on disk has every green as a good non-seamless 0.4 m surface")


def _sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------
# SITE 1 -- render_hole.py: `holes = [e for e in geom if ... == 'hole' ...]`, assigned once and
# never read again in render_hole(). The hole actually drawn comes from
# geo.hole_lines(geom, ...)[hnum], a few lines below, which filters `geom` independently.
# ---------------------------------------------------------------------------------------------
def test_site1_render_hole_output_is_byte_identical():
    """render_hole.render_hole() output for every hole of a real course, hashed and pinned.

    Deleting the orphaned `holes=` binding at render_hole.py cannot change what gets drawn -- nothing
    else in render_hole() reads the name `holes`. The proof is this hash, captured by hand from the
    unfixed tree, still matching after the line is gone.
    """
    slug = _a_course()
    cfg, rh = _bind(slug, "config", "render_hole")
    parts = []
    for hn in cfg.HOLE_NUMS:
        svg, info = rh.render_hole(hn, cfg.HOLES)
        parts.append(svg)
        parts.append(json.dumps(info, sort_keys=True, default=repr))
    digest = _sha(*parts)
    assert digest == "830da484225e1f46ffee15c879b735fea5e969f014d6ff75c4ab1d566980fbda", (
        f"render_hole output for {slug} hashed to {digest!r}; expected the value captured by hand "
        f"from the unfixed tree before deleting the dead `holes=` line at render_hole.py:~438")


# ---------------------------------------------------------------------------------------------
# SITE 2, 3, 4 -- all three live inside render_green.render():
#   SITE 2 (~line 854): `tilt_pct, undul_ft, rise_ft = S['tilt_pct'], S['undul_ft'], S['rise_ft']`.
#     rise_ft is never read again -- the confidence gate that used to consume it now lives inside
#     green_summary() and returns `conf` in S directly; render() reads S['conf'].
#   SITE 3 (~line 796): `ys, xs = np.mgrid[0:H, 0:W]`, dead since the initial commit -- the polygon
#     mask below is built by an independent scanline loop over plain Python ints.
#   SITE 4 (~line 800): `row = []`, reassigned every scanline iteration and never read -- the real
#     accumulator is `xints`.
# ---------------------------------------------------------------------------------------------
def test_site234_render_green_output_is_byte_identical():
    """render_green.render() output for every hole of a real course, hashed and pinned.

    Covers sites 2, 3 and 4 together since all three are unread bindings inside the same function
    and none of them can change what render() draws. The proof is this hash, captured by hand from
    the unfixed tree, still matching after all three lines are gone. Site 3 additionally gets its
    own dedicated behavioural test below (test_site3_...), because it has a real callee to poison.
    """
    slug = _a_course()
    cfg, rg = _bind(slug, "config", "render_green")
    parts = []
    for hn in cfg.HOLE_NUMS:
        svg, summary = rg.render(hn)
        parts.append(svg)
        parts.append(json.dumps(summary, sort_keys=True, default=repr))
    digest = _sha(*parts)
    assert digest == "54103b304652e838c2792e5d963c42d55600c154f0c0685ad7965d45a94291a6", (
        f"render_green output for {slug} hashed to {digest!r}; expected the value captured by hand "
        f"from the unfixed tree before deleting the dead lines at render_green.py:~796,800,854")


def test_site3_render_green_never_subscripts_np_mgrid(monkeypatch):
    """SITE 3 (render_green.py ~line 796): `ys, xs = np.mgrid[0:H, 0:W]`.

    Real behavioural discriminator: replace numpy's `mgrid` with an object that raises on
    subscription, then render every hole of a real course end to end. On the unfixed tree the dead
    line subscripts it and this fails; once it is deleted, render() never touches np.mgrid again --
    the polygon mask a few lines below is a scanline loop over plain Python `r`/`yv`/`xints`.
    """
    slug = _a_course()
    cfg, rg = _bind(slug, "config", "render_green")

    class _RaisingMgrid:
        def __getitem__(self, key):
            raise AssertionError(
                "numpy.mgrid was subscripted -- the dead `ys, xs = np.mgrid[0:H, 0:W]` line at "
                "render_green.py is still live")

    monkeypatch.setattr(rg.np, "mgrid", _RaisingMgrid())
    for hn in cfg.HOLE_NUMS:
        rg.render(hn)   # must complete without ever touching np.mgrid


# ---------------------------------------------------------------------------------------------
# SITE 5 -- fetch_dem.py:~398 and fetch_dem_hd.py:~232: `gc = [(g, *centroid(g)) for g in greens]`.
# The consumer (a local `near()` closure) was deleted by commit 7771571 in BOTH files, replaced with
# geo.match_green(line, greens, label=...), which recomputes each green's centroid inline and adds a
# 40 m bind cap the old code lacked. `gc` now occurs exactly once in each file.
# ---------------------------------------------------------------------------------------------
def test_site5a_fetch_dem_never_calls_centroid_for_a_fully_built_course(monkeypatch):
    """SITE 5a (fetch_dem.py ~line 398).

    On a course where every dem_hd/holeNN.json is already a good, non-seamless, non-insufficient
    surface, keeps_existing_surface() skips every hole before main() reaches the per-hole binding --
    so the ONLY thing in a full main() run that can call fetch_dem.centroid() at all is the dead
    `gc=` line. Monkeypatching it to raise makes that line's continued existence a hard failure;
    deleting it lets main() finish clean.

    Defence in depth, not the thing under test: urlopen and commit_surface are also poisoned, so a
    wrong assumption about "every hole already has a good surface" fails loud instead of silently
    reaching the network or writing under courses/.
    """
    slug = _a_course_with_every_surface_good()
    fetch_dem, = _bind(slug, "fetch_dem")

    def _raising_centroid(g):
        raise AssertionError(
            "fetch_dem.centroid() was called -- the dead `gc = [(g, *centroid(g)) for g in greens]` "
            "line at fetch_dem.py is still live")

    def _no_network(*a, **k):
        raise AssertionError(
            "fetch_dem.main() reached the network -- the precondition (every hole on this course "
            "already has a good surface) did not hold, so this test cannot prove what it claims to")

    def _no_write(*a, **k):
        raise AssertionError(
            "fetch_dem.main() tried to write a surface -- the precondition (every hole on this "
            "course already has a good surface) did not hold, so this test cannot prove what it "
            "claims to")

    monkeypatch.setattr(fetch_dem, "centroid", _raising_centroid)
    monkeypatch.setattr(fetch_dem.urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(fetch_dem.surface_io, "commit_surface", _no_write)

    fetch_dem.main()   # must complete without ever calling centroid(), urlopen(), or commit_surface()


def test_site5b_fetch_dem_hd_centroid_called_once_per_hole_not_once_per_green(monkeypatch):
    """SITE 5b (fetch_dem_hd.py ~line 232).

    build_targets() legitimately calls centroid() once per HOLE (`clat,clon=centroid(green)`, a few
    lines below `gc=`) to place that hole's own DEM patch -- so "centroid is never called" is the
    wrong assertion here; that would fail even on the fix. The real discriminator is the COUNT: on
    the unfixed tree the dead `gc=` line adds one more call per GREEN on top of that, so the total is
    len(greens)+len(holes) instead of len(holes).

    build_targets() touches no LAZ tile and no network -- it only reads osm_geom.json and does
    coordinate math -- so this is safe to run against any real course, not just one with fully-built
    surfaces.
    """
    slug = _a_course()
    fetch_dem_hd, = _bind(slug, "fetch_dem_hd")
    calls = {"n": 0}
    real_centroid = fetch_dem_hd.centroid

    def _counting_centroid(g):
        calls["n"] += 1
        return real_centroid(g)

    monkeypatch.setattr(fetch_dem_hd, "centroid", _counting_centroid)
    targets = fetch_dem_hd.build_targets()
    assert calls["n"] == len(targets), (
        f"fetch_dem_hd.centroid() was called {calls['n']} times while building {len(targets)} "
        f"target(s) for {slug} -- expected exactly one call per hole. The dead "
        f"`gc=[(g,*centroid(g)) for g in greens]` line calls it once per green as well, which "
        f"accounts for the extra {calls['n'] - len(targets)} call(s) seen here.")
