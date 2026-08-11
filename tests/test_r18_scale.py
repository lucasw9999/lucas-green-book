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
"""
import glob
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
    """(total, cluster_count, gap, median_ratio, worst, worst_slug, worst_hole, lo_ratio, hi_ratio).

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
    return dict(total=len(vals), cluster=len(cluster), gap=gap,
                median_ratio=round(180.0 / med), worst=worst, worst_slug=worst_slug,
                worst_hole=worst_hole, lo_ratio=round(180.0 / max(vals)),
                hi_ratio=round(180.0 / min(vals)))


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
