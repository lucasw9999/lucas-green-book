#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The guards that stand between one test and the next, and between an editing slip and the only copy of
the corpus.

They live in conftest.py because that is the ONLY file pytest loads for every test module in this
directory. The deletion guard used to be a session-autouse fixture inside test_phase1_regressions.py,
whose own comment called itself "one choke point ... every deletion in this suite" -- which was not true
of anything but that one file. `pytest tests/<any new file>` ran completely unguarded, and a second test
module is the natural thing for the next person to add.

`_bind_a_course` was in the same position and moved here for the same reason, one round later, once the
"next person" had arrived: this directory now holds eleven test modules and an autouse fixture applies
only to the module (or, from here, the package) that declares it. README's promise that the COURSE
binding is restored "after every test" was true of one file while eight others rebound COURSE, imported
config, and left the binding for whatever ran next -- which is exactly the leakage the shuffled-order
advice beside it is about, and how a real IndexError in render_hole hid for its whole life.

`_a_course_exists_to_bind` is the third, and it is here because a binding needs something to bind TO:
on a fresh clone there is no course at all, so the binder had nothing to do and `import config` died
with SystemExit in every test that reached an engine module. See its own docstring.

What courses/ is, and why deletion is the interesting failure: a course folder holds ~300 MB of
LiDAR, the derived 0.4 m green surfaces, and course.json -- a scorecard a human transcribed from
published cards and cross-verified against club sources. The directory is gitignored by design, so
there is no copy in history, none on a remote, none anywhere. Only laz/ can be fetched again.
"""
import glob
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_COURSE_DATA, _SCRATCH, _OUTSIDE = "course data", "scratch", "outside courses/"

# Every file render_hole.load() reads. Requiring only osm_geom.json admitted half-built dirs whose
# holes then failed to render and were silently swallowed.
CORPUS_NEEDS = ("osm_geom.json", "osm_course.json")

# The slug a FRESH CLONE binds to. See _a_course_exists_to_bind.
FRESH_CLONE_SLUG = "_no_corpus_fixture"


def corpus_slugs():
    """Course slugs that have the geometry needed to render a hole map.

    Underscore-prefixed folders are scratch (staging, the cold-build test, and the fresh-clone
    fixture below) and are skipped so a transient directory cannot silently widen or narrow what the
    corpus tests measure.

    HERE RATHER THAN IN THE SUITE FILE because `_bind_a_course` below needs it and conftest.py cannot
    import a test module. test_phase1_regressions._courses() delegates to this, so the rule has one
    home: two spellings of "is this a course?" is the drift this repo has already fixed in four places
    (see _classify's note on distribution.is_corpus_slug).
    """
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        if all(os.path.exists(os.path.join(ROOT, "courses", slug, f)) for f in CORPUS_NEEDS):
            out.append(slug)
    return out


def _reads_as_a_course_record(path):
    """Does `path` hold JSON config.py can bind to? A leftover that EXISTS is not one that works.

    The depth is deliberate and is not laziness: nothing but _a_course_exists_to_bind ever writes this
    slug, and all it ever writes is examples/course.json, so the only shapes reachable here are the two
    a half-finished run leaves -- no file at all, or a torn one. A missing file is config.py's SystemExit;
    a torn one is a JSONDecodeError out of json.load. Both are "not usable", which is the whole
    question, and validating further would duplicate _check_course over a file this fixture owns.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return isinstance(json.load(fh), dict)
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="session", autouse=True)
def _a_course_exists_to_bind(_deletion_cannot_reach_a_real_course):
    """On a fresh clone, make ONE course for the engine to import against. Inert where a corpus exists.

    courses/ is gitignored, so a stranger who clones this repo has the engine and no data at all.
    `import config` then falls back to its own hardcoded default slug, does not find it, and raises
    SystemExit -- so every test that imports ANY engine module (config, fetch_osm, render_green, and
    everything downstream of them) FAILED rather than skipped. That is precisely what README's promise
    to "skip cleanly with no course data" denies and what test_a_fresh_clone_gets_a_clean_suite exists
    to catch, and one round put six such tests in at once: three grading a pure predicate in config,
    two driving fetch_osm's census over synthetic Overpass replies, one reading render_green.render's
    own source.

    A SKIP WOULD HAVE BEEN THE CHEAPER ANSWER AND THE WRONG ONE. Not one of those six wants course
    DATA -- a pure function, a hand-built OSM reply, a function's source text -- they want the engine
    to be importable, and the engine is importable from a single course.json. So one is made, from
    examples/course.json: it is tracked, it is the file config.py's own refusal message tells a
    stranger to copy, and test_the_shipped_template_has_no_half_pair already grades it as valid.

    Underscore-prefixed, which is what makes it invisible. distribution.is_corpus_slug -- this repo's
    one spelling of "a course, or somebody's scratch?" -- reads it as scratch, so corpus_slugs() above,
    every corpus enumerator in the suite, gen_provenance, gen_disclaimers and cross_flight_check all
    skip it, and _classify below permits deleting it. Nothing measures it; it exists so that an import
    resolves.

    THE BINDING IS SESSION-WIDE, not per test, because module-scoped fixtures are set up BEFORE any
    function-scoped one -- `_bind_a_course` cannot cover an `import config` that happens during a
    module fixture's own setup, which is the same ordering that once let synth_engine's COURSE leak
    into the whole tail of the suite. `_bind_a_course` then sees this as the binding it must restore.

    A leftover directory from a crashed run is REUSED, never replaced or removed: this fixture only
    deletes a directory it created in this process, and only ever its own slug. It does REPAIR the one
    file it owns, and that was the bug: the reuse branch used to skip the copy whenever the directory
    existed, without asking whether course.json was in it. A directory with none -- exactly what a
    part-done rmtree leaves, and `ignore_errors=True` is what lets one happen quietly -- wedged the
    whole point of the fixture, because it can never write what it declines to write. Measured: plant
    courses/<slug>/stray.tmp with no course.json and a corpus-less run goes `7 failed, 145 passed,
    296 skipped`, every failure being `SystemExit: no course.json for COURSE='_no_corpus_fixture'` --
    the same seven tests this fixture exists to fix, named after its own invented slug.
    The copy is staged and os.replace'd rather than written in place, and only when the existing file is
    UNUSABLE, so a second suite bound to this same slug never sees a half-written course.json and never
    has a working one rewritten under it. See
    test_a_wedged_leftover_fresh_clone_course_is_repaired_and_not_silently_reused.

    `ignore_errors=True` STAYS on the cleanup, and it is not what it looks like. It cannot swallow the
    guard's refusal -- the wrapper raises before the real rmtree is ever called, measured in that same
    test -- so what it tolerates is a genuine hiccup removing a scratch directory this process made: a
    concurrent suite that removed it first, or a file a test left unwritable. Failing an otherwise-green
    session over the cleanup of one gitignored scratch slug is the worse of the two trades, and the
    state such a hiccup leaves behind is now repaired by the next run rather than inherited by it.

    THE `_deletion_cannot_reach_a_real_course` PARAMETER IS LOAD-BEARING AND IS NOT A TYPO. It is
    never read; it is there to order these two session fixtures. Both are session-scoped and autouse, so
    used to set them up in definition order and tear them down in reverse -- the guard came DOWN first
    and restored the real shutil.rmtree, and the rmtree below then ran outside the only guard this repo
    has. Measured by printing shutil.rmtree.__qualname__ at that line: `rmtree` without this
    parameter, `guarded_deleter.<locals>.guarded` with it. Moving this fixture to the end of the file
    does not fix it, because teardown order is the reverse of setup order either way. Declaring the
    dependency inverts both.
    What that bought, stated because it is a real refusal and not a theoretical one: if the scratch
    directory is swapped for a SYMLINK to a real course mid-session, the guard refuses it -- realpath
    lands on a corpus slug. The real rmtree notices the swap too and raises OSError("Cannot call rmtree
    on a symbolic link"), which `ignore_errors=True` swallows, leaving the symlink in courses/ and the
    session green. See test_the_fresh_clone_fixture_deletes_through_the_guard_and_not_around_it, which
    grades both halves and exists so a future reader cannot delete this parameter as unused.
    """
    template = os.path.join(ROOT, "examples", "course.json")
    d = os.path.join(ROOT, "courses", FRESH_CLONE_SLUG)
    if corpus_slugs() or not os.path.exists(template):
        yield None
        return
    prev, made = os.environ.get("COURSE"), False
    if not os.path.exists(d):
        os.makedirs(d)
        made = True
    cj = os.path.join(d, "course.json")
    if not _reads_as_a_course_record(cj):
        staged = f"{cj}.staging.{os.getpid()}"
        shutil.copyfile(template, staged)
        os.replace(staged, cj)      # atomic: a concurrent suite reads a whole file or the old one
    os.environ["COURSE"] = FRESH_CLONE_SLUG
    try:
        yield FRESH_CLONE_SLUG
    finally:
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
        if made:
            shutil.rmtree(d, ignore_errors=True)


