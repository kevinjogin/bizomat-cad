"""The drafting intelligence engine (opensketch/drafting), module by module.

Recognition is tested on hand-made facts (no OpenCascade) and on the twelve synthetic benchmark solids (real
OpenCascade geometry, the same code path as a SOLIDWORKS body). The benchmark cases are synthetic test cases, not
expert-reviewed drawings (benchmarks.SYNTHETIC)."""

import json

import pytest

from opensketch.drafting import (benchmarks, dimensioning, disciplines, engine, features, knowledge, layout, learning, qa,
                                 standards, strategy, understanding)


# ----------------------------------------------------------------------------- knowledge base

def test_knowledge_entries_are_complete_unique_and_honest():
    es = knowledge.shipped()
    assert len(es) >= 54
    cats = knowledge.categories()
    assert sorted(cats) == [f"{i:02d}" for i in range(1, 19)]
    assert all(sum(1 for e in es if e["category"] == c) >= 3 for c in cats), "every category has at least three entries"
    for e in es:
        for f in ("topic", "concept", "explanation", "practice", "example", "correct", "mistake"):
            assert e[f], (e["id"], f)
        # nothing shipped claims to be a verified requirement, and no standard reference claims to be verified
        assert e["level"] in ("recommended", "example") and e["validation"] == "unverified", e["id"]
        assert all(not s["verified"] for s in e["standards"]), e["id"]
        assert e["source"]["type"] == "BIZOMAT drafting guide"


def test_a_mandatory_entry_must_be_verified():
    with pytest.raises(ValueError):
        knowledge.normalise({"id": "X", "category": "15", "topic": "t", "concept": "c", "practice": "p", "level": "mandatory"}, "test")
    ok = knowledge.normalise({"id": "X", "category": "15", "topic": "t", "concept": "c", "practice": "p", "level": "mandatory",
                              "validation": "verified"}, "test")
    assert ok["level"] == "mandatory"


@pytest.mark.parametrize("query,discipline,expect", [
    ("counterbore depth on hidden lines", "milling_drilling", "K02-002"),
    ("holes on a circle", None, "K10-004"),
    ("weld size", "weldment", "K05-001"),
    ("general tolerance", None, "K12-002"),
    ("flat pattern k-factor", "sheet_metal", "K06-001"),
    ("spool centre line", "piping", "K08-001"),
    ("thread tapping drill", None, "K03-003"),
])
def test_retrieval_finds_the_entry_a_drafter_would_cite(query, discipline, expect):
    res = knowledge.search(query, discipline=discipline, limit=3)
    assert res and res[0]["id"] == expect, [(r["id"], r["score"]) for r in res]
    assert res[0]["matched"] and res[0]["source"]


def test_suggestions_are_left_out_unless_asked_and_company_entries_rank_first():
    sug = knowledge.normalise({"id": "S1", "category": "10", "topic": "pitch circle trick", "concept": "pitch circle",
                               "practice": "pitch circle holes", "level": "suggestion"}, "company")
    com = knowledge.normalise({"id": "C1", "category": "10", "topic": "pitch circle house rule", "concept": "pitch circle",
                               "practice": "our pitch circle holes are always given with the first hole at 12 o'clock",
                               "level": "company", "validation": "reviewed"}, "company")
    ids = [r["id"] for r in knowledge.search("pitch circle holes", extra=[sug, com], limit=5)]
    assert "S1" not in ids and ids[0] == "C1"
    assert "S1" in [r["id"] for r in knowledge.search("pitch circle holes", extra=[sug, com], include_suggestions=True, limit=6)]


# ----------------------------------------------------------------------------- recognition on hand-made facts

def _cyl(i, r, axis_pt, d, span, concave=True):
    return {"i": i, "type": "cylinder", "area": 2 * 3.14159265 * r * (span[1] - span[0]), "center": axis_pt, "point": axis_pt,
            "axis": {"point": axis_pt, "dir": d}, "span": span, "concave": concave, "radius": r, "loops": 1}


def _plane(i, n, p, area, loops=1, bbox=None):
    return {"i": i, "type": "plane", "area": area, "center": p, "point": p, "normal": n, "offset": sum(a * b for a, b in zip(n, p)),
            "loops": loops, "bbox": bbox or [p, p]}


