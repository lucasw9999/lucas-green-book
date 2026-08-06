#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Two guards that were missing from paths nothing was watching.

  * THE PAIR. A green surface is dem_hd/holeNN.npy plus dem_hd/holeNN.json, and they only mean
    anything together -- the array carries no georeference, the sidecar's bbox places every pixel.
    surface_io.read_pair is this project's one definition of "a pair I am willing to measure
    through", and it was called by NO reader outside surface_io.py: fetch_hole_elev.green_elevation
    and three tools loaded the two halves with a bare json.load + np.load and checked neither the
    recorded shape nor the recorded array_sha256. The pipeline runs fetch_hole_elev BEFORE
    generate.py, so a torn pair put a wrong height into hole_elev.json first and render_green
    refused the hole afterwards -- naming only the surface rebuild as the remedy, so hole_elev.json
    kept the figure measured through the tear.

  * THE BLANK GREEN'S SCALE. render() caps a drawn green at 0.36 in : 5 yd against Rule 4.3's
    3/8 in : 5 yd; _blank_green's tournament branch applied no cap at all, on the stated grounds
    that "no green image is drawn to scale" -- which is false of the true-shape outline it draws.

Corpus tests SKIP where per-course data is absent (courses/ is gitignored), because a skip is
visibly not a pass. Nothing here writes inside courses/: the torn-pair fixtures are built under
tmp_path and the code under test is pointed at them.
"""
import inspect
import json
import math
import os
import re
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Rule 4.3's own numbers, spelled here the way tests/test_phase1_regressions.py spells them rather
# than imported from tools/check_scale.py -- importing that gate pulls in export_pdf's headless-shell
# discovery for a constant.
LIMIT_IN_PER_5YD = 0.375        # USGA Clarification 4.3a/1: 3/8 in : 5 yd == 1:480
TARGET_IN_PER_5YD = 0.360       # the design target render() sizes to, ~4% inside the cap

from geo import mlat, mlon      # noqa: E402  the project's ONE figure of the Earth


def _green_metas():
    """(course, hole, meta) for every built green surface, or [] on a fresh clone."""
    import glob
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "dem_hd", "hole*.json"))):
        slug = os.path.basename(os.path.dirname(os.path.dirname(p)))
        if slug.startswith("_"):
            continue
        with open(p, encoding="utf-8") as fh:
            m = json.load(fh)
        if "W" in m and "H" in m and m.get("polygon") and m.get("bbox"):
            out.append((slug, int(m["hole"]), m))
    return out


_METAS = _green_metas()
needs_corpus = pytest.mark.skipif(not _METAS,
                                  reason="per-course data is gitignored; nothing to measure")


def _px_m(meta):
    """Metres per DEM pixel, mean of the two axes -- the ground scale tools/check_scale.py divides by."""
    xmin, ymin, xmax, ymax = meta["bbox"]
    clat = meta["green_center"][0]
    return (((xmax - xmin) * mlon(clat)) / meta["W"] + ((ymax - ymin) * mlat(clat)) / meta["H"]) / 2.0


def _drawn_in_per_view_unit(svg):
    """The drawing scale a browser lays this SVG out at, in inches per viewBox unit.

    Measured off the emitted markup exactly the way tools/check_scale.py's CARDS_JS measures it off
    the laid-out element: preserveAspectRatio="meet", so the scale is the SMALLER of the two fits.
    """
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    st = re.search(r'style="width:([0-9.]+)in;height:([0-9.]+)in"', svg)
    assert st, "a tournament card must size its green in inches, not in %"
    return min(float(st.group(1)) / vb[2], float(st.group(2)) / vb[3]), vb


def _in_per_5yd(svg, meta):
    """What this drawing's printed scale is, in inches per 5 yards. The gated quantity."""
    k, _vb = _drawn_in_per_view_unit(svg)
    return k * 4.572 / _px_m(meta)


