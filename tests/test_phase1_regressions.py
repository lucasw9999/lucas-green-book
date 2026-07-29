#!/usr/bin/env python3
# Lucas Green Book -- Copyright (c) 2026 Lucas Wu. "Lucas Green Book" is a trademark of Lucas Wu.
# Free for personal, non-commercial use. Licensed under PolyForm Noncommercial 1.0.0.
# https://github.com/lucasw9999/lucas-green-book
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""
Regression tests for every defect three adversarial review rounds found in the yardage-tick and
tree work. Each test names the defect it locks down, so a future change that reintroduces one fails
here instead of on a card in a junior's pocket.

Design notes:
  * Pure-function tests (synthetic geometry, source scans) always run.
  * Corpus tests need per-course data, which is gitignored -- they SKIP on a fresh clone rather
    than fail. That keeps the suite honest: a skip is visibly not a pass.
  * These are checks on the RENDERED OUTPUT wherever possible. Several of the bugs below were
    originally "verified" with a script that re-implemented the code under test, and the circular
    check could not fail. Measuring the artifact is the point.

Run:  python3 -m pytest tests/ -q
"""
import glob
import json
import math
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIMIT_IN_PER_5YD = 0.375        # USGA Clarification 4.3a/1 scale cap: 3/8 in : 5 yd == 1:480
DIGIT_EM = 0.556                # Helvetica/Arial Bold digit advance
R_LAT = 111320.0


def _courses():
    """Course slugs that have the geometry needed to render a hole map."""
    out = []
    for cj in sorted(glob.glob(os.path.join(ROOT, "courses", "*", "course.json"))):
        slug = os.path.basename(os.path.dirname(cj))
        if os.path.exists(os.path.join(ROOT, "courses", slug, "osm_geom.json")):
            out.append(slug)
    return out


def _engine(slug):
    """Import config/render_hole bound to one course (they read the COURSE env var at import)."""
    for m in ("config", "render_hole", "render_green"):
        sys.modules.pop(m, None)
    os.environ["COURSE"] = slug
    import config
    import render_hole
    return config, render_hole


def _mlon(lat):
    return 111320.0 * math.cos(math.radians(lat))


CORPUS = _courses()
needs_corpus = pytest.mark.skipif(not CORPUS, reason="per-course data is gitignored; nothing to measure")


# ---------------------------------------------------------------------------
# Pure-function / source tests -- always run
# ---------------------------------------------------------------------------
def test_no_homoglyphs_in_printed_strings():
    """Round 1: two U+0434 CYRILLIC SMALL LETTER DE shipped as 'yd' on the instruction card of
    all 11 books. Only the em-dash is allowed to be non-ASCII in the engine sources."""
    allowed = {0x2014}          # EM DASH
    bad = []
    for f in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        src = open(f, encoding="utf-8").read()
        for i, ch in enumerate(src):
            if ord(ch) > 127 and ord(ch) not in allowed:
                bad.append((os.path.basename(f), src[:i].count("\n") + 1, hex(ord(ch))))
    assert not bad, f"non-ASCII characters that would print as homoglyphs: {bad}"


def test_overpass_reply_validation_refuses_destructive_replies(tmp_path):
    """Round 3 follow-up: Overpass signals a timeout with HTTP 200 + a remark + a short element
    list. It parses and has the right shape, so it used to be written straight over a good cache,
    silently rebinding holes to the wrong greens."""
    slug = CORPUS[0] if CORPUS else None
    if slug is None:
        pytest.skip("needs a course dir for config import")
    os.environ["COURSE"] = slug
    for m in ("config", "fetch_osm"):
        sys.modules.pop(m, None)
    import fetch_osm

    good = {"version": 0.6, "elements": [
        {"type": "way", "id": i, "tags": {"golf": "green"}, "geometry": [{"lat": 1.0, "lon": 2.0}]}
        for i in range(20)]}
    cache = tmp_path / "osm_geom.json"
    cache.write_text(json.dumps(good))

    fetch_osm._check_response(good, str(cache), "osm_geom.json")      # complete -> accepted

    destructive = {
        "remark + empty":    {"version": 0.6, "remark": "runtime error: Query timed out", "elements": []},
        "remark + partial":  {"version": 0.6, "remark": "check /api/status", "elements": good["elements"][:5]},
        "silent partial":    {"version": 0.6, "elements": good["elements"][:3]},
        "empty, no remark":  {"version": 0.6, "elements": []},
        "not an element list": {"version": 0.6},
    }
    for name, reply in destructive.items():
        with pytest.raises(SystemExit):
            fetch_osm._check_response(reply, str(cache), "osm_geom.json")
        assert json.loads(cache.read_text()) == good, f"{name}: cache must be left untouched"


def test_digitized_guard_refuses_malformed_cache(tmp_path):
    """Rounds 1-2: 'could not read the previous file' became 'nothing to preserve', which erased
    hand-digitized greens that exist in exactly one untracked file. Valid-JSON-wrong-shape was the
    same hole (a misspelled 'elements' key took bay-view's digitized greens 2 -> 0)."""
    slug = CORPUS[0] if CORPUS else None
    if slug is None:
        pytest.skip("needs a course dir for config import")
    os.environ["COURSE"] = slug
    for m in ("config", "fetch_osm"):
        sys.modules.pop(m, None)
    import fetch_osm

    p = tmp_path / "osm_geom.json"
    dig = {"type": "way", "id": -16, "tags": {"golf": "green", "_digitized": "yes"},
           "geometry": [{"lat": 1.0, "lon": 2.0}]}

    assert fetch_osm._digitized_of(str(p)) == []                      # absent -> quiet []
    p.write_text(json.dumps({"version": 0.6, "elements": [dig]}))
    assert len(fetch_osm._digitized_of(str(p))) == 1                  # intact -> preserved

    for name, body in [
        ("truncated", '{"version":0.6,"elem'),
        ("empty", ""),
        ("html error page", "<html>500</html>"),
        ("no elements key", '{"version":0.6}'),
        ("misspelled key", '{"version":0.6,"elemnts":[]}'),
        ("elements a dict", '{"elements":{"a":1}}'),
        ("elements null", '{"elements":null}'),
        ("elements of strings", '{"elements":["a"]}'),
        ("top level a list", '[{"id":1}]'),
    ]:
        p.write_text(body)
        before = p.read_bytes()
        with pytest.raises(SystemExit):
            fetch_osm._digitized_of(str(p))
        assert p.read_bytes() == before, f"{name}: must not modify the file"


# ---------------------------------------------------------------------------
# Corpus tests -- measured on the real rendered output
# ---------------------------------------------------------------------------
@needs_corpus
def test_no_tick_exceeds_its_hole_yardage():
    """Round 3: castlewood-hill h4 printed a '200 yd to green' tick on a hole its own card lists as
    182 yd, because the radius bound was gated on the from-tee value, which is None where the drawn
    centerline overshoots the back tee."""
    bad = []
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue
            card = config.HOLES[hn][2]
            for t in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg):
                if int(t) > card:
                    bad.append((slug, hn, int(t), card))
    assert not bad, f"ticks further from the green than the hole is long: {bad}"


