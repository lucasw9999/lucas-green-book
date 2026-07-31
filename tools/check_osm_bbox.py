#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Does the OSM fetch box actually cover what the cards DRAW?

Overpass returns a way whole if any one of its nodes is inside the query box, so a hole centreline
that pokes past the edge still arrives complete -- and that is exactly what makes this gap invisible.
The features BESIDE that stretch are a different matter: a bunker lying entirely outside the box is
never downloaded at all, the card simply does not draw it, and the footer's bunker count agrees with
the map because it is counted FROM the map. Nothing anywhere disagrees.

It is not hypothetical. valley-hi's box was ~46 m too tight at hole 16, and outside it OSM held:
  * a bunker 17 m from hole 16's centreline and another 14 m from hole 17's -- both inside the 45 m
    corridor the map draws, so two cards were missing a hazard that exists on the ground;
  * the real green for hole 16, 1.3 m from the one that had been hand-traced from NAIP because OSM
    "had none" -- 33 vertices against the tracing's 17;
  * the real centreline for hole 17, 3 vertices and 360 yd against a 358 yd card, where the book was
    using a hand-drawn 2-point line of 220 yd. That short line is why hole 17 alone refused its
    from-tee yardages AND its elevation: it starts 98.6 m from any tee.

So a tight box does not just drop scenery. It can silently invite a hand-traced replacement for
geometry OSM already had, and then look like a data-availability problem rather than a query problem.

What is checked: every printed hole's drawing corridor (render_hole's 45 m) must lie inside the box.
Reported in metres of overshoot per hole, worst first.

Exit codes:  0 every corridor is inside the box
             1 at least one hole draws from outside it -- widen osm_bbox and re-fetch
             2 nothing could be checked

Run:  COURSE=<slug> python3 tools/check_osm_bbox.py
      python3 tools/check_osm_bbox.py --all
"""
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CORRIDOR_M = 45.0          # render_hole.in_corridor's drawing buffer


def check_course(slug):
    """(status, [(hole, overshoot_m)]). status: 'ok' | 'short' | 'skip'."""
    for m in ("config", "render_hole", "render_green"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config                                   # noqa: E402
    import geo                                      # noqa: E402

    bbox = config.COURSE.get("osm_bbox")
    geom_p = os.path.join(config.COURSE_DIR, "osm_geom.json")
    if not bbox or not os.path.isfile(geom_p):
        print(f"{slug}: no osm_bbox or no geometry on disk -- not checked")
        return "skip", []
    S, W, N, E = bbox
    els = json.load(open(geom_p))["elements"]
    loc = config.COURSE.get("location") or {}
    try:
        lines = geo.hole_lines(els, loc.get("lat"), loc.get("lon"))
    except SystemExit as e:
        print(f"{slug}: cannot resolve hole lines -- {str(e).splitlines()[0]}")
        return "skip", []

    bad = []
    for hn, w in sorted(lines.items()):
        worst = 0.0
        for p in w["geometry"]:
            # how far OUTSIDE the box this vertex is, before the corridor is even added
            dlat = max(S - p["lat"], p["lat"] - N, 0.0)
            dlon = max(W - p["lon"], p["lon"] - E, 0.0)
            out = math.hypot(dlon * geo.mlon(p["lat"]), dlat * geo.R_LAT)
            # a vertex INSIDE the box still draws CORRIDOR_M around itself, so the margin it needs is
            # the corridor; anything less than that from an edge can be missing features too
            edge = min((p["lat"] - S) * geo.R_LAT, (N - p["lat"]) * geo.R_LAT,
                       (p["lon"] - W) * geo.mlon(p["lat"]), (E - p["lon"]) * geo.mlon(p["lat"]))
            short = max(0.0, CORRIDOR_M - edge) if out == 0 else out + CORRIDOR_M
            worst = max(worst, short)
        if worst > 0:
            bad.append((hn, round(worst)))
    bad.sort(key=lambda x: -x[1])
    if not bad:
        print(f"{slug}: every hole's {CORRIDOR_M:g} m drawing corridor is inside the fetched box")
        return "ok", []
    print(f"{slug}: {len(bad)} hole(s) draw from outside the fetched box "
          f"(worst {bad[0][1]} m short at hole {bad[0][0]})")
    for hn, m in bad:
        print(f"    hole {hn:2d}: needs {m} m more box to cover its corridor")
    return "short", bad


def main():
    if "--all" in sys.argv:
        slugs = sorted(os.path.basename(os.path.dirname(p))
                       for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
        slugs = [s for s in slugs if not s.startswith("_")]
    else:
        slug = os.environ.get("COURSE")
        if not slug:
            print("set COURSE=<slug>, or pass --all")
            return 2
        slugs = [slug]
    res = {}
    for s in slugs:
        try:
            res[s] = check_course(s)[0]
        except Exception as e:
            print(f"{s}: could not check ({type(e).__name__}: {e})")
            res[s] = "skip"
    shorts = [s for s, v in res.items() if v == "short"]
    oks = [s for s, v in res.items() if v == "ok"]
    print(f"\n{len(oks)} course(s) fully covered, {len(shorts)} with a corridor outside the box, "
          f"{len(res) - len(oks) - len(shorts)} not checked")
    if shorts:
        print("WIDEN osm_bbox AND RE-FETCH: " + ", ".join(shorts))
        print("  A tight box drops features beside the stretch that pokes out, and the card cannot\n"
              "  tell you: the footer counts what the map has, not what the course has.")
        return 1
    return 0 if oks else 2


if __name__ == "__main__":
    sys.exit(main())
