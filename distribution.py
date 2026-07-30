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


YARDAGE = "yardage"


def distribution_status(course):
    """(distributable: bool, label: str, reason: str) for a parsed course.json.

    Fails CLOSED, deliberately. This decides whether a book may be handed out, so every uncertain
    input has to resolve to "no":

    * `None` means the course record could not be read. An exact `== "yardage"` test answered
      "Distributed" for that, which is a publish decision taken on no information at all.
    * The mode is normalised before comparison. `"YARDAGE"` and `" yardage"` both answered
      "Distributed" too, so a stray capital or space in a hand-edited course.json -- and course.json
      IS hand-edited, it holds the scorecard transcription -- would have shipped a personal-use book.

    The corpus uses only `None` (11 courses) and `"yardage"` (1), so nothing changes today; this is
    about which way the next typo falls.
    """
    if course is None:
        return (False, "Personal",
                "no course record could be read, so distributability is unknown; refusing by default")
    mode = (course.get("build_mode") or "").strip().lower()
    if mode == YARDAGE:
        return (False, "Personal",
                "built in yardage mode: no trustworthy post-construction elevation exists, so the "
                "book prints blank greens and is personal-use only")
    return (True, "Distributed", "")


def is_distributable(course):
    return distribution_status(course)[0]


def is_yardage(course):
    """True when this course is built in YARDAGE MODE -- blank greens, verified yardages only.

    A DATA fact, kept separate from the distribution verdict even though yardage mode is currently
    the only reason a book is not distributable. Deriving one from the other means the moment a
    second reason exists, anything that says "yardage mode: blank greens" would say it about a course
    that is not in yardage mode -- an unsupported claim in the legal record. Same normalisation as
    distribution_status, so a mis-cased build_mode reads the same way in both."""
    return ((course or {}).get("build_mode") or "").strip().lower() == YARDAGE