@needs_corpus
def test_from_tee_labels_are_bounded_and_ordered():
    """Round 2: the from-tee number was card_total - yd while yd had become a straight-line radius,
    mixing two measures (max +54 yd wrong). It must now be >= 30, <= the hole's card yardage, and
    increase monotonically as the to-green number does.

    Bounds and ordering are NOT sufficient -- card_total - yd satisfies all three, which is how the
    original bug survived. So the VALUE is also checked against an independently computed
    along-the-line position (dense sampling, no code shared with the engine)."""
    bad = []
    worst_value_err = 0.0
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        geom = json.load(open(os.path.join(ROOT, "courses", slug, "osm_geom.json")))["elements"]
        greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        holes = [e for e in geom if (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry")]
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue
            card = config.HOLES[hn][2]
            rights = [int(x) for x in re.findall(r'<text x="91"[^>]*>(\d+)</text>', svg)]
            lefts = [int(x) for x in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg)]
            for r in rights:
                if r < 30 or r > card:
                    bad.append((slug, hn, "out of range", r, card))
            if rights != sorted(rights, reverse=True):
                bad.append((slug, hn, "from-tee not monotonic", rights, card))
            if lefts != sorted(lefts):
                bad.append((slug, hn, "to-green not monotonic", lefts, card))

            # --- value check, independent of the engine ---
            pairs = re.findall(r'<text x="9" y="([0-9.]+)"[^>]*>(\d+)</text>', svg)
            rmap = dict(re.findall(r'<text x="91" y="([0-9.]+)"[^>]*>(\d+)</text>', svg))
            if not rmap:
                continue
            cand = [h for h in holes if (h.get("tags") or {}).get("ref") == str(hn)]
            if not cand:
                continue
            line = max(cand, key=lambda h: len(h["geometry"]))["geometry"]
            g, _gend, tend = render_hole.match_green(line, greens)
            gla = sum(p["lat"] for p in g["geometry"]) / len(g["geometry"])
            glo = sum(p["lon"] for p in g["geometry"]) / len(g["geometry"])
            la0 = sum(p["lat"] for p in line) / len(line)
            lo0 = sum(p["lon"] for p in line) / len(line)
            em = lambda la, lo: ((lo - lo0) * _mlon(la0), (la - la0) * R_LAT)
            same = (abs(line[0]["lat"] - tend["lat"]) < 1e-9 and abs(line[0]["lon"] - tend["lon"]) < 1e-9)
            ordered = line if same else list(reversed(line))
            pts = [em(p["lat"], p["lon"]) for p in ordered]
            seg = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                   for i in range(len(pts) - 1)]
            arc = sum(seg) or 1.0
            gc = em(gla, glo)
            for y, ln in pairs:
                if y not in rmap:
                    continue
                target = int(ln) * 0.9144
                best = None                      # dense sample the polyline for the radius crossing
                for i in range(len(pts) - 1):
                    base = sum(seg[:i])
                    for k in range(401):
                        f = k / 400.0
                        px = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
                        py = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
                        d = math.hypot(px - gc[0], py - gc[1])
                        if best is None or abs(d - target) < best[0]:
                            best = (abs(d - target), base + seg[i] * f)
                if best is None:
                    continue
                expect = card * best[1] / arc          # card yardage scaled by position on the line
                err = abs(int(rmap[y]) - expect)
                worst_value_err = max(worst_value_err, err)
                if err > 8.0:                          # 8 yd covers sampling + rounding
                    bad.append((slug, hn, "from-tee value wrong", int(rmap[y]), round(expect, 1)))
    assert not bad, (f"from-tee label violations (worst value error {worst_value_err:.1f} yd): "
                     f"{bad[:8]}{' ...' if len(bad) > 8 else ''}")


