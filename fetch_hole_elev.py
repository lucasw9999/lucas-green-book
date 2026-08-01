#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Measure the ELEVATION CHANGE from each tee to its green, from the LiDAR already on disk.

Why: elevation is what makes a junior club up or down, and the card said nothing about it. A yardage
book normally does. We hold ground-classified returns over the whole course, so this is a measurement
we can make rather than a number we would have to invent.

What is printed is the CHANGE ITSELF -- "green 37 ft above the tee" -- not a "plays like +12 yd"
adjustment. Converting elevation into an effective yardage needs a ball-flight model (launch, spin,
apex, air density) that LiDAR cannot supply, so a printed "plays" figure would be exactly the kind of
confident-but-unsupported number this project refuses. The player brings the judgement; we bring the
measurement.

Method, per hole:
  tee   -- median Z of ground-classified returns within TEE_R_M of the hole's BACK TEE
  green -- median Z of the green's own built surface (dem_hd/holeNN.npy), which is already gated
           for density and coverage, so it inherits that honesty check for free
Both are medians, not means: a mean is dragged by a single mis-classified return, and a tee box is
flat enough that the median is the tee's height.

Finding the back tee is the whole difficulty -- see tee_anchor. A hole whose tee cannot be located,
or whose tee has too few ground returns, gets NO figure rather than a guessed one, and the card
simply omits the line. The count and the basis are recorded so every omission is auditable.

Run:  COURSE=<slug> python3 fetch_hole_elev.py [--write]
      --write records hole_elev.json in COURSE_DIR.