# Every module this directory's course binding drops from sys.modules, under one rule: importing it
# reaches the COURSE env var -- by reading it itself, or through a chain of module-level sibling imports
# that ends at one that does. NOT A LIST TO EXTEND BY HAND. The rule is re-derived off the engine's own
# source by test_the_suite_wide_course_module_pop_list_is_derived_from_the_engine_and_not_hand_typed, in
# tests/test_phase1_regressions.py -- there rather than here because pytest collects no test from a
# conftest -- and that test refuses a name that does not meet it. `geo` was listed here and does not meet
# it; that test's docstring has what dropping such a name costs. Named once and iterated below, so the
# entry and the rule cannot drift apart the way they did in test_r14_coverage.py and test_r14_deadcode.py.
_COURSE_MODULES = ("config", "render_hole", "render_green",
                   "fetch_trees", "fetch_hole_elev", "fetch_dem", "fetch_dem_hd")


@pytest.fixture(autouse=True)
def _bind_a_course():
    """Bind COURSE for every test IN THIS DIRECTORY, and restore it afterwards.

    Nine test sites import render_green or config without binding COURSE, so they inherited whatever
    an earlier test left -- or, run singly, config.py's hardcoded default. That default happens to be
    built on this machine, so the crash was invisible here: on a tree without
    the-reserve-at-spanos-park, `pytest -k contours_join` died with SystemExit and looked like a real
    defect. Binding it here makes single-test and randomised-order runs behave like a full run.

    WHERE THERE IS NO CORPUS AT ALL there is nothing here to bind, and this fixture leaves whatever
    _a_course_exists_to_bind put in the environment for the whole session -- which on a fresh clone is
    the one course it makes from examples/course.json. That fixture's docstring has the argument for
    why a fresh clone gets a binding rather than a skip.

    It also RESTORES the binding afterwards, so every test starts from the same course whatever the one
    before it did. Binding without restoring left the suite order-dependent by construction: sites all
    over tests/ rebind COURSE and pop config/render_* out of sys.modules, so a test that ends bound to a
    5-tee course silently reconfigured the next one. That is not hypothetical -- running the suite
    shuffled found a real IndexError in render_hole where a synthetic 2-tee fixture inherited a 5-tee
    binding, a bug production could not reach. File order and reverse order were both green.

    HOW MANY SUCH SITES THERE ARE IS NOT RESTATED HERE. This docstring said "69 sites in this file",
    which was a second copy of a figure README publishes and a grader re-derives -- over a DIFFERENT
    population, because test_the_suite_reports_its_own_module_drop_count_correctly counts across
    `tests/*.py` and this said "this file". The two disagreed the moment a sibling test module landed,
    and the directory-wide count now moves with every one that arrives. One figure, one record: read it
    off README, where that test pins it.

    IN conftest.py, WHICH IS THE POINT. pytest applies an autouse fixture only to the module or package
    that declares it, so while this lived in test_phase1_regressions.py the isolation covered exactly
    one file -- and README went on promising it "after every test" while eight other modules in this
    directory rebound COURSE with no restoration at all. conftest.py is the only file pytest loads for
    every module here, which is the argument this file's own docstring already makes for the deletion
    guard below.

    WHAT IT DROPS IS `_COURSE_MODULES` ABOVE, AND `geo` IS NOT IN IT. It was, for every test in this
    directory, and it does not meet the rule that list is written under: geo reads no COURSE and imports
    no config, it is pure geodesy whose whole module-level body is `import math`, a lazily-filled WGS84
    constant pair and two float thresholds, so it holds nothing course-bound to isolate. Dropping it
    bought nothing and cost identity. TEN files hold `import geo` AT MODULE LEVEL and this fixture
    drops only six of them (fetch_osm, lidar_coverage, tools/check_scale and tools/verify_elevation are
    not dropped), so every teardown left those holders bound to the old module object and handed the next
    `import geo` a SECOND copy of the file. That is the mechanism behind two order-dependent failures
    already fixed in this campaign, at c209a50 and 384e462; here it was latent rather than cashed, since
    nothing yet compares geo through one of the undropped holders.

    Verified after the original change: file order, reverse order, three shuffle seeds, and all 164
    tests each in their own process.
    """
    prev = os.environ.get("COURSE")
    corpus = corpus_slugs()
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
    if corpus:
        os.environ["COURSE"] = corpus[0]
    try:
        yield
    finally:
        # back to what this test started with, and drop the course-bound modules so the next import
        # re-reads the env rather than reusing a module bound to someone else's course
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
        for m in _COURSE_MODULES:
            sys.modules.pop(m, None)



