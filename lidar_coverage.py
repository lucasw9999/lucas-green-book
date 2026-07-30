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


def _green_rings(course_dir, els=None):
    """[(id, [(lon, lat), ...])] for every green in osm_geom.json."""
    if els is None:
        els = _elements(course_dir)
    return [(e.get("id"), [(q["lon"], q["lat"]) for q in e["geometry"]])
            for e in els
            if e.get("geometry") and (e.get("tags") or {}).get("golf") == "green"]


def _footprint_boxes(course_dir):
    """([(transformer, x0, x1, y0, y1)], reason) -- reason is "" when boxes could be built.

    An empty list is NOT the same as "everything is covered", and conflating the two made this module
    assert something it had not checked: with zero tiles on disk it printed "all 1 green(s) sit inside
    the downloaded tiles' data" and exited 0. Poppy Ridge reaches that path today (it has no LAZ at
    all), as would any course built purely on the 1 m seamless DEM.
    """
    foot = tile_footprints(os.path.join(course_dir, "laz"))
    if not foot:
        return [], "no readable LAZ tiles on disk"
    from pyproj import Transformer

    # Resolve one transformer per tile up front. Doing it inside the point loop meant a to_wkt() and a
    # dict lookup per sampled node per tile -- thousands of calls for no gain, since a course's tiles
    # almost always share a CRS.
    # Group the rectangles BY CRS. Holding a flat list of (transformer, rect) meant _inside
    # re-projected the same node once per tile -- up to 9 scalar pyproj calls per node, the very cost
    # the transformer cache was added to avoid. A course's tiles almost always share one CRS, so this
    # is one projection per node in practice.
    cache, grouped = {}, {}
    for _name, crs, x0, x1, y0, y1 in foot:
        if crs is None:
            continue                       # cannot place anything in a tile with no CRS
        key = crs.to_wkt()
        if key not in cache:
            cache[key] = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        grouped.setdefault(key, (cache[key], []))[1].append((x0, x1, y0, y1))
    boxes = list(grouped.values())
    if not boxes:
        return [], f"{len(foot)} tile(s) on disk but none declares a CRS"
    return boxes, ""


def _inside(boxes, lon, lat):
    """True if (lon, lat) falls in any tile's data footprint. `boxes` is [(transformer, [rects])]."""
    for T, rects in boxes:
        x, y = T.transform(lon, lat)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in rects):
            return True
    return False


def _elements(course_dir):
    """osm_geom.json's element list, or [] if it cannot be read."""
    try:
        with open(os.path.join(course_dir, "osm_geom.json")) as f:
            return json.load(f)["elements"]
    except Exception:
        return []


def uncovered_holes(course_dir, boxes=None, els=None):
    """[(hole_ref, n_outside, n_nodes)] for holes whose centreline leaves the point data.

    The greens check alone is not enough. At Castlewood Hill it flagged holes 14 and 16 but not 15
    and 17, whose centrelines also run through the same gap -- and the centreline is where
    fetch_trees.py looks for canopy returns, so those holes silently lose their trees too. Measured
    across the corpus: 9 of 11 courses have every centreline node inside the data; Castlewood Hill
    has 5 of 52 outside (holes 14, 15, 16, 17) and Monarch Bay 5 of 52 (holes 1, 17, 18, which are
    over the bay).
    """
    if els is None:
        els = _elements(course_dir)
    # Keep only the LONGEST centreline per hole ref, exactly as fetch_dem.py, fetch_dem_hd.py,
    # render_hole.py and fetch_trees.py all do -- OSM carries duplicate and fragment ways where a
    # neighbouring course pokes into the bbox. This was the fifth hole reader and the only one
    # omitting it, so a fragment from next door could be reported as an uncovered hole and a ref
    # could appear twice in the output.
    best = {}
    for e in els:
        if not (e.get("geometry") and (e.get("tags") or {}).get("golf") == "hole"):
            continue
        ref = (e.get("tags") or {}).get("ref")
        if ref and ref.isdigit() and len(e["geometry"]) > len(best.get(ref, {}).get("geometry", [])):
            best[ref] = e
    holes = list(best.values())
    if boxes is None:
        boxes, _why = _footprint_boxes(course_dir)
    if not boxes or not holes:
        return []
    bad = []
    for h in holes:
        nodes = h["geometry"]
        out = sum(1 for q in nodes if not _inside(boxes, q["lon"], q["lat"]))
        if out:
            bad.append(((h.get("tags") or {}).get("ref"), out, len(nodes)))
    return sorted(bad, key=lambda r: int(r[0]) if (r[0] or "").isdigit() else 99)


