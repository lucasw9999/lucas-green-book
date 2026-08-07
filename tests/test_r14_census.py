#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Five things nothing graded: the size of the bare-earth grid, the ground returns it is built from,
what the OSM census counts as water, the two escape hatches that waive fetch_trees' cache checks,
and the one geodetic formula that is still hand-copied.

Each test here reproduced a live defect on the tree it was written against. The evidence is in the
docstrings as measurements, not as claims -- the numbers came out of the corpus on disk and out of the
red run, and every one of them is re-derived here rather than quoted.
"""
import contextlib
import io
import json
import os
import re
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# LAS 1.4 public header block: Max X, Min X, Max Y, Min Y, Max Z, Min Z, six little-endian doubles
# starting here (spec table 2.1: 8-byte doubles after the six scale/offset ones at 131..178). The
# block is UNCOMPRESSED at the head of a .laz too, which is what lets a fixture pose the one question
# laspy's writer cannot: a tile whose header states its real extent while a point lies outside it.
LAS_BBOX_OFFSET = 179

# The largest single allocation this stage may ask for while gridding ONE tile, in float64 cells.
# 2**20 cells is 8 MiB. Measured against what the corpus really needs: over all 78 tiles on disk the
# header extents are 2999.99 US survey feet on 41 tiles (914.4 m), 1499.99 m on 4 and 1000.0 m on 33,
# so the widest tile is 1500 m and the largest bare-earth grid any stored tile can produce is
# 376 x 376 cells, 1.08 MiB. This budget is 7.4x that and orders of magnitude below every figure the
# defect reached.
GRID_CELL_BUDGET = 2 ** 20

# How far the ONE stray class-2 return sits outside the tile, in metres. These are the distances the
# audit measured the unbounded allocation at; the last two are what an int32 coordinate scaled by 0.01
# or a garbage State-Plane value reaches.
OUTLIER_M = (914.0, 4_000.0, 61_000.0, 100_000.0, 1_000_000.0)


class _OverBudget(MemoryError):
    """Raised INSTEAD of allocating, so measuring this defect cannot take the machine with it.

    The unfixed arithmetic asks for up to 466 GB from a single np.full. A test that let that call
    through would be an OOM kill, not a failure -- no traceback, no report, and the rest of the suite
    dead with it. So the spy records the shape that was REQUESTED and refuses the ones that are the
    finding, which is the same measurement without the crater.
    """


@contextlib.contextmanager
def _watch_allocations(np_mod, budget_cells=GRID_CELL_BUDGET):
    """Record every np.full shape asked for inside the block; refuse anything over `budget_cells`.

    np.full is the one allocation in this stage sized from data rather than from the OSM polygon, so
    it is the thing to watch. Patched by delegation, so nothing else in the block behaves differently.
    """
    seen = []
    real = np_mod.full

    def full(shape, fill_value, *a, **k):
        n = 1
        for d in (shape if isinstance(shape, (tuple, list)) else (shape,)):
            n *= int(d)
        seen.append(n)
        if n > budget_cells:
            raise _OverBudget("np.full asked for %s = %d cells (%.2f GiB at 8 bytes/cell)"
                              % (shape, n, n * 8 / 2 ** 30))
        return real(shape, fill_value, *a, **k)

    np_mod.full = full
    try:
        yield seen
    finally:
        np_mod.full = real


@contextlib.contextmanager
def _scratch_course(name, lat=40.0, lon=-75.0):
    """A throwaway course under courses/, bound to COURSE, torn down afterwards.

    It has to live under courses/ because config.py resolves COURSE there; the slug starts with '_'
    so conftest's deletion guard classes it as scratch, and it carries the pid so two of these
    running at once cannot delete each other's course.json.
    """
    import shutil

    slug = "_r14_%s_%d" % (name, os.getpid())
    cdir = os.path.join(ROOT, "courses", slug)
    prev = os.environ.get("COURSE")
    mods = ("config", "fetch_trees", "fetch_dem_hd", "fetch_osm", "render_hole", "generate")
    os.makedirs(cdir, exist_ok=True)
    try:
        with open(os.path.join(cdir, "course.json"), "w", encoding="utf-8") as f:
            json.dump(dict(slug=slug, name="R14 " + name, address="",
                           location={"lat": lat, "lon": lon}, par=72, green_speed="",
                           tees=[dict(name="Card", yards=100)],
                           featured_tee="Card", hole_cols=["par", "mens_hcp", "Card"],
                           holes={"1": [72, 1, 100], "2": [72, 2, 100]},
                           osm_bbox=[lat - 0.01, lon - 0.01, lat + 0.01, lon + 0.01],
                           sources={}), f)
        os.environ["COURSE"] = slug
        for m in mods:
            sys.modules.pop(m, None)
        yield slug, cdir
    finally:
        if prev is None:
            os.environ.pop("COURSE", None)
        else:
            os.environ["COURSE"] = prev
        for m in mods:
            sys.modules.pop(m, None)
        shutil.rmtree(cdir, ignore_errors=True)


def _fetch_trees():
    try:
        import fetch_trees
    except ImportError as e:                       # laspy/pyproj are declared but may be absent
        pytest.skip("fetch_trees needs %r" % (getattr(e, "name", None) or e,))
    return fetch_trees


def _write_tile(path, crs_str, x, y, z, cls, withheld=None, n_outside=0):
    """One synthetic LAZ tile. `n_outside` = how many TRAILING points lie outside the header extent.

    laspy GROWS the header to cover every point it writes, so a file written normally can never hold a
    point outside its own stated extent -- and that is precisely the state a corrupt real tile is in.
    The patch is what makes the fixture able to ask the question.

    The patched bbox is computed from the coordinates AS STORED, not from the floats handed in: a LAS
    file quantises XY to its scale/offset, so a bbox written from the pre-quantisation values sits a
    fraction inside the data and clips ~180 edge points of this lattice. That would still pass, and it
    would be measuring the wrong thing -- the fixture has to drop exactly the points it planted.
    """
    import laspy
    import numpy as np
    from pyproj import CRS

    hdr = laspy.LasHeader(version="1.4", point_format=6)
    hdr.add_crs(CRS.from_user_input(crs_str))
    las = laspy.LasData(hdr)
    las.x = np.asarray(x, float)
    las.y = np.asarray(y, float)
    las.z = np.asarray(z, float)
    las.classification = np.asarray(cls)
    if withheld is not None:
        las.withheld = np.asarray(withheld, bool)
    las.write(path)
    if not n_outside:
        return
    back = laspy.read(path)
    inside = slice(0, len(np.asarray(back.x)) - n_outside)
    xmin, xmax = float(np.asarray(back.x)[inside].min()), float(np.asarray(back.x)[inside].max())
    ymin, ymax = float(np.asarray(back.y)[inside].min()), float(np.asarray(back.y)[inside].max())
    with open(path, "rb") as fh:
        b = bytearray(fh.read())
    assert bytes(b[0:4]) == b"LASF" and (b[24], b[25]) == (1, 4), \
        "this fixture patches a LAS 1.4 public header block and laspy wrote something else"
    struct.pack_into("<6d", b, LAS_BBOX_OFFSET,
                     xmax, xmin, ymax, ymin, float(np.max(z)), float(np.min(z)))
    with open(path, "wb") as fh:
        fh.write(bytes(b))
    with laspy.open(path) as f:
        h = f.header
        assert (h.x_min, h.x_max, h.y_min, h.y_max) == (xmin, xmax, ymin, ymax), \
            ("the header patch did not take (%s), so this fixture cannot pose the question it claims"
             % ((h.x_min, h.x_max, h.y_min, h.y_max),))
    outside = ((np.asarray(back.x) < xmin) | (np.asarray(back.x) > xmax)
               | (np.asarray(back.y) < ymin) | (np.asarray(back.y) > ymax))
    assert int(outside.sum()) == n_outside, (
        "the fixture means to place %d point(s) outside the tile's own header extent and placed %d"
        % (n_outside, int(outside.sum())))


def _tree_course(ft, where, outlier_m=None, honest_header=True, sunken_withheld=0):
    """Everything fetch_trees.main() READS, under `where`: laz/ plus the three osm caches.

    Two holes 400 m apart, each a 200 m centreline, over a dense class-2 lattice with a line of
    unclassified returns 8 m above it -- the shape of the corpus, where 10 of 11 courses with tiles
    carry no class-5 vegetation at all.

      outlier_m       -- add ONE class-2 return this far beyond the lattice, diagonally. Nothing else
                         about the tile changes, so any change in the grid is the outlier's doing.
      honest_header   -- patch the header back over the LATTICE only, so the tile states its real
                         extent and the outlier lies outside it -- what a real producer's header says.
                         False leaves laspy's grown header, i.e. a tile whose own header claims the
                         outlier: a corrupt header.
      sunken_withheld -- how many class-2 returns to place 40 m BELOW the lattice under hole 1's
                         canopy, flagged `withheld`. The producer disowns them; used they would put
                         local ground 40 m down, and the 8 m canopy would read as 48 m -- outside the
                         2.5-35 m band, so the markers above them DISAPPEAR.
    """
    import numpy as np

    os.makedirs(os.path.join(where, "laz"), exist_ok=True)
    loc = ft.config.COURSE["location"]
    cx, cy = ft.FWD.transform(loc["lon"], loc["lat"])

    def ll(x, y):
        lo, la = ft.INV.transform(x, y)
        return {"lat": la, "lon": lo}

    origins = {1: (cx, cy), 2: (cx + 400.0, cy)}
    geom = [{"type": "way", "id": 10 + hn, "tags": {"golf": "hole", "ref": str(hn)},
             "geometry": [ll(ox, oy), ll(ox, oy + 200.0)]}
            for hn, (ox, oy) in origins.items()]
    with open(os.path.join(where, "osm_geom.json"), "w", encoding="utf-8") as f:
        json.dump({"elements": geom}, f)
    # a clubhouse 2 km away: fetch_trees hard-stops on a cache with no building polygons, and it must
    # not sit in either corridor or it would drop the markers under test as roof returns
    bld = [ll(cx + 2000.0, cy + 2000.0), ll(cx + 2020.0, cy + 2000.0),
           ll(cx + 2020.0, cy + 2020.0), ll(cx + 2000.0, cy + 2020.0),
           ll(cx + 2000.0, cy + 2000.0)]
    with open(os.path.join(where, "osm_course.json"), "w", encoding="utf-8") as f:
        json.dump({"elements": [{"type": "way", "id": 99, "tags": {"building": "yes"},
                                 "geometry": bld}]}, f)
    with open(os.path.join(where, "osm_relations.json"), "w", encoding="utf-8") as f:
        json.dump({"elements": []}, f)

    gx, gy = np.meshgrid(np.arange(cx - 60.0, cx + 480.0, 3.0),
                        np.arange(cy - 20.0, cy + 220.0, 3.0))
    xs = [gx.ravel()]
    ys = [gy.ravel()]
    zs = [np.zeros(gx.size)]
    cls = [np.full(gx.size, 2)]
    wh = [np.zeros(gx.size, bool)]
    for hn, (ox, oy) in sorted(origins.items()):
        ty = np.arange(oy + 10.0, oy + 190.0, 5.0)       # ~36 markers after the 5 m thinning grid
        xs.append(np.full(ty.size, ox + 6.0))
        ys.append(ty)
        zs.append(np.full(ty.size, 8.0))                 # inside the 2.5-35 m band
        cls.append(np.full(ty.size, 1))                  # unclassified, like most of this corpus
        wh.append(np.zeros(ty.size, bool))
    if sunken_withheld:
        ty = np.arange(cy + 10.0, cy + 190.0, 5.0)[:sunken_withheld]
        xs.append(np.full(ty.size, cx + 6.0))
        ys.append(ty)
        zs.append(np.full(ty.size, -40.0))
        cls.append(np.full(ty.size, 2))
        wh.append(np.ones(ty.size, bool))
    if outlier_m is not None:
        xs.append(np.array([float(gx.max()) + outlier_m]))
        ys.append(np.array([float(gy.max()) + outlier_m]))
        zs.append(np.array([0.0]))
        cls.append(np.array([2]))
        wh.append(np.zeros(1, bool))
    _write_tile(os.path.join(where, "laz", "tile.laz"), ft.UTM,
                np.concatenate(xs), np.concatenate(ys), np.concatenate(zs), np.concatenate(cls),
                withheld=np.concatenate(wh),
                n_outside=(1 if (outlier_m is not None and honest_header) else 0))


def _run_trees(ft, where):
    """fetch_trees.main() against `where`. Returns (layer or None, largest np.full request, exit text)."""
    import numpy as np

    ft.DIR = str(where)
    out = io.StringIO()
    exited = None
    with _watch_allocations(np) as seen:
        try:
            with contextlib.redirect_stdout(out):
                ft.main()
        except _OverBudget as e:
            exited = "OVER BUDGET: %s" % e
        except SystemExit as e:
            exited = str(e)
    biggest = max(seen) if seen else 0
    p = os.path.join(str(where), "trees_lidar.json")
    layer = None
    if exited is None and os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            layer = json.load(fh)
    return layer, biggest, exited, out.getvalue()


# ---------------------------------------------------------------------------
# F-1  the bare-earth grid was sized from an unbounded coordinate span
# ---------------------------------------------------------------------------
def test_one_stray_ground_return_cannot_size_the_bare_earth_grid(tmp_path):
    """`nx = int((x[gnd].max() - gx0) / GC) + 2` read its span off the DATA, so one junk class-2
    return sized a multi-gigabyte allocation and nothing named the tile.

    Every point of every tile went through `pt2utm.transform(las.x, las.y)` with no coordinate sanity
    filter and no clip to the tile's own header extent, and the min/max of the class-2 subset became
    the grid. Measured on this fixture, which is one 540 x 240 m lattice plus ONE class-2 return that
    far outside it:

        outlier at      grid requested (float64)
             914 m        0.4 MiB   -- inside any budget; the defect is invisible here
           4,000 m        7.7 MiB
          61,000 m        1.8 GiB
         100,000 m        4.7 GiB
       1,000,000 m      466   GiB

    pyproj is why this is not caught upstream: for the five courses whose tiles are reprojected
    EPSG:6419 -> EPSG:26910 a garbage native coordinate comes back as a FINITE garbage metre value,
    not inf, so the arithmetic succeeds and the allocation is the first thing that fails -- as a
    MemoryError or an exit-137 with no traceback and nothing saying which tile.

    LATENT on the corpus and measured so: over all 78 tiles on disk not one point lies outside its own
    tile's header bbox (0 of 2,479,193,850), the widest tile is 1500 m across, and the largest grid
    currently reachable is 1.08 MiB. This is the same class tools/lidar_dates.py bounds by construction
    ("one junk gps_time ... sized the allocation by itself") and carries a regression for; fetch_trees
    was the one remaining site.

    The fix has to be a CEILING, not an assertion: a point outside the tile's own header extent is by
    definition not a point this stage may use, so it is dropped before it can be measured. The proof
    is two-part -- the grid must not grow with the outlier's distance, AND the markers must be the
    same ones the clean tile gives, because a fix that simply refused every one of these tiles would
    also pass the first half.
    """
    with _scratch_course("gridspan"):
        ft = _fetch_trees()
        clean = tmp_path / "clean"
        _tree_course(ft, clean)
        base, base_cells, base_exit, _log = _run_trees(ft, clean)
        assert base_exit is None, "the fixture itself must build a layer: %s" % base_exit
        assert base and sum(len(v) for v in base.values()) >= 8, \
            "the fixture must put markers on both holes, else nothing below is measured: %r" % base
        assert base_cells <= GRID_CELL_BUDGET, \
            "a clean 540 x 240 m tile already wants %d cells; the budget is wrong" % base_cells

        rows = []
        for d in OUTLIER_M:
            where = tmp_path / ("outlier_%d" % d)
            _tree_course(ft, where, outlier_m=d)
            layer, cells, exited, log = _run_trees(ft, where)
            rows.append((d, cells, exited, layer, log))

        def table():
            return "\n".join(
                "      outlier %10.0f m -> %12d cells (%8.2f MiB)%s"
                % (d, c, c * 8 / 2 ** 20, "" if e is None else "  " + e.splitlines()[0][:90])
                for d, c, e, _l, _g in rows)

        over = [(d, c) for d, c, _e, _l, _g in rows if c > GRID_CELL_BUDGET]
        assert not over, (
            "ONE stray class-2 return outside the tile's own header extent still sizes the "
            "bare-earth grid:\n%s\n    the clean tile wants %d cells; the budget is %d."
            % (table(), base_cells, GRID_CELL_BUDGET))
        for d, cells, exited, layer, log in rows:
            assert exited is None, (
                "the outlier at %.0f m must be DROPPED, not turned into a refusal of a tile whose "
                "own header is honest: %s" % (d, exited))
            assert layer == base, (
                "the outlier at %.0f m changed the markers the tile yields, so it is still being "
                "measured:\n%s" % (d, table()))
            assert re.search(r"dropping 1 point\(s\) outside", log), (
                "nothing said the outlier at %.0f m was dropped, so the grid is the right size for "
                "some other reason:\n%s" % (d, log[-500:]))
        assert len({c for _d, c, _e, _l, _g in rows}) == 1, (
            "the grid size still varies with the outlier's distance:\n%s" % table())


def test_a_tile_whose_own_header_claims_an_impossible_span_is_refused_by_name(tmp_path):
    """The other half of the ceiling: a header that itself claims the junk.

    Clipping to the tile's own header extent bounds the grid by that extent, which is the right answer
    when the header is honest -- and it is unbounded again if the header is not. laspy's writer GROWS
    the header to cover every point it is given, so a fixture written normally is exactly that tile:
    one 540 x 240 m lattice plus one class-2 return 1,000 km away, with a header that states all of
    it. Unfixed, that asked np.full for 466 GiB.

    The requirement here is narrower than "do not allocate": the run must say WHICH TILE, because an
    exit-137 with no traceback over 78 tiles is a day's work to locate. So the message is asserted to
    carry the file name and the span it refused.
    """
    with _scratch_course("badheader"):
        ft = _fetch_trees()
        where = tmp_path / "corrupt"
        _tree_course(ft, where, outlier_m=1_000_000.0, honest_header=False)
        layer, cells, exited, _log = _run_trees(ft, where)
        assert cells <= GRID_CELL_BUDGET, (
            "a tile whose own header spans 1,000 km still sized the grid from it: %d cells "
            "(%.1f GiB)" % (cells, cells * 8 / 2 ** 30))
        assert exited and "OVER BUDGET" not in exited, (
            "a header this wide must be REFUSED by name, not gridded: %r" % exited)
        assert "tile.laz" in exited, \
            "the refusal must name the tile -- over 78 tiles an unnamed one is unfindable: %s" % exited
        assert re.search(r"\d", exited), \
            "the refusal must state the span it measured: %s" % exited
        assert layer is None, "a refused run must not write a tree layer"


# ---------------------------------------------------------------------------
# F-2  the bare-earth grid was built from returns the producer disowns
# ---------------------------------------------------------------------------
def test_the_bare_earth_grid_drops_the_ground_returns_the_producer_disowned(tmp_path):
    """`gnd = cls == 2` took every class-2 return, including the ones the vendor marked DO NOT USE.

    fetch_dem_hd applies that filter to THE SAME TILES, and its own comment says why: "so the next
    course's tiles cannot quietly contribute rejected points to a green." Measured over all 78 tiles
    in this corpus (2,479,193,850 points): `withheld` resolves on 78 of 78 and marks 19,979,730
    points, `synthetic` marks none, and ZERO of the withheld points are class-2 -- which is why the
    tree layer on disk is unaffected and why this was latent.

    It is not harmless in principle. The bare-earth grid is what every marker's height-above-ground is
    measured against, so a disowned ground return either invents a marker or deletes one. This fixture
    takes the delete direction because it is the one the book's second rule cares about: 12 disowned
    class-2 returns 40 m BELOW the lattice, under hole 1's canopy. Used, local ground drops to -40 m,
    the 8 m canopy reads as 48 m, and every marker above them falls outside the 2.5-35 m band.

    Scope, stated because the asymmetry is deliberate: the filter is applied to the GROUND returns
    only, which is what fetch_dem_hd does and what the finding asks for. Applying it to the CANDIDATE
    returns as well would drop 17,376,591 points across this corpus and move drawn ink on shipped
    cards -- a change that has to be made deliberately and measured, not smuggled in beside a fix.
    """
    with _scratch_course("disowned"):
        ft = _fetch_trees()
        clean = tmp_path / "clean"
        _tree_course(ft, clean)
        base, _c, base_exit, _log = _run_trees(ft, clean)
        assert base_exit is None and base, "the fixture must build a layer: %s" % base_exit
        n1 = len(base.get("1") or [])
        assert n1 >= 8, "hole 1 needs markers for this to measure anything, got %d" % n1

        sunk = tmp_path / "sunken"
        _tree_course(ft, sunk, sunken_withheld=12)
        layer, _c, exited, _log = _run_trees(ft, sunk)
        assert exited is None, "the disowned-point fixture must still run: %s" % exited
        assert layer == base, (
            "12 class-2 returns the PRODUCER disowned changed the tree layer -- hole 1 went from %d "
            "markers to %d, so the bare-earth grid is still built from points marked withheld"
            % (n1, len(layer.get("1") or [])))

        # ...and it must be fetch_dem_hd's own lookup, not a second copy of the flag names here
        import fetch_dem_hd as fdh
        src = open(os.path.join(ROOT, "fetch_trees.py"), encoding="utf-8").read()
        assert "disowned_mask" in src and "DISOWNED_FLAGS" in src, (
            "fetch_trees no longer routes through fetch_dem_hd.disowned_mask / DISOWNED_FLAGS; two "
            "copies of a producer-disowned filter over the same tiles is how they drift apart")
        assert not re.search(r"getattr\(\s*las\s*,\s*[\"']withheld", src), \
            "fetch_trees has grown its own withheld lookup again"
        assert set(fdh.DISOWNED_FLAGS) >= {"withheld", "synthetic"}, \
            "the shared flag set no longer covers both producer-disowned bits: %r" % (fdh.DISOWNED_FLAGS,)


# ---------------------------------------------------------------------------
# F-3  the OSM census counted a SUPERSET of the water that is drawn
# ---------------------------------------------------------------------------
def _osm_module():
    for m in ("config", "fetch_osm", "render_hole"):
        sys.modules.pop(m, None)
    try:
        import fetch_osm
    except ImportError as e:
        pytest.skip("fetch_osm needs %r" % (getattr(e, "name", None) or e,))
    return fetch_osm


def _way(i, tags):
    return {"type": "way", "id": i, "tags": dict(tags),
            "geometry": [{"lat": 38.0, "lon": -121.0}, {"lat": 38.001, "lon": -121.001}]}


def test_the_waterway_census_counts_exactly_the_watercourses_a_card_draws(tmp_path):
    """The census's `waterway` bucket counted every way carrying the key -- dams, culverts, tunnels --
    while render_hole draws only `is_visible_watercourse`. So a reply could lose a real stream and gain
    a culvert and the count would not move.

    That defeats the census's whole purpose. Its docstring says it is ONE spelling of "what is in this
    reply", shared by the shrink guard and the printout, and the guard's unit has to be the class a
    card DRAWS or a swap inside the unit is invisible -- the identical defect 60b9eb2 fixed one level
    up when `water` and `waterway` were one bucket, reappearing inside the survivor.

    Reproduced here at three ways: stream, stream, stream -> stream, stream, culverted stream. Both
    censuses read `waterway 3` and the guard was silent. And it is not a hypothetical shape: 29 of the
    corpus's 178 waterways are undrawn today (23 culverts, 4 tunnel=yes, 1 dam, 1 tunnel=covered), on
    8 of 12 courses -- merion 8 of 20, bay-view 4 of 14, philadelphia 4 of 16.

    Under the project's second rule a lost watercourse is a hazard the golfer can reach that the book
    no longer shows, so the loss has to reach the HAZARD waiver, by name.

    The undrawn ways are still counted, in a bucket of their own. Dropping them from the census
    entirely would put them in `other`, where a filled-in culvert becomes a structural abort; and
    silence about a class the fetch asked for is what put every building in `other` in the first
    place.
    """
    fo = _osm_module()
    import render_hole as rh

    assert fo.is_visible_watercourse is rh.is_visible_watercourse, (
        "the census and the renderer must share ONE definition of a drawn watercourse, or they drift: "
        "the census is what says a lost stream was lost")

    drawn = [_way(1, {"waterway": "stream"}),
             _way(2, {"waterway": "river", "name": "Cobbs Creek"}),
             _way(3, {"waterway": "ditch"})]
    undrawn = [_way(11, {"waterway": "stream", "tunnel": "culvert"}),
               _way(12, {"waterway": "river", "tunnel": "covered"}),
               _way(13, {"waterway": "stream", "tunnel": "yes"}),
               _way(14, {"waterway": "dam"}),
               _way(15, {"waterway": "drain", "covered": "yes"}),
               _way(16, {"waterway": "stream", "location": "underground"})]
    c = fo.census(drawn + undrawn)
    assert c["waterway"] == len(drawn), (
        "the census counts %d waterway ways where the card draws %d: a culvert, a tunnel and a dam "
        "are still in the bucket the shrink guard compares" % (c["waterway"], len(drawn)))
    assert sum(c.values()) == len(drawn) + len(undrawn), (
        "the undrawn ways left the census altogether (%s) -- they were fetched, so their count has to "
        "go somewhere or a filled-in culvert reads as a lost feature of some other kind" % dict(c))

    # THE REPRODUCED SWAP: one real stream lost, one culvert gained, the raw key count unmoved
    cache = tmp_path / "osm_course.json"
    before = [_way(100 + i, {"golf": "green"}) for i in range(18)] \
        + [_way(200 + i, {"golf": "hole"}) for i in range(18)] + drawn
    after = [_way(100 + i, {"golf": "green"}) for i in range(18)] \
        + [_way(200 + i, {"golf": "hole"}) for i in range(18)] + drawn[:2] \
        + [_way(300, {"waterway": "stream", "tunnel": "culvert"})]
    cache.write_text(json.dumps({"version": 0.6, "elements": before}))
    assert (sum(1 for e in before if (e.get("tags") or {}).get("waterway"))
            == sum(1 for e in after if (e.get("tags") or {}).get("waterway"))), \
        "this fixture must hold the RAW key count still, or it does not reproduce the defect"

    waivers = ("ALLOW_SHRINK", "ALLOW_HAZARD_SHRINK", "ALLOW_STRUCTURAL_SHRINK", "ALLOW_REBIND")
    held = {k: os.environ.get(k) for k in waivers}
    try:
        for k in waivers:
            os.environ.pop(k, None)
        fo._check_response({"version": 0.6, "elements": before}, str(cache), "osm_course.json")
        with pytest.raises(SystemExit) as ei:
            fo._check_response({"version": 0.6, "elements": after}, str(cache), "osm_course.json")
        msg = str(ei.value)
        assert "waterway 3 -> 2" in msg, (
            "a reply that lost a real stream and gained a culvert was accepted, or aborted without "
            "naming the loss: %s" % msg)
        assert "ALLOW_HAZARD_SHRINK" in msg, (
            "a lost watercourse is drawn hazard ink; the abort must name the hazard waiver: %s" % msg)

        # ...and the undrawn class must NOT be graded as hazard ink or as structure. A mapper marking
        # a reach culverted is an OSM improvement, and nothing draws or measures it.
        culverts = [_way(400 + i, {"waterway": "ditch", "tunnel": "culvert"}) for i in range(3)]
        cache2 = tmp_path / "with_culverts.json"
        cache2.write_text(json.dumps({"version": 0.6, "elements": before + culverts}))
        fo._check_response({"version": 0.6, "elements": before + culverts[:2]},
                           str(cache2), "osm_course.json")
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_no_stored_cache_loses_a_drawn_watercourse_to_the_new_census(tmp_path):
    """The census change moves numbers, so state which ones -- from the caches, not from a claim.

    Two things have to hold on every stored cache: an unchanged re-fetch stays silent (a guard that
    fires on ordinary work trains you to switch it off, and the flag in reach waives the checks that
    matter), and the drawn count plus the undrawn count still equals every way carrying the key, so
    nothing was quietly dropped from the accounting.
    """
    fo = _osm_module()
    caches = sorted(p for p in
                    (os.path.join(ROOT, "courses", s, "osm_course.json")
                     for s in sorted(os.listdir(os.path.join(ROOT, "courses")))
                     if not s.startswith("_"))
                    if os.path.exists(p))
    if not caches:
        pytest.skip("per-course data is gitignored; nothing to measure")
    waivers = ("ALLOW_SHRINK", "ALLOW_HAZARD_SHRINK", "ALLOW_STRUCTURAL_SHRINK")
    held = {k: os.environ.get(k) for k in waivers}
    try:
        for k in waivers:
            os.environ.pop(k, None)
        for p in caches:
            els = json.load(open(p))["elements"]
            fetchable = [e for e in els
                         if "_digitized" not in (e.get("tags") or {})
                         and e.get("_from_relation") is None]
            c = fo.census(fetchable)
            raw = sum(1 for e in fetchable
                      if (e.get("tags") or {}).get("waterway")
                      and (e.get("tags") or {}).get("building") in (None, "no")
                      and not (e.get("tags") or {}).get("golf")
                      and (e.get("tags") or {}).get("natural") != "water")
            drawn = sum(1 for e in fetchable if fo.is_visible_watercourse(e)
                        and (e.get("tags") or {}).get("building") in (None, "no")
                        and not (e.get("tags") or {}).get("golf")
                        and (e.get("tags") or {}).get("natural") != "water")
            assert c["waterway"] == drawn, (
                "%s: census says %d drawn watercourses, the renderer's own predicate says %d"
                % (os.path.relpath(p, ROOT), c["waterway"], drawn))
            assert c["waterway"] + c.get("waterway_undrawn", 0) == raw, (
                "%s: %d ways carry the waterway key but the census accounts for %d + %d"
                % (os.path.relpath(p, ROOT), raw, c["waterway"], c.get("waterway_undrawn", 0)))
            fo._check_response({"version": 0.6, "elements": list(fetchable)}, p,
                               os.path.basename(p))
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_undrawn_waterway_breakdown_is_derived_not_typed():
    """The undrawn-waterway figures in fetch_osm.py's census() docstring -- mirrored, in a different
    word order, in the docstring of test_the_waterway_census_counts_exactly_the_watercourses_a_card_draws
    above -- were typed once and left ungraded. An audit found the sentence self-contradicting (its
    own parenthesised breakdown summed to 30 while the headline said 29) and both the total and the
    "N of 12 courses" figure stale against the corpus on disk.

    Recompute everything here from courses/*/osm_course.json using fo.census() itself, so the
    census's own bucketing is what gets graded rather than a second implementation of it, and require
    BOTH copies of the sentence to state the freshly computed numbers. The courses-affected
    denominator is this project's whole corpus (however many course directories exist under
    courses/), not just however many happen to have a cached OSM reply today -- Poppy Ridge has none
    (blocked on elevation) and correctly contributes zero undrawn ways to the numerator while still
    counting toward that denominator.
    """
    fo = _osm_module()

    cdir = os.path.join(ROOT, "courses")
    slugs = sorted(s for s in os.listdir(cdir)
                    if not s.startswith("_") and os.path.isdir(os.path.join(cdir, s)))
    caches = [(s, os.path.join(cdir, s, "osm_course.json")) for s in slugs]
    caches = [(s, p) for s, p in caches if os.path.exists(p)]
    if not caches:
        pytest.skip("per-course data is gitignored; nothing to measure")

    total = undrawn = culverts = tunnel_yes = tunnel_covered = dams = 0
    courses_with_undrawn = 0
    per_course = {}
    for slug, p in caches:
        els = json.load(open(p))["elements"]
        c = fo.census(els)
        drawn, gone = c.get("waterway", 0), c.get("waterway_undrawn", 0)
        total += drawn + gone
        undrawn += gone
        per_course[slug] = (gone, drawn + gone)
        if gone:
            courses_with_undrawn += 1
        for e in els:
            t = e.get("tags") or {}
            if not t.get("waterway") or fo.is_visible_watercourse(e):
                continue
            if (t.get("building") not in (None, "no") or t.get("golf")
                    or t.get("natural") == "water"):
                continue                       # census buckets this elsewhere, not as waterway*
            if t.get("waterway") == "dam":
                dams += 1
            elif t.get("tunnel") == "culvert":
                culverts += 1
            elif t.get("tunnel") == "yes":
                tunnel_yes += 1
            elif t.get("tunnel") == "covered":
                tunnel_covered += 1
            else:
                pytest.fail(
                    "%s: an undrawn waterway way (id %s, tags %s) matches none of this test's own "
                    "reason buckets -- the corpus grew a new reason to go undrawn (a weir, a "
                    "lock_gate, a `covered` tag...) that the comment's enumeration would then also "
                    "be missing" % (slug, e.get("id"), t))
    assert culverts + tunnel_yes + tunnel_covered + dams == undrawn, (
        "this test's own breakdown (%d) does not sum to its own total (%d) -- fix the test before "
        "trusting it" % (culverts + tunnel_yes + tunnel_covered + dams, undrawn))
    want = (undrawn, total, culverts, tunnel_yes, tunnel_covered, dams,
            courses_with_undrawn, len(slugs))

    # Both docstrings wrap across source lines, so match against whitespace-collapsed text -- the
    # sentence is what is graded, not which column it happens to wrap at.
    osm_src = open(os.path.join(ROOT, "fetch_osm.py"), encoding="utf-8").read()
    osm_flat = re.sub(r"\s+", " ", osm_src)
    m1 = re.search(
        r"(\d+) of this corpus's (\d+) waterways are undrawn today \((\d+) culverts, (\d+) "
        r"tunnel=yes, (\d+) tunnel=covered, (\d+) dam\) on (\d+) of (\d+) courses", osm_flat)
    assert m1, ("fetch_osm.py's census() docstring no longer states the undrawn-waterway figures in "
                "the expected shape -- update this test's regex to match the new prose, or the prose "
                "regressed")
    got1 = tuple(int(g) for g in m1.groups())
    assert got1 == want, (
        "fetch_osm.py's census() docstring says (undrawn, total, culverts, tunnel=yes, "
        "tunnel=covered, dam, courses, of)=%s but courses/*/osm_course.json currently measures %s"
        % (got1, want))
    m1b = re.search(r"merion (\d+) of (\d+) and bay-view (\d+) of (\d+) among them", osm_flat)
    assert m1b, "fetch_osm.py's census() docstring no longer names merion/bay-view's own figures"
    assert (int(m1b.group(1)), int(m1b.group(2))) == per_course["merion-golf-club"], (
        "fetch_osm.py says merion %s/%s, the corpus measures %s"
        % (m1b.group(1), m1b.group(2), per_course["merion-golf-club"]))
    assert (int(m1b.group(3)), int(m1b.group(4))) == per_course["bay-view-golf-club"], (
        "fetch_osm.py says bay-view %s/%s, the corpus measures %s"
        % (m1b.group(3), m1b.group(4), per_course["bay-view-golf-club"]))

    test_src = open(os.path.join(ROOT, "tests", "test_r14_census.py"), encoding="utf-8").read()
    test_flat = re.sub(r"\s+", " ", test_src)
    m2 = re.search(
        r"(\d+) of the corpus's (\d+) waterways are undrawn today \((\d+) culverts, (\d+) "
        r"tunnel=yes, (\d+) dam, (\d+) tunnel=covered\), on (\d+) of (\d+) courses", test_flat)
    assert m2, ("this file's own mirrored docstring no longer states the undrawn-waterway figures in "
                "the expected shape -- update this test's regex to match the new prose, or the prose "
                "regressed")
    g = m2.groups()
    got2 = (int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[5]), int(g[4]), int(g[6]), int(g[7]))
    assert got2 == want, (
        "this file's own docstring says (undrawn, total, culverts, tunnel=yes, tunnel=covered, dam, "
        "courses, of)=%s but courses/*/osm_course.json currently measures %s" % (got2, want))
    m2b = re.search(r"merion (\d+) of (\d+), bay-view (\d+) of (\d+), philadelphia (\d+) of (\d+)",
                     test_flat)
    assert m2b, "this file's own docstring no longer names merion/bay-view/philadelphia's own figures"
    assert (int(m2b.group(1)), int(m2b.group(2))) == per_course["merion-golf-club"]
    assert (int(m2b.group(3)), int(m2b.group(4))) == per_course["bay-view-golf-club"]
    assert (int(m2b.group(5)), int(m2b.group(6))) == per_course["philadelphia-country-club"], (
        "this file says philadelphia %s/%s, the corpus measures %s"
        % (m2b.group(5), m2b.group(6), per_course["philadelphia-country-club"]))


