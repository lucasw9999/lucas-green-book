#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Do the four artifact gates in tools/ gate what they claim? Three of them did not.

Every test here was written against the defect first and watched fail. What was reproduced, in the
words of the runs that reproduced it:

  * AN UNRECOGNISED ARGUMENT REWROTE THE LEGAL RECORD AND EXITED 0. tools/gen_provenance.py and
    tools/gen_disclaimers.py both decided their mode with `if "--check" in sys.argv:` and fell through
    to the branch that OVERWRITES legal/03_PROVENANCE_BY_COURSE.md and legal/05_DISCLAIMER_TEXT.md
    otherwise. Under the open() interceptor below, `-check`, `--chek`, `--verify`, `-n`, `--check=1`
    and a bare `check` each reached the WRITE branch on BOTH tools, printed "wrote legal/0X_....md",
    and returned 0 -- twelve runs, twelve rewrites of a legal record by something that reads as a
    verification request. legal/03 embeds "Verify with: python3 tools/gen_provenance.py --check"
    inside the file it generates, so a typo in that very command self-certified.
    This is the defect 2b0e248 fixed in tools/export_pdf.py, where the same
    `check = "--check" in sys.argv` let `-check` re-export all 15 PDFs and exit 0. The remedy shape is
    that commit's: refuse an option the tool does not understand, and exit 2.

  * THE OSM FETCH-BOX GATE MEASURED THE DECLARED BOX, NOT THE FETCHED ONE. tools/check_osm_bbox.py
    read `config.COURSE["osm_bbox"]` -- a number in course.json -- and reported on it in the words
    "every hole's 68 m drawing corridor is inside the FETCHED box". Reproduced on a copy under /tmp:
    a narrowed osm_bbox over valley-hi's real cache gave "15 hole(s) draw from outside the fetched
    box (worst 164 m short at hole 17)", rc 1; widening ONLY course.json's osm_bbox -- osm_geom.json
    byte-identical, md5 f56a589a07c024aadcab1d0f786df357 before and after -- gave "every hole's 68 m
    drawing corridor is inside the fetched box", rc 0, over the same narrow cache. The tool's own
    printed remedy is "WIDEN osm_bbox AND RE-FETCH" and the re-fetch half was unverifiable, on a
    course where an aborted fetch has permanently stripped irreplaceable geometry before.
    No cache on disk records the box it was queried with: over all 11 built caches the only
    non-`elements` keys are Overpass's own version/generator/osm3s.

  * THAT SAME GATE EXITED 0 WITH ELEVEN OF TWELVE COURSES UNEXAMINED. `return 0 if oks else 2` under
    an `except Exception -> "skip"` and an `except SystemExit -> "skip"`, so ONE passing course spoke
    for the whole corpus, and `--al` (a typo for `--all`) with COURSE set checked ONE course and
    exited 0. Measured live: `--all` reported "11 course(s) fully covered ... 1 not checked" and
    returned 0, and `COURSE=merion-golf-club python3 tools/check_osm_bbox.py --al` reported
    "1 course(s) fully covered" and returned 0.

  * THE RULE 4.3 GATE PUBLISHED A WORST READING THAT IS NOT THE WORST. tools/check_scale.py said the
    earth-model migration "shifts the worst gated reading from 0.3601 to 0.3600 in : 5 yd". Both ends
    are wrong and so is the direction: re-derived below off the built markup over all 198 gated
    greens, the worst is 0.360121 (bay-view hole 3) -> 0.3601, and under the retired sphere it was
    0.359805 -> 0.3598. legal/06 and legal/11 both say 0.3601; the tool's own comment was the
    outlier, and neither figure appeared in any test file.

  * AND IT ANSWERED 0 FOR A TREE WITH NO BOOK IN IT, while the same file 118 lines below argues that
    an empty measurement "is not a pass".

