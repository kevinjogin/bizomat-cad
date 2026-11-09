"""Phase 2.1: live verification of BIZOMAT CAD in a real SOLIDWORKS, through this branch's LOCAL server.

Run it on the Windows computer, from the apps/cad folder, with the server of windows/start.ps1 running and the
add-in 0.15 connected to it (docs/drafting-intelligence/PHASE2_1_LIVE_VERIFICATION.md has the whole procedure):

  .venv\\Scripts\\python windows\\live_verify.py ^
      --part "C:\\...\\phase21-test\\MT-01_Top_Clamp_Plate_P21TEST.SLDPRT" ^
      --drawing "C:\\...\\phase21-test\\MT-01_Top_Clamp_Plate_P21TEST.SLDDRW" ^
      --original "C:\\...\\MT-01_Top_Clamp_Plate.SLDPRT" --original "C:\\...\\MT-01_Top_Clamp_Plate.SLDDRW"

Guards, checked before anything changes:
- the server must be on this computer (127.0.0.1, ::1 or localhost): production is never used;
- the copies must be in a folder of their own, not next to the originals, and the copied drawing must show the
  copied part (a drawing copied under a new name in Explorer still shows the original part: use Pack and Go);
- the originals are hashed (SHA-256) before and after the run; any change fails the run.

Every operation runs once, on its own; a failure is recorded with SOLIDWORKS' own message and the run goes on.
Engineering values are test values, marked as such on the copy. The result of an operation here is "executed" or
"failed": LIVE VERIFIED needs a person to inspect the evidence (screenshots, the PDF, the read-back).
Output: <out>/results.json, <out>/results.md, the screenshots and the PDFs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

TEST = "PHASE 2.1 TEST VALUE, not a design requirement"
TEST_NOTE = "PHASE 2.1 API TEST COPY. TEST VALUES ONLY. NOT FOR MANUFACTURE."
LOOPBACK = {"127.0.0.1", "::1", "localhost", "[::1]"}
NEEDED = "0.15.0"
AXIS = {"front": (2, 1), "back": (2, -1), "top": (1, 1), "bottom": (1, -1), "right": (0, 1), "left": (0, -1)}
VIEW_X = {"front": (1, 0, 0), "back": (-1, 0, 0), "top": (1, 0, 0), "bottom": (1, 0, 0), "right": (0, 0, -1), "left": (0, 0, 1)}


# ----------------------------------------------------------------------------------------------- pure checks

def check_server(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host not in LOOPBACK:
        return f"{url} is not on this computer: the live verification runs only against the local server (windows/start.ps1)."
    return None


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p.replace("\\", os.sep)))


def check_paths(part: str, drawing: str, originals: list[str], exists: Callable[[str], bool] = os.path.exists) -> list[str]:
    """Problems with the test copies (empty when they are safe to use)."""
    out = []
    if not originals:
        out.append("give the original files with --original (they are hashed before and after the run)")
    for p in [part, drawing, *originals]:
        if not exists(p):
            out.append(f"no such file: {p}")
    orig = {_norm(o) for o in originals}
    for p in (part, drawing):
        if _norm(p) in orig:
            out.append(f"{p} is an original: the test runs on copies only")
    folders = {_norm(os.path.dirname(o.replace("\\", os.sep))) for o in originals}
    for p in (part, drawing):
        if _norm(os.path.dirname(p.replace("\\", os.sep))) in folders:
            out.append(f"{p} is in an original's folder: put the copies in a folder of their own (Pack and Go)")
    return out


def drawing_shows(drawing: dict, part: str) -> tuple[bool, list[str]]:
    """Whether every model view of the drawing shows `part` (the copy), and the paths it shows."""
    models = sorted({str(v.get("model")) for v in drawing.get("views") or [] if v.get("model")})
    return bool(models) and all(_norm(m) == _norm(part) for m in models), models


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def version_tuple(v: Any) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


def orientation(view: dict) -> str:
    return str(view.get("orientation") or "").strip("*").lower()


def main_and_side(drawing: dict) -> tuple[dict | None, dict | None]:
    """The main (front, else first) model view and a standard view beside it."""
    views = [v for v in drawing.get("views") or [] if v.get("outline_mm") and orientation(v) in AXIS]
    main = next((v for v in views if orientation(v) == "front"), views[0] if views else None)
    side = next((v for v in views if v is not main and AXIS[orientation(v)][0] != AXIS[orientation(main)][0]), None) if main else None
    return main, side


def pick(topology: dict, view_orientation: str) -> dict:
    """Model points (part mm) on edges the view shows nearest the viewer: hole circles and two outline lines."""
    ax, sign = AXIS.get(view_orientation, (2, 1))
    edges = topology.get("edges") or []
    if not edges:
        return {}
    level = max(sign * e["mid"][ax] for e in edges)
    near = [e for e in edges if abs(sign * e["mid"][ax] - level) <= 0.05]
    circles = sorted((e for e in near if e.get("type") == "circle" and e.get("radius")), key=lambda e: -e["radius"])
    lines = sorted((e for e in near if e.get("type") == "line" and e.get("dir") and abs(e["dir"][ax]) < 1e-3),
                   key=lambda e: -e.get("length", 0))
    out: dict[str, Any] = {"face_level_mm": round(sign * level, 4), "axis": "xyz"[ax]}
    if circles:
        out["hole"] = circles[0]
        out["small_hole"] = circles[-1]
        out["holes"] = circles
    if lines:
        l1 = lines[0]
        l2 = next((e for e in lines[1:] if abs(sum(a * b for a, b in zip(e["dir"], l1["dir"]))) < 1e-3), None)
        out["line"] = l1
        if l2:
            out["cross_line"] = l2
        vx = VIEW_X.get(view_orientation, (1, 0, 0))
        out["line_runs"] = "horizontal" if abs(sum(a * b for a, b in zip(l1["dir"], vx))) > 0.9 else "vertical"
    faces = [f for f in topology.get("faces") or [] if f.get("type") == "cylinder"]
    if faces:
        out["cylinder"] = max(faces, key=lambda f: f.get("area", 0))
    return out


def mass_findings(details: dict) -> dict:
    """What SOLIDWORKS' own numbers say about the mass: units, the material, the density used, any override."""
    mat = details.get("material") or {}
    act = mat.get("active") or {}
    mp = details.get("mass_properties") or {}
    native = mp.get("native") or {}
    val = lambda d: (d or {}).get("value")
    dens_gcm3 = val(mp.get("density"))
    doc_kgm3 = val(mat.get("document_density"))
    implied = val(mp.get("density_from_mass_and_volume"))
    f: dict[str, Any] = {"material_assigned": act.get("assigned"), "material": act.get("name") or None,
                         "per_configuration": mat.get("per_configuration"),
                         "density_used_kg_m3": None if dens_gcm3 is None else round(dens_gcm3 * 1000, 6),
                         "document_density_kg_m3": doc_kgm3, "density_from_mass_and_volume_kg_m3": implied,
                         "mass": mp.get("mass"), "volume": mp.get("volume"), "native": native,
                         "override_mass": mp.get("override_mass"), "user_assigned": mp.get("user_assigned"),
                         "consistent": mp.get("consistent"), "units": details.get("units")}
    checks = []
    nm, nv = val(native.get("mass")), val(native.get("volume"))
    if nm is not None and val(mp.get("mass")) is not None:
        checks.append(("mass kg -> g", math.isclose(nm * 1000, val(mp["mass"]), rel_tol=1e-6, abs_tol=1e-6)))
    if nv is not None and val(mp.get("volume")) is not None:
        checks.append(("volume m^3 -> mm^3", math.isclose(nv * 1e9, val(mp["volume"]), rel_tol=1e-6, abs_tol=1e-3)))
    f["unit_conversion"] = {k: ok for k, ok in checks}
    causes = []
    if mp.get("override_mass") or mp.get("user_assigned"):
        causes.append("the mass is overridden or assigned by hand in SOLIDWORKS")
    if act.get("assigned") is False:
        causes.append("no material is assigned in the active configuration")
        if doc_kgm3 is not None and dens_gcm3 is not None and math.isclose(doc_kgm3, dens_gcm3 * 1000, rel_tol=1e-6, abs_tol=1e-9):
            causes.append(f"SOLIDWORKS uses the document density of {doc_kgm3:g} kg/m^3 (Document Properties > Material Properties)")
    elif act.get("assigned") and dens_gcm3 is not None:
        causes.append(f"the assigned material {act.get('name')} has a density of {dens_gcm3 * 1000:g} kg/m^3 in SOLIDWORKS")
    if mp.get("consistent") is False:
        causes.append("mass / volume does not equal the density SOLIDWORKS reports")
    if checks and not all(ok for _, ok in checks):
        causes.append("a unit conversion in the add-in does not match SOLIDWORKS' own values")
    f["causes"] = causes
    return f


