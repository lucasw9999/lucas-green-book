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

Run:  python3 tools/check_scale.py [course-slug ...]     (default: every built course)
Exit: 0 = all conform, 1 = at least one green over the limit
"""
import glob
import json
import math
import os
import pathlib
import sys

IN_PER_5YD = 180.0              # 5 yd on the ground, in inches -- so a printed length of L inches
                                # per 5 yd is a scale of 1:(180/L). Derived, because the ratio used to
                                # be hardcoded as "(1:480)" and kept printing 480 when the limit was
                                # changed: "limit 0.75 in per 5 yd (1:480)" is self-contradictory,
                                # 0.75 in per 5 yd being 1:240.
LIMIT_IN_PER_5YD = 0.375        # 3/8 in : 5 yd  == 1:480 (USGA Clarification 4.3a/1)
TARGET_IN_PER_5YD = 0.360       # our design target, ~4% inside the cap
CARD_LIMIT_W_IN, CARD_LIMIT_H_IN = 4.25, 7.0

ROOT = pathlib.Path(__file__).resolve().parent.parent
R_LAT = 111320.0


def mlon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def _headless_shell():
    """The bundled chrome-headless-shell that matches the installed Playwright build."""
    hits = sorted(glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")))
    return hits[-1] if hits else None


def px_m_of(course, hole):
    """True metres per DEM pixel for one green (mean of the two axes)."""
    p = ROOT / "courses" / course / "dem_hd" / f"hole{hole:02d}.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text())
    xmin, ymin, xmax, ymax = m["bbox"]
    clat = m["green_center"][0]
    return ((((xmax - xmin) * mlon(clat)) / m["W"]) + (((ymax - ymin) * R_LAT) / m["H"])) / 2.0


def measure_rendered(courses):
    """{course: {hole: inches_representing_5_yards}} as the browser lays the book out.

    Returns None when no browser is installed, so the caller can say so instead of dying: this
    check MUST be done in a browser (the whole point is that CSS can override the SVG's own
    width), and a machine without one cannot answer the question either way."""
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
            f = ROOT / "courses" / c / "greenbook.html"
            if not f.exists():
                continue
            pg.goto(f.as_uri())
            cards = pg.evaluate("""() => [...document.querySelectorAll('.panel.hole')].map(pan => {
                const s = pan.querySelector('.grn svg'); if (!s) return null;
                const r = s.getBoundingClientRect();
                const vb = s.getAttribute('viewBox').split(' ').map(Number);
                // preserveAspectRatio="meet": the drawing scale is the smaller fit
                return { hole: +(pan.querySelector('.hnum') || {}).textContent,
                         k: Math.min(r.width / 96 / vb[2], r.height / 96 / vb[3]) };
            }).filter(Boolean)""")
            per = {}
            for card in cards:
                pm = px_m_of(c, card["hole"])
                if pm:
                    per[card["hole"]] = card["k"] * 4.572 / pm
            out[c] = per
        b.close()
    return out


def measure_printed(course):
    """Longest printed horizontal rule in the plausible 5-yd-bar range, in inches."""
    try:
        import fitz
    except ImportError:
        return None
    f = ROOT / "courses" / course / "greenbook.pdf"
    if not f.exists():
        return None
    mx = 0.0
    with fitz.open(f) as d:
        for page in d:
            for dr in page.get_drawings():
                for it in dr["items"]:
                    if it[0] == "l" and abs(it[1].y - it[2].y) < 0.4:
                        L = abs(it[2].x - it[1].x) / 72.0
                        if 0.20 < L < 0.60:
                            mx = max(mx, L)
    return mx or None


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
    for c in courses:
        per = rendered.get(c) or {}
        if not per:
            print(f"{c:34s} (no greens measured -- yardage-mode book?)"); continue
        worst_h = max(per, key=per.get)
        worst = per[worst_h]
        total += len(per)
        over = {h: v for h, v in per.items() if v > LIMIT_IN_PER_5YD}
        near = {h: v for h, v in per.items() if LIMIT_IN_PER_5YD >= v > TARGET_IN_PER_5YD + 0.005}
        warned += len(near)
        failures += [(c, h, v) for h, v in over.items()]
        printed = measure_printed(c)
        pr = f" | printed bar {printed:.4f} in" if printed else ""
        print(f"{c:34s} {len(per):3d} greens  worst h{worst_h:<2} {worst:.4f} in/5yd "
              f"(1:{IN_PER_5YD / worst:.0f})  margin {(1 - worst / LIMIT_IN_PER_5YD) * 100:5.1f}%  "
              f"{'FAIL' if over else 'PASS'}{pr}")

    print(f"\n{total} greens measured · limit {LIMIT_IN_PER_5YD} in per 5 yd "
          f"(1:{IN_PER_5YD / LIMIT_IN_PER_5YD:.0f})")
    if total == 0:
        # "0 greens measured ... PASS" used to exit 0, so a renamed directory or a course set that
        # failed to load would report Rule 4.3 conformance for an empty measurement.
        print("FAIL: measured 0 greens -- nothing was checked, so this is not a pass.")
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
