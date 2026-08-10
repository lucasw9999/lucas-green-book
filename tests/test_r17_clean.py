#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""No file in this repository may state that its data was checked against a third-party compilation.

WHAT THE RULE IS. Everything these books are built from is open or public-domain and is named as such:
OpenStreetMap geometry (ODbL), USGS 3DEP LiDAR (public domain), USDA NAIP (public domain), and
par/yardage/handicap **facts from the published scorecard**. Describing those is the point and must stay
explicit -- "measured from the OSM centreline", "computed from public-domain USGS 3DEP LiDAR", "facts
from the published scorecard" are all statements this guard is built to leave alone. What it refuses is a
sentence that sources or cross-checks this project's data against a NAMED commercial compilation of
somebody else's golf data. Facts are not copyrightable (*Feist*, 1991) and a scorecard number is a fact
wherever it is read; but a record that says which company's compilation each figure was checked against
documents a dependence on those compilations rather than on the open data the books are actually built
from, and it is the record, not the fact, that is the problem. Say what CLASS of thing a figure came
from, not which company published a directory of it.

WHY THE GUARD KEYS ON THE ASSERTION AND NOT ON THE NAME. Three statements in this repo name commercial
products deliberately, in order to disclaim them -- legal/00's "No competitor brand name (...) appears
anywhere in any book", legal/01's "Any commercial green-book product (...): no data, imagery, symbols,
layout, or brand used anywhere", and the BRANDS tuple in tests/test_phase1_regressions.py that measures
the first two across every built book. Those are protective and must never be swept away by a cleanup of
this kind, so a bare name search is the wrong instrument. The rule this file enforces is the difference
between the two directions: **"we never used X" stays; "we checked our numbers against X" goes.** So a
finding needs BOTH halves -- a compilation's name AND a sourcing or cross-checking claim close enough to
it to be one statement. test_the_three_protective_disclaimers_still_pass drives the real sentences
through the predicate so that distinction is measured rather than asserted in a comment.

Naming the compilations here is the same protective drafting as BRANDS: a guard cannot forbid what it
cannot spell. This module is the one file the sweep skips, for that reason and no other.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SELF = "tests/test_r17_clean.py"

# The compilations and commercial products whose names must never appear as something this project's
# figures were taken from or checked against. Two families, deliberately in one list:
#   * scorecard / course-rating directories -- the ones a transcriber is tempted to cite;
#   * green-book and shot-tracking products -- the ones legal/00 and legal/01 name to DISCLAIM, kept
#     here so test_the_three_protective_disclaimers_still_pass is a real test of the name-versus-claim
#     distinction rather than a vacuous one.
# Matched case-insensitively on word boundaries, so "ncga.org" counts and "Bingo" would not.
#
# Deliberately ABSENT: the USGA and the R&A. They are the governing bodies whose Rule 4.3 this project
# is designed to conform to (legal/06) and whose Course Rating System defines what a rating IS -- a
# published rating is the primary fact, not a third party's directory of somebody else's data, and
# legal/06 could not be written at all without naming them. Also absent: bare initialisms short enough
# to collide with ordinary prose in this repo, which would make the sweep noisy rather than sharper.
COMPILATIONS = (
    "BlueGolf", "Blue Golf", "GolfLink", "Golf Link", "GolfNow", "GolfPass", "GolfAdvisor",
    "GolfScoreKeeper", "FlashCaddie", "Golfify", "OpenGolfAPI", "NCGA", "GOLF.com", "Wikipedia",
    "StrackaLine", "Stracka Line", "GolfLogix", "Golf Logix", "SwingU", "18Birdies", "Arccos",
    "TheGrint", "Hole19",
)

