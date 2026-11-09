"""windows/live_verify.py, the Phase 2.1 harness for a live SOLIDWORKS run. Its checks are tested here on their own,
and its whole run against the simulated add-in (SimDrafting): that proves the harness's flow and guards, NOT anything
about SOLIDWORKS. The live results come only from running it on the Windows computer."""

import importlib.util
import json
from pathlib import Path

import anyio
import pytest

from opensketch import mcp_server
from tests.test_drafting_tools import _plate, sim  # noqa: F401  (the simulated SOLIDWORKS fixture)

_spec = importlib.util.spec_from_file_location("live_verify", Path(__file__).resolve().parent.parent / "windows" / "live_verify.py")
lv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lv)


def test_only_a_server_on_this_computer_is_used():
    for url in ("https://bizomat.ai/cad/mcp", "https://cados.fly.dev/mcp", "http://192.168.1.5:8000/mcp", "https://mcp.bizomat.ai/mcp"):
        assert lv.check_server(url), url
    for url in ("http://127.0.0.1:8000/mcp", "http://localhost:8000/mcp", "http://[::1]:8000/mcp"):
        assert lv.check_server(url) is None, url
    assert lv.main(["--server", "https://bizomat.ai/cad/mcp", "--part", "a", "--drawing", "b"]) == 2


def test_copies_must_be_apart_from_the_originals():
    o = [r"C:\eng\MT-01.SLDPRT", r"C:\eng\MT-01.SLDDRW"]
    yes = lambda p: True
    assert lv.check_paths(r"C:\test\MT-01_T.SLDPRT", r"C:\test\MT-01_T.SLDDRW", o, yes) == []
    assert any("an original" in p for p in lv.check_paths(o[0], r"C:\test\x.SLDDRW", o, yes))
    assert any("original's folder" in p for p in lv.check_paths(r"C:\eng\MT-01_T.SLDPRT", r"C:\test\x.SLDDRW", o, yes))
    assert any("--original" in p for p in lv.check_paths(r"C:\test\a.SLDPRT", r"C:\test\a.SLDDRW", [], yes))
    assert any("no such file" in p for p in lv.check_paths(r"C:\test\a.SLDPRT", r"C:\test\a.SLDDRW", o, lambda p: "test" not in p))
    ok, models = lv.drawing_shows({"views": [{"model": r"C:\eng\MT-01.SLDPRT"}]}, r"C:\test\MT-01_T.SLDPRT")
    assert not ok and models == [r"C:\eng\MT-01.SLDPRT"], "a drawing copied in Explorer still shows the original part"


def test_the_mass_findings_name_each_possible_cause():
    base = {"units": {"length": "mm"}, "material": {"active": {"name": "", "assigned": False}, "document_density": {"value": 1.0, "unit": "kg/m^3"}},
            "mass_properties": {"native": {"mass": {"value": 0.002256, "unit": "kg"}, "volume": {"value": 0.002256, "unit": "m^3"}},
                                "mass": {"value": 2.256, "unit": "g"}, "volume": {"value": 2256000.0, "unit": "mm^3"},
                                "density": {"value": 0.001, "unit": "g/cm^3"}, "density_from_mass_and_volume": {"value": 1.0, "unit": "kg/m^3"},
                                "consistent": True, "override_mass": False, "user_assigned": False}}
    f = lv.mass_findings(base)
    assert f["unit_conversion"] == {"mass kg -> g": True, "volume m^3 -> mm^3": True}
    assert any("no material is assigned" in c for c in f["causes"]) and any("document density of 1 kg/m^3" in c for c in f["causes"])
    over = json.loads(json.dumps(base))
    over["material"]["active"] = {"name": "1.1730", "assigned": True}
    over["mass_properties"].update(override_mass=True, consistent=False)
    f = lv.mass_findings(over)
    assert any("overridden" in c for c in f["causes"]) and any("does not equal" in c for c in f["causes"])
    bad = json.loads(json.dumps(base))
    bad["mass_properties"]["mass"]["value"] = 2256.0
    assert any("unit conversion" in c for c in lv.mass_findings(bad)["causes"])


