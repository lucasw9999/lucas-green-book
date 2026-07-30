#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generic OSM fetch for a course (reads config.osm_bbox, writes into COURSE_DIR):
  osm_geom.json   -- golf=green polygons + golf=hole centerlines (with geometry)
  osm_course.json -- golf features + water (tees, bunkers, water) for layouts
Run:  COURSE=<slug> python3 fetch_osm.py
"""
import urllib.parse, urllib.request, json, time, os, math
import config

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

    Adding relation[...] to the main query is not enough: Overpass answers a relation under
    `out geom` with bounds and tags only. The member geometry needs the recurse-down form
    `(._;>;); out geom;`, which is why relations are fetched separately.

    Each OUTER member ring becomes its own element carrying the relation's tags -- a fairway drawn as
    several filled rings looks the same as one mapped as several ways, which is how the way-mapped
    courses already render. Inner rings are skipped: filling a hole in the polygon with fairway green
    would be worse than leaving it out.
    """
    out = []
    added = 0
    for e in elements:
        if e.get("type") != "relation":
            out.append(e)
            continue
        tags = e.get("tags") or {}
        for i, m in enumerate(e.get("members") or []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            if (m.get("role") or "outer") != "outer":
                continue
            out.append({"type": "way",
                        "id": -(abs(int(e.get("id", 0))) * 100 + i) - 1,
                        "tags": dict(tags),
                        "geometry": m["geometry"],
                        "_from_relation": e.get("id")})
            added += 1
    if added:
        print(f"  flattened {added} outer ring(s) from multipolygon relations")
    return out


def _check_response(j, path, out):
    """Validate the INCOMING Overpass reply before it is allowed to replace a good cache.

    Overpass signals a timeout or rate-limit with HTTP 200 plus a "remark" and a short (often
    empty) element list. That parses cleanly and has the right SHAPE, so the on-disk guard cannot
    catch it -- the reply would simply be written over the cache, deleting every green and hole for
    the course. Downstream nothing errors: holes bind to their nearest surviving green, so a course
    silently rebinds (measured: bay-view hole 9 to hole 7's green, 47.8 m away).

    Two checks: refuse a remark-bearing reply outright, and refuse a reply whose golf-feature count
    has collapsed against the cache we are about to overwrite. Set ALLOW_SHRINK=1 to override the
    second when OSM genuinely lost features.
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
            old_n = ngolf(json.load(open(path)).get('elements', []))
        except Exception:
            old_n = 0
        if old_n >= 4 and new_n < old_n * 0.5 and not os.environ.get("ALLOW_SHRINK"):
            raise SystemExit(
                f"ABORT: Overpass returned {new_n} golf features for {out} but the existing cache has\n"
                f"  {old_n}. A collapse like this is nearly always a partial reply, and overwriting\n"
                f"  would silently rebind holes to the wrong greens. Re-run; if OSM really did lose\n"
                f"  these features, set ALLOW_SHRINK=1 deliberately.")


def fetch(query, out):
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    path = os.path.join(config.COURSE_DIR, out)
    kept = _digitized_of(path)            # read BEFORE the network call, so a fetch can never race it
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
                        dm = math.hypot((elo-dlo)*111320.0*math.cos(math.radians(dla)),
                                        (ela-dla)*111320.0)
                        if dm < 25.0:
                            raise SystemExit(
                                f"ABORT: digitized green {d.get('id')} in {path} is {dm:.1f} m from a\n"
                                f"  freshly fetched OSM green ({e.get('type')} {e.get('id')}) -- OSM has\n"
                                f"  most likely mapped it for real. Keeping both would give one hole two\n"
                                f"  greens. Delete the digitized copy and rebuild that hole's DEM.")
                j.setdefault('elements', []).extend(add)
                data = json.dumps(j, indent=2).encode()
                print(f"  {out}: preserved {len(add)} of {len(kept)} digitized feature(s)")
            # write atomically: a crash or a full disk must not leave a half-written cache behind
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
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
out geom tags;''', "osm_course.json")

    # Multipolygon relations need their OWN fetch. Under `out geom` a relation comes back as bounds
    # and tags only -- no members, no geometry -- so adding relation[...] to the query above yields
    # 18 fairways that every consumer then skips for having no geometry. The member rings require the
    # recurse-down form `(._;>;); out geom;`, which is kept separate so it does not pull member nodes
    # for every way in the main query.
    rel = fetch(f'''[out:json][timeout:180];
(
 relation["golf"]({BB});
 relation["natural"="water"]({BB});
 relation["building"]({BB});
);
(._;>;);
out geom;''', "osm_relations.json")
    course['elements'] = course['elements'] + _flatten_relations(rel['elements'])
    from collections import Counter
    c = Counter()
    for e in course['elements']:
        t = e.get('tags', {})
        key = (t.get('golf') or t.get('natural') or t.get('landuse')
               or ('water' if t.get('waterway') else 'other'))
        c[key] += 1
    print("osm_course.json feature counts:", dict(c))

if __name__ == "__main__":
    main()
