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
SAMPLE_HALF_M = 15.0        # same box fetch_hole_elev samples at the tee
# A 1 m raster smooths a raised tee platform down, so it reads slightly BELOW the point cloud there:
# measured -1.6 ft at monarch-bay's tees. The change carries that through, so residuals cluster a foot
# or two positive. 10 ft is comfortably above the worst observed (4.9 ft) and far below the hundreds of
# feet a unit fault produces -- this bound is meant to separate those two, not to audit the last foot.
TOL_FT = 10.0
RETRIES = 5


def _mlon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def dem_median_m(lat, lon, half_m=SAMPLE_HALF_M, px=48):
    """Median 3DEP seamless elevation in metres over a box about (lat, lon), or None.

    Returns None rather than raising: an unreachable service must read as "could not check" (exit 2),
    never as agreement. Out of coverage 3DEP hands back a CONSTANT raster instead of an error, so a
    zero-relief patch is reported too -- it means the point is off the edge of the data.
    """
    dlat = half_m / R_LAT
    dlon = half_m / _mlon(lat)
    url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/"
           f"exportImage?bbox={lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
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
    return float(np.median(fin))


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

    print(f"{slug}  (independent check against the 3DEP seamless DEM, tolerance {TOL_FT:g} ft)")
    diffs, unreachable = [], 0
    for hn in sorted(int(k) for k in rec):
        if hn not in holes:
            continue
        la, lo, _basis = fhe.tee_anchor(hn, holes[hn]["geometry"], greens)
        if la is None:
            continue
        meta_p = os.path.join(config.COURSE_DIR, "dem_hd", f"hole{hn:02d}.json")
        if not os.path.isfile(meta_p):
            continue
        gla, glo = json.load(open(meta_p))["green_center"]
        d_tee = dem_median_m(la, lo)
        d_grn = dem_median_m(gla, glo)
        if d_tee is None or d_grn is None:
            print(f"  hole {hn:2d}: DEM unavailable at the tee or the green -- not checked")
            unreachable += 1
            continue
        indep_ft = (d_grn - d_tee) * 3.28084
        ours_ft = rec[str(hn)]["change_ft"]
        d = indep_ft - ours_ft
        diffs.append((abs(d), hn, ours_ft, indep_ft))
        flag = "" if abs(d) <= TOL_FT else "   <== DISAGREES"
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
