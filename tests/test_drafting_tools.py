"""The sw_drafting_* tools through the MCP server, against a simulated SOLIDWORKS (SimSW from test_sw_selftest, plus a
stand-in for the add-in's drawing commands). This proves the tools' wiring, schemas, validation and the flow
analyse -> plan -> build -> check -> feedback. It is NOT a SOLIDWORKS test: the drawing commands here are simulated
(docs/drafting-intelligence/TECHNICAL_SPECIFICATION.md, section 8, lists the live tests still to run)."""

import copy
import json

import anyio
import pytest

from opensketch import mcp_server, sw_tools, swbridge
from opensketch.drafting import strategy
from tests.test_sw_selftest import SimRefusal, SimSW, _swap

SHEETS = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841)}
SW_TYPE = {"sketch": "ProfileFeature", "extrude": "Extrusion", "hole": "HoleWzd"}


class SimDrafting(SimSW):
    """SimSW plus names, numbers, model details and drawings with their annotations, as the add-in (0.15) reports them."""

    material = "6061-T6 (SN)"
    density = 2.7
    mass_override = None

    def __init__(self):
        super().__init__()
        self.detail_reads = 0
        self.annotation_reads = 0
        self.tolerances = {}
        self.annotation_actions = []

    def op_add_features(self, a, d=None):
        res, files = super().op_add_features(a, d)
        d = d or self._doc(a)
        for f, row in zip(a["features"], res["features"]):
            if f.get("name") and row.get("name"):
                d["names"][f["name"]] = d["names"].pop(row["name"])
                row["name"] = f["name"]
        return res, files

    def op_read(self, a):
        d = self._doc(a)
        doc, st = self._regen(d)
        names = {v: k for k, v in d["names"].items()}
        feats, dims = [], []
        for f in doc["features"]:
            typ = "ICE" if f["type"] == "extrude" and f.get("op") == "cut" else SW_TYPE.get(f["type"], f["type"])
            row = {"name": names.get(f["id"], f["id"]), "type": typ}
            if f.get("sketch"):
                row["uses"] = [names.get(f["sketch"], f["sketch"])]
            feats.append(row)
            for c in f.get("constraints", []):
                if c.get("value") is not None:
                    dims += [{"name": f"{c['id']}@{row['name']}@{d['title']}", "value": c["value"], "unit": "mm"}] * 2
            if f.get("depth"):
                dims.append({"name": f"D1@{row['name']}@{d['title']}", "value": f["depth"], "unit": "mm"})
        bb = st.part.bounding_box()
        body = {"solids": 1, "volume_mm3": st.part.volume, "mass_g": st.part.volume * 0.0027,
                "bbox": {"min": list(bb.min), "max": list(bb.max), "size": [bb.size.X, bb.size.Y, bb.size.Z]}}
        out = {"doc": a["doc"], "title": d["title"].rsplit(".", 1)[0], "kind": d["kind"], "features": feats, "sketches": {},
               "body": body, "dimensions": dims, "update_stamp": d["stamp"]}
        if a.get("numbers"):
            out["material"] = "6061-T6 (SN)"
        if a.get("details"):
            self.detail_reads += 1
            out["details"] = self._details(d, doc, st, dims)
        return out, {}

    def _details(self, d, doc, st, dims):
        """The model details in the shape ModelData.cs gives them (system units converted once, units stated)."""
        names = {v: k for k, v in d["names"].items()}
        vol_m3 = st.part.volume * 1e-9
        dens = self.density                                    # g/cm3
        mass_kg = self.mass_override if self.mass_override is not None else vol_m3 * dens * 1000
        implied = mass_kg / vol_m3
        holes = [{"feature": names.get(f["id"], f["id"]), "hole_type": "CounterBored" if f.get("style") == "counterbore" else "Simple",
                  "standard": "ISO", "size": f"M{int(f['diameter']) - 1}", "hole_diameter": f["diameter"], "threaded": False,
                  "threaded_basis": None, "unit": "mm"} for f in doc["features"] if f["type"] == "hole"]
        seen = {}
        for x in dims:
            seen.setdefault(x["name"], {"name": x["name"], "value": x["value"], "unit": "mm", "driven": False, "reference": False,
                                        **({"tolerance": self.tolerances[x["name"]]} if x["name"] in self.tolerances else {})})
        return {"units": {"length": "mm", "angle": "deg", "mass": "g"},
                "configurations": [{"name": "Default", "active": True}], "custom_properties": {"Description": "Clamp plate"},
                "material": {"active": {"name": self.material, "database": "SOLIDWORKS Materials" if self.material else None,
                                        "assigned": bool(self.material)}},
                "mass_properties": {"mass": {"value": round(mass_kg * 1000, 6), "unit": "g"},
                                    "volume": {"value": round(st.part.volume, 3), "unit": "mm^3"},
                                    "density": {"value": dens, "unit": "g/cm^3"},
                                    "density_from_mass_and_volume": {"value": round(implied, 6), "unit": "kg/m^3"},
                                    "consistent": abs(implied - dens * 1000) <= 1e-6 * max(1.0, dens * 1000),
                                    "override_mass": self.mass_override is not None, "user_assigned": False},
                "holes": holes, "threads": [], "cut_list": [], "dimensions": list(seen.values())}

    def op_create_drawing(self, a):
        model = self._doc(a)
        _, st = self._regen(model)
        bb = st.part.bounding_box()
        size = [bb.size.X, bb.size.Y, bb.size.Z]
        num, den = a.get("scale") or [1, 1]
        s = num / den
        W, H = SHEETS[a.get("sheet", "A3")]
        stem = model["title"].rsplit(".", 1)[0]
        path = a["doc"].rsplit("\\", 1)[0] + "\\" + (a.get("name") or stem) + ".SLDDRW"
        if path in self.docs and not a.get("overwrite"):
            path = path.replace(".SLDDRW", "_2.SLDDRW")
        views = []
        x = 20.0
        for i, o in enumerate(a.get("views") or ["front", "top", "right", "isometric"], 1):
            w, h = (strategy.view_size(size, o) if o != "isometric" else (size[0] * 0.7, size[1] * 0.7))
            w, h = w * s, h * s
            # the stand-in places named views in a row, slightly out of line, so the layout check has work to do
            y = 120.0 + 3.0 * i
            views.append({"name": f"Drawing View{i}", "type": "model", "orientation": f"*{o.title()}", "scale": f"{num:g}:{den:g}",
                          "uses_sheet_scale": o != "isometric", "outline_mm": [x, y, x + w, y + h], "display": "hidden_removed",
                          "dimensions": 6 if i == 1 and a.get("dimensions") else 0, "model": a["doc"]})
            x += w + 30
        self.docs[path] = {"kind": "drawing", "title": stem + ".SLDDRW", "features": [], "names": {}, "count": {}, "components": [],
                           "mates": [], "params": {}, "stamp": 0, "views": views, "props": dict(a.get("properties") or {}),
                           "sheet": {"name": "Sheet1", "width_mm": W, "height_mm": H, "scale": f"{num:g}:{den:g}", "projection": "third angle"},
                           "notes": a.get("notes")}
        return {"doc": path, "title": stem + ".SLDDRW", "kind": "drawing", "model": a["doc"], "sheet": self.docs[path]["sheet"],
                "views": [{"name": v["name"], "orientation": v["orientation"]} for v in views], "dimensions": 6, "notes": a.get("notes")}, {}

    def op_read_drawing(self, a):
        d = self._doc(a)
        if d["kind"] != "drawing":
            raise RuntimeError("not a drawing")
        out = {"doc": a["doc"], "title": d["title"], "sheet": d["sheet"], "sheets": 1, "views": copy.deepcopy(d["views"]),
               "properties": dict(d["props"])}
        if a.get("annotations"):
            notes = [{"type": "note", "name": f"DetailItem{i + 1}", "text": t, "at": [10.0, 10.0 + 6 * i], "height_mm": 3.5,
                      "box_mm": [10.0, 10.0 + 6 * i, 10.0 + 2.2 * len(t), 13.5 + 6 * i]}
                     for i, t in enumerate(reversed(d.get("notes") or []))]
            groups = [{"view": "Sheet", "annotations": notes, "tables": d.setdefault("tables", [])}]
            for v in d["views"]:
                groups.append({"view": v["name"], "annotations": [x for x in d.setdefault("annotations", []) if x["view"] == v["name"]],
                               "tables": []})
            out["annotations"] = [{"view": g["view"], "tables": g["tables"],
                                   "annotations": [{k: val for k, val in x.items() if k != "view"} for x in g["annotations"]]} for g in groups]
            self.annotation_reads += 1
        return out, {}

    def _annotate(self, d, view, typ, at, w, h, **extra):
        anns = d.setdefault("annotations", [])
        name = f"{'RD' if typ == 'dimension' else typ.upper()}{len(anns) + 1}"
        row = {"view": view, "type": typ, "name": name, "at": list(at), "box_mm": [at[0], at[1], at[0] + w, at[1] + h], **extra}
        anns.append(row)
        return {k: v for k, v in row.items() if k != "view"}

    def op_edit_drawing(self, a):
        d = self._doc(a)
        out = []
        for act in a["actions"]:
            if act["do"] in ("section", "detail"):
                parent = next(v for v in d["views"] if v["name"] == act["view"])
                o = parent["outline_mm"]
                w, h = (o[2] - o[0], 12.0) if act["do"] == "section" else (40.0, 40.0)
                cx, cy = act["place"]
                d["views"].append({"name": f"{'Section View' if act['do'] == 'section' else 'Detail View'} {act['label']}-{act['label']}",
                                   "type": act["do"], "orientation": "*Front", "scale": parent["scale"], "uses_sheet_scale": True,
                                   "outline_mm": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], "display": "hidden_removed",
                                   "dimensions": 0, "model": parent["model"]})
            elif act["do"] == "move":
                v = next(v for v in d["views"] if v["name"] == act["view"])
                o = v["outline_mm"]
                w, h = o[2] - o[0], o[3] - o[1]
                cx, cy = act["to"]
                v["outline_mm"] = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
            elif act["do"] == "dimensions":
                for v in d["views"]:
                    if v["type"] == "section":
                        v["dimensions"] = 2
            elif act["do"] in ("hole_callout", "surface_finish"):
                self.annotation_actions.append(act)
                v = next((v for v in d["views"] if v["name"] == act["view"]), None)
                if v is None:
                    raise SimRefusal(f"No view {act['view']}")
                o = v["outline_mm"]
                at = act.get("at") or [o[2] + act.get("offset", [12, 12])[0], o[3] - 10 + act.get("offset", [12, 12])[1] / 10]
                if act["do"] == "hole_callout":
                    out.append({"do": act["do"], "ok": True, **self._annotate(d, v["name"], "dimension", at, 24, 9, kind="hole callout",
                                                                               text="2X Ø11 THRU ALL ⌴ Ø18 ↧ 11")})
                else:
                    out.append({"do": act["do"], "ok": True, **self._annotate(d, v["name"], "surface_finish", at, 8, 8,
                                                                               texts=[act.get("roughness_max")])})
                continue
            elif act["do"] == "tolerance":
                self.annotation_actions.append(act)
                if not act.get("model_change"):
                    raise SimRefusal(f"{act['dimension']} is a model dimension: its tolerance is stored in the part, so setting it here "
                                     "changes the part. Set it in the part, or pass model_change=true once the designer agrees.")
                self.tolerances[act["dimension"]] = {"type": act["type"], "hole_fit": act.get("hole_fit"), "shaft_fit": act.get("shaft_fit")}
            elif act["do"] == "move_annotation":
                row = next((x for x in d.get("annotations", []) if x["name"] == act["name"]), None)
                if row is None:
                    raise SimRefusal(f"No annotation named {act['name']} on this sheet.")
                dx, dy = act["to"][0] - row["at"][0], act["to"][1] - row["at"][1]
                row["at"] = list(act["to"])
                row["box_mm"] = [row["box_mm"][0] + dx, row["box_mm"][1] + dy, row["box_mm"][2] + dx, row["box_mm"][3] + dy]
            out.append({"do": act["do"], "ok": True})
        return {"doc": a["doc"], "actions": out, "views": copy.deepcopy(d["views"])}, {}

    def op_export(self, a):
        d = self._doc(a)
        if a.get("format") == "pdf":
            return {"file": "out.pdf", "title": d["title"], "format": "pdf"}, {"out.pdf": b"%PDF-1.4\n%simulated\n"}
        return super().op_export(a)