def test_a_counterbore_and_a_flat_bottomed_blind_hole_from_faces_alone():
    body = {"body": 0, "volume": 1.0, "bbox": {"min": [-50, -50, 0], "max": [50, 50, 20], "size": [100, 100, 20]}, "adjacency": [],
            "faces": [_plane(0, [0, 0, 1], [0, 0, 20], 9000), _plane(1, [0, 0, -1], [0, 0, 0], 9000),
                      _cyl(2, 5.5, [10, 0, 0], [0, 0, 1], [0, 9]),         # the Ø11 hole, z 0..9
                      _cyl(3, 9.0, [10, 0, 9], [0, 0, 1], [0, 11]),        # the Ø18 counterbore, z 9..20
                      _plane(4, [0, 0, 1], [10, 0, 9], 3.14159265 * (81 - 30.25)),
                      _cyl(5, 2.5, [-20, 0, 20], [0, 0, -1], [0, 12]),     # Ø5 blind from the top, z 8..20
                      _plane(6, [0, 0, 1], [-20, 0, 8], 3.14159265 * 6.25)]}
    rec = features.recognise_body(body)
    holes = {h["subtype"]: h for h in rec["holes"]}
    cb = holes["counterbore"]
    assert cb["diameter"] == 11.0 and cb["counterbore"] == {"diameter": 18.0, "depth": 11.0} and cb["through"]
    bl = holes["blind"]
    assert bl["diameter"] == 5.0 and bl["depth"] == 12.0 and bl["bottom"] == "flat"
    assert bl["possible_thread"]["thread"] == "M6" and bl["possible_thread"]["confidence"] == "low"
    assert 6 in bl["faces"] and 4 in cb["faces"]   # each hole owns its own floor and step


def test_four_holes_on_a_rectangle_are_a_grid_and_on_a_bore_a_pitch_circle():
    def hole(n, x, y):
        return {"id": f"H{n}", "subtype": "through", "diameter": 6.0, "dir": [0, 0, 1], "position": [x, y, 0.0]}
    rect = [hole(1, -50, -30), hole(2, 50, -30), hole(3, -50, 30), hole(4, 50, 30)]
    assert features.recognise_patterns(rect)[0]["pattern"] == "grid"
    import math
    circ = [hole(k, 40 * math.cos(math.radians(45 + 90 * k)), 40 * math.sin(math.radians(45 + 90 * k))) for k in range(4)]
    p = features.recognise_patterns(circ, round_axes=[([0, 0, 1], [0, 0, 0])])[0]
    assert p["pattern"] == "pitch_circle" and p["pcd"] == 80 and p["equally_spaced"]


# ----------------------------------------------------------------------------- recognition and planning on real geometry

@pytest.fixture(scope="module")
def bench():
    return engine.run_benchmarks()


def test_the_benchmark_set_is_labelled_synthetic_and_scores(bench):
    assert bench["label"] == benchmarks.SYNTHETIC
    assert len(bench["cases"]) == 12
    print(json.dumps({k: v for k, v in bench.items() if k != "cases"}))
    # regression floors: these held when the engine was written (8 Nov 2026); a change that lowers them is a regression
    assert bench["feature_recall"] >= 0.95
    assert bench["discipline_accuracy"] >= 0.9
    assert bench["main_view_accuracy"] >= 0.9
    assert bench["section_decision_accuracy"] >= 0.9


@pytest.mark.parametrize("name", [c["name"] for c in benchmarks.CASES])
def test_each_benchmark_case(bench, name):
    row = next(r for r in bench["cases"] if r["name"] == name)
    assert row["feature_recall"] == 1.0, row["feature_misses"]
    assert row["disciplines_ok"], (row["disciplines"], row["expected_disciplines"])
    assert row["main_view_ok"], (row["main_view"], row["views"])
    assert row["sections_ok"], row["sections"]
    if "assembly" not in name:
        assert row["release_blocked"], "a synthetic part without material or tolerances can never be release-ready"


def _analysis(name):
    case = next(c for c in benchmarks.CASES if c["name"] == name)
    f = benchmarks.build_facts(case)
    rec = engine.recognise_assembly_facts(f) if f.get("kind") == "assembly" else features.recognise(f)
    return engine.analyse("assembly" if f.get("kind") == "assembly" else "part", name, {"features": []}, {}, rec)


