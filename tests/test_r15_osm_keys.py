#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The module guarding hazard ink read its four acknowledgement keys for bare truthiness, and said
nothing when one of them was spent.

`fetch_osm.py` is where an Overpass reply becomes the cache a book is drawn from, and its four keys --
ALLOW_STRUCTURAL_SHRINK, ALLOW_HAZARD_SHRINK, ALLOW_SHRINK, ALLOW_REBIND -- waive the checks that stand
between a re-fetch and a lost bunker, a lost creek, or a card printing a confident read of the wrong
putting surface. Two faults, both against conventions this repo had already written down elsewhere:

  * INVERTIBLE. All five read sites were `os.environ.get("ALLOW_X")`, so every spelling a person
    reaches for to explicitly DISABLE a waiver -- `=0`, `=false`, `=no` -- is a non-empty string,
    therefore truthy, therefore WAIVES the guard. Measured on the tree this file was written against,
    with one bunker of 36 removed from the reply: ALLOW_HAZARD_SHRINK unset ABORTED, `=0` ACCEPTED,
    `=false` ACCEPTED, `=no` ACCEPTED. The safety-conscious reading gets the unsafe outcome. The repo
    already knew this class -- `fetch_trees._env_on`'s own docstring says a raw truthy check "makes
    ALLOW_NO_TREES=0 and =false mean YES" -- and had fixed it in five other modules; fetch_osm.py
    contained zero uses of `_env_on`.

  * SILENT. These four were the only keys in the family of thirteen that printed NOTHING when
    exercised. Every other one prints a `WARNING:` (or `NOTE:` for ALLOW_OSM_TREES) naming what it
    accepted. So a build that accepted the loss of drawn sand or water left no trace in its own output,
    and `courses/` is gitignored -- the cache the loss landed in is the only copy there is. A waiver
    changes the exit code; it must never hide the finding.

