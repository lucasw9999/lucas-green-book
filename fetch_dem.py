#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generic per-green elevation for any course, from the USGS 3DEP seamless DEM service
(public domain) -- no per-course LiDAR tile picking required.

Reads COURSE_DIR/osm_geom.json, matches each green to its hole (for approach
bearing), downloads a small DEM patch per green via the 3DEP exportImage service
sampled at 0.5 m/px, and writes COURSE_DIR/dem_hd/holeNN.{npy,json} -- the same
format render_green.py consumes.

That service is a MULTI-RESOLUTION MOSAIC, so 0.5 m/px is the sampling and NOT the resolution: at the
only greens this stage has ever run on it answers from 3DEP's 1/9 arc-second tier, 2.72 m E-W x 3.43 m
N-S. The recorded `source` therefore names the source cell MEASURED out of the reply's own resampling
lattice (source_cell_clause) instead of asserting a tier -- it said "1 m" for the life of the project,
which the cards and legal/03 both republished.

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
given, silently replacing 0.4 m greens with the coarse seamless one (Monarch Bay: 3,889,124 bytes
against 4,973,620).

Run:  COURSE=<slug> python3 fetch_dem_hd.py     # first: 0.4 m where LiDAR allows
      COURSE=<slug> python3 fetch_dem.py        # then: the seamless mosaic for the ones it refused
      ONLY=14,16 ...                            # restrict to specific holes (a comma-separated
                                                #   list of numbers; ranges are refused, not guessed)
      OVERWRITE=1 ...                           # replace a good surface on purpose -- with the coarse
                                                #   seamless one, or with a blank green when 3DEP's own
                                                #   reply is refused
"""
import urllib.request, json, math, io, time, os
import numpy as np, rasterio
import config
import geo
from geo import mlat, mlon   # the project's ONE figure of the Earth -- never re-declare these
from lidar_coverage import _env_on   # the project's ONE reading of an escape-hatch key -- see it there
import surface_io

DIR = config.COURSE_DIR
OUT = f"{DIR}/dem_hd"; os.makedirs(OUT, exist_ok=True)
# Sweep stale staging files first, the same way fetch_lidar.py sweeps laz/. A run killed outright
# (SIGKILL, laptop asleep, power) leaves a .holeNN.*.part that commit_surface's `finally` never got to
# run for, and it then sits in dem_hd/ forever -- which matters because that file is the only on-disk
# trace of the surface pair's rename window, and evidence a dead run also leaves is not evidence.
surface_io.sweep_staged(OUT)
# replace a good surface on purpose -- with the coarse seamless mosaic (keeps_existing_surface), or with
# a blank green when this stage's own reply is refused (keeps_readable_surface). Read through
# lidar_coverage._env_on, this project's ONE off-vocabulary, NOT for truthiness:
# bool(os.environ.get(...)) made OVERWRITE=0, OVERWRITE=false and
# OVERWRITE=no all mean YES, so the word "false" armed the path that trades every 0.4 m LiDAR green
# for the coarse seamless mosaic -- the exact loss keeps_existing_surface below exists to prevent. An
# explicit off must be off, and the vocabulary this flag used to spell for itself was one of five
# hand-written copies that then all had to learn `off` and a `.strip()` separately.
OVERWRITE = _env_on("OVERWRITE")
def is_seamless(meta):
    """True when this surface came from the seamless mosaic rather than 0.4 m LiDAR ground returns.

    One spelling of the test, matching generate.py and tools/gen_provenance.py."""
    return "seamless" in str((meta or {}).get("source", "")).lower()


def keeps_existing_surface(meta_path, overwrite=False):
    """True when meta_path already holds a GOOD 0.4 m LiDAR surface that must not be replaced.

    This stage shares dem_hd/ with fetch_dem_hd.py and used to rewrite every hole it was given, so
    running it without ONLY= silently replaced every 0.4 m green with the coarse seamless one and said
    nothing about the better data it had just discarded. The books stayed HONEST -- each such card
    prints the source cell its own array measures -- but a whole course quietly lost its precision.
    Found cold-building Monarch Bay: the result was 3,889,124 bytes against the committed 4,973,620,
    with a coarse-data mark on greens that have real LiDAR.

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
    # card prints the coarse-data honesty label, gen_provenance to count fallbacks in the legal
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