# ----------------------------------------------------------------------------------------------- the run

class Reply:
    def __init__(self, is_error: bool, body: Any, images: list[bytes]):
        self.is_error, self.body, self.images = is_error, body, images

    @property
    def error(self) -> str | None:
        if not self.is_error:
            return None
        return self.body.get("error") if isinstance(self.body, dict) else str(self.body)


Call = Callable[[str, dict], Awaitable[Reply]]


class Run:
    def __init__(self, call: Call, out: Path, fetch: Callable[[str], bytes] | None = None):
        self.call, self.out, self.fetch = call, out, fetch
        self.ops: list[dict] = []
        self.facts: dict[str, Any] = {}
        out.mkdir(parents=True, exist_ok=True)

    async def op(self, step: str, oid: str, title: str, tool: str, args: dict, expect: str = "ok",
                 check: Callable[[Reply], tuple[bool, str]] | None = None) -> Reply | None:
        """One operation: run, record what SOLIDWORKS answered, and the read-back check when there is one.
        expect="refused" for an operation that must be refused (a safety guard)."""
        t0 = time.time()
        row: dict[str, Any] = {"step": step, "id": oid, "title": title, "tool": tool, "args": args, "expect": expect}
        try:
            r = await self.call(tool, args)
        except Exception as exc:          # the run goes on: a transport or schema failure is a result too
            row.update(executed=False, outcome="failed", error=f"{type(exc).__name__}: {exc}", seconds=round(time.time() - t0, 2))
            self.ops.append(row)
            return None
        row["seconds"] = round(time.time() - t0, 2)
        row["executed"] = True
        row["error"] = r.error
        row["result"] = _brief(r.body)
        ok = (not r.is_error) if expect == "ok" else r.is_error
        if ok and check is not None:
            try:
                good, why = check(r)
            except Exception as exc:
                good, why = False, f"read-back check failed: {exc!r}"
            row["readback"] = why
            ok = ok and good
        row["outcome"] = ("passed" if ok else "failed") if expect == "ok" else ("guard held" if ok else "GUARD FAILED")
        for i, img in enumerate(r.images):
            name = f"{oid}{'-' + str(i) if i else ''}.png"
            (self.out / name).write_bytes(img)
            row.setdefault("evidence", []).append(name)
        self.ops.append(row)
        return r

    def skip(self, step: str, oid: str, title: str, why: str) -> None:
        self.ops.append({"step": step, "id": oid, "title": title, "executed": False, "outcome": "not run", "error": why})

    def save_download(self, body: Any, name: str) -> str | None:
        url = body.get("download_url") if isinstance(body, dict) else None
        if not url or self.fetch is None:
            return None
        try:
            (self.out / name).write_bytes(self.fetch(url))
            return name
        except Exception as exc:
            self.facts.setdefault("download_errors", []).append(f"{name}: {exc}")
            return None


