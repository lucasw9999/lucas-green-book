#!/usr/bin/env python3
"""Does the printed green read depend on WHICH survey supplied the points?

Five of the twelve courses were flown across more than one date, so their greens are built from a
blend of two or more passes. That blend is invisible in the book, and it is only harmless if the
passes agree. This tool takes it apart: for every green whose ground returns span two dates, it
grids EACH DATE ON ITS OWN over the shipped tile's grid, runs the same
`render_green.green_summary()` the card is printed from, and compares the numbers.

Two different things can make the answer disagree, and they need opposite responses:
  * noise -- the passes saw the same green and differ inside the sensor's precision. Expected.
  * change -- the green was rebuilt, top-dressed or re-grassed between the passes, so the shipped
    surface is a composite of two DIFFERENT greens and the card reads a shape that never existed.
    philadelphia-country-club is the live risk: its passes are 100 days apart and straddle a
    phased restoration, which is exactly when a course changes under the sensor.

Exits non-zero only when two passes that BOTH saw the green disagree beyond the sensor's demonstrated
precision. This is a diagnostic to run when a course looks wrong or its survey spans dates -- not a
build gate.

Usage:
    COURSE=<slug> python3 tools/cross_flight_check.py
    python3 tools/cross_flight_check.py --all
"""
import glob
import json
import math
import os
import sys

import laspy
import numpy as np
from pyproj import Transformer
from scipy.interpolate import griddata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lidar_dates import course_tz, gps_to_utc            # noqa: E402  (same dir)

# A pass that merely clips the edge of a green cannot be compared with one that covered it: its
# least-squares plane is fitted to a sliver and means nothing. castlewood-valley 12 is the worked
# example -- 716 ground points touching 4% of the tile on 2021-06-21 against 34,507 over 85% on
# 07-02, which "disagreed" by 0.01% vs 5.22% and 32 degrees of aim purely because of that. The
# SHIPPED surface merges all passes (14.3 pts/m2 there) and is unaffected. So require each pass to
# have independently seen most of the green before its numbers are allowed to accuse the other's.
MIN_COVER = 0.50       # fraction of the green's interior cells this pass alone must touch
MIN_PTS = 2000         # and an absolute floor, for small greens where 50% is still very few points
# Tolerances. Set from what two genuinely independent surveys of an UNCHANGED green actually do:
# philadelphia's passes are 100 days apart and agree to 0.01pp of tilt and 2.1 degrees of aim; the
# well-covered Alameda pairs agree to 0.07pp. Anything past these is not precision, it is change.
TOL_TILT_PP = 0.25     # percentage points of dominant tilt
TOL_AIM_DEG = 10.0     # degrees of dominant break direction
# The card claims "Contours join equal height (15 cm each)". That claim is about RELATIVE height
# inside one green, not absolute elevation -- a uniform datum offset moves every contour together and
# changes no read. So the figure that matters is how far two independent surveys of the same green
# disagree AFTER gridding and smoothing, which is what the contour lines are actually drawn from.
CINT_CM = 15.0
CHUNK = 4_000_000
# A course this tool could not examine. Distinct from (0, [], ...) -- "nothing to compare" -- so a
# refusal can never be read as agreement. main() exits non-zero when any course returns it.
REFUSED = (None, [], 0, 0, [])



def dates_recoverable(header):
    """False when a tile's gps_time carries no absolute date, so passes cannot be separated.

    Only Adjusted Standard GPS time (global_encoding bit 0 == 1) is decodable. GPS WEEK TIME records
    seconds since the start of an unrecorded week, so the date is genuinely absent -- lidar_dates.py
    refuses such tiles for the same reason, having once turned every one of them into a fabricated
    2011-09-14.

    Split out from the read loop so the refusal can be tested without a synthetic point cloud: the
    failure it prevents is SILENT, not loud. A bad decode collapses every point into one bogus epoch,
    each green is then covered by a single pass, the course is skipped as "not independently covered",
    and the run reports zero disagreements -- which reads as a pass. This tool's output is the evidence
    in legal/09_GREEN_SURFACE_REPEATABILITY.md, so it must not be able to agree by failing.
    """
    return int(getattr(getattr(header, "global_encoding", None), "gps_time_type", 0)) == 1