def _fold(p):
    """One path, reduced to the form two spellings of the SAME directory share.

    normcase is a no-op on POSIX and lowercases on Windows; casefold is applied unconditionally
    because this repo's own filesystem is APFS, which is case-insensitive -- courses/merion-golf-club
    and COURSES/Merion-Golf-Club are one directory here, and os.path.samefile says so. Folding on a
    case-SENSITIVE filesystem makes the guard refuse a few paths it could have allowed, which is the
    direction this guard is supposed to err in.
    """
    return os.path.normcase(p).casefold()


def _canonical_forms(path):
    """`path` reduced to every absolute, folded spelling it could denote. Empty tuple means "unreadable".

    Canonicalisation is what failed before: the predicate compared with os.path.abspath, which folds
    neither symlinks nor case, so four spellings of a real course were not recognised as being under
    courses/ -- and the old code PERMITTED whatever it did not recognise. Rather than pick one
    normalisation and hope it is the right one, the path is reduced three ways and the caller refuses
    if ANY of them lands on course data:

      * lexical (abspath): folds `//`, a trailing separator and `..` textually.
      * fully resolved (realpath): follows every symlink, including a symlinked LEAF.
      * ancestors resolved, leaf left literal: what os.unlink actually acts on when the leaf is itself
        a symlink -- unlink removes the link, not its target, so a symlink sitting INSIDE a real
        course is that course's data even though realpath points elsewhere.

    WHAT THAT COSTS, stated because it is a real refusal and not a theoretical one: the OTHER
    direction fails closed too. A symlink inside a scratch slug that points at a real course, or any
    symlink whose realpath lands in one, is REFUSED -- measured -- even though unlinking it would only
    drop the link. That is the error direction this guard is built to err in, and since the dir_fd
    waiver was narrowed it costs the whole slug: an rmtree of the scratch directory HOLDING such a
    link is refused too, because the walk's `os.unlink("peek", dir_fd=<the slug's fd>)` now resolves
    to a judgeable path and this reduction judges it as course data. Measured, not supposed. Not
    narrowed, because telling "delete the link" apart from "delete the target" is the same comparison
    this third reduction exists to get right, and that reduction is the one that catches a symlink
    planted inside a real course. A fixture that symlinks a real course into scratch will have to
    unlink it some other way; that is the trade, and it is deliberate.

    An empty tuple is returned for anything that is not a path at all (an int, an object with no
    __fspath__, a name with an embedded NUL). The caller must read that as "refuse", never as "not
    course data".

    The whole normalisation is inside the try, not just the fsdecode: a NUL-byte name decodes fine and
    then raises ValueError out of os.path.abspath, which escaped the predicate as an exception instead
    of returning False. It failed CLOSED at the wrapper either way -- an exception through
    `if not rmtree_target_is_scratch(...)` deletes nothing -- but the docstring below promises one
    early `return False` for a path that cannot be read at all, and that has to be true of every one
    of them.
    """
    try:
        p = os.fsdecode(path)          # bytes and os.PathLike both become str; an int raises TypeError
        if not p:
            return ()
        lexical = os.path.abspath(p)   # ValueError on an embedded NUL, hence the wider try
        forms = [lexical, os.path.realpath(lexical)]
        head, leaf = os.path.split(lexical)
        if leaf not in ("", os.curdir, os.pardir):
            forms.append(os.path.join(os.path.realpath(head), leaf))
        return tuple(dict.fromkeys(_fold(f) for f in forms))
    except (TypeError, ValueError):
        return ()