def _brief(body: Any, n: int = 1500) -> Any:
    text = json.dumps(body, ensure_ascii=False, default=str)
    return body if len(text) <= n else text[:n] + " ..."


def _annotations(drawing: dict) -> list[dict]:
    return [dict(a, view=g.get("view")) for g in drawing.get("annotations") or [] for a in g.get("annotations") or []]


def _tables(drawing: dict) -> list[dict]:
    return [t for g in drawing.get("annotations") or [] for t in g.get("tables") or []]


async def preflight(run: Run, part: str, drawing: str) -> bool:
    st = await run.op("1 preflight", "P1", "SOLIDWORKS connected through the local server", "sw_status", {})
    body = st.body if st and isinstance(st.body, dict) else {}
    run.facts["status"] = _brief(body, 4000)
    if not body.get("connected"):
        run.facts["stopped"] = "SOLIDWORKS is not connected to the local server: no live operation was run."
        return False
    have = body.get("addin_version") or body.get("version")
    run.facts["addin_version"] = have
    run.facts["solidworks_version"] = body.get("sw_version")
    if version_tuple(have) < version_tuple(NEEDED):
        run.facts["stopped"] = f"The add-in is {have}; this verification needs {NEEDED} (windows/update-addin.ps1)."
        return False
    await run.op("1 preflight", "P2", "open the copied part", "sw_open_document", {"path": part})
    r = await run.op("1 preflight", "P3", "open the copied drawing", "sw_open_document", {"path": drawing})
    if r is None or r.is_error:
        run.facts["stopped"] = "The copied drawing did not open."
        return False
    r = await run.op("1 preflight", "P4", "the copied drawing shows the copied part", "sw_get_drawing", {"doc": drawing},
                     check=lambda rr: (drawing_shows(rr.body, part)[0], f"views show {drawing_shows(rr.body, part)[1]}"))
    if r is None or run.ops[-1]["outcome"] != "passed":
        run.facts["stopped"] = ("The copied drawing does not show the copied part (it still references another file): make the "
                                "copies with Pack and Go so the reference is updated. Nothing was changed.")
        return False
    return True