def _client():
    async def call(name, args):
        out = await mcp_server.mcp.call_tool(name, args)
        blocks = out.content if hasattr(out, "content") else out
        body, images = None, []
        for c in blocks:
            if c.type == "text" and body is None:
                try:
                    body = json.loads(c.text)
                except ValueError:
                    body = {"error": c.text}
            elif c.type == "image":
                import base64
                images.append(base64.b64decode(c.data))
        return lv.Reply(bool(getattr(out, "is_error", False)), body or {}, images)
    return call


def _copies(sim):
    part = _plate(sim)
    res, _ = sim.op_create_drawing({"doc": part, "views": ["front", "top", "right"], "dimensions": True, "scale": [1, 2]})
    return part, res["doc"]


def test_a_whole_run_against_the_simulated_addin_records_each_operation_and_keeps_the_originals(sim, tmp_path):  # noqa: F811
    part, drawing = _copies(sim)
    originals = [str(tmp_path / "orig" / "Clamp.SLDPRT"), str(tmp_path / "orig" / "Clamp.SLDDRW")]
    hashes = {o: "h-" + o for o in originals}
    res = anyio.run(lambda: lv.run_all(_client(), tmp_path / "out", part, drawing, originals, steps=None,
                                       exists=lambda p: True, hasher=lambda p: hashes[p], meta={"label": "SIMULATED"}))
    ops = {o["id"]: o for o in res["operations"]}
    assert not res["facts"].get("stopped"), res["facts"].get("stopped")
    assert res["facts"]["addin_version"] == "0.15.0" and res["facts"]["originals_unchanged"] is True
    assert ops["P4"]["outcome"] == "passed", "the copied drawing shows the copied part"
    for oid in ("R1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A10", "A11", "A12", "A14", "A15", "A16", "A17", "A18", "A19", "A21", "A22",
                "W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"):
        assert ops[oid]["outcome"] == "passed", (oid, ops[oid])
    assert ops["A13"]["outcome"] == "guard held" and ops["A13b"]["outcome"] == "guard held", "a model dimension's tolerance is refused"
    assert ops["A20"]["outcome"] == "guard held", "a cut list on a part that is not a weldment is refused"
    assert sim.part_changed is False
    assert ops["A23"]["evidence"] == ["A23.png"] and (tmp_path / "out" / "A23.png").read_bytes().startswith(b"\x89PNG")
    assert res["summary"]["GUARD FAILED"] == 0 and res["summary"]["failed"] == 0, [o for o in res["operations"] if o["outcome"] == "failed"]
    md = (tmp_path / "out" / "results.md").read_text()
    assert "SIMULATED" in md and "LIVE VERIFIED" in md and "| 6 annotations | A13 |" in md


def test_a_drawing_that_still_shows_the_original_stops_the_run_before_any_change(sim, tmp_path):  # noqa: F811
    part, drawing = _copies(sim)
    sim.docs[drawing]["views"][0]["model"] = r"C:\eng\Clamp.SLDPRT"
    res = anyio.run(lambda: lv.run_all(_client(), tmp_path / "out", part, drawing, [r"C:\eng\Clamp.SLDPRT"], exists=lambda p: True,
                                       hasher=lambda p: "same"))
    assert "Pack and Go" in res["facts"]["stopped"]
    assert "edit_drawing" not in sim.ops and "create_drawing" not in sim.ops[-3:], "nothing was changed"


def test_an_older_addin_stops_the_run(sim, tmp_path):  # noqa: F811
    part, drawing = _copies(sim)
    sim.addin_version = "0.14.0"
    res = anyio.run(lambda: lv.run_all(_client(), tmp_path / "out", part, drawing, [str(tmp_path / "o.SLDPRT")], exists=lambda p: True,
                                       hasher=lambda p: "same"))
    assert "0.15.0" in res["facts"]["stopped"] and len(res["operations"]) == 1