def _classify(p, courses):
    """What is one canonical spelling `p` to one canonical spelling of `courses`?

    `p.rstrip(os.sep)` before building the ancestor prefix, because this test asked
    `courses.startswith(p + os.sep)` and for p == "/" that builds "//", which no absolute path starts
    with -- so the ONE directory that contains every course on the machine was the one ancestor this
    guard permitted, while /Users, the home directory, the repo root and its parent were all correctly
    refused. It cannot cost a legitimate scratch path anything: `p` reaches here from
    os.path.abspath, which strips trailing separators from everything except the root itself.
    """
    if p == courses or courses.startswith(p.rstrip(os.sep) + os.sep):
        return _COURSE_DATA            # courses/ itself, or any directory that HOLDS it
    if not p.startswith(courses + os.sep):
        return _OUTSIDE
    import distribution
    slug = p[len(courses) + 1:].split(os.sep)[0]
    # distribution.is_corpus_slug is this repo's single spelling of "a course, or somebody's
    # scratch?" -- the same rule gen_provenance, gen_disclaimers and cross_flight_check ask, after a
    # local startswith("_") in a fourth place had already drifted.
    return _COURSE_DATA if distribution.is_corpus_slug(slug) else _SCRATCH


def rmtree_target_is_scratch(path, root):
    """May a test DELETE `path`? True only when no reading of it is course data.

    DENY BY DEFAULT, and that is the whole point of the rewrite. This function used to ask "can I see
    that this is a real course?" and answer `return True` for everything it could not place under
    courses/ -- an ALLOW default at the end of a chain of incomplete normalisations. Four spellings of
    a real course therefore slipped through, one of them live on this machine:

      * courses/ written COURSES/ -- a case difference, and APFS resolves it to the real directory.
      * a bytes path: str(b"/x/y") is "b'/x/y'", which abspath resolved against the cwd.
      * dir_fd= plus a relative name, resolved against the cwd instead of the descriptor. Refused by
        the wrapper below rather than here; a predicate given only the name cannot know better.
      * the repo reached through a symlinked ancestor, with one side realpath'd and the other not.

    The shape now is: canonicalise both sides every way they could be read, classify the full cross
    product, and permit only if _COURSE_DATA appears nowhere in it. There is one early `return False`
    (a path that cannot be read at all) and one final return that states what it proved.

    A FIFTH case failed open in BOTH the old predicate and this rewrite, and it is a CLASS rather than
    a spelling -- which is why counting it came up short twice: the filesystem root. The ancestor test
    built its prefix as `p + os.sep`, which is "//" when `p` is the root, and no absolute path starts
    with that. So the one directory containing every course on the machine was permitted while /Users,
    the home directory, the repo root and its parent were all refused. EVERY path whose lexical form is
    the root took that branch: `/`, `///`, `/.`, `/..`, `/./`, `/../`, and also `/any/..`, which
    contains no dot-and-separator spelling of the root at all. Re-measured against the pre-fix
    predicate, 16 of 16 spellings tried were permitted; the note that shipped with the fix recorded
    five, and `/.` and `/..` were two it missed.

    `//` belongs to that class for a different reason, stated separately because a fix reasoning only
    from canonicalisation would have missed it: os.path.abspath("//") is "//", not "/". POSIX leaves a
    doubled leading separator implementation-defined and posixpath preserves it, so `//` failed open
    because the prefix IT built was "///" -- not because it reduced to the root. See _classify.

    Two things it is NOT: it does not stop a rewrite in place (that is _courses_are_read_only's job,
    at teardown), and it does not know about deletions that never enter Python -- a subprocess
    `rm -rf`, or a C extension calling unlink(2) directly.

    Pure and root-parameterised so the truth table in test_phase1_regressions.py can attack every
    spelling above against a FAKE repo under tmp_path -- an attack that wins there destroys fake
    data. A predicate testable only by deleting something real is not testable.
    """
    target = _canonical_forms(path)
    try:
        courses = _canonical_forms(os.path.join(os.fsdecode(root), "courses"))
    except (TypeError, ValueError):
        courses = ()
    if not target or not courses:
        return False        # not a path this guard can reason about; refuse rather than guess
    readings = {_classify(p, c) for p in target for c in courses}
    return _COURSE_DATA not in readings


