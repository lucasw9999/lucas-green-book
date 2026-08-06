#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Check the LAZ tiles on disk against the greens they are supposed to feed.

Why this exists: nothing verified that a downloaded tile's DATA reaches the greens, and a tile can
be present, correctly named, and still hold no points where a green is. Castlewood Hill shipped
holes 14 and 16 on the seamless DEM although 0.4 m LiDAR for them exists. Measured:

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
seamless-mosaic fallback plus the card's coarse-data caveat, which names the source cell measured off
that green's own array, is the honest outcome. So this reports rather than refuses: report() prints a
verdict and returns it, and report_or_exit() -- what both fetchers call -- stops the run on that
verdict until it is acknowledged with ALLOW_COVERAGE_GAPS=1 (or with ALLOW_UNCHECKED_COVERAGE=1 when
nothing could be checked at all). What it stops is the silent version: the fetchers used to call
report() as a bare expression statement and discard every word of it.

The check uses each tile's HEADER bounding box, which records the extent of the points actually in
the file, not the nominal grid cell -- that distinction is the whole point above.

But a header bbox is a RECTANGLE, and the points inside it are not. So this test can only ever prove
a green is outside the data; it cannot prove one is inside it, and a green sitting in a hole within
the rectangle reads as covered. Measured, which is why the wording below no longer claims otherwise:
monarch-bay has SIX greens on the seamless fallback (holes 1, 9, 10, 16, 17, 18) and the bbox
test flags only THREE of them (green ids 689151359, 689151368, 689165026). Holes 9, 10 and 16 --
greens 689151373, 689151348, 689168293 -- fall inside a tile's header rectangle, have no ground
returns under them, and were reported as covered. So the report also cross-checks the surfaces that
were actually built (dem_hd/holeNN.json), because those record what the point data really produced.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo  # noqa: E402

# Acknowledgement keys for report_or_exit(), the shape this project already uses for a waiver that
# lets a KNOWN, REAL loss through (fetch_trees.ALLOW_NO_TREES / ALLOW_TREE_LOSS, fetch_dem's
# OVERWRITE). Two of them, not one, because they answer two different questions -- see
# report_or_exit, and fetch_osm._check_response for what one flag gating two questions cost there.
COVERAGE_GAPS_ACK = "ALLOW_COVERAGE_GAPS"        # the gaps this check found are real and known
UNCHECKED_ACK = "ALLOW_UNCHECKED_COVERAGE"       # build although NOTHING was verified


def _env_on(name):
    """An escape hatch is ON only if it is not an explicit off -- fetch_trees._env_on's rule.

    Parsed this way, NOT for truthiness: bool(os.environ.get(..)) makes ALLOW_COVERAGE_GAPS=0 and
    =false mean YES, and these two waive the only check standing between a green the tiles do not
    reach and a fetch that reports success.

    This is the SEVENTH site in the repo spelling that off-vocabulary (fetch_dem and fetch_dem_hd hold
    it in a module constant, fetch_hole_elev and fetch_trees in an `_env_on` of their own, and
    fetch_trees twice more inline) and it is deliberately not imported from any of them: this module
    must keep importing where laspy and numpy are absent, which is the one case ALLOW_UNCHECKED_COVERAGE
    exists for. What makes six of the seven safe is not a shared home, it is that ONE table drives
    them -- test_overwrite_off_does_not_arm_the_overwrite_path_in_either_surface_stage, which now
    DISCOVERS every module defining `_env_on` rather than listing them, so a copy cannot arrive
    unpinned. The two fetch_trees reads spelled inside function bodies are still unreachable by it.
    """
    return os.environ.get(name, "").lower() not in ("", "0", "false", "no")


