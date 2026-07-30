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
      --write records {"lidar_flown": {"first","last","tiles"}} into the course's course.json.
"""
import datetime as dt
import glob
import json
import os
import sys

import laspy

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


def tile_dates(path):
    """(first_utc, last_utc) for one LAZ tile, or None when it carries no usable GPS time.

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
        lo = hi = None
        for chunk in f.chunk_iterator(CHUNK):
            t = chunk.gps_time
            t = t[t > 0]
            if len(t):
                clo, chi = float(t.min()), float(t.max())
                lo = clo if lo is None else min(lo, clo)
                hi = chi if hi is None else max(hi, chi)
        if lo is None:
            return None
        # A tile with times spanning years is raw (unadjusted) GPS time; sanity-check the result.
        def plausible(d):
            return d is not None and (dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc) < d
                                      < dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc))
        first, last = gps_to_utc(lo, adjusted), gps_to_utc(hi, adjusted)
        if not plausible(first):
            first, last = gps_to_utc(lo, not adjusted), gps_to_utc(hi, not adjusted)
        # ...and if the OTHER interpretation is implausible too, refuse. This used to return the
        # second result unchecked, so a tile with corrupt gps_time produced a nonsense date that was
        # written into course.json by --write and PRINTED in every book as "Measured from public USGS
        # 3DEP LiDAR flown <nonsense>". The provenance line is the one claim the honesty argument
        # rests on; better to have no date than an invented one.
        if not plausible(first) or not plausible(last) or last < first:
            return None
        return first, last


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

    allfirst = alllast = None
    per_tile = {}
    for t in tiles:
        d = tile_dates(t)
        name = os.path.basename(t)
        if not d:
            print(f"  {name}: no GPS time"); continue
        first, last = d
        per_tile[name] = [day(first).isoformat(), day(last).isoformat()]
        allfirst = first if allfirst is None else min(allfirst, first)
        alllast = last if alllast is None else max(alllast, last)
        span = "" if day(first) == day(last) else f" .. {day(last)}"
        lf = first.astimezone(tz) if tz else first
        ll = last.astimezone(tz) if tz else last
        print(f"  {name}: flown {day(first)}{span}  ({lf:%H:%M}-{ll:%H:%M} {tzname.split('/')[-1]})")

    if allfirst is None:
        print("  no acquisition dates recoverable"); return 1
    d1, d2 = day(allfirst), day(alllast)
    label = d1.isoformat() if d1 == d2 else f"{d1} to {d2}"
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
                            "label": label, "tz": tzname, "tiles": per_tile}
        json.dump(j, open(p, "w"), indent=2)
        print(f"  wrote lidar_flown into {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
