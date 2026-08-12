#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Two defects a Rule 4.3 review found in legal/06_RULE_4.3_CONFORMANCE.md and in what the book prints.

S-1 -- STALE COUNTS. legal/06 said "198 greens" and a worst-case scale of "0.3601" throughout. The
corpus has grown to 216 greens across the 12 courses that print real greens (a 13th course was
added; poppy-ridge ships blank greens by design and is not one of the 12), and the document's
"26 of 198 greens reach it, median 1:588" sentence predates that growth. Re-derived here off the
built markup, independently of tools/check_scale.py, the same way tests/test_r16_gates.py's
`_gated_green_scales()` already does for the worst-case figure alone:
  * total: 216 (not 198)
  * greens AT the 0.36 design ceiling: 27 (not 26) -- and re-running the SAME measurement over the
    PRIOR 198-green population also returns 27, so the "26" this document carried was already wrong
    before the 13th course existed; the corpus's growth changed the denominator and the median, not
    this count, because the added course's own worst green (0.3552) sits well below the cluster.
  * median: 1:593 (not 1:588)
  * worst: 0.3601 in : 5 yd (1:500), unchanged -- the added course's worst green is not the corpus's
    worst.
Every one of those is graded below against the CURRENT text of legal/06, never against a number
typed into this file, so the document cannot go stale again without this suite noticing.

S-2 -- THE FAQ'S OWN RECOMMENDATION WAS NOT FOLLOWED. Clarification 4.3a/1's FAQ closes with:
developers should "indicate on the cover or within a book's legend the scale of green images as
well as the overall size of the book." The book draws a physical 5-yd bar inside every green's own
viewBox -- genuinely better evidence, since it survives a mis-scaled printer and a ruler on it gives
the true scale -- but an official checking a book at a tournament reads WORDS, and none existed.

THE LEGEND CARD HAS NO ROOM: tests/test_r17_print.py measures monarch-bay's guide card at 1.19 px of
clearance in its own 3.5x5in box, and this project has clipped that card's tail twice already
splicing in far shorter additions than a whole new line. Measured the same way here (a candidate line
spliced into every shipped cover, laid out in chrome-headless-shell under print media): the pocket
cover has room -- 12.44 px of clearance on every course measured, against a card 480 px tall under
print media -- so generate.py's `cover_panel()` now prints the claim there instead, gated on
DISTRIBUTABLE (the same flag `_cover_badge()` uses for "DESIGNED TO CONFORM" itself, so a blank-green
book states no scale it does not print).

NEITHER FIGURE IN THE NEW COVER LINE IS TYPED. The card size is read from `config.CARD_W_IN` /
`CARD_H_IN` at render time, so a course that ever overrides "card" in its course.json prints its OWN
size; the scale is Rule 4.3's own ceiling, `generate.RULE_4_3_SCALE_CAP_IN_PER_5YD`, which this file
pins against `tools/check_scale.py`'s independently-defined `LIMIT_IN_PER_5YD` so the two copies (one
per module, because neither module may import the other without inverting an existing dependency
direction) cannot silently drift apart.

