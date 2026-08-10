#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Shared course config for the green-book engine.

The engine (fetch_*.py, render_*.py, generate.py) is course-agnostic. Pick which
course to build with the COURSE env var (defaults to the first one we built):

    COURSE=the-reserve-at-spanos-park python3 generate.py

Each course lives in courses/<slug>/ with a course.json describing it and holds
that course's cached data (osm_*.json, laz/, dem_hd/) and outputs (greenbook.*).
"""
import glob, json, os, sys

import distribution   # for build_mode: one normalised spelling of that read; it must not import config
from lidar_coverage import _env_on   # the project's ONE reading of an escape-hatch key -- see it there

ROOT = os.path.dirname(os.path.abspath(__file__))
SLUG = os.environ.get("COURSE", "the-reserve-at-spanos-park")
COURSE_DIR = os.path.join(ROOT, "courses", SLUG)

BRAND = "Lucas Green Book"   # product/brand name shown on the cover

_CJ = os.path.join(COURSE_DIR, "course.json")
if not os.path.exists(_CJ):
    # courses/ is gitignored (per-course data and generated books stay local), so a fresh clone has
    # no course to build. Say that plainly instead of raising a bare FileNotFoundError.
    _have = sorted(os.path.basename(os.path.dirname(p))
                   for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
    raise SystemExit(
        f"no course.json for COURSE={SLUG!r} (looked in {COURSE_DIR}).\n"
        + (f"  Available locally: {', '.join(_have)}\n"
           f"  Pick one with:     COURSE=<slug> python3 {os.path.basename(sys.argv[0] or 'generate.py')}\n"
           if _have else
           f"  This repo ships the ENGINE only -- courses/ is gitignored, so per-course data and the\n"
           f"  generated books stay local and are never published. To build one:\n"
           f"    mkdir -p courses/my-course\n"
           f"    cp examples/course.json courses/my-course/course.json   # then edit every value\n"
           f"    COURSE=my-course python3 fetch_osm.py                   # see PIPELINE.md\n"))

# encoding="utf-8" on the READ side too: course.json holds hand-typed course names, and five in the
# corpus carry an em-dash. They survive today only because they happen to be written as \u2014
# escapes; a hand-typed one would come back mojibake under a non-utf-8 locale and generate.py's
# _title_lines would stop splitting the cover title on it.
with open(_CJ, encoding="utf-8") as f:
    COURSE = json.load(f)

# ---- physical card + print layout (inches) -------------------------------
# Card trim size = the finished page that slips into a back-pocket yardage-book
# cover. 3.5 x 5.0 fits standard covers and is well under the Rule 4.3 cap
# (4.25 x 7). Override per course in course.json via "card":{"w":..,"h":..}.
# Engine defaults, named so a tool checking OTHER courses can fall back to them instead of to
# whatever course this module happens to be bound to. tools/check_scale.py used config.CARD_W_IN as
# the default when a course.json had no "card", which meant a scratch course with a 5 x 8 card made
# every other course look 5 x 8 too.
CARD_DEFAULT_W_IN, CARD_DEFAULT_H_IN = 3.5, 5.0
_card = COURSE.get("card", {})
CARD_W_IN = float(_card.get("w", CARD_DEFAULT_W_IN))
CARD_H_IN = float(_card.get("h", CARD_DEFAULT_H_IN))   # 5.0 -> 4 cards (2x2) per US Letter
PAGE_W_IN = float(_card.get("page_w", 8.5))    # print sheet (US Letter portrait)
PAGE_H_IN = float(_card.get("page_h", 11.0))
MARGIN_IN = 0.35
GUTTER_IN = 0.30
COLS = max(1, int((PAGE_W_IN - 2*MARGIN_IN + GUTTER_IN) / (CARD_W_IN + GUTTER_IN)))
ROWS = max(1, int((PAGE_H_IN - 2*MARGIN_IN + GUTTER_IN) / (CARD_H_IN + GUTTER_IN)))
PER = COLS * ROWS

# The four keys below are indexed, not .get() -- they have no sensible default. Name them before
# indexing, because a KeyError traceback is a bad first experience for someone who has just copied
# examples/course.json and renamed a block. Deleting "holes" used to produce a bare
# `KeyError: 'holes'` from this line with nothing pointing at the file or the fix.
_REQUIRED = {
    "name":      'the course name printed on the cover, e.g. "Merion Golf Club — East Course"',
    "address":   'the street address printed under it, e.g. "450 Ardmore Ave, Ardmore, PA 19003"',
    "hole_cols": 'column names for each hole row: ["par", "mens_hcp", then one per tee]',
    "holes":     'the scorecard itself: {"1": [par, mens_hcp, yardage per tee...], "2": [...]}',
}
_missing = [k for k in _REQUIRED if k not in COURSE]
if _missing:
    raise SystemExit(
        f"courses/{SLUG}/course.json is missing {len(_missing)} required key(s):\n"
        + "".join(f'  "{k}" -- {_REQUIRED[k]}\n' for k in _missing)
        + "  Compare against examples/course.json, which documents every field.")

# hole -> (par, mens_hcp, <tee yardages in hole_cols order>)
# EVERY ROW IS AS WIDE AS hole_cols, CHECKED HERE. This was `HOLES = {int(k): tuple(v) ...}` with no
# shape check on the rows at all, and course.json is hand-typed and is the only copy of the transcribed
# scorecard. Every consumer then indexes a row POSITIONALLY by name -- BACK_I, FRONT_I and each entry of
# OTHERS below, plus generate.py's card headline and render_hole's carries, gutters and elevation.
#
# The two failure modes are not equally visible and the quiet one is worse:
#   * a row one value SHORT died later and elsewhere, as a bare `IndexError` out of the
#     _LONGEST_OF_PAIR_IS_SECONDARY sum below, naming neither the course nor the hole -- so the reader
#     starts at a traceback in the engine rather than at the line they mistyped.
#   * a row one value LONG did not fail at all. The extra column is simply never read, and any
#     consumer indexing from the END silently shifts a tee: the card prints one tee's yardage under
#     another tee's label, and the carries and the from-tee gutters are then measured from a tee the
#     player is not standing on. That is exactly the class of wrong number this book exists not to print,
#     and there was nothing between a slipped keystroke and a printed card.
#
# So it is checked beside the transcription, where the file being read is the file that is wrong, and it
# names the course and every offending hole -- a bare "malformed row" leaves 18 of them to search.
_ROW_W = len(COURSE["hole_cols"])
_bad_rows = sorted(((k, len(v)) for k, v in COURSE["holes"].items() if len(v) != _ROW_W),
                   key=lambda kv: (len(kv[0]), kv[0]))
if _bad_rows:
    raise SystemExit(
        f"courses/{SLUG}/course.json: {len(_bad_rows)} scorecard row(s) are not {_ROW_W} values wide.\n"
        f'  "hole_cols" is {COURSE["hole_cols"]}, so every row in "holes" must be par, mens_hcp and one\n'
        f"  yardage per tee, in that order -- {_ROW_W} values.\n"
        + "".join(f"  hole {k}: {n} value(s), {'missing' if n < _ROW_W else 'extra'} "
                  f"{abs(_ROW_W - n)} -- {COURSE['holes'][k]}\n" for k, n in _bad_rows)
        + "  The engine reads these rows by POSITION, so a short or long one prints one tee's yardages\n"
          "  under another tee's label. Fix the transcription against the published scorecard.")
HOLES = {int(k): tuple(v) for k, v in COURSE["holes"].items()}
HOLE_NUMS = sorted(HOLES)                          # actual holes present (9-hole courses have 1..9)
NHOLES = len(HOLE_NUMS)
NAME = COURSE["name"]
ADDRESS = COURSE["address"]
PAR = COURSE.get("par", 72)
# NORMALISED through distribution.build_mode -- see the long note there. Bound raw, a hand-edited
# "Yardage" made generate.py build a full slope book while distribution.py and legal/03 called it
# yardage mode with blank greens: a legal record describing a book that was never made.
BUILD_MODE = distribution.build_mode(COURSE) or "full"   # "full" = slope maps; "yardage" = blank greens

# tee columns (labels) start at index 2 of each hole tuple
TEES = COURSE["hole_cols"][2:]
# `or TEES[x]`, not `.get(k, TEES[x])`: dict.get returns the DEFAULT only when the key is ABSENT,
# and a course.json may carry the key with an explicit null -- which is how the-reserve was written.
# Then SECONDARY became None and TEES.index(None) raised ValueError, so the whole build died on a
# file that is perfectly valid JSON meaning "no preference". A null and a missing key mean the same
# thing here, so treat them the same.
FEATURED = COURSE.get("featured_tee") or TEES[0]
SECONDARY = COURSE.get("secondary_tee") or TEES[-1]
if FEATURED not in TEES:
    raise SystemExit(f"featured_tee {FEATURED!r} is not one of this course's tee columns {TEES}")
if SECONDARY not in TEES:
    raise SystemExit(f"secondary_tee {SECONDARY!r} is not one of this course's tee columns {TEES}")
FI = 2 + TEES.index(FEATURED)                     # featured yardage index
SI = 2 + TEES.index(SECONDARY)                    # secondary yardage index
OTHERS = [(t, 2 + i) for i, t in enumerate(TEES) if t not in (FEATURED, SECONDARY)]
TEE_TABLE = COURSE.get("tees", [])

# "tees" IS A LIST OF OBJECTS, CHECKED HERE, because the guard below is the first thing in the engine
# that reaches INSIDE each entry. Nothing did before it: `tees` was only ever iterated by
# generate.tees_panel, so a malformed one used to import cleanly and go wrong later, in the book. Now a
# bare string in the list, or `tees` written as a dict or a string, dies in a list comprehension in this
# file with `AttributeError: 'str' object has no attribute 'get'` -- naming neither the file nor the key,
# against the convention every other refusal in this module keeps. courses/ is gitignored and hand-typed,
# so the reader has to be sent to the line they mistyped, not to a frame in the engine.
_TEE_SHAPE = ('  Every entry must be an object:\n'
              '    "tees": [{"name": "Blue", "yards": 6565, "rating": 72.3, "slope": 126}, ...]\n'
              '  Use null -- not a missing entry -- for a rating or slope the club does not publish.\n'
              "  Compare against examples/course.json, which documents every field.")
if not isinstance(TEE_TABLE, list):
    raise SystemExit(
        f'courses/{SLUG}/course.json: "tees" is a {type(TEE_TABLE).__name__}, not a list.\n'
        f"  It holds one entry per row of the printed Tees panel, in the order they print.\n"
        + _TEE_SHAPE)
_BAD_TEES = [(i, t) for i, t in enumerate(TEE_TABLE) if not isinstance(t, dict)]
if _BAD_TEES:
    raise SystemExit(
        f'courses/{SLUG}/course.json: {len(_BAD_TEES)} entry(ies) of "tees" are not tee objects.\n'
        + "".join(f"  tees[{i}] is a {type(t).__name__}: {t!r}\n" for i, t in _BAD_TEES)
        + _TEE_SHAPE)


# A COURSE RATING AND A SLOPE ARE ONE MEASUREMENT, SO A REFUSAL TO PRINT ONE IS A REFUSAL TO PRINT BOTH.
# The USGA Course Rating System evaluates one tee for one gender and produces the pair together: the
# Slope Rating IS the spread between that evaluation's bogey and scratch ratings, scaled by a
# GENDER-SPECIFIC constant (5.381 for men, 4.24 for women). So a slope is not an independent fact that
# happens to sit beside a rating -- it is that rating's other half, and it carries the same tee and the
# same gender. "We would not print that rating" and "we will print its slope" cannot both be true of
# one published pair: half a refused pair is still the refused source, only unlabelled.
#
# THE DEFECT THIS EXISTS FOR, measured: micke-grove's card publishes 70.0/116 under Red, and that pair
# is the WOMEN'S rating (the row beneath it on the printed card is 'Ladies' Handicap'; a 5286-yd tee
# cannot rate 70.0 where 6026 rates 68.5). legal/03 records the 70.0 as deliberately withheld for
# exactly that reason -- and course.json kept the 116 from the same pair. The book therefore printed
#     Red | 5286 | -- | 116
# in a column whose other two rows are men's slopes (126, 122) with nothing marking the difference,
# beside a guide card whose only gender statement is "HCP = the men's stroke index". A junior computing
# a course handicap off that row (index x slope / 113) used a women's slope. It read as plausible
# because 116 sits almost exactly on the men's extrapolation (126 @ 6565, 122 @ 6026 -> ~116.5 @ 5286),
# which is the whole reason nothing caught it: the wrong number and the right one look alike.
#
# CHECKED HERE, beside the transcription, because this is the only place every build reads a course
# record -- and refusing the BUILD is the point. The suite's only tee check was rating monotonicity;
# nothing inspected the slope column, so the class was invisible to the tests AND to the reader.
#
# THE ESCAPE HATCH IS A SOURCE, NOT A FLAG. If a men's slope for that tee really is published
# somewhere, record where: "slope_source": "NCGA course-rating DB, men's Red 5286 -> 112". A bare
# boolean would let the next person silence this by asserting the thing the check is asking them to
# evidence. Same shape as `rating_is_womens` on the rating side, one level stricter.
#
# ...and that argument was made and then not enforced. The first version read
# `not str(t.get("slope_source") or "").strip()`, and `str(True)` is "True": non-empty, therefore a
# "source". Measured, every one of `True`, `1`, `"x"`, `"true"`, `["NCGA"]`, `{"db": "NCGA"}` and `3.14`
# silenced the check -- so the hatch WAS the bare boolean this comment says it must not be, and the test
# named test_the_escape_hatch_demands_a_source_and_not_a_flag graded only "", "   ", "\n" and None.
_SLOPE_SOURCE_MIN_CHARS = 8


def _is_a_recorded_source(value):
    """Whether `value` has the SHAPE of a record of where a number came from.

    Two bars, and both of them are about shape -- no check here can tell a true citation from a typed
    one, and it is not trying to. What it can refuse is the two ways this hatch stops being evidence:

      * NOT A STRING. `True`, `1`, `["NCGA"]` and `{"db": "NCGA"}` are assertions that a source exists,
        which is precisely the claim the hatch asks the author to replace with the source itself. A
        non-string cannot be read by the human auditing legal/03, so it cannot be a source.
      * TOO SHORT TO BE ONE. config.py's own refusal asks for "<publication, tee and value>"; the bar is
        deliberately low, and set below anything real rather than above anything imaginable. It admits
        a bare URL ("https://ncga.org/..." -- one token, no prose, and a perfectly good answer) and
        rejects the placeholders a hurried edit leaves instead: "x", "?", "-", "n/a", "TBD", "ok",
        "yes", "true", "unknown".

    A LONG string that names nothing still passes, and a human reading legal/03 is the only check on
    that. This exists so the hatch cannot be opened WITHOUT WRITING ANYTHING, which is what it was.
    """
    return isinstance(value, str) and len(value.strip()) >= _SLOPE_SOURCE_MIN_CHARS


def slopes_without_a_rating(tees):
    """The tees printing a slope while their rating is withheld, with no men's slope source recorded.

    Pure and list-in/list-out so a test can pose the question without a course on disk: the wiring
    below is one call, and a predicate nothing exercises is the "one declaration, zero uses" shape this
    repo has already found inert twice -- tools/check_scale.py's cap, which a test now re-derives, and
    `rating_is_womens`, which appears in tests/test_phase1_regressions.py and on no tee in any
    course.json. tests/test_r14_tees.py grades this one THROUGH a real build for that reason.

    What does and does not count as a recorded `slope_source` is _is_a_recorded_source above: a string,
    long enough to name a publication. A bare `True` does not count, and used to.
    """
    return [t for t in (tees or [])
            if t.get("rating") is None and t.get("slope") is not None
            and not _is_a_recorded_source(t.get("slope_source"))]


_HALF_PAIRS = slopes_without_a_rating(TEE_TABLE)
if _HALF_PAIRS:
    raise SystemExit(
        f"courses/{SLUG}/course.json: {len(_HALF_PAIRS)} tee(s) withhold a course rating but still\n"
        f"publish a slope. A rating and a slope are ONE USGA measurement of ONE tee for ONE gender, so\n"
        f"whatever made the rating unprintable makes the slope beside it unprintable too:\n"
        + "".join(f'  "{t.get("name")}" ({t.get("yards")} yd): rating null, slope {t.get("slope")}\n'
                  for t in _HALF_PAIRS)
        + '  The card prints an em-dash for null, so the fix is usually one edit -- set "slope": null\n'
          "  and the row refuses both halves, which is what the provenance record already says about\n"
          "  the rating. A junior reads that column as men's (the guide card says \"HCP = the men's\n"
          "  stroke index\") and computes index x slope / 113 from it, so a women's or unsourced slope\n"
          "  left in a men's column is a wrong number on a printed card.\n"
          '  If a MEN\'S slope for that tee genuinely is published, record where it came from:\n'
          '    "slope_source": "<publication, tee and value>"\n'
          "  and this build will proceed. It has to be READABLE TEXT: a bare true, or a placeholder\n"
          '  like "n/a" or "TBD", is an assertion that a source exists and is refused as one.\n'
          "  Do not add the key without the source -- legal/03 has to be\n"
          "  able to answer for every number in the book.")

# WHICH TEE THIS BOOK IS BUILT ON -- one answer, here, because it was being decided in two places.
# generate.py picked the longer of FEATURED/SECONDARY for the card headline; render_hole.py and
# fetch_hole_elev.py independently used TEES[0] (the first scorecard column) for the tee marker, the
# from-tee gutter numbers, the carries and the elevation. Those coincided on 11 of 12 courses, so it
# looked fine -- but the-reserve-at-spanos-park SET featured_tee = Gold while Black was column 0, and
# its cards headlined "376 Gold" beside a tee marker reading BLA and a brown gutter measured from the
# 422-yd BLACK tee. 10 of its 18 holes were affected, by up to 46 yd on the number a player reads as
# "how far I have hit". A card must be built on ONE tee.
#
# Past tense throughout, because that course was rebuilt on Black on 2026-07-31 and BACK_NAME now
# equals TEES[0] on 12 of 12. The counterexample is gone, so this reads as history -- do not check
# course.json expecting to find Gold. Kept because the two-places problem is why BACK_I exists at all,
# and a corpus that currently agrees is exactly the state in which someone reintroduces the split.
_LONGEST_OF_PAIR_IS_SECONDARY = (sum(HOLES[h][SI] for h in HOLES) >= sum(HOLES[h][FI] for h in HOLES))
BACK_I, BACK_NAME = ((SI, SECONDARY) if _LONGEST_OF_PAIR_IS_SECONDARY else (FI, FEATURED))
FRONT_I, FRONT_NAME = ((FI, FEATURED) if _LONGEST_OF_PAIR_IS_SECONDARY else (SI, SECONDARY))

# ...and BACK_I is only the longest of the FEATURED/SECONDARY pair, which is not the same thing as
# the longest tee on the scorecard. the-reserve-at-spanos-park left secondary_tee unset, so SECONDARY
# fell back to TEES[-1] (Green, 5246 yd) and the pair became Gold-vs-Green: Black, the real tips at
# 7173 yd, sat in OTHERS as a footnote and could never win. The book headlined Gold, 274 yd shorter,
# and every derived number -- tee marker, from-tee gutters, carries, elevation -- was measured from
# it, on a course whose Black and Gold differ on 10 of 18 holes by up to 46 yd.
#
# A junior 15 or over plays the longest tee they are given, so a book that quietly headlines a
# shorter one is telling them the wrong distance all day. Warn rather than refuse: which tee a book
# is FOR is a real editorial choice (a 9-hole junior edition on a forward tee is legitimate), so this
# must not block a deliberate decision -- only make an accidental one impossible to miss.
_ALL_TOTALS = {t: sum(HOLES[h][2 + i] for h in HOLES) for i, t in enumerate(TEES)} if HOLES else {}
_LONGEST_TEE = max(_ALL_TOTALS, key=_ALL_TOTALS.get) if _ALL_TOTALS else None
SHORTER_TEE_IS_DELIBERATE = bool(COURSE.get("shorter_tee_is_deliberate"))
# QUIET_TEE_CHECK silences the note. It is read through lidar_coverage._env_on, the project's ONE
# off-vocabulary, and NOT for truthiness: `bool(os.environ.get(..))` made `QUIET_TEE_CHECK=0` and
# `=false` SILENCE the warning, which is the same invertible-waiver defect this repo has now closed
# three times. It is the one key in the family that cannot announce itself -- a notice saying "the note
# you asked me to suppress is suppressed" is the note -- so the vocabulary is the only thing standing
# between "I explicitly left this on" and a book that headlines a tee up to 46 yd short of the one a
# junior is actually playing, with no line of output either way. Documented in PIPELINE.md step 8.
if (_LONGEST_TEE and _LONGEST_TEE != BACK_NAME and not SHORTER_TEE_IS_DELIBERATE
        and not _env_on("QUIET_TEE_CHECK")):
    print(f"  NOTE: this book headlines {BACK_NAME} ({_ALL_TOTALS[BACK_NAME]} yd), but "
          f"{_LONGEST_TEE} ({_ALL_TOTALS[_LONGEST_TEE]} yd) is longer.\n"
          f"        Every derived number -- tee marker, from-tee yardages, carries, elevation --\n"
          f"        is measured from {BACK_NAME}. Set featured_tee/secondary_tee to build on\n"
          f"        {_LONGEST_TEE}, or add \"shorter_tee_is_deliberate\": true to silence this.",
          file=sys.stderr)