# shutil.rmtree walks with os.unlink(name, dir_fd=fd) / os.rmdir(name, dir_fd=fd) on this platform
# (shutil._use_fd_functions is True on macOS and Linux). Those inner names are relative to a
# descriptor, so the predicate cannot judge them AS WRITTEN -- but they are all inside a top-level
# path that was already judged, so the wrappers stand down FOR THOSE and nothing else. The stand-down
# is scoped to dir_fd deletions rather than to the whole call because rmtree hands control to caller
# code during that walk: its onerror (3.11) / onexc (3.12) callback used to inherit a blanket
# stand-down, and `shutil.rmtree(<scratch>, onerror=lambda *a: os.remove(<course.json>))` deleted the
# scorecard with no refusal. A callback that deletes by PATH is judged like any other caller now,
# which closes both callback spellings -- and any future rename of them -- without this file knowing
# the parameter list.
# Depth-counted, not a bool, because a callback may itself rmtree a scratch directory, and a bool
# would close the outer stand-down when that inner one returned. Single-threaded assumption stated
# plainly: a dir_fd deletion on ANOTHER thread while an approved rmtree is in flight is not checked.
_approved_subtree_depth = 0


def _dir_fd_dir(fd):
    """The directory `fd` names, or None where this platform cannot say.

    The stand-down above was once justified by "a descriptor cannot be turned back into a path
    portably", and then written to waive EVERY dir_fd deletion during an approved rmtree. Portably is
    the load-bearing word, and it was doing too much work: the fd walk only happens where
    shutil._use_fd_functions is True, which is macOS and Linux, and BOTH answer. macOS has
    fcntl(fd, F_GETPATH); Linux has readlink("/proc/self/fd/N"). So on every platform that can reach
    this code the descriptor resolves, and the waiver can be narrowed to the names that really are
    unjudgeable. Neither call consumes or closes the descriptor -- rmtree keeps using it afterwards.

    None is the honest answer elsewhere (a POSIX platform with neither F_GETPATH nor a mounted procfs)
    and the caller keeps the old waiver for it. Failing closed there would refuse rmtree's own walk
    and break every fixture the waiver exists for, which trades a bounded, disclosed residual for
    a suite that cannot run. See the WHAT IS NOT list.

    The buffer is 1024 bytes and not one more: fcntl.fcntl raises ValueError("fcntl string arg too
    long") above that, and 1024 is also MAXPATHLEN, which is the size F_GETPATH documents it needs.
    A larger buffer looks harmless and is not -- it made every relative name resolve to None, which
    read as "unjudgeable" and waived the deletion this helper exists to judge. Measured that way once.
    """
    try:
        import fcntl
        resolved = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\x00")
        if resolved:
            return os.fsdecode(resolved)
    except (AttributeError, OSError, ValueError, TypeError):
        pass
    try:
        return os.readlink(os.path.join(os.sep, "proc", "self", "fd", str(int(fd))))
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def _dir_fd_target(path, fd):
    """The absolute path `(path, dir_fd=fd)` actually names, or None if it cannot be resolved.

    Two spellings inside the old blanket waiver were fully judgeable, and each destroyed a fake
    course.json 1 for 1 before this existed:

      * an ABSOLUTE `path`. POSIX says the kernel IGNORES dir_fd entirely in that case, and
        _canonical_forms resolves an absolute path perfectly -- so the case was never inside the
        "cannot be resolved" rationale at all, yet it was waived.
      * a RELATIVE `path` whose descriptor resolves, which is every platform that runs the fd walk.
        This is also how `../` escapes out of the approved subtree.

    `path` is returned unchanged when it cannot even be decoded, so the predicate refuses it as the
    unreadable argument it is rather than this helper guessing.
    """
    try:
        p = os.fsdecode(path)
    except (TypeError, ValueError):
        return path
    if os.path.isabs(p):
        return p
    base = _dir_fd_dir(fd)
    return None if base is None else os.path.join(base, p)