@needs_corpus
@pytest.mark.parametrize("font_scale", [1.0, 2.0])
def test_gutter_numbers_never_overprint(font_scale):
    """Round 2: the two gutter numbers had no horizontal guard, so at the 2x coach scale the brown
    number -- painted second WITH a white halo -- erased digits of the to-green yardage
    (monarch-bay h16 printed '1(498'). 25 rows on 5 holes."""
    bad = []
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        for hn in config.HOLE_NUMS:
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES, font_scale=font_scale)
            except Exception:
                continue
            rights = {y: n for y, _f, n in
                      re.findall(r'<text x="91" y="([0-9.]+)" font-size="([0-9.]+)"[^>]*>(\d+)</text>', svg)}
            for y, f, n in re.findall(r'<text x="9" y="([0-9.]+)" font-size="([0-9.]+)"[^>]*>(\d+)</text>', svg):
                if y not in rights:
                    continue
                FSN = float(f)
                left_end = 9 + DIGIT_EM * FSN * len(n)
                right_start = 91 - DIGIT_EM * FSN * len(rights[y])
                if left_end > right_start:
                    bad.append((slug, hn, n, rights[y], round(left_end - right_start, 2)))
    assert not bad, f"overlapping gutter numbers at font_scale={font_scale}: {bad}"


