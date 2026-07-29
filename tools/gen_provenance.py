#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Generate legal/03_PROVENANCE_BY_COURSE.md from what each course was ACTUALLY built from.

Why generate it: the hand-written table drifted badly. It documented 8 of 12 books, named the wrong
dataset for one course, and carried project-name "years" that were wrong by 2-12 years -- because a
USGS project name is not a flight date. A table transcribed by hand goes stale silently; one derived
from the artifacts cannot.

Everything here is read from the build outputs, never from prose:
  * dataset name   <- the laz/ tile filename prefix (the real project, not the label)
  * flight date    <- course.json lidar_flown, decoded from LAZ point records by tools/lidar_dates.py
  * density range  <- dem_hd/holeNN.json (npts / area, computed at build time)
  * digitized      <- elements tagged _digitized in osm_geom.json
  * caveats        <- build_mode, greens_possibly_outdated, and any green flagged insufficient

Run:  python3 tools/gen_provenance.py            # writes legal/03_PROVENANCE_BY_COURSE.md
      python3 tools/gen_provenance.py --check    # exits 1 if the file is stale (for CI / pre-merge)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "legal", "03_PROVENANCE_BY_COURSE.md")


def _tile_project(slug, dem_source=""):
    """(project_label, n_tiles, from_filenames?) -- the real LiDAR project.

    Preferred source is the tile FILENAMES on disk, because a project name recorded by hand has
    been wrong before. Some early downloads saved bare tile ids (t390135.laz) with no project in the
    name; for those we fall back to the recorded dem_source label and say that is what we did."""
    names = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "courses", slug, "laz", "*.laz"))]
    if not names:
        return None, 0, False
    projects = set()
    for n in names:
        stem = re.sub(r"\.laz$", "", n)
        if not stem.startswith("USGS_LPC_"):
            continue                                   # bare tile id: carries no project name
        stem = stem[len("USGS_LPC_"):]
        stem = re.sub(r"__Co\d+$", "", stem)           # tile_copies disambiguation suffix
        stem = re.sub(r"_w\d+n\d+$", "", stem)         # e.g. _w6153n2055
        stem = re.sub(r"_\d{2}[A-Z]{3}\d+$", "", stem)  # e.g. _18TVK474434
        stem = re.sub(r"_\d+$", "", stem)              # numeric tile id
        projects.add(stem)
    if projects:
        return "; ".join(sorted(projects)), len(names), True
    # fall back to the recorded label, flagged as such
    m = re.search(r"([A-Za-z0-9_]*(?:LiDAR|Lidar|LPC|County|Valley|Levee)[A-Za-z0-9_ ]*)", dem_source or "")
    label = (m.group(1).strip() if m else (dem_source or "").split(",")[0].strip()) or "not recorded"
    return label, len(names), False


def _greens(slug):
    """(count, density_lo, density_hi, n_seamless, n_insufficient) over the built green surfaces."""
    metas = []
    for p in sorted(glob.glob(os.path.join(ROOT, "courses", slug, "dem_hd", "hole*.json"))):
        try:
            metas.append(json.load(open(p)))
        except Exception:
            pass
    if not metas:
        return 0, None, None, 0, 0
    dens = [m["density"] for m in metas if m.get("density")]
    seam = sum(1 for m in metas if "seamless" in str(m.get("source", "")).lower())
    insuf = sum(1 for m in metas if m.get("insufficient"))
    return len(metas), (min(dens) if dens else None), (max(dens) if dens else None), seam, insuf


def _digitized(slug):
    p = os.path.join(ROOT, "courses", slug, "osm_geom.json")
    if not os.path.exists(p):
        return []
    try:
        els = json.load(open(p))["elements"]
    except Exception:
        return []
    return [e.get("id") for e in els if "_digitized" in (e.get("tags") or {})]


