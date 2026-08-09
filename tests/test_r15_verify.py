#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The independent elevation checker could not tell "verified" from "not verified".

`tools/verify_elevation.py` is the ONLY check in this project that compares a printed tee-to-green
height against a source the pipeline does not build. Two faults in what it did with a hole it could not
read, both in the same direction -- a run that verified less than it looked like it had:

  * SCOPE. The `surface_io.read_pair` call landed outside the `try/except` that had wrapped the bare
    `np.load`, so a hole whose `.npy` is missing -- or whose array no longer hashes to the digest its
    sidecar records -- raised out of `check_course` entirely. main()'s per-course `except Exception`
    then caught it, named the course, and recorded the WHOLE course as not checked: every other hole's
    independent evidence on that course discarded because one green's pair is torn. A tear is a
    per-pair on-disk condition (surface_io.commit_surface stages two files and renames them; what
    leaves one behind is a process that does not come back between the two renames), so its blast
    radius should be the pair.

  * EXIT STATUS. With one course not checked and ten agreeing, main() printed "1 not checked" and
    returned 0. Exit 0 is documented as "all figures agree", and neither a script nor the agent
    PIPELINE.md step 6 addresses can tell that from "one course was not verified at all". It is the
    same default-to-pass shape `lidar_coverage.report_or_exit` was written to close, and the remedy is
    the one that module established: a keyed acknowledgement, so a permanent and known gap can be
    waived by name while nothing waives it in silence.

