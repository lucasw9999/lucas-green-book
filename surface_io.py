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
cloud, fetch_dem.py at 0.5 m from the seamless mosaic, whose tier over this corpus's greens measures
2.72 m E-W x 3.43 m N-S -- so 0.5 m is that stage's sampling and not its resolution) write into the
same directory, so the rule lives here once rather than in each of them.
"""
import glob
import hashlib
import json, os
import sys

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

    Surfaces built before the digest existed carried no DIGEST_KEY and were read UNVERIFIED, because
    there was nothing on disk to compare them against -- which was all 198 of them, so the read-side
    check protected none of the corpus. They were stamped from the arrays already beside them rather
    than left to gain it on a rebuild: see stamp_digest and main(). A missing key is now an error.

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


def read_pair(base):
    """(arr, meta, digest) for a pair ALREADY on disk, refusing one whose two halves disagree.

    The read half of this module, and the shared definition of "a pair I am willing to MEASURE
    THROUGH". Every reader that derives a number from a surface goes through it -- the digest backfill
    below (twice: once to check every pair before writing anything, once while writing),
    fetch_hole_elev.green_elevation, tools/verify_elevation.py, tools/gen_provenance.py and
    tools/cross_flight_check.py. It was called by none of them for as long as it existed, and each had
    its own bare `json.load` + `np.load` instead, which is the drift this module exists to remove: the
    guard was written, documented, and covered nobody. fetch_hole_elev runs BEFORE generate.py, so the
    reader a tear reached first was the one that writes hole_elev.json.

    IT IS THE FLOOR, NOT THE CEILING, and that distinction is load-bearing rather than pedantic. A
    MISSING DIGEST is accepted here, because stamp_digest and main() below read unstamped pairs through
    this function in order to stamp them -- a strict read would make the backfill unable to read the
    pairs it exists to fix. render_green.render therefore keeps its own inline check rather than calling
    this: post-backfill it REFUSES a sidecar carrying no digest, since every built sidecar now has one
    and a missing key means the file was hand-written, restored from an older tree or truncated. Routing
    the renderer through here would loosen the guard that stands in front of every printed slope, which
    is the exact regression 7b2d097 shipped (`not in (None, digest)` covered 0 of 198 greens). It also
    blanks an `insufficient` green without opening the array at all, which this cannot do.

    Raises ValueError naming the disagreement. NEVER writes, and never opens the .npy for anything but
    a read: the array is the measurement, the sidecar is the description of it, and a migration of the
    description must not be able to touch the thing described.
    """
    with open(base + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    arr = np.load(base + ".npy")
    if (meta.get("H"), meta.get("W")) != arr.shape:
        raise ValueError(f"{os.path.basename(base)}: array is {arr.shape[0]}x{arr.shape[1]} but its "
                         f"meta records {meta.get('H')}x{meta.get('W')} -- this pair is already torn")
    d = array_digest(arr)
    have = meta.get(DIGEST_KEY)
    if have is not None and have != d:
        raise ValueError(f"{os.path.basename(base)}: the array does not hash to the {DIGEST_KEY} its "
                         f"meta already records -- this pair is already torn")
    return arr, meta, d


def stamp_digest(base):
    """Record DIGEST_KEY in an existing pair's meta, computed from the array already beside it.

    THE BACKFILL. 7b2d097 added the digest to the write path and a refusal to the read path, but every
    surface already on disk predated it and a missing digest read as accepted, so the guard covered none
    of the corpus. Disclosing that (gen_provenance --check counts it) is not protecting it. Stamping the
    existing sidecars from the arrays already beside them is, and it moves no printed number: the digest
    lives only in the sidecar, and every figure a card prints comes from the array and the bbox.

    Returns True if it wrote, False if the meta already recorded this exact digest -- so a second run
    over a stamped tree is a no-op rather than 198 rewrites.

    Staged and renamed through the same `.holeNN.json.part` name commit_surface uses, so sweep_staged
    already covers a process that does not come back, and nothing that globs `hole*.json` can pick the
    staged file up. Only the .json is written; `base + ".npy"` is opened read-only by read_pair and
    never rewritten, because this is a migration of the DESCRIPTION and the measurement must not move.
    """
    _arr, meta, d = read_pair(base)
    if meta.get(DIGEST_KEY) == d:
        return False
    _t_npy, t_json = staged_names(base)
    try:
        with open(t_json, "w", encoding="utf-8") as f:
            json.dump(dict(meta, **{DIGEST_KEY: d}), f)
        os.replace(t_json, base + ".json")
    finally:
        if os.path.exists(t_json):
            os.remove(t_json)
    return True


def _sidecars(root):
    """Every real course's surface sidecar bases under root/courses, sorted. Scratch dirs excluded.

    ENUMERATED FROM THE SURFACES, filtered by distribution.is_corpus_slug -- not from
    distribution.course_slugs. Those two differ, and the difference was an unstampable failure:
    course_slugs globs `courses/*/course.json`, while every corpus test that grades these surfaces globs
    `courses/*/dem_hd/hole*.json` and drops only `_`-prefixed slugs. A directory holding SURFACES BUT NO
    course.json is therefore graded -- required to carry a digest -- and invisible to `--stamp`, in the
    one directory nothing can regenerate.

    The scratch filter is the part that must stay, and it is the same predicate course_slugs uses, so a
    fixture's meta still cannot be rewritten in place by the migration. What is dropped is the
    course.json requirement, which was never what "is there a surface here to stamp" depends on.
    """
    import distribution
    out = []
    for p in sorted(glob.glob(os.path.join(root, "courses", "*", "dem_hd", "hole*.json"))):
        slug = os.path.basename(os.path.dirname(os.path.dirname(p)))
        if distribution.is_corpus_slug(slug):
            out.append(p[:-len(".json")])
    return out


def _fingerprint(path):
    """(size, sha256) of a file on disk, or None when it is not there. For the before/after report."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return os.path.getsize(path), hashlib.sha256(f.read()).hexdigest()