WHAT IS DELIBERATELY NOT RUN HERE: neither legal-record generator is ever called without `--check`.
courses/ is the only copy of the corpus and legal/03 and legal/05 are tracked records whose generator
overwrites them in place; the write branch is reached by a person who typed the command, not by a test
run. What the tests below pin instead is the DECISION -- `unknown_args` is a pure function and its
whole truth table is graded, including that the known flags are accepted, so the writer cannot become
unreachable without this file going red.
"""
import builtins
import glob
import io
import json
import math
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


# ==================================================================================================
# D-4 -- an unrecognised argument must never reach a branch that rewrites a legal record
# ==================================================================================================

# The two generators whose non---check branch OVERWRITES a tracked legal document, and the file each
# one would overwrite. Named here so a third generator cannot arrive unpinned: the assertion at the
# bottom of test_every_argv_gate_in_tools_refuses_what_it_does_not_understand discovers every tool in
# tools/ that spells the rule and requires it to be named here or graded explicitly below.
_LEGAL_WRITERS = {"gen_provenance": "legal/03_PROVENANCE_BY_COURSE.md",
                  "gen_disclaimers": "legal/05_DISCLAIMER_TEXT.md"}

# Arguments a person plausibly types meaning "check". Every one of them rewrote both legal records.
_MEANT_CHECK = ("-check", "--chek", "--verify", "-n", "--check=1", "check", "--dry-run", "--CHECK")


class _WriteAttempted(io.StringIO):
    """A stand-in for a file opened for WRITING, so the write lands in memory and not in legal/.

    A StringIO rather than a raising stub on purpose: raising would abort main() at the first write and
    make "no write happened" indistinguishable from "the tool died on the way to the write". Letting
    the write succeed into memory lets the test assert BOTH halves of the defect at once -- that a
    write was attempted at all, AND that the tool then returned 0 as though it had verified something.
    """


def _open_spy():
    """(spy, writes) -- a drop-in for builtins.open that records write-mode opens and never performs one.

    Reads are delegated untouched: both generators read the whole built corpus and the legal file they
    compare against, and a spy that broke reads would test nothing.
    """
    real = builtins.open
    writes = []

    def spy(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wxa+"):
            writes.append((str(file), str(mode)))
            return _WriteAttempted()
        return real(file, mode, *a, **k)
    return spy, writes


def _run_under_open_spy(mod, argv):
    """(rc, printed, writes) for mod.main(argv) with every write-mode open intercepted.

    argv is passed as an ARGUMENT rather than through sys.argv. Under pytest sys.argv holds pytest's
    own arguments, so a tool that reads it directly cannot be driven from a test without monkeypatching
    a global -- which is also how `--al` came to check one course quietly. main(argv) is the seam.

    builtins.open is restored in a `finally` rather than through monkeypatch, because everything after
    this call -- pytest's own reporting included -- needs the real one back before the test returns.
    """
    import contextlib
    spy, writes = _open_spy()
    real = builtins.open
    buf = io.StringIO()
    builtins.open = spy
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(list(argv))
    finally:
        builtins.open = real
    return rc, buf.getvalue(), writes


@pytest.mark.parametrize("tool", sorted(_LEGAL_WRITERS))
@pytest.mark.parametrize("flag", _MEANT_CHECK)
def test_an_unrecognised_argument_never_rewrites_a_legal_record(tool, flag):
    """One character wrong and the legal record was regenerated, in silence, with exit 0.

    The discriminator is the open() interceptor: no write-mode open may happen at all, and the return
    code must be non-zero. Both were violated on both tools by all eight spellings below before this
    was fixed -- the run printed "wrote legal/03_PROVENANCE_BY_COURSE.md (156 lines, 12 courses)" and
    returned 0.

    ANTI-VACUITY, and it is the part that makes this test worth having: the refusal must NAME the
    argument. Without that, a tool that happens to exit 2 for an unrelated reason -- gen_provenance
    returns 2 on a tree with no course data, which is every fresh clone -- would satisfy the two
    assertions above while the defect stood. So the argv check has to be the FIRST thing main() does,
    before it reads a single file, and the message has to prove that is where the run stopped.
    """
    mod = __import__(tool)
    rc, printed, writes = _run_under_open_spy(mod, [flag])
    assert writes == [], (
        f"tools/{tool}.py opened {[w[0] for w in writes]} for writing when handed {flag!r}. "
        f"{_LEGAL_WRITERS[tool]} is a tracked legal record and this argument is not one this tool "
        f"understands -- an option it does not recognise must never select the destructive branch.")
    assert rc != 0, (
        f"tools/{tool}.py returned {rc} for {flag!r}. Exit 0 from a gate reads as 'verified', and "
        f"nothing was verified.\n{printed}")
    assert flag in printed, (
        f"tools/{tool}.py refused {flag!r} without naming it, so this test cannot tell a refusal OF "
        f"THE ARGUMENT from a refusal for some unrelated reason (an empty tree answers 2 as well). "
        f"The argv check must be main()'s first act and must say what it did not understand.\n"
        f"{printed}")


@pytest.mark.parametrize("tool", sorted(_LEGAL_WRITERS))
def test_the_check_flag_still_reaches_the_comparison_and_writes_nothing(tool):
    """The other direction: refusing typos must not have refused the real flag too.

    `--check` must still reach the staleness comparison, and must still write nothing -- the whole
    point of the flag. Graded on the verdict the check branch prints, which is the only thing in either
    tool that can say "up to date", "STALE" or "nothing to check against".
    """
    mod = __import__(tool)
    rc, printed, writes = _run_under_open_spy(mod, ["--check"])
    assert writes == [], f"tools/{tool}.py --check wrote {[w[0] for w in writes]}"
    assert re.search(r"up to date|STALE|is stale|nothing to check", printed), (
        f"tools/{tool}.py --check printed no staleness verdict, so the check branch was not reached:\n"
        f"{printed}")
    assert rc in (0, 1, 2), f"tools/{tool}.py --check returned {rc}"


# --------------------------------------------------------------------------------------------------
# One truth table, discovered across every tool that spells the rule
# --------------------------------------------------------------------------------------------------

def _argv_gates():
    """{module name: module} for every tool in tools/ exposing KNOWN_FLAGS and unknown_args.

    DISCOVERED, not listed. This is lidar_coverage._env_on's precedent applied to the argv rule: the
    off-vocabulary is spelled in seven places in this repo and stays safe because ONE table drives all
    of them, re-derived by a test that finds every module defining it rather than naming them. A copy
    of an argv rule that arrives without the near-miss table graded against it is exactly how `-check`
    survived in export_pdf.py for 96 commits.
    """
    import importlib
    found = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))):
        name = os.path.splitext(os.path.basename(p))[0]
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        if "def unknown_args(" not in src:
            continue
        mod = importlib.import_module(name)
        assert hasattr(mod, "KNOWN_FLAGS"), (
            f"tools/{name}.py defines unknown_args but no KNOWN_FLAGS, so the set it judges against "
            f"is not readable from outside and cannot be graded here")
        found[name] = mod
    return found


def _near_misses(flag):
    """Every spelling of `flag` that is not `flag`, derived from the flag itself.

    Derived rather than typed, so adding a flag adds its own near misses. `-check` (one dash), `check`
    (no dashes), `--check=1` (an inline value), `--CHECK` (case) and `--chec` (a truncation) are the
    five shapes that reached the destructive branch of a real tool in this repo.
    """
    bare = flag.lstrip("-")
    return ["-" + bare, bare, flag + "=1", flag.upper(), flag[:-1], flag + "s", flag + " ", " " + flag]


def test_every_argv_gate_in_tools_refuses_what_it_does_not_understand():
    """The rule, graded once for every tool that spells it: exact membership, and nothing else.

    Three tools carry it (`tools/check_osm_bbox.py`, `tools/gen_disclaimers.py`,
    `tools/gen_provenance.py`) and `tools/export_pdf.py` carries an inline variant that also takes
    course slugs, so it is not judged by this table. What this asserts:

      * every flag the tool declares KNOWN is accepted, and the empty argv is accepted -- without
        this, "refuse everything" would pass, and refusing `--check` would make the check branch
        unreachable while refusing nothing would make the WRITE branch the default.
      * every near-miss spelling of every known flag is refused.
      * a bare positional word is refused. Neither legal generator takes an argument at all.
    """
    gates = _argv_gates()
    assert set(gates) >= set(_LEGAL_WRITERS) | {"check_osm_bbox"}, (
        f"a tool that decides its mode from argv is not spelling the shared rule: found {sorted(gates)}")
    for name, mod in sorted(gates.items()):
        known = list(mod.KNOWN_FLAGS)
        assert known, f"tools/{name}.py declares no known flag"
        assert mod.unknown_args([]) == [], f"tools/{name}.py refuses an empty command line"
        assert mod.unknown_args(known) == [], (
            f"tools/{name}.py refuses its own KNOWN_FLAGS {known} -- the branch each one selects is "
            f"now unreachable")
        for flag in known:
            for miss in _near_misses(flag):
                assert mod.unknown_args([miss]) == [miss], (
                    f"tools/{name}.py accepted {miss!r} as {flag!r}. Membership must be exact: this "
                    f"is the one-character typo that rewrote a legal record and re-exported 15 PDFs.")
        for stray in ("extra", "-", "--", "-x", "--all-of-them"):
            if stray in known:
                continue
            assert mod.unknown_args([stray]) == [stray], f"tools/{name}.py accepted {stray!r}"
        # and the tool has to be one this file knows the stakes of
        assert name in _LEGAL_WRITERS or name == "check_osm_bbox", (
            f"tools/{name}.py spells the argv rule and is not covered by this file -- add it to "
            f"_LEGAL_WRITERS (its non-flag branch destroys something) or grade it explicitly")


# ==================================================================================================
# D-2 -- the fetch-box gate must measure the box the cache was FETCHED with
# ==================================================================================================

def _cache(elements=(), query_bbox=None):
    """An Overpass reply shaped like the ones on disk: version/generator/osm3s plus elements."""
    c = {"version": 0.6, "generator": "Overpass API 0.7.62",
         "osm3s": {"timestamp_osm_base": "2026-08-01T00:00:00Z", "copyright": "..."},
         "elements": list(elements)}
    if query_bbox is not None:
        import check_osm_bbox
        c[check_osm_bbox.QUERY_BBOX_KEY] = list(query_bbox)
    return c


def _line(hole, pts):
    """A hole centreline in geo.hole_lines' shape: {"geometry": [{"lat":..,"lon":..}, ...]}."""
    return {"geometry": [{"lat": la, "lon": lo} for la, lo in pts]}