# --------------------------------------------------------------------------------------------------
# The pair
# --------------------------------------------------------------------------------------------------

def _commit_torn_pair(base, arr_run2, meta_run1, arr_run1):
    """Write the torn pair surface_io.commit_surface's two os.replace calls can leave behind.

    Run 1 commits properly (array and sidecar agree, digest recorded). Run 2's array then lands and
    the process dies before the sidecar rename -- so this run's array sits beside last run's
    sidecar. W and H are EQUAL on both runs, which is the case that matters: the pixel dimensions
    truncate metres to whole pixels, so a green whose polygon moves by less than one pixel keeps
    them, and the shape check alone cannot see the tear. The recorded array_sha256 can.
    """
    import surface_io
    surface_io.commit_surface(base, arr_run1, meta_run1)
    np.save(base + ".npy", arr_run2)          # the second rename never happened


def _torn_fixture(tmp_path):
    """A dem_hd holding one honest pair (hole 4) and one torn pair (hole 7), from real geometry.

    Real geometry, because a torn bbox has to be a bbox that could plausibly have moved: run 1's
    sidecar is run 2's shifted 5 m north-east, which is inside a single pixel of drift for these
    surfaces and is what a re-traced OSM ring looks like.
    """
    slug, hole, meta = _METAS[0]
    src = os.path.join(ROOT, "courses", slug, "dem_hd", f"hole{hole:02d}")
    arr2 = np.load(src + ".npy")
    dem = tmp_path / "dem_hd"
    dem.mkdir(parents=True, exist_ok=True)
    import surface_io

    honest = dict(meta, hole=4)
    surface_io.commit_surface(str(dem / "hole04"), arr2, honest)

    clat = meta["green_center"][0]
    dlat, dlon = 5.0 / mlat(clat), 5.0 / mlon(clat)
    x0, y0, x1, y1 = meta["bbox"]
    run1 = dict(meta, hole=7, bbox=[x0 + dlon, y0 + dlat, x1 + dlon, y1 + dlat])
    arr1 = arr2.copy()
    arr1[0, 0] = arr1[0, 0] + 0.01           # a different run's array, same dtype and shape
    _commit_torn_pair(str(dem / "hole07"), arr2, run1, arr1)
    return str(tmp_path), honest, run1, arr2


@needs_corpus
def test_a_torn_green_pair_cannot_write_a_hole_height(tmp_path, monkeypatch):
    """green_elevation must refuse a pair whose two halves came from different runs.

    THE ORDER IS THE WHOLE PROBLEM. PIPELINE.md runs fetch_hole_elev at step 6, before generate.py
    at step 7, so this function writes hole_elev.json first and render_green only refuses the hole
    later -- and render_green's remedy named the surface rebuild alone, so the height measured
    through the tear stayed in hole_elev.json and generate.py went on printing it.

    It checked `insufficient` and NaN-ness and nothing else: no H/W consistency test against the
    sidecar and no array_sha256 test, which is the only property that distinguishes two runs whose
    arrays have the same shape. Returning None would not do either -- PIPELINE.md notes that a
    missing elevation line is indistinguishable from an honest refusal, so a tear has to stop the
    run and say so.
    """
    import fetch_hole_elev as fhe
    dem_root, honest, run1, arr2 = _torn_fixture(tmp_path)
    monkeypatch.setattr(fhe, "DIR", dem_root)

    ok = fhe.green_elevation(4)
    assert ok is not None and math.isfinite(ok), (
        "the honest pair must still measure a height, or this test cannot fail for the right reason")

    with pytest.raises(SystemExit) as e:
        fhe.green_elevation(7)
    msg = str(e.value)
    assert "hole07" in msg or "hole 7" in msg, f"the refusal must name the hole: {msg}"
    assert "fetch_hole_elev" in msg, (
        "the refusal must name re-running fetch_hole_elev --write as part of the remedy: "
        "hole_elev.json is derived, and rebuilding only the surface leaves the torn figure in it")

    # And the figure it would have written is not the honest one, so this is a guard over a real
    # difference rather than a formality: the mask is placed by the torn sidecar's bbox.
    import render_green as rg
    a = arr2.astype(float)
    a[~np.isfinite(a)] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    H, W = a.shape
    poly = rg.poly_to_px(run1["polygon"], run1["bbox"], W, H)
    mask = np.array([[rg.point_in_poly(c + 0.5, r + 0.5, poly) for c in range(W)] for r in range(H)])
    would_have = float(np.nanmedian(a[mask]))
    assert abs(would_have - ok) * 3.28084 > 0.1, (
        f"the torn read must differ from the honest one for this fixture to be discriminating "
        f"(moved {abs(would_have - ok) * 3.28084:.3f} ft)")