@pytest.fixture()
def sim(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path / "data"))
    s = SimDrafting()
    monkeypatch.setattr(sw_tools, "_run", s.run)
    from opensketch import sw_drafting
    monkeypatch.setattr(sw_drafting, "_run", s.run)
    monkeypatch.setattr(swbridge, "status", lambda who, *a: {"connected": True, "machine": "SIM"})
    sw_tools._cache.clear()
    yield s
    sw_tools._cache.clear()


def _call(name, args):
    out = anyio.run(mcp_server.mcp.call_tool, name, args)
    blocks = out.content if hasattr(out, "content") else out[0] if isinstance(out, tuple) else out
    return json.loads(blocks[0].text), bool(getattr(out, "is_error", False) or getattr(out, "isError", False))


def _circle(sid, plane, cx, cy, dia):
    return {"id": sid, "type": "sketch", "plane": plane,
            "entities": [{"id": "c", "type": "point", "x": cx, "y": cy}, {"id": "k", "type": "circle", "center": "c", "r": dia / 2}],
            "constraints": [{"id": "D", "type": "diameter", "refs": ["k"], "value": dia},
                            {"id": "X", "type": "distance", "refs": ["c", "origin"], "orient": "horizontal", "value": abs(cx)},
                            {"id": "Y", "type": "distance", "refs": ["c", "origin"], "orient": "vertical", "value": abs(cy)}]}


