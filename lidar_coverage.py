#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Check the LAZ tiles on disk against the greens they are supposed to feed.

Why this exists: nothing verified that a downloaded tile's DATA reaches the greens, and a tile can
be present, correctly named, and still hold no points where a green is. Castlewood Hill shipped
holes 14 and 16 on the 1 m seamless DEM although 0.4 m LiDAR for them exists. Measured:

  both greens fall in grid cell w6153n2055
  the copy on disk (CA_AlamedaCo_1_2021, 30,648,617 bytes) has a DATA footprint of only
      x 6153000..6153470 -- a 470-ft strip of a 3000-ft cell
  the greens sit at x 6155652 and x 6155938, some 2,200-2,500 ft east of that data edge
  the next tile east (w6156n2055) starts at x 6156000, east of both greens
  CA_AlamedaCo_3_2021 holds a 689,926,608-byte copy of the same cell -- 22x larger -- which was
      skipped as "cached" because it shared a filename with the copy already downloaded

So the honest read of those two greens was available and we printed the coarse one instead. The
filename collision is fixed in fetch_lidar.py and fetch_lidar_alameda.py; this module is the check
that would have caught the consequence regardless of the cause.

A green with no returns is NOT an error -- bayside greens over water genuinely have none, and the
1 m fallback plus the card's "1 m data" label is the honest outcome. So this reports rather than
refuses. What it stops is the silent version.

The check uses each tile's HEADER bounding box, which records the extent of the points actually in
the file, not the nominal grid cell -- that distinction is the whole point above.
"""
import glob
import json
import os


def tile_footprints(laz_dir):
    """[(name, crs, x0, x1, y0, y1)] over the tiles on disk, from their headers."""
    import laspy

    out = []
    for p in sorted(glob.glob(os.path.join(laz_dir, "*.laz"))):
        try:
            with laspy.open(p) as f:
                h = f.header
                out.append((os.path.basename(p), h.parse_crs(),
                            h.x_min, h.x_max, h.y_min, h.y_max))
        except Exception as e:
            print(f"  ! could not read {os.path.basename(p)}: {type(e).__name__}")
    return out


def _green_rings(course_dir):
    """[(id, [(lon, lat), ...])] for every green in osm_geom.json."""
    try:
        els = json.load(open(os.path.join(course_dir, "osm_geom.json")))["elements"]
    except Exception:
        return []
    return [(e.get("id"), [(q["lon"], q["lat"]) for q in e["geometry"]])
            for e in els
            if e.get("geometry") and (e.get("tags") or {}).get("golf") == "green"]


def uncovered_greens(course_dir):
    """[(green_id, n_nodes_outside, n_nodes)] for greens the tile data does not fully reach.

    A green's own nodes plus its centroid must each fall inside some tile's data footprint. Sampling
    the green itself rather than its bounding box matters: a bbox corner can sit off the putting
    surface entirely, so a bbox test both misses real gaps and invents fake ones.
    """
    rings = _green_rings(course_dir)
    if not rings:
        return []
    foot = tile_footprints(os.path.join(course_dir, "laz"))
    if not foot:
        return []
    from pyproj import Transformer

    # Resolve one transformer per tile up front. Doing it inside the point loop meant a to_wkt() and a
    # dict lookup per green node per tile -- thousands of calls for no gain, since a course's tiles
    # almost always share a CRS.
    cache, boxes = {}, []
    for _name, crs, x0, x1, y0, y1 in foot:
        if crs is None:
            continue                       # cannot place a green in a tile with no CRS
        key = crs.to_wkt()
        if key not in cache:
            cache[key] = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        boxes.append((cache[key], x0, x1, y0, y1))
    if not boxes:
        print("  ! no tile declares a CRS -- cannot check the greens against the point data")
        return []

    bad = []
    for gid, ring in rings:
        pts = list(ring)
        pts.append((sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)))
        outside = 0
        for lon, lat in pts:
            if not any(x0 <= (xy := T.transform(lon, lat))[0] <= x1 and y0 <= xy[1] <= y1
                       for T, x0, x1, y0, y1 in boxes):
                outside += 1
        if outside:
            bad.append((gid, outside, len(pts)))
    return bad


def report(course_dir):
    """Print the coverage verdict. Returns the uncovered list."""
    bad = uncovered_greens(course_dir)
    if not bad:
        rings = _green_rings(course_dir)
        if rings:
            print(f"  coverage: all {len(rings)} green(s) sit inside the downloaded tiles' data")
        return bad
    print(f"  !! {len(bad)} green(s) are NOT fully covered by the point data on disk:")
    for gid, out, tot in bad:
        print(f"       green {gid}: {out} of {tot} sampled node(s) have no returns over them")
    print("     These greens will fall back to the 1 m seamless DEM and their cards will say\n"
          "     '1 m data'. That is honest if the survey truly does not cover them -- bayside\n"
          "     greens over water have no ground returns at all. But check first that a tile copy\n"
          "     is not simply missing: one geographic cell can exist in several sub-projects, each\n"
          "     holding only its own strip, and Castlewood Hill lost two greens' 0.4 m reads that\n"
          "     way. Re-run the fetch; it now keeps every sub-project copy under its own name.")
    return bad


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    bad = report(config.COURSE_DIR)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
