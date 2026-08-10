#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The book is printed IN COLOUR, on paper, and carried in a pocket. Nothing in this suite had ever
graded it as a printed artifact, and four things were wrong at once.

Every figure below was measured on this machine, in the same chrome-headless-shell build
tools/export_pdf.py exports the PDFs with, and every one of them is re-derived by the tests rather
than quoted at them.

  1. THE POCKET BOOK NEVER SAID "PRINT IN COLOUR", AND SAID THE OPPOSITE. render_hole fills a
     fairway #cfe8b2 and a bunker #efe3b8. Through Chrome's own `filter: grayscale(1)` -- the
     luminance the printer's mono conversion approximates -- those become greys 223 and 226: a
     **3.00 level** separation out of 255, **1.18%**, with only a 0.8-unit #c9b477 outline (grey 180)
     between them. trump-national-los-angeles names **149 bunkers** across its 18 footers and prints a
     `carry N` per hole defined against sand a mono reader cannot see.
     The warning existed in the ENLARGED edition only (`coach_about_card`). The pocket guide card
     instead reassured the reader: "steeper is always darker, so it reads in black and white too" --
     true of the green's heat ramp, false of the hole map beside it, and read by someone about to
     choose a printer. README asserted "Both books say so on the guide card"; one did.
     THE ROW COST NOTHING, and that is why the warning replaced the reassurance instead of being added
     under it. Measured by splicing each candidate into all 12 shipped guide cards: a NEW legend row
     overflows monarch-bay's card by 12.36 px and philadelphia's by 1.81 px -- monarch-bay ships with
     **1.19 px** of clearance -- while the in-place replacement leaves all 12 at their existing slack to
     the hundredth of a pixel.

  2. THE DEPTH LADDER WAS THE FAINTEST DATA ON THE CARD. The 5-yd rung labels -- yards from the front
     edge, which is how a player judges depth -- were `#8a8a8a` inside a group at `opacity="0.7"`.
     Composited that is grey **172-173**: **2.24:1** against white paper, where WCAG asks 4.5:1, at a
     printed size of **4.09 pt** (callippe hole 9) to 8.90 pt. And unlike the slope numbers they
     carried NO white halo. Measured over all 1151 of them, against the pre-fix markup reconstructed
     into the same rendered SVGs: **1104 of 1104 under 4.5:1 on paper**, **1081 under 4.5:1 against the
     collar they actually sit on** (worst **1.15:1**, micke-grove hole 5's "20", grey 172 on amber
     214/179/128), and **243** with a quarter or more of that collar filled by the green's own #20402a
     outline or a #15271b arrow. The pre-fix population is 1104 and not 1151 because **47** labels were
     too faint for a luma-190 threshold to find their strokes at all.
     DARKENING ALONE WOULD HAVE MADE THE WORST CASE WORSE, which is why the halo is not optional: over
     the #20402a outline the old label composites to grey 112 and reads 2.37:1 against it, while an
     opaque #6b6b6b digit on that same outline reads **2.16:1**. Dropping the opacity without a halo
     also stops at 3.45:1 on paper, still under 4.5.

  3. THE COVER ADDRESS HAD NO FITTING LOGIC. A fixed 9-unit font inside a 221.3 pt gold frame. The
     13th course's address is **2.965 in** wide with **3.93 pt** of clearance a side; next tightest is
     Castlewood at 10.46 pt, median 24.85 pt. The title has had a width-aware estimator all along; the
     address did not, so one longer address crosses the frame with nothing to notice. Fixed to 8.6
     units on that one cover -- **9.84 pt** clear -- and the other twelve render byte-identical.

  4. A COURSE NAME OVER 30 CHARACTERS WITH NO EM-DASH GREEDY-FILLS, and the fill splits "Golf Club".
     Exactly one course reaches that branch, so a smarter `_title_lines` would rewrap ZERO of the
     other twelve and could not be exercised. The durable guard is the test below.

