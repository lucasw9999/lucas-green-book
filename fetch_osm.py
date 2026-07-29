#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0
"""
Generic OSM fetch for a course (reads config.osm_bbox, writes into COURSE_DIR):
  osm_geom.json   -- golf=green polygons + golf=hole centerlines (with geometry)
  osm_course.json -- golf features + water (tees, bunkers, water) for layouts
Run:  COURSE=<slug> python3 fetch_osm.py
"""
import urllib.parse, urllib.request, json, time, os
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
        prev = json.load(open(path)).get('elements', [])
    except Exception as e:
        raise SystemExit(
            f"REFUSING to overwrite {path}: it exists but could not be parsed ({type(e).__name__}: {e}).\n"
            f"  It may hold hand-digitized geometry that exists nowhere else. Restore or move it\n"
            f"  aside deliberately before re-fetching.")
    return [e for e in prev if '_digitized' in (e.get('tags') or {})]


def fetch(query, out):
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    path = os.path.join(config.COURSE_DIR, out)
    kept = _digitized_of(path)            # read BEFORE the network call, so a fetch can never race it
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'greenbook/1.0'})
            data = urllib.request.urlopen(req, timeout=150).read()
            j = json.loads(data)                  # validate
            if kept:
                have = {e.get('id') for e in j.get('elements', []) if e.get('id') is not None}
                add = [e for e in kept if e.get('id') is None or e.get('id') not in have]
                if len(add) != len(kept):
                    raise SystemExit(
                        f"ABORT: {len(kept)-len(add)} digitized feature(s) in {path} collide by id with\n"
                        f"  freshly fetched OSM elements. OSM may now map that green for real. Resolve by\n"
                        f"  hand (delete the digitized copy if OSM's is correct) rather than guessing.")
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
