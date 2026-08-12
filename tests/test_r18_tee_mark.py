#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
THE MARK ON THE HOLE MAP THAT NAMED THE BACK TEE AT A PAD THAT IS NOT THE BACK TEE.

render_hole draws one tee mark, at the start of the DRAWN centreline, and labelled it with the back
tee's name on every card. On 22 of the corpus's 216 cards the mapped centreline does not span the
card: 17 run a complete route from a FORWARD tee, 2 were traced PAST the back tee, and on 3 nothing
can say where the shortfall lives. There the marked pad is not the tee the label named, and the card
told a junior standing on it that they were on the back tee.

Merion 5 is the case in full, measured from the OSM centreline and the mapped tee polygons:

  * the scorecard row is par 4, hcp 1, Championship 501, Middle 394, Forward 381
  * the traced centreline walks 397.9 yd -- the MIDDLE tee's route, not the Championship's
  * the line's start lies INSIDE mapped tee way 285155689; the next pad is 68.7 m away and is not
    drawn on the card at all
  * the shipped card headlines 501, carries `276 / 297` -- correctly measured from the Championship
    tee, through the +103.3 yd shift render_hole applies for exactly this case -- and marked the pad
    under the reader's feet "CHA"

So one card carried two claims 103 yd apart: the carries were measured from the real tee and the map
said the real tee was where the reader was standing.

WHY THE LABEL IS OMITTED THERE RATHER THAN MOVED OR RENAMED. Three options were measured:

  * MARK THE TRUE BACK TEE. It is not mapped in any form this engine can point at. On merion 5 the
    shortfall needs a pad 94.5 m behind the line's start along the hole axis; the nearest candidates
    sit 57.8 m and 84.9 m back by centroid and the closer of the two carries `ref=2` -- it is hole 2's
    tee. And the frame is fitted to the features it draws, so a mark 94 m outside it would rescale
    every card in the book.
  * NAME THE PAD THE LINE ACTUALLY STARTS ON. That rests on the forward-tee yardage match alone, which
    render_hole.line_runs_from_a_forward_tee's own measurement calls weak -- it fires on 41% of decoys.
    trump-national-los-angeles 10 is the live counter-example: its line's start pad is the REAR-MOST of
    the hole's pads (the other four sit +18 to +98 m DOWN the hole), while the yardage match names Blue,
    so naming the nearest pad would print a second wrong name on that card.
  * OMIT IT, which is what ships. The label's POSITION is itself the claim -- it points at one of the 2
    to 5 tee pads the card draws -- so no word pinned to that pad can stop the card asserting which pad
    the headline yardage belongs to. What is lost is only the claim: the green stays at the top of every
    frame with GRN on it, the pads stay drawn in tee ink, and the pad the line runs from is still the
    foot of the dashed centre line.

