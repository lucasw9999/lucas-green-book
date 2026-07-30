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

# The cost of this local flat-earth model, MEASURED rather than assumed. Comparing every course
# centreline point against a WGS84 geodesic (pyproj) at the radii the book actually prints:
#   100 yd tick -> worst 0.29 yd     200 yd -> 0.60 yd     300 yd -> 0.89 yd
# Under one yard everywhere a tick appears, against club gaps of 10-15 yd, and the labels are
# integers. Using the true meridian radius would shave that but would change every book's output for
# no gain a golfer could act on -- so this is a deliberate, quantified approximation, not an
# oversight. Re-measure before assuming it is still fine if tick radii ever exceed 300 yd (the error
# grows with distance: 1.53 yd at 540 yd).


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


# The furthest a hole's line endpoint legitimately sits from its green's centroid, measured across
# all 198 built greens: worst 11.1 m (philadelphia h12), median 2.0 m. The documented mis-binding --
# bay-view hole 9 attaching to hole 7's green -- was 47.8 m away. 40 m therefore catches that with
# room to spare while clearing the worst real case by 3.6x.
GREEN_BIND_MAX_M = 40.0


def assert_one_green_per_hole(bound, label=""):
    """Refuse if two holes bound to the SAME green. `bound` is {hole_number: green_element}.

    The max_m cap in match_green catches a hole reaching for a FAR green -- bay-view h9 to h7's
    green, 47.8 m -- but it cannot catch the near case, and the near case is the more likely one. If
    a hole's own green disappears from the OSM extract while a neighbour's green sits inside the cap,
    both holes bind there, both cards print that surface, and one of them is a confident read of the
    wrong putting green. Nothing in match_green can see this: it is called once per hole and has no
    view of the others.

    Measured across all 11 built courses: 0 greens are bound to more than one hole today, and the
    furthest legitimate bind is 11.1 m, so this only ever fires on a real fault.
    """
    seen = {}
    clash = []
    for hn in sorted(bound):
        g = bound[hn]
        key = g.get("id", id(g))
        if key in seen:
            clash.append((seen[key], hn, key))
        else:
            seen[key] = hn
    if clash:
        lines = "\n".join(f"    green {k} is bound to BOTH hole {a} and hole {b}"
                           for a, b, k in clash)
        raise SystemExit(
            f"{label or 'this course'}: {len(clash)} green(s) bound to more than one hole.\n"
            f"{lines}\n"
            f"  One of those cards would print a confident read of the wrong putting surface. A\n"
            f"  hole's own green is probably missing from the OSM extract while a neighbour's sits\n"
            f"  inside the {GREEN_BIND_MAX_M:.0f} m bind limit, so the distance cap cannot catch it.\n"
            f"  Re-run fetch_osm.py, or add the missing green (tagged _digitized) before building.")


def match_green(hole_line, greens, max_m=GREEN_BIND_MAX_M, label=""):
    """Bind a hole's centerline to its green: (green, green_end_point, tee_end_point).

    Binds to the NEAREST green to either endpoint, but REFUSES beyond max_m. Without that cap a hole
    whose own green is missing from OSM silently attaches to a neighbour's, and the card then prints a
    confident, correctly-computed read of the WRONG putting surface -- the worst thing this project can
    do. It has happened: bay-view hole 9 bound to hole 7's green, 47.8 m away, when an Overpass reply
    truncated the data.

    Lives here because the same binding was written three times -- fetch_dem_hd.py, fetch_dem.py and
    render_hole.py -- and a cap added to one would have left the others silent. That is the exact
    duplication this module was created to end.
    """
    def near(pt):
        best, bg = 1e9, None
        for g in greens:
            gg = g['geometry']
            gla = sum(p['lat'] for p in gg) / len(gg)
            glo = sum(p['lon'] for p in gg) / len(gg)
            dm = math.hypot((pt['lon'] - glo) * mlon(gla), (pt['lat'] - gla) * R_LAT)
            if dm < best:
                best, bg = dm, g
        return best, bg

    da, ga = near(hole_line[0])
    db, gb = near(hole_line[-1])
    d, g, gend, tend = ((da, ga, hole_line[0], hole_line[-1]) if da <= db
                        else (db, gb, hole_line[-1], hole_line[0]))
    if g is None:
        raise SystemExit(f"no green found to bind {label or 'this hole'} to.")
    if d > max_m:
        raise SystemExit(
            f"{label or 'a hole'}: the nearest green is {d:.0f} m from either end of its centerline,\n"
            f"  beyond the {max_m:.0f} m bind limit. Its own green is probably missing from the OSM\n"
            f"  extract, and binding anyway would print a confident read of the WRONG putting surface.\n"
            f"  Re-run fetch_osm.py, or add the green (tagged _digitized) before building.")
    return g, gend, tend
