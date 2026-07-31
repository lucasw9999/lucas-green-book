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

with open(_CJ) as f:
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

# hole -> (par, mens_hcp, <tee yardages in hole_cols order>)
HOLES = {int(k): tuple(v) for k, v in COURSE["holes"].items()}
HOLE_NUMS = sorted(HOLES)                          # actual holes present (9-hole courses have 1..9)
NHOLES = len(HOLE_NUMS)
NAME = COURSE["name"]
ADDRESS = COURSE["address"]
PAR = COURSE.get("par", 72)
BUILD_MODE = COURSE.get("build_mode", "full")   # "full" = slope maps; "yardage" = blank greens (no elevation data yet)

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
# from-tee gutter numbers, the carries and the elevation. Those coincide on 11 of 12 courses, so it
# looked fine -- but the-reserve-at-spanos-park sets featured_tee = Gold while Black is column 0, and
# its cards headlined "376 Gold" beside a tee marker reading BLA and a brown gutter measured from the
# 422-yd BLACK tee. 10 of its 18 holes were affected, by up to 46 yd on the number a player reads as
# "how far I have hit". A card must be built on ONE tee.
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