WHAT IS DELIBERATELY NOT HERE. Nothing in this module re-asserts a hex string out of the engine's
source. Defects 1 and 2 are graded off pixels sampled from a rendered card, and 3 off glyph boxes
measured in a browser, because "the fill is still #efe3b8" is true of both the broken book and the
fixed one.
"""
import glob
import math
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conftest import corpus_slugs                                        # noqa: E402

# Courses with the OSM geometry a hole map and a green card need. poppy-ridge has none: it is built
# from the scorecard alone, its greens are blank and its cards carry no hole map at all -- which is
# also why it is the one book that legitimately needs no colour warning.
GEOM = corpus_slugs()

# ...and every course with a scorecard, which is the population defects 3 and 4 live in: they read
# course.json, and the yardage book has a cover and a name like any other. distribution.is_corpus_slug
# is this repo's one spelling of "a course, or somebody's scratch?" -- see its docstring.
def book_slugs():
    import distribution
    return [s for s in sorted(os.path.basename(os.path.dirname(p))
                              for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
            if distribution.is_corpus_slug(s)]


BOOKS = book_slugs()

needs_geom = pytest.mark.skipif(not GEOM, reason="per-course geometry is gitignored; nothing to render")
needs_books = pytest.mark.skipif(not BOOKS, reason="per-course data is gitignored; nothing to measure")

# WCAG 2.x asks 4.5:1 for text this size. The ladder prints from 4.09 pt, which is SMALLER than
# anything the "large text" 3:1 relaxation covers, so 4.5 is the bar that applies.
WCAG_MIN = 4.5

# render_hole's own two fills, named here only so the test can FIND them in a rendered card and read
# the greyscale off the pixels. The assertion is on the pixels, never on the string.
FAIRWAY_FILL, BUNKER_FILL, BUNKER_EDGE = "#cfe8b2", "#efe3b8", "#c9b477"

RUNG_FONT_SIZE = "3.4"       # render_green's 5-yd ladder labels; the slope numbers are 4.6


def _engine(slug, deck=False):
    """config / render_hole / render_green / generate bound to ONE course.

    `generate` is popped as well, which conftest's `_bind_a_course` does not do: it holds
    `from config import ... NAME as COURSE, ADDRESS as ADDR` at module level, so a stale copy prints
    the previous course's cover.

    `deck=True` runs build_deck() first, and for the guide card that is not optional. THREE of the
    card's legend rows are conditional on what the greens turned out to be -- `_faint_note`,
    `_no_fall_note` and `_flown_line`'s coarse-lattice row all read the GREENS dict build_deck fills --
    so `guide_panel()` called on a cold import silently emits a SHORTER card than the book ships.
    Measured: philadelphia's cold card leaves 25.28 px of clearance and its real one 11.73;
    monarch-bay's cold card 49.38 and its real one 1.19. A card-space test taken cold would have
    measured 48 px of room that does not exist. With the deck built, the panel this returns is
    byte-identical to the one in the shipped book -- checked on monarch-bay, philadelphia and
    trump-national-los-angeles.

    It renders in memory and writes nothing: build_deck() only fills GREENS/LAYOUTS. main() is what
    writes a book, and nothing here calls it.
    """
    for m in ("config", "render_hole", "render_green", "generate", "distribution"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config
    import generate
    import render_green
    import render_hole
    if deck:
        generate.build_deck()
    return config, generate, render_hole, render_green


def _flat(html):
    return re.sub(r"\s+", " ", html)


# ---------------------------------------------------------------------------
# colour arithmetic, written out rather than imported: the point of these tests is to be a second
# opinion on what the page does, so they own their own definition of "how dark is that".
# ---------------------------------------------------------------------------
def _rel_lum(rgb):
    """WCAG relative luminance of an 8-bit sRGB triple."""
    out = 0.0
    for c, k in zip(rgb, (0.2126, 0.7152, 0.0722)):
        s = c / 255.0
        out += k * (s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    return out


def _contrast(a, b):
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _luma601(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _hex(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------------------
# browser
# ---------------------------------------------------------------------------
PAGE_FONT = '"Helvetica Neue", Arial, sans-serif'    # the book's own stack; SVG text inherits it


def _shell():
    import export_pdf
    return export_pdf._headless_shell()


class _Browser:
    """One chrome-headless-shell page, or a clean skip. Renders through set_content only.

    Nothing is written to disk at all: every asset in a book is a base64 data URI, so a page needs no
    file to resolve against, and courses/ is the only copy of the corpus.
    """

    def __init__(self, scale=1.0):
        self.scale = scale

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            pytest.skip("playwright not installed")
        self._pw = sync_playwright().start()
        exe = _shell()
        try:
            self._b = (self._pw.chromium.launch(executable_path=exe) if exe
                       else self._pw.chromium.launch())
        except Exception:
            self._pw.stop()
            pytest.skip("no browser available")
        self.page = self._b.new_page(device_scale_factor=self.scale)
        self.page.emulate_media(media="print")
        return self.page

    def __exit__(self, *a):
        try:
            self._b.close()
        finally:
            self._pw.stop()


def _shot(page, sel="#w"):
    """One element, screenshotted and decoded to an (H, W, 3) uint8 array.

    Decoded with PyMuPDF rather than Pillow. Pillow is the obvious tool and is NOT a declared
    dependency of this project, and test_every_third_party_import_is_declared refuses an undeclared
    import with no exemption for guarding it -- correctly, since a test that silently skips is a test
    that measures nothing. PyMuPDF is already declared (OPTIONAL, for its licence's sake), is already
    how this suite reads pixels and glyph runs out of the exported PDFs, and opens a PNG buffer
    directly. Its import carries the guard that an OPTIONAL package's imports must all carry.
    """
    import numpy as np
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf not installed")
    pm = fitz.Pixmap(page.locator(sel).screenshot())
    a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
    return a[..., :3]


def _wrap(inner, extra_css="", box=""):
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            "*{box-sizing:border-box}"
            f"html,body{{margin:0;padding:0;background:#fff;font-family:{PAGE_FONT}}}"
            f"#w{{display:inline-block;background:#fff;{box}}}"
            f"{extra_css}</style></head><body><div id='w'>{inner}</div></body></html>")


# ===========================================================================
# 1. print in colour
# ===========================================================================
_GREY_TOL = 12.0        # levels of 255. Measured separation is 3.00; a fix that made the two fills
                        # tell apart in mono would clear this by a wide margin and the premise below
                        # would (correctly) fail, sending the next reader back to this docstring.


@pytest.mark.slow          # renders one hole card per course, twice, in a browser
@needs_geom
def test_a_mono_print_cannot_tell_a_bunker_from_the_fairway_it_lies_in():
    """THE PREMISE for the warning on the guide card, measured on real cards rather than assumed.

    Chrome's `filter: grayscale(1)` is the CSS luminance matrix -- the same quantity a mono printer's
    conversion approximates -- so applying it to a rendered hole map and sampling the two fills is a
    direct measurement of what a black-and-white print does to the sand.

    Measured on the fullest hole of each of the 12 geometry courses: fairway grey 223, bunker grey
    226. THREE levels of 255. The only thing left between them is the bunker's own 0.8-unit #c9b477
    edge at grey 180, which at this scale is a hairline.

    Bunker COUNT is taken from render_hole's own `info["bunkers"]` -- the number the card's footer
    prints -- so the scale of what disappears is the book's own figure and not this test's.

    Both fills are located by COLOUR in the un-filtered screenshot, not by parsing the SVG, so this
    measures the ink that actually reached the page: a fill overpainted by a tree, the centre line or
    a water body is simply not in the mask.
    """
    import numpy as np
    fair, bunk, edge = _hex(FAIRWAY_FILL), _hex(BUNKER_FILL), _hex(BUNKER_EDGE)

    def near(a, rgb, tol=4):
        return np.all(np.abs(a.astype(int) - np.array(rgb)) <= tol, axis=-1)

    rows, seen, total_bunkers = [], [], 0
    with _Browser(scale=6.25) as page:                       # 600 dpi
        for slug in GEOM:
            cfg, _gen, rh, _rg = _engine(slug)
            best = None
            for h in cfg.HOLE_NUMS:
                svg, info = rh.render_hole(h, cfg.HOLES)
                total_bunkers += info["bunkers"]
                if best is None or info["bunkers"] > best[1]["bunkers"]:
                    best = (h, info, svg)
            assert best, f"{slug}: no hole rendered"
            h, info, svg = best
            if not info["bunkers"]:
                continue                                     # nothing to lose in mono on this course
            shots = {}
            for grey in (False, True):
                css = "#w{filter:grayscale(1)}" if grey else ""
                page.set_content(_wrap(svg, extra_css=css,
                                       box="width:1.29in;height:2.5in") +
                                 "<style>#w svg{width:100%;height:100%}</style>")
                shots[grey] = _shot(page)
            C, G = shots[False], shots[True]
            mf, mb, me = near(C, fair), near(C, bunk), near(C, edge)
            if not mf.any() or not mb.any():
                continue                                     # no sand inside a fairway on this card
            gf = float(np.median(G[..., 0][mf]))
            gb = float(np.median(G[..., 0][mb]))
            ge = float(np.median(G[..., 0][me])) if me.any() else None
            rows.append((slug, h, info["bunkers"], gf, gb, abs(gb - gf), ge))
            seen.append(slug)

    assert len(rows) >= 10, (
        f"only {len(rows)} course(s) put measurable sand inside a fairway on their fullest hole, so "
        f"this premise is not established across the corpus: {[r[0] for r in rows]}")
    worst = max(rows, key=lambda r: r[5])
    assert worst[5] <= _GREY_TOL, (
        f"the greyscale separation between a bunker and its fairway is now {worst[5]:.2f} levels of "
        f"255 on {worst[0]} hole {worst[1]} (fairway {worst[3]:.0f}, bunker {worst[4]:.0f}). It was "
        f"3.00. If the fills really do tell apart in mono now, the guide card's PRINT IN COLOUR line "
        f"and README's paragraph are overstated and both need re-reading -- this test is the record "
        f"of why they were written.")
    # ...and the hairline that is all a mono reader gets instead
    edges = [r[6] for r in rows if r[6] is not None]
    assert edges, "no bunker edge was sampled, so 'only a hairline outline is left' measures nothing"
    assert max(edges) < min(r[3] for r in rows) - 20, (
        f"the bunker edge greys {sorted(set(round(e) for e in edges))} are no longer distinguishable "
        f"from the fairway either, so nothing at all marks the sand in mono")
    assert total_bunkers > 500, (
        f"only {total_bunkers} bunkers across {len(GEOM)} courses; the corpus this warning is for is "
        f"bigger than that, so the population may have been narrowed by an import failure")


@needs_geom
def test_both_editions_tell_the_reader_to_print_in_colour():
    """The warning has to be on the card a junior actually holds, not only the coach's enlarged one.

    Twelve of the thirteen books carry a hole map; all twelve had NO print-in-colour line, while the
    three enlarged editions had one. This grades the card each build emits, so it is true of the next
    build rather than of the last one.

    The yardage book is exempt BY MEASUREMENT, not by name: its cards draw no hole map, so it has no
    bunker to lose. The test asks the engine which build mode it is in and then requires the exemption
    to be earned -- if that book ever starts drawing sand, it stops being exempt here.

    It also forbids the sentence that was there instead. "steeper is always darker, so it reads in
    black and white too" is TRUE of the green's heat ramp and FALSE of the hole map on the same card,
    and its position -- inside the row a reader consults when deciding how to print -- is what made it
    worse than silence. Any "black and white ... too" reassurance fails here.
    """
    warned, exempt, reassured, missing = [], [], [], []
    for slug in BOOKS:
        cfg, gen, rh, _rg = _engine(slug, deck=True)
        yardage = (cfg.BUILD_MODE == "yardage")
        card = _flat(gen.yardage_guide_panel() if yardage else gen.guide_panel())
        if yardage:
            # Earn the exemption from the DECK this book actually builds: not one card of it draws
            # render_hole's sand fill, so there is no bunker for a mono print to lose. If that ever
            # changes the assertion fires here rather than the book quietly going out unwarned.
            deck = gen.build_deck()[0]
            assert not any(BUNKER_FILL in p for p in deck), (
                f"{slug} builds in yardage mode but its deck now draws bunkers, so it is no longer "
                f"exempt from the print-in-colour warning")
            exempt.append(slug)
            continue
        if re.search(r"black (?:and|&(?:amp;)?) white\s+too", card, re.I):
            reassured.append(slug)
        if "Print in colour" in card and re.search(r"vanish in black", card, re.I):
            warned.append(slug)
        else:
            missing.append(slug)

    assert not missing, (
        f"{len(missing)} pocket guide card(s) never tell the reader to print in colour, on a book "
        f"whose bunkers separate from the fairway by 3.00 greys of 255 and whose every hole footer "
        f"prints a carry defined against that sand: {missing}")
    assert not reassured, (
        f"{len(reassured)} guide card(s) still say the colour ramp 'reads in black and white too'. "
        f"That is true of the green and false of the hole map printed beside it, and it is the "
        f"sentence a reader meets while choosing a printer: {reassured}")
    assert len(warned) >= 10 and len(warned) + len(exempt) == len(BOOKS), (
        f"warned {len(warned)}, exempt {len(exempt)}, of {len(BOOKS)} books -- every book must land "
        f"in exactly one of the two")

    # the enlarged edition, from the same builder the enlarged deck uses
    cfg, gen, _rh, _rg = _engine(next(s for s in BOOKS if s in GEOM), deck=True)
    coach = _flat(gen.coach_about_card())
    assert "Print in colour" in coach and re.search(r"vanish in black", coach, re.I), (
        "the enlarged edition's about card has lost the print-in-colour warning it always had")


@needs_geom
def test_readmes_colour_paragraph_says_what_the_books_say_and_what_the_pixels_say():
    """README's front-door paragraph made two checkable claims and one of them was false.

    "Both books say so on the guide card" -- one did. That sentence is the only place a reader is told
    the books themselves carry the warning, so it was the sentence standing in for the guide card that
    did not.

    Its "within 3% grey" figure is graded against the SAME measurement the test above takes, in the
    conservative direction: the number README publishes must be an upper bound on the separation, so a
    fill change that widened the gap past it fails here rather than leaving a stale figure on the
    front page. Rec.601 is the coefficient set used for that comparison and is named in the message,
    because "3% grey" is meaningless without one -- the same two fills are 2.87% apart in Rec.601 and
    1.43% in Rec.709.
    """
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        raw = fh.read()
    # The paragraph, not the whole file: bounded by blank lines in the SOURCE and flattened afterwards,
    # so a sentence that happens to appear elsewhere in README cannot satisfy a claim about this one.
    para = re.search(r"^\*\*Print in colour\.\*\*.*?(?=\n\n)", raw, re.S | re.M)
    assert para, "README no longer carries the print-in-colour paragraph this test grades"
    said = _flat(para.group(0))

    m = re.search(r"within\s+([\d.]+)%\s+grey", said)
    assert m, f"README's colour paragraph no longer publishes a grey separation figure: {said!r}"
    claimed = float(m.group(1))
    delta = abs(_luma601(_hex(BUNKER_FILL)) - _luma601(_hex(FAIRWAY_FILL))) / 255.0 * 100.0
    assert delta <= claimed, (
        f"README says a bunker's sand sits within {claimed}% grey of its fairway; measured Rec.601 on "
        f"the two fills render_hole emits it is {delta:.2f}%. The published bound no longer holds.")

    # ...and the "both books" claim, graded against the two panel builders it is about
    both = re.search(r"Both books say\s*so on the guide card", said)
    assert both, (
        "README's colour paragraph no longer states which books carry the warning on their guide "
        f"card. That sentence is the claim this test exists to keep honest; it now reads: {said!r}")
    cfg, gen, _rh, _rg = _engine(GEOM[0], deck=True)
    for name, card in (("guide_panel", gen.guide_panel()), ("coach_about_card", gen.coach_about_card())):
        assert "Print in colour" in _flat(card), (
            f"README says BOTH books say so on the guide card, and {name}() does not. Either put the "
            f"line back or stop claiming it -- this exact sentence was false for the whole life of "
            f"the pocket book.")


@pytest.mark.slow          # lays every shipped guide card out in a browser
@needs_books
def test_the_print_in_colour_line_costs_the_guide_card_no_room():
    """Card space is the binding constraint on this card, so the fix has to be measured, not preferred.

    `.card` is a fixed 3.5x5 in box with `overflow:hidden`: text that does not fit VANISHES, and the
    tail of this particular card is the licence, the warranty disclaimer and the contact address. The
    project has clipped that block twice.

    Measured here, per book, as the gap from the lowest inked text in the guide card to the bottom of
    the card box. monarch-bay ships with **1.19 px**; philadelphia 11.73; micke-grove 14.73. So the
    warning was put in place of the sentence it corrects rather than added under it, and the two
    candidates were measured against all twelve cards before choosing:

      * a NEW legend row               -> monarch-bay -12.36 px, philadelphia -1.81 px  (CLIPS)
      * keep the reassurance, scope it  -> monarch-bay  -9.36 px                        (CLIPS)
      * replace the reassurance         -> every book unchanged to 0.01 px               (SHIPPED)

    This test measures the CARD THE ENGINE EMITS NOW against the same bound, so the next caveat
    someone adds to guide_panel() is refused here instead of on paper. It reads the shipped book only
    for its stylesheet -- the one thing a panel cannot carry with it -- and lays the freshly built
    panel out under it.

    The metric is self-validating: an element deliberately parked below the card is measured first and
    must come back negative, so a change that makes this blind fails here rather than passing quietly.
    """
    JS = """() => {
      const c = document.querySelector('#w');
      const cb = c.getBoundingClientRect();
      let bot = -1e9, who = null, txt = null;
      c.querySelectorAll('*').forEach(e => {
        if (e.closest('svg')) return;
        if (![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length)) return;
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return;
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (r.bottom > bot) { bot = r.bottom; who = e.getAttribute('class') || ''; txt = e.textContent.trim().slice(-44); }
      });
      return {slack: +(cb.bottom - bot).toFixed(2), who, txt, h: cb.height};
    }"""
    PROBE = ("<div style='position:absolute;left:4px;top:520px' class='overflow-probe'>PROBE</div>")
    rows, checked = [], []
    with _Browser() as page:
        for slug in BOOKS:
            book = os.path.join(ROOT, "courses", slug, "greenbook.html")
            if not os.path.exists(book):
                continue
            with open(book, encoding="utf-8") as fh:
                css = re.search(r"<style>(.*?)</style>", fh.read(), re.S)
            assert css, f"{slug}: the shipped book carries no stylesheet to lay the card out under"
            cfg, gen, _rh, _rg = _engine(slug, deck=True)
            panel = (gen.yardage_guide_panel() if cfg.BUILD_MODE == "yardage" else gen.guide_panel())
            # the card box itself, exactly as the book's own stylesheet defines it
            box = (f"position:relative;width:{cfg.CARD_W_IN}in;height:{cfg.CARD_H_IN}in;overflow:hidden")
            page.set_content(_wrap(panel + PROBE, extra_css=css.group(1), box=box))
            seen = page.evaluate(JS)
            assert seen["slack"] < 0 and seen["who"] == "overflow-probe", (
                f"{slug}: the probe parked below the card box was not the lowest thing measured "
                f"({seen['who']!r} at {seen['slack']} px), so this test cannot see clipped text and "
                f"its silence means nothing")
            page.set_content(_wrap(panel, extra_css=css.group(1), box=box))
            got = page.evaluate(JS)
            rows.append((slug, got["slack"], got["who"], got["txt"]))
            checked.append(slug)

    assert len(checked) >= 10, f"only {len(checked)} guide card(s) measured: {checked}"
    over = [r for r in rows if r[1] < 0]
    assert not over, (
        "the guide card now overflows its own 3.5x5in box, so the tail -- the licence, the warranty "
        "disclaimer and the contact address -- is being cut off by overflow:hidden:\n  "
        + "\n  ".join(f"{s}: {sl:+.2f} px past the card, last element .{w} {t!r}"
                      for s, sl, w, t in sorted(over, key=lambda r: r[1])))
    tight = min(rows, key=lambda r: r[1])
    assert tight[1] < 8.0, (
        f"the tightest guide card now has {tight[1]:.2f} px of clearance ({tight[0]}), which is more "
        f"than the ~12 px a wrapped legend line costs. The paragraph above says this card has under "
        f"one legend row of headroom and that a new row clips it; if there is really that much room "
        f"now, re-measure before trusting the reasoning -- and check _engine(deck=True) is still "
        f"filling GREENS, because a cold panel measures 48 px of room that does not exist.")


# ===========================================================================
# 2. the depth ladder
# ===========================================================================
@pytest.mark.slow          # ~60 s: renders every green of every book at 600 dpi, three ways
@needs_geom
def test_the_depth_ladder_reads_on_paper():
    """The 5-yd rung labels are the yards-from-the-front-edge numbers a player judges depth with.

    They were the FAINTEST data on the card: `#8a8a8a` inside a group at `opacity="0.7"`, which
    composites to grey 172-173 -- **2.24:1** on white paper against WCAG's 4.5 -- printed at 4.09 pt
    to 8.90 pt. The slope numbers beside them are #111 with a white halo. The ladder had neither.

    Measured here at 600 dpi, three renders per green so the glyph can be told apart from what is
    behind it:

      * T -- the rung labels ALONE over white. Its darkest pixel is the ink, uncontaminated by
        whatever the card draws underneath, and its light pixels are the halo. Every earlier attempt
        at this measurement read the dark green outline bleeding through the glyph's antialiasing as
        "ink" and reported a healthy 10:1 for the worst labels on the card.
      * V -- the whole card. The 1-to-3-px collar around the glyph strokes, taken from V, is what the
        digit actually has to stand out against.
      * B -- the card with the ladder hidden, for the paint-order check below.

    THREE NUMBERS, and they are three different failures. Measured over all 1151 rung labels of the
    twelve books that carry a green card, against the pre-fix markup reconstructed into the same
    rendered SVGs:

      * INK AGAINST PAPER, the WCAG one:            1104 of 1104 under 4.5:1  ->  0 of 1151
      * LOCAL CONTRAST against its own collar:      1081 of 1104 under 4.5:1  ->  0 of 1151
      * COLLAR OVERPAINTED by dark ink (>= 25%):     243 of 1104               ->  0 of 1151

    The pre-fix population is 1104 and not 1151 because 47 labels were so faint that a luma-190
    threshold could not find their strokes at all -- they are missing from the "before" column of every
    row above, which understates it.

    Local contrast is the one darkening alone could not have fixed: a 1.3-unit #20402a stroke through a
    3.4-unit glyph is over three times the width of the digit's own stem, and grey on dark green is not
    a contrast problem a darker grey solves. It needs the halo.

    The collar figure has a bound rather than a zero because ONE mark on the card is drawn after the
    ladder and is neither dark nor light: the #666 compass, luma 102. On trump-national-los-angeles
    hole 15 its needle clips 10.7% of the "25" rung's collar -- beside the digit, not through it, and
    that label's local contrast is a clean 5.33:1. The bound is 25%, where the two populations
    separate: worst measured 10.7% against a pre-fix 95th percentile of 46.8% and a worst of 71.2%.

    AND NOTHING PAINTED AFTER THE LADDER MAY BE DISTURBED BY IT. The halo is opaque white, so if the
    label group were ever emitted after the slope numbers or the pin ring it would erase them. The
    pin ring is the one mark on the card the player writes on. Graded by pixel identity between V and
    B over exactly those two marks.
    """
    import numpy as np

    BOXES = ("(fs) => { const svg=document.querySelector('#w svg');"
             " return [...svg.querySelectorAll('text')]"
             ".filter(t=>t.getAttribute('font-size')===fs && /^[0-9]+$/.test(t.textContent.trim()))"
             ".map(t=>{const r=t.getBoundingClientRect();"
             " return {txt:t.textContent.trim(),x:r.x,y:r.y,w:r.width,h:r.height};}); }")
    ONLY = ("(fs) => { const svg=document.querySelector('#w svg'); svg.style.visibility='hidden';"
            " [...svg.querySelectorAll('text')]"
            ".filter(t=>t.getAttribute('font-size')===fs && /^[0-9]+$/.test(t.textContent.trim()))"
            ".forEach(t=>{t.style.visibility='visible';}); }")
    HIDE = ("(fs) => { const svg=document.querySelector('#w svg'); svg.style.visibility='';"
            " [...svg.querySelectorAll('text')]"
            ".filter(t=>t.getAttribute('font-size')===fs && /^[0-9]+$/.test(t.textContent.trim()))"
            ".forEach(t=>{t.style.visibility='hidden';}); }")
    ALL = ("() => { const svg=document.querySelector('#w svg'); svg.style.visibility='';"
           " svg.querySelectorAll('text').forEach(t=>{t.style.visibility='';}); }")

    SCALE = 6.25                       # 600 dpi
    RING_OUT, RING_IN = 3, 1           # device px; the halo runs ~5 px at this scale
    DARK = 120.0                       # #20402a is luma 52, an arrow 34, #333 51, the #666 compass 102
    COLLAR_MAX = 0.25                  # see the docstring: worst 0.107 after, 0.712 before
    SLOPE_INK, PIN_INK = (17, 17, 17), (192, 57, 43)   # #111 and #c0392b, both full opacity

    def luma(a):
        return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]

    def dilate(m, r):
        out = m.copy()
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
        return out

    n_rungs, faint, illegible, ringed, seen = 0, [], [], [], []
    worst_paper, worst_ring, worst_collar, disturbed, covered = None, None, (0.0, None), [], 0
    with _Browser(scale=SCALE) as page:
        for slug in GEOM:
            cfg, _gen, _rh, rg = _engine(slug)
            if cfg.BUILD_MODE == "yardage":
                continue
            here = 0
            for h in cfg.HOLE_NUMS:
                svg = rg.render(h, tournament=True)[0]
                page.set_content(_wrap(svg))
                boxes = page.evaluate(BOXES, RUNG_FONT_SIZE)
                if not boxes:
                    continue
                page.evaluate(ONLY, RUNG_FONT_SIZE); T = _shot(page)
                page.evaluate(HIDE, RUNG_FONT_SIZE); B = _shot(page)
                page.evaluate(ALL);                  V = _shot(page)
                # Nothing painted AFTER the ladder may be changed by it. Matched on EXACT colour, not a
                # colour range: the slope numbers' fill is #111 and the pin ring's stroke #c0392b, both at
                # full opacity, so their fully-covered pixels are those two triples and nothing else on
                # the card produces them -- an arrow composites to (21,39,27) and the heat ramp's red end
                # to (190,122,117). A range mask caught both of those through antialiasing and reported
                # 31 greens "disturbed" when nothing was.
                def cores(a):
                    return ((np.all(a == np.array(SLOPE_INK), axis=-1),
                             np.all(a == np.array(PIN_INK), axis=-1)))
                (sV, pV), (sB, pB) = cores(V), cores(B)
                d = int((sV != sB).sum() + (pV != pB).sum())
                if d:
                    disturbed.append((slug, h, d))
                covered += int(sV.sum() > 0) + int(pV.sum() > 0)
                H, W, _c = V.shape
                for bx in boxes:
                    pad = 10
                    x0 = max(0, int(bx["x"] * SCALE) - pad)
                    x1 = min(W, int(math.ceil((bx["x"] + bx["w"]) * SCALE)) + pad)
                    y0 = max(0, int(bx["y"] * SCALE) - pad)
                    y1 = min(H, int(math.ceil((bx["y"] + bx["h"]) * SCALE)) + pad)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    t = T[y0:y1, x0:x1].astype(int)
                    v = V[y0:y1, x0:x1].astype(int)
                    lt = luma(t)
                    core = lt < 190                    # the digit strokes, isolated over white
                    if not core.any():
                        continue
                    n_rungs += 1
                    here += 1
                    ii = np.unravel_index(np.argmin(np.where(core, lt, 1e9)), lt.shape)
                    ink = tuple(int(x) for x in t[ii])
                    paper = _contrast(ink, (255, 255, 255))
                    ring = dilate(core, RING_OUT) & ~dilate(core, RING_IN)
                    rv = v[ring]
                    loc = (tuple(int(x) for x in np.median(rv, axis=0)) if rv.size
                           else (255, 255, 255))
                    dfrac = float((luma(rv) < DARK).mean()) if rv.size else 0.0
                    local = _contrast(ink, loc)
                    key = (slug, h, bx["txt"])
                    if paper < WCAG_MIN:
                        faint.append(key + (round(paper, 2), ink))
                    if local < WCAG_MIN:
                        illegible.append(key + (round(local, 2), ink, loc))
                    if dfrac >= COLLAR_MAX:
                        ringed.append(key + (round(dfrac, 2), round(local, 2), loc))
                    if worst_paper is None or paper < worst_paper[0]:
                        worst_paper = (paper, key, ink)
                    if worst_ring is None or local < worst_ring[0]:
                        worst_ring = (local, key, ink, loc)
                    if dfrac > worst_collar[0]:
                        worst_collar = (dfrac, key)
            if here:
                seen.append(slug)

    assert n_rungs > 800, (
        f"only {n_rungs} rung labels measured across {len(seen)} course(s); the corpus carries over a "
        f"thousand, so the population was narrowed by something other than the data")
    assert len(seen) >= 10, f"only {len(seen)} course(s) contributed a rung label: {seen}"
    assert not faint, (
        f"{len(faint)} of {n_rungs} depth-ladder labels are under {WCAG_MIN}:1 against white paper. "
        f"These are the yards-from-the-front-edge numbers, printed from 4.09 pt; worst "
        f"{worst_paper[0]:.2f}:1 at {worst_paper[1]} ink={worst_paper[2]}. Sample: {faint[:6]}")
    assert not illegible, (
        f"{len(illegible)} of {n_rungs} depth-ladder labels are under {WCAG_MIN}:1 against the collar "
        f"they actually sit on -- which is what the white halo exists to make white. Worst "
        f"{worst_ring[0]:.2f}:1 at {worst_ring[1]}, ink {worst_ring[2]} on {worst_ring[3]}. This was "
        f"1081 of 1104 before the halo went on, and darkening the grey alone cannot fix it: grey on "
        f"#20402a is not a luminance problem. Sample: {illegible[:6]}")
    assert not ringed, (
        f"{len(ringed)} of {n_rungs} depth-ladder labels have dark ink (under luma {DARK:.0f}) filling "
        f"at least {COLLAR_MAX:.0%} of the {RING_OUT}-px collar around their own glyph strokes -- the "
        f"green's 1.3-unit #20402a outline or a #15271b arrow, drawn through a digit with nothing to "
        f"separate it. Worst collar {worst_collar[0]:.3f} at {worst_collar[1]}; the bound is set where "
        f"this separates from the one benign case (a #666 compass needle at 0.107). Sample: "
        f"{ringed[:6]}")
    assert not disturbed, (
        f"the depth ladder now disturbs the pin ring or the slope numbers on {len(disturbed)} green(s) "
        f"-- its halo is opaque white, so it must stay behind both. {disturbed[:6]}")
    assert covered > 300, (
        f"only {covered} of the greens measured put a fully-covered #111 slope digit or #c0392b pin "
        f"pixel on the page, so the paint-order check above had almost nothing to compare and its "
        f"silence would mean nothing")


# ===========================================================================
# 3. the cover address
# ===========================================================================
_ADDR_MIN_CLEAR_PT = 5.0    # the shipped tightest was 3.93 pt; see the docstring
_ADDR_BUDGET_CHARS = 60     # the character length the guard must still hold the frame at


@pytest.mark.slow          # lays every cover of every course out in a browser
@needs_books
def test_no_cover_address_crosses_the_gold_frame():
    """The address had a fixed 9-unit font and no width awareness, on a 221.3 pt frame.

    Measured, pocket and enlarged: the 13th course's "1 OCEAN TRAILS DR, RANCHO PALOS VERDES, CA
    90275" is 2.965 in wide with **3.93 pt** clear each side; Castlewood is next at 10.46 pt and the
    median is 24.85. The title has had a width-aware estimator since it was written. The address had
    none, so the first longer address crosses the gold rule with nothing in the pipeline to notice.

    FOUR THINGS ARE GRADED, because a sizing rule can fail in four directions:

      * every real address clears the inner frame by at least 5 pt. The bar is above the 3.93 pt that
        shipped, on purpose -- it is the thing that was wrong.
      * an address that ALREADY cleared that bar at the old fixed 9-unit size must still render at 9.
        This is what stops a fitting rule from quietly restyling twelve covers that were fine, and it
        is measured by setting the attribute back to 9 in the DOM and re-reading the glyph box, so the
        comparison does not depend on the order of attributes in the source.
      * the guard's CHARACTER BUDGET is walked rather than quoted: synthetic addresses of growing
        length are fed through the module global the covers read, and the longest one that still
        clears the bar is reported. The corpus's longest is 47 characters and the budget must reach at
        least 60, because the corpus is exactly the population that cannot exercise a guard.
      * the estimator behind the sizing must be CONSERVATIVE -- the real glyph box no wider than the
        width the rule predicted -- or the rule is guessing in the dangerous direction. Measured over
        every course.
    """
    JS = """() => {
      const svg = document.querySelector('.cover svg');
      const a = [...svg.querySelectorAll('text')].find(t => t.getAttribute('letter-spacing') === '1'
                  && /,/.test(t.textContent));
      if (!a) return null;
      const fr = [...svg.querySelectorAll('rect')].find(r => r.getAttribute('x') === '21');
      const bb = a.getBBox();
      const fx = parseFloat(fr.getAttribute('x')), fw = parseFloat(fr.getAttribute('width'));
      const sw = parseFloat(fr.getAttribute('stroke-width'));
      const r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
      const upt = Math.min(r.width / vb.width, r.height / vb.height) * 0.75;   // css px -> pt
      return {text: a.textContent, fs: parseFloat(a.getAttribute('font-size')),
              left_pt: (bb.x - (fx + sw / 2)) * upt,
              right_pt: ((fx + fw - sw / 2) - (bb.x + bb.width)) * upt,
              width_u: bb.width, width_in: bb.width * upt / 72, frame_pt: (fw - sw) * upt};
    }"""
    FORCE = """(fs) => {
      const svg = document.querySelector('.cover svg');
      const a = [...svg.querySelectorAll('text')].find(t => t.getAttribute('letter-spacing') === '1'
                  && /,/.test(t.textContent));
      a.setAttribute('font-size', String(fs));
    }"""
    CSS = (".card{position:absolute;left:0;top:0;width:3.5in;height:5in;overflow:hidden}"
           ".panel{position:absolute;inset:0;padding:0.07in;display:flex;flex-direction:column}"
           ".cover{position:relative;overflow:hidden;padding:0}")

    def look(page, panel, force=None):
        page.set_content(_wrap(f"<div class='card'>{panel}</div>", extra_css=CSS))
        if force is not None:
            page.evaluate(FORCE, force)
        got = page.evaluate(JS)
        assert got, "the cover no longer carries a letter-spaced address line this test can find"
        return got

    def clear(got):
        return min(got["left_pt"], got["right_pt"])

    rows, tight, restyled, optimistic, seen = [], [], [], [], []
    with _Browser() as page:
        for slug in BOOKS:
            cfg, gen, _rh, _rg = _engine(slug)
            for label, panel in (("pocket", gen.cover_panel()),
                                 ("enlarged", gen.coach_cover_panel("Test"))):
                got = look(page, panel)
                rows.append((slug, label, got))
                forced = look(page, panel, force=9)      # would 9 have cleared the bar?
                if clear(forced) >= _ADDR_MIN_CLEAR_PT and abs(got["fs"] - 9.0) > 1e-6:
                    restyled.append((slug, label, got["fs"], round(clear(forced), 2)))
                if clear(got) < _ADDR_MIN_CLEAR_PT:
                    tight.append((slug, label, round(clear(got), 2), round(got["width_in"], 3),
                                  got["fs"]))
                # the estimator the rule sizes by must not under-predict the real glyph box
                est = gen._addr_width_units(cfg.ADDRESS, got["fs"])
                if got["width_u"] > est + 0.5:
                    optimistic.append((slug, label, round(got["width_u"], 1), round(est, 1)))
            seen.append(slug)

        # THE BUDGET, walked rather than quoted. Synthetic addresses through the module global both
        # covers read. Built from real street and place words, NOT from a repeated letter: ADDR_CHAR_EM
        # is calibrated on upper-case English addresses, and a string of N (0.722 em in Helvetica,
        # against the corpus's measured 0.575-0.590 average) makes the estimator under-predict by 1% --
        # which is a true and separate fact about the estimator, not the guard this walk is grading.
        WORDS = ("North", "Canyon", "View", "Parkway", "Rancho", "Santa", "Margarita", "Village",
                 "Heights", "Junction", "Crossing", "Meadows")
        cfg, gen, _rh, _rg = _engine(BOOKS[0])
        budget, walked = 0, []
        for n in range(40, 86):
            addr, i = "13001", 0
            while len(addr) < n - 12:
                addr += (", " if i in (3, 7) else " ") + WORDS[i % len(WORDS)]
                i += 1
            addr = (addr[:n - 12].rstrip(" ,") + ", CA 92688")
            gen.ADDR = addr
            got = look(page, gen.cover_panel())
            walked.append((len(addr), round(clear(got), 2), got["fs"]))
            if clear(got) >= _ADDR_MIN_CLEAR_PT:
                budget = max(budget, len(addr))

    assert len(seen) == len(BOOKS), f"only {len(seen)} of {len(BOOKS)} covers measured"
    assert not tight, (
        f"{len(tight)} cover address(es) come within {_ADDR_MIN_CLEAR_PT} pt of the inner gold frame, "
        f"which is 221.3 pt wide -- (slug, edition, clearance pt, width in, font units): {tight}")
    assert not restyled, (
        f"{len(restyled)} cover address(es) were resized even though they already cleared the frame at "
        f"the old fixed 9-unit size. The fitting rule is a clipping guard, not a layout change -- "
        f"(slug, edition, size, clearance it had at 9): {restyled}")
    assert not optimistic, (
        f"the address width estimator UNDER-predicts the real glyph box on {len(optimistic)} cover(s), "
        f"so the sizing rule is guessing in the direction that clips -- "
        f"(slug, edition, measured units, predicted): {optimistic}")
    longest = max(len(g["text"]) for _s, _l, g in rows)
    assert budget >= _ADDR_BUDGET_CHARS, (
        f"the address guard holds the frame only to {budget} characters, against a required "
        f"{_ADDR_BUDGET_CHARS}. The corpus's longest is {longest}, so the corpus cannot exercise this "
        f"and the walk is the whole test of it. Measured (chars, clearance pt, font units): "
        f"{[w for w in walked if w[0] >= budget - 2][:8]}")
    # and the figures the docstring publishes, re-derived rather than remembered
    pocket = {s: g for s, lbl, g in rows if lbl == "pocket"}
    clears = sorted((clear(g), s) for s, g in pocket.items())
    assert clears[0][0] < 25.0, (
        f"the tightest cover address now has {clears[0][0]:.2f} pt of clearance ({clears[0][1]}); the "
        f"paragraph above is written about a corpus where one address was down to 3.93 pt, and if the "
        f"tightest is now comfortable that reasoning needs re-reading")

# ===========================================================================
# 4. the cover title break
# ===========================================================================
_NAME_ONE_LINE_MAX = 30      # _title_lines' own threshold; read off the function, asserted below


@needs_books
def test_no_course_name_over_thirty_characters_lacks_an_em_dash():
    """`_title_lines` greedy-fills a long name at 20 characters, and the fill splits phrases.

    "Trump National Golf Club Los Angeles" is 36 characters with no em-dash, so it took that branch
    and came out as ['Trump National Golf', 'Club Los Angeles'] -- "Golf Club" broken across two lines
    on the cover of a book with the club's name on it.

    THE GUARD IS THIS TEST AND NOT A SMARTER `_title_lines`, and that is a measurement rather than a
    preference: of the thirteen courses, five carry an em-dash and split on it, seven are 30 characters
    or fewer and stay on one line, and exactly ONE reaches the greedy fill. A rewrap rule would change
    nothing about the other twelve, so it would ship unexercised -- while the 14th course would hit
    whatever it happened to do. A course name is a hand-entered field in course.json, and the em-dash
    convention is already in use ("Merion Golf Club -- East Course" and four more), so the fix is to
    require it and fail loudly.

    The threshold is read off `_title_lines` rather than typed here, so moving the function's own
    boundary moves this test with it instead of leaving it grading a number the code abandoned.

    The premise is graded too: a >30-character name with no em-dash must still be one this test is
    right to refuse. If `_title_lines` ever learns to wrap on phrase boundaries, that assertion fails
    and points whoever taught it back here to decide whether the data rule is still wanted.
    """
    import json
    _cfg, gen, _rh, _rg = _engine(BOOKS[0])

    src = _flat(open(os.path.join(ROOT, "generate.py"), encoding="utf-8").read())
    m = re.search(r"if len\(raw\) <= (\d+): return \[raw\]", src)
    assert m, "_title_lines no longer keeps a short name on one line with an explicit threshold"
    limit = int(m.group(1))
    assert limit == _NAME_ONE_LINE_MAX, (
        f"_title_lines now keeps names up to {limit} characters on one line, not "
        f"{_NAME_ONE_LINE_MAX}. Move the constant in this test with it and re-read the census below.")

    dashed, short, greedy = [], [], []
    for slug in BOOKS:
        with open(os.path.join(ROOT, "courses", slug, "course.json"), encoding="utf-8") as fh:
            name = (json.load(fh).get("name") or "").strip()
        assert name, f"{slug}: course.json has no name for the cover"
        if "—" in name:
            dashed.append(slug)
        elif len(name) <= limit:
            short.append(slug)
        else:
            greedy.append((slug, name, len(name), gen._title_lines(name)))

    assert not greedy, (
        f"{len(greedy)} course name(s) are over {limit} characters with no em-dash, so the cover title "
        f"greedy-fills at 20 characters and breaks wherever the count lands -- "
        + "; ".join(f"{s}: {n!r} ({k} chars) -> {lines}" for s, n, k, lines in greedy)
        + f". Put an em-dash between the club and the course, as {len(dashed)} course(s) already do "
        f"(e.g. 'Merion Golf Club — East Course'), or shorten the name to {limit} characters.")
    assert dashed and short, (
        f"the census behind this rule no longer holds: {len(dashed)} em-dashed, {len(short)} short, "
        f"of {len(BOOKS)}. Both conventions must be in live use for 'require the em-dash' to be the "
        f"cheap fix rather than a new rule imposed on the data.")

    # the premise: the branch this rule exists to keep the data out of really does split a phrase
    probe = "Trump National Golf Club Los Angeles"
    assert len(probe) > limit and "—" not in probe
    lines = gen._title_lines(probe)
    assert len(lines) > 1 and lines[0].endswith("Golf") and lines[1].startswith("Club"), (
        f"_title_lines({probe!r}) now returns {lines}, which no longer splits 'Golf Club'. If it has "
        f"learned to wrap on phrase boundaries, the data rule above may no longer be needed -- decide "
        f"that deliberately rather than leaving both in place.")
