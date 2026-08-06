#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Cross-check every recorded tee-to-green height against an INDEPENDENT elevation product.

Why this exists. hole_elev.json is built from LAZ ground returns plus the green's own 0.4 m surface.
Both come from the same point cloud, so every check inside that pipeline shares its assumptions --
including its units. A unit fault therefore passed every gate the project had: the code subtracted a
US-survey-foot tee height from an already-metric green height and scaled the difference, and 74 of 175
holes carried a wrong figure, median error 298 ft, worst 554 ft. castlewood-hill 15 printed "green
558 ft below the tee" for a real -3.7 ft. Nothing objected, because every existing gate asks about
coverage, density and refusal -- none compares the answer with a second source.

The 3DEP seamless DEM is that second source: a different product, delivered in metres, reached over
the network rather than read off disk. It agrees with the corrected figures to a per-course median of
0.03-0.63 ft (measured 2026-08-05, all 11 courses, all 171 holes; it was quoted as 0.6-2.2 ft from before
both ends of the comparison moved onto the feature polygons), and it disagreed with the buggy ones by
hundreds of feet. So it separates the two cases decisively. Both ends are BOUNDS and are rounded
OUTWARD: the worst per-course median measures 0.6243 ft, and 0.62 -- its correct two-digit rounding --
would exclude the course it is there to cover.

The residual disagreement was reported as ONE-SIDED, and it is not. The note at TOL_FT said so from the
time the unit fault was fixed -- a 1 m raster smooths a raised tee pad down, measured -1.6 ft at
monarch-bay's tees, so residuals cluster a foot or two positive -- but only |diff| was ever REPORTED, so
no run could confirm it. When it was finally measured it held on the pre-polygon sampling: the DEM read
the green 0.80 ft higher relative to the tee than we did (median; mean +0.96), positive on 151 of 177
holes and significant on 9 of the 11 courses. Once BOTH ends were moved onto the feature polygons that
one-sidedness went. MEASURED 2026-08-05 over all 171 holes: corpus median -0.03 ft, mean -0.08, positive
on 59 of 171. Most of what the old paragraph attributed to the coarser reference was our own sampling
region, and the paragraph is kept only as the record of that.
The run prints the signed bias for this reason. It is evidence about the REFERENCE, not a fault in
the figures being checked, which is why a NEGATIVE bias would be the interesting result -- and it would
have been invisible.

It also reports the ABSOLUTE agreement, which costs no extra network and closes a gap the
cross-flight repeatability check explicitly cannot: that check compares our processing to ITSELF
(two surveys, both gridded by us), so a constant offset introduced by our own handling -- a vertical
unit read wrong, a CRS or grid misalignment, a geoid/ellipsoid mixup -- cancels out of every height
CHANGE and stays invisible. Comparing a green's absolute elevation against a raster this project does
not build catches exactly that class. MEASURED 2026-08-05 over 171 greens across all 11 courses: worst
per-course median 0.045 m, worst single green 0.312 m (merion). A US-survey-foot cloud read as metres
would show tens of metres here, a geoid confusion
about 30 m in California, and the foot/metre fault above showed a median 298 ft. What this still does
NOT bound is the source program's own datum or a turfgrass ground-classification bias, since the
seamless DEM comes from the same LiDAR -- recorded as still open in legal/09.

RE-MEASURED 2026-08-05, and every figure above now comes from one run of `--all` that reached all 171
holes. They previously predated 2026-08-02, when `_fetch_patch` was found to be discarding the GeoTIFF's
own georeference: the ring sampler built its pixel centres from the bbox it REQUESTED while the
ImageServer had EXPANDED that bbox to the square `size` it was asked for, so every sample sat at the
wrong place on the ground and reached past the polygon it was meant to be confined to (short axis
expanded more than 1.05x on 185 of 198 greens, worst 2.712). That inflated the disagreement, so the old
figures were upper bounds, and the correction is about the factor of two the one re-measured course
predicted: the corpus's worst absolute offset went 0.47 -> 0.312 m and the worst per-course median
0.10 -> 0.045 m. legal/09 item 1 still quotes the OLD figures from that era and is not this file's to
edit -- it needs the same replacement, from this run.

