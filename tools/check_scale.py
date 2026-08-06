#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Rule 4.3 conformance gate -- measures what actually PRINTS, not what we intended.

USGA Clarification 4.3a/1 ("Limitations on Using Green-Reading Materials") sets:
  * scale limit -- a putting-green image must be 3/8 inch to 5 yards (1:480) OR SMALLER
  * size  limit -- the book must not exceed 4 1/4 x 7 inches
Nothing in Rule 4.3 limits contour interval, arrow density or slope numbers.

Why this exists: render_green.py computes a legal size in inches, but a stylesheet rule
once overrode it (an SVG width= presentation attribute has zero CSS specificity), which
silently enlarged 15 of 198 greens past the cap while three documents asserted the cap
held. Intent is not evidence -- so measure the rendered/printed artifact and fail loudly.

Measures each green two independent ways:
  1. browser layout  -- the 'meet'-fitted drawing box, with the hole number read off the
     card (deck order is imposition order, NOT hole order -- do not zip by index)
  2. printed PDF     -- the length of the printed "5 yd" scale bar (72pt = 1in)

Covers BOTH editions, and gates only the one that claims to conform:
  * the POCKET book (greenbook.html/.pdf) carries a "DESIGNED TO CONFORM - RULE 4.3" badge, so
    every green in it is a gating measurement.
  * the ENLARGED edition (greenbook_coach.html, COACH=1) is deliberately past the cap so the
    greens read at arm's length, and says so on its own guide card. It is measured and REPORTED,
    and can never change the exit code.

Why the enlarged edition is measured here at all, given that it cannot fail:
legal/06_RULE_4.3_CONFORMANCE.md states its scale range as a fact ("0.368-0.599 in : 5 yd"), and
until this was added nothing in the project computed that. A number in a legal exhibit that no
tool produces is the same defect this file exists to prevent, and it had already started to rot:
tests/test_phase1_regressions.py said the range was "measured off its own PDFs", but that edition
renders with tournament=False, which emits no "5 yd" bar at all -- there is nothing in those PDFs
for measure_printed to find, so only the browser layout can answer. One hand measurement, two
documents, and they disagreed.

Run:  python3 tools/check_scale.py [course-slug ...]     (default: every built course)
Exit: 0 = every POCKET green conforms, 1 = one is over the limit or went unmeasured,
      2 = no browser here, so nothing could be measured either way. The enlarged edition is
      reported on every one of those paths and gates none of them.