async def read_model(run: Run, part: str) -> dict:
    s = "5 read-only model"
    r = await run.op(s, "R1", "model details (units, configurations, properties, material, mass, Hole Wizard, threads, cut list)",
                     "sw_get_document", {"doc": part, "details": True},
                     check=lambda rr: (bool((rr.body or {}).get("details")), "details present" if (rr.body or {}).get("details") else "no details"))
    details = ((r.body if r and isinstance(r.body, dict) else {}) or {}).get("details") or {}
    run.facts["details"] = details
    run.facts["mass"] = mass_findings(details) if details else None
    await run.op(s, "R2", "feature states, volume, mass, centre of mass", "sw_inspect_design", {"doc": part})
    topo = await run.op(s, "R3", "faces and edges (geometry)", "sw_body_topology", {"doc": part, "kind": "both", "limit": 500})
    run.facts["topology_counts"] = {k: len((topo.body or {}).get(k) or []) for k in ("faces", "edges")} if topo and not topo.is_error else None
    return (topo.body if topo and not topo.is_error else {}) or {}


async def annotate(run: Run, part: str, drawing: str, topo: dict) -> None:
    s = "6 annotations"
    r = await run.op(s, "A0", "read the drawing with annotations", "sw_get_drawing", {"doc": drawing, "annotations": True},
                     check=lambda rr: ("annotations" in (rr.body or {}), f"{len(_annotations(rr.body or {}))} annotations read"))
    drw = (r.body if r and not r.is_error else {}) or {}
    main, side = main_and_side(drw)
    if main is None:
        run.skip(s, "A*", "annotation operations", "no standard model view on the copied drawing")
        return
    o = main["outline_mm"]
    sheet = drw.get("sheet") or {}
    W, H = float(sheet.get("width_mm") or 420), float(sheet.get("height_mm") or 297)
    p = pick(topo, orientation(main))
    run.facts["picked"] = {k: (v.get("mid") if isinstance(v, dict) else v) for k, v in p.items() if k != "holes"}
    pt = lambda e: e["mid"] if e else None
    hole, small, line, cross = p.get("hole"), p.get("small_hole"), p.get("line"), p.get("cross_line")
    V = main["name"]
    created: dict[str, dict] = {}

    async def edit(oid, title, action, expect="ok", kind=None):
        def check(rr):
            done = ((rr.body or {}).get("results") or [{}])[-1] if isinstance(rr.body, dict) else {}
            if kind is None:
                return True, "ok"
            got = done.get("type") == kind or kind in json.dumps(done)
            if got:
                created[oid] = done
            return got, f"SOLIDWORKS answered: {json.dumps(done, ensure_ascii=False)[:300]}"
        return await run.op(s, oid, title, "sw_edit_drawing", {"doc": drawing, "actions": [action]}, expect=expect, check=check)

    await edit("A1", "test note on the copy", {"do": "note", "text": TEST_NOTE, "at": [10.0, H - 12.0]})
    await edit("A2", "model-associated dimensions (InsertModelAnnotations) in the main view", {"do": "dimensions", "view": V})
    if line:
        await edit("A3", "reference dimension: length of an outline edge", {"do": "dimension", "view": V, "kind": "linear",
                                                                             "edges": [pt(line)], "at": [(o[0] + o[2]) / 2, o[3] + 10]}, kind="dimension")
    else:
        run.skip(s, "A3", "reference dimension", "no outline line found on the face nearest the viewer")
    if hole:
        await edit("A4", "diameter dimension on a hole", {"do": "dimension", "view": V, "kind": "diameter", "edges": [pt(hole)]}, kind="dimension")
        await edit("A5", "radius dimension on a hole", {"do": "dimension", "view": V, "kind": "radius", "edges": [pt(small)]}, kind="dimension")
        await edit("A6", "hole callout", {"do": "hole_callout", "view": V, "edge": pt(hole), "offset": [14, 10]}, kind="dimension")
        await edit("A7", "centre mark", {"do": "centre_mark", "view": V, "edge": pt(small), "style": "single"})
    else:
        for oid in ("A4", "A5", "A6", "A7"):
            run.skip(s, oid, "hole-based operation", "no hole circle on the face nearest the viewer")
    if cross and p.get("holes"):
        ords = [pt(cross)] + [pt(h) for h in p["holes"][:3]]
        await edit("A8", "ordinate dimensions (zero, then holes)", {"do": "ordinate", "view": V, "edges": ords, "at": [(o[0] + o[2]) / 2, o[1] - 12],
                                                                    "direction": p.get("line_runs", "horizontal")})
    else:
        run.skip(s, "A8", "ordinate dimensions", "no zero edge or holes found")
    cyl = p.get("cylinder")
    if side and cyl:
        await edit("A9", "centre line on a hole seen from the side", {"do": "centre_line", "view": side["name"], "face": cyl["point"]})
    else:
        run.skip(s, "A9", "centre line", "no side view or no cylindrical face")
    ref_dim = (created.get("A3") or {}).get("dimension")
    dia_dim = (created.get("A4") or {}).get("dimension")
    if ref_dim:
        await edit("A10", "bilateral tolerance on the drawing's reference dimension", {
            "do": "tolerance", "dimension": ref_dim, "type": "bilateral", "lower": -0.1, "upper": 0.1, "confirmed_by": TEST})
        await edit("A11", "limit dimension on the reference dimension", {
            "do": "tolerance", "dimension": ref_dim, "type": "limit", "lower": -0.05, "upper": 0.05, "confirmed_by": TEST})
    else:
        run.skip(s, "A10", "tolerance on a reference dimension", "the reference dimension was not made (A3)")
    if dia_dim:
        await edit("A12", "fit H7 on the drawing's diameter dimension", {"do": "tolerance", "dimension": dia_dim, "type": "fit",
                                                                       "hole_fit": "H7", "confirmed_by": TEST})
    else:
        run.skip(s, "A12", "fit on a diameter", "the diameter dimension was not made (A4)")
    # the guard: a model dimension's tolerance lives in the part, so it must be refused without model_change
    after = await run.call("sw_get_drawing", {"doc": drawing, "annotations": True})
    views = {v.get("name") for v in (after.body or {}).get("views") or []}
    model_dim = next((a.get("dimension") for a in _annotations(after.body or {}) if a.get("type") == "dimension" and a.get("dimension")
                      and not any(str(a["dimension"]).lower().endswith("@" + str(v).lower()) for v in views)), None)
    if model_dim:
        await edit("A13", "GUARD: tolerance on a model dimension without model_change is refused", {
            "do": "tolerance", "dimension": model_dim, "type": "bilateral", "lower": -0.1, "upper": 0.1, "confirmed_by": TEST}, expect="refused")
        st = await run.call("sw_status", {})
        docs = ((st.body or {}).get("docs") or []) if isinstance(st.body, dict) else []
        dirty = [d for d in docs if _norm(str(d.get("saved_as") or d.get("doc") or "")) == _norm(part) and d.get("unsaved")]
        if not any(_norm(str(d.get("saved_as") or d.get("doc") or "")) == _norm(part) for d in docs):
            dirty = [{"note": "the copied part is not among the open documents: the check could not be made"}]
        run.ops.append({"step": s, "id": "A13b", "title": "GUARD: the copied part has no unsaved change after A13", "executed": True,
                        "outcome": "guard held" if not dirty else "GUARD FAILED", "result": _brief(docs, 800)})
    else:
        run.skip(s, "A13", "tolerance guard", "no model dimension on the drawing (A2 inserted none)")
    if line:
        await edit("A14", "surface texture symbol", {"do": "surface_finish", "view": V, "edge": pt(line), "symbol": "machining_required",
                                                     "roughness_max": "3.2", "confirmed_by": TEST})
        await edit("A15", "datum feature symbol A", {"do": "datum", "view": V, "edge": pt(cross or line), "label": "A", "confirmed_by": TEST})
    if hole:
        await edit("A16", "GD&T position frame", {"do": "gtol", "view": V, "edge": pt(hole), "confirmed_by": TEST,
                                                  "frames": [{"symbol": "position", "tolerance": "0.1", "diameter": True, "material_condition": "M", "datums": ["A"]}]})
    if line:
        await edit("A17", "weld symbol (fillet, test value) on the copy", {"do": "weld_symbol", "view": V, "edge": pt(line), "symbol": "fillet",
                                                                            "size": "5", "side": "arrow", "confirmed_by": TEST})
    await edit("A18", "revision table", {"do": "revision_table", "at": [W - 10, H - 10]})
    if cross:
        await edit("A19", "hole table", {"do": "hole_table", "view": V, "origin": pt(cross), "face": [*pt(cross)[:2], p["face_level_mm"]] if p.get("axis") == "z" else pt(cross),
                                         "at": [12.0, H - 25.0]})
    await edit("A20", "cut-list table on a part that is not a weldment (must be refused)", {"do": "cut_list", "view": V, "at": [W - 10, H - 60]},
               expect="refused")
    if ref_dim:
        before = next((a for a in _annotations(after.body or {}) if a.get("dimension") == ref_dim), None)
        if before and before.get("at") and before.get("name"):
            to = [before["at"][0] + 15, before["at"][1]]

            def moved(rr):
                d = (rr.body.get("results") or [{}])[-1]
                at = d.get("at") or [None, None]
                return (at[0] is not None and abs(at[0] - to[0]) < 0.5 and d.get("value") == before.get("value"),
                        f"moved to {at}, value {d.get('value')} (was {before.get('value')})")
            await run.op(s, "A21", "move an annotation (position only, value unchanged)", "sw_edit_drawing",
                         {"doc": drawing, "actions": [{"do": "move_annotation", "name": before["name"], "to": to}]}, check=moved)
    final = await run.op(s, "A22", "read every annotation back", "sw_get_drawing", {"doc": drawing, "annotations": True},
                         check=lambda rr: (bool(_annotations(rr.body or {})), f"{len(_annotations(rr.body or {}))} annotations, "
                                                                             f"{len(_tables(rr.body or {}))} tables"))
    if final and not final.is_error:
        (run.out / "annotations-after.json").write_text(json.dumps(final.body, indent=1, ensure_ascii=False), encoding="utf-8")
    await run.op(s, "A23", "screenshot of the copied drawing", "sw_preview", {"doc": drawing, "screenshot": True, "width": 1600, "height": 1100})