def keeps_readable_surface(meta_path, overwrite=False):
    """True when meta_path holds a READABLE surface that an INSUFFICIENT fetch here must not replace.

    THE OTHER HALF of keeps_existing_surface above, and it cannot be that function. That one answers
    "may this stage refresh what is on disk?" and returns False for a seamless meta ON PURPOSE, because
    filling gaps -- including re-filling its own -- is the whole job. This one answers a different
    question, and only once the reply is already known to be unusable: "is what is here better than the
    blank green I am about to write?" For a refused reply the answer is yes even when the record it
    protects is seamless, which is exactly the case the predicate above must let through.

    THE GAP THAT LEFT: a plain `COURSE=<slug> python3 fetch_dem.py` -- no ONLY=, no OVERWRITE= -- re-
    fetches every green this stage owns. If 3DEP answers WORSE than last time -- a CONSTANT raster out
    of coverage (measured at St Andrews; see the note beside `flat` in main()) or more than
    NAN_FRAC_MAX of the green with no elevation -- the honesty gate marked the new surface
    insufficient=True and main() committed it anyway, `insufficient` being RECORDED in the meta and
    never gating the write. render_green.render then returns _blank_green, so a card that printed a real
    read prints blank, with no flag set and nothing in the output naming what was lost. The retry loop
    cannot catch it either: it retries on EXCEPTIONS, and a bad-quality reply is a 200 carrying a
    perfectly valid GeoTIFF.

    THE EXACT MIRROR of fetch_dem_hd.keeps_existing_surface, deliberately down to the rule -- any
    positively-sourced record that is not itself a refusal, whatever built it -- because it is the same
    trade seen from this side. That stage must not blank a working seamless fill; this one must not
    blank a working anything. One idiom for "do not replace a good surface with a worse one", in both
    producers of dem_hd/.

    WHAT IT STILL PERMITS, which is everything this stage exists to do:
      * a GAP -- no meta on disk at all -- is filled.
      * a good surface is replaced by another GOOD one. Only a refused reply is a downgrade, and
        refreshing a seamless green with a better seamless read stays this stage's job.
      * a record ALREADY marked insufficient is rebuilt: that IS the gap, and re-fetching it is the
        repair -- the same reading of `insufficient` keeps_existing_surface makes.
      * a meta with no source at all stays fillable. Unknown provenance is not protected on a guess,
        which is the rule both other predicates in this pair of stages keep.
      * an unreadable file is rebuilt.
      * OVERWRITE=1 still does it on purpose, so this is a safety net and not a wall.

    A predicate rather than an inline branch so it can be exercised by truth table -- the same reason
    is_flat_fill, only_holes and both keeps_existing_surface predicates are predicates.
    """
    if overwrite or not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path) as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return False                        # unreadable: rebuilding it is the repair
    return bool(str((prev or {}).get("source", "")).strip()) and not prev.get("insufficient")



def centroid(g):
    la = sum(p['lat'] for p in g['geometry']) / len(g['geometry'])
    lo = sum(p['lon'] for p in g['geometry']) / len(g['geometry']); return la, lo
def bearing(a_lat, a_lon, b_lat, b_lon):
    dE = (b_lon - a_lon) * mlon((a_lat + b_lat) / 2); dN = (b_lat - a_lat) * mlat((a_lat + b_lat) / 2)
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


class UnusableReply(Exception):
    """The reply cannot be used, and retrying it will not change that.

    Base class so main()'s no-retry handler covers every such verdict by kind rather than by name --
    a new one added later must not fall through to the generic `except Exception`, which retries four
    times and then reports a fetch failure for something that was never transient.
    """


