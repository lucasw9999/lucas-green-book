#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generic OSM fetch for a course (reads config.osm_bbox, writes into COURSE_DIR):
  osm_geom.json   -- golf=green polygons + golf=hole centerlines (with geometry)
  osm_course.json -- golf features + water (tees, bunkers, water) for layouts, INCLUDING outer
                     rings flattened out of multipolygon relations
  osm_relations.json -- the raw relation reply those rings are flattened from
Run:  COURSE=<slug> python3 fetch_osm.py
"""
import urllib.parse, urllib.request, json, time, os, math
from collections import Counter
import config
import geo
# ONE definition of "a watercourse a card draws", and it lives with the renderer that draws it. The
# census below counts water so the shrink guard can tell a lost hazard from churn; if it counted a
# WIDER set than the map draws, a reply could lose a real stream and gain a culvert without moving the
# number. Importing render_hole for a predicate is this project's existing pattern -- fetch_hole_elev
# does it for par3_exact_from_tee ("one definition of 'straight par 3'") and tools/check_osm_bbox.py
# for DRAW_CORRIDOR_M -- and the module is import-safe: constants and functions only.
from render_hole import is_visible_watercourse

S, W, N, E = config.COURSE["osm_bbox"]   # [south, west, north, east]
BB = f"{S},{W},{N},{E}"

def _digitized_of(path):
    """Hand-added elements in an existing cache file, tagged _digitized.

    These are irreplaceable: some courses carry greens traced from public-domain NAIP because OSM
    had none, there is no script that regenerates them, and courses/ is gitignored -- so this file
    is the ONLY copy. Losing one is silent and destructive: holes bind to their NEAREST green, so
    the affected hole would quietly bind to a neighbouring green (measured: 42.5 m away) and print
    a confident slope map for the wrong putting surface.

    Therefore an unreadable existing file is a HARD STOP, never "nothing to preserve" -- a corrupt
    or truncated cache plus a re-fetch would otherwise erase the geometry with no message at all.
    """
    if not os.path.exists(path):
        return []
    try:
        j = json.load(open(path))
    except Exception as e:
        raise SystemExit(
            f"REFUSING to overwrite {path}: it exists but could not be parsed ({type(e).__name__}: {e}).\n"
            f"  It may hold hand-digitized geometry that exists nowhere else. Restore or move it\n"
            f"  aside deliberately before re-fetching.")
    # Shape-check too, not just parseability. A file that is valid JSON but the wrong SHAPE (no
    # 'elements' key, elements not a list, elements holding non-objects) would otherwise be read as
    # "nothing to preserve" and silently overwritten -- exactly the loss this guard exists to stop.
    if not isinstance(j, dict) or not isinstance(j.get('elements'), list) \
            or any(not isinstance(e, dict) for e in j['elements']):
        raise SystemExit(
            f"REFUSING to overwrite {path}: it parsed as JSON but is not an Overpass result\n"
            f"  (expected an object with an 'elements' list of objects). Treating this as\n"
            f"  'nothing to preserve' could destroy hand-digitized geometry. Inspect it by hand.")
    return [e for e in j['elements'] if '_digitized' in (e.get('tags') or {})]


def _flatten_relations(elements):
    """Turn multipolygon relations into way-shaped elements so nothing downstream needs to change.

    The course query only asked for way[...], and on many courses the fairways are mapped as
    MULTIPOLYGON RELATIONS. Measured live: valley-hi has 18 fairway relations and 0 fairway ways,
    monarch-bay 36, the-reserve 18 -- so those books drew no fairway at all while every card set's
    legend promises "fairway (green)". The largest feature of a golf hole was simply missing.

    Getting the member geometry needs care. Overpass answers a relation under `out geom` with bounds
    and tags only. The recurse-down form `(._;>;); out geom;` does return it, but it pulls every
    member NODE and times out on real course bboxes -- four attempts against valley-hi returned 504,
    504, 429, 504. The cheap form asks for the relation BODIES (tags plus member refs, no geometry)
    and separately for the member WAYS with inline geometry, then joins them by way id: 1.3 s on the
    same bbox that would not answer at all.

    Each OUTER member ring becomes its own element carrying the relation's tags -- a fairway drawn as
    several filled rings looks the same as one mapped as several ways, which is how the way-mapped
    courses already render. Inner rings are skipped: filling a hole in the polygon with fairway green
    would be worse than leaving it out.
    """
    ways = {e.get("id"): e for e in elements
            if e.get("type") == "way" and e.get("geometry")}
    out = []
    missing = []
    for e in elements:
        if e.get("type") != "relation":
            continue
        tags = e.get("tags") or {}
        for i, m in enumerate(e.get("members") or []):
            if m.get("type") != "way" or (m.get("role") or "outer") != "outer":
                continue
            w = ways.get(m.get("ref"))
            if not w or not w.get("geometry"):
                missing.append(f"{e.get('id')}/{m.get('ref')}")
                continue
            out.append({"type": "way",
                        "id": -(abs(int(e.get("id", 0))) * 100 + i) - 1,
                        "tags": dict(tags),
                        "geometry": w["geometry"],
                        "_from_relation": e.get("id")})
    if out:
        print(f"  flattened {len(out)} outer ring(s) from multipolygon relations")
    if missing:
        # Silence here is how the fairways went missing in the first place: a relation whose rings we
        # never received produces no feature and no error, and the book just draws less.
        print(f"  WARNING {len(missing)} outer ring(s) had no geometry in the reply "
              f"(relation/way {', '.join(missing[:6])}{' ...' if len(missing) > 6 else ''}).\n"
              f"          Those parts of the course will not be drawn. Re-run.")
    return out


def census(elements):
    """Features grouped by the KIND a consumer looks for, as {kind: count}.

    ONE spelling of "what is in this reply", used for the shrink guard and for the post-fetch
    printout, because they have to be counting the same thing.

    `building` is tested FIRST and on its own. It was missing from the printout's key chain
    (`golf or natural or landuse or waterway`), so every building landed in `other` -- on
    castlewood-hill all 182 of them, on callippe all 540, on the-reserve 1,529 of 1,530. That is
    precisely the number fetch_trees.py hard-stops on ("no building polygons in osm_course.json --
    this cache predates the way[building] query, so roofs would be drawn as trees", 53 markers on
    Merion's clubhouse), so the one figure that would have predicted that refusal was the one figure
    the fetch never printed. Buildings come first for the same reason: fetch_trees.py's footprint test
    asks `building not in (None, 'no')` before it looks at anything else, so counting a
    golf-tagged clubhouse as golf here would make this census disagree with the check it exists to
    anticipate.

    `natural=water` AREAS and `waterway=*` LINES are counted APART, because the map and the card
    footer have never merged them: render_hole draws the areas in `waters` -- the same filled blue as
    golf=water_hazard -- and the lines in `creeks` as a blue polyline, and the footer reports them as
    two separate numbers (`water_hazards` and `watercourses`). While both landed in one `water`
    bucket, the shrink guard's unit was wider than any class a card draws, so a reply could delete
    every pond a course had and replace them one for one with new stream ways without moving the
    count. Measured on bay-view: 2 pond areas and 14 waterway lines, and dropping both ponds while
    adding two streams was accepted in silence -- those two ponds are drawn inside the 45 m water
    corridor of holes 7, 10 and 18 (22.7 m, 10.0 m and 1.5 m off the played line), all three of which
    print a non-zero W in their footer.

    ...and `waterway` was STILL wider than the drawn class, one level down. It counted every way
    carrying the key, while render_hole's `creeks` takes only `is_visible_watercourse`: not a dam or a
    weir (a structure beside water sits exactly where the water is NOT), and not a culverted, covered
    or underground reach (merion 13 once printed "1W" whose only blue mark was a 14.7 m culvert). So
    the same swap survived inside the surviving bucket -- lose a real stream, gain a culvert, count
    unmoved, guard silent. Not hypothetical: 29 of this corpus's 179 waterways are undrawn today (24
    culverts, 4 tunnel=yes, 1 tunnel=covered, 1 dam) on 9 of 12 courses, merion 8 of 20 and bay-view 4
    of 14 among them.

    The undrawn ones are counted in `waterway_undrawn` rather than dropped. Two reasons: the fetch
    asked for them, and silence about a class the query requested is exactly what put every building
    in `other` (1,529 of the-reserve's 1,530); and letting them fall through to `other` would make a
    filled-in culvert a STRUCTURAL abort, which is the wrong severity for something no card draws. It
    is listed as volatile and not as a hazard for the same reason: it churns like the drawn lines do,
    and nothing is drawn or measured from it.
    """
    c = Counter()
    for e in elements:
        t = e.get('tags') or {}
        if t.get('building') not in (None, 'no'):
            c['building'] += 1
        elif t.get('golf'):
            c[t['golf']] += 1
        elif t.get('natural') == 'water':
            c['water'] += 1
        elif t.get('waterway'):
            c['waterway' if is_visible_watercourse(e) else 'waterway_undrawn'] += 1
        elif t.get('natural') or t.get('landuse'):
            c[t.get('natural') or t.get('landuse')] += 1
        else:
            c['other'] += 1
    return c


# Kinds whose count CHURNS in OSM independently of the golf course, and which nothing a card
# MEASURES is derived from. A landcover polygon is split at a new path, a creek is re-segmented at a
# road crossing (render_hole already has to de-duplicate that: one creek, many ways), a mapper adds
# or deletes a handful of tree nodes. Everything NOT listed here -- green, hole, fairway, tee,
# bunker, cartpath, rough, driving_range, water, water_hazard, and any kind not yet seen -- keeps ZERO
# tolerance, and gets no rarity exemption either, because losing one of those rebinds or re-draws a
# hole. Default-deny: a new kind is structural until someone shows it churns.
VOLATILE_KINDS = frozenset({
    # observed in this corpus' caches: tree, tree_row, wood, waterway, building, rock
    # ...plus the other landcover kinds main()'s own queries ask for
    'tree', 'tree_row', 'wood', 'forest', 'scrub', 'wetland',
    'waterway', 'waterway_undrawn', 'building', 'bare_rock', 'rock', 'stone',
})

# Kinds whose loss removes drawn HAZARD ink from a card: sand and water, the tan and the blue, the two
# things the footer counts as "NB" and "NW". These get NO rarity exemption and NO tolerance floor,
# because rare is exactly when one loss matters most -- see the block in _check_response.
#
# `waterway` is in BOTH sets, and that is the point. It churns (a creek is re-segmented at a road
# crossing) and it is also drawn, in the same blue as a pond, by render_hole's `creeks`. So it keeps
# the PROPORTIONAL part of the churn tolerance and loses the floor of 1: 2% of 53 is one way, 2% of 3
# is zero. Since the bucket became the DRAWN lines only (see census), the-reserve's network is 49 of
# them and 2% of 49 is also zero -- so no course in this corpus is currently handed a free
# re-segmentation, and the proportional part is what a 50+ line course would get. That direction is
# the safe one for a hazard kind, and the free loss it withdraws is the one this pair of sets exists
# to withdraw.
#
# `waterway_undrawn` -- the culverts, the tunnels and the dams -- is volatile and NOT a hazard kind,
# because no card draws it and nothing measures from it. A mapper marking a reach culverted is an OSM
# improvement, and it must not read as a lost hazard.
#
# `water` -- the natural=water AREAS -- is a hazard kind and NOT a volatile one, which is where it
# differs from the merged bucket these two were split out of. The re-segmentation that earns waterway
# its tolerance is a property of LINES; an area mapped in several pieces arrives as a multipolygon
# relation, which the baseline filter removes anyway. Areas are what `waters` draws, alongside
# golf=water_hazard, and they now get exactly what golf=water_hazard already got: nothing. That costs
# this corpus no silence -- the largest fetchable pond count in it is 6 (the-reserve), and 2% of 6 was
# already 0 -- and it stops a course that maps 50 ponds from being handed a free one.
HAZARD_KINDS = frozenset({'bunker', 'water_hazard', 'lateral_water_hazard', 'water', 'waterway'})

# 2%, floor 1. Chosen from what these counts actually are on this corpus (the-reserve 2,462 trees and
# 1,530 buildings, micke-grove 532 trees, the-reserve 49 waterway ways, merion 8 wood) against what the
# guard has to keep catching: every documented truncation lost 89-100% of a kind (fairway 18 -> 0,
# 37 -> 1, 23 -> 4, and the remark replies that return nothing at all). So 2% sits an order of
# magnitude below the smallest real failure while covering ordinary editing -- 49 trees at the-reserve,
# 30 buildings. The floor of 1 is what the reproduced defect needed: one deleted natural=tree node out
# of 2,462 hard-aborted the whole fetch, and without a floor a 4 -> 3 tree shrink still would.
# (Every count here is the FETCHABLE one, i.e. the baseline the guard really compares. the-reserve's
# waterways were once published as "60 water ways"; 60 is the raw merged figure, of which 7 were pond
# areas -- one of those carrying _from_relation -- leaving 53 lines and 6 areas, and of those 53 lines
# four are culverts the map does not draw, so the drawn bucket the guard compares is 49.)
CHURN_TOLERANCE = 0.02


def _churn_tolerance(old_count, kind=None):
    """How many features of `kind` may go missing without a human looking.

    The floor of 1 exists for the reproduced defect (one deleted tree node out of 2,462 hard-aborted a
    whole fetch) and it is wrong for a HAZARD kind, where it would hand a three-watercourse course a
    free watercourse. Hazard kinds therefore get the proportional part only, which is zero below 50
    features. (Only `waterway` is in both sets, so only `waterway` ever reads this branch; the other
    hazard kinds are not volatile and _check_response gives them no tolerance at all, and
    `waterway_undrawn` is volatile but not a hazard so it takes the floor like the landcover kinds.)
    """
    if kind in HAZARD_KINDS:
        return int(old_count * CHURN_TOLERANCE)
    return max(1, int(old_count * CHURN_TOLERANCE))


def _check_response(j, path, out):
    """Validate the INCOMING Overpass reply before it is allowed to replace a good cache.

    Overpass signals a timeout or rate-limit with HTTP 200 plus a "remark" and a short (often
    empty) element list. That parses cleanly and has the right SHAPE, so the on-disk guard cannot
    catch it -- the reply would simply be written over the cache, deleting every green and hole for
    the course. Downstream nothing errors: holes bind to their nearest surviving green, so a course
    silently rebinds (measured: bay-view hole 9 to hole 7's green, 47.8 m away).

    Three checks: refuse a remark-bearing reply outright, refuse a reply that has lost features of any
    KIND against the cache we are about to overwrite, and refuse one whose total golf-feature count
    has collapsed.

    THREE different waivers, because these are three different questions a human has to answer.
    ALLOW_SHRINK=1 accepts a real OSM deletion of a VOLATILE kind (trees, buildings, landcover);
    ALLOW_HAZARD_SHRINK=1 accepts the loss of drawn HAZARD ink -- sand or water, the kinds in
    HAZARD_KINDS; ALLOW_STRUCTURAL_SHRINK=1 accepts the loss of a green, hole, fairway or any other kind
    a card is built from. One flag used to gate the first two of those, and the message for a churned
    tree prescribed it -- so waiving a deleted tree stump also waived the green check that exists to stop
    18 cards rebinding. The third was split off for the identical reason: a waiver granted for a
    re-mapped green must not also accept a bunker that quietly stopped being fetched.
    """
    if not isinstance(j, dict) or not isinstance(j.get('elements'), list):
        raise SystemExit(f"ABORT: Overpass reply for {out} is not an element list -- refusing to write.")
    remark = j.get('remark')
    if remark:
        raise SystemExit(
            f"ABORT: Overpass returned a remark instead of complete data for {out}:\n"
            f"    {str(remark)[:160]}\n"
            f"  This is a timeout or rate-limit reply, NOT an empty course. Writing it would delete\n"
            f"  the existing cache. Wait and re-run.")
    def ngolf(els):
        return sum(1 for e in els if (e.get('tags') or {}).get('golf'))
    new_n = ngolf(j['elements'])
    if os.path.exists(path):
        try:
            old = json.load(open(path)).get('elements', [])
        except Exception:
            old = []
        old_n = ngolf(old)
        # PER KIND, because the aggregate cannot see the loss that matters. osm_geom.json holds
        # greens AND hole centrelines, i.e. about 2x the hole count, so `new_n < old_n * 0.5` lets a
        # reply drop up to HALF the golf features silently -- and where holes >= greens that is EVERY
        # GREEN. Counted on this corpus: bay-view (18 greens, 18 holes), valley-hi (18, 18) and
        # castlewood-valley (19, 20) could lose every single green and still pass; the other eight
        # could lose all but one to six of them. A reply with all the holes and none of the greens is
        # exactly the truncated reply that bound bay-view hole 9 to hole 7's green.
        #
        # No tolerance for the kinds a card is built from, because these are stable mapped polygons and
        # the documented failure cost ONE green. A genuine OSM deletion is what ALLOW_STRUCTURAL_SHRINK
        # is for; it should need a human to look.
        #
        # COMPARE LIKE WITH LIKE. The baseline is the cache, which holds two classes of element the raw
        # Overpass reply CANNOT contain: hand-digitized features merged in after this check runs, and
        # rings flattened out of multipolygon relations by a later fetch. Counting them made the guard
        # fire on a legitimate re-fetch of 9 of the 11 courses -- valley-hi fairway 18 -> 0, monarch-bay
        # 37 -> 1, micke-grove 23 -> 4, the-reserve 20 -> 2 -- and deterministically, so the only
        # available action was the waiver the message prescribes, which then waives the real checks too.
        # A guard that must be switched off to do ordinary work is worse than none: it trains you to
        # switch it off.
        #
        # Filtering the baseline is the honest comparison, not a loosening. The reply is still
        # required to carry every FETCHED feature the cache had; it is simply no longer asked to
        # carry the ones this project added itself.
        def _fetchable(els):
            # _digitized is a TAG; _from_relation is a TOP-LEVEL key (written that way at line 94).
            # Reading both from tags filtered nothing, so the guard still refused 9 of 11 courses --
            # and my verification of that fix used a probe that read the same wrong key, so it agreed
            # with itself. Measured on valley-hi: 18 elements carry _from_relation at top level,
            # 0 inside tags.
            return [e for e in els
                    if '_digitized' not in (e.get('tags') or {})
                    and e.get('_from_relation') is None]
        oc, nc = census(_fetchable(old)), census(j['elements'])
        # RARE IS NOT SAFE, and the `oc[k] < 4` floor below said it was. It exempted any kind with
        # fewer than four features ENTIRELY, and `water`'s max(1, 2%) tolerance gave the small ones
        # one free loss on top. Measured on the caches now on disk, as the guard sees them:
        #
        #     castlewood-hill    water_hazard 1, waterway 3   -- draws water on 3 of 18 cards
        #     castlewood-valley  water_hazard 2, lateral_water_hazard 1, waterway 7   -- 12 of 18
        #     monarch-bay        water_hazard 1, waterway 1    -- 3 of 18
        #     callippe water_hazard 1; merion lateral 1 + water 4; philadelphia lateral 3 + water 2;
        #     valley-hi lateral 5 + water 1; bay-view water 2 + waterway 14
        #
        # Reproduced against those counts: hill could lose ALL THREE of its watercourses, valley both
        # its water_hazards, monarch-bay its only one, and every one of those replies was accepted
        # silently. A book that promises never to omit a hazard the golfer can reach had no floor at all
        # under the hazards a card actually draws.
        #
        # The exemption is now confined to the kinds that actually CHURN, which is what its own
        # justification always claimed and what fetch_trees.py cites it as. It had been reaching
        # STRUCTURAL drawn kinds too, while VOLATILE_KINDS' comment denied it: monarch-bay's only
        # fetchable golf=fairway way (1 -> 0), the-reserve's two (2 -> 0), philadelphia's single
        # golf=rough (1 -> 0) and six courses' golf=driving_range (1 -> 0) were all free. A fairway is
        # the largest feature on the card. Rare landcover keeps the exemption -- castlewood-hill's 2
        # wood polygons, micke-grove's 3 tree_rows -- because nothing a card measures comes from them.
        #
        # THE CACHE-LEVEL BASELINE IS GONE, AND THE QUESTION IT WOULD HAVE ANSWERED IS NOT. febbbba
        # re-fetched castlewood-hill, castlewood-valley, copper-valley and monarch-bay and its message
        # reports "ZERO upstream drift on all four". The pre-fetch caches no longer exist anywhere --
        # `courses/` is gitignored, so git never held them, and they are not in /tmp, /var/tmp or the
        # home tree -- so that zero is UNVERIFIABLE at the level of ids, tags and geometry, and no
        # reconstruction settles it: a uniform-shrink model reproduces every published shortfall and
        # then self-refutes, because under it hill 16's own green would have sat outside the old box and
        # the book rendered hole 16.
        #
        # But the question that MATTERS here -- did that re-fetch drop a hazard the book draws -- is
        # answered, from the printed side. The 12 pre-re-fetch greenbook.html files survived and are
        # kept at ~/greenbook-prefetch-evidence-2026-08-03. They authenticate against febbbba's own
        # published pre-values (castlewood-hill 10,422 tree markers and 106 drawn tee polygons,
        # castlewood-valley 9,238 and 60) and reproduce its published deltas exactly (hill -9 tree /
        # +1 tee, valley -3 / +3; copper-valley identical in every drawn class). Counting the drawn ink
        # then against now: the DRAWN WATER POLYGON count and the drawn watercourse polyline count are
        # IDENTICAL on all 12, and the "NB NW" footer sequence is unchanged on hill, valley and copper.
        # No water was lost. Read the cache-level zero as unchecked, read the hazard question as
        # closed, and do not let the baseline go a second time -- which is what HAZARD_KINDS is for.
        lost, churn, hazard = {}, {}, {}
        for k in oc:
            if nc[k] >= oc[k]:
                continue
            if oc[k] < 4 and k in VOLATILE_KINDS and k not in HAZARD_KINDS:
                continue
            # A hazard kind that also churns keeps the proportional tolerance and nothing else; one that
            # does not churn (golf-tagged sand and hazards are stable mapped polygons) gets none.
            tol = _churn_tolerance(oc[k], k) if k in VOLATILE_KINDS else 0
            if oc[k] - nc[k] <= tol:
                continue
            bucket = hazard if k in HAZARD_KINDS else churn if k in VOLATILE_KINDS else lost
            bucket[k] = (oc[k], nc[k])
        def _detail(d):
            return ", ".join(f"{k} {o} -> {n}" for k, (o, n) in sorted(d.items()))
        if lost and not os.environ.get("ALLOW_STRUCTURAL_SHRINK"):
            raise SystemExit(
                f"ABORT: Overpass returned FEWER features than the existing cache for {out}:\n"
                f"    {_detail(lost)}\n"
                f"  Overwriting would silently rebind holes to the wrong greens -- a card then\n"
                f"  prints a confident, correctly-computed read of the WRONG putting surface.\n"
                f"  Re-run; if OSM really did lose these features, set ALLOW_STRUCTURAL_SHRINK=1\n"
                f"  deliberately.")
        if hazard and not os.environ.get("ALLOW_HAZARD_SHRINK"):
            raise SystemExit(
                f"ABORT: Overpass returned FEWER HAZARD features than the existing cache for {out}:\n"
                f"    {_detail(hazard)}\n"
                f"  Sand and water are the two things this book promises never to omit -- the map draws\n"
                f"  them and the footer counts them as NB and NW. There is no rarity exemption here on\n"
                f"  purpose: a course with one water hazard is the course where losing it is invisible.\n"
                f"  Re-run; if OSM really did lose them (a bunker filled in, a pond drained), set\n"
                f"  ALLOW_HAZARD_SHRINK=1 deliberately -- that waives THIS check only, never the\n"
                f"  greens/holes/fairways one, and no other waiver grants it.")
        if churn and not os.environ.get("ALLOW_SHRINK"):
            raise SystemExit(
                f"ABORT: Overpass returned far fewer features of a churning kind than the existing\n"
                f"  cache for {out}:\n"
                f"    {_detail(churn)}\n"
                f"  A drop this large is nearly always a partial reply. Nothing a card MEASURES comes\n"
                f"  from these, but the map would draw less of the course than it has. Re-run; if OSM\n"
                f"  really did lose them, set ALLOW_SHRINK=1 deliberately -- that waives THIS check\n"
                f"  only, never the greens/holes/fairways one above.")
        if old_n >= 4 and new_n < old_n * 0.5 and not os.environ.get("ALLOW_STRUCTURAL_SHRINK"):
            raise SystemExit(
                f"ABORT: Overpass returned {new_n} golf features for {out} but the existing cache has\n"
                f"  {old_n}. A collapse like this is nearly always a partial reply, and overwriting\n"
                f"  would silently rebind holes to the wrong greens. Re-run; if OSM really did lose\n"
                f"  these features, set ALLOW_STRUCTURAL_SHRINK=1 deliberately.")


def _bindings(elements, out):
    """{hole_number: green_element} for a reply, or None when it carries no hole centrelines."""
    greens = [e for e in elements
              if (e.get('tags') or {}).get('golf') == 'green' and e.get('geometry')]
    holes = [e for e in elements
             if (e.get('tags') or {}).get('golf') == 'hole' and e.get('geometry')]
    if not holes:
        return None     # not a geometry reply (the relation pass returns untagged member ways)
    if not greens:
        raise SystemExit(
            f"ABORT: the reply for {out} has {len(holes)} hole centreline(s) and NO green polygons.\n"
            f"  Every card would bind to nothing, or -- worse, once one green reappears -- all of them\n"
            f"  to that one. Refusing to write it over the existing cache.")
    loc = config.COURSE.get('location') or {}
    return {hn: geo.match_green(h['geometry'], greens, label=f"{out} hole {hn}")[0]
            for hn, h in geo.hole_lines(elements, loc.get('lat'), loc.get('lon')).items()}


def _check_bindings(elements, out, prev=()):
    """Refuse a reply that would leave a hole bound to a NEIGHBOUR's green -- before it is written.

    geo.assert_one_green_per_hole was called from fetch_dem.py and fetch_dem_hd.py and nowhere else,
    so it only ever ran when the SURFACES were rebuilt. A re-fetch that dropped greens followed by a
    generate.py-only rebuild never reached it, and generate.py/render_hole.py call geo.match_green,
    which is blind to the near case by construction: it is called once per hole and has no view of
    the others. Measured across this corpus: 47 of the 198 holes have a green that is not their own
    within 40 m of their TEE end -- 20.2 to 39.5 m, worst cases castlewood-hill 13 at 20.2 m and
    monarch-bay 1 at 22.1 m -- all inside the GREEN_BIND_MAX_M cap. So for those 47, losing the
    hole's own green rebinds the card to the neighbour's silently, and nothing on the page or in the
    build disagrees.

    Here is the right place for it, because here is where a reply becomes the cache. It runs on the
    elements about to be WRITTEN, after the hand-digitized greens have been merged back in -- bay-view
    carries two of those (ids 900000005, 900000007) and OSM's own reply does not contain them, so
    checking the raw reply would refuse every re-fetch of that course over a green that is not
    missing at all.

    TWO checks, because the shared-green test alone is not enough. Deleting the own green of each of
    ten at-risk holes, one course at a time: assert_one_green_per_hole caught seven, and missed
    monarch-bay 1, callippe 1 and the-reserve 1 -- because those extracts hold MORE greens than the
    course has holes (20 for 18 at monarch-bay and callippe, 21 for 18 at the-reserve, a practice
    green or a neighbour inside the bbox), so the green the hole wrongly reached for was not bound to
    any other hole and no clash existed to detect. What does see all ten is the cache we are about to
    replace: comparing hole -> green against the PREVIOUS binding catches a rebind whether or not it
    collides. ALLOW_REBIND=1 to accept one deliberately, e.g. when OSM has genuinely redrawn a green
    under a new id.
    """
    bound = _bindings(elements, out)
    if bound is None:
        return
    geo.assert_one_green_per_hole(bound, label=f"{config.SLUG} ({out})")
    if not prev or os.environ.get("ALLOW_REBIND"):
        return
    try:
        was = _bindings(prev, out)
    except SystemExit:
        return          # the old cache cannot be bound either; nothing to compare against
    if not was:
        return
    moved = [(hn, (was[hn] or {}).get('id'), (bound[hn] or {}).get('id'))
             for hn in sorted(set(bound) & set(was))
             if (was[hn] or {}).get('id') != (bound[hn] or {}).get('id')]
    if moved:
        lines = "\n".join(f"    hole {hn}: green {a} -> green {b}" for hn, a, b in moved)
        raise SystemExit(
            f"ABORT: {len(moved)} hole(s) would bind to a DIFFERENT green than the existing cache:\n"
            f"{lines}\n"
            f"  A hole whose own green vanished from the extract binds to the nearest survivor, and 47\n"
            f"  of this corpus's holes have a neighbour's green within {geo.GREEN_BIND_MAX_M:.0f} m of\n"
            f"  their tee end -- so this is what a truncated reply looks like from the outside. The\n"
            f"  card would print a confident, correctly-computed read of the WRONG putting surface.\n"
            f"  Re-run; if OSM has genuinely redrawn a green, set ALLOW_REBIND=1 deliberately.")



def _cached_elements(path):
    """The element list of an existing cache, or [] -- for comparing a reply against what it replaces.

    Never raises: _digitized_of already hard-stops on a cache it cannot parse, and it is called first,
    so reaching here with a broken file is impossible. [] simply means there is nothing to compare.
    """
    try:
        return json.load(open(path)).get('elements') or []
    except Exception:
        return []


def fetch(query, out, write=True):
    """Run one Overpass query and commit the reply to COURSE_DIR/<out>, returning it.

    write=False validates and returns the reply WITHOUT committing it, for the one caller that has
    more to put in the file: see main(), which appends the flattened multipolygon rings first and
    writes osm_course.json exactly once. A file that is not complete until a LATER network call has
    succeeded must not be committed before that call is made.
    """
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    path = os.path.join(config.COURSE_DIR, out)
    kept = _digitized_of(path)            # read BEFORE the network call, so a fetch can never race it
    prev = _cached_elements(path)         # ...and so can the binding we are about to change
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'greenbook/1.0'})
            data = urllib.request.urlopen(req, timeout=150).read()
            j = json.loads(data)                  # validate parseability
            _check_response(j, path, out)         # ...and that it is COMPLETE, not a timeout stub
            if kept:
                have = {e.get('id') for e in j.get('elements', []) if e.get('id') is not None}
                add = [e for e in kept if e.get('id') is None or e.get('id') not in have]
                if len(add) != len(kept):
                    clash = [(e.get('type'), e.get('id')) for e in kept if e not in add]
                    raise SystemExit(
                        f"ABORT: {len(kept)-len(add)} digitized feature(s) in {path} collide by id with\n"
                        f"  freshly fetched OSM elements {clash}. OSM may now map that green for real.\n"
                        f"  Resolve by hand (delete the digitized copy if OSM's is correct).")
                # An id check alone is not enough. It IS reachable (bay-view uses 9000000xx, and the
                # same cache holds real way ids above 9e8) but it is dead for negative ids, and in
                # either case OSM mapping the same green afresh gives it a NEW id -- so the real
                # collision is GEOMETRIC. Keeping both would leave two greens for one hole and let
                # nearest-green matching pick the stale trace.
                for d in add:
                    dg = d.get('geometry') or []
                    if not dg or (d.get('tags') or {}).get('golf') != 'green':
                        continue
                    dla = sum(p['lat'] for p in dg)/len(dg); dlo = sum(p['lon'] for p in dg)/len(dg)
                    for e in j.get('elements', []):
                        eg = e.get('geometry') or []
                        if not eg or (e.get('tags') or {}).get('golf') != 'green':
                            continue
                        ela = sum(p['lat'] for p in eg)/len(eg); elo = sum(p['lon'] for p in eg)/len(eg)
                        dm = math.hypot((elo-dlo)*geo.mlon(dla),
                                        (ela-dla)*geo.mlat(dla))
                        if dm < 25.0:
                            raise SystemExit(
                                f"ABORT: digitized green {d.get('id')} in {path} is {dm:.1f} m from a\n"
                                f"  freshly fetched OSM green ({e.get('type')} {e.get('id')}) -- OSM has\n"
                                f"  most likely mapped it for real. Keeping both would give one hole two\n"
                                f"  greens. Delete the digitized copy and rebuild that hole's DEM.")
                j.setdefault('elements', []).extend(add)
                data = json.dumps(j, indent=2).encode()
                print(f"  {out}: preserved {len(add)} of {len(kept)} digitized feature(s)")
            # Last gate before the bytes land: would this cache bind a hole to the wrong green?
            _check_bindings(j.get('elements') or [], out, prev)
            if write:
                # write atomically: a crash or a full disk must not leave a half-written cache behind
                tmp = path + ".part"
                try:
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, path)
                finally:
                    # A staged file left here is invisible twice over: courses/<slug>/ is the one
                    # directory nothing sweeps (surface_io.sweep_staged is dem_hd-only by its
                    # `.hole*.part` pattern, fetch_lidar's is laz/-only), and the `except Exception`
                    # below SWALLOWS the failure and retries, so nothing reports it either. And it
                    # would sit beside the only copy of the hand-digitized greens.
                    if os.path.exists(tmp):     # a no-op once the rename above has happened
                        os.remove(tmp)
            return j
        except SystemExit:
            raise
        except Exception as e:
            print(f"  {out} attempt {attempt+1} failed: {type(e).__name__} {e}; retry")
            time.sleep(5)
    raise SystemExit(f"FAILED to fetch {out}")

def main():
    geom = fetch(f'[out:json][timeout:120];(way["golf"="green"]({BB});way["golf"="hole"]({BB}););out geom tags;', "osm_geom.json")
    gr = [e for e in geom['elements'] if e.get('tags', {}).get('golf') == 'green']
    ho = [e for e in geom['elements'] if e.get('tags', {}).get('golf') == 'hole']
    refs = sorted([h['tags'].get('ref') for h in ho if h.get('tags', {}).get('ref')],
                  key=lambda x: int(x) if x and x.isdigit() else 99)
    print(f"osm_geom.json: {len(gr)} greens, {len(ho)} holes, refs={refs}")

    course = fetch(f'''[out:json][timeout:120];
(
 way["golf"]({BB});
 way["building"]({BB});
 way["natural"="water"]({BB});
 way["waterway"]({BB});
 way["natural"="wood"]({BB});
 way["landuse"="forest"]({BB});
 way["natural"="scrub"]({BB});
 way["natural"="tree_row"]({BB});
 way["natural"="bare_rock"]({BB});
 way["natural"="rock"]({BB});
 node["natural"="tree"]({BB});
 node["natural"="rock"]({BB});
 node["natural"="stone"]({BB});
);
out geom tags;''', "osm_course.json", write=False)

    # Multipolygon relations need their OWN fetch. Under `out geom` a relation comes back as bounds
    # and tags only -- no members, no geometry -- so adding relation[...] to the query above yields
    # 18 fairways that every consumer then skips for having no geometry.
    #
    # `out body` gives the relation's tags AND its member refs without geometry, and `way(r)` then
    # returns those member ways with inline geometry. _flatten_relations joins the two by way id.
    # The obvious alternative, `(._;>;); out geom;`, recurses down to every member NODE and does not
    # complete: four attempts against valley-hi returned 504, 504, 429, 504. This form answers the
    # same bbox in 1.3 s.
    rel = fetch(f'''[out:json][timeout:180];
(
 relation["golf"]({BB});
 relation["natural"="water"]({BB});
 relation["building"]({BB});
);
out body;
way(r);
out geom;''', "osm_relations.json")
    flat = _flatten_relations(rel['elements'])
    course['elements'] = course['elements'] + flat
    # WRITE IT ONCE, HERE -- which is why the fetch above was told not to commit. osm_course.json is
    # not COMPLETE until these rings are in it, and the relation fetch is allowed to abort (an
    # Overpass remark is a hard stop by design). Writing the way-only reply first and rewriting it
    # afterwards put that abort BETWEEN the two writes, so one timed-out relations call left the file
    # every consumer reads permanently stripped of its rings -- valley-hi 18 -> 0, no 'fairway' key
    # at all -- and _check_response's baseline filter means no later re-fetch can notice.
    cpath = os.path.join(config.COURSE_DIR, "osm_course.json")
    tmp = cpath + ".part"
    try:
        with open(tmp, "w") as f:
            json.dump(course, f, indent=2)
        os.replace(tmp, cpath)
    finally:
        # json.dump streams, so a value it cannot encode leaves PARTIAL json in the staged file, and
        # courses/<slug>/ is the one directory nothing sweeps. Same `finally` as the other four
        # staged writers in this project (tools/lidar_dates.write_lidar_flown,
        # surface_io.commit_surface, fetch_hole_elev.write_hole_elev, fetch_trees.write_layer).
        if os.path.exists(tmp):     # a no-op once the rename above has happened
            os.remove(tmp)
    if flat:
        print(f"  osm_course.json written with {len(flat)} flattened ring(s)")
    c = census(course['elements'])
    print("osm_course.json feature counts:", dict(c))
    if not c.get('building'):
        # fetch_trees.py REFUSES to run on a cache with no buildings, because a roof is 2.5-35 m above
        # ground and reads exactly like canopy on the unclassified tiles most of this corpus uses (53
        # markers stood on Merion's clubhouse before the footprint test existed). Say it here, where
        # the fetch that would have supplied them just finished, rather than leaving it to be
        # discovered two stages later.
        print("  WARNING no building polygons in this reply. fetch_trees.py will refuse to run:\n"
              "          a clubhouse roof arrives as an unclassified return and only its FOOTPRINT\n"
              "          identifies it. If this bbox genuinely has no buildings, run fetch_trees.py\n"
              "          with ALLOW_NO_BUILDINGS=1 deliberately.")

if __name__ == "__main__":
    main()
