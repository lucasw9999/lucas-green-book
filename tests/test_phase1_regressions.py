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
import collections.abc
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


def _dist_to_poly(pt, poly, em):
    """Metres from a projected point to a polygon: 0 inside, else nearest edge. Written here rather
    than imported so the test's model choice does not lean on the engine's own geometry code."""
    P = [em(p["lat"], p["lon"]) for p in (poly.get("geometry") or [])]
    if not P:
        return 1e9
    x, y = pt
    inside = False
    for i in range(len(P)):
        x1, y1 = P[i]
        x2, y2 = P[(i + 1) % len(P)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-12):
            inside = not inside
    if inside:
        return 0.0
    best = 1e18
    for i in range(len(P)):
        x1, y1 = P[i]
        x2, y2 = P[(i + 1) % len(P)]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


CORPUS = _courses()


def _books():
    """Slugs with a BUILT BOOK, whether or not they have OSM geometry.

    CORPUS requires osm_geom.json + osm_course.json because the hole maps cannot be rendered without
    them. poppy-ridge has neither: it is yardage mode, built from the scorecard alone with blank
    greens and a separate aerial. That is correct for geometry tests and wrong for every test that
    only reads the shipped HTML -- so its 18 cards, its scorecard panel and its legal text were
    outside the reach of EVERY corpus test in this file. The one book least like the others was the
    one nothing checked.
    """
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        if os.path.exists(os.path.join(ROOT, "courses", slug, "greenbook.html")):
            out.append(slug)
    return out


BOOKS = _books()


_EXPECTED_GEOM_HOLES = None


def geometry_courses():
    """The SET of slugs with geometry on disk. Filesystem-derived, independent of CORPUS."""
    out = set()
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        d = os.path.join(ROOT, "courses", slug)
        if all(os.path.exists(os.path.join(d, f))
               for f in ("osm_geom.json", "osm_course.json")):
            out.add(slug)
    return out


def _code_only(src):
    """`src` with comments and string literals removed, so a source assertion cannot be satisfied by prose.

    This codebase deliberately writes long explanatory comments that quote the very names its guards
    check for, and that has defeated four separate assertions in this suite: two of them are satisfied
    today by a comment in production source, proven by mutation --

      * fetch_dem.py:155 reads "# assert_one_green_per_hole compared nothing.", which satisfies the
        check that fetch_dem CALLS it, so deleting the live call at :161 left the test green;
      * fetch_dem.py:130 names keeps_existing_surface in a comment, so replacing the live
        `if keeps_existing_surface(...)` with `if False:` left its test green.

    Tokenising is the only reliable fix: a grep cannot tell code from a comment about code, and asking
    people to stop explaining themselves is the wrong trade in a codebase whose comments are its best
    feature.
    """
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        # RAISE, do not fall back. Returning the raw source here was itself an instance of the fault
        # this helper exists to prevent, and it defeated a real guard: splitting a module on
        # "def main(" yields a fragment starting "):\n    ..." which does not tokenise, so this
        # returned the source WITH comments and a check that fetch_dem_hd.main() still calls
        # keeps_existing_surface was satisfied by a comment naming that function. Replacing the live
        # call with `if False:` left the test green. A silent fallback in a guard-hardening helper is
        # worse than no helper, because the call site reads as protected.
        raise AssertionError(
            "_code_only() was handed source that does not tokenise, so it cannot strip comments and "
            "the caller's assertion would be checking prose. Pass a whole module, or a fragment that "
            "parses on its own (dedent it, or re-attach a synthetic header). First 60 chars: "
            f"{src[:60]!r}")
    return " ".join(out)


def _elev_rows(slug):
    """{hole: record} from a course's hole_elev.json, {} when the stage was not run."""
    fp = os.path.join(ROOT, "courses", slug, "hole_elev.json")
    if not os.path.isfile(fp):
        return {}
    try:
        with open(fp, encoding="utf-8") as fh:
            return json.load(fh).get("holes") or {}
    except Exception:
        return {}


def assert_no_course_skipped(seen, what, exempt=None):
    """Every course with geometry must have CONTRIBUTED something -- not merely been visited.

    A COUNT floor cannot express this. Derived from CORPUS it falls with the count, so dropping a
    course keeps the test green; derived from the filesystem with a one-course slack it still keeps
    it green, because the slack is exactly the thing being lost. Both were tried and both passed a
    mutation that hid valley-hi inside _courses(). Per-item totals vary legitimately (a green too
    shallow for three ladder rungs, a hole with no from-tee number), but a course contributing
    NOTHING is always a skip.

    IT TOOK A SET, AND A SET CANNOT TELL THE DIFFERENCE. Twelve of the call sites did
    `for ref in CORPUS: seen.add(ref)` at the TOP of the loop, which records intent, not work -- and
    two of them iterated geometry_courses() itself, making the assertion literally `not (X - X)`,
    unfalsifiable by any change to the code under test. Proven by mutation: making two such tests
    `continue` immediately after the add, so the course contributed nothing at all, left them green.

    So it takes a MAPPING of course -> how many things that course contributed, and a count cannot be
    incremented without something to count. The right place for the increment is beside the per-item
    counter each of these tests already keeps, past whatever gate can legitimately skip an item.
    """
    if not isinstance(seen, collections.abc.Mapping):
        raise TypeError(
            f"{what}: pass a MAPPING of course -> contribution count, not a {type(seen).__name__}. A set "
            f"records only that the loop reached a course, which is what let twelve call sites assert "
            f"nothing at all -- see this function's docstring. Use collections.Counter() and increment "
            f"beside the per-item counter, past the gates that may legitimately skip an item.")
    contributed = {k for k, v in seen.items() if v}
    # `exempt` is {slug: why} for courses that legitimately contribute NOTHING to this particular
    # test -- a course printing no carry at all cannot contribute to a carry test. It must be spelled
    # with a reason, so that a course going quiet for a BAD reason still fails. The alternative that
    # was in use -- incrementing at the top of the loop so every course looks like a contributor --
    # exempts all twelve silently, which is how a whole 18-hole course could drop out unnoticed.
    exempt = exempt or {}
    assert not (set(exempt) - geometry_courses()), (
        f"{what}: exemption names a course with no geometry: {sorted(set(exempt) - geometry_courses())}")
    for slug, why in exempt.items():
        assert isinstance(why, str) and len(why) > 12, (
            f"{what}: exemption for {slug} needs a real reason, got {why!r}")
    stale = sorted(s for s in exempt if seen.get(s))
    assert not stale, (f"{what}: {stale} is exempted but DID contribute -- drop the exemption rather "
                       f"than leave a stale one that would hide a real skip later")
    missing = sorted(geometry_courses() - contributed - set(exempt))
    assert not missing, (f"{what}: these courses have geometry on disk but contributed nothing -- "
                         f"they are being skipped: {missing}")


def expected_geometry_holes():
    """Holes across every course that HAS geometry on disk -- computed from the filesystem, never
    from CORPUS.

    This distinction is the whole point. expected_holes() sums over CORPUS, so if a course silently
    drops OUT of CORPUS the floor falls with the count and the test still passes -- which is exactly
    how poppy-ridge stayed invisible. Verified by mutation: hiding valley-hi inside _courses() left
    all 164 tests green while a CORPUS-derived floor was in place, and fails here.

    Still derived, so it scales for someone who has built two courses instead of twelve. It counts
    what is on disk, not what this machine happens to have.
    """
    global _EXPECTED_GEOM_HOLES
    if _EXPECTED_GEOM_HOLES is None:
        n = 0
        for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
            slug = os.path.basename(os.path.dirname(cj))
            if slug.startswith("_"):
                continue
            d = os.path.join(ROOT, "courses", slug)
            if not all(os.path.exists(os.path.join(d, f))
                       for f in ("osm_geom.json", "osm_course.json")):
                continue
            with open(cj, encoding="utf-8") as fh:
                n += len(json.load(fh).get("holes") or {})
        _EXPECTED_GEOM_HOLES = n
    return _EXPECTED_GEOM_HOLES


def _expected_cards():
    """How many hole cards the built books SHOULD have, from the files themselves.

    Derived, never hardcoded: an absolute floor punishes anyone who has built two courses instead of
    twelve, which is the same defect as the fresh-clone failures. But it must be derived from what is
    PRESENT rather than from what a loop happens to visit, or a skipped course lowers the bar it was
    supposed to trip."""
    n = 0
    for slug in BOOKS:
        with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as fh:
            n += len(json.load(fh).get("holes") or {})
    return n
needs_corpus = pytest.mark.skipif(not CORPUS, reason="per-course data is gitignored; nothing to measure")


@pytest.fixture(scope="session", autouse=True)
def _courses_are_read_only():
    """The suite must not write inside courses/. That data cannot be got back.

    A course folder holds ~300 MB of LiDAR tiles, the derived 0.4 m surfaces, and the hand-verified
    scorecard in course.json. It is gitignored by design -- so there is no copy in history, no copy on a
    remote, and a test that truncates or deletes one has destroyed work that took a network fetch and a
    manual cross-check to produce. Rebuilding a green surface is hours; re-verifying a scorecard against
    club sources is worse.

    Nothing in the suite writes there today. This is here so that stays true by accident-detection rather
    than by everyone remembering: a fixture that builds a course under courses/ instead of tmp_path would
    be a natural thing to write, and would look fine until the day it picked a real slug.

    Session-scoped, comparing the set of paths and the mtime of every course.json and book, so it costs
    one directory walk per run rather than one per test.
    """
    def snap():
        out = {}
        for p in glob.glob(os.path.join(ROOT, "courses", "*", "*")):
            base = os.path.basename(p)
            if base.endswith(".json") or base.startswith("greenbook") or base.endswith(".pdf"):
                try:
                    out[os.path.relpath(p, ROOT)] = os.path.getmtime(p)
                except OSError:
                    pass
        return out

    before = snap()
    yield
    after = snap()
    vanished = sorted(set(before) - set(after))
    touched = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    assert not vanished, (
        f"the test run DELETED files under courses/, which is gitignored and has no copy anywhere: "
        f"{vanished[:5]}")
    assert not touched, (
        f"the test run modified files under courses/: {touched[:5]}. Course data and built books are "
        f"inputs to the suite, not scratch space -- write to tmp_path instead.")


@pytest.fixture(autouse=True)
def _no_network(request):
    """Block outbound sockets unless a test says @pytest.mark.network.

    What this actually blocks: socket.socket.connect and socket.create_connection, which is the path
    urllib, requests and http.client all take -- so it catches the realistic accident, a test quietly
    reaching a live service. It is NOT a sandbox. Playwright's two Rule 4.3 tests launch Chromium
    in-process and still pass with the guard on, because that IPC does not go through connect(); an
    already-open socket or a raw sendto would slip past too. Stated plainly so nobody reads a green
    suite here as proof of hermeticity beyond what is checked.

    The suite is hermetic today -- verified by running all 164 with socket.connect blocked -- and that
    is a property worth keeping rather than rediscovering. A test that quietly reaches a live service is
    slow, fails offline, fails on a fresh clone, and fails differently depending on whose machine it is,
    which is the opposite of what a regression suite is for. The two tests that exercise network FAILURE
    paths already fake urlopen; their 8 s and 4 s are real retry backoff, not real traffic.

    The cold build is the one legitimate exception: it re-fetches ~300 MB of LiDAR on purpose. It is
    marked, and skipped unless COLD_BUILD=1 anyway.
    """
    if request.node.get_closest_marker("network"):
        yield
        return
    import socket
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def blocked(self, address, *a, **k):
        raise RuntimeError(
            f"this test opened a network connection to {address!r}. The suite is meant to run "
            f"offline and on a fresh clone; fake the transport, or mark the test @pytest.mark.network "
            f"if it genuinely needs the wire.")

    socket.socket.connect = blocked
    socket.create_connection = lambda *a, **k: blocked(None, a[0] if a else None)
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.create_connection = real_create


@pytest.fixture(autouse=True)
def _bind_a_course():
    """Bind COURSE for every test.

    Nine test sites import render_green or config without binding COURSE, so they inherited whatever
    an earlier test left -- or, run singly, config.py's hardcoded default. That default happens to be
    built on this machine, so the crash was invisible here: on a tree without
    the-reserve-at-spanos-park, `pytest -k contours_join` died with SystemExit and looked like a real
    defect. Binding it here makes single-test and randomised-order runs behave like a full run.

    It now also RESTORES the binding afterwards, so every test starts from the same course whatever the
    one before it did. Binding without restoring left the suite order-dependent by construction: 69
    sites in this file rebind COURSE and pop config/render_* out of sys.modules, so a test that ends
    bound to a 5-tee course silently reconfigured the next one. That is not hypothetical -- running the
    suite shuffled found a real IndexError in render_hole where a synthetic 2-tee fixture inherited a
    5-tee binding, a bug production could not reach. File order and reverse order were both green.

    Restoring here makes the isolation structural rather than something to remember. Verified after the
    change: file order, reverse order, three shuffle seeds, and all 164 tests each in their own process.
    """
    prev = os.environ.get("COURSE")
    # UNCONDITIONAL when there is a corpus. `if CORPUS and not prev` meant the binding was skipped
    # whenever COURSE was already set -- which defeated the isolation this fixture's docstring promises,
    # because the module-scoped synth_engine fixture is set up BEFORE any function-scoped fixture and
    # binds COURSE=_synth_ticks during its own setup. Every test from the first synthetic one to the end
    # of the session then saw prev="_synth_ticks", declined to rebind, and RESTORED it on teardown -- so
    # the whole tail of the suite silently ran against a 2-hole, 1-tee authored course. That is what made
    # three green tests fail in a full run and pass in isolation, and what turned the fixture's cleanup
    # into a landmine: the moment courses/_synth_ticks stops existing, every later `import config` dies
    # with "no course.json for COURSE='_synth_ticks'".
    #
    # Safe for the synthetic tests themselves: _engine(slug) hands back modules ALREADY imported against
    # their course, so rebinding the env afterwards cannot reach them.
    if CORPUS:
        os.environ["COURSE"] = CORPUS[0]
    try:
        yield
    finally:
        # back to what this test started with, and drop the course-bound modules so the next import
        # re-reads the env rather than reusing a module bound to someone else's course
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
        for m in ("config", "render_hole", "render_green", "geo",
                  "fetch_trees", "fetch_hole_elev", "fetch_dem", "fetch_dem_hd"):
            sys.modules.pop(m, None)


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
def test_the_course_template_documents_every_key_the_engine_reads():
    """examples/course.json is the ONLY course data this repo ships, and a stranger's whole map of

    the format. courses/ is gitignored, so nobody outside can look at a real one to see what a field
    should contain -- the template is it. A key the engine reads but the template never mentions is
    therefore invisible: you find out it existed when a build behaves oddly, or never.

    It had drifted. `dem_source` is carried by 11 of the 12 real courses and read in 8 places, and
    the template did not mention it. `greens_outdated_basis` is REQUIRED whenever
    greens_possibly_outdated is set -- a test enforces exactly that -- and the template documented
    the trigger without the obligation, so following it landed you on a failing suite.

    The template documents a key either by carrying it or by describing it under a leading
    underscore, which is its own convention for "optional, here is what it means". Both count.
    """
    p = os.path.join(ROOT, "examples", "course.json")
    if not os.path.exists(p):
        pytest.skip("no examples/course.json")
    with open(p, encoding="utf-8") as fh:
        ex = json.load(fh)
    known = {k.lstrip("_") for k in ex}

    # what the engine actually asks a course.json for
    reads = set()
    for f in (sorted(glob.glob(os.path.join(ROOT, "*.py")))
              + sorted(glob.glob(os.path.join(ROOT, "tools", "*.py")))):
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        reads |= set(re.findall(r'COURSE\.get\(["\'](\w+)["\']', src))
        reads |= set(re.findall(r'COURSE\[["\'](\w+)["\']\]', src))
    # keys that exist only to be written by a fetch stage, not authored by a person
    DERIVED = {"lidar", "lidar_project"}
    undocumented = sorted(k for k in reads - known - DERIVED)
    assert not undocumented, (
        "the engine reads these course.json keys but examples/course.json neither carries nor "
        "documents them, so nobody outside this machine can learn they exist:\n  "
        + "\n  ".join(undocumented))



@needs_corpus
def test_no_real_course_carries_a_key_the_template_never_mentions():
    """The other direction: a field in use locally must be described in the shipped template.

    This is how `dem_source` went missing -- 11 of 12 courses carry it, the engine reads it in 8
    places, and a stranger had no way to learn it exists. Separate from the engine-side check
    because it reads the gitignored corpus and must skip without it, while the engine-side half has
    to run on a fresh clone, which is precisely where it matters.
    """
    p = os.path.join(ROOT, "examples", "course.json")
    if not os.path.exists(p):
        pytest.skip("no examples/course.json")
    with open(p, encoding="utf-8") as fh:
        known = {k.lstrip("_") for k in json.load(fh)}
    DERIVED = {"lidar", "lidar_project"}     # written by a fetch stage, never authored by hand
    missing, checked = [], 0
    for slug in CORPUS:
        cj = os.path.join(ROOT, "courses", slug, "course.json")
        if not os.path.exists(cj):
            continue
        checked += 1
        with open(cj, encoding="utf-8") as fh:
            for k in json.load(fh):
                if k.lstrip("_") not in known and k.lstrip("_") not in DERIVED:
                    missing.append(f"{k} (in {slug})")
    assert checked >= 5, f"only {checked} course.json files examined"
    assert not missing, ("real courses carry keys the template never mentions:\n  "
                         + "\n  ".join(sorted(set(missing))))


def test_a_missing_required_key_names_itself():
    """A newcomer's first course.json will be wrong somehow. The error has to say how.

    config indexes four keys with no sensible default -- name, address, hole_cols, holes -- and used to
    index them bare. Deleting "holes", which is the single likeliest mistake when copying
    examples/course.json and renaming a block, produced `KeyError: 'holes'` and a traceback: no file
    named, no field described, no next step. That is the moment a stranger gives up, and it is the
    cheapest possible thing to fix.

    Checked as a property of the message, not just of the exit code: it must name the file, name every
    missing key rather than one per run, and point at the template. Reporting them one at a time turns
    four mistakes into four rounds of guessing.
    """
    src = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    assert "_REQUIRED" in src and "is missing" in src, \
        "config.py no longer names its required keys before indexing them"
    for key in ("name", "address", "hole_cols", "holes"):
        assert f'"{key}"' in src.split("_REQUIRED")[1].split("_missing")[0], \
            f"{key} is indexed by config.py but not covered by the required-key guard"
    guard = src.split("_missing = ")[1].split("# hole ->")[0]
    assert "for k in _REQUIRED if k not in COURSE" in guard, \
        "the guard must collect ALL missing keys, not stop at the first"
    assert "examples/course.json" in guard, \
        "the message must point at the documented template"


def test_a_null_tee_preference_is_not_a_crash():
    """`"secondary_tee": null` means "no preference", not "index the list with None".

    dict.get returns its default only when the key is ABSENT. A course.json carrying the key with an
    explicit null -- which is exactly how the-reserve-at-spanos-park was written -- got None, and
    TEES.index(None) raised ValueError. The whole build died on a file that is valid JSON saying
    nothing unusual. A null and a missing key mean the same thing here, so they behave the same.

    A tee NAME that is not a column is the opposite case and must be loud: silently defaulting a
    typo would build the entire book on the wrong tee.
    """
    src = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    assert 'COURSE.get("featured_tee") or' in src and 'COURSE.get("secondary_tee") or' in src, \
        "a present-but-null tee preference must fall back, not become None"
    assert "is not one of this course's tee columns" in src, \
        "a tee name that is not a scorecard column must be refused, not silently mis-indexed"


@needs_corpus
def test_the_course_location_decides_hole_lines_by_a_wide_margin():
    """course.json "location" is now load-bearing, so measure how much room it has to be wrong.

    geo.hole_lines resolves duplicate OSM ways for one hole number by distance to the stated course
    centre, and refuses under a 150 m margin rather than guess. Three more stages were moved onto it
    -- fetch_dem_hd (green surfaces), fetch_trees (tree corridors), fetch_dem (gap-fill) -- so a
    location that is merely PLAUSIBLE is no longer good enough: it now decides which hole's geometry
    every stage builds on. Pick wrong and another course's hole, green and slope print on this card.

    Two properties, because passing today is not the same as being safe:

      * MARGIN, not just the answer. castlewood-valley is the real case -- it shares an OSM area with
        castlewood-hill, whose clubhouse is 960 m away, and its holes 1 and 9 each have two candidate
        ways. Their margins are 602 m and 632 m against the 150 m floor, so the decision is made with
        4x the room it needs. Asserting only "the right way was chosen" would still pass at 151 m,
        one bad edit from a coin toss.
      * No way is claimed by two courses. That is the actual failure this protects against, stated
        directly, and it holds across the whole corpus: 198 chosen ways, 198 distinct.

    A stated location sitting a few hundred metres from the mapped-feature centroid is normal and NOT
    checked -- a clubhouse address legitimately sits off-centre, and the corpus runs to 617 m. What
    matters is the margin, not the offset.
    """
    import math
    R = 111320.0
    checked, tight, shared = 0, [], {}
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "osm_geom.json")
        if not os.path.exists(p):
            continue
        cfg, _rh = _engine(ref)
        import geo
        with open(p, encoding="utf-8") as fh:
            els = json.load(fh)["elements"]
        loc = cfg.COURSE.get("location") or {}
        if not loc.get("lat"):
            continue
        mlon = R * math.cos(math.radians(loc["lat"]))
        by_ref = {}
        for e in els:
            t = e.get("tags") or {}
            if t.get("golf") == "hole" and e.get("geometry") and (t.get("ref") or "").isdigit():
                by_ref.setdefault(int(t["ref"]), []).append(e)
        for hn, cands in sorted(by_ref.items()):
            if len(cands) < 2:
                continue
            ds = []
            for g in cands:
                n = len(g["geometry"])
                la = sum(q["lat"] for q in g["geometry"]) / n
                lo = sum(q["lon"] for q in g["geometry"]) / n
                ds.append(math.hypot((la - loc["lat"]) * R, (lo - loc["lon"]) * mlon))
            ds.sort()
            checked += 1
            margin = ds[1] - ds[0]
            if margin < geo.AMBIGUOUS_MARGIN_M * 2:
                tight.append(f"{ref} hole {hn}: nearest {ds[0]:.0f} m, next {ds[1]:.0f} m -- a "
                             f"margin of {margin:.0f} m, under twice the "
                             f"{geo.AMBIGUOUS_MARGIN_M:.0f} m floor. Verify \"location\" against "
                             f"the clubhouse before this becomes a coin toss.")
        try:
            for hn, g in geo.hole_lines(els, loc.get("lat"), loc.get("lon")).items():
                shared.setdefault(g.get("id"), set()).add(ref)
        except SystemExit:
            pass
    both = {k: v for k, v in shared.items() if len(v) > 1}
    assert not both, ("an OSM hole way is claimed by two different courses -- one of those books "
                      f"is printing another course's hole: "
                      + "; ".join(f"way {k} -> {sorted(v)}" for k, v in list(both.items())[:5]))
    assert not tight, "a hole-line choice rests on too little margin:\n  " + "\n  ".join(tight)
    assert checked >= 1, "no contested hole number in the corpus -- the margin was never exercised"


@needs_corpus
def test_no_book_quietly_headlines_a_shorter_tee():
    """The headline yardage must be the longest tee on the card, or the course must say it is on purpose.

    BACK_I picks the longer of the FEATURED/SECONDARY pair, which is not the same as the longest tee
    on the scorecard. the-reserve-at-spanos-park left secondary_tee null, so SECONDARY fell back to
    TEES[-1] (Green, 5246 yd), the pair became Gold-vs-Green, and Black -- the real tips at 7173 yd
    -- sat in OTHERS as a footnote where it could never win. The book headlined Gold, 274 yd shorter,
    and every derived number followed it: tee marker, from-tee gutter yardages, carries, elevation.
    Black and Gold differ on 10 of that course's 18 holes, by up to 46 yd on hole 12.

    A junior 15 or over plays the longest tee they are given, so a book that quietly headlines a
    shorter one misstates the distance all day. The opt-out exists because which tee a book is FOR
    is a real editorial choice -- a forward-tee junior edition is legitimate -- but it has to be
    written down rather than fallen into.
    """
    offenders = []
    for ref in CORPUS:
        cfg, _rh = _engine(ref)
        totals = {t: sum(cfg.HOLES[h][2 + i] for h in cfg.HOLES)
                  for i, t in enumerate(cfg.TEES)}
        if not totals:
            continue
        longest = max(totals, key=totals.get)
        if longest == cfg.BACK_NAME or cfg.COURSE.get("shorter_tee_is_deliberate"):
            continue
        offenders.append(f"{ref}: headlines {cfg.BACK_NAME} ({totals[cfg.BACK_NAME]} yd) but "
                         f"{longest} ({totals[longest]} yd) is longer -- the map, gutters, carries "
                         f"and elevation are all measured from the shorter tee")
    assert not offenders, ("a book is built on a shorter tee without saying so:\n  "
                           + "\n  ".join(offenders))


@needs_corpus
def test_every_printed_caveat_matches_the_data_behind_it():
    """The governing rule of this project, checked against the shipped books rather than a fixture.

    Three caveats are the honesty rule made concrete, and each is a claim about the DATA:
      * "1 m data"        -- this green came from the coarser seamless model, not the point cloud
      * "pre-rebuild data" -- the course was rebuilt after the flight, so the map may be stale
      * no slope at all    -- the gate refused to read this surface
    Every one is tested somewhere on a synthetic surface, which proves the rule fires. None was
    tested against the corpus, which is what proves the LABELS ON THE PAGE match the files on disk.
    Those are different claims: a card can carry a perfectly working rule applied to the wrong hole.

    Both directions, because each fails differently. A missing caveat is the dangerous one -- a
    junior trusts a 1 m read as if it were 0.4 m LiDAR. A spurious one is the corrosive one: it
    disclaims data that is actually good, and a book that cries wolf teaches the reader to skip the
    warnings that matter.

    It also pins two couplings the guide card asserts in prose: the holes it NAMES as coarse must be
    exactly the coarse ones, and a green printing a slope must not be one the gate refused.

    Note for whoever next edits this: split panels on `<div class="panel ` and filter, not on
    `panel hole">`. The guide card's own explanation of "1 m data" otherwise lands inside the
    preceding hole's block and reads as a mislabelled card -- which is exactly the false alarm this
    test was written after chasing.
    """
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        cj = os.path.join(ROOT, "courses", ref, "course.json")
        with open(cj, encoding="utf-8") as fh:
            stale = set(json.load(fh).get("greens_possibly_outdated") or [])
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                # `hole ycard` too. poppy-ridge's yardage edition uses class="panel hole ycard", so
                # a startswith('hole"') filter silently skipped its 18 cards -- and it is the course
                # LEAST like the others, which is exactly where a check is worth most.
                continue
            hm = re.search(r'<div class="hnum">(\d+)</div>', blk)
            if not hm:
                continue
            hn = int(hm.group(1))
            meta_p = os.path.join(ROOT, "courses", ref, "dem_hd", f"hole{hn:02d}.json")
            if not os.path.exists(meta_p):
                continue
            with open(meta_p, encoding="utf-8") as fh:
                meta = json.load(fh)
            checked += 1
            seen_courses[ref] += 1   # past the gates: counts WORK, not intent
            coarse = "seamless" in str(meta.get("source", "")).lower()
            says_coarse = "GREEN &middot; 1 m data" in blk
            if coarse and not says_coarse and hn not in stale:
                problems.append(f"{ref} hole {hn}: built from the 1 m seamless model but the card "
                                f"does not say so -- the read looks as sharp as a LiDAR one")
            if says_coarse and not coarse:
                problems.append(f"{ref} hole {hn}: card says \"1 m data\" but the green was built "
                                f"from {meta.get('source')!r} -- disclaiming data that is good")

            says_stale = "pre-rebuild data" in blk
            if (hn in stale) != says_stale:
                problems.append(f"{ref} hole {hn}: greens_possibly_outdated says "
                                f"{hn in stale}, the card says {says_stale}")

            refused = bool(meta.get("insufficient"))
            no_slope = "no slope printed" in blk
            if refused and not no_slope:
                problems.append(f"{ref} hole {hn}: the gate refused this surface but the card still "
                                f"prints a slope -- a number the data does not support")
            if no_slope and re.search(r"&middot; \d+\.\d%", blk):
                problems.append(f"{ref} hole {hn}: card says no slope printed, yet prints one")
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} cards checked of {expected_geometry_holes()} holes with geometry -- a course is being "
        f"skipped")
    assert_no_course_skipped(seen_courses, "test_every_printed_caveat_matches_the_data_behind_it")
    assert not problems, ("a printed caveat does not match its data:\n  "
                          + "\n  ".join(problems[:10]))


def _arc_yd_for(ref, panel_html):
    """The drawn centreline length in yards for the hole this panel shows, from the engine itself.

    The card yardage is the SCORECARD's walked figure; the drawn OSM line can be longer or shorter.
    Any bound on the gutter pair has to use the line the numbers were measured on."""
    m = re.search(r'<div class="hnum">(\d+)</div>', panel_html)
    if not m:
        return None
    cfg, rh = _engine(ref)
    try:
        _svg, info = rh.render_hole(int(m.group(1)), cfg.HOLES)
    except Exception:
        return None
    return info.get("arc_yd")


@needs_corpus
def test_no_hole_grouping_uses_a_golf_term_with_the_wrong_meaning():
    """One book must not group its own holes two different ways, and must not redefine "front".

    The corner tab is a thumb index -- which third of the cut deck a card sits in -- and it read
    "Front" / "Mid" / "Finish". In golf "front" means holes 1-9, universally; here it meant 1-6, while
    the SAME book's scorecard splits Out 1-9 / In 10-18. So a junior looking under "Front" for hole 8
    found it tabbed "Mid", and the book answered "which holes are the front?" two ways.

    The split was also uneven -- 6/8/4 on eighteen holes -- because it came from two hand-written
    branches rather than from the holes present.

    Now literal ranges, derived: 1-6 / 7-12 / 13-18 on eighteen, 1-3 / 4-6 / 7-9 on nine. A range
    cannot collide with a golf term because it states the grouping instead of naming it.

    Asserted two ways. No tab may reuse a scorecard word (front, back, out, in) -- which is the
    ambiguity itself, not a style preference -- and the thirds must be within one card of even, which
    is what a thumb index is for.
    """
    WORDS = ("front", "back", "out", "in")
    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        groups = {}
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                continue
            hn = re.search(r'<div class="hnum">(\d+)</div>', blk)
            st = re.search(r'<div class="sheettab">([^<]*)</div>', blk)
            if hn and st:
                groups.setdefault(st.group(1).strip(), []).append(int(hn.group(1)))
        if not groups:
            continue
        checked += 1
        for label, holes in groups.items():
            assert label.lower() not in WORDS, (
                f"{ref}/{os.path.basename(p)}: a corner tab reads {label!r} and covers holes "
                f"{min(holes)}-{max(holes)}, but the scorecard in the same book uses that word for a "
                f"different set -- one book, two meanings for one golf term")
            assert re.fullmatch(r"\d+[\u2013-]\d+", label), (
                f"{ref}/{os.path.basename(p)}: the tab {label!r} names a grouping instead of stating "
                f"it; a literal range cannot be misread")
        sizes = sorted(len(v) for v in groups.values())
        assert sizes[-1] - sizes[0] <= 1, (
            f"{ref}/{os.path.basename(p)}: the thumb index splits the deck {sizes}, which is not "
            f"thirds -- fanning to a group lands in the wrong place")
        # ...and the groups must partition the holes, with no hole in two tabs or none
        allh = sorted(h for v in groups.values() for h in v)
        assert len(allh) == len(set(allh)), f"{ref}: a hole appears under two different tabs"
    assert checked >= 10, f"only {checked} books checked -- build them first"


def test_render_hole_reads_its_tee_columns_from_the_row_it_was_given():
    """render_hole takes HOLES as an argument. It must not size that argument using global state.

    The function is passed HOLES and reads BACK_I and the tee names from the module-global config, so
    the two have to describe the same course. Nothing said so. One line iterated
    `range(len(_cfg.TEES))` while indexing `HOLES[hnum]`, so a caller whose row had fewer tee columns
    than the bound course raised IndexError deep inside the from-tee derivation.

    Production never hit it -- generate.py passes the HOLES of the course it has just bound -- which is
    why it survived. It surfaced only when the suite ran in a SHUFFLED order: a synthetic 2-tee fixture
    inherited a real 5-tee binding left behind by whichever test happened to run before it. In file
    order and in reverse order the suite was green; two of three shuffles failed. That is the shape of
    a bug that hides for years and then appears as a mystery on someone else's machine.

    Tested two ways, because either alone is weak. A 2-column row is rendered while a 5-column course is
    bound, which is the exact failing configuration. And the source is checked for the pattern, since
    the fixture only exercises one arity and the next such line might involve a different one.
    """
    src = open(os.path.join(ROOT, "render_hole.py"), encoding="utf-8").read()
    bad = re.findall(r"range\(len\(_cfg\.TEES\)\)", src)
    assert not bad, ("render_hole sizes a HOLES row from the global config's tee count again. The row's "
                     "own length is the only honest source: a caller whose row is narrower than the "
                     "bound course gets IndexError, and nothing declares they must match.")

    # ...and prove it by doing exactly what broke: narrow row, wide binding.
    slug = a_course()
    cfg, rh = _engine(slug)
    if len(cfg.TEES) < 3:
        pytest.skip(f"{slug} has only {len(cfg.TEES)} tee columns; need a wider course to narrow")
    wide = len(cfg.TEES)
    hn = sorted(cfg.HOLES)[0]
    row = cfg.HOLES[hn]
    narrow = {h: tuple(cfg.HOLES[h][:4]) for h in cfg.HOLES}      # par, hcp, two tees
    assert len(narrow[hn]) < 2 + wide, "the narrowed row is not actually narrower"
    try:
        rh.render_hole(hn, narrow)
    except IndexError as e:
        pytest.fail(f"render_hole({hn}, <4-column row>) raised IndexError with a {wide}-tee course "
                    f"bound: {e}. It is reading the row's width from config instead of the row.")
    except Exception:
        pass          # any OTHER failure is about the synthetic row's content, not this bug


@needs_corpus
def test_the_qr_code_says_where_it_goes():
    """A QR sits under "VISIT lucasgreenbook.org" and does NOT go there. It must say so.

    The code on the dedication card is an INSTAGRAM QR -- Instagram logo, brand gradient, labelled
    LUCASWU.GOLF. It is printed directly beneath the line inviting the reader to visit the website, so
    a twelve-year-old scans the square expecting lucasgreenbook.org and arrives at a social profile.
    Nothing on the page said otherwise; the only distinguishing mark was the logo baked into the image,
    which is exactly the kind of detail a reader skips.

    The caption class `.dqrcap` was already defined for this, including an Instagram-purple rule for a
    <b> inside it, and was never emitted -- so the caption had been intended and was lost. Now it
    prints "Instagram @lucaswu.golf".

    Asserted as a relationship, not a string: if a book invites the reader to a URL and also carries a
    QR image, the QR must be labelled. Both halves must be present because either alone is fine -- a
    website line with no QR, or a QR with no competing URL beside it.
    """
    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        has_qr = bool(re.search(r'class="dqr"', html))
        invites = bool(re.search(r"lucasgreenbook\.org", html))
        if not (has_qr and invites):
            continue
        checked += 1
        assert re.search(r'class="dqrcap"', html), (
            f"{ref}/{os.path.basename(p)} prints a QR code beneath an invitation to visit "
            f"lucasgreenbook.org, but nothing labels where the QR actually goes -- it is an Instagram "
            f"code, and a reader will scan it expecting the website")
        cap = re.search(r'class="dqrcap">(.*?)</div>', html, re.S)
        flat = " ".join(re.sub(r"<[^>]+>", "", cap.group(1)).split())
        assert re.search(r"instagram", flat, re.I), (
            f"{ref}/{os.path.basename(p)}: the QR caption reads {flat!r}, which does not name the "
            f"destination")
    assert checked >= 10, f"only {checked} books carried both a QR and a website line"


@needs_corpus
def test_nothing_is_drawn_off_the_putting_surface():
    """Every mark on a green map claims something about ground you can putt on. Verify it is.

    Three placements, each meaningless or misleading if it strays outside the outline:
      * downhill ARROWS. One poking past the edge says the ball rolls that way off a surface that is
        not green -- a bank or a bunker face. render_green already tests the tip plus a forward head
        allowance, so this re-tests the ARTIFACT: 12,161 drawn arrows, tips and all three arrowhead
        vertices, against the outline drawn beside them.
      * the HOLE map's pin ring, placed at the green's CENTROID. A centroid is not guaranteed to lie
        inside its own polygon -- a strongly kidney-shaped green can put it on the apron -- so this is
        a real geometric risk rather than a hypothetical one. 198 of 198 are inside.
      * the GREEN panel's dashed pin ring, at the mid-depth point. Same question, different frame: it
        is emitted AFTER the rotated group closes, so it is in screen space while the outline is not.
        The outline is rotated here before comparing, which is the only way the two are comparable.

    Frames are the whole difficulty in this check and getting one wrong produces confident nonsense: a
    first pass matched the hole map's r=2.6 pin against the green panel's outline and reported 63 of
    198 pins off the surface. Both radii and both frames are pinned explicitly for that reason.
    """
    import math

    def inside(px, py, poly):
        c, n = False, len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / ((y2 - y1) or 1e-12):
                c = not c
        return c

    def rot(x, y, cx, cy, deg):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        dx, dy = x - cx, y - cy
        return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

    arrows = hole_pins = green_pins = slope_labels = 0
    problems, seen = [], collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                continue
            hn = re.search(r'<div class="hnum">(\d+)</div>', blk)
            if not hn:
                continue
            seen[ref] += 1

            # --- arrows and the green outline share ONE rotated frame ---
            g = re.search(r'<g transform="rotate\((-?[\d.]+) ([\d.]+) ([\d.]+)\)">(.*?)'
                          r'<path d="(M [^"]*)" fill="none" stroke="#20402a"[^>]*/></g>', blk, re.S)
            if g:
                raw = [(float(x), float(y))
                       for x, y in re.findall(r"([\d.-]+),([\d.-]+)", g.group(5))]
                if len(raw) >= 3:
                    ag = re.search(r'<g stroke="#15271b"[^>]*>(.*?)</g>', g.group(4), re.S)
                    if ag:
                        for m in re.finditer(
                                r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" '
                                r'y2="([\d.-]+)"/><polygon points="([^"]+)"', ag.group(1)):
                            arrows += 1
                            pts = [(float(m.group(3)), float(m.group(4)))]
                            pts += [(float(a), float(b))
                                    for a, b in re.findall(r"([\d.-]+),([\d.-]+)", m.group(5))]
                            for px, py in pts:
                                if not inside(px, py, raw):
                                    problems.append(f"{ref} hole {hn.group(1)}: an arrow reaches "
                                                    f"({px:.1f},{py:.1f}), outside the green outline")
                                    break
                    # --- the green panel's dashed pin, in SCREEN space ---
                    gpin = re.search(r'<circle cx="([\d.-]+)" cy="([\d.-]+)" r="1\.4" '
                                     r'fill="none" stroke="#c0392b"', blk)
                    if gpin:
                        th, cx, cy = float(g.group(1)), float(g.group(2)), float(g.group(3))
                        screen = [rot(x, y, cx, cy, th) for x, y in raw]
                        green_pins += 1
                        if not inside(float(gpin.group(1)), float(gpin.group(2)), screen):
                            problems.append(f"{ref} hole {hn.group(1)}: the green panel's pin ring is "
                                            f"outside the putting surface it marks")

            # --- slope % labels, also in screen space ---
            # Left out of the first version of this test, which is why they are called out here: they
            # are clamped to the FRAME (VBx+2.5 .. VBx+VBw-2.5), not to the polygon, so a label staying
            # on the green is a property of where the candidates are picked rather than of the clamp.
            # 1,323 of them are inside today; nothing makes that structural.
            if g:
                raw2 = [(float(x), float(y))
                        for x, y in re.findall(r"([\d.-]+),([\d.-]+)", g.group(5))]
                if len(raw2) >= 3:
                    th, cx, cy = float(g.group(1)), float(g.group(2)), float(g.group(3))
                    screen2 = [rot(x, y, cx, cy, th) for x, y in raw2]
                    for sx, sy, val in re.findall(
                            r'<text x="([\d.-]+)" y="([\d.-]+)" font-size="4\.6"[^>]*>(\d+)</text>',
                            blk):
                        slope_labels += 1
                        if not inside(float(sx), float(sy), screen2):
                            problems.append(f"{ref} hole {hn.group(1)}: the slope label \"{val}%\" "
                                            f"sits off the green, so it describes ground that is not "
                                            f"putting surface")

            # --- the hole map's pin, at the green centroid ---
            hm = re.search(r'<div class="lay"><div class="minilab">HOLE</div>(<svg.*?</svg>)',
                           blk, re.S)
            if hm:
                gp = re.search(r'<path d="(M [^"]*)" fill="#7cc45a"', hm.group(1))
                pin = re.search(r'<circle cx="([\d.-]+)" cy="([\d.-]+)" r="2\.6"', hm.group(1))
                if gp and pin:
                    poly = [(float(x), float(y))
                            for x, y in re.findall(r"([\d.-]+),([\d.-]+)", gp.group(1))]
                    hole_pins += 1
                    if not inside(float(pin.group(1)), float(pin.group(2)), poly):
                        problems.append(f"{ref} hole {hn.group(1)}: the hole map's pin ring sits off "
                                        f"the green -- its centroid falls outside its own polygon")

    assert arrows > 5000, f"only {arrows} arrows examined -- the sweep found almost nothing"
    assert hole_pins >= 150 and green_pins >= 150, \
        f"only {hole_pins} hole pins and {green_pins} green pins examined"
    assert slope_labels > 500, f"only {slope_labels} slope labels examined"
    assert_no_course_skipped(seen, "test_nothing_is_drawn_off_the_putting_surface")
    assert not problems, ("marks are drawn off the putting surface they describe:\n  "
                          + "\n  ".join(problems[:8]))


@needs_corpus
def test_the_printed_flight_date_still_matches_the_tiles_on_disk():
    """The guide card prints "flown 2024-12-17". That is a claim about a file, so check the file.

    A USGS project name is not a flight date -- monarch-bay's tiles are named
    CA_AlamedaCounty_2021_B21 and its points were flown 2019-08-14, two years earlier -- which is why
    the date is decoded from GPS time in the point records rather than read off a label. Four courses
    were mislabelled by 2-12 years before that was done.

    But the decode is cached in course.json, and the CARD prints the cache. So a re-fetch that brought
    down different tiles, or a tile deleted to save space, would leave the book asserting a flight date
    the data on disk no longer supports -- and nothing would notice, because every other check reads
    the same cached value.

    Two links, both against the filesystem rather than the cache:
      * every tile named in lidar_flown["tiles"] still exists in laz/. All 11 courses pass; the tiles on
        disk that are NOT in the record are correctly absent, being the ones with no points over a
        green, which is the whole point of narrowing the range to the greens.
      * the basis must be the strong one. lidar_dates falls back to a union over WHOLE TILES when no
        point lies over a green, and a tile 1.3 km away can then set the extremes. All 11 record
        "points within 30 m of a green"; anything weaker has to be visible, not silent.

    Re-decoding the dates themselves needs to read every point record, so it is a tool
    (tools/lidar_dates.py) rather than a test. Run against all 11 courses while writing this: every
    label reproduced exactly, including monarch-bay's 2019 date under a 2021 project name and
    philadelphia's 2024-12-17 to 2025-03-27 range.
    """
    checked, problems = 0, []
    for ref in CORPUS:
        cj = os.path.join(ROOT, "courses", ref, "course.json")
        if not os.path.exists(cj):
            continue
        with open(cj, encoding="utf-8") as fh:
            flown = (json.load(fh).get("lidar_flown") or {})
        recorded = flown.get("tiles") or {}
        if not recorded:
            continue                          # a course with no point cloud claims no flight date
        checked += 1
        laz = {os.path.basename(x)
               for x in glob.glob(os.path.join(ROOT, "courses", ref, "laz", "*.laz"))}
        gone = sorted(set(recorded) - laz)
        if gone:
            problems.append(f"{ref}: the printed flight date rests on {len(gone)} tile(s) that are no "
                            f"longer in laz/ -- {gone[:3]} -- so the card cites data that is not there")
        basis = str(flown.get("basis") or "")
        if not basis.startswith("points within"):
            problems.append(f"{ref}: flight date basis is {basis!r}, not a points-over-the-greens "
                            f"measurement -- a tile far from any green may be setting the range, and "
                            f"the provenance table must say so rather than print a bare date")
        assert flown.get("label"), f"{ref}: records tiles and dates but no printed label"
    assert checked >= 10, f"only {checked} courses carry a flight-date record"
    assert not problems, ("the printed flight date no longer matches the tiles on disk:\n  "
                          + "\n  ".join(problems))


@needs_corpus
def test_the_colour_legend_shows_the_colours_the_map_actually_uses():
    """The legend prints three swatches and the number 5%. Both must come from the ramp, not beside it.

    A reader matches a patch of green against the swatch to read steepness, so the swatch has to BE the
    ramp's colour. If the ramp were retuned -- a different red, a midpoint moved -- the legend would go
    on showing the old squares and every colour read would be off by however much it drifted, silently,
    on every card. Nothing connected the two: the legend hardcodes three rgb() literals in generate.py
    and the ramp lives in render_green.heat_color.

    So the swatches are compared against heat_color(0), heat_color(2.5) and heat_color(5.0) -- the ramp
    evaluated, not copied. All 11 books match exactly today.

    The "(>=5%)" in the legend text is checked too, because it is the one number in the sentence: the
    ramp saturates at 5% by construction (t = slope/5, clamped), so 5% and 50% draw the identical red.
    That is what makes the claim true, and a change to the divisor would falsify the printed number
    while every colour still looked plausible.

    NOT asserted, having measured it: that "longer = steeper" holds for every arrow. Length is
    2.2 + 3.4*min(slope/smax, 1) against a 92nd-percentile smax, so the steepest arrows share one
    length -- 7.3% of 12,161 arrows sit at their green's cap, median 7.4% per green, worst 13.3%. The cap
    is right rather than wrong: without it a single outlier pixel would shrink every other arrow to
    nothing. The legend is a fair simplification of the ordinary case, and the card carries slope
    numbers and colour as well, so the tail is not unreadable -- just not distinguishable by length.
    """
    cfg, _rh = _engine(a_course())
    import render_green
    want = [render_green.heat_color(0.0), render_green.heat_color(2.5), render_green.heat_color(5.0)]
    assert len(set(want)) == 3, f"the ramp no longer has three distinct stops: {want}"

    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        g = re.search(r'<div class="legrow"><svg width="28" height="14">((?:<rect[^>]*/>){3})', html)
        if not g:
            continue                      # a yardage-mode book prints no colour legend
        checked += 1
        got = [c.replace(" ", "") for c in re.findall(r'fill="(rgb\([\d, ]+\))"', g.group(1))]
        assert got == want, (
            f"{ref}/{os.path.basename(p)}: the legend shows {got} but the map's ramp is {want} -- a "
            f"reader matching a patch to a swatch would misread the slope")
        # the sentence's own number must be where the ramp actually saturates
        assert re.search(r"red \(&ge;5%\)|red \(\u22655%\)", html), (
            f"{ref}/{os.path.basename(p)}: the colour legend no longer states the 5% saturation point")
    assert checked >= 10, f"only {checked} colour legends checked -- build the books first"
    # and the ramp really does saturate at 5, or the printed number is wrong
    assert render_green.heat_color(5.0) == render_green.heat_color(50.0), \
        "the legend says red at >=5% but the ramp keeps changing above 5"


@needs_corpus
def test_the_contour_interval_is_the_one_the_legend_states():
    """The card says "Contours join equal height (15 cm each)". That is a measurement, so verify it.

    A reader counts contour lines to judge how much a putt will move: five lines close together means
    something specific only if each one is the height the legend claims. Change CINT_M and every green
    map still looks entirely plausible -- the lines just mean a different amount of fall, and no reader
    could tell. The legend would be quietly wrong on every card in every book.

    Checked against the built surfaces rather than by reading the constant back: the number of levels
    the marching-squares loop can visit on a green is floor(relief / interval), and across merion's 18
    greens (relief 2.51-7.36 m) that gives 16-49 levels at 15 cm. A 10 cm interval would give 25-73 and
    a 20 cm one 12-36, so the counts distinguish the stated interval from its neighbours rather than
    merely being consistent with it.

    Also asserts the two editions draw the SAME contours, which they do to the segment: 8683 for
    merion, 5954 for monarch-bay, 5797 for philadelphia, identical in pocket and enlarged. They import
    one render_green so a divergence should be impossible -- but these two editions have drifted four
    times now (honesty rules, playline row, stroke-index label, ODbL URL), and "impossible by
    construction" is what was believed each of those times.
    """
    import numpy as np
    cfg, _rh = _engine(a_course())
    import render_green
    # READ THE LEGEND, do not hardcode what it says. `stated_cm = 15` made this a comparison between
    # render_green.CINT_M and a literal in the test -- so a legend that said "20 cm each" over contours
    # drawn at 15 passed, which is precisely the disagreement this test is named for. Proven by mutation.
    # Parsed from every built book so both editions are covered and a divergence between them fails too.
    stated = set()
    for name in ("greenbook.html", "greenbook_coach.html"):
        for slug in CORPUS:
            fp = os.path.join(ROOT, "courses", slug, name)
            if not os.path.isfile(fp):
                continue
            with open(fp, encoding="utf-8") as fh:
                book = fh.read()
            for m in re.finditer(r"join equal height[^0-9]{0,12}(\d+)&nbsp;cm", book):
                stated.add(int(m.group(1)))
    assert stated, ("no book states a contour interval, so this test would pass vacuously -- the legend "
                    "wording changed and this pattern no longer finds it")
    assert len(stated) == 1, f"the books disagree about the contour interval: {sorted(stated)} cm"
    stated_cm = stated.pop()
    assert abs(render_green.CINT_M * 100 - stated_cm) < 0.01, (
        f"render_green.CINT_M is {render_green.CINT_M} m, so the legend's '{stated_cm} cm each' is "
        f"wrong on every card in every book")

    for ref in CORPUS:
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", ref, "dem_hd", "hole*.npy"))):
            a = np.load(p)
            fin = a[np.isfinite(a)]
            if fin.size == 0:
                continue
            relief = float(fin.max() - fin.min())
            levels = int(relief / render_green.CINT_M)
            # a green with real relief must admit several bands, or the legend describes nothing
            if relief > 1.0:
                assert levels >= 6, (
                    f"{ref} {os.path.basename(p)}: {relief:.2f} m of relief yields only {levels} "
                    f"contour bands at {render_green.CINT_M} m -- the interval and the surfaces "
                    f"disagree about scale")
        break                                  # one course exercises the arithmetic; the constant is global

    # both editions must draw the same contours
    for ref in CORPUS:
        pocket = os.path.join(ROOT, "courses", ref, "greenbook.html")
        coach = os.path.join(ROOT, "courses", ref, "greenbook_coach.html")
        if not (os.path.exists(pocket) and os.path.exists(coach)):
            continue
        counts = {}
        for label, path in (("pocket", pocket), ("enlarged", coach)):
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
            n = 0
            for blk in re.split(r'<div class="panel ', html)[1:]:
                if not re.match(r'hole[\s"]', blk):
                    continue
                g = re.search(r'<g stroke="#3c5a34" stroke-width="0\.5" opacity="0\.55">(.*?)</g>',
                              blk, re.S)
                if g:
                    n += len(re.findall(r"<line ", g.group(1)))
            counts[label] = n
        assert counts["pocket"] == counts["enlarged"], (
            f"{ref}: the pocket book draws {counts['pocket']} contour segments and the enlarged "
            f"edition {counts['enlarged']} -- they no longer describe the same surface, so one "
            f"edition's '15 cm each' legend is wrong")


@needs_corpus
def test_no_tree_marker_sits_on_a_playing_surface():
    """The README promises trees are "never placed on greens/fairways/tees/bunkers". Hold the corpus
    to it.

    A tree dot in the middle of a fairway is a map that lies about where the ball can go, and it is the
    kind of error a reader trusts because everything around it is right. The markers come from LiDAR
    canopy returns, so nothing about their source prevents one landing on mown grass -- a low return
    over a green, a bush beside a tee, a maintenance shed edge. fetch_trees.on_playing_surface exists
    to reject those, and a unit test covers the classifier on synthetic polygons.

    What was never checked is the ARTIFACT: that the filter actually ran, over every course, and left
    nothing behind. Those are different claims -- the classifier can be perfect and still be applied to
    the wrong polygon set, or skipped for a course whose surfaces failed to load. Re-tested here
    independently, with a fresh point-in-polygon over osm_course.json rather than by calling the
    function that did the filtering, so a fault in that function cannot vouch for itself.

    68,884 markers across 11 courses, zero on a green, fairway, tee or bunker.
    """
    def inside(px, py, poly):
        c, n = False, len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / ((y2 - y1) or 1e-12):
                c = not c
        return c

    total, offenders, seen = 0, [], collections.Counter()
    for ref in CORPUS:
        tp = os.path.join(ROOT, "courses", ref, "trees_lidar.json")
        cp = os.path.join(ROOT, "courses", ref, "osm_course.json")
        if not (os.path.exists(tp) and os.path.exists(cp)):
            continue
        with open(tp, encoding="utf-8") as fh:
            trees = json.load(fh)
        with open(cp, encoding="utf-8") as fh:
            elements = json.load(fh)["elements"]
        surfaces = []
        for e in elements:
            kind = (e.get("tags") or {}).get("golf")
            if kind in ("green", "fairway", "tee", "bunker") and e.get("geometry"):
                surfaces.append((kind, [(q["lon"], q["lat"]) for q in e["geometry"]]))
        if not surfaces:
            continue
        seen[ref] += 1
        for hn, pts in (trees.items() if isinstance(trees, dict) else []):
            for entry in pts:
                lat, lon = ((entry[0], entry[1]) if isinstance(entry, (list, tuple))
                            else (entry["lat"], entry["lon"]))
                total += 1
                for kind, poly in surfaces:
                    if inside(lon, lat, poly):
                        offenders.append(f"{ref} hole {hn}: a tree marker sits on a {kind} "
                                         f"at {lat:.6f},{lon:.6f}")
                        break
    assert total > 10000, f"only {total} tree markers examined -- the sweep found almost nothing"
    assert_no_course_skipped(seen, "test_no_tree_marker_sits_on_a_playing_surface")
    assert not offenders, ("tree markers are drawn on ground the ball can be played from, which the "
                           f"README says cannot happen ({len(offenders)} of {total}):\n  "
                           + "\n  ".join(offenders[:8]))


@needs_corpus
def test_the_hand_written_verdict_matches_the_machine_verdict():
    """legal/00 names, by hand, every book that is safe to hand out. That list has drifted twice.

    The document says so itself: an earlier revision listed Poppy Ridge among the distributed books
    and then called them "safe to hand out", contradicting the generated provenance table; another
    said "ELEVEN" while listing six courses. It closes by telling the reader to prefer the generated
    table if the two disagree -- which is the right instinct and an admission that they can.

    They should not be able to. distribution.py is the single rule, gen_provenance.py renders it, and
    the summary is prose over the top. So this asserts the prose against the rule: every course the
    rule calls Distributed must be named in the verdict list, and any course it calls Personal must
    NOT be. Getting that wrong in the direction that happened before -- a personal-use book listed as
    safe to hand out -- is the one error in this repo with a real-world cost outside the code.

    Matched on a distinctive token from each course name rather than the full string, because the
    summary legitimately abbreviates ("Merion (East)" for "Merion Golf Club — East Course"). Scoped to
    the verdict LIST only: Poppy Ridge is discussed at length elsewhere in the same document, which is
    exactly where it should be.
    """
    p = os.path.join(ROOT, "legal", "00_SUMMARY_AND_VERDICT.md")
    if not os.path.exists(p):
        pytest.skip("no legal/00 summary")
    with open(p, encoding="utf-8") as fh:
        doc = fh.read()
    m = re.search(r"distributed books are CLEAN\s*\n(.*?)\n\s*\n", doc, re.S)
    assert m, "legal/00 no longer has a parsable list of distributed books under its verdict heading"
    listed = " ".join(m.group(1).split())

    import distribution
    wrong = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        with open(cj, encoding="utf-8") as fh:
            course = json.load(fh)
        ok, _label, why = distribution.distribution_status(course)
        name = course.get("name", slug)
        # a token long enough to be distinctive, skipping generic words
        GENERIC = {"golf", "club", "course", "country", "the", "at", "preserve", "links", "and"}
        tokens = [w.strip("—-·,()") for w in name.split()]
        key = next((w for w in tokens if len(w) > 3 and w.lower() not in GENERIC), tokens[0])
        present = key.lower() in listed.lower()
        if ok and not present:
            wrong.append(f"{name} is Distributed but is not named in the verdict list")
        if not ok and present:
            wrong.append(f"{name} is PERSONAL ({why[:60]}...) but the verdict list names it among the "
                         f"books that are safe to hand out")
    assert not wrong, ("legal/00's hand-written verdict contradicts distribution.py, the rule that "
                       "actually decides:\n  " + "\n  ".join(wrong))


@needs_corpus
def test_every_sheet_tells_the_printer_not_to_scale():
    """The Rule 4.3 margin is 4%, which protects against rounding -- not against a printer.

    Greens are drawn at 0.36 in : 5 yd against a 0.375 limit. Enlarge a sheet by 4.1% and the worst
    green is over the cap while the cover still says "DESIGNED TO CONFORM - RULE 4.3". The book measured
    conforming, the paper does not, and the reader has no way to know: tools/check_scale.py measures the
    PDF, and the badge is printed before anyone picks a print setting.

    Nothing in the book said so. Every instance of "100%" was CSS; there was no "actual size", no "do not
    scale", no mention of fit-to-page in any book.

    The instruction belongs in the sheet margin note rather than on a card. That note is already
    printer-facing -- it carries "BACK (duplex, flip on LONG edge)" -- it sits outside the trim so it is
    discarded when the cards are cut, and it costs none of the card space that four earlier attempts at
    guide-card wording could not find. Checked on every sheet of every book, because scaling is a
    per-SHEET setting.

    What this does not claim: "fit to page" onto A4 shrinks a Letter sheet, which is safe, because the cap
    is a ceiling. The dangerous setting is a deliberate enlargement.
    """
    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        notes = re.findall(r'<div class="sheetnote">([^<]*)</div>', html)
        assert notes, f"{ref}/{os.path.basename(p)} has no sheet margin note at all"
        for note in notes:
            checked += 1
            assert "PRINT AT 100%" in note, (
                f"{ref}/{os.path.basename(p)}: a sheet note reads {note!r} without telling the printer "
                f"not to scale. A 4.1% enlargement breaks the Rule 4.3 cap the cover claims.")
    assert checked >= 30, f"only {checked} sheet notes checked -- build the books first"


def test_only_the_conforming_edition_claims_to_conform():
    """One edition is built to Rule 4.3 and one deliberately is not. Neither may be mistaken for the
    other.

    The pocket book is measured at 0.36 in : 5 yd, ~4% under the 3/8 in cap, and wears a
    "DESIGNED TO CONFORM - RULE 4.3" badge. The enlarged edition breaks the cap on purpose so the
    greens read at arm's length: measured off its own LAYOUT under print media it prints
    0.368-0.599 in : 5 yd (1:489 to 1:301) across all 54 of its greens, from 1.9% UNDER the cap to 60%
    over, with 53 of the 54 over it -- monarch-bay hole 14 is the one green that lands inside. That is a
    design decision, and the only thing that keeps it honest is the sentence on its guide card saying so
    plus the absence of the badge.

    THIS DOCSTRING WAS WRONG ON BOTH HALVES, and one explains the other. It said "measured off its own
    PDFs it prints 0.47-0.60 in : 5 yd, which is 26-60% OVER the limit". No PDF could have produced
    either number: the enlarged edition renders with tournament=False and render_green emits the "5 yd"
    bar only when tournament=True, so those PDFs contain no bar to measure. And 0.47-0.60 is the range
    of the three books' WORST greens, not of the 54. legal/06 had the right figures all along -- two
    documents quoting one hand measurement is how a wrong one survives, so tools/check_scale.py now
    measures the enlarged books itself and prints the range in a separate, non-gating section.

    Both halves are load-bearing and neither is enforced anywhere else. The enlarged books sit OUTSIDE
    the 198/198 scale gate rather than passing it -- deliberately, because gating an edition built to
    exceed the cap would be a gate against a design decision
    -- they are outside the gate rather than passing it. legal/06 did not mention them either until
    this commit. So a reader had a conformance document, a passing gate and a cover badge, and nothing
    connecting any of that to the edition it does not describe.

    Asserted as a pair: the enlarged edition must SAY it does not conform, and must NOT carry the
    badge. Either alone leaves the other free to drift.
    """
    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook_coach.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        # Normalise whitespace before matching. The sentence wraps across a source line inside a <b>,
        # so "...under\n    Rule&nbsp;4.3" does not match a naive one-line pattern -- the assertion
        # failed on text that was present, which is the false alarm this note exists to prevent.
        flat = " ".join(html.split())
        checked += 1
        assert re.search(r"NOT a conforming competition book under Rule", flat), (
            f"{ref}: the enlarged edition prints greens 26-60% over the Rule 4.3 scale cap but no "
            f"longer says so -- a coach would take it into a competition")
        assert "DESIGNED TO CONFORM" not in html, (
            f"{ref}: the enlarged edition carries the conformance badge, which belongs only to the "
            f"pocket book it is measured on")
        # Matched on substance, not on one sentence. The literal phrase "use the standard pocket
        # edition for competition" was pinned here, so tightening that legend row to fit the card --
        # the row had grown a line and was clipping the About & legal text below it -- failed this test
        # for wording while the claim it protects was still made. What matters is that the disclaimer
        # names the pocket edition as the alternative, in the same breath as competition.
        assert re.search(r"[Uu]se the (standard )?pocket edition (for|in) competition", flat), (
            f"{ref}: the enlarged edition disclaims conformance without naming the edition that does "
            f"conform, which leaves the reader with no usable alternative")
    if checked == 0:
        pytest.skip("no enlarged edition built (COURSE=<slug> COACH=1 python3 generate.py)")

    # ...and the pocket book must still make the claim, or the badge check above proves nothing
    pocket = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        if "DESIGNED TO CONFORM" in html:
            pocket += 1
    assert pocket >= 1, ("no pocket book claims Rule 4.3 conformance, so the enlarged edition's "
                         "'use the standard edition' instruction points at nothing")


@needs_corpus
def test_every_osm_using_book_carries_the_attribution_odbl_requires():
    """ODbL attribution is a LICENCE OBLIGATION, not a courtesy, and legal/02 states what it is.

    Any book whose maps come from OpenStreetMap is a Produced Work under ODbL 1.0, and the licence
    requires the attribution to travel with it. legal/02_ATTRIBUTIONS.md fixes the canonical string as
    "(c) OpenStreetMap contributors" + the licence named + openstreetmap.org/copyright. The pocket book
    carried all three. The ENLARGED edition carried the first two and dropped the URL -- the fourth
    time these two editions have drifted, after the green honesty rules, the playline row and the
    men's-stroke-index label, and the only one of the four that is a licence question rather than a
    quality one. All three enlarged books are marked Distributed.

    Scoped by USE, not by course: a book is only asked for OSM attribution if it actually contains OSM
    data. poppy-ridge is yardage mode -- no osm_geom.json, no hole maps, no green maps -- so it names
    OpenStreetMap nowhere and owes nothing. Requiring the string unconditionally would have forced a
    false credit onto a book built entirely from a scorecard and public-domain NAIP, which is its own
    kind of dishonesty.
    """
    ELEMENTS = {
        "the contributors credit": r"OpenStreetMap\s*(?:&nbsp;|\s)*contributors",
        "the licence by name": r"ODbL|Open\s*Database\s*Licen[cs]e",
        "the copyright URL": r"osm\.org/copyright|openstreetmap\.org/copyright",
        "the USGS credit": r"USGS(?:&nbsp;|\s)*3DEP",
    }
    checked, problems = 0, []
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        ref = os.path.basename(os.path.dirname(p))
        if ref.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        if "OpenStreetMap" not in html:
            # No OSM data in this book. Confirm that is really why, rather than a lost credit.
            assert not re.search(r'minilab">(HOLE|GREEN)', html), (
                f"{ref}/{os.path.basename(p)} draws maps but never names OpenStreetMap -- if those "
                f"maps are OSM-derived this is an ODbL breach, not an omission")
            continue
        checked += 1
        for what, pat in ELEMENTS.items():
            if not re.search(pat, html, re.I):
                problems.append(f"{ref}/{os.path.basename(p)} is a Produced Work from OSM data but "
                                f"is missing {what}")
    assert checked >= 10, f"only {checked} OSM-using books checked -- build them first"
    assert not problems, ("ODbL attribution is incomplete in a distributed book:\n  "
                          + "\n  ".join(problems))


def test_the_esri_imagery_incident_stays_resolved():
    """legal/07 records that licensed Esri/Maxar imagery was removed from this project. Enforce it.

    That incident is the only time this project used a third party's copyrighted content: Poppy
    Ridge's aerial embedded Esri World Imagery (Maxar). Esri's licence permits on-screen display and
    transitory caching, not exporting or building printed derivatives -- so baking those pixels into a
    PDF was a breach even privately, and real exposure if shared. The fix was to delete the source
    files and rebuild the aerial from public-domain USDA NAIP.

    A resolution recorded in prose decays. Two halves of it are mechanically checkable and now are:

      * the named source files stay deleted. If either returns -- a restore from a backup, a stray
        copy, an old worktree promoted -- the incident silently reopens.
      * no photographic raster enters the tracked tree at all. This is the general form of the rule
        and the one that matters going forward, because the next breach will not be called
        aerial_src.jpeg. Judged by distinct-colour count: the only tracked raster is the project
        banner, a designed graphic at 4643 distinct colours over 911k pixels (0.5%). An aerial tile or
        photo runs tens of thousands and a far higher ratio, so the 20000 threshold sits about 4x
        above the legitimate asset and well below any photograph.

    The third claim in that document -- a retained GREENS_LETTERED_coords.txt -- is NOT asserted here,
    because re-checking found the file gone. It lived under gitignored courses/ so its removal is
    undated and unrecorded. Its absence strengthens the position rather than weakening it (nothing
    Esri-derived remains, not even the factual coordinates), and the document now says so instead of
    listing evidence an auditor would go looking for and not find.
    """
    import subprocess
    GONE = ("aerial_src.jpeg", "GREENS_LETTERED.jpg")
    back = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f in GONE:
                back.append(os.path.relpath(os.path.join(root, f), ROOT))
    assert not back, (
        "an Esri/Maxar-derived file that legal/07 records as DELETED is back in the tree, which "
        f"reopens a resolved licensing breach: {back}")

    # fitz, not Pillow: PyMuPDF is already a declared dependency and reads PNG/JPEG fine, so this
    # check adds nothing to install. Reaching for Pillow here immediately failed the
    # every-third-party-import-is-declared test written one iteration earlier -- which is that guard
    # doing its job on its author, and the right answer was to use what is already there.
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    try:
        listing = subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=60)
    except Exception as e:
        pytest.skip(f"git unavailable: {e}")
    if listing.returncode != 0:
        pytest.skip("not a git checkout")
    photos = []
    for rel in listing.stdout.split():
        if not rel.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp")):
            continue
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            continue
        pm = fitz.Pixmap(p)
        if pm.alpha:                          # drop the alpha channel before counting colours
            pm = fitz.Pixmap(pm, 0)
        buf, comp = pm.samples, pm.n
        n = len({buf[i:i+comp] for i in range(0, len(buf), comp)})
        if n > 20000:
            photos.append(f"{rel} has {n} distinct colours -- that is photographic, not a graphic")
    assert not photos, (
        "a tracked raster looks like a photograph or an aerial tile. This project ships open data, "
        "public domain and facts only, and licensed imagery is the one line it has crossed before:\n  "
        + "\n  ".join(photos))


def test_every_third_party_import_is_declared():
    """A dependency the code uses but requirements.txt omits works on the author's machine and
    nowhere else.

    rasterio was missing for the life of tools/verify_elevation.py, and that tool is the ONLY
    independent cross-check on the printed tee-to-green heights -- it is what separated a real -3.7 ft
    from the "558 ft below" a units fault produced. Worse, its GeoTIFF read sat inside
    `except Exception: return None`, so on a fresh install every hole reported "DEM unavailable" and
    the run ended "nothing could be verified -- treat as UNKNOWN". Indistinguishable from a USGS
    outage, and the natural reading is that the service is down rather than that a package is absent.
    Silence would have been better than a misleading diagnosis.

    Discovered by parsing the imports, not from a list, and mapped where the install name differs from
    the import name (fitz -> PyMuPDF). A guarded optional import is fine and is exempted explicitly:
    `try: import x / except ImportError` says the code copes without it. rasterio's problem was that
    it was guarded in a way that produced a WRONG explanation, which is why it is now declared and
    refused up front instead.
    """
    import ast
    req = os.path.join(ROOT, "requirements.txt")
    if not os.path.exists(req):
        pytest.skip("no requirements.txt")
    # Parse PACKAGE NAMES, not a substring of the file. Substring-matching the whole text meant a
    # commented-out `#numpy removed` line still counted as declaring numpy -- a mutation that should
    # have failed, passed.
    declared = set()
    with open(req, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                declared.add(re.split(r"[<>=!~\[]", line)[0].strip().lower())
    # install name != import name
    ALIAS = {"fitz": "pymupdf", "PIL": "pillow", "yaml": "pyyaml", "cv2": "opencv"}
    # the stdlib, plus this repo's own modules, plus test-only helpers
    local = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "*.py"))}
    local |= {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "tools", "*.py"))}
    missing = []
    for p in sorted(glob.glob(os.path.join(ROOT, "*.py"))
                    + glob.glob(os.path.join(ROOT, "tools", "*.py"))
                    + glob.glob(os.path.join(ROOT, "tests", "*.py"))):
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        # NO exemption for guarded imports. `try: import x / except ImportError` was exempted at
        # first, and that is exactly how the rasterio mutation slipped through: wrapping the import
        # in a guard made the test stop requiring it, while verify_elevation.py still REFUSES to run
        # without it. Guarded is not the same as optional. Declaring a genuinely optional package
        # costs nothing -- it just gets installed -- so the rule has no exemption to game.
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in sys.stdlib_module_names or m in local or m.startswith("_"):
                    continue
                if ALIAS.get(m, m).lower() not in declared:
                    missing.append(f"{os.path.relpath(p, ROOT)} imports {m!r}, which "
                                   f"requirements.txt does not declare")
    assert not missing, ("the code needs packages the install instructions do not name, so it runs "
                         "only where it was written:\n  " + "\n  ".join(sorted(set(missing))))


def test_every_runnable_tool_is_documented():
    """A tool nobody can find is a trap, and two of these were traps the SUITE itself sets.

    The docs named 7 runnable scripts of 11. The four missing ones were not obscure:

      * tools/gen_provenance.py and tools/gen_disclaimers.py regenerate the two derived legal docs,
        and the test suite FAILS while either is stale. So adding a course gave a newcomer four red
        tests whose message says "STALE" and never names the command that fixes it. I walked into this
        myself while building a nine-hole test course.
      * tools/check_osm_bbox.py catches a fetch box so tight that features beside the hole were never
        downloaded -- the case where the map and the footer agree because both count only what arrived.
      * tools/lidar_dates.py is where the provenance table's flight dates come from. Four courses were
        mislabelled by 2-12 years before those were decoded from the point records.

    Asserted by discovery, not by a list: anything with a __main__ block must be named in README.md or
    PIPELINE.md. A hardcoded list of expected tools would need updating by the same person who forgot
    to write the docs.
    """
    undocumented = []
    docs = ""
    for d in ("README.md", "PIPELINE.md"):
        p = os.path.join(ROOT, d)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                docs += fh.read()
    assert docs, "neither README.md nor PIPELINE.md is present"
    for p in sorted(glob.glob(os.path.join(ROOT, "*.py"))
                    + glob.glob(os.path.join(ROOT, "tools", "*.py"))):
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        if "__main__" not in src:
            continue                      # a module, not something anyone runs
        name = os.path.basename(p)
        if name not in docs:
            undocumented.append(os.path.relpath(p, ROOT))
    assert not undocumented, (
        "these scripts can be run but no doc mentions them, so nobody can discover them:\n  "
        + "\n  ".join(undocumented))


def test_no_doc_names_a_script_or_flag_that_does_not_exist():
    """The other direction: a documented command a newcomer types must actually work.

    Cheap to check and the failure is expensive -- a stale command in the first thing a stranger reads
    stops them before they build anything, and they cannot tell a renamed script from their own
    mistake."""
    problems = []
    for d in ("README.md", "PIPELINE.md"):
        p = os.path.join(ROOT, d)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        for m in re.finditer(r"python3?\s+((?:tools/)?[a-z_0-9]+\.py)((?:\s+--[a-z-]+)*)", text):
            script, flags = m.group(1), m.group(2).split()
            sp = os.path.join(ROOT, script)
            if not os.path.exists(sp):
                problems.append(f"{d} tells the reader to run {script}, which does not exist")
                continue
            with open(sp, encoding="utf-8") as fh:
                src = fh.read()
            for f in flags:
                if f not in src:
                    problems.append(f"{d} passes {f} to {script}, which does not mention it")
    assert not problems, "the docs name something that is not there:\n  " + "\n  ".join(problems)


def test_the_printed_binding_still_fits_the_printed_cards():
    """The repo ships a 3D-printable binding, and its fit is a silent dependency on the card size.

    `green book binding.stl` is a spine the trimmed deck slides into. Its long axis is 90.0 mm against
    a 88.9 mm card -- 1.1 mm of total clearance, about half a millimetre a side. Change CARD_W_IN and
    the STL does not move with it: the book still builds, every test still passes, and the failure
    only shows up when someone has spent an hour printing a binding their cards will not go into.
    Nothing linked the two.

    Also checks the mesh is actually printable, because a broken STL fails in the slicer with a
    message about geometry rather than about this project: 1122 triangles, no zero-area faces, and
    every edge shared by exactly two of them, which is what watertight means.

    Units are assumed mm, the STL convention and what every slicer defaults to. If the model were
    ever authored in inches its long axis would read 3.54 rather than 90, so the fit assertion
    catches that too.
    """
    import struct
    p = os.path.join(ROOT, "green book binding.stl")
    if not os.path.exists(p):
        pytest.skip("no binding STL in this checkout")
    with open(p, "rb") as fh:
        raw = fh.read()
    assert raw[:5].lower() != b"solid" or b"facet" not in raw[:2000], \
        "expected a binary STL; an ASCII one needs a different reader"
    n = struct.unpack("<I", raw[80:84])[0]
    assert len(raw) == 84 + 50 * n, (
        f"STL is {len(raw)} bytes but its header declares {n} triangles "
        f"({84 + 50*n} expected) -- the file is truncated or padded")

    xs, ys, zs = [], [], []
    degenerate, edges = 0, {}
    for i in range(n):
        rec = raw[84 + 50*i: 84 + 50*(i+1)]
        vs = [struct.unpack_from("<fff", rec, 12 + 12*v) for v in range(3)]
        for x, y, z in vs:
            xs.append(x); ys.append(y); zs.append(z)
        a, b, c = vs
        u = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        v = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        cr = (u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0])
        if (cr[0]**2 + cr[1]**2 + cr[2]**2) ** 0.5 / 2 < 1e-9:
            degenerate += 1
        q = lambda t: (round(t[0], 4), round(t[1], 4), round(t[2], 4))
        for k in range(3):
            e = tuple(sorted([q(vs[k]), q(vs[(k+1) % 3])]))
            edges[e] = edges.get(e, 0) + 1
    assert degenerate == 0, f"{degenerate} zero-area triangle(s) -- slicers reject or mis-fill these"
    bad = [e for e, c in edges.items() if c != 2]
    assert not bad, (f"{len(bad)} edge(s) not shared by exactly two triangles -- the mesh is not "
                     f"watertight and will not slice into a solid part")

    span = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
    cfg, _rh = _engine(a_course())
    card_mm = cfg.CARD_W_IN * 25.4
    fits = [s for s in span if 0 <= s - card_mm <= 4.0]
    assert fits, (
        f"the binding measures {span[0]:.1f} x {span[1]:.1f} x {span[2]:.1f} mm and no axis is a "
        f"slide-on fit for a {card_mm:.1f} mm card (CARD_W_IN={cfg.CARD_W_IN}). Either the card size "
        f"changed and the STL did not, or the STL is not in millimetres -- a deck that does not go "
        f"into its binding is only discovered after an hour of printing")


def test_a_personal_aerial_reference_is_honest_about_what_it_is():
    """The aerial sheet is a shipped artifact that NO test touched, and it makes three claims.

    poppy-ridge is yardage mode -- no OSM geometry, blank greens -- so it ships an extra
    aerial_reference_PERSONAL.pdf: a NAIP photo of the course with its own full scorecard. It is
    outside CORPUS (no geometry), outside BOOKS (not a greenbook), and outside export_pdf's freshness
    stamp, so nothing verified any of it.

    Three things it must get right, each a live risk for this project:
      * imagery provenance. It is public-domain USDA NAIP, and it says so, and it states plainly that
        no Esri/Maxar, Google or Apple imagery was used. That sentence is the project's whole IP
        posture on one page; it must not quietly disappear.
      * the personal marking. It shows a PRE-2025 layout of a course rebuilt in 2025, so it is not
        merely undistributable, it is actively out of date. The filename says PERSONAL and so must the
        page.
      * its scorecard. It reprints all five tees hole by hole -- 90 yardages -- which is more tee
        detail than the book itself carries. Nothing checked them against course.json.
    """
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    sheets = sorted(glob.glob(os.path.join(ROOT, "courses", "*", "aerial_reference*.pdf")))
    if not sheets:
        pytest.skip("no aerial reference sheet built")
    for p in sheets:
        ref = os.path.basename(os.path.dirname(p))
        with fitz.open(p) as d:
            text = " ".join(d[i].get_text() for i in range(len(d)))
            text = " ".join(text.split())
            n_img = sum(len(d.get_page_images(i)) for i in range(len(d)))
        assert n_img >= 1, f"{ref}: the aerial sheet embeds no image at all"
        assert "NAIP" in text, f"{ref}: the aerial does not name its imagery source"
        assert re.search(r"public.domain", text, re.I), \
            f"{ref}: the aerial does not state that its imagery is public domain"
        assert re.search(r"No Esri/Maxar, Google, or Apple imagery", text), (
            f"{ref}: the aerial has lost the sentence disclaiming commercial imagery -- that line is "
            f"this project's IP posture stated on the page")
        assert "PERSONAL" in text, (
            f"{ref}: the sheet is named PERSONAL but the PAGE does not say so, and a printed page "
            f"outlives its filename")

        cj = os.path.join(ROOT, "courses", ref, "course.json")
        with open(cj, encoding="utf-8") as fh:
            course = json.load(fh)
        holes, ncol = course["holes"], len(course["hole_cols"])
        if "H Par HCP" not in text:
            continue                       # a sheet with no scorecard has nothing more to check
        nums = [int(x) for x in re.findall(r"\b\d+\b", text[text.index("H Par HCP"):])]
        rows, i = {}, 0
        while i + ncol < len(nums) and len(rows) < len(holes):
            if nums[i] == len(rows) + 1:
                rows[nums[i]] = nums[i+1:i+1+ncol]
                i += 1 + ncol
            else:
                i += 1
        assert len(rows) == len(holes), (
            f"{ref}: parsed {len(rows)} of {len(holes)} scorecard rows off the aerial")
        for hn, got in sorted(rows.items()):
            want = list(holes[str(hn)])
            assert got == want, (f"{ref} hole {hn}: the aerial's scorecard row {got} does not match "
                                 f"course.json {want} -- two artifacts of one course disagree")


@needs_corpus
def test_the_book_says_which_stroke_index_it_prints():
    """"HCP 15" appears on every card and decides where a player takes their handicap strokes.

    The data column is literally named mens_hcp, and the book printed "HCP" 19 times per copy without
    ever saying so. Many courses publish a DIFFERENT women's stroke index, so a girl using this book
    -- and this is a junior golf book, so half the intended readership -- would take her strokes on
    the wrong holes and not know it. Nothing was false; something necessary was simply unsaid, which
    is the same failure as the carry sentence and the dogleg sums.

    Fixed in prose that already existed, because the guide card is full: the About block already said
    "par, yardage & handicap are facts from the published scorecard", so it now names which handicap.

    Checked on the shipped HTML of BOTH editions -- the pocket and enlarged books carry separate legal
    blocks and only one of them getting the label is exactly how they have drifted before.
    """
    books = 0
    for ref in BOOKS:                      # BOOKS: poppy prints HCP too, and CORPUS excludes it
        for name in ("greenbook.html", "greenbook_coach.html"):
            p = os.path.join(ROOT, "courses", ref, name)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as fh:
                html = fh.read()
            if "HCP" not in html:
                continue                        # a book with no stroke index has nothing to label
            books += 1
            assert "stroke index" in html, (
                f"{ref}/{name} prints HCP on its cards but never says it is the MEN'S stroke index -- "
                f"a girl reading this book takes her strokes on the wrong holes")
            assert re.search(r"men.{0,8}s(</b>)? stroke index", html), (
                f"{ref}/{name} mentions a stroke index without saying whose")
    assert books >= 10, f"only {books} books checked -- build them first"


@needs_corpus
def test_the_scorecard_panel_agrees_with_every_hole_card():
    """Par, stroke index and yardage appear TWICE in each book -- on the hole card and in the
    scorecard panel -- and a junior allocates strokes off the scorecard while playing off the card.

    They came from different places. Every hole card headlines config.BACK_I, the tee the book is
    actually built on; scorecard_panel used config.FEATURED, which is only whichever of the pair
    course.json happens to name first. On 6 of 12 courses that is the FORWARD tee, so callippe's
    scorecard led "White / Black" with White's 6015 in the first column while every one of its cards
    headlined Black 6749 -- a 734 yd difference between two panels of one book. The title did name the
    order, so nothing was false; the reader simply had to notice the columns had swapped relative to
    the cards to find the one their book is built on.

    This is the same drift config.py's BACK_I comment describes -- one card is built on ONE tee -- in
    the last panel that had not been moved onto it.

    Checked field by field on the shipped HTML, because the defect was precisely a disagreement
    between two renderings of the same numbers.
    """
    checked, problems = 0, []
    for ref in BOOKS:                      # BOOKS, not CORPUS: this reads HTML, not geometry
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        cfg, _rh = _engine(ref)
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        cm = re.search(r'<div class="panel card">(.*?)(?=<div class="panel|\Z)', html, re.S)
        assert cm, f"{ref}: no scorecard panel in the book"
        title = re.search(r"Scorecard &mdash; ([^<]*)", cm.group(1))
        assert title, f"{ref}: the scorecard panel has no title naming its columns"
        lead = title.group(1).split("/")[0].strip()
        assert lead == cfg.BACK_NAME, (
            f"{ref}: the scorecard leads with {lead!r} but every hole card headlines "
            f"{cfg.BACK_NAME!r} -- two panels of one book disagree on which tee it is for")
        rows = {}
        for r in re.findall(r"<tr>(.*?)</tr>", cm.group(1), re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if len(cells) >= 4 and cells[0].isdigit():
                rows[int(cells[0])] = cells
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                # `hole ycard` too. poppy-ridge's yardage edition uses class="panel hole ycard", so
                # a startswith('hole"') filter silently skipped its 18 cards -- and it is the course
                # LEAST like the others, which is exactly where a check is worth most.
                continue
            hm = re.search(r'<div class="hnum">(\d+)</div>', blk)
            pm = re.search(r'<div class="par">PAR (\d+)</div>', blk)
            im = re.search(r'<div class="si">HCP (\d+)</div>', blk)
            ym = re.search(r'class="ymain"[^>]*>(\d+)</span>', blk)
            if not (hm and pm and im and ym):
                continue
            hn = int(hm.group(1))
            row = rows.get(hn)
            if not row:
                problems.append(f"{ref} hole {hn}: has a card but no row in the scorecard panel")
                continue
            checked += 1
            for label, card_val, sc_val in (("par", pm.group(1), row[1]),
                                            ("stroke index", im.group(1), row[2]),
                                            ("yardage", ym.group(1), row[3])):
                if card_val != sc_val:
                    problems.append(f"{ref} hole {hn}: the card says {label} {card_val}, the "
                                    f"scorecard panel says {sc_val}")
    # 216 = 12 courses x 18 holes. A floor of 150 passed happily while poppy-ridge's 18 cards were
    # being skipped by a too-narrow panel filter, so the floor now names the whole corpus.
    want = _expected_cards()
    assert checked == want, (f"{checked} cards checked but the built books hold {want} -- a course "
                             f"or a panel class is being skipped")
    assert not problems, ("the scorecard panel contradicts the hole cards:\n  "
                          + "\n  ".join(problems[:10]))


@needs_corpus
def test_a_printed_carry_never_overstates_what_it_clears():
    """"carry 224" is a number a junior clubs against off the tee, so it must err SHORT, never long.

    The figure is the near edge of fairway sand measured along the line from the back tee. Two
    separate ways it could mislead, and they point opposite ways:

      * Too LONG is dangerous. A carry printed further than the sand actually starts tells a player
        they have room they do not have. Checked by recomputing the near edge from only the polygon
        points that lie within 15 m of the line -- the sand genuinely in the ball's path -- and
        requiring the printed number never to exceed it. It does not: the printed value is
        conservative by a median 0 and up to 20 yd, because min() is taken over the whole polygon
        including parts up to 45 m off the line. Erring short is the right direction.

      * Too SHORT is only safe if the card does not promise otherwise, and it used to. The guide said
        "Clearing it needs more than N", which is false where the sand is long: the-reserve 8 prints
        "carry 90" for sand occupying the line from 92 to 201 yd on a 237-yd par 3, so clearing needs
        201. Sand runs a median 23 yd past the printed number and up to 126. The number is right --
        it is where the sand starts -- so the sentence was corrected rather than the figure.

    Also holds the stated window: 80-300 yd from the tee, and never within 40 yd of the green, since
    greenside sand is not a tee carry.
    """
    import math
    IN_LINE_M = 15.0
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        book = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(book):
            continue
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        assert "where fairway sand <b>starts</b>" in html and "can run well past N" in html, (
            f"{ref}: the guide no longer says the sand can run past the printed carry -- on "
            f"the-reserve 8 that is 111 yd of unstated sand")
        cfg, rh = _engine(ref)
        try:
            course, geom = rh.load()
        except Exception:
            continue
        import geo
        loc = cfg.COURSE.get("location") or {}
        try:
            lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
        except SystemExit:
            continue
        greens = [e for e in geom
                  if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        bunkers = [g for g in course
                   if (g.get("tags") or {}).get("golf") == "bunker" and g.get("geometry")]
        for hn, hole in sorted(lines.items()):
            line = hole["geometry"]
            try:
                _green, gend, tend = geo.match_green(line, greens)
                _svg, info = rh.render_hole(hn, cfg.HOLES)
            except Exception:
                continue
            carries = info.get("carries") or []
            if not carries:
                continue
            la0 = sum(q["lat"] for q in line) / len(line)
            lo0 = sum(q["lon"] for q in line) / len(line)
            def em(la, lo):
                return ((lo - lo0) * rh.mlon(la0), (la - la0) * rh.R_LAT)
            tee = em(tend["lat"], tend["lon"]); gc = em(gend["lat"], gend["lon"])
            L = math.hypot(gc[0] - tee[0], gc[1] - tee[1]) or 1.0
            ux, uy = (gc[0] - tee[0]) / L, (gc[1] - tee[1]) / L
            perp = (-uy, ux)
            card = info["card_yd"]
            for near, _far in carries:
                checked += 1
                seen_courses[ref] += 1   # past the gates: counts WORK, not intent
                if not (80 <= near <= 300):
                    problems.append(f"{ref} hole {hn}: carry {near} is outside the 80-300 yd window")
                if near > card - 40:
                    problems.append(f"{ref} hole {hn}: carry {near} on a {card} yd hole is greenside "
                                    f"sand, not a tee carry")
                in_line = None
                for g in bunkers:
                    al, of = [], []
                    for q in g["geometry"]:
                        e, n = em(q["lat"], q["lon"])
                        dx, dy = e - tee[0], n - tee[1]
                        al.append(dx*ux + dy*uy); of.append(dx*perp[0] + dy*perp[1])
                    if not al or abs(min(al) / 0.9144 - near) > 2:
                        continue
                    near_in = [a / 0.9144 for a, o in zip(al, of) if abs(o) <= IN_LINE_M]
                    if near_in:
                        in_line = min(near_in)
                if in_line is not None and near > in_line + 2:
                    problems.append(
                        f"{ref} hole {hn}: prints carry {near} but sand in the ball's path starts at "
                        f"{in_line:.0f} yd -- the card claims room the hole does not give")
    assert checked >= 50, f"only {checked} carries checked -- build the books first"
    assert_no_course_skipped(
        seen_courses, "test_a_printed_carry_never_overstates_what_it_clears",
        exempt={"bay-view-golf-club": "prints no carry on any hole -- nothing for this test to check"})
    assert not problems, "a printed carry overstates what it clears:\n  " + "\n  ".join(problems[:8])


@needs_corpus
@needs_corpus
def test_the_printed_height_is_measured_over_the_green_and_not_its_surroundings():
    """The green's height must come from the GREEN, not from the patch the green sits in.

    green_elevation() took the median of the whole dem_hd .npy, and that array is the green's bounding
    box padded by fetch_dem_hd.MARGIN_M = 12 m on every side -- a region 5.5x the green's area, of which
    a corpus-median 82% is not green. Because a green is usually a raised pad surrounded by fairway and
    bunker, the figure read LOW: the interior median is higher on 137 of 171 holes, mean +0.458 ft,
    one-sided at p = 2.7e-15. It moved 102 printed integers.

    The polygon was in the SAME meta file the whole time, and render_green.py rasterises it to measure
    every slope figure the card prints. So the test is a comparison between the two readers of one file:
    the recorded height must match the median over render_green's own mask, and must NOT match the median
    over the whole patch. Both directions matter -- the second is what fails if this ever regresses,
    and without it a test that only checked the first would also pass on the old code whenever the two
    happened to agree.

    Behavioural, not a grep: it re-derives the number from the .npy rather than asserting that
    green_elevation contains the word "polygon".
    """
    import numpy as np
    checked = agreed_with_patch = 0
    problems = []
    for slug in CORPUS:
        cdir = os.path.join(ROOT, "courses", slug)
        rp = os.path.join(cdir, "hole_elev.json")
        if not os.path.isfile(rp):
            continue
        os.environ["COURSE"] = slug
        for m in ("config", "geo", "render_green"):
            sys.modules.pop(m, None)
        import config                                    # noqa: F401
        import render_green as rg
        with open(rp, encoding="utf-8") as fh:
            rec = json.load(fh)["holes"]
        for hn, r in rec.items():
            gz = r.get("green_z_m")
            mp = os.path.join(cdir, "dem_hd", f"hole{int(hn):02d}.json")
            npy = mp.replace(".json", ".npy")
            if gz is None or not (os.path.isfile(mp) and os.path.isfile(npy)):
                continue
            with open(mp, encoding="utf-8") as fh:
                meta = json.load(fh)
            a = np.load(npy).astype(float)
            a[~np.isfinite(a)] = np.nan
            a[np.abs(a) > 1e30] = np.nan
            H, W = a.shape
            poly = rg.poly_to_px(meta["polygon"], meta["bbox"], W, H)
            mask = np.array([[rg.point_in_poly(c + 0.5, r_ + 0.5, poly) for c in range(W)]
                             for r_ in range(H)])
            if not mask.any() or np.all(np.isnan(a[mask])):
                continue
            checked += 1
            inside = float(np.nanmedian(a[mask]))
            whole = float(np.nanmedian(a))
            if abs(gz - inside) > 0.02:
                problems.append(f"{slug} hole {hn}: recorded green_z_m {gz:.2f} m is not the median over "
                                f"the green polygon ({inside:.2f} m). Whole-patch median is {whole:.2f} m "
                                f"-- if that is what it matches, the height is being taken over the green "
                                f"PLUS its 12 m collar again.")
            if abs(gz - whole) <= 0.02:
                agreed_with_patch += 1
    assert checked >= 150, f"only {checked} greens checked -- run fetch_hole_elev --write first"
    assert not problems, ("the recorded green height is not measured over the green:\n  "
                          + "\n  ".join(problems[:10]))
    # The anti-vacuous half: on the old code EVERY hole matched the whole-patch median, so a test that
    # only checked the first condition would have been just as green then as now on any hole where the
    # two coincide. They coincide on very few.
    assert agreed_with_patch <= checked // 4, (
        f"{agreed_with_patch} of {checked} recorded heights equal the WHOLE-PATCH median, which is what "
        f"the collar bug produced. Either the mask is not being applied or it is selecting the whole "
        f"array.")


@needs_corpus
def test_the_elevation_word_matches_the_elevation_sign():
    """"green 22 ft below" is a WORD derived from a signed number, and the word is what a golfer clubs
    off. Flip it and the book confidently sends the ball a full club short.

    tools/verify_elevation.py cross-checks the NUMBER against the 3DEP DEM, so a units fault or a
    wrong tee is caught. It never looks at the page, so the translation from -6.7 to "below" was
    unguarded end to end -- and that translation is the whole product of the elevation feature. A
    reader cannot tell a flipped word from a real hill; both read as a confident measurement.

    The chain is checked link by link against the artifacts:
      * change_m == green_z_m - tee_z_m, from the two absolute heights the record stores. This is the
        sign CONVENTION -- positive means the green sits higher, which is what "above" must mean.
      * change_ft is that in feet, within 0.07 (change_m is stored to 2 dp and change_ft to 1, so the
        double rounding alone allows 0.066 -- the corpus worst is 0.0614).
      * the printed word is "above" exactly when change_ft > 0, and the printed magnitude is
        abs(round(change_ft)).
      * a height under 3 ft prints NOTHING. That threshold is deliberate: a tee box's own contour
        justifies that much, so a small number would be false precision. It also means "nothing
        printed" is only correct BELOW it -- a suppressed 20 ft hill is a missing measurement, and
        this asserts both directions.
    """
    printed, level, problems = 0, 0, []
    for ref in CORPUS:
        book = os.path.join(ROOT, "courses", ref, "greenbook.html")
        ep = os.path.join(ROOT, "courses", ref, "hole_elev.json")
        if not (os.path.exists(book) and os.path.exists(ep)):
            continue
        with open(ep, encoding="utf-8") as fh:
            rec = json.load(fh)["holes"]
        for hn, r in rec.items():
            gz, tz, cm, cf = (r.get("green_z_m"), r.get("tee_z_m"),
                              r.get("change_m"), r.get("change_ft"))
            if None in (gz, tz, cm, cf):
                problems.append(f"{ref} hole {hn}: incomplete elevation record {sorted(r)}")
                continue
            if abs((gz - tz) - cm) > 0.02:
                problems.append(f"{ref} hole {hn}: change_m {cm} is not green {gz} minus tee {tz} "
                                f"({gz - tz:.2f}) -- the sign convention is broken at the source")
            if abs(cm * 3.28084 - cf) > 0.07:
                problems.append(f"{ref} hole {hn}: change_ft {cf} is not {cm} m in feet "
                                f"({cm * 3.28084:.2f})")
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                # `hole ycard` too. poppy-ridge's yardage edition uses class="panel hole ycard", so
                # a startswith('hole"') filter silently skipped its 18 cards -- and it is the course
                # LEAST like the others, which is exactly where a check is worth most.
                continue
            hm = re.search(r'<div class="hnum">(\d+)</div>', blk)
            if not hm:
                continue
            hn = hm.group(1)
            # the EXACT figure where the producer records it. Deriving truth from change_ft (0.1 ft)
            # invented ties the measurement never had: castlewood-valley 7 measures 8.478 ft, is stored
            # as 8.5, and this test then demanded the card print 9 -- enforcing a tie rule on a tie that
            # is purely an artifact of the storage precision. The card prints 8, correctly.
            _r = rec.get(hn, {})
            truth = _r.get("change_ft_exact")
            if truth is None:
                truth = _r.get("change_ft")
            pm = re.search(r"green <b>(\d+) ft (above|below)</b>", blk)
            if pm:
                printed += 1
                if truth is None:
                    problems.append(f"{ref} hole {hn}: prints {pm.group(0)!r} with no measurement "
                                    f"on record")
                    continue
                if abs(truth) < 3:
                    problems.append(f"{ref} hole {hn}: prints a height for {truth} ft, which is "
                                    f"inside the tee box's own contour and must read as level")
                want = "above" if truth > 0 else "below"
                if pm.group(2) != want:
                    problems.append(f"{ref} hole {hn}: prints \"{pm.group(1)} ft {pm.group(2)}\" "
                                    f"but the measurement is {truth:+.1f} ft -- the card is telling "
                                    f"a player to club the WRONG WAY")
                # The printed integer must be A rounding of the measurement -- floor or ceil of its
                # magnitude -- not equal to abs(round(truth)). Pinning Python's round() here made this
                # test enforce BANKER'S rounding, which is the defect: change_ft is stored to 0.1 ft, 17
                # holes hold a value ending in .5, and round() breaks those ties to the even integer, so
                # -21.5 printed 22 while -24.5 printed 24. One measurement, rounded two ways. The card
                # now rounds half away from zero; this checks the property (the integer is a rounding of
                # the number, off by less than 1) instead of re-implementing the rule it audits, and the
                # tie direction is pinned separately below.
                mag = abs(truth)
                if int(pm.group(1)) not in (math.floor(mag), math.ceil(mag)):
                    problems.append(f"{ref} hole {hn}: prints {pm.group(1)} ft against a measured "
                                    f"{truth:+.1f} -- that is not a rounding of the measurement")
                elif abs(mag - int(pm.group(1))) == 0.5 and int(pm.group(1)) < mag:
                    problems.append(f"{ref} hole {hn}: prints {pm.group(1)} ft for {truth:+.1f}, "
                                    f"rounding a tie TOWARD zero. Ties must go away from zero, or the "
                                    f"same .5 prints differently depending on the parity of the "
                                    f"integer beside it -- which is what banker's rounding did here.")
            elif truth is not None and abs(truth) >= 3:
                problems.append(f"{ref} hole {hn}: {truth:+.1f} ft measured but the card prints no "
                                f"height at all -- a real hill is missing from the page")
            elif truth is not None:
                level += 1
    assert printed >= 50, f"only {printed} elevation phrases checked -- build the books first"
    # 55 of 171 records fall under the 3 ft level threshold, so the printed count is ~2/3 of the
    # records; a floor on the RECORDS is what catches a skipped course.
    assert printed + level >= 150, (
        f"only {printed + level} elevation records reached ({printed} printed, {level} level) -- "
        f"a course is being skipped")
    assert level >= 10, f"only {level} holes exercised the level threshold"
    assert not problems, "the elevation figure and its word disagree:\n  " + "\n  ".join(problems[:10])


@needs_corpus
def test_a_from_tee_number_is_never_scaled_off_a_line_that_disagrees_with_the_card():
    """The drawn line and the scorecard are INDEPENDENT sources. Where they disagree, refuse.

    OSM supplies the centreline; the club supplies the yardage. Comparing them is the one genuinely
    independent check available on a printed distance, and across 198 holes they agree to a median
    1.2%, with 174 inside 5%.

    The 24 that differ by more than 5% are the interesting ones, and all of them are accounted for:
      * fwd_tee -- the line starts at a FORWARD tee, so it is legitimately short of the back-tee card
        (merion 9 is 69 yd short, merion 5 is 103). The shortfall is at the tee end, so the from-tee
        figure is still exact.
      * past_tee -- traced past the tee, the mirror case (castlewood-hill 4, 36 yd long).
      * par3_straight -- a short par-3 line, where from-tee is card minus to-green on a collinear hole
        and the line's length is never used (merion 3, 35 yd short).
      * neither, and then NO from-tee number is printed at all. castlewood-valley 10 and 18 are drawn
        497 and 385 against cards of 561 and 426, and their lengths match no published tee -- 497 sits
        between a 534 and a 460, 385 between a 352 and a 426 -- so the engine cannot tell where along
        the hole the missing yardage lives and prints nothing. That refusal is the correct answer, not
        a gap to be filled.

    So the invariant is not "the line matches the card". It is that a from-tee number is never SCALED
    off a line the card disagrees with: either an exact mechanism applies, or the gutter stays empty.
    Violating it would print a distance interpolated along a route that is not the route the yardage
    describes -- wrong by up to the shortfall at the tick nearest the tee.
    """
    checked, big, problems, seen, refused = 0, 0, [], collections.Counter(), []
    for ref in CORPUS:
        if not os.path.exists(os.path.join(ROOT, "courses", ref, "osm_geom.json")):
            continue
        cfg, rh = _engine(ref)
        seen[ref] += 1
        for hn in sorted(cfg.HOLES):
            try:
                svg, info = rh.render_hole(hn, cfg.HOLES)
            except Exception:
                continue
            checked += 1
            card, arc = info["card_yd"], info["arc_yd"]
            if not card:
                continue
            vbw = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
            printed = [txt for x, txt in re.findall(r'<text x="([\d.]+)"[^>]*>([^<]+)</text>', svg)
                       if float(x) >= vbw / 2 and txt.isdigit()]
            gap = abs(arc - card) / card * 100.0
            if gap <= 5.0:
                if not printed:
                    refused.append(f"{ref} h{hn}")
                continue
            big += 1
            exact = (info.get("fwd_tee") or info.get("past_tee") or info.get("par3_straight"))
            if not printed:
                refused.append(f"{ref} h{hn}")
            if printed and not exact:
                problems.append(
                    f"{ref} hole {hn}: the drawn line is {arc} yd against a card of {card} "
                    f"({gap:.0f}% apart) and no exact mechanism applies, yet it prints from-tee "
                    f"numbers {printed}. Those are interpolated along a route the yardage does not "
                    f"describe -- the gutter should stay empty instead.")
    assert checked >= 150, f"only {checked} holes compared -- build the books first"
    assert big >= 5, (f"only {big} holes disagree with their card by >5%, where 24 are expected -- "
                      f"either the corpus shrank or the comparison is not measuring what it did")
    # An empty gutter is correct where the line cuts a dogleg, but it is also what a REGRESSION looks
    # like: loosen a guard and holes stop printing from-tee numbers silently. 2 of 198 refuse today,
    # both castlewood-valley, both because their line is straight (arc/chord 1.000 and 1.038) against a
    # card that measures the corner. Pin the count so the refusal cannot quietly spread.
    assert len(refused) <= 4, (
        f"{len(refused)} holes print no from-tee number, against 2 expected: {refused[:8]}. Either a "
        f"guard has tightened or a course's centrelines have changed.")
    assert_no_course_skipped(seen, "test_a_from_tee_number_is_never_scaled_off_a_disagreeing_line")
    assert not problems, ("a printed from-tee distance rests on a line that contradicts the "
                          "scorecard:\n  " + "\n  ".join(problems[:8]))


@needs_corpus
def test_the_two_gutter_numbers_are_the_two_things_the_card_says_they_are():
    """A player can ADD the two numbers on a row. On a dogleg they will not reach the card yardage,
    and the guide has to say so, because the arithmetic is a twelve-year-old's first instinct.

    Left is the STRAIGHT distance to the green centre -- the shot you actually have to hit. Right is
    the distance from the tee WALKED along the centreline, which is how a scorecard measures. On a
    straight hole those sum to the card; on a bend they cannot, and the gap grows as the tick moves
    into the corner. philadelphia 17 is the extreme: card 472, drawn arc 441, and its 300-yd row
    reads 300 + 102 = 402. Both numbers are individually true. 50 of 196 cards have a row off by
    10 yd or more.

    Neither number may quietly become the other, so this asserts what each IS rather than that they
    agree:
      * the sums track the drawn ARC, not the card -- if left became a walked distance the sums would
        snap onto the card yardage and the printed to-green figure would overstate the shot by up to
        43 yd on a dogleg, which is the one number a player clubs off;
      * every to-green label is one of the fixed 100/150/200/250/300 radii, so left is a radius;
      * the guide card explains the mismatch, so a reader who adds them is not left thinking the
        book is broken.
    """
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        assert re.search(r"on a dogleg they do <b>not</b> add up", html), (
            f"{ref}: the guide card no longer explains why the two gutter numbers do not sum -- "
            f"a reader who adds them finds up to 54 yd of unexplained discrepancy")
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                # `hole ycard` too. poppy-ridge's yardage edition uses class="panel hole ycard", so
                # a startswith('hole"') filter silently skipped its 18 cards -- and it is the course
                # LEAST like the others, which is exactly where a check is worth most.
                continue
            ym = re.search(r'class="ymain"[^>]*>(\d+)</span>', blk)
            sm = re.search(r'<div class="lay"><div class="minilab">HOLE</div>(<svg.*?</svg>)',
                           blk, re.S)
            if not (ym and sm):
                continue
            svg = sm.group(1)
            vbw = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
            lanes = {}
            for x, y, txt in re.findall(
                    r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]+)</text>', svg):
                if txt.isdigit():
                    lanes.setdefault(round(float(y), 1), {})[
                        "L" if float(x) < vbw / 2 else "R"] = int(txt)
            card = int(ym.group(1))
            arc = _arc_yd_for(ref, blk) or card
            for v in lanes.values():
                if "L" not in v:
                    continue
                checked += 1
                seen_courses[ref] += 1   # past the gates: counts WORK, not intent
                if v["L"] not in (100, 150, 200, 250, 300):
                    problems.append(f"{ref}: a to-green label reads {v['L']}, which is not one of "
                                    f"the fixed radii -- it is no longer a straight-line distance")
                # The ceiling is max(card, arc), and finding that took two wrong guesses worth
                # recording. Bounding on the CARD flagged 115 legitimate rows: castlewood-valley 1 is
                # drawn 444 yd against a 429 card, so every row there exceeds the card by ~12. Bounding
                # on the ARC failed too, because the from-tee figure is scaled to the CARD, so on a
                # hole drawn shorter than its card the pair exceeds the arc. Only the larger of the two
                # is a real ceiling, and against it the whole corpus fits inside +4 yd -- which is the
                # rounding of two integers, not a measurement fault.
                limit = max(card, arc)
                if "R" in v and v["L"] + v["R"] > limit + 4:
                    problems.append(f"{ref}: a row reads {v['L']} + {v['R']} = {v['L']+v['R']} "
                                    f"against a card of {card} and a drawn line of {arc} yd -- past "
                                    f"both, so one of the two is measuring more than the hole")
    # ~4 rows a hole, so scale with the corpus rather than pinning 500 against an actual 830.
    assert checked >= 2 * expected_geometry_holes(), (
        f"only {checked} gutter rows checked across {expected_geometry_holes()} holes -- at under two rows a "
        f"hole, cards are being skipped")
    assert_no_course_skipped(seen_courses, "test_the_two_gutter_numbers_are_the_two_things_the_card_says_they_are")
    assert not problems, "the gutter numbers are not what the card says:\n  " + "\n  ".join(problems[:8])


@needs_corpus
def test_the_stated_green_depth_and_its_ladder_are_the_same_measurement():
    """"37yd deep" in the footer and the 5-yd rungs on the map must be measuring one green.

    A player uses them together: the footer to size the green at a glance, the ladder to place the
    pin within it. They are computed apart -- depth_yd from the polygon extent in the approach frame,
    the rungs by stepping 4.572/px_m from the front edge -- so nothing forced them to agree, and a
    disagreement is invisible on the page because each looks reasonable alone.

    The deepest rung must be a multiple of 5 lying within one rung of the stated depth: for a green
    printed as 37 yd deep the ladder ends at 35, and the rungs below it are every 5 yd from the front.

    The window is [depth-5, depth] rather than an exact value, and that is a real property of the two
    numbers, not slack for its own sake. The footer rounds -- int(round(depth_yd)) -- while the ladder
    walks the true float and stops strictly before the back edge. So a green measuring 29.6 yd prints
    "30yd deep" and DOES draw a rung at 30, while one measuring 30.4 also prints "30" and stops at 25.
    Both are right. Across the corpus 25 cards draw the back-edge rung and 227 do not, and the two
    groups are separated by nothing more than a sub-yard remainder the card never shows.

    Getting that wrong is how this test was first written -- as an exact identity that the 11 legitimate
    cards failed. Recorded because the tempting fix is to "correct" the engine to match the assertion.

    What the window still catches is everything that actually matters: rungs not stepped every 5 yd,
    a ladder measuring the width instead of the depth on a non-square green, a front/back swap, or a
    ladder stepped in metres -- all of which miss by more than one rung on most holes.
    """
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel ', html)[1:]:
            if not re.match(r'hole[\s"]', blk):
                # `hole ycard` too. poppy-ridge's yardage edition uses class="panel hole ycard", so
                # a startswith('hole"') filter silently skipped its 18 cards -- and it is the course
                # LEAST like the others, which is exactly where a check is worth most.
                continue
            hm = re.search(r'<div class="hnum">(\d+)</div>', blk)
            dm = re.search(r"(\d+)yd deep", blk)
            if not (hm and dm):
                continue
            rungs = [int(x) for x in re.findall(r'fill="#8a8a8a"[^>]*>(\d+)</text>', blk)]
            if not rungs:
                continue
            checked += 1
            seen_courses[ref] += 1   # past the gates: counts WORK, not intent
            depth, deepest = int(dm.group(1)), max(rungs)
            if not (depth - 5 <= deepest <= depth):
                problems.append(
                    f"{ref} hole {hm.group(1)}: footer says {depth}yd deep but the ladder's deepest "
                    f"rung is {deepest} -- more than one rung apart, so the two numbers are not "
                    f"measuring the same green")
            if sorted(rungs) != list(range(5, deepest + 1, 5)):
                problems.append(f"{ref} hole {hm.group(1)}: ladder rungs {sorted(rungs)} are not "
                                f"every 5 yd from the front edge")
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} cards checked of {expected_geometry_holes()} holes with geometry -- a course is being "
        f"skipped")
    assert_no_course_skipped(seen_courses, "test_the_stated_green_depth_and_its_ladder_are_the_same_measurement")
    assert not problems, ("the printed depth and the depth ladder disagree:\n  "
                          + "\n  ".join(problems[:8]))


@needs_corpus
def test_the_scale_bar_and_the_depth_ladder_agree_on_a_yard():
    """A green card states its scale twice. Both statements must mean the same yard.

    The printed 5-yd bar is the instrument tools/check_scale.py measures to prove Rule 4.3
    conformance -- the whole legal claim rests on that one rule being the length it says. The depth
    ladder is the other statement: rungs every 5 yd front-to-back, which is what a player actually
    steps off to judge how deep the pin is. They come from one expression today (4.572/px_m), so in
    VIEW units they agree by construction -- but that is the weak claim. What matters is the paper,
    where one is horizontal and the other vertical, and only a uniform scale keeps them equal.

    That is not guaranteed by anything upstream: the green raster is anisotropic by up to 0.85% (px_x
    vs px_y), the SVG is meet-fit into a box, and the card CSS can size it. If the bar and the ladder
    ever disagreed, one of two things is true -- either check_scale is certifying a ruler the map does
    not obey, or the ladder a golfer paces off is lying. Both are worse than a layout bug.

    Measured off the exported PDF, per card, pairing each bar with the ladder in ITS OWN card slot:
    median disagreement 0.02%, worst 1.10%. Bounded at 5% for glyph-centre and one-decimal rounding
    on rungs that can sit only ~15 pt apart; a genuine axis mix-up would show as a whole aspect
    ratio, far outside it.
    """
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    import statistics
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        pdf = os.path.join(ROOT, "courses", ref, "greenbook.pdf")
        if not os.path.exists(pdf):
            continue
        cfg, _rh = _engine(ref)
        cw, ch, gut = cfg.CARD_W_IN*72, cfg.CARD_H_IN*72, cfg.GUTTER_IN*72
        pw, ph = cfg.PAGE_W_IN*72, cfg.PAGE_H_IN*72
        gx0 = (pw - (cfg.COLS*cw + (cfg.COLS-1)*gut)) / 2
        gy0 = (ph - (cfg.ROWS*ch + (cfg.ROWS-1)*gut)) / 2
        slots = []
        for j in range(cfg.PER):
            r, c = divmod(j, cfg.COLS)
            x, y = gx0 + c*(cw+gut), gy0 + r*(ch+gut)
            slots.append(fitz.Rect(x, y, x+cw, y+ch))
        with fitz.open(pdf) as d:
            for page in d:
                spans = [sp for blk in page.get_text("dict")["blocks"]
                         for ln in blk.get("lines", []) for sp in ln.get("spans", [])]
                draws = page.get_drawings()
                for s in slots:
                    cap = [sp for sp in spans
                           if sp["text"].strip() == "5 yd" and s.contains(fitz.Rect(sp["bbox"]))]
                    if not cap:
                        continue
                    cb = fitz.Rect(cap[0]["bbox"])
                    bars = [dr["rect"].width for dr in draws
                            if s.contains(dr["rect"]) and dr["rect"].height <= 2.0
                            and dr["rect"].width >= 4
                            and abs(dr["rect"].y0 - cb.y1) < 12
                            and abs((dr["rect"].x0 + dr["rect"].x1)/2 - (cb.x0 + cb.x1)/2) < 40]
                    rungs = sorted(((fitz.Rect(sp["bbox"]).y0 + fitz.Rect(sp["bbox"]).y1)/2,
                                    int(sp["text"].strip()))
                                   for sp in spans
                                   if sp["text"].strip().isdigit() and sp["color"] == 0x8a8a8a
                                   and int(sp["text"].strip()) % 5 == 0
                                   and s.contains(fitz.Rect(sp["bbox"])))
                    rungs.sort(key=lambda t: t[1])
                    if not bars or len(rungs) < 3:
                        continue
                    gaps = [abs(rungs[i+1][0] - rungs[i][0]) / ((rungs[i+1][1] - rungs[i][1]) / 5)
                            for i in range(len(rungs)-1) if rungs[i+1][1] != rungs[i][1]]
                    if not gaps:
                        continue
                    bar, lad = max(bars), statistics.median(gaps)
                    checked += 1
                    seen_courses[ref] += 1   # past the gates: counts WORK, not intent
                    off = abs(bar - lad) / lad * 100
                    if off > 5.0:
                        problems.append(
                            f"{ref}: the printed 5 yd bar is {bar:.1f} pt but the depth ladder puts "
                            f"5 yd at {lad:.1f} pt ({off:.0f}% apart) -- either Rule 4.3 is being "
                            f"certified against a ruler the map does not obey, or the ladder a "
                            f"golfer paces off is wrong")
    assert checked >= expected_geometry_holes() - 36, (
        f"only {checked} greens compared of {expected_geometry_holes()} holes with geometry -- yardage-mode books "
        f"print no scale bar, but two courses' worth of absence means something is being skipped")
    assert_no_course_skipped(seen_courses, "test_the_scale_bar_and_the_depth_ladder_agree_on_a_yard")
    assert not problems, "the card's two scale statements disagree:\n  " + "\n  ".join(problems[:8])


def test_a_fresh_clone_gets_a_clean_suite():
    """The README promises `pytest tests/` "skip cleanly with no course data". Enforce that promise.

    courses/ is gitignored, so a stranger who clones this repo has the engine and none of the data.
    If the suite greets them with failures, the repo looks broken through no fault of theirs, and
    they cannot tell our red from their red. That mattered enough that gen_provenance.py carries the
    same fix ("no courses is not the same as stale") and this file already has needs_corpus, a_course()
    and an autouse COURSE binder -- whose docstring records this exact crash happening before.

    This test used to look for the fault in the SOURCE: it listed the ways a test reaches per-course
    data (_engine(, CORPUS[, `for x in CORPUS`) and demanded a skip on each. That is a proxy, and it
    failed exactly as a proxy does -- three tests reached the corpus a fourth way, globbing courses/
    directly, and so failed on a fresh clone while this test, whose whole job is to prevent that,
    passed. Widening the pattern list then produced two FALSE positives, tests that skip on absent data
    through an inline pytest.skip the pattern could not see. A heuristic that both misses and
    over-reports is not worth tuning.

    So it now performs the actual experiment: copy every tracked file into a temp tree, leave courses/
    empty, and run the suite there. Whatever a stranger would see, this sees. No pattern to keep in
    step with, and a new way of reading course data is covered the day it is written.

    Cheap because it is measuring the empty case: with no corpus almost everything skips and the child
    run takes about a second.
    """
    if os.environ.get("GREENBOOK_FRESH_CLONE_CHILD"):
        pytest.skip("child run of the fresh-clone experiment; would recurse")
    import shutil
    import subprocess
    import tempfile
    try:
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                                 capture_output=True).stdout.split(b"\0")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout, cannot enumerate a fresh clone")
    files = [f.decode() for f in tracked if f]
    assert any(f.startswith("tests/") for f in files), "no tests are tracked; nothing would run"
    assert not any(f.startswith("courses/") for f in files), (
        "a file under courses/ is TRACKED. Per-course data and generated books must never be "
        "committed -- that is the standing rule for this repo, and it also means a fresh clone would "
        "carry data this test assumes absent.")

    tmp = tempfile.mkdtemp(prefix="greenbook-freshclone-")
    try:
        for f in files:
            src = os.path.join(ROOT, f)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(tmp, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        os.makedirs(os.path.join(tmp, "courses"), exist_ok=True)
        env = dict(os.environ, GREENBOOK_FRESH_CLONE_CHILD="1")
        env.pop("COURSE", None)
        env.pop("COLD_BUILD", None)
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line", "-p",
                            "no:cacheprovider"], cwd=tmp, env=env, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        failed = re.findall(r"^FAILED (\S+)", out, re.M) or re.findall(r"^(\S+::\S+) FAILED", out, re.M)
        passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1])
        skipped = int((re.search(r"(\d+) skipped", out) or [0, 0])[1])
        assert passed + skipped > 50, (
            f"the fresh-clone run collected almost nothing ({passed} passed, {skipped} skipped), so it "
            f"proved nothing. Tail:\n{out[-1500:]}")
        assert r.returncode == 0, (
            "a fresh clone of this repo does NOT get a clean suite. A stranger with no course data "
            f"sees {len(failed)} failure(s) and cannot tell our red from their red:\n  "
            + "\n  ".join(f.split("::")[-1] for f in failed[:12])
            + "\n\n  A test that reads per-course data needs BOTH an anti-vacuous floor (assert it "
              "checked something) AND a skip when there is nothing to check -- @needs_corpus, "
              "a_course(), or an explicit pytest.skip. Those are different jobs.\n\n"
            + out[-1200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_nine_hole_course_is_a_first_class_course(tmp_path):
    """Junior golf is played on nine-hole courses, and the README invites people to add their own.

    Everything about this engine is written around eighteen -- the corpus is twelve 18-hole courses,
    the scorecard prints OUT and IN, par sums are checked against 72 in the wild. A hardcoded 18
    anywhere would make the engine useless for exactly the audience the book is for, and nothing in
    the suite ever built a nine.

    It works, and this pins the parts that would break first if someone assumed eighteen:
      * config.NHOLES follows the file rather than a constant;
      * the stroke index is validated as a permutation of 1..N, not 1..18;
      * the scorecard collapses OUT/IN into one total, since a nine has no back nine to sum;
      * par is checked against the file's own declared par, not against 72.

    Built from a JSON fixture in tmp_path, so it runs on a fresh clone with no course data. That
    matters more than usual here: the whole point is the newcomer's first course, and a check that
    only runs where twelve courses already exist would never see their situation.
    """
    holes = {str(h): (4 if h % 3 else 3, 0, 380 - 6*h, 350 - 6*h) for h in range(1, 10)}
    order = sorted(holes, key=lambda k: -holes[k][2])
    for rank, k in enumerate(order, 1):
        v = list(holes[k]); v[1] = rank; holes[k] = v
    cj = {
        "slug": "nine", "name": "Nine Hole Test", "holes_count": 9,
        "hole_cols": ["par", "mens_hcp", "Black", "White"],
        "holes": holes,
        "par": sum(v[0] for v in holes.values()),
        "tees": [{"name": "Black", "yards": sum(holes[k][2] for k in holes),
                  "rating": 35.2, "slope": 118},
                 {"name": "White", "yards": sum(holes[k][3] for k in holes),
                  "rating": 34.0, "slope": 112}],
        "location": {"lat": 40.0, "lon": -75.0},
    }
    errs = _check_course(cj, "nine-hole fixture")
    assert not errs, "a valid nine-hole scorecard was rejected:\n  " + "\n  ".join(errs)

    # ...and the same file with an 18-hole assumption baked in must FAIL, or the check above is
    # only passing because it never looks at N.
    bad = dict(cj, holes=dict(cj["holes"]))
    bad["holes"]["1"] = [cj["holes"]["1"][0], 14] + list(cj["holes"]["1"][2:])   # hcp 14 on a nine
    assert _check_course(bad, "nine with an 18-hole handicap"), \
        "a handicap of 14 on a nine-hole card must be rejected -- the permutation is 1..9"

    # config.py resolves courses/ relative to the repo, with no override, so binding a tmp_path
    # course would mean either writing into the real courses/ (which the suite must never do) or
    # adding a test-only env hook to production code. _check_course is the gate every course.json
    # passes and is where an 18-hole assumption would live, so exercising it directly is the honest
    # coverage; NHOLES is asserted separately below against the corpus.
    assert "len(HOLE_NUMS)" in open(os.path.join(ROOT, "config.py"), encoding="utf-8").read(), \
        "NHOLES must be derived from the file's own holes, never a constant"
    gen = open(os.path.join(ROOT, "generate.py"), encoding="utf-8").read()
    # Anchored on scorecard_panel's OWN branch. This used to match "config.NHOLES <= 9", which lived
    # in the thumb-tab code and had nothing to do with the scorecard -- so the assertion passed for the
    # wrong reason for as long as that unrelated line happened to exist, and only broke when the tab
    # code was rewritten. A proxy string is not the thing.
    sc = gen[gen.index("def scorecard_panel"):]
    sc = sc[:sc.index("\ndef ")]
    assert "len(nums) <= 9" in sc, \
        "scorecard_panel must collapse OUT/IN into one Total for a nine-hole card"
    assert "no front/back split" in sc, \
        "the nine-hole scorecard branch must say why it has no front/back split"


def test_nothing_tracked_carries_a_work_identity_or_a_home_path():
    """This repo is PUBLIC. Nothing in it may carry a work identity, an employer domain, or a path
    that only exists on one laptop.

    Two of the three have already happened on this project: a work email reached two public repos and
    had to be scrubbed out of their history, and a `courses` SYMLINK created by a git worktree slipped
    past the `courses/` ignore rule -- which matches a directory, not a link -- so `git add -A` would
    have committed a machine-specific absolute path. Both were caught by hand. History rewrites and
    support tickets are the expensive way to find this; a test is the cheap way.

    An absolute home path is not only an identity leak, it is a bug: a tool that hardcodes one cannot
    run on anyone else's machine, and this repo is meant to be cloned.

    Scans TRACKED files only, so it follows .gitignore rather than duplicating it -- courses/ and
    local scratch stay out of scope by definition.
    """
    import subprocess
    try:
        listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=60)
    except Exception as e:                       # not a git checkout (tarball, vendored copy)
        pytest.skip(f"git unavailable: {e}")
    if listing.returncode != 0:
        pytest.skip("not a git checkout")
    files = [f for f in listing.stdout.split("\0") if f]
    assert len(files) > 10, f"only {len(files)} tracked files -- the scan would prove nothing"

    patterns = [
        (re.compile(r"/Users/[A-Za-z0-9_.-]+"), "an absolute home path (also unrunnable elsewhere)"),
        (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]*apple\.com", re.I), "a work email address"),
        (re.compile(r"\b(?:luyao[a-z_]*|lu9999|luyao-wu)\b", re.I), "a work username"),
        (re.compile(r"\b[a-z0-9.-]*\.apple\.com\b", re.I), "an internal hostname"),
    ]
    problems = []
    for rel in files:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue                              # a submodule or a broken link
        try:
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
        except (UnicodeDecodeError, OSError):
            continue                              # binary asset
        if os.path.abspath(path) == os.path.abspath(__file__):
            # This file necessarily SPELLS the things it hunts for. Skipping it entirely would be a
            # hole, so instead drop only the lines that build the pattern list, and scan the rest.
            body = "\n".join(ln for ln in body.splitlines() if "re.compile(" not in ln)
        for rx, what in patterns:
            for hit in sorted(set(rx.findall(body)))[:3]:
                if "@apple.com" in hit.lower() or not hit.lower().endswith("example.com"):
                    problems.append(f"{rel}: {what} -- {hit!r}")
    assert not problems, ("tracked files in a PUBLIC repo carry identity or machine-specific "
                          "details:\n  " + "\n  ".join(sorted(set(problems))[:12]))


def test_the_3_ft_elevation_floor_sees_the_measurement_not_a_display_value():
    """The 3 ft floor was compared against a figure already rounded to 0.1 ft, so a hole measured at
    2.956 ft was stored as 3.0 and printed "green 3 ft above" -- a number the floor exists to forbid.

    Two cards were doing it: micke-grove 6 at +2.956 ft and the-reserve 10 at -2.952 ft. That floor is
    not a style choice. generate.py argues at length that below 3 ft two honest sources -- this
    pipeline and the 3DEP seamless DEM -- disagree by more than the figure itself, so printing one
    would be the confident-but-unsupported number this book exists not to print.

    The same double-round moved three other cards by a whole foot (castlewood-valley 7 printed 9 for
    8.478, copper-valley 14 printed 44 for 43.470, copper-valley 17 printed 49 for 48.486), because
    round(x, 1) pushed them onto a .5 that the display rounding then carried away from zero. 17 of 171
    holes hold a stored value ending in .5, so a tenth of the corpus was exposed.

    Fixed by recording change_ft_exact beside change_ft and gating on the exact value. Asserted here
    against BOTH: no printed figure may come from a hole under the floor, and every printed figure
    must match the unrounded measurement.
    """
    import math as _math
    floor_ft, checked, problems = 3.0, 0, []
    seen = collections.Counter()
    for slug in CORPUS:
        rec_path = os.path.join(ROOT, "courses", slug, "hole_elev.json")
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not (os.path.isfile(rec_path) and os.path.isfile(book)):
            continue
        with open(rec_path, encoding="utf-8") as fh:
            holes = (json.load(fh).get("holes") or {})
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        for hn, v in holes.items():
            exact = v.get("change_ft_exact")
            if exact is None:
                continue               # record predates the exact field; the fallback path is tested below
            checked += 1
            seen[slug] += 1
            want = ("" if abs(exact) < floor_ft
                    else f'green <b>{_math.floor(abs(exact) + 0.5)} ft '
                         f'{"above" if exact > 0 else "below"}</b>')
            # what the book actually prints for this hole
            blk = next((b for b in re.split(r'<div class="panel hole', html)[1:]
                        if re.search(rf'class="hnum">{int(hn)}</div>', b)), "")
            blk = re.split(r'<div class="panel ', blk)[0]
            got = re.search(r"green <b>\d+ ft (?:above|below)</b>", blk)
            got = got.group(0) if got else ""
            if got != want:
                problems.append(
                    f"{slug} h{hn}: measured {exact:+.3f} ft, card prints {got or 'nothing'!r}, "
                    f"expected {want or 'nothing'!r}")
    if not checked:
        pytest.skip("no course records change_ft_exact yet")

    # ...and the ENGINE must agree, not only the shipped book. Comparing HTML alone catches a stale
    # book but not a re-introduced gate bug: putting the threshold back on the rounded value left this
    # green, because the books on disk were already correct. Re-render the phrase from the live engine
    # for the two holes that sit within a rounding step of the floor, which is where the bug lived.
    near = [(sl, hn, ex) for sl in CORPUS
            for hn, ex in [(k, (v or {}).get("change_ft_exact"))
                           for k, v in _elev_rows(sl).items()]
            if ex is not None and 2.5 <= abs(ex) < 3.5]
    assert near, "no hole sits near the 3 ft floor, so the gate cannot be exercised"
    for slug, hn, exact in near:
        os.environ["COURSE"] = slug
        for m in ("config", "generate"):
            sys.modules.pop(m, None)   # generate reads hole_elev.json at IMPORT time into HOLE_ELEV
        import generate as _g
        phrase = _g.elev_phrase(int(hn))
        expect_blank = abs(exact) < 3.0
        assert bool(phrase.strip()) != expect_blank, (
            f"{slug} h{hn}: measured {exact:+.3f} ft and the engine "
            f"{'printed' if phrase.strip() else 'suppressed'} it -- the 3 ft floor is being applied to "
            f"a rounded display value, not to the measurement")
    for m in ("config", "generate"):
        sys.modules.pop(m, None)       # leave no rebound module for the next test
    assert not problems, (
        "printed elevation disagrees with the measurement, or breaches the 3 ft honesty floor:\n  "
        + "\n  ".join(problems[:8]))
    # No exemption for poppy-ridge: it has no geometry on disk, so geometry_courses() never names it
    # and the guard already ignores it. An exemption for a course outside the checked set is itself a
    # hazard -- it reads as covering something and covers nothing.
    assert_no_course_skipped(
        seen, "test_the_3_ft_elevation_floor_sees_the_measurement_not_a_display_value")


def test_a_bigger_clock_glitch_is_never_easier_to_publish_than_a_smaller_one():
    """The flight-date trimmer's reliability INVERTED with the size of the corruption: 8 junk readings
    were trimmed with a warning, 9 were refused, and 10 published silently with n_dropped = 0.

    Support was measured at a fixed offset of MAX_ISOLATED_VALUES + 1 positions, so a cluster LARGER
    than that window vouched for ITSELF -- with 10 junk readings, position 0 found its supporter at
    j = 9, still inside the junk and 0.09 s away. The walk then returned the extreme value and reported
    nothing dropped, so neither the warning nor the refusal fired. A 100-point cluster published a date
    two decades from the flight, and `--write` puts that label on EVERY card and into legal/03.

    This is the third time this function has published a wrong date, and each previous fix moved a
    threshold. This one asserts the PROPERTY instead: refusal must be monotonic in corruption, so no
    cluster size can ever be easier to publish than a smaller one. A fix that merely bumps the window
    fails here at window + 1.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ld_probe", os.path.join(ROOT, "tools", "lidar_dates.py"))
    ld = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ld)
    cls = next(o for o in vars(ld).values() if isinstance(o, type) and hasattr(o, "_resolve"))
    base = 1024358400.0                                   # a real GPS-adjusted flight second
    bulk = [base + i * 0.01 for i in range(2000)]         # a genuine pass: thousands of contiguous pts

    def outcome(k, off_days):
        """(published?, n_dropped) for k junk readings off_days from the bulk."""
        vals = sorted([base + off_days * 86400.0 + i * 0.01 for i in range(k)] + bulk)
        got = cls._resolve(cls.__new__(cls), vals)
        return (False, None) if got is None else (True, got[1])

    for off in (-700, -365, -100, -2, 700):
        published = [k for k in range(0, 41) if outcome(k, off)[0]]
        refused = [k for k in range(0, 41) if not outcome(k, off)[0]]
        if not refused:
            continue                    # this offset is inside the tolerated glitch window throughout
        # everything published must be SMALLER than everything refused: no re-entry at a larger k
        assert max(published) < min(refused), (
            f"at {off:+d} days the trimmer publishes a date for {max(published)} junk readings but "
            f"refuses {min(refused)} -- reliability inverts with the size of the corruption, so a "
            f"BIGGER clock fault is easier to publish than a smaller one")

    # and a published date must never come from the junk itself: a trimmed run reports what it dropped
    for k in range(1, ld.MAX_ISOLATED_VALUES + 1):
        ok, dropped = outcome(k, -700)
        assert ok and dropped == k, (
            f"{k} junk readings 700 days from the bulk: expected them all trimmed and counted, got "
            f"published={ok} dropped={dropped}. n_dropped is what drives the warning, so a silent 0 "
            f"means the card carries a date nobody was told to check.")


def test_the_steepness_colour_still_reads_in_black_and_white():
    """The slope ramp is the only thing in the book carrying information no word repeats, and it used
    to invert on a mono printer -- which is how a junior actually prints this.

    The old ramp went green -> pale yellow -> red, brightening to the 2.5% midpoint before darkening.
    Its grey value FOLDED: 0.00% and 3.65% both printed grey 170, and 26% of all heat cells in the
    shipped books collided with a slope at least 1.5 points different. The legend inverted too -- a
    3.6% cell matched the FLAT swatch, so the book actively told a junior that steep ground was level.

    Asserts the property, not the constants: luminance must fall monotonically across the whole
    interpolated range, and two slopes 1.5 points apart must be separated by enough grey to tell
    apart. Written against the ramp's OUTPUT so any future restyle is free to change the hues.
    """
    cfg, _rh = _engine(a_course())
    import render_green

    def lum(pct):
        r, g, b = map(int, re.findall(r"\d+", render_green.heat_color(pct)))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    ls = [lum(i / 100.0) for i in range(0, 501)]
    reversals = [(i / 100.0, ls[i], ls[i + 1]) for i in range(len(ls) - 1) if ls[i + 1] > ls[i] + 0.4]
    assert not reversals, (
        f"the steepness ramp gets LIGHTER as it gets steeper at {len(reversals)} points, starting at "
        f"{reversals[0][0]:.2f}% ({reversals[0][1]:.0f} -> {reversals[0][2]:.0f} grey). On a mono "
        f"printer that makes steep ground impersonate flat ground.")

    # a reader must be able to tell 1.5 percentage points apart in grey alone
    sep = min(ls[i] - ls[i + 150] for i in range(len(ls) - 150))
    assert sep >= 6.0, (
        f"two slopes 1.5 points apart differ by only {sep:.1f} grey levels at the worst point -- "
        f"indistinguishable in a home mono print")

    # and the legend swatches must be the ramp's own output, not a hardcoded copy that can drift
    src = _code_only(open(os.path.join(ROOT, "generate.py"), encoding="utf-8").read())
    assert "heat_color" in src, (
        "generate.py hardcodes the legend swatches instead of calling render_green.heat_color -- "
        "they printed the OLD ramp's colours after the ramp was fixed, so the key disagreed with "
        "the map it explains")


def test_the_published_tile_count_is_exactly_what_is_on_disk():
    """The tile count is a published claim about the LiDAR behind a book, and it must be a fact rather
    than an estimate that drifts.

    Two attempts to count only what the build READ both failed. Filtering on mtime against the newest
    LiDAR-derived artifact first looked right -- callippe showed 10 files against a correct 7, three
    fetched by an audit the build never saw. Then the count swung to 11 the moment fetch_hole_elev
    re-ran, because the TEE STAGE DOWNLOADS TILES AS IT RUNS: five of callippe's twelve are its own,
    over tees outside every green's tile. So a filtered count moves with WHEN the stages last ran
    rather than with what they read, and it moved in the overstating direction.

    No stage records its inputs, so "used" is not recoverable from the artifacts. The published number
    is therefore what is on disk, labelled "tiles held" so it claims presence and nothing about use.
    This asserts both halves: the number matches the directory exactly, and the wording does not
    promise more than the number can support.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gp_prov", os.path.join(ROOT, "tools", "gen_provenance.py"))
    gp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gp)

    doc = os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")
    if not os.path.isfile(doc):
        pytest.skip("provenance doc not generated")
    with open(doc, encoding="utf-8") as fh:
        body = fh.read()

    seen = collections.Counter()
    for slug in CORPUS:
        cdir = os.path.join(ROOT, "courses", slug)
        tiles = glob.glob(os.path.join(cdir, "*.laz")) + glob.glob(os.path.join(cdir, "laz", "*.laz"))
        if not tiles:
            continue                   # seamless-DEM course, or tiles kept outside the repo
        seen[slug] += 1
        _proj, n, _from_names = gp._tile_project(slug)
        assert n == len(tiles), (
            f"{slug}: the generator counts {n} tiles but {len(tiles)} .laz files are on disk. The "
            f"published number must be exactly what is there -- every attempt to publish a cleverer "
            f"number has drifted, and drifted upward.")

        with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as jf:
            name = json.load(jf).get("name", slug)
        row = next((ln for ln in body.splitlines() if ln.startswith(f"| {name} |")), None)
        if row is None or "tiles" not in row:
            continue                   # course not distributed, so it has no row to check
        m = re.search(r"\((\d+) tiles held\)", row)
        assert m, (
            f"{slug}: the provenance row states a tile count without the word 'held': {row[:160]}. "
            f"The count is what is on disk, not what the build consumed -- no stage records its "
            f"inputs -- so the wording must not imply otherwise.")
        assert int(m.group(1)) == n, (
            f"{slug}: the generator counts {n} tiles but the published doc says {m.group(1)} -- "
            f"regenerate legal/03_PROVENANCE_BY_COURSE.md")
    # SKIP, not fail, when a fresh clone has no course data: an anti-vacuous floor and a
    # nothing-to-check skip are different jobs, and a stranger must be able to tell our red from
    # theirs. The floor is the per-course assertions above, which cannot pass without a real count.
    if not seen:
        pytest.skip("no course has local tiles")

def test_no_commit_carries_a_work_identity():
    """The same rule as the tracked-file scan, applied to the COMMIT METADATA -- the vector that
    actually caused the incident that test's own docstring describes.

    A work email "reached two public repos and had to be scrubbed out of their history". It did not get
    there in a file. It got there as the AUTHOR of a commit, because the machine-wide git identity is an
    employer address and an `includeIf` for this directory was the eventual fix. Scanning file contents
    would never have found it -- `git log --format=%ae` is where it lived, and a history rewrite plus
    support tickets to two hosts is what removing it cost.

    So this checks author, committer, and message on every reachable commit. The message matters too: a
    branch name carrying the work account, quoted in a commit body, is published just as surely as a
    filename, and it names the work account.

    Deliberately NOT limited to unpushed commits. What is already public is what most needs finding --
    that is the case that costs a rewrite -- and reporting it is the only way it gets fixed.
    """
    import subprocess
    try:
        log = subprocess.run(
            ["git", "log", "--all", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%s%n%b%x1e"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
    except Exception as e:                       # not a git checkout (tarball, vendored copy)
        pytest.skip(f"git unavailable: {e}")
    if log.returncode != 0:
        pytest.skip("not a git checkout")
    commits = [c for c in log.stdout.split("\x1e") if c.strip()]
    assert len(commits) > 10, f"only {len(commits)} commits parsed -- the scan would prove nothing"

    # \b does not fire between "/" and a letter the way it does at a space, and the work username
    # appears in exactly that position in a branch name, so match it without leaning on a word break.
    work = re.compile(r"(?:luyao[a-z0-9_.-]*|lu9999|luyao-wu)|[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]*apple\.com",
                      re.I)
    problems = []
    for entry in commits:
        parts = entry.strip().split("\x1f")
        if len(parts) < 6:
            continue
        sha, an, ae, cn, ce, msg = parts[0][:8], parts[1], parts[2], parts[3], parts[4], parts[5]
        for field, val in (("author", f"{an} <{ae}>"), ("committer", f"{cn} <{ce}>"), ("message", msg)):
            for hit in sorted(set(work.findall(val)))[:2]:
                problems.append(f"{sha} {field}: {hit!r}")
    assert not problems, (
        "commit(s) in a PUBLIC repo carry a work identity. Metadata is published exactly as file "
        "contents are, and this is how a work email reached two public repos before:\n  "
        + "\n  ".join(sorted(set(problems))[:12]))


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
    slug = "_synth_ticks"                       # scratch, per distribution.is_corpus_slug
    # The leading underscore is not self-enforcing -- glob("courses/*/course.json") matches it
    # happily, and tools/cross_flight_check.py had no filter at all until this comment was
    # checked. The convention now has one implementation that every audit tool shares.
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
        # RESTORE FIRST, then clean up. The order was the other way round, and it made this fixture a
        # source of flaky, order-dependent failures elsewhere in the file: os.rmdir raises if ANYTHING
        # is left in the directory (a dem_hd/ a test wrote, a stray file), and the raise skipped the
        # restore -- leaving COURSE bound to a slug whose course.json had just been deleted. Every later
        # test that binds a course then died with "no course.json for COURSE='_synth_ticks'", which is
        # exactly the symptom seen: three unrelated green tests failing in a full run and passing in
        # isolation. Restoring first cannot fail, and shutil.rmtree does not care what is in the way.
        _restore_course(prev)
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)


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
            card = config.HOLES[hn][config.BACK_I]   # not column 0
            for t in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg):
                labels += 1
                if int(t) > card:
                    bad.append((slug, hn, int(t), card))
    _assert_examined(holes, labels, errors, "tick-vs-card sweep")
    assert not bad, f"ticks further from the green than the hole is long: {bad}"


@needs_corpus
def test_par3_exact_from_tee_rule():
    """The straightness guard on the exact par-3 from-tee derivation, tested DIRECTLY.

    The corpus cannot exercise it: its only non-straight par 3 (copper-valley 13, arc/chord 1.0237)
    happens to agree with the proportional value within 2 yd, so deleting the guard changes no
    printed number and every corpus sweep still passes. Verified by mutation -- removing the guard
    left the from-tee sweep green, which is exactly the kind of hole this file exists to close."""
    _config, render_hole = _engine(CORPUS[0])
    f = render_hole.par3_exact_from_tee
    assert f(3, 100.0, 100.0)          # dead straight par 3 -> collinear, derivation is exact
    assert f(3, 101.9, 100.0)          # inside the 2% slack for vertex noise
    assert not f(3, 102.1, 100.0)      # a par 3 cannot bend: this is bad data, so refuse
    assert not f(4, 100.0, 100.0)      # par 4/5 card follows a played route that can dogleg
    assert not f(5, 100.0, 100.0)
    assert not f(3, 100.0, 0.0)        # degenerate chord must not fall through to True


@needs_corpus
def test_carries_are_measured_from_the_back_tee():
    """A carry is the number a player actually clubs against, so it must be from the BACK tee.

    Every along-line distance in render_hole is measured from where the drawn line starts, and on a
    forward-tee hole that is the forward tee. Unshifted, merion 5 printed "carry 173" for sand that is
    nearer 276 from the Championship tee -- understating the one number a club is chosen against by
    103 yd, which is worse than the empty gutter beside it.

    The invariant: on a forward-tee hole every printed carry must clear (tee-to-tee gap + the 80 yd
    reach floor), because the floor is applied to the UNSHIFTED distance and the gap is then added. An
    unshifted carry cannot satisfy that. The floor is checked unshifted on purpose -- shifting first
    swept in sand lying BEHIND the forward tee (merion 5 grew a "carry 81" from a bunker 22 yd back
    down its own line), where the back tee's unknown lateral offset makes the shift meaningless."""
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        for hn in config.HOLE_NUMS:
            try:
                _svg, info = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue
            if not info.get("fwd_tee") or not info.get("carries"):
                continue
            gap = info["card_yd"] - info["arc_yd"]
            floor = gap + 80.0 - 1.0                     # 1 yd of rounding slack
            worst = min(c[0] for c in info["carries"])
            assert worst >= floor, (
                f"{slug} h{hn}: carry {worst} is below {floor:.0f} (gap {gap} + 80 yd reach), so it "
                f"was measured from the forward tee, not the back tee")
            # and the greenside rule must be judged on the same back-tee scale
            for near, _far in info["carries"]:
                assert near <= info["card_yd"] - 40, \
                    f"{slug} h{hn}: carry {near} is greenside sand on a {info['card_yd']} yd hole"

    if "merion-golf-club" in CORPUS:
        config, render_hole = _engine("merion-golf-club")
        _svg, i5 = render_hole.render_hole(5, config.HOLES)
        assert i5["carries"] and min(c[0] for c in i5["carries"]) > 250, \
            f"merion 5 carries should be back-tee figures near 276/297, got {i5['carries']}"
        _svg, i9 = render_hole.render_hole(9, config.HOLES)
        assert not i9["carries"], (
            "merion 9's only bunker sits 215 yd out on a 231 yd hole once measured from the back tee, "
            f"i.e. greenside, and must not print as a tee carry: {i9['carries']}")
        # A SPANNING hole must NOT be shifted -- its line already starts at the back tee. Pinned on
        # merion 1, whose line is 14 yd under its card: applying the shift there anyway moves its
        # carries from 172/212/245 to 186/226/259, and no forward-tee assertion above would notice.
        _svg, i1 = render_hole.render_hole(1, config.HOLES)
        assert not i1["fwd_tee"], "merion 1 spans its card; this pin assumes that"
        assert i1["carries"] and 168 <= min(c[0] for c in i1["carries"]) <= 176, \
            f"merion 1 carries look shifted: {i1['carries']} (expected a near edge around 172)"


@needs_corpus
def test_every_green_surface_still_belongs_to_the_hole_that_draws_it():
    """dem_hd/holeNN.json's green_id must equal the green the CURRENT code binds that hole to.

    The surface and the drawn outline come from the same file, so a card is always internally
    consistent -- which is the danger. If a re-fetch, a bbox change or a binding change moves which
    green a hole binds to, the stored surface keeps describing the OLD green and nothing looks wrong:
    the slope map, the arrows, the depth grid and the footer would all agree with each other about the
    wrong putting surface.

    Cheap to check and worth having permanently, because three things in this review could have caused
    it: geo.hole_lines changing which way IS a hole, valley-hi's widened box replacing a hand-traced
    green with the real OSM one, and fetch_osm re-fetching geometry under existing surfaces."""
    checked, bad = 0, []
    for slug in CORPUS:
        config, _rh = _engine(slug)
        import geo
        geom_p = os.path.join(ROOT, "courses", slug, "osm_geom.json")
        if not os.path.isfile(geom_p):
            continue
        els = json.load(open(geom_p))["elements"]
        greens = [e for e in els if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        loc = config.COURSE.get("location") or {}
        lines = geo.hole_lines(els, loc.get("lat"), loc.get("lon"))
        for p_ in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            meta = json.load(open(p_))
            hn = meta["hole"]
            if hn not in lines:
                bad.append(f"{slug} h{hn}: a surface exists for a hole with no centreline")
                continue
            g, _ge, _te = geo.match_green(lines[hn]["geometry"], greens, label=f"h{hn}")
            checked += 1
            if g.get("id") != meta.get("green_id"):
                bad.append(f"{slug} h{hn}: surface built for green {meta.get('green_id')} but the hole "
                           f"now binds to {g.get('id')} -- rebuild that hole's DEM")
    assert checked >= 150, f"only {checked} surfaces checked; expected the corpus"
    assert not bad, "green surfaces no longer match their holes:\n  " + "\n  ".join(bad[:8])


@needs_corpus
def test_a_tee_with_no_hole_by_hole_yardages_is_marked():
    """A tee row the book cannot break down must say so.

    Tees are listed from course.json's `tees`; per-hole yardages come from `hole_cols`, and the sets
    differ on two courses. philadelphia lists a Green tee at 5819 yd with a 69.3/128 rating and has no
    Green column; the-reserve lists two COMBINATION tees (Blu/Wht, Wht/Grn) which by nature have none.
    Nothing printed is false -- they are published facts about real tees -- but a junior playing one would
    search all 18 cards for a yardage that is not in the book, and philadelphia's Green also sits outside
    the four tees its own sources cross-verified."""
    marked = plain = 0
    for slug in CORPUS + [s_ for s_ in
                          (os.path.basename(os.path.dirname(p_)) for p_ in
                           glob.glob(os.path.join(ROOT, "courses", "*", "greenbook.html")))
                          if s_ not in CORPUS and not s_.startswith("_")]:
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not os.path.isfile(book):
            continue
        for m in ("config", "render_hole", "render_green", "generate"):
            sys.modules.pop(m, None)
        os.environ["COURSE"] = slug
        import config
        html = open(book, encoding="utf-8").read()
        tbl = re.search(r'<table class="tt".*?</table>', html, re.S)
        if not tbl:
            continue
        per_hole = set(config.TEES)
        cells = re.findall(r'<tr><td>([^<]*)(<sup>&dagger;</sup>)?</td>', tbl.group(0))
        for name, dag in cells:
            if name in ("Tee",):
                continue
            full = next((t["name"] for t in config.TEE_TABLE if t["name"][:7] == name), name)
            backed = full in per_hole
            if backed:
                plain += 1
                assert not dag, f"{slug}: {full} HAS per-hole yardages but is marked unsupported"
            else:
                marked += 1
                assert dag, (f"{slug}: {full} has no per-hole column and is not marked -- a reader will "
                             f"hunt 18 cards for a yardage that is not in the book")
                assert "no hole-by-hole yardages in this book" in html, (
                    f"{slug}: a tee is daggered but the panel never explains the mark")
    assert plain >= 30, f"only {plain} backed tee rows checked"
    assert marked >= 3, (f"only {marked} unbacked tee rows found -- philadelphia Green plus "
                         f"the-reserve's two combination tees were expected")


@needs_corpus
def test_one_card_is_built_on_one_tee():
    """The tee marker, the from-tee gutter, the carries and the elevation must all be the tee the card
    headlines.

    "Which tee is this book built on" was decided in two places: generate.py took the longer of
    FEATURED/SECONDARY for the headline, while render_hole.py and fetch_hole_elev.py used TEES[0], the
    first scorecard column. Those coincide on 11 of 12 courses. the-reserve-at-spanos-park sets
    featured_tee = Gold while Black is column 0, so its cards headlined "376 Gold" beside a tee marker
    reading BLA and a brown gutter of 322 measured from the 422-yd BLACK tee -- 10 of 18 holes, up to
    46 yd out on the number a player reads as how far they have hit."""
    import re as _re
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        assert config.BACK_I in range(2, 2 + len(config.TEES)), f"{slug}: BACK_I out of range"
        for hn in config.HOLE_NUMS:
            try:
                svg, info = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue
            want = config.HOLES[hn][config.BACK_I]
            assert info["card_yd"] == want, (
                f"{slug} h{hn}: the map is built on {info['card_yd']} yd but the card headlines "
                f"{want} yd ({config.BACK_NAME}) -- two tees on one card")
            lab = _re.findall(r'fill="#20402a"[^>]*>([A-Z]{3})</text>', svg)
            if lab:
                assert lab[0] == config.BACK_NAME[:3].upper(), (
                    f"{slug} h{hn}: tee marker reads {lab[0]} but the card is built on "
                    f"{config.BACK_NAME}")
        # the elevation stage must anchor on the same tee
        p_elev = os.path.join(ROOT, "courses", slug, "hole_elev.json")
        if os.path.isfile(p_elev):
            sys.modules.pop("fetch_hole_elev", None)
            import fetch_hole_elev as fhe
            for hn_s, row in json.load(open(p_elev))["holes"].items():
                basis = str(row.get("tee_basis", ""))
                m = _re.search(r"card (\d+) yd", basis)
                if m:
                    assert int(m.group(1)) == config.HOLES[int(hn_s)][config.BACK_I], (
                        f"{slug} h{hn_s}: elevation anchored on card {m.group(1)} yd, "
                        f"card is {config.HOLES[int(hn_s)][config.BACK_I]}")
            del fhe


@needs_corpus
def test_no_recorded_source_is_lost_to_truncation():
    """Every source recorded for a course must appear UNCUT somewhere in legal/03.

    The table shortens the Scorecard column to 190 characters to stay readable, and that cut twice threw
    away real provenance -- the basis for philadelphia's pre-rebuild caveat, and five courses' rating and
    slope sources, all written into that one field. It also hid bay-view's "CORRECTED 2026-07-17 --
    earlier Blue/White/Red data was wrong (those tees don't exist on this course)", which is exactly the
    kind of thing a provenance document exists to carry.

    The cut is fine; losing the text was not. A "Sources in full" section now reproduces everything, and
    this test is what keeps the two in step -- otherwise a longer note added tomorrow disappears again
    with nothing to notice."""
    doc = open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
    assert "## Sources in full" in doc, "the full-text section is gone; truncation is lossy again"
    tail = " ".join(doc.split("## Sources in full", 1)[1].split())
    missing, checked = [], 0
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        j = json.load(open(cj))
        for key, val in sorted((j.get("sources") or {}).items()):
            val = " ".join(str(val).split())
            if not val:
                continue
            checked += 1
            if val not in tail:
                missing.append(f"{slug}.sources.{key}: {val[:70]}...")
    assert checked >= 20, f"only {checked} recorded sources checked"
    assert not missing, ("recorded source text does not appear in full in legal/03:\n  "
                         + "\n  ".join(missing[:6]))


@needs_corpus
def test_every_printed_rating_is_either_cited_or_visibly_uncited():
    """The Rating/Slope table is printed on every card; legal/03 must say where each course's came from.

    It was the only printed number whose source this project did not report, and 7 of 12 courses have
    none recorded. Worse, the panel's own note read "All yardages from the official scorecard" -- true
    of the Yds column, silent about the two columns beside it, and a reader takes it as covering the
    table.

    This test does NOT demand a citation: 7 courses genuinely have none, and inventing one would be the
    real failure. It demands that the absence be STATED, so an uncited number is visibly uncited and can
    be filled in later, rather than reading like the cross-checked yardages next to it."""
    doc = open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
    cited = uncited = 0
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        j = json.load(open(cj))
        if not any(t.get("rating") is not None for t in (j.get("tees") or [])):
            continue
        name = j.get("name", slug)
        line = next((l for l in doc.splitlines() if l.startswith("| " + name + " |")), None)
        assert line, f"{name} prints rating/slope but has no provenance row"
        assert "tee rating/slope" in line, (
            f"{name} prints a rating/slope table and legal/03 says nothing about where it came from")
        if "NOT recorded" in line:
            uncited += 1
        else:
            cited += 1
            src = " ".join(str((j.get("sources") or {}).get("rating") or "").split())
            assert src, f"{name}: legal/03 claims a rating source that course.json does not record"
            assert " ".join(src.split()[:5]) in " ".join(line.split()), (
                f"{name}: the recorded rating source does not reach legal/03")
    assert cited + uncited >= 10, f"only {cited + uncited} rating tables checked"
    assert cited, "no course cites a rating source, so the cited branch is untested"
    assert uncited, ("no course lacks a rating source -- if that is now true, delete this test's "
                     "uncited branch rather than leaving it unexercised")


@needs_corpus
def test_a_pre_rebuild_caveat_carries_its_basis():
    """"Rebuilt after the flight" is an assertion about real cards; it must cite why.

    Philadelphia marks its whole back nine pre-rebuild -- 9 of 18 cards -- and the evidence (a phased
    Flynn restoration; the front nine reopened 2024, before the Dec 2024-Mar 2025 flight, the back nine
    after it) was recorded inside sources.scorecard. legal/03 truncates that field to its first sentence,
    so the justification never reached the row making the claim: a reader auditing the caveat saw the
    assertion with no basis, in a table whose entire purpose is traceability.

    This project cites its yardages to three cross-checked sources. A caveat printed on nine cards has to
    meet the same bar."""
    doc = open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
    checked = 0
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        j = json.load(open(cj))
        stale = j.get("greens_possibly_outdated") or []
        if not stale:
            continue
        checked += 1
        basis = str(j.get("greens_outdated_basis") or "").strip()
        assert basis, (f"{slug} labels greens {stale} pre-rebuild data on {len(stale)} cards with no "
                       f"recorded basis -- add greens_outdated_basis to course.json")
        name = j.get("name", slug)
        line = next((l for l in doc.splitlines() if l.startswith("| " + name + " |")), None)
        assert line, f"{name} has no provenance row"
        assert "basis not recorded" not in line, f"{name}: legal/03 reports the basis as unrecorded"
        head = " ".join(basis.split()[:6])
        assert head in " ".join(line.split()), (
            f"{name}: the pre-rebuild basis does not reach legal/03 (looked for {head!r})")
    assert checked, "no course marks any green pre-rebuild, so this claim is untested"


@needs_corpus
def test_a_book_that_may_not_be_shared_says_so_on_the_page():
    """A non-distributable book must not print a free-to-share licence.

    distribution.py has always classed Poppy Ridge personal-use only -- rebuilt in 2025, no
    post-construction survey, greens deliberately blank -- and legal/03 has always said so. The BOOK
    printed the same "free to share, not for sale -- CC BY-NC-ND 4.0" as every distributable one. The
    verdict lived in the policy and the paperwork; the artifact invited the opposite, and a PDF that
    leaves this machine carries no trace of either.

    Asks the shared rule, not build_mode, so this cannot drift from the Status column in legal/03."""
    import distribution
    # NOT CORPUS: that requires osm_geom.json, which a yardage-mode course has none of -- so the only
    # non-distributable book in the tree was excluded and every assertion below passed vacuously. Scan
    # built books instead, which is the population this claim is actually about.
    slugs = sorted(os.path.basename(os.path.dirname(p_))
                   for p_ in glob.glob(os.path.join(ROOT, "courses", "*", "greenbook.html"))
                   if not os.path.basename(os.path.dirname(p_)).startswith("_"))
    checked = 0
    for slug in slugs:
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        j = json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
        html = open(book, encoding="utf-8").read()
        shareable = distribution.is_distributable(j)
        checked += 1
        if shareable:
            assert "free to share, not for sale" in html, f"{slug} is distributable but says otherwise"
            assert "personal use only" not in html, f"{slug} is distributable but warns against sharing"
            assert "DESIGNED TO CONFORM" in html, f"{slug} lost its Rule 4.3 cover badge"
        else:
            # THE COVER, not just the About text. Page 1 is what anyone receiving the PDF sees first,
            # and a non-distributable book used to carry an identical cover to a distributable one --
            # "DESIGNED TO CONFORM * RULE 4.3 / JUNIOR GOLF EDITION" -- with the personal-use notice
            # four cards deep. On a blank-green book that badge is also beside the point: Rule 4.3 limits
            # green-reading material, and a book printing none conforms trivially.
            assert "PERSONAL USE ONLY" in html, (
                f"{slug} may not be shared and its COVER does not say so")
            assert "DESIGNED TO CONFORM" not in html, (
                f"{slug} prints no green maps, so leading its cover with a Rule 4.3 claim emphasises "
                f"the one thing it is not doing")
            assert "free to share, not for sale" not in html, (
                f"{slug} is {distribution.distribution_status(j)[1]} but its book invites sharing")
            assert "personal use only" in html, (
                f"{slug} may not be shared and its book does not say so")
    assert checked >= 10, f"only {checked} books checked; expected every built book"
    assert any(not distribution.is_distributable(
        json.load(open(os.path.join(ROOT, "courses", s, "course.json")))) for s in slugs), \
        "no non-distributable book in the tree, so the branch that matters is untested"


@needs_corpus
def test_built_books_still_match_the_engine_and_the_data():
    """Every tee-shot row in every built book must equal what the engine produces from today's data.

    Nothing else checks this. `export_pdf --check` compares the PDF with the HTML, `gen_provenance` and
    `gen_disclaimers --check` compare their docs with the HTML -- every gate compares artifacts against
    OTHER artifacts, so a book built before a data or engine change stays "consistent" forever.
    Demonstrated: setting one recorded change_ft to 99.9 ft left all four checks and the whole suite
    green. It is also how the enlarged edition's legal text sat stale in legal/05 unnoticed.

    Re-rendering is cheap because the surfaces are already on disk, and it catches stale data and a
    stale engine with the same assertion."""
    stale, compared = [], 0
    for slug in CORPUS:
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not os.path.isfile(book):
            continue
        for m in ("config", "render_hole", "render_green", "generate"):
            sys.modules.pop(m, None)
        os.environ["COURSE"] = slug
        import config
        import generate
        import render_hole
        html = open(book, encoding="utf-8").read()
        for card in re.split(r'(?=<div class="panel hole)', html):
            mh = re.search(r'<div class="hnum">(\d+)</div>', card)
            if not mh:
                continue
            hn = int(mh.group(1))
            if hn not in config.HOLES:
                continue
            mp = re.search(r'<div class="playline">(.*?)</div>', card, re.S)
            printed = (mp.group(1).strip() if mp else "")
            try:
                _svg, info = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue                      # yardage-mode course: no hole map, no playline
            fresh = re.sub(r'</?div[^>]*>', '', generate.playline_html(hn, info)).strip()
            compared += 1
            if printed != fresh:
                stale.append(f"{slug} h{hn}: book has {printed!r}, engine+data say {fresh!r}")
    # A sweep that examines nothing passes vacuously, which is the failure mode this file keeps hitting.
    assert compared >= 150, f"only {compared} playlines compared; expected the whole corpus"
    assert not stale, ("built books are stale against the engine or the data:\n  "
                       + "\n  ".join(stale[:8]) + (" ..." if len(stale) > 8 else ""))


@needs_corpus
def test_hole_line_choice_does_not_depend_on_element_order():
    """Which OSM way IS a given hole must not depend on the order Overpass serialised the response.

    Every reader chose `max(candidates, key=len(geometry))` -- most vertices. At Castlewood two 18-hole
    courses share one OSM area, so every Valley ref has a Hill way with the same ref, and Valley hole 1's
    two candidates BOTH have 3 vertices, 513 m apart. Shuffling the element list flipped the answer
    between them, so a re-fetch could silently put the Hill course's first hole -- its map, its green, its
    slope, its yardage ticks -- on a Valley card. Length is no tie-breaker either: the way that must be
    REJECTED (425.8 yd) matches Valley's 429 card better than the right one (444.3 yd) does.

    Seven call sites made this choice separately. They must agree: a green surface built for one way and a
    map drawn from another is a card that is internally wrong with no visible symptom."""
    import random
    import geo
    for slug in CORPUS:
        p_geom = os.path.join(ROOT, "courses", slug, "osm_geom.json")
        if not os.path.isfile(p_geom):
            continue
        els = json.load(open(p_geom))["elements"]
        loc = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("location") or {}
        assert loc.get("lat") is not None, f"{slug}: course.json has no location to disambiguate refs"
        base = {hn: w["id"] for hn, w in geo.hole_lines(els, loc["lat"], loc["lon"]).items()}
        for seed in (1, 2, 3):
            shuf = list(els)
            random.Random(seed).shuffle(shuf)
            got = {hn: w["id"] for hn, w in geo.hole_lines(shuf, loc["lat"], loc["lon"]).items()}
            assert got == base, f"{slug}: hole choice changed with element order (seed {seed})"

    # the ambiguous case, pinned: Valley must keep ITS holes, not the Hill course's
    if "castlewood-valley-course" in CORPUS:
        els = json.load(open(os.path.join(ROOT, "courses", "castlewood-valley-course",
                                          "osm_geom.json")))["elements"]
        loc = json.load(open(os.path.join(ROOT, "courses", "castlewood-valley-course",
                                         "course.json")))["location"]
        picked = geo.hole_lines(els, loc["lat"], loc["lon"])
        assert picked[1]["id"] == 690943804, f"Valley hole 1 should be way 690943804, got {picked[1]['id']}"
        assert picked[9]["id"] == 690943812, f"Valley hole 9 should be way 690943812, got {picked[9]['id']}"
        cands = sum(1 for e in els if (e.get("tags") or {}).get("ref") == "1"
                    and (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry"))
        assert cands > 1, "this pin assumes hole 1 is ambiguous; it no longer is"

    # A MARGINAL centre must refuse too. The choice rests on course.json "location", and one course's
    # recorded location sits 617 m from its own hole centroid -- the same order as the 602 m margin that
    # separates castlewood-valley's holes from their Hill-course twins. So a location that far off on a
    # course WITH duplicate refs could flip the answer, and a near-tie has to stop rather than guess.
    near = [{"id": 1, "tags": {"golf": "hole", "ref": "2"},
             "geometry": [{"lat": 37.000, "lon": -121.0}, {"lat": 37.001, "lon": -121.0}]},
            {"id": 2, "tags": {"golf": "hole", "ref": "2"},
             "geometry": [{"lat": 37.002, "lon": -121.0}, {"lat": 37.003, "lon": -121.0}]}]
    with pytest.raises(SystemExit):                      # centre equidistant between the two
        geo.hole_lines(near, 37.0015, -121.0)
    far = geo.hole_lines(near, 36.990, -121.0)            # centre clearly nearer the first
    assert far[2]["id"] == 1
    assert geo.AMBIGUOUS_MARGIN_M <= 300, (
        "the margin must stay well under the 602 m that separates the real ambiguous holes, or it "
        "would refuse them too")

    # and with NO centre, an ambiguous ref must REFUSE rather than pick by order
    two = [{"id": 1, "tags": {"golf": "hole", "ref": "1"},
            "geometry": [{"lat": 37.0, "lon": -121.0}, {"lat": 37.001, "lon": -121.0}]},
           {"id": 2, "tags": {"golf": "hole", "ref": "1"},
            "geometry": [{"lat": 38.0, "lon": -122.0}, {"lat": 38.001, "lon": -122.0}]}]
    with pytest.raises(SystemExit):
        geo.hole_lines(two, None, None)
    one = geo.hole_lines(two[:1], None, None)          # unambiguous: no centre needed
    assert one[1]["id"] == 1

    # EXACTLY equidistant candidates must REFUSE, not pick. An earlier version of this asserted the id
    # tie-break resolved them deterministically -- deterministic, but arbitrary: OSM id order says
    # nothing about which course a hole belongs to. Once the margin guard existed, "stable" stopped
    # being good enough and the honest answer became "the centre cannot decide this".
    tie = [{"id": 99, "tags": {"golf": "hole", "ref": "4"},
            "geometry": [{"lat": 37.01, "lon": -121.0}, {"lat": 37.01, "lon": -121.0}]},
           {"id": 11, "tags": {"golf": "hole", "ref": "4"},
            "geometry": [{"lat": 36.99, "lon": -121.0}, {"lat": 36.99, "lon": -121.0}]}]
    for flip in (False, True):
        with pytest.raises(SystemExit):
            geo.hole_lines(list(reversed(tie)) if flip else tie, 37.0, -121.0)
    # the id tie-break still matters: it makes the RANKING -- and so the refusal message -- the same
    # whichever order the elements arrive in.
    msgs = set()
    for flip in (False, True):
        try:
            geo.hole_lines(list(reversed(tie)) if flip else tie, 37.0, -121.0)
        except SystemExit as e:
            msgs.add(str(e))
    assert len(msgs) == 1, "the refusal message depends on element order"


@needs_corpus
@needs_corpus
def test_every_green_has_its_own_printed_scale_bar():
    """One measured 5-yd bar per green, each found by its OWN caption.

    check_scale's second, INDEPENDENT reading of Rule 4.3 used to be "the longest horizontal rule
    anywhere in the book between 0.20 and 0.60 in". That is not the bar: on callippe it returned
    0.3554 in from a rule sitting nowhere near a "5 yd" label, while every real bar in that book is
    0.1902-0.3200 in. It matched the browser-layout figure on the other ten courses only because their
    longest stray rule happens to land near their largest bar.

    Nothing was ever mis-gated -- the pass/fail rests on the layout measure and the printed figure was
    informational -- but a second opinion that can latch onto an unrelated rule is not a second opinion,
    and this tool exists precisely because intent is not evidence."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    for m in ("check_scale", "export_pdf"):
        sys.modules.pop(m, None)
    import check_scale
    checked = 0
    for slug in CORPUS:
        if not os.path.isfile(os.path.join(ROOT, "courses", slug, "greenbook.pdf")):
            continue
        config, _rh = _engine(slug)
        # measure_printed now returns a REASON alongside the bars instead of a bare None, because
        # every way it could fail -- no PyMuPDF, no PDF, no captioned rule -- came back as None and
        # check_scale's caller said nothing at all, so the artifact half of the Rule 4.3 gate could
        # vanish from the report without a word. Unpack all three and SKIP on a stated reason.
        mx, bars, why = check_scale.measure_printed(slug)
        if mx is None:
            continue
        assert not why, why
        checked += 1
        ngreens = sum(1 for hn in config.HOLE_NUMS
                      if os.path.isfile(os.path.join(ROOT, "courses", slug, "dem_hd",
                                                     f"hole{hn:02d}.json")))
        assert len(bars) == ngreens, (
            f"{slug}: {len(bars)} printed 5-yd bars found for {ngreens} greens -- a bar was matched to "
            f"the wrong rule, or a green's caption has no bar beside it")
        assert mx <= check_scale.LIMIT_IN_PER_5YD, (
            f"{slug}: a printed bar measures {mx:.4f} in per 5 yd, over the "
            f"{check_scale.LIMIT_IN_PER_5YD} in Rule 4.3 cap")
    assert checked >= 10, f"only {checked} books measured"


@needs_corpus
def test_the_card_footer_cannot_break_mid_phrase():
    """The footer must wrap BETWEEN its two spans, never inside one.

    On a 5-tee course three "other" tees make the right span 44 characters, too long to share a line with
    the left one on a 3.5 in card -- so it wrapped, and without these rules it broke mid-phrase:
    monarch-bay orphaned "3.1%" onto its own line and split "Gol403 / Gre338 /" from "Red288", on holes 1,
    3 and 5. Five courses have five tee columns (callippe, copper-valley, monarch-bay, poppy, the-reserve).

    Exactly the fault the playline had, which is why that row was given its own line.

    This asserted only that the SUBSTRINGS ".foot span" and "white-space: nowrap" appear in the HTML --
    and they did, inside CSS the browser threw away. Both rules sat in an f-string with one brace too
    many on each side, so the emitted stylesheet read `.foot span {{ white-space: nowrap; }}` with a
    stray `}` on the rule above it. Chrome discarded the whole block: `.foot span` was not in
    document.styleSheets at all and getComputedStyle(span).whiteSpace was "normal". The test was green
    for as long as the rule had never once worked. Its own docstring called the approach crude; the
    suite already drives Playwright, so it is now measured where it matters -- in the renderer that
    prints the book."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    checked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            for slug in CORPUS:
                book = os.path.join(ROOT, "courses", slug, "greenbook.html")
                if not os.path.isfile(book):
                    continue
                if '<div class="foot">' not in open(book, encoding="utf-8").read():
                    continue
                checked += 1
                page.goto("file://" + os.path.abspath(book))
                page.emulate_media(media="print")
                got = page.evaluate("""() => {
                  const sp = document.querySelector('.foot span');
                  const ft = document.querySelector('.foot');
                  return { ws: getComputedStyle(sp).whiteSpace,
                           wrap: getComputedStyle(ft).flexWrap,
                           display: getComputedStyle(ft).display };
                }""")
                assert got["ws"] == "nowrap", (
                    f"{slug}: the browser computes white-space:{got['ws']} on a .foot span, so a phrase "
                    f"can still be split across lines. The CSS text may LOOK right -- check the brace "
                    f"count in the f-string that emits it, which is how this broke before.")
                assert got["wrap"] == "wrap", (
                    f"{slug}: .foot computes flex-wrap:{got['wrap']}, so an over-long span breaks "
                    f"mid-phrase instead of the footer moving to a second line")
                assert got["display"] == "flex", (
                    f"{slug}: .foot computes display:{got['display']}, not flex -- the whole footer rule "
                    f"was dropped by the parser")
        finally:
            browser.close()
    assert checked >= 10, f"only {checked} books checked"


@needs_corpus
def test_both_editions_share_one_playline_definition():
    """The pocket and enlarged cards must build the tee-shot row from the SAME code.

    They have drifted three times: green_honesty lived only in hole_panel(), then the footer, then this
    row -- the enlarged edition's own legend described an elevation and a carry its cards never printed.
    Each fix copied the content across, which only resets the clock, so both now call playline_html()
    and this asserts they still do. Source-level on purpose: the point is that no SECOND expression of
    this row exists to fall out of step."""
    import inspect
    for m in ("config", "render_hole", "render_green", "generate"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = CORPUS[0]
    import generate
    assert hasattr(generate, "playline_html"), "the shared playline helper is gone"
    for fn_name in ("hole_panel", "coach_map_card"):
        src = inspect.getsource(getattr(generate, fn_name))
        assert "playline_html(" in src, f"{fn_name} no longer uses the shared playline helper"
        assert "elev_phrase(" not in src and "carry_phrase(" not in src, (
            f"{fn_name} builds the row itself again -- that is how the two editions drift")
    # ...and the duplex upright-back rule, which was the last one still written twice: the pocket path
    # called is_upright_back() while the coach path reimplemented it inline. Identical then, but three
    # rules have already drifted between these two paths, so the copy is the hazard, not the mismatch.
    assert hasattr(generate, "is_upright_back"), "the shared upright-back helper is gone"
    for fn_name in ("main", "build_coach"):
        src = inspect.getsource(getattr(generate, fn_name))
        assert "is_upright_back(" in src, f"{fn_name} no longer uses the shared upright-back rule"
        # The right disjunct was already asserted on the line above, so `A or B` was `A or True`.
        # What this means to say is that the last-card test is not RE-INLINED here: the helper is
        # called and the raw index comparison is absent. Both, not either.
        assert "len(cards)-1" not in _code_only(src).replace(" ", ""), (
            f"{fn_name} tests the last-card condition itself again")


@needs_corpus
def test_line_traced_past_the_tee_shifts_the_other_way():
    """A line traced BEYOND the back tee must shift NEGATIVELY, and its guard is corpus-invisible.

    Both overshoot holes measured every along-line distance from a point ~36 yd behind their real tee:
    castlewood-hill 4 printed "carry 85" for sand that is 49 yd off the tee -- not a carry decision at
    all -- and callippe 3 printed 269 for a real 233. The signed shift already handled this direction;
    it simply was not applied."""
    _config, render_hole = _engine(CORPUS[0])
    f = render_hole.line_traced_past_the_tee
    assert f(586.0, 550.0, 578.0)            # callippe 3: 36 yd past, and straight
    assert f(218.4, 182.0, 218.4)            # castlewood-hill 4
    assert not f(397.9, 501.0, 393.0)        # SHORT, not past -- that is the forward-tee case
    assert not f(505.0, 500.0, 498.0)        # within tolerance: the line spans, no shift
    # a WANDERING line's extra length need not be at the tee end, so refuse it
    assert not f(586.0, 550.0, 480.0)
    assert not f(586.0, 550.0, 0.0)          # degenerate chord must not fall through to True

    if "castlewood-hill-course" in CORPUS:
        config, render_hole = _engine("castlewood-hill-course")
        _svg, i4 = render_hole.render_hole(4, config.HOLES)
        assert i4["past_tee"], "castlewood-hill 4 is traced past its tee; this pin assumes that"
        assert not i4["carries"], (
            "castlewood-hill 4's sand is 49 yd off the real tee and must not print as a carry: "
            f"{i4['carries']}")
    if "callippe-preserve-golf-course" in CORPUS:
        config, render_hole = _engine("callippe-preserve-golf-course")
        _svg, i3 = render_hole.render_hole(3, config.HOLES)
        assert i3["past_tee"] and i3["carries"], "callippe 3 should still carry a shifted carry"
        assert 225 <= i3["carries"][0][0] <= 241, (
            f"callippe 3 carry {i3['carries'][0][0]} looks unshifted (269) or over-shifted")


@needs_corpus
def test_forward_tee_rule_guards():
    """Both guards on the forward-tee derivation, tested DIRECTLY.

    Neither is exercised by the corpus: the one hole that fails the tee-box test (valley-hi 17, which
    starts 98.6 m out in the fairway) also fails the yardage test, and the one overshoot hole
    (callippe 3) matches no forward-tee figure either. So deleting either guard changes no printed
    number and every corpus sweep still passes -- verified by mutation."""
    _config, render_hole = _engine(CORPUS[0])
    f = render_hole.line_runs_from_a_forward_tee
    # a 398 yd line on a 501 yd hole, on a tee box, against published forward tees of 394/381
    assert f(397.9, 501, [394, 381], 0.0)
    assert f(397.9, 501, [394, 381], 19.0)          # still on the box within slack
    # starts out in the fairway -> truncated line, refuse however well the yardage matches
    assert not f(397.9, 501, [394, 381], 98.6)
    assert not f(397.9, 501, [394, 381], 20.1)
    # on a tee box but the length matches NO published forward tee -> cannot say which tee it is
    assert not f(497.0, 561, [460, 430], 0.0)
    # OVERSHOOT: line traced PAST the tee, so the extra length is at the tee end and subtracting the
    # remaining walk from the card understates the distance (callippe 3, 586 yd line on a 550 card)
    # The forward-tee figures here are chosen to MATCH the overshooting length, so only the overshoot
    # guard can reject them -- an earlier version of this case matched nothing and passed even with the
    # guard deleted, which is exactly the false comfort mutation testing is for.
    assert not f(585.9, 550, [580, 520], 0.0)
    assert not f(218.4, 182, [215, 170], 0.0)
    # no tee polygons on the course at all -> the 1e9 sentinel must refuse, not sail through
    assert not f(397.9, 501, [394, 381], 1e9)
    assert not f(397.9, 501, [], 0.0)


@needs_corpus
def test_short_par45_holes_still_get_their_from_tee_numbers():
    """Merion 2, 5, 6 and 8 must carry a from-tee number on every tick.

    Their OSM line runs from the Middle tee, not the Championship tee, so it is 23-103 yd shorter than
    the card and the proportional model cannot be used -- the whole brown gutter was empty on four of
    eighteen cards, which reads as a broken book. Pinned as an OUTPUT because reverting the derivation
    violates no invariant: it just empties those gutters again while every consistency check passes."""
    if "merion-golf-club" not in CORPUS:
        pytest.skip("merion-golf-club not built")
    config, render_hole = _engine("merion-golf-club")
    for hn in (2, 5, 6, 8):
        svg, info = render_hole.render_hole(hn, config.HOLES)
        lefts = [int(x) for x in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg)]
        rights = [int(x) for x in re.findall(r'<text x="91"[^>]*>(\d+)</text>', svg)]
        card = config.HOLES[hn][config.BACK_I]   # not column 0
        assert info["fwd_tee"], f"merion {hn} should use the forward-tee derivation"
        assert rights, f"merion {hn} has an empty from-tee gutter again"
        assert len(lefts) == len(rights), f"merion {hn} unmatched rows: {lefts} / {rights}"
        assert rights == sorted(rights, reverse=True), f"merion {hn} not monotonic: {rights}"
        # the tee-most number must reflect the BACK tee, i.e. exceed the forward-tee card it was
        # derived past -- a degenerate derivation would land near the forward figure instead
        assert max(rights) > config.HOLES[hn][3] - 150, \
            f"merion {hn} from-tee {max(rights)} looks derived from the wrong tee (card {card})"


@needs_corpus
def test_short_par3_still_gets_its_gutter_numbers():
    """A hole under 150 yd must still carry a to-green/from-tee pair.

    Merion 13 (128 yd) printed NOTHING in either gutter: its only tick sits 18 yd along a line 10 yd
    shy of the card, under the 25-yd clutter cut, and its from-tee figure of 28 yd was under a flat
    30-yd floor. Both thresholds were absolute, so they scaled wrongly -- 30 yd is noise on a 500-yd
    hole and a fifth of this one. Pinned as an OUTPUT because reverting the scaled floor breaks no
    invariant: it just quietly empties this card again, and every consistency check still passes."""
    if "merion-golf-club" not in CORPUS:
        pytest.skip("merion-golf-club not built")
    config, render_hole = _engine("merion-golf-club")
    svg, _ = render_hole.render_hole(13, config.HOLES)
    card = config.HOLES[13][2]
    assert card == 128, f"this test is pinned to merion 13 at 128 yd, card now says {card}"
    lefts = [int(x) for x in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg)]
    rights = [int(x) for x in re.findall(r'<text x="91"[^>]*>(\d+)</text>', svg)]
    assert lefts and rights, f"merion 13 has empty gutters again: {lefts} / {rights}"
    assert len(lefts) == len(rights), f"unmatched rows: {lefts} / {rights}"
    for l, r in zip(lefts, rights):
        assert l + r == card, f"par-3 pair {l}+{r} != {card}"


@needs_corpus
def test_from_tee_labels_are_bounded_and_ordered():
    """Round 2: the from-tee number was card_total - yd while yd had become a straight-line radius,
    mixing two measures (max +54 yd wrong). It must now be >= 30, <= the hole's card yardage, and
    increase monotonically as the to-green number does.

    Bounds and ordering are NOT sufficient -- card_total - yd satisfies all three, which is how the
    original bug survived. So the VALUE is also checked against an independently computed
    along-the-line position (dense sampling, no code shared with the engine).

    The engine derives the from-tee number two ways, and this test must check the one it actually
    used or it just re-asserts the model it happens to encode:
      * PAR 3 on a straight line -- exact: from-tee = card - to_green, because tee, tick and green
        are collinear. Checked as (a) the printed pair summing to the card exactly, which catches a
        brown number paired with the wrong to-green row, and (b) the tick's measured along-the-line
        position matching (arc - to_green), which catches the tick being drawn in the wrong place.
        Bound (b) per hole by how far the line's green end sits from the green centroid -- the only
        thing that makes a straight line's walked and radial measures differ -- plus 5 yd. Worst
        residual over the corpus is 2.17 yd, so that is 2.3x headroom, and it scales with the
        geometry instead of being a constant that a bigger green would silently break.
      * everything else -- the card yardage scaled by position along the drawn line."""
    bad, nholes, labels, errors = [], 0, 0, []
    worst_value_err = 0.0
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        geom = json.load(open(os.path.join(ROOT, "courses", slug, "osm_geom.json")))["elements"]
        greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        holes = [e for e in geom if (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry")]
        import geo as _geo
        _loc = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("location") or {}
        hole_lines = _geo.hole_lines(geom, _loc.get("lat"), _loc.get("lon"))
        _cj = json.load(open(os.path.join(ROOT, "courses", slug, "osm_course.json")))["elements"]
        course_tees = [e for e in _cj
                       if (e.get("tags") or {}).get("golf") == "tee" and e.get("geometry")]
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception as e:
                errors.append((slug, hn, repr(e)[:120])); continue
            nholes += 1
            card = config.HOLES[hn][config.BACK_I]   # not column 0
            rights = [int(x) for x in re.findall(r'<text x="91"[^>]*>(\d+)</text>', svg)]
            lefts = [int(x) for x in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg)]
            # Floor is scaled: 30 yd is noise on a 500-yd hole but a fifth of a 128-yd one, where a
            # 28-yd figure is real information. Recomputed here rather than imported so a change to
            # the engine's floor has to be restated deliberately.
            ft_floor = min(30.0, 0.20 * card)
            for r in rights:
                if r < ft_floor or r > card:
                    bad.append((slug, hn, "out of range", r, card))
            if rights != sorted(rights, reverse=True):
                bad.append((slug, hn, "from-tee not monotonic", rights, card))
            if lefts != sorted(lefts):
                bad.append((slug, hn, "to-green not monotonic", lefts, card))
            # On a STRAIGHT PAR 3 both gutter numbers are known exactly, so every row must carry the
            # pair. A row with only the green number reads as a missing number rather than as a
            # refusal -- the complaint that prompted this -- and it happened because the row and its
            # from-tee figure were gated by two different thresholds. One threshold now governs both.
            if config.HOLES[hn][0] == 3 and len(lefts) != len(rights):
                _svg, _info = render_hole.render_hole(hn, config.HOLES)
                if _info["par3_straight"]:
                    bad.append((slug, hn, "straight par 3 has an unmatched gutter row",
                                lefts, rights))

            # --- value check, independent of the engine ---
            pairs = re.findall(r'<text x="9" y="([0-9.]+)"[^>]*>(\d+)</text>', svg)
            rmap = dict(re.findall(r'<text x="91" y="([0-9.]+)"[^>]*>(\d+)</text>', svg))
            if not rmap:
                continue
            if hn not in hole_lines:
                continue
            line = hole_lines[hn]["geometry"]
            g, gend, tend = render_hole.match_green(line, greens)
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
            # straightness and the green-end offset, both measured here rather than taken from the
            # engine, so the choice of model is verified and not inherited
            chord = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) or 1.0
            exact_model = config.HOLES[hn][0] == 3 and arc <= 1.02 * chord
            # Which model applies to a SHORT par 4/5: a complete route from a forward tee, or nothing?
            # Decided here from the geometry and the scorecard, not read off the engine, so a change to
            # either side has to be restated. Both conditions must hold, as in the engine.
            arc_yd_ = arc / 0.9144
            spans = abs(arc_yd_ - card) <= max(15.0, 0.05 * card)
            fwd_model = False
            if not spans and not exact_model and arc_yd_ < card:
                start_tee_m = min((_dist_to_poly(pts[0], t, em) for t in course_tees), default=1e9)
                fwd_yds = [config.HOLES[hn][2 + i] for i in range(len(config.TEES))
                           if 2 + i != config.BACK_I]
                fwd_model = (start_tee_m <= 20.0 and
                             any(abs(arc_yd_ - y) <= max(15.0, 0.05 * y) for y in fwd_yds))
            # ...and the mirror case: a line traced PAST the tee uses the same offset derivation, so
            # this must be modelled here too or its holes read as wrong values (callippe 3 did).
            if (not spans and not exact_model and arc_yd_ > card
                    and arc <= 1.02 * chord):
                fwd_model = True
            ge = em(gend["lat"], gend["lon"])
            green_end_off = math.hypot(ge[0] - gc[0], ge[1] - gc[1]) / 0.9144
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
                labels += 1
                if exact_model:
                    # (a) the pair must sum to the card exactly -- collinearity is the whole claim
                    if int(rmap[y]) + int(ln) != card:
                        bad.append((slug, hn, "par-3 pair does not sum to the card",
                                    f"{rmap[y]}+{ln}", card))
                    # (b) the tick must SIT where a straight tee-to-green line puts it
                    err = abs(best[1] / 0.9144 - (arc / 0.9144 - int(ln)))
                    worst_value_err = max(worst_value_err, err)
                    if err > green_end_off + 5.0:
                        bad.append((slug, hn, "par-3 tick off the straight-line position",
                                    round(err, 1), round(green_end_off + 5.0, 1)))
                    continue
                expect = card * best[1] / arc          # card yardage scaled by position on the line
                if fwd_model:
                    # back-tee card minus the walk still left to the green -- both walked measures
                    expect = card - (arc - best[1]) / 0.9144
                err = abs(int(rmap[y]) - expect)
                worst_value_err = max(worst_value_err, err)
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
        import geo as _geo
        _loc = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("location") or {}
        hole_lines = _geo.hole_lines(geom, _loc.get("lat"), _loc.get("lon"))
        for hn in config.HOLE_NUMS:
            if hn not in hole_lines:
                continue
            line = hole_lines[hn]["geometry"]
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
    12 books: 1,323 labels, 99 above 8%, worst 10 (the cap).

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
                        # .strip(): Chrome emits a real leading ' ' glyph ahead of some text-anchor="end"
                        # labels at the enlarged edition's font size, and the unstripped match dropped 25
                        # of them -- 15 in monarch-bay's coach book, 10 in philadelphia's, all yardages.
                        # Those 25 were then exempt from test_every_number_printed_in_a_pdf_exists_in_its
                        # _html, in exactly the two books whose right-anchored numbers it cannot see.
                        # Harmless for the slope view today (all 25 are 135-499, above its v < 100 filter)
                        # but a two-digit slope label would hide the same way.
                        if re.fullmatch(r"\d{1,3}", txt.strip()):
                            out.append(int(txt.strip()))
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
    was checking.

    IT ALSO COULD NOT CATCH ITS OWN DEFECT. The flagged set was
    `{v for v in pdf_numbers if v > BOUND} & html_slopes` -- intersected with the HTML -- so a PDF
    could only be accused of printing a slope the HTML ALSO printed. That is the exact opposite of the
    stale-export failure in the docstring above, where the HTML was already capped. Proven by
    mutation: injecting a 41 into the HTML failed the test (41 happens to appear among the PDF's
    yardages), while injecting 40 -- the literal Merion defect -- passed, because whether the verdict
    fires depended on the number coinciding with something else on the page.

    So discriminate the slope layer by FONT RESOURCE instead. Chrome emits each green's SVG text as its
    own Type3 font, and a green's slope labels therefore land in a resource of their own. A resource
    holding only 1-2 digit values, at least one of them not a multiple of 5, is a slope-label set: the
    ladder rungs and the gutter ticks are always multiples of 5, and the hole-map yardages are
    3-digit, so neither can qualify. Measured across the corpus this isolates exactly 252 resources --
    one per green card, 198 pocket + 54 enlarged -- with a maximum value of 10, the cap. Nothing is
    intersected with the HTML, so a PDF that disagrees with its source is now visible here.

    Sibling coverage, so this test does not have to carry it: PDF-vs-HTML faithfulness is
    test_every_number_printed_in_a_pdf_exists_in_its_html, and staleness is
    test_the_printed_pdf_is_not_older_than_the_html_it_came_from, which hashes content rather than
    comparing mtimes."""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    PUTTING_PLAUSIBLE_MAX_PCT = 12

    def slope_label_sets(path):
        """{(page, font resource): {values}} for the runs that are a green's slope labels."""
        by = {}
        with fitz.open(path) as d:
            for pg in d:
                for blk in pg.get_text("rawdict")["blocks"]:
                    for ln in blk.get("lines", []):
                        for sp in ln.get("spans", []):
                            if "Type3" not in sp.get("font", ""):
                                continue
                            txt = "".join(c.get("c", "") for c in sp.get("chars", [])).strip()
                            if re.fullmatch(r"\d{1,3}", txt):
                                by.setdefault((pg.number, sp["font"]), set()).add(int(txt))
        # `all(x < 100)` alone. An earlier version also required at least one value not a multiple of
        # 5, on the theory that ladder rungs and gutter ticks are always multiples. Measured, that
        # clause excluded 0 of 252 resources -- zero discriminating power -- while carrying all the
        # risk: it DISCARDED {40}, {5,40}, {15,40}, {5,10,40}, so the one value this test exists to
        # catch was never examined. Patching a real shipped PDF to print 40, 5, 5, 5, 5, 5, 5 passed.
        # The stale-export defect in the docstring prints 15/20/25/30/35/40 -- every one a multiple of
        # 5 -- so the clause was precisely wrong for the case it was written for. Two live cards are one
        # glyph from it: callippe p4 is {5,6} and castlewood-hill p1 is {3,5}.
        #
        # The real discriminators are the two structural facts: the ladder rungs are drawn with
        # stroke="none" and land in a Type0 font, so they never enter this dict at all; and the gutter
        # resource always carries a 3-digit to-green radius alongside its 1-2 digit from-tee number, so
        # all(x < 100) excludes it.
        return {k: v for k, v in by.items() if all(x < 100 for x in v)}

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
        sets = slope_label_sets(pdf)
        # One resource per green card, so the count is a floor on having found the layer at all. A
        # rewrite that stops emitting per-green fonts, or a discriminator that stops matching, would
        # otherwise silently examine nothing and pass.
        # The engine knows this number: one resource per green card. `>= 15` tolerated three greens
        # silently dropped per book, 42 across the corpus.
        n_green_cards = len(re.findall(r'font-size="4\.6"[^>]*font-weight="700"',
                                       open(html, encoding="utf-8").read())) and \
            len(re.findall(r'class="minilab">GREEN', open(html, encoding="utf-8").read()))
        assert len(sets) >= max(15, n_green_cards or 15), (
            f"{os.path.relpath(pdf, ROOT)}: only {len(sets)} slope-label font resource(s) isolated for a "
            f"book with green cards. Expected roughly one per green. The discriminator has stopped "
            f"finding the layer, so this test is examining nothing -- fix it rather than let it pass.")
        bad = sorted({v for vals in sets.values() for v in vals if v > PUTTING_PLAUSIBLE_MAX_PCT})
        assert not bad, (
            f"{os.path.relpath(pdf, ROOT)} prints unputtable slope label(s) {bad}. A putting surface "
            f"has no {bad[0]}% slope. Read from the PDF's own glyph runs, NOT compared against the "
            f"HTML -- so a shipped PDF that disagrees with its source shows up here.")
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
    s = dict(feeds="front-left", conf="clear", tilt_pct=3.1, depth_yd=33, width_yd=25,
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
        # THE PRODUCER'S predicate, not a copy of it. This line was byte-identical to
        # fetch_dem.py's inline expression, so the test graded its own rule: setting `flat = False`
        # in the producer left this green. A test that re-implements the rule catches a wrong
        # application of it and never a wrong rule -- and here the rule IS the honesty gate.
        return fd.is_flat_fill(ni, nf, rel)

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


def test_one_hole_line_chooser_for_the_whole_pipeline():
    """Every stage must place its data on the SAME hole line, so no stage can drift off the others.

    geo.hole_lines exists because "longest way per ref, first wins on a tie" is order-dependent: on
    castlewood-valley hole 1 two candidate ways sit 513 m apart and the answer flips when the element
    list is reordered. That was fixed in render_hole -- and three fetch scripts quietly kept their own
    verbatim copy of the old rule. fetch_dem_hd places the green SURFACES, fetch_trees places the tree
    corridors, fetch_dem places the gap-fill DEM. Each could have bound to a different line from the
    one render_hole draws and fetch_hole_elev measures the tee against, and the book would look
    entirely normal: a real green, real trees, real elevation -- belonging to the wrong hole.

    They agreed on all 198 holes only because the cached element order happened to favour it. A
    re-fetch reorders elements, so this was one Overpass call away from a silent split.

    Asserted as "no module re-implements the rule", not as "the outputs happen to match today",
    because matching today is exactly the state that hid it.
    """
    import glob as _glob
    offenders = []
    for path in sorted(_glob.glob(os.path.join(ROOT, "*.py"))
                       + _glob.glob(os.path.join(ROOT, "tools", "*.py"))):
        name = os.path.basename(path)
        if name == "geo.py":
            continue                      # the one legitimate home for the rule
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        # the shape of the old heuristic: keep the longest geometry per ref
        if re.search(r"len\(\s*h\[[\'\"]geometry[\'\"]\]\s*\)\s*>\s*len\(", code):
            offenders.append(f"{name} re-implements longest-way-per-ref instead of calling "
                             f"geo.hole_lines -- it can bind to a different line than the map draws")
    assert not offenders, "the hole-line rule has been duplicated again:\n  " + "\n  ".join(offenders)

    # and every stage that places data by hole must actually go through the shared chooser
    for name in ("fetch_dem_hd.py", "fetch_dem.py", "fetch_trees.py", "render_hole.py",
                 "fetch_hole_elev.py"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            src = fh.read()
        assert "hole_lines(" in src, f"{name} no longer uses the shared hole-line chooser"


@needs_corpus
def test_each_green_is_turned_the_way_the_card_promises():
    """"Approach at the bottom" is the promise every green map is read through. Verify the chain.

    A green is rotated by theta = -90 - atan2(-cos B, sin B), where B is the approach bearing, so the
    player is looking up the page from where they stand. Get B or theta wrong and NOTHING looks
    broken: the outline is still a green, the arrows still point somewhere, the slope numbers are
    still right. The map is just turned relative to the golfer, so every break they read is wrong by
    that angle -- and on a 180 error it is exactly backwards. No existing check touches it.

    Three links, each verified against the one before rather than against a restatement of itself:

      1. B is re-derived from the artifacts -- the OSM hole line chosen by geo.hole_lines, its green
         matched by geo.match_green, and the bearing of the last segment INTO the green end. If
         fetch_dem_hd ever picked a different line or the other end of it, this diverges. It
         reproduces to 0.001 deg across the corpus.
      2. theta is recomputed from B by the formula above.
      3. The printed compass needle is read back out of the built book and compared with theta. The
         compass is drawn OUTSIDE the rotated group from the same theta, so it is an independent
         witness to the rotation actually applied to the map -- not a copy of the input.

    Bounded at 3 deg only because SVG coordinates are written to one decimal and the needle is 4
    units long, which is worth about 1.5 deg of rounding; the worst in the corpus is 1.49. A sign
    error or a swapped axis lands 90 or 180 deg away, nowhere near the bound.
    """
    import math
    checked, problems = 0, []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        book = os.path.join(ROOT, "courses", ref, "greenbook.html")
        geom_p = os.path.join(ROOT, "courses", ref, "osm_geom.json")
        if not (os.path.exists(book) and os.path.exists(geom_p)):
            continue
        cfg, _rh = _engine(ref)
        import geo
        with open(geom_p, encoding="utf-8") as fh:
            els = json.load(fh)["elements"]
        greens = [e for e in els if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        loc = cfg.COURSE.get("location") or {}
        try:
            lines = geo.hole_lines(els, loc.get("lat"), loc.get("lon"))
        except SystemExit:
            continue
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel hole">', html)[1:]:
            hm = re.search(r'<div class="hnum">(\d+)</div>', blk)
            cm = re.search(r'<g stroke="#666" fill="#666"><line x1="([\d.-]+)" y1="([\d.-]+)" '
                           r'x2="([\d.-]+)" y2="([\d.-]+)"', blk)
            if not (hm and cm):
                continue
            hn = int(hm.group(1))
            meta_p = os.path.join(ROOT, "courses", ref, "dem_hd", f"hole{hn:02d}.json")
            if hn not in lines or not os.path.exists(meta_p):
                continue
            with open(meta_p, encoding="utf-8") as fh:
                recorded = json.load(fh)["approach_bearing"]

            # link 1: the bearing, re-derived from the geometry the card is drawn from
            line = lines[hn]["geometry"]
            _green, gend, _tend = geo.match_green(line, greens, label=f"hole {hn}")
            prev = line[1] if gend is line[0] else line[-2]
            p1, p2 = math.radians(prev["lat"]), math.radians(gend["lat"])
            dl = math.radians(gend["lon"] - prev["lon"])
            indep = (math.degrees(math.atan2(
                math.sin(dl)*math.cos(p2),
                math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl))) + 360) % 360
            gap = abs((indep - recorded + 180) % 360 - 180)
            if gap > 1.0:
                problems.append(f"{ref} hole {hn}: recorded approach bearing {recorded:.1f} deg but "
                                f"the hole line into the green runs {indep:.1f} deg -- the green is "
                                f"turned to a direction the course does not have")

            # links 2+3: theta, and the needle the book actually printed from it
            a = math.degrees(math.atan2(-math.cos(math.radians(recorded)),
                                        math.sin(math.radians(recorded))))
            th = math.radians(-90.0 - a)
            ex, ey = math.sin(th), -math.cos(th)
            x1, y1, x2, y2 = (float(v) for v in cm.groups())
            px, py = x2 - x1, y2 - y1
            n = math.hypot(px, py)
            checked += 1
            seen_courses[ref] += 1   # past the gates: counts WORK, not intent
            if n == 0:
                problems.append(f"{ref} hole {hn}: the north needle has zero length")
                continue
            off = math.degrees(math.acos(max(-1.0, min(1.0, (px/n)*ex + (py/n)*ey))))
            if off > 3.0:
                problems.append(f"{ref} hole {hn}: the printed north arrow sits {off:.0f} deg from "
                                f"where an approach bearing of {recorded:.0f} deg puts it -- the "
                                f"green is not turned the way \"approach at the bottom\" promises")
    # Derived, not a magic number: a floor of 100 against 198 greens let a whole course vanish
    # unnoticed (see the poppy-ridge coverage gap). expected_holes() scales with whatever is built.
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} greens checked of {expected_geometry_holes()} holes with geometry -- a course is being "
        f"skipped")
    assert_no_course_skipped(seen_courses, "test_each_green_is_turned_the_way_the_card_promises")
    assert not problems, "green orientation is wrong:\n  " + "\n  ".join(problems[:10])


@needs_corpus
def test_every_tee_name_prints_dark_enough_to_read():
    """A tee's ink matches its NAME, and the match must not cost the reader the name.

    tee_color() inks a Black tee black and a Gold tee gold, which is the right instinct -- and it
    already knew the trap, since White and Yellow get dark substitutes so they do not vanish. The
    gold did not get the same treatment: #b8860b is 3.25:1 on white, below the 4.5:1 a 7pt label
    needs. That is not an edge case, because gold is also the FALLBACK for any name that is not a
    colour -- Championship, Middle, Forward, Blu/Wht, Wht/Grn -- so it inked the back-tee name on the
    headline of every Merion and Philadelphia card, next to the largest number on the page.

    Checked as a pure function over the names the corpus actually uses plus the fallback, so it holds
    for a course added later whose tees are named something new.
    """
    def contrast_on_white(hexc):
        def lin(c):
            c = c / 255.0
            return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
        r, g, b = (int(hexc[i:i+2], 16) for i in (1, 3, 5))
        return 1.05 / (0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b) + 0.05)

    import generate
    names = {"__no_such_tee__"}          # forces the fallback ink through the same bar
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "course.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for t in (json.load(fh).get("tees") or []):
                if t.get("name"):
                    names.add(t["name"].strip())
    faint = []
    for n in sorted(names):
        ink = generate.tee_color(n)
        c = contrast_on_white(ink)
        if c < 4.5:
            faint.append(f"tee {n!r} inks {ink} at {c:.2f}:1 on white -- under 4.5:1 for 7pt text")
    assert len(names) > 5, "no tee names were checked"
    assert not faint, "tee names too faint to read on a home-printed card:\n  " + "\n  ".join(faint)


def test_the_information_carrying_greys_are_readable_on_paper():
    """The footer is secondary, not faint: it carries numbers a golfer plays a shot on.

    `.foot` holds the feed direction, the tilt %, the green depth and the bunker/water count;
    `.playline` holds the measured elevation change and the carries; `.yalt` holds another tee's
    yardage for the hole. They are deliberately quieter than the headline, and that is right -- but
    they were #999 and #9a9a9a, 2.85:1 and 2.81:1 on white, well under the 4.5:1 a 7.5pt line needs.
    Quiet is a hierarchy choice; too faint to read on a home inkjet is a defect, and this book's
    whole point is that a junior golfer prints it themselves.

    Both stylesheets are checked, because the pocket book and the enlarged one each carry their own
    copy and only one of them getting fixed is exactly the drift this suite exists to stop.
    """
    def contrast_on_white(hexc):
        h = hexc.lstrip("#")
        if len(h) == 3:
            h = "".join(ch*2 for ch in h)
        def lin(c):
            c = c / 255.0
            return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        return 1.05 / (0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b) + 0.05)

    with open(os.path.join(ROOT, "generate.py"), encoding="utf-8") as fh:
        src = fh.read()
    faint, found = [], 0
    # DISCOVERED, not listed. This named three selectors -- .foot, .playline, .yalt -- and passed while
    # .minilab inked at #9a9a9a (2.81:1), .dcopy the same, and .gsmall and .dqrcap at #777 (4.48:1). The
    # worst of those is the worst possible place for it: .minilab carries "GREEN . pre-rebuild data" and
    # "GREEN . 1 m data", the two marks whose whole job is to tell a junior to trust that green LESS. An
    # allow-list can only ever cover what someone thought of, so this now sweeps every rule in both
    # stylesheets and exempts by name, with a reason, rather than including by name.
    EXEMPT = {
        # decorative or on a coloured ground, so white-background contrast is not the right measure
        ".dqr": "the QR block's own caption sits on the code, checked by the QR test",
        ".crop": "crop ticks are register marks, not text",
        ".sheettab": "printed on the thumb-index tab's own fill",
        ".cover": "cover ink, set on the cover's own dark ground, not on paper white",
        ".ymain": "a SEMANTIC tee colour that must match the tee marker; covered with its own rule by "
                  "test_every_tee_name_prints_dark_enough_to_read",
        ".ylab": "same semantic tee colour as .ymain",
        ".pageno": "deliberate wayfinding, carries no information a reader acts on",
        ".sheetnote": "printer guidance in the sheet MARGIN, outside the trim -- read once with the "
                      "sheet in hand, never on the course",
        # Cover and back-cover typography. All of these are light inks set ON the cover's own dark
        # ground, so contrast against paper white is simply the wrong measurement for them; the pair
        # that matters there is ink-on-cover, which the cover's own fill controls. Listed individually
        # rather than by prefix because they share none, and listed at all because the alternative --
        # skipping any selector that fails -- is how the allow-list version of this test came to miss
        # .minilab at 2.81:1.
        ".crest": "cover crest, light ink on the cover's dark ground",
        ".btop": "back-cover heading, on the dark ground",
        ".bmain": "back-cover body, on the dark ground",
        ".cchip": "cover chip label, on the dark ground",
        ".dwebtag": "dedication card web tag, on the dark ground",
        ".etag": "the ENLARGED corner tag, reversed out of its own fill",
    }
    for m in re.finditer(r"(\.[a-zA-Z][\w-]*) \{\{([^}]*color:\s*#[0-9a-fA-F]{3,6}[^}]*)\}\}", src):
        cls, body = m.group(1), m.group(2)
        if cls in EXEMPT:
            continue
        col = re.search(r"color:\s*(#[0-9a-fA-F]{3,6})", body).group(1)
        found += 1
        c = contrast_on_white(col)
        if c < 4.5:
            faint.append(f"{cls} inks {col} at {c:.2f}:1 -- printed text needs 4.5:1 on paper. If this "
                         f"selector is decorative or sits on a coloured ground, add it to EXEMPT with a "
                         f"reason; do not raise the threshold.")
    assert found >= 14, (
        f"only {found} coloured rules discovered across both stylesheets; the sweep has stopped finding "
        f"them, which is how an allow-list version of this test missed .minilab at 2.81:1")
    assert not faint, "information-carrying text is too faint to print:\n  " + "\n  ".join(faint)


@needs_corpus
def test_the_feed_word_never_contradicts_the_green_s_own_arrows():
    """Each green states which way the ball rolls TWICE, and the two must not disagree.

    The footer names it in words -- "feeds front-left" -- from a least-squares plane fitted over the
    green core. The map shows it as arrows, each the local negative gradient of the denoised surface.
    Two independent derivations of the one claim the book exists to make. If either grew a sign error,
    a swapped axis, or lost the approach rotation, one of them would point the wrong way and only a
    reader standing on the green would ever find out.

    Bounded at 90 degrees, deliberately, because the two answer different questions and are SUPPOSED
    to differ a little: a plane fit describes the whole surface's tilt while the arrows follow every
    tier and hollow, so on an undulating green they diverge. Measured across the corpus the gap runs
    to a median 11.3 deg and a 90th percentile of 26.3 deg, and only 2 of 198 exceed one 45 deg
    octant -- monarch-bay 12 and the-reserve 8, whose plane tilt is 0.5% and 0.4%, flat enough that
    the tilt direction is barely more than noise. Both cards mark those "(faint)" and print the
    measured percentage beside the word, so the book already tells the reader not to lean on them.

    90 deg is therefore not a quality bar, it is a CONTRADICTION bar: past it the words and the
    picture are telling a golfer to play opposite breaks. Nothing in the corpus is above 68.8 deg.

    Arrows are weighted by their own length, which is how the legend defines them ("longer =
    steeper"), and rotated by the group transform the card applies, so both quantities are compared
    in the frame the reader actually sees.
    """
    import math
    import render_green
    dirs = render_green.DIRS
    checked, worst, problems = 0, (0.0, None), []
    seen_courses = collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel hole">', html)[1:]:
            hn = re.search(r'<div class="hnum">(\d+)</div>', blk)
            said = re.search(r"feeds <b>([a-z-]+)</b>", blk)
            grp = re.search(r'<g transform="rotate\((-?[\d.]+) [\d.]+ [\d.]+\)">(.*?)'
                            r'<path d="M [^"]*" fill="none" stroke="#20402a"', blk, re.S)
            if not (hn and said and grp):
                continue
            th = math.radians(float(grp.group(1)))
            ca, sa = math.cos(th), math.sin(th)
            vx = vy = 0.0
            for x1, y1, x2, y2 in re.findall(
                    r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)"/><polygon',
                    grp.group(2)):
                dx, dy = float(x2)-float(x1), float(y2)-float(y1)
                L = math.hypot(dx, dy) or 1.0
                a, b = dx/L, dy/L
                vx += (a*ca - b*sa) * L                 # rotate into the card frame, weight by steepness
                vy += (a*sa + b*ca) * L
            n = math.hypot(vx, vy)
            if n == 0:
                continue
            sx, sy = next((x, y) for x, y, w in dirs if w == said.group(1))
            cos = (vx*sx + vy*sy) / (n * math.hypot(sx, sy))
            gap = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            checked += 1
            seen_courses[ref] += 1   # past the gates: counts WORK, not intent
            if gap > worst[0]:
                worst = (gap, f"{ref} hole {hn.group(1)}")
            if gap > 90.0:
                problems.append(f"{ref} hole {hn.group(1)}: the footer says 'feeds {said.group(1)}' "
                                f"but the green's own arrows resolve {gap:.0f} deg away -- the words "
                                f"and the map are giving opposite breaks")
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} greens cross-checked of {expected_geometry_holes()} with geometry -- a course is missing")
    assert_no_course_skipped(seen_courses, "test_the_feed_word_never_contradicts_the_green_s_own_arrows")
    assert not problems, ("the printed feed direction contradicts the drawn arrows:\n  "
                          + "\n  ".join(problems[:10]))
    assert worst[0] <= 90.0, f"worst divergence {worst[0]:.1f} deg at {worst[1]}"


@needs_corpus
def test_every_duplex_back_lands_behind_its_own_front():
    """The one defect that would ruin every PHYSICAL copy while every digital check stayed green.

    A book is printed two-sided and cut up. Leaf L is card 2L+1 on the front and 2L+2 on the back, and
    the sheet tells the printer to flip on the LONG edge -- which for portrait paper turns the sheet
    about its vertical axis and so mirrors it left-to-right. generate.py compensates by placing each
    back card in the column-mirrored slot. Get that backwards and hole 4's green prints behind hole
    6's map: the PDF looks perfect on screen, every yardage is right, the scale conforms, and the
    error only exists once paper comes out of the printer. Nothing here could have caught it.

    Three things are asserted, measured off the exported PDF rather than the HTML, because it is the
    paper that has to be right:
      * every back card is on the page immediately after its front;
      * mirroring a back card's slot about the page's vertical centreline lands it exactly on its
        front's slot, to half a point;
      * exactly one back is printed upright and it is the LAST card. The other backs are rotated 180
        so they read the right way up when the cut card is flipped over its top edge; the dedication
        is the back cover of the finished book and must read upright, which is is_upright_back's job.

    Cards are located by the small grey `.pageno` number in their corner -- the artifact's own label,
    not a recomputed guess.
    """
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    checked, problems = 0, []
    for f in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        ref = os.path.basename(os.path.dirname(f))
        if ref.startswith("_"):
            continue
        cfg, _rh = _engine(ref)
        cw, ch, gut = cfg.CARD_W_IN*72, cfg.CARD_H_IN*72, cfg.GUTTER_IN*72
        pw, ph = cfg.PAGE_W_IN*72, cfg.PAGE_H_IN*72
        gx0 = (pw - (cfg.COLS*cw + (cfg.COLS-1)*gut)) / 2
        gy0 = (ph - (cfg.ROWS*ch + (cfg.ROWS-1)*gut)) / 2
        slots = {}
        for j in range(cfg.PER):
            r, c = divmod(j, cfg.COLS)
            x, y = gx0 + c*(cw+gut), gy0 + r*(ch+gut)
            slots[j] = fitz.Rect(x, y, x+cw, y+ch)
        loc = {}
        with fitz.open(f) as d:
            for pno, page in enumerate(d):
                for blk in page.get_text("dict")["blocks"]:
                    for ln in blk.get("lines", []):
                        for sp in ln.get("spans", []):
                            t = sp["text"].strip()
                            if not t.isdigit() or not (7.5 <= sp["size"] <= 8.5):
                                continue
                            if sp["color"] not in (0xbbbbbb, 0xcccccc):   # .pageno grey
                                continue
                            b = fitz.Rect(sp["bbox"])
                            for j, s in slots.items():
                                if s.contains(b):
                                    loc.setdefault(int(t), []).append(
                                        (pno, j, tuple(round(v, 1) for v in ln["dir"])))
        name = f"{ref}/{os.path.basename(f)}"
        if not loc:
            problems.append(f"{name}: no card numbers found -- the check verified nothing")
            continue
        dup = sorted(n for n in loc if len(loc[n]) != 1)
        if dup:
            problems.append(f"{name}: card number(s) {dup} appear in more than one slot")
        last = max(loc)
        for L in range((last + 1) // 2):
            fr, bk = 2*L+1, 2*L+2
            if fr not in loc or bk not in loc:
                continue
            (pf, jf, _df), (pb, jb, db) = loc[fr][0], loc[bk][0]
            sf, sb = slots[jf], slots[jb]
            checked += 1
            if pb != pf + 1:
                problems.append(f"{name}: card {bk} is on page {pb+1}, not behind card {fr} "
                                f"on page {pf+1}")
            if abs((pw - sb.x1) - sf.x0) > 0.5 or abs(sb.y0 - sf.y0) > 0.5:
                problems.append(f"{name}: card {bk} does not land behind card {fr} after a "
                                f"long-edge flip (slot {jb} vs {jf}) -- the back of a leaf would "
                                f"carry a different hole's page")
            upright = db == (1.0, 0.0)
            if upright != (bk == last):
                problems.append(f"{name}: card {bk} prints "
                                f"{'upright' if upright else 'rotated 180'} but "
                                f"{'only the last card may be upright' if upright else 'the last card must be upright'}")
    assert checked, "no leaf was checked -- export a book first (tools/export_pdf.py)"
    assert not problems, ("duplex imposition is wrong -- printed copies would be mis-assembled:\n  "
                          + "\n  ".join(problems[:10]))


@needs_corpus
def test_the_enlarged_edition_never_drops_half_a_ladder_row():
    """The big-print book may drop a whole row for spacing; it may NOT drop one number OF a row.

    Each row of the corridor ladder is a pair: to-green on the left, from-tee on the right. Dropping
    the pair is a legible layout decision -- at 2x type two rows 50 yd apart on a short hole really do
    collide, and four rows that read beat five that overlap. Dropping only the RIGHT number is a
    different thing: the row still prints, so nothing looks missing, and the reader of the LARGE-print
    edition silently gets less than the reader of the pocket one. That is backwards, and it happened
    to 21 numbers on 5 of 54 cards -- monarch-bay 9, 12 and 16 and philadelphia 12 lost their entire
    from-tee column while the pocket book printed all five.

    The cause was that the two numbers sit in gutters pinned to a fixed 100-unit box, so the room for
    them never grew with the type; render_hole now widens the BOX on demand (never the map, never the
    scale) up to what the panel's aspect allows. This test states the invariant rather than the fix,
    so any future change that trades a from-tee number for space fails here.

    Rendered in-process at both font scales -- no build, no PDF -- so it holds for courses whose books
    are not on disk.
    """
    checked = missing = 0
    for ref in CORPUS:
        if not os.path.exists(os.path.join(ROOT, "courses", ref, "osm_geom.json")):
            continue
        cfg, rh = _engine(ref)

        def rows(font_scale):
            """{to_green_yd: from_tee_yd or None} per hole, paired by shared text baseline"""
            out = {}
            for hn in sorted(cfg.HOLES):
                try:
                    svg, _info = rh.render_hole(hn, cfg.HOLES, font_scale=font_scale)
                except Exception:
                    continue
                vbw = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
                lanes = {}
                for x, y, s in re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]+)</text>', svg):
                    if not s.isdigit():
                        continue
                    lanes.setdefault(round(float(y), 1), {})[
                        "L" if float(x) < vbw / 2 else "R"] = int(s)
                out[hn] = {v["L"]: v.get("R") for v in lanes.values() if "L" in v}
            return out

        small, big = rows(1.0), rows(2.0)
        for hn in small:
            for yd, ft in small[hn].items():
                if ft is None:
                    continue
                if yd not in big.get(hn, {}):
                    continue                      # whole row dropped for spacing -- allowed
                checked += 1
                if big[hn][yd] != ft:
                    missing += 1
                    print(f"  {ref} hole {hn}: the {yd}yd row prints from-tee {ft} in the pocket "
                          f"book but {big[hn][yd]!r} in the enlarged one")
    assert checked, "no hole was compared across the two editions -- nothing was verified"
    assert missing == 0, (f"{missing} ladder row(s) keep their to-green number in the enlarged "
                          f"edition but lose the from-tee number beside it")


@needs_corpus
def test_no_printed_words_fall_outside_the_card_they_belong_to():
    """Every word on the paper must sit inside a card, because the paper gets CUT along the ticks.

    Text that overruns a card boundary is not merely ugly: the crop ticks are a cutting instruction,
    so an overrunning line is sliced in half and half of it goes in the bin. The reader is then left
    with a sentence that stops mid-clause, and on this project the sentence in question is the legal
    notice -- "not endorsed by or sponsored by any course, club, association or product" -- which is
    the one text on the card that has to survive intact.

    Nothing caught this. The card SIZE is checked against Rule 4.3, the scale bar is checked, the
    HTML is byte-compared against a cold build; all of them passed while the enlarged edition ran 25
    text spans off the card, because every one of those checks asks about the card and none of them
    asks what is inside it. It is only visible in the laid-out PDF: the HTML is correct, the browser
    decides where the words land, and it does not warn you when they land past the box.

    The ONE thing allowed outside a card is generate.py's `.sheetnote` printer label ("Sheet 1 ·
    FRONT"), which is deliberately in the sheet margin as an instruction to whoever prints it. So the
    assertion is not "few spans outside" but "nothing outside except that label" -- a threshold would
    have quietly accepted the 2 spans that were already over the edge before this was measured.
    """
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    checked, problems = 0, []
    for f in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.pdf"))):
        ref = os.path.basename(os.path.dirname(f))
        if ref.startswith("_"):
            continue
        cfg, _rh = _engine(ref)
        cw, ch = cfg.CARD_W_IN * 72, cfg.CARD_H_IN * 72
        gut = cfg.GUTTER_IN * 72
        pw, ph = cfg.PAGE_W_IN * 72, cfg.PAGE_H_IN * 72
        gx0 = (pw - (cfg.COLS * cw + (cfg.COLS - 1) * gut)) / 2
        gy0 = (ph - (cfg.ROWS * ch + (cfg.ROWS - 1) * gut)) / 2
        slots = []
        for j in range(cfg.PER):
            r, c = divmod(j, cfg.COLS)
            x, y = gx0 + c * (cw + gut), gy0 + r * (ch + gut)
            slots.append(fitz.Rect(x, y, x + cw, y + ch))
        with fitz.open(f) as d:
            for pno, page in enumerate(d):
                for blk in page.get_text("dict")["blocks"]:
                    for ln in blk.get("lines", []):
                        for sp in ln.get("spans", []):
                            txt = sp["text"].strip()
                            if not txt or txt.startswith("Sheet "):
                                continue          # the printer label, deliberately in the margin
                            b = fitz.Rect(sp["bbox"])
                            if any(s.contains(b) for s in slots):
                                continue
                            problems.append(
                                f"{ref}/{os.path.basename(f)} p{pno + 1}: {txt[:52]!r} at "
                                f"({b.x0:.1f},{b.y0:.1f})-({b.x1:.1f},{b.y1:.1f}) is not inside any "
                                f"card -- the trim line runs through it")
        checked += 1
    if checked == 0:
        pytest.skip("no book has been exported to PDF here (run tools/export_pdf.py)")
    assert not problems, (f"{len(problems)} printed span(s) would be cut by the trim line:\n  "
                          + "\n  ".join(problems[:12]))


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
                # -0.5 to read the array at the pixel the contour is DRAWN at. A drawn coordinate is a
                # PIXEL and z[r,c] is the sample at pixel (c+0.5, r+0.5) -- fetch_dem_hd.py builds the
                # grid on cell centres -- so bilerp(z, ax, ay) asks for the elevation half a cell up
                # and left of the line it is checking. It agreed anyway while render_green drew the
                # marching-squares corners at bare (c,r): the test embedded the renderer's own
                # off-by-half, so the two errors cancelled and this assertion could not see either.
                # With the renderer corrected it reported "a contour sits 74.1 mm off any 15 cm level"
                # on a corpus whose contours are exact to 0.000 mm.
                z1, z2 = bilerp(z, ax - 0.5, ay - 0.5), bilerp(z, bx - 0.5, by - 0.5)
                checked += 1
                worst_iso = max(worst_iso, abs(z1 - z2))
                mid = (z1 + z2) / 2.0
                worst_level = max(worst_level, abs(mid / cint - round(mid / cint)) * cint)
    assert checked > 2000, f"only {checked} interior contour segments examined"
    # measured on this corpus: 8.4 mm and 4.0 mm. The bounds are a third of the interval, which is
    # loose enough to survive a smoothing difference and tight enough that a real break fails.
    # Both figures were 11.8 mm and 5.8 mm while the renderer and this test shared an off-by-half;
    # correcting both TIGHTENED them, which is the corroboration that the registration was the fault
    # and not the smoothing.
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
    198 of 198 greens agree exactly; the one difference sits 0.1 degrees from an octant boundary."""
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
        k = 0.03                                     # a 3% plane: fall unambiguously "clear"
        z = np.fromfunction(
            lambda r, c: 100.0 - k * math.sin(th) * px_x * c + k * math.cos(th) * px_y * r,
            (H, W), dtype=float)
        np.save(os.path.join(gate_course, "dem_hd", f"hole{hole:02d}.npy"), z)

        _svg, summ = render_green.render(hole)
        assert summ["feeds"] == want, (
            f"a plane falling toward bearing {bearing} deg (approach due north) must read "
            f"{want!r}, got {summ['feeds']!r} -- the card frame is rotated wrongly")
        assert summ["conf"] == "clear", (
            f"a 3% plane's fall should read 'clear', got {summ['conf']!r}. The values are\n"
            f"clear/faint, describing the EVIDENCE -- whether the fall stands above the survey noise.\n"
            f"They were firm/subtle, which a golfer reads as a claim about the TURF, the one thing\n"
            f"render_green's own docstring says it cannot know.")
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
    disagreement reached 16 yd (two clubs), and on 98 of 198 greens the old value was closer to the
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

    # THE VERDICT, BY TRUTH TABLE. This reached the coverage half only by grepping the source for
    # "uncovered > UNCOVERED_MAX" -- so a gate that stopped refusing would have gone unnoticed, and in a
    # file whose comments quote that very expression the grep was one edit from being satisfied by
    # prose. Coverage is the gate that matters most here: nan_frac cannot see an INTERIOR void, because
    # standing water absorbs 1064 nm and the interpolation spans the hole and counts it as measured. A
    # demo deleting the returns in a 6 m circle at each green centre reported nan_frac 0.0000 while
    # changing 7 of 18 printed reads.
    for (nf, dens, unc), want, why in (
            ((0.0, 10.0, 0.0), False, "a well-measured green must be read"),
            ((fdh.NAN_FRAC_MAX + 0.01, 10.0, 0.0), True, "extrapolated past the hull gate"),
            ((0.0, fdh.DENSITY_MIN - 0.1, 0.0), True, "too few returns per m2 inside the ring"),
            ((0.0, 10.0, fdh.UNCOVERED_MAX + 0.01), True,
             "an INTERIOR void -- the case nan_frac and density both miss"),
            ((0.0, fdh.DENSITY_MIN, fdh.UNCOVERED_MAX), False,
             "exactly at both floors must still be read, or the gate refuses what it accepts")):
        assert fdh.is_insufficient(nf, dens, unc) is want, (
            f"fetch_dem_hd.is_insufficient({nf}, {dens}, {unc}) returned "
            f"{fdh.is_insufficient(nf, dens, unc)}, expected {want}: {why}")
    src = open(os.path.join(ROOT, "fetch_dem_hd.py"), encoding="utf-8").read()
    assert "is_insufficient" in _code_only(src.split("def is_insufficient", 1)[1]), (
        "fetch_dem_hd defines the gate but main() never calls it, so nothing is refused")
    # after the import, so removing the query while keeping `from scipy.spatial import cKDTree`
    # cannot satisfy this -- the same import-vs-use hole that let a proxy string stand in for the
    # scorecard's nine-hole branch elsewhere in this file
    assert "cKDTree(" in src.split("import cKDTree", 1)[1], \
        "coverage needs a nearest-return query, not just the import"
    assert 0 < fdh.COVER_R_M <= 2.0 and 0 < fdh.UNCOVERED_MAX <= 0.10


@needs_corpus
def test_every_built_green_records_its_coverage():
    """The gate's inputs must be recorded in the meta, so a printed read can be audited after the
    fact rather than taken on trust.

    Across the corpus the worst uncovered share stays under 1% against the 2% gate, and the worst
    in-green density above 4.5 pts/m^2 against the 4.0 floor. Deliberately bounds rather than exact
    figures: the exact worst shifts whenever a course is added or re-fetched, and both this docstring
    and fetch_dem_hd.py's comment had drifted to 0.9%/0.87% against an actual 0.71%.
    """
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
            # Water is inked TWO ways and both must count, which is where this test used to be as
            # blind as the code it guards. A pond is a filled polygon; a stream or ditch is a blue
            # POLYLINE, drawn from the same palette and just as wet. Counting only the fill let 17
            # cards print "0W" over visible blue -- merion 5 said it over five lines of Cobbs Creek.
            # The stroke-width is what separates a watercourse from a hazard polygon's own outline.
            drawn = (panel.count('fill="#efe3b8"'),
                     panel.count('fill="#a9d3ef"')
                     + panel.count('stroke="#5b9bd0" stroke-width="1.8"'))
            # Bunkers: exact. One drawn shape is one bunker.
            if footer[0] != drawn[0]:
                bad.append((slug, "bunkers", footer[0], drawn[0]))
            # Water: DIRECTIONAL, not exact, and the direction is the honesty rule.
            #
            # A watercourse is split into several OSM ways at every road crossing and tag change, and
            # those ways are drawn as separate joined polylines that a reader sees as ONE creek. So the
            # footer counts distinct water (render_hole.watercourse_identity) while the map inks every
            # segment, and demanding equality here would force the footer back to counting OSM ways --
            # which is how copper-valley 11 came to print "7W" for two NHD reaches and merion 13 "2W"
            # for two ways both named Cobbs Creek.
            #
            # What must hold is the pair of one-sided rules:
            #   * never a count with no ink -- that is merion 13's original defect, "1W" whose only blue
            #     mark was a buried culvert. So footer > 0 requires ink, and footer <= drawn.
            #   * never ink with no count -- water visible on the map that the footer calls zero.
            if footer[1] > drawn[1]:
                bad.append((slug, "water counted but not drawn", footer[1], drawn[1]))
            if bool(footer[1]) != bool(drawn[1]):
                bad.append((slug, "water/ink disagree about whether there is any",
                            footer[1], drawn[1]))
    assert checked >= 150, f"only {checked} hole cards examined"
    assert not bad, (f"{len(bad)} of {checked} cards print a count that contradicts their own map "
                     f"(slug, what, footer, drawn): {bad[:6]}")


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


def test_the_1m_fallback_does_not_overwrite_a_good_lidar_green(tmp_path):
    """fetch_dem.py (1 m seamless) writes into the SAME dem_hd/ as fetch_dem_hd.py (0.4 m LiDAR) and
    used to rewrite every hole it was given. So running it without ONLY= silently replaced every
    0.4 m green with the coarse 1 m one, saying nothing about the better data it had just discarded.

    The books stayed HONEST throughout -- each affected card prints "1 m data" -- but a whole course
    quietly lost its precision, which is why no gate caught it. Found cold-building Monarch Bay:
    3,889,124 bytes against the committed 4,973,620, with "1 m data" on greens that have real LiDAR.
    Verified after the fix on a copy of that course: 12 LiDAR surfaces kept, only the 6 seamless
    holes rewritten.

    It now FILLS GAPS by default; OVERWRITE=1 is the explicit way to replace a good surface."""
    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_dem"):
        sys.modules.pop(m, None)
    try:
        import fetch_dem as fd
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    def meta(name, **kw):
        p = tmp_path / name
        p.write_text(json.dumps(kw))
        return str(p)

    lidar = {"source": "USGS 3DEP LiDAR ground returns @0.4m", "insufficient": False}
    # a good LiDAR surface must be kept
    assert fd.keeps_existing_surface(meta("a.json", **lidar)) is True
    # ...but not when it is the very gap this stage exists to fill
    assert fd.keeps_existing_surface(
        meta("b.json", source=lidar["source"], insufficient=True)) is False
    # an existing seamless surface may be refreshed
    assert fd.keeps_existing_surface(
        meta("c.json", source="USGS 3DEP seamless 1 m @0.5m sampling", insufficient=False)) is False
    # absent or unreadable: rebuilding is the repair
    assert fd.keeps_existing_surface(str(tmp_path / "nope.json")) is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert fd.keeps_existing_surface(str(bad)) is False
    # and the override must be explicit
    assert fd.keeps_existing_surface(meta("d.json", **lidar), overwrite=True) is False

    # the loop must actually consult it, or the guard is decoration
    src = open(os.path.join(ROOT, "fetch_dem.py"), encoding="utf-8").read()
    assert "keeps_existing_surface" in _code_only(src.split("def keeps_existing_surface", 1)[1]), \
        "fetch_dem.py defines the guard but never calls it"


def test_a_missing_green_surface_explains_itself(tmp_path):
    """render_green.render() died with a bare FileNotFoundError from json.load, several frames deep,
    naming a path and nothing else. The situation it describes is ordinary, not exotic:
    fetch_dem_hd.py builds only the greens with usable 0.4 m LiDAR ground returns, and the ones it
    refuses need the 1 m seamless fallback from fetch_dem.py. Monarch Bay has six such holes, so
    running generate.py without fetch_dem.py hits this every time -- which is how it was found,
    cold-building that course.

    Every other stage here explains itself and names the command to run; this one now does too."""
    import shutil
    import subprocess

    slug = "_testmsg"
    d = os.path.join(ROOT, "courses", slug)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "dem_hd"))
    try:
        with open(os.path.join(ROOT, "courses", a_course(), "course.json"), encoding="utf-8") as f:
            j = json.load(f)
        j["slug"] = slug
        with open(os.path.join(d, "course.json"), "w", encoding="utf-8") as f:
            json.dump(j, f, indent=2)
        r = subprocess.run(
            [sys.executable, "-c",
             "import os;os.environ['COURSE']=%r;import render_green;render_green.render(1)" % slug],
            cwd=ROOT, capture_output=True, text=True)
        out = r.stdout + r.stderr
        assert r.returncode != 0, "a missing surface must not silently succeed"
        assert "FileNotFoundError" not in out, f"still a raw traceback:\n{out[-600:]}"
        assert "no green surface" in out, out[-600:]
        # it must name the hole and both stages that produce a surface
        assert "hole 1" in out and "fetch_dem_hd.py" in out and "fetch_dem.py" in out, out[-600:]
    finally:
        shutil.rmtree(d, ignore_errors=True)


@needs_corpus
def test_every_green_surface_records_its_gate_verdict():
    """Each dem_hd meta must state what the honesty gate concluded -- nan_frac and insufficient --
    not leave them absent.

    Six of 198 did: Monarch Bay's seamless greens (holes 1, 9, 10, 16, 17, 18) carried neither key,
    because they were written by a version of fetch_dem.py that predated the gate being added, and
    were never regenerated after it was. `None` is falsy, so they rendered exactly as
    insufficient=False would -- and independently recomputing the gate from the committed surfaces
    confirms False is the right answer (nan_frac 0.0000 against a 0.02 limit). Nothing printed was
    wrong, and no gate was bypassed either: render_green.py recomputes nan_frac from the surface
    itself rather than trusting the meta.

    But a record whose whole purpose is to say what was measured must not be silent about it -- an
    auditor reading hole01.json would have found no verdict at all. Regenerating those six left all
    18 surfaces byte-identical and the book identical at 4,973,620 bytes, which is what made the fix
    safe to apply.
    """
    missing = []
    checked = 0
    for slug in CORPUS:
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
            checked += 1
            # fetch_dem_hd runs THREE honesty gates -- extrapolation (nan_frac), in-green density,
            # and coverage (uncovered) -- and this required the verdict of only one of them plus the
            # outcome. A surface written without `uncovered` would pass while carrying no record that
            # the coverage gate ever ran, and coverage is the gate added specifically because nan_frac
            # cannot see an INTERIOR void: standing water absorbs 1064 nm, so a hole in the middle of a
            # green is spanned by the interpolation and counted as measured.
            #
            # Required for the 192 point-cloud surfaces. The 6 seamless ones come from fetch_dem.py,
            # which has no point cloud to measure coverage or density against and legitimately records
            # neither -- so the requirement is keyed on the surface's own recorded source.
            seamless = "seamless" in str(m.get("source", "")).lower()
            need = (("nan_frac", "insufficient") if seamless else
                    ("nan_frac", "insufficient", "uncovered", "density"))
            for key in need:
                if m.get(key) is None:
                    missing.append(f"{slug} hole {m.get('hole')}: {key} absent "
                                   f"(source={str(m.get('source'))[:34]})")
    assert checked, "no green surfaces to check"
    assert not missing, (
        f"{len(missing)} green surface(s) record no gate verdict -- regenerate them "
        f"(fetch_dem_hd.py, then fetch_dem.py for the gaps):\n  " + "\n  ".join(missing[:12]))


@needs_corpus
def test_derived_artifacts_are_not_older_than_their_inputs():
    """The pipeline is a chain -- osm_geom/osm_course -> dem_hd -> trees_lidar -> greenbook.html --
    and re-running one stage without the ones downstream leaves a book built from mixed vintages.

    That happened, and only the cold-build test caught it. Re-fetching OSM to recover the fairways
    changed which polygons trees may sit on; the books were rebuilt but fetch_trees.py was not, so 7
    courses drew trees that the new fairways should have dropped. Micke Grove was the measurable
    case: 5,642 markers committed and 5,642 on a fresh run, exactly the 15 markers now falling on
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
        assert "assert_one_green_per_hole" in _code_only(src), (
            f"{mod} never CALLS assert_one_green_per_hole. Checked against the tokenised source: "
            f"fetch_dem.py explains that function in a comment, which satisfied a plain grep, so "
            f"deleting the live call left this test green (proven by mutation).")

    # fetch_dem.py used to name a local list `geo`, shadowing the module; it worked only because
    # `import geo` sat inside the loop. Moving that import to the top -- the obvious tidy-up -- would
    # have made geo.match_green() an AttributeError on a list from the second hole onward.
    fd = open(os.path.join(ROOT, "fetch_dem.py"), encoding="utf-8").read()
    assert "for p in geo]" not in fd, "a local named `geo` is shadowing the geo module again"



@needs_corpus
def test_green_binding_wins_by_a_wide_margin_not_a_hair():
    """Two tests already cover green binding. Neither says the decision was CLOSE, which is the thing
    that goes wrong first.

    test_a_hole_never_binds_to_a_distant_green pins the 40 m cap; test_no_built_green_surface_is_shared
    checks no green serves two holes. Both would pass with a hole whose own green sits 19 m away and a
    neighbour's at 20 -- a correct answer decided by a metre, one OSM edit from flipping. And a flipped
    binding is the worst single failure available here: the entire slope map, every arrow, the feed
    direction and the depth ladder all belong to a different hole, while the card looks perfect.

    Measured instead of assumed: the bound green is the nearest on all 198, by a median 107 m, and the
    tightest case is philadelphia 11 at 8.3 m against a runner-up at 41.3 m -- a five-fold ratio, not a
    coin toss. The floor here is 15 m, under half the tightest observed, so it flags a genuine near-tie
    without firing on the corpus.

    A near-tie is not necessarily a bug: two greens really can sit close, on a double green or a shared
    complex. But it is the point at which a human should look, rather than the point at which the code
    quietly picks one.

    One thing this measurement settled. Inverting match_green to bind the FARTHEST green within the cap
    changes nothing on 197 of 198 holes, because only ONE green is inside the 40 m cap on those -- merion
    18 is the sole exception, with its own green at 0.3 m and another at 38.1. So the cap does the work
    and the nearest-rule is a tiebreak that almost never has a tie to break. Useful to know before
    trusting a mutation of that rule: an ineffective mutation there means the cap is carrying the
    decision, not that the test is weak.
    """
    import math
    FLOOR_M = 15.0
    tight, checked, seen = [], 0, collections.Counter()
    for ref in CORPUS:
        p = os.path.join(ROOT, "courses", ref, "osm_geom.json")
        if not os.path.exists(p):
            continue
        cfg, _rh = _engine(ref)
        import geo
        with open(p, encoding="utf-8") as fh:
            els = json.load(fh)["elements"]
        greens = [e for e in els
                  if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        loc = cfg.COURSE.get("location") or {}
        try:
            lines = geo.hole_lines(els, loc.get("lat"), loc.get("lon"))
        except SystemExit:
            continue
        seen[ref] += 1
        for hn, w in sorted(lines.items()):
            try:
                bound, gend, _tend = geo.match_green(w["geometry"], greens)
            except Exception:
                continue
            mlon = 111320.0 * math.cos(math.radians(gend["lat"]))
            ds = []
            for g in greens:
                n = len(g["geometry"])
                la = sum(q["lat"] for q in g["geometry"]) / n
                lo = sum(q["lon"] for q in g["geometry"]) / n
                ds.append((math.hypot((gend["lat"] - la) * 111320.0,
                                      (gend["lon"] - lo) * mlon), g.get("id")))
            ds.sort()
            checked += 1
            assert bound.get("id") == ds[0][1], (
                f"{ref} hole {hn}: bound to green {bound.get('id')} at "
                f"{next(d for d, i in ds if i == bound.get('id')):.1f} m while green {ds[0][1]} is "
                f"nearer at {ds[0][0]:.1f} m")
            if len(ds) > 1 and (ds[1][0] - ds[0][0]) < FLOOR_M:
                tight.append(f"{ref} hole {hn}: its green is {ds[0][0]:.1f} m from the line end and "
                             f"another is {ds[1][0]:.1f} m -- a {ds[1][0] - ds[0][0]:.1f} m margin. One "
                             f"OSM edit could swap the whole slope map onto the wrong hole.")
    assert checked >= 150, f"only {checked} greens checked"
    assert_no_course_skipped(seen, "test_green_binding_wins_by_a_wide_margin_not_a_hair")
    assert not tight, ("a green binding rests on too little margin:\n  " + "\n  ".join(tight[:6]))


@needs_corpus
def test_no_built_green_surface_is_shared_by_two_holes():
    """The corpus half of the rule above: no green actually built is bound to two holes.

    Split out so each half keeps its own guarantee. The rule itself is a pure function and must be
    tested wherever the engine runs, including a fresh clone with no data; THIS is an assertion about
    built artifacts and has to skip when there are none. Left together, the corpus loop silently
    iterated nothing on an empty tree while the test still reported green.
    """
    checked = 0
    for slug in CORPUS:
        seen = {}
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
            gid, hn = meta.get("green_id"), meta.get("hole")
            if gid is None:
                continue
            checked += 1
            assert gid not in seen, f"{slug}: green {gid} bound to holes {seen[gid]} and {hn}"
            seen[gid] = hn
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} built green surfaces examined of {expected_geometry_holes()} holes with geometry")


@needs_corpus
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


@needs_corpus
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
    # with nothing said. Measured: 10 of 11 courses have every centreline node inside the data.
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
        assert "sweep_partials(" in src, \
            f"{mod} must remove stale partial downloads before deciding what is cached"

    # ...and the sweep itself must actually delete them. Asserting the source text of two
    # byte-identical copies is what kept the duplication alive; test the behaviour once instead.
    import fetch_lidar as _fl
    d = tmp_path / "sweep"
    d.mkdir()
    (d / "a.laz.part").write_bytes(b"\0" * 2048)
    (d / "keep.laz").write_bytes(b"\0" * 2048)
    _fl.sweep_partials(str(d))
    left = sorted(p.name for p in d.iterdir())
    assert left == ["keep.laz"], f"sweep_partials left {left}"


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
    assert whole[2] == 0, "no rings supplied -> no point is known to be over a green"

    over = ld.tile_dates(f, [ring])
    assert over is not None
    first, last, npts, crs_ok, wfirst, wlast = over
    assert npts == 100 and crs_ok is True, (npts, crs_ok)
    # the WHOLE-tile range must still span both days even though first/last are narrowed to the
    # green. main() builds its "over whole tiles the range would be" comparison from these, and it
    # used to build it from the narrowed first/last -- understating the very range it contrasts with.
    assert wfirst.date() == near.date() and wlast.date() == far.date(), (wfirst, wlast)
    assert first.date() == near.date() and last.date() == near.date(), (first, last)
    assert first.date() == near.date(), \
        (f"dated {first.date()}..{last.date()}; the 2018-01-21 points are 2 km from the green and "
         f"must not widen the range -- this is The Reserve's 38-day label")

    # a tile that covers NO green must report near=False so the caller can exclude it entirely
    far_ring = [(lon + 0.5 + a, lat + 0.5 + b) for a, b in
                ((-d, -d), (d, -d), (d, d), (-d, d))]
    none_over = ld.tile_dates(f, [far_ring])
    assert none_over[2] == 0, "a tile with no points over a green must report none"
    assert none_over[3] is True, "the greens WERE placeable here; only the points are absent"

    # The pad must be converted into the CRS's own units. Callippe's tiles are in US survey feet, so
    # treating 30 as feet shrinks the collar to 9.1 m and drops points genuinely on the green's
    # collar. Use a TINY ring so the pad -- not the green's own extent -- decides: a point 20 m out
    # is inside a 30 m collar and outside a 9.1 m one.
    tiny = 0.00002
    small_ring = [(lon - tiny, lat - tiny), (lon + tiny, lat - tiny),
                  (lon + tiny, lat + tiny), (lon - tiny, lat + tiny)]
    ft = _synthetic_laz(tmp_path / "ftus.laz", 2227, small_ring, near, far, near_offset_m=20.0)
    r = ld.tile_dates(ft, [small_ring])
    assert r[2] == 100, \
        (f"found {r[2]} points 20 m from the green in a ftUS tile; the {ld.GREEN_PAD_M:g} m pad was "
         f"probably not converted from metres")
    assert r[0].date() == near.date() and r[1].date() == near.date()

    # and a non-feeding tile must be dropped from the range, not folded into it
    src = open(os.path.join(ROOT, "tools", "lidar_dates.py"), encoding="utf-8").read()
    i = src.index("if rings and not nnear:")
    block = src[i:src.index("per_tile[name]", i)]   # scoped structurally, not by a character budget
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

    # size-based cache matching: write the two cell copies under the OTHER one's name.
    # SPARSE -- plan_downloads only ever calls os.path.getsize, and materialising these for real
    # cost ~572 MiB of tmpdir and a 317 MB peak allocation on every run.
    for _, n in todo:
        want = next(t["sizeInBytes"] for t, nn in todo if nn == n)
        with open(laz / n, "wb") as fh:
            fh.truncate(want)
    todo2, cached2 = fl.plan_downloads(tiles, str(laz))
    assert cached2 == 3 and not todo2, f"already-present copies re-scheduled: {todo2}"

    # a file of the wrong size must NOT satisfy the cache -- that is a truncated download
    with open(laz / same[0], "wb") as fh:
        fh.truncate(12345)
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
    with open(other / "USGS_LPC_CA_X_2021_B21_w9999n9999.laz", "wb") as fh:
        fh.truncate(317568432)
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
    # Both fetchers must reach ONE implementation of "which local file holds which copy". It was
    # written twice and the copies disagreed: fetch_lidar.plan_downloads matches the cache BY SIZE,
    # while fetch_lidar_alameda.py tested `os.path.getsize(fn) >= sz - 1024`, which is ONE-SIDED, so a
    # file LARGER than expected satisfied a smaller expectation. Measured at Callippe, where cell
    # w6165n2052 exists in CA_AlamedaCo_1_2021 at 21,981,521 bytes and CA_AlamedaCo_3_2021 at
    # 244,776,088 (both confirmed by HEAD): the 245 MB copy is on disk under the plain name and the
    # 22 MB one under `__Co1`, a name that module can never generate (sub-project 1 is probed first,
    # so it always takes the plain name). A re-run therefore called the Co_1 copy cached against the
    # 245 MB file and downloaded Co_3 again as `__Co3.laz`. fetch_dem_hd.py globs laz/*.laz with no
    # de-duplication, so 10 of Callippe's 18 greens would have published exactly twice their real
    # in-green density -- 13.0-15.8 pts/m2 becoming 26.0-31.6 in legal/03.
    #
    # Asserted as a DELEGATION, not as "the file mentions copy_suffix somewhere": that spelling was
    # satisfied by the word appearing in a COMMENT, which is the same dead assertion this file
    # records twice elsewhere (fetch_dem_hd's OVERWRITE guard, its DISOWNED_FLAGS set).
    ala = open(os.path.join(ROOT, "fetch_lidar_alameda.py"), encoding="utf-8").read()
    code = "\n".join(ln for ln in ala.splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))
    assert "fetch_lidar.plan_downloads(" in code, \
        "the Alameda fetcher must plan its downloads through the shared, size-matching implementation"
    assert not re.search(r"getsize\([^\n]*?\)\s*(>=|<=|>|<)", code), \
        ("the Alameda fetcher must not decide 'cached' with a size COMPARISON: "
         "`getsize(fn) >= sz - 1024` is one-sided, so it reported a 245 MB file as a cached 22 MB "
         "tile and re-downloaded the 245 MB copy under a second name")
    assert "__Co" not in code, \
        ("the Alameda fetcher must not spell the copy suffix at all -- naming belongs to "
         "fetch_lidar.copy_suffix. It had its own spelling once (`__Co_3_2021`, the sub-project's "
         "last 9 characters) and gen_provenance.py's `__Co\\d+` strip does not match it")
    # and the shared helper must yield __Co<digits> for every real Alameda sub-project
    for sub, want in (("CA_AlamedaCo_1_2021", "1"), ("CA_AlamedaCo_2_2021", "2"),
                      ("CA_AlamedaCo_3_2021", "3")):
        got = fl.copy_suffix(sub, 1, "USGS_LPC_X_w1n1", ".laz", set())
        assert got == f"USGS_LPC_X_w1n1__Co{want}.laz", (sub, got)
        assert re.search(r"__Co\d+\.laz$", got), got
    # ...and the shared planner must resolve the Callippe shape: a plain-named file holding the LARGER
    # sub-project copy, with the smaller one under a name the fetcher would never choose.
    cal = tmp_path / "callippe"
    cal.mkdir()
    stem = "USGS_LPC_CA_AlamedaCounty_2021_B21_w6165n2052"
    for nm, sz in ((f"{stem}.laz", 244776088), (f"{stem}__Co1.laz", 21981521)):
        with open(cal / nm, "wb") as fh:
            fh.truncate(sz)
    aroot = "https://x/Projects/CA_AlamedaCounty_2021_B21"
    todo5, cached5 = fl.plan_downloads(
        [{"downloadURL": f"{aroot}/CA_AlamedaCo_1_2021/LAZ/{stem}.laz", "sizeInBytes": 21981521},
         {"downloadURL": f"{aroot}/CA_AlamedaCo_3_2021/LAZ/{stem}.laz", "sizeInBytes": 244776088}],
        str(cal))
    assert cached5 == 2 and not todo5, \
        (f"both sub-project copies are already on disk under other names; re-fetching one duplicates "
         f"its points and doubles the density the legal record publishes. got {todo5}")


def test_an_unresolvable_head_is_never_reported_as_the_edge_of_the_survey():
    """The end-of-run NOTE asserts "not on the server (authoritative 404) ... That is the edge of the
    survey." An early exit added for speed made that claim reachable for a tile nobody ever got an
    answer about: tile_copies breaks at the top of its sub-project loop once anything is unresolved,
    so `copies` comes back empty and main() fell into its "absent" branch. Before that early exit all
    three sub-projects had to 404; afterwards one timeout was enough.

    The run does still abort, so no book is built on the invented gap -- but the printed provenance
    made exactly the false claim 08cb08d exists to prevent, two lines above the correct one. Reported
    by four independent review passes and reproduced under a simulated outage.

    Also covers head_size returning 0 for a 200 that carries no Content-Length: that is not an
    absence either, and it used to be dropped exactly like a 404."""
    import contextlib
    import io

    os.environ["COURSE"] = a_course()
    for m in ("config", "fetch_lidar_alameda"):
        sys.modules.pop(m, None)
    try:
        import fetch_lidar_alameda as fla
    except Exception as e:
        pytest.skip(f"not importable: {type(e).__name__}")

    real = fla.urllib.request.urlopen
    try:
        fla.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("outage"))
        buf = io.StringIO()
        exited = None
        with contextlib.redirect_stdout(buf):
            try:
                fla.main()
            except SystemExit as e:
                exited = str(e)
        out = buf.getvalue()
        assert "authoritative 404" not in out, \
            f"a total outage was reported as an authoritative 404:\n{out[-500:]}"
        assert "edge of coverage, skip" not in out, \
            f"a total outage was reported as the edge of coverage:\n{out[-500:]}"
        assert exited and "could not determine" in exited, \
            f"an unresolvable HEAD must still abort the run, got {exited!r}"

        # a 200 with no Content-Length is UNKNOWN, not ABSENT
        class _NoLen:
            headers = {}
        fla.urllib.request.urlopen = lambda *a, **k: _NoLen()
        assert fla.head_size("https://x/t.laz", tries=1) == fla.UNKNOWN, \
            "a 200 without Content-Length must not be read as 'this tile does not exist'"
    finally:
        fla.urllib.request.urlopen = real


def test_the_book_discloses_a_weaker_flight_basis(tmp_path):
    """tools/lidar_dates.py narrows the printed flight range to the points over the greens and records
    that in `basis`; where it cannot, it falls back to the union over WHOLE TILES. The legal
    provenance table qualifies such a range -- but the governing rule is about what the BOOK prints,
    and generate.py printed the bare label either way.

    A tile can span weeks while holding no point within a kilometre of any green: The Reserve's did,
    which is how "flown 2017-12-15 to 2018-01-21" came to be printed for greens flown on two days.

    Both surfaces also fail CLOSED on a MISSING basis, because a record written before the
    distinction existed had a whole-tile label -- so silence must read as the weaker claim."""
    for m in ("config", "generate"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = a_course()
    import generate

    saved = dict(generate.config.COURSE)
    try:
        for basis, want_qualified in [
                (f"points within 30 m of a green", False),
                ("whole tiles (no points found over any green)", True),
                (None, True),                      # absent -> must read as the weaker claim
        ]:
            fl = {"label": "2017-12-16 to 2017-12-17"}
            if basis is not None:
                fl["basis"] = basis
            generate.config.COURSE["lidar_flown"] = fl
            line = generate._flown_line()
            assert "2017-12-16 to 2017-12-17" in line, line
            qualified = "covers whole survey tiles" in line
            assert qualified == want_qualified, \
                f"basis={basis!r}: qualified={qualified}, expected {want_qualified} -- {line}"
    finally:
        generate.config.COURSE.clear()
        generate.config.COURSE.update(saved)


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
    # scope to the REPORTING block in main(), not the early-exit `if unknown: break` that stops
    # probing once the run is already doomed
    i = src.index("could not determine whether")
    assert "raise SystemExit" in src[max(0, i - 300):i + 200], \
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
    # prev is read BEFORE the try. Assigned inside it -- as it was -- any raise from the three
    # json.dump calls below made the finally clause die with UnboundLocalError, replacing the real
    # error with a bogus one at the exact moment you need to read it.
    prev = os.environ.get("COURSE")
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
        # Restore FIRST, then clean up -- the same ordering fault synth_engine had. os.rmdir raises on
        # a non-empty directory, and the raise skipped the restore, leaving COURSE bound to a slug whose
        # course.json had just been deleted; every later test that imported config then died. rmtree does
        # not care what is in the way.
        _restore_course(prev)
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)


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


@needs_corpus
def test_elevation_change_scales_only_the_tee_height():
    """The green surface is already metres; only the raw LAZ tee height takes the CRS axis scale.

    The code read `(green - tee) * vscale`, subtracting a US-survey-foot tee height from a metric green
    height and then scaling the difference. Silent and large: monarch-bay hole 3 printed "green 21 ft
    below the tee" for a real -6.2 ft, and 5 of the 11 courses were affected. The other 6 are metric,
    where vscale is 1.0 and the two forms coincide -- so checking Merion, which is metric, could never
    have caught it. That is why this test pins a ftUS case explicitly."""
    _config, _rh = _engine(CORPUS[0])
    import fetch_hole_elev as fhe
    FT_US = 0.30480060960121924
    got = fhe.elevation_change_m(6.53, 27.62, FT_US)          # monarch-bay hole 3, measured
    assert abs(got * 3.28084 - (-6.2)) < 0.15, f"{got*3.28084:.2f} ft, expected about -6.2"
    buggy = (6.53 - 27.62) * FT_US
    assert abs(got - buggy) > 1.0, "this is the buggy form; only the tee takes the scale"
    # metric course: the two forms must agree, which is precisely why the bug hid
    assert fhe.elevation_change_m(100.0, 90.0, 1.0) == 10.0
    assert abs(fhe.elevation_change_m(100.0, 90.0, 1.0) - (100.0 - 90.0) * 1.0) < 1e-12


@needs_corpus
def test_recorded_green_height_matches_the_built_surface():
    """hole_elev.json's green_z_m must equal the green surface's own median, unscaled.

    Independent of the arithmetic test above: this reads what was actually WRITTEN for every course,
    so a re-scaling reintroduced anywhere in the writer shows up as a factor-of-3.28 mismatch on the
    ftUS courses."""
    checked = 0
    for slug in CORPUS:
        p = os.path.join(ROOT, "courses", slug, "hole_elev.json")
        if not os.path.isfile(p):
            continue
        # fetch_hole_elev binds DIR = config.COURSE_DIR at IMPORT, and _engine only pops
        # config/render_hole/render_green -- so a cached copy keeps reading the FIRST course's files
        # and this test compared one course's json against another's surfaces.
        sys.modules.pop("fetch_hole_elev", None)
        _config, _rh = _engine(slug)
        import fetch_hole_elev as fhe
        rows = json.load(open(p))["holes"]
        for hn, row in rows.items():
            gz = fhe.green_elevation(int(hn))
            if gz is None:
                continue
            checked += 1
            assert abs(row["green_z_m"] - gz) < 0.02, (
                f"{slug} h{hn}: recorded green_z_m {row['green_z_m']} vs surface median {gz:.2f} -- "
                f"ratio {row['green_z_m']/gz if gz else 0:.3f} (3.28 means a double unit scale)")
    assert checked >= 100, f"only {checked} recorded green heights checked; expected the whole corpus"


@needs_corpus
def test_provenance_records_the_elevation_basis():
    """Every printed number must be traceable in legal/03, and the height change was not.

    The table accounted for OSM geometry, LiDAR project, flight dates, density and the scorecard, but
    said nothing about a figure printed on ~130 cards -- nor which of the two bases produced it. The
    par-3 extrapolated tee is a weaker claim than a tee sampled where the line starts, and a reader
    auditing a card cannot tell them apart without this."""
    doc = open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")).read()
    checked = 0
    for slug in CORPUS:
        p_elev = os.path.join(ROOT, "courses", slug, "hole_elev.json")
        if not os.path.isfile(p_elev):
            continue
        rows = json.load(open(p_elev))["holes"]
        name = json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))).get("name", slug)
        # match the FULL name: two Castlewood courses share a prefix, and a prefix match picked
        # the Hill row when checking the Valley course
        line = next((l for l in doc.splitlines() if l.startswith("| " + name + " |")), None)
        assert line, f"{name} has no provenance row"
        assert f"measured on {len(rows)} of" in line, (
            f"{name}: provenance does not record the {len(rows)} measured height changes")
        n_ex = sum(1 for r in rows.values() if "extrapolated" in str(r.get("tee_basis", "")))
        if n_ex:
            assert "extrapolated" in line, (
                f"{name}: {n_ex} hole(s) use an extrapolated tee and the doc does not say so")
        checked += 1
    assert checked >= 10, f"only {checked} courses checked; expected the corpus"


@needs_corpus
def test_no_implausible_elevation_figure_is_recorded():
    """No hole may record a tee-to-green change beyond the plausibility bound.

    The unit bug produced 300-550 ft figures that printed on real cards and read as data -- 74 of 175
    holes, median error 298 ft. Nothing in the pipeline objected, because every other check was about
    coverage and density, not magnitude. The largest genuine figure in the corpus is 151 ft, so the
    bound also has to be shown to be loose enough not to clip real terrain."""
    sys.modules.pop("fetch_hole_elev", None)
    _config, _rh = _engine(CORPUS[0])
    import fetch_hole_elev as fhe
    # the bound itself, directly: clean corpus data cannot trip it
    assert fhe.is_plausible_change(160.2) and fhe.is_plausible_change(-160.2)   # real castlewood 18
    assert not fhe.is_plausible_change(-500.0)      # what the unit bug produced
    assert not fhe.is_plausible_change(300.0)
    assert 200.0 <= fhe.MAX_PLAUSIBLE_FT <= 400.0, "bound moved outside a defensible range"
    worst, worst_at, n = 0.0, None, 0
    for slug in CORPUS:
        p = os.path.join(ROOT, "courses", slug, "hole_elev.json")
        if not os.path.isfile(p):
            continue
        for hn, row in json.load(open(p))["holes"].items():
            n += 1
            if abs(row["change_ft"]) > abs(worst):
                worst, worst_at = row["change_ft"], f"{slug} h{hn}"
            assert abs(row["change_ft"]) <= fhe.MAX_PLAUSIBLE_FT, (
                f"{slug} h{hn}: {row['change_ft']:+.1f} ft exceeds the {fhe.MAX_PLAUSIBLE_FT:.0f} ft "
                f"bound -- that is a units or datum fault, not terrain")
    assert n >= 150, f"only {n} figures checked; expected the whole corpus"
    # the bound must not be so tight that real hilly terrain trips it
    assert abs(worst) < fhe.MAX_PLAUSIBLE_FT * 0.85, (
        f"largest real figure {worst:+.1f} ft ({worst_at}) is close to the bound; raise it deliberately "
        f"rather than letting it clip terrain")


@needs_corpus
def test_tee_anchor_locates_the_back_tee_or_refuses():
    """The elevation figure names the BACK TEE, so the point sampled must actually be one.

    Two ways it silently was not, both fixed and both pinned here:

    * The old code took line geometry[0] as the tee. That is the tee end on all 198 corpus holes, so
      it worked by luck; a course traced GREEN-FIRST would have compared the green's height against
      itself and printed an elevation change of about zero -- plausible-looking, not obviously wrong.
      No course exercises this, so the reversed line is built here explicitly.

    * The mapped line stops short of the back tee on 19 of 198 holes, by up to 103 yd. Sampling there
      measures the fairway. A straight par 3 is recoverable by collinearity; a par 4/5 is not and must
      refuse. Merion 9 moved 11.5 ft (23.0 -> 34.5 ft below) once measured at the real tee, so this is
      not a rounding concern. (Was 22 holes and 138 yd, before valley-hi 17's 220 yd stub was replaced
      by its real 360 yd centreline -- see fetch_hole_elev.py, which carries the same figures.)"""
    for m in ("config", "render_hole", "fetch_hole_elev"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = "merion-golf-club"
    if not os.path.isdir(os.path.join(ROOT, "courses", "merion-golf-club")):
        pytest.skip("merion-golf-club not built")
    import config
    import fetch_hole_elev as fhe
    geom = json.load(open(os.path.join(ROOT, "courses", "merion-golf-club", "osm_geom.json")))["elements"]
    greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    holes = {}
    for e in geom:
        t = e.get("tags") or {}
        if t.get("golf") == "hole" and e.get("geometry"):
            r = t.get("ref")
            if r and r.isdigit() and len(e["geometry"]) > len(holes.get(int(r), {}).get("geometry", [])):
                holes[int(r)] = e

    def anchor(hn, line):
        return fhe.tee_anchor(hn, line, greens)

    def _match_green_for(hn):
        import geo
        return geo.match_green(holes[hn]["geometry"], greens)[0]

    def yd_from_green_of(hn, la_, lo_):
        g = _match_green_for(hn)
        gla_ = sum(p["lat"] for p in g["geometry"]) / len(g["geometry"])
        glo_ = sum(p["lon"] for p in g["geometry"]) / len(g["geometry"])
        return math.hypot((lo_ - glo_) * _mlon(gla_), (la_ - gla_) * R_LAT) / 0.9144

    # hole 7 spans its card -> anchored on the line's own tee end
    la, lo, basis = anchor(7, holes[7]["geometry"])
    assert la is not None and basis.startswith("tee end"), basis
    # and it must be the TEE end, i.e. about a hole's length from the green. Returning the green end
    # instead also satisfies the basis string and reversal-invariance, so check the position.
    d7 = yd_from_green_of(7, la, lo)
    assert abs(d7 - config.HOLES[7][2]) < 0.20 * config.HOLES[7][2], \
        f"spanning anchor sits {d7:.1f} yd from the green on a {config.HOLES[7][2]} yd hole"

    # hole 9: par 3, line 69 yd short -> tee recovered along the hole axis. Check WHERE it landed, not
    # merely that it moved: a sign error in the extrapolation also moves it (off toward the green),
    # and "it moved" accepted that mutation.
    g9 = _match_green_for(9)
    gla = sum(p["lat"] for p in g9["geometry"]) / len(g9["geometry"])
    glo = sum(p["lon"] for p in g9["geometry"]) / len(g9["geometry"])

    def yd_from_green(la_, lo_):
        return math.hypot((lo_ - glo) * _mlon(gla), (la_ - gla) * R_LAT) / 0.9144

    la9, lo9, b9 = anchor(9, holes[9]["geometry"])
    assert la9 is not None and "extrapolated" in b9, b9
    card9 = config.HOLES[9][2]
    d9 = yd_from_green(la9, lo9)
    assert abs(d9 - card9) < 3.0, f"par-3 tee should sit {card9} yd from the green centre, got {d9:.1f}"
    tend9 = holes[9]["geometry"][0]
    assert d9 > yd_from_green(tend9["lat"], tend9["lon"]) + 30.0, \
        "the recovered tee must be FURTHER from the green than the short line's end, not nearer"
    # ...and on the SAME SIDE. Distance-from-the-green alone cannot see a sign error: flipping the
    # extrapolation puts the anchor the card yardage away on the far side of the green, which keeps
    # that distance identical. So pin how far it sits from the line's own tee end -- the gap it was
    # meant to close, not roughly twice the hole.
    gap9 = card9 - yd_from_green(tend9["lat"], tend9["lon"])
    off9 = math.hypot((lo9 - tend9["lon"]) * _mlon(tend9["lat"]),
                      (la9 - tend9["lat"]) * R_LAT) / 0.9144
    assert abs(off9 - gap9) < 5.0, \
        f"recovered tee sits {off9:.1f} yd from the line's tee end but the gap is {gap9:.1f} yd"

    # ...and reversing hole 9's line must not move the anchor. The spanning branch returns the tee end
    # match_green picked, so it is reversal-safe on its own; the extrapolation reads pts[0], which is
    # where taking geometry[0] would silently start from the GREEN.
    r9 = anchor(9, list(reversed(holes[9]["geometry"])))
    assert r9[0] is not None and abs(r9[0] - la9) < 1e-7 and abs(r9[1] - lo9) < 1e-7, \
        f"reversed par-3 line anchored elsewhere: {r9[:2]} vs {(la9, lo9)} -- geometry[0] was used"
    r7 = anchor(7, list(reversed(holes[7]["geometry"])))
    assert abs(r7[0] - la) < 1e-9 and abs(r7[1] - lo) < 1e-9, "reversed spanning line moved"

    # holes 2/5/6/8: par 4 and 5 whose lines fall short -> must REFUSE, not guess
    for hn in (2, 5, 6, 8):
        la_, lo_, why = anchor(hn, holes[hn]["geometry"])
        assert la_ is None and lo_ is None, f"hole {hn} should refuse, got {(la_, lo_)}"
        assert "dogleg" in why, why


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


@pytest.mark.network          # re-fetches ~300 MB of LiDAR on purpose; see the _no_network fixture
@pytest.mark.skipif(not os.environ.get("COLD_BUILD"),
                    reason="set COLD_BUILD=1 to run: needs network and reprocesses ~300 MB of LiDAR")
def test_cold_build_reproduces_every_book_byte_for_byte():
    """End-to-end determinism, over the WHOLE corpus. Every other test checks one stage; this one
    runs the pipeline from nothing but course.json and the cached LAZ (fresh OSM fetch, fresh
    surfaces, fresh trees, fresh book) and requires each result to match the committed book EXACTLY.

    That property is what makes the provenance claims checkable: same inputs -> same book. It is also
    the only thing that catches CROSS-STAGE breakage, and it has earned its keep twice:

      * An OSM re-fetch changed which polygons a tree may sit on and the tree layers were not
        rebuilt. Micke Grove: 5,642 markers committed and 5,642 fresh.
      * fetch_dem.py rewrote every hole it was given instead of filling gaps, replacing good 0.4 m
        LiDAR greens with the 1 m DEM. Monarch Bay: 3,889,124 bytes against 4,973,620.

    It ran on ONE course until both of those were found by hand on others, so it now runs on all of
    them. Verified 2026-07-30, byte-for-byte: micke-grove 4,334,614; castlewood-hill 4,483,840;
    merion 5,878,513; monarch-bay 4,973,620; copper-valley 6,101,580; callippe 6,818,104;
    castlewood-valley 5,855,370; philadelphia 4,617,612; the-reserve 5,136,961.

    Courses carrying HAND-DIGITIZED geometry are handled separately, and that case is itself
    meaningful: a cold start has no cache for fetch_osm.py to preserve those features from, so a
    green traced from NAIP is simply absent. Such a course must then REFUSE to build --
    geo.match_green's distance cap fires rather than binding a hole to a neighbour's green. That is
    asserted here, not skipped silently. Which courses those are is read from the data, not listed:
    valley-hi was one until its osm_bbox was found to be ~46 m too tight, and widening it turned up
    the REAL OSM green its tracing had duplicated (1.3 m away, 33 vertices against 17) plus the real
    centreline for hole 17. With both placeholders removed it carries no digitized geometry and is
    cold-buildable. bay-view's box is fully covered, so its two traced greens are genuinely absent
    from OSM.

    Run:  COLD_BUILD=1 python3 -m pytest tests/ -q -k cold_build
    """
    import shutil
    import subprocess

    reproduced, refused, problems = [], [], []
    for ref in CORPUS:
        src = os.path.join(ROOT, "courses", ref)
        if not os.path.exists(os.path.join(src, "greenbook.html")):
            continue
        import distribution
        with open(os.path.join(src, "course.json"), encoding="utf-8") as f:
            if not distribution.is_distributable(json.load(f)):
                continue    # yardage mode: no green surfaces to reproduce. Asks the SHARED rule
                            # rather than re-testing build_mode == "yardage", which is the fragile
                            # exact form distribution.py exists to replace.
        try:
            with open(os.path.join(src, "osm_geom.json"), encoding="utf-8") as f:
                digitized = any("_digitized" in (e.get("tags") or {})
                                for e in json.load(f)["elements"])
        except Exception:
            digitized = False

        cold = "_cold_" + ref[:8]
        dst = os.path.join(ROOT, "courses", cold)
        shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst)
        try:
            with open(os.path.join(src, "course.json"), encoding="utf-8") as f:
                j = json.load(f)
            j["slug"] = cold
            with open(os.path.join(dst, "course.json"), "w", encoding="utf-8") as f:
                json.dump(j, f, indent=2)
            has_laz = os.path.isdir(os.path.join(src, "laz"))
            if has_laz:
                os.symlink(os.path.join(src, "laz"), os.path.join(dst, "laz"))
            # (script, extra args, extra env). fetch_hole_elev.py MUST be here: it was added after
            # this test was written, so the cold book came out with no elevation lines at all while the
            # committed one had 12 -- the byte-for-byte claim was quietly false for every course with a
            # point cloud. A new stage that writes into COURSE_DIR has to join this list or the
            # reproducibility guarantee silently stops covering the book it produces.
            stages = ([("fetch_osm.py", [], {}), ("fetch_dem_hd.py", [], {}),
                       ("fetch_dem.py", [], {}), ("fetch_trees.py", [], {}),
                       ("fetch_hole_elev.py", ["--write"], {}), ("generate.py", [], {})]
                      if has_laz else
                      [("fetch_osm.py", [], {}), ("fetch_dem.py", [], {}), ("generate.py", [], {})])
            # ...and the ENLARGED edition, for the courses that ship one. It is gated behind COACH=1, so
            # no normal build touches it and it sat outside every reproducibility guarantee the project
            # has -- which is how its legal text went stale in legal/05 unnoticed.
            has_coach = os.path.exists(os.path.join(src, "greenbook_coach.html"))
            if has_coach:
                stages.append(("generate.py", [], {"COACH": "1"}))
            env = {**os.environ, "COURSE": cold}
            failed = None
            for stage, args, extra in stages:
                r = subprocess.run([sys.executable, os.path.join(ROOT, stage)] + args, cwd=ROOT,
                                   env={**env, **extra}, capture_output=True, text=True)
                if r.returncode != 0:
                    failed = (stage + (" " + " ".join(args) if args else "")
                              + (" COACH=1" if extra.get("COACH") else ""),
                              (r.stdout + r.stderr)[-900:])
                    break
            if digitized:
                if failed is None:
                    problems.append(f"{ref}: built without its hand-digitized geometry -- the bind "
                                    f"cap should have refused")
                elif "_digitized" not in failed[1] and "bind limit" not in failed[1]:
                    problems.append(f"{ref}: failed at {failed[0]} for an unexpected reason: "
                                    f"{failed[1][-250:]}")
                else:
                    refused.append(ref)
                continue
            if failed:
                problems.append(f"{ref}: {failed[0]} failed: {failed[1][-250:]}")
                continue
            books = ["greenbook.html"] + (["greenbook_coach.html"] if has_coach else [])
            for book in books:
                with open(os.path.join(src, book), encoding="utf-8") as f:
                    a = f.read()
                cold_book = os.path.join(dst, book)
                if not os.path.exists(cold_book):
                    problems.append(f"{ref}: {book} was not produced by the cold build")
                    continue
                with open(cold_book, encoding="utf-8") as f:
                    b = f.read()
                if a == b:
                    reproduced.append((f"{ref}/{book}", len(a)))
                else:
                    w = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                             min(len(a), len(b)))
                    problems.append(
                        f"{ref} {book}: differs ({len(a)} vs {len(b)} bytes), first at byte {w}: "
                        f"a=...{a[max(0, w - 60):w + 30]!r} b=...{b[max(0, w - 60):w + 30]!r}")
        finally:
            shutil.rmtree(dst, ignore_errors=True)

    assert reproduced, "no course was cold-built -- nothing was verified"
    # AND A MAJORITY MUST ACTUALLY HAVE BEEN COMPARED. `assert reproduced` alone passes on ONE course,
    # so once a network failure became a refusal rather than a problem (see above), a bad Overpass day
    # could verify 1 of 11 and still read as a clean reproducibility run -- the exact silent skip the
    # comment below warns about, reintroduced by the fix for the false accusation. Failing here is the
    # honest outcome: this test is gated behind COLD_BUILD=1, i.e. it is run deliberately, and "the
    # service was busy so we checked one course" is a result the operator needs told, not hidden.
    _built = {n.split("/")[0] for n, _ in reproduced}
    _want = {ref for ref in CORPUS
             if os.path.exists(os.path.join(ROOT, "courses", ref, "greenbook.html"))}
    assert len(_built) * 2 > len(_want), (
        f"only {len(_built)} of {len(_want)} courses could be cold-built ({sorted(_want - _built)} were "
        f"refused), so this run is not evidence of reproducibility either way. If the refusals are "
        f"network failures, re-run when Overpass is quiet; the books themselves are not implicated.")
    # A silent skip would pass this test while verifying less than it claims, which is exactly how the
    # enlarged edition stayed outside the guarantee in the first place. So name what MUST have been
    # compared: every course that ships an enlarged book.
    want_coach = {f"{ref}/greenbook_coach.html" for ref in CORPUS
                  if os.path.exists(os.path.join(ROOT, "courses", ref, "greenbook_coach.html"))
                  and ref not in refused}
    got = {name for name, _ in reproduced}
    missed = sorted(want_coach - got)
    assert not missed, f"enlarged book(s) never compared by the cold build: {missed}"
    assert not problems, "cold build is not reproducible:\n  " + "\n  ".join(problems)


def test_the_cross_flight_check_shares_the_renderers_plane_fit():
    """A checker with its own copy of the arithmetic verifies a number nobody prints.

    tools/cross_flight_check.py is the project's only evidence that the printed slope read is
    reproducible across independent surveys, and that the 15 cm contour interval sits well above the
    noise floor (legal/09_GREEN_SURFACE_REPEATABILITY.md). That evidence is only about the CARD if the
    tool derives its figures the way the card does, which is why green_summary was lifted to module
    scope in render_green.py. Inline a second plane fit into the tool and both sides keep passing while
    the tool quietly measures its own arithmetic.

    Checked by OBSERVING THE CALL, not by grepping the source. An earlier version asserted "lstsq" was
    absent from the tool and "green_summary(" present after the import -- a proxy, and this suite has
    now watched proxies fail twice: the fresh-clone guard pattern-matched for a property and missed
    three real violations, and a scrollHeight probe could not see the overflow it existed to catch. A
    tool that computed its own plane through np.linalg.solve, or via a helper in another module, would
    satisfy every string the old test wanted.

    So: replace render_green.green_summary with a recorder, run the tool's own summary path over a
    synthetic green, and require that the recorder was called. If the tool stops routing through the
    renderer's function, nothing gets recorded and this fails.
    """
    import numpy as np
    tool = os.path.join(ROOT, "tools", "cross_flight_check.py")
    assert os.path.exists(tool), "tools/cross_flight_check.py is gone; delete this test or the claim"

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    for m in ("config", "geo", "render_green", "cross_flight_check"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = a_course()
    import render_green as rg
    import cross_flight_check as cfc

    real = rg.green_summary
    calls = []

    def recorder(arr, mask, px_x, px_y, putt=None):
        calls.append((arr.shape, int(mask.sum()), putt is not None))
        return real(arr, mask, px_x, px_y, putt=putt)

    # a small synthetic green: a plane tilted east, inside a square outline
    W = H = 40
    yy, xx = np.mgrid[0:H, 0:W]
    meta = {"W": W, "H": H, "bbox": [-100.0, 40.0, -99.999, 40.001], "hole": 1,
            "polygon": [[40.0002, -99.9998], [40.0002, -99.9992],
                        [40.0008, -99.9992], [40.0008, -99.9998]],
            "green_center": [40.0005, -99.9995]}
    rg.green_summary = recorder
    try:
        grid = cfc._grid(meta)
        assert grid[4].sum() > 50, "the synthetic outline did not rasterise; fix the fixture"
        # ORIENTATION IS NOT CHECKED HERE, AND THAT IS A KNOWN GAP. The fixture below tilts a SQUARE
        # green EAST, which is invariant under a vertical flip -- so this test observed the delegation
        # while cross_flight_check gridded every surface upside down and half a cell out, for as long as
        # it existed (linspace(ymin, ymax, H) puts row 0 at the SOUTH edge on bbox EDGES; the shipped
        # surface is north-up on cell centres). Fixed in the tool, and the corrected corpus run is the
        # evidence: the rendered-surface noise floor fell from RMS 0.85 cm to 0.56 cm and the contour
        # interval went from 18x it to 27x.
        #
        # Two attempts to guard it here were themselves unfalsifiable and are recorded so the third is
        # not: a source grep for "linspace(ymin, ymax" is satisfied by the COMMENT in the tool that
        # explains the fix, and recomputing the expected cell centres in the test compares them only
        # against themselves. The sound check is to grid one real green from its LAZ through the tool
        # and difference it against the shipped .npy -- a mirrored grid shows up as a vertical flip. It
        # needs point data, so it belongs with the other LAZ-reading tests, not in this fixture.
        lon = (-100.0) + (xx.ravel()/W)*0.001
        lat = 40.0 + (yy.ravel()/H)*0.001
        z = (xx.ravel()/W)*2.0                      # 2 m of fall across the green
        S = cfc._summary(meta, grid, lon, lat, z, 1.0)
    finally:
        rg.green_summary = real

    assert calls, (
        "tools/cross_flight_check.py did not call render_green.green_summary while summarising a "
        "green, so whatever it measures is no longer what the card prints. That is the exact drift "
        "green_summary was lifted to module scope to prevent.")
    assert S is not None and "tilt_pct" in S, "the tool's summary path returned nothing usable"
    assert S["tilt_pct"] > 0.5, (
        f"the tool read {S['tilt_pct']:.2f}% tilt off a surface with 2 m of fall across it, so it is "
        f"not actually measuring the surface it was handed")

    # and the renderer must still get its numbers from that same shared function
    with open(os.path.join(ROOT, "render_green.py"), encoding="utf-8") as f:
        src = f.read()
    assert src.count("lstsq") == 1, (
        "render_green.py fits a least-squares plane in more than one place, so the card and the "
        "cross-flight check can disagree about the same green")


@needs_corpus
def test_the_printed_read_is_fitted_to_putting_surface_only():
    """The tilt on the card must come from putting surface, not from bank inside the mapped outline.

    A green outline comes from OpenStreetMap. One drawn a little generously laps onto the surrounding
    bank, and erode(mask, 3) trims only about 1.2 m of collar while such a bank reaches 8 m inside the
    outline. philadelphia 18 is the worked case: 21% slope in one corner, 4.1 cm of surface texture
    against 1.2 cm over the rest of the green, sitting 0.9 ft above it. Fitting the plane through it
    printed "3.6%, feeds LEFT" where the putting surface alone reads "2.6%, feeds FRONT-LEFT" -- while
    the same card's legend tells the reader that ground over 10% is shown by colour precisely BECAUSE
    it is not a puttable read.

    Checked BEHAVIOURALLY, against the shipped books. An earlier version of this test asserted on the
    source -- that `fit = core & (slope <= SLOPE_LABEL_MAX_PCT)` appeared, that the plane used
    surf[fit] -- which is a proxy, and proxies have failed twice in this suite: the fresh-clone guard
    pattern-matched for a property and missed three real violations, and a scrollHeight probe could not
    see the overflow it was written to catch. A restructure that preserved every one of those strings
    while changing the answer would have passed. So instead: re-derive each green's tilt twice, once as
    shipped and once with the restriction lifted, and where the two disagree require the BOOK to print
    the restricted figure.

    31 of 198 greens distinguish the two, which is what gives the test teeth -- on the other 167 the
    question does not arise, and a test that only saw those would be measuring nothing.
    """
    import numpy as np
    restricted_wins, ambiguous, seen = [], 0, collections.Counter()
    for slug in geometry_courses():
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not os.path.exists(book):
            continue
        seen[slug] += 1
        os.environ["COURSE"] = slug
        for m in ("config", "geo", "render_green"):
            sys.modules.pop(m, None)
        import render_green as rg
        from geo import R_LAT, mlon
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        printed = {}
        for blk in re.split(r'<div class="panel hole">', html)[1:]:
            hn = re.search(r'class="hnum">(\d+)<', blk)
            # The qualifier is OPTIONAL and only ever "(faint)": it prints on the minority of greens
            # whose fall is inside the survey noise, and on none of the rest. This pattern required it,
            # so when the card stopped printing "(firm)" on every green the parse silently returned
            # None for 195 of 198 holes and the comparison below had nothing left to compare -- a test
            # that would have gone quiet rather than red if the format had drifted the other way.
            rd = re.search(r'(?:feeds <b>[^<]*</b>|<b>no clear fall</b>)(?: \(faint\))?'
                           r' &middot; ([\d.]+)%', blk)
            if hn and rd:
                printed[int(hn.group(1))] = float(rd.group(1))
            elif hn and 'class="gwrap"' in blk and 'GREEN' in blk:
                # A green panel whose slope phrase did not parse. Either the green is legitimately
                # unread (the honesty gate refused it, so no % prints at all) or this pattern has gone
                # stale. Only the first is allowed to be silent.
                assert 'no slope' in blk or '%' not in blk.split('class="gwrap"')[1][:400], (
                    f"{slug} hole {hn.group(1)}: a green card prints a slope % that this test could not "
                    f"parse, so it was skipped rather than checked. The footer format has drifted away "
                    f"from the pattern above -- fix the pattern, do not let the check go quiet.")
        for mp in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            with open(mp, encoding="utf-8") as fh:
                meta = json.load(fh)
            if meta.get("insufficient"):
                continue
            arr = np.load(mp.replace(".json", ".npy"))
            H, W = arr.shape
            x0, y0, x1, y1 = meta["bbox"]
            px_x = (x1-x0)*mlon(meta["green_center"][0])/W
            px_y = (y1-y0)*R_LAT/H
            poly = rg.poly_to_px(meta["polygon"], meta["bbox"], W, H)
            X, Y = np.meshgrid(np.arange(W)+0.5, np.arange(H)+0.5)
            mask = np.zeros((H, W), bool)
            n = len(poly); j = n-1
            for i in range(n):
                xi, yi = poly[i]; xj, yj = poly[j]
                mask ^= ((yi > Y) != (yj > Y)) & (X < (xj-xi)*(Y-yi)/(yj-yi+1e-12)+xi)
                j = i
            if mask.sum() < 50:
                continue
            arr = np.where(np.isnan(arr), float(np.nanmedian(arr[mask])), arr)
            _s, _c, S = rg.green_summary(arr, mask, px_x, px_y)
            _s2, _c2, U = rg.green_summary(arr, mask, px_x, px_y, putt=np.ones_like(mask))
            r_t, u_t = round(S["tilt_pct"], 1), round(U["tilt_pct"], 1)
            if r_t == u_t:
                ambiguous += 1
                continue
            got = printed.get(meta["hole"])
            restricted_wins.append((slug, meta["hole"], got, r_t, u_t))
    assert_no_course_skipped(seen, "test_the_printed_read_is_fitted_to_putting_surface_only")
    assert len(restricted_wins) >= 20, (
        f"only {len(restricted_wins)} greens distinguish a putting-surface fit from an unrestricted "
        f"one ({ambiguous} could not tell them apart), so this test has almost no purchase. If the "
        f"corpus really changed that much, re-measure; do not just lower this number.")
    wrong = [(s, h, g, r, u) for s, h, g, r, u in restricted_wins if g != r]
    assert not wrong, (
        "the book printed a tilt fitted to ground the same card calls unputtable:\n  "
        + "\n  ".join(f"{s} hole {h}: book prints {g}%, putting surface reads {r}%, "
                       f"including the bank gives {u}%" for s, h, g, r, u in wrong[:8]))


@needs_corpus
def test_a_green_whose_plane_and_arrows_conflict_names_no_direction():
    """When the card's two derivations of the fall point opposite ways, it must not pick one.

    Each green states which way the ball rolls twice: the footer word, from a plane over the putting
    surface, and the arrows, from every local gradient. They answer slightly different questions and
    are expected to differ a little -- median 11 deg across the corpus, 90th percentile 27. Past 90
    deg they are giving opposite breaks, and no honest word exists. micke-grove 2 is the one: 0.5% of
    tilt, plane and arrows 177 deg apart, where naming either is a coin toss dressed as a read.

    So the refusal must actually reach print. Asserted on the built books rather than on the source,
    because a sentinel the renderer sets and the layout drops would leave the contradiction on the
    card while every unit-level check passed.
    """
    import render_green
    found, seen = [], collections.Counter()
    for ref in BOOKS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        seen[ref] += 1
        with open(p, encoding="utf-8") as f:
            html = f.read()
        for blk in re.split(r'<div class="panel hole">', html)[1:]:
            hn = re.search(r'<div class="hnum">(\d+)</div>', blk)
            if not hn:
                continue
            if render_green.NO_CLEAR_FALL in blk:
                found.append(f"{ref} hole {hn.group(1)}")
                # it must NOT be phrased as a direction
                assert f'feeds <b>{render_green.NO_CLEAR_FALL}' not in blk, (
                    f"{ref} hole {hn.group(1)} prints 'feeds {render_green.NO_CLEAR_FALL}', which "
                    f"reads as a compass direction -- the whole point is to name none")
                # the measured tilt is still true and must still be shown
                assert re.search(r'&middot; [\d.]+%', blk), (
                    f"{ref} hole {hn.group(1)} refuses the direction AND drops the measured tilt; "
                    f"the percentage is still a fact and the card should keep it")
    assert_no_course_skipped(seen, "test_a_green_whose_plane_and_arrows_conflict_names_no_direction")
    assert found, (
        "no green in the corpus prints the no-clear-fall wording. micke-grove 2 did (0.5% tilt, plane "
        "and arrows 177 deg apart). If a data or threshold change made every green consistent that is "
        "good news, but verify it rather than assuming: an unreachable refusal path is a refusal that "
        "will not fire when it is next needed.")


@needs_corpus
def test_a_mapped_green_is_mostly_puttable_ground():
    """An OSM green outline drawn around the whole COMPLEX corrupts every figure for that hole.

    The outline is the one piece of a green card that is not measured here -- it comes from an
    OpenStreetMap mapper. Everything else is derived from it: the printed depth and width, the 5-yard
    depth ladder, the extent of the heat colouring and the contours, and (until the plane fit was
    restricted) the tilt and feed word. So a mapper who traced the green complex -- putting surface
    plus its surrounds and bunker faces -- makes all of those wrong at once, in a way no other check
    in this suite looks for: `check_osm_bbox.py` tests the FETCH box, and the drawing tests only
    confirm that nothing is drawn outside the outline, not that the outline is right.

    Ground steeper than SLOPE_LABEL_MAX_PCT is the available proxy: this renderer, and the card's own
    legend, already call it "not putting surface (a bank or bunker face inside the mapped edge)". A
    real green is mostly not that. Measured across the corpus the fraction runs p50 0.4%, p90 8.0%,
    p99 19.5%, worst 21.6% (copper-valley 3, followed by philadelphia 18 at 20.7% -- a genuine bank
    inside a slightly generous outline, which is what the tail of a healthy distribution looks like).

    The ceiling is deliberately loose. It is not a mapping-quality bar -- a fifth of an outline being
    bank is already worth a look, and this would pass it -- but a tripwire for an outline that is
    describing something other than a putting green.
    """
    import numpy as np

    def mask_of(poly, W, H):
        """Vectorized crossing-number; verified identical to render_green.point_in_poly."""
        X, Y = np.meshgrid(np.arange(W)+0.5, np.arange(H)+0.5)
        inside = np.zeros((H, W), bool)
        n = len(poly); j = n-1
        for i in range(n):
            xi, yi = poly[i]; xj, yj = poly[j]
            inside ^= ((yi > Y) != (yj > Y)) & (X < (xj-xi)*(Y-yi)/(yj-yi+1e-12)+xi)
            j = i
        return inside

    CEILING = 0.35
    worst, checked, bad, seen = (0.0, None), 0, [], collections.Counter()
    for slug in geometry_courses():
        os.environ["COURSE"] = slug
        for m in ("config", "geo", "render_green"):
            sys.modules.pop(m, None)
        import render_green as rg
        from geo import R_LAT, mlon
        for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("insufficient"):
                continue
            arr = np.load(p.replace(".json", ".npy"))
            H, W = arr.shape
            x0, y0, x1, y1 = meta["bbox"]
            px_x = (x1-x0)*mlon(meta["green_center"][0])/W
            px_y = (y1-y0)*R_LAT/H
            mask = mask_of(rg.poly_to_px(meta["polygon"], meta["bbox"], W, H), W, H)
            if mask.sum() < 50:
                continue
            arr = np.where(np.isnan(arr), float(np.nanmedian(arr[mask])), arr)
            _surf, _core, S = rg.green_summary(arr, mask, px_x, px_y)
            frac = float((mask & (S["slope"] > rg.SLOPE_LABEL_MAX_PCT)).sum())/float(mask.sum())
            checked += 1
            seen[slug] += 1     # past the gates: a course yielding no surface now fails
            if frac > worst[0]:
                worst = (frac, f"{slug} hole {meta['hole']}")
            if frac > CEILING:
                bad.append(f"{slug} hole {meta['hole']}: {frac*100:.0f}% of the mapped green is "
                           f"steeper than {rg.SLOPE_LABEL_MAX_PCT:.0f}%, so the outline is describing "
                           f"a green complex rather than a putting surface -- its printed depth, "
                           f"depth ladder and colouring all describe ground you cannot putt on")
    assert checked >= expected_geometry_holes() - 18, (
        f"only {checked} greens measured of {expected_geometry_holes()} with geometry -- a course "
        f"was skipped, and this check is worthless on the course it skipped")
    # This loop iterates geometry_courses() -- the same set the guard checks against -- so
    # incrementing at the TOP made the assertion literally `not (X - X)`, unfalsifiable by any change
    # to the code under test. Counting past the per-surface gates is what gives it teeth.
    assert_no_course_skipped(seen, "test_a_mapped_green_is_mostly_puttable_ground")
    assert not bad, "green outline(s) do not describe a putting surface:\n  " + "\n  ".join(bad)
    assert worst[0] <= CEILING, f"worst {worst[0]*100:.1f}% at {worst[1]}"


def test_the_tree_finder_does_not_filter_on_a_vegetation_class():
    """Restricting tree candidates to class 5 would empty the tree layer on almost every course.

    fetch_trees.py's whole tree layer rests on a height-above-ground filter, NOT on the LiDAR
    vegetation classification, because 10 of the 11 courses with tiles carry zero class-5 points --
    their tiles are unclassified, class 1 + 2 only. A tidy-up that "correctly" restricted candidates
    to class 5 would look more principled and would silently produce a book with no trees at all,
    while every hole map still printed a legend promising them.

    The module docstring claimed the class-5 filter for a long time while the code deliberately did
    the opposite, which is how this became worth pinning down: the documentation was describing a
    version of the pipeline that would not have worked.

    Also checks the exclusions that make a height filter honest -- buildings, noise, water and bridge
    decks are not trees, and a roof reads exactly like canopy.
    """
    with open(os.path.join(ROOT, "fetch_trees.py"), encoding="utf-8") as f:
        src = f.read()

    body = src.split('"""', 2)[-1]        # skip the module docstring
    # `A or B` where B was a near-guarantee. On tokenised code -- so a comment mentioning the class
    # cannot satisfy it -- the candidate mask must simply not select on class 5 at all. Proven by
    # mutation: replacing the real mask (cls!=2)&(cls!=6)&... with cand=(cls==5) fails here. An earlier
    # note said this leg was unproven; that was my probe looking for a "cls != 5" spelling the module
    # does not use, not a weakness in the assertion.
    assert "cls==5" not in _code_only(body).replace(" ", ""), (
        "fetch_trees.py now selects candidates by classification 5. Ten of eleven courses have no "
        "class-5 points, so this empties the tree layer while the hole-map legend still promises "
        "trees. The filter must stay height-above-ground.")
    assert "hgt>2.5" in body.replace(" ", ""), "the 2.5 m height floor is gone"
    assert "hgt<35" in body.replace(" ", ""), "the 35 m ceiling is gone -- nothing that tall is a tree"
    for cl, why in ((6, "buildings: a roof is 2.5-35 m up and reads exactly like canopy"),
                    (7, "noise"), (9, "water"), (17, "bridge decks"), (18, "high noise")):
        assert f"cls!={cl}" in body.replace(" ", ""), (
            f"class {cl} is no longer excluded from tree candidates ({why})")

    # and the docstring must not go back to claiming a vegetation class it does not use
    doc = src.split('"""')[1]
    # This was `A or B` with B permanently true: fetch_trees' docstring already contains the word
    # "NOT". Require instead that any mention of class 5 in the docstring is a mention of NOT using
    # it -- checked in the same sentence, not anywhere in the file.
    _sent = [t for t in re.split(r"(?<=[.;])\s+", doc) if "class 5" in t or "class-5" in t]
    assert all(("not" in t.lower() or "no " in t.lower()) for t in _sent), (
        "fetch_trees.py's docstring claims a class-5 vegetation filter again; the code uses height "
        "above ground, and the two disagreeing is what sent this looking in the first place")


@needs_corpus
def test_the_geometry_counts_the_comments_quote_are_still_true():
    """Comments quote measured corpus counts, and those counts go stale silently.

    Two figures are cited repeatedly across the engine because so much behaviour turns on them: how
    many mapped centrelines STOP SHORT of the back tee (the from-tee gutter number, the elevation
    sampling point and the tick bound all branch on it) and how many OVERSHOOT it. They appear in
    fetch_hole_elev.py, render_hole.py and several docstrings here.

    They have gone stale twice. "22 of 198 holes, by up to 138 yd" survived in this file after
    valley-hi 17's 220 yd stub was replaced by its real 360 yd centreline, which made the truth 19 and
    103; and fetch_dem_hd.py quoted a worst uncovered share of 0.87% against an actual 0.71%. A stale
    count is not harmless here -- it is the evidence a reader uses to judge whether a branch is worth
    keeping, so an inflated one argues for defending a case that no longer exists.

    Pinned as exact values on purpose. If a course is added or a centreline re-traced these SHOULD
    fail, because that is the moment the comments need rewriting; the failure message says so.
    """
    SHORT, SHORT_YD, OVER, OVER_YD = 19, 103, 2, 36
    short, over, total = [], [], 0
    for slug in geometry_courses():
        os.environ["COURSE"] = slug
        os.environ["QUIET_TEE_CHECK"] = "1"
        for m in ("config", "geo"):
            sys.modules.pop(m, None)
        import config
        import geo
        gp = os.path.join(ROOT, "courses", slug, "osm_geom.json")
        if not os.path.exists(gp):
            continue
        with open(gp, encoding="utf-8") as f:
            d = json.load(f)
        loc = config.COURSE.get("location") or {}
        lines = geo.hole_lines(d["elements"] if isinstance(d, dict) else d,
                              loc.get("lat"), loc.get("lon"))
        for hn, el in lines.items():
            pts = [(p["lat"], p["lon"]) for p in el.get("geometry", [])]
            row = config.COURSE["holes"].get(str(hn))
            if not row or len(pts) < 2:
                continue
            card = row[config.BACK_I]
            if not isinstance(card, int):
                continue
            total += 1
            clat = sum(p[0] for p in pts)/len(pts)
            ml = 111320.0*math.cos(math.radians(clat))
            arc = sum(math.hypot((pts[i+1][1]-pts[i][1])*ml, (pts[i+1][0]-pts[i][0])*111320.0)
                      for i in range(len(pts)-1))/0.9144
            tol = max(15.0, 0.05*card)          # render_hole.py's own tee_ok tolerance
            if arc < card - tol:
                short.append((round(card-arc), slug, hn))
            elif arc > card + tol:
                over.append((round(arc-card), slug, hn))

    assert total >= expected_geometry_holes() - 18, f"only {total} holes measured"
    why = ("\n  These counts are quoted in fetch_hole_elev.py, render_hole.py and test docstrings. If "
           "the change\n  was intentional (a course added, a centreline re-traced), update those "
           "comments AND\n  these constants together -- do not just move the number here.")
    assert len(short) == SHORT, (
        f"{len(short)} holes stop short of the back tee, comments say {SHORT}: "
        f"{sorted(short, reverse=True)[:4]}{why}")
    assert max(short)[0] == SHORT_YD, (
        f"worst shortfall is {max(short)[0]} yd, comments say {SHORT_YD} "
        f"({max(short)[1]} h{max(short)[2]}){why}")
    assert len(over) == OVER, (
        f"{len(over)} holes overshoot the back tee, comments say {OVER}: {over}{why}")
    assert max(over)[0] == OVER_YD, (
        f"worst overshoot is {max(over)[0]} yd, comments say {OVER_YD}{why}")


@needs_corpus
def test_the_duplex_backs_are_actually_rotated_in_the_printed_pdf():
    """The 180-degree duplex rotation must survive into the PDF, not merely be asked for in HTML.

    test_duplex_imposition_puts_every_back_behind_its_own_front checks the HTML: correct mirrored slot,
    `flip` class present. Neither proves the transform RENDERS. `.card.flip { transform: rotate(180deg) }`
    is one stylesheet rule away from being overridden or dropped under print media, and if it went the
    slots would still be perfect while every back printed upside-down -- a book whose reverse side is
    unreadable, with nothing in the pipeline objecting.

    That is not hypothetical in this project. The Rule 4.3 scale cap was defeated exactly this way: the
    green size was emitted as an SVG presentation attribute, the stylesheet overrode it with zero
    specificity, and 15 of 198 greens printed over the legal limit while three documents said the cap
    held. The lesson recorded then was to measure the artifact, not the intent. This does that.

    Method: `.pageno` is positioned top-left of its card in CSS. Rotate the card 180 about its centre
    and that stamp must land bottom-right. So on every BACK sheet the stamps belong bottom-right --
    except exactly one, the dedication back cover, which is_upright_back() deliberately leaves upright.
    """
    fitz = pytest.importorskip("fitz", reason="PyMuPDF needed to read the printed PDF")
    GREY = {0xbbbbbb, 0xcccccc}          # .pageno colour in the pocket and enlarged stylesheets
    checked, problems, seen = 0, [], collections.Counter()
    for ref in BOOKS:
        pdf = os.path.join(ROOT, "courses", ref, "greenbook.pdf")
        if not os.path.exists(pdf):
            continue
        seen[ref] += 1
        os.environ["COURSE"] = ref
        sys.modules.pop("config", None)
        import config
        CW, CH, G = config.CARD_W_IN*72, config.CARD_H_IN*72, config.GUTTER_IN*72
        gx0 = (config.PAGE_W_IN*72 - (config.COLS*CW + (config.COLS-1)*G))/2
        gy0 = (config.PAGE_H_IN*72 - (config.ROWS*CH + (config.ROWS-1)*G))/2
        doc = fitz.open(pdf)
        try:
            tl = br = 0
            for pno in range(1, len(doc), 2):            # BACK sheets only
                for blk in doc[pno].get_text("dict")["blocks"]:
                    for ln in blk.get("lines", []):
                        for sp in ln.get("spans", []):
                            if (sp["color"] in GREY and 7.0 < sp["size"] < 9.5
                                    and sp["text"].strip().isdigit()):
                                x = (sp["bbox"][0]+sp["bbox"][2])/2
                                y = (sp["bbox"][1]+sp["bbox"][3])/2
                                c = 0 if x < gx0+CW+G/2 else 1
                                r = 0 if y < gy0+CH+G/2 else 1
                                cx, cy = gx0+c*(CW+G), gy0+r*(CH+G)
                                if (x-cx) < CW*0.35 and (y-cy) < CH*0.25:
                                    tl += 1
                                elif (x-cx) > CW*0.65 and (y-cy) > CH*0.75:
                                    br += 1
        finally:
            doc.close()
        if tl + br == 0:
            problems.append(f"{ref}: no page-number stamp found on any back sheet, so nothing was "
                            f"verified -- has .pageno's colour or size changed?")
            continue
        checked += 1
        # exactly one upright back is expected: the dedication / back cover
        if tl != 1:
            problems.append(
                f"{ref}: {tl} of {tl+br} back-sheet stamps sit TOP-LEFT, i.e. those cards were not "
                f"rotated. Expected exactly 1 (the dedication back cover, which is_upright_back() "
                f"exempts). If the rest lost their rotation the whole reverse of the book prints "
                f"upside-down while the imposition still looks correct in HTML.")
        if br < 1:
            problems.append(f"{ref}: no rotated back stamp at all -- the duplex transform is not "
                            f"reaching the PDF")
    assert checked, "no book PDF was inspected, so this test verified nothing"
    assert_no_course_skipped(seen, "test_the_duplex_backs_are_actually_rotated_in_the_printed_pdf")
    assert not problems, "duplex rotation is wrong in the printed PDF:\n  " + "\n  ".join(problems)


@needs_corpus
def test_no_card_silently_clips_its_own_text():
    """`.card` is a fixed 3.5x5in box with overflow:hidden, so text that does not fit VANISHES.

    No warning, no reflow, no scrollbar -- the sentence simply ends. On a card that carries the legal
    notice, an insufficient-green explanation or the guide-card legend, the tail is exactly the part
    that qualifies the claim, so silent truncation turns a hedged statement into a bare one.

    Nothing in this suite could see it. The obvious probe, scrollHeight > clientHeight, is BLIND here:
    with overflow:hidden Chrome clamps scrollHeight to clientHeight, and an injected 400px div moved
    neither number. The card's children are absolutely positioned too. So this walks the elements that
    directly hold visible text -- skipping SVG internals, whose rects legitimately exceed the card
    because the hole map's background fills are clipped by the map's own viewBox on purpose -- and
    compares each rect against the card box.

    The metric is self-validating: it appends a deliberately overflowing element first and asserts it
    is detected, so a future change that makes the check blind fails here rather than passing quietly.

    Slack is real and THIN, measured: the About/guide card has **under one legend row of headroom**. Its
    ink comes within 1.2 mm of the trim on three pocket books, and injecting one more conditional legend
    row overflows 7 of the 15 books -- worst 22.8 px on the pocket edition, 38.9 px on the enlarged one,
    clipping the licence line and the contact address.

    That is not a defect in what ships: no course emits every conditional row at once, and this test
    verifies the real builds. It is a warning to whoever adds the next caveat. The rows that fire
    conditionally are _no_fall_note() and _flown_line()'s rebuild / 1-m-data lists, so a future course
    with a no-clear-fall green AND pre-rebuild greens AND seamless-fallback greens is the case that will
    break it -- and it will break it here, loudly, rather than silently on paper. Make room first.
    """
    # BOTH editions. Globbing only greenbook.html is how this guard missed a live defect: the enlarged
    # edition's About & legal card was overflowing by 27 px on two courses, clipping the licence line,
    # the warranty disclaimer and the contact address off the printed page, and the test that exists to
    # catch exactly that never opened the file. The coach book is the MORE likely one to overflow -- same
    # 3.5x5in card, larger type -- so checking only the pocket edition inverts the risk.
    books = [f for f in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html")))
             if not os.path.basename(os.path.dirname(f)).startswith("_")]
    if not books:
        pytest.skip("no book built")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import export_pdf
    exe = export_pdf._headless_shell()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    JS = """() => {
      const out=[];
      document.querySelectorAll('.card').forEach((c,ci)=>{
        const cb=c.getBoundingClientRect();
        c.querySelectorAll('*').forEach(e=>{
          if(e.closest('svg')) return;                 // clipped by the map's viewBox by design
          if(![...e.childNodes].some(n=>n.nodeType===3 && n.textContent.trim().length)) return;
          const s=getComputedStyle(e);
          if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)===0) return;
          const r=e.getBoundingClientRect();
          if(r.width===0||r.height===0) return;
          const over=Math.max(cb.top-r.top, r.bottom-cb.bottom, cb.left-r.left, r.right-cb.right);
          if(over>0.5) out.push({ci, cls:(e.getAttribute('class')||''), over:+over.toFixed(1),
                                 txt:e.textContent.trim().slice(0,60)});
        });
      });
      return out;
    }"""
    PROBE = """() => {
      const c=document.querySelectorAll('.card')[0];
      const d=document.createElement('div');
      d.style.cssText='position:absolute;top:900px;left:4px';
      d.textContent='OVERFLOW PROBE';
      d.setAttribute('class','overflow-probe');
      c.appendChild(d);
    }"""
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception:
            pytest.skip("no browser available")
        pg = b.new_page()
        problems, checked, seen = [], 0, collections.Counter()
        try:
            for bf in books:
                ref = os.path.basename(os.path.dirname(bf))
                seen[ref] += 1
                pg.goto("file://" + os.path.abspath(bf))
                pg.emulate_media(media="print")
                clipped = pg.evaluate(JS)
                # the check must be able to SEE overflow on this very page
                pg.evaluate(PROBE)
                if not any(x["cls"] == "overflow-probe" for x in pg.evaluate(JS)):
                    problems.append(f"{ref}: the overflow probe was NOT detected, so this test cannot "
                                    f"see clipped text and its silence means nothing")
                    continue
                checked += 1
                for x in clipped:
                    problems.append(
                        f"{ref} card {x['ci']}: text overruns the card by {x['over']}px and is cut off "
                        f"by overflow:hidden -- {x['txt']!r}")
        finally:
            b.close()
    assert checked, "no book was measured in a browser, so nothing was verified"
    assert_no_course_skipped(seen, "test_no_card_silently_clips_its_own_text")
    assert not problems, "text is being silently clipped:\n  " + "\n  ".join(problems[:10])


@needs_corpus
def test_the_scorecard_facts_obey_their_own_arithmetic():
    """Rating, slope and stroke index are HAND-TRANSCRIBED, and each has a hard constraint.

    Everything else in a card is computed from data, so a mistake in it is a bug with a cause. These
    three are read off a published scorecard by a person, which makes a typo the realistic failure --
    and the card prints them as fact, beside a note saying the yardages come from the official
    scorecard. A reader takes that as covering the columns next to them.

    Five constraints, chosen because each catches a different slip:

    * The men's stroke index must be a PERMUTATION of 1..N -- every index used exactly once. A
      duplicated or missing index is arithmetically impossible on a real card, and it is what a
      mis-keyed digit produces.
    * Slope must lie in 55..155. That is the USGA's own range, not a heuristic, so a 445 or a 45
      cannot hide.
    * The per-hole yardages must SUM to the total the tees block states. These are transcribed from
      different lines of the scorecard -- the hole row and the summary -- so agreement is evidence and
      disagreement pins the fault to one of them. It is the strongest check here: a single mis-keyed
      hole yardage is invisible to everything else and shows up in this sum at once. All 51 backed tees
      agree to the yard.
    * A LONGER tee must not rate EASIER than a shorter one on the same course. Rating is dominated by
      length, so this catches the likeliest paste error: one tee's figures landing on another's row.
    * A rating must sit near what the corpus itself says a course of that length rates. Fitted over 53
      tee sets the relationship is rating = 0.00465 x yards + 41.71, i.e. one stroke per 215 yards --
      which independently matches the USGA's own rule of thumb of about a stroke per 220, and is
      therefore evidence the transcriptions are sound rather than an assumption imposed on them.

    The residual bound is deliberately loose at 4 strokes against a measured worst of 1.59. It is here
    to catch a rating belonging to a different course, not to grade course difficulty: the two extremes
    are Merion rating 1.3 strokes HARDER than trend and Poppy Ridge 1.6 EASIER, which is exactly the
    real difficulty variation this must not flag.
    """
    import numpy as np
    tees, problems, seen = [], [], collections.Counter()
    summed = unbacked = 0
    for slug in CORPUS:
        cp = os.path.join(ROOT, "courses", slug, "course.json")
        if not os.path.exists(cp):
            continue
        seen[slug] += 1
        with open(cp, encoding="utf-8") as f:
            j = json.load(f)

        # 1. stroke index is a permutation
        cols = j.get("hole_cols") or []
        if "mens_hcp" in cols:
            i = cols.index("mens_hcp")
            vals = [row[i] for _h, row in sorted(j["holes"].items(), key=lambda kv: int(kv[0]))]
            n = len(vals)
            nums = [v for v in vals if isinstance(v, int)]
            missing = sorted(set(range(1, n+1)) - set(nums))
            dup = sorted({v for v in nums if nums.count(v) > 1})
            if missing or dup or len(nums) != n:
                problems.append(
                    f"{slug}: the men's stroke index is not a permutation of 1..{n} -- "
                    f"missing {missing}, duplicated {dup}. A real card uses each index once, so this "
                    f"is a transcription error and the HCP printed on some hole is wrong.")

        rows = [(t.get("yards"), t.get("rating"), t.get("slope"), t.get("name"))
                for t in (j.get("tees") or [])]
        for y, r, s, nm in rows:
            # 2. USGA hard bounds
            if s is not None and not (55 <= s <= 155):
                problems.append(f"{slug} {nm}: slope {s} is outside the USGA's 55-155 range")
            if r is not None and not (55.0 <= r <= 80.0):
                problems.append(f"{slug} {nm}: course rating {r} is impossible for {y} yards")
            if y and r:
                tees.append((y, r, slug, nm))
        # 3. the per-hole yardages must SUM to the total the tees block states.
        # The two are transcribed from different parts of the scorecard -- the hole row and the
        # summary line -- so agreement is real evidence and disagreement pins the error to one of
        # them. It is the strongest check available on this data: a single mis-keyed hole yardage
        # is invisible to every other constraint here, and shows up in this sum immediately.
        # Measured across the corpus: all 51 backed tees agree EXACTLY, to the yard.
        # A tee named in the ratings table with no hole column is not an error -- the-reserve's
        # Blu/Wht and Wht/Grn are combination tees, philadelphia's Green is published but not
        # transcribed per hole -- and those rows are daggered and footnoted on the card
        # (test_the_rating_table_marks_tees_it_cannot_break_down covers that). Skipped here, not
        # silently: counted, and required to stay a small minority.
        for y, r, s, nm in rows:
            if nm in cols and y:
                per = [row[cols.index(nm)] for row in j["holes"].values()
                       if isinstance(row[cols.index(nm)], int)]
                if len(per) == len(j["holes"]):
                    summed += 1
                    if sum(per) != y:
                        problems.append(
                            f"{slug} {nm}: the {len(per)} hole yardages sum to {sum(per)} but the "
                            f"tees block says {y} ({sum(per)-y:+d}). These come from different lines "
                            f"of the same scorecard, so one of them is mis-transcribed -- and if it "
                            f"is a hole row, that hole's card prints the wrong number.")
            elif y:
                unbacked += 1
        # 4. longer must not rate easier
        srt = sorted([x for x in rows if x[0] and x[1]])
        for a, b in zip(srt, srt[1:]):
            if b[1] < a[1] - 0.05:
                problems.append(
                    f"{slug}: the {b[3]} tee is LONGER ({b[0]} yd) than {a[3]} ({a[0]} yd) but rates "
                    f"EASIER ({b[1]} vs {a[1]}) -- two tees' figures are probably swapped")

    assert_no_course_skipped(seen, "test_the_scorecard_facts_obey_their_own_arithmetic")
    assert len(tees) >= 30, f"only {len(tees)} rated tee sets found; nothing much was checked"

    assert summed >= 25, (
        f"only {summed} tees had a full set of per-hole yardages to cross-check against their "
        f"stated total; the corpus has 27, so this check has lost its reach")
    assert unbacked <= summed // 3, (
        f"{unbacked} rated tees have no per-hole yardages against {summed} that do. Those rows "
        f"print a rating the book cannot break down, and while they are daggered and footnoted, "
        f"a book that is mostly unbacked tees is not covering the course it claims to.")

    # 5. distance from the corpus's own rating/length relationship
    Y = np.array([t[0] for t in tees], float)
    R = np.array([t[1] for t in tees], float)
    a, b = np.polyfit(Y, R, 1)
    assert 150 <= 1/a <= 300, (
        f"the corpus now implies one stroke of course rating per {1/a:.0f} yards. The USGA's own rule "
        f"of thumb is about 220, and this file's reasoning depends on the two agreeing -- if the fit "
        f"has moved this far, a rating or a yardage is wrong somewhere.")
    for (y, r, slug, nm), pred in zip(tees, a*Y+b):
        if abs(r-pred) > 4.0:
            problems.append(
                f"{slug} {nm}: {y} yd rated {r}, where every other tee in the corpus implies about "
                f"{pred:.1f}. That is too far to be course difficulty; check the transcription.")
    assert not problems, ("hand-transcribed scorecard facts break their own arithmetic:\n  "
                          + "\n  ".join(problems[:10]))


def test_a_confirmed_rebuild_says_so_rather_than_no_coverage(gate_course):
    """_blank_green's rebuilt=True path is unreachable today. Pin it anyway, so it works when wired.

    render_green has two reasons to refuse a green, and they must not print the same words. "no LiDAR
    coverage" means nobody measured this surface; "rebuilt after survey" means it WAS measured and the
    green has since been reshaped. A reader who sees the wrong one draws the wrong conclusion about
    whether better data could exist.

    Only the first is reachable from render(). That is deliberate: a green whose rebuild is merely
    SUSPECTED keeps its map with a "pre-rebuild data" label -- printing a hedged read beats withholding
    a measured one -- so `greens_possibly_outdated` never routes here. Which leaves the rebuilt branch
    dark, and dark branches rot: this one carries two distinct strings and a distinct `feeds` value, all
    currently produced by nothing and asserted by nothing.

    So exercise it directly. The alternative is deleting it, but the capability is real -- a course with
    some confirmed-rebuilt greens and some current ones cannot use yardage mode, which is
    all-or-nothing -- and a rotted branch discovered on the day it is needed is worse than a tested one
    that waits.

    Also asserts the two reasons stay DISTINCT, which is the property that actually matters: they are
    the card's explanation of why it has no arrows.
    """
    import render_green
    tilt = lambda r, c: 100.0 + 0.03 * r
    _synth_green(gate_course, 3, tilt, insufficient=True)
    mp = os.path.join(ROOT, "courses", gate_course, "dem_hd", "hole03.json")
    with open(mp, encoding="utf-8") as f:
        meta = json.load(f)

    svg_nc, s_nc = render_green._blank_green(meta, True, rebuilt=False)
    svg_rb, s_rb = render_green._blank_green(meta, True, rebuilt=True)

    assert "no LiDAR coverage" in svg_nc, "the never-measured card must say so"
    assert "rebuilt after survey" in svg_rb, "the confirmed-rebuild card must say so"
    assert "no LiDAR coverage" not in svg_rb, (
        "a green that WAS measured and then rebuilt must not tell the reader there is no coverage -- "
        "that says better data cannot exist, when in fact it merely does not exist yet")
    assert s_nc["feeds"] == "not surveyed" and s_rb["feeds"] == "rebuilt since survey", (
        f"the two refusals must carry different feeds labels, got {s_nc['feeds']!r} and "
        f"{s_rb['feeds']!r}")
    for s in (s_nc, s_rb):
        assert s["insufficient"] is True and s["conf"] == "no data" and s["tilt_pct"] == 0.0, (
            "a refused green must report no slope, not 0.0% dressed as a reading")
    assert "mark your own read" in svg_rb, "a refused green must still invite the player's own read"
    # both must draw the real OSM outline: that geometry is measured even when the surface is not
    assert svg_rb.count("<path") >= 1 and "&#9650; approach" in svg_rb

    # and record the fact that nothing routes here, so this test's subject is understood
    with open(os.path.join(ROOT, "render_green.py"), encoding="utf-8") as f:
        src = f.read()
    live = [l for l in src.splitlines() if "_blank_green(" in l and "def " not in l]
    assert live, "no call sites found; _blank_green may have been renamed"
    assert not any("rebuilt=True" in l for l in live), (
        "something now reaches _blank_green(rebuilt=True). That is a real policy change -- a green is "
        "being withheld rather than printed with a pre-rebuild label -- so update this test and the "
        "docstring at _blank_green, which both record that the branch is deliberately dark.")


@needs_corpus
def test_a_hole_the_survey_missed_does_not_print_as_open_ground():
    """A hole with no tree markers must say so ON ITS OWN CARD, because blank does not mean clear.

    Trees are found by height above ground in the point cloud, so a hole the survey does not reach
    draws none -- and on the map that is indistinguishable from a links hole that genuinely has none,
    while the guide card's legend promises "trees". A junior planning a line off the tee reads open
    ground.

    Monarch Bay 1, 17 and 18 are the case: zero markers each, and exactly the three holes
    lidar_coverage.py reports as having centreline outside the point data ("Trees along those stretches
    ... will be missing"). They are the ONLY zero-tree holes anywhere in the corpus, which is what makes
    the blank the survey's edge rather than open ground. The card already named those holes for a
    different reason -- their greens fall back to the 1 m DEM -- so a reader was told the green was
    coarser and not that the corridor was unmapped.

    On the hole card, not the guide card, and that placement is load-bearing rather than cosmetic. The
    guide panel holds the other per-hole data caveats and is FULL: one extra row there overflowed
    monarch-bay's card by 20 px and clipped the legal notice and the contact line, and trimming 33
    characters of existing wording did not buy the line back. It is also the better place -- the caveat
    sits beside the bunker and water counts, on the card whose map shows the blank corridor.

    The wording claims only what is known. Derived from the shipped tree data, the book cannot prove WHY
    a hole is empty, so it says "no tree data" rather than asserting missing coverage. The provenance
    record carries the fuller statement, and this checks that too: legal/03 documents every other
    per-hole limitation, so omitting this one would make it read complete when it is not.
    """
    checked, problems, seen, bare_total = 0, [], collections.Counter(), 0
    with open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md"), encoding="utf-8") as f:
        prov = f.read()
    for ref in BOOKS:
        tp = os.path.join(ROOT, "courses", ref, "trees_lidar.json")
        book = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not (os.path.exists(tp) and os.path.exists(book)):
            continue
        seen[ref] += 1
        with open(tp, encoding="utf-8") as f:
            tl = json.load(f)
        if not (tl and any(tl.values())):
            continue                     # no tree layer at all: nothing to distinguish, no caveat owed
        checked += 1
        bare = sorted(int(h) for h, v in tl.items() if not v)
        bare_total += len(bare)
        # BOTH editions. Checking only the pocket book is how this caveat reached one edition and not the
        # other: the enlarged edition drew monarch-bay 1, 17 and 18 as open ground with nothing to say the
        # survey does not reach them, and this test passed the whole time.
        editions = [("pocket edition", book)]
        _coach = os.path.join(ROOT, "courses", ref, "greenbook_coach.html")
        if os.path.exists(_coach):
            editions.append(("enlarged edition", _coach))
        for ed, bpath in editions:
            with open(bpath, encoding="utf-8") as f:
                html = f.read()
            marked = set()
            for blk in re.split(r'<div class="panel hole">', html)[1:]:
                # Cut the block at the NEXT panel. Splitting on the hole-panel opener alone leaves every
                # following panel's markup inside the block, so once the guide card started defining
                # "no tree data" -- as it must, the mark was printed and explained nowhere -- that phrase
                # was attributed to whichever hole happened to precede the guide card in the imposed
                # deck. It reported hole 5 as marked on all 11 courses.
                blk = re.split(r'<div class="panel ', blk)[0]
                hn = re.search(r'class="hnum">(\d+)</div>', blk)
                if hn and "no tree data" in blk:
                    marked.add(int(hn.group(1)))
            if marked == set(bare):
                continue
            problems.append(
                f"{ref} ({ed}): holes {sorted(set(bare)-marked)} draw NO trees and their cards do not "
                f"say so"
                f"{'; holes ' + str(sorted(marked-set(bare))) + ' are marked but do have trees' if marked-set(bare) else ''}"
                f". The map shows an unmeasured corridor as open ground while the legend promises trees.")
        if bare and not re.search(r"no tree markers on holes? "
                                  + re.escape(", ".join(str(h) for h in bare)), prov):
            problems.append(
                f"{ref}: the book marks treeless holes {bare} but legal/03 does not record it. That "
                f"table documents every other per-hole data limitation -- 1 m green fallbacks, how many "
                f"holes carry a measured height -- so omitting this makes it read complete when it is "
                f"not. Re-run tools/gen_provenance.py.")
    assert checked >= 10, f"only {checked} books with a tree layer were checked"
    assert_no_course_skipped(seen, "test_a_hole_the_survey_missed_does_not_print_as_open_ground")
    assert bare_total >= 3, (
        f"only {bare_total} treeless holes across the corpus; monarch-bay 1, 17 and 18 are the known "
        f"case, so if that is gone the tree fetch changed and this test now proves nothing")
    assert not problems, "a hole the survey missed prints as open ground:\n  " + "\n  ".join(problems)


@needs_corpus
def test_every_enlarged_green_is_on_the_back_of_its_own_hole():
    """The enlarged edition's whole promise is "the course map, then the green on its REVERSE".

    Nothing checked the pairing. test_every_duplex_back_lands_behind_its_own_front verifies that leaf
    L's back card sits geometrically behind its front, to 0.000 pt -- but geometry cannot say whether
    the green on that back is the SAME HOLE's green. A deck that emitted hole 7's map and hole 8's
    green on one leaf would pass every existing test: the imposition is right, the trim is right, the
    mirror is right, and both cards individually carry correct numbers.

    That failure mode is not hypothetical for this edition. It is built by a second code path from the
    pocket book's (build_coach, not build_deck), one hole is TWO cards rather than one, and the two
    editions have already drifted on the green honesty labels, the footer, the playline, the ODbL URL
    and the upright-back rule. A junior reading a coach's book would be putting to the wrong green with
    nothing on the page to say so -- the most serious thing this project could print, and the one thing
    a per-card number check cannot see.

    Measured on the deck rather than the imposed HTML: the deck IS the contract, and the imposition is
    separately verified. All three enlarged books, 18 leaves each, correct today.
    """
    checked = collections.Counter()
    for slug in CORPUS:
        if not os.path.isfile(os.path.join(ROOT, "courses", slug, "greenbook_coach.html")):
            continue
        os.environ["COURSE"] = slug
        for m in ("config", "geo", "render_green", "render_hole", "generate"):
            sys.modules.pop(m, None)
        import config
        import generate

        for h in config.HOLE_NUMS:
            generate.GREENS[h] = generate.render_green.render(h, tournament=False)
            generate.LAYOUTS[h] = generate.render_hole.render_hole(h, generate.HOLES, font_scale=2.0)
        for h in config.HOLE_NUMS:
            mp, gp = generate.coach_map_card(h), generate.coach_green_card(h)
            m_hole = re.search(r'class="hnum">(\d+)</div>', mp)
            g_hole = re.search(r'class="hnum">(\d+)</div>', gp)
            assert m_hole and g_hole, f"{slug} hole {h}: a coach card carries no hole number"
            assert int(m_hole.group(1)) == h, (
                f"{slug}: the map card built for hole {h} prints hole {m_hole.group(1)}")
            assert int(g_hole.group(1)) == h, (
                f"{slug}: the GREEN card built for hole {h} prints hole {g_hole.group(1)} -- a coach "
                f"would hand a junior the wrong green, and every geometric duplex check would still "
                f"pass because the imposition is correct")
            # and they must be the two SIDES of one leaf: map first, green second, nothing between
            assert "HOLE" in mp and "GREEN" in gp, (
                f"{slug} hole {h}: the map/green captions are swapped or missing, so the reader is told "
                f"to flip for a green that is on the front")
            # THE DRAWING, not just the label. Checking the printed hole number alone is not enough and
            # I proved it: swapping coach_green_card to embed GREENS[hole+1] left the earlier version of
            # this test green, because the number comes from `hole` while the surface comes from the
            # dict -- so the card would have said "13" over hole 14's green. That is the exact failure
            # this test exists for, so it has to compare the SURFACE.
            assert generate.GREENS[h][0] in gp, (
                f"{slug} hole {h}: the green card does not contain the surface rendered for hole {h}. "
                f"It is drawing another hole's green under this hole's number -- a junior would putt to "
                f"the wrong map, and the number on the card would not give it away.")
            assert generate.LAYOUTS[h][0] in mp, (
                f"{slug} hole {h}: the map card does not contain the layout rendered for hole {h}")
            checked[slug] += 1
    if not checked:
        pytest.skip("no enlarged edition built (COURSE=<slug> COACH=1 python3 generate.py)")
    assert sum(checked.values()) >= 36, (
        f"only {sum(checked.values())} enlarged leaves checked across {len(checked)} book(s); the corpus "
        f"ships three enlarged editions of 18 holes each")


@needs_corpus
def test_the_card_deck_has_exactly_one_implementation():
    """main() and the iOS reader must lay the deck out the same way, or the app shows the wrong hole.

    The companion app repo needs this deck to map a hole to a PDF page, and its exporter
    (app/tools/course_worker.py) hand-rewrote the loop rather than calling the engine. The copy then
    drifted, and shipped exactly the things this engine had deliberately fixed:

      * `grp = "Front" if h <= 6 else ("Mid" if h <= 14 else "Finish")` -- the tab wording removed
        because "Front" means holes 1-9 in golf while it was being used for 1-6, so a junior looking
        under "Front" for hole 8 found it tabbed "Mid" in a book whose own scorecard says Out 1-9.
      * `notes_panel("Notes 1-9", range(1, 10))` -- a heading describing half the book.
      * `range(1, 19)` -- a hard-coded 18, after the engine moved to config.HOLE_NUMS for nine-hole
        courses.

    The dangerous one is neither: the app derives firstHolePage from ITS OWN leading list, so any panel
    added here shifts the app's hole-to-page map silently and the reader shows a green beside the wrong
    hole. build_deck() exists so there is one list. This test pins the contract the app depends on --
    the return shape, and that the labels are the corrected ones.
    """
    os.environ["COURSE"] = CORPUS[0]
    for m in ("config", "geo", "render_green", "render_hole", "generate"):
        sys.modules.pop(m, None)
    import config
    import generate

    assert hasattr(generate, "build_deck"), (
        "generate.build_deck is gone. The app's exporter calls it; without it the app must hand-copy "
        "main()'s deck again, which is how it came to ship 'Front'/'Mid'/'Finish' tabs and a "
        "'Notes 1-9' heading over eighteen holes.")
    panels, n_leading, n_holes = generate.build_deck()
    assert n_holes == config.NHOLES, f"deck has {n_holes} hole cards for {config.NHOLES} holes"
    assert n_leading >= 2, "the deck must lead with at least a cover and a guide card"
    assert len(panels) == n_leading + n_holes + 4, (
        f"deck is {len(panels)} panels for {n_leading} leading + {n_holes} holes; the app computes its "
        f"hole-to-page map from these counts, so the shape is part of the contract")

    # main() must USE it, not carry a second copy
    with open(os.path.join(ROOT, "generate.py"), encoding="utf-8") as f:
        src = f.read()
    body = src.split("def main(", 1)[1].split("\ndef ", 1)[0]
    assert "build_deck()" in body, "main() no longer calls build_deck -- there are two decks again"
    # No grep for the removed words "Front"/"Mid"/"Finish". They appear in the comments that explain why
    # they were removed, so the grep failed on prose -- the same trap that made the fetch_dem_hd guard
    # test pass on a comment, inverted. The tab check below is strictly stronger anyway: it requires a
    # LITERAL RANGE that contains the hole, which no golf term can satisfy.

    # the hole cards must carry literal-range tabs covering every hole exactly once
    tabs = {}
    for h, panel in zip(config.HOLE_NUMS, panels[n_leading:n_leading + n_holes]):
        m = re.search(r'class="sheettab"[^>]*>(\d+)\u2013(\d+)<', panel)
        assert m, f"hole {h}'s card has no literal-range thumb tab"
        lo, hi = int(m.group(1)), int(m.group(2))
        assert lo <= h <= hi, f"hole {h} is tabbed {lo}-{hi}"
        tabs.setdefault((lo, hi), []).append(h)
    covered = sorted(x for v in tabs.values() for x in v)
    assert covered == list(config.HOLE_NUMS), f"tabs cover {covered}, not {list(config.HOLE_NUMS)}"

    # and the notes heading must describe the whole book
    notes = [p for p in panels[n_leading + n_holes:] if "Notes" in p]
    assert notes, "no notes panel in the deck"
    assert f"Notes {config.HOLE_NUMS[0]}-{config.HOLE_NUMS[-1]}" in notes[0], (
        f"the notes heading does not name every hole in the book -- the app shipped 'Notes 1-9' over "
        f"eighteen holes for exactly this reason. Got: {re.findall(r'Notes[^<]*', notes[0])[:2]}")


@needs_corpus                    # render_hole imports config, which needs a bound course to import
def test_a_card_counts_water_the_golfer_can_actually_see():
    """"1W" must mean one watercourse a player standing on the hole can see.

    The selection took any feature with a `waterway` tag whose CENTROID was within 45 m of the
    centreline. Two independent faults, pulling opposite ways:

      * PIPED water counted. A waterway tagged tunnel=culvert, covered=yes or location=underground runs
        under the ground: not visible, not a hazard, not playable. merion 13 printed "1W" whose only blue
        mark on the page was a 14.7 m culverted section, and nine holes counted one. 27 such features
        exist across 7 of the 12 courses.
      * OPEN water missed. A creek is long and mostly somewhere else, so a stream that crosses THIS
        fairway usually has its centroid two holes away. The centroid test hid 48 open watercourses on 31
        holes, one of them passing 0.7 m from the centreline. For a LINE the right question is whether any
        part of it comes near, which is what any_within asks.

    Together those made the card show the wrong water: a hole with none printed 1, and holes with a
    stream across them printed 0. Corpus water count went 134 -> 169 when both were fixed.

    Truth table on the predicate, plus the corpus fact that makes it matter.
    """
    os.environ["COURSE"] = CORPUS[0] if CORPUS else "merion-golf-club"
    for m in ("config", "geo", "render_hole"):
        sys.modules.pop(m, None)
    import render_hole as rh
    cases = [
        ({"waterway": "stream"}, True, "an open stream is visible water"),
        ({"waterway": "ditch"}, True, "an open ditch is visible"),
        ({"waterway": "river", "tunnel": "no"}, True, "explicitly not tunnelled"),
        ({"waterway": "stream", "tunnel": "culvert"}, False, "piped under the ground"),
        ({"waterway": "stream", "tunnel": "yes"}, False, "tunnelled"),
        ({"waterway": "drain", "covered": "yes"}, False, "covered"),
        ({"waterway": "stream", "location": "underground"}, False, "underground"),
        ({"waterway": "dam"}, False, "a dam is a structure beside water, not water"),
        ({"waterway": "weir"}, False, "a weir is a structure"),
        ({"natural": "water"}, False, "not a waterway -- counted on the other list"),
        ({}, False, "no tags at all"),
    ]
    for tags, want, why in cases:
        got = rh.is_visible_watercourse({"tags": tags})
        assert got is want, (f"is_visible_watercourse({tags}) returned {got}, expected {want}: {why}")

    # The corpus fact. Without this the truth table above would pass on a corpus where no piped feature
    # exists, and the test would be describing a risk rather than covering one.
    piped = 0
    for slug in CORPUS:
        p = os.path.join(ROOT, "courses", slug, "osm_course.json")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as fh:
            els = json.load(fh).get("elements") or []
        piped += sum(1 for e in els
                     if (e.get("tags") or {}).get("waterway") and not rh.is_visible_watercourse(e))
    assert piped >= 10, (
            f"only {piped} piped or structural waterway(s) found in the corpus. This test exists because "
        f"27 of them were being drawn and counted as visible water; if the number has collapsed, "
        f"either the data was re-fetched differently or the predicate stopped excluding anything.")


@needs_corpus
def test_the_carry_legend_says_sand_because_water_is_not_quantified():
    """"carry N" covers SAND only, and the card has to keep saying so.

    render_hole computes carries from bunkers alone. That is deliberate -- applying the same test to
    water finds 62 features in the tee-shot corridor, but 41 span 300-1300 yd ALONG the line, which is a
    stream running WITH the hole where one number means nothing. Of the 21 that genuinely cross, 10
    straddle the chord and only 4 carry a golf water tag; the rest are `waterway=drain` or `stream`,
    covering culverted and seasonally dry channels nobody carries. Quantifying those would mean printing
    "carry 86" for a storm drain, which is the confident-but-unsupported number this book exists not to
    print.

    The omission is honest only while the card SAYS "sand". A reader who sees "carry 220 / 246" under a
    legend reading "hazard" or "carry" would take it as covering the water they can see drawn in blue,
    and four holes in this corpus have water crossing the tee-shot line with no distance printed. So the
    wording is the load-bearing part, not the computation: it is the difference between an omission and
    an over-claim.

    Also requires the extent hedge. Sand can run far past N -- the worst case in the corpus is 126 yards
    of it -- so a bare "carry N" would read as the whole obstacle rather than its near edge.
    """
    checked, problems, seen = 0, [], collections.Counter()
    for ref in BOOKS:
        p = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not os.path.exists(p):
            continue
        seen[ref] += 1
        with open(p, encoding="utf-8") as f:
            html = f.read()
        if "carry" not in html:
            continue
        legend = [m for m in re.findall(r"<span>(?:(?!</span>).)*carry(?:(?!</span>).)*</span>",
                                        html, re.S)
                  if "carry <b>N</b>" in m or "<b>carry N</b>" in m]
        if not legend:
            problems.append(f"{ref}: prints carry numbers but no legend row explains what one is")
            continue
        checked += 1
        flat = re.sub(r"<[^>]+>", " ", " ".join(legend)).lower()
        if "sand" not in flat:
            problems.append(
                f"{ref}: the carry legend no longer says SAND. Carries are computed from bunkers only, "
                f"so a legend that says 'hazard' or just 'carry' claims to cover the water this corpus "
                f"draws crossing the tee-shot line on four holes without a distance. Either say sand or "
                f"quantify water -- see the note at CARRY_OFF_M in render_hole.py for why the second is "
                f"not free.")
        if not re.search(r"past|beyond|run", flat):
            problems.append(
                f"{ref}: the carry legend dropped the hedge that sand can run past N. N is the NEAR "
                f"edge; the worst window in this corpus runs 40+ yd further, so a bare number reads as "
                f"the whole obstacle.")
    assert checked >= 10, f"only {checked} books' carry legends were checked"
    assert_no_course_skipped(seen, "test_the_carry_legend_says_sand_because_water_is_not_quantified")
    assert not problems, "the carry legend over-claims what it covers:\n  " + "\n  ".join(problems)


@needs_corpus
def test_the_provenance_record_dates_the_geometry_not_just_the_lidar():
    """The OSM extract date must be reported, for the same reason the flight date is.

    Overpass stamps every response with osm3s.timestamp_osm_base -- the instant of the planet data the
    answer was computed from. It sat unread in every extract on disk while this project went to real
    trouble over the other side of the provenance: flight dates are decoded out of the LiDAR point
    records because four courses had been mislabelled by 2-12 years by their project names.

    The card tells a reader the hole and green SHAPES come from OpenStreetMap, and prints the flight date
    so they can judge whether the green SLOPE is current. Without the extract date they cannot judge the
    same thing about the shapes -- a re-bunkered hole or a re-routed green reads exactly as authoritative
    as a current one. Every extract in this corpus is a day or two old, so this pins a fact rather than
    fixing a live problem, which is the point: it is recorded now, before a course goes two years without
    a refetch and nothing says so.

    Asserted against the FILES, not against the document's own prose, so the record cannot drift from the
    artifacts it claims to describe. Earliest of the three extracts per course, because the honest claim
    about a book is the age of its oldest ingredient.
    """
    with open(os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md"), encoding="utf-8") as f:
        prov = f.read()
    checked, problems, seen = 0, [], collections.Counter()
    for slug in CORPUS:
        stamps = []
        for fn in ("osm_geom.json", "osm_course.json", "osm_relations.json"):
            p = os.path.join(ROOT, "courses", slug, fn)
            if not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8") as f:
                t = (json.load(f).get("osm3s") or {}).get("timestamp_osm_base")
            if t:
                stamps.append(str(t))
        seen[slug] += 1
        if not stamps:
            continue                      # no OSM extract at all (a yardage-mode course may have none)
        checked += 1
        want = min(stamps)[:10]
        if f"extract **{want}**" not in prov:
            problems.append(
                f"{slug}: its oldest OSM extract is {want} and legal/03 does not say so. That table "
                f"dates the LiDAR to the day; leaving the geometry undated means a reader cannot tell a "
                f"current hole shape from one traced before the course was re-bunkered. Re-run "
                f"tools/gen_provenance.py.")
        if "not recorded" in prov and want:
            # a row claiming no date while the file has one is worse than either alone
            pass
    assert checked >= 10, f"only {checked} courses had an OSM extract to date"
    assert_no_course_skipped(seen, "test_the_provenance_record_dates_the_geometry_not_just_the_lidar")
    assert "Geometry carries a date for the same reason" in prov, (
        "the table no longer explains what the extract date is or why it is there; a bare date in a "
        "column is not provenance")
    assert not problems, "the provenance record leaves the geometry undated:\n  " + "\n  ".join(problems)

    # And exercise the EARLIEST choice directly, because the corpus cannot. Every course's three
    # extracts land on the same calendar day -- they are Overpass calls a minute apart -- so min and max
    # agree to the day and swapping them is undetectable from the real data. It stops being undetectable
    # the first time a fetch straddles midnight, which is exactly when reporting the newer date would
    # overstate how current a book is.
    import shutil
    import tempfile
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.modules.pop("gen_provenance", None)
    import gen_provenance
    tmp = tempfile.mkdtemp(prefix="greenbook-osmdate-")
    try:
        slug = "_datetest"
        d = os.path.join(tmp, "courses", slug)
        os.makedirs(d)
        for fn, ts in (("osm_geom.json", "2026-07-29T23:58:00Z"),
                       ("osm_course.json", "2026-07-30T00:04:00Z")):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                json.dump({"osm3s": {"timestamp_osm_base": ts}, "elements": []}, f)
        real_root = gen_provenance.ROOT
        gen_provenance.ROOT = tmp
        try:
            got = gen_provenance._osm_extract_date(slug)
        finally:
            gen_provenance.ROOT = real_root
        assert got == "2026-07-29", (
            f"_osm_extract_date returned {got!r} for extracts spanning 2026-07-29T23:58 and "
            f"2026-07-30T00:04. It must report the OLDER ingredient: the newer date would claim the "
            f"book is a day fresher than its oldest geometry actually is.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_surface_builder_drops_points_the_producer_disowns():
    """LAS `withheld` and `synthetic` points must never reach a green surface.

    Those bits are the producer's own verdict: withheld means "this measurement should not be used",
    synthetic means "computed, not observed". A book that prints a slope read off them is printing a
    number its own source disclaims. Every tile in the corpus carries ZERO of both, which is why this
    needs a test rather than a measurement -- there is no data to notice a regression with.

    Asserted as the SET of flags, read out of the source. The first version of this test searched main()
    for their NAMES, and that was vacuous: main() contains a prose comment explaining both flags, so
    replacing the tuple with ("key_point",) satisfied every assertion -- "withheld" in body, "synthetic"
    in body, the `g = g & ~bad` narrowing, and the "overlap" negative -- while the code dropped KEY
    POINTS and kept the withheld ones. A one-line edit to the very line the test guards, passing all of
    its assertions, corrupting the ground mask every printed slope, tilt and contour is measured from.
    The flag set was lifted to module scope so this test can read it instead of grepping for it.

    `overlap` must stay OUT, asserted too, because it looks like the same kind of flag and is not.
    Overlap points are valid returns where two flight lines meet; USGS flags them so derivative products
    *can* drop them. Two courses here are 31% and 47% overlap by ground point, and gridded separately the
    overlap points agree with the rest to RMS 1.16 cm over all 18 bay-view greens, every printed tilt
    within 0.07 pp. Dropping them would halve that course's density for nothing.
    """
    with open(os.path.join(ROOT, "fetch_dem_hd.py"), encoding="utf-8") as f:
        src = f.read()

    ns = {}
    for line in src.splitlines():
        if line.startswith("DISOWNED_FLAGS"):
            exec(line, ns)                  # noqa: S102 -- a literal tuple from this repo's own source
            break
    flags = ns.get("DISOWNED_FLAGS")
    assert flags is not None, (
        "fetch_dem_hd.py no longer defines DISOWNED_FLAGS at module scope. It was lifted there so this "
        "test could assert the SET; searching main() for the words is vacuous, because the comment that "
        "explains them contains them.")
    assert set(flags) == {"withheld", "synthetic"}, (
        f"the disowned-point flag set is {sorted(flags)}, expected ['synthetic', 'withheld']. Points the "
        f"producer marks unusable would reach a green the book prints a slope read off.")
    assert "overlap" not in flags, (
        "fetch_dem_hd.py now drops `overlap`. Those are valid returns where two flight lines meet, not "
        "rejected ones: bay-view is 47% overlap by ground point and its overlap-only surface agrees with "
        "the rest to RMS 1.16 cm, every tilt within 0.07 pp. Filtering halves the density and buys "
        "nothing -- see legal/09_GREEN_SURFACE_REPEATABILITY.md before changing this.")

    # and the set must actually narrow the ground mask, not merely exist
    body = src.split("def main(", 1)[-1]
    assert "DISOWNED_FLAGS" in body, (
        "main() no longer consults DISOWNED_FLAGS -- the set is defined and unused, which is worse than "
        "absent, because the comment beside it claims it works")
    assert re.search(r"g\s*=\s*g\s*&\s*~\s*bad", body), (
        "the flags are read but the ground mask is not narrowed by them")
    assert "cls==2" in body.replace(" ", ""), "the ground-class selection itself is gone"
    assert re.search(r"NOT filtering|not filtering", src), (
        "the note explaining why `overlap` is kept is gone; without it the flag reads like an oversight")


def test_the_cross_flight_check_cannot_agree_by_failing_to_read_a_date():
    """A tile whose gps_time carries no absolute date must stop the run, not quietly shorten it.

    cross_flight_check separates a green's surveys by decoding each point's date, and that decode is only
    valid for Adjusted Standard GPS time. GPS WEEK TIME records seconds since the start of a week the
    file does not name, so the date is genuinely unrecoverable -- lidar_dates.py refuses such tiles,
    having once turned every one of them into a fabricated 2011-09-14. This tool called gps_to_utc with
    its `adjusted=True` default: it assumed what the other module verifies.

    The reason that matters is the shape of the failure, which is silent and flattering. A bad decode does
    not produce visible nonsense: it collapses every point into one epoch, each green is then covered by a
    single pass, the course is skipped as "not independently covered", and the run prints ZERO
    disagreements. That reads as a clean bill of health, and this tool's output is the repeatability and
    contour-interval evidence in legal/09_GREEN_SURFACE_REPEATABILITY.md.

    Exercised as a decision on real header shapes rather than as a string in the source, because a
    pattern-shaped assertion has missed the actual edit three times in this suite already.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.modules.pop("cross_flight_check", None)
    import cross_flight_check as cfc

    class _GE:
        def __init__(self, t):
            self.gps_time_type = t

    class _H:
        def __init__(self, t=None):
            if t is not None:
                self.global_encoding = _GE(t)

    assert cfc.dates_recoverable(_H(1)) is True, (
        "adjusted standard GPS time (bit 0 = 1) is the only decodable form and must be accepted")
    assert cfc.dates_recoverable(_H(0)) is False, (
        "GPS WEEK TIME carries no week number, so no absolute date exists -- accepting it lets the run "
        "collapse every pass into one epoch and then report zero disagreements, which reads as a pass")
    assert cfc.dates_recoverable(_H()) is False, (
        "a header with no global_encoding at all must fail CLOSED; assuming adjusted time is the "
        "assumption this check exists to remove")

    # A REFUSAL must be a distinguishable OUTCOME, not the same value as "nothing to compare".
    # Both used to return (0, [], 0, 0, []), so main() printed one extra line, added zero to every
    # aggregate, and the run still exited 0 -- the tool agreeing by failing, which is exactly what its
    # docstring says it must not be able to do. Verified end to end: forcing dates_recoverable False on
    # a multi-date course makes the run print "REFUSED" and exit 1.
    assert cfc.REFUSED[0] is None, (
        "cross_flight_check.REFUSED no longer carries a distinguishing marker, so a course it could not "
        "examine reads as a course that agreed")
    assert cfc.REFUSED != (0, [], 0, 0, []), (
        "REFUSED is now byte-identical to the 'nothing to compare' return, which is how a refusal came "
        "to read as a pass")
    src_main = open(os.path.join(ROOT, "tools", "cross_flight_check.py"), encoding="utf-8").read()
    assert "return 1 if refused else 0" in src_main, (
        "main() no longer exits non-zero when a course was refused. A run that could not examine a "
        "course must not report success -- this tool's output is the evidence in "
        "legal/09_GREEN_SURFACE_REPEATABILITY.md.")

    # and the read loop must consult it, not just define it
    with open(os.path.join(ROOT, "tools", "cross_flight_check.py"), encoding="utf-8") as f:
        src = f.read()
    after = src.split("def check(", 1)[-1]
    assert "dates_recoverable(" in after, (
        "cross_flight_check.check() no longer consults dates_recoverable, so the refusal is defined and "
        "unused -- worse than absent, because the docstring claims the run cannot agree by failing")


def test_render_refuses_a_green_that_falls_metres_inside_its_own_outline(gate_course):
    """MAX_PLAUSIBLE_RELIEF_M had no test. It is the gate against a NoData crater.

    render_green carries four refusal gates and three were exercised: too much of the interior
    extrapolated, a perfectly constant surface, and a producer-flagged insufficient. The fourth --
    "a putting surface cannot plausibly fall metres within its own outline", written to catch a
    partially-filled NoData patch that survives the fraction test -- was reached by nothing. Coverage
    over the whole suite put render_green at 95% with these two lines among the remainder.

    That is the same shape as the confirmed-rebuild branch: a refusal in the honesty path that no data
    triggers and no test drives, so a wrong comparison or a mistyped constant would leave the suite green
    while a green with a 30 m hole in it printed a slope read. And the number it would print is not
    obviously wrong -- the plane fit through a crater still yields a tilt and a feed direction.

    Both sides asserted, because a gate that always refuses is as broken as one that never does: 30 m of
    fall must be refused, and a steep-but-real green must still be read.
    """
    import numpy as np
    import render_green
    assert render_green.MAX_PLAUSIBLE_RELIEF_M == 30.0, (
        "the plausible-relief ceiling moved; this test's surfaces are chosen either side of 30 m")

    # a crater: mostly a real green, with one deep patch, as a partially-filled NoData hole looks
    def crater(r, c):
        z = 100.0 + 0.02 * r
        return np.where((r > 25) & (r < 35) & (c > 25) & (c < 35), z - 40.0, z)

    _synth_green(gate_course, 11, crater, insufficient=False)
    _svg, s = render_green.render(11)
    assert s.get("insufficient") is True, (
        "a green falling 40 m inside its own outline must be refused. That is a NoData patch, not "
        "terrain, and the plane fit through it still returns a confident-looking tilt and feed word")
    assert s["conf"] == "no data" and s["tilt_pct"] == 0.0, (
        "a refused green must report no slope rather than the number computed from the crater")

    # ...and a genuinely severe green stays readable: 2.5 m of fall is a real, steep putting surface
    _synth_green(gate_course, 12, lambda r, c: 100.0 + 0.042 * r, insufficient=False)
    _svg2, s2 = render_green.render(12)
    assert not s2.get("insufficient"), (
        "2.5 m of fall across a green is severe but real -- refusing it would blank legitimate greens, "
        "and this corpus has surfaces with over 2 m of relief")
    assert s2["tilt_pct"] > 0, "a real sloping green must still report a tilt"


@needs_corpus
def test_re_running_the_surface_builder_cannot_blank_a_working_fallback(tmp_path):
    """fetch_dem_hd shares dem_hd/ with fetch_dem, and must not trade a working 1 m fill for a blank.

    The two stages write the same directory. fetch_dem_hd builds 0.4 m surfaces from LiDAR ground
    returns; fetch_dem fills the greens it gives up on from the seamless 1 m DEM, and those cards print a
    real read labelled "1 m data". Re-running fetch_dem_hd ALONE -- an ordinary thing to do after
    changing the point filter -- overwrote that fill with an insufficient=True record, and the green then
    prints BLANK. A card silently loses information and the only symptom is the blank itself.

    Found by doing it: re-running the stage on monarch-bay turned hole 10 from "1 m data" into a refused
    green (its 0.4 m attempt reports nan 1.000, density 0.0 -- a bayside green with essentially no ground
    returns). It is the exact mirror of the fault fetch_dem.keeps_existing_surface was written for, on the
    same course: that one replaced good 0.4 m greens with coarse 1 m ones and cost 1.1 MB of precision
    without printing a dishonest word. Only one direction had been guarded.

    Checked on the ARTIFACTS rather than in the source, because the clobber has a signature there: it
    leaves a green sourced from LiDAR and marked insufficient, where a seamless-sourced readable one used
    to be. So the corpus invariant is that nothing shipped is insufficient, and the fallback count has not
    quietly fallen.
    """
    insufficient, seamless, seen = [], [], set()
    for mf in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "dem_hd", "hole*.json"))):
        ref = os.path.basename(os.path.dirname(os.path.dirname(mf)))
        if ref.startswith("_"):
            continue
        seen.add(ref)
        with open(mf, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("insufficient"):
            insufficient.append(f"{ref} hole {m.get('hole')}")
        if "seamless" in str(m.get("source", "")).lower():
            seamless.append(f"{ref} hole {m.get('hole')}")
    assert seen, "no built greens found"
    assert not insufficient, (
        "green surface(s) on disk are marked insufficient, so their cards print blank:\n  "
        + "\n  ".join(insufficient)
        + "\n  If this followed a re-run of fetch_dem_hd.py, it overwrote a working 1 m fallback. "
          "Re-run fetch_dem.py to restore the fill, or use OVERWRITE=1 if blanking was the intent.")
    assert len(seamless) >= 6, (
        f"only {len(seamless)} green(s) are on the 1 m seamless fallback; monarch-bay alone has 6. A "
        f"drop means fetch_dem_hd replaced a fill -- with a GOOD 0.4 m surface that is an upgrade and "
        f"this floor should be lowered deliberately, but with a refused one it is a blanked green.")

    # The guard itself, by TRUTH TABLE. The two assertions here used to be greps over the module
    # source -- 'os.environ.get("OVERWRITE")' and "is_seamless" -- and BOTH were satisfied from outside
    # the guard: the first by the module-scope OVERWRITE read, the second by the word "is_seamless"
    # inside an import COMMENT. Deleting the entire guard left this test green, which is the whole
    # failure mode the artifact assertions above also share (they read files written days ago and never
    # invoke the module). Now the decision is a predicate and the test exercises it.
    import fetch_dem_hd
    def keeps(rec, overwrite=False):
        if rec is None:
            return fetch_dem_hd.keeps_existing_surface(str(tmp_path / "absent.json"), overwrite)
        mp = tmp_path / "prev.json"
        mp.write_text(rec if isinstance(rec, str) else json.dumps(rec), encoding="utf-8")
        return fetch_dem_hd.keeps_existing_surface(str(mp), overwrite)

    LIDAR = {"source": "USGS 3DEP LiDAR ground returns @0.4m", "insufficient": False}
    SEAMLESS = {"source": "USGS 3DEP 1 m seamless DEM", "insufficient": False}
    cases = [
        (LIDAR, False, True, "a good 0.4 m LiDAR surface -- the 192-green majority. The old guard "
                             "tested is_seamless, so it protected ONLY the 6 seamless records and would "
                             "have let a refused re-run blank any of the other 192."),
        (SEAMLESS, False, True, "a working 1 m seamless fill -- the case the guard was written for"),
        ({**LIDAR, "insufficient": True}, False, False,
         "a record that was ALREADY a refusal is not worth keeping; rebuilding it is the repair"),
        ({"insufficient": False}, False, False,
         "no source field at all: unknown provenance, so leave it fillable rather than protect it on a "
         "guess -- same rule as fetch_dem.keeps_existing_surface"),
        ("{not json", False, False, "an unreadable file must be rebuilt, not protected"),
        (None, False, False, "nothing on disk yet"),
        (LIDAR, True, False, "OVERWRITE=1 must still be able to do it on purpose, or the guard is a "
                             "wall rather than a safety net"),
    ]
    for rec, ow, want, why in cases:
        got = keeps(rec, ow)
        assert got is want, (
            f"fetch_dem_hd.keeps_existing_surface returned {got}, expected {want}: {why}")

    # and main() must actually consult it -- a correct predicate nobody calls protects nothing
    with open(os.path.join(ROOT, "fetch_dem_hd.py"), encoding="utf-8") as f:
        src = f.read()
    # keep the "def main(" so the fragment tokenises -- splitting AFTER it yields "):\n    ..." which
    # does not, and _code_only used to answer that by returning the raw source, comments and all.
    body = "def main(" + src.split("def main(", 1)[1]
    assert "keeps_existing_surface" in _code_only(body), (
        "fetch_dem_hd.main() no longer calls keeps_existing_surface, so a refused 0.4 m attempt can "
        "overwrite a working surface again and blank the card")


def test_one_normalised_spelling_of_build_mode_across_the_engine(tmp_path):
    """A capitalised build_mode split the engine: a full slope book, described as blank greens.

    course.json is hand-edited -- it carries the scorecard transcription -- so a stray capital or a
    trailing space is a realistic typo. distribution.py already normalised for that on its own side and
    its docstring argues the exact case. config.py did not: it bound COURSE.get("build_mode", "full")
    raw, and generate.py / fetch_hole_elev.py compared it with == "yardage" exactly.

    So "Yardage" made the two halves disagree in the worst available way. distribution_status() answered
    Personal and tools/gen_provenance.py wrote "yardage mode: blank greens" into legal/03, while
    generate.py built a FULL book with slope maps, contours and arrows off the LiDAR that yardage mode
    exists to suppress. Not a wrong number -- a legal record describing a book that was never made.
    Four of five plausible spellings diverged; only the exact one agreed.

    Asserted as agreement between the two consumers, on the values a typo actually produces, rather than
    as a string in either file.
    """
    import subprocess

    import distribution
    for raw in ("yardage", "Yardage", "YARDAGE", " yardage", "yardage\n", "\tYardage "):
        course = {"build_mode": raw}
        assert distribution.build_mode(course) == "yardage", f"{raw!r} did not normalise"
        assert distribution.is_yardage(course) is True, f"{raw!r} is not read as yardage mode"
        assert distribution.distribution_status(course)[1] == "Personal", (
            f"{raw!r} must be personal-use: yardage mode means no trustworthy post-construction "
            f"elevation, so the book prints blank greens")

    # And config must expose the SAME answer, since generate.py branches on config.BUILD_MODE. Built
    # through a throwaway course dir, following the gate_course/_synth_* convention: config resolves
    # courses/ from the repo root, not the cwd, so a tmp_path cannot stand in for it. The leading
    # underscore keeps the slug out of CORPUS, gen_provenance and the distribution scan.
    import shutil
    slug = "_synth_bmode"
    cdir = os.path.join(ROOT, "courses", slug)
    prev = os.environ.get("COURSE")
    try:
        os.makedirs(cdir, exist_ok=True)
        for raw, want in (("Yardage", "yardage"), (" yardage", "yardage"), ("YARDAGE", "yardage"),
                          ("full", "full"), ("", "full"), ("Full", "full")):
            with open(os.path.join(cdir, "course.json"), "w", encoding="utf-8") as f:
                json.dump(dict(slug=slug, name="BMode", address="", par=72,
                               location={"lat": 40.0, "lon": -75.0},
                               tees=[dict(name="Card", yards=100, rating=70.0, slope=113)],
                               featured_tee="Card", hole_cols=["par", "mens_hcp", "Card"],
                               holes={"1": [72, 1, 100]}, build_mode=raw,
                               osm_bbox=[39.99, -75.01, 40.01, -74.99], sources={}), f)
            r = subprocess.run(
                [sys.executable, "-c",
                 "import config, distribution as d, json;"
                 "print(json.dumps([config.BUILD_MODE, d.build_mode(config.COURSE)]))"],
                cwd=ROOT, env=dict(os.environ, COURSE=slug, QUIET_TEE_CHECK="1"),
                capture_output=True, text=True)
            assert r.returncode == 0, f"config failed to bind build_mode={raw!r}:\n{r.stderr[-600:]}"
            got, norm = json.loads(r.stdout.strip().splitlines()[-1])
            assert got == want, (
                f"build_mode={raw!r}: config.BUILD_MODE is {got!r}, expected {want!r}. generate.py "
                f"compares this with == 'yardage', so a mismatch builds a full slope book for a course "
                f"distribution.py and legal/03 describe as having blank greens.")
            assert (got == "yardage") == (norm == "yardage"), (
                f"build_mode={raw!r}: config says {got!r}, distribution says {norm!r} -- the two halves "
                f"of the engine disagree about whether this course has slope maps")
    finally:
        shutil.rmtree(cdir, ignore_errors=True)
        _restore_course(prev)


@needs_corpus
def test_the_card_only_claims_an_official_scorecard_where_one_is_recorded():
    """The tees card said "Yardages from the official scorecard." on every book. 7 of 11 had none.

    Only 4 courses record an official or printed club scorecard. The other 7 record third-party
    aggregators -- BlueGolf, NCGA, GolfLink, Wikipedia, Golfify -- so "official" was a claim about
    provenance the record does not support, printed directly beside the numbers it vouches for. The same
    book already said the honest version two cards away: the guide card credits "facts from the PUBLISHED
    scorecard".

    Aggregator data is not the problem and this is not a downgrade for its own sake. bay-view's own source
    note records that a third-party record was WRONG and had to be corrected against the club's card --
    which is exactly why the distinction is worth printing rather than papering over. A reader who knows
    the yardages came from an aggregator can weigh them; one told they came from the club cannot.

    Derived from sources.scorecard, the same field the provenance record is built from, so the card and
    legal/03 cannot disagree. Asserted in BOTH directions: a course that earned "official" must still say
    it, or the fix would have quietly cost four books a true claim.
    """
    checked, problems, off_n, pub_n, seen = 0, [], 0, 0, collections.Counter()
    for ref in BOOKS:
        cp = os.path.join(ROOT, "courses", ref, "course.json")
        bp = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not (os.path.exists(cp) and os.path.exists(bp)):
            continue
        seen[ref] += 1
        with open(cp, encoding="utf-8") as f:
            src = str((json.load(f).get("sources") or {}).get("scorecard") or "").lower()
        with open(bp, encoding="utf-8") as f:
            html = f.read()
        earned = ("official" in src) or ("printed scorecard" in src)
        says_off = "Yardages from the <b>official</b> scorecard" in html
        says_pub = "Yardages from <b>published</b> scorecard data" in html
        if says_off == says_pub:
            problems.append(f"{ref}: the tees card makes neither claim, or both -- the wording moved and "
                            f"this test can no longer see it")
            continue
        checked += 1
        off_n += says_off
        pub_n += says_pub
        if says_off and not earned:
            problems.append(
                f"{ref}: prints 'from the official scorecard' but records only {src[:60]!r}. That is a "
                f"provenance claim the record does not support, beside the numbers it vouches for.")
        if earned and not says_off:
            problems.append(
                f"{ref}: records an official scorecard ({src[:50]!r}) but prints the weaker 'published' "
                f"claim -- it earned the stronger one and should say so.")
    assert checked >= 10, f"only {checked} tees cards were readable"
    assert_no_course_skipped(seen, "test_the_card_only_claims_an_official_scorecard_where_one_is_recorded")
    assert off_n and pub_n, (
        f"every book now makes the SAME claim ({off_n} official, {pub_n} published), so this test cannot "
        f"tell the two apart any more. The corpus had 4 and 7; if that really changed, re-measure.")
    assert not problems, "the tees card overstates where its yardages came from:\n  " + "\n  ".join(problems)


@needs_corpus
def test_the_naip_credit_lands_on_the_course_that_actually_used_it():
    """The USDA NAIP credit was printed on the wrong course, and withheld from the right one.

    Two different uses, decided from two different kinds of evidence:
      * TRACING geometry from NAIP is checkable against the artifact -- the traced feature carries a
        `_digitized` tag naming NAIP.
      * Using NAIP as a site REFERENCE leaves nothing in the geometry, so it can only come from the
        record, under sources.aerial.

    Gating the whole thing on "does the word naip appear anywhere in sources" inverted it. valley-hi's
    sources.geometry still said it digitized hole 16's green from NAIP -- true once, until check_osm_bbox
    found its OSM bbox ~46 m short at that hole, a widened box recovered the REAL green 1.3 m away (33
    vertices against the tracing's 17), and the tracing was dropped. Zero `_digitized` features remain, so
    the book credited NAIP for geometry it no longer contains. Meanwhile bay-view, holding the corpus's
    only two NAIP-traced greens (ways 900000005 and 900000007), credited nothing, because its
    sources.geometry says only "OpenStreetMap contributors (ODbL)".

    NAIP is public domain, so no notice is legally owed either way. What is owed is that a book which
    enumerates its sources enumerates the right ones -- and a credit on a course that did not use it is
    the same class of error as a missing one.
    """
    checked, problems, printed, seen = 0, [], [], collections.Counter()
    for ref in BOOKS:
        cp = os.path.join(ROOT, "courses", ref, "course.json")
        bp = os.path.join(ROOT, "courses", ref, "greenbook.html")
        if not (os.path.exists(cp) and os.path.exists(bp)):
            continue
        seen[ref] += 1
        checked += 1
        with open(cp, encoding="utf-8") as f:
            j = json.load(f)
        traced = False
        for fn in ("osm_geom.json", "osm_course.json"):
            fp = os.path.join(ROOT, "courses", ref, fn)
            if not os.path.isfile(fp):
                continue
            with open(fp, encoding="utf-8") as f:
                for e in (json.load(f).get("elements") or []):
                    if "naip" in str((e.get("tags") or {}).get("_digitized", "")).lower():
                        traced = True
                        break
            if traced:
                break
        referenced = "naip" in str((j.get("sources") or {}).get("aerial") or "").lower()
        with open(bp, encoding="utf-8") as f:
            credits = "USDA NAIP" in f.read()
        if credits:
            printed.append(ref)
        want = traced or referenced
        if credits and not want:
            problems.append(
                f"{ref}: credits USDA NAIP but has no NAIP-traced geometry (`_digitized`) and no NAIP "
                f"under sources.aerial. The book is enumerating a source it did not use.")
        if want and not credits:
            problems.append(
                f"{ref}: {'traced geometry from NAIP' if traced else 'records NAIP under sources.aerial'} "
                f"and credits it nowhere. A book that lists its sources should list all of them.")
    assert checked >= 10, f"only {checked} books checked"
    assert_no_course_skipped(seen, "test_the_naip_credit_lands_on_the_course_that_actually_used_it")
    assert printed, (
        "no book credits USDA NAIP at all. bay-view holds two NAIP-traced greens, so if that is gone the "
        "geometry changed and this test now proves nothing -- re-measure rather than lowering the bar.")
    assert not problems, "the NAIP credit is on the wrong course:\n  " + "\n  ".join(problems)


@pytest.mark.slow          # grids one real green from its point cloud
@needs_corpus
def test_the_cross_flight_grid_matches_the_surface_it_checks():
    """cross_flight_check must grid a pass the way the shipped surface was gridded, or it compares a
    different green.

    It gridded with `linspace(ymin, ymax, H)` -- row 0 at the SOUTH edge, sampling bbox EDGES -- while
    fetch_dem_hd writes north-up on cell centres ("row0=top=ymax") and both the green mask and the
    plane fit assume that. So the one tool that checks the printed read against itself was comparing a
    vertically MIRRORED surface, half a cell out. Over 90 corpus greens: a median 0.42 pp of tilt and
    76 degrees of aim, 62 of 90 past TOL_TILT_PP and 84 of 90 past TOL_AIM_DEG -- the tolerances were
    calibrated on those numbers. Correcting it took the noise floor from RMS 0.85 cm to 0.56 and the
    contour interval from 18x it to 27x, i.e. the whole of legal/09 moved.

    THREE EARLIER ATTEMPTS TO GUARD THIS COULD NOT FAIL, and the reasons are worth keeping:
      * the sibling delegation test tilts a SQUARE green EAST -- invariant under a vertical flip, which
        is how the tool shipped mirrored for its whole life with a test watching it;
      * a source grep for "linspace(ymin, ymax" is satisfied by the COMMENT in the tool that explains
        the fix -- this codebase writes long explanatory comments, so source greps are unreliable in it;
      * recomputing the expected cell centres inside the test compares them only against themselves.

    So this grids a REAL green from its own LAZ through the tool's own `_summary` and differences the
    result against the shipped `.npy`. A mirrored grid shows up as a vertical flip: the correlation
    against the shipped surface collapses while the correlation against its row-reversal is high. No
    sign convention to get right, and nothing a comment can satisfy.
    """
    import numpy as np
    laspy = pytest.importorskip("laspy")
    pytest.importorskip("scipy")

    slug = next((c for c in CORPUS
                 if glob.glob(os.path.join(ROOT, "courses", c, "laz", "*.laz"))
                 and os.path.isfile(os.path.join(ROOT, "courses", c, "dem_hd", "hole01.json"))), None)
    if slug is None:
        pytest.skip("no course with both a point cloud and a built surface")

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    for m in ("config", "geo", "render_green", "cross_flight_check", "fetch_dem_hd"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import cross_flight_check as cfc
    from fetch_dem_hd import laz_to_utm
    from pyproj import Transformer

    cdir = os.path.join(ROOT, "courses", slug)
    meta = json.load(open(os.path.join(cdir, "dem_hd", "hole01.json"), encoding="utf-8"))
    if meta.get("insufficient") or "seamless" in str(meta.get("source", "")).lower():
        pytest.skip("hole 1 is not a point-cloud surface on this course")
    shipped = np.load(os.path.join(cdir, "dem_hd", "hole01.npy")).astype(float)
    _pt2utm, zscale = laz_to_utm()

    x0, y0, x1, y1 = meta["bbox"]
    lons, lats, zs = [], [], []
    for tile in sorted(glob.glob(os.path.join(cdir, "laz", "*.laz"))):
        with laspy.open(tile) as f:
            crs = f.header.parse_crs()
            if crs is None:
                continue
            inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            for ch in f.chunk_iterator(4_000_000):
                g = np.asarray(ch.classification) == 2
                if not g.any():
                    continue
                lo, la = inv.transform(np.asarray(ch.x)[g], np.asarray(ch.y)[g])
                sel = (lo > x0) & (lo < x1) & (la > y0) & (la < y1)
                if sel.any():
                    lons.append(lo[sel]); lats.append(la[sel]); zs.append(np.asarray(ch.z)[g][sel])
        if sum(len(a) for a in lons) > 40_000:
            break
    if not lons:
        pytest.skip("no ground returns recovered over this green")

    grid = cfc._grid(meta)
    S = cfc._summary(meta, grid, np.concatenate(lons), np.concatenate(lats),
                     np.concatenate(zs), zscale)
    assert S is not None, "the tool could not summarise a green it has point data for"
    mask = grid[4]
    got = S["surf"]
    assert got.shape == shipped.shape, f"grid shape {got.shape} vs shipped {shipped.shape}"

    def corr(a, b):
        u, v = a[mask].ravel(), b[mask].ravel()
        ok = np.isfinite(u) & np.isfinite(v)
        if ok.sum() < 100 or np.std(u[ok]) == 0 or np.std(v[ok]) == 0:
            return 0.0
        return float(np.corrcoef(u[ok], v[ok])[0, 1])

    upright = corr(got, shipped)
    flipped = corr(got, shipped[::-1, :])
    assert upright > flipped, (
        f"tools/cross_flight_check.py grids {slug} hole 1 UPSIDE-DOWN: its surface correlates "
        f"{flipped:.3f} with the vertical mirror of the shipped one and only {upright:.3f} with the "
        f"shipped one itself. Every tilt and aim it reports is then measured on a different green from "
        f"the one the card prints, and legal/09 rests on those numbers. The shipped convention is "
        f"cell centres with row 0 at the NORTH edge -- see fetch_dem_hd.py's 'row0=top=ymax'.")
    assert upright > 0.9, (
        f"cross_flight_check's surface correlates only {upright:.3f} with the shipped one over the "
        f"green interior; the orientation is right but something else about the grid is not")


@pytest.mark.slow          # re-renders every card of every book
@needs_corpus
def test_every_shipped_card_is_what_the_engine_produces_now():
    """The books on disk must be what today's code emits, panel for panel.

    A MUTATION SURVEY OF THIS SUITE FOUND THIS TO BE ITS LARGEST STRUCTURAL GAP. Roughly a third of the
    suite's evidence is the committed artifact -- greenbook*.html, the PDFs, dem_hd/*.json,
    hole_elev.json -- so an ENGINE change that emits a wrong number leaves every artifact test green
    until somebody happens to rebuild. Four such mutations were run and all four passed the full suite:

      * every footer's bunker count made one too low in generate.py
      * every footer's water count made one too low
      * the scorecard's Out row made to sum holes 1-8, dropping hole 9
      * an unqualified Rule 4.3 conformance claim emitted on every card

Each of those puts a wrong number in a junior's pocket. `test_built_books_still_match_the_engine_and_
    the_data` closes this loop for the PLAYLINE ROW only; the cold-build test closes it completely but
    is gated behind COLD_BUILD=1 and takes twenty minutes, so it does not run in an ordinary suite.

    This re-renders every hole panel and every green panel in process and requires the shipped HTML to
    contain them verbatim. It is the cheap half of the cold build: it cannot catch a change to the
    sheet imposition or the cover, but it catches any change to what a CARD says -- which is where the
    printed numbers live. When it fails the fix is almost always to rebuild, and the message says so.

    IT ALSO CLOSES THE SURVEY'S OTHER FINDING, which I first reported as still open. The survey showed
    a POCKET-edition green drawn for the wrong hole survives when the two holes share a rotation and a
    depth -- the enlarged edition has a dedicated guard and the pocket edition did not. Comparing the
    whole panel verbatim catches it regardless: swapping two DISTINCT green SVGs between monarch-bay
    holes 2 and 13 in the shipped book (18,975 and 22,753 characters, file length unchanged) fails here.
    That is the matched-rotation matched-depth pair the survey chose precisely because the old guards
    could not see it. Checked after the fact, because I had claimed otherwise -- and a first attempt to
    reproduce it passed only because the mutation was ineffective, a non-greedy </div> match swapping a
    fragment inside the SVG rather than the surface.

    The gap that genuinely remains is different in kind, and no amount of re-rendering closes it:
    self-consistency standing in for verification. Par, stroke index, tee yardage, page totals and tee
    elevation are each checked only against other copies of themselves, so six mutations that changed
    every copy together stayed green -- including a tee yardage off by 10 yd, consistent across
    course.json, both editions, the scorecard row and the totals. Nothing in this suite compares a
    yardage to anything OUTSIDE course.json; closing that needs an external reference the project does
    not hold.
    """
    checked = collections.Counter()
    stale = []
    for slug in CORPUS:
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        if not os.path.isfile(book):
            continue
        os.environ["COURSE"] = slug
        for m in ("config", "geo", "render_green", "render_hole", "generate"):
            sys.modules.pop(m, None)
        import config
        import generate
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        yardage = (config.BUILD_MODE == "yardage")
        if not yardage:
            for h in config.HOLE_NUMS:
                generate.GREENS[h] = generate.render_green.render(h, tournament=True)
                generate.LAYOUTS[h] = generate.render_hole.render_hole(h, generate.HOLES)
        thirds = generate._deck_thirds(config.HOLE_NUMS)
        for h in config.HOLE_NUMS:
            grp = next(lbl for lo, hi, lbl in thirds if lo <= h <= hi)
            panel = (generate.yardage_hole_panel(h, grp) if yardage
                     else generate.hole_panel(h, grp))
            checked[slug] += 1
            if panel not in html:
                stale.append(f"{slug} hole {h}")
        for maker in (generate.scorecard_panel, generate.tees_panel):
            try:
                p = maker()
            except Exception:
                continue
            checked[slug] += 1
            if p not in html:
                stale.append(f"{slug} {maker.__name__}")
    assert sum(checked.values()) >= 150, (
        f"only {sum(checked.values())} panels re-rendered; the corpus ships 216 hole cards")
    assert not stale, (
        f"{len(stale)} shipped panel(s) are not what the engine emits now:\n  "
        + "\n  ".join(stale[:12])
        + "\n\n  Either the books need rebuilding (COURSE=<slug> python3 generate.py, then "
          "python3 tools/export_pdf.py), or a code change altered a printed value and the books "
          "still show the old one. Until they agree, every test that reads the shipped HTML is "
          "measuring yesterday's engine.")
    assert_no_course_skipped(checked, "test_every_shipped_card_is_what_the_engine_produces_now")


@needs_corpus
def test_par_and_length_agree_with_each_other():
    """The FIRST check in this suite on a scorecard fact that is not another copy of itself.

    A mutation survey found the suite's second structural weakness: par, stroke index, tee yardage and
    the page totals are each verified only against other copies of themselves. Six mutations that
    changed every copy consistently -- course.json, both editions, the scorecard row, Out and Tot --
    left the suite green, including a tee yardage off by 10 yd and a par 5 turned into a par 4. Nothing
    here compares a yardage to anything OUTSIDE course.json, so a transcription error that is faithfully
    propagated is invisible.

    Par and length are not independent, and that is an anchor outside the file: the rules of golf and
    the USGA's yardage guidelines constrain them. Measured over the corpus at the BACK tee -- the column
    every card headlines -- par 3 runs 125-250 yd, par 4 runs 275-502 and par 5 runs 469-622. The par
    3/par 4 boundary is CLEAN with a 25 yd gap; par 4 and par 5 genuinely overlap by 33 yd, because long
    par 4s and short par 5s both exist, so the bounds below are one-sided where the data overlaps.

    What this catches: a mis-keyed ROW -- the realistic transcription error, where a hole takes another
    hole's par or another hole's yardage. A par 3 at 413 yd, a par 5 at 200, a par 4 at 620.

    What it does NOT catch, stated so the coverage is not overread: a yardage off by ten, or a stroke
    index swapped with its neighbour. Those need a published reference this project does not hold, and
    the honest way to close them is a committed file of per-hole yardages transcribed a second time from
    each course's card -- a data task, not a code one.
    """
    # Generous against the measured corpus (par 3 max 250 -> 260; par 4 min 275 -> 265, max 502 -> 540;
    # par 5 min 469 -> 440). Wide enough that no real hole is accused, tight enough that a swapped row is.
    BOUNDS = {3: (90, 260), 4: (265, 540), 5: (440, 700), 6: (600, 900)}
    checked = collections.Counter()
    bad = []
    for slug in CORPUS:
        os.environ["COURSE"] = slug
        for m in ("config", "geo"):
            sys.modules.pop(m, None)
        import config
        for hn in config.HOLE_NUMS:
            row = config.HOLES[hn]
            par, yd = row[0], row[config.BACK_I]
            if par not in BOUNDS or not isinstance(yd, (int, float)) or yd <= 0:
                continue
            checked[slug] += 1
            lo, hi = BOUNDS[par]
            if not (lo <= yd <= hi):
                bad.append(f"{slug} hole {hn}: par {par} at {yd} yd from {config.BACK_NAME} "
                           f"(a par {par} runs {lo}-{hi} yd)")
    assert sum(checked.values()) >= 190, (
        f"only {sum(checked.values())} holes checked; the corpus has 216")
    assert not bad, (
        "a hole's par and its length contradict each other, which usually means a row was mis-keyed -- "
        "the hole took another hole's par or another hole's yardage:\n  " + "\n  ".join(bad))
    assert_no_course_skipped(checked, "test_par_and_length_agree_with_each_other")


@needs_corpus
def test_no_par_3_prints_a_carry():
    """"carry N" is a tee-shot decision, and a par 3 does not have one.

    The figure answers "how far must I fly to clear the sand and land on fairway short of the green" --
    a real question on a par 4 or 5, and no question at all on a par 3, where the shot is to the green.
    All six par-3 carries in the corpus printed a number far short of the card yardage, and on two of
    them the near edge was actively misleading:

      * the-reserve 8 printed "carry 90" for a waste complex running 90 to 216 yd on a 237 yd hole --
        sand ending four yards short of the green front. Flying 90 clears nothing; the distance that
        matters is ~215. A 126 yd gap, eight or nine clubs.
      * merion 13 printed "carry 82" on a 128 yd hole for sand running 82 to 113 with the green front
        at 107 -- again no landing area beyond it.

    Checked on the ARTIFACT and against the scorecard's own par, so it cannot be satisfied by reading
    the same constant the renderer reads. The map still draws every bunker and the footer still counts
    it, so this hides nothing -- it removes an invitation to play a shot that does not exist.
    """
    checked = collections.Counter()
    offenders = []
    for slug in CORPUS:
        book = os.path.join(ROOT, "courses", slug, "greenbook.html")
        cj = os.path.join(ROOT, "courses", slug, "course.json")
        if not (os.path.isfile(book) and os.path.isfile(cj)):
            continue
        with open(cj, encoding="utf-8") as fh:
            holes = json.load(fh).get("holes") or {}
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        for blk in re.split(r'<div class="panel hole', html)[1:]:
            blk = re.split(r'<div class="panel ', blk)[0]
            hn = re.search(r'class="hnum">(\d+)</div>', blk)
            if not hn:
                continue
            par = (holes.get(hn.group(1)) or [None])[0]
            if par is None:
                continue
            checked[slug] += 1
            carry = re.search(r'carry <b>([^<]*)</b>', blk)
            if par == 3 and carry:
                offenders.append(f"{slug} hole {hn.group(1)} (par 3, {(holes[hn.group(1)] or [0,0,0])[2]} yd) "
                                 f"prints carry {carry.group(1)}")
    assert sum(checked.values()) >= 150, (
        f"only {sum(checked.values())} hole cards examined; the corpus ships 216")
    assert not offenders, ("a par 3 prints a carry, which invites a lay-up that does not exist:\n  "
                           + "\n  ".join(offenders))
    assert_no_course_skipped(checked, "test_no_par_3_prints_a_carry")


@needs_corpus
def test_a_printed_carry_has_an_origin_the_geometry_corroborates():
    """A carry is measured FROM THE BACK TEE. Where the tee's position is unknown, print nothing.

    Every carry distance is measured along the drawn line from where the line starts, plus tee_shift_yd
    -- and that shift only exists when tee_ok, fwd_tee or past_tee has established where the back tee is.
    Two holes printed carries with no such evidence:

      * castlewood-valley 10 printed "carry 139 / 277" while its from-tee gutter is BLANK on all five
        rows, precisely because the code cannot say where the line's 64 yd shortfall lives. The carries
        asserted the line's start IS the Black tee -- the assumption the empty gutter refuses to make.
        The mapped Black tee is 51-66 yd further back, so 139 understated by that much and 277 is
        328-341 yd from the real tee, past CARRY_MAX_YD: a second-shot bunker printed as a driving
        carry on a 561 yd par 5.
      * merion 3 printed gutters from a 250 yd origin (par3_exact, asserted from the card) and
        "carry 170" from a 215 yd one -- two origins 35 yd apart on one card.

    par3_straight is deliberately NOT an origin-establishing condition, and that is the substance of this
    test rather than an implementation detail. Propagating its card-derived origin to the carries is the
    obvious fix and it is the wrong one: on merion 3 it would print 205 for sand the mapped geometry puts
    at 184, trading a 14 yd understatement for a 21 yd OVERSTATEMENT. Too long is the dangerous direction
    -- it tells a player they have room they do not have.

    Asserted over the whole corpus so the rule cannot be satisfied by special-casing two holes, and in
    both directions: a hole WITH a corroborated origin must keep printing its carries, or a fix that
    silenced the footer everywhere would pass.
    """
    with_origin, without, seen = 0, [], collections.Counter()
    for slug in geometry_courses():
        os.environ["COURSE"] = slug
        os.environ["QUIET_TEE_CHECK"] = "1"
        for m in ("config", "geo", "render_hole"):
            sys.modules.pop(m, None)
        import config
        import render_hole
        _bp = os.path.join(ROOT, "courses", slug, "greenbook.html")
        shipped = open(_bp, encoding="utf-8").read() if os.path.isfile(_bp) else None
        seen[slug] += 1
        for h in sorted(config.HOLES, key=lambda x: int(x)):
            _svg, i = render_hole.render_hole(int(h), config.HOLES)
            known = bool(i["line_spans"] or i["fwd_tee"] or i["past_tee"])
            assert i["carry_origin_known"] == known, (
                f"{slug} hole {h}: carry_origin_known={i['carry_origin_known']} but line_spans/fwd_tee/"
                f"past_tee say {known} -- the exported flag has drifted from the condition")
            # THE OBSERVABLE CONSEQUENCE, not the formula again. The assertion above restates
            # render_hole's own expression verbatim, so it can only catch the exported flag drifting from
            # it -- never a wrong origin, which is what the test is named for. What matters is what the
            # CARD does: a hole whose origin nothing corroborates must print no carry, and it must print
            # none in the shipped book too, not merely in this re-render. Checked against the artifact so
            # a stale book cannot hide behind a correct engine.
            if not known:
                assert not i.get("carries"), (
                    f"{slug} hole {h}: the engine produced carries {i.get('carries')} with no "
                    f"corroborated origin -- the suppression at render_hole's origin gate did not fire")
                if shipped is not None:
                    blk = next((b for b in re.split(r'<div class="panel hole', shipped)[1:]
                                if re.search(rf'class="hnum">{int(h)}</div>', b)), "")
                    blk = re.split(r'<div class="panel ', blk)[0]
                    assert "carry <b>" not in blk, (
                        f"{slug} hole {h}: the SHIPPED card prints a carry although the geometry gives "
                        f"no origin for it. The engine suppresses it, so this book predates that fix -- "
                        f"rebuild, or a reader is being handed a number measured from nowhere.")
            if i.get("carries"):
                if known:
                    with_origin += 1
                else:
                    without.append((slug, int(h), i["carries"], i["par3_straight"]))
    assert_no_course_skipped(seen, "test_a_printed_carry_has_an_origin_the_geometry_corroborates")
    assert not without, (
        "hole(s) print a carry measured from an origin nothing corroborates:\n  "
        + "\n  ".join(f"{s} hole {h}: {c} (par3_exact={p3}) -- if par3_exact is the only reason this "
                      f"hole has a gutter, its origin comes from the card alone and the mapped tees may "
                      f"contradict it; refuse the carry rather than print it long"
                      for s, h, c, p3 in without))
    assert with_origin >= 80, (
        f"only {with_origin} holes print a carry with a corroborated origin; the corpus has 90. A rule "
        f"that silenced the footer broadly would satisfy the check above, so this floor is the other "
        f"half of it.")