TOP = {"type": "face", "origin": [0, 0, 20], "normal": [0, 0, 1], "xdir": [1, 0, 0]}


def _plate(sim):
    res, _ = sim.op_create_document({"name": "Clamp", "kind": "part"})
    doc = res["doc"]
    rect = {"id": "s1", "type": "sketch", "plane": {"ref": "Front Plane"}, "name": "Outline",
            "entities": [{"id": "a", "type": "point", "x": -80, "y": -50}, {"id": "b", "type": "point", "x": 80, "y": -50},
                         {"id": "c", "type": "point", "x": 80, "y": 50}, {"id": "d", "type": "point", "x": -80, "y": 50},
                         {"id": "l1", "type": "line", "p1": "a", "p2": "b"}, {"id": "l2", "type": "line", "p1": "b", "p2": "c"},
                         {"id": "l3", "type": "line", "p1": "c", "p2": "d"}, {"id": "l4", "type": "line", "p1": "d", "p2": "a"}],
            "constraints": [{"id": "L", "type": "distance", "refs": ["a", "b"], "value": 160},
                            {"id": "W", "type": "distance", "refs": ["b", "c"], "value": 100}]}
    feats = [rect, {"id": "e1", "type": "extrude", "sketch": "s1", "depth": 20, "name": "Plate"}]
    for n, x in enumerate((-60, 60)):
        feats.append({"id": f"h{n}", "type": "hole", "plane": TOP, "x": x, "y": 0, "diameter": 11, "end": "through_all", "reverse": True,
                      "style": "counterbore", "bore_diameter": 18, "bore_depth": 11})
    sk = _circle("s9", TOP, 20, 25, 5.0)
    sk["name"] = "M6 Tapping"
    feats += [sk, {"id": "e9", "type": "extrude", "sketch": "s9", "op": "cut", "depth": 12, "reverse": True}]
    sk2 = _circle("s10", TOP, -20, 25, 5.0)
    feats += [sk2, {"id": "e10", "type": "extrude", "sketch": "s10", "op": "cut", "depth": 12, "reverse": True}]
    r, _ = sim.op_add_features({"doc": doc, "features": [_swap(copy.deepcopy(f), {}) for f in feats]})
    assert all(row["state"] != "error" for row in r["features"]), r
    return doc


