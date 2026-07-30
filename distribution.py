#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
One answer to "may this course's book be handed out?".

Why this is its own module: the rule existed in exactly one place, inside tools/gen_provenance.py,
where it decided the Status column of legal/03_PROVENANCE_BY_COURSE.md -- a file whose own legend
reads *"Distributed" = safe to hand out; "Personal" = do not distribute*. Nothing else consulted it.
So when the iOS app's exporter was written it bundled every course it found, Poppy Ridge included,
and the app would have shipped a book that the project's own legal record says must not be
distributed. legal/00_SUMMARY_AND_VERDICT.md is explicit: "Poppy Ridge is not -- it is personal-use
only."

An App Store build, a web download and a handed-out printout are all distribution. Any code that
publishes a book asks here first, and the legal record is generated from the same function, so the
two cannot drift apart.

The rule itself: a course built in YARDAGE MODE is personal-use. Yardage mode means no trustworthy
post-construction elevation exists, so the book prints verified yardages with blank greens rather
than slope that could be wrong -- and for Poppy Ridge the aerial also predates the 2025 rebuild.
"""


def distribution_status(course):
    """(distributable: bool, label: str, reason: str) for a parsed course.json."""
    if (course or {}).get("build_mode") == "yardage":
        return (False, "Personal",
                "built in yardage mode: no trustworthy post-construction elevation exists, so the "
                "book prints blank greens and is personal-use only")
    return (True, "Distributed", "")


def is_distributable(course):
    return distribution_status(course)[0]