DISTRIBUTABLE IS NOT THE GATE THAT SEPARATES THE TWO EDITIONS. It gates SHARING, and the enlarged
(COACH=1) edition is deliberately NON-conforming -- past the scale cap on purpose -- yet all three
built enlarged books (merion, monarch-bay, philadelphia) are DISTRIBUTABLE=True, same as every
pocket book. Measured off generate.py's own source and off its output: `build_coach()` calls
`coach_cover_panel()`, never `cover_panel()`, and `coach_cover_panel()`'s compiled bytecode names
neither `cover_panel` nor `_scale_size_line` -- so the claim is architecturally unreachable from the
enlarged build, not merely unlikely under today's flags.
`test_the_conforming_scale_claim_never_appears_on_the_enlarged_non_conforming_edition` pins this
with a mutation: it splices `_scale_size_line()`'s own output into `coach_cover_panel()`'s real
output, proving the check fails against that BEFORE trusting it to pass against the real function.
"""
import glob
import html
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conftest import corpus_slugs                                        # noqa: E402


def _flat(text):
    return re.sub(r"\s+", " ", text)


LEGAL_06 = os.path.join(ROOT, "legal", "06_RULE_4.3_CONFORMANCE.md")


def _legal_06_text():
    with open(LEGAL_06, encoding="utf-8") as fh:
        return _flat(fh.read())


# ===========================================================================
# S-1 -- re-derive the corpus's green count and scale figures off the built markup
# ===========================================================================

def _gated_green_scales():
    """(in_per_5yd, slug, hole) for every green in every shipped POCKET book, worst first.

    Deliberately its OWN implementation, not an import of test_r16_gates.py's
    `_gated_green_scales` -- an independent re-derivation is a second opinion on the same claim,
    and importing one test module from another would make this file's numbers a re-statement of
    that file's rather than a check on it. Reads the shipped SVG's own `style="width:...in;
    height:...in"` against its `viewBox`, exactly as render_green.py wrote it (`wattr, hattr =
    f'{VBw*kf:.3f}in', f'{VBh*kf:.3f}in'` -- no browser needed, because nothing in the current
    stylesheet overrides those inline styles; see legal/06's own account of the CSS-specificity bug
    that WAS true once). Divided by the same per-green ground scale
    tools/check_scale.py's own `px_m_of` computes from dem_hd/holeNN.json, through geo's one figure
    of the Earth.
    """
    from geo import mlat, mlon
    rows = []
    for book in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "greenbook.html"))):
        slug = os.path.basename(os.path.dirname(book))
        if slug.startswith("_"):
            continue
        with open(book, encoding="utf-8") as fh:
            page = fh.read()
        for panel in re.split(r'(?=<div class="panel hole)', page)[1:]:
            hn = re.search(r'class="hnum"[^>]*>(\d+)<', panel)
            grn = panel.find('<div class="grn">')
            if not hn or grn < 0:
                continue
            svg = re.search(r'<svg viewBox="([^"]+)" style="width:([0-9.]+)in;height:([0-9.]+)in"',
                            panel[grn:])
            if not svg:
                continue
            vb = [float(v) for v in svg.group(1).split()]
            k = min(float(svg.group(2)) / vb[2], float(svg.group(3)) / vb[3])
            meta_p = os.path.join(ROOT, "courses", slug, "dem_hd", f"hole{int(hn.group(1)):02d}.json")
            if not os.path.isfile(meta_p):
                continue
            with open(meta_p, encoding="utf-8") as fh:
                m = json.load(fh)
            x0, y0, x1, y1 = m["bbox"]
            clat = m["green_center"][0]
            px_m = (((x1 - x0) * mlon(clat)) / m["W"] + ((y1 - y0) * mlat(clat)) / m["H"]) / 2.0
            rows.append((k * 4.572 / px_m, slug, int(hn.group(1))))
    rows.sort(reverse=True)
    return rows


# The design ceiling render_green.py sizes every green under (`legal_kf = 0.36 * px_m / 4.572`) --
# named here, at the SAME value check_scale.py calls TARGET_IN_PER_5YD, so "reaches the ceiling" has
# one definition rather than a fresh guess.
DESIGN_CEILING_IN_PER_5YD = 0.36

# How close to the ceiling a green has to print to count as "reaching" it. 0.003 is not a guess at
# the corpus: it sits inside the gap the corpus actually shows -- the ceiling cluster's floor is
# <0.0003 below DESIGN_CEILING_IN_PER_5YD (0.35975) and the next-highest green today, trump-national
# -los-angeles hole 15 at 0.3552, is >0.0045 below it -- so the split is unambiguous with wide margin
# on both sides. test_the_ceiling_cluster_is_a_real_gap_not_a_guessed_threshold below refuses to
# trust the count this produces once that margin closes to under half a band.
CEILING_BAND = 0.003


def _ceiling_cluster(vals_desc):
    """(cluster, rest) -- greens within CEILING_BAND of the design ceiling, and everything else."""
    cluster = [v for v in vals_desc if v >= DESIGN_CEILING_IN_PER_5YD - CEILING_BAND]
    rest = [v for v in vals_desc if v < DESIGN_CEILING_IN_PER_5YD - CEILING_BAND]
    return cluster, rest


def _corpus_scale_stats():
    """(total, cluster_count, gap, median_ratio, worst, worst_slug, worst_hole, lo_ratio, hi_ratio,
    courses, cluster_lo, cluster_hi, next_down, next_down_slug, next_down_hole).

    `gap` is cluster_floor - rest_ceiling: how much daylight separates "reaches the ceiling" from
    "does not", so a caller can refuse the split when the corpus closes it. Returns None if the
    corpus holds no pocket-book green at all.
    """
    import statistics
    rows = _gated_green_scales()
    if not rows:
        return None
    vals = [v for v, _s, _h in rows]
    cluster, rest = _ceiling_cluster(vals)
    gap = (min(cluster) - max(rest)) if cluster and rest else float("inf")
    med = statistics.median(vals)
    worst, worst_slug, worst_hole = rows[0]
    next_down, next_down_slug, next_down_hole = max(
        (r for r in rows if r[0] < DESIGN_CEILING_IN_PER_5YD - CEILING_BAND), key=lambda r: r[0])
    return dict(total=len(vals), cluster=len(cluster), gap=gap,
                median_ratio=round(180.0 / med), worst=worst, worst_slug=worst_slug,
                worst_hole=worst_hole, lo_ratio=round(180.0 / max(vals)),
                hi_ratio=round(180.0 / min(vals)), courses=len({s for _v, s, _h in rows}),
                cluster_lo=min(cluster), cluster_hi=max(cluster),
                next_down=next_down, next_down_slug=next_down_slug, next_down_hole=next_down_hole)



needs_corpus = pytest.mark.skipif(not corpus_slugs(), reason="courses/ is gitignored; nothing built here")


@needs_corpus
def test_the_ceiling_cluster_is_a_real_gap_not_a_guessed_threshold():
    """The 27-greens-reach-the-ceiling count means nothing if the split that produced it is close.

    Refuses to trust `_corpus_scale_stats`'s cluster count once the gap between "at the ceiling" and
    "not" shrinks below half of CEILING_BAND -- comfortably inside the corpus's actual margin today
    (cluster floor 0.35975, next-highest green 0.3552 at trump-national-los-angeles hole 15, gap
    0.00455 against a 0.003 band, over 3x the refusal threshold).
    """
    stats = _corpus_scale_stats()
    if stats is None:
        pytest.skip("no pocket-book green built here")
    assert stats["gap"] > CEILING_BAND * 0.5, (
        f"the ceiling-cluster split has only {stats['gap']:.5f} of daylight left around a "
        f"{CEILING_BAND} band -- re-examine _ceiling_cluster before trusting the {stats['cluster']} "
        f"count it produced; the corpus may now have a green that genuinely sits between the two "
        f"groups.")


@needs_corpus
def test_legal_06_states_the_corpus_measured_green_count_ceiling_cluster_and_median():
    """Every population figure legal/06 states about the pocket-book corpus, re-derived and checked.

    Fails loudly, and by design, if legal/06 is ever edited to restate a number without re-running
    this derivation -- which is exactly what happened when a 13th course was added and the document
    kept saying "198"/"26"/"1:588".
    """
    stats = _corpus_scale_stats()
    if stats is None:
        pytest.skip("no pocket-book green built here")
    text = _legal_06_text()

    m = re.search(r"across all (\d+) greens in the corpus's (\d+) courses", text)
    assert m, "legal/06 no longer states the ceiling-measurement population in the expected wording"
    assert int(m.group(1)) == stats["total"], (
        f"legal/06 says the ceiling measurement covers {m.group(1)} greens; the built markup has "
        f"{stats['total']}.")

    m = re.search(r"\*\*(\d+) reach it\*\*", text)
    assert m, "legal/06 no longer states how many greens reach the design ceiling"
    assert int(m.group(1)) == stats["cluster"], (
        f"legal/06 says {m.group(1)} greens reach the 0.36 design ceiling; re-derived off the built "
        f"markup, {stats['cluster']} do (gap {stats['gap']:.5f} around a {CEILING_BAND} band, so the "
        f"split is not ambiguous).")

    course_hits = list(re.finditer(r"in the (?:corpus's )?(\d+) courses that print real greens", text))
    assert len(course_hits) >= 2, (
        f"legal/06 no longer states the course-count population in both expected places (found "
        f"{len(course_hits)})")
    for m in course_hits:
        assert int(m.group(1)) == stats["courses"], (
            f"legal/06 says the ceiling measurement spans {m.group(1)} courses; the built markup "
            f"has {stats['courses']} distinct courses contributing a gated green.")

    # The cluster's RANGE (its printed floor specifically) is graded in
    # test_legal_06_states_the_browser_measured_ceiling_cluster_range below, against
    # tools/check_scale.py's own browser-layout measurement, not here. The floor sits on a rounding
    # boundary between that method and this function's static-markup one -- 0.359742 vs 0.359755,
    # 0.3597 vs 0.3598 -- and legal/06 says which one it prints and why. Checking it against BOTH
    # methods in two different tests would make one of them wrong by construction.

    m = re.search(r"next value down\s+([0-9.]+) \(([\w‑-]+) hole (\d+)", text)
    assert m, "legal/06 no longer states the next-value-down figure in the expected wording"
    assert round(float(m.group(1)), 4) == round(stats["next_down"], 4), (
        f"legal/06 states the next value down as {m.group(1)}; re-derived off the built markup it "
        f"is {stats['next_down']:.4f}.")
    slug = m.group(2).replace("‑", "-")
    assert (slug, int(m.group(3))) == (stats["next_down_slug"], stats["next_down_hole"]), (
        f"legal/06 attributes the next-value-down figure to {slug} hole {m.group(3)}; re-derived "
        f"off the built markup it is {stats['next_down_slug']} hole {stats['next_down_hole']}.")

    for label, m in (("ceiling-measurement", re.search(r"the next value down[^*]*?median \*\*1:(\d+)\*\*",
                                                        text)),
                      ("per-hole-range", re.search(r"roughly 1:\d+ to 1:\d+; median 1:(\d+)\)", text))):
        assert m, f"legal/06's {label} sentence no longer states a median in the expected wording"
        assert int(m.group(1)) == stats["median_ratio"], (
            f"legal/06's {label} sentence states the median scale as 1:{m.group(1)}; re-derived off "
            f"the built markup it is 1:{stats['median_ratio']}.")

    m = re.search(r"\*\*(\d+)/(\d+) conforming, worst ([0-9.]+) in : 5 yd \(1:(\d+)\)\*\*, "
                  r"([0-9.]+)% margin", text)
    assert m, "legal/06 no longer states the gate's latest run in the expected wording"
    passed, of, worst_str, worst_ratio, margin = m.groups()
    assert passed == of == str(stats["total"]), (
        f"legal/06's gate line says {passed}/{of} conforming; the built markup has {stats['total']} "
        f"pocket-book greens.")
    assert round(float(worst_str), 4) == round(stats["worst"], 4), (
        f"legal/06's gate line states the worst gated reading as {worst_str} in : 5 yd; re-derived "
        f"off the built markup it is {stats['worst']:.4f} ({stats['worst_slug']} hole "
        f"{stats['worst_hole']}).")
    assert int(worst_ratio) == round(180.0 / stats["worst"]), (
        f"legal/06's gate line states the worst reading as 1:{worst_ratio}; re-derived it is "
        f"1:{round(180.0 / stats['worst'])}.")
    margin_now = (1 - stats["worst"] / 0.375) * 100
    assert abs(float(margin) - margin_now) < 0.05, (
        f"legal/06 states a {margin}% margin against the 0.375 in cap; re-derived off the worst "
        f"reading it is {margin_now:.1f}%.")

    m = re.search(r"roughly 1:(\d+) to 1:(\d+)", text)
    assert m, "legal/06 no longer states the per-hole scale range in the expected wording"
    assert (int(m.group(1)), int(m.group(2))) == (stats["lo_ratio"], stats["hi_ratio"]), (
        f"legal/06 states the per-hole range as 1:{m.group(1)} to 1:{m.group(2)}; re-derived off the "
        f"built markup it is 1:{stats['lo_ratio']} to 1:{stats['hi_ratio']}.")

    assert f"outside** the {stats['total']}/{stats['total']} gate" in text, (
        f"legal/06's account of the enlarged edition no longer says it sits outside the "
        f"{stats['total']}/{stats['total']} gate -- it still names the population this replaced.")


@pytest.mark.slow          # lays every pocket book out in a browser
@needs_corpus
def test_legal_06_states_the_browser_measured_ceiling_cluster_range():
    """The ceiling cluster's printed FLOOR sits exactly on a rounding boundary between two ways of
    measuring it, and legal/06 says which one is authoritative: `tools/check_scale.py`'s own
    browser-layout measurement (what actually gets laid out under print media), the same method
    that produces the worst-gated reading two paragraphs above -- not the static-markup parse
    `_gated_green_scales` uses for speed elsewhere in this file, which reads 0.359755 -> 0.3598
    where the browser reads 0.359742 -> 0.3597 (a 1.25e-05 difference). Grading the printed floor
    against the FAST method here would make this test wrong by construction; this is the one place
    in this file that pays for a browser launch to check a single digit.

    The ceiling (0.3601) is not sensitive to the same boundary -- both methods round to it -- so it
    is checked here too, off the same measurement, for one self-consistent figure rather than a
    floor from one method beside a ceiling from another.
    """
    import statistics
    import check_scale as cs
    courses = sorted(p.parent.name for p in (cs.ROOT / "courses").glob("*/greenbook.html")
                      if not p.parent.name.startswith("_"))
    rendered = cs.measure_rendered(courses)
    if rendered is None:
        pytest.skip("no browser to measure the rendered layout in")
    vals = sorted((v for c in courses for v in (rendered.get(c) or {}).get("per", {}).values()),
                  reverse=True)
    if not vals:
        pytest.skip("no pocket-book green measured in the browser")
    cluster, rest = _ceiling_cluster(vals)
    assert (min(cluster) - max(rest) if cluster and rest else float("inf")) > CEILING_BAND * 0.5, (
        "the browser-layout cluster split has too little daylight to trust -- see "
        "test_the_ceiling_cluster_is_a_real_gap_not_a_guessed_threshold's reasoning, re-applied here "
        "to the browser measurement instead of the static one")

    text = _legal_06_text()
    m = re.search(r"a clear cluster printing ([0-9.]+)[–-]([0-9.]+) in : 5 yd", text)
    assert m, "legal/06 no longer states the ceiling cluster's range in the expected wording"
    assert round(float(m.group(1)), 4) == round(min(cluster), 4), (
        f"legal/06 states the ceiling cluster's floor as {m.group(1)}, attributed to the browser-"
        f"layout method; re-measured under print media it is {min(cluster):.6f} -> "
        f"{round(min(cluster), 4)}.")
    assert round(float(m.group(2)), 4) == round(max(cluster), 4), (
        f"legal/06 states the ceiling cluster's top as {m.group(2)}; re-measured under print media "
        f"it is {max(cluster):.6f} -> {round(max(cluster), 4)}.")


@needs_corpus
def test_legal_06_states_the_true_card_default_and_that_no_course_overrides_it():
    """The 'Book size' bullet claims config.py's own default AND that no course.json overrides it.

    The second half is a scan across every course.json in the corpus, not an assertion trusted from
    memory -- a course that starts setting "card" makes the sentence claiming otherwise false, and
    this is what would catch that.
    """
    cfg, _generate, _dist = _engine(CORPUS[0])
    text = _legal_06_text()

    m = re.search(r"cards are \*\*([0-9.]+) [×x] ([0-9.]+) in\*\*", text)
    assert m, "legal/06 no longer states the pocket book's card size in the expected wording"
    assert (round(float(m.group(1)), 1), round(float(m.group(2)), 1)) == \
           (round(cfg.CARD_DEFAULT_W_IN, 1), round(cfg.CARD_DEFAULT_H_IN, 1)), (
        f"legal/06 states the card size as {m.group(1)} x {m.group(2)} in; config.py's own "
        f"CARD_DEFAULT_W_IN/CARD_DEFAULT_H_IN are {cfg.CARD_DEFAULT_W_IN} x {cfg.CARD_DEFAULT_H_IN}.")

    m = re.search(r"CARD_DEFAULT_W_IN, CARD_DEFAULT_H_IN = ([0-9.]+), ([0-9.]+)", text)
    assert m, "legal/06 no longer quotes config.py's CARD_DEFAULT_W_IN/H_IN literal in the expected form"
    assert (float(m.group(1)), float(m.group(2))) == (cfg.CARD_DEFAULT_W_IN, cfg.CARD_DEFAULT_H_IN), (
        f"legal/06 quotes 'CARD_DEFAULT_W_IN, CARD_DEFAULT_H_IN = {m.group(1)}, {m.group(2)}'; the "
        f"real values in config.py are {cfg.CARD_DEFAULT_W_IN}, {cfg.CARD_DEFAULT_H_IN}.")

    assert 'no course sets `"card"`' in text, (
        "legal/06 no longer claims that no course overrides the card size -- if a course now does, "
        "the sentence must say so instead of asserting the opposite")
    overridden = []
    for cj in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")):
        slug = os.path.basename(os.path.dirname(cj))
        if slug.startswith("_"):
            continue
        with open(cj, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("card"):
            overridden.append(slug)
    assert not overridden, (
        f"legal/06 says no course.json sets \"card\", but {overridden} do -- their books do NOT "
        f"print {cfg.CARD_DEFAULT_W_IN} x {cfg.CARD_DEFAULT_H_IN} in, and the sentence claiming "
        f"otherwise is now false")


def test_the_re_derivation_would_have_refused_the_stale_figures_it_replaced():
    """Proves the checks above have teeth, without needing the gitignored corpus to do it.

    Runs the SAME regex extraction the test above uses against a hand-built "document" carrying the
    exact stale wording this file's own docstring quotes -- "26 of 198 greens reach it, median
    1:588" and "198/198 conforming" -- paired with the CURRENT corpus's re-derived numbers, and
    checks that the comparison flags every one of them. A grader that cannot be shown failing is not
    known to be checking anything.
    """
    stale_doc = _flat("""
        measured off the built markup across all 198 greens in the corpus's 11 courses,
        26 reach it, median 1:588.
        latest run: 198/198 conforming, worst 0.3601 in : 5 yd (1:500), 4.0% margin.
        roughly 1:500 to 1:944; median 1:588.
        sits outside the 198/198 gate above.
    """)
    current = dict(total=216, cluster=27, median_ratio=593, worst=0.3601, worst_slug="x",
                   worst_hole=1, lo_ratio=500, hi_ratio=944)

    mismatches = []
    m = re.search(r"across all (\d+) greens in the corpus's (\d+) courses", stale_doc)
    if int(m.group(1)) != current["total"]:
        mismatches.append("total")
    m = re.search(r"(\d+) reach it", stale_doc)
    if int(m.group(1)) != current["cluster"]:
        mismatches.append("cluster")
    for m in re.finditer(r"median 1:(\d+)", stale_doc):
        if int(m.group(1)) != current["median_ratio"]:
            mismatches.append("median")
    m = re.search(r"(\d+)/(\d+) conforming", stale_doc)
    if m.group(1) != str(current["total"]):
        mismatches.append("gate-population")
    m = re.search(r"outside the (\d+)/(\d+) gate", stale_doc)
    if m.group(1) != str(current["total"]):
        mismatches.append("gate-reference")

    assert mismatches == ["total", "cluster", "median", "median", "gate-population",
                           "gate-reference"], (
        f"the stale-document fixture was supposed to disagree with the current corpus on every "
        f"figure it quotes; it disagreed on {mismatches} instead. Either the fixture text or the "
        f"comparison logic has drifted from what test_legal_06_states_the_corpus_measured_... "
        f"actually checks.")

    # and the CURRENT wording -- what legal/06 says after the fix -- must agree with itself
    current_doc = _flat("""
        measured off the built markup across all 216 greens in the corpus's 12 courses,
        27 reach it, median 1:593.
        latest run: 216/216 conforming, worst 0.3601 in : 5 yd (1:500), 4.0% margin.
        roughly 1:500 to 1:944; median 1:593.
        sits outside the 216/216 gate above.
    """)
    m = re.search(r"across all (\d+) greens in the corpus's (\d+) courses", current_doc)
    assert int(m.group(1)) == current["total"]
    m = re.search(r"(\d+) reach it", current_doc)
    assert int(m.group(1)) == current["cluster"]
    assert all(int(mm.group(1)) == current["median_ratio"]
               for mm in re.finditer(r"median 1:(\d+)", current_doc))


# ===========================================================================
# S-2 -- the cover states the scale cap and card size in words, derived, and it fits
# ===========================================================================

def _engine(slug):
    """(config, generate, distribution) bound to `slug`, or a skip.

    Same shape as tests/test_r17_print.py's `_engine`: `generate` and `distribution` are popped too,
    because conftest's `_bind_a_course` (autouse in this directory) does not drop them, and both hold
    module-level state keyed to the course bound when they were first imported (`DISTRIBUTABLE =
    distribution.is_distributable(config.COURSE)` in generate.py).
    """
    for m in ("config", "render_hole", "render_green", "generate", "distribution"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    try:
        import config
        import generate
        import distribution
    except SystemExit as e:                                      # pragma: no cover - env-dependent
        pytest.skip(f"cannot bind {slug}: {e}")
    return config, generate, distribution


CORPUS = corpus_slugs()
needs_geom = pytest.mark.skipif(not CORPUS, reason="per-course geometry is gitignored; nothing to bind")


def _scale_size_text(cover_html):
    m = re.search(r"SCALE 1:(\d+) OR SMALLER[^<]*?CARD ([0-9.]+) [^<]*? ([0-9.]+) IN", _flat(cover_html))
    return m


@needs_geom
def test_generate_and_check_scale_agree_on_rule_4_3s_own_ceiling():
    """generate.py's copy of the Rule's scale cap and tools/check_scale.py's copy must be the same
    number.

    Neither module may import the other without inverting an existing dependency direction (tools/
    scripts import the engine; the engine does not import tools/), so each keeps its own named
    constant. This is the seam that keeps the two from drifting apart the way legal/06's copy of the
    worst-gated-reading figure once did from tools/check_scale.py's.
    """
    import check_scale
    _cfg, generate, _dist = _engine(CORPUS[0])
    assert generate.RULE_4_3_SCALE_CAP_IN_PER_5YD == check_scale.LIMIT_IN_PER_5YD, (
        f"generate.py states the Rule 4.3 scale cap as {generate.RULE_4_3_SCALE_CAP_IN_PER_5YD}; "
        f"tools/check_scale.py gates every green against {check_scale.LIMIT_IN_PER_5YD}. A cover that "
        f"quotes one number while the gate enforces another is not a claim that can be trusted.")


@needs_geom
def test_the_cover_states_the_true_card_size_and_scale_cap_derived_from_config():
    """The words on the cover must be config.py's real card size and the Rule's real cap -- not a
    typed copy of either.

    Rebinds to a SECOND card size via monkeypatch and re-renders: if the cover's words did not move
    with them, they would be a typed literal wearing a config-derived costume.
    """
    cfg, generate, _dist = _engine(CORPUS[0])
    assert generate.DISTRIBUTABLE, f"{CORPUS[0]} is not distributable; pick a different course"

    m = _scale_size_text(generate.cover_panel())
    assert m, "cover_panel() no longer prints a SCALE/CARD line in the expected wording"
    cap, w, h = m.groups()
    assert int(cap) == round(180.0 / generate.RULE_4_3_SCALE_CAP_IN_PER_5YD), (
        f"the cover states the scale cap as 1:{cap}; Rule 4.3's own ceiling "
        f"(RULE_4_3_SCALE_CAP_IN_PER_5YD={generate.RULE_4_3_SCALE_CAP_IN_PER_5YD}) is "
        f"1:{round(180.0 / generate.RULE_4_3_SCALE_CAP_IN_PER_5YD)}.")
    assert float(w) == round(cfg.CARD_W_IN, 1) and float(h) == round(cfg.CARD_H_IN, 1), (
        f"the cover states the card size as {w} x {h} in; config.py's own CARD_W_IN/CARD_H_IN are "
        f"{cfg.CARD_W_IN} x {cfg.CARD_H_IN}.")

    # Now change what config actually is, and confirm the cover's words move with it -- this is the
    # difference between "derived from config.py" and "happens to currently match config.py".
    import unittest.mock as mock
    with mock.patch.object(cfg, "CARD_W_IN", 4.2), mock.patch.object(cfg, "CARD_H_IN", 6.8):
        m2 = _scale_size_text(generate.cover_panel())
        assert m2, "cover_panel() stopped printing the SCALE/CARD line under a patched card size"
        assert (m2.group(2), m2.group(3)) == ("4.2", "6.8"), (
            f"patched config.CARD_W_IN/CARD_H_IN to 4.2 x 6.8 and the cover still printed "
            f"{m2.group(2)} x {m2.group(3)} -- the card-size words are not actually reading "
            f"config.py at render time.")


def _scale_size_line_text(generate_mod):
    """The literal, entity-decoded text content of `_scale_size_line()`'s own `<text>` element."""
    m = re.search(r"<text\b[^>]*>(.*?)</text>", generate_mod._scale_size_line(), re.S)
    assert m, "_scale_size_line() no longer emits a single <text> element"
    return html.unescape(m.group(1))


