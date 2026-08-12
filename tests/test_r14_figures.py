#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Graders for two published figures that drifted because nothing measured them (round-06 audit,
findings K-1 and K-2):

  * legal/09_GREEN_SURFACE_REPEATABILITY.md quoted "71 of the 72 LAZ tiles in the corpus" for a
    scan whose real, on-disk population is 78 physical .laz files / 71 distinct tile footprints --
    72 was neither, and the same document's own legal/03 table and two OTHER records
    (`fetch_dem_hd.py`, the sibling regression suite) already say 78.
  * render_hole.py's carry-figure cost comment said "Cost: 8 figures across 8 of 198 cards,
    128 -> 119", which is its own arithmetic done wrong (128-119=9, not 8) and contradicted by a
    sentence six lines later in the SAME comment block ("Nine windows in this corpus have no
    landing area").

Both are corpus tests: they recompute the published counts from the actual .laz tiles and the
actual shipped greenbook.html files, and FAIL if a document disagrees with what is on disk. They
SKIP on a fresh clone -- courses/ is gitignored, so a checkout with no course data has nothing to
recompute against, and a skip is visibly not a pass.

Design mirrors tests/test_phase1_regressions.py's corpus graders (see e.g. its `_published` /
`_flow` helpers): a regex anchored to the actual sentence extracts the published number, which is
then compared to a value recomputed from the artifact -- never to a second copy of the same
literal, and never a bare substring probe.
"""
import glob
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEGAL_09 = os.path.join(ROOT, "legal", "09_GREEN_SURFACE_REPEATABILITY.md")
RENDER_HOLE = os.path.join(ROOT, "render_hole.py")


def _flow(text):
    """Source/prose text with line-leading '#' markers stripped and whitespace collapsed to one space.

    So a pattern can span a line wrap without being hostage to where a 100-column limit happens to
    break the sentence. Same idea as _flow in test_phase1_regressions.py, kept as a private copy
    here rather than imported -- this file must not touch or depend on the module another agent
    owns this round.
    """
    return re.sub(r"\s+", " ", re.sub(r"(?m)^[ \t]*#", " ", text))


def _rendered_courses():
    """Slugs with the geometry render_hole.py needs (osm_geom.json + osm_course.json).

    This is the population "198 cards" in render_hole.py's comment actually means: poppy-ridge has
    a shipped greenbook.html (built in yardage-only mode from the scorecard alone, no LiDAR green
    surfaces yet) but no osm_geom.json/osm_course.json, so render_hole.render_hole() -- and every
    carry figure it computes -- never runs for it. Deriving this from the files on disk, rather
    than hardcoding "198" or "the 12 courses minus poppy-ridge", keeps the grader honest if a course
    is added or removed from the checkout.
    """
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        d = os.path.dirname(cj)
        if (os.path.exists(os.path.join(d, "osm_geom.json"))
                and os.path.exists(os.path.join(d, "osm_course.json"))
                and os.path.exists(os.path.join(d, "greenbook.html"))):
            out.append(slug)
    return out


needs_laz = pytest.mark.skipif(
    not glob.glob(os.path.join(ROOT, "courses", "*", "laz", "*.laz")),
    reason="courses/*/laz/ is gitignored; no LAZ tiles present in this checkout")
needs_books = pytest.mark.skipif(
    not _rendered_courses(),
    reason="courses/ is gitignored; no rendered greenbook.html present in this checkout")


# --------------------------------------------------------------------------------------------------
# K-1: the LAZ tile-count populations legal/09 argues about
# --------------------------------------------------------------------------------------------------

def _laz_tile_records():
    """One record per real .laz file under courses/*/laz/: (course_slug, tile_id_or_None, path).

    tile_id is the `w####n####` USGS 3DEP grid cell parsed out of the filename where the naming
    scheme carries one (the Alameda-county deliveries do). Every other naming scheme in this
    corpus (UTM-tile names, DEM-index names) never repeats a filename across two course
    directories, so those tiles need no tile_id to be de-duplicated correctly below -- they are
    unique by construction.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "laz", "*.laz"))):
        slug = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if slug.startswith("_"):
            continue
        m = re.search(r"(w\d+n\d+)(?:__Co\d+)?\.laz$", os.path.basename(path))
        out.append((slug, m.group(1) if m else None, path))
    return out


def _laz_tile_counts():
    """(n_files, n_collapsed, n_footprints) -- the three populations K-1 is about.

    n_files      : every physical .laz file on disk.
    n_collapsed  : n_files with __CoN delivery-variant duplicates of the SAME (course, tile)
                   collapsed to one (this corpus has two: callippe's w6165n2052 and
                   castlewood-hill's w6153n2055 each carry a plain file and a __CoN sibling).
    n_footprints : n_collapsed with the SAME tile id held by more than one course directory
                   collapsed to one (four Alameda cells in this corpus are shared this way).
    """
    records = _laz_tile_records()
    n_files = len(records)
    collapsed = {(slug, tile) if tile else (slug, path) for slug, tile, path in records}
    n_collapsed = len(collapsed)
    footprints = {tile if tile else key for key in collapsed
                  for slug, tile in (((key[0], key[1]) if isinstance(key[1], str)
                                      and re.match(r"w\d+n\d+$", key[1]) else (key[0], None)),)}
    n_footprints = len(footprints)
    return n_files, n_collapsed, n_footprints


@needs_laz
def test_legal_09_laz_tile_count_matches_the_corpus_on_disk():
    """legal/09's withheld/synthetic-scan sentence must name today's real tile populations.

    That sentence used to say "71 of the 72 LAZ tiles in the corpus", a number that matched
    neither the 78 real files on disk, the 76 you get after collapsing __CoN delivery-variant
    duplicates, nor the 71 distinct tile footprints -- while legal/03's own per-course "(N tiles
    held)" figures already summed to 78, and fetch_dem_hd.py and the sibling regression suite both
    independently measured "78 of 78" for the identical withheld/synthetic finding. This grades the
    replacement sentence against a live recount of courses/*/laz/, so it fails again the moment a
    13th course's tiles are added and nobody updates the prose.
    """
    n_files, n_collapsed, n_footprints = _laz_tile_counts()
    with open(LEGAL_09, encoding="utf-8") as fh:
        prose = _flow(fh.read())

    m = re.search(
        r"Today's corpus holds \*\*(\d+) LAZ tiles on disk \((\d+) distinct tile footprints",
        prose)
    assert m, (
        "legal/09 no longer states today's LAZ corpus size in a form this test can read "
        "(looked for \"Today's corpus holds **<N> LAZ tiles on disk (<M> distinct tile "
        f"footprints\"). Measured on disk: {n_files} files, {n_collapsed} after collapsing __CoN "
        f"delivery variants, {n_footprints} distinct tile footprints.")
    said_files, said_footprints = int(m.group(1)), int(m.group(2))
    assert said_files == n_files, (
        f"legal/09 says today's corpus holds {said_files} LAZ tiles on disk; "
        f"courses/*/laz/*.laz on this machine has {n_files}.")
    assert said_footprints == n_footprints, (
        f"legal/09 says today's corpus holds {said_footprints} distinct tile footprints; "
        f"measured {n_footprints} after collapsing __CoN delivery variants ({n_collapsed}) and "
        f"tiles shared between adjacent course directories.")

    # The number this whole passage exists to attribute a population to. This project's one-off
    # scans are never re-run by this suite (this one would mean reading 11.6 GiB of tiles), so the
    # return count itself cannot be re-derived here -- only that the sentence still states it next
    # to the population it was measured over, so a future edit that silently drops the attribution
    # is caught.
    assert re.search(r"counted \*\*582,510,577 class.2 ground returns\*\*.{0,400}"
                      r"the same population the .withheld.\W+on\W+\*\*78 of 78\*\* figures",
                      prose), (
        "legal/09 no longer ties the 582,510,577 class-2 ground return count to a stated "
        "population (files vs. de-duplicated footprints). That attribution -- not just the digits "
        "-- is the thing K-1 found missing; re-derive and state it rather than dropping the tie.")


@needs_laz
def test_legal_09_no_longer_publishes_the_stale_72_tile_denominator():
    """The specific broken pairing this defect was: "71 of the 72", where 72 matched nothing.

    Anchored to the withheld/synthetic scan's own sentence (not a bare corpus-wide substring
    search for "72", which would also match e.g. a page number or an unrelated percentage) so this
    cannot pass just because the string "72" appears somewhere in an 8,000-word document.
    """
    with open(LEGAL_09, encoding="utf-8") as fh:
        prose = _flow(fh.read())
    m = re.search(r"class.2 ground returns", prose)
    assert m, "could not find the withheld/synthetic ground-return sentence to check at all."
    window = prose[max(0, m.start() - 200):m.end()]   # the old "N of the M LAZ tiles" sat BEFORE it
    assert not re.search(r"\b\d+ of the \d+ LAZ tiles", window), (
        f"the withheld/synthetic sentence still uses an 'N of M LAZ tiles' denominator "
        f"({window!r}) -- K-1 was exactly that a stale M (72) matched none of the corpus's "
        f"real populations (78 files / 76 collapsed / 71 footprints).")


# --------------------------------------------------------------------------------------------------
# K-2: the carry-figure cost comment in render_hole.py
# --------------------------------------------------------------------------------------------------

_HNUM_RE = re.compile(r'<div class="hnum">(\d+)</div>')
_PLAYLINE_RE = re.compile(r'<div class="playline">.*?</div>')
_NO_CARRY = "no carry: sand to the green"


def _carry_stats():
    """Recomputed from the shipped pocket books: (total_figures, cards_with_a_figure, no_carry).

    no_carry is a dict of {(slug, hole): n_other_printed_figures_on_that_same_card}, which is what
    "four cards lose their only carry row" (n_other == 0) and "an EARLIER carry survives" (n_other
    > 0) both name in the comment being graded.

    Counts INDIVIDUAL numbers, not playline rows: one row can print more than one carry ("carry
    204 / 274" is two figures on one row), and a row printing both a kept carry and the refusal
    phrase ("carry 178 &middot; no carry: sand to the green") is both a counted figure AND a
    no-carry card -- dropping either half double-counts or under-counts what the comment claims.
    """
    total_figures = 0
    cards_with_figure = 0
    no_carry = {}
    for slug in _rendered_courses():
        path = os.path.join(ROOT, "courses", slug, "greenbook.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        hnums = [(m.start(), m.group(1)) for m in _HNUM_RE.finditer(html)]

        def hole_for(pos):
            prev = [n for p, n in hnums if p < pos]
            return prev[-1] if prev else "?"

        for pm in _PLAYLINE_RE.finditer(html):
            text = re.sub("<[^>]+>", "", pm.group())
            if "carry" not in text:
                continue
            has_refusal = _NO_CARRY in text
            remainder = text.replace(_NO_CARRY, "")
            nums = []
            for cm in re.finditer(r"carry\s+([0-9/\s]+?)(?:&middot;|$)", remainder):
                nums.extend(re.findall(r"\d+", cm.group(1)))
            if has_refusal:
                no_carry[(slug, hole_for(pm.start()))] = len(nums)
            if nums:
                total_figures += len(nums)
                cards_with_figure += 1
    return total_figures, cards_with_figure, no_carry


@needs_books
def test_render_hole_carry_cost_comment_matches_the_shipped_books():
    """render_hole.py's "Cost: N figures across N of 198 cards, X -> Y" must match reality.

    The comment said "8 figures across 8 of 198 cards, 128 -> 119" -- which is 128-119=9, not 8,
    contradicting its own arithmetic, and contradicting a sentence six lines later in the same
    block ("Nine windows in this corpus have no landing area"). Graded against a live count of the
    shipped greenbook.html files' printed "carry N" figures and "no carry: sand to the green"
    refusals, not against a second copy of the same number, so this fails again if a future change
    to the landing-area filter moves the count and nobody updates the comment.
    """
    total_figures, cards_with_figure, no_carry = _carry_stats()
    n_expected_cards = sum(
        len(json.load(open(os.path.join(ROOT, "courses", s, "course.json"), encoding="utf-8"))
            .get("holes") or {})
        for s in _rendered_courses())

    with open(RENDER_HOLE, encoding="utf-8") as fh:
        src = _flow(fh.read())
    m = re.search(
        r"Cost: (\d+) figures across (\d+) of (\d+) cards, (\d+) -> (\d+)", src)
    assert m, (
        "render_hole.py no longer publishes the carry-figure cost in a form this test can read "
        "(looked for \"Cost: <N> figures across <N> of <T> cards, <X> -> <Y>\"). Measured: "
        f"{total_figures} figures across {cards_with_figure} of {n_expected_cards} cards; "
        f"{len(no_carry)} refused windows.")
    said_n_figures, said_n_cards, said_total, said_before, said_after = (
        int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))

    assert said_total == n_expected_cards, (
        f"render_hole.py's cost comment scopes itself to {said_total} cards; the corpus that "
        f"actually runs through render_hole() (osm_geom.json + osm_course.json present) has "
        f"{n_expected_cards}.")
    assert said_after == total_figures, (
        f"render_hole.py says {said_after} carry figures print today; the shipped greenbook.html "
        f"files print {total_figures}.")
    assert said_n_figures == said_before - said_after, (
        f"render_hole.py's own arithmetic doesn't close: {said_before} -> {said_after} is a cost "
        f"of {said_before - said_after}, not the {said_n_figures} the comment states.")
    # WINDOWS REFUSED AND CARDS MARKED ARE TWO COUNTS, and this test conflated them because they were
    # equal. The cost figure counts windows the landing rule REFUSED; the mark is printed only where the
    # sand from that window also REACHES the green, which is a second question the rule does not answer
    # (see render_hole's reach gate). They coincided for as long as every refusal happened to reach, and
    # trump-national-los-angeles 16 is the card where that stopped: refused on 5.13 yd of room, silent,
    # because its sand stops 5.13 yd short of the front. Grading the cost against the MARK count made
    # this test demand the engine print a claim its own geometry denies.
    #
    # So the cost is graded against the figures actually withheld -- before minus after, which is what
    # the arithmetic above already closes -- and the mark count is graded separately against its own
    # published figure. Both are still derived from the shipped books; neither is a second copy of the
    # other.
    assert said_n_figures >= len(no_carry), (
        f"render_hole.py says the landing-area filter costs {said_n_figures} figures while the shipped "
        f"books print \"{_NO_CARRY}\" on {len(no_carry)} cards ({sorted(no_carry)}). Every marked card "
        f"is a refused window, so the marks can never outnumber the refusals -- one of the two counts "
        f"is wrong.")
    assert said_n_cards == said_n_figures, (
        f"render_hole.py says the filter costs {said_n_figures} figures across {said_n_cards} cards; "
        f"this corpus never refuses two windows on one hole, so those must be the same number.")
    m_mark = re.search(r"Of those \d+ refusals, (\d+) print the mark", src)
    assert m_mark, (
        "render_hole.py no longer publishes how many of the refused windows PRINT the mark, which is "
        "the count that stopped equalling the refusal count (looked for \"Of those <N> refusals, <M> "
        f"print the mark\"). Measured: {len(no_carry)} of {said_n_figures}.")
    assert int(m_mark.group(1)) == len(no_carry), (
        f"render_hole.py says {m_mark.group(1)} of its refusals print the mark; the shipped books "
        f"print \"{_NO_CARRY}\" on {len(no_carry)} cards ({sorted(no_carry)}).")

    # render_hole.py's own comments never spell a course's full course.json slug -- they use one
    # fixed shorthand per course throughout the file ("callippe", not "callippe-preserve"; grep
    # confirms this is the ONLY spelling render_hole.py ever uses for each). That is a naming
    # convention this test has to know to compare against the doc at all, not a re-implementation
    # of the rule being graded (which is about WHICH cards lose their only row, not what they are
    # called).
    SHORTHAND = {
        "bay-view-golf-club": "bay-view",
        "callippe-preserve-golf-course": "callippe",
        "castlewood-hill-course": "castlewood-hill",
        "castlewood-valley-course": "castlewood-valley",
        "copper-valley-golf-club": "copper-valley",
        "merion-golf-club": "merion",
        "micke-grove-golf-links": "micke-grove",
        "monarch-bay-golf-club": "monarch-bay",
        "philadelphia-country-club": "philadelphia",
        "the-reserve-at-spanos-park": "the-reserve",
        "valley-hi-country-club": "valley-hi",
    }
    lose_only = sorted((SHORTHAND[slug], hole) for (slug, hole), n_other in no_carry.items()
                        if n_other == 0)
    m2 = re.search(r"four cards lose their only carry row\s*\(([^)]*)\)", src)
    assert m2, "render_hole.py no longer names the cards that lose their only carry row."
    # "philadelphia 1, micke-grove 3 and 13, callippe 12" -- a course name followed by one or more
    # hole numbers joined by "and", comma-separated between courses.
    # The loop variable is `entry` and not `segment` deliberately: `segment` is one of the analytics
    # package names test_the_security_record_still_describes_this_repository scans executable code for,
    # to hold SECURITY.md's "collects no user data" promise, and it reads a bare identifier as a hit.
    named = set()
    for entry in m2.group(1).split(","):
        seg_m = re.match(r"\s*([a-z][a-z-]*)\s+(\d+(?:\s+and\s+\d+)*)\s*$", entry)
        assert seg_m, f"render_hole.py's only-carry-row list has an entry this test cannot parse: {entry!r}"
        for hole in re.findall(r"\d+", seg_m.group(2)):
            named.add((seg_m.group(1), hole))
    assert len(lose_only) == 4, (
        f"render_hole.py's comment says four cards lose their only carry row; measured "
        f"{len(lose_only)}: {lose_only}.")
    assert named == set(lose_only), (
        f"render_hole.py names {sorted(named)} as the cards that lose their only carry row; "
        f"measured {lose_only}.")
