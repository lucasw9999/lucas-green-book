#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Do the artifact gates in tools/ gate what they claim? The two legal generators did not.

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

    Two tools carry it (`tools/gen_disclaimers.py`, `tools/gen_provenance.py`) and
    `tools/export_pdf.py` carries an inline variant that also takes course slugs, so it is not judged
    by this table. What this asserts:

      * every flag the tool declares KNOWN is accepted, and the empty argv is accepted -- without
        this, "refuse everything" would pass, and refusing `--check` would make the check branch
        unreachable while refusing nothing would make the WRITE branch the default.
      * every near-miss spelling of every known flag is refused.
      * a bare positional word is refused. Neither legal generator takes an argument at all.
    """
    gates = _argv_gates()
    assert set(gates) >= set(_LEGAL_WRITERS), (
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
        assert name in _LEGAL_WRITERS, (
            f"tools/{name}.py spells the argv rule and is not covered by this file -- add it to "
            f"_LEGAL_WRITERS (its non-flag branch destroys something) or grade it explicitly")