CORPUS FIGURES ARE PRINTED BY `_print_corpus`, which did not exist while they were being published.
Every corpus figure this file and generate.elev_phrase quote -- the median, the mean, the worst hole, the
worst per-course median, the counts over 2 and 3 ft -- had NO producer: this tool printed per-course
lines only, and one of them ("mean 0.27 ft" in elev_phrase) could not be found in the output of anything.
A CORPUS MEDIAN AND A MEDIAN OF PER-COURSE MEDIANS are also different numbers, and elev_phrase presented
one as the other; both are printed now, named, and they differ by a third on this corpus.

That spread is also what justifies the card's 3 ft floor: below it, two honest sources disagree by
enough that a printed "green 2 ft above" would be inside the gap between them (see elev_phrase in
generate.py).

It is a TOOL, not a unit test, because it needs the network. Run it when a course is added or the
elevation code changes.

Exit codes:  0 all figures agree within tolerance
             1 at least one figure disagrees -- suspect units, datum, or the wrong tee. EITHER a
               tee-to-green change outside TOL_FT, OR an absolute green elevation outside ABS_FAULT_M;
               the second used to be printed as a "processing fault" and then exit 0 regardless
             2 could not check (no data, or the elevation service was unreachable)

Run:  COURSE=<slug> python3 tools/verify_elevation.py
      python3 tools/verify_elevation.py --all