@needs_geom
def test_legal_06_quotes_the_cover_lines_actual_text_verbatim():
    """legal/06 quotes "SCALE 1:480 OR SMALLER . CARD 3.5 x 5.0 IN" as what the code prints.

    A quote is a stronger claim than a paraphrase -- it says these are the exact characters on the
    page -- and nothing checked that before this test. If `_scale_size_line()`'s wording ever
    changes (a word added, the middot swapped for a different separator, the capitalisation
    changed), the quote in legal/06 would silently become a misquote: the same defect class commit
    2de00fe set out to close for the green-count figures, but for prose instead of a number.
    """
    _cfg, generate, _dist = _engine(CORPUS[0])
    assert generate.DISTRIBUTABLE, f"{CORPUS[0]} is not distributable; pick a different course"
    real = _scale_size_line_text(generate)

    text = _legal_06_text()
    m = re.search(r'now prints \*\*"(.+?)"\*\*', text)
    assert m, "legal/06 no longer quotes the cover's scale/size line in the expected wording"
    quoted = html.unescape(m.group(1))
    assert quoted == real, (
        f"legal/06 quotes the cover as printing {quoted!r}; the code's actual, current text is "
        f"{real!r}. A quotation mark is a promise these are the same characters.")


@needs_geom
def test_the_scale_size_line_is_absent_from_a_non_distributable_book():
    """Poppy Ridge prints no green image, so it has nothing to disclose a scale for.

    Checked both on the real non-distributable course in the corpus AND with DISTRIBUTABLE patched
    False on a normally-distributable one, so the assertion holds whichever course happens to be
    non-distributable in a given checkout.
    """
    non_distributable = [s for s in CORPUS
                          if not _engine(s)[1].DISTRIBUTABLE]
    if non_distributable:
        _cfg, generate, _dist = _engine(non_distributable[0])
        assert _scale_size_text(generate.cover_panel()) is None, (
            f"{non_distributable[0]} is not distributable and prints no green image, but its cover "
            f"still states a Rule 4.3 scale cap.")

    cfg, generate, _dist = _engine(CORPUS[0])
    import unittest.mock as mock
    with mock.patch.object(generate, "DISTRIBUTABLE", False):
        assert _scale_size_text(generate.cover_panel()) is None, (
            "with DISTRIBUTABLE patched False, cover_panel() still states a Rule 4.3 scale cap.")