# A box about 300 m x 300 m at 37.8N, and a wider one around it. Small enough that a corridor of 68 m
# is a large fraction of it, so the arithmetic below is not sensitive to the earth model.
_NARROW = [37.8000, -122.4000, 37.8027, -122.4000 + 0.0034]
_WIDE = [_NARROW[0] - 0.01, _NARROW[1] - 0.01, _NARROW[2] + 0.01, _NARROW[3] + 0.01]
_CORRIDOR_M = 68.0


def test_widening_the_declared_box_cannot_turn_the_gate_green_over_the_same_cache():
    """THE defect: the verdict moved when course.json moved and the cache did not.

    Reproduced end to end on a /tmp copy of valley-hi -- 15 holes "short", rc 1; widen ONLY
    course.json's osm_bbox and the same byte-identical cache reads "every hole's 68 m drawing corridor
    is inside the fetched box", rc 0. The tool's printed remedy is "WIDEN osm_bbox AND RE-FETCH", and
    the widening half was the half that changed its verdict.

    Graded at the seam: evaluate() is handed the cache, the DECLARED box and the lines, and when the
    cache records the box it was queried with, that recorded box is the one measured. A declared box
    that has been widened past it is a finding of its own -- the record and the data disagree -- and
    not a pass.
    """
    import check_osm_bbox as cb
    lines = {1: _line(1, [(37.8010, -122.3990), (37.8010, -122.3970)])}   # inside _NARROW, well clear

    # a cache honestly fetched with the narrow box, and a course.json that agrees
    st, bad, measured, why = cb.evaluate(_cache(query_bbox=_NARROW), _NARROW, lines, _CORRIDOR_M)
    assert st == cb.SHORT and bad, (
        "a 68 m corridor around a centreline 40 m from the edge of a 300 m box IS short -- the "
        f"fixture must bind before the interesting case is asked: got {st} {bad}")
    assert measured == _NARROW and why == "", (why, measured)

    # now widen the DECLARATION only. The cache is untouched; nothing was re-fetched.
    st2, bad2, measured2, _why2 = cb.evaluate(_cache(query_bbox=_NARROW), _WIDE, lines, _CORRIDOR_M)
    assert st2 == cb.DRIFT, (
        f"course.json declares {_WIDE} and the cache records being fetched with {_NARROW}, so the "
        f"declared box was widened without a re-fetch -- the exact state this gate's own remedy "
        f"produces halfway through. It reported {st2!r}.")
    assert measured2 == _NARROW, (
        f"the shortfalls must be measured against the box the cache was FETCHED with ({_NARROW}), "
        f"not the one course.json declares: measured {measured2}")
    assert bad2, "and the corridor is still outside the box that was really queried"


