"""Module I: the drawing quality report.

Deterministic checks of a real drawing (sw_get_drawing), against the engineering model and, when there is one, the
drawing plan. Findings have a category (model, views, dimensions, annotations, engineering, presentation,
document) and a severity:

  blocker  stops release: engineering information missing or wrong (material, general tolerance, threads, welds,
           rebuild errors). Listed separately; never corrected automatically.
  major    a checker would reject the drawing (missing section, wrong model, overlapping views)
  minor    a checker would ask for a change (alignment, crowding, missing title-block fields)
  info     worth knowing

The 100-point index deducts per finding within each category's share; blockers do not count in the index but set
`release_blocked`. `manufacturing_ready` is never true from this report: release needs a person's approval.
"""

from __future__ import annotations

from typing import Any

from . import dimensioning, layout, standards

WEIGHTS = {"model": 10, "views": 20, "dimensions": 25, "annotations": 10, "engineering": 15, "presentation": 15, "document": 5}
COST = {"major": 6, "minor": 2, "info": 0, "blocker": 0}


def _orient(v: dict) -> str:
    return str(v.get("orientation") or "").strip("*").lower()


def check(drawing: dict, model: dict | None = None, plan: dict | None = None, exports: dict | None = None,
          confirmed: dict | None = None, status: dict | None = None) -> dict[str, Any]:
    confirmed = confirmed or {}
    findings: list[dict] = []

    def add(cat, sev, check_id, msg, **kw):
        findings.append(dict({"category": cat, "severity": sev, "check": check_id, "message": msg}, **kw))

    views = drawing.get("views") or []
    props = drawing.get("properties") or {}
    is_part = not model or model.get("kind") != "assembly"
    sheet = drawing.get("sheet") or {}
    # ---------------------------------------------------------------- model
    models = sorted({str(v.get("model")) for v in views if v.get("model")})
    if plan and plan.get("model", {}).get("doc") and models:
        want = str(plan["model"]["doc"]).lower()
        if not any(m.lower() == want for m in models):
            add("model", "major", "model_link", f"The drawing shows {', '.join(models)}, not the planned model {plan['model']['doc']}.")
    if len(models) > 1:
        add("model", "info", "several_models", f"Views show {len(models)} different models.")
    if model:
        for p in model.get("problems", []):
            if p["kind"] == "rebuild":
                add("model", p["severity"], "rebuild", f"Feature {p['feature']} has a rebuild {p['state']}: {p.get('reason')}.")
            elif p["kind"] == "sketch":
                add("model", "minor", "sketch_definition", f"Sketch {p['sketch']} is {p['state']}: {p['why']}.")
            elif p["kind"] in ("mass", "material"):
                add("engineering", "major", p["kind"], p["why"])
    # ---------------------------------------------------------------- views
    orients = [_orient(v) for v in views]
    types = [str(v.get("type")) for v in views]
    if plan:
        for pv in plan.get("views", []):
            if pv["orientation"] not in orients:
                add("views", "major" if pv["role"] in ("main", "edge", "end") else "minor", "planned_view",
                    f"The planned {pv['orientation']} view ({pv['role']}: {pv['why']}) is not on the drawing.")
        n_sec = sum(1 for t in types if t == "section")
        if n_sec < len(plan.get("sections", [])):
            add("views", "major", "section_missing",
                f"{len(plan['sections']) - n_sec} planned section(s) missing: " + "; ".join(s["why"] for s in plan["sections"][n_sec:]),
                knowledge="K02-002")
        n_det = sum(1 for t in types if t == "detail")
        if n_det < len(plan.get("details", [])):
            add("views", "minor", "detail_missing", f"{len(plan['details']) - n_det} planned detail view(s) missing.", knowledge="K02-003")
    elif model:
        hidden = [h for b in (model.get("recognised") or {}).get("bodies", []) for h in b.get("holes", [])
                  if h["subtype"] in ("counterbore", "countersink", "stepped")]
        if hidden and "section" not in types:
            add("views", "major", "section_missing",
                f"{len(hidden)} counterbored, countersunk or stepped hole(s) and no section view: their depths can only be shown "
                "on hidden lines.", features=[h["id"] for h in hidden], knowledge="K02-002")
    if model and model.get("kind") == "part":
        size = (model.get("overall") or {}).get("size") or []
        if size and sorted(size)[0] <= 0.25 * sorted(size)[1]:
            thin = "xyz"[size.index(sorted(size)[0])]
            edge_views = [v for v in views if _orient(v) in {"x": ("front", "top", "back", "bottom"),
                                                             "y": ("front", "right", "back", "left"),
                                                             "z": ("top", "right", "bottom", "left")}[thin] and v.get("type") == "model"]
            if len(edge_views) >= 2:
                # keep the edge view that carries more dimensions, then the wider one (the long side in projection)
                def _w(v):
                    o = v.get("outline_mm") or [0, 0, 0, 0]
                    return abs(o[2] - o[0])
                dims = sorted(edge_views, key=lambda v: (v.get("dimensions") or 0, _w(v)))
                add("views", "minor", "redundant_view",
                    f"{dims[0]['name']} ({_orient(dims[0])}) shows the plate's thickness again: one edge view is enough; delete it or replace it "
                    "with a section.", view=dims[0]["name"], knowledge="K18-003")
    scale = sheet.get("scale")
    for v in views:
        if v.get("type") in ("model", "projected") and _orient(v) != "isometric" and not v.get("uses_sheet_scale", True):
            add("views", "minor", "view_scale", f"{v['name']} is at {v.get('scale')}, not the sheet scale {scale}: label its scale.", view=v["name"])
    # ---------------------------------------------------------------- dimensions
    ortho = [v for v in views if _orient(v) != "isometric" and v.get("type") in ("model", "projected")]
    if ortho and all((v.get("dimensions") or 0) == 0 for v in ortho):
        add("dimensions", "major", "no_dimensions", "No view carries a dimension: the model's dimensions are not marked for drawing, or were not inserted.")
    main = ortho[0] if ortho else None
    if plan and plan.get("views"):
        mo = plan["views"][0]["orientation"]
        main = next((v for v in ortho if _orient(v) == mo), main)
    if main is not None and (main.get("dimensions") or 0) == 0 and any((v.get("dimensions") or 0) > 0 for v in ortho):
        add("dimensions", "minor", "main_view_bare", f"The main view {main['name']} carries no dimensions; features are dimensioned where they are seen true.")
    if model:
        unique = (model.get("design") or {}).get("dimension_count") or 0
        shown = sum(v.get("dimensions") or 0 for v in views)
        dims_plan = (plan or {}).get("dimensioning") or {}
        if not dims_plan:
            dp = dimensioning.plan(model, [])
            dims_plan = {"redundancy": dp["redundancy"], "missing_in_model": dp["coverage"]["missing"]}
        for r in dims_plan.get("redundancy", []):
            if r["kind"] == "repeated_locations":
                add("dimensions", "minor", "repeated_locations", f"{r['owner']}: {r['advice']}.", knowledge=r.get("knowledge"))
            elif r["kind"] == "pcd_as_offsets":
                add("dimensions", "minor", "pcd_as_offsets", r["advice"] + ".", knowledge=r.get("knowledge"))
            elif r["kind"] == "closed_chain":
                add("dimensions", "minor", "closed_chain", r["advice"] + ".", knowledge=r.get("knowledge"))
        for m in (dims_plan.get("missing_in_model") or [])[:8]:
            add("dimensions", "major", "missing_dimension", f"{m['feature']}: no model dimension for its {m['what']} ({m['value']:g}); add it in "
                "the model's sketch so the drawing stays associative.")
        if unique and shown > 1.6 * unique:
            add("dimensions", "minor", "possible_duplicates", f"{shown} dimensions shown for {unique} in the model: check for duplicates.")
    # ---------------------------------------------------------------- annotations and title block
    prof = standards.profile((plan or {}).get("standard", {}).get("profile") if plan else None)
    for f in prof["required_fields"]:
        if f == "Material" and not is_part:
            continue
        if not str(props.get(f, "")).strip():
            add("annotations", "major", "title_block", f"Title block: {f} is empty.")
    for f in ("DrawnBy", "Date", "Finish"):
        if not str(props.get(f, "")).strip():
            add("annotations", "minor", "title_block", f"Title block: {f} is empty.")
    if plan:
        for t in plan.get("notes_status", {}).get("to_be_confirmed", []):
            pass  # reported under engineering below
    else:
        add("annotations", "info", "notes_unread", "General notes are not read back by the add-in: check them on a screenshot.")
    # ---------------------------------------------------------------- engineering (release blockers)
    material = props.get("Material") or (model or {}).get("overall", {}).get("material") or confirmed.get("material")
    if is_part and not material:
        add("engineering", "blocker", "material", "No material stated (title block or part).", knowledge="K15-002")
    gt = confirmed.get("general_tolerance")
    if not gt and plan:
        gt = next((n for n in plan.get("notes_status", {}).get("confirmed", []) if "GENERAL TOLERANCE" in n), None)
    if is_part and not gt:
        add("engineering", "blocker", "general_tolerance", "The general tolerance is not confirmed.", knowledge="K12-002")
    if model:
        threads = [h["id"] for b in (model.get("recognised") or {}).get("bodies", []) for h in b.get("holes", []) if h.get("possible_thread")]
        cats = (model.get("design") or {}).get("feature_categories") or {}
        if threads and not confirmed.get("threads") and not cats.get("thread"):
            add("engineering", "blocker", "threads", f"Holes {', '.join(threads)} are at tapping-drill size: confirm whether they are threaded "
                "(size, pitch, class, depth).", knowledge="K03-003", features=threads)
        for u in model.get("unknown", []):
            if u["what"] == "welds" and not confirmed.get("welds"):
                add("engineering", "blocker", "welds", "Weld type, size and quality are not specified.", knowledge="K05-001")
    if plan:
        for t in plan.get("dimensioning", {}).get("tolerance_candidates", [])[:6]:
            if not (confirmed.get("fits") or {}).get(t["feature"]):
                add("engineering", "major", "fit_unconfirmed", f"{t['feature']} ({t['what']}): {t['why']}; no fit or tolerance confirmed.",
                    knowledge="K12-001")
    add("engineering", "info", "standards", prof["statement"])
    # ---------------------------------------------------------------- presentation
    lay = layout.evaluate(drawing, (plan or {}).get("projection"))
    findings += lay["findings"]
    # ---------------------------------------------------------------- document
    doc = str(drawing.get("doc") or "")
    if doc and not doc.lower().endswith(".slddrw"):
        add("document", "major", "not_saved", "The drawing has no saved .SLDDRW path.")
    if status and status.get("unsaved"):
        add("document", "minor", "unsaved", "The drawing has unsaved changes.")
    for fmt, res in (exports or {}).items():
        if res.get("error"):
            add("document", "major", "export", f"{fmt.upper()} export failed: {res['error']}")
        else:
            add("document", "info", "export", f"{fmt.upper()} exported ({res.get('size_bytes', '?')} bytes).")
    # ---------------------------------------------------------------- score
    score = 100.0
    lost: dict[str, float] = {}
    for f in findings:
        c = f["category"]
        lost[c] = min(WEIGHTS[c], lost.get(c, 0) + COST[f["severity"]])
    score -= sum(lost.values())
    blockers = [f for f in findings if f["severity"] == "blocker"]
    sev_order = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
    findings.sort(key=lambda f: (sev_order[f["severity"]], f["category"]))
    return {"quality_index": round(score, 1), "out_of": 100,
            "by_category": {c: round(WEIGHTS[c] - lost.get(c, 0), 1) for c in WEIGHTS},
            "release_blocked": bool(blockers), "release_blockers": blockers,
            "counts": {s: sum(1 for f in findings if f["severity"] == s) for s in sev_order},
            "findings": findings, "layout": {"fill": lay["fill"], "corrections": lay["corrections"]},
            "auto_correctable": [f for f in findings if f.get("fix")],
            "manufacturing_ready": False,
            "release": "A person checks and approves the drawing before it is issued; this report never releases it."}
