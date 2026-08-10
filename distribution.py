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
FULL = "full"
# The CLOSED domain of build_mode, and the reason distribution_status can refuse anything outside it.
# examples/course.json documents exactly these two ("OPTIONAL, defaults 'full'. Set to 'yardage' when no
# trustworthy post-construction elevation exists"); an absent or empty value means FULL.
MODES = (FULL, YARDAGE)
# A directory under courses/ whose name starts with this is SCRATCH, not a course: a synthetic fixture
# a test authored, a cold-build staging copy, a hand-made probe. Never a real green book.
SCRATCH_PREFIX = "_"


def is_corpus_slug(name):
    """Is this directory name a real course, or somebody's scratch?

    The rule already existed three times -- gen_provenance.py, gen_disclaimers.py and the test suite
    each carried their own `startswith("_")` -- and tools/cross_flight_check.py, added later, carried
    none. That is the tool whose output IS the evidence in legal/09_GREEN_SURFACE_REPEATABILITY.md, so
    a leaked fixture directory would have been scanned, printed and counted as one of the surveyed
    courses in a document about how trustworthy the surveys are.

    gen_disclaimers.py's docstring records the same fault already happening once, with the receipt:
    a throwaway directory became a named distributed green book in a legal record ("Variant A1 --
    printed on 11 book(s): _ccrit_noloc, bay-view-golf-club, ...") and --check then told you to
    regenerate, i.e. to falsify the document.

    It is not hypothetical here either. The synth_engine fixture's teardown removed its directory
    BEFORE restoring COURSE, so an os.rmdir that raised on a leftover file skipped the restore and left
    courses/_synth_ticks behind -- which is how it was found. Both ends are fixed: the fixture cleans up
    with rmtree after restoring, and a leak that does happen can no longer reach a published record.

    One spelling, in the module that already answers "may this be published?", because "what counts as
    a course" is the same class of question.
    """
    return bool(name) and not name.startswith(SCRATCH_PREFIX)


def course_slugs(root=None):
    """Every real course slug under root/courses, sorted. Scratch directories excluded.

    root defaults to THIS FILE's directory -- the repo root -- never the cwd. It used to default to
    ".", which made this the one enumerator in the repo that resolves courses/ against the cwd;
    config.py, tools/gen_provenance.py, tools/verify_elevation.py, tools/check_osm_bbox.py,
    tools/gen_disclaimers.py and tools/export_pdf.py all derive it from __file__.

    That default had teeth. tools/cross_flight_check.py computes its own __file__ root for sys.path and
    then asked here for slugs, so run from anywhere but the repo root `--all` enumerated ZERO courses,
    examined nothing, printed "0 green(s) had two passes ... 0 disagree" and returned 0 -- a run that
    looked at no data, indistinguishable in output and exit status from one that checked the whole corpus
    and found it consistent. legal/09_GREEN_SURFACE_REPEATABILITY.md names that command as the reproducer
    for its published figures, and that tool's own docstring says it must not be able to agree by failing.
    """
    import glob
    import os
    if root is None:
        root = os.path.dirname(os.path.abspath(__file__))
    return sorted(s for s in (os.path.basename(os.path.dirname(p))
                              for p in glob.glob(os.path.join(root, "courses", "*", "course.json")))
                  if is_corpus_slug(s))


def is_course_record(course):
    """Is this something this module can answer ABOUT at all -- a parsed course.json object?

    The one readability test, because two functions need it and they were disagreeing. `build_mode`
    laundered every falsy non-dict through `(course or {})` and `distribution_status` tested only
    `course is None`, so four other spellings of "the record could not be read" answered *publishable*
    and a fifth crashed. Measured before this existed:

        None       -> refused (the only one that was right)
        [] / 0 / False / ''  -> (True, "Distributed", "")
        'yardage'            -> AttributeError: 'str' object has no attribute 'get'

    Each of those is a real shape: a course.json rooted on a list, a file holding a bare literal, an
    empty read, and a caller passing the MODE where the record goes. tools/gen_provenance.py hands this
    module JSON it loaded itself and writes the answer into the Status column of
    legal/03_PROVENANCE_BY_COURSE.md, whose legend reads *"Distributed" = safe to hand out*.

    An EMPTY DICT is a course record, deliberately. "No build_mode means full" is documented in
    examples/course.json and 11 of the 12 corpus records rely on it, so `{}` is the minimal record of
    that class rather than an unreadable one -- tests/test_phase1_regressions.py pins exactly that
    ("an ordinary course with no build_mode is distributable; this documents the default"). The
    distinction being drawn here is between a mapping and something that is not one at all.
    """
    return isinstance(course, dict)