def test_a_cache_that_does_not_record_its_query_box_is_not_a_verified_pass():
    """No cache on disk records the box it was queried with, and silence there must not read as a pass.

    Confirmed over all 11 built caches: the only non-`elements` keys anywhere are Overpass's own
    version, generator and osm3s. Until fetch_osm.py records its query box there is nothing on disk
    that can answer "was this cache fetched with the box course.json now declares?", and this gate
    must say so rather than measure the declaration and print the word "fetched".

    It still MEASURES -- a corridor outside the declared box is a real finding whichever box was
    queried -- so `unverified` is a second, independent answer beside the status, and main() keys them
    separately. That is lidar_coverage.report_or_exit's two-key rule: a waiver for "these gaps are
    real" must not silence "nothing was checked".
    """
    import check_osm_bbox as cb
    inside = {1: _line(1, [(37.8013, -122.3980), (37.8014, -122.3979)])}
    st, bad, measured, why = cb.evaluate(_cache(), _WIDE, inside, _CORRIDOR_M)
    assert not bad, f"the fixture centreline must be well inside the wide box: {bad}"
    assert why, ("a cache with no recorded query box must say that the FETCH box is unverified; "
                 f"evaluate() returned {why!r}")
    assert cb.QUERY_BBOX_KEY in why, (
        f"the message must name the key fetch_osm.py has to write, or nobody can act on it: {why!r}")
    assert st == cb.OK and measured == _WIDE, (st, measured)

    # and the unverified answer must not swallow the specific one
    short = {1: _line(1, [(37.8010, -122.3990), (37.8010, -122.3970)])}
    st2, bad2, _m2, why2 = cb.evaluate(_cache(), _NARROW, short, _CORRIDOR_M)
    assert st2 == cb.SHORT and bad2 and why2, (
        "a course whose declared box is short AND whose cache records no query box has two findings, "
        f"and both have to survive: got {st2!r} bad={bad2} why={why2!r}")


def test_the_recorded_query_box_is_read_in_course_json_order_and_nothing_else_is_accepted():
    """What fetch_osm.py must write, pinned so the two halves cannot be built to different shapes.

    `[south, west, north, east]` -- course.json's own order, which is also Overpass's `(S,W,N,E)`
    bbox filter order and the order fetch_osm already unpacks it in (`S, W, N, E =
    config.COURSE["osm_bbox"]`). Anything else must be REFUSED rather than guessed at: a box read in
    the wrong order is worse than no box, because it would be measured against with confidence.
    """
    import check_osm_bbox as cb
    assert cb.recorded_query_bbox(_cache(query_bbox=_NARROW)) == _NARROW
    assert cb.recorded_query_bbox(_cache()) is None
    for junk in ([1, 2, 3], [1, 2, 3, 4, 5], "37.8,-122.4,37.81,-122.39", {}, [], None,
                 [1, 2, 3, "x"], [None, 1, 2, 3]):
        c = _cache()
        c[cb.QUERY_BBOX_KEY] = junk
        assert cb.recorded_query_bbox(c) is None, (
            f"a malformed recorded box must read as ABSENT, never be measured against: {junk!r}")


