#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. All rights reserved.
# "Lucas Green Book" is a trademark of Lucas Wu.
# Published for reference. Not licensed for use, modification or redistribution.
# https://github.com/lucasw9999/lucas-green-book
"""
The one rule for putting a green surface on disk.

A green surface is TWO files -- an elevation array and a JSON sidecar -- and they only mean anything
together. The array is a grid of heights and carries no georeference of its own, so the sidecar's
extent is what places every pixel on the earth. Hold the right array beside the wrong extent and
nothing crashes: the green is simply rasterised against ground it does not cover, and the slope
printed on the card is wrong. Several producers write into the same directory, so the rule for
committing a pair lives here once rather than in each of them.

Why a whole module for two file writes
--------------------------------------
Because "write the array, then write the sidecar" is two statements, and the gap between them is
reachable: an interrupt during a long build, a full disk, an exception while encoding the sidecar.
Land in that gap on a rebuild and the new array sits beside the previous run's extent. That is not a
crash to debug later -- it is a wrong number on a card a junior carries onto a green, and every
downstream consumer that re-derives scale from the same sidecar inherits the error rather than
catching it.

So this module does three things a pair of `write()` calls does not:

  * **Stages, then renames.** Both files are written under dot-prefixed temporary names and renamed
    into place, so nothing scanning for finished surfaces can pick up a half-written one.
  * **Makes the pair self-identifying.** The sidecar records a cryptographic digest of the array
    committed with it, and readers refuse a pair whose array does not hash to what its sidecar
    claims. Two atomic renames are not one transaction, so a process killed between them can still
    tear a pair -- and the tears that matter are exactly the ones a shape comparison cannot see,
    because a green can change extent while keeping identical pixel dimensions. A digest is
    shape-blind, which is what that case needs.
  * **Cleans up after a run that never came back.** A `finally` handles an exception. It cannot
    handle a SIGKILL or a laptop suspended mid-build, so stale staged files are swept explicitly.

The residual is one case: a tear whose two runs produced bit-identical arrays under different
extents. For a sampled terrain surface that means the elevations did not move at all, and a green
flat enough for that reads the same either way.
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
    """Remove stale staging files in a surface directory. Returns what it removed.

    The `finally` in commit_surface handles an exception; it cannot handle the process not coming back
    at all -- a SIGKILL, a laptop asleep mid-build, power. A staged file then sits there indefinitely.

    Never valid data, by construction: a staged file is only ever renamed into place after its write
    returns, so anything still wearing the staged name is incomplete. It must be swept rather than
    tolerated, because a leftover staged sidecar is the only on-disk trace of the rename window
    described above -- and as evidence it is worth nothing if a finished run leaves one too.

    Matched on the dot-prefixed staged pattern alone, so it can never reach a real surface file.
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
    """A fingerprint of the array a sidecar is committed beside, stable across save and load.

    dtype and shape go in with the bytes, and the bytes are taken C-contiguous, because the on-disk
    format records array order and a load may hand back a differently-ordered view of identical
    values -- hashing raw memory would then disagree with itself across a round trip for no real
    difference.

    Hashed rather than merely counted because the point is to catch a pair whose two halves came from
    DIFFERENT RUNS, and the only property that reliably distinguishes those is the content. Pixel
    dimensions do not: see commit_surface.
    """
    a = np.ascontiguousarray(arr)
    h = hashlib.sha256()
    h.update(f"{a.dtype.str}|{a.shape}|".encode())
    h.update(a.tobytes())
    return h.hexdigest()