def test_a_plate_gets_a_plan_view_an_edge_view_and_a_section_no_isometric():
    ana = _analysis("multi_hole_plate")
    pl = engine.plan(ana, doc="C:\\x\\plate.SLDPRT")
    roles = [(v["orientation"], v["role"]) for v in pl["views"]]
    assert roles == [("front", "main"), ("top", "edge")]
    assert any("isometric" in o for o in pl["omitted_views"]) and any("thickness again" in o for o in pl["omitted_views"])
    assert pl["sections"] and {"counterbore", "countersink"} & set(pl["sections"][0]["why"].split(", ")) or "counterbore" in pl["sections"][0]["why"]
    assert pl["release_blocked"] and "general_tolerance" in pl["release_blocked_by"] and "threads" in pl["release_blocked_by"]
    assert "GENERAL TOLERANCES: TO BE CONFIRMED." in " ".join(pl["notes"])
    assert all("2768" not in n for n in pl["notes"]), "the engine never chooses a general tolerance"
    assert pl["execution"]["create_drawing"]["views"] == ["front", "top"]
    assert "CheckedBy" not in (pl["title_block"] or {}) and "ApprovedBy" not in (pl["title_block"] or {})


def test_answers_replace_the_placeholders_and_clear_the_blockers():
    ana = _analysis("multi_hole_plate")
    pl = engine.plan(ana, doc="d", answers={"general_tolerance": "ISO 2768-m", "material": "6061-T6",
                                            "threads": {"H1": "M6x1-6H thread 10", "H2": "M6x1-6H thread 10"}})
    assert "3. GENERAL TOLERANCES: ISO 2768-M." in pl["notes"]
    assert not [q for q in pl["questions"] if q["blocking"]]
    assert pl["title_block"]["Material"] == "6061-T6"


def test_a_shaft_gets_one_side_view_a_groove_detail_and_a_cross_hole_section():
    pl = engine.plan(_analysis("stepped_shaft"), doc="d")
    assert [v["orientation"] for v in pl["views"]] == ["front"]
    assert pl["details"] and pl["details"][0]["scale"] in ("2:1", "5:1", "10:1")
    assert pl["sections"] and "cross hole" in pl["sections"][0]["why"]


def test_an_assembly_is_classified_as_one_and_its_parts_get_their_own_disciplines():
    ana = _analysis("mechanical_assembly")
    d = ana["disciplines"]
    assert d["applies"] == ["mechanical_assembly"]
    prim = {p["part"]: p["primary"] for p in d["part_drawings"]}
    assert prim["Shaft"] == "turning"
    pl = engine.plan(ana, doc="d")
    assert any(v["orientation"] == "isometric" for v in pl["views"])
    assert not [q for q in pl["questions"] if q["id"] in ("general_tolerance", "material")]


def test_the_user_can_override_the_classification():
    ana = _analysis("bracket")
    over = disciplines.classify(ana["model"], ["sheet_metal", "mechanical_assembly"])
    assert over["applies"] == ["sheet_metal", "mechanical_assembly"] and over["overridden"]
    with pytest.raises(ValueError):
        disciplines.classify(ana["model"], ["origami"])


# ----------------------------------------------------------------------------- understanding and dimensioning

def _plate_read():
    dims = []
    for n, v in [("L@Outline", 160), ("W@Outline", 100), ("D1@Boss", 20), ("D1@M6 Tapping", 5),
                 ("D2@M6 Tapping", 28.284), ("D3@M6 Tapping", 28.284), ("D4@M6 Tapping", 28.284), ("D1@Cut-Extrude2", 15)]:
        dims += [{"name": n + "@P.Part", "value": v}] * 3
    return {"title": "P", "features": [{"name": "Outline", "type": "ProfileFeature"}, {"name": "Boss", "type": "Extrusion", "uses": ["Outline"]},
                                       {"name": "M6 Tapping", "type": "ProfileFeature"},
                                       {"name": "Cut-Extrude2", "type": "ICE", "uses": ["M6 Tapping"]}],
            "sketches": {"Outline": {"state": "fully defined"}, "M6 Tapping": {"state": "under defined"}}, "dimensions": dims,
            "body": {"volume_mm3": 320000.0, "mass_g": 0.32, "bbox": {"size": [160, 20, 100]}}}