# ---------------------------------------------------------------------------
# F-4  two escape hatches nothing pinned
# ---------------------------------------------------------------------------
# The vocabulary an explicit "off" is spelled in, and the one thing every hatch in this repo must
# agree on: ALLOW_X=0 / =false / =no must WAIVE NOTHING. bool(os.environ.get(..)) makes all three mean
# yes, and these two waive the guards that stand between a stale OSM cache and roofs drawn as trees.
HATCH_TABLE = (("", False), ("0", False), ("false", False), ("FALSE", False),
               ("no", False), ("No", False), ("1", True), ("true", True), ("yes", True))


@contextlib.contextmanager
def _flag(name, raw):
    held = os.environ.get(name)
    if raw is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = raw
    try:
        yield
    finally:
        if held is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = held


def test_the_two_stale_cache_hatches_are_pinned_by_behaviour():
    """ALLOW_NO_BUILDINGS and ALLOW_NO_RELATIONS were read inline inside main(), so nothing could
    reach them and narrowing, removing or inverting either was invisible.

    What they waive is not small. ALLOW_NO_BUILDINGS turns off the footprint test, and a clubhouse
    roof is 2.5-35 m above ground and reads exactly like canopy on the unclassified tiles most of this
    corpus uses -- 53 markers stood on Merion's clubhouse before that test existed. ALLOW_NO_RELATIONS
    accepts a cache fetched before the multipolygon pass, where a building, pond or fairway mapped as
    a relation is simply absent, so its roof or its open water comes back as trees.

    This repo already knew the hazard: the existing pin table's own docstring records that narrowing a
    module's off-vocabulary to ("", "0") -- which makes ALLOW_X=false a waiver -- left the whole suite
    at its baseline, and it names these two as the ones it could not reach. Pinning them needed the
    reads routed through the module's own `_env_on` and the guards lifted out of main() so a test can
    call them. Both halves are asserted here: the parse, over the same table the other hatches are
    driven over, and the BEHAVIOUR -- off means the guard fires, on means it is waived and the finding
    is still PRINTED, because a waiver that prints nothing is a silence.
    """
    with _scratch_course("hatches"):
        ft = _fetch_trees()
        for name, call, waived_needle in (
                ("ALLOW_NO_BUILDINGS", lambda: ft.check_buildings(0), "building"),
                ("ALLOW_NO_RELATIONS", lambda: ft.check_relations("/nonexistent/osm_relations.json"),
                 "RELATIONS")):
            assert hasattr(ft, "_env_on"), "fetch_trees no longer has the _env_on this pins"
            for raw, want in HATCH_TABLE + ((None, False),):
                with _flag(name, raw):
                    assert ft._env_on(name) is want, (
                        "fetch_trees._env_on: %s=%r parsed to %s, expected %s -- an explicit 'off' "
                        "must not waive the guard it names" % (name, raw, ft._env_on(name), want))
                    buf = io.StringIO()
                    exited = None
                    try:
                        with contextlib.redirect_stdout(buf):
                            call()
                    except SystemExit as e:
                        exited = str(e)
                    if want:
                        assert exited is None, (
                            "%s=%r must waive this guard: %s" % (name, raw, exited))
                        assert waived_needle in buf.getvalue() and name in buf.getvalue(), (
                            "%s=%r waived the guard in SILENCE; the finding it waives must still be "
                            "printed: %r" % (name, raw, buf.getvalue()))
                    else:
                        assert exited is not None, (
                            "%s=%r did NOT fire the guard -- an explicit off, or an unset flag, is a "
                            "waiver" % (name, raw))
                        assert name in exited, (
                            "the refusal must name the flag that waives it: %s" % exited)

        # ...and neither guard may fire on a cache that is FINE, or the hatch becomes routine
        with _flag("ALLOW_NO_BUILDINGS", None), _flag("ALLOW_NO_RELATIONS", None):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ft.check_buildings(7)
                ft.check_relations(os.path.join(ROOT, "requirements.txt"))
            assert buf.getvalue() == "", \
                "a complete cache must produce no warning at all, got %r" % buf.getvalue()