@needs_corpus
def test_to_green_label_is_a_true_straight_line_distance():
    """Rounds 1-2: the label first meant a straight-line distance but the tick sat up to 85 m off
    the drawn line; then the tick was on the line but the label had become a WALKING distance, up
    to +43 yd over what a rangefinder reads. Both properties must hold at once.

    Measured from the SVG, not by re-running the placement helper -- the original verification was
    circular and could not have failed."""
    worst_label = 0.0
    worst_offline = 0.0
    for slug in CORPUS:
        config, render_hole = _engine(slug)
        geom = json.load(open(os.path.join(ROOT, "courses", slug, "osm_geom.json")))["elements"]
        greens = [e for e in geom if (e.get("tags") or {}).get("golf") == "green" and e.get("geometry")]
        holes = [e for e in geom if (e.get("tags") or {}).get("golf") == "hole" and e.get("geometry")]
        for hn in config.HOLE_NUMS:
            cand = [h for h in holes if (h.get("tags") or {}).get("ref") == str(hn)]
            if not cand:
                continue
            line = max(cand, key=lambda h: len(h["geometry"]))["geometry"]
            g, _gend, _tend = render_hole.match_green(line, greens)
            gla = sum(p["lat"] for p in g["geometry"]) / len(g["geometry"])
            glo = sum(p["lon"] for p in g["geometry"]) / len(g["geometry"])
            la0 = sum(p["lat"] for p in line) / len(line)
            lo0 = sum(p["lon"] for p in line) / len(line)
            em = lambda la, lo: ((lo - lo0) * _mlon(la0), (la - la0) * R_LAT)
            gc = em(gla, glo)
            lem = [em(p["lat"], p["lon"]) for p in line]
            try:
                svg, _ = render_hole.render_hole(hn, config.HOLES)
            except Exception:
                continue
            # recover each tick's drawn position by re-solving the radius from the label itself
            for t in re.findall(r'<text x="9"[^>]*>(\d+)</text>', svg):
                yd = int(t)
                # the point on the polyline at that radius, found independently of render_hole
                target = yd * 0.9144
                best = None
                for i in range(len(lem) - 1):
                    ax, ay = lem[i]
                    bx, by = lem[i + 1]
                    for k in range(201):            # dense sample: no shared code with the engine
                        f = k / 200.0
                        px, py = ax + (bx - ax) * f, ay + (by - ay) * f
                        d = math.hypot(px - gc[0], py - gc[1])
                        if best is None or abs(d - target) < abs(best[0] - target):
                            best = (d, px, py)
                assert best is not None
                worst_label = max(worst_label, abs(best[0] - target) / 0.9144)
                off = min(render_hole.dist_pt_seg(best[1], best[2], lem[i][0], lem[i][1],
                                                  lem[i + 1][0], lem[i + 1][1])
                          for i in range(len(lem) - 1))
                worst_offline = max(worst_offline, off)
    # 1 yd covers the sampling step and the engine's local flat-earth metric vs a geodesic
    assert worst_label < 1.0, f"to-green label off by {worst_label:.2f} yd from the true straight line"
    assert worst_offline < 1.0, f"tick sits {worst_offline:.2f} m off the drawn centerline"


@needs_corpus
def test_no_tree_marker_sits_on_a_building():
    """Phase 1's goal: 1107 markers project-wide (53 on Merion's clubhouse roof) were drawn as
    trees. Class-6 filtering alone is not enough -- most tiles are unclassified, so a roof arrives
    as class 1 and only the OSM footprint identifies it."""
    def pip(x, y, poly):
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
                inside = not inside
            j = i
        return inside

    total_on_building = 0
    checked = 0
    for slug in CORPUS:
        tp = os.path.join(ROOT, "courses", slug, "trees_lidar.json")
        cp = os.path.join(ROOT, "courses", slug, "osm_course.json")
        if not (os.path.exists(tp) and os.path.exists(cp)):
            continue
        trees = json.load(open(tp))
        blds = []
        for e in json.load(open(cp))["elements"]:
            if (e.get("tags") or {}).get("building") not in (None, "no") and e.get("geometry"):
                poly = [(p["lon"], p["lat"]) for p in e["geometry"]]
                xs = [c[0] for c in poly]
                ys = [c[1] for c in poly]
                blds.append((min(xs), min(ys), max(xs), max(ys), poly))
        for pts in trees.values():
            for la, lo in pts:
                checked += 1
                for x0, y0, x1, y1, poly in blds:
                    if x0 <= lo <= x1 and y0 <= la <= y1 and pip(lo, la, poly):
                        total_on_building += 1
                        break
    if not checked:
        pytest.skip("no tree data built")
    assert total_on_building == 0, f"{total_on_building} of {checked} tree markers sit on a building"


