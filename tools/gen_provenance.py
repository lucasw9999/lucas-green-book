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
sys.path.insert(0, ROOT)
import distribution  # noqa: E402
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
        stem = re.sub(r"__Co\d+$", "", stem)           # extra sub-project copy (fetch_lidar.copy_suffix)
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


def _elevation(slug):
    """(n_measured, n_holes_on_card, n_extrapolated) from hole_elev.json, or (0, 0, 0).

    The card prints a tee-to-green height on ~130 cards across the corpus, and this table -- whose
    whole purpose is that every printed number is traceable to an artifact -- said nothing about it.
    It also has to distinguish the two BASES, because they are not equally direct: most holes are
    sampled at the tee end of the mapped centreline, but on a short par 3 the tee is extrapolated
    along the hole axis to the card yardage. A reader auditing a figure needs to know which.
    """
    p = os.path.join(ROOT, "courses", slug, "hole_elev.json")
    if not os.path.isfile(p):
        return 0, 0, 0
    try:
        rows = json.load(open(p)).get("holes") or {}
    except Exception:
        return 0, 0, 0
    extrap = sum(1 for r in rows.values() if "extrapolated" in str(r.get("tee_basis", "")))
    try:
        holes = len(json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
                    .get("holes", {})) or 18
    except Exception:
        holes = 18
    return len(rows), holes, extrap