"""
import json
import os
import pathlib
import re
import statistics
import sys

IN_PER_5YD = 180.0              # 5 yd on the ground, in inches -- so a printed length of L inches
                                # per 5 yd is a scale of 1:(180/L). Derived, because the ratio used to
                                # be hardcoded as "(1:480)" and kept printing 480 when the limit was
                                # changed: "limit 0.75 in per 5 yd (1:480)" is self-contradictory,
                                # 0.75 in per 5 yd being 1:240.
LIMIT_IN_PER_5YD = 0.375        # 3/8 in : 5 yd  == 1:480 (USGA Clarification 4.3a/1)
TARGET_IN_PER_5YD = 0.360       # our design target, ~4% inside the cap
CARD_LIMIT_W_IN, CARD_LIMIT_H_IN = 4.25, 7.0

POCKET_BOOK = "greenbook.html"           # claims conformance in print          -> GATED
ENLARGED_BOOK = "greenbook_coach.html"   # COACH=1, deliberately over the cap   -> reported only

from export_pdf import _headless_shell   # one discovery of the bundled
                                         # chrome-headless-shell, not two

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# THE GATE AND THE THING IT GATES MUST BE ON THE SAME EARTH. This tool divides the drawn size by a
# ground scale to get "inches per 5 yd", and render_green.py multiplies by that same scale to SIZE the
# drawing in the first place (`legal_kf = 0.36 * px_m / 4.572`). It used to re-derive the scale from its
# own copy of `R_LAT = 111320.0`, so the day the renderer's earth model moved the gate would have gone
# on measuring the renderer against a metric that no longer sized it -- Rule 4.3 conformance certified
# against the wrong ruler. Import it; never re-declare it. (Measured when the model was migrated to the
# true per-axis WGS84 scales: the ground scale below moves by a median -0.083%, which shifts the worst
# gated reading from 0.3601 to 0.3600 in : 5 yd against a 0.375 in cap -- a 4.0% margin.)
from geo import mlat, mlon

def px_m_of(course, hole):
    """True metres per DEM pixel for one green (mean of the two axes), or None with the reason.

    Returns a (value, reason) pair rather than a bare value because the caller has to be able to SAY
    that a green went unmeasured. It used to return None on a missing dem_hd/holeNN.json and the
    caller dropped it with `if pm:` -- no message, and no increment to the green count either, so the
    gate reported "PASS" over a smaller book than the one on disk. Reproduced by moving one meta
    aside: merion printed "17 greens ... PASS" and exited 0 while its PDF still carried 18 scale bars.
    """
    p = ROOT / "courses" / course / "dem_hd" / f"hole{hole:02d}.json"
    if not p.exists():
        return None, f"no dem_hd/hole{hole:02d}.json, so its ground scale is unknown"
    m = json.loads(p.read_text())
    xmin, ymin, xmax, ymax = m["bbox"]
    clat = m["green_center"][0]
    pm = ((((xmax - xmin) * mlon(clat)) / m["W"]) + (((ymax - ymin) * mlat(clat)) / m["H"])) / 2.0
    if not pm:
        return None, f"dem_hd/hole{hole:02d}.json gives a zero ground scale"
    return pm, ""


def dem_hd_holes(course):
    """Hole numbers with a built green surface on disk -- what the book is expected to draw.

    The gate's own green count has to be checked against something outside the browser, or a card
    the selector fails to find is indistinguishable from a card that is not there.
    """
    out = set()
    for p in (ROOT / "courses" / course / "dem_hd").glob("hole*.json"):
        m = re.match(r"hole(\d+)\.json$", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


# ONE copy of the drawing-scale expression, called with the selectors each edition needs. It is
# written once on purpose: `k` is the load-bearing line of the whole gate, and a second copy of it for
# the enlarged deck is a second place for it to be wrong.
CARDS_JS = """([sel, caption]) => [...document.querySelectorAll('.panel.hole')].map(pan => {
    // The ENLARGED deck puts TWO cards on the same hole number -- the course map on the front of the
    // leaf, the green on its back -- and both drawings live in .cmap under the same .hnum. So its
    // green card is identified by its OWN printed caption, for the same reason the hole number is
    // read off the card rather than counted: deck order is imposition order, so indexing into it is
    // guessing. Take the map card by mistake and the "green scale" reported is a hole map's.
    // The pocket deck has one card per hole with its green in .grn, so it passes no caption.
    const lab = (pan.querySelector('.minilab') || {}).textContent || '';
    if (caption && lab.indexOf(caption) < 0) return null;
    const s = pan.querySelector(sel); if (!s) return null;
    const r = s.getBoundingClientRect();
    const vb = s.getAttribute('viewBox').split(' ').map(Number);
    // preserveAspectRatio="meet": the drawing scale is the SMALLER fit. Width alone is wrong --
    // height is the limiting dimension on most greens.
    return { hole: +(pan.querySelector('.hnum') || {}).textContent,
             k: Math.min(r.width / 96 / vb[2], r.height / 96 / vb[3]) };
}).filter(Boolean)"""
POCKET_CARDS = [".grn svg", None]                    # one card per hole
ENLARGED_CARDS = [".cmap svg", "approach at bottom"] # two cards per hole; the green says this


def measure_rendered(courses, book=POCKET_BOOK, cards_sel=POCKET_CARDS):
    """{course: {"per": {hole: inches_per_5yd}, "skipped": [(hole, why)], "cards": n}}, or None.

    Returns None when no browser is installed, so the caller can say so instead of dying: this
    check MUST be done in a browser (the whole point is that CSS can override the SVG's own
    width), and a machine without one cannot answer the question either way.

    `skipped` and `cards` exist so the caller can compare what was MEASURED against what was FOUND
    and against the surfaces on disk. A green that could not be measured used to disappear here.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    exe = _headless_shell()
    out = {}
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as e:
            print(f"no browser available ({type(e).__name__}); cannot measure rendered scale")
            return None
        pg = b.new_page()
        # Measure under PRINT media. Without this the gate measured the SCREEN layout while README
        # claimed "under print media" -- and a print-only rule (a @media print block that enlarges a
        # green) would have passed a gate that never looked at print. The book's own stylesheet has
        # @page and print rules, so this is the layout that actually reaches paper.
        pg.emulate_media(media="print")
        for c in courses:
            f = ROOT / "courses" / c / book
            if not f.exists():
                continue
            pg.goto(f.as_uri())
            cards = pg.evaluate(CARDS_JS, cards_sel)
            per, skipped = {}, []
            for card in cards:
                pm, why = px_m_of(c, card["hole"])
                if pm:
                    per[card["hole"]] = card["k"] * 4.572 / pm
                else:
                    skipped.append((card["hole"], why))
            out[c] = {"per": per, "skipped": skipped, "cards": len(cards)}
        b.close()
    return out