def _grid(meta):
    """The shipped tile's own grid, plus the green-interior mask, so every pass is compared on it."""
    import render_green as rg
    from geo import R_LAT, mlon
    W, H = meta['W'], meta['H']
    xmin, ymin, xmax, ymax = meta['bbox']
    clat = (ymin+ymax)/2.0
    px_x = (xmax-xmin)*mlon(clat)/W
    px_y = (ymax-ymin)*R_LAT/H
    poly = rg.poly_to_px(meta['polygon'], meta['bbox'], W, H)
    # rg.point_in_poly rather than matplotlib's Path: the same test the renderer uses, and no
    # dependency the install instructions would then have to name for one diagnostic.
    mask = np.array([[rg.point_in_poly(c+0.5, r+0.5, poly) for c in range(W)] for r in range(H)])
    return W, H, px_x, px_y, mask


def _cover(meta, mask, lon, lat):
    """Fraction of the GREEN's interior cells this pass alone puts a ground return in."""
    W, H = meta['W'], meta['H']
    x0, y0, x1, y1 = meta['bbox']
    cx = np.clip(((lon-x0)/(x1-x0)*W).astype(int), 0, W-1)
    cy = np.clip(((lat-y0)/(y1-y0)*H).astype(int), 0, H-1)
    inside = mask[cy, cx]
    if not mask.sum():
        return 0.0
    return len(set(zip(cx[inside].tolist(), cy[inside].tolist())))/float(mask.sum())


def _summary(meta, grid, lon, lat, z, zscale, putt=None):
    """Grid one pass's points on the shipped tile's own grid and return the card's numbers."""
    import render_green as rg
    W, H, px_x, px_y, mask = grid
    xmin, ymin, xmax, ymax = meta['bbox']
    gx, gy = np.meshgrid(np.linspace(xmin, xmax, W), np.linspace(ymin, ymax, H))
    zi = griddata(np.c_[lon, lat], z*zscale, np.c_[gx.ravel(), gy.ravel()],
                  method='linear').reshape(H, W)
    if not mask.any() or np.isnan(zi[mask]).all():
        return None
    arr = np.where(np.isnan(zi), float(np.nanmedian(zi[mask])), zi)
    surf, core, S = rg.green_summary(arr, mask, px_x, px_y, putt=putt)
    S['aim_deg'] = math.degrees(math.atan2(S['pdc'], -S['pdr'])) % 360.0
    S['surf'] = surf                 # kept so two passes' rendered surfaces can be differenced
    S['core'] = core
    S['nan_frac'] = float(np.isnan(zi[mask]).mean())
    return S


def _shipped_putt(meta, grid):
    """Which cells count as putting surface, decided ONCE from the shipped surface.

    Each pass covers the green a little differently, so each would classify slightly different cells
    as too steep to putt, and the comparison would then be measuring that reclassification rather
    than a difference in the ground. Holding one definition fixed for both passes isolates the
    question actually being asked: did the SURFACE change between the surveys?
    """
    import render_green as rg
    W, H, px_x, px_y, mask = grid
    arr = np.load(f"{meta['_dir']}/dem_hd/hole{meta['hole']:02d}.npy")
    if not mask.any() or np.isnan(arr[mask]).all():
        return None
    arr = np.where(np.isnan(arr), float(np.nanmedian(arr[mask])), arr)
    _surf, _core, S = rg.green_summary(arr, mask, px_x, px_y)
    return S['putt']


