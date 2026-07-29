#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Shared geodesy helpers.

This module exists because the same two facts were previously derived independently in
fetch_dem_hd.py and fetch_trees.py, and a fix to one had to be hand-applied to the other. A
divergence between them would be silent and serious: both feed the same green surface.
"""
import math

R_LAT = 111320.0                    # metres per degree of latitude (mean)


def mlon(lat):
    """Metres per degree of longitude at a given latitude."""
    return 111320.0 * math.cos(math.radians(lat))


def utm_epsg(lon):
    """NAD83 UTM zone EPSG code for a longitude (26910 = CA zone 10, 26919 = MA zone 19)."""
    return "EPSG:%d" % (26900 + int((lon + 180) / 6) + 1)


def vertical_scale(src):
    """Factor converting the point cloud's Z unit to METRES, from the CRS itself.

    This must never be guessed. It was previously inferred by substring-matching the CRS name for
    "foot"/"ftus", which happens to work when laspy hands back full WKT (all current tiles) but
    fails silently for a bare EPSG code -- and a bare code is exactly what course.json's
    `lidar_crs` override supplies. EPSG:2227 and EPSG:6420 are genuinely US survey foot, yet
    str() gives only "EPSG:2227", so the match missed and Z stayed unscaled: every slope,
    contour and arrow inflated by 3.28x, with nothing to reveal it.

    So ask pyproj for the actual axis unit. Prefer the vertical axis of a compound CRS; fall back
    to the horizontal unit (in a LAS file Z shares the horizontal unit when the CRS is 2D); and
    RAISE rather than assume metres if neither is available -- a loud stop beats a 3.28x error.
    """
    from pyproj import CRS
    try:
        crs = src if hasattr(src, "axis_info") else CRS.from_user_input(src)
    except Exception as e:
        raise SystemExit(f"cannot interpret {src!r} as a CRS ({type(e).__name__}: {e}).\n"
                         f"  Check \"lidar_crs\" in course.json.")

    vert = None
    if getattr(crs, "is_compound", False) and len(crs.sub_crs_list) >= 2:
        vsub = crs.sub_crs_list[-1]                    # the vertical component
        if vsub.axis_info:
            vert = vsub.axis_info[-1]
    if vert is None and crs.axis_info:
        # 2D or unusual: the last axis is vertical on a 3D CRS, otherwise Z follows the horizontal
        vert = crs.axis_info[-1]

    factor = getattr(vert, "unit_conversion_factor", None) if vert is not None else None
    unit = (getattr(vert, "unit_name", "") or "").lower() if vert is not None else ""
    # The unit must be a LENGTH. A geographic CRS reports degrees, whose conversion factor is
    # 0.0174533 (degrees->radians) -- taking that as a vertical scale would shrink every elevation
    # by 57x and look like a nearly flat green rather than an error.
    is_length = any(k in unit for k in ("met", "foot", "feet", "ft", "yard", "chain", "link", "mile"))
    if not factor or factor <= 0 or not is_length:
        raise SystemExit(
            f"cannot determine the vertical LENGTH unit of {crs.name!r} ({src!r}); "
            f"got unit={unit!r} factor={factor!r}.\n"
            f"  Refusing to assume metres: if this cloud is in US survey feet, every slope would be\n"
            f"  printed 3.28x too steep. Set \"lidar_crs\" in course.json to a CRS that carries its\n"
            f"  units (a compound EPSG code or the full WKT), then re-run.")
    return factor