_REFUSAL_ADVICE = (
    "  courses/ is gitignored -- no copy in history, none on a remote -- and course.json is a\n"
    "  hand-transcribed, cross-verified scorecard. Write fixtures to tmp_path, or to a slug starting\n"
    "  with '_' if config.py has to resolve them under courses/.")


def refuse_unless_deletable(call, path, kwargs, root):
    """Raise unless `path` is provably not course data. The one place a refusal is worded."""
    if kwargs.get("dir_fd") is not None:
        raise AssertionError(
            f"REFUSING {call}({path!r}, dir_fd={kwargs['dir_fd']!r}): a name relative to a file\n"
            f"  descriptor cannot be resolved to a directory portably, so this guard cannot tell\n"
            f"  whether it is course data. Nothing in this repo passes dir_fd.\n" + _REFUSAL_ADVICE)
    if not rmtree_target_is_scratch(path, root):
        raise AssertionError(
            f"REFUSING {call}({path!r}): that is course data, not scratch space.\n" + _REFUSAL_ADVICE)


def guarded_deleter(real, call, root, opens_subtree=False):
    """Wrap one deletion primitive. `opens_subtree` marks rmtree, whose inner dir_fd calls are waived.

    Returned rather than defined inline so the truth table can build a guard bound to a FAKE root and
    attack the wrapper -- the dir_fd and `path=` cases live here, not in the predicate, and a wrapper
    nothing can call without aiming at the real corpus is a wrapper nobody tests.
    """
    def guarded(path, *a, **k):
        global _approved_subtree_depth
        # The waiver is exactly as wide as its justification: a name this guard provably cannot judge,
        # inside an rmtree whose top-level path was already judged. Everything else -- a deletion by
        # path from an onerror/onexc callback running during that same walk, an ABSOLUTE name whose
        # dir_fd the kernel ignores anyway, and a relative name whose descriptor this platform can
        # resolve -- is judged.
        fd = k.get("dir_fd")
        if _approved_subtree_depth and fd is not None:
            resolved = _dir_fd_target(path, fd)
            if resolved is not None and not rmtree_target_is_scratch(resolved, root):
                raise AssertionError(
                    f"REFUSING {call}({path!r}, dir_fd={fd!r}) -> {resolved!r}: that is course data,\n"
                    f"  not scratch space. An approved rmtree's stand-down covers only a name this\n"
                    f"  guard cannot resolve; this one resolved.\n" + _REFUSAL_ADVICE)
        else:
            refuse_unless_deletable(call, path, k, root)
        if not opens_subtree:
            return real(path, *a, **k)
        _approved_subtree_depth += 1
        try:
            return real(path, *a, **k)
        finally:
            _approved_subtree_depth -= 1
    return guarded