def check(slug, verbose=True):
    """Returns (n_greens_compared, [disagreements])."""
    os.environ['COURSE'] = slug
    for m in ('config', 'geo', 'render_green'):
        sys.modules.pop(m, None)
    import config                                        # noqa: F401  (binds the course)
    from fetch_dem_hd import laz_to_utm

    cdir = f"courses/{slug}"
    metas = {}
    for p in sorted(glob.glob(f"{cdir}/dem_hd/hole*.json")):
        m = json.load(open(p))
        if not m.get('insufficient'):
            m['_dir'] = cdir
            metas[m['hole']] = m
    if not metas:
        return 0, [], 0, 0, []
    _pt2utm, zscale = laz_to_utm()
    tz = course_tz(config.COURSE['location']['lat'], config.COURSE['location']['lon'],
                   config.COURSE.get('tz'))

    # collect ground returns per (hole, local flight date)
    per = {h: {} for h in metas}
    for lp in sorted(glob.glob(f"{cdir}/laz/*.laz")):
        with laspy.open(lp) as f:
            crs = f.header.parse_crs()
            if crs is None:
                continue
            # Separating passes means DECODING each point's date, and that decode is only valid for
            # Adjusted Standard GPS time. lidar_dates.py checks this and refuses otherwise, with the
            # worked failure: GPS WEEK TIME carries no week number, so the old interpretation landed
            # every such tile on a fabricated 2011-09-14. This tool used gps_to_utc's `adjusted=True`
            # default, i.e. it assumed what that module verifies.
            #
            # The silent failure is the reason to check rather than trust the corpus. A bad decode does
            # not produce obvious nonsense here: it collapses every point into one bogus epoch, the
            # green then has only ONE pass, the course is skipped as "not independently covered", and
            # the run reports 0 disagreements -- which reads as a pass. This tool's output is the
            # evidence in legal/09_GREEN_SURFACE_REPEATABILITY.md, so it must not be able to agree by
            # failing. All 11 corpus courses are uniformly type 1; this is for the next one.
            if not dates_recoverable(f.header):
                # REFUSED, and that must not look like "nothing to compare". Both used to return the
                # same tuple, so main() printed one extra line, added zero to every aggregate, and the
                # run still exited 0 -- a check that agrees by failing, which this tool's own docstring
                # says it must not be able to do. REFUSED is now its own outcome and main() exits
                # non-zero on it.
                print(f"    {os.path.basename(lp)}: gps_time is GPS Week Time (global_encoding bit "
                      f"0 = 0), so no absolute date is recoverable and passes cannot be separated")
                return REFUSED
            inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            for ch in f.chunk_iterator(CHUNK):
                g = np.asarray(ch.classification) == 2
                if not g.any():
                    continue
                try:
                    t = np.asarray(ch.gps_time)[g]
                except Exception:
                    # No per-point time at all: the passes cannot be separated, so this is a REFUSAL
                    # too, not an "everything agreed".
                    print(f"    {os.path.basename(lp)}: no per-point gps_time, so passes cannot be "
                          f"separated")
                    return REFUSED
                lon, lat = inv.transform(np.asarray(ch.x)[g], np.asarray(ch.y)[g])
                z = np.asarray(ch.z)[g]
                for h, m in metas.items():
                    x0, y0, x1, y1 = m['bbox']
                    s = (lon > x0) & (lon < x1) & (lat > y0) & (lat < y1)
                    if not s.any():
                        continue
                    days = np.array([gps_to_utc(v).astimezone(tz).date().isoformat()
                                     for v in t[s]])
                    for d in np.unique(days):
                        k = days == d
                        per[h].setdefault(d, []).append(
                            np.c_[lon[s][k], lat[s][k], z[s][k]])

    bad, n, skipped, flips, surfd = [], 0, 0, 0, []
    for h in sorted(metas):
        grid = _grid(metas[h])
        putt = _shipped_putt(metas[h], grid)
        got = {}
        for d, chunks in sorted(per[h].items()):
            A = np.vstack(chunks)
            if len(A) < MIN_PTS:
                continue
            cov = _cover(metas[h], grid[4], A[:, 0], A[:, 1])
            if cov < MIN_COVER:
                skipped += 1
                continue
            S = _summary(metas[h], grid, A[:, 0], A[:, 1], A[:, 2], zscale, putt=putt)
            if S:
                S['cover'] = cov
                S['n'] = len(A)
                got[d] = S
        if len(got) < 2:
            continue
        n += 1
        ds = sorted(got)
        ref = got[ds[0]]
        for d in ds[1:]:
            o = got[d]
            daim = min(abs(ref['aim_deg']-o['aim_deg']), 360-abs(ref['aim_deg']-o['aim_deg']))
            dtilt = abs(ref['tilt_pct']-o['tilt_pct'])
            over = dtilt > TOL_TILT_PP or daim > TOL_AIM_DEG
            flip = (round(ref['tilt_pct'], 1) != round(o['tilt_pct'], 1)
                    or ref['conf'] != o['conf'])
            if flip and not over:
                flips += 1
            if verbose:
                note = ("DISAGREES" if over else
                        "rounds either side of a printed digit" if flip else "ok")
                print(f"    hole {h:2d}  {ds[0]} {ref['tilt_pct']:5.2f}% ({ref['conf']:6s},"
                      f" {ref['cover']*100:3.0f}% cover)  vs  {d} {o['tilt_pct']:5.2f}%"
                      f" ({o['conf']:6s}, {o['cover']*100:3.0f}%)"
                      f"   d_tilt {dtilt:4.2f}pp  d_aim {daim:4.1f}deg   {note}")
            if over:
                bad.append((slug, h, ds[0], d, ref['tilt_pct'], o['tilt_pct'], dtilt, daim))
            # noise floor of the drawn surface, for the contour-interval claim
            both = ref['core'] & o['core']
            if both.any():
                surfd.append(np.abs(ref['surf']-o['surf'])[both]*100.0)
    return n, bad, skipped, flips, surfd