def main(argv=None):
    """Report or backfill the pair digest across every built green surface.

        python3 surface_io.py            # report coverage, write nothing
        python3 surface_io.py --stamp    # stamp the sidecars that carry no digest

    ALL OR NOTHING. Every pair is read and checked first; if any one fails to load or disagrees with
    its meta, nothing is written at all and the offenders are named. courses/ is the only copy of these
    surfaces, so a half-applied migration over it is not an acceptable intermediate state -- and a pair
    that is ALREADY torn must be rebuilt, not stamped, because stamping it would certify the tear.

    Prints each sidecar's size and sha256 before and after, so the diff of a run that writes into the
    only copy of the data is on the record rather than taken on trust.
    """
    argv = sys.argv[1:] if argv is None else argv
    root = os.path.dirname(os.path.abspath(__file__))
    write = "--stamp" in argv
    bases = _sidecars(root)
    if not bases:
        print("no green surfaces built here (courses/ is gitignored) -- nothing to stamp.")
        return 2

    broken, without = [], []
    for b in bases:
        try:
            _arr, meta, _d = read_pair(b)
        except (ValueError, OSError) as e:
            broken.append(f"{os.path.relpath(b, root)}: {e}")
            continue
        if meta.get(DIGEST_KEY) is None:
            without.append(b)
    if broken:
        print(f"REFUSING to write: {len(broken)} of {len(bases)} pairs do not read as a pair. Rebuild "
              f"these rather than stamping them -- a digest written over a torn pair certifies the tear:")
        for b in broken:
            print(f"  {b}")
        return 1

    print(f"pair digests: {len(bases) - len(without)} of {len(bases)} green surfaces carry {DIGEST_KEY}")
    if not without:
        print("  nothing to do.")
        return 0
    if not write:
        print(f"  {len(without)} carry none and are read UNVERIFIED. Stamp them from the arrays "
              f"already on disk: python3 {os.path.basename(__file__)} --stamp")
        return 1

    wrote = 0
    for b in without:
        before = _fingerprint(b + ".json")
        npy_before = _fingerprint(b + ".npy")
        changed = stamp_digest(b)
        after = _fingerprint(b + ".json")
        npy_after = _fingerprint(b + ".npy")
        # RAISE, do not assert. `python -O` deletes an assert statement, and this is the only thing
        # standing between an array that moved between the read and the write and a digest that
        # certifies the moved one -- on the single write in this project that touches data with no copy
        # anywhere (courses/ is gitignored; only laz/ is refetchable). Stop the run rather than finish
        # the loop: every sidecar already written is correct, and continuing would stamp more metas
        # against a corpus whose state is now unknown.
        if npy_before != npy_after:
            raise SystemExit(
                f"ABORT after {wrote} sidecar(s): {b}.npy changed during a sidecar-only migration "
                f"({npy_before} -> {npy_after}). This run reads each array and writes only its meta, so "
                f"the array moving underneath means something else is writing to courses/ -- stamping "
                f"the rest would certify arrays nobody measured. Stop that writer and re-run; the "
                f"sidecars already stamped above are correct and this one was not written.")
        wrote += bool(changed)
        print(f"  {os.path.relpath(b + '.json', root)}: {before[0]}B {before[1][:12]} -> "
              f"{after[0]}B {after[1][:12]}")
    print(f"stamped {wrote} sidecar(s); {len(bases)} of {len(bases)} now carry {DIGEST_KEY}. "
          f"No .npy was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