def test_no_built_cache_records_a_query_box_that_disagrees_with_its_course_json():
    """The live half, over whatever is on disk: recorded is either absent or EQUAL to the declaration.

    True today because every cache is silent, and true after fetch_osm.py starts recording because a
    re-fetch writes the box it used. It goes red in exactly one state -- a declared box widened
    without the re-fetch the gate's own remedy asks for -- which is the state this whole defect is
    about, and which nothing on disk could previously express.
    """
    import check_osm_bbox as cb
    checked = 0
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        geom = os.path.join(os.path.dirname(cj), "osm_geom.json")
        if not os.path.isfile(geom):
            continue
        with open(cj, encoding="utf-8") as fh:
            declared = json.load(fh).get("osm_bbox")
        with open(geom, encoding="utf-8") as fh:
            recorded = cb.recorded_query_bbox(json.load(fh))
        checked += 1
        if recorded is None or declared is None:
            continue
        assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(declared, recorded)), (
            f"{slug}: course.json declares osm_bbox {declared} and osm_geom.json records being "
            f"fetched with {recorded}. The declaration was widened without the re-fetch, so every "
            f"feature beside the widened strip is still missing from the cache and the cards drawn "
            f"from it. Re-run fetch_osm.py for this course.")
    if not checked:
        pytest.skip("no OSM cache on disk; courses/ is gitignored")


# ==================================================================================================
# D-3 -- a course that could not be checked must be distinguishable from one that passed
# ==================================================================================================

def _stub_corpus(monkeypatch, verdicts):
    """Point check_osm_bbox's enumerator at `verdicts`' keys and its per-course check at their values.

    A value that is an exception instance is RAISED, which is how the two silent skips are reproduced:
    `except Exception -> "skip"` in main() and `except SystemExit -> "skip"` inside check_course.
    """
    import check_osm_bbox as cb
    monkeypatch.setattr(cb.distribution, "course_slugs", lambda root=None: sorted(verdicts))

    def fake(slug):
        v = verdicts[slug]
        if isinstance(v, BaseException):
            raise v
        return v
    monkeypatch.setattr(cb, "check_course", fake)
    for key in (cb.NO_CACHE_ACK, cb.UNRECORDED_ACK):
        monkeypatch.delenv(key, raising=False)
    return cb


def test_one_examined_course_cannot_speak_for_the_eleven_that_were_not(monkeypatch, capsys):
    """`return 0 if oks else 2`: one passing course out of twelve published a clean gate.

    Live before the fix, `--all` printed "11 course(s) fully covered, 0 with a corridor outside the
    box, 1 not checked" and returned 0 -- and the same arithmetic returns 0 for 1 covered and 11
    unexamined. Reproduced here by forcing the per-course function to raise on eleven of twelve.
    """
    cb = _stub_corpus(monkeypatch, dict(
        {"ok-course": ("ok", [], "")},
        **{f"broken-{i}": RuntimeError("osm_geom.json is not JSON") for i in range(11)}))
    rc = cb.main(["--all"])
    out = capsys.readouterr().out
    assert rc != 0, (
        f"1 course examined and 11 refused returned {rc}. Exit 0 from this gate is documented as "
        f"'every corridor is inside the box', which is a claim about the corpus.\n{out}")
    assert "11" in out, f"the count of courses that were not checked has to be printed:\n{out}"


def test_a_course_whose_hole_lines_are_refused_is_not_waived_by_any_key(monkeypatch, capsys):
    """geo.hole_lines' HARD REFUSALS were downgraded to "not checked" and then to exit 0.

    A refusal out of hole_lines is our own cache disagreeing with itself -- a hole with no resolvable
    centreline -- so it is a defect in the data being CHECKED, not a fact about the world. It gets no
    acknowledgement key, for the reason tools/verify_elevation.py gives a torn surface pair none: a
    run that certifies what it could not read is worse than one that reports it.
    """
    cb = _stub_corpus(monkeypatch, {"good": ("ok", [], ""),
                                    "refuses": SystemExit("hole 7 has no centreline")})
    assert cb.main(["--all"]) != 0, "a refused course must not exit 0"
    base = capsys.readouterr().out
    assert "refuses" in base, base
    for key in (cb.NO_CACHE_ACK, cb.UNRECORDED_ACK):
        monkeypatch.setenv(key, "1")
        assert cb.main(["--all"]) != 0, (
            f"{key} waived a refusal it has no business waiving -- it names a course whose OSM cache "
            f"is absent, or one whose fetch box is unrecorded, and neither is 'this cache could not "
            f"be read'")
        capsys.readouterr()
        monkeypatch.delenv(key)