BAR_NEAR_LABEL_PT = 14.0        # a bar sits directly under its "5 yd" caption
BAR_SAME_COLUMN_PT = 40.0       # ...and within the same card column


def measure_printed(course):
    """(max, [all], reason) printed 5-yd bar lengths in inches; reason is "" when bars were measured.

    Each bar is found by its OWN caption. This used to take the longest horizontal rule anywhere in the
    book inside a 0.20-0.60 in window, and that is not the same thing: on callippe it returned 0.3554 in
    from a rule sitting nowhere near a "5 yd" label, while every real bar in that book measures
    0.1902-0.32 in. It agreed with the browser-layout figure on the other ten courses by coincidence --
    their longest stray rule happens to land near their largest bar.

    That mattered because this is the INDEPENDENT half of the gate. The whole point of the tool is that
    intent is not evidence, so the printed artifact gets measured too; a second opinion that can latch
    onto an unrelated rule is not a second opinion. It was informational only, so nothing was ever
    mis-gated -- but the number it printed was not the bar.

    It now returns a REASON instead of a bare None. Every way of failing -- no PyMuPDF, no PDF, no bar
    found -- came back as None and the caller said nothing at all, so the artifact half of the gate
    could vanish without a word. Reproduced by moving one greenbook.pdf aside: the line for that course
    simply lost its "| printed bars ..." half and the tool still exited 0.
    """
    try:
        import fitz
    except ImportError:
        return None, [], "PyMuPDF (fitz) is not installed"
    f = ROOT / "courses" / course / "greenbook.pdf"
    if not f.exists():
        return None, [], "no greenbook.pdf on disk -- run tools/export_pdf.py"
    bars = []
    with fitz.open(f) as d:
        for page in d:
            labels = [sp["bbox"] for blk in page.get_text("dict")["blocks"]
                      for ln in blk.get("lines", []) for sp in ln.get("spans", [])
                      if sp["text"].strip() == "5 yd"]
            if not labels:
                continue
            rules = []
            for dr in page.get_drawings():
                for it in dr["items"]:
                    if it[0] == "l" and abs(it[1].y - it[2].y) < 0.4:
                        rules.append((abs(it[2].x - it[1].x) / 72.0,
                                      (it[1].x + it[2].x) / 2.0, it[1].y))
            for bb in labels:
                cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
                near = [r for r in rules
                        if abs(r[2] - cy) < BAR_NEAR_LABEL_PT and abs(r[1] - cx) < BAR_SAME_COLUMN_PT]
                if near:
                    bars.append(max(near, key=lambda r: r[0])[0])
    if not bars:
        return None, [], 'no "5 yd" caption with a rule beside it in the PDF'
    return max(bars), bars, ""


def enlarged_courses(only):
    """Slugs with an enlarged edition built. Its own glob, not main()'s course list.

    main() discovers courses by `*/greenbook.html`, and reusing that list would report nothing for a
    tree where only the enlarged book has been built -- exactly the tree that most needs the number,
    since it is the enlarged book being worked on. Widening main()'s glob instead would be worse: a
    coach-only course would then be a POCKET book with 0 greens measured, which the gate correctly
    treats as a failure.
    """
    slugs = sorted(p.parent.name for p in (ROOT / "courses").glob(f"*/{ENLARGED_BOOK}")
                   if not p.parent.name.startswith("_"))
    return [s for s in slugs if not only or s in only]


