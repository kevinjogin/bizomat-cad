"""The drafting intelligence tools (opensketch/drafting/): analyse a model, plan a drawing, build it, check it,
look up drafting knowledge and record feedback.

They extend the existing sw_ tools and reuse them for every SOLIDWORKS operation: the model is read with the add-in's
`read` and `geometry` commands, the drawing is made with sw_create_drawing and sw_edit_drawing, read with
`read_drawing`, exported with sw_export. No new SOLIDWORKS API call, no new add-in version needed. The reasoning
(opensketch/drafting) is plain data in and out, so it is the same for every AI model that connects.

Engineering-critical content (tolerances, fits, threads, welds, materials, finishes) is never chosen here: the plan
asks for it, the drawing shows TO BE CONFIRMED until it is given, the check reports it as a release blocker, and the
layout correction only ever moves views.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from . import store
from .drafting import disciplines as dmod
from .drafting import engine, knowledge, layout, learning, qa
from .mcp_server import _who, mcp
from .sw_tools import _COMP, _DEV, _DOC, _SCALE, GEOM_ERRORS, _cad, _device, _geometry, _routed, _run, _text

_ANSWERS = Annotated[dict | None, Field(description=(
    'Answers to the plan\'s questions, only what the designer has confirmed: {"material": "...", "general_tolerance": '
    '"ISO 2768-m", "threads": {"H1": "M6x1-6H, full thread 12"}, "fits": {"H11": "Ø40 H7"}, "surface_finish": "Ra 3.2", '
    '"edge_break": "Break sharp edges 0.3", "welds": "...", "finish": "...", "title_block": {"DrawingNo": "...", '
    '"Revision": "A", "DrawnBy": "..."}, "notes": ["..."], "approve_proposed_notes": true}'))]
_PLAN_ID = Annotated[str, Field(description="The plan_id from sw_drafting_plan")]
ANSWER_KEYS = {"material": str, "general_tolerance": str, "threads": dict, "fits": dict, "surface_finish": str, "edge_break": str,
               "welds": str, "finish": str, "title_block": dict, "notes": list, "approve_proposed_notes": bool}


def _account() -> str | None:
    return store.owner_of(_who())


def _check_answers(answers: dict | None) -> tuple[dict, list[str]]:
    out, problems = {}, []
    for k, v in (answers or {}).items():
        t = ANSWER_KEYS.get(k)
        if t is None:
            problems.append(f"answers: unknown key {k!r} (known: {', '.join(ANSWER_KEYS)})")
        elif not isinstance(v, t):
            problems.append(f"answers.{k} must be {t.__name__}")
        elif t is str and len(v) > 200:
            problems.append(f"answers.{k}: up to 200 characters")
        elif t is dict and (len(v) > 40 or any(len(str(a)) > 60 or len(str(b)) > 200 for a, b in v.items())):
            problems.append(f"answers.{k}: up to 40 entries, keys up to 60 and values up to 200 characters")
        elif t is list and (len(v) > 8 or any(len(str(x)) > 200 for x in v)):
            problems.append(f"answers.{k}: up to 8 lines of up to 200 characters")
        else:
            out[k] = v
    return out, problems


async def _analyse(doc: str | None, component: str | None, drawing: str | None = None,
                   override: list[str] | None = None) -> tuple[dict | None, dict, str | None]:
    """(analysis, meta, error): the model read from SOLIDWORKS (feature tree, numbers, geometry) and analysed."""
    read, _, err = await _run("read", {"doc": doc, "component": component}, timeout=180)
    if err:
        return None, {}, err
    numbers, _, err2 = await _run("read", {"doc": doc, "component": component, "numbers": True}, timeout=180)
    if err2:
        numbers = {}
    props = None
    if drawing:
        dr, _, err3 = await _run("read_drawing", {"doc": drawing}, timeout=180)
        props = (dr or {}).get("properties") if not err3 else None
    try:
        g = await _geometry(doc, component)
        rec = await _cad(engine.recognise_part, g["doc"]) if g["kind"] == "part" else await _cad(engine.recognise_assembly, g["doc"])
    except GEOM_ERRORS as exc:
        return None, {}, f"Could not read the geometry: {exc}"
    kind = "assembly" if g["kind"] == "assembly" else "part"
    title = (read or {}).get("title") or g.get("title")
    analysis = engine.analyse(kind, title, read, numbers, rec, props, override=override,
                              extra_knowledge=learning.guidelines(_account()))
    meta = {"doc": (read or {}).get("doc") or doc, "title": title, "kind": kind, "update_stamp": (read or {}).get("update_stamp")}
    return analysis, meta, None


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
@_routed
async def sw_drafting_analyse(doc: _DOC = None, component: _COMP = None,
                              drawing: Annotated[str | None, Field(description="An existing drawing of the model: its title-block fields are taken into account")] = None,
                              disciplines: Annotated[list[str] | None, Field(description="Override the discipline classification (ids: " + ", ".join(dmod.LABELS) + ")")] = None,
                              detail: Annotated[bool, Field(description="Include the full recognised features and the engineering model")] = False,
                              device: _DEV = None) -> CallToolResult:
    """Understand a SOLIDWORKS part or assembly as a drafter does, before any drawing: the features recognised from
    its real geometry (holes and their types, patterns and pitch circles, pockets, steps, slots, turned profiles,
    grooves, fillets, chamfers, members, sheet metal, pipe bends, flanges), the SOLIDWORKS design information
    (feature tree, sketch names and states, dimensions, material, mass), the drafting disciplines it needs with the
    evidence for each, how it is made, what is confirmed, what is only inferred and what is unknown, the
    information the designer must give, and the drafting knowledge that applies. Read-only."""
    try:
        ana, meta, err = await _analyse(doc, component, drawing, disciplines)
    except ValueError as exc:
        return _text({"error": str(exc)}, True)
    if err:
        return _text({"error": err}, True)
    out = {"model": meta, **engine.summary(ana)}
    out["reasoning"] = {k: {kk: v.get(kk) for kk in ("operations", "datums", "critical_features", "cut_list", "joints",
                                                       "members", "bolt_groups", "checks", "items") if v.get(kk)}
                        for k, v in ana["reasoning"]["by_discipline"].items()}
    out["dimensioning"] = {k: ana["dimensioning"][k] for k in ("scheme", "redundancy", "callouts", "tolerance_candidates")}
    out["dimensioning"]["coverage"] = {k: ana["dimensioning"]["coverage"][k] for k in ("coverage", "needed", "found", "missing")}
    if detail:
        out["engineering_model"] = ana["model"]
    out["next"] = "sw_drafting_plan(doc) makes the drawing plan; it lists the questions that affect correctness."
    return _text(out)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
@_routed
async def sw_drafting_plan(doc: _DOC = None, component: _COMP = None,
                           purpose: Annotated[Literal["manufacturing", "fabrication", "assembly", "installation", "inspection", "maintenance",
                                                      "general_arrangement"] | None, Field(description="What the drawing is for; omit to infer it")] = None,
                           standard: Annotated[Literal["AS1100", "ISO", "ASME"], Field(description="Drawing conventions (projection, notes, title block)")] = "AS1100",
                           disciplines: Annotated[list[str] | None, Field(description="Override the discipline classification")] = None,
                           sheet: Annotated[Literal["A4", "A3", "A2", "A1", "A0"] | None, Field(description="Force a sheet size")] = None,
                           scale: Annotated[str | None, Field(description='Force a scale such as "1:2"')] = None,
                           isometric: Annotated[bool | None, Field(description="Force an isometric view on or off; omit to decide by the shape")] = None,
                           answers: _ANSWERS = None, device: _DEV = None) -> CallToolResult:
    """Plan a professional drawing before drawing it: purpose and reader, the drawing package, sheet and preferred
    scale, each view with the reason it is needed (and the views left out, with why), sections through hidden
    features, detail views for small ones, datums, the dimensioning method, dimension coverage and redundancy,
    proposed hole callouts, general notes (confirmed, proposed, TO BE CONFIRMED), title-block fields, and only the
    questions that materially affect correctness. Saved on the server with a plan_id for sw_drafting_build. Nothing
    is changed in SOLIDWORKS."""
    ans, problems = _check_answers(answers)
    if problems:
        return _text({"error": "Nothing was planned.", "input_problems": problems}, True)
    if scale:
        m = _SCALE.match(scale)
        if not m or float(m.group(1)) <= 0 or float(m.group(2)) <= 0:
            return _text({"error": 'scale is "a:b" with two positive numbers, for example "1:2".'}, True)
    try:
        ana, meta, err = await _analyse(doc, component, None, disciplines)
        if err:
            return _text({"error": err}, True)
        pl = engine.plan(ana, doc=meta["doc"], standard=standard, purpose=purpose, sheet=sheet, scale=scale,
                         isometric=isometric, answers=ans)
    except ValueError as exc:
        return _text({"error": str(exc)}, True)
    pl["model"]["update_stamp"] = meta.get("update_stamp")
    pl["answers"] = ans
    try:
        learning.save_plan(_account(), pl, meta.get("update_stamp"))
    except store.StorageError as exc:
        return _text({"error": str(exc)}, True)
    out = dict(pl)
    out["next"] = ("Ask the user the blocking questions (or build a draft: unknowns show as TO BE CONFIRMED); "
                   f"then sw_drafting_build(plan_id=\"{pl['plan_id']}\").")
    return _text(out)


def _main_view(drawing: dict, plan: dict) -> dict | None:
    want = plan["views"][0]["orientation"] if plan.get("views") else "front"
    for v in drawing.get("views") or []:
        if str(v.get("orientation") or "").strip("*").lower() == want:
            return v
    return (drawing.get("views") or [None])[0]


def _section_actions(drawing: dict, plan: dict) -> list[dict]:
    """sw_edit_drawing actions for the planned sections and details, placed in free space beside the main view."""
    main = _main_view(drawing, plan)
    if main is None or not main.get("outline_mm"):
        return []
    o = main["outline_mm"]
    w, h = abs(o[2] - o[0]), abs(o[3] - o[1])
    size = sorted(((plan.get("model") or {}).get("size") or []) or [0])
    s = _scale_value(plan.get("scale"))
    depth = (size[0] * s) if size and size[0] else 0.4 * h
    acts = []
    snapshot = json.loads(json.dumps(drawing))
    for sec in plan.get("sections", []):
        sw_, sh_ = (w, depth) if sec["direction"] == "horizontal" else (depth, h)
        at = layout.free_spot(snapshot, sw_ + 10, sh_ + 10, near=main["name"])
        acts.append({"do": "section", "view": main["name"], "direction": sec["direction"], "through": sec["through"],
                     "label": sec["label"], "place": at})
        snapshot.setdefault("views", []).append({"name": f"Section {sec['label']}", "outline_mm": [at[0] - sw_ / 2, at[1] - sh_ / 2, at[0] + sw_ / 2, at[1] + sh_ / 2]})
    for det in plan.get("details", []):
        k = _scale_value(det["scale"])
        r = det.get("radius_mm", 12)
        size_d = 2 * r * (k / max(s, 1e-6))
        at = layout.free_spot(snapshot, size_d + 10, size_d + 10, near=main["name"])
        acts.append({"do": "detail", "view": main["name"], "through": det["through"], "radius": r, "scale": det["scale"],
                     "label": det["label"], "place": at})
        snapshot.setdefault("views", []).append({"name": f"Detail {det['label']}", "outline_mm": [at[0] - size_d / 2, at[1] - size_d / 2, at[0] + size_d / 2, at[1] + size_d / 2]})
    if plan.get("sections") or plan.get("details"):
        acts.append({"do": "dimensions"})          # the model's remaining dimensions go to the new views (no duplicates)
    acts.append({"do": "centre_marks"})
    if plan["model"].get("kind") == "assembly":
        sheet = drawing.get("sheet") or {}
        acts.append({"do": "bom", "view": main["name"], "at": [float(sheet.get("width_mm", 420)) - 10, float(sheet.get("height_mm", 297)) - 10],
                     "type": "top", "balloons": True})
    acts.append({"do": "arrange_dimensions"})
    return acts


def _scale_value(sc: Any) -> float:
    try:
        a, b = str(sc).split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return 1.0


async def _read_drawing(drawing: str | None) -> tuple[dict | None, str | None]:
    res, _, err = await _run("read_drawing", {"doc": drawing}, timeout=180)
    return res, err


async def _correct(drawing_doc: str | None, plan: dict | None, rounds: int) -> tuple[dict | None, list[dict], str | None]:
    """Up to `rounds` passes of non-critical layout corrections (view moves only)."""
    from .sw_tools import sw_edit_drawing
    applied: list[dict] = []
    drw, err = await _read_drawing(drawing_doc)
    for _ in range(max(0, rounds)):
        if err or not drw:
            break
        fixes = layout.evaluate(drw, (plan or {}).get("projection"))["corrections"]
        fixes = [f for f in fixes if f.get("do") == "move"][:20]
        if not fixes:
            break
        res = await sw_edit_drawing(actions=fixes, doc=drawing_doc, device=_device())
        body = json.loads(res.content[0].text)
        applied += fixes
        if res.is_error:
            err = body.get("error")
            break
        drw, err = await _read_drawing(drawing_doc)
    return drw, applied, err


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
@_routed
async def sw_drafting_build(plan_id: _PLAN_ID,
                            overwrite: Annotated[bool, Field(description="Replace a drawing of the same name (it is closed first)")] = False,
                            correct_layout: Annotated[bool, Field(description="Fix non-critical layout problems afterwards (view moves only)")] = True,
                            export: Annotated[list[Literal["pdf", "dwg", "dxf"]] | None, Field(description="Export the finished drawing")] = None,
                            device: _DEV = None) -> CallToolResult:
    """Make the planned drawing in SOLIDWORKS with the existing drawing commands: the planned views at the planned
    sheet and scale with the model's own (associative) dimensions, title block and notes; then the planned sections
    and details placed in free space; centre marks; arranged dimensions; a parts list for an assembly. Then it reads
    the drawing back, corrects non-critical layout problems (moves only), checks it (quality index and release
    blockers) and exports what was asked. It never changes the model and never marks the drawing ready for
    manufacture."""
    from .sw_tools import sw_create_drawing, sw_edit_drawing, sw_export
    plan = learning.get_plan(_account(), plan_id)
    if plan is None:
        return _text({"error": f"No plan {plan_id}: make one with sw_drafting_plan."}, True)
    steps: list[dict] = []
    read, _, err = await _run("read", {"doc": plan["model"]["doc"]}, timeout=120)
    if err:
        return _text({"error": err}, True)
    if plan["model"].get("update_stamp") is not None and (read or {}).get("update_stamp") not in (None, plan["model"]["update_stamp"]):
        steps.append({"step": "model check", "note": "the model changed since the plan was made; consider a new plan"})
    plan["model"]["size"] = ((read or {}).get("body") or {}).get("bbox", {}).get("size")
    c = dict(plan["execution"]["create_drawing"])
    res = await sw_create_drawing(doc=c["doc"], sheet=c["sheet"], projection=c["projection"], views=c["views"], scale=c["scale"],
                                  dimensions=True, properties=c.get("properties"), notes=c.get("notes"), centre_marks=True,
                                  overwrite=overwrite, device=_device())
    created = json.loads(res.content[0].text)
    steps.append({"step": "create_drawing", "ok": not res.is_error, "result": {k: created.get(k) for k in ("doc", "sheet", "views", "dimensions", "notes", "error")}})
    if res.is_error:
        return _text({"error": "SOLIDWORKS did not make the drawing.", "steps": steps}, True)
    ddoc = created.get("doc")
    applied: list[dict] = []
    if correct_layout:
        # the base views into their projection places first, then the sections go into the space that is left
        drw, applied, err = await _correct(ddoc, plan, 2)
    else:
        drw, err = await _read_drawing(ddoc)
    if err:
        return _text({"error": err, "steps": steps, "drawing": ddoc}, True)
    acts = _section_actions(drw, plan)
    if acts:
        res = await sw_edit_drawing(actions=acts, doc=ddoc, device=_device())
        body = json.loads(res.content[0].text)
        steps.append({"step": "edit_drawing", "ok": not res.is_error, "actions": [a["do"] for a in acts],
                      "error": body.get("error") if res.is_error else None})
    if correct_layout:
        drw, more, err = await _correct(ddoc, plan, 2)
        applied += more
        steps.append({"step": "layout corrections", "moves": applied, "error": err})
    else:
        drw, err = await _read_drawing(ddoc)
    exports = {}
    for fmt in export or []:
        r = await sw_export(format=fmt, doc=ddoc, device=_device())
        b = json.loads(r.content[0].text)
        exports[fmt] = {"error": b.get("error")} if r.is_error else {k: b.get(k) for k in ("download_url", "size_bytes", "sha256", "expires_at")}
    try:
        ana, _, aerr = await _analyse(plan["model"]["doc"], None)
    except ValueError as exc:
        ana, aerr = None, str(exc)
    if aerr:
        steps.append({"step": "model analysis for the check", "error": aerr})
    report = qa.check(drw or {}, ana["model"] if ana else None, plan=plan, exports=exports, confirmed=plan.get("answers") or {})
    return _text({"drawing": ddoc, "plan_id": plan_id, "steps": steps, "exports": exports, "quality": _brief(report),
                  "next": "Look at it (sw_preview doc=the drawing, screenshot=true). Answer the release blockers, then plan and build again "
                          "with the answers; a person checks and approves before release."})


def _brief(report: dict) -> dict:
    return {k: report[k] for k in ("quality_index", "out_of", "by_category", "release_blocked", "counts", "manufacturing_ready", "release")} | {
        "release_blockers": [f["message"] for f in report["release_blockers"]],
        "findings": [{k: f.get(k) for k in ("severity", "category", "check", "message", "view", "knowledge")} for f in report["findings"]
                     if f["severity"] != "info"][:40]}


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
@_routed
async def sw_drafting_check(doc: Annotated[str | None, Field(description="The drawing (path or window title); omit for the active document")] = None,
                            plan_id: Annotated[str | None, Field(description="Check against this plan as well")] = None,
                            with_model: Annotated[bool, Field(description="Also analyse the model the drawing shows (threads, sections, redundant views, material)")] = True,
                            correct_layout: Annotated[bool, Field(description="Apply non-critical layout corrections (view moves only), then check again")] = False,
                            rounds: Annotated[int, Field(ge=1, le=3)] = 2,
                            answers: _ANSWERS = None, device: _DEV = None) -> CallToolResult:
    """The drawing quality report for a real SOLIDWORKS drawing: model link and rebuild state, views (required,
    sections for hidden features, redundant views, scales), dimensions (presence, duplicates, pattern and pitch-circle
    practice, coverage), title block and notes, engineering release blockers (material, general tolerance, threads,
    welds, fits), presentation (off-sheet, overlaps, title-block clash, crowding, projection order, alignment, use of
    the sheet) and the document (saved, exports). A 100-point quality index, release blockers listed separately.
    With correct_layout it moves views to fix layout problems, never anything else."""
    ans, problems = _check_answers(answers)
    if problems:
        return _text({"error": "Nothing was checked.", "input_problems": problems}, True)
    plan = learning.get_plan(_account(), plan_id) if plan_id else None
    if plan_id and plan is None:
        return _text({"error": f"No plan {plan_id}."}, True)
    applied: list[dict] = []
    if correct_layout:
        drw, applied, err = await _correct(doc, plan, rounds)
    else:
        drw, err = await _read_drawing(doc)
    if err:
        return _text({"error": err}, True)
    ana = None
    note = None
    if with_model:
        model_path = next((v.get("model") for v in (drw or {}).get("views") or [] if v.get("model")), None)
        if model_path:
            try:
                ana, _, aerr = await _analyse(model_path, None)
                note = aerr
            except ValueError as exc:
                note = str(exc)
    confirmed = dict((plan or {}).get("answers") or {})
    confirmed.update(ans)
    report = qa.check(drw or {}, ana["model"] if ana else None, plan=plan, confirmed=confirmed)
    out = {"drawing": (drw or {}).get("doc"), **report}
    if applied:
        out["layout_moves_applied"] = applied
    if note:
        out["model_note"] = f"The model could not be analysed: {note}"
    return _text(out)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
async def sw_drafting_knowledge(query: Annotated[str, Field(description="What you want to know, e.g. 'counterbore depth in a section' or 'pitch circle'")],
                                discipline: Annotated[str | None, Field(description="Favour entries for this discipline id")] = None,
                                category: Annotated[str | None, Field(description='Knowledge category "01".."18"')] = None,
                                include_suggestions: Annotated[bool, Field(description="Also return suggestions that are not yet verified")] = False,
                                limit: Annotated[int, Field(ge=1, le=20)] = 6) -> CallToolResult:
    """Search the BIZOMAT drafting knowledge base: structured entries (concept, explanation, practice, example, correct
    approach, common mistake, standards referenced, source, level and validation status) and the account's own company
    guidelines. Each result says why it matched. Use it to explain a drafting decision and cite where it comes from;
    shipped entries are recommended practice, not verified standard text."""
    if discipline and discipline not in dmod.LABELS:
        return _text({"error": f"discipline is one of {', '.join(dmod.LABELS)}"}, True)
    res = knowledge.search(query, discipline=discipline, category=category, extra=learning.guidelines(_account()),
                           include_suggestions=include_suggestions, limit=limit)
    return _text({"query": query, "results": res, "knowledge_base": knowledge.summary(),
                  "note": "Shipped entries are BIZOMAT's recommended practice; no standard text is reproduced. Verify against "
                          "the licensed standard before treating any entry as a requirement."})


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
async def sw_drafting_feedback(kind: Annotated[Literal["accept", "reject", "edit_dimensions", "change_views", "move_annotation", "change_notes",
                                                       "expert_approve", "expert_reject", "guideline", "answers"],
                                               Field(description="What happened")],
                               plan_id: Annotated[str | None, Field(description="The plan the feedback is about")] = None,
                               drawing: Annotated[str | None, Field(description="The drawing it is about")] = None,
                               target: Annotated[str | None, Field(description="The view, dimension, note or feature concerned")] = None,
                               before: Annotated[Any, Field(description="What the plan or drawing had")] = None,
                               after: Annotated[Any, Field(description="What the person changed it to")] = None,
                               comment: Annotated[str | None, Field(description="Why (in the person's words)")] = None,
                               reviewer: Annotated[Literal["user", "expert"], Field(description="expert only when a qualified reviewer gave it")] = "user",
                               retain: Annotated[bool, Field(description="Keep the plan with it as a training example (the person's choice; default no)")] = False,
                               guideline: Annotated[dict | None, Field(description='kind=guideline: {"topic": "...", "practice": "...", "concept": "...", '
                                                                                   '"disciplines": ["..."], "category": "15", "explanation": "...", "mistake": "..."}')] = None
                               ) -> CallToolResult:
    """Record what the person or a reviewer did with a drafting recommendation (accepted, rejected, edited dimensions,
    changed views, moved annotations, changed notes, expert approval or rejection), or add a company drafting
    guideline. Kept on this server in the account's own store, never sent elsewhere and never used to train an
    external model. Expert-approved examples are kept apart from unverified user edits; a guideline from an expert is
    company practice, from a user a suggestion awaiting verification."""
    try:
        if kind == "guideline":
            if not guideline or not guideline.get("topic") or not guideline.get("practice"):
                return _text({"error": "guideline needs at least topic and practice."}, True)
            g = dict(guideline)
            g.setdefault("concept", g["topic"])
            entry = learning.add_guideline(_account(), g, reviewer)
            return _text({"guideline": entry, "status": entry["level"]})
        if comment and len(comment) > 2000:
            return _text({"error": "comment: up to 2000 characters."}, True)
        rec = learning.record_feedback(_account(), kind, plan_id=plan_id, drawing=drawing, target=target, before=before, after=after,
                                       comment=comment, reviewer=reviewer, retain=retain)
    except (ValueError, store.StorageError) as exc:
        return _text({"error": str(exc)}, True)
    rec["stats"] = learning.stats(_account())
    return _text(rec)