def _enlarged_courses():
    """Slugs with an enlarged (COACH=1) edition already built. Read-only glob, same shape as
    tools/check_scale.py's `enlarged_courses`."""
    return sorted(os.path.basename(os.path.dirname(p))
                  for p in glob.glob(os.path.join(ROOT, "courses", "*", "greenbook_coach.html"))
                  if not os.path.basename(os.path.dirname(p)).startswith("_"))


def _assert_no_scale_claim(html, where):
    m = _scale_size_text(html)
    assert m is None, (
        f"{where} states a Rule 4.3 scale cap (\"SCALE 1:{m.group(1)} OR SMALLER\") -- that claim "
        f"is FALSE on the enlarged edition, which is built past the cap on purpose.")


@pytest.mark.skipif(not _enlarged_courses(), reason="no enlarged (COACH=1) edition built here")
def test_the_conforming_scale_claim_never_appears_on_the_enlarged_non_conforming_edition():
    """The enlarged/COACH edition is deliberately NON-conforming, and DISTRIBUTABLE does not know it.

    `_scale_size_line()` is gated on DISTRIBUTABLE because that is the flag `_cover_badge()` already
    uses to decide whether a book carries the "DESIGNED TO CONFORM" claim at all -- but DISTRIBUTABLE
    answers "may this book be shared", not "does this book conform". All three enlarged books built in
    this corpus (merion, monarch-bay, philadelphia) are DISTRIBUTABLE=True, exactly like every pocket
    book, so a regression that routed cover_panel()'s output (or just `_scale_size_line()`'s) into the
    enlarged build would sail past that flag and print "SCALE 1:480 OR SMALLER" on a cover whose
    greens tools/check_scale.py measures at up to 0.599 in : 5 yd (1:301, philadelphia-country-club)
    -- 60% past the very cap the line would claim, on 53 of that measurement's 54 enlarged greens.
    Its card is genuinely the same physical 3.5 x 5.0 in as the pocket book (`build_coach`'s own
    `CW, CH = config.CARD_W_IN, config.CARD_H_IN`), so only the SCALE half of a leaked claim would be
    false -- which is exactly why gating on card size, or on DISTRIBUTABLE, could not have caught
    this. What actually keeps the claim off this cover today is architectural, not a flag: build_coach
    calls `coach_cover_panel()`, main()/build_deck() calls `cover_panel()`, and neither function is
    reachable from the other's build path -- read directly off generate.py, not assumed.

    THE MUTATION, so this test is shown catching the regression it exists for before it is trusted to
    clear the real code: `coach_cover_panel()`'s own output is spliced with `_scale_size_line()`'s
    output -- simulating the exact leak the paragraph above describes -- and `_assert_no_scale_claim`
    is proven to raise against that BEFORE it is asked to pass against the unmutated function.
    """
    checked = []
    for slug in _enlarged_courses():
        cfg, generate, _dist = _engine(slug)
        assert generate.DISTRIBUTABLE, (
            f"{slug}'s enlarged edition is not DISTRIBUTABLE -- this test needs at least one "
            f"DISTRIBUTABLE=True enlarged course to prove that flag is not what keeps the scale "
            f"claim off its cover; every enlarged book in this corpus was expected to be one")
        coach_html = generate.coach_cover_panel("")

        leaked = coach_html.replace("</svg></div>", generate._scale_size_line() + "</svg></div>", 1)
        assert "SCALE 1:" in leaked, (
            f"{slug}: the simulated leak did not actually insert a scale claim -- "
            f"coach_cover_panel()'s closing tag no longer matches what this splice expects")
        with pytest.raises(AssertionError):
            _assert_no_scale_claim(leaked, f"{slug} (simulated leak)")

        _assert_no_scale_claim(coach_html, slug)
        checked.append(slug)

    assert checked, "no enlarged edition was checked"