def test_a_course_with_no_osm_cache_stops_the_run_until_it_is_named(monkeypatch, capsys):
    """poppy-ridge has no osm_bbox and no cache, and that used to vanish into exit 0.

    Keyed rather than unconditional, which is lidar_coverage.report_or_exit's argument: monarch-bay's
    holes 1, 17 and 18 are permanently over the bay and an unconditional refusal would wedge that
    course's re-fetch forever. poppy-ridge is the same shape here -- built in yardage mode with no OSM
    geometry -- so `--all` needs a way through that names it rather than one that hides it.
    """
    cb = _stub_corpus(monkeypatch, {"good": ("ok", [], ""), "no-cache": ("nocache", [], "")})
    assert cb.main(["--all"]) != 0, "an unexamined course must not read as a covered one"
    out = capsys.readouterr().out
    assert cb.NO_CACHE_ACK in out, f"the refusal must name the key that clears it:\n{out}"
    monkeypatch.setenv(cb.NO_CACHE_ACK, "1")
    assert cb.main(["--all"]) == 0, "and once named by the reader it must let the run finish"
    assert "WARNING" in capsys.readouterr().out, "a waived finding still has to be said out loud"


def test_an_unverifiable_fetch_box_and_an_unexamined_course_need_their_own_keys(monkeypatch, capsys):
    """Two questions, two keys, neither waiving the other -- fetch_osm._check_response' own lesson.

    "This course has no OSM cache" and "no cache anywhere records the box it was fetched with" are
    different facts about different failures, and a single flag over both is what
    lidar_coverage.report_or_exit records the cost of.
    """
    cb = _stub_corpus(monkeypatch, {"unrecorded": ("ok", [], "osm_geom.json records no query_bbox"),
                                    "no-cache": ("nocache", [], "")})
    assert cb.main(["--all"]) != 0
    capsys.readouterr()
    monkeypatch.setenv(cb.NO_CACHE_ACK, "1")
    assert cb.main(["--all"]) != 0, (
        f"{cb.NO_CACHE_ACK} silenced an unverifiable fetch box, which is a different question")
    out = capsys.readouterr().out
    assert cb.UNRECORDED_ACK in out, out
    monkeypatch.setenv(cb.UNRECORDED_ACK, "1")
    assert cb.main(["--all"]) == 0, "both named, both cleared"


def test_a_typo_for_all_is_refused_rather_than_narrowing_the_run_to_one_course(monkeypatch, capsys):
    """`--al` with COURSE set checked ONE course of twelve and exited 0, and said nothing about it.

    Measured live: `COURSE=merion-golf-club python3 tools/check_osm_bbox.py --al` printed
    "1 course(s) fully covered, 0 with a corridor outside the box, 0 not checked" and returned 0. The
    unrecognised argument was simply discarded, and a corpus-wide gate silently became a one-course
    one. Same remedy as D-4: refuse it, name it.
    """
    cb = _stub_corpus(monkeypatch, {"only": ("ok", [], "")})
    monkeypatch.setenv("COURSE", "only")
    rc = cb.main(["--al"])
    out = capsys.readouterr().out
    assert rc != 0, f"`--al` returned {rc} having checked one course of the corpus:\n{out}"
    assert "--al" in out, f"the refusal must name the argument:\n{out}"
    assert cb.main(["--all"]) == 0, "and the real flag must still work"


def test_a_verdict_this_gate_cannot_place_stops_the_run_rather_than_being_dropped(monkeypatch, capsys):
    """The shape that let `skip` reach exit 0: a verdict nothing classifies.

    Refused rather than asserted, because `python3 -O` strips an assert and a partition that stops being
    exhaustive under an optimisation flag is a waiver nobody granted. tools/export_pdf.py's own
    freshness gate carries the same requirement in the other direction -- every tag it can return has to
    be classified or the test fails rather than filing an unknown one under "cannot know".
    """
    cb = _stub_corpus(monkeypatch, {"good": ("ok", [], ""), "odd": ("something-new", [], "")})
    assert cb.main(["--all"]) == 2, "an unplaced verdict must not be dropped"
    assert "does not classify" in capsys.readouterr().out


def test_the_short_corridor_verdict_is_still_the_specific_finding(monkeypatch, capsys):
    """Exit 1 is reserved for the actionable measurement: a corridor drawn from outside the box.

    Non-zero is not enough. This gate's documented contract distinguishes "widen the box and re-fetch"
    (1) from "this could not be checked" (2), which is tools/verify_elevation.py's split and
    lidar_coverage.main's, and a reader scripting on the exit code needs the difference.
    """
    cb = _stub_corpus(monkeypatch, {"short": ("short", [(7, 112)], ""), "good": ("ok", [], "")})
    assert cb.main(["--all"]) == 1, "a measured shortfall is exit 1"
    assert "WIDEN" in capsys.readouterr().out
    cb2 = _stub_corpus(monkeypatch, {"good": ("ok", [], ""), "no-cache": ("nocache", [], "")})
    assert cb2.main(["--all"]) == 2, "and something that could not be checked is exit 2"
    capsys.readouterr()


