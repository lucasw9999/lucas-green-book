#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. All rights reserved.
# "Lucas Green Book" is a trademark of Lucas Wu.
# Published for reference. Not licensed for use, modification or redistribution.
# https://github.com/lucasw9999/lucas-green-book
"""
One answer to "may this course's book be handed out?".

Every book this project makes is built from open and public-domain data. Not every book is fit to
DISTRIBUTE, and that is a different question: a course whose elevation data cannot be trusted -- one
rebuilt since the last public survey, say -- gets a book with verified yardages and deliberately
blank greens, because a blank green is honest and a wrong slope is not. Those books are personal-use
only.

This module is the single place that decides. An App Store build, a web download and a handed-out
printout are all distribution, so every code path that publishes a book asks here first, and the
project's own provenance record is generated from the same function. One rule, one spelling, so the
record and the artifact cannot drift apart.

The rule itself: a course built in YARDAGE MODE is personal-use.

Why this module is written the way it is
----------------------------------------
It is a GATE, so it FAILS CLOSED. Refusing to publish a book that was in fact fine is visible and
recoverable in a minute. Publishing one that was not is neither. Every function here is written on
that asymmetry, which is why several of them look more defensive than a three-line predicate needs
to: the input is a hand-edited file, and the field being read is the one that says "do not trust the
elevation here".
"""


YARDAGE = "yardage"
FULL = "full"
# The CLOSED domain of build_mode. Closed on purpose: normalising a value and then testing it against
# one exact word means every OTHER value falls through to "publishable". A misspelling of the single
# field whose job is to say "the elevation here is not trustworthy" would then publish precisely what
# that field exists to withhold. So anything outside this tuple is refused rather than assumed.
MODES = (FULL, YARDAGE)
# A directory whose name starts with this is SCRATCH, not a course: a synthetic test fixture, a
# staging copy, a hand-made probe. Never a real green book.
SCRATCH_PREFIX = "_"


def is_corpus_slug(name):
    """Is this directory name a real course, or somebody's scratch?

    It lives in this module rather than in each caller because "what counts as a course" is the same
    class of question as "may this be published?", and a rule that exists in four places is a rule
    that will eventually disagree with itself. A scratch directory that reached a published record
    would appear there as a real course, which is a claim about a book that does not exist.
    """
    return bool(name) and not name.startswith(SCRATCH_PREFIX)


def course_slugs(root=None):
    """Every real course slug under root/courses, sorted. Scratch directories excluded.

    root defaults to THIS FILE's directory, never the current working directory. That distinction
    matters more than it looks: an enumerator that resolves against the cwd returns an EMPTY list
    when run from elsewhere, and a checking tool that examines zero courses reports the same "nothing
    disagrees" as one that examined all of them and found them consistent. A check that can pass by
    finding nothing is not a check.
    """
    import glob
    import os
    if root is None:
        root = os.path.dirname(os.path.abspath(__file__))
    return sorted(s for s in (os.path.basename(os.path.dirname(p))
                              for p in glob.glob(os.path.join(root, "courses", "*", "course.json")))
                  if is_corpus_slug(s))


def is_course_record(course):
    """Is this something this module can answer ABOUT at all -- a NON-EMPTY parsed course.json object?

    One readability test, shared, because the functions below must agree on what "unreadable" means.
    There are more shapes of unreadable than the obvious one, and each is a real file state: a
    course.json rooted on a list, a file holding a bare literal, an empty read, or a caller passing
    the MODE string where the record belongs.

    AN EMPTY DICT IS NOT A COURSE RECORD. It resembles the documented "no build_mode means full"
    default and is not it -- that default is a statement about one OPTIONAL field missing from a
    record that has content. An empty mapping omits everything, including the keys the loader
    requires, and one of those keys IS the scorecard transcription. A course.json with no course in
    it is the shape a truncated or reset file has, and nothing can be published on the strength of
    it.
    """
    return isinstance(course, dict) and bool(course)


def build_mode(course):
    """The course's build mode, NORMALISED. The one spelling of this read for the whole engine.

    course.json is hand-edited -- it holds the scorecard transcription -- so a stray capital or a
    trailing newline is a realistic typo rather than a hypothetical one. Normalising here, once,
    keeps every consumer reading the same value: a reader that compares raw strings and a gate that
    normalises would disagree about the same file, and the disagreement would not be a wrong number
    but a provenance record describing a book that was never built.

    A record this module cannot read has NO mode, and says so by answering "" rather than raising.
    The publish decision for such a record belongs to distribution_status, which refuses it; this
    function's job is to answer, and a reader that raises where a verdict was expected turns a
    decision into a traceback.
    """
    if not is_course_record(course):
        return ""
    return (course.get("build_mode") or "").strip().lower()


def distribution_status(course):
    """(distributable: bool, label: str, reason: str) for a parsed course.json.

    Fails CLOSED, deliberately. This decides whether a book may be handed out, so every uncertain
    input resolves to "no":

    * A record this module CANNOT READ is refused -- all of the shapes is_course_record rejects, not
      just the obvious empty one.
    * The mode is NORMALISED before comparison, so a stray capital or space in a hand-edited file
      cannot change the verdict.
    * A build_mode OUTSIDE the documented domain is refused. This is the one that needs stating
      plainly: normalise, then test against a single exact word, and every other value falls through
      to "publishable". An unrecognised value is a typo, and the two things a typo could have meant
      have opposite consequences for what gets printed, so it is not a guess this gate is entitled to
      make.

    An absent or empty build_mode FIELD is NOT uncertain -- "defaults to full" is documented and most
    courses rely on it -- so a record that has content but no build_mode stays distributable. An
    empty RECORD is a different input wearing the same shape; see is_course_record.

    Refusing rather than guessing is the governing rule of this project. It is what lets a book print
    a blank green instead of a slope nobody can stand behind.
    """
    if isinstance(course, dict) and not course:
        # Spelled apart from the branch below because "the course record is a dict, not a parsed
        # course.json object" is a confusing thing to say about `{}`. The fault is that it is EMPTY.
        return (False, "Personal",
                "the course record is EMPTY -- a course.json with no course in it: no name, no "
                "address, no hole_cols and no holes, and the holes table IS the scorecard. That is "
                "the shape a truncated or reset file has, not the documented 'no build_mode means "
                "full' default, so what this book was built from is unknown; refusing by default")
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
    the only reason a book is not distributable. Deriving one from the other means that the moment a
    second reason exists, anything reporting "yardage mode: blank greens" would say it about a course
    not in yardage mode -- an unsupported claim in a published record. Same normalisation as
    distribution_status, so a mis-cased build_mode reads the same way in both."""
    return build_mode(course) == YARDAGE
