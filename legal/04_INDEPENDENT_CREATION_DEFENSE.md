# Independent Creation — the Defense

If a commercial green‑book company (or anyone) accuses you of copying, this is the factual
answer. It maps 1:1 to the legal elements a challenger must overcome — and it is **true** for
the six distributed books.

## Hand this to a challenger (verbatim)

> **"Lucas Green Book" is an independent, free, non‑commercial project for junior golfers.**
> Every distributed book is built solely from open and public‑domain data: hole and green
> geometry from **OpenStreetMap** (© OpenStreetMap contributors, licensed under the ODbL 1.0);
> green slope, contours and break arrows **independently computed by the maker** from
> **public‑domain USGS 3DEP** elevation data (a U.S. Government work with no copyright); and
> **par/yardage/handicap facts** from the published scorecard. **No proprietary data, imagery,
> artwork, symbol set, page layout, or trade dress of any commercial green‑reading product was
> used, copied, referenced, or reverse‑engineered.** No Google, Apple, Bing, or Esri/Maxar
> imagery is embedded in any distributed book, and no competitor brand appears anywhere in the
> product. The maps were created **remotely from public data without entering any course.**
> Course names are used **only nominatively** to identify the course, with an explicit
> statement of non‑affiliation and non‑endorsement. The full build pipeline and its open inputs
> are **reproducible**, demonstrating independent creation. The books are **given away, not
> sold**. If any course would prefer not to be included, the maker will remove it promptly on
> request: **info@lucasgreenbook.org**.

## Why each legal theory fails (against the six books)
- **Copyright infringement** — needs copying of protected expression. We copied none; we
  independently created from open/public inputs. Two maps of the same green look alike because
  they depict the **same physical reality** (facts/nature aren't ownable; *Feist*; merger
  doctrine). **Independent creation is a complete defense.**
- **Trade dress** — protects distinctive, **non‑functional** look‑and‑feel. Our arrows/contours/
  colors are **functional** (they convey slope) and our own design; no competitor's glyphs,
  colors, layout, or typography are used; our "Lucas Green Book" brand negates confusion.
- **Trademark / passing off** — no competitor mark appears in any product; course names are
  nominative fair use.
- **Unfair competition / misappropriation** — we're not a competitor (free, non‑commercial),
  we don't pass off, and we didn't take anyone's survey investment.
- **Patents** — we practice no one's specific claimed method; a generic slope‑map render from
  public elevation is not a patented device/process, and "print a map in a booklet" is old.

## Evidence of independent creation (kept on file)
- The **build pipeline** (`fetch_*.py`, `render_*.py`, `generate.py`) — open inputs → our output.
- The **cached open inputs** per course (`osm_*.json`, `dem_hd/`) — all OSM/USGS.
- This `legal/` folder documenting every source and license.
- Grep evidence: no competitor brand/data/imagery in any distributed output.
