#!/usr/bin/env python3
"""
Download a course's LiDAR point-cloud tiles (USGS, public domain) so the trees
(fetch_trees.py) and high-precision green surfaces (fetch_dem_hd.py) can be built.

Discovery via USGS TNM products API (robust retry — it rate-limits/outages).
Picks the newest project's tiles overlapping the course bbox and downloads the
LAZ into COURSE_DIR/laz/.

Run:  COURSE=<slug> python3 fetch_lidar.py
Then: COURSE=<slug> python3 fetch_dem_hd.py   # precision green surfaces
      COURSE=<slug> python3 fetch_trees.py    # trees from canopy returns
      COURSE=<slug> python3 generate.py
"""
import os, json, time, urllib.request
import config

DIR = config.COURSE_DIR
os.makedirs(f"{DIR}/laz", exist_ok=True)
S, W, N, E = config.COURSE["osm_bbox"]
BBOX = f"{W},{S},{E},{N}"            # TNM wants minx,miny,maxx,maxy

def tnm_items(tries=8):
    url = ("https://tnmaccess.nationalmap.gov/api/v1/products?bbox=" + BBOX +
           "&datasets=Lidar%20Point%20Cloud%20(LPC)&outputFormat=JSON&max=60")
    for a in range(tries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'greenbook/1.0'}), timeout=90).read()
            items = json.loads(data).get('items', [])
            if items:
                return items
            print(f"  TNM try {a+1}: 0 items (service busy), retrying")
        except Exception as e:
            print(f"  TNM try {a+1} failed: {type(e).__name__}, retrying")
        time.sleep(10)
    return []

def main():
    items = tnm_items()
    if not items:
        raise SystemExit("USGS TNM returned no tiles after retries (temporary outage). "
                         "Re-run later; point cloud is known to exist for this bbox.")
    # newest project
    items.sort(key=lambda i: i.get('publicationDate', ''), reverse=True)
    proj = ' '.join(items[0]['title'].split()[4:7])
    tiles = [i for i in items if ' '.join(i['title'].split()[4:7]) == proj]
    print(f"project: {proj}  ({len(tiles)} tiles)")
    for it in tiles:
        u = it.get('downloadURL')
        if not u:
            continue
        fn = f"{DIR}/laz/" + os.path.basename(u)
        if os.path.exists(fn) and os.path.getsize(fn) > 1e6:
            print("  cached", os.path.basename(u)); continue
        for a in range(4):
            try:
                urllib.request.urlretrieve(u, fn)
                print("  downloaded", os.path.basename(u), round(os.path.getsize(fn)/1e6), "MB"); break
            except Exception as e:
                print(f"  {os.path.basename(u)} try {a+1} failed: {e}"); time.sleep(3)
    print("done ->", f"{DIR}/laz")

if __name__ == "__main__":
    main()
