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
import json, os

import numpy as np


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

    What remains, stated rather than implied: the two renames are not one transaction, so a process
    killed between them still leaves a mismatch. That window is two syscalls instead of an entire array
    write plus a JSON encode, and the shape half of it is caught on the read side (render_green refuses
    a pair whose array does not match its recorded W,H). The .json is renamed LAST because it is what
    every consumer gates on -- render_green refuses a hole with no meta, and keeps_existing_surface
    reads the meta alone -- so it is the closest thing this pair has to a commit marker.
    """
    d, n = os.path.dirname(base), os.path.basename(base)
    t_npy = os.path.join(d, f".{n}.npy.part")
    t_json = os.path.join(d, f".{n}.json.part")
    # np.save is given an open handle, not a path: handed a path it APPENDS ".npy" unless the name
    # already ends in it, which would turn the staged name into ".holeNN.npy.part.npy".
    with open(t_npy, "wb") as f:
        np.save(f, arr)
    with open(t_json, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(t_npy, base + ".npy")
    os.replace(t_json, base + ".json")
