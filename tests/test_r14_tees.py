#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The slope column, which nothing graded.

THE DEFECT: micke-grove's Red row shipped as `Red | 5286 | -- | 116`. The em-dash is deliberate and
documented -- legal/03 records that the card's 70.0/116 under Red is the WOMEN'S pair (the row beneath
it on the printed card is 'Ladies' Handicap'; a 5286-yd tee cannot rate 70.0 where 6026 rates 68.5) and
that printing the rating "would inflate a boy's handicap differential by ~5 strokes". The 70.0 was
dropped from course.json. The 116 from the SAME pair was kept, in a column whose other two rows are
men's slopes (126, 122), with nothing marking the difference, beside a guide card whose only gender
statement is "HCP = the men's stroke index". A junior computing a course handicap off that row
(index x slope / 113) used a women's slope, and no men's Red slope is published anywhere.

WHY IT SURVIVED: the whole suite's only tee check was rating MONOTONICITY
(test_phase1_regressions._check_course), which reads `rating` and never `slope`. And 116 sits almost
exactly on the men's linear extrapolation -- 126 @ 6565 and 122 @ 6026 give ~116.5 @ 5286 -- so the
unsupported number and the supported one look alike. That is the reason a check is needed rather than
an eye: plausibility was the camouflage.

Four graders, deliberately at different levels, because a defect of this shape can hide from any one
of them:
  * the predicate itself (pure, always runs) -- including the two ways an escape hatch goes wrong;
  * every course record on disk (the class, corpus-wide -- not a micke-grove assertion);
  * the ENGINE's refusal, exercised through a real `import config` in a subprocess, so a predicate that
    got defined but never wired cannot pass;
  * the SHIPPED BOOK's own tees table, because a source-level check alone stays green while the book on
    disk still prints the number a reader actually holds.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The tees card as generate.tees_panel emits it: one <table class="tt">, a header row marked
# class="th", then one row per entry of course.json's "tees" -- tee, yards, rating, slope. A tee with
# no per-hole column carries a dagger superscript inside its name cell (philadelphia's Green,
# the-reserve's two combination tees), so the name is matched loosely and the CELLS are what is graded.
TT_TABLE = re.compile(r'<table class="tt">(.*?)</table>', re.S)
TT_ROW = re.compile(r'<tr(?! class="th")[^>]*>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*'
                    r'<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', re.S)
EM_DASH = "&mdash;"


def _course_records():
    """(slug, parsed course.json) for every real course on disk, scratch slugs excluded.

    Uses distribution.is_corpus_slug -- this repo's single spelling of "a course, or somebody's
    scratch?" -- rather than a fifth local startswith("_"), which is drift conftest._classify already
    names. Enumerated from the FILESYSTEM and not from test_phase1_regressions.CORPUS on purpose:
    CORPUS additionally requires OSM geometry, and poppy-ridge (yardage mode, blank greens, no
    osm_*.json) has a published tees card like every other book. The one course least like the others
    was outside the reach of every corpus test in that file until _books() was added for the same reason.
    """
    import distribution
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if not distribution.is_corpus_slug(slug):
            continue
        with open(cj, encoding="utf-8") as f:
            out.append((slug, json.load(f)))
    return out


def _books():
    """Every shipped book HTML: greenbook.html AND greenbook_coach.html, scratch slugs excluded.

    The coach edition drops the tees card outright (generate.py builds it without that panel so the
    sheet has no trailing blank page), so it contributes no rows -- but it is globbed rather than
    assumed, because "the file nothing looked at" is the shape of every finding in this round.
    """
    import distribution
    out = []
    for h in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook*.html"))):
        slug = os.path.basename(os.path.dirname(h))
        if distribution.is_corpus_slug(slug):
            out.append((slug, h))
    return out


def _predicate():
    """config.slopes_without_a_rating, imported without caring which course config is bound to.

    conftest's autouse fixture binds COURSE to a real slug, so this import is the ordinary one every
    engine module does. The function is pure, so the binding cannot affect the answer.
    """
    import config
    return config.slopes_without_a_rating


def _fixture_course(tees):
    """A minimal but genuinely valid course.json carrying `tees`. Two holes, two tee columns."""
    return {
        "name": "Half Pair Test Course",
        "address": "1 Fixture Rd, Nowhere, ST 00000",
        "par": 8,
        "hole_cols": ["par", "mens_hcp", "Blue", "Red"],
        "holes": {"1": [4, 1, 400, 300], "2": [4, 2, 400, 300]},
        "tees": tees,
    }


# ---------------------------------------------------------------------------
# 1. the predicate itself -- runs with no course data at all
# ---------------------------------------------------------------------------
def test_the_predicate_names_a_withheld_rating_that_kept_its_slope():
    """The exact shape micke-grove shipped, plus the rows that must NOT be flagged."""
    half = _predicate()
    caught = half([
        {"name": "Blue", "yards": 6565, "rating": 72.3, "slope": 126},   # a whole pair: fine
        {"name": "White", "yards": 6026, "rating": 68.5, "slope": 122},  # a whole pair: fine
        {"name": "Red", "yards": 5286, "rating": None, "slope": 116},    # HALF a refused pair
    ])
    assert [t["name"] for t in caught] == ["Red"], caught
    # Both halves refused is the fix, not another violation.
    assert half([{"name": "Red", "yards": 5286, "rating": None, "slope": None}]) == []
    # A slope withheld while the rating prints is a different thing and not this check's business:
    # nothing there is attributed to a source it did not come from.
    assert half([{"name": "Red", "yards": 5286, "rating": 68.0, "slope": None}]) == []
    # Absent keys read as absent values, not as KeyError -- course.json is hand-typed and omitting
    # both is how a tee with no published rating at all is written.
    assert half([{"name": "Red", "yards": 5286}]) == []
    assert half([]) == [] and half(None) == []


def test_the_escape_hatch_demands_a_source_and_not_a_flag():
    """A men's slope may legitimately exist where a men's rating is not published -- but then WHERE it
    came from has to be on the record, because legal/03 has to answer for every number in the book.

    Both failure modes of a hatch are graded here. A bare truthy flag would let the next person silence
    the check by asserting exactly the thing it asks them to evidence -- that is how `rating_is_womens`
    ended up being real vocabulary set on no tee in the entire corpus. And an EMPTY or whitespace
    string is what a half-finished edit leaves behind; reading it as evidence would make the hatch
    wider than the flag it replaced.

    THE DEFECT THIS TEST'S OWN NAME ASSERTED AND DID NOT GRADE. The guard shipped as
    `not str(t.get("slope_source") or "").strip()`, and `str(True)` is "True" -- four non-characters
    long, non-empty, and therefore a "source". Measured on the unfixed guard, every one of these
    SILENCED it: True, 1, "x", "true", ["a publication"], {"db": "a publication"}, 3.14. The test
    asserted in its title that a flag would not do and then graded only "", "   ", "\\n" and None -- the
    four values a bare `or ""` already handled. So the hatch it was written to keep narrow was, in fact,
    exactly the bare boolean its own docstring says is how `rating_is_womens` came to exist.
    """
    half = _predicate()
    sourced = {"name": "Red", "yards": 5286, "rating": None, "slope": 112,
               "slope_source": "a publication's course-rating DB, men's Red 5286"}
    assert half([sourced]) == [], "a recorded men's slope source must let the number print"
    # A bare URL is one token and no prose, and is a perfectly good answer to "where did this come
    # from?" -- so whatever the bar is, it must not be "must read like a sentence".
    assert half([dict(sourced, slope_source="https://example.org/course-rating?id=1234")]) == [], \
        "a URL is a recorded source"
    refused = [
        # a half-finished edit
        "", "   ", "\n", None,
        # ASSERTION IN PLACE OF EVIDENCE -- the shape this hatch exists to refuse
        True, 1, "true", "TRUE", "yes",
        # not a string at all: a container or a number cannot say where a number came from
        ["a publication"], {"db": "a publication"}, 3.14, 0, False, [],
        # a string, but too short to name a publication, a tee and a value
        "x", "?", "-", "n/a", "TBD", "ok", "unknown",
    ]
    for v in refused:
        assert [t["name"] for t in half([dict(sourced, slope_source=v)])] == ["Red"], (
            f"slope_source={v!r} is not a source, and must not silence the check")


# ---------------------------------------------------------------------------
# 2. the class, over every course record on disk
# ---------------------------------------------------------------------------
def test_no_course_record_prints_a_slope_whose_rating_was_withheld():
    """THE DISCRIMINATING TEST. Red on the unfixed corpus:

        micke-grove-golf-links: Red (5286 yd) withholds its rating but prints slope 116

    A class check over whatever corpus is present, never an assertion about one slug, so a course added
    next month cannot reintroduce it. Skips on a fresh clone -- courses/ is gitignored -- and proves it
    examined something first, because a corpus test that enumerated nothing is the vacuous pass this
    campaign keeps finding.
    """
    records = _course_records()
    if not records:
        pytest.skip("per-course data is gitignored; no course.json on disk to check")
    half = _predicate()
    tees_seen, rated, bad = 0, 0, []
    for slug, j in records:
        tees = j.get("tees") or []
        tees_seen += len(tees)
        rated += sum(1 for t in tees if t.get("slope") is not None)
        bad += [f"{slug}: {t.get('name')} ({t.get('yards')} yd) withholds its rating but prints "
                f"slope {t.get('slope')}" for t in half(tees)]
    # NON-VACUITY, and not merely "we opened some files": a corpus of tee lists that all happened to be
    # empty, or that published no slopes at all, would satisfy this check while grading nothing. Both
    # populations are counted, and both have to be non-empty for the assertion below to mean anything.
    assert tees_seen >= len(records), \
        f"{len(records)} course record(s) but only {tees_seen} tee(s) -- nothing was graded"
    assert rated > 0, "no course on disk publishes a slope at all -- this check graded nothing"
    assert not bad, (
        "a rating and a slope are ONE USGA measurement of one tee for one gender, so a withheld "
        "rating must withhold its slope too:\n  " + "\n  ".join(bad))


def test_the_shipped_template_has_no_half_pair():
    """examples/course.json is what a stranger copies, and its own _README already warns that a second
    copy of the card can "list a WOMEN'S rating in a men's column" and says to "leave a value null
    rather than guess". The template must not itself demonstrate the defect. Runs on a fresh clone:
    examples/ is in git."""
    p = os.path.join(ROOT, "examples", "course.json")
    if not os.path.exists(p):
        pytest.skip("no examples/course.json")
    with open(p, encoding="utf-8") as f:
        tees = json.load(f).get("tees") or []
    assert tees, "the template publishes no tees -- there is nothing here to copy or to grade"
    assert _predicate()(tees) == [], "the template a stranger copies ships half a refused pair"


# ---------------------------------------------------------------------------
# 3. the engine's refusal, wired -- a defined-but-uncalled predicate must not pass
# ---------------------------------------------------------------------------
def _import_config_for(slug):
    """`import config` bound to `slug`, in a subprocess. Returns (returncode, stdout+stderr)."""
    env = dict(os.environ, COURSE=slug, QUIET_TEE_CHECK="1")
    r = subprocess.run([sys.executable, "-c", "import config"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_the_engine_refuses_to_build_a_book_from_a_half_pair(tmp_path):
    """The guard has to be CALLED, not just callable.

    Graded through a real `import config`, which is the one thing every stage of the pipeline does --
    generate.py, render_hole.py, fetch_*.py -- so a refusal here is a refusal to build the book. A
    source-level assertion that the predicate exists would have passed on a `def` nothing invoked,
    which is the "one declaration, zero uses" shape this repo has already found inert twice.

    The fixture lives at courses/_r14_tees_halfpair/ because config.py resolves COURSE under courses/
    and nowhere else; conftest's deletion guard permits an underscore-prefixed scratch slug, and every
    tool and corpus enumerator skips one, so it is invisible to anything else while it exists.
    """
    slug = "_r14_tees_halfpair"
    d = os.path.join(ROOT, "courses", slug)
    assert not os.path.exists(d), f"{d} already exists -- refusing to overwrite it"
    os.makedirs(d)
    try:
        cj = os.path.join(d, "course.json")

        def write(tees):
            with open(cj, "w", encoding="utf-8") as f:
                json.dump(_fixture_course(tees), f)

        whole = {"name": "Blue", "yards": 800, "rating": 70.0, "slope": 126}
        # (i) a half pair must stop the build, and say which tee and how to fix it
        write([whole, {"name": "Red", "yards": 600, "rating": None, "slope": 116}])
        rc, out = _import_config_for(slug)
        assert rc != 0, f"the engine BUILT a book from a half-refused rating pair:\n{out}"
        assert "Red" in out and "116" in out, f"the refusal must name the tee and its slope:\n{out}"
        assert "slope_source" in out, f"the refusal must say how to proceed legitimately:\n{out}"
        # (ii) refusing both halves builds
        write([whole, {"name": "Red", "yards": 600, "rating": None, "slope": None}])
        rc, out = _import_config_for(slug)
        assert rc == 0, f"withholding BOTH halves is the fix and must build:\n{out}"
        # (iii) so does a recorded men's slope source
        write([whole, {"name": "Red", "yards": 600, "rating": None, "slope": 112,
                       "slope_source": "a publication's course-rating DB, men's Red 600"}])
        rc, out = _import_config_for(slug)
        assert rc == 0, f"a recorded men's slope source must be allowed to print:\n{out}"
    finally:
        shutil.rmtree(d)


def test_a_malformed_tees_value_is_refused_by_name_and_not_by_traceback():
    """A hand-typed `"tees"` of the wrong SHAPE must refuse like every other bad course.json here.

    The half-pair guard above is the first thing in the engine that reaches INSIDE each tee object, and
    it made three shapes reachable that used to import cleanly (`tees` was only ever iterated by
    generate.tees_panel, which no `import config` runs). Measured on the unfixed guard, all three died
    inside a list comprehension in config.py with

        AttributeError: 'str' object has no attribute 'get'

    naming neither the file nor the key -- against this file's own convention, which is the one config.py
    states four times over: a missing course.json, a missing required key, a short scorecard row and a
    half-refused rating pair all name `courses/<slug>/course.json`, say what is wrong, and point at
    examples/course.json. courses/ is gitignored and hand-edited, so the file that is wrong is the file
    the reader has to be sent to.

    Not a false positive against anything real: no course on disk and not the shipped template carries
    these shapes (test_no_course_record_prints_a_slope_whose_rating_was_withheld reads every one).
    """
    slug = "_r14_tees_malformed"
    d = os.path.join(ROOT, "courses", slug)
    assert not os.path.exists(d), f"{d} already exists -- refusing to overwrite it"
    os.makedirs(d)
    try:
        cj = os.path.join(d, "course.json")
        shapes = {
            "a bare string inside the tees list": ["Blue"],
            "tees as a dict of name -> yardage": {"Blue": 6565},
            "tees as a string": "Blue",
            "a null inside the tees list": [None],
            "a number inside the tees list": [{"name": "Blue", "slope": 126, "rating": 72.3}, 126],
        }
        for what, tees in shapes.items():
            with open(cj, "w", encoding="utf-8") as f:
                json.dump(_fixture_course(tees), f)
            rc, out = _import_config_for(slug)
            assert rc != 0, f"{what}: the engine imported a malformed \"tees\" without complaint:\n{out}"
            assert "Traceback" not in out and "AttributeError" not in out, (
                f"{what}: a hand-edit error came back as an interpreter traceback rather than a named "
                f"refusal:\n{out}")
            assert f"courses/{slug}/course.json" in out, (
                f"{what}: the refusal does not name the file that is wrong:\n{out}")
            assert "tees" in out, f"{what}: the refusal does not name the key that is wrong:\n{out}"
            assert "examples/course.json" in out, (
                f"{what}: the refusal does not point at the template, as config.py's other four "
                f"refusals do:\n{out}")
        # ...and the well-formed shape those five are contrasted with still builds, so this is a check
        # on the SHAPE and not a new obstacle in front of a valid record.
        with open(cj, "w", encoding="utf-8") as f:
            json.dump(_fixture_course([{"name": "Blue", "yards": 800, "rating": 70.0, "slope": 126},
                                       {"name": "Red", "yards": 600, "rating": None, "slope": None}]), f)
        rc, out = _import_config_for(slug)
        assert rc == 0, f"a well-formed tees list must import:\n{out}"
        # An ABSENT "tees" is legitimate -- config.py defaults it to [] and the panel prints no card.
        j = _fixture_course([])
        j.pop("tees")
        with open(cj, "w", encoding="utf-8") as f:
            json.dump(j, f)
        rc, out = _import_config_for(slug)
        assert rc == 0, f"a course record with no \"tees\" at all must still import:\n{out}"
    finally:
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# 4. the artifact -- what a reader actually holds
# ---------------------------------------------------------------------------
def test_the_printed_tees_card_never_shows_a_slope_beside_a_withheld_rating():
    """The book on disk, not the record it was built from.

    Red on the unfixed corpus: micke-grove-golf-links prints
        <tr><td>Red</td><td>5286</td><td>&mdash;</td><td>116</td></tr>

    This grader is the one that cannot be satisfied by a data fix alone: course.json could say null
    while the shipped HTML beside it still prints 116, and every source-level check in the suite would
    stay green. Both directions are graded -- no em-dash rating beside a printed slope in the artifact,
    and every rating course.json withholds actually reaching the page as an em-dash.
    """
    books = _books()
    if not books:
        pytest.skip("per-course data is gitignored; no built book on disk to measure")
    records = dict(_course_records())
    rows_seen, tables, bad = 0, 0, []
    for slug, path in books:
        with open(path, encoding="utf-8") as f:
            html = f.read()
        for body in TT_TABLE.findall(html):
            tables += 1
            rows = TT_ROW.findall(body)
            # The panel emits exactly one row per published tee. Comparing the count against
            # course.json ties this measurement to the record AND catches a book built before a tee was
            # added or removed -- without it, a parser that silently matched zero rows would pass.
            want = len(records.get(slug, {}).get("tees") or [])
            assert len(rows) == want, (
                f"{os.path.relpath(path, ROOT)}: the tees card prints {len(rows)} row(s) but "
                f"course.json publishes {want} tee(s) -- stale book or a parser that missed rows")
            for tee, yds, rate, slp in rows:
                rows_seen += 1
                if rate.strip() == EM_DASH and slp.strip() != EM_DASH:
                    bad.append(f"{os.path.relpath(path, ROOT)}: {tee.strip()} ({yds.strip()} yd) "
                               f"prints slope {slp.strip()} beside a withheld rating")
        # ...and the refusal recorded in the data has to survive the build.
        for t in records.get(slug, {}).get("tees") or []:
            if t.get("rating") is not None:
                continue
            printed = [r for body in TT_TABLE.findall(html) for r in TT_ROW.findall(body)
                       if r[0].split("<")[0].strip() == str(t.get("name"))[:12]]
            for _tee, _yds, rate, _slp in printed:
                assert rate.strip() == EM_DASH, (
                    f"{os.path.relpath(path, ROOT)}: course.json withholds {t.get('name')}'s rating "
                    f"but the book prints {rate.strip()} -- the book is stale")
    # Non-vacuity, counted from a DIFFERENT enumerator than the loop above: every course record with a
    # built greenbook.html must have contributed a tees table, so a regex that stopped matching cannot
    # read as "no violations".
    want_tables = sum(1 for slug in records
                      if os.path.exists(os.path.join(ROOT, "courses", slug, "greenbook.html")))
    assert tables == want_tables, (
        f"measured {tables} tees card(s) but {want_tables} built book(s) publish one")
    assert rows_seen >= tables, f"{tables} tees card(s) yielded only {rows_seen} row(s)"
    assert not bad, "the printed card shows a slope its rating was refused for:\n  " + "\n  ".join(bad)