def tile_footprints(laz_dir):
    """[(name, crs, x0, x1, y0, y1)] over the tiles on disk, from their headers."""
    try:
        import laspy
    except ImportError:
        # Raising here would surface at the very END of an otherwise successful fetch, after every
        # download. Report and let the caller treat it as "could not check".
        print("  ! laspy is not installed -- cannot read tile headers to check coverage")
        return []

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
    """([(transformer, [(x0, x1, y0, y1), ...])], reason) -- reason is "" when boxes could be built.

    Rectangles are GROUPED BY CRS so a sampled node is projected once per CRS rather than once per
    tile; see _inside.

    An empty list is NOT the same as "everything is covered", and conflating the two made this module
    assert something it had not checked: with zero tiles on disk it printed "all 1 green(s) sit inside
    the downloaded tiles' data" and exited 0. Poppy Ridge reaches that path today (it has no LAZ at
    all), as would any course built purely on the seamless DEM.
    """
    foot = tile_footprints(os.path.join(course_dir, "laz"))
    if not foot:
        return [], "no readable LAZ tiles on disk"
    from pyproj import Transformer

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
    across the corpus: of the 11 courses that have tiles on disk (12 are built; poppy-ridge has no
    LAZ at all, so nothing is checked there), 10 have every centreline node inside the data;
    Castlewood Hill had 5 of 52 outside (holes 14, 15, 16, 17) until its missing tile copy arrived
    and is now 0 of 52; Monarch Bay has 5 of 52 (holes 1, 17, 18, which are over the bay).
    """
    if els is None:
        els = _elements(course_dir)
    # ONE centreline per hole ref, via the shared chooser -- OSM carries duplicate ways where a
    # neighbouring course pokes into the bbox, and at Castlewood two 18-hole courses share the area, so
    # every ref has a twin. This was the fifth hole reader and the only one omitting the dedupe, so a
    # way from next door could be reported as an uncovered hole and a ref could appear twice.
    # The course centre comes from course.json, read here rather than from a module global because this
    # function is deliberately course-agnostic (it takes course_dir).
    _cjp = os.path.join(course_dir, "course.json")
    _loc = (json.load(open(_cjp)).get("location") or {}) if os.path.isfile(_cjp) else {}
    holes = list(geo.hole_lines(els, _loc.get("lat"), _loc.get("lon")).values())
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


def built_surfaces(course_dir):
    """{green_id: meta} for every green surface dem_hd/ actually holds.

    The POPULATION the cross-check in report() is drawn from, and it is NOT the OSM green count.
    That conflation was published: the ratio counted dem_hd metas over `len(rings)`, so monarch-bay
    printed "6 of 20 green(s) did NOT get a surface from the point cloud" against 20 OSM greens and
    18 built surfaces -- rings 689151352 and 1441733934 have no meta at all, so EIGHT of its 20
    greens have no point-cloud surface, and a reader subtracting got 14 where the true number is 12.
    Keyed by green_id, like fell_back(), whose docstring names this mismatch as the reason.
    """
    out = {}
    for p in sorted(glob.glob(os.path.join(course_dir, "dem_hd", "hole*.json"))):
        try:
            with open(p) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue                      # an unreadable meta is not evidence either way
        gid = m.get("green_id")
        if gid is not None:
            out[gid] = m
    return out


def fell_back(course_dir, built=None):
    """{green_id: (hole, why)} for greens whose BUILT surface says the point data did not serve them.

    The bbox test above is a rectangle, so it can prove a green is outside the point data but never
    that it is inside. dem_hd/holeNN.json is the other end of the same question, recorded after the
    fact by the stage that actually read the points: `source` names the seamless DEM when
    fetch_dem.py had to fill the green in, and `insufficient` is set when fetch_dem_hd.py refused its
    own 0.4 m attempt. Either way the LiDAR did not produce a usable surface there.

    This is not a substitute for the bbox check -- it is only available AFTER the surfaces are built,
    while the bbox check runs at fetch time -- but where both exist they must agree, and today they do
    not: monarch-bay records 6 fallback greens against 3 the rectangle flags. Reporting the 3 as if
    they were the whole answer is the silent half of exactly the fault this module was written for.

    Read by green_id rather than by hole number so it can be compared with uncovered_greens(), whose
    unit is the OSM green -- osm_geom.json routinely holds more greens than the course has holes (20
    for 18 at monarch-bay, from a neighbouring practice green inside the bbox).

    `built` is built_surfaces()' answer when the caller has it, so report() reads dem_hd/ once.
    """
    if built is None:
        built = built_surfaces(course_dir)
    out = {}
    for gid, m in built.items():
        src = str(m.get("source") or "")
        if m.get("insufficient"):
            out[gid] = (m.get("hole"), "the 0.4 m attempt was refused as insufficient")
        elif "seamless" in src.lower():
            out[gid] = (m.get("hole"), "built from the seamless DEM, not the point cloud")
    return out


def _unexplained(bad, fb):
    """Green ids the header rectangle vouched for whose BUILT surface says the points never served
    them -- monarch-bay's holes 9, 10 and 16, all three of them today.

    Written once because main() and report_or_exit() both decide on it, and two spellings of "what
    counts as a finding" is how a verdict and an exit code come to disagree.
    """
    flagged = {gid for gid, _o, _t in bad}
    return [gid for gid in fb if gid not in flagged]


def report(course_dir):
    """Print the coverage verdict. Returns (status, uncovered_greens, uncovered_holes, fell_back).

    status is "checked", or a reason why nothing could be checked. Callers must not read an empty
    green list as "covered" without looking at the status -- that conflation is what let this module
    claim full coverage for a course with no point cloud at all. The same goes for the fallback map,
    which is `{}` on every path that checked nothing: dem_hd/ was not read, so it says "not known",
    not "nothing fell back".

    The fallback map is RETURNED rather than left for the caller to go and fetch. main() used to
    re-run fell_back() for its exit code, re-reading every dem_hd/holeNN.json this function had
    already read, eleven lines below a comment saying there was one call and one answer.
    """
    boxes, why = _footprint_boxes(course_dir)
    els = _elements(course_dir)          # parsed ONCE and threaded down, not three times
    rings = _green_rings(course_dir, els)
    if not boxes:
        print(f"  coverage NOT CHECKED: {why}. Greens here are read from the seamless DEM (or\n"
              f"     not at all); nothing has been verified against a point cloud.")
        return why, [], [], {}
    if not rings:
        print("  coverage NOT CHECKED: no green geometry in osm_geom.json -- run fetch_osm.py first.")
        return "no green geometry", [], [], {}
    holes = uncovered_holes(course_dir, boxes, els)
    if holes:
        n = sum(o for _r, o, _t in holes)
        print(f"  !! {len(holes)} hole(s) have centreline outside the point data "
              f"({n} node(s) total): " + ", ".join(f"h{r}({o}/{t})" for r, o, t in holes))
        print("     Trees along those stretches come from canopy returns and will be missing.")
    bad = uncovered_greens(course_dir, boxes, els)
    ntiles = sum(len(r) for _T, r in boxes)
    if not bad:
        # Say what a rectangle can support and no more. This used to read "all N green(s) sit inside
        # the downloaded tiles' DATA", which is a claim about the points; the test behind it is
        # point-in-header-BBOX, and a green in a hole inside that rectangle reads as covered. It is
        # printed for 10 of the 11 courses that have tiles on disk (12 are built; poppy-ridge has no
        # LAZ at all, so it never reaches this line).
        print(f"  coverage: all {len(rings)} green(s) fall inside the downloaded tiles' header\n"
              f"     bounding boxes ({ntiles} tile(s) checked). That is a RECTANGLE per tile, not the\n"
              f"     point data: a green in a gap inside the box cannot be told apart from a covered\n"
              f"     one here. See the dem_hd cross-check below for what the points produced.")
    else:
        print(f"  !! {len(bad)} green(s) are NOT fully covered by the point data on disk:")
        for gid, out, tot in bad:
            print(f"       green {gid}: {out} of {tot} sampled node(s) have no returns over them")
        print("     These greens will fall back to the 3DEP seamless mosaic and their cards will carry\n"
              "     a coarse-data caveat naming the source cell measured off their own arrays. That is\n"
              "     honest if the survey truly does not cover them -- bayside\n"
              "     greens over water have no ground returns at all. But check first that a tile copy\n"
              "     is not simply missing: one geographic cell can exist in several sub-projects, each\n"
              "     holding only its own strip, and Castlewood Hill lost two greens' 0.4 m reads that\n"
              "     way. Re-run the fetch; it now keeps every sub-project copy under its own name.")
    # CROSS-CHECK against the surfaces actually built, which is the only evidence that answers the
    # question the rectangle cannot. See fell_back(): monarch-bay has 6 greens on the seamless fallback
    # and the rectangle flags 3, so the three it misses (holes 9, 10 and 16) were reported covered.
    # COUNTED AGAINST THE SURFACES, not against len(rings): the numerator is dem_hd metas, so the
    # denominator has to be too. See built_surfaces() for the figures that mismatch published.
    built = built_surfaces(course_dir)
    fb = fell_back(course_dir, built)
    if fb:
        unexplained = set(_unexplained(bad, fb))
        missed = sorted((hole, gid, whyfb) for gid, (hole, whyfb) in fb.items()
                        if gid in unexplained)
        print(f"  dem_hd cross-check: {len(fb)} of {len(built)} built green surface(s) did NOT "
              f"come from the point cloud")
        for hole, gid, whyfb in missed:
            print(f"       hole {hole} (green {gid}): inside a tile's header bbox, yet {whyfb}")
        if missed:
            print(f"     So the bbox test above accounts for {len(fb) - len(missed)} of the {len(fb)}; "
                  f"the other {len(missed)} sit in a hole INSIDE a tile's rectangle.\n"
                  f"     Their cards print the coarse-data caveat, which is honest -- but the rectangle\n"
                  f"     is not evidence that the survey reaches them, so do not read a clean bbox\n"
                  f"     report as one. Check whether a sub-project copy of their cell is missing.")
    elif built:
        print(f"  dem_hd cross-check: all {len(built)} built green surface(s) came from the point "
              f"cloud")
    elif os.path.isdir(os.path.join(course_dir, "dem_hd")):
        # An empty dem_hd/ used to reach the line above and print "every built green surface came
        # from the point cloud" over a population of none, which is a claim about nothing.
        print("  dem_hd cross-check: dem_hd/ holds no green surface to cross-check")
    return "checked", bad, holes, fb


def report_or_exit(course_dir):
    """report(), then STOP the run unless the verdict is clean or explicitly acknowledged.

    Both fetchers used to call report() as a BARE EXPRESSION STATEMENT and discard all of it, so a
    fetch ending

        !! 1 green(s) are NOT fully covered by the point data on disk

    exited 0, and so did one ending "coverage NOT CHECKED: no readable LAZ tiles on disk". main()
    has mapped those two verdicts to exit 1 and exit 2 since this module was written -- standalone on
    the same data, monarch-bay exits 1, poppy-ridge 2, bay-view 0 -- and nothing carried it to the
    caller. PIPELINE.md titles that sequence "Add a NEW course (what an agent does each time)", so an
    agent gating on the fetch step's exit code read a coverage gap as success.

    KEYED, not unconditional, and that is load-bearing. Reporting rather than refusing is still this
    module's stance for a green that genuinely has no returns: monarch-bay's holes 1, 17 and 18 are
    permanently over San Francisco Bay, so its verdict will never be clean, and an unconditional
    non-zero would wedge that course's re-fetch forever. So each verdict names the key that clears
    it, the shape fetch_trees (ALLOW_NO_TREES / ALLOW_TREE_LOSS) and fetch_dem (OVERWRITE) already use.

    TWO keys, because they are two different questions and fetch_osm._check_response records what
    one flag gating two questions costs. ALLOW_COVERAGE_GAPS says "these gaps are real and I have read
    them"; ALLOW_UNCHECKED_COVERAGE says "build although NOTHING was verified", which is where a
    missing laspy lands. Monarch Bay needs the first set forever, so it must not silence the second.

    Cheap to obey: the tiles are already on disk when this runs, so re-running with the key set
    finds every copy cached.
    """
    status, bad, holes, fb = report(course_dir)
    if status != "checked":
        if not _env_on(UNCHECKED_ACK):
            raise SystemExit(
                f"coverage was NOT CHECKED ({status}), so nothing on disk has been verified\n"
                f"  against a point cloud. A green the tiles do not reach falls back to the 3DEP\n"
                f"  seamless mosaic, and this check is the only thing that would have said so.\n"
                f"  Install the tile reader (laspy, see requirements.txt) or confirm the tiles are\n"
                f"  where they should be, then re-run -- every copy is cached, so it costs nothing.\n"
                f"  Set {UNCHECKED_ACK}=1 to build with no coverage check on purpose.")
        print(f"WARNING: {UNCHECKED_ACK} set -- building with no coverage check at all ({status})")
        return status, bad, holes, fb
    unexplained = _unexplained(bad, fb)
    if bad or holes or unexplained:
        if not _env_on(COVERAGE_GAPS_ACK):
            raise SystemExit(
                f"the coverage verdict above is not clean: {len(bad)} green(s) outside the tiles'\n"
                f"  header boxes, {len(holes)} hole centreline(s) outside them, and "
                f"{len(unexplained)} green(s) the\n"
                f"  boxes vouched for whose BUILT surface came from the seamless mosaic. Each of\n"
                f"  those greens carries the coarse-data caveat naming the source cell measured off\n"
                f"  its own array, and each of those holes loses the canopy returns its trees are\n"
                f"  drawn from -- honest outcomes, and silent ones when this verdict is discarded.\n"
                f"  Check first that a sub-project copy of a cell is not simply missing; Castlewood\n"
                f"  Hill lost two greens' 0.4 m reads that way.\n"
                f"  Set {COVERAGE_GAPS_ACK}=1 once you have read the verdict and the gaps are real\n"
                f"  -- monarch-bay's holes 1, 17 and 18 are permanently over the bay, so that course\n"
                f"  needs it every time.")
        print(f"WARNING: {COVERAGE_GAPS_ACK} set -- {len(bad)} uncovered green(s), {len(holes)} "
              f"uncovered hole(s) and {len(unexplained)} fallback green(s) accepted as real gaps")
    return status, bad, holes, fb


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    # One call, one answer -- and the answer now includes the dem_hd fallback set. main() used to
    # re-run uncovered_holes() for its exit code, which reopened every tile header; the replacement
    # still re-ran fell_back() eleven lines below this comment, re-reading every dem_hd/holeNN.json
    # report() had just read. Two calls and two answers, under a note claiming one.
    status, bad, holes, fb = report(config.COURSE_DIR)
    if status != "checked":
        return 2          # could not check -- same convention as tools/gen_provenance.py
    # holes count too: a course can have every green covered while a centreline leaves the data, and
    # that is where fetch_trees.py looks for canopy returns. So does a green the BBOX vouches for that
    # the built surface says fell back to the seamless DEM -- returning 0 for that was the under-report
    # this module's whole purpose forbids (monarch-bay: 6 fallback greens, 3 flagged).
    return 1 if (bad or holes or _unexplained(bad, fb)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