def _build_coach_html_in_memory(generate_mod, coach_name=""):
    """Call `build_coach()` for real and return the deck HTML it WOULD have written -- no disk write.

    `write_book` is the only place `build_coach()` opens a file (staged and renamed -- see its own
    docstring on why), so intercepting just that call captures the exact bytes the shipped
    `greenbook_coach.html` would contain without ever creating, truncating or touching one.
    `courses/` is the only copy of the corpus and has no undo, so this is deliberately narrower than
    monkeypatching `open()` or redirecting `COURSE_DIR` -- it patches the one function that writes,
    calls the real, un-mutated `build_coach()`, and restores it in a `finally` whether or not
    `build_coach()` raises.
    """
    import unittest.mock as mock
    captured = {}
    def _capture(out, html):
        captured["out"], captured["html"] = out, html
    with mock.patch.object(generate_mod, "write_book", _capture):
        generate_mod.build_coach(coach_name)
    assert "html" in captured, "build_coach() finished without calling write_book() at all"
    return captured["html"]


@pytest.mark.skipif(not _enlarged_courses(), reason="no enlarged (COACH=1) edition built here")
def test_the_assembled_enlarged_deck_itself_never_carries_the_conforming_scale_claim():
    """Closes the other half of the regression class the test above cannot see.

    That test calls `coach_cover_panel()` DIRECTLY, so it only detects a leak INTO that function's own
    body. It cannot see a leak at the CALL SITE -- `build_coach()`'s
    `cards = [coach_cover_panel(coach_name), coach_about_card()]` changed to
    `cards = [cover_panel(), coach_about_card()]` -- because it never calls `build_coach()` at all.
    Reproduced by hand: with that one-line edit in place, the pytest module in this file passing
    `-v` reported every test PASSED, including the mutation arm above, while the assembled deck
    carried "SCALE 1:480 OR SMALLER . CARD 3.5 x 5.0 IN" on greens `tools/check_scale.py` measures up
    to 0.599 in : 5 yd (1:301) -- 60% past the cap that line claims.

    So this arm asserts on what the EDITION actually produces: `build_coach()`'s real output,
    captured via `_build_coach_html_in_memory` (no disk write -- see that helper), never on
    `coach_cover_panel()`'s return value in isolation. Kept ALONGSIDE the arm above rather than in
    place of it -- that one still catches a leak INTO `coach_cover_panel()` (or `_scale_size_line()`)
    cheaply, without a full deck build, and losing it would narrow coverage rather than widen it.

    THE MUTATION here is `generate.coach_cover_panel` patched to return the POCKET cover instead of
    its own -- the same observable defect the call-site edit above produces (the enlarged deck's
    cover card becomes `cover_panel()`'s output), reached without editing generate.py's source on
    disk mid-test. Proven to turn this assertion red before it is trusted to pass on the real,
    unpatched `build_coach()`.
    """
    import unittest.mock as mock
    checked = []
    for slug in _enlarged_courses():
        cfg, generate, _dist = _engine(slug)

        with mock.patch.object(generate, "coach_cover_panel", lambda _name: generate.cover_panel()):
            leaked_deck = _build_coach_html_in_memory(generate)
        assert "SCALE 1:" in leaked_deck, (
            f"{slug}: patching coach_cover_panel to return the pocket cover did not actually put a "
            f"scale claim into the assembled deck -- the simulated regression did not reproduce")
        assert _scale_size_text(leaked_deck) is not None, (
            f"{slug}: 'SCALE 1:' appears in the leaked deck but not in the exact wording "
            f"_scale_size_text expects -- re-check that regex before trusting the real assertion below")

        real_deck = _build_coach_html_in_memory(generate)
        assert _scale_size_text(real_deck) is None, (
            f"{slug}: the ASSEMBLED enlarged deck -- build_coach()'s real output, not "
            f"coach_cover_panel() in isolation -- states a Rule 4.3 scale cap. That claim is false: "
            f"this edition is built past the cap on purpose.")
        checked.append(slug)

    assert checked, "no enlarged edition's assembled deck was checked"