class NoGeoreference(UnusableReply):
    """The reply carries no GeoTIFF transform, so the extent it covers is unknown."""


class NotSquareInMetres(UnusableReply):
    """Reserved: kept so `UnusableReply` has more than one concrete kind and the base-class handler in
    main() is exercised by intent rather than by accident. NOT raised for an anisotropic reply -- see
    sampling_note for why such a reply is recorded rather than refused."""


# How far off square a served pixel may be before its sampling is no longer "0.5 m". Set from the
# corpus, not guessed: across all 198 built surfaces the served pixel measures between 1.000041 and
# 1.008503 off square (integer W,H against a real-valued span), so this admits every real one with
# ~6x margin. The failure it exists to catch is a grid square in DEGREES, whose metric aspect is
# mlat/mlon -- 1.2584 at monarch-bay -- rejected by 5x. (The retired flat-earth constants made that
# ratio exactly 1/cos(lat), i.e. 1.2637 there, which is the figure the shipped URLs were built with.)
PIXEL_ASPECT_MAX = 1.05


def served_pixel_aspect(bbox, W, H):
    """max/min of the served pixel's two side lengths IN METRES. 1.0 is square.

    Reads the property off the ARTIFACT -- the bbox the GeoTIFF carries and the array's own shape --
    which is the only way to know the service honoured the request. A URL-literal assertion proves a
    string was sent; ArcGIS REST silently IGNORES parameters it does not recognise, so what was sent
    and what was honoured are different questions, and only the second one matters here.

    The centre latitude comes from the bbox itself, so this needs nothing from the caller and can be
    applied to any recorded surface, including the 198 already on disk.
    """
    xmin, ymin, xmax, ymax = bbox
    clat = (ymin + ymax) / 2.0
    mx = (xmax - xmin) * mlon(clat) / W
    my = (ymax - ymin) * mlat(clat) / H
    lo, hi = min(abs(mx), abs(my)), max(abs(mx), abs(my))
    return float("inf") if lo == 0 else hi / lo


def source_cell_clause(arr, px_x, px_y):
    """(clause, warning or None) naming the SOURCE grid a reply was resampled from. "" if no array.

    The other half of the provenance claim, and the half that was pure assertion. `sampling_note`
    below has always described the OUTPUT sampling -- 0.5 m per pixel, square in metres -- and that
    part was measured. The SOURCE resolution was the literal string "1 m", typed once, and 3DEP's
    seamless ImageServer is a MULTI-RESOLUTION MOSAIC: at the six greens this stage has actually run
    on it serves the 1/9 arc-second tier, 2.72 m E-W x 3.43 m N-S at that latitude. Six cards, the
    guide note and two lines of legal/03 published a resolution 2.7x and 3.4x better than the data,
    about 9x in area, on the one label that exists to say trust this green LESS.

    An aspect test cannot ever catch this: PIXEL_ASPECT_MAX compares the served pixel's two sides to
    each other, so every tier of the mosaic passes it identically. What catches it is the resampling
    lattice in the pixels themselves -- see render_green.source_lattice, which needs no network and
    works on the 198 arrays already on disk.

    CROSS-CHECKED LIVE ONCE, on 2026-08-05, against the service's own catalog (`/query` with
    `LowPS < 20` at monarch-bay hole 1's green centre): the finest raster covering that point is
    `CA_AlamedaCounty_2021_B21` at LowPS 1, and the next is OID 11875
    `ned19_n37x75_w122x25_ca_sanfrancisocoast_2010` at LowPS 3.4358 in WebMercator -- which is
    3.4358*cos(37.69 deg) = 2.7189 m on the ground -- inside the 2.70-2.73 m E-W range the six arrays
    measure, and 0.23% from hole 1's own 2.7250 m. (This read "= 2.720 m ... to three decimals" and
    neither half held: the arithmetic gives 2.719, and that green's array gives 2.725.) "ned19" is
    literally NED 1/9 arc-second. Its AcquisitionDate is 2011-04-03. That date is NOT
    published anywhere in this repo and must not be: the offline lattice is what any future run can
    re-derive from its own artifacts, whereas which raster the default mosaic rule resolves to is a
    property of the service on the day. legal/03 says instead that this build decodes no acquisition
    date for that raster, which is exactly true and is gradeable without a network. A stage that
    recorded the served OID and date per green would close that gap properly.

    Fails LOUD rather than quiet when the lattice cannot be found: publishing the served pixel as the
    source cell would understate the coarseness, which is the dangerous direction for this label.

    render_green is imported lazily so this module keeps importing in an environment that has not
    built a course yet, the same way fetch_hole_elev.py reaches for it.
    """
    if arr is None:
        return "", None
    import render_green
    lat = render_green.source_lattice(arr, px_x, px_y)
    if not lat["resampled"]:
        return (", source cell NOT MEASURED",
                f"no resampling lattice was found in this reply ({lat['flat_ew']*100:.1f}% / "
                f"{lat['flat_ns']*100:.1f}% of its second differences sit at the float32 floor, "
                f"against the {render_green.SOURCE_LATTICE_FLAT_MIN*100:.0f}% a resampled patch "
                f"needs), so the grid it was sampled from is unknown. The recorded source says so "
                f"rather than naming the 0.5 m pixel, which would overstate the resolution")
    return (f", {lat['cell_ew_m']:.2f} m E-W x {lat['cell_ns_m']:.2f} m N-S source cell", None)