def commit_surface(base, arr, meta):
    """Write `arr` to base + ".npy" and `meta` to base + ".json" so that both land, or neither does.

    Both files are staged first, then renamed. The staged names are DOT-PREFIXED so that nothing
    scanning a surface directory for finished pairs can pick a half-written one up as real.

    WHAT THE TWO RENAMES STILL LEAVE. A rename is atomic per file; two of them are not one
    transaction, so a process killed between them leaves the previous run's sidecar beside this run's
    array. The outcomes split, and they are not equally survivable:

      * pixel dimensions differ -> the read side refuses the pair and names both shapes. Loud, and
        recoverable by rebuilding.
      * dimensions EQUAL, extent different -> a shape check sees nothing wrong. Silent, and a wrong
        printed slope.

    The silent case is reachable rather than theoretical, because pixel dimensions are derived from a
    green's size by truncating division: a green re-traced in the source data, or moved, or resized by
    less than one pixel keeps the same dimensions while its extent changes. A rebuild interrupted
    between the two renames lands exactly there.

    Nor does rename ORDER help. The sidecar is renamed last because it is what consumers gate on, so
    on a FIRST build a crash leaves an array nothing will read -- harmless. On a REBUILD, where both
    names already hold the previous pair, either order can tear.

    So the pair is made SELF-IDENTIFYING instead: the sidecar carries a digest of the array committed
    with it, and readers refuse a pair whose array does not hash to what its sidecar claims. That is
    shape-blind, which is what the silent case needs. Writing both into a single container, or
    renaming a staged directory, would be atomic outright -- but both change the on-disk layout every
    existing consumer and every already-built surface depends on, so they are a migration plus a full
    rebuild rather than a fix.

    Both staged files are removed if anything goes wrong before the renames. A leftover staged file is
    not merely untidy: it is the one on-disk trace of the rename window above, so it is evidence, and
    evidence a failed run also leaves is worth nothing. sweep_staged covers the case no `finally` can.
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
    THROUGH". Every reader that derives a number from a surface goes through it, so that "is this pair
    intact?" has one answer rather than one per caller -- a guard that each consumer reimplements is a
    guard that will eventually differ between them.

    IT IS THE FLOOR, NOT THE CEILING. A MISSING digest is accepted here, because the backfill below
    reads unstamped pairs through this function in order to stamp them, and a strict read would make
    the migration unable to read the pairs it exists to fix. The renderer therefore keeps its own
    stricter check rather than calling this: once every built sidecar carries a digest, a missing one
    means the file was hand-written, restored from an older tree or truncated, and the guard standing
    in front of a printed slope should not be the loosest one in the project.

    Raises ValueError naming the disagreement. NEVER writes, and never opens the array for anything
    but a read: the array is the measurement, the sidecar is the description of it, and a migration of
    the description must not be able to touch the thing described.
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
    """Record DIGEST_KEY in an existing pair's sidecar, computed from the array already beside it.

    THE BACKFILL. Adding a digest to the write path protects surfaces built afterwards and none of the
    ones already on disk, and a guard that covers nothing is not a guard -- so existing sidecars are
    stamped from the arrays already beside them. This moves no printed number: the digest lives only
    in the sidecar, and every figure a card prints comes from the array and the extent.

    Returns True if it wrote, False if the sidecar already recorded this exact digest -- so a second
    run over a stamped tree is a no-op rather than a full rewrite.

    Staged and renamed through the same temporary name commit_surface uses, so sweep_staged already
    covers a process that does not come back, and nothing scanning for finished sidecars can pick the
    staged file up. Only the sidecar is written; the array is opened read-only by read_pair and never
    rewritten, because this is a migration of the DESCRIPTION and the measurement must not move.
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
    """Every real course's surface sidecar base, sorted. Scratch directories excluded.

    ENUMERATED FROM THE SURFACES THEMSELVES, filtered by distribution.is_corpus_slug. Enumerating
    from the course records instead would miss a directory that holds surfaces but no course record --
    which is precisely the directory a migration cannot afford to skip, because nothing can regenerate
    it. What the surfaces are graded on is whether a surface is there, so that is what this globs.

    The scratch filter is the part that must stay, and it is the same predicate used elsewhere, so a
    test fixture's sidecar can never be rewritten in place by the migration.
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
    its sidecar, nothing is written at all and the offenders are named. The built surfaces are the only
    copy of that data, so a half-applied migration over them is not an acceptable intermediate state
    -- and a pair that is ALREADY torn must be rebuilt, not stamped, because stamping it would certify
    the tear.

    Prints each sidecar's size and digest before and after, so the diff of a run that writes into the
    only copy of the data is on the record rather than taken on trust.
    """
    argv = sys.argv[1:] if argv is None else argv
    root = os.path.dirname(os.path.abspath(__file__))
    write = "--stamp" in argv
    bases = _sidecars(root)
    if not bases:
        print("no green surfaces built here (course data is not published) -- nothing to stamp.")
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
        # certifies the moved one -- on the single write in this project that touches data with no
        # copy anywhere. Stop the run rather than finish the loop: every sidecar already written is
        # correct, and continuing would stamp more against a corpus whose state is now unknown.
        if npy_before != npy_after:
            raise SystemExit(
                f"ABORT after {wrote} sidecar(s): {b}.npy changed during a sidecar-only migration "
                f"({npy_before} -> {npy_after}). This run reads each array and writes only its meta, so "
                f"the array moving underneath means something else is writing to the corpus -- stamping "
                f"the rest would certify arrays nobody measured. Stop that writer and re-run; the "
                f"sidecars already stamped above are correct and this one was not written.")
        wrote += bool(changed)
        print(f"  {os.path.relpath(b + '.json', root)}: {before[0]}B {before[1][:12]} -> "
              f"{after[0]}B {after[1][:12]}")
    print(f"stamped {wrote} sidecar(s); {len(bases)} of {len(bases)} now carry {DIGEST_KEY}. "
          f"No array was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