@pytest.fixture(scope="session", autouse=True)
def _deletion_cannot_reach_a_real_course():
    """Refuse the syscall, not just report it afterwards.

    Wrapping the primitives rather than offering a helper the fixtures are asked to remember: a
    helper is the kind of guard this suite keeps finding inert, because a fixture written next month
    calls shutil.rmtree like every fixture before it and nothing notices.

    WHAT IS COVERED, stated exactly, because the claim used to be "every deletion":
      * shutil.rmtree -- every fixture that builds a scratch course under courses/ and removes it
        again. How many of those there are is NOT restated here: one figure, one record, and the
        record is _courses_are_read_only's docstring in test_phase1_regressions.py, where
        test_every_published_count_of_the_scratch_slugs_written_under_courses_is_derived re-derives
        it from the source. Two stale copies of it used to be published side by side.
      * os.remove and os.unlink -- separate function objects on POSIX, both wrapped. This is the one
        that reaches the crown jewel: a single unlink of a real course.json destroys the scorecard
        while leaving the folder looking intact.
      * os.rmdir, which also covers os.removedirs (it calls the module-global rmdir) .
      * pathlib.Path.unlink and Path.rmdir, which are os.unlink(self) and os.rmdir(self) on 3.11 --
        module-attribute lookups, so patching os covers them.

    WHAT IS NOT:
      * os.rename / os.replace / open(..., "w") over a real file. Those destroy data too, and no
        deletion guard sees them; _courses_are_read_only notices at teardown, which is a report and
        not a recovery.
      * a subprocess (`rm -rf`, `git clean`), or a C extension calling unlink(2) without going
        through the os module -- rasterio and laspy both write through Python, but nothing here
        enforces that.
      * another thread deleting while an approved rmtree is in flight.
      * a deletion that passes dir_fd= WHILE an approved shutil.rmtree is in flight AND whose
        descriptor this platform cannot resolve to a directory. That last clause is the whole of what
        is left, and it is a bounded residual rather than an impossibility. The waiver used to cover
        every dir_fd deletion during an approved rmtree, and called itself irreducible for it; two
        spellings inside it were fully judgeable and each destroyed a fake course.json 1 for 1 when
        it was attacked -- an ABSOLUTE name, whose dir_fd POSIX says the kernel ignores outright, and
        a RELATIVE name whose descriptor resolves, which covers a `../` escape out of the approved
        subtree. Both are judged now: see _dir_fd_target. What still stands down is a relative name on
        a platform answering neither fcntl(fd, F_GETPATH) (macOS) nor readlink("/proc/self/fd/N")
        (Linux) -- and those are exactly the two platforms where shutil._use_fd_functions is True, so
        on anything that runs the fd walk at all there is nothing left here. Failing closed on an
        unresolvable descriptor instead would refuse rmtree's own walk and break every fixture
        this waiver exists for. Three things bound it further: nothing in this repo passes dir_fd at
        all, outside an approved rmtree it is refused whether it resolves or not, and a callback
        deleting by PATH is checked -- that one WAS open, and closed; see guarded_deleter.

    Everything not under courses/ is delegated untouched, including pytest's own tmp_path cleanup --
    but on a PROOF that it is elsewhere (see _canonical_forms), not because the check failed to
    recognise it.
    """
    import shutil
    saved = [(shutil, "rmtree", shutil.rmtree, True), (os, "remove", os.remove, False),
             (os, "unlink", os.unlink, False), (os, "rmdir", os.rmdir, False)]
    for mod, name, real, opens in saved:
        setattr(mod, name, guarded_deleter(real, f"{mod.__name__}.{name}", ROOT, opens))
    try:
        yield
    finally:
        for mod, name, real, _ in saved:
            setattr(mod, name, real)