# The claim half, and it is a claim about an OBJECT: text that says a figure came from something, or was
# checked against something, with the something still to come. Two shapes, because the removed wording
# used both, and they are matched in different directions (see `findings`).
#
# Kept to phrases that carry a source with them. The bare verb "used" is deliberately absent -- legal/01's
# protective "no data, imagery, symbols, layout, or brand used anywhere" would match it, and that
# sentence is the opposite of the thing being forbidden.
#
# `verified` and `checked` carry a lookbehind that refuses a hyphenated prefix, because legal/00's
# "(grep-verified across all HTML/PDF)" is a claim about THIS repository's own grep sweep over its own
# books -- the object is the books, not a directory -- and it sits five words from two product names it
# exists to disclaim. That is the exact statement this guard must not fight. The cost is a named
# false-negative channel: "grep-verified across <name>" would be missed. It is narrow, it is here in
# writing, and the alternative measured on this tree was a guard that deletes its own disclaimers.
_NOT_HYPHENATED = r"(?<![\w\-‐‑‒–—])"
CLAIM = re.compile(
    _NOT_HYPHENATED + r"cross[-‑\s]?check|" + _NOT_HYPHENATED + r"cross[-‑\s]?verif|"
    + _NOT_HYPHENATED + r"cross[-‑\s]?referenc|"
    + _NOT_HYPHENATED + r"verified\s+(?:against|across|via|with|by)|"
    + _NOT_HYPHENATED + r"checked\s+(?:against|across|via|with)|"
    r"corroborated\s+(?:by|against|across)|"
    r"reconciled\s+(?:against|with|across)|"
    r"(?:sourced|transcribed|copied|taken)\s+(?:off|from)|"
    r"\bauthoritative\b|"
    r"\bsources?\b\s*[:(]",
    re.I)

# The trailing shape: "<name> / <name> (verified)", "<name> (Callippe Preserve GC), verified",
# "... + <name> (cross-checked)". Here the name comes FIRST and the claim is a bare qualifier hung off
# the end of it. Bare is the whole point -- the token, stripped of brackets and punctuation, IS the
# checking word and nothing else. "grep-verified" is not, "verified across all HTML/PDF" is not, so
# legal/00's disclaimer stays clean while a course record's "(verified)" does not.
QUALIFIER = re.compile(
    r"^(?:cross[-‑]?check(?:ed)?|cross[-‑]?verified|verified|checked|authoritative)$", re.I)

NAME = re.compile("|".join(r"(?<![\w-])%s(?![\w-])" % re.escape(n) for n in COMPILATIONS), re.I)

# How near is "one statement"? Measured on this tree rather than chosen. Forward -- claim first, name as
# its object -- reaches 20 words, which is what a wrapped "Sources (cross-checked):" list of four
# directories spans. Backward is 8, because a trailing "(verified)" qualifies the thing just named and a
# wide backward reach is what pulls an unrelated product name into an unrelated sentence. A paragraph
# break ends both windows: two paragraphs are two statements.
WINDOW_WORDS = 20
BACK_WINDOW = 8

# Text this sweep cannot read as prose. Book output and images are graded elsewhere (the BRANDS scan in
# tests/test_phase1_regressions.py reads every built HTML and PDF); this is a check on the repository's
# own committed wording.
SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".pdf", ".stl", ".laz", ".npy", ".ico", ".woff", ".woff2")


def _blocks(text):
    """Paragraphs, whitespace-normalised. A blank line ends a statement; a wrapped line does not.

    Prose in this repo wraps mid-sentence at ~100 columns, so a line-at-a-time reading would miss
    "cross-checked\n  with <name>" -- the commonest shape of the thing being looked for. Markdown table
    cells are split as well, because legal/03 puts a whole course's provenance on one physical line and
    two cells of it are two statements.
    """
    for para in re.split(r"\n\s*\n", text):
        for cell in para.split("|"):
            words = cell.split()
            if words:
                yield words


def _bare(word):
    """`word` with brackets, markdown emphasis and trailing punctuation removed. Inner hyphens kept.

    So "(cross-checked):**" reads as "cross-checked" and "grep-verified" still reads as
    "grep-verified" -- the distinction QUALIFIER is built on.
    """
    return word.strip("*_`“”\"'()[]{}<>,.;:!?—–-‐‑")