def test_analyse_plan_build_check_and_feedback_through_the_mcp_server(sim):
    doc = _plate(sim)
    ana, err = _call("sw_drafting_analyse", {"doc": doc})
    assert not err, ana
    text = " ".join(ana["identified"])
    assert "counterbored Ø18 x 11" in text and "Ø5 x 12 blind" in text, ana["identified"]
    assert ana["primary"] in ("milling_drilling", "plate_fabrication")
    assert any(u["what"] == "threads" and u["blocking"] for u in ana["unknown"])
    assert ana["knowledge"] and all("source" in k for k in ana["knowledge"])

    pl, err = _call("sw_drafting_plan", {"doc": doc, "standard": "AS1100"})
    assert not err, pl
    assert pl["plan_id"].startswith("pl_") and pl["views"][0]["role"] == "main" and pl["views"][0]["why"]
    assert pl["sections"], "counterbores need a section"
    assert {q["id"] for q in pl["questions"] if q["blocking"]} >= {"general_tolerance", "threads"}
    assert "GENERAL TOLERANCES: TO BE CONFIRMED." in " ".join(pl["notes"])

    built, err = _call("sw_drafting_build", {"plan_id": pl["plan_id"], "export": ["pdf"]})
    assert not err, built
    assert built["drawing"].endswith(".SLDDRW")
    assert "create_drawing" in sim.ops and "edit_drawing" in sim.ops and "read_drawing" in sim.ops
    steps = {s["step"]: s for s in built["steps"]}
    assert "section" in steps["edit_drawing"]["actions"] and steps["edit_drawing"]["ok"]
    assert steps["layout corrections"]["moves"], "the stand-in's views are out of line: the build moved them"
    assert {m["do"] for m in steps["layout corrections"]["moves"]} <= {"move", "move_annotation"}, "presentation moves only"
    q = built["quality"]
    assert q["release_blocked"] and q["manufacturing_ready"] is False
    assert any("general tolerance" in b.lower() for b in q["release_blockers"])
    assert built["exports"]["pdf"].get("download_url")
    drw = sim.docs[built["drawing"]]
    assert any(v["type"] == "section" for v in drw["views"])
    assert drw["props"].get("Material") == "6061-T6 (SN)" and "CheckedBy" not in drw["props"]

    chk, err = _call("sw_drafting_check", {"doc": built["drawing"], "plan_id": pl["plan_id"],
                                           "answers": {"general_tolerance": "ISO 2768-m", "threads": {"H1": "M6x1-6H thread 10"}}})
    assert not err, chk
    assert not any(f["check"] in ("general_tolerance", "threads") for f in chk["release_blockers"])
    assert chk["manufacturing_ready"] is False and 0 <= chk["quality_index"] <= 100

    rv, err = _call("sw_drafting_feedback", {"kind": "submit_for_review", "plan_id": pl["plan_id"]})
    assert not err, rv
    assert rv["review"]["status"] == "awaiting_expert" and rv["review"]["engine"]["release_blocked"] == chk["release_blocked"]
    assert rv["review"]["engine"]["quality_index"] == chk["quality_index"], "the engine's latest check is what the expert is compared with"
    out, err = _call("sw_drafting_feedback", {"kind": "expert_approve", "plan_id": pl["plan_id"], "reviewer": "expert"})
    assert err and "reviewer_name" in out["error"]
    fb, err = _call("sw_drafting_feedback", {"kind": "expert_approve", "plan_id": pl["plan_id"], "reviewer": "expert", "retain": True,
                                             "reviewer_name": "A. Reviewer", "expert_score": 70, "comment": "good"})
    assert not err and fb["status"] == "approved expert example" and fb["stats"]["approved_examples"] == 1
    assert fb["review"]["status"] == "expert_reviewed"
    assert fb["review"]["agreement"] == ("engine stricter" if chk["release_blocked"] else "agree")
    assert fb["stats"]["reviews"]["expert_reviewed"] == 1
    g, err = _call("sw_drafting_feedback", {"kind": "guideline", "reviewer": "expert",
                                            "guideline": {"topic": "clamp plates", "practice": "dimension clamp plate holes from the centre lines"}})
    assert not err and g["status"] == "company"
    kb, err = _call("sw_drafting_knowledge", {"query": "clamp plate holes centre lines"})
    assert not err and kb["results"][0]["level"] == "company", "the account's own guideline is found first"


