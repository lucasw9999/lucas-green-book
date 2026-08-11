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
import ast
import glob
import hashlib
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Every module that reads the COURSE env var at import time -- itself, or through a chain of
# module-level sibling imports that ends at one that does. NOT A LIST TO EXTEND BY HAND: the rule is
# re-derived off the engine's own source by
# test_the_course_module_pop_list_is_derived_from_the_engine_and_not_hand_typed below, which refuses a
# name that does not meet it. surface_io and geo were both listed here and neither meets it; that
# test's docstring has what the first one cost.
_COURSE_MODULES = ("config", "fetch_dem", "fetch_dem_hd", "render_hole", "render_green")


@pytest.fixture(autouse=True)
def _isolate_course_binding():
    """Restore COURSE and drop course-bound modules after every test in this file.

    Mirrors tests/conftest.py's _bind_a_course fixture for the same reason it exists there: several
    tests below rebind COURSE and pop config/render_*/fetch_* out of sys.modules, so without this,
    test order would decide which course the NEXT test inherits. (That fixture used to live in
    tests/test_phase1_regressions.py, which is where this docstring named it; it moved to conftest.py
    so it could cover every module in the directory rather than one.)
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


def _names_this_file_binds():
    """Every module name this file hands to _bind(), read off this file's own source."""
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_bind":
            out |= {a.value for a in node.args[1:] if isinstance(a, ast.Constant)}
    return out