def sampling_note(bbox, W, H, arr=None):
    """(source string, warning or None) -- the provenance claim this patch's pixels actually support.

    The whole squareness of this stage's grid rested on ONE query parameter, `adjustAspectRatio=false`,
    and nothing had ever checked it. ArcGIS REST silently ignores parameters it does not recognise, so
    if that one is dropped, renamed, or retired the service goes back to keeping `size` and stretching
    the bbox to square pixels IN DEGREES -- anisotropic by mlat/mlon, 1.2584 at monarch-bay's 37.6916
    deg, measured by re-issuing all six shipped URLs, which the retired constants made 1/cos(lat) =
    1.2637. The external-contract review that covered OSM, ASPRS,
    TNM and R&A never ran at ArcGIS, and this is the path a BRAND-NEW course takes for every green the
    LiDAR stage refuses: the least gated and most used producer in the pipeline.

    RECORDED, not refused. An expanded reply is still a usable surface once it is placed right -- the
    bbox is read off the GeoTIFF either way, so it degrades to merely anisotropic rather than
    mis-georeferenced, which is the decision
    test_a_seamless_green_records_the_extent_its_array_actually_covers exists to hold. What must not
    survive is the CLAIM: this string is what tools/gen_provenance.py prints into legal/03, and on an
    anisotropic grid the sampling half of it is false. So the source string states the sampling the
    pixels support, and the caller prints the warning.

    It also used to state a SOURCE resolution -- "USGS 3DEP seamless 1 m" -- that nothing measured and
    that was wrong at every green this stage ever wrote. That clause now comes from the array; see
    source_cell_clause. The two halves are separate because they fail separately: a reply can be
    square in metres and still come from a tier three times coarser than the label claimed.

    Every consumer tests `"seamless" in source.lower()` (fetch_dem.is_seamless, generate.py,
    gen_provenance._greens), so both spellings keep that word.
    """
    xmin, ymin, xmax, ymax = bbox
    clat = (ymin + ymax) / 2.0
    mx = (xmax - xmin) * mlon(clat) / W
    my = (ymax - ymin) * mlat(clat) / H
    cell, cell_warn = source_cell_clause(arr, abs(mx), abs(my))
    aspect = served_pixel_aspect(bbox, W, H)
    if aspect <= PIXEL_ASPECT_MAX:
        return f"USGS 3DEP seamless mosaic{cell} @0.5m sampling", cell_warn
    aniso = (f"served pixels are {aspect:.4f}x from square in metres ({mx:.4f} m E-W vs {my:.4f} m "
             f"N-S). exportImage did not honour adjustAspectRatio=false -- 1/cos(lat) is "
             f"{1 / math.cos(math.radians(clat)):.4f} here, so check the request parameters against "
             f"the current ArcGIS REST API. The surface is still placed correctly (its bbox is read "
             f"off the GeoTIFF), but render_green's gauss(arr, 3.0) is one sigma in PIXELS, so the read "
             f"is blurred unequally, and the '@0.5m sampling' provenance claim is NOT being recorded")
    return (f"USGS 3DEP seamless mosaic{cell}, sampled "
            f"{mx:.3f} m E-W x {my:.3f} m N-S (ANISOTROPIC, not 0.5 m square)",
            aniso if cell_warn is None else aniso + " -- and " + cell_warn)