# ---------------------------------------------------------------------------
# F-6  the UTM zone formula was hand-copied into both fetch stages
# ---------------------------------------------------------------------------
INLINE_ZONE = re.compile(r"26900\s*\+\s*int\(")


def test_the_utm_zone_formula_lives_in_geo_and_nowhere_else():
    """geo.utm_epsg() was an UNFINISHED migration, not dead code.

    `git log -S'utm_epsg'` returns exactly one commit, d2b0d10, which ADDED it; nothing ever removed a
    caller. That commit's message frames geo.py as the shared home for "the same two facts ...
    previously derived independently in fetch_dem_hd.py and fetch_trees.py" -- the vertical unit and
    the UTM zone -- and it did wire both files to geo.vertical_scale(), but left the zone line inline
    in both. So the helper had zero callers and two byte-identical copies of its body.

    geo.py's own docstring says this exact duplication-drift hazard has already cost this project two
    audits (the nine-module R_LAT saga). Three copies of one geodetic formula is the setup for a
    fourth, and the zone decides which projection every tree position and every green surface is
    computed through.

    Re-derived over the 12 real courses rather than asserted: the helper and the copies agree on every
    longitude the corpus uses, so this is a de-duplication and not a behaviour change. If that stops
    being true the copies were the bug.
    """
    import geo

    for rel in ("fetch_trees.py", "fetch_dem_hd.py"):
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "geo.utm_epsg(" in src, (
            "%s still derives its own UTM zone; geo.utm_epsg exists to be the one copy" % rel)
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert not INLINE_ZONE.search(code), (
            "%s still carries a hand-copied `26900 + int(...)` zone formula beside the call to "
            "geo.utm_epsg -- two copies is how the R_LAT saga started" % rel)

    lons = []
    cdir = os.path.join(ROOT, "courses")
    for slug in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        if slug.startswith("_"):
            continue
        p = os.path.join(cdir, slug, "course.json")
        if not os.path.exists(p):
            continue
        lon = ((json.load(open(p)).get("location") or {}) or {}).get("lon")
        if lon is None:
            continue
        lons.append((slug, lon))
        assert geo.utm_epsg(lon) == "EPSG:%d" % (26900 + int((lon + 180) / 6) + 1), (
            "%s (lon %s): geo.utm_epsg gives %s, the formula the two fetch stages carried gives a "
            "different zone -- that is a real bug, not a de-duplication"
            % (slug, lon, geo.utm_epsg(lon)))
    if not lons:
        pytest.skip("per-course data is gitignored; no longitude to re-derive")
    assert len({geo.utm_epsg(l) for _s, l in lons}) >= 2, (
        "every course in this corpus lands in one UTM zone, so this check could not tell a broken "
        "formula from a working one: %s" % lons)