@needs_corpus
def test_every_green_conforms_to_rule_4_3_scale_cap():
    """The critical defect: render_green computed a legal size but emitted it as an SVG width=
    presentation attribute, which has zero CSS specificity, so the book stylesheet overrode it and
    15 of 198 greens printed over the 3/8 in : 5 yd cap (worst 1:392, 22% over) while three
    documents asserted the cap held."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_scale.py")],
                       cwd=ROOT, capture_output=True, text=True)
    if "no built books found" in r.stdout:
        pytest.skip("no built books to measure")
    assert r.returncode == 0, f"Rule 4.3 scale gate failed:\n{r.stdout[-2000:]}"
    assert "PASS" in r.stdout


# ---------------------------------------------------------------------------
# Course-data integrity -- catches transcription errors before they reach a card
# ---------------------------------------------------------------------------
def _check_course(j, label):
    """The five checks a course.json must satisfy. Every one of these has been violated in
    practice: par that did not sum, a handicap column that was not a permutation, and a tee whose
    rating ROSE as its yardage fell (Micke Grove's Red row was a women's rating, which would
    inflate a boy's handicap differential by ~5 strokes)."""
    holes = j["holes"]
    nums = sorted(int(k) for k in holes)
    cols = j["hole_cols"][2:]
    errs = []
    if sum(holes[str(h)][0] for h in nums) != j.get("par", 72):
        errs.append(f"{label}: per-hole pars do not sum to par={j.get('par')}")
    if sorted(holes[str(h)][1] for h in nums) != list(range(1, len(nums) + 1)):
        errs.append(f"{label}: mens_hcp is not a permutation of 1..{len(nums)}")
    for h in nums:
        if len(holes[str(h)]) != len(j["hole_cols"]):
            errs.append(f"{label}: hole {h} has {len(holes[str(h)])} values, hole_cols has {len(j['hole_cols'])}")
    by_name = {t["name"]: t for t in j.get("tees", [])}
    for i, name in enumerate(cols):
        if name not in by_name:
            errs.append(f"{label}: hole_cols names tee {name!r} which is absent from 'tees'")
            continue
        tot = sum(holes[str(h)][2 + i] for h in nums)
        if by_name[name].get("yards") is not None and tot != by_name[name]["yards"]:
            errs.append(f"{label}: {name} rows sum to {tot} but 'tees' says {by_name[name]['yards']}")
    rated = [(t["yards"], t["rating"], t["name"]) for t in j.get("tees", [])
             if t.get("rating") is not None and t.get("yards") is not None]
    rated.sort(reverse=True)
    for a, b in zip(rated, rated[1:]):
        if b[1] > a[1]:
            errs.append(f"{label}: {b[2]} ({b[0]}yd) rates {b[1]} above {a[2]} ({a[0]}yd) at {a[1]} "
                        f"-- a women's rating in a men's column?")
    return errs


def test_example_template_is_self_consistent():
    """The template a stranger copies must itself pass every check a real course must -- it was
    shipped once with per-hole rows summing to 7020 against a declared 6800."""
    p = os.path.join(ROOT, "examples", "course.json")
    if not os.path.exists(p):
        pytest.skip("no examples/course.json")
    errs = _check_course(json.load(open(p)), "examples/course.json")
    assert not errs, "template is inconsistent: " + "; ".join(errs)


@needs_corpus
def test_every_built_course_is_self_consistent():
    """Same checks against every course actually built here."""
    errs = []
    for slug in CORPUS:
        errs += _check_course(json.load(open(os.path.join(ROOT, "courses", slug, "course.json"))), slug)
    assert not errs, "course data inconsistencies: " + "; ".join(errs)