"""
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np

try:
    import rasterio
except ImportError:                     # not in requirements for years -- see the note in main()
    rasterio = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The project's ONE figure of the Earth. Re-declaring it here is how the value stayed wrong through
# two audits: ten files carried the literal and none imported it. See the note in geo.py.
from geo import mlat, mlon      # noqa: E402 -- ROOT must be on sys.path first
import surface_io               # noqa: E402 -- read_pair: the one definition of a readable pair

# THE TEE REGION, and it is not the same question on this tool's two tee branches.
#
# THE MAPPED-PAD BRANCH does not sample the producer's region, and a note here used to say it did. The
# GREEN side matches -- both read the green polygon. The TEE side does not: 9cc3bce established that the
# PRODUCER samples the mapped pad INTERSECTED with a 15 m window at the anchor, while this tool samples
# the WHOLE mapped ring (see check_course). That is a real difference on 55 of 177 mapped pads whose ring
# reaches past that window on an axis -- up to 63.0 m, micke-grove 17 -- and the producer's own
# derivation measures the median shift between the two regions at up to 1.87 ft, over 0.5 ft on 10 pads.
# TOL_FT is 10 ft, so this tool can never flag it: the disagreement it reports at those tees is partly a
# region difference, and the direction is known -- a wider region INFLATES it, so every |diff| this tool
# prints for them is an upper bound.
#
# NOT changed to sample the window, deliberately. Which region an INDEPENDENT reference should read is a
# real design question with a measured cost: the ring is what OSM actually maps, the window is what the
# producer chose, and a checker quietly re-pointed at the producer's own choice is a weaker check rather
# than a stronger one -- it would stop being able to disagree about region at all. Recorded as open, and
# graded by test_the_independent_checker_says_which_region_each_side_of_it_samples, which fails if the
# code starts clipping or if these counts drift.
#
# THE FALLBACK BRANCH -- the anchors that land in NO mapped ring, 5 of 182 in this corpus -- is the
# opposite case, and it was a 15 m box here for a reason that stopped being true. There is no OSM ring to
# be independent ABOUT on this branch: the region is chosen on BOTH sides, and this side's 15.0 was a
# copy of `fetch_hole_elev.TEE_R_M`, the producer's own fallback box. fd39647 measured that box wrong --
# bay-view 16's spanned 31.9 ft of hillside and printed "green 46 ft below" for a hole its own
# near-anchor ground puts at 48 -- and moved the producer to a TEE_FALLBACK_R_M DISC sized from the
# corpus's mapped pads. Holding 15.0 here afterwards would not have been independence; it would have
# been a stale copy of a region the producer had abandoned, comparing 900 m^2 against 113 m^2.
#
# So this branch now reads the producer's own disc -- see tee_fallback_radius_m, which takes the radius
# FROM the producer rather than re-declaring it. MEASURED COST of the alignment, in the DEM, at all five
# anchors, as the shift in the tee-to-green change this tool reports (15 m box -> the 6 m disc):
#     bay-view 16 +0.63 ft   castlewood-hill 4 +0.16   merion 3 -1.05   merion 9 +0.43   merion 15 -0.45
# Worst is MERION 3 at 1.05 ft, not bay-view 16, and it is under 1.1 ft on 5 of 171 holes and flips no
# verdict at TOL_FT. Two things follow that a one-sided reading would have missed. First the SIGN IS
# MIXED -- the box read the tee both above and below the disc -- so the "a wider region only INFLATES it,
# every |diff| is an upper bound" rationale that holds on the pad branch above never held on this branch,
# and keeping the box could not honestly have been written down as an upper bound at all. Second, the
# alignment REMOVED region difference from the hole this tool's own worst-observed figure used to name:
# bay-view 16 reported 1.21 ft against the 15 m box and 0.58 ft against the producer's disc, so 0.63 ft
# of what was published as a data disagreement was the two sides standing in different places -- the
# same +0.63 the row above names, because it is the same quantity. BOTH |diff| FIGURES ARE ON ONE BASIS,
# the rounded `change_ft` this tool reports against (check_course reads that field). The pair was
# published as 1.24/0.58 for a commit, which mixes it: 1.24 is measured against `change_ft_exact` and
# 0.58 against `change_ft`, the two differ by 0.033 ft on this hole, and the 0.66 ft their difference
# gives is neither region's cost. 1.24/0.61 would have been the other honest pair.
# NOT to be confused with the box-vs-disc difference in the POINT CLOUD, which is the producer's own
# figure and larger: +1.886 ft on bay-view 16 and -1.116 on merion 9 (fd39647). Those are LiDAR medians
# over the two regions; the five above are what the 3DEP raster does over the same two regions, and they
# are the only ones that describe THIS tool's comparison.
# A 1 m raster smooths a raised tee platform down, so it reads slightly BELOW the point cloud there:
# measured -1.6 ft at monarch-bay's tees. The change carried that through, so residuals were expected to
# cluster a foot or two positive; measured over all 171 holes they do not, and the note above the signed
# bias records that. 10 ft is comfortably above the worst observed (2.46 ft, philadelphia 5, measured
# 2026-08-05 over all 171 holes) and far below the hundreds of
# feet a unit fault produces -- this bound is meant to separate those two, not to audit the last foot.
TOL_FT = 10.0
ABS_FAULT_M = 1.0           # absolute green elevation vs the DEM. This is a SEPARATE verdict from
# TOL_FT: it is the only figure in the project that can see a constant offset in our own handling (unit,
# CRS, datum), because a constant cancels out of every height CHANGE and out of every check that compares
# our processing with itself. It used to be printed and then dropped -- `bad` was built from `diffs`
# alone -- so a run could print "this is a processing fault" and still return "ok" and exit 0.
# The gate was 2.0 while the sentence it printed said "a metre or more", so 1 to 2 m printed unmarked.
# The SENTENCE won: it is the promise this tool makes to its reader, and the evidence puts the line
# there. Healthy corpus offsets are a worst per-course median of 0.045 m and a worst single green of
# 0.312 m (measured 2026-08-05 over all 171), so 1 m clears real data by 3.2x -- it was 2x against the
# pre-georeference-fix figures -- while the faults it names -- ftUS read as metres, a
# geoid/ellipsoid confusion in California -- land tens of metres out. The wording below is BUILT from
# this constant so the two cannot drift apart again.
RETRIES = 5


def tee_fallback_radius_m():
    """Radius in metres of the disc the PRODUCER samples when no mapped ring holds the tee anchor.

    READ FROM fetch_hole_elev, never re-declared here. A checker that keeps its own copy of the
    producer's region cannot tell "the region moved" from "the ground disagrees", and this file already
    carries the record of what re-declaring a shared figure costs (see the note at the geo import: ten
    files held the Earth's radius and none imported it). Imported lazily because fetch_hole_elev is
    course-bound. See the region note above TOL_FT for why this branch aligns while the mapped-pad
    branch deliberately does not.
    """
    import fetch_hole_elev as fhe          # course-bound, so imported here rather than at module scope
    return float(fhe.TEE_FALLBACK_R_M)


def dem_median_over_ring(ring, px=64):
    """Median 3DEP elevation in metres over a lat/lon RING's interior, or None.

    Fetches the ring's bounding box and masks to the interior, so the reference measures the same ground
    the pipeline does. Without this the check compared a 3DEP box against our polygon, and the region
    mismatch dominated: a green is usually a raised pad, so a box that reaches 12 m past it reads low, and
    the residual that produced was previously written off in this file's own comment as a property of the
    1 m raster smoothing a tee platform down.

    The mask is built on the extent the SERVICE RETURNED, not the one requested. Asking for a square
    `size={px},{px}` over a bbox that is not square makes the ImageServer EXPAND the short axis to match,
    so the array covers more ground than the bbox above describes: measured 1.4819x in lon on monarch-bay
    hole 3, over 1.05x on 185 of the corpus's 198 greens, worst 2.712. Rebuilding pixel centres from the
    requested bbox therefore put every one of them at the wrong place on the ground and pulled the collar
    back into the sample -- 2889 cells where 1945 are inside that green -- which is the region error this
    function exists to remove.
    """
    import fetch_hole_elev as fhe          # course-bound, so imported here rather than at module scope
    rla, rlo = ring
    la0 = float(np.mean(rla))
    pad = 1.0 / mlat(la0)                              # a metre of margin so edge pixels exist
    s, n = float(rla.min()) - pad, float(rla.max()) + pad
    w, e = float(rlo.min()) - pad/math.cos(math.radians(la0)), float(rlo.max()) + pad/math.cos(math.radians(la0))
    got = _fetch_patch(w, s, e, n, px)
    if got is None:
        return None
    a, (w, s, e, n) = got               # the extent the service served, which is not the one asked for
    H, W = a.shape
    # pixel centres -> lat/lon -> inside test, in a local metric frame
    lons = w + (np.arange(W) + 0.5) / W * (e - w)
    lats = n - (np.arange(H) + 0.5) / H * (n - s)
    LO, LA = np.meshgrid(lons, lats)
    k, kla = mlon(la0), mlat(la0)
    inside = fhe._mask_in_ring((LO*k).ravel(), (LA*kla).ravel(), rlo*k, rla*kla).reshape(H, W)
    vals = a[inside & np.isfinite(a)]
    if vals.size == 0:
        return None
    return float(np.median(vals))


def _fetch_patch(w, s, e, n, px):
    """3DEP seamless elevation as `(array, (w, s, e, n))`, or None. The bbox is the one RETURNED.

    The georeference has to travel with the pixels. The ImageServer expands a non-square bbox to match
    the square `size` it was asked for, so the array does NOT cover the bbox this was called with, and a
    caller that assumes it does places every pixel centre wrong (see dem_median_over_ring).

    Returns None rather than raising: an unreachable service must read as "could not check" (exit 2),
    never as agreement. Out of coverage 3DEP hands back a CONSTANT raster instead of an error, so a
    zero-relief patch is reported as None too -- it means the point is off the edge of the data.
    """
    url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/"
           f"exportImage?bbox={w},{s},{e},{n}"
           f"&bboxSR=4326&size={px},{px}&imageSR=4326&format=tiff&pixelType=F32"
           "&interpolation=RSP_BilinearInterpolation&f=image")
    raw = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "greenbook/1.0"})
            raw = urllib.request.urlopen(req, timeout=120).read()
            break
        except Exception:
            if attempt == RETRIES - 1:
                return None
            time.sleep(2 + 2 * attempt)
    if not raw:
        return None
    try:
        with rasterio.open(io.BytesIO(raw)) as ds:
            a = ds.read(1).astype(float)
            b, ident = ds.bounds, ds.transform.is_identity
    except Exception:
        return None
    if ident:
        return None                     # no georeference at all: refuse rather than guess an extent
    a[~np.isfinite(a)] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return None
    if float(fin.max() - fin.min()) == 0.0:
        return None                     # constant raster: off the edge of 3DEP, not a reading
    return a, (float(b.left), float(b.bottom), float(b.right), float(b.top))


def dem_median_m(lat, lon, r_m=None, px=64):
    """Median 3DEP elevation in metres over a DISC about (lat, lon), or None. The FALLBACK sampler, for
    a tee anchor no mapped ring contains -- the ring sampler above is what the greens and mapped tees
    use. On the GREEN side that is the same region the pipeline reads, and on THIS branch it now is too:
    the radius is the producer's own TEE_FALLBACK_R_M (see tee_fallback_radius_m), so what is left here
    is disagreement about the data. At a MAPPED tee it still is not: this tool reads the whole mapped ring
    where the pipeline reads the pad inside a 15 m window -- see the region note above TOL_FT, which
    measures how far apart those two regions get and why that branch is left alone.

    This was a 15 m BOX until the producer's fallback stopped being one; that note also records what
    aligning it cost, per hole. Masked on the extent the SERVICE RETURNED for the same reason
    dem_median_over_ring is: the ImageServer expands a non-square bbox, so pixel centres rebuilt from the
    requested one sit at the wrong place on the ground."""
    r = tee_fallback_radius_m() if r_m is None else float(r_m)
    dlat = (r + 1.0) / mlat(lat)                       # a metre of margin so edge pixels exist
    dlon = (r + 1.0) / mlon(lat)
    got = _fetch_patch(lon-dlon, lat-dlat, lon+dlon, lat+dlat, px)
    if got is None:
        return None
    a, (w, s, e, n) = got               # the extent the service served, which is not the one asked for
    H, W = a.shape
    lons = w + (np.arange(W) + 0.5) / W * (e - w)
    lats = n - (np.arange(H) + 0.5) / H * (n - s)
    LO, LA = np.meshgrid(lons, lats)
    dx, dy = (LO - lon) * mlon(lat), (LA - lat) * mlat(lat)
    m = (dx*dx + dy*dy <= r*r) & np.isfinite(a)
    if not m.any():
        return None
    return float(np.median(a[m]))


def check_course(slug):
    """(status, n_checked, worst_diff_ft, worst_hole, samples). status: 'ok' | 'bad' | 'skip'.

    `samples` carries the per-hole numbers out so main() can publish CORPUS figures. It exists because
    the figures elev_phrase's docstring quotes to justify the card's 3 ft print floor -- a corpus median,
    a corpus mean, a worst hole, a worst per-course median -- were produced by NO CODE PATH in this
    project: this tool printed per-course lines only, and a grep for the mean found the sentence and
    nothing else. A published figure with no producer is the defect this repo keeps finding, so the
    producer is here now and main() prints every one of them.
    """
    for m in ("config", "render_hole", "render_green", "fetch_hole_elev"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config                                    # noqa: E402
    import geo                                       # noqa: E402
    import fetch_hole_elev as fhe                    # noqa: E402

    p = os.path.join(config.COURSE_DIR, "hole_elev.json")
    if not os.path.isfile(p):
        print(f"{slug}: no hole_elev.json -- nothing to verify")
        return "skip", 0, 0.0, None, {}
    rec = json.load(open(p))["holes"]
    els = json.load(open(f"{config.COURSE_DIR}/osm_geom.json"))["elements"]
    greens = [e for e in els if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    _loc = config.COURSE.get("location") or {}
    holes = geo.hole_lines(els, _loc.get("lat"), _loc.get("lon"))

    tee_rings = fhe.tee_rings_latlon()
    print(f"{slug}  (independent check against the 3DEP seamless DEM, tolerance {TOL_FT:g} ft)")
    diffs, signed, absolute, unreachable = [], [], [], 0
    for hn in sorted(int(k) for k in rec):
        if hn not in holes:
            continue
        la, lo, _basis = fhe.tee_anchor(hn, holes[hn]["geometry"], greens)
        if la is None:
            continue
        meta_p = os.path.join(config.COURSE_DIR, "dem_hd", f"hole{hn:02d}.json")
        if not os.path.isfile(meta_p):
            continue
        # THE PAIR, read as a pair -- surface_io.read_pair, this project's one definition of a surface
        # worth measuring through. The sidecar was loaded here with json.load and the array below with
        # np.load, so neither the shape the sidecar records nor its array_sha256 was checked, and a torn
        # pair breaks BOTH halves of this tool's comparison at once: the polygon it samples the 3DEP
        # reference over comes from the sidecar, and the absolute elevation it holds that reference
        # against comes from the array beside it. The disagreement would then be reported as data, in
        # the one line whose whole job is to bound our own processing.
        # It raises rather than skipping the hole on purpose: a checker that quietly drops the one green
        # whose pair is torn still prints a median and a worst case over "the corpus". main()'s per-course
        # `except Exception` catches it, names the course and the tear, and records the course as NOT
        # CHECKED -- which can never be read as agreement (see the `if not ok` exit-2 arm).
        _a_raw, _meta, _digest = surface_io.read_pair(meta_p[:-len(".json")])
        # `green_center` is no longer read here, and its consumer was replaced DELIBERATELY rather than
        # lost: this was `gla, glo = ...["green_center"]` feeding `d_grn = dem_median_m(gla, glo)`, a disc
        # median at the green's centre, until 4b19d2f moved the reference onto the green POLYGON so that
        # both sides of the comparison measure the same region ("the measured height of the green was
        # measured mostly off the green"). The unpack outlived it. See dem_median_over_ring below.
        # The reference reads the green POLYGON, which IS the region the pipeline reads, so on the
        # green side what is left is disagreement about the data. At a MAPPED tee it reads the WHOLE
        # mapped tee ring while the pipeline reads the pad inside a 15 m window, so there the difference
        # also carries a region difference -- inflating it, never hiding it. Where no ring holds the
        # anchor both sides now read the producer's own fallback disc. See the region note above TOL_FT.
        _gp = np.asarray(_meta["polygon"], float)
        d_grn = dem_median_over_ring((_gp[:, 0], _gp[:, 1]))
        _ring = fhe.ring_containing(la, lo, tee_rings)
        d_tee = (dem_median_over_ring(_ring) if _ring is not None else dem_median_m(la, lo))
        if d_tee is None or d_grn is None:
            print(f"  hole {hn:2d}: DEM unavailable at the tee or the green -- not checked")
            unreachable += 1
            continue
        indep_ft = (d_grn - d_tee) * 3.28084
        ours_ft = rec[str(hn)]["change_ft"]
        d = indep_ft - ours_ft
        diffs.append((abs(d), hn, ours_ft, indep_ft))
        flag = "" if abs(d) <= TOL_FT else "   <== DISAGREES"
        signed.append(indep_ft - ours_ft)
        # ABSOLUTE agreement, free of extra network: d_grn is already in hand. The height CHANGE is a
        # difference, so it cancels any constant offset in our own processing -- a vertical unit read
        # wrong, a CRS or grid misalignment, a geoid/ellipsoid mixup. Those are exactly the faults the
        # cross-flight repeatability check cannot see, because that compares our processing to itself.
        # Comparing the green's absolute elevation against a raster this project does NOT build closes
        # that gap. This is not hypothetical: a foot/metre fault once put 74 of 175 holes' elevations
        # out by a median 298 ft. A US-survey-foot cloud read as metres shows tens of metres here; a
        # geoid confusion about 30 m in California. Measured over all 177 holes with both sides masked
        # to the green polygon: median 0.00 m, worst 0.80 m -- both pre-georeference-fix, so upper
        # bounds; see PENDING RE-MEASUREMENT in the module docstring. See
        # legal/09_GREEN_SURFACE_REPEATABILITY.md.
        #
        # MASKED, like green_elevation. This took the median of the WHOLE .npy -- the green plus its 12 m
        # collar -- and compared it against a 3DEP median masked to the green polygon, so it measured the
        # region difference the pipeline had just stopped making and reported a spurious +0.127 m offset
        # in the one line whose job is to bound our own processing. It also skipped the >1e30 NoData
        # sentinels that green_elevation strips.
        try:
            _a = _a_raw.astype(float)     # already checked against its sidecar; see read_pair above
            _a[~np.isfinite(_a)] = np.nan
            _a[np.abs(_a) > 1e30] = np.nan
            _gpx = fhe.np_green_mask(_a.shape, _meta) if hasattr(fhe, "np_green_mask") else None
            if _gpx is None:
                import render_green as _rg
                _H, _W = _a.shape
                _poly = _rg.poly_to_px(_meta["polygon"], _meta["bbox"], _W, _H)
                _gpx = np.array([[_rg.point_in_poly(c + 0.5, r + 0.5, _poly) for c in range(_W)]
                                 for r in range(_H)])
            if _gpx.any() and not np.all(np.isnan(_a[_gpx])):
                absolute.append(d_grn - float(np.nanmedian(_a[_gpx])))
        except Exception:
            pass
        print(f"  hole {hn:2d}: ours {ours_ft:+7.1f} ft   DEM {indep_ft:+7.1f} ft   "
              f"diff {d:+6.2f}{flag}")
    if not diffs:
        print(f"  could not check any hole ({unreachable} unreachable)")
        return "skip", 0, 0.0, None, {}
    diffs.sort(reverse=True)
    worst, worst_hn = diffs[0][0], diffs[0][1]
    med = float(np.median([d[0] for d in diffs]))
    bad = [d for d in diffs if d[0] > TOL_FT]
    abs_fault, aw = False, 0.0
    samples = {"abs_diff_ft": [(d[0], d[1]) for d in diffs], "median_ft": med,
               "signed_ft": list(signed), "absolute_m": list(absolute), "unreachable": unreachable}
    print(f"  => {len(diffs)} holes checked, median |diff| {med:.2f} ft, worst {worst:.2f} ft "
          f"(hole {worst_hn}){', ' + str(unreachable) + ' unreachable' if unreachable else ''}")
    # Report the SIGNED bias too. "Small" and "unbiased" are different claims, and reporting only
    # |diff| hid a systematic: the DEM reads the green ~0.8 ft higher relative to the tee than we do,
    # on 151 of 177 holes corpus-wide -- until both ends moved onto the feature polygons, after which it
    # is 94 of 171 and two-sided. The direction WAS expected of a coarser reference -- a 1 m
    # raster smooths a raised tee pad toward the ground around it, so it under-reads the tee -- so it
    # says something about the REFERENCE, not about the figures being checked. A run that came out
    # NEGATIVE would be the anomaly worth chasing, and it was invisible before.
    if absolute:
        am = float(np.median(absolute))
        aw = max(absolute, key=abs)
        abs_fault = abs(aw) > ABS_FAULT_M
        tag = ("" if not abs_fault else
               f"  <== {ABS_FAULT_M:g} m or more of ABSOLUTE offset is a processing fault (unit, CRS, "
               f"datum), not terrain; see the module docstring")
        print(f"     absolute green elevation vs the DEM: median {am:+.2f} m, worst {aw:+.2f} m "
              f"over {len(absolute)} green(s){tag}")
    if signed:
        pos = sum(1 for v in signed if v > 0)
        sm = float(np.median(signed))
        # Three outcomes, and only one is interesting. A positive bias is expected (the coarser
        # reference under-reads a raised tee). NO bias is unremarkable -- copper-valley sits at
        # -0.01 ft with 9 of 18 positive, and flagging that as "negative" was this line's first bug.
        # A genuinely REVERSED bias would mean the DEM reads the tee higher than the point cloud,
        # which no resolution argument explains, so that is what earns a mark.
        tag = ("" if sm >= -0.5 else
               "  <== REVERSED bias: the DEM reads the tee HIGHER than the point cloud, which "
               "resolution does not explain; see the module docstring")
        print(f"     signed bias (DEM - ours): median {sm:+.2f} ft, "
              f"mean {float(np.mean(signed)):+.2f}, positive on {pos} of {len(signed)}{tag}")
    if bad:
        print(f"  !! {len(bad)} hole(s) disagree by more than {TOL_FT:g} ft. A difference this size is\n"
              f"     not terrain: check the vertical unit (only the raw LAZ tee height takes the CRS\n"
              f"     axis scale -- the green surface is already metres), the vertical datum, and that\n"
              f"     the tee anchor is the tee you think it is.")
    if abs_fault:
        # The verdict this used to leave out. An absolute offset does NOT show up in the diffs above --
        # it moves both ends of every hole together and cancels out of the change -- so a run that
        # reported only |diff| exited 0 on exactly the fault class this line was added to catch.
        print(f"  !! the green's ABSOLUTE elevation is out by up to {aw:+.2f} m against the DEM, over\n"
              f"     {ABS_FAULT_M:g} m. That is not terrain and it does not show up in the tee-to-green\n"
              f"     changes above, because a constant offset cancels out of a difference: check the\n"
              f"     vertical unit, the CRS, and the vertical datum/geoid.")
    if bad or abs_fault:
        return "bad", len(diffs), worst, worst_hn, samples
    return "ok", len(diffs), worst, worst_hn, samples


def _print_corpus(results):
    """The CORPUS figures, printed by the tool that measures them.

    Every figure elev_phrase's docstring quotes to justify the card's 3 ft print floor is a corpus
    figure -- a median and a mean over all holes, a worst hole, a worst per-course median -- and until
    this function existed NO CODE PATH in this project produced one. The tool printed per-course lines;
    the corpus numbers were arrived at somewhere else and typed in. One of them ("mean 0.27 ft") could
    not be found in any output at all: a grep turned up the sentence and nothing else.

    A CORPUS MEDIAN AND A MEDIAN OF PER-COURSE MEDIANS ARE DIFFERENT NUMBERS and the docstring labelled
    one as the other, so both are printed here, named. On this corpus they differ by a third.

    THE BEST per-course median is printed beside the worst because the figure published about this run
    is a RANGE and only one of its two ends had a producer. The low end had to be read off eleven
    per-course lines that print to 0.01 ft, so nothing could grade it at the precision a range endpoint
    needs -- and an endpoint rounded the wrong way excludes the very course it is supposed to cover.
    """
    per = {s: r[4] for s, r in results.items() if r[4]}
    if not per:
        return
    alld = [(v, s, h) for s, d in per.items() for v, h in d["abs_diff_ft"]]
    if not alld:
        return
    vals = sorted(v for v, _s, _h in alld)
    meds = {s: d["median_ft"] for s, d in per.items()}
    worst = max(alld)
    wc = max(meds, key=lambda s: meds[s])
    bc = min(meds, key=lambda s: meds[s])
    sgn = [v for d in per.values() for v in d["signed_ft"]]
    ab = [v for d in per.values() for v in d["absolute_m"]]
    unreach = sum(d["unreachable"] for d in per.values())
    print(f"CORPUS over {len(vals)} hole(s) in {len(per)} course(s)"
          f"{f', {unreach} unreachable' if unreach else ''}:")
    print(f"  |diff| vs the DEM   : median {float(np.median(vals)):.4f} ft, mean "
          f"{float(np.mean(vals)):.4f}, worst {worst[0]:.4f} ({worst[1]} {worst[2]})")
    print(f"  per-COURSE medians  : worst {meds[wc]:.4f} ft ({wc}), best {meds[bc]:.4f} ({bc}), "
          f"median of the {len(meds)} course medians "
          f"{float(np.median(list(meds.values()))):.4f} "
          f"-- NOT the same figure as the corpus median above")
    for t in (2.0, 3.0):
        n = sum(1 for v in vals if v > t)
        print(f"  holes over {t:g} ft        : {n}")
    if sgn:
        print(f"  signed bias DEM-ours: median {float(np.median(sgn)):+.4f} ft, mean "
              f"{float(np.mean(sgn)):+.4f}, positive on {sum(1 for v in sgn if v > 0)} of {len(sgn)}")
    if ab:
        pc = [max(abs(v) for v in d["absolute_m"]) for d in per.values() if d["absolute_m"]]
        pcm = [abs(float(np.median(d["absolute_m"]))) for d in per.values() if d["absolute_m"]]
        print(f"  absolute green vs DEM: worst per-course median {max(pcm):.4f} m, worst single green "
              f"{max(pc):.4f} m over {len(ab)} green(s)")
    print()


def main():
    # This tool is the ONLY independent check on the printed elevation figures -- it is what
    # separated a real -3.7 ft from the "558 ft below" a units fault produced. rasterio was never in
    # requirements.txt, and the read was wrapped in `except Exception: return None`, so on a fresh
    # install every hole came back "DEM unavailable" and the run ended "nothing could be verified --
    # treat as UNKNOWN". Indistinguishable from a USGS outage, and the natural reading is that the
    # service is down rather than that a package is missing. Say which it is.
    if rasterio is None:
        print("rasterio is not installed, so the DEM comparison cannot run at all.\n"
              "  This is a MISSING DEPENDENCY, not an unreachable service:\n"
              "    python3 -m pip install rasterio\n"
              "  Refusing rather than reporting every hole as unverifiable.")
        return 2
    if "--all" in sys.argv:
        slugs = sorted(os.path.basename(os.path.dirname(p))
                       for p in __import__("glob").glob(os.path.join(ROOT, "courses", "*", "course.json")))
        slugs = [s for s in slugs if not s.startswith("_")]
    else:
        slug = os.environ.get("COURSE")
        if not slug:
            print("set COURSE=<slug>, or pass --all"); return 2
        slugs = [slug]
    results = {}
    for s in slugs:
        try:
            results[s] = check_course(s)
        except Exception as e:
            print(f"{s}: could not verify ({type(e).__name__}: {e})")
            results[s] = ("skip", 0, 0.0, None, {})
        print()
    _print_corpus(results)
    bad = [s for s, r in results.items() if r[0] == "bad"]
    ok = [s for s, r in results.items() if r[0] == "ok"]
    skip = [s for s, r in results.items() if r[0] == "skip"]
    print(f"{len(ok)} course(s) agree, {len(bad)} disagree, {len(skip)} not checked")
    if bad:
        print("DISAGREE: " + ", ".join(bad))
        return 1
    if not ok:
        print("nothing could be verified -- treat as UNKNOWN, not as agreement")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