NOTHING HERE NEEDS THE NETWORK: both DEM samplers are stubbed so every hole's change agrees exactly,
which leaves the torn hole as the only variable. NOTHING HERE WRITES UNDER courses/ -- the corpus is
read, never copied or modified, and the only files written are two real torn pairs under tmp_path. The
tear reaching `check_course` is injected as the exception a REAL torn pair on disk produces, captured
from `read_pair` itself, so what this grades is where that exception is caught and what it costs --
not a guess at which exception a tear raises. Corpus tests SKIP where per-course data is absent,
because a skip is visibly not a pass.
"""
import contextlib
import glob
import io
import json
import os
import re
import sys
import traceback

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _drivable():
    """Course slugs this file can drive the checker over: geometry, recorded heights, built surfaces.

    Enumerated through conftest.corpus_slugs -- this repo's one spelling of "is this a course?" -- then
    narrowed to the files `check_course` actually opens, so a half-built course cannot make a test here
    fail for having less data.
    """
    from conftest import corpus_slugs
    out = []
    for s in corpus_slugs():
        d = os.path.join(ROOT, "courses", s)
        if all(os.path.isfile(os.path.join(d, f))
               for f in ("hole_elev.json", "osm_course.json", "osm_geom.json")) \
                and glob.glob(os.path.join(d, "dem_hd", "hole*.npy")):
            out.append(s)
    return out


def _records_no_height():
    """A real course that records NO tee-to-green height, or None. poppy-ridge is this corpus's one.

    Read off `distribution.course_slugs` rather than the corpus list above, because the course this
    looks for is defined by what it does NOT have -- poppy-ridge was rebuilt in 2025 with no
    post-rebuild LiDAR, so it has no hole_elev.json and no osm_course.json either.
    """
    import distribution
    for s in distribution.course_slugs(ROOT):
        d = os.path.join(ROOT, "courses", s)
        if os.path.isfile(os.path.join(d, "course.json")) \
                and not os.path.isfile(os.path.join(d, "hole_elev.json")):
            return s
    return None


DRIVABLE = _drivable()
needs_corpus = pytest.mark.skipif(not DRIVABLE, reason="per-course data is gitignored; nothing to drive")
# bay-view is the course the suite's existing absolute-offset helper aims at, so the green/tee pairing
# the stub relies on is known to hold there; any other built course does as well.
SOURCE = ("bay-view-golf-club" if "bay-view-golf-club" in DRIVABLE
          else (DRIVABLE[0] if DRIVABLE else None))

HOLE_LINE = re.compile(r"^\s*hole\s+(\d+):\s+ours", re.M)


def _verify_elevation():
    """tools/verify_elevation.py, imported once."""
    import verify_elevation as ve
    return ve


@contextlib.contextmanager
def _dem_that_agrees(ve, cdir):
    """Stub both DEM samplers so every hole's tee-to-green change agrees EXACTLY, with no network.

    The reference is not what is under test here; a torn pair is. So the stub answers the green with
    the median of that hole's own array and the tee with that median minus the recorded change, which
    makes the checker's `indep_ft - ours_ft` zero on every hole it reaches. The only thing that can
    then move the hole count or the verdict is the tear.

    The green is always sampled before the tee for a given hole, so the green call identifies the hole
    (by its polygon's centroid) and the tee call reuses it -- the pairing
    tests/test_phase1_regressions.py's absolute-offset helper relies on.
    """
    with open(os.path.join(cdir, "hole_elev.json"), encoding="utf-8") as fh:
        rec = json.load(fh)["holes"]
    rough, ours_m, key = {}, {}, {}
    for p in sorted(glob.glob(os.path.join(cdir, "dem_hd", "hole*.json"))):
        with open(p, encoding="utf-8") as fh:
            meta = json.load(fh)
        hn = int(meta["hole"])
        if str(hn) not in rec or not meta.get("polygon") or not os.path.exists(p[:-5] + ".npy"):
            continue
        a = np.load(p[:-5] + ".npy").astype(float)
        a[~np.isfinite(a)] = np.nan
        a[np.abs(a) > 1e30] = np.nan
        rough[hn] = float(np.nanmedian(a))
        ours_m[hn] = rec[str(hn)]["change_ft"] / 3.28084
        gp = np.asarray(meta["polygon"], float)
        key[(round(float(np.mean(gp[:, 0])), 6), round(float(np.mean(gp[:, 1])), 6))] = hn
    assert rough, f"{cdir} has no hole with both a recorded height and a readable green surface"
    state = {}

    def fake_disc(lat, lon, r_m=None, px=64):
        assert "hn" in state, "a tee was sampled before any green, so the stub cannot pair them"
        hn = state["hn"]
        return rough[hn] - ours_m[hn]

    def fake_ring(ring, px=64):
        rla, rlo = ring
        hn = key.get((round(float(np.mean(rla)), 6), round(float(np.mean(rlo)), 6)))
        if hn is not None:                                     # the green
            state["hn"] = hn
            return rough[hn]
        return fake_disc(None, None)                           # the mapped tee pad of the same hole

    real = ve.dem_median_over_ring, ve.dem_median_m
    ve.dem_median_over_ring, ve.dem_median_m = fake_ring, fake_disc
    try:
        yield
    finally:
        ve.dem_median_over_ring, ve.dem_median_m = real


@contextlib.contextmanager
def _pairs_torn_at(ve, raises):
    """Make the read_pair CHECK_COURSE CALLS raise `raises[holeNN]` for those bases; behave for the rest.

    The tear is injected AT read_pair because read_pair is where the code under test meets it, and the
    exceptions handed in here are the ones a real torn pair on disk produced (see
    `_real_tear_exceptions`). Every other hole goes through the real function, so a fix that refused
    everything would not pass.

    PATCHED ON `ve.surface_io`, AND A FRESH `import surface_io` HERE IS NOT THE SAME OBJECT. That is not
    a nicety; it is the whole of why this test passed alone and failed in a full run. verify_elevation
    does `import surface_io` at module level and calls `surface_io.read_pair(...)`, so the function it
    reaches is an attribute of the module object IT bound. tests/test_r14_deadcode.py's autouse
    `_isolate_course_binding` pops every name in its `_COURSE_MODULES` out of sys.modules after each of
    its own tests, and that tuple -- documented as "every module that reads the COURSE env var at import
    time" -- lists surface_io, which reads no COURSE and imports no config. So once that file has run,
    sys.modules holds no surface_io while verify_elevation still holds the module that was there, and an
    `import surface_io` here EXECUTED surface_io.py AGAIN and patched a SECOND copy: check_course went
    on reading the real, intact pairs through the first, reported all eleven holes checked, and the
    injection graded nothing. Measured as three node ids, in this order:

        tests/test_phase1_regressions.py
            ::test_the_independent_checker_says_which_region_each_side_of_it_samples
        tests/test_r14_deadcode.py::test_site1_render_hole_output_is_byte_identical
        tests/test_r15_verify.py::test_a_torn_pair_costs_the_hole_it_is_on_and_not_the_whole_course

    -- 11 checked where 9 was required, with either of the first two dropped it passes, and the autouse
    COURSE fixture in conftest.py cannot see any of it: the leaked state is a module IDENTITY (in fact
    the ABSENCE of a sys.modules entry), not a COURSE binding, and restoring COURSE cannot make a second
    copy of surface_io become the copy verify_elevation holds.

    Reaching through `ve` cannot drift back into that: `ve.surface_io` is BY CONSTRUCTION the object
    whose read_pair check_course calls, whatever any other test has done to sys.modules.
    """
    surface_io = ve.surface_io
    real = surface_io.read_pair

    def patched(base):
        exc = raises.get(os.path.basename(base))
        if exc is not None:
            raise exc
        return real(base)

    surface_io.read_pair = patched
    try:
        yield
    finally:
        surface_io.read_pair = real


def _real_tear_exceptions(ve, tmp_path):
    """{label: exception} raised by read_pair on two REAL torn pairs written under tmp_path.

    The two spellings of one tear, both built through the producer that commits a pair:

      * the array is GONE -- the sidecar survived a rebuild its array did not.
      * the array is there, its shape still agrees, and it no longer hashes to the array_sha256 the
        sidecar records. This is the case the digest exists for and the only one that can see a pair
        whose two halves came from different runs (surface_io.commit_surface's silent tear).

    Captured rather than assumed, so this file cannot end up catching an exception class that a tear
    does not actually raise -- which is how a guard comes to cover nothing.

    Captured through `ve.surface_io`, the same module object the checker reads its pairs through, for
    the reason `_pairs_torn_at` states: a bare `import surface_io` in this file is a second copy of the
    module once anything has dropped it from sys.modules, and an exception raised by a copy the code
    under test never calls is a guess about that code dressed up as a measurement.
    """
    surface_io = ve.surface_io
    arr = np.arange(12, dtype=float).reshape(3, 4)
    meta = {"hole": 1, "H": 3, "W": 4, "bbox": [-75.0, 40.0, -74.999, 40.001],
            "polygon": [[40.0, -75.0], [40.0, -74.999], [40.001, -74.999]]}
    out = {}
    for label in ("missing array", "digest disagrees"):
        base = os.path.join(str(tmp_path), label.replace(" ", "_"))
        surface_io.commit_surface(base, arr, dict(meta))
        if label == "missing array":
            os.remove(base + ".npy")
        else:
            with open(base + ".npy", "wb") as fh:      # same shape, different values
                np.save(fh, arr + 1.0)
        try:
            surface_io.read_pair(base)
        except Exception as e:                         # noqa: BLE001 -- the point is which one it is
            out[label] = e
            continue
        raise AssertionError(
            f"surface_io.read_pair accepted a pair whose {label} -- this file's whole subject is what "
            f"the checker does with a pair read_pair refuses, so there is nothing here to grade")
    return out


def _check(ve, slug):
    """(result, printed) for one `check_course` run, or ("RAISED", type, traceback) if it raised.

    The raise is CAUGHT here rather than left to fail the test, because "did it raise?" is one of the
    two things under test and the message has to be able to say so.
    """
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = ve.check_course(slug)
    except Exception as e:                             # noqa: BLE001 -- see docstring
        return ("RAISED", type(e).__name__, f"{e}\n{traceback.format_exc()}"), buf.getvalue()
    return res, buf.getvalue()


def _samples(n=3, torn=(), unreachable=0):
    """A per-course `samples` payload of the shape check_course hands main() and _print_corpus."""
    return {"abs_diff_ft": [(0.1 * (i + 1), i + 1) for i in range(n)], "median_ft": 0.2,
            "signed_ft": [0.1] * n, "absolute_m": [0.01] * n, "unreachable": unreachable,
            "torn": list(torn)}


def _run_main(ve, results, env=None):
    """(exit code, printed) for `main() --all` over stubbed per-course results.

    `check_course` is stubbed, so this grades main()'s VERDICT -- how per-course statuses become an
    exit code -- with no course data and no network. A value that is an exception is raised instead of
    returned, which is how a torn pair used to reach main() before the scope fix.

    The slug list comes back through glob because that is where `--all` gets it; the paths need not
    exist, since main() only takes the parent directory's name off each one. Every patch is scoped to
    this call: `glob.glob` is how config.py and distribution enumerate courses, so a leaked one breaks
    every test that runs after it.
    """
    paths = [os.path.join(os.sep, "nonexistent-r15", s, "course.json") for s in results]

    def fake_check(slug):
        r = results[slug]
        print(f"{slug}  (stubbed)")
        if isinstance(r, BaseException):
            raise r
        return r

    buf = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        for k, v in (env or {}).items():
            mp.setenv(k, v)
        if ve.rasterio is None:  # the missing-dependency refusal is pinned elsewhere, not by this test
            mp.setattr(ve, "rasterio", object())
        mp.setattr(glob, "glob", lambda *a, **k: list(paths))
        mp.setattr(ve, "check_course", fake_check)
        mp.setattr(sys, "argv", ["verify_elevation.py", "--all"])
        with contextlib.redirect_stdout(buf):
            rc = ve.main()
    return rc, buf.getvalue()


# --------------------------------------------------------------------------------------------------
# (a) SCOPE -- a torn pair costs the hole it is on
# --------------------------------------------------------------------------------------------------

@needs_corpus
def test_a_torn_pair_costs_the_hole_it_is_on_and_not_the_whole_course(tmp_path):
    """One unreadable green surface took a whole course's independent verification with it.

    `surface_io.read_pair` is the right call -- it is this project's one definition of a pair worth
    measuring through, and a torn pair breaks BOTH halves of this tool's comparison at once (the
    polygon it samples the reference over comes from the sidecar; the absolute elevation it holds that
    reference against comes from the array beside it). But it was placed where an exception leaves
    `check_course` altogether, so main()'s per-course `except Exception` recorded the entire course as
    not checked. On this corpus that trades seventeen holes' evidence for one.

    A tear is per-PAIR by construction: commit_surface stages and renames two files, and what leaves
    one behind is a process that does not come back between the two renames, or one green rebuilt.
    Nothing about it says the other greens on the course are suspect.

    So the tear must cost its own hole, and be LOUD about it -- printed with the hole number, counted
    on the course's summary line, and carried out in `samples` so main() and the corpus block can see
    it. A hole quietly dropped would be worse than the whole-course refusal: the tool would still
    print a median and a worst case "over the corpus" with a hole silently missing from them.

    Both tears are the ones a REAL torn pair raises, captured off disk rather than named here.
    """
    ve = _verify_elevation()
    cdir = os.path.join(ROOT, "courses", SOURCE)
    tears = _real_tear_exceptions(ve, tmp_path)

    with _dem_that_agrees(ve, cdir):
        intact, intact_out = _check(ve, SOURCE)
    assert intact[0] in ("ok", "bad"), (
        f"the untorn {SOURCE} came out {intact[0]!r}, so this test has no baseline to measure a tear "
        f"against:\n{intact_out}")
    checked = [int(h) for h in HOLE_LINE.findall(intact_out)]
    assert len(checked) >= 3, (
        f"only {len(checked)} hole(s) were checked on {SOURCE}; this test needs at least three to "
        f"show that a tear costs one hole rather than all of them:\n{intact_out}")
    gone, faked = checked[0], checked[1]
    raises = {f"hole{gone:02d}": tears["missing array"],
              f"hole{faked:02d}": tears["digest disagrees"]}

    with _dem_that_agrees(ve, cdir), _pairs_torn_at(ve, raises):
        torn, torn_out = _check(ve, SOURCE)

    assert torn[0] != "RAISED", (
        f"a torn pair on hole {gone} raised {torn[1]} out of check_course, so main()'s per-course "
        f"except records the WHOLE course as not checked and the other {len(checked) - 2} verified "
        f"holes are discarded. Refuse the HOLE: catch the tear at the read_pair call, name the hole, "
        f"count it, and carry on:\n{torn[2]}\n{torn_out}")
    assert torn[1] == intact[1] - 2, (
        f"two of {len(checked)} holes were torn and the tool checked {torn[1]} where it checked "
        f"{intact[1]} intact -- a tear must cost exactly the hole it is on:\n{torn_out}")
    assert torn[0] == intact[0], (
        f"the verdict moved from {intact[0]!r} to {torn[0]!r} because two holes are unreadable, while "
        f"every hole it could still read agrees exactly:\n{torn_out}")
    for hn in (gone, faked):
        assert re.search(rf"hole\s+{hn}\b", torn_out), (
            f"hole {hn}'s pair is torn and the run does not name it. A hole dropped in silence leaves "
            f"the median and the worst case printed 'over the corpus' with a hole missing from "
            f"them:\n{torn_out}")
    assert sorted(h for h, _why in torn[4].get("torn", ())) == sorted((gone, faked)), (
        f"check_course did not carry the torn holes out in `samples` (got {torn[4].get('torn')!r}), "
        f"so neither main()'s exit status nor the corpus block can see that two holes went "
        f"unverified:\n{torn_out}")

    # ...and the corpus block, the only producer of the figures legal/09 and elev_phrase quote, must
    # say so too: a corpus figure computed over a hole set with holes silently missing from it is the
    # shape this project keeps having to re-derive.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ve._print_corpus({SOURCE: torn})
    corpus_out = buf.getvalue()
    assert "torn" in corpus_out.lower(), (
        f"_print_corpus published corpus figures over a hole set two holes short and did not mention "
        f"the tears:\n{corpus_out}")


# --------------------------------------------------------------------------------------------------
# (b) EXIT STATUS -- "not checked" is not agreement
# --------------------------------------------------------------------------------------------------

def test_a_course_that_verified_nothing_cannot_leave_the_run_exiting_zero():
    """The run printed "1 not checked" and exited 0, which reads as "verified" to anything but a human.

    main() returned 1 for a disagreement, 2 only when NOTHING anywhere could be verified, and 0 for
    every mixture -- so ten courses agreeing were enough to publish a clean exit status over an
    eleventh that produced no verification at all. The tool's own docstring calls exit 0 "all figures
    agree within tolerance", and PIPELINE.md step 6 tells whoever adds a course to run this; that is
    the same reader `lidar_coverage.report_or_exit` was written for, after both fetchers discarded a
    coverage verdict and exited 0 on a gap.

    The remedy is that module's, because the problem is that module's: a KEYED acknowledgement. An
    unconditional refusal would be wrong here for the reason monarch-bay makes it wrong there -- a
    course can be permanently unverifiable through nobody's fault -- so the stop names the key that
    clears it, the key is parsed with this repo's off-vocabulary (`=0`, `=false`, `=no` waive
    NOTHING), and setting it still PRINTS the finding, because a waiver that prints nothing is a
    silence.

    Both directions are pinned: an all-clear run must still exit 0, or this would pass on a tool that
    refuses everything.
    """
    ve = _verify_elevation()
    ack = getattr(ve, "UNVERIFIED_ACK", "ALLOW_UNVERIFIED_COURSES")
    ok = ("ok", 3, 0.4, 2, _samples())
    mixed = {"aaa-agrees": ok, "bbb-unverified": ("skip", 0, 0.0, None, {})}

    rc, out = _run_main(ve, dict(mixed))
    assert rc != 0, (
        f"one course produced NO verification and one agreeing course was enough to exit 0. Exit 0 is "
        f"documented as 'all figures agree'; a script, a CI step or the agent PIPELINE.md step 6 "
        f"addresses cannot tell that from this:\n{out}")
    assert rc == 2, (
        f"a course that verified nothing exited {rc}; this tool's own docstring reserves 2 for 'could "
        f"not check' and 1 for a figure that DISAGREES, and those are different findings:\n{out}")
    assert "bbb-unverified" in out and ack in out, (
        f"the refusal must name the course it is about and the key that clears it, the shape "
        f"lidar_coverage.report_or_exit uses:\n{out}")

    # the all-clear direction: this must not be satisfiable by a tool that refuses everything
    rc, out = _run_main(ve, {"aaa-agrees": ok, "bbb-agrees": ok})
    assert rc == 0, f"two courses agreed on every hole and the run still exited {rc}:\n{out}"

    # the key, over the off-vocabulary every hatch in this repo shares
    for raw, waives in (("1", True), ("true", True), ("yes", True),
                        ("0", False), ("false", False), ("no", False), ("", False)):
        rc, out = _run_main(ve, dict(mixed), env={ack: raw})
        if waives:
            assert rc == 0, f"{ack}={raw!r} did not waive the stop:\n{out}"
            assert "bbb-unverified" in out and ack in out, (
                f"{ack}={raw!r} waived the stop in SILENCE -- the finding it waives must still be "
                f"printed, or the acknowledgement hides what it acknowledges:\n{out}")
        else:
            assert rc != 0, (
                f"{ack}={raw!r} WAIVED the stop. An explicit off must waive nothing -- "
                f"bool(os.environ.get(..)) is how =0 and =false came to mean yes elsewhere in this "
                f"repo:\n{out}")

    # ...and it cannot turn a run that verified NOTHING ANYWHERE into agreement, which is why
    # lidar_coverage keeps two keys: waiving a known gap must not silence "nothing was checked".
    rc, out = _run_main(ve, {"bbb-unverified": ("skip", 0, 0.0, None, {})}, env={ack: "1"})
    assert rc != 0, (
        f"{ack}=1 turned a run in which NOT ONE course was verified into exit 0:\n{out}")

    # a course whose verification blew up entirely reaches main() as an exception, and that is the
    # loudest form of "not verified" -- it must not be quieter than the skip above.
    rc, out = _run_main(ve, {"aaa-agrees": ok,
                             "bbb-broken": RuntimeError("osm_geom.json is missing")})
    assert rc != 0, (
        f"a course whose check raised was recorded as 'not checked' and the run still exited 0:\n{out}")


@pytest.mark.skipif(_records_no_height() is None,
                    reason="every course present records tee-to-green heights; nothing to classify")
def test_a_course_with_no_recorded_heights_is_nothing_to_verify_rather_than_unverified():
    """A course that prints no elevation figure at all must not need a waiver, forever.

    poppy-ridge has no hole_elev.json -- it was rebuilt in 2025 and no post-rebuild LiDAR exists, so
    it records no height and its cards print no height line. There is therefore no printed figure for
    this tool to have been unable to verify, and lumping that in with "this course's figures went
    unverified" would make `--all` permanently non-zero on a state that is not a fault. That is the
    wedge lidar_coverage's keyed refusal exists to avoid, one step earlier: better to tell the two
    cases apart than to hand the reader a waiver for a non-finding.

    The status is taken from the code, not asserted as a spelling: what matters is that it is not the
    one main() stops on, and that a run holding one of these beside a course that agrees exits 0.
    """
    ve = _verify_elevation()
    slug = _records_no_height()
    res, out = _check(ve, slug)
    assert res[0] != "RAISED", f"check_course raised on {slug}, which has no hole_elev.json:\n{res[2]}"
    assert "nothing to verify" in out, (
        f"a course with no recorded heights must say so plainly:\n{out}")
    assert res[0] != "skip", (
        f"{slug} records no tee-to-green height at all and is reported with the same status as a "
        f"course whose recorded figures could not be verified. Those are different findings: the "
        f"first prints no height on any card, the second prints heights nothing has checked.")

    rc, out = _run_main(ve, {"aaa-agrees": ("ok", 3, 0.4, 2, _samples()),
                             "ccc-noelev": (res[0], 0, 0.0, None, {})})
    assert rc == 0, (
        f"a course with no recorded heights beside a course that agrees exited {rc}. Nothing was left "
        f"unverified -- there is no figure there to verify -- so this must not need a waiver every "
        f"time:\n{out}")


def test_a_torn_pair_reaches_the_exit_status_and_no_waiver_silences_it():
    """A tear scoped back to one hole must not become invisible in the exit status.

    Refusing the hole instead of the course is only safe while the hole is still counted somewhere a
    caller can see, so a run holding a torn pair exits non-zero on that alone -- the course's other
    holes may all agree, and under the old whole-course refusal the course was at least visibly not
    checked.

    NOT waivable, and deliberately not sharing the unverified-course key. lidar_coverage keeps its two
    keys apart so that waiving one course's permanent, unavoidable gaps can never silence "nothing was
    checked at all"; the same argument applies here with more force, because a torn pair is not a
    permanent fact about the world. It is a fault in OUR OWN data -- the array and the sidecar came
    from different runs -- and surface_io.main's stance on exactly that is to REFUSE and say rebuild,
    because a digest written over a torn pair certifies the tear. So there is no key, the remedy is a
    rebuild of that green, and the message says so.
    """
    ve = _verify_elevation()
    ack = getattr(ve, "UNVERIFIED_ACK", "ALLOW_UNVERIFIED_COURSES")
    torn = ("ok", 2, 0.4, 2, _samples(n=2, torn=[(7, "hole07: this pair is already torn")]))
    results = {"aaa-agrees": ("ok", 3, 0.4, 2, _samples()), "bbb-torn": torn}

    rc, out = _run_main(ve, dict(results))
    assert rc != 0, (
        f"a green surface pair is torn, so that hole's printed height was verified by nothing, and "
        f"the run exited 0:\n{out}")
    assert "bbb-torn" in out and re.search(r"\b7\b", out), (
        f"the run must name the course and the hole whose pair is torn -- the whole-course refusal it "
        f"replaces named neither:\n{out}")
    assert "rebuild" in out.lower(), (
        f"the refusal must say what clears it. A torn pair is repaired by rebuilding that green's "
        f"surface, and it is the one finding here with no acknowledgement key:\n{out}")

    rc_acked, out_acked = _run_main(ve, dict(results), env={ack: "1"})
    assert rc_acked != 0, (
        f"{ack}=1 silenced a torn pair. That key acknowledges a course this tool could not verify; a "
        f"torn pair is a fault in the data being checked, and surface_io refuses to certify one "
        f"rather than offering a waiver for it:\n{out_acked}")
