#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generic per-green elevation for any course, from the USGS 3DEP seamless 1 m DEM
(public domain) -- no per-course LiDAR tile picking required.

Reads COURSE_DIR/osm_geom.json, matches each green to its hole (for approach
bearing), downloads a small DEM patch per green via the 3DEP exportImage service
sampled at 0.5 m/px, and writes COURSE_DIR/dem_hd/holeNN.{npy,json} -- the same
format render_green.py consumes.

The recorded bbox is the one the REPLY carries, never the one this asked for. ArcGIS exportImage
adjusts the bbox to the requested `size`'s aspect ratio in the IMAGE SR -- degrees here -- while
`size` is computed from the bbox's METRIC aspect, so the service used to expand the latitude span by
1/cos(lat) and hand back a raster the recorded bbox did not describe. See _served_patch: the request
now says adjustAspectRatio=false so the grid is square in METRES, and the georeference is read off the
GeoTIFF either way so the meta always describes its own array.

Run it AFTER fetch_dem_hd.py, not instead of it. This stage FILLS GAPS: it shares dem_hd/ with
fetch_dem_hd.py and skips any green that already holds a good 0.4 m LiDAR surface, so the two
compose per GREEN rather than per course -- which is what a bayside course needs, where most
greens have ground returns and a few over water have none. It used to rewrite every hole it was
given, silently replacing 0.4 m greens with the coarse 1 m DEM (Monarch Bay: 3,889,124 bytes
against 4,973,620).

Run:  COURSE=<slug> python3 fetch_dem_hd.py     # first: 0.4 m where LiDAR allows
      COURSE=<slug> python3 fetch_dem.py        # then: 1 m for the greens it refused
      ONLY=14,16 ...                            # restrict to specific holes (a comma-separated
                                                #   list of numbers; ranges are refused, not guessed)
      OVERWRITE=1 ...                           # replace a good 0.4 m surface on purpose