def test_a_corridor_shortfall_is_measured_the_same_way_before_and_after_the_seam():
    """corridor_shortfalls is the arithmetic, pulled out so the box it is handed is visible.

    Anti-regression on the measurement itself: a vertex INSIDE the box still draws corridor_m around
    itself, so the margin it needs from every edge is the corridor -- that is the 23 m of ground the
    old `CORRIDOR_M = 45.0` copy let through. Graded on hand-checkable geometry: a point dead centre
    of a box 300 m across needs 68 m of margin and has ~150 m, so nothing is short; the same point
    with a 200 m corridor is short by ~50 m.
    """
    import check_osm_bbox as cb
    import geo
    S, W, N, E = _NARROW
    mid = {4: _line(4, [((S + N) / 2.0, (W + E) / 2.0)])}
    assert cb.corridor_shortfalls(_NARROW, mid, 68.0) == []
    half_ns = (N - S) / 2.0 * geo.mlat((S + N) / 2.0)
    half_ew = (E - W) / 2.0 * geo.mlon((S + N) / 2.0)
    edge = min(half_ns, half_ew)
    got = cb.corridor_shortfalls(_NARROW, mid, edge + 50.0)
    assert got and got[0][0] == 4 and abs(got[0][1] - 50) <= 1, (
        f"a corridor {edge + 50:.0f} m wide about the centre of a box whose nearest edge is "
        f"{edge:.0f} m away is 50 m short; got {got}")
    # a vertex OUTSIDE the box is short by its own overshoot PLUS the whole corridor
    out = {9: _line(9, [(N + 0.001, (W + E) / 2.0)])}
    over = 0.001 * geo.mlat(N)
    got2 = cb.corridor_shortfalls(_NARROW, out, 68.0)
    assert got2 and abs(got2[0][1] - (over + 68.0)) <= 1, (over, got2)


# ==================================================================================================
# D-10 / D-20a -- tools/check_scale.py
# ==================================================================================================

def _gated_green_scales():
    """[(in_per_5yd, slug, hole)] for every green the POCKET book gates, off the built markup.

    Independent of the browser and of tools/check_scale.py, on purpose: the figure being graded is one
    that tool publishes about itself, so re-deriving it through the tool would be the tool agreeing
    with itself. The scale is read the way CARDS_JS reads it off the laid-out element --
    preserveAspectRatio="meet", so the drawing scale is the SMALLER of the two fits -- and divided by
    the same ground scale px_m_of computes from dem_hd/holeNN.json, through geo's one figure of the
    Earth. tests/test_r14_pair.py measures a green the same way for the same reason.
    """
    from geo import mlat, mlon
    rows = []
    for book in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook.html"))):
        slug = os.path.basename(os.path.dirname(book))
        if slug.startswith("_"):
            continue
        with open(book, encoding="utf-8") as fh:
            page = fh.read()
        for panel in re.split(r'(?=<div class="panel hole)', page)[1:]:
            hn = re.search(r'class="hnum"[^>]*>(\d+)<', panel)
            grn = panel.find('<div class="grn">')
            if not hn or grn < 0:
                continue
            svg = re.search(r'<svg viewBox="([^"]+)" style="width:([0-9.]+)in;height:([0-9.]+)in"',
                            panel[grn:])
            if not svg:
                continue
            vb = [float(v) for v in svg.group(1).split()]
            k = min(float(svg.group(2)) / vb[2], float(svg.group(3)) / vb[3])
            meta_p = os.path.join(ROOT, "courses", slug, "dem_hd", f"hole{int(hn.group(1)):02d}.json")
            if not os.path.isfile(meta_p):
                continue
            with open(meta_p, encoding="utf-8") as fh:
                m = json.load(fh)
            x0, y0, x1, y1 = m["bbox"]
            clat = m["green_center"][0]
            px_m = (((x1 - x0) * mlon(clat)) / m["W"] + ((y1 - y0) * mlat(clat)) / m["H"]) / 2.0
            rows.append((k * 4.572 / px_m, slug, int(hn.group(1))))
    rows.sort(reverse=True)
    return rows


