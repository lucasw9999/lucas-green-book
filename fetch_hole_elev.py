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

      * The line may STOP SHORT of the back tee -- 22 of the 198 holes do, by up to 138 yd. Sampling
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
    card_yd = config.HOLES[hnum][2]
    card_m = card_yd*0.9144
    arc_yd = arc_m/0.9144
    if abs(arc_yd - card_yd) <= max(15.0, 0.05*card_yd):
        return tend['lat'], tend['lon'], "tee end of the mapped hole line"
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
    """Median elevation of the green's built surface, or None."""
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


def main():
    if config.BUILD_MODE == "yardage":
        print(f"{config.SLUG} is a yardage-mode course: no green surfaces, so no elevation change "
              f"to measure against.")
        return 0
    els = json.load(open(f"{DIR}/osm_geom.json"))["elements"]
    holes = {}
    for e in els:
        t = e.get("tags") or {}
        if t.get("golf") != "hole" or not e.get("geometry"):
            continue
        ref = t.get("ref")
        if ref and ref.isdigit() and len(e["geometry"]) > len(
                holes.get(int(ref), {}).get("geometry", [])):
            holes[int(ref)] = e            # longest centreline per ref, as every other reader does
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
        d_m = (gz - tz) * vscale
        rows[str(hn)] = {"tee_z_m": round(tz * vscale, 2),
                         "green_z_m": round(gz * vscale, 2),
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
