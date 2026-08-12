#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The scorecard's own arithmetic, graded on the page a reader holds rather than in the file behind it.

WHY THIS FILE EXISTS. A card's numbers are the one thing in this book nothing measures from the
ground: a green's slope is computed from LiDAR, a yardage tick is computed from the centreline, but
par, the stroke index and the per-tee yardages are transcribed by hand. So the only defences against a
transcription slip are (a) the card's own internal arithmetic and (b) whether the record's prose about
those numbers agrees with the numbers. Both are graded here, and both have caught something.

WHAT WAS ALREADY GRADED AND WHAT WAS NOT. test_phase1_regressions._check_course sums the 18 per-hole
rows of each tee and compares that sum against `tees[].yards`. That is the grand total only, in the
SOURCE file only. Three things sat outside it:

  * THE OUT AND IN SUBTOTALS. generate.scorecard_panel derives Out, In and Tot itself, by summing
    HOLES -- so the printed card carries three sums the source file does not contain. A book built
    from a course.json that has since been edited prints subtotals that add up perfectly to each other
    and disagree with the record; the source-side check cannot see it because it never opens the book,
    and the book-side check in test_phase1_regressions compares whole rendered cards byte for byte,
    which goes red for any cosmetic change and so cannot be the thing that pins arithmetic.
  * WHETHER A RECORD'S CLAIM ABOUT WITHHELD RATINGS IS TRUE. micke-grove's Red row is the defect this
    corpus already paid for -- a women's slope printed in a men's column -- and tests/test_r14_tees.py
    now refuses that shape in the DATA. It does not read the prose. A record that says "no rating or
    slope is withheld here" while a tee withholds one, or the reverse, is a provenance document that
    describes a different course than the one it ships beside, and legal/03 reproduces that prose
    verbatim.
  * THE BAND THE PROSE USES AS A BAR. One course record rejected a printed scorecard on the grounds
    that its back row implied 328 yd per stroke of Course Rating "against a normal 190-265". The
    rejection is right and the bar was quoted from nowhere: measured across all 45 adjacent rated tee
    pairs in this corpus the real spread is 141.8 to 284.0 yd per stroke, so FIVE legitimate pairs
    of published USGA figures fall outside 190-265 -- micke-grove Blue->White at 141.8, bay-view
    Silver->Green at 174.3, philadelphia Black->Blue at 266.4, monarch-bay Black->Gold at 280.0 and
    bay-view Gold->Silver at 284.0. A bar this project's own data fails is not a bar; it is a figure
    that happened to be on the right side of one bad row. So the band enforced here is derived from
    the corpus with headroom, it still refuses 328, and any band a record QUOTES must contain
    everything the corpus actually produces.