def findings(text):
    """[(the claim, the compilation named, the words around them)] for `text`, deduplicated.

    Both halves are always required. The direction matters and is the whole precision of this guard:

      forward   a CLAIM phrase, then a compilation name within WINDOW_WORDS after it -- the name is the
                object of the claim ("cross-checked with <name>", "Sources (cross-checked): ... <name>",
                "transcribed from <name>", "the authoritative scorecard (<name>, ...)").
      backward  a bare QUALIFIER, with a compilation name within BACK_WINDOW before it -- the claim is
                hung off the end of the name instead ("<name> / <name> (verified)", "... + <name>
                (cross-checked)").

    A name that merely sits near a claim whose object is something else is NOT a finding, which is what
    keeps legal/00's "(StrackaLine, GolfLogix, etc.) appears anywhere in any book (grep-verified across
    all HTML/PDF)" clean.
    """
    out = {}
    for words in _blocks(text):
        names = {}
        for i, w in enumerate(words):
            for m in NAME.finditer(w):
                names.setdefault(i, []).append(m.group(0))
        if not names:
            continue
        for i, word in enumerate(words):
            # forward: the claim phrase has to BEGIN in this token, so one phrase is counted once
            ahead = " ".join(words[i:i + 5])
            m = CLAIM.search(ahead)
            if m and m.start() <= len(word):
                for j, found in names.items():
                    if i < j <= i + WINDOW_WORDS:
                        for nm in found:
                            out[(i, j, nm.lower())] = (m.group(0), nm, _quote(words, i, j))
            # backward: a bare trailing qualifier, with the name it qualifies just before it
            if QUALIFIER.match(_bare(word)):
                for j, found in names.items():
                    if i - BACK_WINDOW <= j < i:
                        for nm in found:
                            out[(j, i, nm.lower())] = (_bare(word), nm, _quote(words, j, i))
    return sorted(out.values())


def _quote(words, lo, hi):
    return " ".join(words[max(0, lo - 4):hi + 5])


def _tracked():
    """Every file git tracks, as repo-relative paths. Text only, and never this module.

    `git ls-files -z` rather than a walk: the question is what this repository PUBLISHES, and a walk
    would read the gitignored corpus, the build outputs and __pycache__ -- none of which are the public
    record. courses/*/course.json is graded separately, by
    test_no_course_record_cites_a_third_party_compilation, because it is the upstream of legal/03 and
    the place a name has to be stopped rather than the place it shows up.
    """
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, f"git ls-files failed: {out.stderr[-400:]}"
    return [p for p in out.stdout.split("\0")
            if p and p != SELF and not p.lower().endswith(SKIP_SUFFIX)]


def _read(rel):
    try:
        with io.open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def test_no_tracked_file_says_the_data_was_checked_against_a_third_party_compilation():
    """The sweep, over everything this repository publishes.

    Non-vacuous in three ways, because a sweep that reads nothing passes: the file count carries a
    floor, the two documents that make this project's provenance argument have to be among the files
    actually read, and the predicate is proven to fire on this very tree in
    test_the_guard_bites_inside_a_real_document.
    """
    files, unreadable, bad = 0, [], []
    for rel in _tracked():
        text = _read(rel)
        if text is None:
            unreadable.append(rel)
            continue
        files += 1
        for claim, name, quote in findings(text):
            bad.append(f"{rel}: {name!r} within {WINDOW_WORDS} words of {claim!r} -- ...{quote}...")
    assert files >= 40, f"only {files} tracked text file(s) read, so a clean result proves nothing"
    for must in ("legal/01_DATA_SOURCES_AND_LICENSES.md", "legal/03_PROVENANCE_BY_COURSE.md",
                 "PIPELINE.md", "README.md"):
        assert _read(must) is not None, f"{must} was not readable, so it was not swept"
    assert not unreadable, f"tracked text file(s) this sweep could not read: {unreadable}"
    assert not bad, (
        "a tracked file states that this project's data was sourced from or checked against a named "
        "third-party compilation. The books are built from open and public-domain data, and the record "
        "has to say what CLASS of thing a figure came from -- 'facts from the published scorecard' -- "
        "not which company published a directory of it:\n  " + "\n  ".join(bad))