def test_the_course_module_pop_list_is_derived_from_the_engine_and_not_hand_typed():
    """_COURSE_MODULES is a hand-typed list under a written-down rule. Grade the rule, not the list.

    A NAME LISTED HERE THAT DOES NOT MEET THE RULE IS NOT UNTIDY, IT IS A HAZARD, and this list had
    two. Popping a module that other modules already hold a module-level reference to leaves those
    holders bound to the OLD object; the next `import` re-executes the file and makes a SECOND copy,
    so a test that patches an attribute on one copy patches something the code under test never calls.

      * surface_io -- seven module-level holders (fetch_dem, fetch_dem_hd, fetch_hole_elev,
        render_green, tools/gen_provenance, tools/cross_flight_check, tools/verify_elevation), and
        NOTHING ELSE in tests/ ever dropped it, so this list was the whole of the hazard. It cost a
        real order-dependent failure, fixed in 89a2412: a torn-pair injection patched the second copy
        while tools/verify_elevation.check_course read the intact pairs through the first, so eleven
        holes came back checked and no hole was named torn. See tests/test_r15_verify.py's
        `_pairs_torn_at`, which reaches through `ve.surface_io` for exactly that reason.
      * geo -- same shape, latent rather than cashed: it reads no COURSE and imports no config, it is
        pure geodesy with no course-bound state, and tests/conftest.py's `_bind_a_course` drops it for
        every test in this directory anyway, so dropping it a second time here bought nothing.

    WHAT THIS TEST DECIDES:
      * every name in _COURSE_MODULES reaches COURSE when it is imported -- by reading the env var
        itself, or through a chain of module-level sibling imports that ends at one that does;
      * every module name this file hands to _bind() is in the list, so nothing this file
        fresh-imports is left holding another test's course;
      * the list is CLOSED under that chain: no sibling a listed module imports at module level
        reaches COURSE while sitting outside the list. That is the converse, as far as it can safely
        go here, and it is what would have flagged geo/surface_io from the other side.

    WHAT IT DOES NOT DECIDE. Not the suite-wide list -- tests/conftest.py's `_bind_a_course` drops
    seven names for every test in this directory, and this file's list is deliberately narrower than
    that. Not imports made inside a function. And not the whole population meeting the rule: eleven
    engine modules do, and a file has no business dropping the ones it never imports.
    """
    reach, edges = _course_reaching_modules()
    assert "config" in reach, (
        "no module in this repo was found reading os.environ['COURSE'] at import time, so this "
        "grader derived an empty rule and would pass over any list at all")
    unqualified = [m for m in _COURSE_MODULES if m not in reach]
    assert not unqualified, (
        f"_COURSE_MODULES lists {unqualified} under the rule 'reads the COURSE env var at import "
        f"time', and importing {'them' if len(unqualified) > 1 else 'it'} reads no COURSE: no env "
        f"read of its own, and no module-level import chain that ends at one. Dropping such a module "
        f"from sys.modules gives every module that already holds it a stale reference and the next "
        f"import a second copy of the file -- see this test's docstring for the failure that cost")
    bound = _names_this_file_binds()
    assert bound, (
        "no _bind(slug, ...) call found in this file; this half of the grader measures nothing")
    unpopped = sorted(bound - set(_COURSE_MODULES))
    assert not unpopped, (
        f"this file fresh-imports {unpopped} through _bind() without listing "
        f"{'them' if len(unpopped) > 1 else 'it'} in _COURSE_MODULES, so the module stays in "
        f"sys.modules bound to whichever course imported it first and the next test inherits that "
        f"binding")
    siblings = {d for m in _COURSE_MODULES for d in edges[m]} - set(_COURSE_MODULES)
    leaked = sorted(m for m in siblings if m in reach)
    assert not leaked, (
        f"{leaked} reach COURSE at import time and are imported at module level by a module in "
        f"_COURSE_MODULES, but are not in it -- so popping the listed module drops a course-bound "
        f"import while leaving {leaked} resident, still bound to the previous test's course")


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
    else in render_hole() reads the name `holes`. The proof of THAT was this hash, captured by hand from
    the unfixed tree at 0aef283 and unchanged across the deletion.

    RE-PINNED at the 2026-08-10 corpus rebuild, and the value below is the CURRENT engine's render, not
    the 0aef283 one. The deletion proof is historical: it was discharged at that commit and cannot be
    re-run from here, because seven later commits deliberately moved this renderer's output. The cause is
    not inferred -- 29d00ad ("a card measured its carries from one origin and its tick ladder from
    another") ADDED `carry_origin_known`, `green_gap_yd` and `carry_tee_shift_yd` to the `info` dict that
    is hashed here, so a digest taken before those keys existed cannot match one taken after, whatever
    else is or is not equal. The others: fab663a resolved `golf=out_of_bounds`, 03541c8 made
    `golf=penalty_area` a class the renderer draws, 91d30d0 and a7fc354 moved carry figures, 22d23bf and
    89c265b changed what the query asks for.

    RE-PINNED AGAIN when `golf=penalty_area` was split out of the water class into a hazard class of its
    own, for ONE reason and it is measured rather than assumed: the `info` dict gained a `penalty_areas`
    key. This course carries no penalty area at all -- the value is 0 on all 18 holes -- and removing
    that single key from the dict before hashing reproduces the previous pin,
    d786e07749e9c02d4226bfd2594d4d7bf2490fcbf47f67cd67fb7dac62b93d4b, exactly. So no SVG byte and no
    other `info` value moved on this course; a dict with a new key serialises differently, and that is
    all this digest is reporting.

    RE-PINNED A THIRD TIME for the same kind of reason, measured the same way: the `info` dict gained
    `water_ids` and `creek_ids`, the ids of the features each card inked as water. They exist because rule 2
    was being checked by COUNT and a count cannot see a swap -- a genuine `waterway=stream` was made to lose
    its blue on copper-valley 3 with an offsetting mark on copper-valley 1, and every water test in the
    suite passed. The two positive guards now check by IDENTITY instead
    (test_no_card_omits_a_watercourse_the_played_line_reaches and its area sibling), which needs the ids.

    Proved to be the whole cause, not assumed: stripping those two keys from the dict before hashing
    reproduces the previous pin, 7ae3e441eb8d2529e3420559d8d25823efb7e85b0814287fab53aa69590eb773, exactly.
    Separately, hashing the SVGs ALONE with and without the two keys gives identical digests on all twelve
    geometry courses. No card's bytes moved.

    WHAT THE CONSTANT STILL BUYS, which is why it is re-pinned rather than dropped: it catches a FUTURE
    edit at this site that touches something live. That was always its forward-looking job -- the
    docstring at the top of this file says a truly dead line cannot make this hash go red-then-green --
    and it is undiminished by the pin having moved for a reason named above. Re-derived by running the
    code below, never by copying the digest out of a failure message without asking what moved it.
    """
    slug = _a_course()
    cfg, rh = _bind(slug, "config", "render_hole")
    parts = []
    for hn in cfg.HOLE_NUMS:
        svg, info = rh.render_hole(hn, cfg.HOLES)
        parts.append(svg)
        parts.append(json.dumps(info, sort_keys=True, default=repr))
    digest = _sha(*parts)
    assert digest == "b4ce00b406d01035dbb906bf68ca6cb95af351e1ed9d2c5dd10bbd2907f850b5", (
        f"render_hole output for {slug} hashed to {digest!r}; expected the value re-pinned when `info` "
        f"gained water_ids/creek_ids. If a deliberate engine change moved it, "
        f"re-derive this digest and say in the docstring which commit moved it -- do not copy it out of "
        f"this message blind")


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
    and none of them can change what render() draws. The proof of THAT was this hash, captured by hand
    from the unfixed tree at 0aef283 and unchanged across all three deletions. Site 3 additionally gets
    its own dedicated behavioural test below (test_site3_...), which reaches the same conclusion by
    poisoning a real callee and so does not depend on this digest at all.

    RE-PINNED at the 2026-08-10 corpus rebuild, and the value below is the CURRENT engine's render. The
    cause is named and checked, not inferred: 30a324f ("the pocket book reassured a mono printer, and the
    depth ladder was the faintest data on the card") re-inked the depth ladder from `fill="#8a8a8a"` at
    opacity 0.7 to an opaque `RUNG_INK = "#6b6b6b"` with a white paint-order halo, because at 1,104 of
    1,104 labels the old grey composited to 2.24:1 against WCAG's 4.5:1. That ink is written into the SVG
    this digest is taken over -- the current render contains #6b6b6b and no #8a8a8a -- so the pre-30a324f
    digest cannot match. Four further commits moved this renderer (171d978, fc9f3bc, e3e6bbb, 22d23bf).

    The forward-looking job is unchanged: a future edit at sites 2 or 4 that touches something live moves
    this digest. Re-derived by running the code below.
    """
    slug = _a_course()
    cfg, rg = _bind(slug, "config", "render_green")
    parts = []
    for hn in cfg.HOLE_NUMS:
        svg, summary = rg.render(hn)
        parts.append(svg)
        parts.append(json.dumps(summary, sort_keys=True, default=repr))
    digest = _sha(*parts)
    assert digest == "f8d5a61214639afb3b6e8096e7ce578a60aa9b630a6b00df2274394762bd0aa0", (
        f"render_green output for {slug} hashed to {digest!r}; expected the value re-pinned at the "
        f"2026-08-10 corpus rebuild. If a deliberate engine change moved it, re-derive this digest and "
        f"say in the docstring which commit moved it -- do not copy it out of this message blind")


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
