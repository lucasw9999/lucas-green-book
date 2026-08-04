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
  * a bunker 17 m from hole 16's centreline and another 14 m from hole 17's -- both well inside the
    corridor the map draws, so two cards were missing a hazard that exists on the ground;
  * the real green for hole 16, 1.3 m from the one that had been hand-traced from NAIP because OSM
    "had none" -- 33 vertices against the tracing's 17;
  * the real centreline for hole 17, 3 vertices and 360 yd against a 358 yd card, where the book was
    using a hand-drawn 2-point line of 220 yd. That short line is why hole 17 alone refused its
    from-tee yardages AND its elevation: it starts 98.6 m from any tee.

So a tight box does not just drop scenery. It can silently invite a hand-traced replacement for
geometry OSM already had, and then look like a data-availability problem rather than a query problem.

What is checked: every printed hole's drawing corridor must lie inside the box, at the WIDEST
half-width render_hole selects any feature class on -- render_hole.DRAW_CORRIDOR_M, currently the 68 m
OSM tree-node radius. Reported in metres of overshoot per hole, worst first.

THIS CHECK USED TO ASK FOR 45 m, from a `CORRIDOR_M = 45.0` of its own commented "render_hole's drawing
buffer". 45 is one of nine per-class radii and was never the widest, so the pre-flight could pass a
course whose drawn corridor reached 23 m of ground the fetch never requested -- which is precisely the
failure this tool exists to catch, since a feature outside the box is never downloaded, the card does
not draw it, and the footer is counted FROM the map. The number is now derived from render_hole's own
named set rather than kept here.

FOUR COURSES ARE SHORT, and the earlier live probe NO LONGER COVERS ANY OF THEM. Current measurement,
at 68 m:

    castlewood-hill      88 m short (holes 1, 8, 7, 10, 18)            widening costs +27% query area
    castlewood-valley   103 m short (7, 12, 14, 6, 17 and 3 more)      widening costs +39% query area
    copper-valley        39 m short (hole 5)                           widening costs +2% query area
    monarch-bay          41 m short (holes 15, 10, 14)                 widening costs +5% query area

Every figure grew by the 23 m the corridor grew, and two courses gained holes that had been just inside
the old bar: hill 3 holes -> 5, monarch-bay 1 -> 3. The area costs are unchanged because they are
properties of the boxes, not of this bar.

An earlier revision of this note recorded a live Overpass probe with a 120 m-widened box finding no
drawn feature missing, at "28 m short (holes 6, 17, 18, 8, 13)" for hill and "28 m" for valley. Those
figures never matched, and now none of the four does: at 45 m the shortfalls read 65, 80, 16 and 18, and
at the corridor actually drawn they read 88, 103, 39 and 41. Whatever that probe checked, it did not
check this.

Treat all four as UNVERIFIED. The reassurance was the dangerous part -- a stale "already investigated"
is worse than no note, because it stops the next person looking. valley-hi's 46 m turned out to hide two
bunkers inside a drawn corridor, a green, and a hole line, so a shortfall of 39-103 m is not obviously
harmless.

Still not widened, and the reason is unchanged: a re-fetch pulls whatever else has moved upstream in OSM
since the last one, so it would change four books for reasons unrelated to the fix. But that is a
deferral now, not a clearance.

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


def check_course(slug):
    """(status, [(hole, overshoot_m)]). status: 'ok' | 'short' | 'skip'."""
    for m in ("config", "render_hole", "render_green"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config                                   # noqa: E402
    import geo                                      # noqa: E402
    # The corridor half-width comes from the engine that DRAWS it, never from a second copy here. This
    # module carried `CORRIDOR_M = 45.0` commented "render_hole.in_corridor's drawing buffer", and 45
    # was never the widest of render_hole's nine per-class radii -- OSM tree nodes reach 68 m -- so this
    # pre-flight could pass a course whose drawn corridor took in 23 m of ground the fetch never
    # requested. render_hole.DRAW_CORRIDOR_M is the max of its named set, so widening any one class
    # widens this check with it. Imported after COURSE is bound, because render_hole reads config at
    # import time.
    import render_hole                              # noqa: E402
    corridor_m = render_hole.DRAW_CORRIDOR_M

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
            out = math.hypot(dlon * geo.mlon(p["lat"]), dlat * geo.mlat(p["lat"]))
            # a vertex INSIDE the box still draws corridor_m around itself, so the margin it needs is
            # the corridor; anything less than that from an edge can be missing features too
            edge = min((p["lat"] - S) * geo.mlat(p["lat"]), (N - p["lat"]) * geo.mlat(p["lat"]),
                       (p["lon"] - W) * geo.mlon(p["lat"]), (E - p["lon"]) * geo.mlon(p["lat"]))
            short = max(0.0, corridor_m - edge) if out == 0 else out + corridor_m
            worst = max(worst, short)
        if worst > 0:
            bad.append((hn, round(worst)))
    bad.sort(key=lambda x: -x[1])
    if not bad:
        print(f"{slug}: every hole's {corridor_m:g} m drawing corridor is inside the fetched box")
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