def build_mode(course):
    """The course's build mode, NORMALISED. The one spelling of this read for the whole engine.

    course.json is hand-edited -- it holds the scorecard transcription -- so a stray capital or a
    trailing space is a realistic typo, and this module already normalised for that on its own side.
    config.py did not: it bound `COURSE.get("build_mode", "full")` raw and generate.py compared it with
    `== "yardage"` exactly. So `"Yardage"` split the engine in two. distribution_status() answered
    Personal and tools/gen_provenance.py wrote *"yardage mode: blank greens"* into legal/03, while
    generate.py built a FULL book with slope maps, contours and arrows off the LiDAR that yardage mode
    exists to suppress.

    That is the worst shape a disagreement can take here: not a wrong number, but a legal record
    describing a book that was not made. Four of five plausible spellings of the value diverged
    ("Yardage", " yardage", "YARDAGE", "yardage\n"); only the exact one agreed.

    A record this module cannot read has NO mode, and says so by answering "" rather than raising --
    `build_mode("yardage")` used to be an AttributeError. The publish decision for such a record is
    distribution_status's, which refuses it; this function's job is to answer, and a reader that raises
    where a verdict was expected turns a decision into a traceback.

    Lives here rather than in config.py because this module is the one thing that must answer for a
    course record it did not load -- tools/gen_provenance.py hands it parsed JSON directly -- so it
    cannot depend on config, and config can depend on it.
    """
    if not is_course_record(course):
        return ""
    return (course.get("build_mode") or "").strip().lower()


def distribution_status(course):
    """(distributable: bool, label: str, reason: str) for a parsed course.json.

    Fails CLOSED, deliberately. This decides whether a book may be handed out, so every uncertain
    input has to resolve to "no":

    * A record this module CANNOT READ is refused. That used to mean `None` alone, and `None` is one
      spelling of it out of six: `(course or {})` laundered every falsy non-dict into an empty course,
      so `[]` (a course.json rooted on a list), `0` and `False` (a file holding a bare literal) and `''`
      (an empty read) each answered *publishable*, and `'yardage'` -- a caller passing the MODE where
      the record goes -- raised AttributeError instead of deciding. An exact `== "yardage"` test
      answered "Distributed" for `None` too, which is a publish decision taken on no information at all.
      See is_course_record for why an EMPTY DICT is not in that set.
    * The mode is normalised before comparison. `"YARDAGE"` and `" yardage"` both answered
      "Distributed" too, so a stray capital or space in a hand-edited course.json -- and course.json
      IS hand-edited, it holds the scorecard transcription -- would have shipped a personal-use book.
    * A build_mode OUTSIDE the documented domain is refused as well, and that was the hole the first two
      bullets left open: normalising then testing one exact word means everything else falls through to
      "Distributed". `"yardge"`, `"yardage mode"`, `"yardage_only"`, `"personal"` all answered
      *publishable*, and because none of them equals "yardage", is_yardage() answered False too -- so
      generate.py built the FULL slope book with contours and arrows, stamped it free to share, and
      legal/03 recorded it as safe to hand out. A misspelling of the one field whose purpose is to say
      "the elevation here is not trustworthy" published exactly what it was meant to withhold. Nothing in
      the repo validated the value, and the field is hand-typed.

    Refusing rather than guessing is the governing rule of this project, and it is the right way for this
    particular uncertainty to fall: an unrecognised value is a typo, and the two things a typo could have
    meant have opposite consequences for what gets printed. An absent or empty build_mode is NOT
    uncertain -- "defaults 'full'" is documented and 11 corpus courses rely on it -- so it stays
    distributable.

    The corpus uses only `None` (11 courses) and `"yardage"` (1), so nothing changes today; this is
    about which way the next typo falls.
    """
    if not is_course_record(course):
        return (False, "Personal",
                f"the course record is a {type(course).__name__}, not a parsed course.json object, so "
                f"nothing here could be read and distributability is unknown; refusing by default")
    mode = build_mode(course)
    if mode == YARDAGE:
        return (False, "Personal",
                "built in yardage mode: no trustworthy post-construction elevation exists, so the "
                "book prints blank greens and is personal-use only")
    if mode and mode not in MODES:
        return (False, "Personal",
                f"unrecognised build_mode {mode!r}: the field that decides whether this book prints "
                f"slope at all is neither {' nor '.join(MODES)}, so what was intended is unknown. "
                f"Almost certainly a typo in a hand-edited course.json; fix the value rather than "
                f"publishing on a guess")
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
    return build_mode(course) == YARDAGE
