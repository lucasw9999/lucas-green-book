#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Shared course config for the green-book engine.

The engine (fetch_*.py, render_*.py, generate.py) is course-agnostic. Pick which
course to build with the COURSE env var (defaults to the first one we built):

    COURSE=the-reserve-at-spanos-park python3 generate.py

Each course lives in courses/<slug>/ with a course.json describing it and holds
that course's cached data (osm_*.json, laz/, dem_hd/) and outputs (greenbook.*).
"""
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
SLUG = os.environ.get("COURSE", "the-reserve-at-spanos-park")
COURSE_DIR = os.path.join(ROOT, "courses", SLUG)

BRAND = "Lucas Green Book"   # product/brand name shown on the cover

with open(os.path.join(COURSE_DIR, "course.json")) as f:
    COURSE = json.load(f)

# ---- physical card + print layout (inches) -------------------------------
# Card trim size = the finished page that slips into a back-pocket yardage-book
# cover. 3.5 x 5.5 fits standard covers and is well under the Rules of Golf cap
# (4.25 x 7). Override per course in course.json via "card":{"w":..,"h":..}.
_card = COURSE.get("card", {})
CARD_W_IN = float(_card.get("w", 3.5))
CARD_H_IN = float(_card.get("h", 5.0))         # 5.0 -> 4 cards (2x2) per US Letter
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
FEATURED = COURSE.get("featured_tee", TEES[0])
SECONDARY = COURSE.get("secondary_tee", TEES[-1])
FI = 2 + TEES.index(FEATURED)                     # featured yardage index
SI = 2 + TEES.index(SECONDARY)                    # secondary yardage index
OTHERS = [(t, 2 + i) for i, t in enumerate(TEES) if t not in (FEATURED, SECONDARY)]
TEE_TABLE = COURSE.get("tees", [])
MAX_YARDS = max((t["yards"] for t in TEE_TABLE), default=0)