"""
import glob
import json
import math
import os
import sys

import numpy as np

import config
import geo
import render_hole                 # for par3_exact_from_tee: one definition of "straight par 3"

DIR = config.COURSE_DIR
TEE_R_M = 15.0          # half-width of the box sampled around the tee point
MIN_TEE_PTS = 200       # below this, refuse to state a tee height
GROUND = 2              # LAS classification for bare earth
R_LAT = 111320.0        # metres per degree of latitude
# A tee-to-green change beyond this is not a golf hole, it is a units or datum fault. The largest real
# figure in the corpus is 160 ft (castlewood-hill 18, a genuinely hilly Pleasanton course), so this
# leaves better than half again of headroom. It exists because the unit bug this file once had produced
# 300-550 ft figures that printed on real cards and looked like data: a plausibility bound is the one
# check that would have stopped them at the source instead of needing a reader to notice.
MAX_PLAUSIBLE_FT = 250.0


def _mlon(lat):
    return 111320.0*math.cos(math.radians(lat))


def tee_anchor(hnum, line, greens):
    """(lat, lon, basis) for this hole's BACK TEE, or (None, None, reason) to refuse.

    The elevation change is only honest if the point sampled really is the tee, and two separate
    things can make the mapped centreline's tee end NOT the tee. Both are checked, not assumed:

      * The line may be traced GREEN-FIRST, in which case its first vertex is the green. This code
        used to take geometry[0]; that is the tee end on all 198 holes in the corpus today, so it
        worked by luck. A course mapped the other way round would have compared the green's own
        height against itself and reported an elevation change of about zero -- a number that reads
        as plausible rather than as obviously broken, which is the worst kind of wrong. geo.match_green
        decides which end is which.

      * The line may STOP SHORT of the back tee -- 19 of the 198 holes do, by up to 103 yd. (Was 22
        holes and 138 yd; valley-hi 17's 220 yd stub was replaced by its real 360 yd centreline when
        that course's osm_bbox was widened, which removed both the count and the worst case.) Sampling
        there measures the ground somewhere up the fairway and labels it the tee, and on a climbing
        hole those are not the same height. So:
          - line spans the card yardage      -> its tee end IS the tee; sample there.
          - straight PAR 3 that falls short   -> the tee is recoverable. A par 3 is played straight
            tee-to-green, so the tee lies on the hole's own axis at exactly the card yardage from the
            green centre; extrapolate to that point. This is the same collinearity that lets
            render_hole.par3_exact_from_tee print exact from-tee yardages on these holes.
          - anything else                     -> REFUSE. A par 4/5 card follows a played route that
            can dogleg, so there is no way to say where the missing yardage went.
    """
    green, gend, tend = geo.match_green(line, greens, label=f"hole {hnum}")
    la0 = sum(p['lat'] for p in line)/len(line)
    lo0 = sum(p['lon'] for p in line)/len(line)
    em = lambda la, lo: ((lo-lo0)*_mlon(la0), (la-la0)*R_LAT)
    same = lambda a, b: abs(a['lat']-b['lat']) < 1e-9 and abs(a['lon']-b['lon']) < 1e-9
    ordered = line if same(line[0], tend) else list(reversed(line))
    pts = [em(p['lat'], p['lon']) for p in ordered]
    arc_m = sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
                for i in range(len(pts)-1)) or 1.0
    chord_m = math.hypot(pts[-1][0]-pts[0][0], pts[-1][1]-pts[0][1]) or 1.0
    card_yd = config.HOLES[hnum][config.BACK_I]      # the tee the book is built on, not column 0
    card_m = card_yd*0.9144
    arc_yd = arc_m/0.9144
    if abs(arc_yd - card_yd) <= max(15.0, 0.05*card_yd):
        return tend['lat'], tend['lon'], "tee end of the mapped hole line"
    if render_hole.line_traced_past_the_tee(arc_yd, card_yd, chord_m/0.9144):
        # The line runs BEYOND the book's tee, so that tee lies ON the drawn line: walk back from the
        # green end until the remaining walk equals the card yardage. Interpolation on real geometry,
        # not extrapolation -- and the only reason it is needed is that a course whose OSM lines were
        # traced along a LONGER tee's route (the-reserve: lines follow Black, the book is built on Gold)
        # would otherwise sample the ground at the wrong tee, ~40 yd back, and call it this tee's height.
        want = card_m
        acc = 0.0
        for i in range(len(pts)-1, 0, -1):
            seg = math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1])
            if acc + seg >= want:
                f = (want - acc)/(seg or 1.0)          # fraction from pts[i] toward pts[i-1]
                tx = pts[i][0] + (pts[i-1][0]-pts[i][0])*f
                ty = pts[i][1] + (pts[i-1][1]-pts[i][1])*f
                return (ty/R_LAT + la0, tx/_mlon(la0) + lo0,
                        f"walked back along the mapped line to the card {card_yd} yd "
                        f"(the line runs {arc_yd:.0f} yd, past this tee)")
            acc += seg
    if render_hole.par3_exact_from_tee(config.HOLES[hnum][0], arc_m, chord_m):
        gp = [em(p['lat'], p['lon']) for p in green['geometry']]
        gc = (sum(p[0] for p in gp)/len(gp), sum(p[1] for p in gp)/len(gp))
        te = pts[0]
        dx, dy = te[0]-gc[0], te[1]-gc[1]
        d = math.hypot(dx, dy) or 1.0
        tx, ty = gc[0] + dx/d*card_m, gc[1] + dy/d*card_m
        return (ty/R_LAT + la0, tx/_mlon(la0) + lo0,
                f"par-3 tee extrapolated along the hole axis to the card {card_yd} yd "
                f"(mapped line runs {arc_yd:.0f} yd)")
    return None, None, (f"mapped line is {arc_yd:.0f} yd against a card {card_yd} yd, so its tee end "
                        f"is not the back tee and a par-{config.HOLES[hnum][0]} card can dogleg")


def _tee_points(anchors):
    """{hole: (x, y)} in the LAZ CRS for each hole's tee anchor, plus the CRS used."""
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        return {}, None
    import laspy
    from pyproj import Transformer
    with laspy.open(tiles[0]) as f:
        crs = f.header.parse_crs()
    if crs is None:
        return {}, None
    T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return {hn: T.transform(lo, la) for hn, (la, lo) in anchors.items()}, crs


def tee_elevations(anchors):
    """{hole: (median_z, n_points)} sampled from ground returns around each tee anchor."""
    targets, crs = _tee_points(anchors)
    if not targets:
        return {}
    import laspy
    acc = {hn: [] for hn in targets}
    for path in sorted(glob.glob(f"{DIR}/laz/*.laz")):
        with laspy.open(path) as f:
            hb = f.header
            # skip a tile that cannot contain any tee box at all
            if all(x + TEE_R_M < hb.x_min or x - TEE_R_M > hb.x_max or
                   y + TEE_R_M < hb.y_min or y - TEE_R_M > hb.y_max
                   for x, y in targets.values()):
                continue
            for chunk in f.chunk_iterator(3_000_000):
                cl = np.asarray(chunk.classification)
                g = cl == GROUND
                if not g.any():
                    continue
                x = np.asarray(chunk.x)[g]
                y = np.asarray(chunk.y)[g]
                z = np.asarray(chunk.z)[g]
                for hn, (tx, ty) in targets.items():
                    m = (np.abs(x - tx) < TEE_R_M) & (np.abs(y - ty) < TEE_R_M)
                    if m.any():
                        acc[hn].append(z[m])
    out = {}
    for hn, parts in acc.items():
        if not parts:
            continue
        zs = np.concatenate(parts)
        out[hn] = (float(np.median(zs)), int(zs.size))
    return out


def green_elevation(hole):
    """Median elevation of the green's built surface, in METRES, or None.

    Already metres, both ways in: fetch_dem_hd.py scales LAZ Z by the CRS axis unit before gridding
    (its line `z = np.asarray(las.z)[g]*zscale`), and fetch_dem.py's seamless patches come from 3DEP
    in metres. So this value must NOT be scaled again -- see the note in main() on the bug that was.
    """
    mp = f"{DIR}/dem_hd/hole{hole:02d}.json"
    npy = mp.replace(".json", ".npy")
    if not (os.path.isfile(mp) and os.path.isfile(npy)):
        return None
    with open(mp) as f:
        meta = json.load(f)
    if meta.get("insufficient"):
        return None            # no trustworthy surface -> no elevation claim either
    a = np.load(npy).astype(float)
    a[~np.isfinite(a)] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    if np.all(np.isnan(a)):
        return None
    return float(np.nanmedian(a))


def is_plausible_change(change_ft):
    """False when a tee-to-green figure can only be a units or datum fault. See MAX_PLAUSIBLE_FT.

    Clean data cannot exercise this, so deleting the CALL in main() is invisible until a fault appears
    -- at which point the corpus test on the recorded figures catches it. That is defence in depth, not
    full coverage, and is stated here rather than implied."""
    return abs(change_ft) <= MAX_PLAUSIBLE_FT


def elevation_change_m(green_z_m, tee_z_raw, vscale):
    """Green minus tee, in metres. ONLY the tee height is raw LAZ Z, so only it takes the axis scale.

    Kept as a pure function because the mistake it encodes was invisible in every other check. The
    code read `(green - tee) * vscale`, subtracting a US-survey-foot tee height from an already-metric
    green height and scaling the difference. It produced confident, plausible, badly wrong figures on
    the 5 ftUS courses -- monarch-bay hole 3 printed "green 21 ft below the tee" against a real
    -6.2 ft -- while the 6 metric courses were exactly right, because vscale is 1.0 there and the two
    forms coincide. Merion is metric, so no amount of checking Merion could surface it.
    """
    return green_z_m - tee_z_raw * vscale


def main():
    if config.BUILD_MODE == "yardage":
        print(f"{config.SLUG} is a yardage-mode course: no green surfaces, so no elevation change "
              f"to measure against.")
        return 0
    els = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    _loc = config.COURSE.get("location") or {}
    holes = geo.hole_lines(els, _loc.get("lat"), _loc.get("lon"))   # one shared, deterministic choice
    if not holes:
        print("no hole centrelines in osm_geom.json"); return 1

    # Vertical units: the Z we compare must be metres. geo.vertical_scale RAISES rather than assume,
    # which is what we want -- a ftUS cloud read as metres would report a 3.28x elevation change.
    tiles = sorted(glob.glob(f"{DIR}/laz/*.laz"))
    if not tiles:
        print(f"{config.SLUG}: no LAZ on disk, so tee heights cannot be measured"); return 2
    import laspy
    with laspy.open(tiles[0]) as f:
        vscale = geo.vertical_scale(config.COURSE.get("lidar_crs") or f.header.parse_crs())

    greens = [e for e in els if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
    anchors, refused, bases = {}, {}, {}
    for hn in sorted(holes):
        la, lo, basis = tee_anchor(hn, holes[hn]["geometry"], greens)
        bases[hn] = basis
        if la is None:
            refused[hn] = basis
        else:
            anchors[hn] = (la, lo)
            refused[hn] = None
            if not basis.startswith("tee end"):
                print(f"  hole {hn:2d}: {basis}")

    tees = tee_elevations(anchors)
    rows = {}
    print(f"{config.SLUG}  ({len(holes)} holes, tee radius {TEE_R_M:g} m, Z x {vscale:g} -> m)")
    for hn in sorted(holes):
        gz = green_elevation(hn)
        tz_n = tees.get(hn)
        if refused[hn] is not None:
            print(f"  hole {hn:2d}: no elevation figure -- {refused[hn]}")
            continue
        if gz is None or tz_n is None or tz_n[1] < MIN_TEE_PTS:
            why = ("no usable green surface" if gz is None else
                   f"only {tz_n[1] if tz_n else 0} ground returns at the tee "
                   f"(need {MIN_TEE_PTS})")
            print(f"  hole {hn:2d}: no elevation figure -- {why}")
            continue
        tz, n = tz_n
        # UNITS. The green surface is ALREADY metres (see green_elevation); the tee median is raw LAZ
        # Z, so only IT takes the CRS axis scale. Getting this wrong was silent and large: the code
        # read `(gz - tz) * vscale`, subtracting a ftUS tee height from a metric green height and then
        # scaling the difference. On every US-survey-foot course that produced a confident, plausible,
        # badly wrong figure -- monarch-bay hole 3 printed "green 21 ft below the tee" for a real
        # -6.2 ft. Metric courses (merion, philadelphia) were unaffected because vscale is 1.0 there,
        # which is exactly why spot-checking Merion did not reveal it.
        tz_m = tz * vscale
        d_m = elevation_change_m(gz, tz, vscale)
        if not is_plausible_change(d_m * 3.28084):
            print(f"  hole {hn:2d}: no elevation figure -- {d_m*3.28084:+.0f} ft is not a golf hole, "
                  f"it is a units or datum fault (green {gz:.1f} m, tee {tz_m:.1f} m)")
            continue
        rows[str(hn)] = {"tee_z_m": round(tz_m, 2),
                         "green_z_m": round(gz, 2),
                         "change_m": round(d_m, 2),
                         "change_ft": round(d_m * 3.28084, 1),
                         "tee_points": n,
                         "tee_basis": bases[hn]}
        d_ft = d_m * 3.28084
        word = "above" if d_ft > 0 else "below"
        print(f"  hole {hn:2d}: green {abs(d_ft):5.1f} ft {word} the tee   "
              f"({d_m:+.1f} m, {n} tee returns)")

    if not rows:
        print("  no hole got a figure -- writing nothing"); return 1
    print(f"  => {len(rows)} of {len(holes)} holes measured")
    if "--write" in sys.argv:
        p = f"{DIR}/hole_elev.json"
        tmp = p + ".part"
        with open(tmp, "w") as f:
            json.dump({"tee_radius_m": TEE_R_M, "min_tee_points": MIN_TEE_PTS,
                       "source": "USGS 3DEP LiDAR ground returns (class 2) vs the green's own "
                                 "0.4 m surface",
                       "holes": rows}, f, indent=2)
        os.replace(tmp, p)
        print(f"  wrote {os.path.relpath(p, config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
