#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Extract TREES from the LiDAR point cloud for a course, so trees appear at real
locations even where OpenStreetMap has none.

NOT from a vegetation classification. 10 of the 11 courses with tiles have ZERO
class-5 (high vegetation) points -- their tiles are unclassified, class 1 + 2 only
-- so a marker is any return 2.5-35 m ABOVE LOCAL GROUND that is not classified
ground, building, noise, water or bridge deck. See the comment at the candidate
filter; do not "restore" a class-5 filter, it would empty the tree layer on almost
every course.

What that means for what is drawn: this finds TALL THINGS, and cannot tell a tree
from a hedge, a light pole, netting or a flagstick. On a golf corridor tall things
are overwhelmingly trees, and the two systematic false positives are handled --
buildings by footprint, and anything standing on a playing surface (mower, cart,
person, flagstick) by on_playing_surface() below. No species, height or canopy
validation is claimed beyond that.

Reads COURSE_DIR/laz/*.laz + osm_geom.json (hole centerlines), keeps candidate
points within a corridor of each hole, thins them to a grid so each clump gives a
few markers, and writes COURSE_DIR/trees_lidar.json = {hole: [[lat,lon],...]}.

Run:  COURSE=<slug> python3 fetch_trees.py
"""
import glob, os, json, math
import numpy as np, laspy
from pyproj import Transformer
import config
import geo
from lidar_coverage import _env_on   # the project's ONE reading of an escape-hatch key -- see it there

DIR = config.COURSE_DIR
# NAD83 UTM zone chosen from the course longitude (26910 = CA zone 10, 26919 = MA zone 19)
# No default. A course.json without "location" used to fall back to -121.0, i.e. silently pick
# California UTM zone 10 -- for a Pennsylvania course (zone 18) every tree would be projected
# through the wrong zone, and nothing would say so.
#
# The zone FORMULA is geo.utm_epsg's, not a copy of it. This line used to spell
# `"EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)` and so did fetch_dem_hd.py, byte for byte, while
# geo.utm_epsg -- added by d2b0d10 (2026-07-29) to be the one home for exactly this fact -- had no
# callers at all. That commit's message describes geo.py as the shared home for "the same two facts ...
# previously derived independently in fetch_dem_hd.py and fetch_trees.py", the vertical unit and the UTM
# zone; it wired both files to geo.vertical_scale and left the zone behind, so the migration was never
# finished. geo.py's own docstring says this duplication-drift hazard has already cost this project two
# audits (the nine-module R_LAT saga), and the zone decides which projection every tree position is
# computed through.
_LOC = config.COURSE.get("location") or {}
if not isinstance(_LOC, dict) or _LOC.get("lon") is None:
    raise SystemExit('course.json needs "location": {"lat": .., "lon": ..} -- it selects the UTM '
                     'zone for every tree position. Refusing to guess one.')
_LON = _LOC["lon"]
UTM = geo.utm_epsg(_LON)
FWD = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)   # lon/lat -> UTM m
INV = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)

GC = 4.0        # ground-grid cell (m) for height-above-ground. At module scope because the grid this
                # sizes is what every marker's height is measured against, and ground_grid() below is
                # graded on its own rather than through a whole run.

# THE WIDEST SPAN THIS STAGE WILL EVER GRID FOR ONE TILE, in metres of the course's UTM zone.
#
# The grid below is sized from the coordinates of the tile's own ground returns, and that number has to
# have a ceiling. Two of them, in fact, because the two failures are different:
#
#   * a stray coordinate INSIDE an honest tile -- caught by construction, by clipping the points to the
#     tile's own header extent before anything measures them (see in_header_bbox). A point outside the
#     tile's own stated bbox is by definition not a point this stage may use.
#   * a header that itself claims the junk -- nothing inside the file then contradicts it, so the clip
#     above bounds the grid by an absurd extent. That is what this constant refuses, BY NAME.
#
# 10 km is chosen against what the corpus is. Measured over all 78 tiles on disk: 41 carry US survey
# feet in their header (914.4 m at the widest), 4 carry 1499.99 m, and 33 carry 1000.0 m. Of the 41
# ftUS tiles, 24 span exactly 2999.99 ftUS, 9 span exactly 2499.999 ftUS, and the remaining 8 are edge
# tiles narrower than that in at least one axis -- a mapped delivery tiles its coverage on a fixed
# grid, and the courses near the edge of that grid get a shorter tile in whichever axis runs off it.
# So the widest tile here is 1500 m and the largest bare-earth grid any stored tile can produce is
# 376 x 376 cells, 1.08 MiB. A 10 km ceiling is 6.7x wider in each axis than that and costs 47.8 MiB if
# a real delivery ever ships tiles that big, while the unbounded arithmetic it replaces reached 466 GiB
# from a single junk coordinate.
GRID_SPAN_MAX_M = 10_000.0

def laz_to_utm():
    """Transformer from the tiles' native CRS -> the course's UTM zone (metres) + vertical scale to m."""
    src = config.COURSE.get("lidar_crs")
    if not src:
        for t in sorted(glob.glob(f"{DIR}/laz/*.laz")):
            try:
                with laspy.open(t) as f:
                    src = f.header.parse_crs()
                    if src:
                        break
            except Exception:
                pass
    if src is None:
        # Assuming the tiles are already in the course's UTM zone with metres for Z is exactly the
        # guess geo.vertical_scale exists to prevent: a US-survey-foot cloud would go unscaled and
        # every slope, contour and arrow would print 3.28x too steep, with nothing to reveal it.
        raise SystemExit(
            "no CRS in any LAZ tile and no \"lidar_crs\" in course.json.\n"
            "  Refusing to assume the cloud is already in %s with metres for Z: if it is in US\n"
            "  survey feet, every slope would print 3.28x too steep. Set \"lidar_crs\" to a CRS\n"
            "  that carries its units (a compound EPSG code or full WKT), then re-run." % UTM)
    # vertical unit from the CRS axis, never guessed from its name (see geo.vertical_scale)
    return Transformer.from_crs(src, UTM, always_xy=True), geo.vertical_scale(src)


def _dem_hd():
    """fetch_dem_hd, imported LAZILY -- for its producer-disowned point filter, nothing else.

    That module is the one place in this project that knows how to ask a LAS file which of its points
    the vendor marked DO NOT USE, and it applies that filter to THE SAME TILES this stage reads. A
    second copy of the flag names and the getattr dance here is a second thing to keep in step, and its
    own comment already says why it exists: "so the next course's tiles cannot quietly contribute
    rejected points to a green."

    Lazily, because importing it creates COURSE_DIR/dem_hd and sweeps that directory's staging files at
    IMPORT time. That is the green-surface stage's business, not a tree fetch's, so the import happens
    past main()'s "no LAZ tiles" refusal instead -- i.e. only on a course that has a point cloud, and so
    already has a dem_hd/. (tools/cross_flight_check.py imports it from inside a function for the
    neighbouring reason: to keep config binding out of module scope.)
    """
    import fetch_dem_hd
    return fetch_dem_hd


def disowned_tally():
    """A fresh {flag: counts} in fetch_dem_hd's own shape, so its format_disowned_report can print it.

    The shape is shared for the same reason the filter is: "ran on 78 of 78 tiles, 0 ground point(s)
    dropped" and "DID NOT RUN on 78 of 78 tiles" are the two readings a silent filter makes identical,
    and that sentence is already written -- once -- over there.
    """
    fdh = _dem_hd()
    return {f: {fdh.FILTER_APPLIED: 0, fdh.FILTER_UNAVAILABLE: 0, "flagged": 0, "dropped": 0}
            for f in fdh.DISOWNED_FLAGS}


def in_header_bbox(las):
    """Mask of the points inside the tile's OWN header extent, in the tile's native units.

    THE CEILING ON THE GRID, by construction. Everything downstream measured the span of the class-2
    returns straight off the data -- `nx = int((x[gnd].max() - gx0) / GC) + 2` -- so ONE junk
    coordinate sized the whole allocation by itself. Measured on a 540 x 240 m fixture plus one stray
    class-2 return: 9.2 MiB at 4 km out, 1.76 GiB at 61 km, 4.69 GiB at 100 km, 466 GiB at 1000 km,
    which is a MemoryError or an exit-137 OOM kill with no traceback and nothing naming the tile.

    pyproj is why nothing upstream catches it: for the five courses whose tiles are reprojected
    EPSG:6419 -> EPSG:26910 a garbage native coordinate comes back FINITE, so the arithmetic succeeds
    and the allocation is the first thing that fails.

    A point outside the tile's own header bbox is by definition not a point this stage may use, so the
    honest fix is to drop it before anything measures it -- the same treatment tools/lidar_dates.py
    gives its MASS_BUCKETS window, and for the same reason ("one junk gps_time ... sized the allocation
    by itself"). Compared in NATIVE units, against the header the producer wrote, because that is the
    only statement of what this tile IS; a reprojected garbage coordinate is indistinguishable from a
    real one.

    LATENT on this corpus, measured: over all 78 tiles on disk not one point lies outside its own tile's
    header bbox (0 of 2,479,193,850), and the widest tile is 1500 m across. This drops nothing today.
    """
    h = las.header
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    return (x >= h.x_min) & (x <= h.x_max) & (y >= h.y_min) & (y <= h.y_max)


def tile_points(las, pt2utm, zscale, label="", tally=None):
    """(cls, x, y, z, gnd) for ONE tile: XY in the course's UTM metres, Z in metres, `gnd` = usable ground.

    Two prefilters, and they are deliberately not the same shape:

      * EVERY point is clipped to the tile's own header extent (see in_header_bbox). This bounds the
        grid, and it is applied to the candidate returns too -- a coordinate the tile disowns is not a
        tree either, and the candidates are indexed into the grid with np.clip, so a stray one would be
        folded onto an edge cell and measured against ground it is nowhere near.
      * `gnd` additionally excludes the returns the PRODUCER disowns. Only the ground returns, which is
        what fetch_dem_hd does over these same tiles. Measured over all 78 tiles (2,479,193,850
        points): `withheld` resolves on 78 of 78 and marks 19,979,730 points, `synthetic` marks none,
        and ZERO of the withheld points are class-2 -- so this changes no stored tree layer. It matters
        because the bare-earth grid is what every marker's height-above-ground is measured against, so
        one disowned ground return either invents a marker or deletes one, and the markers are drawn on
        the hole maps.
        NOT extended to the candidates: 17,376,591 of the withheld points ARE candidates across this
        corpus, so filtering them would move drawn ink on shipped cards. That is a change to make
        deliberately and measure, not one to smuggle in beside a fix.
    """
    fdh = _dem_hd()
    keep = in_header_bbox(las)
    n_out = int(keep.size - keep.sum())
    if n_out:
        h = las.header
        print(f"  {label}: dropping {n_out:,} point(s) outside this tile's own header extent "
              f"[{h.x_min:.2f},{h.x_max:.2f}] x [{h.y_min:.2f},{h.y_max:.2f}] (native units) -- "
              f"they are not points this stage may use, and one of them can size the ground grid")
    cls = np.asarray(las.classification)[keep]
    x, y = pt2utm.transform(np.asarray(las.x)[keep], np.asarray(las.y)[keep])
    z = np.asarray(las.z)[keep] * zscale
    gnd = cls == 2
    for flag in fdh.DISOWNED_FLAGS:
        bad, status = fdh.disowned_mask(las, flag)
        if tally is not None and flag in tally:
            tally[flag][status] = tally[flag].get(status, 0) + 1
        if bad is None:
            continue                       # no such bit in this point format; the tally reports it
        bad = bad[keep]
        if tally is not None and flag in tally:
            tally[flag]["flagged"] += int(bad.sum())
        n_drop = int((gnd & bad).sum())
        if n_drop:
            if tally is not None and flag in tally:
                tally[flag]["dropped"] += n_drop
            print(f"  {label}: dropping {n_drop:,} ground point(s) flagged {flag}")
        gnd = gnd & ~bad
    return cls, x, y, z, gnd


def ground_grid(gx, gy, gz, label=""):
    """(grd, gx0, gy0) -- min ground z per GC-metre cell, over the GROUND returns handed in.

    `grd` is np.inf where no ground return landed, which is what makes an unmeasured cell produce a
    non-finite height rather than a confident one.

    The span is refused rather than allocated when it is wider than one tile can be. Reaching here with
    such a span means the tile's HEADER claims it -- tile_points has already clipped the points to that
    header -- so nothing inside the file contradicts it and there is no honest grid to build. The
    refusal names the tile because the failure this replaces was an exit-137 over a directory of 78 of
    them, with no traceback and nothing saying which.
    """
    gx0, gy0 = gx.min(), gy.min()
    spanx, spany = float(gx.max() - gx0), float(gy.max() - gy0)
    if not (spanx <= GRID_SPAN_MAX_M and spany <= GRID_SPAN_MAX_M):
        raise SystemExit(
            f"REFUSING to grid {label or 'this tile'}: its ground returns span "
            f"{spanx:,.0f} x {spany:,.0f} m, over the {GRID_SPAN_MAX_M:,.0f} m one tile may cover.\n"
            f"  The points have already been clipped to the tile's own header extent, so the HEADER\n"
            f"  claims this span -- either the file is corrupt or \"lidar_crs\" is projecting it\n"
            f"  through the wrong CRS. A {GC:.0f} m grid over that is "
            f"{(spanx / GC + 2) * (spany / GC + 2) * 8 / 2 ** 30:,.1f} GiB, which is an OOM kill and\n"
            f"  not an error message. Fix or remove the tile.")
    nx = int(spanx / GC) + 2
    ny = int(spany / GC) + 2
    grd = np.full((nx, ny), np.inf)
    gi = ((gx - gx0) / GC).astype(int)
    gj = ((gy - gy0) / GC).astype(int)
    np.minimum.at(grd, (gi, gj), gz)
    return grd, gx0, gy0

def dist_pt_seg(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay; L2=dx*dx+dy*dy
    if L2<1e-9: return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/L2)); return math.hypot(px-(ax+t*dx),py-(ay+t*dy))

def _pip(x, y, poly):
    """point-in-polygon (ray cast); poly is a list of (lon,lat)."""
    inside=False; n=len(poly); j=n-1
    for i in range(n):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>y)!=(yj>y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-15)+xi):
            inside=not inside
        j=i
    return inside

def load_playing_surfaces():
    """Polygons where a tree marker must be a false positive, with bboxes:
      * fairway / green / tee / bunker -- trees never grow on a playing surface, so a marker
        there is an edge-tree clipped in or a non-vegetation elevated return (cart, mower,
        person, flagstick).
      * BUILDINGS -- a roof is 2.5-35 m above ground and reads exactly like canopy. On tiles
        that carry class 6 we drop those points upstream, but most of our tiles are
        unclassified, so a clubhouse roof arrives as class 1 and only its FOOTPRINT can
        identify it (53 markers sat on Merion's clubhouse before this)."""
    els=[]; seen=set()
    for fn in ("osm_course.json","osm_geom.json"):
        p=f"{DIR}/{fn}"
        if os.path.exists(p):
            j=json.load(open(p))
            for e in (j.get("elements",j) if isinstance(j,dict) else j):
                # the two files overlap (greens appear in both), so de-dup by id or the polygon
                # itself -- otherwise the same green is tested twice and the log over-counts.
                k=e.get('id') if e.get('id') is not None else id(e)
                if k in seen: continue
                seen.add(k); els.append(e)
    surfaces=[]
    for e in els:
        t=e.get('tags',{})
        # WATER belongs here. The filter caught golf surfaces and buildings -- and it catches those
        # perfectly, zero markers land on either across all 11 courses -- but not ponds, so canopy height
        # measured over open water was drawn as trees. 535 of the 68,884 markers shipping BEFORE this
        # filter sat inside a mapped water polygon, 151 more than 5 m from the bank and 40 more than
        # 10 m in; the worst is 22.0 m inside a pond on the-reserve 2, a card that draws that water in
        # its own footer ("5B 2W") with 339 tree dots on top of it. A tree standing in a pond is the
        # same defect class as the 1,107 markers once drawn on roofs, 53 of them on Merion's clubhouse.
        # (68,884 is the PRE-filter population, quoted so the removals have a denominator. What the
        # corpus stores today is 68,257 -- the same set less the 615 this filter and its sibling below
        # take out, and less 12 more that only became visible when castlewood-hill's and
        # castlewood-valley's osm_bbox were widened to cover the drawing corridor on 2026-08-04: this
        # filter cannot exclude a house or a tee the OSM fetch never asked for. See
        # tools/check_osm_bbox.py.)
        is_surface = (t.get('golf') in ('fairway','green','tee','bunker')
                      or t.get('building') not in (None, 'no')
                      or t.get('natural') == 'water'
                      or t.get('landuse') in ('reservoir', 'basin'))
        if is_surface and e.get('geometry'):
            poly=[(p['lon'],p['lat']) for p in e['geometry']]
            xs=[c[0] for c in poly]; ys=[c[1] for c in poly]
            # building='no' means NOT a building -- must not be treated as a surface at all
            kind = ('building' if t.get('building') not in (None,'no')
                    else 'water' if (t.get('natural') == 'water'
                                     or t.get('landuse') in ('reservoir','basin'))
                    else 'golf')
            surfaces.append((min(xs),min(ys),max(xs),max(ys),poly,kind))
    return surfaces

# A hole must have held at least this many markers before losing all of them counts as a LOSS rather
# than churn. Same floor and same reason as fetch_osm._check_response's `oc[k] < 4` skip: a corridor
# with one or two markers is a filter edge case, while the failures this has to catch take a hole from
# tens or hundreds to zero.
# Re-measured over the eleven stored layers. monarch-bay's three survey-edge holes -- 1, 17 and 18 --
# are the corpus's only zeros, and
#   the smallest per-hole count above them is 16, on monarch-bay 16 (then 19, on monarch-bay 7),
#   and outside monarch-bay entirely it is 47, on philadelphia 11.
# So a floor of 4 still sits clear of every real corridor. This was published as 15, a figure that
# reproduces on no hole of any course.
TREE_HOLE_FLOOR = 4


def _stored_layer(path):
    """{hole: marker count} for the tree layer already on disk; {} when there is none to compare against.

    An unreadable file is treated as no baseline rather than a hard stop, which is the opposite of
    fetch_osm._digitized_of's rule and deliberately so: nothing in trees_lidar.json is hand-made, this
    run is regenerating the whole file from the tiles, and the zero-total guard below still applies. The
    counts are all that is needed -- the guard asks "did a hole that had canopy lose it", never what the
    coordinates were.
    """
    if not os.path.exists(path):
        return {}
    try:
        j = json.load(open(path))
    except Exception:
        return {}
    if not isinstance(j, dict):
        return {}
    return {str(k): len(v) for k, v in j.items() if isinstance(v, list)}


def check_layer(out, path):
    """Refuse to commit a tree layer that has LOST the canopy the stored one recorded.

    Two different questions, so two different waivers -- the distinction fetch_osm._check_response
    records the hard way, where one flag gated both a churned tree node and the loss of a green:

      * ALLOW_NO_TREES  -- this layer has no markers at all. A re-run returns zero for reasons that
        have nothing to do with the trees: a wrong "lidar_crs" projects every point out of its
        corridor, an osm_geom.json that lost its golf=hole ways leaves the corridor list empty, a tile
        with no class-2 return is skipped. None of those is "this course has no trees", and the
        difference is invisible downstream -- render_hole._lidar_trees() hard-stops on a MISSING file
        when the course has tiles, but an EMPTY one parses, generate._book_draws_trees() then finds no
        hole that drew a mark of either kind and drops the per-card "no tree data" caveat as noise, and
        gen_provenance reports bare holes only
        `if tl and any(tl.values())`. So the one state nothing reports is the one that reports nothing.
        (That reader used to be called generate._course_has_trees; 6325af0 replaced it because it keyed
        the caveat on the LiDAR marker list while render_hole FALLS BACK to OSM tree nodes. The
        successor asks what each hole DREW, so on a course that has OSM trees an empty layer now draws
        sparse OSM markers instead of nothing -- the same silence reached a different way.)
      * ALLOW_TREE_LOSS -- some hole that HAD canopy now has none. Checked per hole because the
        aggregate cannot see it: a course can keep 96% of its markers while one card goes from
        tree-lined to open ground, and that card is what a golfer aims over.

    The per-hole test is skipped when the layer is empty outright: every hole has then lost its
    markers, that is the same fact the first guard already states, and needing two flags to say it once
    is how a waiver becomes a habit.
    """
    tot = sum(len(v) for v in out.values())
    prev = _stored_layer(path)
    if tot == 0:
        if not _env_on("ALLOW_NO_TREES"):
            raise SystemExit(
                "REFUSING to write an EMPTY tree layer to %s.\n"
                "  Zero markers is not the same claim as 'this course has no trees', and nothing\n"
                "  downstream can tell them apart: the maps draw open ground and no card is marked\n"
                "  \"no tree data\". Check that \"lidar_crs\" is right, that osm_geom.json still holds\n"
                "  golf=hole ways, and that the tiles carry class-2 ground returns.\n"
                "  Set ALLOW_NO_TREES=1 if this course genuinely has none." % path)
        print("WARNING: ALLOW_NO_TREES set -- writing a tree layer with no markers at all; every "
              "hole will draw as open ground")
        return
    lost = sorted(int(h) for h, n in prev.items()
                  if n >= TREE_HOLE_FLOOR and not out.get(h))
    if lost:
        if not _env_on("ALLOW_TREE_LOSS"):
            raise SystemExit(
                "REFUSING to write %s: hole(s) %s had %s markers in the stored layer and this run\n"
                "  found none. Those cards would print open ground where the survey found canopy,\n"
                "  and the \"no tree data\" caveat only appears when SOME hole still has markers.\n"
                "  Set ALLOW_TREE_LOSS=1 if the loss is real (a hole re-routed, or the corridor is\n"
                "  genuinely outside the point data)."
                % (path, ", ".join(str(h) for h in lost),
                   ", ".join(str(prev[str(h)]) for h in lost)))
        print("WARNING: ALLOW_TREE_LOSS set -- hole(s) %s lose every marker they had"
              % ", ".join(str(h) for h in lost))


def write_layer(path, out):
    """Stage the tree layer beside trees_lidar.json and rename it in, sweeping the stage either way.

    The write this replaces was `json.dump(out, open(path, "w"))`, three lines under a comment calling
    check_layer "the last gate before the bytes land". json.dump TRUNCATES the file when it opens it
    and then streams, so a failure part-way through the encode leaves a wreck that is LARGER than the
    layer it replaced, having got as far as the key it choked on -- measured on course.json at 327 bytes
    where 265 were. Tree layers run 126 KB (merion) to 245 KB (valley-hi) and are the only record of the
    canopy; the tiles can rebuild them, but nothing tells the next reader that this file is a wreck
    rather than a survey.

    Nothing DOWNSTREAM told them either, which is why staging this was worth more than tidiness.
    lidar_dates.write_lidar_flown's docstring justified leaving this one write in place by saying a
    truncated layer "fails loudly at render_hole.py's json.load" -- while generate._tree_markers held a
    bare `except Exception: _TREES = {}` around exactly that call, turning the loud failure into zero
    markers everywhere, which then suppressed the per-card "no tree data" caveat as noise and produced a
    clean-looking, tree-free 18-hole book. Both halves are fixed together: the write cannot leave a
    wreck, and the build no longer swallows one.

    The stage is removed on the failure path, and the handle is closed by the `with` rather than by
    refcount. Encoding is named because coordinates are ASCII and saying so removes the locale from the
    question; ensure_ascii keeps it true whatever the machine.
    """
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):     # a no-op once the rename above has happened
            os.remove(tmp)


def on_playing_surface(lon,lat,surfaces):
    """'golf' | 'building' | False -- which kind of surface this marker falls on (counted
    separately, because reporting a building drop as a 'green/fairway/tee/bunker' drop
    overstated that number by 16x on valley-hi)."""
    for x0,y0,x1,y1,poly,kind in surfaces:
        if x0<=lon<=x1 and y0<=lat<=y1 and _pip(lon,lat,poly):
            return kind
    return False


# The two stale-cache guards below were inline in main(), and their escape hatches were read there
# too -- `os.environ.get("ALLOW_NO_BUILDINGS", "").lower() not in (...)` spelled out twice, inside a
# function body. Nothing could reach either one: no test can import a local, so narrowing, removing or
# inverting either flag was invisible. The existing pin table for this repo's off-vocabulary says so in
# its own docstring ("the two inline reads ... are still unreachable ... pinning them needs the read
# routed through fetch_trees._env_on first"), and records that narrowing a copy of that vocabulary to
# ("", "0") -- which makes ALLOW_X=false a WAIVER -- left the whole suite at its baseline.
#
# So: lifted to module scope, and the reads go through _env_on like the other two hatches here. The flag
# names stay LITERAL rather than becoming module constants, because that pin table also requires every
# module-scope ALLOW_* string it finds to be one it drives, and it drives the two check_layer hatches
# only. `_env_on` is now IMPORTED from lidar_coverage rather than spelled here: this module used to hold
# its own copy of the off-vocabulary, and the round that had to add `off` and a `.strip()` to it would
# have had to find all five copies.
def check_buildings(n_bld):
    """Refuse to place tree markers against a cache that carries no building footprints.

    A cache fetched before way[building] was added silently disables the footprint test, and clubhouse
    roofs come back as trees -- 53 of them at Merion. A roof is 2.5-35 m above ground and reads exactly
    like canopy on the unclassified tiles most of this corpus uses, so the FOOTPRINT is the only thing
    that identifies it.
    """
    if n_bld:
        return
    if not _env_on("ALLOW_NO_BUILDINGS"):
        raise SystemExit("no building polygons in osm_course.json -- this cache predates the "
                         "way[building] query, so roofs would be drawn as trees.\n"
                         "  Re-run: COURSE=%s python3 fetch_osm.py   "
                         "(or set ALLOW_NO_BUILDINGS=1 if this course genuinely has none)"
                         % config.SLUG)
    print("WARNING: ALLOW_NO_BUILDINGS set -- building footprint test DISABLED; "
          "roofs may be drawn as trees")


def check_relations(rel_path):
    """Refuse a cache that predates fetch_osm.py's MULTIPOLYGON pass -- the same fault one query deeper.

    A building, pond or fairway mapped as a relation is invisible to a cache that predates that pass, so
    load_playing_surfaces() never sees the footprint and its roof or its open water comes back as canopy.
    That is the identical failure check_buildings exists for (53 markers on Merion's clubhouse; 615 of
    the 68,884 markers shipping before these two filters were inside a mapped pond, worst 22.0 m in --
    the corpus stores 68,257 today, that set less exactly those 615 and the 12 a too-narrow osm_bbox hid).

    The marker is the FILE, not a count of relations: a cache with zero flattened rings is either a
    course that genuinely has no multipolygons or a cache that never asked, and those two are not the
    same claim. osm_relations.json exists exactly when the pass ran, so its presence records "we asked"
    and a reply of zero relations is then a positive answer.

    Measured over this corpus: castlewood-hill and castlewood-valley WERE the only two caches with no
    osm_relations.json, and also the only two with zero `_from_relation` elements; the other nine carry
    1 to 36 flattened rings (monarch-bay 36 fairways, micke-grove 19, the-reserve 19, valley-hi 18).
    Both were re-fetched on 2026-08-04 when their osm_bbox was widened to cover the drawing corridor
    (see tools/check_osm_bbox.py), and both replies hold ZERO golf / natural=water / building relations
    -- so nothing was in fact missing from those two books, and now the FILE says so instead of a
    comment. All eleven caches with geometry carry osm_relations.json today; this gate is what keeps a
    twelfth from arriving without one.
    """
    if os.path.exists(rel_path):
        return
    if not _env_on("ALLOW_NO_RELATIONS"):
        raise SystemExit("no osm_relations.json -- this cache predates fetch_osm.py's multipolygon\n"
                         "  pass, so a building, pond or fairway mapped as a RELATION is missing from\n"
                         "  osm_course.json and its roof or its open water would be drawn as trees.\n"
                         "  Re-run: COURSE=%s python3 fetch_osm.py   (or set ALLOW_NO_RELATIONS=1 if\n"
                         "  you have confirmed this bbox has no multipolygon features)" % config.SLUG)
    print("WARNING: ALLOW_NO_RELATIONS set -- multipolygon buildings and ponds are NOT in this\n"
          "         cache; their roofs and their water may be drawn as trees")


def main():
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        raise SystemExit("no LAZ tiles in "+DIR+"/laz  (download the course point cloud first)")
    pt2utm, zscale = laz_to_utm()
    surfaces = load_playing_surfaces()
    # Counted by KIND, not as a remainder. `len(surfaces) - n_golf` was a building count until water
    # joined the exclusion list, at which point every pond inflated the printed building figure and
    # -- worse -- could satisfy the `n_bld == 0` hard stop below, so a cache that genuinely predates
    # the way[building] query would sail through on ponds alone and draw roofs as trees again.
    n_golf=sum(1 for s in surfaces if s[5]=='golf')
    n_bld=sum(1 for s in surfaces if s[5]=='building')
    n_water=sum(1 for s in surfaces if s[5]=='water')
    check_buildings(n_bld)
    check_relations(f"{DIR}/osm_relations.json")
    geom = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    # hole centrelines as UTM segment lists.
    # ONE hole-line chooser for the whole pipeline. This used to keep the longest way per ref,
    # first-wins on a tie -- the exact heuristic geo.hole_lines was written to replace after it
    # flipped under element reordering on castlewood-valley (two candidates 604 m apart, both
    # 3 vertices). Three fetch scripts still carried their own copy of it, so the tree corridors,
    # the green surfaces and the gap-fill DEM could each have been placed on a DIFFERENT line
    # from the one render_hole draws and fetch_hole_elev measures against. They all agreed on all
    # 198 holes only because the cached element order happened to favour it. geo.hole_lines picks
    # by distance to the course centre and REFUSES a near-tie rather than guessing.
    _loc = config.COURSE.get('location') or {}
    hlines={hn: [FWD.transform(p['lon'], p['lat']) for p in h['geometry']]
            for hn, h in geo.hole_lines(geom, _loc.get('lat'), _loc.get('lon')).items()}
    BUF=42.0                      # metres either side of the centerline
    CELL=5.0                      # thinning grid (m) -> ~one marker per clump
    acc={hn:{} for hn in hlines}  # hole -> {cell:(x,y)}
    tally=disowned_tally()
    for tf in tiles:
        las=laspy.read(tf)
        label=os.path.basename(tf)
        # Every point in the course's UTM metres, clipped to the tile's OWN header extent, plus the
        # ground mask the bare-earth grid may be built from. See tile_points: one junk coordinate used
        # to size this grid, and a ground return the producer disowned used to define local ground.
        cls,x,y,z,gnd = tile_points(las, pt2utm, zscale, label=label, tally=tally)
        if not gnd.any():
            print(label,"no ground"); continue
        # bare-earth grid from ground returns (class 2): min z per GC-metre cell
        grd,gx0,gy0 = ground_grid(x[gnd], y[gnd], z[gnd], label=label)
        nx,ny = grd.shape
        # Candidate canopy points: NON-ground, 2.5-35 m above local ground.
        # Excluded classes: 2 ground, 6 BUILDING, 7 noise, 9 water, 17 bridge deck, 18 high noise.
        # We must NOT restrict to class 5 (high vegetation): 10 of 11 courses have ZERO class-5
        # points (their tiles are unclassified, class 1 + 2 only), so vegetation arrives as class
        # 1/3/4 and a class-5 filter would yield no trees at all on almost every course.
        cand=(cls!=2)&(cls!=6)&(cls!=7)&(cls!=9)&(cls!=17)&(cls!=18)
        cx=x[cand]; cy=y[cand]; cz=z[cand]
        ci=np.clip(((cx-gx0)/GC).astype(int),0,nx-1); cj=np.clip(((cy-gy0)/GC).astype(int),0,ny-1)
        hgt=cz-grd[ci,cj]
        tree=np.isfinite(hgt)&(hgt>2.5)&(hgt<35)
        tx=cx[tree]; ty=cy[tree]
        for hn,line in hlines.items():
            xs=[p[0] for p in line]; ys=[p[1] for p in line]
            bx0,bx1,by0,by1=min(xs)-BUF,max(xs)+BUF,min(ys)-BUF,max(ys)+BUF
            sel=(tx>=bx0)&(tx<=bx1)&(ty>=by0)&(ty<=by1)
            if not sel.any(): continue
            xx=tx[sel]; yy=ty[sel]
            for i in range(len(xx)):
                px,py=xx[i],yy[i]
                near=min(dist_pt_seg(px,py,line[j][0],line[j][1],line[j+1][0],line[j+1][1])
                         for j in range(len(line)-1))
                if near<BUF:
                    acc[hn][(round(px/CELL),round(py/CELL))]=(px,py)
        print(label,f"processed ({int(tree.sum())} canopy pts)")
    # Say what the producer-disowned filter DID, always -- fetch_dem_hd's own wording, because it is
    # the same filter over the same tiles. Without this a filter that ran and found nothing to drop and
    # a filter that never ran at all print the same thing: nothing.
    for _line in _dem_hd().format_disowned_report(tally):
        print(_line)
    out={}
    dropped_surface=0; dropped_building=0
    for hn,cells in acc.items():
        pts=[]
        for (ux,uy) in cells.values():
            lon,lat=INV.transform(ux,uy)
            lat=round(lat,6); lon=round(lon,6)          # round FIRST so stored==tested
            hit=on_playing_surface(lon,lat,surfaces)   # golf surface OR building footprint
            if hit:
                if hit=='building': dropped_building+=1
                else: dropped_surface+=1
                continue
            pts.append([lat,lon])
        out[str(hn)]=pts
    path=f"{DIR}/trees_lidar.json"
    # LAST GATE BEFORE THE BYTES LAND, like fetch_osm's _check_bindings: everything above is a
    # measurement of the tiles, and this asks whether the measurement is one the book may be built on.
    check_layer(out,path)
    write_layer(path,out)
    tot=sum(len(v) for v in out.values())
    print(f"wrote trees_lidar.json: {tot} tree markers across {len(out)} holes "
          f"(dropped {dropped_surface} on green/fairway/tee/bunker, {dropped_building} on buildings; "
          f"{n_golf} golf + {n_bld} building + {n_water} water polygons; e.g. hole1={len(out.get('1',[]))})")

if __name__=="__main__":
    main()
