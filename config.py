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
if (_LONGEST_TEE and _LONGEST_TEE != BACK_NAME and not SHORTER_TEE_IS_DELIBERATE
        and not os.environ.get("QUIET_TEE_CHECK")):
    import sys as _sys
    print(f"  NOTE: this book headlines {BACK_NAME} ({_ALL_TOTALS[BACK_NAME]} yd), but "
          f"{_LONGEST_TEE} ({_ALL_TOTALS[_LONGEST_TEE]} yd) is longer.\n"
          f"        Every derived number -- tee marker, from-tee yardages, carries, elevation --\n"
          f"        is measured from {BACK_NAME}. Set featured_tee/secondary_tee to build on\n"
          f"        {_LONGEST_TEE}, or add \"shorter_tee_is_deliberate\": true to silence this.",
          file=_sys.stderr)