def report_enlarged(only):
    r"""Print the enlarged edition's measured green scale. Returns nothing and gates nothing.

    That edition breaks the scale cap ON PURPOSE, so a failure here would be a gate against a design
    decision -- the honesty requirement on it is that it says so on its guide card and does not wear
    the conformance badge, and both of those are asserted in the test suite, not here.

    It reports in "in : 5 yd" rather than the "in/5yd" the gated lines use, and that is deliberate,
    not sloppiness: tests/test_phase1_regressions.py's test_every_green_conforms_to_rule_4_3_scale_cap
    scrapes `([0-9.]+) in/5yd` out of this tool's stdout and asserts every number it finds is inside
    the cap. Spelling the enlarged figures the same way would feed 53 deliberately over-cap numbers
    into that assertion and turn the pocket book's gate red. Do not "tidy" the two spellings into one
    without reading that test.

    Nor does it print the phrase "greens measured" -- the same suite reads the pocket book's green
    count out of the first `(\d+) greens measured` in this output.
    """
    slugs = enlarged_courses(only)
    if not slugs:
        return
    rendered = measure_rendered(slugs, ENLARGED_BOOK, ENLARGED_CARDS)
    if rendered is None:
        # Unreachable from main() (it has already measured the pocket books in this browser), but a
        # silent return would be the one failure mode this file was written against.
        print("\nenlarged edition: no browser, so its scale is UNMEASURED here")
        return
    print(f"\nenlarged edition ({ENLARGED_BOOK}) -- MEASURED, NOT GATED: it is a practice aid "
          f"that prints past the cap by design")
    allv = []
    for c in slugs:
        info = rendered.get(c) or {}
        per = info.get("per") or {}
        skipped = info.get("skipped") or []
        ncards = info.get("cards", 0)
        for h, whyskip in skipped:
            print(f"{c:34s} !! hole {h} not measured: {whyskip}")
        missing = sorted(dem_hd_holes(c) - set(per) - {h for h, _w in skipped})
        if missing:
            print(f"{c:34s} !! {len(missing)} built green surface(s) {missing} that no green card "
                  f"corresponds to ({ncards} green card(s) found in the page)")
        if not per:
            print(f"{c:34s} !! 0 greens measured, so the figure quoted in legal/06 for this book "
                  f"currently rests on nothing")
            continue
        lo, hi = min(per.values()), max(per.values())
        over = [v for v in per.values() if v > LIMIT_IN_PER_5YD]
        print(f"{c:34s} {len(per):3d} greens  {lo:.4f}-{hi:.4f} in : 5 yd "
              f"(1:{IN_PER_5YD / hi:.0f} to 1:{IN_PER_5YD / lo:.0f})  "
              f"{len(over)} of {len(per)} over the cap")
        allv += [(c, h, v) for h, v in per.items()]
    if not allv:
        return
    vals = sorted(v for _c, _h, v in allv)
    over = [r for r in allv if r[2] > LIMIT_IN_PER_5YD]
    cc, chole, cv = min(allv, key=lambda r: r[2])
    print(f"{len(allv)} enlarged green(s) across {len(slugs)} book(s): {vals[0]:.4f}-{vals[-1]:.4f} "
          f"in : 5 yd (1:{IN_PER_5YD / vals[-1]:.0f} to 1:{IN_PER_5YD / vals[0]:.0f}), median "
          f"{statistics.median(vals):.4f} -- {(vals[0] / LIMIT_IN_PER_5YD - 1) * 100:+.0f}% to "
          f"{(vals[-1] / LIMIT_IN_PER_5YD - 1) * 100:+.0f}% against the {LIMIT_IN_PER_5YD} in cap, "
          f"{len(over)} of {len(allv)} over it")
    side = ("inside the cap" if cv <= LIMIT_IN_PER_5YD else "over it")
    off = abs(cv / LIMIT_IN_PER_5YD - 1) * 100
    print(f"   closest to conforming: {cc} hole {chole} at {cv:.4f} in : 5 yd "
          f"(1:{IN_PER_5YD / cv:.0f}, {off:.1f}% {side})")
    print("   quote these figures in legal/06_RULE_4.3_CONFORMANCE.md; do not hand-measure them")
    if not over:
        # The mirror-image defect, and the only way this section can report something WRONG: an
        # "enlarged" edition that no longer prints larger than the tournament scale. It happened --
        # build_coach once asked for the size-capped render and printed at ratio 1.00 on all 18
        # holes while its own card claimed otherwise. Said here too because this is the tool that
        # now owns the number.
        print("   !! not one enlarged green exceeds the cap, yet the edition's guide card says it "
              "prints larger than tournament scale -- one of the two is wrong")


