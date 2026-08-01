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
the network rather than read off disk. It agrees with the corrected figures to a median 0.6-2.2 ft
across the courses measured, and it disagreed with the buggy ones by hundreds of feet. So it separates
the two cases decisively.

The residual disagreement is ONE-SIDED. The note at TOL_FT has said so since the unit fault was fixed
-- a 1 m raster smooths a raised tee pad down, measured -1.6 ft at monarch-bay's tees, so residuals
cluster a foot or two positive -- but only |diff| was ever REPORTED, so no run could confirm it held.
Measured across the whole corpus it does: the DEM used to read the green 0.80 ft higher relative to the tee
than we do (median; mean +0.96), positive on 151 of 177 holes and significant on 9 of the 11 courses.
That one-sidedness is GONE. Once BOTH ends were moved onto the feature polygons the residual became
two-sided: measured 2026-08-01, corpus median +0.00 ft, positive on 94 of 171 holes, significant on
none of the eleven. Most of what this paragraph attributed to the coarser reference was our own
sampling region, and the paragraph is kept only as the record of that.
The run now prints the signed bias for that reason. It is evidence about the REFERENCE, not a fault in
the figures being checked, which is why a NEGATIVE bias would be the interesting result -- and it would
have been invisible.

It also reports the ABSOLUTE agreement, which costs no extra network and closes a gap the
cross-flight repeatability check explicitly cannot: that check compares our processing to ITSELF
(two surveys, both gridded by us), so a constant offset introduced by our own handling -- a vertical
unit read wrong, a CRS or grid misalignment, a geoid/ellipsoid mixup -- cancels out of every height
CHANGE and stays invisible. Comparing a green's absolute elevation against a raster this project does
not build catches exactly that class. Measured over 171 greens across all 11 courses: worst per-course median 0.10 m,
worst 0.47 m. A US-survey-foot cloud read as metres would show tens of metres here, a geoid confusion
about 30 m in California, and the foot/metre fault above showed a median 298 ft. What this still does
NOT bound is the source program's own datum or a turfgrass ground-classification bias, since the
seamless DEM comes from the same LiDAR -- recorded as still open in legal/09.

That spread is also what justifies the card's 3 ft floor: below it, two honest sources disagree by
enough that a printed "green 2 ft above" would be inside the gap between them (see elev_phrase in
generate.py).

It is a TOOL, not a unit test, because it needs the network. Run it when a course is added or the
elevation code changes.

Exit codes:  0 all figures agree within tolerance
             1 at least one figure disagrees -- suspect units, datum, or the wrong tee
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

R_LAT = 111320.0
SAMPLE_HALF_M = 15.0        # fallback box, for a tee with no mapped ring. NOT "the same box
# fetch_hole_elev samples at the tee" -- that comment was false on 5 of 11 courses, because TEE_R_M was
# applied in raw CRS units there and so described a 9.1 m box, not a 30 m one. Both sides now sample the
# same REGIONS: the green polygon and the mapped tee pad. Sampling a box against a polygon made this
# tool's disagreement a measure of the region difference rather than of the data.
# A 1 m raster smooths a raised tee platform down, so it reads slightly BELOW the point cloud there:
# measured -1.6 ft at monarch-bay's tees. The change carries that through, so residuals cluster a foot
# or two positive. 10 ft is comfortably above the worst observed (3.14 ft, bay-view 16) and far below the hundreds of
# feet a unit fault produces -- this bound is meant to separate those two, not to audit the last foot.
TOL_FT = 10.0
RETRIES = 5


