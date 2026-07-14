#!/usr/bin/env python3
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

def fetch(query, out):
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'greenbook/1.0'})
            data = urllib.request.urlopen(req, timeout=150).read()
            json.loads(data)                      # validate
            open(os.path.join(config.COURSE_DIR, out), "wb").write(data)
            return json.loads(data)
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
