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
from tests.test_sw_selftest import SimSW, _swap

SHEETS = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841)}
SW_TYPE = {"sketch": "ProfileFeature", "extrude": "Extrusion", "hole": "HoleWzd"}


class SimDrafting(SimSW):
    """SimSW plus names, numbers and drawings as the add-in reports them."""

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
        return out, {}

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
        return {"doc": a["doc"], "title": d["title"], "sheet": d["sheet"], "sheets": 1, "views": copy.deepcopy(d["views"]),
                "properties": dict(d["props"])}, {}

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
    assert all(m["do"] == "move" for m in steps["layout corrections"]["moves"])
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

    fb, err = _call("sw_drafting_feedback", {"kind": "expert_approve", "plan_id": pl["plan_id"], "reviewer": "expert", "retain": True,
                                             "comment": "good"})
    assert not err and fb["status"] == "approved expert example" and fb["stats"]["approved_examples"] == 1
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