def test_the_tools_refuse_bad_input_before_anything_reaches_solidworks(sim):
    doc = _plate(sim)
    n = len(sim.ops)
    out, err = _call("sw_drafting_plan", {"doc": doc, "answers": {"tolerance": "loose"}})
    assert err and "input_problems" in out and len(sim.ops) == n
    out, err = _call("sw_drafting_plan", {"doc": doc, "scale": "half"})
    assert err and "scale" in out["error"]
    out, err = _call("sw_drafting_build", {"plan_id": "pl_nope"})
    assert err and "No plan" in out["error"]
    out, err = _call("sw_drafting_knowledge", {"query": "x", "discipline": "origami"})
    assert err
    out, err = _call("sw_drafting_feedback", {"kind": "guideline", "guideline": {"topic": "x"}})
    assert err and "practice" in out["error"]


def test_a_plan_belongs_to_its_account(sim, monkeypatch):
    doc = _plate(sim)
    pl, _ = _call("sw_drafting_plan", {"doc": doc})
    from opensketch import sw_drafting
    monkeypatch.setattr(sw_drafting, "_account", lambda: "someone-else")
    out, err = _call("sw_drafting_build", {"plan_id": pl["plan_id"]})
    assert err and "No plan" in out["error"]


def test_the_tools_page_lists_the_drafting_tools():
    from opensketch import catalog
    names = {n for _, tools in catalog.GROUPS for n, _, _ in tools}
    assert {"sw_drafting_analyse", "sw_drafting_plan", "sw_drafting_build", "sw_drafting_check", "sw_drafting_knowledge",
            "sw_drafting_feedback"} <= names
    tools = {t.name: t for t in anyio.run(mcp_server.mcp.list_tools)}
    assert tools["sw_drafting_analyse"].annotations.read_only_hint is True
    assert tools["sw_drafting_knowledge"].annotations.read_only_hint is True
    assert "answers" in tools["sw_drafting_plan"].input_schema["properties"]