def _served_patch(raw):
    """(array, [xmin, ymin, xmax, ymax]) from an exportImage reply -- the extent it actually SERVED.

    The georeference has to travel with the pixels. `size={W},{H}` is derived from the bbox's METRIC
    aspect (0.5 m per pixel each way), while `imageSR=4326` makes ArcGIS adjust the bbox to that
    size's aspect ratio IN DEGREES -- so without adjustAspectRatio=false the service expands the
    latitude span by mlat/mlon and the array does not cover the bbox it was asked for. Measured by
    re-issuing all six shipped monarch-bay URLs, which were requested under the retired constants
    that made that ratio 1/cos(37.6916 deg) = 1.2637: 1.2542x to 1.2675x, each north and south edge
    out by 5.5 to 7.7 m. On the true WGS84 scales the same ratio there is 1.2584. Recording the requested bbox anyway put an
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

    Squareness in METRES is measured separately, at the point where the claim about it gets written --
    see sampling_note. It is not a refusal here, because an expanded reply is still usable once placed
    right; what it must not do is go on calling itself 0.5 m sampling.
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
    that replaces 0.4 m LiDAR surfaces with the coarse seamless one, and next to OVERWRITE=1 in the same
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
    # A SPENT WAIVER MUST LEAVE A RECORD. Every ALLOW_* key in this project prints `KEY set -- <what it
    # accepted>` when it is exercised; OVERWRITE printed nothing, and the only mention of it in this
    # stage's output was the SUGGESTION below, on the path where it is NOT set. So the one flag that can
    # discard a 0.4 m LiDAR surface was the one flag whose use left no trace -- and `courses/` is
    # gitignored, so the surface it discards has no other copy and the run's own output is the only
    # record there is. A suggestion is not a receipt.
    if OVERWRITE:
        print("WARNING: OVERWRITE set -- this run will REPLACE existing green surfaces with the coarse\n"
              "  seamless mosaic instead of keeping the 0.4 m LiDAR ones, and a green whose reply this\n"
              "  run REFUSES will replace a working surface with a blank one. dem_hd/ has no other copy.")
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
        # running it without ONLY= silently replaced every 0.4 m green with the coarse seamless one
        # and said nothing about the better data it had just discarded. The books stayed HONEST
        # (each such card prints the source cell its own array measures) but a whole course quietly
        # lost its precision. Found cold-building Monarch Bay: the result was 3,889,124 bytes
        # against the committed 4,973,620, with a coarse-data mark on greens that have real LiDAR.
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
        mrg = 12.0; dlat = mrg/mlat(clat); dlon = mrg/mlon(clat)
        # The extent to ASK FOR, and a size that makes the grid square in METRES over it. What gets
        # RECORDED is whatever extent the reply carries; the two agree only because of
        # adjustAspectRatio=false below. See _served_patch.
        q_xmin, q_xmax = min(lons)-dlon, max(lons)+dlon
        q_ymin, q_ymax = min(lats)-dlat, max(lats)+dlat
        wm = (q_xmax-q_xmin)*mlon(clat); hm = (q_ymax-q_ymin)*mlat(clat)
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
            except UnusableReply as e:
                # not transient: retrying cannot conjure up a transform, nor make a degrees-square
                # grid square in metres. Caught by BASE CLASS so a verdict added later cannot fall
                # through to the generic handler below and be retried four times as a network blip.
                refused = str(e)
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
        # DO NOT TRADE A WORKING SURFACE FOR A REFUSED ONE. This is the reply-QUALITY direction of the
        # fault the two keeps_* predicates already guard between them: keeps_existing_surface above stops
        # this stage replacing a good 0.4 m green with the coarse mosaic, and
        # fetch_dem_hd.keeps_existing_surface stops that stage replacing a working fill with a blank one.
        # A plain re-run of THIS stage could still blank a green on its own, because `insufficient` was
        # recorded in the meta below and never gated the commit -- so a worse 3DEP answer (a constant
        # raster out of coverage, or a green mostly NoData) overwrote a real read with insufficient=True
        # and the card printed blank, with no flag set and no line naming the surface that was lost.
        #
        # Same shape and same escape hatch as fetch_dem_hd's guard: refuse, say so, OVERWRITE=1 to do it
        # on purpose. A SUFFICIENT reply still replaces whatever is here -- that is gap-filling and
        # refreshing, which is what this stage is for; only the refused case is a downgrade.
        #
        # BEFORE the `flat` notice below on purpose: that notice ends "no slope will be printed", which
        # is true of the surface being refused and false of the one being kept. The refusal line carries
        # the same relief figure, so nothing is lost by not printing both.
        if insufficient and keeps_readable_surface(f"{OUT}/hole{hn:02d}.json", OVERWRITE):
            print(f"hole {hn:2d}: seamless refused (nan {nan_frac:.3f}, relief {relief*100:.1f} cm, "
                  f"{n_in} green cell(s)) -- KEEPING the existing surface. "
                  f"OVERWRITE=1 to replace it with a blank green.")
            continue
        if flat:
            print(f"hole {hn}: CONSTANT surface across the green ({relief*100:.1f} cm of relief) -- "
                  f"outside 3DEP coverage, not a flat green; no slope will be printed")
        # The provenance claim this patch's pixels actually support -- BOTH halves measured. "@0.5m
        # sampling" is only true if the service honoured adjustAspectRatio=false, which nothing
        # checked; and the SOURCE resolution used to be the hardcoded words "1 m", which was wrong at
        # every green this stage has ever written (3DEP's seamless service is a multi-resolution
        # mosaic and answered here from its 1/9 arc-second tier). Both come off the artifact now: the
        # aspect from the served bbox and the array's own shape, the source cell from the resampling
        # lattice in the pixels. That string is what gen_provenance prints into legal/03.
        _source, _aniso = sampling_note([xmin, ymin, xmax, ymax], W, H, arr)
        if _aniso:
            print(f"hole {hn}: !! {_aniso}")
        # ONE unit: the array carries no georeference, so an array beside a stale bbox is a printed
        # slope for ground the pixels do not cover. See surface_io.commit_surface.
        surface_io.commit_surface(
            f"{OUT}/hole{hn:02d}", arr,
            dict(hole=hn, approach_bearing=appr, bbox=[xmin, ymin, xmax, ymax], W=W, H=H,
                 green_id=green['id'], green_center=[clat, clon],
                 polygon=[[p['lat'], p['lon']] for p in gpoly],
                 source=_source,
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
              f"  This stage only FILLS GAPS. To replace a good surface with the seamless one anyway, "
              f"re-run with OVERWRITE=1.")
    print(f"\nWrote {done} greens -> {OUT}")

if __name__ == "__main__":
    main()