def test_no_course_record_cites_a_third_party_compilation():
    """The same rule one step upstream, where legal/03's wording actually comes from.

    legal/03_PROVENANCE_BY_COURSE.md is GENERATED by tools/gen_provenance.py and reproduces each
    course's `sources` text -- truncated in the table, uncut under "Sources in full". So a name put back
    into a course record reaches a legal document on the next regeneration, and the sweep above would
    report the generated file rather than the field that has to change. Graded here instead, naming the
    field.

    courses/ is gitignored, so on a fresh clone there is nothing to grade and this skips rather than
    passing quietly -- the same shape as the rest of the suite's corpus tests.
    """
    records = [p for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
               if not os.path.basename(os.path.dirname(p)).startswith("_")]
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    bad, fields = [], 0
    for p in records:
        slug = os.path.basename(os.path.dirname(p))
        with io.open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
        texts = dict((f"sources.{k}", v) for k, v in (rec.get("sources") or {}).items())
        for k in ("dem_source", "greens_outdated_basis"):
            if rec.get(k):
                texts[k] = rec[k]
        for key, val in sorted(texts.items()):
            if not isinstance(val, str):
                continue
            fields += 1
            for claim, name, quote in findings(val):
                bad.append(f"{slug}.{key}: {name!r} near {claim!r} -- ...{quote}...")
    assert fields >= 20, f"only {fields} recorded source field(s) read"
    assert not bad, (
        "a course record cites a third-party compilation as where its figures came from or were checked "
        "against. tools/gen_provenance.py copies these fields into legal/03_PROVENANCE_BY_COURSE.md "
        "verbatim, so this is a legal document one regeneration away:\n  " + "\n  ".join(bad))


def test_the_three_protective_disclaimers_still_pass():
    """"We never used X" must survive a guard whose whole subject is the word X.

    The three statements are load-bearing in the other direction: legal/00 and legal/01 name the
    commercial green-book products precisely to record that none of their data, imagery, symbols, layout
    or brand is used anywhere, and the BRANDS tuple in tests/test_phase1_regressions.py is what measures
    that claim across every built book. A cleanup that keys on names rather than on claims deletes
    exactly these, which is why they are read out of the real files here and driven through the
    predicate. They are found by content, not by line number, so the check cannot quietly stop
    measuring when the files are re-wrapped."""
    checked = []
    for rel, needle in (("legal/00_SUMMARY_AND_VERDICT.md", "No competitor brand name"),
                        ("legal/01_DATA_SOURCES_AND_LICENSES.md", "commercial green"),
                        ("tests/test_phase1_regressions.py", "BRANDS = (")):
        text = _read(rel)
        assert text is not None, f"{rel} is unreadable"
        blocks = [b for b in re.split(r"\n\s*\n", text) if needle in b]
        assert blocks, (
            f"{rel} no longer contains {needle!r}. That is one of the three statements this project "
            f"keeps ON PURPOSE -- naming a commercial product in order to disclaim it -- so either it "
            f"was removed, which is the failure this test exists to catch, or it moved and this test "
            f"has to be re-anchored.")
        for block in blocks:
            assert NAME.search(block), (
                f"{rel}: the {needle!r} statement no longer names any product this guard knows, so it "
                f"is not exercising the name-versus-claim distinction at all")
            found = findings(block)
            assert not found, (
                f"{rel}: the guard reads a PROTECTIVE disclaimer as a cross-check claim: {found}. "
                f"'we never used X' must stay; only 'we checked our numbers against X' goes.")
            checked.append(rel)
    assert len(checked) >= 3, f"only {len(checked)} disclaimer(s) graded"