def _old_addin(monkeypatch):
    """An add-in that reports 0.14: the 0.15 reads and actions are refused before anything is sent."""
    def too_old(user, needed, what, device=None):
        if swbridge.version_tuple(needed) > swbridge.version_tuple("0.14.0"):
            return f"{what} needs the CAD Automation add-in {needed} or newer; SOLIDWORKS on SIM runs 0.14.0."
        return None
    monkeypatch.setattr(swbridge, "addin_too_old", too_old)


def test_with_a_015_addin_the_model_details_and_annotations_are_read(sim):
    doc = _plate(sim)
    ana, err = _call("sw_drafting_analyse", {"doc": doc, "detail": True})
    assert not err, ana
    assert sim.detail_reads >= 1 and ana["model"]["details_read"] is True and ana["model"]["addin"] is None
    em = ana["engineering_model"]
    assert em["overall"]["material"] == "6061-T6 (SN)" and em["overall"]["material_read_from_part"] is True
    assert any(c["what"] == "material" and "details" in c["source"] for c in em["confirmed"])
    assert em["design"]["units"]["length"] == "mm" and em["design"]["configurations"][0]["name"] == "Default"
    assert {h["hole_type"] for h in em["design"]["hole_wizard"]} == {"CounterBored"}
    mp = next(i for i in em["inferred"] if i["what"] == "mass properties")
    assert mp["mass"]["unit"] == "g" and mp["volume"]["unit"] == "mm^3" and mp["density"]["unit"] == "g/cm^3"
    assert not [p for p in em["problems"] if p["kind"] in ("mass", "material", "mass_unverified", "material_unverified")]


def test_a_mass_that_does_not_fit_the_material_is_explained_from_solidworks_own_numbers(sim):
    doc = _plate(sim)
    sim.material, sim.density = "", 0.001          # no material assigned: SOLIDWORKS uses a document density of 1 kg/m3
    ana, err = _call("sw_drafting_analyse", {"doc": doc, "detail": True})
    assert not err, ana
    probs = {p["kind"]: p for p in ana["engineering_model"]["problems"]}
    assert "material" not in probs, "no title block material: the missing material is asked for, not claimed as a mismatch"
    assert any(u["what"] == "material" and u["blocking"] and "no material assigned" in u["why"] for u in ana["engineering_model"]["unknown"])
    sim.material, sim.density, sim.mass_override = "6061-T6 (SN)", 2.7, 0.5
    ana, _ = _call("sw_drafting_analyse", {"doc": doc, "detail": True})
    assert any(p["kind"] == "mass" and "overridden" in p["why"] for p in ana["engineering_model"]["problems"])