def _shell():
    import export_pdf
    return export_pdf._headless_shell()


@pytest.mark.slow          # lays every distributable cover out in a browser
@needs_geom
def test_the_scale_size_line_costs_the_cover_no_room():
    """Card space is scarce here too, so the fix is measured, not assumed.

    `.cover` is `overflow:hidden` at the card's own 3.5x5in size with `padding:0` (it fills the
    whole card, unlike every other panel's 0.07in inset), and a self-validating probe -- a text node
    parked one card-height below the card box, which must come back as the lowest thing measured or
    this test cannot see clipped text -- proves the harness would notice an overflow before trusting
    its silence on the real content.

    Measured across the corpus's distributable books at 12.44 px of clearance to the card's own
    bottom edge (480 px tall under print media): this asserts merely that the number stays positive,
    not that it stays exactly 12.44, since a future redesign of the cover is expected to move it.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    exe = _shell()
    rows = []
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception:
            pytest.skip("no browser available")
        page = b.new_page()
        page.emulate_media(media="print")
        JS = """() => {
            const w = document.querySelector('#w');
            const wb = w.getBoundingClientRect();
            let bot = -1e9, who = null;
            document.querySelectorAll('text').forEach(t => {
                const r = t.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                if (r.bottom > bot) { bot = r.bottom; who = t.textContent.slice(0, 30); }
            });
            return {slack: +(wb.bottom - bot).toFixed(2), who};
        }"""
        PROBE = ('<text x="175" y="2000" font-size="6">PROBE</text>')
        checked = []
        for slug in CORPUS:
            cfg, generate, _dist = _engine(slug)
            if not generate.DISTRIBUTABLE:
                continue
            book = os.path.join(ROOT, "courses", slug, "greenbook.html")
            if not os.path.exists(book):
                continue
            with open(book, encoding="utf-8") as fh:
                css = re.search(r"<style>(.*?)</style>", fh.read(), re.S)
            if not css:
                continue
            panel = generate.cover_panel()
            box = (f"position:relative;width:{cfg.CARD_W_IN}in;height:{cfg.CARD_H_IN}in;"
                   f"overflow:hidden")
            wrap = lambda inner: (
                "<!DOCTYPE html><html><head><meta charset='utf-8'><style>*{box-sizing:border-box}"
                f"html,body{{margin:0;padding:0;background:#fff}}#w{{{box}}}"
                f"{css.group(1)}</style></head><body><div id='w'>{inner}</div></body></html>")
            page.set_content(wrap(panel.replace("</svg></div>", PROBE + "</svg></div>")))
            seen = page.evaluate(JS)
            assert seen["slack"] < 0 and seen["who"] == "PROBE", (
                f"{slug}: the probe parked below the card was not the lowest thing measured "
                f"({seen['who']!r} at {seen['slack']} px) -- this test cannot see clipped text and "
                f"its silence would mean nothing")
            page.set_content(wrap(panel))
            got = page.evaluate(JS)
            rows.append((slug, got["slack"], got["who"]))
            checked.append(slug)
        b.close()

    assert len(checked) >= 1, "no distributable book with a built cover was measured"
    over = [r for r in rows if r[1] < 0]
    assert not over, (
        "the new SCALE/CARD line now overflows the cover's own 3.5x5in box:\n  "
        + "\n  ".join(f"{s}: {sl:+.2f} px past the card, last element {w!r}" for s, sl, w in over))


_CLEARANCE_JS = """() => {
    const c = document.querySelector('#w');
    const cb = c.getBoundingClientRect();
    let bot = -1e9;
    document.querySelectorAll('#w *').forEach(e => {
        if (e.closest('svg') && e.tagName.toLowerCase() !== 'text') return;
        if (e.tagName.toLowerCase() !== 'text' &&
            !([...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length))) return;
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return;
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.bottom > bot) bot = r.bottom;
    });
    return +(cb.bottom - bot).toFixed(4);
}"""


def _measure_clearance(page, css, cfg, panel):
    """Card-box bottom minus the lowest inked text's bottom, in px, under print media.

    ONE js probe for both cards this file measures clearance on: `.grn svg` text lives inside an
    <svg> and `.abtxt`'s prose does not, so the walk keeps an SVG subtree only down to its own
    <text> leaves and everything else only if it carries a real text node -- the same two rules
    tests/test_r17_print.py's overflow probe and this file's cover-overflow test apply separately,
    unified here because this function measures both cards.
    """
    box = f"position:relative;width:{cfg.CARD_W_IN}in;height:{cfg.CARD_H_IN}in;overflow:hidden"
    html_doc = ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>*{box-sizing:border-box}"
                f"html,body{{margin:0;padding:0;background:#fff}}#w{{{box}}}{css}</style></head>"
                f"<body><div id='w'>{panel}</div></body></html>")
    page.set_content(html_doc)
    return page.evaluate(_CLEARANCE_JS)


@pytest.mark.slow          # lays every distributable cover AND legend card out in a browser, twice
@needs_geom
def test_legal_06_states_the_measured_cover_and_legend_clearance():
    """The 'Scale & size, in words, on the cover' bullet quotes two MEASURED clearances -- 12.44 px
    on the pocket cover (every distributable course), 1.19 px on monarch-bay's legend card -- as
    evidence for why the line went on the cover and not the legend. Re-measured here, independently
    of tests/test_r17_print.py's own figure for the legend card (a second opinion on the same claim,
    not a re-statement of it, the way tests/test_r16_gates.py's worst-gated-reading check and this
    file's own `_gated_green_scales` are independent of each other), in the same browser under the
    same print media every other measurement in this file uses.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    exe = _shell()
    cover_rows, legend_rows = [], []
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception:
            pytest.skip("no browser available")
        page = b.new_page()
        page.emulate_media(media="print")
        for slug in CORPUS:
            cfg, generate, _dist = _engine(slug)
            if not generate.DISTRIBUTABLE:
                continue
            book = os.path.join(ROOT, "courses", slug, "greenbook.html")
            if not os.path.exists(book):
                continue
            with open(book, encoding="utf-8") as fh:
                css = re.search(r"<style>(.*?)</style>", fh.read(), re.S)
            if not css:
                continue
            cover_rows.append((slug, _measure_clearance(page, css.group(1), cfg,
                                                          generate.cover_panel())))
            generate.build_deck()      # the guide card's conditional rows need GREENS/LAYOUTS filled
            legend_rows.append((slug, _measure_clearance(page, css.group(1), cfg,
                                                           generate.guide_panel())))
        b.close()

    assert len(cover_rows) >= 1 and len(legend_rows) >= 1, "no distributable book was measured"

    text = _legal_06_text()

    cover_vals = {round(v, 2) for _s, v in cover_rows}
    assert len(cover_vals) == 1, (
        f"the cover's SCALE/CARD line clearance is not the same across every course measured: "
        f"{sorted(cover_rows, key=lambda r: r[1])} -- legal/06 states one figure for all of them")
    m = re.search(r"with ([0-9.]+) px of\s*\n?\s*clearance to the card's own edge", text)
    assert m, "legal/06 no longer states the cover's measured clearance in the expected wording"
    assert round(float(m.group(1)), 2) == next(iter(cover_vals)), (
        f"legal/06 states the cover's clearance as {m.group(1)} px; re-measured under print media "
        f"it is {next(iter(cover_vals)):.2f} px on every distributable course.")

    # EVERY BOOK AT THE MINIMUM MUST BE NAMED, not just one of them, and the tie is why this is not a
    # single-slug match any more. monarch-bay held the tightest legend card alone at 1.19 px; the
    # wetland/dry-channel split added a legend row to the six books that draw the not-water grey, and
    # micke-grove -- which had 14.73 px and draws one dry channel -- landed on exactly the same 1.19.
    # "The tightest card is monarch-bay" is now false by omission, and a doc that names one of two equally
    # tight cards would let the other one drift unwatched, which is the whole thing this assertion is for.
    tight_val = min(v for _s, v in legend_rows)
    at_min = sorted(s for s, v in legend_rows if round(v, 2) == round(tight_val, 2))
    m = re.search(r"([0-9.]+) px of clearance in its own [0-9.]+ [×x] [0-9.]+ in box on "
                  r"([^(]+)", text)
    assert m, "legal/06 no longer states the legend card's measured clearance in the expected wording"
    assert round(float(m.group(1)), 2) == round(tight_val, 2), (
        f"legal/06 states the tightest legend card's clearance as {m.group(1)} px; re-measured "
        f"under print media the tightest is {tight_val:.2f} px ({at_min}).")
    named = re.findall(r"[\w‑-]+", m.group(2).replace("‑", "-"))
    unnamed = [s for s in at_min if not any(s == n or s.startswith(n) for n in named)]
    assert not unnamed, (
        f"legal/06 attributes the tightest legend card to {named}; re-measured under print media the "
        f"book(s) {unnamed} sit at the same {tight_val:.2f} px and are not named (all measured: "
        f"{sorted(v for _s, v in legend_rows)}). Name every one of them -- a card at the minimum that the "
        f"doc does not mention is a card nobody is watching, and this project has clipped that tail twice.")