def main():
    slugs = ([os.path.basename(os.path.dirname(p)) for p in sorted(glob.glob("courses/*/course.json"))]
             if "--all" in sys.argv else [os.environ.get("COURSE") or sys.exit(
                 "set COURSE=<slug> or pass --all")])
    total, bad, skipped, flips, surfd, refused = 0, [], 0, 0, [], []
    for s in slugs:
        j = json.load(open(f"courses/{s}/course.json"))
        dates = {d for pair in j.get('lidar_flown', {}).get('tiles', {}).values() for d in pair}
        if len(dates) < 2:
            if "--all" not in sys.argv:
                print(f"  {s}: single flight date {sorted(dates) or '(unrecorded)'} "
                      f"-- nothing to cross-check")
            continue
        print(f"  {s}: survey spans {sorted(dates)}")
        res = check(s)
        if res[0] is None:
            print(f"    {s}: REFUSED -- this course could not be examined, so it is not evidence of "
                  f"agreement")
            refused.append(s)
            continue
        n, b, sk, fl, sd = res
        if n == 0:
            print("    no green was independently covered by 2 passes -- nothing comparable")
        total += n
        bad += b
        skipped += sk
        flips += fl
        surfd += sd
    print(f"\n  {total} green(s) had two passes that each covered them; {len(bad)} disagree beyond "
          f"{TOL_TILT_PP}pp tilt / {TOL_AIM_DEG:.0f}deg aim")
    print(f"  {skipped} pass/green pair(s) skipped for covering under {MIN_COVER*100:.0f}% of the "
          f"green -- a sliver cannot check a survey")
    print(f"  {flips} agreed physically but landed either side of a printed digit (e.g. 2.05 vs "
          f"2.06 -> \"2.0\" vs \"2.1\"); that is rounding, not disagreement")
    if surfd:
        a = np.concatenate(surfd)
        rms = float(np.sqrt((a**2).mean()))
        print(f"  rendered-surface noise floor from {len(surfd)} green pair(s), {len(a)} cells: "
              f"RMS {rms:.2f} cm, p95 {np.percentile(a, 95):.2f} cm, max {a.max():.2f} cm")
        print(f"  -> the card's {CINT_CM:.0f} cm contour interval is {CINT_CM/max(rms, 1e-9):.0f}x that RMS, "
              f"so adjacent contours are not inside the survey noise")
    if refused:
        print(f"\n  {len(refused)} course(s) REFUSED and contribute no evidence either way: "
              f"{', '.join(refused)}")
        print("  Exiting non-zero: a run that could not examine a course must not read as a clean one.")
    if bad:
        print("\n  A green whose two passes disagree beyond the tolerance was probably CHANGED\n"
              "  between them, which makes the shipped surface a composite of two different\n"
              "  greens. Resolve it before shipping that hole:")
        for slug, h, d1, d2, t1, t2, dt, daim in bad:
            print(f"    {slug} hole {h}: {d1} {t1:.2f}% vs {d2} {t2:.2f}% "
                  f"(d {dt:.2f}pp, aim {daim:.1f}deg)")
        return 1
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
