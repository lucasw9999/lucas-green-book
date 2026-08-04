#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Shared geodesy helpers.

This module exists because the same two facts were previously derived independently in
fetch_dem_hd.py and fetch_trees.py, and a fix to one had to be hand-applied to the other. A
divergence between them would be silent and serious: both feed the same green surface.

It now also owns the project's two LOCAL GROUND SCALES -- `mlat` and `mlon` -- for the same reason
carried to its conclusion: they were re-declared as literals in nine other modules, so the value
could not be corrected without correcting nine copies, and it was not corrected for two audits
running. See the note below the imports.
"""
import math

# --- THE PROJECT'S FIGURE OF THE EARTH, AND ITS ONLY COPY ------------------------------------------
# Every horizontal length this book prints is a difference of DEGREES multiplied by one of the two
# functions below: green depth and width, the grey 5-yd ladder and the printed 5-yd scale bar, green
# tilt % (a rise over one of these runs), the hole map's yardage ticks and the carries measured off
# them, and the Rule 4.3 print scale the pocket edition claims to conform to. So `mlat` and `mlon` are
# the figure of the Earth for this project, and the whole point of this section is that there is now
# exactly ONE copy of them.
#
# There used to be ten, and the duplication was the reason the value stayed wrong through two audits
# that found it. The retired model was the constant pair `R_LAT = 111320.0` with a longitude scale of
# 111320.0*cos(lat), re-declared as a literal in nine shipped modules and imported from none of them.
# Those nine modules once carried the literal: fetch_dem.py, fetch_dem_hd.py, fetch_hole_elev.py,
# fetch_osm.py, fetch_trees.py, render_green.py, render_hole.py, tools/check_scale.py,
# tools/verify_elevation.py. Two of fetch_osm.py's were INLINE inside a distance calculation and not
# named R_LAT, so an audit that grepped for the NAME found eight and only one that grepped for the
# NUMBER found all nine. There was no knob to turn; that is an argument for introducing one, which is
# what this is, not for leaving the number wrong. All nine now import from here, except that
# fetch_trees.py's pair was DEAD -- declared at module level and never referenced by anything in the
# file -- so it was deleted rather than migrated. A test asserts no module re-declares either scale.
#
# WHY THE RETIRED PAIR WAS WRONG, measured rather than assumed. The retired model used 111320.0 m/deg
# of latitude and 111320.0*cos(lat) m/deg of longitude: at 37.8N -- the middle of this corpus -- the
# true local scales are 110992.70 m/deg of latitude and 88070.46 m/deg of longitude, so that model ran
# +0.295% LONG in latitude and -0.125% SHORT in longitude. That is a 0.42 pp spread BETWEEN ITS OWN TWO
# AXES, half again the 0.84% raster anisotropy render_green.screen_m_per_unit exists to decompose, so
# the pipeline was internally inconsistent by more than the effect it had just been corrected for.
#
# WHY PER-AXIS LOCAL SCALES ARE THE RIGHT FIX rather than switching to a projected CRS. fetch_dem_hd
# samples a green's cell centres linear in lon/lat -- `lon_g = xmin + us*(xmax-xmin)` -- so a green's
# array genuinely IS a plate-carree grid, and the local scales of such a grid are exactly the meridian
# radius of curvature M and the parallel arc N*cos(lat). They are LOCAL scales, not a one-degree
# geodesic: a geodesic across a whole degree cuts inside the parallel and reads 88070.04 against
# 88070.46 at 37.8N. Confirmed by measurement, not by argument: over all 198 built greens these scales
# reproduce the true WGS84 geodesic length of the very front-to-back line each card measures to a median
# 5.8e-07 yd and a worst 1.48e-05 yd, where the retired sphere differed from that same truth by a median
# 0.0405 yd, p95 0.0939 and worst 0.1112.
#
# WHAT THE MIGRATION MOVED ON PAPER. Today no printed depths land on the wrong side of a half yard.
# Four did under the retired model, and each printed one yard DEEPER than the ground: copper-valley 16
# printed 37 against a ground length of 36.489, micke-grove 13 printed 20 against 19.450, monarch-bay 1
# printed 35 against 34.451 on a seamless-DEM green, and the-reserve 7 printed 33 against 32.438. Two of
# those four -- copper-valley 16 and micke-grove 13 -- were depths the earlier pixel-anisotropy fix had
# moved the WRONG WAY, because it corrected the raster while leaving the datum wrong. The four cards are
# named for a reader, not just here, in legal/11_HORIZONTAL_EARTH_MODEL.md, and a test re-measures every
# figure in that record off the built corpus.
#
# The hole map gained more than the green card did, and here the measurement has to match the question a
# tick asks. A to-green tick is not drawn at a mapped point: render_hole places it where the drawn
# centreline crosses the circle of that radius about the green centroid. So the honest figure is the
# printed radius against the TRUE WGS84 geodesic to the point the tick lands on. Over the 861 radius
# crossings the 198 drawn centrelines have, the retired model was out by up to 0.2962 yd at the 100 yd
# tick, 0.4426 at the 150 yd tick, 0.5931 at the 200 yd tick, 0.7421 at the 250 yd tick and 0.8891 at the
# 300 yd tick; on these scales the worst at those same five radii is 0.0013, 0.0018, 0.0021, 0.0022 and
# 0.0019 yd. Out to the furthest point any centreline reaches, 595.8 yd, the retired model's worst over
# all 589 hole-line vertices -- 598 counting the duplicate refs hole_lines() resolves -- was 1.5502 yd
# against 0.0023 yd now.
#
# THE FIGURES THIS NOTE CARRIED UNTIL 2026-08-04 WERE WRONG IN BOTH DIRECTIONS, and the correction is
# recorded because nothing re-derived them. It said 0.43 yd at 100, 0.73 at 200, 0.99 at 300, and
# "the same 391 vertices" out by 0.0003/0.0013/0.0027/0.0077. The retired figures were impossible: this
# pair scaled both axes off one constant, so any length it measured was out by a fraction between its two
# axis errors -- at worst +0.2975% over these vertices -- and 0.43 yd at a 100 yd radius needs 0.43%.
# They were the worst error anywhere in the 50-yard BAND above each tick, printed as the error AT it. The
# new figures were measured with the scales anchored at the GREEN rather than at the line centroid where
# render_hole takes them, which is why they grew quadratically. And "391" named a population nothing in
# this tree produces. The approximation that was documented here as "deliberate and quantified" is still
# two orders of magnitude smaller than the integers it feeds -- but it is now a figure a reader of
# legal/11_HORIZONTAL_EARTH_MODEL.md can check, and a test re-derives every cell of that table.


def _wgs84():
    """(semi-major axis in metres, first eccentricity squared) of WGS84, cached.

    Asked of pyproj rather than transcribed, for the same reason `vertical_scale` asks it about units:
    a hand-copied ellipsoid parameter is a figure of the Earth that nothing checks. Cached because
    `mlat`/`mlon` are called per green, per centreline vertex and per candidate hole line, and building
    a CRS object each time would be the one avoidable cost in a pure-arithmetic helper.
    """
    global _WGS84
    if _WGS84 is None:
        from pyproj import CRS
        ell = CRS.from_epsg(4326).ellipsoid
        a = ell.semi_major_metre
        f = 1.0 / ell.inverse_flattening
        _WGS84 = (a, f * (2.0 - f))
    return _WGS84


_WGS84 = None


def mlat(lat):
    """Metres per degree of LATITUDE at a given latitude, on WGS84.

    The meridian radius of curvature M, which is the true north-south ground scale of a grid spaced
    uniformly in degrees -- see the note above for why that is the right quantity and for what the
    retired constant 111320.0 cost the printed page.
    """
    a, e2 = _wgs84()
    s2 = math.sin(math.radians(lat)) ** 2
    return a * (1.0 - e2) / (1.0 - e2 * s2) ** 1.5 * math.pi / 180.0


def mlon(lat):
    """Metres per degree of LONGITUDE at a given latitude, on WGS84.

    The parallel arc N*cos(lat), N being the prime-vertical radius of curvature.
    """
    a, e2 = _wgs84()
    p = math.radians(lat)
    return a / math.sqrt(1.0 - e2 * math.sin(p) ** 2) * math.cos(p) * math.pi / 180.0


def utm_epsg(lon):
    """NAD83 UTM zone EPSG code for a longitude (26910 = CA zone 10, 26919 = MA zone 19)."""
    return "EPSG:%d" % (26900 + int((lon + 180) / 6) + 1)


def vertical_scale(src):
    """Factor converting the point cloud's Z unit to METRES, from the CRS itself.

    This must never be guessed. It was previously inferred by substring-matching the CRS name for
    "foot"/"ftus", which happens to work when laspy hands back full WKT (all current tiles) but
    fails silently for a bare EPSG code -- and a bare code is exactly what course.json's
    `lidar_crs` override supplies. EPSG:2227 and EPSG:6420 are genuinely US survey foot, yet
    str() gives only "EPSG:2227", so the match missed and Z stayed unscaled: every slope,
    contour and arrow inflated by 3.28x, with nothing to reveal it.

    So ask pyproj for the actual axis unit. Prefer the vertical axis of a compound CRS; fall back
    to the horizontal unit (in a LAS file Z shares the horizontal unit when the CRS is 2D); and
    RAISE rather than assume metres if neither is available -- a loud stop beats a 3.28x error.
    """
    from pyproj import CRS
    try:
        crs = src if hasattr(src, "axis_info") else CRS.from_user_input(src)
    except Exception as e:
        raise SystemExit(f"cannot interpret {src!r} as a CRS ({type(e).__name__}: {e}).\n"
                         f"  Check \"lidar_crs\" in course.json.")

    vert = None
    if getattr(crs, "is_compound", False) and len(crs.sub_crs_list) >= 2:
        vsub = crs.sub_crs_list[-1]                    # the vertical component
        if vsub.axis_info:
            vert = vsub.axis_info[-1]
    if vert is None and crs.axis_info:
        # 2D or unusual: the last axis is vertical on a 3D CRS, otherwise Z follows the horizontal
        vert = crs.axis_info[-1]

    factor = getattr(vert, "unit_conversion_factor", None) if vert is not None else None
    unit = (getattr(vert, "unit_name", "") or "").lower() if vert is not None else ""
    # The unit must be a LENGTH. A geographic CRS reports degrees, whose conversion factor is
    # 0.0174533 (degrees->radians) -- taking that as a vertical scale would shrink every elevation
    # by 57x and look like a nearly flat green rather than an error.
    is_length = any(k in unit for k in ("met", "foot", "feet", "ft", "yard", "chain", "link", "mile"))
    if not factor or factor <= 0 or not is_length:
        raise SystemExit(
            f"cannot determine the vertical LENGTH unit of {crs.name!r} ({src!r}); "
            f"got unit={unit!r} factor={factor!r}.\n"
            f"  Refusing to assume metres: if this cloud is in US survey feet, every slope would be\n"
            f"  printed 3.28x too steep. Set \"lidar_crs\" in course.json to a CRS that carries its\n"
            f"  units (a compound EPSG code or the full WKT), then re-run.")
    return factor


def sole_laz_crs(laz_dir):
    """The ONE CRS every tile in `laz_dir` agrees on, or None when no tile carries one.

    Refuses a directory holding more than one, naming the two tiles and the two CRSs. Here, in the
    module that exists because fetch_dem_hd and fetch_trees each derived the same CRS facts
    independently -- because THREE stages need this answer and each read it its own way:

      * fetch_dem_hd.laz_to_utm applies one transform and one vertical scale to every tile, and used to
        break out of its scan at the first tile it could read a CRS from. Measured on a mixed directory:
        the ftUS scale 0.3048006096 applied to a metre tile threw its points ~1.9e6 m away, where the
        bbox prefilter dropped them in silence and the run printed "fed 0 greens". Had the two been
        closer, the surface would have been built from Z scaled by 3.28.
      * fetch_hole_elev read the first tile's CRS TWICE -- once to place each hole's tee anchor for the
        ground returns over the tee pad, once for the vertical scale -- and assumed the rest matched. The
        far case prints no height for the hole; the near case prints a confident figure 3.28x wrong.
      * fetch_trees.laz_to_utm is still a hand copy of the pre-fix version and still takes the first CRS
        it can read. It draws markers, not numbers, which is why the stops went to the other two first.

    Reachable by ordinary use rather than hypothetical: nothing ever removes a previously-fetched
    project's tiles from laz/, and both families are live in this corpus -- California zone 3 ftUS on 5
    courses, UTM 10N/18N metres on 6. All 11 courses with tiles resolve one CRS today, so this is latent.

    A tile whose header will not parse contributes no CRS and is not an error by itself; deciding what to
    do with NO CRS at all belongs to the caller, which is why this returns None rather than raising --
    fetch_dem_hd refuses, and course.json's `lidar_crs` override can answer for it.
    """
    import glob as _glob
    import os as _os
    import laspy
    read = []                               # (tile name, CRS) for every tile that carries one
    for t in sorted(_glob.glob(_os.path.join(laz_dir, "*.laz"))):
        try:
            with laspy.open(t) as f:
                c = f.header.parse_crs()
        except Exception:
            continue                        # unreadable header: it contributes no CRS, that is all
        if c:
            read.append((_os.path.basename(t), c))
    for name, c in read[1:]:
        if c != read[0][1]:
            n0, c0 = read[0]

            def _z(crs):
                # the vertical scale is the concrete thing that goes wrong, but a CRS whose unit
                # vertical_scale refuses to read must not replace THIS message with that one
                try:
                    return "Z x %s -> m" % vertical_scale(crs)
                except SystemExit:
                    return "vertical unit unreadable"
            raise SystemExit(
                "the tiles in %s are not all in one CRS, and one transform is applied to all of\n"
                "  them:\n    %s: %s (%s)\n    %s: %s (%s)\n"
                "  Refusing to project one through the other: on this pair the points land far enough\n"
                "  apart that the misplaced tile is silently dropped by the bbox prefilter, and a\n"
                "  closer pair would build the surface from Z values scaled by the wrong unit. Remove\n"
                "  the tiles that do not belong to this course's LiDAR project and re-run."
                % (laz_dir, n0, c0.name, _z(c0), name, c.name, _z(c)))
    return read[0][1] if read else None


# The furthest a hole's line endpoint legitimately sits from its green's centroid, measured across
# all 198 built greens: worst 11.1 m (philadelphia h12), median 2.0 m. The documented mis-binding --
# bay-view hole 9 attaching to hole 7's green -- was 47.8 m away. 40 m therefore catches that with
# room to spare while clearing the worst real case by 3.6x.
GREEN_BIND_MAX_M = 40.0


def assert_one_green_per_hole(bound, label=""):
    """Refuse if two holes bound to the SAME green. `bound` is {hole_number: green_element}.

    The max_m cap in match_green catches a hole reaching for a FAR green -- bay-view h9 to h7's
    green, 47.8 m -- but it cannot catch the near case, and the near case is the more likely one. If
    a hole's own green disappears from the OSM extract while a neighbour's green sits inside the cap,
    both holes bind there, both cards print that surface, and one of them is a confident read of the
    wrong putting green. Nothing in match_green can see this: it is called once per hole and has no
    view of the others.

    Measured across all 11 built courses: 0 greens are bound to more than one hole today, and the
    furthest legitimate bind is 11.1 m, so this only ever fires on a real fault.
    """
    seen = {}
    clash = []
    for hn in sorted(bound):
        g = bound[hn]
        # `g.get("id", id(g))` returned None when the key was PRESENT but null, collapsing every
        # such green onto one key and inventing a clash. The default only covers an absent key.
        gid = g.get("id")
        key = gid if gid is not None else id(g)
        if key in seen:
            clash.append((seen[key], hn, key))
        else:
            seen[key] = hn
    if clash:
        lines = "\n".join(f"    green {k} is bound to BOTH hole {a} and hole {b}"
                           for a, b, k in clash)
        raise SystemExit(
            f"{label or 'this course'}: {len(clash)} green(s) bound to more than one hole.\n"
            f"{lines}\n"
            f"  One of those cards would print a confident read of the wrong putting surface. A\n"
            f"  hole's own green is probably missing from the OSM extract while a neighbour's sits\n"
            f"  inside the {GREEN_BIND_MAX_M:.0f} m bind limit, so the distance cap cannot catch it.\n"
            f"  Re-run fetch_osm.py, or add the missing green (tagged _digitized) before building.")


def match_green(hole_line, greens, max_m=GREEN_BIND_MAX_M, label=""):
    """Bind a hole's centerline to its green: (green, green_end_point, tee_end_point).

    Binds to the NEAREST green to either endpoint, but REFUSES beyond max_m. Without that cap a hole
    whose own green is missing from OSM silently attaches to a neighbour's, and the card then prints a
    confident, correctly-computed read of the WRONG putting surface -- the worst thing this project can
    do. It has happened: bay-view hole 9 bound to hole 7's green, 47.8 m away, when an Overpass reply
    truncated the data.

    Lives here because the same binding was written three times -- fetch_dem_hd.py, fetch_dem.py and
    render_hole.py -- and a cap added to one would have left the others silent. That is the exact
    duplication this module was created to end.
    """
    def near(pt):
        best, bg = 1e9, None
        for g in greens:
            gg = g['geometry']
            gla = sum(p['lat'] for p in gg) / len(gg)
            glo = sum(p['lon'] for p in gg) / len(gg)
            dm = math.hypot((pt['lon'] - glo) * mlon(gla), (pt['lat'] - gla) * mlat(gla))
            if dm < best:
                best, bg = dm, g
        return best, bg

    da, ga = near(hole_line[0])
    db, gb = near(hole_line[-1])
    d, g, gend, tend = ((da, ga, hole_line[0], hole_line[-1]) if da <= db
                        else (db, gb, hole_line[-1], hole_line[0]))
    if g is None:
        raise SystemExit(f"no green found to bind {label or 'this hole'} to.")
    if d > max_m:
        raise SystemExit(
            f"{label or 'a hole'}: the nearest green is {d:.0f} m from either end of its centerline,\n"
            f"  beyond the {max_m:.0f} m bind limit. Its own green is probably missing from the OSM\n"
            f"  extract, and binding anyway would print a confident read of the WRONG putting surface.\n"
            f"  Re-run fetch_osm.py, or add the green (tagged _digitized) before building.")
    return g, gend, tend


# How much closer the winning candidate must be than the runner-up for the course centre to be
# DECIDING rather than guessing. The two real ambiguous holes (castlewood-valley 1 and 9, each with a
# Hill-course twin) are separated by 602 m and 632 m, so 150 m keeps 4x headroom while still refusing a
# genuinely close call. It is not academic: copper-valley's recorded location sits 617 m from its own
# hole centroid, the same order as those margins, so a location that far off on a course WITH duplicate
# refs could flip the choice. Better to stop and say so than to print another course's hole.
AMBIGUOUS_MARGIN_M = 150.0


def hole_lines(elements, course_lat, course_lon):
    """{hole_number: the ONE way that is this course's hole}, chosen DETERMINISTICALLY.

    Every reader used to do this itself as `max(candidates, key=len(geometry))` -- most vertices wins.
    Two faults in that, and they compound:

      * It is not deterministic. When two candidates tie on vertex count, max() returns whichever came
        first, i.e. whatever order Overpass happened to serialise. Verified: shuffling castlewood-valley
        hole 1's candidates flips the answer between two different ways.
      * At Castlewood, two 18-hole courses share one OSM area, so a Valley ref can have a Hill way with
        the same ref. Valley hole 1's two candidates both have 3 vertices, 604 m apart. So a re-fetch
        could silently put the HILL course's first hole -- its map, its green, its slope, its yardage
        ticks -- on a Valley card, with nothing to say so. Length is no help either: the way it must
        REJECT (425.8 yd) matches Valley's 429 card better than the right one (444.3 yd) does.

    Nearest the course's own centre wins, which is the question actually being asked, and exact ties
    break on the OSM id so the result can never depend on element order. Seven call sites did this
    separately; they must agree, because a green surface built for one way and a map drawn from another
    is a card that is internally wrong with no symptom.
    """
    by_ref = {}
    for e in elements:
        t = e.get("tags") or {}
        if t.get("golf") != "hole" or not e.get("geometry"):
            continue
        ref = t.get("ref")
        if not (ref and str(ref).isdigit()):
            continue
        by_ref.setdefault(int(ref), []).append(e)

    # The centre is needed only to BREAK ambiguity, so it is demanded only when there is ambiguity to
    # break. That keeps callers with no course.json (the synthetic fixtures) working, while a real
    # two-course club without a recorded centre fails loudly instead of picking by element order.
    if course_lat is None or course_lon is None:
        ambiguous = sorted(hn for hn, ws in by_ref.items() if len(ws) > 1)
        if ambiguous:
            raise SystemExit(
                f"hole ref(s) {ambiguous} have more than one OSM way, and no course centre was given\n"
                f"  to tell them apart (course.json \"location\"). Choosing by element order is how the\n"
                f"  WRONG course's hole ends up on a card at a club with two courses.")
        return {hn: ws[0] for hn, ws in by_ref.items()}

    def score(w):
        g = w["geometry"]
        la = sum(p["lat"] for p in g) / len(g)
        lo = sum(p["lon"] for p in g) / len(g)
        d = math.hypot((lo - course_lon) * mlon(la), (la - course_lat) * mlat(la))
        return (round(d, 3), w.get("id") or 0)

    out = {}
    for hn, ws in by_ref.items():
        ranked = sorted(ws, key=score)
        out[hn] = ranked[0]
        if len(ranked) > 1:
            margin = score(ranked[1])[0] - score(ranked[0])[0]
            if margin < AMBIGUOUS_MARGIN_M:
                raise SystemExit(
                    f"hole {hn} has {len(ranked)} OSM ways and the course centre cannot tell them\n"
                    f"  apart: nearest {score(ranked[0])[0]:.0f} m (way {ranked[0].get('id')}),\n"
                    f"  next {score(ranked[1])[0]:.0f} m (way {ranked[1].get('id')}) -- a margin of only\n"
                    f"  {margin:.0f} m, under the {AMBIGUOUS_MARGIN_M:.0f} m this needs to be a decision\n"
                    f"  rather than a coin toss. Check course.json \"location\": it is what separates two\n"
                    f"  courses that share one OSM area, and picking wrong puts ANOTHER course's hole --\n"
                    f"  its map, its green, its slope, its yardages -- on this card.")
    return out