def uncovered_greens(course_dir, boxes=None, els=None):
    """[(green_id, n_nodes_outside, n_nodes)] for greens the tile data does not fully reach.

    A green's own nodes plus its centroid must each fall inside some tile's data footprint. Sampling
    the green itself rather than its bounding box matters: a bbox corner can sit off the putting
    surface entirely, so a bbox test both misses real gaps and invents fake ones.
    """
    rings = _green_rings(course_dir, els)
    if not rings:
        return []
    if boxes is None:
        boxes, _why = _footprint_boxes(course_dir)
    if not boxes:
        return []
    bad = []
    for gid, ring in rings:
        pts = list(ring)
        pts.append((sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)))
        outside = sum(1 for lon, lat in pts if not _inside(boxes, lon, lat))
        if outside:
            bad.append((gid, outside, len(pts)))
    return bad


def report(course_dir):
    """Print the coverage verdict. Returns (status, uncovered_greens, uncovered_holes).

    status is "checked", or a reason why nothing could be checked. Callers must not read an empty
    green list as "covered" without looking at the status -- that conflation is what let this module
    claim full coverage for a course with no point cloud at all.
    """
    boxes, why = _footprint_boxes(course_dir)
    els = _elements(course_dir)          # parsed ONCE and threaded down, not three times
    rings = _green_rings(course_dir, els)
    if not boxes:
        print(f"  coverage NOT CHECKED: {why}. Greens here are read from the 1 m seamless DEM (or\n"
              f"     not at all); nothing has been verified against a point cloud.")
        return why, [], []
    if not rings:
        print("  coverage NOT CHECKED: no green geometry in osm_geom.json -- run fetch_osm.py first.")
        return "no green geometry", [], []
    holes = uncovered_holes(course_dir, boxes, els)
    if holes:
        n = sum(o for _r, o, _t in holes)
        print(f"  !! {len(holes)} hole(s) have centreline outside the point data "
              f"({n} node(s) total): " + ", ".join(f"h{r}({o}/{t})" for r, o, t in holes))
        print("     Trees along those stretches come from canopy returns and will be missing.")
    bad = uncovered_greens(course_dir, boxes, els)
    if not bad:
        print(f"  coverage: all {len(rings)} green(s) sit inside the downloaded tiles' data "
              f"({sum(len(r) for _T, r in boxes)} tile(s) checked)")
        return "checked", bad, holes
    print(f"  !! {len(bad)} green(s) are NOT fully covered by the point data on disk:")
    for gid, out, tot in bad:
        print(f"       green {gid}: {out} of {tot} sampled node(s) have no returns over them")
    print("     These greens will fall back to the 1 m seamless DEM and their cards will say\n"
          "     '1 m data'. That is honest if the survey truly does not cover them -- bayside\n"
          "     greens over water have no ground returns at all. But check first that a tile copy\n"
          "     is not simply missing: one geographic cell can exist in several sub-projects, each\n"
          "     holding only its own strip, and Castlewood Hill lost two greens' 0.4 m reads that\n"
          "     way. Re-run the fetch; it now keeps every sub-project copy under its own name.")
    return "checked", bad, holes


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    # One call, one answer. main() used to re-run uncovered_holes() for its exit code, which reopened
    # every tile header and left a window where the verdict printed and the code returned could
    # disagree.
    status, bad, holes = report(config.COURSE_DIR)
    if status != "checked":
        return 2          # could not check -- same convention as tools/gen_provenance.py
    # holes count too: a course can have every green covered while a centreline leaves the data, and
    # that is where fetch_trees.py looks for canopy returns
    return 1 if (bad or holes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