# ---------------------------------------------------------------------------
# F-5  prose that names a symbol nothing defines
# ---------------------------------------------------------------------------
def test_fetch_trees_prose_names_only_functions_that_exist():
    """fetch_trees.py's comments explain themselves by naming the code downstream that would swallow a
    failure, and one of those names was deleted.

    check_layer's docstring said `generate._course_has_trees()` drops the per-card "no tree data"
    caveat as noise. Commit 6325af0 removed that function -- it keyed the caveat on the LiDAR marker
    list while the renderer FALLS BACK to OSM tree nodes -- and replaced it with `_book_draws_trees()`,
    which asks what each hole DREW. The sentence was left pointing at a symbol that no longer exists,
    which is the exact species of defect that commit was raised to fix.

    Graded generically rather than by naming the one line, because the next stale reference will be a
    different symbol: every `<module>.<name>(` this file cites is resolved against that module's own
    defs, read from source so nothing has to be imported.
    """
    import ast

    src = open(os.path.join(ROOT, "fetch_trees.py"), encoding="utf-8").read()
    defs = {}
    for mod in ("generate", "render_hole", "geo", "fetch_osm", "fetch_dem_hd", "config",
                "surface_io", "distribution", "lidar_coverage"):
        p = os.path.join(ROOT, mod + ".py")
        if not os.path.exists(p):
            continue
        tree = ast.parse(open(p, encoding="utf-8").read())
        defs[mod] = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} | {
                         t.id for n in tree.body if isinstance(n, ast.Assign)
                         for t in n.targets if isinstance(t, ast.Name)}
    cited = set(re.findall(r"\b(%s)\.([A-Za-z_][A-Za-z0-9_]*)\(" % "|".join(defs), src))
    assert cited, "no cross-module references found in fetch_trees.py; this check reads nothing"
    missing = sorted("%s.%s" % (m, n) for m, n in cited if n not in defs[m])
    assert not missing, (
        "fetch_trees.py names %s, which no longer exists. A comment that points at a deleted symbol "
        "sends the next reader looking for code that is not there." % ", ".join(missing))