def _enlarged_stats():
    """(total, lo, hi, lo_ratio, hi_ratio, pct_lo, pct_hi, over, closest_slug, closest_hole,
    closest_v, median, median_ratio) across every built enlarged edition -- or None with no browser
    or no enlarged book on disk.

    Uses `tools/check_scale.py`'s OWN `measure_rendered`/`enlarged_courses`/`ENLARGED_CARDS`, the
    exact functions its `report_enlarged()` computes these figures from -- this is the tool
    legal/06's paragraph already credits ("tools/check_scale.py ... every figure in this paragraph
    is its output"), so re-deriving through a hand-rolled parallel implementation here would not be
    a second opinion on that claim, only a differently-shaped restatement of it.
    """
    import statistics
    import check_scale as cs
    slugs = cs.enlarged_courses(set())
    if not slugs:
        return None
    rendered = cs.measure_rendered(slugs, cs.ENLARGED_BOOK, cs.ENLARGED_CARDS)
    if rendered is None:
        return None
    allv = [(c, h, v) for c in slugs for h, v in (rendered.get(c) or {}).get("per", {}).items()]
    if not allv:
        return None
    vals = sorted(v for _c, _h, v in allv)
    lo, hi = vals[0], vals[-1]
    med = statistics.median(vals)
    closest_slug, closest_hole, closest_v = min(allv, key=lambda r: r[2])
    return dict(total=len(allv), lo=lo, hi=hi, lo_ratio=round(cs.IN_PER_5YD / hi),
                hi_ratio=round(cs.IN_PER_5YD / lo),
                pct_lo=round((lo / cs.LIMIT_IN_PER_5YD - 1) * 100),
                pct_hi=round((hi / cs.LIMIT_IN_PER_5YD - 1) * 100),
                over=sum(1 for v in vals if v > cs.LIMIT_IN_PER_5YD),
                closest_slug=closest_slug, closest_hole=closest_hole, closest_v=closest_v,
                median=med, median_ratio=round(cs.IN_PER_5YD / med))