def main():
    # Underscore-prefixed dirs are scratch (staging, review sandboxes, the cold-build test). Every
    # other course-scanning tool filters them -- export_pdf.py, gen_disclaimers.py, gen_provenance.py
    # and the test suite -- but this one did not, so a leftover sandbox inflated the green count and
    # turned the Rule 4.3 gate RED on a clean checkout. The review workflow mandates "_" slugs, so
    # this failure was guaranteed by our own process.
    courses = sys.argv[1:] or sorted(
        p.parent.name for p in (ROOT / "courses").glob("*/greenbook.html")
        if not p.parent.name.startswith("_"))
    if not courses:
        print("no built books found"); return 0

    # Bind COURSE to a course that EXISTS here before importing config. The card size is
    # engine-wide, but config still refuses to import without a valid course, so this tool used to
    # die on whatever COURSE happened to be in the environment -- inside the test suite that is
    # whichever course ran last, which made the Rule 4.3 gate fail in any tree that did not happen
    # to have that course built.
    os.environ.setdefault("COURSE", courses[0])
    if not os.path.exists(ROOT / "courses" / os.environ["COURSE"] / "course.json"):
        os.environ["COURSE"] = courses[0]
    import config  # card size is engine-wide
    # The card size is PER COURSE (config.py:49-51 reads course.json's "card"), so reading it once
    # from whichever course imported first and calling it engine-wide would let an over-size book
    # through: the gate would report the default 3.5 x 5.0 while a course printing 5 x 8 passed.
    # Check every course's own card.
    oversize = []
    for c in courses:
        cd = {}
        cjp = ROOT / "courses" / c / "course.json"
        if cjp.exists():
            cd = (json.loads(cjp.read_text()).get("card") or {})
        # fall back to the ENGINE default, never to config's currently-bound course
        cw = float(cd.get("w", config.CARD_DEFAULT_W_IN))
        chh = float(cd.get("h", config.CARD_DEFAULT_H_IN))
        if cw > CARD_LIMIT_W_IN or chh > CARD_LIMIT_H_IN:
            oversize.append((c, cw, chh))
    card_ok = not oversize
    print(f"card size {config.CARD_W_IN} x {config.CARD_H_IN} in "
          f"vs limit {CARD_LIMIT_W_IN} x {CARD_LIMIT_H_IN} in -> "
          f"{'OK' if card_ok else 'OVER SIZE LIMIT'}\n")

    rendered = measure_rendered(courses)
    if rendered is None:
        # Distinct exit code: "could not check" is neither PASS nor FAIL. The pytest gate treats a
        # non-zero rc as a failure, so it is told apart by this message.
        print("SKIP: no browser to measure the rendered layout in; Rule 4.3 is UNVERIFIED here.")
        return 2
    failures, warned, total = [], 0, 0
    # A green this tool cannot measure is not a green that conforms. Every one of these paths ended in
    # silence and rc 0:
    #   * px_m_of returned None for a missing dem_hd/holeNN.json and the caller dropped it with
    #     `if pm:` -- no message, and `total` never counted it. Reproduced: merion printed
    #     "17 greens ... PASS" with hole 7's meta moved aside, while its PDF still held 18 bars.
    #   * an empty `per` printed "(no greens measured -- yardage-mode book?)" and continued, which is
    #     indistinguishable from a selector that stopped matching .panel.hole in every book.
    # Both are now compared against evidence outside the browser: the cards the page yielded, and the
    # green surfaces on disk. The pocket edition CLAIMS Rule 4.3 conformance in print, so an
    # unmeasured green has to read as unverified, not as a pass.
    unmeasured = []
    import distribution          # one spelling of build_mode for the whole engine
    for c in courses:
        info = rendered.get(c) or {}
        per = info.get("per") or {}
        skipped = info.get("skipped") or []
        ncards = info.get("cards", 0)
        metas = dem_hd_holes(c)
        cj = ROOT / "courses" / c / "course.json"
        cjson = json.loads(cj.read_text()) if cj.exists() else None
        yardage = distribution.is_yardage(cjson)
        for h, whyskip in skipped:
            unmeasured.append((c, f"hole {h}: {whyskip}"))
        missing_cards = sorted(metas - set(per) - {h for h, _w in skipped})
        if missing_cards:
            # A built green surface with no card measuring it. Either the book does not draw that hole
            # or the .panel.hole/.grn svg selector missed it -- and a selector that has stopped
            # matching is exactly the failure the "(no greens measured)" line could not distinguish.
            unmeasured.append((c, f"{len(missing_cards)} built green surface(s) {missing_cards} that "
                                  f"no measured card corresponds to ({ncards} card(s) found in the "
                                  f"page)"))
        if not per:
            if yardage:
                # The one legitimate case: a yardage-mode book prints blank greens on purpose, so
                # there is no green image for Rule 4.3 to cap. poppy-ridge is the live example.
                print(f"{c:34s} (no greens measured -- build_mode=yardage, blank greens by design)")
            else:
                unmeasured.append((c, f"0 greens measured but {len(metas)} green surface(s) on disk "
                                      f"and {ncards} card(s) in the page, and build_mode is not "
                                      f"'yardage'"))
                print(f"{c:34s} !! 0 greens measured -- see the failure list below")
            continue
        worst_h = max(per, key=per.get)
        worst = per[worst_h]
        total += len(per)
        over = {h: v for h, v in per.items() if v > LIMIT_IN_PER_5YD}
        near = {h: v for h, v in per.items() if LIMIT_IN_PER_5YD >= v > TARGET_IN_PER_5YD + 0.005}
        warned += len(near)
        failures += [(c, h, v) for h, v in over.items()]
        printed, bars, whybars = measure_printed(c)
        if printed is None:
            # The independent half of the gate. Informational, but it must never go missing quietly:
            # the tool exists because intent is not evidence, and a second opinion that is absent
            # without saying so is not a second opinion either.
            pr = f" | printed bars NOT MEASURED: {whybars}"
        else:
            pr = f" | printed bars {min(bars):.4f}-{printed:.4f} in ({len(bars)})"
            # the legal claim is about the ARTIFACT, so every bar must clear the cap on its own
            over_bar = [b for b in bars if b > LIMIT_IN_PER_5YD]
            if over_bar:
                failures += [(c, "bar", max(over_bar))]
                pr += f"  !! {len(over_bar)} printed bar(s) OVER the limit"
            elif printed > worst + 0.01:
                pr += (f"  !! a printed bar exceeds the measured layout scale ({worst:.4f}) -- the two "
                       f"should agree")
            elif len(bars) != len(per):
                # The two halves must be counting the same book. This is how a silently dropped green
                # showed itself once the layout half stopped hiding it.
                pr += f"  !! {len(bars)} printed bar(s) against {len(per)} measured green(s)"
        print(f"{c:34s} {len(per):3d} greens  worst h{worst_h:<2} {worst:.4f} in/5yd "
              f"(1:{IN_PER_5YD / worst:.0f})  margin {(1 - worst / LIMIT_IN_PER_5YD) * 100:5.1f}%  "
              f"{'FAIL' if over else 'PASS'}{pr}")

    print(f"\n{total} greens measured · limit {LIMIT_IN_PER_5YD} in per 5 yd "
          f"(1:{IN_PER_5YD / LIMIT_IN_PER_5YD:.0f})")
    # Reported BEFORE the verdict returns, so the enlarged figures are printed on a failing run too.
    # Placed after the pocket book's own count so that count stays the FIRST "greens measured" in the
    # output, which is where the suite reads it from.
    report_enlarged(set(sys.argv[1:]))
    if total == 0:
        # "0 greens measured ... PASS" used to exit 0, so a renamed directory or a course set that
        # failed to load would report Rule 4.3 conformance for an empty measurement.
        print("FAIL: measured 0 greens -- nothing was checked, so this is not a pass.")
        return 1
    if unmeasured:
        print(f"FAIL: {len(unmeasured)} green(s)/course(s) were NOT measured, so their conformance is "
              f"unverified rather than proven:")
        for c, whyskip in unmeasured:
            print(f"   {c}: {whyskip}")
        return 1
    if not card_ok:
        # Rule 4.3 caps the book SIZE as well as the scale; this was computed, printed and then
        # ignored, so a 5 x 8 in card exited 0 while the docstring advertised both limits.
        print(f"FAIL: {len(oversize)} course(s) print a card over the Rule 4.3 size limit of "
              f"{CARD_LIMIT_W_IN} x {CARD_LIMIT_H_IN} in:")
        for c, cw, chh in oversize:
            print(f"   {c}: {cw} x {chh} in")
        return 1
    if failures:
        print(f"FAIL: {len(failures)} green(s) exceed the Rule 4.3 scale limit:")
        for c, h, v in sorted(failures, key=lambda r: -r[2]):
            print(f"   {c} hole {h}: {v:.4f} in/5yd (1:{IN_PER_5YD / v:.0f})")
        return 1
    print(f"PASS: every green conforms (design target {TARGET_IN_PER_5YD} in; "
          f"{warned} above target but legal)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
