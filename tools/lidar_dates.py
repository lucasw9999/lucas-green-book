#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Decode the TRUE LiDAR acquisition date from the point records of a course's LAZ tiles.

Why this exists: a USGS project NAME is not a date, and the LAS header's creation date is the
DELIVERY date, not the flight. Both mislead. Two of our own courses were mislabelled --
"Alameda 2021" was flown 2019-08-14 and "CA Central Valley LiDAR 2016" was flown 2017-12-16 --
and Philadelphia CC's greens were flown 2024-12-17, in the middle of a rebuild that did not
finish until 2025-06-02. A green map is only as current as the flight under it, so the flight
date belongs in the book.

The real date lives in each point's gps_time. When global_encoding.gps_time_type == 1 the values
are Adjusted Standard GPS time (standard GPS seconds - 1e9), counted from the GPS epoch
1980-01-06, which runs ahead of UTC by the accumulated leap seconds (18 s since 2017-01-01).

Run:  COURSE=<slug> python3 tools/lidar_dates.py [--write]
      --write records {"lidar_flown": {"first","last","label","tz","basis","tiles"}} into
      the course's course.json. `basis` names what the range was measured over.
"""
import datetime as dt
import glob
import json
import os
import sys

import laspy
import numpy as np

try:
    from zoneinfo import ZoneInfo
except ImportError:                      # pragma: no cover - stdlib since 3.9
    ZoneInfo = None

GPS_EPOCH = dt.datetime(1980, 1, 6, tzinfo=dt.timezone.utc)
LEAP_SECONDS = 18          # GPS - UTC since 2017-01-01; LiDAR here is all post-2017.
                           # A pre-2017 survey would need 17 (or 16 before 2015-07-01). The error is
                           # ONE SECOND, so it can only change the printed DATE for a flight within a
                           # second of midnight UTC -- checked, none of ours is. Revisit only if a
                           # pre-2017 course is ever added.
# No sample cap. Reading only the first 2M points of a tile (2% of the largest one here) made the
# tool report a NARROWER survey than the data holds, and that narrower claim was printed: Callippe's
# book said "flown 2021-06-21", one day, for a survey that ran 2021-06-21 to 2021-07-02 -- twelve.
# Castlewood Valley was wrong the same way. A full scan of every tile costs 6-8 s per course and the
# tool runs once per course, so there is nothing to buy with a prefix.
CHUNK = 2_000_000
MAX_TILE_SPAN_DAYS = 730   # a tile whose gps_time spans more than two years is not one acquisition
# Collar around a green's own footprint, for deciding which points DATE it. Deliberately wider than
# the 12 m margin fetch_dem_hd.py builds the surface from (MARGIN_M): the question here is "was this
# tile flown over this green", and a flight line that clipped the collar is the same pass. Note the
# consequence and do not overstate it -- a point 20 m out can widen the printed range without having
# contributed to the surface, so `basis` says "points within 30 m of a green" rather than claiming
# these are the returns the surface was built from.
GREEN_PAD_M = 30.0


def green_rings(course_dir):
    """Each green's outline as [(lon, lat), ...], from osm_geom.json. [] if OSM is not fetched."""
    try:
        els = json.load(open(os.path.join(course_dir, "osm_geom.json")))["elements"]
    except Exception:
        return []
    return [[(p["lon"], p["lat"]) for p in e["geometry"]]
            for e in els
            if e.get("geometry") and (e.get("tags") or {}).get("golf") == "green"]