@pytest.mark.slow          # lays every enlarged edition out in a browser
def test_legal_06_states_the_measured_enlarged_edition_figures():
    """legal/06 says of the enlarged-edition paragraph: "every figure in this paragraph is its
    output" (tools/check_scale.py's). That sentence was false as written -- none of those figures
    was pinned by any test, so nothing would notice the corpus changing under it. This pins every
    figure the sentence claims: the green count, the scale range and its 1:N ratios, the
    over-the-cap percentages, the count over the cap, the closest-to-conforming hole, and the
    median and its ratio.
    """
    stats = _enlarged_stats()
    if stats is None:
        pytest.skip("no enlarged (COACH=1) edition built here, or no browser to measure it in")
    text = _legal_06_text()

    pat = (r"across all (\d+) of its greens, it prints \*\*([0-9.]+)[–-]([0-9.]+) in : 5 yd "
           r"\(1:(\d+) to 1:(\d+)\) . from ([+-]?\d+)% UNDER the cap to ([+-]?\d+)% over\*\*, "
           r"with (\d+) of the (\d+) over it \(([\w‑-]+) hole (\d+) alone lands inside\)")
    m = re.search(pat, text)
    assert m, "legal/06 no longer states the enlarged-edition range/over-cap sentence in the expected wording"
    (total, lo, hi, hi_ratio, lo_ratio, pct_lo, pct_hi, over, of, closest_slug, closest_hole) = m.groups()
    assert int(total) == int(of) == stats["total"], (
        f"legal/06 says the enlarged edition covers {total}/{of} greens; re-measured it is "
        f"{stats['total']}.")
    assert round(float(lo), 3) == round(stats["lo"], 3), (
        f"legal/06 states the enlarged edition's floor as {lo}; re-measured it is {stats['lo']:.3f}.")
    assert round(float(hi), 3) == round(stats["hi"], 3), (
        f"legal/06 states the enlarged edition's ceiling as {hi}; re-measured it is {stats['hi']:.3f}.")
    assert int(lo_ratio) == stats["lo_ratio"] and int(hi_ratio) == stats["hi_ratio"], (
        f"legal/06 states the enlarged edition's ratio range as 1:{hi_ratio} to 1:{lo_ratio}; "
        f"re-measured it is 1:{stats['hi_ratio']} to 1:{stats['lo_ratio']}.")
    assert -int(pct_lo) == stats["pct_lo"] and int(pct_hi) == stats["pct_hi"], (
        f"legal/06 states the enlarged edition's margin range as {pct_lo}% UNDER to {pct_hi}% over; "
        f"re-measured it is {stats['pct_lo']:+d}% to {stats['pct_hi']:+d}% against the cap.")
    assert int(over) == stats["over"], (
        f"legal/06 says {over} of {of} enlarged greens are over the cap; re-measured it is "
        f"{stats['over']} of {stats['total']}.")
    assert closest_slug.replace("‑", "-") == stats["closest_slug"] or stats[
        "closest_slug"].startswith(closest_slug.replace("‑", "-")), (
        f"legal/06 says {closest_slug} hole {closest_hole} alone lands inside the cap; re-measured "
        f"it is {stats['closest_slug']} hole {stats['closest_hole']}.")
    assert int(closest_hole) == stats["closest_hole"], (
        f"legal/06 says hole {closest_hole} is the enlarged edition's closest-to-conforming green; "
        f"re-measured it is hole {stats['closest_hole']} ({stats['closest_slug']}).")

    m = re.search(r"median\s*\*\*([0-9.]+) in : 5 yd \(1:(\d+)\)\*\*", text)
    assert m, "legal/06 no longer states the enlarged edition's median in the expected wording"
    assert round(float(m.group(1)), 3) == round(stats["median"], 3), (
        f"legal/06 states the enlarged edition's median as {m.group(1)}; re-measured it is "
        f"{stats['median']:.3f}.")
    assert int(m.group(2)) == stats["median_ratio"], (
        f"legal/06 states the enlarged edition's median ratio as 1:{m.group(2)}; re-measured it is "
        f"1:{stats['median_ratio']}.")