NOTHING HERE TOUCHES THE WIRE and nothing here writes under `courses/`. Every reply is a hand-built
Overpass result and every cache is a file under tmp_path, because what is being graded is the parse of
an environment variable and the text a waiver prints -- neither needs a real fetch, and a real fetch
against the corpus would be the destructive operation these guards exist to refuse.
"""
import contextlib
import glob
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The off-vocabulary, and the on side of it, exactly as `_env_on` spells it: an escape hatch is ON only
# if it is not an explicit off. The upper/mixed-case entries are here because `_env_on` case-folds and a
# copy that forgot to would pass a lower-case-only table.
OFF_VALUES = ("", "0", "false", "FALSE", "False", "no", "No", "NO")
ON_VALUES = ("1", "true", "TRUE", "yes", "Yes", "on", "2")

# The four keys this module reads, and what each one waives. Named literally so a rename cannot quietly
# drop one out of the grading.
OSM_ACKS = ("ALLOW_STRUCTURAL_SHRINK", "ALLOW_HAZARD_SHRINK", "ALLOW_SHRINK", "ALLOW_REBIND")


def _osm():
    """fetch_osm, imported once, against whatever course conftest bound.

    DELIBERATELY WITHOUT `sys.modules.pop`, which is the idiom the sibling modules use here. Two
    reasons, and the first is that the figure README publishes -- "drops modules from `sys.modules` at N
    sites", the evidence for its shuffled-order advice -- is counted across `tests/*.py`, so a new module
    reaching for the idiom moves a number in a file this change has no business touching.

    The second is that nothing here needs a re-import. Every reply and every cache below is synthetic:
    the only module state these tests read is `config.SLUG` and `config.COURSE["location"]`, both used
    for labels and for tie-breaking hole refs that are unique in these fixtures. Which course fetch_osm
    happens to be bound to therefore cannot change an answer -- unlike the census tests next door, whose
    corpus arm reads the real caches. The sibling modules pop on their way IN, so a module left cached
    here cannot reach them either.
    """
    try:
        import fetch_osm
    except ImportError as e:                                        # pragma: no cover - env-dependent
        pytest.skip("fetch_osm needs %r" % (getattr(e, "name", None) or e,))
    except SystemExit as e:                                         # pragma: no cover - env-dependent
        pytest.skip("fetch_osm cannot bind a course: %s" % e)
    return fetch_osm


@contextlib.contextmanager
def _only(**flags):
    """Bind exactly these ALLOW_* keys and clear every other one this module reads.

    Clearing the others is the point, not tidiness: the whole reason there are four keys and not one is
    that a waiver granted for a deleted tree stump must not spend the green check, so a test that left a
    neighbouring key set could not tell which key answered.
    """
    held = {k: os.environ.get(k) for k in OSM_ACKS}
    try:
        for k in OSM_ACKS:
            os.environ.pop(k, None)
        for k, v in flags.items():
            if v is not None:
                os.environ[k] = v
        yield
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _el(i, tags, extra=None):
    e = {"type": "way", "id": i, "tags": dict(tags),
         "geometry": [{"lat": 37.70, "lon": -121.90}, {"lat": 37.7001, "lon": -121.9001}]}
    e.update(extra or {})
    return e


_TAGS = {"water": {"natural": "water"}, "waterway": {"waterway": "stream"},
         "tree": {"natural": "tree"}, "wood": {"natural": "wood"},
         "building": {"building": "yes"}}


def _reply(counts, extra=None):
    """An Overpass result holding `counts` features of each kind, as `census` classifies them."""
    els, n = [], iter(range(1, 1000000))
    for kind, count in counts.items():
        tags = _TAGS.get(kind) or {"golf": kind}
        els += [_el(next(n), tags, extra) for _ in range(count)]
    return {"version": 0.6, "elements": els}


# One synthetic cache shaped like a small real one, in the classes the guard buckets separately:
# structural (green/hole/fairway), hazard (bunker/water_hazard/waterway) and volatile churn (tree).
# CHURN_TOLERANCE is 2%, so 300 trees may lose 6 and 300 -> 100 is a collapse, while one bunker of 36
# and one green of 18 have no tolerance at all.
BASE = {"green": 18, "hole": 18, "fairway": 18, "bunker": 36, "water_hazard": 1,
        "waterway": 3, "tree": 300}

# A cache whose golf features are ALL flattened multipolygon rings, which is how the AGGREGATE
# golf-count check is reachable on its own. `_fetchable` strips `_from_relation` elements from the
# per-kind baseline but `ngolf` counts every element in the file, so this cache offers the per-kind
# checks nothing to compare and the total-count check 120 features to lose.
RELATION_ONLY = {"green": 60, "fairway": 60}


def _cases(tmp_path, fo):
    """(label, key, run, expected-fragments) for each of the four shrink read sites.

    `run` replays one reply against one cache; the fragments are what the printed acknowledgement has to
    name, so that a reader can see what the waiver gave up rather than that something was given up.
    """
    def cache(name, counts, extra=None):
        p = tmp_path / name
        p.write_text(json.dumps(_reply(counts, extra)))
        return str(p)

    def against(path, counts, out="osm_course.json"):
        return lambda: fo._check_response(_reply(counts), path, out)

    full = cache("full.json", BASE)
    rings = cache("rings.json", RELATION_ONLY, {"_from_relation": 4242})
    return (
        ("a lost green", "ALLOW_STRUCTURAL_SHRINK",
         against(full, {**BASE, "green": 17}), ("green 18 -> 17",)),
        ("a lost bunker", "ALLOW_HAZARD_SHRINK",
         against(full, {**BASE, "bunker": 35}), ("bunker 36 -> 35",)),
        ("a lost watercourse", "ALLOW_HAZARD_SHRINK",
         against(full, {**BASE, "waterway": 2}), ("waterway 3 -> 2",)),
        ("a collapse in churning kinds", "ALLOW_SHRINK",
         against(full, {**BASE, "tree": 100}), ("tree 300 -> 100",)),
        ("a collapse in the golf-feature total", "ALLOW_STRUCTURAL_SHRINK",
         against(rings, {"green": 9}), ("9", "120")),
    )


def test_an_explicit_off_does_not_waive_an_osm_shrink_guard(tmp_path):
    """`ALLOW_HAZARD_SHRINK=0` waived the hazard-loss guard, and so did `=false` and `=no`.

    This is the discriminating red. The four keys were read as `not os.environ.get("ALLOW_X")`, and
    every off-spelling except the empty string is a truthy string. Reproduced against the reply that
    loses one bunker of 36 -- the smallest hazard loss this corpus can suffer, and 36 bunkers is
    castlewood-hill's real count:

        ALLOW_HAZARD_SHRINK unset     ABORT   (correct)
        ALLOW_HAZARD_SHRINK=1         accept  (correct)
        ALLOW_HAZARD_SHRINK=true      accept  (correct)
        ALLOW_HAZARD_SHRINK=yes       accept  (correct)
        ALLOW_HAZARD_SHRINK=0         accept  <-- the defect
        ALLOW_HAZARD_SHRINK=false     accept  <-- the defect
        ALLOW_HAZARD_SHRINK=no        accept  <-- the defect
        ALLOW_HAZARD_SHRINK=""        ABORT   (correct only by accident: "" is the one off-spelling
                                              that is also falsy)

    Driven over all four read sites, not just the hazard one, and with the empty string kept in the
    table on purpose -- it passed before the fix for a reason that does not generalise, so dropping it
    would leave the one value that agreed with the fix ungraded.

    A KEY MUST ALSO NOT ANSWER FOR ANOTHER KEY'S CHECK, which is why every other ALLOW_* is cleared
    around each row: three of the five sites read a different key than their neighbour, and a table
    that left them set could not tell "the key waived it" from "some key waived it".
    """
    fo = _osm()
    for label, key, run, _ in _cases(tmp_path, fo):
        with _only():
            with pytest.raises(SystemExit) as ei:
                run()
            assert key in str(ei.value), (
                "%s: the abort must name the key that waives it, or a reader cannot answer it: %s"
                % (label, ei.value))
        for raw in OFF_VALUES:
            with _only(**{key: raw}):
                with pytest.raises(SystemExit, match=re.escape(key)) as ei:
                    run()
                assert key in str(ei.value), (label, raw, str(ei.value))
        for raw in ON_VALUES:
            with _only(**{key: raw}):
                with contextlib.redirect_stdout(io.StringIO()):
                    run()           # a deliberate, affirmative waiver still has to work


def _square(gid, lat, lon, side=0.0002):
    """A green polygon, as Overpass returns one: a closed ring with `out geom`."""
    ring = [(lat, lon), (lat + side, lon), (lat + side, lon + side), (lat, lon + side), (lat, lon)]
    return {"type": "way", "id": gid, "tags": {"golf": "green"},
            "geometry": [{"lat": a, "lon": b} for a, b in ring]}


def _centreline(wid, ref, green_lat, green_lon, side=0.0002):
    """A hole centreline whose GREEN end sits on that green and whose tee end is ~1 km away."""
    return {"type": "way", "id": wid, "tags": {"golf": "hole", "ref": str(ref)},
            "geometry": [{"lat": green_lat + 0.010, "lon": green_lon},
                         {"lat": green_lat + side / 2, "lon": green_lon + side / 2}]}


def test_an_explicit_off_does_not_waive_the_rebind_guard():
    """ALLOW_REBIND had the same inversion with the opposite polarity, and no test of any kind.

    Its read was `if not prev or os.environ.get("ALLOW_REBIND"): return` -- an early return rather than
    an `and not`, so the truthy-string fault reaches the same outcome by the other route: `=0` returns
    before the comparison is made and the rebind is accepted in silence. Grep of tests/ on the tree this
    file was written against: ALLOW_REBIND appeared in exactly one line, a list of keys another test
    clears, and nothing anywhere exercised it.

    What it waives is the check `_check_bindings` exists for. `geo.assert_one_green_per_hole` misses the
    case where the extract holds MORE greens than the course has holes -- measured at monarch-bay,
    callippe and the-reserve -- so the only thing that sees those rebinds is the comparison against the
    cache about to be replaced. 47 of this corpus's 198 holes have a neighbour's green within
    GREEN_BIND_MAX_M of their tee end, so a rebind is what a truncated reply looks like from outside.

    The fixture is the honest shape of the case the key is FOR: OSM redraws one green under a new id, so
    hole 1 binds to green 502 where the cache had 501.
    """
    fo = _osm()
    lat, lon = 37.70, -121.90
    hole = _centreline(701, 1, lat, lon)
    prev = [_square(501, lat, lon), hole]
    new = [_square(502, lat, lon), hole]

    # the fixture has to actually REBIND, or this test grades nothing
    assert (fo._bindings(prev, "osm_geom.json")[1]["id"] == 501
            and fo._bindings(new, "osm_geom.json")[1]["id"] == 502), (
        "the fixture no longer moves hole 1 from green 501 to green 502, so the rebind guard is not "
        "reached and nothing below is a measurement")

    with _only():
        fo._check_bindings(new, "osm_geom.json", prev=())        # no baseline -> nothing to compare
        fo._check_bindings(prev, "osm_geom.json", prev=prev)     # unchanged binding -> silent
        with pytest.raises(SystemExit, match="ALLOW_REBIND") as ei:
            fo._check_bindings(new, "osm_geom.json", prev=prev)
        assert "501" in str(ei.value) and "502" in str(ei.value), (
            "the rebind abort must name the greens it moved between: %s" % ei.value)
    for raw in OFF_VALUES:
        with _only(ALLOW_REBIND=raw):
            with pytest.raises(SystemExit, match="ALLOW_REBIND"):
                fo._check_bindings(new, "osm_geom.json", prev=prev)
    for raw in ON_VALUES:
        with _only(ALLOW_REBIND=raw):
            with contextlib.redirect_stdout(io.StringIO()):
                fo._check_bindings(new, "osm_geom.json", prev=prev)

    # ...and no other key grants it: a waiver spent on a drained pond must not accept a card rebinding
    # to the wrong putting surface.
    for other in ("ALLOW_SHRINK", "ALLOW_HAZARD_SHRINK", "ALLOW_STRUCTURAL_SHRINK"):
        with _only(**{other: "1"}):
            with pytest.raises(SystemExit, match="ALLOW_REBIND"):
                fo._check_bindings(new, "osm_geom.json", prev=prev)


def test_a_spent_osm_waiver_names_what_it_accepted(tmp_path):
    """These four were the only keys of the thirteen that printed nothing when they were spent.

    The convention is written down in the code they were meant to match: `fetch_trees.check_layer`
    prints "WARNING: ALLOW_TREE_LOSS set -- hole(s) 4, 11 lose every marker they had",
    `lidar_coverage.report_or_exit` and `fetch_hole_elev` the same shape, `render_hole` a NOTE. A waiver
    changes the exit code and never hides the finding, because the finding is the only record: the
    reply lands in `courses/<slug>/osm_course.json`, which is gitignored, so once it is written there is
    nothing left to compare against. That is not hypothetical here -- febbbba re-fetched four courses
    and its pre-fetch caches exist nowhere, which is why fetch_osm.py carries a note calling its own
    zero-drift claim unverifiable.

    Reproduced before the fix: with ALLOW_HAZARD_SHRINK=1 and a reply that dropped a bunker,
    `_check_response` returned having printed the empty string. So the COUNTS are required here, not
    just the key name -- "a hazard loss was accepted" tells a reader nothing they can act on, while
    "bunker 36 -> 35" tells them which ink left the card.
    """
    fo = _osm()
    for label, key, run, wants in _cases(tmp_path, fo):
        with _only(**{key: "1"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run()
            said = buf.getvalue()
        assert said.strip(), (
            "%s: %s=1 accepted the loss and printed NOTHING. Every other ALLOW_* key in this project "
            "names what it accepted; the cache this one waived into is gitignored, so its own output is "
            "the only record that the loss happened." % (label, key))
        assert key in said, (
            "%s: the acknowledgement does not name the key that granted it (%r) -- a reader cannot tell "
            "which of the four waivers was spent" % (label, said))
        for want in wants:
            assert want in said, (
                "%s: the acknowledgement does not name the loss itself (%r is not in %r). A generic "
                "sentence cannot tell a reader which ink left the card." % (label, want, said))

    # the rebind waiver, whose finding is which hole moved to which green
    lat, lon = 37.70, -121.90
    hole = _centreline(701, 1, lat, lon)
    prev, new = [_square(501, lat, lon), hole], [_square(502, lat, lon), hole]
    with _only(ALLOW_REBIND="1"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fo._check_bindings(new, "osm_geom.json", prev=prev)
        said = buf.getvalue()
    assert said.strip(), (
        "ALLOW_REBIND=1 accepted a hole binding to a different green and printed NOTHING -- the one "
        "waiver in this module whose finding is 'the card may now show the wrong putting surface'")
    assert "ALLOW_REBIND" in said, said
    for want in ("1", "501", "502"):
        assert want in said, (
            "the rebind acknowledgement does not name the hole and the greens it moved between "
            "(%r is not in %r)" % (want, said))


def _env_reads(path):
    """[(key, lineno)] for every `os.environ.get("ALLOW_...")` in `path`, found by AST.

    By AST and not by grep, because this repo's house style is to quote the very name a guard checks
    for in the prose beside it -- and the fix for this defect had to write `os.environ.get("ALLOW_X")`
    into a comment to say what the old code did. A regex over the source text is satisfied by that
    comment, which is the failure mode `_code_only` exists for in test_phase1_regressions and
    `_course_restoring_autouse_fixtures` walks the tree for in test_r14_export. Neither a comment nor a
    docstring is a Call node, so neither can answer this question.
    """
    import ast
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and "environ" in ast.unparse(n.func.value)):
            continue
        if n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str) and n.args[0].value.startswith("ALLOW_"):
            out.append((n.args[0].value, n.lineno))
    return out


def test_fetch_osm_reads_its_acknowledgement_keys_through_the_shared_env_on():
    """One spelling of "off", imported rather than re-written -- the rule the rest of the repo follows.

    Two halves, and both were false here. `fetch_osm.py` contained zero uses of `_env_on` and five bare
    `os.environ.get("ALLOW_...")` reads; and the obvious local fix -- copy the helper in -- would have
    made an EIGHTH hand-written copy of the same off-vocabulary in this repo. Seven already existed when
    `tools/verify_elevation.py` set the other precedent by importing lidar_coverage's, and the reason is
    recorded there: narrowing one copy's tuple to ("", "0") turns ALLOW_X=false back into a waiver and
    left the whole suite green when it was tried.

    So this pins the shape, not the string: no bare environment read of an ALLOW_ key survives in the
    module, and the helper it uses is the SAME OBJECT lidar_coverage defines. Identity is the assertion
    that matters -- a re-spelled copy would satisfy any behavioural table written here while still being
    a copy that can drift.

    The import is safe in this direction and that is checked rather than assumed: `lidar_coverage`
    imports only the standard library and `geo`, so it cannot reach back to `fetch_osm`, `config` or
    `render_hole`, and it deliberately imports where laspy and numpy are absent.
    """
    import ast

    fo = _osm()
    import lidar_coverage

    path = os.path.join(ROOT, "fetch_osm.py")
    bare = _env_reads(path)
    assert not bare, (
        "fetch_osm.py reads %d acknowledgement key(s) for bare truthiness again: %s. A non-empty string "
        "is truthy, so ALLOW_X=0 / =false / =no WAIVE the guard they name -- and this module's guards "
        "are the ones standing between a re-fetch and a lost bunker or creek." % (len(bare), bare))
    with open(path, encoding="utf-8") as fh:
        defines = [n.name for n in ast.walk(ast.parse(fh.read())) if isinstance(n, ast.FunctionDef)]
    assert "_env_on" not in defines, (
        "fetch_osm.py now defines its own _env_on. Eight hand-written copies of one off-vocabulary is "
        "how a narrowed tuple turns an explicit 'off' into a waiver in one module and nowhere else -- "
        "import lidar_coverage's, as tools/verify_elevation.py does.")
    assert getattr(fo, "_env_on", None) is lidar_coverage._env_on, (
        "fetch_osm._env_on is not lidar_coverage._env_on, so the two spellings of 'off' can drift apart")

    # the import cannot be a cycle: nothing lidar_coverage imports at module scope can reach back here
    with open(os.path.join(ROOT, "lidar_coverage.py"), encoding="utf-8") as fh:
        lc = ast.parse(fh.read())
    top = {a.name.split(".")[0] for n in lc.body if isinstance(n, ast.Import) for a in n.names}
    top |= {(n.module or "").split(".")[0] for n in lc.body if isinstance(n, ast.ImportFrom)}
    for reachable in ("fetch_osm", "render_hole", "config"):
        assert reachable not in top, (
            "lidar_coverage now imports %s at module scope, which closes a cycle with fetch_osm's "
            "import of _env_on -- move the helper to a module below both of them" % reachable)


def _module_level_holders(module):
    """Engine modules that hold a reference to `module` AT IMPORT TIME, read off the engine's source.

    Module level only. `import x` inside a function binds a name at call time and re-resolves out of
    sys.modules on every call, so it cannot be the stale holder this file's guard is about; a
    module-level `from x import y` copies the object once, for the life of the process.
    """
    import ast

    out = []
    for rel in sorted(glob.glob(os.path.join(ROOT, "*.py"))
                      + glob.glob(os.path.join(ROOT, "tools", "*.py"))):
        with open(rel, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=rel)
        for node in tree.body:
            hit = ((isinstance(node, ast.Import) and any(a.name == module for a in node.names))
                   or (isinstance(node, ast.ImportFrom) and not node.level and node.module == module))
            if hit and os.path.basename(rel) != module + ".py":
                out.append("%s:%d" % (os.path.relpath(rel, ROOT), node.lineno))
    return out


def _sys_modules_pop_names(path):
    """Every module name `path` drops from sys.modules, resolved through an enclosing `for m in (...)`.

    By AST for `_env_reads`' reason, and here it is not a nicety: this file's prose NAMES the idiom it
    does not use, so a regex over the source text finds a drop site in a docstring. Neither a comment
    nor a docstring is a Call node.
    """
    import ast

    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "pop"
                and ast.unparse(n.func.value).replace(" ", "") == "sys.modules"):
            continue
        arg = n.args[0] if n.args else None
        if isinstance(arg, ast.Constant):
            found.append((n.lineno, [arg.value]))
            continue
        names, p = [ast.unparse(arg) if arg is not None else "?"], n
        while p in parents:                     # walk out to the `for` that supplies the loop variable
            p = parents[p]
            if isinstance(p, ast.For) and isinstance(p.target, ast.Name) \
                    and isinstance(arg, ast.Name) and p.target.id == arg.id:
                # A literal iterable is resolved to the names themselves; a named one (the sibling
                # modules' `_COURSE_MODULES`) is reported as the expression, because the point here is
                # to name the drop site for a reader, not to constant-fold another file's list.
                names = ([e.value for e in p.iter.elts if isinstance(e, ast.Constant)]
                         if isinstance(p.iter, (ast.Tuple, ast.List, ast.Set))
                         else ["<%s>" % ast.unparse(p.iter)])
                break
        found.append((n.lineno, names))
    return found


def test_this_file_drops_no_module_from_sys_modules():
    """The ABSENCE of the drop idiom here is load-bearing, so it is pinned rather than trusted.

    `_osm()`'s docstring gives two reasons for it: the figure README publishes is counted across
    `tests/*.py`, and nothing here needs a re-import. There is a third and sharper one, and it cost a
    real order-dependent failure next door rather than in this file. `fetch_osm.py` holds
    `from lidar_coverage import _env_on` AT MODULE LEVEL. Dropping `lidar_coverage` while `fetch_osm`
    stays resident therefore leaves the holder bound to the old function and hands the next
    `import lidar_coverage` a SECOND copy of the file -- at which point
    test_fetch_osm_reads_its_acknowledgement_keys_through_the_shared_env_on stops asking whether
    fetch_osm imports the shared helper and starts comparing two copies of one function. That is exactly
    what tests/test_r14_coverage.py's fixture did until this round, and it is why this file, whose whole
    subject is that identity, may not reach for the idiom itself.

    THE HOLDER EDGE IS MEASURED, not asserted: an unmeasured premise is how this class hides. If
    fetch_osm ever stops importing the helper at module level this test says so, which is the only
    condition under which the hazard would not exist.

    The general rule -- a name may be dropped only if importing it reaches the COURSE env var, itself or
    through a chain of module-level sibling imports -- is graded on the lists that HAVE one, in
    tests/test_r14_coverage.py and tests/test_r14_deadcode.py. This file's list is empty; this keeps it
    that way, and a drop that really is needed here has to be argued against that rule and against
    README's count, not typed in.
    """
    holders = _module_level_holders("lidar_coverage")
    assert "fetch_osm.py:39" in holders or any(h.startswith("fetch_osm.py:") for h in holders), (
        "fetch_osm.py no longer imports lidar_coverage at module level, so the premise of this test is "
        "gone -- and so, probably, is the shared `_env_on` that "
        "test_fetch_osm_reads_its_acknowledgement_keys_through_the_shared_env_on grades. Holders "
        "found: %s" % (holders,))
    dropped = _sys_modules_pop_names(os.path.abspath(__file__))
    assert not dropped, (
        "this file now drops %d module(s) from sys.modules: %s. Every module in this repo that reads "
        "COURSE at import is already dropped for every test in this directory by tests/conftest.py, so "
        "a drop here buys no isolation this file needs -- and dropping `lidar_coverage`, which reads no "
        "COURSE at all, forks the very function this file asserts fetch_osm shares with it (see this "
        "test's docstring). It also moves the count README publishes over tests/*.py."
        % (len(dropped), dropped))


def test_every_osm_acknowledgement_key_is_documented_in_the_pipeline():
    """The recipe has to name every key a reader might have to set, and describe it as it now behaves.

    PIPELINE.md step 3 is where an operator meets these four. It named them from 12fb943 onward; what it
    could not say before this round is that a spent waiver reports itself and that an explicit off does
    not waive -- the two properties that make "set it deliberately" an auditable instruction rather than
    a silent one.

    The off-vocabulary the document publishes is checked AGAINST THE PARSE, not taken on trust. A recipe
    that tells an operator `=0` disables a waiver is a promise, and the way that promise broke here was
    the code changing under it -- so every spelling the document names is driven through the helper the
    module actually reads.
    """
    with open(os.path.join(ROOT, "PIPELINE.md"), encoding="utf-8") as fh:
        doc = fh.read()
    for key in OSM_ACKS:
        assert key in doc, (
            "PIPELINE.md does not name %s, so an operator meets it for the first time in an abort "
            "message" % key)
    with open(os.path.join(ROOT, "fetch_osm.py"), encoding="utf-8") as fh:
        src = fh.read()
    # A string-literal scan is the right check for message TEXT (a comment here would be a false alarm,
    # never a false pass) -- and the runtime side of this claim is graded in
    # test_a_spent_osm_waiver_names_what_it_accepted, which reads what the waivers actually print.
    for key in OSM_ACKS:
        assert re.search(r"WARNING:[^\"']*%s" % key, src), (
            "fetch_osm.py has no WARNING naming %s, so spending it leaves no trace in the build's own "
            "output" % key)

    fo = _osm()
    named_off = [v for v in ("0", "false", "no") if "`=%s`" % v in doc]
    assert len(named_off) == 3, (
        "PIPELINE.md step 3 no longer publishes the off-vocabulary for these keys (%s of 0/false/no). "
        "An operator who does not know that `=0` means off is one keystroke from waiving the hazard "
        "guard by trying to disarm it, which is the defect this round fixed." % (named_off,))
    for raw in named_off:
        for key in OSM_ACKS:
            with _only(**{key: raw}):
                assert fo._env_on(key) is False, (
                    "PIPELINE.md tells an operator %s=%s is OFF and the module reads it as ON" % (key, raw))