@needs_corpus
def test_the_cross_flight_check_reads_the_shipped_surface_through_the_pair_guard(tmp_path):
    """tools/cross_flight_check.py's _shipped_putt fixes one putting-surface classification for both
    passes off the SHIPPED array -- and loaded it with a bare np.load.

    That tool's evidence is legal/09, and surface_io.commit_surface's own docstring names it as one
    of the consumers that re-derive metres-per-pixel from the sidecar and so inherit a tear rather
    than notice it. A pass comparison run against a torn pair is not a repeatability measurement.
    """
    import cross_flight_check as cfc
    dem_root, _honest, run1, arr2 = _torn_fixture(tmp_path)
    W, H = run1["W"], run1["H"]
    mask = np.zeros((H, W), bool)
    mask[H // 4:3 * H // 4, W // 4:3 * W // 4] = True
    grid = (W, H, 0.4, 0.4, mask)

    good = cfc._shipped_putt(dict(run1, hole=4, _dir=dem_root), grid)
    assert good is not None, "the honest pair must still classify, or this test proves nothing"
    with pytest.raises(ValueError, match="torn"):
        cfc._shipped_putt(dict(run1, hole=7, _dir=dem_root), grid)


def test_read_pair_is_the_definition_every_surface_reader_uses():
    """The claim surface_io.read_pair's docstring makes about itself, graded.

    STRUCTURAL, and said so plainly: there is no output-level discriminator for "this module reached
    the same conclusion by its own arithmetic". What it locks down is the thing that actually went
    wrong -- four readers of the pair, none of them calling the one function that defines what a
    readable pair is, so the guard existed and covered nobody. A fifth reader added next month is the
    failure this catches.

    render_green.render is deliberately NOT on this list and is asserted to be stricter instead. It
    refuses a sidecar carrying NO array_sha256, which read_pair accepts by design -- surface_io's own
    digest backfill reads unstamped pairs through read_pair, so read_pair cannot hold that bar
    without stamp_digest being unable to read the pairs it exists to stamp. read_pair is the floor;
    the renderer holds a ceiling above it.
    """
    for rel in ("fetch_hole_elev.py", os.path.join("tools", "verify_elevation.py"),
                os.path.join("tools", "gen_provenance.py"),
                os.path.join("tools", "cross_flight_check.py")):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "read_pair(" in src, (
            f"{rel} reads a green surface pair without surface_io.read_pair, so the shape and "
            f"array_sha256 checks that define a readable pair are absent from it")

    import render_green
    render_src = inspect.getsource(render_green.render)
    assert "DIGEST_KEY) is None" in render_src, (
        "render_green must keep REFUSING a sidecar with no array_sha256. read_pair accepts one (the "
        "backfill needs to), so routing the renderer through it would loosen the one guard that "
        "covers every printed slope")


# --------------------------------------------------------------------------------------------------
# The blank green's scale
# --------------------------------------------------------------------------------------------------

@needs_corpus
def test_a_blank_green_is_capped_by_rule_4_3_like_a_measured_one():
    """A pocket card badged "DESIGNED TO CONFORM - RULE 4.3" must not draw an over-scale green,
    whether the surface was measured or not.

    _blank_green draws the OSM outline of the putting green, uniformly scaled -- that is an image of
    a putting green, so the Clarification's 3/8 in : 5 yd applies to it. Its tournament branch fit
    the panel and nothing else, on a comment claiming no green image is drawn to scale. Measured
    across the built corpus as if each green were blank, 23 of 198 exceeded the cap, worst
    castlewood-hill 14 at 0.4772 in : 5 yd -- 27% over -- while legal/06 asserts as a blanket fact
    that greens are "rendered at 0.36 in : 5 yd". tools/check_scale.py would have caught it after
    the fact, in a browser, if anyone ran it; nothing prevented it.

    0 of 198 corpus greens are blank today, so this is the latent case -- and the trigger arrives
    for a whole course at once (see depth_width_yd), not for one green.
    """
    import render_green as rg
    over = []
    for slug, hole, meta in _METAS:
        svg, summary = rg._blank_green(dict(meta, insufficient=True), True)
        ipf = _in_per_5yd(svg, meta)
        if ipf > LIMIT_IN_PER_5YD:
            over.append((round(ipf, 4), slug, hole))
        assert summary["scale_max_in"] is not None, (
            f"{slug} hole {hole}: a blank card records no legal on-page height, so nothing "
            f"downstream can state the scale it was drawn at")
    over.sort(reverse=True)
    assert not over, (
        f"{len(over)} of {len(_METAS)} greens drawn through the blank path exceed the Rule 4.3 cap "
        f"of {LIMIT_IN_PER_5YD} in : 5 yd, worst {over[:3]}")


@needs_corpus
def test_a_blank_green_and_a_measured_one_are_sized_against_the_same_panel():
    """The blank path reserved 0.18 in of footer room where render() reserves 3*0.125 + 0.125.

    render()'s own comment says why 0.18 is wrong: a footer can wrap to three lines plus the
    playline, so 0.18 under-reserves by up to 0.32 in and a green sized against it is too tall for
    its panel. A blank card's footer is the same .foot flex row, so it wraps the same way.

    BEHAVIOURAL ONLY WHERE HEIGHT IS THE BINDING FIT, which is the whole difficulty, and the first
    version of this fixture did not have it. That version wrote its ring as [lon, lat] pairs while
    poly_to_px reads (lat, lon), so the shape drawn was not the 8 m x 40 m green its comment claimed:
    it laid out at VBw 95.70 x VBh 41.10, aspect 2.3285, and WIDTH bound it -- w-fit 0.021001 against
    h-fit 0.093917 -- so it drew 0.863 in into a 3.860 in panel, 4.5x of slack, and the assertion
    below passed at every footer allowance between 0.18 and 0.50. (The rotation was never the problem:
    approach_frame returns -90 - a_ang, and at bearing 0 a_ang is exactly -90, so theta is 0.0 and the
    pixel ring is drawn north-up. That half of the old comment was true.)

    16 m wide x 80 m deep at 0.4 m per pixel, ring in (lat, lon) like every real sidecar's, lays out
    at VBw 56.0 x VBh 216.0, aspect 0.2593 -- below the GRN_PANEL_W_IN/GRN_PANEL_H_IN = 0.5207 ratio at
    which height starts to bind -- and at 0.2043 in : 5 yd it is far enough inside the Rule 4.3 cap
    that neither of the other two fits can take over. It draws 3.860 in with the shared constant and
    4.180 in with the 0.18 allowance restored, so the assertion below fails when the constant is put
    back. That the fixture is height-bound at all is now asserted rather than asserted-about, because a
    fixture that quietly stops binding is exactly how this test came to grade nothing.

    Synthetic, because no shipped card reaches it. Measured through the blank path across the 198 built
    green geometries, height binds on 0: 167 are limited by the 2.010 in column and 31 by the Rule 4.3
    cap, and the most height-limited green (castlewood-valley 13, VBw/VBh = 0.5508) still sits above
    0.5207. (Those two counts are the BLANK path's, whose viewBox is the padded ring alone; the 172/26
    split at GRN_PANEL_W_IN is render()'s, over its own viewBox.)
    """
    import render_green as rg
    # 16 m wide (E-W) x 80 m deep (N-S) at 0.4 m per pixel, approached from due north. The ring is
    # (lat, lon) per vertex because that is the order poly_to_px reads and every real sidecar writes.
    clat = 37.5
    res_m, w_m, h_m = 0.4, 16.0, 80.0
    w_deg, h_deg = w_m / mlon(clat), h_m / mlat(clat)
    lon0, lat0 = -122.0, clat
    ring = [[lat0, lon0], [lat0, lon0 + w_deg], [lat0 + h_deg, lon0 + w_deg], [lat0 + h_deg, lon0]]
    meta = {"hole": 3, "W": int(round(w_m / res_m)), "H": int(round(h_m / res_m)),
            "bbox": [lon0, lat0, lon0 + w_deg, lat0 + h_deg],
            "green_center": [lat0 + h_deg / 2.0, lon0 + w_deg / 2.0], "polygon": ring,
            "approach_bearing": 0.0, "insufficient": True}
    svg, _summary = rg._blank_green(meta, True)
    k, vb = _drawn_in_per_view_unit(svg)
    VBw, VBh = vb[2], vb[3]
    drawn_h_in = k * VBh

    # ANTI-VACUITY, in two parts, both about this fixture rather than about the code. The footer
    # allowance can only move a drawing whose HEIGHT fit is the binding one of the three, and the
    # allowance it replaced has to actually overfill the panel; without both, the assertion after them
    # is satisfied by any allowance and grades nothing.
    cap, w_fit = TARGET_IN_PER_5YD * _px_m(meta) / 4.572, rg.GRN_PANEL_W_IN / VBw
    assert rg.GRN_PANEL_H_IN / VBh < min(cap, w_fit), (
        f"this fixture is not height-bound (h-fit {rg.GRN_PANEL_H_IN / VBh:.6f} against w-fit "
        f"{w_fit:.6f} and Rule 4.3 cap {cap:.6f}), so what footer allowance the blank path reserves "
        f"cannot change what it draws and the assertion below cannot fail")
    one_line_h_in = rg.config.CARD_H_IN - 2*0.07 - 0.50 - 0.18       # the allowance render() replaced
    would_have_drawn = min(cap, w_fit, one_line_h_in / VBh) * VBh
    assert would_have_drawn > rg.GRN_PANEL_H_IN + 0.05, (
        f"restoring the one-line 0.18 in allowance would draw {would_have_drawn:.3f} in into a "
        f"{rg.GRN_PANEL_H_IN:.3f} in panel, which does not overfill it, so the assertion below is "
        f"satisfied either way")

    assert drawn_h_in <= rg.GRN_PANEL_H_IN + 1e-9, (
        f"the blank path drew a {drawn_h_in:.3f} in green into a {rg.GRN_PANEL_H_IN:.3f} in panel; "
        f"it is sized against a footer allowance render() already replaced")
    assert _in_per_5yd(svg, meta) <= LIMIT_IN_PER_5YD, "and it must still be inside the Rule 4.3 cap"

    # ONE spelling of the panel, referenced by both paths -- not a third copy of the arithmetic.
    for fn in (rg.render, rg._blank_green):
        src = inspect.getsource(fn)
        assert "GRN_PANEL_H_IN" in src and "GRN_PANEL_W_IN" in src, (
            f"{fn.__name__} computes its own panel size instead of using the shared constants")
        assert "0.18" not in src, f"{fn.__name__} still carries the one-line-footer allowance"