def _pcd_rec():
    import math
    holes = []
    for k in range(4):
        a = math.radians(45 + 90 * k)
        holes.append({"kind": "hole", "id": f"H{k + 1}", "subtype": "blind", "diameter": 5.0, "depth": 15.0, "bottom": "flat",
                      "dir": [0, 1, 0], "axis": "y", "position": [round(40 * math.cos(a), 3), 20.0, round(40 * math.sin(a), 3)],
                      "segments": [{"diameter": 5.0, "from": 5, "to": 20, "length": 15.0, "faces": []}], "faces": [],
                      "through": False, "possible_thread": features._thread_hint(5.0)})
    body = {"body": 0, "bbox": {"min": [-80, 0, -50], "max": [80, 20, 50], "size": [160, 20, 100]}, "volume": 320000.0,
            "holes": holes, "patterns": features.recognise_patterns(holes, [([0, 1, 0], [0, 0, 0])]), "slots": [], "pockets": [],
            "steps": [], "bosses": [], "fillets": [], "chamfers": [], "turned_profile": None, "wall": None, "sheet_metal": None,
            "member": None, "elbows": [], "flange": None, "directions": {"y": [h["id"] for h in holes]}}
    return {"bodies": [body], "body_count": 1, "bbox": body["bbox"], "volume": body["volume"]}


def test_names_dimensions_and_mass_are_read_with_their_status():
    rec = _pcd_rec()
    m = understanding.build("part", "P", _plate_read(), {}, rec, {"Material": "S355 steel"})
    assert m["design"]["dimension_count"] == 8, "each model dimension once, although the add-in lists it three times"
    h = rec["bodies"][0]["holes"][0]
    assert "M6 Tapping" in h["named_by"] and h["possible_thread"]["confidence"] == "medium"
    kinds = {p["kind"] for p in m["problems"]}
    assert {"material", "mass", "sketch"} <= kinds, kinds
    assert any(u["what"] == "threads" and u["blocking"] for u in m["unknown"])
    assert any(c["what"] == "material" and "title block" in c["source"] for c in m["confirmed"])


def test_pitch_circle_given_as_offsets_and_repeated_locations_are_found():
    m = understanding.build("part", "P", _plate_read(), {}, _pcd_rec())
    dp = dimensioning.plan(m, ["milling_drilling"])
    kinds = {r["kind"] for r in dp["redundancy"]}
    assert "pcd_as_offsets" in kinds and "repeated_locations" in kinds
    call = dp["callouts"][0]
    assert call["callout"] == "4x Ø5 ↧15 EQ SP ON Ø80 PCD" and call["needs_confirmation"] == "thread"
    assert dp["coverage"]["coverage"] is not None and not [x for x in dp["coverage"]["missing"] if x["what"] == "depth"]


def test_hole_callouts_follow_iso_and_as_practice():
    cb = {"subtype": "counterbore", "diameter": 11.0, "through": True, "counterbore": {"diameter": 17.5, "depth": 11.0}}
    assert standards.callout(cb, 6) == "6x Ø11 THRU, ⌴Ø17.5 ↧11"
    cs = {"subtype": "countersink", "diameter": 6.6, "countersink": {"diameter": 13.0, "angle_deg": 90.0}}
    assert standards.callout(cs) == "Ø6.6 THRU, ⌵Ø13 x 90°"
    p = standards.profile("as1100")
    assert p["projection"] == "third" and not p["verified"] and "not claimed" in p["statement"]
    with pytest.raises(ValueError):
        standards.profile("XYZ")


# ----------------------------------------------------------------------------- layout and QA on a drawing as the add-in reads it

def _drawing(views, props=None, w=420, h=297):
    return {"doc": "C:\\x\\P.SLDDRW", "sheet": {"width_mm": w, "height_mm": h, "scale": "1:2", "projection": "third angle"},
            "views": views, "properties": props or {}}


def _view(name, o, box, dims=5, typ="model"):
    return {"name": name, "type": typ, "orientation": f"*{o.title()}", "scale": "1:2", "uses_sheet_scale": True,
            "outline_mm": box, "dimensions": dims, "model": "C:\\x\\P.SLDPRT"}


def test_layout_finds_misalignment_overlap_and_off_sheet_and_only_moves_views():
    d = _drawing([_view("V1", "front", [60, 70, 240, 90]), _view("V2", "top", [70, 110, 250, 240]),
                  _view("V3", "right", [230, 80, 380, 100]), _view("V4", "isometric", [400, 250, 460, 300], dims=2)])
    ev = layout.evaluate(d)
    checks = {f["check"] for f in ev["findings"]}
    assert {"alignment", "overlap", "off_sheet", "pictorial_dimensions"} <= checks, checks
    assert ev["corrections"] and all(c["do"] == "move" for c in ev["corrections"])
    top_fix = next(c for c in ev["corrections"] if c["view"] == "V2")
    assert top_fix["to"][0] == 150.0, "the top view moves over the front view's centre"