def green_boxes(crs, rings):
    """Each green's padded footprint in the tile's own CRS, or None if the greens cannot be placed.

    The pad is converted into the CRS's own units: these tiles are not all metric -- Callippe's are
    in US survey feet -- and a 30 that means feet where metres were intended shrinks the collar to
    9 m."""
    if crs is None or not rings:
        return None
    try:
        from pyproj import Transformer
        T = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        ax = crs.axis_info[0] if crs.axis_info else None
        unit = ((getattr(ax, "unit_name", "") or "").lower() if ax else "")
        per_unit = getattr(ax, "unit_conversion_factor", None) if ax else None
    except Exception:
        return None
    # The pad is in METRES, so the axis unit must be a LENGTH. Defaulting a missing or non-length
    # factor to 1.0 is the guess geo.vertical_scale refuses to make for the same reason: a geographic
    # CRS reports degrees, and a 30 m pad would become ~1719 units, so every point in the tile would
    # count as "over a green" while `basis` still published "points within 30 m of a green". Refuse
    # instead -- the caller reports the tile as unplaceable and records that in the basis.
    if not per_unit or per_unit <= 0 or not any(
            k in unit for k in ("met", "foot", "feet", "ft", "yard", "chain", "link", "mile")):
        return None
    pad = GREEN_PAD_M / per_unit
    out = []
    for ring in rings:
        xs, ys = [], []
        for lon, lat in ring:
            x, y = T.transform(lon, lat)
            if x in (float("inf"), float("-inf")) or x != x:
                return None
            xs.append(x); ys.append(y)
        out.append((min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad))
    return out or None


def course_tz(lat, lon, override=None):
    """The timezone whose calendar day is the FLIGHT day, for a course at lat/lon.

    Topographic LiDAR is often flown at night, so the UTC date can be the day AFTER the local flight
    date. Bay View's entire survey ran 20:39-21:55 local on 2020-04-14 and the book printed "flown
    2020-04-15"; Philadelphia's and The Reserve's ranges were off by a day at one end each. USGS
    records the local flight day, so the local day is the one a reader can check against the flight
    log.

    Resolved from a CONUS longitude band, which is exact for every course here and wrong only near a
    zone boundary or outside the US. course.json may set "tz" to override it; None means "leave the
    date in UTC and say so" rather than guess."""
    if override:
        return ZoneInfo(override) if ZoneInfo else None
    if ZoneInfo is None or lat is None or lon is None:
        return None
    if not (-125.0 <= lon <= -66.9 and 24.0 <= lat <= 49.5):
        return None                       # outside CONUS: do not guess, keep UTC
    name = ("America/Los_Angeles" if lon < -114 else
            "America/Denver" if lon < -102 else
            "America/Chicago" if lon < -87 else "America/New_York")
    return ZoneInfo(name)


def gps_to_utc(gps_seconds, adjusted=True):
    """Adjusted Standard GPS time (or raw standard GPS time) -> UTC datetime, or None.

    Returns None instead of raising for a value datetime cannot represent. A corrupt gps_time (or the
    wrong interpretation of a valid one) can land tens of thousands of years out, and
    timedelta/datetime raises OverflowError there -- which crashed the tool with a traceback rather
    than reporting "no usable GPS time" for that tile."""
    standard = gps_seconds + 1_000_000_000 if adjusted else gps_seconds
    try:
        return GPS_EPOCH + dt.timedelta(seconds=standard - LEAP_SECONDS)
    except (OverflowError, OSError, ValueError):
        return None