def _row(slug):
    j = json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
    name = j.get("name", slug)
    yardage_mode = j.get("build_mode") == "yardage"
    proj, ntiles, from_names = _tile_project(slug, j.get('dem_source', ''))
    ngreens, dlo, dhi, seam, insuf = _greens(slug)
    dig = _digitized(slug)
    stale = sorted(j.get("greens_possibly_outdated", []))
    flown = (j.get("lidar_flown") or {}).get("label")

    geom = "OSM (ODbL)"
    if dig:
        geom += f"; {len(dig)} green(s) hand-added, tagged `_digitized` (ids {', '.join(str(d) for d in dig)})"

    if yardage_mode:
        slope = "**none** — yardage mode: blank greens to mark your own read"
    elif not ngreens:
        slope = "not built"
    else:
        bits = [f"computed by us from **USGS 3DEP LiDAR** (public domain)"]
        if proj:
            bits.append(f"project `{proj}` ({ntiles} tiles)"
                        + ("" if from_names else " *(label recorded in course.json; these tiles\u2019 filenames carry no project name)*"))
        if flown:
            bits.append(f"**flown {flown}**")
        if dlo is not None:
            bits.append(f"{dlo:g}–{dhi:g} pts/m² over {ngreens} greens @0.4 m")
        if seam:
            bits.append(f"{seam} green(s) fall back to the 1 m seamless DEM")
        slope = ", ".join(bits)

    notes = []
    if stale:
        notes.append(f"greens on holes {', '.join(str(h) for h in stale)} were **rebuilt after the "
                     f"flight** — those cards are labelled *pre-rebuild data*")
    if insuf:
        notes.append(f"{insuf} green(s) had no usable point cloud and print no read")
    if dig:
        notes.append("hand-added greens were traced from public-domain USDA NAIP because OSM had none")
    status = "Personal" if yardage_mode else "**Distributed ✅**"

    # first sentence of the recorded scorecard provenance, so the table stays readable
    sc = (j.get("sources", {}) or {}).get("scorecard", "")
    sc = re.sub(r"\s+", " ", sc).strip()
    if len(sc) > 190:
        cut = sc[:190].rsplit(". ", 1)[0]
        sc = (cut + ".") if len(cut) > 60 else sc[:190] + "…"
    return f"| {name} | {status} | {geom} | {slope} | {sc or '—'} | {'; '.join(notes) or 'clean'} |"


def build():
    # ignore scratch/underscore dirs: transient course folders (cold-build tests, staging) must not
    # make the provenance doc look stale and fail the drift check
    slugs = sorted(s for s in (os.path.basename(os.path.dirname(p))
                              for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
                   if not s.startswith("_"))
    rows = [_row(s) for s in slugs]
    return f"""# Provenance by Course

<!-- GENERATED by tools/gen_provenance.py -- do not hand-edit; re-run it instead.
     Every field is read from the build artifacts (laz/ tile names, dem_hd metadata, osm_geom.json,
     course.json), never from prose, so this table cannot drift from what was actually built.
     Verify with: python3 tools/gen_provenance.py --check -->

Exactly what data built each book. "Distributed" = safe to hand out; "Personal" = do not distribute.

**Every book on this list is built only from:** OpenStreetMap geometry (ODbL 1.0), slope/contours
computed by us from public-domain USGS 3DEP LiDAR, par/yardage/handicap **facts** from published
scorecards, and — where an aerial or a missing green is needed — public-domain USDA NAIP.
No Esri/Maxar, Google, Apple or Bing imagery, and nothing from any commercial green-reading product.

**Flight dates are decoded from the LiDAR point records** (`tools/lidar_dates.py`), not from the
project name. Four courses were mislabelled by 2–12 years before this was measured, so the dataset
names below are taken from the actual tile filenames on disk.

| Course | Status | Geometry | Green slope | Scorecard | Notes |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## Notes on the special cases
- **1 m seamless fallback.** A few greens have no usable LiDAR ground returns — bayside holes over
  water, or greens under heavy canopy. Those use the USGS **3DEP seamless 1 m DEM** instead of the
  0.4 m point cloud: still public domain, just less sharp, and the card says `1 m data`.
- **Hand-added greens.** Where OSM mapped no green at all, the putting surface was traced from
  **public-domain USDA NAIP** imagery and tagged `_digitized`. Only coordinates are derived; no
  imagery is embedded in any book. `fetch_osm.py` refuses to overwrite a cache it cannot read, so a
  re-fetch cannot silently delete this geometry.
- **Greens rebuilt after the flight.** Where a course was reconstructed after its LiDAR was flown,
  the map is real measured data but may no longer match the ground. Those cards are labelled
  *pre-rebuild data* and the guide page names the holes.
- **Yardage mode.** Where no trustworthy post-construction elevation exists at all, the book prints
  verified yardages with **blank greens** rather than slope maps that could be wrong.
- **Jay Blasi routing diagram (Poppy Ridge):** only **viewed**, to establish hole numbering; never
  reproduced or embedded. Extracting factual hole positions is not copying.
"""


def main():
    if not glob.glob(os.path.join(ROOT, "courses", "*", "course.json")):
        # "no courses" is not the same as "stale". On a fresh clone courses/ is gitignored and empty,
        # so regenerating produced an EMPTY table and --check reported the committed 12-row table as
        # stale -- turning the repo's front door red for someone who had done nothing wrong.
        print("no course data present (courses/ is gitignored) -- nothing to check against.")
        return 2
    text = build()
    if "--check" in sys.argv:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            print("STALE: legal/03_PROVENANCE_BY_COURSE.md does not match the build artifacts.\n"
                  "  Re-run: python3 tools/gen_provenance.py")
            return 1
        print("legal/03_PROVENANCE_BY_COURSE.md is up to date")
        return 0
    open(OUT, "w").write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({text.count(chr(10))} lines, "
          f"{len([l for l in text.splitlines() if l.startswith('| ') and not l.startswith('| Course |') and not l.startswith('|---')])} courses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