def test_projection_order_is_checked_for_third_angle():
    d = _drawing([_view("V1", "front", [60, 150, 240, 170]), _view("V2", "top", [60, 70, 240, 130])])
    assert any(f["check"] == "projection_position" for f in layout.evaluate(d)["findings"])


def test_qa_blocks_release_on_engineering_gaps_and_never_says_ready():
    rec = _pcd_rec()
    m = understanding.build("part", "P", _plate_read(), {}, rec)
    d = _drawing([_view("V1", "front", [60, 70, 240, 90]), _view("V2", "top", [60, 110, 240, 240]),
                  _view("V3", "right", [260, 70, 360, 90])], {"Title": "P"})
    rep = qa.check(d, m)
    ids = {f["check"] for f in rep["release_blockers"]}
    assert {"material", "general_tolerance", "threads"} <= ids, ids
    assert rep["release_blocked"] and rep["manufacturing_ready"] is False
    assert any(f["check"] == "redundant_view" and f["view"] == "V3" for f in rep["findings"])
    assert 0 <= rep["quality_index"] <= 100
    ok = qa.check(d, m, confirmed={"general_tolerance": "ISO 2768-m", "threads": {"H1": "M6"}, "material": "S355"})
    assert not ok["release_blocked"] and ok["manufacturing_ready"] is False


def test_section_placement_finds_free_space():
    d = _drawing([_view("V1", "front", [60, 70, 240, 90]), _view("V2", "top", [60, 110, 240, 240])])
    at = layout.free_spot(d, 180, 20, near="V2")
    box = (at[0] - 90, at[1] - 10, at[0] + 90, at[1] + 10)
    for v in d["views"]:
        o = v["outline_mm"]
        assert box[2] <= o[0] or box[0] >= o[2] or box[3] <= o[1] or box[1] >= o[3]


# ----------------------------------------------------------------------------- learning store

def test_feedback_keeps_decisions_and_only_retained_expert_approvals_become_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path))
    pl = engine.plan(_analysis("bracket"), doc="d")
    learning.save_plan("acct-1", pl)
    assert learning.get_plan("acct-1", pl["plan_id"])["plan_id"] == pl["plan_id"]
    assert learning.get_plan("acct-2", pl["plan_id"]) is None, "plans are per account"
    learning.record_feedback("acct-1", "change_views", plan_id=pl["plan_id"], before=["top", "front"], after=["top"], reviewer="user")
    r = learning.record_feedback("acct-1", "expert_approve", plan_id=pl["plan_id"], reviewer="expert", retain=False)
    assert not r["retained_as_example"]
    r = learning.record_feedback("acct-1", "expert_approve", plan_id=pl["plan_id"], reviewer="expert", retain=True)
    assert r["retained_as_example"] and r["status"] == "approved expert example"
    assert len(learning.examples("acct-1")) == 1
    g_user = learning.add_guideline("acct-1", {"topic": "our datum", "concept": "datum", "practice": "A is always the base"}, "user")
    g_exp = learning.add_guideline("acct-1", {"topic": "our edges", "concept": "edges", "practice": "break edges 0.3"}, "expert")
    assert g_user["level"] == "suggestion" and g_exp["level"] == "company"
    st = learning.stats("acct-1")
    assert st["plans"] == 1 and st["approved_examples"] == 1 and st["guidelines"] == 2
    with pytest.raises(ValueError):
        learning.record_feedback("acct-1", "teach_everything")


def test_the_drafting_modules_import_first_in_a_fresh_process():
    """A CAD worker's first import is the module of the function it runs (engine.recognise_part)."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    mods = sorted(p.stem for p in (root / "opensketch" / "drafting").glob("*.py") if p.stem != "__init__")
    code = ("import importlib, sys\nbad = []\nfor n in sys.argv[1:]:\n    for m in [k for k in sys.modules if k.startswith('opensketch')]:\n"
            "        del sys.modules[m]\n    try:\n        importlib.import_module('opensketch.drafting.' + n)\n"
            "    except Exception as e:\n        bad.append(f'{n}: {e!r}')\nprint('\\n'.join(bad))\nsys.exit(1 if bad else 0)\n")
    r = subprocess.run([sys.executable, "-c", code, *mods], cwd=root, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