"""
import urllib.request, json, math, io, time, os
import numpy as np, rasterio
import config
import geo
import surface_io

DIR = config.COURSE_DIR
OUT = f"{DIR}/dem_hd"; os.makedirs(OUT, exist_ok=True)
# replace a good 0.4 m surface on purpose. Parsed the way fetch_trees.py parses its two escape
# hatches, NOT for truthiness: bool(os.environ.get(...)) made OVERWRITE=0, OVERWRITE=false and
# OVERWRITE=no all mean YES, so the word "false" armed the path that trades every 0.4 m LiDAR green
# for the coarse 1 m DEM -- the exact loss keeps_existing_surface below exists to prevent. An
# explicit off must be off.
OVERWRITE = os.environ.get("OVERWRITE", "").lower() not in ("", "0", "false", "no")
R_LAT = 111320.0
def is_seamless(meta):
    """True when this surface came from the 1 m seamless DEM rather than 0.4 m LiDAR ground returns.

    One spelling of the test, matching generate.py and tools/gen_provenance.py."""
    return "seamless" in str((meta or {}).get("source", "")).lower()


def keeps_existing_surface(meta_path, overwrite=False):
    """True when meta_path already holds a GOOD 0.4 m LiDAR surface that must not be replaced.

    This stage shares dem_hd/ with fetch_dem_hd.py and used to rewrite every hole it was given, so
    running it without ONLY= silently replaced every 0.4 m green with the coarse 1 m one and said
    nothing about the better data it had just discarded. The books stayed HONEST -- each card prints
    "1 m data" -- but a whole course quietly lost its precision. Found cold-building Monarch Bay:
    the result was 3,889,124 bytes against the committed 4,973,620, with "1 m data" on greens that
    have real LiDAR.

    An INSUFFICIENT LiDAR surface is not worth keeping: that is exactly the gap this stage fills. An
    unreadable file is not worth keeping either -- rebuilding it is the repair.
    """
    if overwrite or not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception:
        return False
    # Ask the SAME question the rest of the engine asks, the same way. generate.py (twice) and
    # tools/gen_provenance.py all test `'seamless' in source` -- generate.py to decide whether the
    # card prints the "1 m data" honesty label, gen_provenance to count fallbacks in the legal
    # record. Testing `"lidar" in source` here instead made this the one reader with the OPPOSITE
    # polarity over the same hand-written prose field: reword the producer string and the write
    # guard and the printed label would move in opposite directions, and one of them is the label
    # the honesty argument rests on.
    # Requires a source we can positively read as LiDAR-derived. A meta with no source at all is of
    # unknown provenance, and this stage exists to fill gaps -- so leave it fillable rather than
    # protect it on a guess. (That also keeps the pre-existing behaviour of the `"lidar" in source`
    # test for that case, so unifying the polarity above changes nothing in practice.)
    src = str((meta or {}).get("source", "")).strip()
    return bool(src) and not is_seamless(meta) and not meta.get("insufficient")


def mlon(lat): return 111320.0 * math.cos(math.radians(lat))

def centroid(g):
    la = sum(p['lat'] for p in g['geometry']) / len(g['geometry'])
    lo = sum(p['lon'] for p in g['geometry']) / len(g['geometry']); return la, lo
def bearing(a_lat, a_lon, b_lat, b_lon):
    dE = (b_lon - a_lon) * mlon((a_lat + b_lat) / 2); dN = (b_lat - a_lat) * R_LAT
    return (math.degrees(math.atan2(dE, dN)) + 360) % 360

NAN_FRAC_MAX = 0.02          # matches fetch_dem_hd.py's gate
MIN_RELIEF_M = 0.05          # 5 cm across a whole green patch: not a green, a zero-fill


def is_flat_fill(n_in, nan_frac, relief):
    """True when a patch is a zero-fill or a constant raster rather than a green -- refuse it.

    Extracted so the TEST can call it. test_fetch_dem_gate_measures_only_the_green_interior carried its
    own byte-identical copy of this expression, so it verified its own rule and not this one: setting
    `flat = False` here left it green (found by a mutation survey). A test that re-implements the
    producer's rule can only ever catch a wrong APPLICATION of it, never a wrong rule -- and the rule is
    the honesty gate.

    Same shape and reason as fetch_dem_hd.keeps_existing_surface: a predicate can be exercised by truth
    table, an inline boolean inside main() cannot.
    """
    return bool(n_in and nan_frac < 1.0 and relief < MIN_RELIEF_M)


def _green_interior_stats(arr, bbox, W, H, polygon):
    """(nan fraction, cells tested, relief in m) over the GREEN INTERIOR only.

    Everything here must be restricted to the interior. The patch carries a 12 m margin, so a
    statistic taken over the whole raster describes mostly surround: a green sitting on the edge of
    3DEP coverage can be entirely zero-filled while the margin outside it holds real elevation, and
    a whole-patch relief test then reports a healthy range and lets the fabricated green through --
    the exact case the test exists to catch."""
    xmin, ymin, xmax, ymax = bbox
    lats = [p[0] for p in polygon]; lons = [p[1] for p in polygon]
    px = [((lo - xmin) / (xmax - xmin) * W, (ymax - la) / (ymax - ymin) * H)
          for la, lo in zip(lats, lons)]
    n_in = 0; n_nan = 0
    lo, hi = float("inf"), float("-inf")
    for r in range(H):
        yv = r + 0.5
        xs = []
        n = len(px); j = n - 1
        for i in range(n):
            xi, yi = px[i]; xj, yj = px[j]
            if (yi > yv) != (yj > yv):
                xs.append((xj - xi) * (yv - yi) / (yj - yi + 1e-12) + xi)
            j = i
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[k] - 0.5))); b = min(W - 1, int(math.floor(xs[k + 1] - 0.5)))
            if b >= a:
                seg = arr[r, a:b + 1]
                n_in += seg.size
                n_nan += int(np.isnan(seg).sum())
                fin = seg[np.isfinite(seg)]
                if fin.size:
                    lo = min(lo, float(fin.min())); hi = max(hi, float(fin.max()))
    relief = (hi - lo) if hi >= lo else 0.0
    return (1.0 if n_in == 0 else n_nan / n_in), n_in, relief


class NoGeoreference(Exception):
    """The reply carries no GeoTIFF transform, so the extent it covers is unknown."""


def _served_patch(raw):
    """(array, [xmin, ymin, xmax, ymax]) from an exportImage reply -- the extent it actually SERVED.

    The georeference has to travel with the pixels. `size={W},{H}` is derived from the bbox's METRIC
    aspect (0.5 m per pixel each way), while `imageSR=4326` makes ArcGIS adjust the bbox to that
    size's aspect ratio IN DEGREES -- so without adjustAspectRatio=false the service expands the
    latitude span by 1/cos(lat) and the array does not cover the bbox it was asked for. Measured by
    re-issuing all six shipped monarch-bay URLs: 1.2542x to 1.2675x against 1/cos(37.6916 deg) =
    1.2637, each north and south edge out by 5.5 to 7.7 m. Recording the requested bbox anyway put an
    inflated tilt on all six of that course's seamless cards, because render_green takes the array's
    SHAPE from the array and its metres-per-pixel and polygon mask from the meta.

    This used to read the pixels with tifffile.imread(), which parses no GeoTIFF transform, so the
    georeference was discarded before anything could compare it. rasterio is what
    tools/verify_elevation._fetch_patch reads the same reply with -- one reader, so the producer and
    the only independent verifier of these heights agree by construction rather than by luck. That
    function was fixed for this exact fault and this one was not; that is the whole reason the error
    survived.

    Refuses rather than guessing when there is no transform at all, the same way _fetch_patch does:
    a surface whose position on the ground is unknown cannot be measured, and this project prefers a
    refusal to an unsupported number.
    """
    with rasterio.open(io.BytesIO(raw)) as ds:
        arr = ds.read(1).astype('float64')
        b, identity = ds.bounds, ds.transform.is_identity
    if identity:
        raise NoGeoreference("the elevation service returned a raster with no georeference, so the "
                            "ground it covers is unknown")
    return arr, [b.left, b.bottom, b.right, b.top]


def only_holes(raw):
    """The set of hole numbers ONLY= names, or REFUSE if it names something this parser cannot read.

    It used to keep the digit tokens and drop the rest, so `ONLY=1-9` silently meant EVERY hole -- and
    the "ONLY holes:" acknowledgement sits inside `if only:`, so it printed nothing either. On the stage
    that replaces 0.4 m LiDAR surfaces with the coarse 1 m DEM, and next to OVERWRITE=1 in the same
    usage block, a typo that DOUBLES the scope of the run is the one way a scope filter must not fail.

    Ranges stay unsupported on purpose: the documented syntax is a comma-separated list (`ONLY=14,16`
    here, in README.md and in PIPELINE.md), and a second spelling understood only by this script is a
    parser the docs and the other stages do not share. `1-9` is a typo for `1,9`, so say so.

    Extracted so the TEST can call it -- main() cannot be exercised without the network. Same reason
    is_flat_fill and both keeps_existing_surface predicates are predicates.
    """
    txt = (raw or "").replace(" ", "")
    toks = [t for t in txt.split(",") if t]
    bad = [t for t in toks if not t.isdigit()]
    if bad or (txt and not toks):
        why = ("not a hole number: " + ", ".join(repr(t) for t in bad)) if bad else "it names no hole"
        raise SystemExit(
            f"cannot read ONLY={raw!r}: {why}.\n"
            f"  ONLY takes a comma-separated list of hole numbers, e.g. ONLY=14,16 -- ranges are not\n"
            f"  supported. Dropping what it cannot read would mean EVERY hole, which with OVERWRITE=1\n"
            f"  is the difference between rebuilding the holes you named and rebuilding all of them.")
    return {int(t) for t in toks}


def main():
    # ONLY=14,10 restricts the run to specific holes. Protecting the neighbours' sharp 0.4 m
    # surfaces is no longer its job -- keeps_existing_surface() does that unconditionally now, which
    # also means ONLY= on a hole that already holds a good LiDAR surface writes nothing without
    # OVERWRITE=1.
    only = only_holes(os.environ.get("ONLY", ""))
    if only:
        print("ONLY holes:", sorted(only))
    d = json.load(open(f"{DIR}/osm_geom.json"))
    els = d['elements']
    greens = [e for e in els if e.get('tags', {}).get('golf') == 'green' and e.get('geometry')]
    # ONE hole-line chooser for the whole pipeline. This used to keep the longest way per ref,
    # first-wins on a tie -- the exact heuristic geo.hole_lines was written to replace after it
    # flipped under element reordering on castlewood-valley (two candidates 604 m apart, both
    # 3 vertices). Three fetch scripts still carried their own copy of it, so the tree corridors,
    # the green surfaces and the gap-fill DEM could each have been placed on a DIFFERENT line
    # from the one render_hole draws and fetch_hole_elev measures against. They all agreed on all
    # 198 holes only because the cached element order happened to favour it. geo.hole_lines picks
    # by distance to the course centre and REFUSES a near-tie rather than guessing.
    _loc = config.COURSE.get('location') or {}
    holes = list(geo.hole_lines(els, _loc.get('lat'), _loc.get('lon')).values())
    gc = [(g, *centroid(g)) for g in greens]

    # Bind EVERY hole to its green and check the invariant BEFORE deciding what to write. Building
    # `bound` inside the write loop made the check vacuous exactly when it mattered: both `ONLY=` and
    # the gap-fill skip below `continue` before the binding, so on a normal course -- where every
    # green already has a 0.4 m surface and all 18 are skipped -- `bound` was empty and
    # assert_one_green_per_hole compared nothing. Now it sees the whole course whatever gets written.
    bound = {}
    for h in holes:
        ref = h['tags'].get('ref')
        if ref and ref.isdigit():
            bound[int(ref)] = geo.match_green(h['geometry'], greens, label=f"hole {int(ref)}")[0]
    geo.assert_one_green_per_hole(bound, label=config.SLUG)

    done = 0
    skipped = []
    for h in holes:
        ref = h['tags'].get('ref')
        if not (ref and ref.isdigit()):
            continue
        if only and int(ref) not in only:
            continue
        hn = int(ref); line = h['geometry']
        # FILL GAPS, do not overwrite better data. This stage shares dem_hd/ with fetch_dem_hd.py,
        # which builds 0.4 m LiDAR surfaces, and it used to rewrite every hole it was given -- so
        # running it without ONLY= silently replaced every 0.4 m green with the coarse 1 m one and
        # said nothing about the better data it had just discarded. The books stayed HONEST (each
        # card prints "1 m data") but a whole course quietly lost its precision. Found cold-building
        # Monarch Bay: the result was 3,889,124 bytes against the committed 4,973,620, with "1 m
        # data" on greens that have real LiDAR.
        if keeps_existing_surface(f"{OUT}/hole{hn:02d}.json", OVERWRITE):
            skipped.append(hn)
            continue
        green, gend, _tend = geo.match_green(line, greens, label=f"hole {hn}")
        prev = line[1] if gend is line[0] else line[-2]
        appr = bearing(prev['lat'], prev['lon'], gend['lat'], gend['lon'])

        # NB: this list used to be called `geo`, shadowing the geo MODULE. It worked only because
        # `import geo` sat inside the loop and rebound the name each iteration -- moving that import
        # to the top, the obvious tidy-up, would have made geo.match_green() an AttributeError on a
        # list from the second hole onward.
        gpoly = green['geometry']; lats = [p['lat'] for p in gpoly]; lons = [p['lon'] for p in gpoly]
        clat, clon = centroid(green)
        mrg = 12.0; dlat = mrg/R_LAT; dlon = mrg/mlon(clat)
        # The extent to ASK FOR, and a size that makes the grid square in METRES over it. What gets
        # RECORDED is whatever extent the reply carries; the two agree only because of
        # adjustAspectRatio=false below. See _served_patch.
        q_xmin, q_xmax = min(lons)-dlon, max(lons)+dlon
        q_ymin, q_ymax = min(lats)-dlat, max(lats)+dlat
        wm = (q_xmax-q_xmin)*mlon(clat); hm = (q_ymax-q_ymin)*R_LAT
        W = max(48, int(wm/0.5)); H = max(48, int(hm/0.5))
        # adjustAspectRatio=false is what makes bbox AND size both honoured. By default exportImage
        # keeps `size` and stretches the bbox to match its aspect ratio in the image SR, which in
        # 4326 means square pixels in DEGREES -- 0.5038 m east-west against 0.6366 m north-south on
        # monarch-bay hole 1, measured. render_green smooths with `gauss(arr, 3.0)`, one sigma in
        # PIXELS, so that grid blurs 1.5 m one way and 1.9 m the other however the bbox is recorded.
        # With the flag: 0.5038 m by 0.5042 m, square in metres the way fetch_dem_hd's 0.4 m grid is.
        url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
               f"?bbox={q_xmin},{q_ymin},{q_xmax},{q_ymax}&bboxSR=4326&imageSR=4326&size={W},{H}"
               "&adjustAspectRatio=false"
               "&format=tiff&pixelType=F32&interpolation=RSP_BilinearInterpolation"
               "&noData=-9999&noDataInterpretation=esriNoDataMatchAny&f=image")
        arr = bbox = None
        refused = None
        for attempt in range(4):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'greenbook/1.0'}), timeout=120).read()
                arr, bbox = _served_patch(raw)
                break
            except NoGeoreference as e:
                refused = str(e)        # not transient: retrying cannot conjure up a transform
                break
            except Exception as e:
                print(f"hole {hn}: attempt {attempt+1} failed ({e}); retry"); time.sleep(1.5)
        if refused:
            print(f"hole {hn}: REFUSED -- {refused}; no surface written")
            continue
        if arr is None:
            print(f"hole {hn}: DEM fetch FAILED"); continue
        # The ARRAY is the authority for its own shape, and its GeoTIFF for its own extent. Both used
        # to be taken from the request instead, and the meta then described a patch of ground the
        # pixels beside it do not cover.
        H, W = arr.shape
        xmin, ymin, xmax, ymax = bbox
        # Honesty gate -- the SAME contract fetch_dem_hd.py writes. This producer used to write no
        # gate keys at all, so render_green's meta.get("insufficient") was None (falsy) and nothing
        # could stop an unusable surface from being printed. This is the path a BRAND-NEW course
        # takes, which made it the least gated and most used producer.
        arr = np.where(np.isfinite(arr) & (np.abs(arr) < 1e30), arr, np.nan)   # NoData sentinels
        arr = np.where(arr <= -9998.0, np.nan, arr)                            # requested noData
        nan_frac, n_in, relief = _green_interior_stats(
            arr, [xmin, ymin, xmax, ymax], W, H, [[p['lat'], p['lon']] for p in gpoly])
        # Out of coverage, 3DEP's exportImage returns a CONSTANT raster (measured at St Andrews:
        # min 0.0, max 0.0, one unique value) rather than any NoData marker -- so a nan_frac test
        # alone reported insufficient=False for a green with no measurement at all, and the book
        # printed 18 cards of "feeds back (subtle) - 0.0%". A real green is never perfectly flat.
        flat = is_flat_fill(n_in, nan_frac, relief)
        insufficient = bool(n_in == 0 or nan_frac > NAN_FRAC_MAX or flat)
        if flat:
            print(f"hole {hn}: CONSTANT surface across the green ({relief*100:.1f} cm of relief) -- "
                  f"outside 3DEP coverage, not a flat green; no slope will be printed")
        # ONE unit: the array carries no georeference, so an array beside a stale bbox is a printed
        # slope for ground the pixels do not cover. See surface_io.commit_surface.
        surface_io.commit_surface(
            f"{OUT}/hole{hn:02d}", arr,
            dict(hole=hn, approach_bearing=appr, bbox=[xmin, ymin, xmax, ymax], W=W, H=H,
                 green_id=green['id'], green_center=[clat, clon],
                 polygon=[[p['lat'], p['lon']] for p in gpoly],
                 source="USGS 3DEP seamless 1 m @0.5m sampling",
                 nan_frac=nan_frac, insufficient=insufficient,
                 # A seamless raster has no point cloud, so there is no measured point
                 # density. Report None rather than inventing a plausible number.
                 density=None))
        if insufficient:
            print(f"hole {hn}: INSUFFICIENT -- {nan_frac*100:.0f}% of the green has no elevation; "
                  f"no slope will be printed")
        done += 1
        print(f"hole {hn:2d}: green {green['id']} {arr.shape} approach {appr:.0f}deg")
        time.sleep(0.2)
    if skipped:
        print(f"\nkept the existing 0.4 m LiDAR surface on {len(skipped)} green(s): "
              f"{', '.join(str(h) for h in sorted(skipped))}\n"
              f"  This stage only FILLS GAPS. To replace a good surface with the 1 m DEM anyway, "
              f"re-run with OVERWRITE=1.")
    print(f"\nWrote {done} greens -> {OUT}")

if __name__ == "__main__":
    main()