def _mlon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def dem_median_over_ring(ring, px=64):
    """Median 3DEP elevation in metres over a lat/lon RING's interior, or None.

    Fetches the ring's bounding box and masks to the interior, so the reference measures the same ground
    the pipeline does. Without this the check compared a 3DEP box against our polygon, and the region
    mismatch dominated: a green is usually a raised pad, so a box that reaches 12 m past it reads low, and
    the residual that produced was previously written off in this file's own comment as a property of the
    1 m raster smoothing a tee platform down.
    """
    import fetch_hole_elev as fhe          # course-bound, so imported here rather than at module scope
    rla, rlo = ring
    la0 = float(np.mean(rla))
    pad = 1.0 / R_LAT                                  # a metre of margin so edge pixels exist
    s, n = float(rla.min()) - pad, float(rla.max()) + pad
    w, e = float(rlo.min()) - pad/math.cos(math.radians(la0)), float(rlo.max()) + pad/math.cos(math.radians(la0))
    a = _fetch_patch(w, s, e, n, px)
    if a is None:
        return None
    H, W = a.shape
    # pixel centres -> lat/lon -> inside test, in a local metric frame
    lons = w + (np.arange(W) + 0.5) / W * (e - w)
    lats = n - (np.arange(H) + 0.5) / H * (n - s)
    LO, LA = np.meshgrid(lons, lats)
    k = _mlon(la0)
    inside = fhe._mask_in_ring((LO*k).ravel(), (LA*R_LAT).ravel(), rlo*k, rla*R_LAT).reshape(H, W)
    vals = a[inside & np.isfinite(a)]
    if vals.size == 0:
        return None
    return float(np.median(vals))


def _fetch_patch(w, s, e, n, px):
    """3DEP seamless elevation over a lat/lon bbox as a float array, or None.

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
    except Exception:
        return None
    a[~np.isfinite(a)] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return None
    if float(fin.max() - fin.min()) == 0.0:
        return None                     # constant raster: off the edge of 3DEP, not a reading
    return a


def dem_median_m(lat, lon, half_m=SAMPLE_HALF_M, px=48):
    """Median 3DEP elevation in metres over a box about (lat, lon), or None. The FALLBACK sampler, for
    a tee anchor no mapped ring contains -- the ring sampler above is what the greens and mapped tees
    use, so both sides of the comparison measure the same region."""
    dlat = half_m / R_LAT
    dlon = half_m / _mlon(lat)
    a = _fetch_patch(lon-dlon, lat-dlat, lon+dlon, lat+dlat, px)
    if a is None:
        return None
    return float(np.median(a[np.isfinite(a)]))


def check_course(slug):
    """(status, n_checked, worst_diff_ft, worst_hole). status: 'ok' | 'bad' | 'skip'."""
    for m in ("config", "render_hole", "render_green", "fetch_hole_elev"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config                                    # noqa: E402
    import geo                                       # noqa: E402
    import fetch_hole_elev as fhe                    # noqa: E402

    p = os.path.join(config.COURSE_DIR, "hole_elev.json")
    if not os.path.isfile(p):
        print(f"{slug}: no hole_elev.json -- nothing to verify")
        return "skip", 0, 0.0, None
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
        _meta = json.load(open(meta_p))
        gla, glo = _meta["green_center"]
        # Sample the reference over the SAME regions the pipeline does -- the green polygon and the
        # mapped tee pad -- so what is left is disagreement about the data. See dem_median_over_ring.
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
        # to the green polygon: median 0.00 m, worst 0.80 m. See
        # legal/09_GREEN_SURFACE_REPEATABILITY.md.
        #
        # MASKED, like green_elevation. This took the median of the WHOLE .npy -- the green plus its 12 m
        # collar -- and compared it against a 3DEP median masked to the green polygon, so it measured the
        # region difference the pipeline had just stopped making and reported a spurious +0.127 m offset
        # in the one line whose job is to bound our own processing. It also skipped the >1e30 NoData
        # sentinels that green_elevation strips.
        try:
            _a = np.load(meta_p.replace(".json", ".npy")).astype(float)
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
              f"diff {d:+6.1f}{flag}")
    if not diffs:
        print(f"  could not check any hole ({unreachable} unreachable)")
        return "skip", 0, 0.0, None
    diffs.sort(reverse=True)
    worst, worst_hn = diffs[0][0], diffs[0][1]
    med = float(np.median([d[0] for d in diffs]))
    bad = [d for d in diffs if d[0] > TOL_FT]
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
        tag = ("" if abs(aw) <= 2.0 else
               "  <== a metre or more of ABSOLUTE offset is a processing fault (unit, CRS, datum), "
               "not terrain; see the module docstring")
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
        return "bad", len(diffs), worst, worst_hn
    return "ok", len(diffs), worst, worst_hn


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
            results[s] = ("skip", 0, 0.0, None)
        print()
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