def test_the_guard_bites_on_every_shape_that_was_removed():
    """Red before green: each shape of claim this cleanup removed, composed and refused.

    Composed from the two halves rather than quoted, so proving the guard works does not put a removed
    sentence back into a tracked file. The shapes are the ones that were really in this repo -- a
    "Sources (cross-checked):" list, a per-course "cross-checked with", a "verified across", a
    "transcribed from", and a name reached only by a line wrap -- and each is asserted to fire on the
    NAME as well as on the claim, so a pass cannot come from the claim phrase alone.
    """
    name = "GolfLink"
    shapes = {
        "a Sources list": f"**Sources (cross-checked):** official course sites, {name} — used only "
                          f"to verify the numbers.",
        "a per-course cross-check": f"Detailed + standard scorecard (cross-checked with {name} & OSM par)",
        "a verified-across claim": f"Ratings/slopes verified across {name} + a second directory.",
        "a transcribed-from claim": f"Per-hole yardages transcribed from {name}'s detailed scorecard.",
        "a reconciled-against claim": f"Every tee reconciled against an independent {name} mirror.",
        "a line-wrapped list": f"- **Sources (cross-checked):** official course sites,\n  {name} "
                               f"— used only to verify the numbers.",
        "a recipe step": f"Find the authoritative scorecard ({name}, state GA, or the club) and record "
                         f"par, per-hole handicap, and yardages for every tee.",
    }
    missed = []
    for what, text in shapes.items():
        got = findings(text)
        if not got or not any(g[1].lower() == name.lower() for g in got):
            missed.append(f"{what}: {text.strip()[:90]!r} -> {got}")
    assert not missed, (
        "the guard does not fire on wording this repository actually carried, so it would not have "
        "caught it:\n  " + "\n  ".join(missed))

    # ...and the other direction, so the pass above is a measurement and not a pattern that matches
    # everything. Each of these is a sentence this project must be free to write.
    allowed = (
        "Par / yardage / handicap — facts from the published scorecard (facts, not copyrightable).",
        "Green slope computed by us from public-domain USGS 3DEP LiDAR, flown 2023-10-02.",
        "Yardages measured from the OSM centreline and the mapped tee polygons.",
        "Per-hole par corroborated by OpenStreetMap's own golf=hole par tags.",
        "Sources: OpenStreetMap contributors (ODbL); USGS 3DEP; USDA NAIP.",
        "Any commercial green-book product (StrackaLine, GolfLogix, etc.): no data, imagery, symbols, "
        "layout, or brand used anywhere.",
        "No competitor brand name (StrackaLine, GolfLogix, etc.) appears anywhere in any book.",
    )
    wrong = [(s, findings(s)) for s in allowed if findings(s)]
    assert not wrong, (
        "the guard refuses a sentence this project must be able to write -- open-data provenance, or a "
        "disclaimer that names a product in order to reject it:\n  "
        + "\n  ".join(f"{s[:80]!r} -> {f}" for s, f in wrong))


def test_the_guard_bites_inside_a_real_document(tmp_path):
    """The sweep, proven on a doctored COPY of a file it really reads. Nothing tracked is written.

    The two tests above grade a predicate over strings; this one grades the thing the sweep actually
    does -- read a real document off disk and report the file -- because a predicate that works while
    the sweep reads the wrong bytes, or skips the file, or swallows the path, is the failure mode a
    string test cannot see. legal/01 is the copy used because section 3 is where the removed wording
    lived.
    """
    rel = "legal/01_DATA_SOURCES_AND_LICENSES.md"
    real = _read(rel)
    assert real is not None and "facts from the published scorecard" in real, (
        f"{rel} no longer carries the replacement wording this cleanup put in, so this probe is "
        f"anchored to a document that has moved on")
    assert not findings(real), f"{rel} is not clean to begin with, so the injection below proves nothing"

    anchor = "- **Status:** **facts.**"
    assert anchor in real, f"the injection anchor {anchor!r} is gone from {rel}; re-anchor this probe"
    doctored = real.replace(
        anchor,
        "- **Sources (cross-checked):** official course sites, BlueGolf/NCGA — used only to "
        "verify the numbers.\n" + anchor, 1)
    p = tmp_path / "01_doctored.md"
    p.write_text(doctored, encoding="utf-8")

    got = findings(io.open(p, encoding="utf-8").read())
    assert got, ("one sentence naming a compilation as a cross-check source was added to a copy of "
                 f"{rel} and the sweep read it as clean")
    assert {g[1].lower() for g in got} >= {"bluegolf", "ncga"}, (
        f"the sweep found something in the doctored copy but not both names: {got}")

    # The real file is untouched: the sweep must still be clean on it after the probe.
    assert not findings(_read(rel)), f"{rel} was modified by this test"