def _osm_extract_date(slug):
    """Earliest OSM data timestamp across this course's extracts, as YYYY-MM-DD, or None.

    Overpass stamps every response with osm3s.timestamp_osm_base -- the instant of the planet data the
    answer was computed from. It has been sitting unread in every extract on disk while this table went
    to real trouble over the LiDAR side, decoding flight dates out of the point records because four
    courses had been mislabelled by 2-12 years by their project names.

    The same argument applies to geometry. The card tells a reader the hole and green SHAPES come from
    OpenStreetMap, and it prints the flight date so they can judge whether the SLOPE is current. Without
    the extract date they cannot judge the same thing about the shapes: a re-bunkered hole or a re-routed
    green looks exactly as authoritative as a current one. Today every extract is a day or two old, so
    this records a fact rather than fixing a live problem -- which is the moment to record it, before a
    course goes two years without a refetch and nothing says so.

    EARLIEST of the three files, deliberately: geometry, course features and relations are separate
    Overpass calls a minute or so apart, and the honest claim about a book is the age of its oldest
    ingredient.
    """
    stamps = []
    for fn in ("osm_geom.json", "osm_course.json", "osm_relations.json"):
        p = os.path.join(ROOT, "courses", slug, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                t = (json.load(fh).get("osm3s") or {}).get("timestamp_osm_base")
        except (OSError, ValueError):
            continue
        if t:
            stamps.append(str(t))
    return min(stamps)[:10] if stamps else None


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
    # Both from distribution.py, with the SAME normalisation, but they are different questions: the
    # Status column is a policy verdict, "yardage mode: blank greens" is a fact about the data. They
    # used to be derived separately -- this line was an exact `== "yardage"` match while Status asked
    # distribution.py -- so a mis-cased or space-padded build_mode in a hand-edited course.json
    # printed "Personal" in Status and a LiDAR density sentence in Green slope, in the same row.
    # Deriving one FROM the other would be the mirror fault: the day a second reason makes a course
    # non-distributable, the slope cell would claim yardage mode for a course not in it.
    distributable, label, _why = distribution.distribution_status(j)
    yardage_mode = distribution.is_yardage(j)
    proj, ntiles, from_names = _tile_project(slug, j.get('dem_source', ''))
    ngreens, dlo, dhi, seam, insuf = _greens(slug)
    dig = _digitized(slug)
    stale = sorted(j.get("greens_possibly_outdated", []))
    flown_rec = j.get("lidar_flown") or {}
    flown = flown_rec.get("label")
    # A flight range is only as trustworthy as what it was measured over. tools/lidar_dates.py
    # narrows the range to the points that actually lie over the greens and records that in `basis`;
    # when it cannot -- no point over any green, or no green geometry to place -- it falls back to the
    # union over WHOLE TILES and says so there. This table read only `label`, so that fallback would
    # have been published as a flight date with no hint that a tile 1.3 km from any green may have set
    # its extremes, which is the exact fault the lidar_dates change was made to fix. Qualify it here.
    # Fail closed. A record with NO basis was written before that distinction existed, and its label
    # WAS the union over whole tiles -- so an absent basis must read as the weaker claim, not the
    # stronger one. Only a basis that positively says "points within ..." earns an unqualified date.
    basis = flown_rec.get("basis") or ""
    flown_note = "" if basis.startswith("points within") else \
        " *(range measured over whole tiles, not only the points over the greens)*"

    geom = "OSM (ODbL)"
    osm_date = _osm_extract_date(slug)
    geom += f", extract **{osm_date}**" if osm_date else ", extract date **not recorded**"
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
            bits.append(f"**flown {flown}**{flown_note}")
        if dlo is not None:
            bits.append(f"{dlo:g}–{dhi:g} pts/m² over {ngreens} greens @0.4 m")
        if seam:
            bits.append(f"{seam} green(s) fall back to the 1 m seamless DEM")
        slope = ", ".join(bits)

    nelev, nholes, nextrap = _elevation(slug)
    if nelev:
        bits = [f"tee-to-green **height change measured on {nelev} of {nholes} holes** from the same "
                f"public LiDAR (ground returns at the tee vs the green's own surface)"]
        if nextrap:
            bits.append(f"{nextrap} of them with the tee extrapolated along the hole axis to the card "
                        f"yardage, because the mapped line stops short of the back tee")
        if nelev < nholes:
            bits.append(f"the other {nholes - nelev} print no height: the tee could not be located or "
                        f"had no ground returns")
        elev_note = "; ".join(bits)
    else:
        elev_note = ""

    notes = []
    if elev_note:
        notes.append(elev_note)
    if stale:
        # The caveat AND its basis, together. "rebuilt after the flight" is an assertion about 9 of
        # philadelphia's 18 cards, and its evidence was recorded in sources.scorecard -- which this table
        # truncates to the first sentence for readability, so the justification never reached the row
        # that makes the claim. A reader auditing the caveat could not see why it was made.
        note = (f"greens on holes {', '.join(str(h) for h in stale)} were **rebuilt after the "
                f"flight** — those cards are labelled *pre-rebuild data*")
        basis = re.sub(r"\s+", " ", str(j.get("greens_outdated_basis") or "")).strip()
        note += f" ({basis})" if basis else " *(basis not recorded — see greens_outdated_basis)*"
        notes.append(note)
    if insuf:
        notes.append(f"{insuf} green(s) had no usable point cloud and print no read")
    if dig:
        notes.append("hand-added greens were traced from public-domain USDA NAIP because OSM had none")
    # The TREE layer's coverage gap belongs here too. This table already records where the green
    # surfaces fall back to the 1 m DEM and how many holes carry a measured height change, so the one
    # remaining per-hole data limitation it did not report was trees: they are found by height above
    # ground in the point cloud, so a hole the survey does not reach draws none -- and on the card that
    # is indistinguishable from a hole that genuinely has none. Monarch Bay 1, 17 and 18 are the case,
    # and they are exactly the three holes lidar_coverage.py reports as having centreline outside the
    # point data, which is why the blank is the survey's edge rather than open ground.
    tp = os.path.join(ROOT, "courses", slug, "trees_lidar.json")
    if os.path.exists(tp):
        try:
            with open(tp, encoding="utf-8") as fh:
                tl = json.load(fh)
        except (OSError, ValueError):
            tl = {}
        if tl and any(tl.values()):
            bare = sorted(int(h) for h, v in tl.items() if not v)
            if bare:
                notes.append(
                    f"**no tree markers on hole{'s' if len(bare) > 1 else ''} "
                    f"{', '.join(str(h) for h in bare)}** — the point cloud does not reach those "
                    f"corridors, so the maps show them treeless; the cards say to read the blank as "
                    f"unmapped rather than clear")
    # Every card prints a Rating/Slope table. Those are the only printed numbers whose source this table
    # did not report, and 7 of 12 courses have none recorded -- while the panel's own note said "All
    # yardages from the official scorecard", which a reader takes as covering the columns beside them.
    # Report the gap rather than let it stay invisible; an uncited number should be visibly uncited.
    rating_src = re.sub(r"\s+", " ", str((j.get("sources") or {}).get("rating") or "")).strip()
    if any(t.get("rating") is not None for t in (j.get("tees") or [])):
        notes.append(f"tee rating/slope: {rating_src}" if rating_src else
                     "**tee rating/slope source NOT recorded** — the cards print them; nothing cites them")
    # the SAME rule any publisher uses -- see distribution.py for why this is shared (resolved above,
    # so the Status column and the slope text cannot disagree)
    status = f"**{label} ✅**" if distributable else label

    # first sentence of the recorded scorecard provenance, so the table stays readable
    # The table keeps this cell short to stay readable, and that truncation has now twice DISCARDED
    # recorded provenance: the basis for philadelphia's pre-rebuild caveat and five courses' rating/slope
    # sources were all written into this one field and cut off. Two fixes, because a silent cut is the
    # actual fault: say when it happened, and reproduce every source in full below the table.
    sc_full = re.sub(r"\s+", " ", (j.get("sources", {}) or {}).get("scorecard", "")).strip()
    sc = sc_full
    if len(sc) > 190:
        cut = sc[:190].rsplit(". ", 1)[0]
        # ...and always mark it. It used to re-close the sentence with a full stop, so valley-hi's cell
        # ended "transcribed directly; all." -- a mid-sentence cut that reads like a finished thought.
        sc = ((cut + ". …") if len(cut) > 60 else sc[:190] + "…") + f" *(full text: [{name}](#sources-in-full))*"
    return f"| {name} | {status} | {geom} | {slope} | {sc or '—'} | {'; '.join(notes) or 'clean'} |"


def build():
    # ignore scratch/underscore dirs: transient course folders (cold-build tests, staging) must not
    # make the provenance doc look stale and fail the drift check
    slugs = sorted(s for s in (os.path.basename(os.path.dirname(p))
                              for p in glob.glob(os.path.join(ROOT, "courses", "*", "course.json")))
                   if not s.startswith("_"))
    rows = [_row(s) for s in slugs]
    full = []
    for slug in slugs:
        j = json.load(open(os.path.join(ROOT, "courses", slug, "course.json")))
        full.append(f"### {j.get('name', slug)}")
        for key in sorted(j.get("sources") or {}):
            val = re.sub(r"\s+", " ", str((j.get("sources") or {})[key])).strip()
            if val:
                full.append(f"- **{key}** — {val}")
        for key in ("greens_outdated_basis", "dem_source"):
            val = re.sub(r"\s+", " ", str(j.get(key) or "")).strip()
            if val:
                full.append(f"- **{key}** — {val}")
        full.append("")
    full_text = chr(10).join(full)
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

**Geometry carries a date for the same reason.** Each row's OSM *extract* date is the earliest
`osm3s.timestamp_osm_base` across that course's Overpass responses — the instant of the planet data
they were computed from, read off the files rather than recorded by hand. The flight date lets a reader
judge whether the green SLOPE is current; without this one they cannot judge the same thing about the
hole and green SHAPES, and a re-bunkered hole looks exactly as authoritative as a current one.

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

## Sources in full

The table above shortens the Scorecard column to stay readable. Everything recorded for each course is
reproduced here uncut, so a claim can always be traced to what was actually written down.

{full_text}"""


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