def tile_dates(path, rings=()):
    """(first, last, n_over_greens, crs_placeable, whole_first, whole_last) for one LAZ tile, or
    None when it carries no usable GPS time.

    `first`/`last` are narrowed to the points lying over a green when `rings` is supplied and any
    were found; `whole_first`/`whole_last` always span every point in the tile, so the caller can
    contrast the two. `crs_placeable` is False when the tile declares no CRS, which is a fact about
    us rather than about the survey.

    global_encoding bit 0 == 0 means GPS WEEK TIME: seconds since the start of the current GPS week,
    0..604800, with the week number recorded nowhere in the file. The absolute date is therefore NOT
    recoverable and the only honest answer is None. The old code treated bit 0 == 0 as raw standard
    GPS time, which put the value near 1980, failed the 2000-2040 window, flipped to the +1e9
    interpretation and landed on 1980-01-06 + 1e9 s = 2011-09-14 -- INSIDE the plausibility window.
    So every week-time tile silently produced a fabricated September-2011 flight date."""
    with laspy.open(path) as f:
        gtt = int(getattr(f.header.global_encoding, "gps_time_type", 0))
        if "gps_time" not in [d.name for d in f.header.point_format.dimensions]:
            return None
        if gtt == 0:
            print(f"    {os.path.basename(path)}: gps_time is GPS Week Time "
                  f"(global_encoding bit 0 = 0); no absolute date is recoverable from it")
            return None
        adjusted = True
        crs = f.header.parse_crs()
        boxes = green_boxes(crs, rings) if rings else None
        crs_ok = not rings or boxes is not None
        # Skip the GREEN FILTERING for a tile whose HEADER bbox cannot contain a single green point.
        # A point inside a padded green box must lie inside the header bbox, so nothing is lost --
        # this is the same header-extent fact lidar_coverage.py is built on. Without it, a
        # neighbouring tile that feeds no green had its x/y scaled and every chunk run through the
        # per-green box arithmetic for a result that could only ever be empty. gps_time is still read
        # for every chunk, because the whole-tile range is reported alongside -- so this saves the
        # coordinate work, not the decompression. Measured end to end: castlewood-hill 16.6 s -> 11.8 s,
        # the-reserve 4.0 s -> 2.6 s, same dates. The Reserve's t390135.laz is the case -- 26.8M
        # points, zero over any green.
        if boxes:
            hb = f.header
            if all(x1 < hb.x_min or x0 > hb.x_max or y1 < hb.y_min or y0 > hb.y_max
                   for x0, x1, y0, y1 in boxes):
                boxes = None
        # union of the green boxes: one cheap mask before the per-green ones. Each green otherwise
        # costs 8 full-length array ops on a 2M-point chunk -- 26 ms for 18 greens, 43 ms for 30,
        # as expensive as decompressing the chunk. Any box hit implies a union hit, so the selection
        # is identical.
        ubox = (min(b[0] for b in boxes), max(b[1] for b in boxes),
                min(b[2] for b in boxes), max(b[3] for b in boxes)) if boxes else None
        lo = hi = None            # over points near a green, when we can tell
        wlo = whi = None          # over the whole tile, always
        nnear = 0
        for chunk in f.chunk_iterator(CHUNK):
            t = np.asarray(chunk.gps_time)
            keep = t > 0
            if not keep.any():
                continue
            tk = t[keep]                      # one boolean-index copy, not two
            wlo = min(wlo, float(tk.min())) if wlo is not None else float(tk.min())
            whi = max(whi, float(tk.max())) if whi is not None else float(tk.max())
            if boxes is None:
                continue
            x, y = np.asarray(chunk.x), np.asarray(chunk.y)
            cand = keep & (x >= ubox[0]) & (x <= ubox[1]) & (y >= ubox[2]) & (y <= ubox[3])
            idx = np.flatnonzero(cand)
            if not idx.size:
                continue
            xs, ys = x[idx], y[idx]
            sel = np.zeros(idx.size, dtype=bool)
            for x0, x1, y0, y1 in boxes:
                sel |= (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
            if sel.any():
                tn = t[idx[sel]]
                nnear += int(tn.size)
                lo = min(lo, float(tn.min())) if lo is not None else float(tn.min())
                hi = max(hi, float(tn.max())) if hi is not None else float(tn.max())
        near = lo is not None
        if not near:
            # No points over any green. Either this tile is a neighbour that feeds nothing, or we
            # could not place the greens in its CRS. Report the whole-tile range and let the caller
            # decide -- it must NOT be folded into the flight range the book prints.
            lo, hi = wlo, whi
        if lo is None:
            return None
        # A tile with times spanning years is raw (unadjusted) GPS time; sanity-check the result.
        def plausible(d):
            return d is not None and (dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc) < d
                                      < dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc))
        first, last = gps_to_utc(lo, adjusted), gps_to_utc(hi, adjusted)
        if not plausible(first):
            adjusted = not adjusted
            first, last = gps_to_utc(lo, adjusted), gps_to_utc(hi, adjusted)
        # The WHOLE-tile range, kept separate. main() used to build its "over whole tiles the range
        # would be" comparison out of the returned first/last -- which for a feeding tile is already
        # narrowed to the green points -- so the audit line understated the very range it exists to
        # contrast against.
        whole_first, whole_last = gps_to_utc(wlo, adjusted), gps_to_utc(whi, adjusted)
        # ...and if the OTHER interpretation is implausible too, refuse. This used to return the
        # second result unchecked, so a tile with corrupt gps_time produced a nonsense date that was
        # written into course.json by --write and PRINTED in every book as "Measured from public USGS
        # 3DEP LiDAR flown <nonsense>". The provenance line is the one claim the honesty argument
        # rests on; better to have no date than an invented one.
        if not plausible(first) or not plausible(last) or last < first:
            return None
        # A single tile cannot span years. One junk-but-positive gps_time is enough to break the
        # range: with adjusted time, 1.0 decodes to 1980-01-06 + 1e9 s = 2011-09-14, which IS inside
        # the 2000-2040 window and so cannot be excluded by any plausibility filter -- it is
        # indistinguishable from a genuine 2011 flight. What gives it away is the SPAN. A real
        # acquisition is days; anything past a couple of years means the times in this tile are not
        # all the same clock, and the honest answer is no date for it.
        if (last - first) > dt.timedelta(days=MAX_TILE_SPAN_DAYS):
            print(f"    {os.path.basename(path)}: gps_time spans {(last - first).days} days "
                  f"({first.date()}..{last.date()}) -- not one acquisition; refusing to date it")
            return None
        return first, last, nnear, crs_ok, whole_first, whole_last


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
    tiles = sorted(glob.glob(f"{config.COURSE_DIR}/laz/*.laz"))
    if not tiles:
        print(f"{config.SLUG}: no LAZ tiles on disk"); return 1

    loc = config.COURSE.get("location") or {}
    tz = course_tz(loc.get("lat"), loc.get("lon"), config.COURSE.get("tz"))
    tzname = getattr(tz, "key", None) or "UTC"
    print(f"{config.SLUG}  ({len(tiles)} tiles)  dates in {tzname}")

    def day(d):
        """The calendar day of the flight, in the course's own timezone."""
        return (d.astimezone(tz) if tz else d).date()

    # Date the points that actually built the green surfaces, not whole tiles. The tile set is
    # chosen by bbox overlap with the whole course, so it routinely includes neighbours that cover no
    # green at all -- and the union over whole tiles then widens the range the book prints. Measured
    # at The Reserve: t390135.laz spans 2017-12-16..2018-01-21 and has NO point within 60 m of any
    # green (its nearest green is 1336 m from its earliest point, 1382 m from its latest), while the
    # three tiles that do feed greens span only 2017-12-16..2017-12-17. The book printed "flown
    # 2017-12-15 to 2018-01-21" -- 38 days -- for greens flown on two.
    rings = green_rings(config.COURSE_DIR)
    if not rings:
        print("  (no green geometry in osm_geom.json -- dating whole tiles)")

    allfirst = alllast = None
    wholefirst = wholelast = None
    per_tile = {}
    nskip = 0
    unplaceable = []
    for t in tiles:
        d = tile_dates(t, rings)
        name = os.path.basename(t)
        if not d:
            print(f"  {name}: no GPS time"); continue
        first, last, nnear, crs_ok, wfirst, wlast = d
        # accumulate the TRUE whole-tile range, not the green-narrowed one
        wholefirst = wfirst if wholefirst is None else min(wholefirst, wfirst)
        wholelast = wlast if wholelast is None else max(wholelast, wlast)
        span = "" if day(first) == day(last) else f" .. {day(last)}"
        lf = first.astimezone(tz) if tz else first
        ll = last.astimezone(tz) if tz else last
        if rings and not nnear:
            nskip += 1
            # Distinguish the two reasons. "No points over a green" is a fact about the data; "could
            # not place the greens" is a fact about us, and reporting the second as the first would
            # blame the survey for our own missing CRS. tile_dates already parsed the header, so it
            # reports which case it hit rather than making us reopen the file to find out.
            if not crs_ok:
                why = "no CRS in its header, so the greens cannot be placed in it"
                unplaceable.append(name)
            else:
                why = "no points over a green"
            print(f"  {name}: {why} -- NOT counted in the flight range "
                  f"(whole tile {day(first)}{span})")
            continue
        per_tile[name] = [day(first).isoformat(), day(last).isoformat()]
        allfirst = first if allfirst is None else min(allfirst, first)
        alllast = last if alllast is None else max(alllast, last)
        over = f", {nnear:,} pts over greens" if rings else ""
        print(f"  {name}: flown {day(first)}{span}  "
              f"({lf:%H:%M}-{ll:%H:%M} {tzname.split('/')[-1]}{over})")

    basis = f"points within {GREEN_PAD_M:g} m of a green"
    if unplaceable:
        # A green-feeding tile excluded because WE could not read its CRS narrows the printed range
        # for our own reason, not the survey's. Say so in the record rather than letting `basis` claim
        # the range was measured over the greens when some tiles never got the chance.
        basis += f"; {len(unplaceable)} tile(s) excluded for declaring no CRS ({', '.join(unplaceable)})"
    if allfirst is None:
        if wholefirst is None:
            print("  no acquisition dates recoverable"); return 1
        # Every tile missed every green. That is worth saying rather than silently falling back: it
        # means no green was built from these returns, or the greens could not be placed in the tile
        # CRS. The whole-tile range is the honest best available, labelled as such.
        print("  !! no tile holds points over a green; falling back to the whole-tile range")
        allfirst, alllast = wholefirst, wholelast
        basis = "whole tiles (no points found over any green)"
    elif not rings:
        basis = "whole tiles (no green geometry available)"
    d1, d2 = day(allfirst), day(alllast)
    label = d1.isoformat() if d1 == d2 else f"{d1} to {d2}"
    if nskip:
        w1, w2 = day(wholefirst), day(wholelast)
        wl = w1.isoformat() if w1 == w2 else f"{w1} to {w2}"
        print(f"  ({nskip} tile(s) cover no green; over whole tiles the range would be {wl})")
    print(f"  => ACQUIRED: {label}")
    stated = config.COURSE.get("dem_source", "")
    for yr in (str(y) for y in range(2010, 2031)):
        if yr in stated and yr != str(d1.year):
            print(f"  !! dem_source says '{yr}' but the points were flown {d1.year} "
                  f"-- the project name is not the flight date")
            break

    if "--write" in sys.argv:
        p = os.path.join(config.COURSE_DIR, "course.json")
        j = json.load(open(p))
        j["lidar_flown"] = {"first": d1.isoformat(), "last": d2.isoformat(),
                            "label": label, "tz": tzname, "basis": basis, "tiles": per_tile}
        # Atomic: course.json is HAND-AUTHORED -- the scorecard transcription, the bbox, the tee
        # table -- and nothing can regenerate it. Writing in place means a crash or a full disk
        # truncates it, in a directory the project documents as unrecoverable. The dem_hd and
        # trees_lidar metas are written in place deliberately: those are derived from the LAZ and a
        # re-run rebuilds them.
        tmp = p + ".part"
        with open(tmp, "w") as f:
            json.dump(j, f, indent=2)
        os.replace(tmp, p)
        print(f"  wrote lidar_flown into {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
