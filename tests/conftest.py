#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The guard that stands between an editing slip and the only copy of the corpus.

It lives in conftest.py because that is the ONLY file pytest loads for every test module in this
directory. It used to be a session-autouse fixture inside test_phase1_regressions.py, whose own
comment called itself "one choke point ... every deletion in this suite" -- which was not true of
anything but that one file. `pytest tests/<any new file>` ran completely unguarded, and a second test
module is the natural thing for the next person to add.

What courses/ is, and why deletion is the interesting failure: a course folder holds ~300 MB of
LiDAR, the derived 0.4 m green surfaces, and course.json -- a scorecard a human transcribed from
published cards and cross-verified against club sources. The directory is gitignored by design, so
there is no copy in history, none on a remote, none anywhere. Only laz/ can be fetched again.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_COURSE_DATA, _SCRATCH, _OUTSIDE = "course data", "scratch", "outside courses/"


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
    and break the nine fixtures the waiver exists for, which trades a bounded, disclosed residual for
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
    calls shutil.rmtree like the nine before it and nothing notices.

    WHAT IS COVERED, stated exactly, because the claim used to be "every deletion":
      * shutil.rmtree -- the nine fixtures that build a directory under courses/ and remove it again.
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
        unresolvable descriptor instead would refuse rmtree's own walk and break the nine fixtures
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