# ---------------------------------------------------------------------------
# F-7  a tile-unit grouping was typed once and left to drift from the corpus
# ---------------------------------------------------------------------------
def test_the_ftus_tile_grouping_comment_is_derived_not_typed():
    """GRID_SPAN_MAX_M's comment says how the corpus's 78 LAZ tiles split by header unit, and -- for
    the US-survey-foot ones -- how many span each exact tile size. An audit found the ftUS grouping
    loose: 41 is the count of ftUS tiles, but the old prose read as if every one of them spans
    2999.99 ftUS exactly, when a mapped delivery tiles its coverage area on a fixed grid and the
    tiles nearest the edge of that grid come out narrower in at least one axis.

    Re-derive every count here from the tiles' own headers -- header.mins/maxs and
    header.parse_crs(), never point data -- so the comment cannot drift from the corpus again.
    """
    import glob
    import laspy
    import geo

    tiles = sorted(glob.glob(os.path.join(ROOT, "courses", "*", "laz", "*.laz")))
    if not tiles:
        pytest.skip("per-course LAZ tiles are gitignored; nothing to measure")

    US_FT = 0.3048006096
    full_2999 = full_2499 = edge = metre_1499 = metre_1000 = 0
    unclassified = []
    for t in tiles:
        with laspy.open(t) as f:
            h = f.header
            dx = h.maxs[0] - h.mins[0]
            dy = h.maxs[1] - h.mins[1]
            crs = h.parse_crs()
        factor = None
        if crs is not None:
            try:
                factor = geo.vertical_scale(crs)
            except SystemExit:
                factor = None
        if factor and abs(factor - US_FT) < 1e-6:                  # US survey foot
            if abs(dx - 2999.99) < 0.02 and abs(dy - 2999.99) < 0.02:
                full_2999 += 1
            elif abs(dx - 2499.999) < 0.02 and abs(dy - 2499.999) < 0.02:
                full_2499 += 1
            else:
                edge += 1
        elif factor and abs(factor - 1.0) < 1e-9:                  # metre
            span = max(dx, dy)
            if abs(span - 1499.99) < 0.02:
                metre_1499 += 1
            elif abs(span - 1000.0) < 0.02 or abs(span - 999.99) < 0.02:
                metre_1000 += 1
            else:
                unclassified.append((t, dx, dy, factor))
        else:
            unclassified.append((t, dx, dy, factor))
    assert not unclassified, (
        "this test's own bucketing does not cover every tile in the corpus, so it cannot grade the "
        "comment honestly: %r" % unclassified)

    ftus_total = full_2999 + full_2499 + edge
    assert ftus_total + metre_1499 + metre_1000 == len(tiles)
    widest_ftus_m = round(2999.99 * US_FT, 1)

    src = open(os.path.join(ROOT, "fetch_trees.py"), encoding="utf-8").read()
    # The sentence wraps across "#"-prefixed source lines; collapse each line-continuation to a
    # single space so the sentence is what gets matched, not the column it wraps at.
    flat = re.sub(r"\n[ \t]*#+[ \t]*", " ", src)

    m = re.search(
        r"Measured over all (\d+) tiles on disk: (\d+) carry US survey feet in their header "
        r"\(([\d.]+) m at the widest\), (\d+) carry ([\d.]+) m, and (\d+) carry ([\d.]+) m\. "
        r"Of the (\d+) ftUS tiles, (\d+) span exactly ([\d.]+) ftUS, (\d+) span exactly ([\d.]+) "
        r"ftUS, and the remaining (\d+) are edge tiles", flat)
    assert m, ("fetch_trees.py's GRID_SPAN_MAX_M comment no longer states the tile-unit grouping in "
               "the expected shape -- update this test's regex to match the new prose, or the prose "
               "regressed")
    g = m.groups()
    got = (int(g[0]), int(g[1]), float(g[2]), int(g[3]), float(g[4]), int(g[5]), float(g[6]),
           int(g[7]), int(g[8]), float(g[9]), int(g[10]), float(g[11]), int(g[12]))
    want = (len(tiles), ftus_total, widest_ftus_m, metre_1499, 1499.99, metre_1000, 1000.0,
            ftus_total, full_2999, 2999.99, full_2499, 2499.999, edge)
    assert got == want, (
        "fetch_trees.py's GRID_SPAN_MAX_M comment says (total, ftus, widest_m, m1499_n, m1499_val, "
        "m1000_n, m1000_val, ftus_again, full2999, 2999.99, full2499, 2499.999, edge)=%s but the "
        "corpus's own tile headers currently measure %s" % (got, want))