async def workflow(run: Run, part: str) -> None:
    s = "7 machining workflow"
    await run.op(s, "W1", "analyse the model (features, discipline, what is confirmed)", "sw_drafting_analyse", {"doc": part, "detail": True})
    pl = await run.op(s, "W2", "plan: strategy, views, sections, dimensions, callouts", "sw_drafting_plan", {"doc": part, "standard": "AS1100"})
    plan = (pl.body if pl and not pl.is_error else {}) or {}
    run.facts["plan"] = {k: plan.get(k) for k in ("plan_id", "sheet", "scale", "views", "omitted_views", "sections", "details", "questions")}
    run.facts["plan_annotations"] = (plan.get("execution") or {}).get("annotations")
    if not plan.get("plan_id"):
        run.skip(s, "W3", "build", "no plan")
        return
    b = await run.op(s, "W3", "build the drawing (views, section, model dimensions, callouts, layout, QA, PDF)", "sw_drafting_build",
                     {"plan_id": plan["plan_id"], "overwrite": False, "export": ["pdf"]})
    built = (b.body if b and not b.is_error else {}) or {}
    ddoc = built.get("drawing")
    run.facts["built_drawing"] = ddoc
    if not ddoc:
        return
    if built.get("exports", {}).get("pdf"):
        run.save_download(built["exports"]["pdf"], "W3-build.pdf")
    await run.op(s, "W4", "check the drawing against the plan, layout correction", "sw_drafting_check",
                 {"doc": ddoc, "plan_id": plan["plan_id"], "correct_layout": True})
    await run.op(s, "W5", "save the native drawing", "sw_save", {"doc": ddoc})
    await run.op(s, "W6", "close and reopen the drawing from disk", "sw_open_document", {"path": ddoc, "reopen": True},
                 check=lambda rr: (bool((rr.body or {}).get("reopened")), json.dumps((rr.body or {}).get("reopened"))))
    await run.op(s, "W7", "read the reopened drawing", "sw_get_drawing", {"doc": ddoc, "annotations": True},
                 check=lambda rr: (len((rr.body or {}).get("views") or []) >= 2, f"{len((rr.body or {}).get('views') or [])} views after reopening"))
    e = await run.op(s, "W8", "export PDF", "sw_export", {"format": "pdf", "doc": ddoc})
    if e and not e.is_error:
        name = run.save_download(e.body, "W8-drawing.pdf")
        run.ops[-1]["evidence"] = [name] if name else []
    await run.op(s, "W9", "screenshot of the built drawing", "sw_preview", {"doc": ddoc, "screenshot": True, "width": 1600, "height": 1100})