def test_the_worst_gated_green_scale_the_tool_publishes_is_the_one_it_measures():
    """"the worst gated reading from 0.3601 to 0.3600 in : 5 yd" -- and it is 0.3601.

    Re-derived over all 198 gated greens off the built markup: 0.360121 at bay-view-golf-club hole 3,
    with valley-hi 11 (0.360085), castlewood-hill 3 (0.360079) and bay-view 16 (0.360053) also
    rounding to 0.3601. Running the gate agrees to the digit -- its per-course worst lines read
    "0.3601 in/5yd" for bay-view, castlewood-hill and valley-hi.

    So the comment was wrong at both ends AND in direction. legal/11 records the earth-model migration
    as shifting the reported figure by "under +0.09%" (median +0.083% re-derived here), which moves the
    worst UP, not down: under the retired 111320.0 sphere the same markup reads 0.359805 -> 0.3598.
    legal/06 and legal/11 both publish 0.3601. The tool's own comment was the only copy that did not,
    and no test file mentioned either number -- so the figure now has a producer, a name, and this
    grader.
    """
    rows = _gated_green_scales()
    if not rows:
        pytest.skip("no pocket book with a built green surface here; courses/ is gitignored")
    import check_scale
    worst, slug, hole = rows[0]
    assert round(worst, 4) == check_scale.WORST_GATED_IN_PER_5YD, (
        f"tools/check_scale.py publishes {check_scale.WORST_GATED_IN_PER_5YD} as the worst gated "
        f"reading; {len(rows)} greens re-derived off the built markup put it at {worst:.6f} -> "
        f"{round(worst, 4)} ({slug} hole {hole}). A figure in a legal exhibit that no tool produces is "
        f"the defect this gate exists to prevent.")
    assert worst <= check_scale.LIMIT_IN_PER_5YD, (
        f"{slug} hole {hole} is over the Rule 4.3 cap at {worst:.4f} in : 5 yd")
    # and the two legal exhibits that quote it have to quote the SAME figure
    figure = f"{check_scale.WORST_GATED_IN_PER_5YD:.4f}"
    for rel in ("legal/06_RULE_4.3_CONFORMANCE.md", "legal/11_HORIZONTAL_EARTH_MODEL.md"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            text = fh.read()
        assert figure in text, (
            f"{rel} does not quote the worst gated reading {figure} in : 5 yd that the corpus "
            f"measures. Three documents once asserted a cap that 15 greens broke; a figure quoted in "
            f"only some of them is how that starts.")


def test_the_worst_gated_reading_is_written_as_a_literal_exactly_once():
    """One home for the figure. It had none in code and one in a comment, and the comment was wrong.

    The value lived only in a parenthetical beside the geo import, where nothing could grade it, so it
    said 0.3600 while legal/06 and legal/11 said 0.3601 and the tool measured 0.3601. The rule that
    prevents the recurrence is mechanical and needs no reading of prose: the CURRENT figure is written
    as a literal exactly once -- WORST_GATED_IN_PER_5YD's own definition -- and every other mention of
    it goes through that name. A second literal is a second thing to forget.

    Retired figures (0.3598 under the old sphere) and the wrong one this replaced stay written out, and
    must: they are attributed history, they cannot silently become the current figure, and a note that
    only records the correction is how "already investigated" turns into a dead end -- this file's own
    docstring makes that argument about a stale Overpass probe.
    """
    with open(os.path.join(ROOT, "tools", "check_scale.py"), encoding="utf-8") as fh:
        src = fh.read()
    import check_scale
    figure = f"{check_scale.WORST_GATED_IN_PER_5YD:.4f}"
    literals = re.findall(rf"(?<![\d.]){re.escape(figure)}(?![\d])", src)
    assert len(literals) == 1, (
        f"tools/check_scale.py writes the worst gated reading {figure} as a literal {len(literals)} "
        f"times. One of them is WORST_GATED_IN_PER_5YD; the rest are copies that will drift from the "
        f"corpus the way the retired comment did. Reference the constant instead.")
    assert src.count("WORST_GATED_IN_PER_5YD") >= 2, (
        "the constant must be REFERENCED where the figure is discussed, or the prose can drift from "
        "it exactly as before")


def test_a_tree_with_no_built_book_is_not_a_rule_4_3_pass(monkeypatch, capsys, tmp_path):
    """"no built books found" returned 0 -- a Rule 4.3 conformance pass over zero greens.

    The same file 118 lines below refuses that reading in as many words: "0 greens measured ... PASS
    used to exit 0, so a renamed directory or a course set that failed to load would report Rule 4.3
    conformance for an empty measurement." Both paths are the same claim and now answer the same code.

    THE CONVENTION CHOSEN IS 2, and it is this file's own: its docstring already reserves 2 for
    "nothing could be measured either way", and it is what every sibling gate answers for the same
    question -- tools/gen_provenance.py for a tree with no course data, lidar_coverage.main for no
    readable tile, tools/verify_elevation.py for a course it could not verify, and
    tools/check_osm_bbox.py for a corpus it could not examine. 1 stays reserved for a MEASURED
    non-conformance: a green over the cap, or one that went unmeasured while its book sat on disk.
    """
    import check_scale
    monkeypatch.setattr(check_scale, "ROOT", tmp_path)
    (tmp_path / "courses").mkdir()
    rc = check_scale.main([])
    out = capsys.readouterr().out
    assert "no built books found" in out, out
    assert rc == 2, (
        f"an empty tree returned {rc} from the Rule 4.3 gate. Exit 0 is documented as 'every POCKET "
        f"green conforms', and no green was measured.\n{out}")


def test_the_rule_4_3_gate_documents_the_code_it_now_answers():
    """The exit table is part of the gate. It said 2 meant one thing, and 2 now covers three.

    Graded because the docstring is what a reader scripts against, and a gate whose documented codes
    and real codes disagree is the same class of defect as a figure with no producer.
    """
    import check_scale
    doc = check_scale.__doc__
    assert re.search(r"2 =", doc), doc
    for phrase in ("no book", "browser"):
        assert phrase in doc, (
            f"the exit-code table must name {phrase!r} among the things that answer 2:\n{doc}")