def test_the_build_adds_the_planned_hole_callouts_and_reads_the_annotations_back(sim):
    doc = _plate(sim)
    pl, err = _call("sw_drafting_plan", {"doc": doc})
    assert not err, pl
    planned = pl["execution"]["annotations"]
    assert planned and {a["do"] for a in planned} == {"hole_callout"} and all(a["view"] == "@main" for a in planned)
    assert not any(a["do"] in ("tolerance", "surface_finish") for a in planned), "no engineering value without an answer"
    built, err = _call("sw_drafting_build", {"plan_id": pl["plan_id"]})
    assert not err, built
    step = next(s for s in built["steps"] if s["step"] == "annotations")
    assert step["ok"] and len(step["done"]) == len(planned), step
    views = {v["name"] for v in sim.docs[built["drawing"]]["views"]}
    assert all(a["view"] in views and "for" not in a and "why" not in a for a in sim.annotation_actions)
    assert sim.annotation_reads >= 1
    assert built["quality"]["findings"] is not None
    chk, err = _call("sw_drafting_check", {"doc": built["drawing"], "plan_id": pl["plan_id"]})
    assert not err and chk["annotations"]["counts"].get("dimension") == len(planned), chk["annotations"]
    assert not any(f["check"] == "annotations_unread" for f in chk["findings"])


def test_a_fit_goes_on_the_model_dimension_only_when_the_designer_allows_the_part_to_change(sim):
    doc = _plate(sim)
    pl, err = _call("sw_drafting_plan", {"doc": doc, "answers": {"fits": {"tapped holes": "Ø5 H7"}}})
    assert not err, pl
    assert not any(a["do"] == "tolerance" for a in pl["execution"]["annotations"])
    assert any("apply_fits_to_model" in d and "changes the part" in d for d in pl["execution"]["deferred"]), pl["execution"]["deferred"]
    pl, err = _call("sw_drafting_plan", {"doc": doc, "answers": {"fits": {"tapped holes": "Ø5 H7"}, "apply_fits_to_model": True}})
    tol = [a for a in pl["execution"]["annotations"] if a["do"] == "tolerance"]
    assert tol and tol[0]["hole_fit"] == "H7" and tol[0]["model_change"] is True
    assert tol[0]["confirmed_by"] == f"answers given for plan {pl['plan_id']}"
    built, err = _call("sw_drafting_build", {"plan_id": pl["plan_id"]})
    assert not err, built
    assert sim.tolerances and next(iter(sim.tolerances.values()))["hole_fit"] == "H7"
    # straight through sw_edit_drawing, a model dimension's tolerance without model_change is refused by SOLIDWORKS
    out, err = _call("sw_edit_drawing", {"doc": built["drawing"], "actions": [
        {"do": "tolerance", "dimension": tol[0]["dimension"], "type": "fit", "hole_fit": "H8", "confirmed_by": "J. Designer"}]})
    assert err and "changes the part" in out["error"]


def test_an_older_addin_gets_no_015_request_and_the_build_says_what_was_deferred(sim, monkeypatch):
    doc = _plate(sim)
    _old_addin(monkeypatch)
    ana, err = _call("sw_drafting_analyse", {"doc": doc})
    assert not err, ana
    assert sim.detail_reads == 0 and ana["model"]["details_read"] is False and "older than 0.15.0" in ana["model"]["addin"]
    pl, _ = _call("sw_drafting_plan", {"doc": doc})
    built, err = _call("sw_drafting_build", {"plan_id": pl["plan_id"]})
    assert not err, built
    step = next(s for s in built["steps"] if s["step"] == "annotations")
    assert step["deferred"] == [a["do"] for a in pl["execution"]["annotations"]] and "0.15.0" in step["note"]
    assert sim.annotation_reads == 0 and not sim.annotation_actions
    n = len(sim.ops)
    out, err = _call("sw_edit_drawing", {"doc": built["drawing"], "actions": [{"do": "hole_callout", "view": "Drawing View1", "edge": [0, 0, 0]}]})
    assert err and "0.15.0" in out["error"] and len(sim.ops) == n
    out, err = _call("sw_get_document", {"doc": doc, "details": True})
    assert err and "0.15.0" in out["error"]