WHAT THIS FILE PINS, AND WHY IT IS NOT test_one_card_is_built_on_one_tee AGAIN. That test asserts the
label TEXT equals the back tee's name whenever a label is present; it never asks whether the marked pad
IS that tee, so all 22 wrong cards passed it. The relationship is measured here instead, and measured
independently: the centreline is walked in metres through geo's own earth model rather than read back
out of render_hole's `info`, so a flag drifting from the geometry cannot satisfy both sides.
"""
import glob
import json
import math
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conftest import corpus_slugs                                        # noqa: E402

GEOM = corpus_slugs()
needs_geom = pytest.mark.skipif(not GEOM, reason="per-course geometry is gitignored; nothing to render")

# The tee mark's ink. render_hole draws exactly one text element in it -- the tee-end label -- so its
# presence and its wording are both readable off the rendered card. The GRN label is #2f5a26 and the
# two gutter numbers are #2f5a26 / #7a4a12, so nothing else can be mistaken for it.
TEE_LABEL_INK = "#20402a"

# render_hole's own tolerance for "the drawn line spans this card", restated here because this file
# has to answer the same question from the geometry side. A line within 15 yd, or 5% on a long hole,
# of the card is taken to run from the tee the card measures.
def _spans(arc_yd, card_yd):
    return abs(arc_yd - card_yd) <= max(15.0, 0.05 * card_yd)


def _engine(slug):
    """config / render_hole / geo bound to ONE course, with the tee-column NOTE silenced."""
    for m in ("config", "render_hole", "render_green", "generate", "geo"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    os.environ["QUIET_TEE_CHECK"] = "1"
    import config
    import geo
    import render_hole
    return config, render_hole, geo


def _cards(slug):
    """Every card of one course, measured off the cache rather than read out of `info`.

    Per hole: the card's own back-tee yardage, the WALKED length of the drawn centreline in yards,
    how far the line's start lies from the nearest mapped tee polygon, and the tee-end label the
    rendered card actually carries.
    """
    cfg, rh, geo = _engine(slug)
    course, geom = rh.load()
    loc = cfg.COURSE.get("location") or {}
    lines = geo.hole_lines(geom, loc.get("lat"), loc.get("lon"))
    greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    pads = [g for g in course if (g.get("tags") or {}).get("golf") == "tee" and g.get("geometry")]
    out = {}
    for hn in sorted(cfg.HOLES):
        hn = int(hn)
        if hn not in lines:
            continue
        line = lines[hn]["geometry"]
        _green, _gend, tee_end = geo.match_green(line, greens)
        lat0 = sum(p["lat"] for p in line) / len(line)
        lon0 = sum(p["lon"] for p in line) / len(line)

        def em(lat, lon, lat0=lat0, lon0=lon0):
            return ((lon - lon0) * geo.mlon(lat0), (lat - lat0) * geo.mlat(lat0))

        pts = [em(p["lat"], p["lon"]) for p in line]
        arc_m = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                    for i in range(len(pts) - 1))
        start = em(tee_end["lat"], tee_end["lon"])
        pad_m = min((rh.dist_to_poly_m(start, t, em) for t in pads), default=float("inf"))
        svg, info = rh.render_hole(hn, cfg.HOLES)
        labels = re.findall(rf'fill="{TEE_LABEL_INK}"[^>]*>([^<]*)</text>', svg)
        out[hn] = dict(card_yd=cfg.HOLES[hn][cfg.BACK_I], arc_yd=arc_m / 0.9144,
                       pad_m=pad_m, labels=labels, info=info,
                       back=(cfg.BACK_NAME[:3].upper() if cfg.BACK_NAME else "TEE"))
    # A hole that fell out of the loop is a finding, not a narrowing: this course has the geometry
    # every card needs, so a missing centreline would quietly shrink every population below.
    assert len(out) == len(cfg.HOLES), (
        f"{slug}: {len(out)} of {len(cfg.HOLES)} scorecard holes have a drawn centreline; the cards "
        f"this file measures would be missing {sorted(set(map(int, cfg.HOLES)) - set(out))}")
    return out


# The cards whose drawn centreline does not span their card, per course -- the population whose tee
# mark may not name a tee. Pinned as a census rather than as a total so a regression that silences
# one MORE card, or one FEWER, names the card. Re-measure against the caches; do not adjust to match.
# It moved once already: valley-hi 17 left this set on 2026-07-31 when its too-tight osm_bbox was
# widened and the re-fetch replaced a 220 yd hand-drawn stub with the real 360 yd centreline.
UNSPANNED = {
    "bay-view-golf-club": (2, 6, 7, 12, 14, 15, 16),
    "callippe-preserve-golf-course": (3, 17),
    "castlewood-hill-course": (4, 16),
    "castlewood-valley-course": (10, 18),
    "merion-golf-club": (2, 3, 5, 6, 8, 9),
    "philadelphia-country-club": (17,),
    "trump-national-los-angeles": (10,),
    "valley-hi-country-club": (6,),
}


@needs_geom
def test_the_tee_mark_names_the_back_tee_only_where_the_line_runs_from_it():
    """A card may name the tee its mark sits on only when the geometry says the mark IS that tee.

    The measure is the one the whole engine already turns on, taken here from the cache: the drawn
    centreline's WALKED length against the yardage the published scorecard prints for the back tee. If
    the mark were the back tee those two describe the same route, so a line 103 yd short of its card
    is a line starting somewhere else, whatever pad it starts on.

    Graded in BOTH directions. A fix that stripped the label from every card would satisfy the half
    that matters here and quietly take the tee's name off the 194 cards that have earned it, so those
    are asserted to keep it.
    """
    named, unnamed, wrong = [], {}, []
    for slug in sorted(GEOM):
        for hn, c in sorted(_cards(slug).items()):
            gap = abs(c["arc_yd"] - c["card_yd"])
            if _spans(c["arc_yd"], c["card_yd"]):
                named.append((slug, hn))
                if c["labels"] != [c["back"]]:
                    wrong.append(
                        f"{slug} hole {hn}: the drawn line walks {c['arc_yd']:.1f} yd against a card of "
                        f"{c['card_yd']}, so the mark IS the {c['back']} tee, but the card labels it "
                        f"{c['labels'] or 'nothing'} -- the tee's name has been taken off a card that "
                        f"earned it")
                continue
            unnamed.setdefault(slug, []).append(hn)
            if c["labels"]:
                where = ("behind them" if c["arc_yd"] < c["card_yd"]
                         else "in front of them -- the line was traced PAST it")
                wrong.append(
                    f"{slug} hole {hn}: the mark is labelled {c['labels'][0]!r} at the start of a line "
                    f"that walks {c['arc_yd']:.1f} yd against a card of {c['card_yd']} -- {gap:.0f} yd "
                    f"apart, so the pad under that label is not the tee the card is built on. The mark "
                    f"stands where the reader stands and the tee it names is {gap:.0f} yd {where}.")
    assert not wrong, (
        f"{len(wrong)} card(s) mislabel their tee mark:\n  " + "\n  ".join(wrong[:12])
        + ("\n  ..." if len(wrong) > 12 else ""))
    # The census, graded per course so it holds on a partial corpus too: a course absent from the
    # record must have no unspanned card at all.
    for slug in sorted(GEOM):
        assert tuple(unnamed.get(slug, ())) == tuple(UNSPANNED.get(slug, ())), (
            f"{slug}: the cards whose line does not span their card measure "
            f"{tuple(unnamed.get(slug, ()))}, recorded as {tuple(UNSPANNED.get(slug, ()))}. Re-measure "
            f"against the caches rather than adjusting the record -- a card LEAVING this set gains a "
            f"tee name and a card joining it loses one.")
    assert len(named) >= 150, (
        f"only {len(named)} card(s) have a line that spans their card, so the direction that keeps the "
        f"tee's name on the page is barely exercised")
    assert sum(len(v) for v in unnamed.values()) >= 1, (
        "no card in this tree has a line short of its card, so the refusal this file exists for is "
        "not exercised at all")


@needs_geom
def test_merion_5_marks_a_pad_the_championship_tee_is_103_yd_behind():
    """The card this defect was found on, end to end, so the two claims are visible together.

    The carries are RIGHT and the mark was wrong, which is what made this invisible: the footer's
    `276 / 297` is measured from the Championship tee through render_hole's +103 yd tee shift, while
    the map put the Championship tee's name on the pad 103 yd in front of it. Nothing here changes a
    carry.
    """
    if "merion-golf-club" not in GEOM:
        pytest.skip("merion-golf-club has no geometry here")
    cards = _cards("merion-golf-club")
    c = cards[5]
    assert c["card_yd"] == 501, f"merion 5's back-tee card is {c['card_yd']}, expected 501"
    assert abs(c["arc_yd"] - 397.9) < 1.0, (
        f"merion 5's centreline walks {c['arc_yd']:.1f} yd; this case is measured at 397.9, the Middle "
        f"tee's own 394 yd route")
    assert abs((c["card_yd"] - c["arc_yd"]) - 103.3) < 1.0, "the tee-to-tee shortfall is measured at 103.3 yd"
    assert c["pad_m"] == 0.0, (
        f"merion 5's line starts {c['pad_m']:.1f} m from the nearest mapped tee pad; it is measured "
        f"INSIDE one, which is what made the wrong label look right")
    assert not c["labels"], (
        f"merion 5 still labels its tee mark {c['labels']} at a pad the Championship tee is 103 yd "
        f"behind")
    assert c["info"]["fwd_tee"] and not c["info"]["line_spans"], \
        "this pin assumes merion 5 is the forward-tee case"
    assert [n for n, _f in c["info"]["carries"]] == [276, 297], (
        f"merion 5's carries are {c['info']['carries']}; they are back-tee figures and this change "
        f"must not have moved them")
    # ...and the card that ships. The mark is what changed, so the shipped book still carries the old
    # label until the corpus is rebuilt; the carries in it must already be the back-tee pair.
    book = os.path.join(ROOT, "courses", "merion-golf-club", "greenbook.html")
    if os.path.isfile(book):
        with open(book, encoding="utf-8") as fh:
            html = fh.read()
        blk = next((b for b in re.split(r'<div class="panel hole', html)[1:]
                    if re.search(r'class="hnum">\s*5</div>', b)), "")
        blk = re.split(r'<div class="panel ', blk)[0]
        assert "carry <b>276 / 297</b>" in blk, (
            "merion 5's shipped card no longer prints the back-tee carry pair 276 / 297, which is the "
            "half of this card that was already right")


@needs_geom
def test_a_pad_under_the_mark_is_not_evidence_of_which_tee_it_is():
    """Every one of the 22 refused marks stands INSIDE a mapped tee pad. That is why it looked right.

    render_hole already measures this as `start_at_tee_m`, and on all 22 it is 0.00 m: the drawn line
    begins within a mapped `golf=tee` polygon on every card whose length says it cannot be the back
    tee's route. So "there is a tee here" is true of the refused marks and the named ones alike, and it
    is the one thing about that pad the geometry can establish -- not which tee it is. A future change
    that leans on the pad's presence to name the tee will be leaning on this.

    ONE card in the corpus goes the other way and is pinned so it cannot spread quietly: merion 15's
    line spans its card (405.8 yd against 415) and starts 63.4 m from the nearest mapped pad, with no
    tee polygon inside the drawing corridor at all -- that card draws no tee ink and its mark sits on
    open ground. It keeps its label, because the length is what licenses the name and the length agrees;
    the missing pad is an OSM gap, and it is recorded here rather than left to be rediscovered.
    """
    MARK_OFF_ANY_PAD = {("merion-golf-club", 15): 63.4}
    off, unspanned_off_pad = {}, []
    for slug in sorted(GEOM):
        for hn, c in sorted(_cards(slug).items()):
            spans = _spans(c["arc_yd"], c["card_yd"])
            if not spans and c["pad_m"] > 0.0:
                unspanned_off_pad.append(f"{slug} hole {hn}: {c['pad_m']:.2f} m")
            if c["pad_m"] > 1.0:
                off[(slug, hn)] = c["pad_m"]
    assert not unspanned_off_pad, (
        "a card whose line does not span its card starts clear of every mapped tee pad: "
        + ", ".join(unspanned_off_pad) + ". The docstring's claim that all 22 stand inside one no "
        "longer holds, so re-read it before trusting the pad's presence anywhere.")
    got = {k: round(v, 1) for k, v in sorted(off.items()) if k[0] in GEOM}
    want = {k: v for k, v in MARK_OFF_ANY_PAD.items() if k[0] in GEOM}
    assert got == want, (
        f"the cards whose tee mark stands clear of every mapped tee pad measure {got}, recorded as "
        f"{want}. A new entry is a card marking a tee on open ground -- re-measure the caches, and if "
        f"OSM has gained the pad, take the entry out rather than widening the tolerance.")