async def fabrication(run: Run, weldment: str) -> None:
    s = "9 fabrication smoke test"
    await run.op(s, "F1", "open the weldment copy", "sw_open_document", {"path": weldment})
    r = await run.op(s, "F2", "weldment details: members, cut list, lengths, material", "sw_get_document", {"doc": weldment, "details": True},
                     check=lambda rr: (bool(((rr.body or {}).get("details") or {}).get("cut_list")), "cut list read" if ((rr.body or {}).get("details") or {}).get("cut_list") else "no cut list"))
    run.facts["weldment_cut_list"] = (((r.body if r else {}) or {}).get("details") or {}).get("cut_list") if r and isinstance(r.body, dict) else None
    await run.op(s, "F3", "analyse the weldment", "sw_drafting_analyse", {"doc": weldment})
    d = await run.op(s, "F4", "a drawing of the weldment copy", "sw_create_drawing", {"doc": weldment, "dimensions": False, "overwrite": False})
    ddoc = (d.body or {}).get("doc") if d and not d.is_error else None
    if not ddoc:
        return
    rd = await run.call("sw_get_drawing", {"doc": ddoc})
    main, _ = main_and_side(rd.body if isinstance(rd.body, dict) else {})
    sheet = (rd.body or {}).get("sheet") or {} if isinstance(rd.body, dict) else {}
    if main:
        await run.op(s, "F5", "cut-list table", "sw_edit_drawing", {"doc": ddoc, "actions": [{"do": "cut_list", "view": main["name"],
                                                                                               "at": [float(sheet.get("width_mm", 420)) - 10, float(sheet.get("height_mm", 297)) - 10]}]})
        topo = await run.call("sw_body_topology", {"doc": weldment, "kind": "edges", "limit": 500})
        p = pick(topo.body if isinstance(topo.body, dict) else {}, orientation(main))
        if p.get("line"):
            await run.op(s, "F6", "weld symbol with test values (no weld specification is implied)", "sw_edit_drawing", {"doc": ddoc, "actions": [
                {"do": "weld_symbol", "view": main["name"], "edge": p["line"]["mid"], "symbol": "fillet", "size": "5", "side": "arrow", "confirmed_by": TEST}]})
    await run.op(s, "F7", "screenshot of the weldment drawing", "sw_preview", {"doc": ddoc, "screenshot": True, "width": 1600, "height": 1100})


