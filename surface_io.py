#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
The one rule for putting a green surface on disk.

A green surface is TWO files -- dem_hd/holeNN.npy and dem_hd/holeNN.json -- and they only mean
anything together: the array carries no georeference of its own, so the meta's bbox, polygon and
green_center are what place every pixel. Both producers (fetch_dem_hd.py at 0.4 m from the point
cloud, fetch_dem.py at 1 m from the seamless DEM) write into the same directory, so the rule lives
here once rather than in each of them.
"""
import glob
import hashlib
import json, os

import numpy as np

DIGEST_KEY = "array_sha256"
_STAGED_GLOB = ".hole*.part"


def staged_names(base):
    """The two staging paths commit_surface writes for `base`. One spelling, used by the sweep too."""
    d, n = os.path.dirname(base), os.path.basename(base)
    return os.path.join(d, f".{n}.npy.part"), os.path.join(d, f".{n}.json.part")


def sweep_staged(out_dir):
    """Remove stale staging files in a dem_hd directory. Returns what it removed.

    The `finally` in commit_surface handles an exception; it cannot handle the process not coming back
    -- a SIGKILL, a laptop asleep mid-build, power. Then a `.holeNN.*.part` sits there forever.

    Never valid data, by the same argument fetch_lidar.py's laz/ sweep makes: a staged file is only
    ever renamed into place after its write returns, so anything still wearing the staged name is by
    construction incomplete. And it must be swept rather than tolerated, because a leftover
    `.holeNN.json.part` is the ONLY on-disk trace of the two-rename window in commit_surface -- as
    evidence it is worth nothing if a finished run leaves one too.

    Matched on the dot-prefixed staged pattern alone, so it can never reach a real `holeNN.npy` or
    `holeNN.json`.
    """
    gone = []
    for stale in sorted(glob.glob(os.path.join(out_dir, _STAGED_GLOB))):
        os.remove(stale)
        gone.append(stale)
    if gone:
        print(f"  removed {len(gone)} stale staged surface file(s) from a killed run: "
              f"{', '.join(os.path.basename(g) for g in gone)}")
    return gone


def array_digest(arr):
    """A fingerprint of the array a meta is committed beside, stable across save and load.

    dtype and shape go in with the bytes, and the bytes are taken C-contiguous, because .npy records
    fortran_order and np.load may hand back a differently-ordered view of identical values -- hashing
    raw memory would then disagree with itself across a round trip for no real difference.

    Hashed rather than merely counted because the point is to catch a pair whose two halves came from
    DIFFERENT RUNS, and the only property that reliably distinguishes those is the content. W and H
    do not: see commit_surface.
    """
    a = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(f"{a.dtype.str}|{a.shape}|".encode())
    h.update(a.tobytes())
    return h.hexdigest()


def commit_surface(base, arr, meta):
    """Write `arr` to base + ".npy" and `meta` to base + ".json" so that both land, or neither does.

    This was two independent statements -- `np.save(...)` immediately followed by `json.dump(...)` --
    in both producers. Anything in between (Ctrl-C during a 198-green build, a full disk, an exception
    while encoding the meta) left the NEW array sitting beside the PREVIOUS run's extent, and that is
    not a crash, it is a wrong printed number: render_green.render takes H,W from the array but the
    bbox, the ring and the centre from the meta, so a mismatched pair rasterises the green against an
    extent the pixels do not cover. That exact disagreement shipped once, when fetch_dem recorded the
    bbox it ASKED FOR beside the raster 3DEP RETURNED -- the mask stretched ~26% past the green's north
    and south edges and the printed tilt on six monarch-bay cards was inflated 16.6% to 52.5%. Nothing
    downstream notices: check_scale.py and cross_flight_check.py re-derive metres-per-pixel from the
    same meta and inherit the error, and verify_elevation's absolute gate cannot see a stretched
    vertical mapping.

    Both files are staged first, then renamed. The staged names are DOT-PREFIXED so that nothing which
    globs `hole*.npy` or `dem_hd/hole*.json` -- the corpus sweeps in the test suite, check_scale.py,
    gen_provenance.py, cross_flight_check.py -- can pick a half-written surface up as a real one.

    WHAT THE TWO RENAMES STILL LEAVE, and why it needed more than a disclosure. os.replace is atomic
    per file; two of them are not one transaction, so a process killed between them still leaves last
    run's meta beside this run's array. The outcomes split, and they were not equally survivable:

      * shapes differ -> the read side refuses the pair and names both shapes. Loud, recoverable.
      * shapes EQUAL, bbox different -> nothing looked at it. Silent, permanent, and a wrong printed
        slope on a card a junior carries.

    The silent case is REACHABLE, not theoretical, because the pixel dimensions truncate:
    `W = max(48, int(wm/0.5))` (fetch_dem.py) and `W = max(40, int(wm/RES))` (fetch_dem_hd.py). A green
    whose polygon is re-traced in OSM, or moves, or changes size by less than one pixel keeps the same
    W and H while its bbox changes -- so a rebuild interrupted between the two renames lands there.

    Nor does the rename ORDER help. The .json is still renamed last because it is what every consumer
    gates on (render_green refuses a hole with no meta; keeps_existing_surface reads the meta alone),
    so on a FIRST build a crash leaves an array nothing will read. On a REBUILD, where both names
    already hold last run's pair, either order tears.

    So the pair is made SELF-IDENTIFYING instead: the meta carries a digest of the array committed
    with it, and render_green refuses a pair whose array does not hash to what its meta claims. That is
    shape-blind, which is exactly what the silent case needs. The residual is now one case -- a tear
    whose two runs produced BIT-IDENTICAL arrays under different bboxes -- which for a sampled terrain
    surface means the elevations did not move at all, and a green flat enough for that prints the same
    slope either way. A staged DIRECTORY rename, or a single .npz holding array and meta together,
    would be atomic outright; both change the on-disk layout that render_green, check_scale.py,
    gen_provenance.py, cross_flight_check.py and 198 built greens all glob, so they are a migration
    plus a full rebuild, not a fix.

    Surfaces built before the digest existed carry no DIGEST_KEY and are read unverified -- there is
    nothing to compare them against. They gain the check the next time they are rebuilt.

    Both staged files are removed if anything goes wrong before the renames. A .part left behind is not
    just untidy: dem_hd/.holeNN.json.part is the one on-disk trace of the rename window above, so it is
    evidence, and evidence a failed run also leaves is worth nothing. sweep_staged covers the case no
    `finally` can -- the process not coming back at all.
    """
    t_npy, t_json = staged_names(base)
    try:
        # np.save is given an open handle, not a path: handed a path it APPENDS ".npy" unless the name
        # already ends in it, which would turn the staged name into ".holeNN.npy.part.npy".
        with open(t_npy, "wb") as f:
            np.save(f, arr)
        # A copy, not a mutation: a producer that reused its meta dict after committing would otherwise
        # carry one hole's digest onto the next.
        with open(t_json, "w", encoding="utf-8") as f:
            json.dump(dict(meta, **{DIGEST_KEY: array_digest(arr)}), f)
        os.replace(t_npy, base + ".npy")
        os.replace(t_json, base + ".json")
    finally:
        for t in (t_npy, t_json):
            # after a successful pair of renames neither exists, so this is a no-op on the happy path
            if os.path.exists(t):
                os.remove(t)