NO MODULE IS DROPPED FROM sys.modules ANYWHERE IN THIS FILE, deliberately. README publishes how many
sites in tests/ do that, and test_the_suite_reports_its_own_module_drop_count_correctly re-derives it
off the token stream; a new module that rebinds COURSE would move a figure in a file this one does not
own. Nothing here needs the engine bound to a course: every grader reads JSON and HTML off disk.
"""
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

# generate.scorecard_panel's own markup: one <table> inside the Scorecard panel, a header row marked
# class="th" whose last two cells are the two tee names TRUNCATED TO FOUR CHARACTERS (esc(fl[:4])),
# then one row per hole, then Out / In / Tot rows marked class="sum".
SCORECARD = re.compile(r'<div class="cardtitle">Scorecard\s*&mdash;\s*(.*?)</div>\s*'
                       r'<table>(.*?)</table>', re.S)
ROW = re.compile(r'<tr(?P<cls> class="[^"]*")?>\s*<td>(?P<a>[^<]*)</td>\s*<td>(?P<b>[^<]*)</td>\s*'
                 r'<td>(?P<c>[^<]*)</td>\s*<td>(?P<d>[^<]*)</td>\s*<td>(?P<e>[^<]*)</td>\s*</tr>', re.S)

# A band on (yards lost) / (rating stroke lost) between two adjacent rated tees. DERIVED, not chosen:
# the 45 adjacent pairs in this corpus span 141.8 to 284.0, and the shape this exists to refuse is
# 328. The margin is ~8% below the measured floor and ~6% above the measured ceiling -- wide enough
# that a newly added course of ordinary published figures does not go red, tight enough that 328 does.
# test_the_band_is_wide_enough_for_the_corpus_and_tight_enough_to_refuse_328 grades both edges.
BAND_LO, BAND_HI = 130.0, 300.0

# The 2012 printed card's back row, which is the reason there is a band at all. Not read from any file:
# it is the value a REFUSED source implied, and it lives here so the refusal is reproducible.
REFUSED_YD_PER_STROKE = 328.0

# "328 yd per stroke of Course Rating against a normal 190-265" -- a band quoted in prose as the bar a
# source was judged against. Matched only when a rating-stroke phrase is close by, so an unrelated
# hyphenated pair of numbers in the same paragraph is not read as a band.
QUOTED_BAND = re.compile(
    r"(?:yd|yards?)\s+per\s+stroke[^.]{0,80}?(\d{2,4})\s*[-‐‑‒–—]\s*(\d{2,4})"
    r"|per\s+(?:rating\s+stroke|stroke\s+of\s+Course\s+Rating)[^.]{0,80}?"
    r"(\d{2,4})\s*[-‐‑‒–—]\s*(\d{2,4})", re.I)


def _records():
    """(slug, parsed course.json) for every real course on disk. Scratch slugs excluded.

    distribution.is_corpus_slug rather than a local startswith("_"), which is the drift
    tests/conftest.py's _classify already names -- four spellings of "is this a course?" had to be
    reconciled once and this is not going to be a fifth.
    """
    import distribution
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if not distribution.is_corpus_slug(slug):
            continue
        with io.open(cj, encoding="utf-8") as fh:
            out.append((slug, json.load(fh)))
    return out


def _books():
    """(slug, edition, html) for every shipped book: the standard deck and the enlarged coach deck.

    Both, because scorecard_panel is shared and a stale coach deck is as wrong as a stale standard one.
    """
    out = []
    for slug, _ in _records():
        for edition in ("greenbook.html", "greenbook_coach.html"):
            p = os.path.join(ROOT, "courses", slug, edition)
            if os.path.exists(p):
                with io.open(p, encoding="utf-8") as fh:
                    out.append((slug, edition, fh.read()))
    return out


def _int(cell):
    cell = re.sub(r"<[^>]+>", "", cell).replace("&nbsp;", " ").strip()
    return int(cell) if re.fullmatch(r"-?\d+", cell) else None


def scorecard_rows(html):
    """[(label, par, hcp, back, front)] from a book's Scorecard panel, plus its two tee names.

    Returns (None, None) when the panel is absent, so a caller can say so rather than crash: poppy-ridge
    is built in yardage mode and every book here is generated by the same panel, but "the panel moved"
    has to read as a failure rather than as a vacuous pass.
    """
    m = SCORECARD.search(html)
    if not m:
        return None, None
    names = [p.strip() for p in re.sub(r"<[^>]+>", "", m.group(1)).split("/")]
    rows = []
    for r in ROW.finditer(m.group(2)):
        label = re.sub(r"<[^>]+>", "", r.group("a")).strip()
        rows.append((label, _int(r.group("b")), _int(r.group("c")),
                     _int(r.group("d")), _int(r.group("e"))))
    return names, rows


# ---------------------------------------------------------------------------
# 1. the printed card's own arithmetic: per-hole rows -> Out / In -> Tot
# ---------------------------------------------------------------------------
def scorecard_problems(where, names, rows):
    """([problem strings], sums graded) for ONE parsed scorecard. Pure, so a probe can attack it.

    Extracted rather than inlined in the sweep for the reason this repo keeps re-learning: a corpus
    sweep that only ever sees correct data cannot demonstrate that it would notice incorrect data. The
    probe below doctors a copy of a real book and drives it through this same function, so the sweep
    and the demonstration cannot drift apart.
    """
    problems, graded = [], 0
    if rows is None:
        return [f"{where}: no Scorecard panel found -- either the book has none or the panel's markup "
                f"moved and this grader is reading the wrong thing"], 0
    holes = [r for r in rows if re.fullmatch(r"\d+", r[0])]
    out_r = next((r for r in rows if r[0] == "Out"), None)
    in_r = next((r for r in rows if r[0] == "In"), None)
    tot_r = next((r for r in rows if r[0] == "Tot"), None)
    if tot_r is None:
        return [f"{where}: the scorecard prints no Tot row"], 0
    if len(holes) < 9:
        return [f"{where}: only {len(holes)} hole row(s) in the scorecard"], 0
    # column 1 is par, columns 3 and 4 are the two printed tees; the HCP column has no subtotal
    for ci, what in ((1, "par"), (3, names[0] if names else "back"),
                     (4, names[1] if len(names) > 1 else "front")):
        front9 = [r for r in holes if int(r[0]) <= 9]
        back9 = [r for r in holes if int(r[0]) > 9]
        if out_r is not None and in_r is not None and back9:
            for sub, nine, lbl in ((out_r, front9, "Out"), (in_r, back9, "In")):
                want = sum(r[ci] for r in nine if r[ci] is not None)
                if sub[ci] != want:
                    problems.append(f"{where}: the {lbl} row's {what} prints {sub[ci]} but holes "
                                    f"{nine[0][0]}-{nine[-1][0]} sum to {want}")
                graded += 1
            if tot_r[ci] != (out_r[ci] or 0) + (in_r[ci] or 0):
                problems.append(f"{where}: {what} Tot prints {tot_r[ci]} but Out {out_r[ci]} + "
                                f"In {in_r[ci]} = {(out_r[ci] or 0) + (in_r[ci] or 0)}")
            graded += 1
        allhole = sum(r[ci] for r in holes if r[ci] is not None)
        if tot_r[ci] != allhole:
            problems.append(f"{where}: {what} Tot prints {tot_r[ci]} but its {len(holes)} printed "
                            f"hole rows sum to {allhole}")
        graded += 1
    return problems, graded


def test_every_printed_scorecard_adds_up_to_its_own_out_in_and_total():
    """Out + In = Tot, and each subtotal is the sum of the holes printed above it, ON THE PAGE.

    The three sums are derived by generate.scorecard_panel and appear nowhere in course.json, so this
    is the only check that can see them. Graded per column -- par, and both printed tees -- because a
    slip in one column is invisible in the others: the Out row's par and the Out row's yardage are two
    independent sums of two independent columns.
    """
    books = _books()
    if not books:
        pytest.skip("no built book on disk (courses/ is gitignored): nothing to grade")
    problems, graded_sums = [], 0
    for slug, edition, html in books:
        names, rows = scorecard_rows(html)
        p, n = scorecard_problems(f"{slug}/{edition}", names, rows)
        problems += p
        graded_sums += n
    assert graded_sums >= 3 * len(books), \
        f"only {graded_sums} sum(s) graded over {len(books)} book(s) -- nothing was measured"
    assert not problems, ("a printed scorecard does not add up to its own subtotals:\n  "
                          + "\n  ".join(problems))


def test_the_scorecard_arithmetic_grader_bites_on_a_doctored_book(tmp_path):
    """Red before green, on a COPY of a book this sweep really reads. Nothing on disk is written.

    One hole's printed yardage is moved by 7 yd in the copy. That is the shape a transcription slip
    takes -- one cell, still plausible -- and it must break the Out (or In) subtotal AND the Tot for
    that column while leaving every other column untouched. A grader that reports nothing here would
    report nothing on a real slip either.
    """
    books = _books()
    if not books:
        pytest.skip("no built book on disk (courses/ is gitignored): nothing to grade")
    slug, edition, html = books[0]
    names, rows = scorecard_rows(html)
    assert rows, f"{slug}/{edition} has no readable scorecard, so this probe proves nothing"
    clean, n = scorecard_problems("clean", names, rows)
    assert not clean and n > 0, f"{slug}/{edition} is not clean to begin with: {clean}"

    # move the back-tee cell of hole 3 by 7 yd, in the markup, exactly as a mistyped card would read
    hole3 = next(r for r in rows if r[0] == "3")
    m = SCORECARD.search(html)
    old_cell = (f'<tr><td>3</td><td>{hole3[1]}</td><td>{hole3[2]}</td>'
                f'<td>{hole3[3]}</td><td>{hole3[4]}</td></tr>')
    assert old_cell in m.group(2), f"could not locate hole 3's row to doctor: {old_cell!r}"
    doctored = html.replace(old_cell, old_cell.replace(f"<td>{hole3[3]}</td>",
                                                       f"<td>{hole3[3] + 7}</td>", 1), 1)
    p = tmp_path / "doctored.html"
    p.write_text(doctored, encoding="utf-8")
    dn, dr = scorecard_rows(io.open(p, encoding="utf-8").read())
    found, _ = scorecard_problems("doctored", dn, dr)
    assert found, ("one printed yardage was moved by 7 yd and the arithmetic grader read the card as "
                   "consistent")
    assert any("Out" in f for f in found), f"the Out subtotal did not report it: {found}"
    assert any("Tot" in f for f in found), f"the Tot row did not report it: {found}"
    # and only the doctored column: par and the front tee must stay silent
    assert not any("par" in f for f in found), f"an unrelated column reported: {found}"
    # the real file is untouched
    assert not scorecard_problems("recheck", *scorecard_rows(html))[0], \
        f"{slug}/{edition} was modified by this test"


def page_vs_record(where, names, rows, j):
    """([problem strings], columns tied back) for one printed card against its own course.json.

    Pure for the same reason scorecard_problems is: the probe below drives a synthetic disagreement
    through this exact function, so "it would notice" is measured rather than asserted.
    """
    problems, checked = [], 0
    if rows is None:
        return [], 0                                    # reported by the arithmetic grader
    tot_r = next((r for r in rows if r[0] == "Tot"), None)
    if tot_r is None:
        return [], 0
    holes, cols = j["holes"], j["hole_cols"][2:]
    nums = sorted(int(k) for k in holes)
    by_name = {t["name"]: t for t in (j.get("tees") or [])}
    for ci, printed_name in ((3, names[0] if names else None),
                             (4, names[1] if names and len(names) > 1 else None)):
        if not printed_name:
            continue
        # the header truncates a tee name to four characters (esc(fl[:4])), so match on that prefix
        matches = [c for c in cols if c[:4] == printed_name[:4]]
        if len(matches) != 1:
            problems.append(f"{where}: the printed column {printed_name!r} matches {matches} in "
                            f"hole_cols -- it cannot be tied back to exactly one tee")
            continue
        col = matches[0]
        i = cols.index(col)
        from_record = sum(holes[str(h)][2 + i] for h in nums)
        if tot_r[ci] != from_record:
            problems.append(f"{where}: {col} Tot prints {tot_r[ci]} but course.json's per-hole rows "
                            f"sum to {from_record} -- the book is stale against the record, or the "
                            f"record was edited without a rebuild")
        published = (by_name.get(col) or {}).get("yards")
        if published is not None and published != from_record:
            problems.append(f"{where}: {col} rows sum to {from_record} but tees[] publishes "
                            f"{published}")
        checked += 1
    # par, which has no tee column and is the sum this project has already had wrong once
    if tot_r[1] is not None and "par" in j and tot_r[1] != j["par"]:
        problems.append(f"{where}: the card prints par {tot_r[1]}, the record says {j['par']}")
    checked += 1
    return problems, checked


def test_every_printed_total_is_the_record_it_was_built_from():
    """The page against the file: printed Tot == per-hole sum in course.json == `tees[].yards`.

    Three numbers that must be one number. The middle one is what test_phase1_regressions._check_course
    already ties to the third; this adds the FIRST, which is the only one a reader ever sees. A book
    left unbuilt after a yardage correction is exactly the state this catches, and it is a state this
    repo reaches on purpose -- the corpus is rebuilt in one pass after a round of data fixes, so
    between those two moments the record and the page disagree and something has to say so.
    """
    books = _books()
    if not books:
        pytest.skip("no built book on disk (courses/ is gitignored): nothing to grade")
    by_slug = dict(_records())
    problems, checked = [], 0
    for slug, edition, html in books:
        names, rows = scorecard_rows(html)
        p, n = page_vs_record(f"{slug}/{edition}", names, rows, by_slug[slug])
        problems += p
        checked += n
    assert checked >= len(books), f"only {checked} column(s) tied back to a record"
    assert not problems, ("the printed card and the record it came from disagree:\n  "
                          + "\n  ".join(problems))


def test_the_page_versus_record_grader_bites_on_a_stale_book():
    """Red before green: a record whose per-hole rows no longer sum to what the page prints.

    Composed rather than taken off disk, because the failure being demonstrated is a book that is stale
    against its record -- and producing one on disk would mean either rewriting a book or rewriting the
    only copy of a hand-transcribed scorecard. The three disagreements are separated so a single
    over-broad message cannot satisfy all of them.
    """
    j = {"par": 8, "hole_cols": ["par", "mens_hcp", "Black", "White"],
         "holes": {"1": [4, 1, 400, 300], "2": [4, 2, 400, 300]},
         "tees": [{"name": "Black", "yards": 800}, {"name": "White", "yards": 600}]}
    names = ["Black", "White"]
    ok = [("1", 4, 1, 400, 300), ("2", 4, 2, 400, 300), ("Tot", 8, None, 800, 600)]
    assert page_vs_record("clean", names, ok, j) == ([], 3), page_vs_record("clean", names, ok, j)

    stale = [("1", 4, 1, 400, 300), ("2", 4, 2, 400, 300), ("Tot", 8, None, 807, 600)]
    p, _ = page_vs_record("stale", names, stale, j)
    assert any("Black Tot prints 807" in x for x in p), p

    wrong_par = [("1", 4, 1, 400, 300), ("2", 4, 2, 400, 300), ("Tot", 9, None, 800, 600)]
    p, _ = page_vs_record("par", names, wrong_par, j)
    assert any("prints par 9" in x for x in p), p

    # and the record's own tees[] disagreeing with its own rows, which the page cannot reveal
    bad_record = dict(j, tees=[{"name": "Black", "yards": 807}, {"name": "White", "yards": 600}])
    p, _ = page_vs_record("record", names, ok, bad_record)
    assert any("tees[] publishes 807" in x for x in p), p

    # a printed column that cannot be tied to exactly one tee must say so rather than pass quietly
    ambiguous = dict(j, hole_cols=["par", "mens_hcp", "BlackA", "Blackb"],
                     holes={"1": [4, 1, 400, 300], "2": [4, 2, 400, 300]})
    p, _ = page_vs_record("ambiguous", ["Blac", "Blac"], ok, ambiguous)
    assert any("cannot be tied back to exactly one tee" in x for x in p), p


# ---------------------------------------------------------------------------
# 2. a rating and a slope are ONE measurement -- and the prose has to know it
# ---------------------------------------------------------------------------
def half_sourced(tees):
    """Tees publishing exactly ONE of {rating, slope}. Pure, so it can be attacked directly.

    Either direction is half a measurement. A slope beside a withheld rating is the shape micke-grove
    shipped and is the more dangerous one -- a junior computes a course handicap from index x slope /
    113 and never touches the rating, so the number is USED -- which is why config.slopes_without_a
    _rating and tests/test_r14_tees.py exist for it specifically, with a documented `slope_source`
    escape hatch. This predicate is the symmetric statement and is deliberately NOT the hatch's judge:
    it reports the pair as incomplete either way, and the caller below honours the hatch. A rating with
    no slope is not dangerous in the same way, but it is still half of one USGA measurement of one tee
    for one gender, and a record that publishes it without saying which half is missing is a record
    that cannot be checked.
    """
    out = []
    for t in (tees or []):
        r, s = t.get("rating"), t.get("slope")
        if (r is None) != (s is None):
            out.append((t.get("name"), "slope without a rating" if r is None
                        else "rating without a slope"))
    return out


def test_no_tee_in_the_corpus_publishes_half_a_rating_measurement():
    """Every rated tee on disk carries BOTH halves, or neither, or names where the lone half came from.

    The hatch is honoured exactly as config.slopes_without_a_rating defines it, by asking that module
    rather than restating the rule -- a second spelling of "is this sourced?" is how the corpus ended
    up with `rating_is_womens` as real vocabulary set on no tee at all.
    """
    records = _records()
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    import config
    problems, tees_seen, pairs, excused_seen = [], 0, 0, 0
    for slug, j in records:
        tees = j.get("tees") or []
        tees_seen += len(tees)
        pairs += sum(1 for t in tees if t.get("rating") is not None and t.get("slope") is not None)
        # A slope printed beside a withheld rating is excused ONLY by a recorded slope_source, and
        # config.slopes_without_a_rating is the one place that judgement lives -- it returns the tees
        # NOT excused, so the excused ones are the difference.
        unsourced = {id(t) for t in config.slopes_without_a_rating(tees)}
        excused = {t.get("name") for t in tees
                   if t.get("rating") is None and t.get("slope") is not None
                   and id(t) not in unsourced}
        excused_seen += len(excused)
        for name, how in half_sourced(tees):
            if name in excused:
                continue                                 # a recorded slope_source answers for it
            problems.append(f"{slug}: {name} publishes {how}")
    assert tees_seen >= len(records), \
        f"{len(records)} record(s) but only {tees_seen} tee(s) -- nothing was graded"
    assert pairs > 0, "no course on disk publishes a complete rating/slope pair -- nothing was graded"
    assert not problems, (
        "a rating and a slope are one USGA measurement of one tee for one gender, so a tee must "
        "publish both or neither:\n  " + "\n  ".join(problems))


def test_the_half_pair_predicate_names_both_directions_and_nothing_else():
    """Red before green for `half_sourced`, and the rows it must stay silent about.

    The dangerous direction (a slope beside a withheld rating) is micke-grove's shipped defect and is
    already refused in the data by tests/test_r14_tees.py; this predicate is the symmetric statement,
    so both directions are graded here and the three legitimate shapes are graded too. Without the
    negative half, `lambda tees: [(t["name"], "half") for t in tees]` would pass the positive half.
    """
    assert [n for n, _ in half_sourced([{"name": "Red", "rating": None, "slope": 116}])] == ["Red"]
    assert [n for n, _ in half_sourced([{"name": "Red", "rating": 68.0, "slope": None}])] == ["Red"]
    assert "slope without a rating" in half_sourced([{"name": "R", "rating": None, "slope": 1}])[0][1]
    assert "rating without a slope" in half_sourced([{"name": "R", "rating": 1.0, "slope": None}])[0][1]
    # a whole pair, both halves refused, and both keys simply absent are all fine -- the last is how a
    # tee with no published rating at all is written by hand
    assert half_sourced([{"name": "Blue", "rating": 72.3, "slope": 126}]) == []
    assert half_sourced([{"name": "Red", "rating": None, "slope": None}]) == []
    assert half_sourced([{"name": "Red", "yards": 5286}]) == []
    assert half_sourced([]) == [] and half_sourced(None) == []


def test_a_record_that_says_nothing_is_withheld_is_telling_the_truth():
    """The prose against the data. legal/03 reproduces `sources.rating` verbatim, so it has to be true.

    Two directions, because both are a lie of the same size:
      * a record asserting that no rating or slope is withheld, beside a tee that withholds one;
      * a tee withholding one, beside a rating note that never mentions it.
    The first is the one a reader is misled by; the second is the one that lets the first happen next
    time. micke-grove is the course that pays for this rule -- its Red row withholds BOTH halves on
    purpose, and its record has to keep saying so.
    """
    records = _records()
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    said_something, problems = 0, []
    for slug, j in records:
        tees = j.get("tees") or []
        prose = " ".join(str(v) for v in (j.get("sources") or {}).values())
        withheld = [t.get("name") for t in tees
                    if t.get("rating") is None or t.get("slope") is None]
        claims_none = re.search(
            r"no\s+(?:rating|course\s+rating)\s+or\s+slope\s+is\s+withheld"
            r"|(?:all|every)\s+\w+\s+(?:men's\s+)?pairs?\s+(?:are|is)\s+published", prose, re.I)
        if claims_none:
            said_something += 1
            if withheld:
                problems.append(f"{slug}: the record says no rating or slope is withheld, but "
                                f"{withheld} withhold(s) one")
        if withheld:
            said_something += 1
            # the record must name the withholding somewhere, in whatever words it uses for it
            if not re.search(r"withh(?:eld|olds|olding)|not\s+published|deliberately\s+(?:dropped|"
                             r"not\s+used)|left\s+null|refused", prose, re.I):
                problems.append(f"{slug}: {withheld} withhold(s) a rating or slope and no source note "
                                f"mentions a withheld figure at all")
    assert said_something > 0, (
        "no record in this corpus either claims a complete set of pairs or withholds one, so this "
        "grader read nothing")
    assert not problems, ("a course record's prose about withheld ratings does not match its own "
                          "tees:\n  " + "\n  ".join(problems))


# ---------------------------------------------------------------------------
# 3. yards per rating stroke between adjacent tees
# ---------------------------------------------------------------------------
def yards_per_rating_stroke(j):
    """[(long tee, short tee, yd per rating stroke)] for adjacent rated tees, longest first.

    A tee flagged `rating_is_womens` is excluded from BOTH pairs it touches: a women's rating in the
    ladder is real data (it is higher than the men's rating of a longer tee) and differencing across it
    measures nothing. That is the same waiver test_phase1_regressions._check_course grants its
    monotonicity check, asked for the same reason.
    """
    tees = j.get("tees") or []
    womens = {t["name"] for t in tees if t.get("rating_is_womens")}
    rated = sorted(((t["yards"], t["rating"], t["name"]) for t in tees
                    if t.get("rating") is not None and t.get("yards") is not None), reverse=True)
    out = []
    for a, b in zip(rated, rated[1:]):
        if a[2] in womens or b[2] in womens:
            continue
        dr = a[1] - b[1]
        if dr <= 0:
            continue                       # not a fall in rating: _check_course's monotonicity check
        out.append((a[2], b[2], (a[0] - b[0]) / dr))
    return out


def test_no_adjacent_tee_pair_implies_an_impossible_yards_per_rating_stroke():
    """A rating stroke costs a plausible number of yards, or the pair is a transcription error.

    THE DISCRIMINATING CASE, and it is a real refusal rather than a hypothetical: one course's 2012
    printed card puts 7242 yd against the same 75.0 Course Rating that the published men's figures pair
    with 6871. Differenced against the tee below it that card's back row implies 328 yd per stroke,
    which is how the row was caught and the card set aside. 328 is refused by this band; every one of
    the 45 adjacent pairs this corpus actually publishes is inside it.
    """
    records = _records()
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    pairs, problems = [], []
    for slug, j in records:
        for a, b, v in yards_per_rating_stroke(j):
            pairs.append((v, slug, a, b))
            if not (BAND_LO <= v <= BAND_HI):
                problems.append(f"{slug}: {a} -> {b} implies {v:.1f} yd per rating stroke, outside "
                                f"{BAND_LO:g}-{BAND_HI:g}")
    assert len(pairs) >= 2 * len(records), (
        f"{len(records)} record(s) produced only {len(pairs)} adjacent rated pair(s) -- a corpus of "
        f"single-tee courses would satisfy this check while grading nothing")
    assert not problems, (
        "an adjacent tee pair implies an impossible number of yards per stroke of Course Rating, "
        "which is how a back row transcribed from the wrong card is caught:\n  "
        + "\n  ".join(problems))


def test_the_band_is_wide_enough_for_the_corpus_and_tight_enough_to_refuse_328():
    """Both edges of the band, measured. A band that refuses nothing is not a check.

    The lower edge is graded against the corpus itself rather than a remembered number, so a course
    added next month whose published figures sit under BAND_LO reports HERE -- as "the band needs
    widening, and here is by how much" -- instead of turning the grader above into a false alarm about
    a transcription error that did not happen.
    """
    records = _records()
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    vals = [v for _, j in records for _, _, v in yards_per_rating_stroke(j)]
    assert vals, "no adjacent rated pair in the corpus -- the band is graded against nothing"
    lo, hi = min(vals), max(vals)
    assert BAND_LO <= lo and hi <= BAND_HI, (
        f"the corpus spans {lo:.1f}-{hi:.1f} yd per rating stroke and the band is "
        f"{BAND_LO:g}-{BAND_HI:g}: real published figures fall outside it, so widen the band rather "
        f"than letting it call them errors")
    # ...and it must still refuse the shape it exists for. Driven through the same function, on a
    # fixture rather than on a file, so the refusal is reproducible without a bad card on disk.
    refused = yards_per_rating_stroke({
        "tees": [{"name": "Back", "yards": 7242, "rating": 75.0, "slope": 144},
                 {"name": "Next", "yards": 6289, "rating": 72.1, "slope": 137}]})
    assert len(refused) == 1, refused
    assert abs(refused[0][2] - REFUSED_YD_PER_STROKE) < 1.0, (
        f"the refused 2012 back row should imply ~{REFUSED_YD_PER_STROKE:g} yd per stroke, "
        f"this fixture gives {refused[0][2]:.1f}")
    assert not (BAND_LO <= refused[0][2] <= BAND_HI), (
        f"the band {BAND_LO:g}-{BAND_HI:g} ACCEPTS {refused[0][2]:.1f} yd per rating stroke, which is "
        f"the row it exists to refuse -- it has been widened past the point of being a check")
    # and the band is not so wide it would accept anything: a doubled yardage must still fail
    wide = yards_per_rating_stroke({
        "tees": [{"name": "Back", "yards": 7000, "rating": 74.0},
                 {"name": "Next", "yards": 6000, "rating": 73.0}]})
    assert wide and not (BAND_LO <= wide[0][2] <= BAND_HI), \
        f"1000 yd for one rating stroke is inside the band: {wide}"


def test_a_band_quoted_in_a_record_covers_what_the_corpus_actually_produces():
    """A bar used to REJECT a source must be one this project's own data passes.

    THE DEFECT THIS CATCHES. A record rejected a printed card because its back row implied 328 yd per
    stroke "against a normal 190-265". The rejection is correct; the bar was not measured. Five
    adjacent pairs of published USGA figures in this very corpus sit outside 190-265, so quoting it as
    "normal" states a rule the books beside it break -- and legal/03 reproduces the sentence. A quoted
    band therefore has to contain the corpus, exactly like the band this file enforces.

    Narrow on purpose: only a two-number range sitting within eighty characters of a rating-stroke
    phrase is read as a band, so an unrelated hyphenated pair elsewhere in the same note is not.
    """
    records = _records()
    if not records:
        pytest.skip("no course records on disk (courses/ is gitignored): nothing to grade")
    vals = [v for _, j in records for _, _, v in yards_per_rating_stroke(j)]
    assert vals, "no adjacent rated pair in the corpus"
    lo, hi = min(vals), max(vals)
    quoted, problems = 0, []
    for slug, j in records:
        prose = " ".join(str(v) for v in (j.get("sources") or {}).values())
        for m in QUOTED_BAND.finditer(prose):
            g = [x for x in m.groups() if x is not None]
            if len(g) != 2:
                continue
            qlo, qhi = float(g[0]), float(g[1])
            if qhi <= qlo:
                continue
            quoted += 1
            if qlo > lo or qhi < hi:
                problems.append(
                    f"{slug}: the record quotes {qlo:g}-{qhi:g} yd per rating stroke as the normal "
                    f"range, but this corpus spans {lo:.1f}-{hi:.1f} -- "
                    f"{sum(1 for v in vals if not (qlo <= v <= qhi))} of {len(vals)} published "
                    f"adjacent pairs fall outside the bar the record judges a source by")
    if not quoted:
        pytest.skip("no course record quotes a yards-per-rating-stroke band; nothing to check "
                    "against the corpus")
    assert not problems, ("a record judges a source against a band its own corpus fails:\n  "
                          + "\n  ".join(problems))