def report_md(run: Run, meta: dict) -> str:
    lines = ["# Phase 2.1 live verification: harness results", "",
             "Each row is what SOLIDWORKS answered. `passed` means the call succeeded and its read-back matched; LIVE VERIFIED "
             "still needs a person to inspect the evidence.", ""]
    for k, v in meta.items():
        lines.append(f"- **{k}**: {v}")
    if run.facts.get("stopped"):
        lines += ["", f"**Stopped:** {run.facts['stopped']}"]
    lines += ["", "| Step | Id | Operation | Outcome | SOLIDWORKS message / read-back | Evidence |", "| --- | --- | --- | --- | --- | --- |"]
    for o in run.ops:
        msg = (o.get("error") or o.get("readback") or "").replace("|", "/").replace("\n", " ")[:240]
        lines.append(f"| {o['step']} | {o['id']} | {o['title']} | {o['outcome']} | {msg} | {', '.join(o.get('evidence') or [])} |")
    if run.facts.get("mass"):
        lines += ["", "## Mass and density", "", "```json", json.dumps(run.facts["mass"], indent=1, ensure_ascii=False), "```"]
    return "\n".join(lines) + "\n"


async def run_all(call: Call, out: Path, part: str, drawing: str, originals: list[str], weldment: str | None = None,
                  steps: set[str] | None = None, fetch: Callable[[str], bytes] | None = None, meta: dict | None = None,
                  exists: Callable[[str], bool] = os.path.exists, hasher: Callable[[str], str] = sha256) -> dict:
    run = Run(call, out, fetch)
    problems = check_paths(part, drawing, originals, exists)
    if weldment and not exists(weldment):
        problems.append(f"no such file: {weldment}")
    meta = dict(meta or {})
    if problems:
        run.facts["stopped"] = "Unsafe or missing test files: " + "; ".join(problems)
    else:
        before = {o: hasher(o) for o in originals}
        run.facts["originals_before"] = before
        steps = steps or {"read", "annotations", "workflow", "fabrication"}
        if await preflight(run, part, drawing):
            topo = await read_model(run, part) if "read" in steps or "annotations" in steps else {}
            if "annotations" in steps:
                await annotate(run, part, drawing, topo)
            if "workflow" in steps:
                await workflow(run, part)
            if "fabrication" in steps and weldment:
                await fabrication(run, weldment)
            elif "fabrication" in steps:
                run.skip("9 fabrication smoke test", "F*", "weldment operations", "no --weldment copy given")
        after = {o: hasher(o) for o in originals}
        run.facts["originals_after"] = after
        run.facts["originals_unchanged"] = after == before
        if after != before:
            run.facts["ORIGINALS_CHANGED"] = [o for o in originals if before[o] != after[o]]
    result = {"meta": meta, "facts": run.facts, "operations": run.ops,
              "summary": {k: sum(1 for o in run.ops if o["outcome"] == k) for k in ("passed", "failed", "guard held", "GUARD FAILED", "not run")}}
    (out / "results.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "results.md").write_text(report_md(run, meta), encoding="utf-8")
    return result


# ----------------------------------------------------------------------------------------------- MCP over HTTP

async def _http_main(a) -> int:
    import anyio  # noqa: F401  (the MCP client's own dependency)
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(a.server) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            init = await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]

            async def call(name: str, args: dict) -> Reply:
                r = await session.call_tool(name, args)
                body: Any = None
                images = []
                for c in r.content:
                    if getattr(c, "type", None) == "text" and body is None:
                        try:
                            body = json.loads(c.text)
                        except ValueError:
                            body = {"error": c.text} if r.is_error else {"text": c.text}
                    elif getattr(c, "type", None) == "image":
                        images.append(base64.b64decode(c.data))
                return Reply(bool(r.is_error), body if body is not None else {}, images)

            def fetch(url: str) -> bytes:
                if check_server(url):
                    raise RuntimeError("download address is not on this computer")
                return httpx.get(url, timeout=120).content

            git = os.popen("git rev-parse --short HEAD").read().strip() if Path(".git").exists() or Path("../.git").exists() or Path("../../.git").exists() else None
            meta = {"server": a.server, "server_name": init.server_info.name, "tools": len(tools),
                    "drafting_tools": sorted(t for t in tools if t.startswith("sw_drafting_")), "commit": git,
                    "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "part": a.part, "drawing": a.drawing,
                    "weldment": a.weldment}
            res = await run_all(call, Path(a.out), a.part, a.drawing, a.original, a.weldment,
                                set(a.steps.split(",")) if a.steps else None, fetch, meta)
    s = res["summary"]
    print(json.dumps(s))
    print(f"Results: {Path(a.out) / 'results.md'}")
    if res["facts"].get("stopped"):
        print("Stopped: " + res["facts"]["stopped"])
    if res["facts"].get("ORIGINALS_CHANGED"):
        print("ORIGINAL FILES CHANGED: " + ", ".join(res["facts"]["ORIGINALS_CHANGED"]))
        return 3
    return 0 if not s.get("failed") and not s.get("GUARD FAILED") and not res["facts"].get("stopped") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--server", default="http://127.0.0.1:8000/mcp")
    ap.add_argument("--part", required=True, help="the copied part (Pack and Go copy)")
    ap.add_argument("--drawing", required=True, help="the copied drawing, showing the copied part")
    ap.add_argument("--original", action="append", default=[], help="an original file (hashed before and after; repeat)")
    ap.add_argument("--weldment", help="a copied weldment part for the fabrication smoke test")
    ap.add_argument("--steps", help="comma list of read,annotations,workflow,fabrication (default all)")
    ap.add_argument("--out", default=str(Path.home() / "Documents" / "BIZOMAT CAD" / "Projects" / "phase21-test" / "evidence"))
    a = ap.parse_args(argv)
    bad = check_server(a.server)
    if bad:
        print(bad)
        return 2
    import anyio
    return anyio.run(_http_main, a)


if __name__ == "__main__":
    sys.exit(main())
