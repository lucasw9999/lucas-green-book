#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
High-resolution green surfaces from RAW LiDAR ground returns.

Upgrade over fetch_dem.py (which used the gridded seamless DEM): here we read the
course's USGS 3DEP point cloud (4.7-27.9 pts/m^2 over a green in this corpus),
keep ONLY ground-classified points (class 2), and interpolate a 0.4 m surface
over each green — sampled on the same lat/lon grid render_green.py expects, so
the renderer is unchanged. Output -> dem_hd/holeNN.{npy,json}.
"""
import json, math, glob, os
import numpy as np, laspy
from pyproj import Transformer
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
import config
import geo
from geo import mlat, mlon   # the project's ONE figure of the Earth -- never re-declare these
import surface_io

DIR = config.COURSE_DIR
OUT = f"{DIR}/dem_hd"; os.makedirs(OUT, exist_ok=True)
# Sweep stale staging files first, the same way fetch_lidar.py sweeps laz/. A run killed outright
# (SIGKILL, laptop asleep, power) leaves a .holeNN.*.part that commit_surface's `finally` never got to
# run for, and it then sits in dem_hd/ forever -- which matters because that file is the only on-disk
# trace of the surface pair's rename window, and evidence a dead run also leaves is not evidence.
surface_io.sweep_staged(OUT)
RES = 0.4                                   # target metres/pixel
# OVERWRITE=1 lets a refused 0.4 m attempt replace a working seamless fallback with a blank green --
# see keeps_existing_surface, whose guard this flag is the escape hatch for. (The sentence lost its
# subject when this was promoted from a trailing comment on the assignment to a block above it, so it
# has read as a fragment beginning "replace a working..." since fd1f1ca.) Parsed the way
# fetch_trees.py parses its two
# escape hatches, NOT for truthiness: bool(os.environ.get(...)) made OVERWRITE=0, OVERWRITE=false and
# OVERWRITE=no all mean YES, so the word "false" armed the one path in this stage that can turn a card
# that prints a real read into a blank one. An explicit off must be off.
OVERWRITE = os.environ.get("OVERWRITE", "").lower() not in ("", "0", "false", "no")
# Point flags the PRODUCER disowns: "do not use this measurement", and "computed, not observed".
# Named at module scope so a test can assert the SET rather than grep main() for the words -- the
# first version of that test searched main()'s text, where both words also appear in the comment
# explaining them, so swapping the tuple for ("key_point",) passed every assertion while dropping
# key points and keeping withheld ones. NOT "overlap": see the note at the filter.
DISOWNED_FLAGS = ("withheld", "synthetic")
# The three outcomes of looking one of those bits up, named so main() can TALLY them and a test can
# assert on them rather than parse a log line.
FILTER_APPLIED = "applied"
FILTER_UNAVAILABLE = "unavailable"
MARGIN_M = 12.0
# Trust thresholds for a green surface. Above/below these the surface was not really measured,
# so the book must not print a read for it (see the honesty gate in main()).
NAN_FRAC_MAX = 0.02                         # max share of the green interior that may be extrapolated
DENSITY_MIN = 4.0                           # min ground returns per m^2 INSIDE the green ring
COVER_R_M = 1.0                             # a green node is "measured" if a ground return is
                                            # within this radius of it
UNCOVERED_MAX = 0.02                        # max share of the green interior with no return nearby


def disowned_mask(las, flag):
    """(mask, status) for one producer-disowned point flag on one tile.

    (array, FILTER_APPLIED)     -- the bit is present; True marks the points the PRODUCER disowns.
    (None,  FILTER_UNAVAILABLE) -- this point format carries no such bit, so the filter DID NOT RUN.

    This was an inline `try: bad = np.asarray(getattr(las, _flag)).astype(bool) / except Exception:
    continue` with no message, and every way it could fail was silent. A laspy attribute rename, a
    dtype it could not cast, or an absent bit all quietly disabled the one check that keeps
    vendor-disowned measurements out of the 0.4 m surface a book prints slope reads from.

    Extracted so the caller can TALLY the outcome and report it, because the log could not tell a
    disabled filter from a working one. Measured over all 78 tiles in the corpus: `withheld` resolves
    on 78 of 78 and marks 19,979,730 points, of which 0 are class-2 ground; `synthetic` marks none
    anywhere. So `bad.any()` is true on every tile and the only line the old code printed was
    "dropping 0 ground point(s) flagged withheld" -- which reads exactly like a no-op, and is what a
    disabled filter also looks like.

    Only AttributeError is read as "no such bit". That is what laspy raises for a dimension it does not
    have, and it is the one cause the original comment named. Everything else propagates: a filter that
    cannot run for a reason nobody anticipated must stop the build, not silently shrink itself.
    """
    try:
        raw = getattr(las, flag)
    except AttributeError:
        return None, FILTER_UNAVAILABLE
    return np.asarray(raw).astype(bool), FILTER_APPLIED


def format_disowned_report(tally):
    """The per-flag disclosure lines for a whole run's `tally`, so the three states are legible.

    Printed unconditionally, on the pass as well as the fail -- the same argument
    tools/gen_provenance.py makes for its pair-digest coverage figure: a status that only appears when
    something else is already wrong is not a disclosure. "ran on 78 of 78 tiles, 0 ground point(s)
    dropped" and "DID NOT RUN on 78 of 78 tiles" are the two readings that used to be identical.
    """
    out = []
    for flag in DISOWNED_FLAGS:
        t = tally.get(flag) or {}
        ran, missing = t.get(FILTER_APPLIED, 0), t.get(FILTER_UNAVAILABLE, 0)
        n = ran + missing
        if not n:
            continue
        if missing:
            out.append(f"  !! disowned-point filter `{flag}` DID NOT RUN on {missing} of {n} tile(s): "
                       f"that point format carries no such bit, so any point the producer disowns "
                       f"reached this surface UNFILTERED")
        if ran:
            out.append(f"  disowned-point filter `{flag}`: ran on {ran} of {n} tile(s), "
                       f"{t.get('flagged', 0):,} point(s) flagged, "
                       f"{t.get('dropped', 0):,} ground point(s) dropped")
    return out


def is_insufficient(nan_frac, dens, uncovered):
    """True when a green surface was not really MEASURED, so the book must print no read for it.

    The three gates together: extrapolation beyond the point cloud's hull (nan_frac), in-green density,
    and near-node coverage. Coverage exists because nan_frac cannot see an INTERIOR void -- standing
    water absorbs 1064 nm, so a hole in the middle of a green is spanned by the interpolation and
    counted as measured. A demo deleting the returns in a 6 m circle at each green centre still
    reported nan_frac 0.0000 while changing 7 of 18 printed reads.

    Extracted so the TEST can call it. This was an inline boolean in main(), and its test reached the
    coverage half only by grepping the source for the constant -- so a gate that stopped refusing would
    have gone unnoticed. Same reason fetch_dem.is_flat_fill and keeps_existing_surface are predicates:
    a predicate can be exercised by truth table, an inline boolean inside main() cannot.
    """
    return bool(nan_frac > NAN_FRAC_MAX or dens < DENSITY_MIN or uncovered > UNCOVERED_MAX)

# NAD83 UTM zone chosen from the course longitude (26910 = CA zone 10, 26919 = MA zone 19).
# No default: falling back to -121.0 silently selected California zone 10, so a Pennsylvania course
# (zone 18) would have every green surface projected through the wrong zone with nothing to say so.
# fetch_trees.py was fixed this way; this module -- which actually BUILDS the surfaces -- was missed.
_LOC = config.COURSE.get("location") or {}
if not isinstance(_LOC, dict) or _LOC.get("lon") is None:
    raise SystemExit('course.json needs "location": {"lat": .., "lon": ..} -- it selects the UTM '
                     'zone every green surface is built in. Refusing to guess one.')
_LON = _LOC["lon"]
UTM = "EPSG:%d" % (26900 + int((_LON + 180) / 6) + 1)
TR = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)   # lon/lat -> UTM metres

def laz_to_utm():
    """Transformer from the tiles' native CRS -> the course's UTM zone (metres), plus the
    vertical scale to metres. Auto-read from the LAZ header so State Plane (ftUS) and UTM
    both work; everything downstream then stays in metres.

    ONE transform is applied to EVERY tile in laz/ (main() reprojects each tile with the pair returned
    here), so every tile that carries a CRS has to agree. This used to break out of the scan at the
    first tile it could read a CRS from, with no cross-tile comparison anywhere -- and nothing ever
    removes a previously-fetched project's tiles from laz/, so a directory holding both families in
    this corpus (California zone 3 ftUS on 5 courses, UTM 10N/18N metres on 6) is reachable by ordinary
    use. Measured on a mixed directory: the ftUS scale 0.3048006096 was applied to a metre tile, whose
    points then landed about 1.9e6 m away and were dropped in silence by main()'s bbox prefilter,
    printing only "fed 0 greens". Had the two been closer, the surface would have been built from
    points scaled by 3.28 instead.

    THE SCAN AND ITS REFUSAL NOW LIVE IN geo.sole_laz_crs, because fetch_hole_elev needed the same
    answer and was reading the first tile's CRS TWICE on its own. geo.py is where a fact two stages
    derive independently belongs -- that is the reason the module exists -- and a third hand copy is
    how this one stayed unfixed through two audits.

    STILL not fixed for the whole pipeline: fetch_trees.laz_to_utm() is a hand copy of the pre-fix
    version of this function and still takes the first CRS it can read, which would put that course's
    tree markers through it. It draws markers, not numbers, which is why the stops went elsewhere first.
    """
    src = config.COURSE.get("lidar_crs") or geo.sole_laz_crs(f"{DIR}/laz")
    if src is None:
        # Assuming a CRS-less cloud is already in the course UTM zone with metres for Z is the guess
        # geo.vertical_scale exists to prevent: geo.vertical_scale(UTM) returns 1.0, so a US-survey-
        # foot cloud would go unscaled and EVERY printed slope, contour and arrow would be 3.28x too
        # steep. fetch_trees.py was hard-stopped on this; this module makes the surfaces those numbers
        # come from, so it matters more here.
        raise SystemExit(
            "no CRS in any LAZ tile and no \"lidar_crs\" in course.json.\n"
            "  Refusing to assume the cloud is already in %s with metres for Z: if it is in US\n"
            "  survey feet, every slope would print 3.28x too steep. Set \"lidar_crs\" to a CRS\n"
            "  that carries its units (a compound EPSG code or full WKT), then re-run." % UTM)
    pt = Transformer.from_crs(src, UTM, always_xy=True)
    return pt, geo.vertical_scale(src)      # from the CRS axis unit, never guessed from its name

def centroid(g):
    la=sum(p['lat'] for p in g['geometry'])/len(g['geometry'])
    lo=sum(p['lon'] for p in g['geometry'])/len(g['geometry']); return la,lo

def _polygon_utm(geometry):
    """The green ring as UTM (x, y) arrays."""
    vx, vy = TR.transform([p['lon'] for p in geometry], [p['lat'] for p in geometry])
    return np.asarray(vx), np.asarray(vy)


def _ring_area_m2(geometry):
    """Shoelace area of the green ring in square metres (UTM)."""
    vx, vy = _polygon_utm(geometry)
    return abs(float(np.dot(vx, np.roll(vy, -1)) - np.dot(np.roll(vx, -1), vy))) / 2.0


def _in_polygon(ux, uy, geometry):
    """Mask of sample points (UTM) falling inside a green polygon (lat/lon ring).
    Vectorised ray-cast; the ring is projected to the same UTM frame as the samples."""
    vx, vy = TR.transform([p['lon'] for p in geometry], [p['lat'] for p in geometry])
    vx = np.asarray(vx); vy = np.asarray(vy)
    inside = np.zeros(len(ux), dtype=bool)
    for i in range(len(vx)):
        j = i-1
        x1, y1, x2, y2 = vx[i], vy[i], vx[j], vy[j]
        crosses = (y1 > uy) != (y2 > uy)
        with np.errstate(divide='ignore', invalid='ignore'):
            xint = (x2-x1)*(uy-y1)/np.where(y2 == y1, np.nan, y2-y1) + x1
        inside ^= crosses & (ux < xint)
    return inside

def bearing(a_lat,a_lon,b_lat,b_lon):
    dE=(b_lon-a_lon)*mlon((a_lat+b_lat)/2); dN=(b_lat-a_lat)*mlat((a_lat+b_lat)/2)
    return (math.degrees(math.atan2(dE,dN))+360)%360

def build_targets():
    geom=json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    greens=[e for e in geom if e.get('tags',{}).get('golf')=='green' and e.get('geometry')]
    # ONE hole-line chooser for the whole pipeline. This used to keep the longest way per ref,
    # first-wins on a tie -- the exact heuristic geo.hole_lines was written to replace after it
    # flipped under element reordering on castlewood-valley (two candidates 604 m apart, both
    # 3 vertices). Three fetch scripts still carried their own copy of it, so the tree corridors,
    # the green surfaces and the gap-fill DEM could each have been placed on a DIFFERENT line
    # from the one render_hole draws and fetch_hole_elev measures against. They all agreed on all
    # 198 holes only because the cached element order happened to favour it. geo.hole_lines picks
    # by distance to the course centre and REFUSES a near-tie rather than guessing.
    _loc = config.COURSE.get('location') or {}
    holes = list(geo.hole_lines(geom, _loc.get('lat'), _loc.get('lon')).values())
    targets={}
    bound={}          # hole -> green, so a green shared by two holes can be caught (see geo.py)
    for h in holes:
        ref=h['tags'].get('ref')
        if not(ref and ref.isdigit()):continue
        hn=int(ref); line=h['geometry']
        green,gend,_tend = geo.match_green(line, greens, label=f"hole {hn}")
        bound[hn]=green
        prev = line[1] if gend is line[0] else line[-2]
        appr=bearing(prev['lat'],prev['lon'],gend['lat'],gend['lon'])
        gpoly=green['geometry']; lats=[p['lat'] for p in gpoly]; lons=[p['lon'] for p in gpoly]
        clat,clon=centroid(green)
        dlat=MARGIN_M/mlat(clat); dlon=MARGIN_M/mlon(clat)
        xmin,xmax=min(lons)-dlon,max(lons)+dlon
        ymin,ymax=min(lats)-dlat,max(lats)+dlat
        wm=(xmax-xmin)*mlon(clat); hm=(ymax-ymin)*mlat(clat)
        W=max(40,int(wm/RES)); H=max(40,int(hm/RES))
        # grid of cell-centre lon/lat -> UTM (for interpolation) ; store bbox for renderer
        us=(np.arange(W)+0.5)/W; vs=(np.arange(H)+0.5)/H
        lon_g=xmin+us*(xmax-xmin); lat_g=ymax-vs*(ymax-ymin)   # row0=top=ymax
        LON,LAT=np.meshgrid(lon_g,lat_g)
        UX,UY=TR.transform(LON.ravel(),LAT.ravel())
        # UTM bbox of the patch (for point pre-filtering)
        cx,cy=TR.transform([xmin,xmax,xmin,xmax],[ymin,ymin,ymax,ymax])
        targets[hn]=dict(green=green,appr=appr,bbox=[xmin,ymin,xmax,ymax],W=W,H=H,
                         clat=clat,clon=clon,
                         UX=UX,UY=UY,   # target sample points in UTM
                         uxmin=min(cx)-2,uxmax=max(cx)+2,uymin=min(cy)-2,uymax=max(cy)+2,
                         acc_x=[],acc_y=[],acc_z=[])
    geo.assert_one_green_per_hole(bound, label=config.SLUG)
    return targets

def keeps_existing_surface(meta_path, overwrite=False):
    """True when meta_path holds a READABLE surface that a refused 0.4 m attempt must not replace.

    The mirror of fetch_dem.keeps_existing_surface, with the seamless case INVERTED -- that one protects
    good 0.4 m LiDAR from the coarse seamless fill, this one protects ANY readable record from a blank
    green. (Said "the coarse 1 m fill" here until this round. 7d8d131 corrected the other three notes in
    this module and missed this one, and the reason is worth recording: the grader it measured them with
    binds the figure to the product by ADJACENCY -- seamless, mosaic, national model, fallback, DEM --
    and "fill" is not on that list, so the same claim in the same paragraph was invisible. The arrays
    are measured 20 lines below.)

    The inline guard this replaced tested `fetch_dem.is_seamless(prev)`, so it protected only the 6
    seamless records in a 198-green corpus -- 3%. The other 192 are LiDAR-sourced, and re-running this
    stage on one whose density had slipped under DENSITY_MIN would overwrite a working read with
    insufficient=True and blank the card. The tightest live case is the-reserve hole 9: 2443 in-ring
    ground returns over a 520.53 m^2 ring, i.e. 4.6933 pts/m^2 (published as 4.7) against a floor of
    4.0, so a 14.8% loss of in-green ground returns flips it, and the old guard would not have fired.
    (Measured with this module's own helpers off that course's four LAZ tiles. The figure was written
    here as "a 15% loss" while the gate was still comparing the ROUNDED density, where nothing flipped
    until 15.84% -- the example and the code were wrong in opposite directions.) The comment above the
    guard said "Only one direction was guarded"; it was true one level further down than it looked.

    A predicate rather than an inline branch so it can be tested by truth table. The test that was meant
    to pin the old guard asserted only that the strings 'os.environ.get("OVERWRITE")' and "is_seamless"
    appear in the module source -- both satisfied outside the guard, the second by the word inside an
    import COMMENT -- so deleting the whole guard left it green.
    """
    if overwrite or not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path) as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return False                        # unreadable: rebuilding it is the repair
    # Any positively-sourced record that is not itself a refusal. Deliberately NOT is_seamless: a
    # seamless surface and a good 0.4 m one are both real reads, and both beat a blank green. (Said
    # "seamless 1 m" here until this round: the six greens this corpus takes from that mosaic have
    # arrays measuring 2.72 m E-W x 3.43 m N-S, so "1 m" overstated the one mark whose job is to say
    # trust this green LESS. a60fcae corrected the string literals and the legal records and stopped
    # short of comments, naming this note as one of the two it stopped short of.)
    return bool(str((prev or {}).get("source", "")).strip()) and not prev.get("insufficient")


def main():
    pt2utm, zscale = laz_to_utm()
    print(f"LiDAR -> {UTM} reproject; vertical scale to m =", zscale)
    targets=build_targets()
    tiles=sorted(glob.glob(f"{DIR}/laz/*.laz"))
    print("tiles:",[os.path.basename(t) for t in tiles])
    disowned_tally = {f: {FILTER_APPLIED: 0, FILTER_UNAVAILABLE: 0, "flagged": 0, "dropped": 0}
                      for f in DISOWNED_FLAGS}
    for tf in tiles:
        las=laspy.read(tf)
        cls=np.asarray(las.classification)
        g=cls==2
        # Drop points the PRODUCER disowns. LAS carries a `withheld` bit for measurements the vendor
        # marked as not to be used and a `synthetic` bit for points that were computed rather than
        # measured; neither belongs in a surface this book prints a slope read off.
        #
        # What the corpus actually holds, measured over all 78 tiles rather than assumed: `withheld`
        # is set on 78 of 78 tiles, 19,979,730 points in all -- so this filter is LIVE, not dormant.
        # ZERO of those points are class-2 GROUND, which is why it changes no shipped surface; and
        # `synthetic` marks nothing anywhere. (This comment used to say "every tile in the corpus has
        # ZERO of both", which was false on 78 of 78 and made a live filter read as a no-op.) It is
        # here so the next course's tiles cannot quietly contribute rejected points to a green.
        #
        # Deliberately NOT filtering `overlap`, which is a different thing: those are valid returns in
        # the strip where two flight lines meet, and USGS flags them only so derivative products CAN
        # exclude them. Two courses here are 31% and 47% overlap by ground point, and dropping them
        # would halve bay-view's density for no gain: gridded separately, the overlap points and the
        # rest agree to RMS 1.16 cm over all 18 of its greens, with every printed tilt within 0.07
        # percentage points -- below what the card resolves. Measured, see
        # legal/09_GREEN_SURFACE_REPEATABILITY.md.
        for _flag in DISOWNED_FLAGS:
            bad, _status = disowned_mask(las, _flag)
            _t = disowned_tally[_flag]
            _t[_status] += 1
            if bad is None:
                continue           # this point format has no such bit; reported in the run summary
            _t["flagged"] += int(bad.sum())
            n_drop = int((g & bad).sum())
            _t["dropped"] += n_drop
            if n_drop:
                print(f"  {os.path.basename(tf)}: dropping {n_drop} ground point(s) "
                      f"flagged {_flag}")
            g = g & ~bad
        # reproject ground points to the course UTM zone (metres); scale Z to metres
        x,y = pt2utm.transform(np.asarray(las.x)[g], np.asarray(las.y)[g])
        z = np.asarray(las.z)[g]*zscale
        txmin,txmax=x.min(),x.max(); tymin,tymax=y.min(),y.max()
        used=0
        for hn,t in targets.items():
            if t['uxmax']<txmin or t['uxmin']>txmax or t['uymax']<tymin or t['uymin']>tymax:
                continue
            m=(x>=t['uxmin'])&(x<=t['uxmax'])&(y>=t['uymin'])&(y<=t['uymax'])
            if m.any():
                t['acc_x'].append(x[m]); t['acc_y'].append(y[m]); t['acc_z'].append(z[m]); used+=1
        print(f"  {os.path.basename(tf)}: {g.sum()} ground pts, fed {used} greens")
        del las,cls,x,y,z

    # Say what the producer-disowned filter DID, always. Without this, a filter that ran and found no
    # ground points to drop and a filter that never ran at all produce the same output.
    for _line in format_disowned_report(disowned_tally):
        print(_line)

    for hn,t in sorted(targets.items()):
        if not t['acc_x']:
            print(f"hole {hn}: NO POINTS"); continue
        px=np.concatenate(t['acc_x']); py=np.concatenate(t['acc_y']); pz=np.concatenate(t['acc_z'])
        pts=np.c_[px,py]
        grid=np.c_[t['UX'],t['UY']]
        zi=griddata(pts,pz,grid,method='linear')
        nan=np.isnan(zi)
        # HONESTY GATE. griddata's linear pass returns NaN for every node OUTSIDE the point
        # cloud's convex hull; the nearest pass below then copies a z value in -- terrain the
        # LiDAR never saw. That is fine for the 12 m margin ring (deliberately outside the
        # green) but NOT on the putting surface itself, so measure the gap where it matters:
        # the fraction of NaN nodes lying INSIDE the green polygon. Recorded in the meta so
        # render_green can refuse to draw a read that was invented rather than measured.
        inside=_in_polygon(t['UX'],t['UY'],t['green']['geometry'])
        n_in=int(inside.sum())
        nan_frac=float((nan & inside).sum())/n_in if n_in else 1.0
        # nan_frac alone answers "is the green inside the point cloud's CONVEX HULL?", which is not
        # the question. griddata's linear pass only returns NaN outside the hull, so an INTERIOR void
        # -- standing water absorbs 1064 nm and returns nothing -- is spanned by the interpolation and
        # counted as measured. A demo deleting the returns in a 6 m circle at each green centre (about
        # a quarter of a 450 m^2 green) still reported nan_frac=0.0000 and insufficient=False, while
        # changing 7 of 18 printed reads. So ALSO measure real coverage: every green node must have a
        # ground return near it. (Measured on the built corpus: the worst uncovered share sits under
        # 1%, well inside the 2% gate, so no existing green is affected -- this closes a blind spot
        # rather than reclassifying anything. Stated as a bound, not an exact figure: the exact worst
        # moves whenever a course is added or re-fetched, and this comment carried a stale 0.87%
        # against an actual 0.71% for exactly that reason.)
        if n_in:
            tree=cKDTree(pts)
            dist,_=tree.query(grid[inside], k=1)
            uncovered=float((dist>COVER_R_M).mean())
        else:
            uncovered=1.0
        if nan.any():
            zi[nan]=griddata(pts,pz,grid[nan],method='nearest')
        arr=zi.reshape(t['H'],t['W'])
        # Density INSIDE the green ring, over the ring's true area. It used to divide the points of a
        # padded prefilter region by the unpadded bbox -- and that bbox includes MARGIN_M=12 m of
        # fairway and bunker, so the published figure was neither a green density nor consistent with
        # its own divisor. gen_provenance publishes this number as density "over N greens".
        g_area=_ring_area_m2(t['green']['geometry'])
        n_pts_in=int(_in_polygon(px,py,t['green']['geometry']).sum())
        # GATE ON THE MEASUREMENT, PUBLISH THE ROUNDING. `dens` is a display figure (the meta, the run
        # log, and gen_provenance's "N pts/m^2 over N greens" all show one decimal); dens_exact is what
        # the gate sees. Rounding first let a green measured at 3.96 pts/m^2 through a floor of 4.0
        # written to refuse it -- round(3.96, 1) == 4.0, and 4.0 is not < 4.0. That is the same fault as
        # the 3 ft elevation floor compared against a value already rounded to 0.1 ft (e59cdc4), and
        # density was the ONE gate input rounded before its comparison: nan_frac and uncovered are
        # passed exact here and rounded only on their way into the meta below.
        #
        # Latent when found -- the corpus minimum is the-reserve hole 9 at 4.7, whose 2443 in-ring
        # returns over a 520.53 m^2 ring measure 4.6933 -- so no shipped green moves. What it changes is
        # the next thin green: at a 15% loss of that hole's in-green returns the exact density is 3.9893
        # and the gate now refuses, where the rounded one accepted until the loss reached 15.84%.
        dens_exact = n_pts_in/g_area if g_area>0 else 0.0
        dens = round(dens_exact,1)
        # A green is only trustworthy if the surface was actually measured under it.
        insufficient = is_insufficient(nan_frac, dens_exact, uncovered)
        # Do not trade a WORKING seamless fallback for a refused 0.4 m attempt. This stage shares dem_hd/
        # with fetch_dem.py, which fills the greens this one gives up on, and re-running this stage
        # alone -- an ordinary thing to do after changing the point filter -- overwrote that fill with
        # an insufficient=True record. The green then prints BLANK where it previously printed a real
        # read carrying the coarse-data caveat: a card silently loses information, and the only symptom
        # is the blank itself.
        #
        # This is the exact mirror of the fault fetch_dem.keeps_existing_surface was written for, found
        # on the same course: that one replaced good 0.4 m greens with the coarse mosaic ones, and cost
        # Monarch Bay 1.1 MB of precision without printing a dishonest word. Only one direction was
        # guarded. Same convention here, same escape hatch: OVERWRITE=1 to do it on purpose.
        #
        # A SUFFICIENT 0.4 m surface still replaces a seamless one -- that is the upgrade this stage
        # exists for, and only the refused case is a downgrade.
        if insufficient and keeps_existing_surface(f"{OUT}/hole{hn:02d}.json", OVERWRITE):
            print(f"hole {hn:2d}: 0.4m refused (nan {nan_frac:.3f}, dens {dens}, unc "
                  f"{uncovered:.3f}) -- KEEPING the existing surface. "
                  f"OVERWRITE=1 to replace it with a blank green.")
            continue
        meta=dict(hole=hn,approach_bearing=t['appr'],bbox=t['bbox'],W=t['W'],H=t['H'],
                  green_id=t['green']['id'],green_center=[t['clat'],t['clon']],
                  polygon=[[p['lat'],p['lon']] for p in t['green']['geometry']],
                  source="USGS 3DEP LiDAR ground returns @0.4m",
                  npts=int(len(pz)), density=dens,
                  nan_frac=round(nan_frac,4), uncovered=round(uncovered,4),
                  insufficient=insufficient)
        # ONE unit: the array carries no georeference, so an array beside a stale bbox is a printed
        # slope for ground the pixels do not cover. See surface_io.commit_surface.
        surface_io.commit_surface(f"{OUT}/hole{hn:02d}", arr, meta)
        flag=("  *** INSUFFICIENT LiDAR: %.1f%% of the green interior was extrapolated, not "
              "measured -- render blank ***" % (100*nan_frac)) if insufficient else ""
        print(f"hole {hn:2d}: {t['W']}x{t['H']} @0.4m  {len(pz):6d} ground pts "
              f"({dens}/m^2 in-green, {100*nan_frac:.1f}% extrapolated, "
              f"{100*uncovered:.1f}% uncovered){flag}")

if __name__=="__main__":
    main()