def test_the_015_actions_are_checked_before_anything_reaches_solidworks(sim):
    doc = _plate(sim)
    pl, _ = _call("sw_drafting_plan", {"doc": doc})
    built, _ = _call("sw_drafting_build", {"plan_id": pl["plan_id"]})
    n = len(sim.ops)
    bad = [
        ({"do": "tolerance", "dimension": "D1@Plate", "type": "bilateral", "lower": -0.1, "upper": 0.1}, "needs confirmed_by"),
        ({"do": "tolerance", "dimension": "D1@Plate", "type": "bilateral", "confirmed_by": "J. Designer"}, "lower and/or upper"),
        ({"do": "tolerance", "dimension": "D1@Plate", "type": "fit", "hole_fit": "H 7", "confirmed_by": "J. Designer"}, "ISO 286"),
        ({"do": "tolerance", "dimension": "D1@Plate", "type": "fit", "hole_fit": "H7", "confirmed_by": "J. Designer", "model_change": "yes"},
         "model_change"),
        ({"do": "gtol", "view": "Drawing View1", "frames": [{"symbol": "wobble", "tolerance": "0.1"}], "confirmed_by": "J. Designer"}, "symbol"),
        ({"do": "gtol", "view": "Drawing View1", "frames": [{"symbol": "position"}], "confirmed_by": "J. Designer"}, "tolerance value"),
        ({"do": "datum", "view": "Drawing View1", "edge": [0, 0, 0], "label": "a", "confirmed_by": "J. Designer"}, "capital letters"),
        ({"do": "weld_symbol", "view": "Drawing View1", "edge": [0, 0, 0], "symbol": "fillet"}, "needs confirmed_by"),
        ({"do": "surface_finish", "view": "Drawing View1", "edge": [0, 0, 0], "symbol": "shiny", "confirmed_by": "J. Designer"}, "symbol"),
        ({"do": "dimension", "view": "Drawing View1", "kind": "diameter", "edges": [[0, 0, 0], [1, 0, 0]]}, "edges takes 1"),
        ({"do": "dimension", "view": "Drawing View1", "kind": "wiggly", "edges": [[0, 0, 0]]}, "kind"),
        ({"do": "centre_line", "view": "Drawing View1"}, "either face"),
        ({"do": "hole_callout", "view": "Drawing View1", "edge": [0, 0]}, "model point"),
        ({"do": "move_annotation", "name": "RD1", "to": [10]}, "[x, y]"),
    ]
    for act, why in bad:
        out, err = _call("sw_edit_drawing", {"doc": built["drawing"], "actions": [act]})
        assert err, act
        text = " ".join(out.get("input_problems") or [out.get("error", "")])
        assert why in text, (act, text)
    assert len(sim.ops) == n, "nothing was sent"


def test_overlapping_annotations_are_moved_apart_by_the_check_and_nothing_else_changes(sim):
    doc = _plate(sim)
    pl, _ = _call("sw_drafting_plan", {"doc": doc})
    built, _ = _call("sw_drafting_build", {"plan_id": pl["plan_id"], "correct_layout": True})
    d = sim.docs[built["drawing"]]
    v = d["views"][0]
    x, y = v["outline_mm"][0] + 5, v["outline_mm"][3] + 4
    sim._annotate(d, v["name"], "dimension", [x, y], 20, 5, value=160.0)
    sim._annotate(d, v["name"], "dimension", [x + 2, y + 1], 20, 5, value=100.0)
    before = {a["name"]: a.get("value") for a in d["annotations"]}
    chk, err = _call("sw_drafting_check", {"doc": built["drawing"], "correct_layout": True})
    assert not err, chk
    moves = [m for m in chk.get("layout_moves_applied", []) if m["do"] == "move_annotation"]
    assert moves, chk.get("layout_moves_applied")
    assert {a["name"]: a.get("value") for a in d["annotations"]} == before, "values are never changed"
    assert not any(f["check"] == "annotation_overlap" for f in chk["findings"])
