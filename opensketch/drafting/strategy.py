"""Module E: the drawing strategy. A structured plan made before anything is drawn.

The plan says why each view, section and detail is there (the information it carries), which sheet and preferred
scale fit, which notes are confirmed, proposed or still to be confirmed, which title-block fields are missing, and
which questions materially affect correctness. It ends with the exact calls the build step makes through the
existing drawing commands (create_drawing, then edit_drawing actions placed from the real view outlines).

SOLIDWORKS' standard views (model coordinates): front looks along -Z (screen x = X, y = Y), top looks down -Y
(screen x = X, y = -Z), right looks along -X (screen x = -Z, y = Y).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from . import standards

SHEETS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0), "A0": (1189.0, 841.0)}
SCALES = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100)]
GAP = 25.0          # sheet mm between views: room for dimensions
TITLE_BAND = 65.0   # the add-in's layout keeps the bottom 65 mm for the title block
VIEW_ALONG = {"z": "front", "y": "top", "x": "right"}
SCREEN = {"front": (0, 1), "top": (0, 2), "right": (2, 1), "bottom": (0, 2), "left": (2, 1), "back": (0, 1)}


def view_size(size: list[float], orientation: str) -> tuple[float, float]:
    i, j = SCREEN[orientation]
    return size[i], size[j]


def _screen_xy(p: list[float], orientation: str) -> tuple[float, float]:
    """A model point's position across a standard view (up to the view's own offset)."""
    if orientation == "front":
        return p[0], p[1]
    if orientation == "top":
        return p[0], -p[2]
    if orientation == "right":
        return -p[2], p[1]
    return p[0], p[1]


def _bodies(model: dict) -> list[dict]:
    return (model.get("recognised") or {}).get("bodies", [])


def choose_views(model: dict, disciplines: list[str], isometric: bool | None = None) -> tuple[list[dict], list[str]]:
    """The orthographic views (with the reason for each) and the views deliberately left out (with why)."""
    size = (model.get("overall") or {}).get("size") or [1, 1, 1]
    omitted: list[str] = []
    views: list[dict] = []
    bodies = _bodies(model)
    kind = model.get("kind")
    if kind == "assembly":
        views = [{"orientation": "front", "role": "main", "why": "the assembly in its working position", "dimensions": "overall and interface sizes only"},
                 {"orientation": "top", "role": "projection", "why": "positions of components in plan", "dimensions": "interfaces"},
                 {"orientation": "right", "role": "projection", "why": "depth and side interfaces", "dimensions": "interfaces"}]
        iso = True if isometric is None else isometric
        if iso:
            views.append({"orientation": "isometric", "role": "pictorial", "why": "shows how the parts go together; carries the balloons if clearer", "dimensions": "none"})
        return views, omitted
    tp = next((b["turned_profile"] for b in bodies if b.get("turned_profile")), None)
    if tp:
        ax = tp["axis"] if isinstance(tp["axis"], str) else "x"
        main = {"x": "front", "z": "right", "y": "front"}[ax]
        why = "the side view of the turned profile, axis horizontal: every diameter and length is seen true"
        if ax == "y":
            why = "the side view of the turned profile (the model's axis is vertical: a drafter would draw it horizontal; reorienting needs a custom model view)"
        views.append({"orientation": main, "role": "main", "why": why, "dimensions": "diameters, lengths, grooves, chamfers"})
        along = VIEW_ALONG[ax]
        off_axis = [h for b in bodies for h in b["holes"] if isinstance(h["axis"], str) and h["axis"] == ax]
        flats = [p for b in bodies for p in b["pockets"] + b["steps"] + b["slots"]]
        if off_axis or flats:
            views.append({"orientation": along, "role": "end", "why": f"end view: {len(off_axis)} hole(s) off the axis" + (" and flats or keyways" if flats else "") + " seen true shape",
                          "dimensions": "pitch circle and angular positions"})
        else:
            omitted.append(f"{along} (end view): a plain turned part shows only circles end-on; diameters are given in the side view")
        iso = False if isometric is None else isometric
        if not iso:
            omitted.append("isometric: a turned part is clear from its side view")
        else:
            views.append({"orientation": "isometric", "role": "pictorial", "why": "requested", "dimensions": "none"})
        return views, omitted
    dirs = {}
    weight: dict[str, float] = {}
    small = max(1e-6, sorted(size)[0])
    for b in bodies:
        for k, v in (b.get("directions") or {}).items():
            dirs.setdefault(k, []).extend(v)
        for h in b["holes"]:
            if isinstance(h["axis"], str):
                d = max([h["diameter"]] + [s["diameter"] for s in h["segments"]])
                weight[h["axis"]] = weight.get(h["axis"], 0.0) + 1.0 + 10.0 * (d / small) ** 2 + (1.0 if h["subtype"] in ("counterbore", "stepped") else 0.0)
        for p in b["pockets"] + b["steps"] + b["slots"] + b["bosses"]:
            a = (p.get("normal") or p.get("axis") or "")
            if isinstance(a, str) and a:
                weight[a.lstrip("-")] = weight.get(a.lstrip("-"), 0.0) + 2.0
    order = sorted(range(3), key=lambda i: size[i])
    thin = "xyz"[order[0]]
    plate = size[order[0]] <= 0.25 * size[order[1]]
    multi = len(bodies) > 1
    if plate or multi:
        main_ax = thin
    else:
        main_ax = max("xyz", key=lambda a: (round(weight.get(a, 0.0), 3), _area(size, a)))
    main = VIEW_ALONG[main_ax]
    views.append({"orientation": main, "role": "main",
                  "why": ("plan view: the plate's outline and hole pattern seen true" if plate and not multi else
                          "plan of the assembly of members" if multi else
                          f"the main functional features seen true shape ({len(dirs.get(main_ax, []))} feature(s), the largest ones first)"),
                  "dimensions": "outline, positions of features seen true"})
    others = [a for a in "xyz" if a != main_ax]
    if plate and not multi:
        # the edge view along the shorter side shows the longer side and the thickness
        edge_ax = min(others, key=lambda a: size["xyz".index(a)])
        views.append({"orientation": VIEW_ALONG[edge_ax], "role": "edge", "why": "edge view: the thickness and any edge features", "dimensions": "thickness"})
        rest = [a for a in others if a != edge_ax]
        for a in rest:
            if dirs.get(a):
                views.append({"orientation": VIEW_ALONG[a], "role": "projection", "why": f"{len(dirs[a])} feature(s) seen true only from this side", "dimensions": "those features"})
            else:
                omitted.append(f"{VIEW_ALONG[a]}: it would show the thickness again")
    else:
        for a in others:
            if dirs.get(a):
                views.append({"orientation": VIEW_ALONG[a], "role": "projection", "why": f"{len(dirs[a])} feature(s) seen true from this side", "dimensions": "those features"})
        if len(views) == 1:
            views.append({"orientation": VIEW_ALONG[min(others, key=lambda a: size['xyz'.index(a)])], "role": "projection",
                          "why": "shows the depth of the part and its features", "dimensions": "depths and heights"})
        for a in others:
            if VIEW_ALONG[a] not in [v["orientation"] for v in views]:
                omitted.append(f"{VIEW_ALONG[a]}: no feature is seen better from this side")
    complex_shape = len([a for a in "xyz" if dirs.get(a)]) >= 3
    iso = (multi or complex_shape or "sheet_metal" in disciplines or "weldment" in disciplines) if isometric is None else isometric
    if iso:
        views.append({"orientation": "isometric", "role": "pictorial",
                      "why": "the shape is easier to read in 3D (members, bends or features on three sides); undimensioned", "dimensions": "none"})
    else:
        omitted.append("isometric: the orthographic views are clear on their own; it would carry no information")
    return views, omitted


def _area(size, axis: str) -> float:
    i = "xyz".index(axis)
    a, b = [size[k] for k in range(3) if k != i]
    return a * b


def choose_sections(model: dict, views: list[dict], applies: list[str] | None = None) -> list[dict]:
    """Sections through features that outside views show only as hidden lines: counterbores, countersinks, blind
    and stepped holes, pockets. One cutting line through as many of them as possible; a second only if needed.
    Fabrication drawings (piping, weldments, structural) and assemblies are not sectioned here: their parts are."""
    out = []
    if model.get("kind") == "assembly" or any(a in (applies or []) for a in ("piping", "weldment", "structural_steel")):
        return out
    bodies = _bodies(model)
    main = next((v for v in views if v["role"] == "main"), None)
    if main is None or main["orientation"] == "isometric":
        return out
    o = main["orientation"]
    along = {"front": "z", "top": "y", "right": "x"}.get(o)
    hidden = []
    for b in bodies:
        for h in b["holes"]:
            # a plain blind hole's depth goes in its callout; counterbores, countersinks and stepped bores need a section
            if h["subtype"] in ("counterbore", "countersink", "stepped") and h.get("axis") == along:
                hidden.append((h["id"], h["subtype"], h["position"], _sig(h)))
        for p in b["pockets"]:
            if p["normal"].lstrip("-") == along and p.get("at"):
                hidden.append((p["id"], "pocket", p["at"], ("pocket", p["depth"], tuple(p.get("extent", [])))))
        tp = b.get("turned_profile")
        if tp:
            for h in b["holes"]:
                if h.get("axis") != tp["axis"]:
                    hidden.append((h["id"], "cross hole", h["position"], _sig(h)))
            for h in b["holes"]:
                if h.get("axis") == tp["axis"] and h["position"] and abs(h["position"][1]) < 0.01 and abs(h["position"][2]) < 0.01:
                    hidden.append((h["id"], "axial bore", h["position"], _sig(h)))
    if not hidden:
        return out
    labels = iter("ABCDEFGH")
    remaining = hidden[:]
    while remaining and len(out) < 2:
        best = None
        for direction, idx in (("horizontal", 1), ("vertical", 0)):
            lines: dict[float, list] = {}
            for f in remaining:
                c = round(_screen_xy(f[2], o)[idx], 1)
                lines.setdefault(c, []).append(f)
            for c, fs in lines.items():
                kinds = len({f[1] for f in fs})
                key = (len(fs) + 0.5 * kinds, direction == "horizontal")
                if best is None or key > best[0]:
                    best = (key, direction, fs)
        _, direction, fs = best
        if out and len(fs) < 1:
            break
        out.append({"label": next(labels), "in_view": "main", "direction": direction, "through": fs[0][2],
                    "features": [f[0] for f in fs],
                    "why": "shows " + ", ".join(sorted({f[1] for f in fs})) + " true, so depths are dimensioned on visible edges, not hidden lines"})
        covered = {f[3] for f in fs}
        # identical features need one representative in a section, not one section each
        remaining = [f for f in remaining if f not in fs and f[3] not in covered]
        if remaining and not any(f[1] in ("counterbore", "countersink", "stepped", "pocket") for f in remaining):
            break
    if remaining:
        out[-1]["not_covered"] = [f[0] for f in remaining]
    return out


def _sig(h: dict) -> tuple:
    return (h["subtype"], h["diameter"], h.get("depth"), (h.get("counterbore") or {}).get("diameter"),
            (h.get("counterbore") or {}).get("depth"), (h.get("countersink") or {}).get("diameter"),
            tuple(x["diameter"] for x in h.get("segments", [])))


def choose_details(model: dict, scale: float) -> list[dict]:
    """Detail views for features too small to dimension at the sheet scale (grooves, undercuts)."""
    out = []
    labels = iter("PQRSTUVW")
    for b in _bodies(model):
        tp = b.get("turned_profile")
        if not tp:
            continue
        ax = tp["axis"] if isinstance(tp["axis"], str) else "x"
        i = "xyz".index(ax)
        lo = b["bbox"]["min"][i]
        for g in tp["grooves"]:
            if g["width"] * scale >= 4.0:
                continue
            need = 5.0 / max(g["width"], 0.1)
            k = next((s for s in (2, 5, 10, 20) if s >= need), 20)
            pt = [0.0, 0.0, 0.0]
            pt[i] = lo + g["at"] + g["width"] / 2
            j = (i + 1) % 3
            pt[j] = g["diameter"] / 2 + g["depth"]
            out.append({"label": next(labels), "in_view": "main", "through": [round(v, 3) for v in pt],
                        "scale": f"{k}:1", "radius_mm": 12, "features": [f"groove at {g['at']:g}"],
                        "why": f"the groove is {g['width']:g} mm wide: {g['width'] * scale:.1f} mm on the sheet, too small to dimension"})
    return out


def _group_size(size, views: list[dict], sections: list[dict], s: float) -> tuple[float, float]:
    ortho = [v for v in views if v["orientation"] != "isometric"]
    main = ortho[0]
    mw, mh = view_size(size, main["orientation"])
    w, h = mw * s, mh * s
    for v in ortho[1:]:
        vw, vh = view_size(size, v["orientation"])
        if v["orientation"] in ("top", "bottom") and main["orientation"] in ("front", "back"):
            h += GAP + vh * s
        elif main["orientation"] == "top" and v["orientation"] in ("front", "back"):
            h += GAP + vh * s
        else:
            w += GAP + vw * s
    if sections:
        # a section is about the size of the view it is projected from (its width) by the part's depth across it
        depth = sorted(size)[0] if len(ortho) > 1 else min(mw, mh)
        sw_, sh_ = mw * s, depth * s
        n = len(sections)
        below = (max(w, sw_), h + n * (GAP + sh_))
        right = (w + GAP + sw_, max(h, n * sh_ + (n - 1) * GAP))
        w, h = min((below, right), key=lambda wh: max(wh[0] / 395.0, wh[1] / 217.0))
    return w, h


def choose_sheet_and_scale(model: dict, views: list[dict], sections: list[dict], sheet: str | None, scale: str | None,
                           profile: dict) -> tuple[str, str, float, float]:
    size = (model.get("overall") or {}).get("size") or [100, 100, 100]
    iso = any(v["orientation"] == "isometric" for v in views)
    allowed = [tuple(int(x) for x in sc.split(":")) for sc in profile["preferred_scales"]]
    pref = [sc for sc in SCALES if sc in allowed] or SCALES
    sheets = [sheet] if sheet else list(SHEETS)
    biggest = max(size)
    natural = 1.0 if biggest <= 150 else 0.5 if biggest <= 400 else 0.2 if biggest <= 1000 else 0.1 if biggest <= 2500 else 0.05
    if model.get("kind") == "assembly":
        natural /= 2
    best = None
    for sh in sheets:
        W, H = SHEETS[sh]
        uw, uh = (W - 25) * (2 / 3 if iso else 1), H - TITLE_BAND - 15
        cands = pref if not scale else [tuple(int(float(x)) for x in scale.split(":"))]
        for a, b in cands:
            s = a / b
            gw, gh = _group_size(size, views, sections, s)
            if gw <= uw and gh <= uh:
                fill = (gw * gh) / (uw * uh)
                if best is None:
                    best = (sh, f"{a}:{b}", s, fill)
                if s >= natural * 0.999:
                    return sh, f"{a}:{b}", s, fill
                break
    if best:
        return best
    sh = sheet or "A0"
    return sh, scale or "1:100", 0.01, 1.0


def compose_notes(model: dict, reasoning: dict, answers: dict, profile: dict) -> tuple[list[str], dict]:
    """General notes: confirmed lines, approved proposals, and TO BE CONFIRMED placeholders for what is missing
    (so an incomplete draft is visibly incomplete, never silently completed)."""
    status = {"confirmed": [], "proposed": [], "to_be_confirmed": []}
    lines = ["NOTES:", "1. ALL DIMENSIONS IN MILLIMETRES.", "2. DO NOT SCALE DRAWING."]
    status["confirmed"] += lines[1:]
    n = 3
    gt = answers.get("general_tolerance")
    if model.get("kind") == "assembly" and not gt:
        pass
    elif gt:
        lines.append(f"{n}. GENERAL TOLERANCES: {str(gt).upper()}.")
        status["confirmed"].append(lines[-1])
    else:
        lines.append(f"{n}. GENERAL TOLERANCES: TO BE CONFIRMED.")
        status["to_be_confirmed"].append("general tolerance")
    n = len(lines)
    if answers.get("edge_break"):
        lines.append(f"{n}. {str(answers['edge_break']).upper()}")
        status["confirmed"].append(lines[-1])
        n += 1
    proposed = []
    for r in reasoning.get("by_discipline", {}).values():
        proposed += [p for p in r.get("proposed_notes", []) if p not in proposed]
    for p in proposed:
        if answers.get("approve_proposed_notes"):
            lines.append(f"{n}. {p.split(' (')[0]}")
            status["confirmed"].append(lines[-1])
            n += 1
        else:
            status["proposed"].append(p)
    if answers.get("surface_finish"):
        lines.append(f"{n}. GENERAL SURFACE FINISH: {str(answers['surface_finish']).upper()}.")
        status["confirmed"].append(lines[-1])
        n += 1
    threads = answers.get("threads") or {}
    if threads:
        for spec, ids in _group_specs(threads).items():
            lines.append(f"{n}. HOLES {', '.join(ids)}: {spec.upper()}.")
            status["confirmed"].append(lines[-1])
            n += 1
    elif any(h.get("possible_thread") for b in _bodies(model) for h in b["holes"]):
        status["to_be_confirmed"].append("threads")
    fits = answers.get("fits") or {}
    for feat, fit in fits.items():
        lines.append(f"{n}. {feat}: {str(fit).upper()}.")
        status["confirmed"].append(lines[-1])
        n += 1
    if answers.get("welds"):
        lines.append(f"{n}. WELDS: {str(answers['welds']).upper()}.")
        status["confirmed"].append(lines[-1])
        n += 1
    for extra in answers.get("notes") or []:
        lines.append(f"{n}. {str(extra).upper()}")
        status["confirmed"].append(lines[-1])
        n += 1
    out = []
    for ln in lines:
        while len(ln) > 90:
            cut = ln.rfind(" ", 0, 90)
            out.append(ln[:cut])
            ln = "   " + ln[cut + 1:]
        out.append(ln)
    if len(out) > 12:
        status["overflow"] = out[12:]
        out = out[:12]
    return out, status


FIT_CODE = __import__("re").compile(r"\b([A-Z]{1,2}\d{1,2})(?:\s*/\s*([a-z]{1,2}\d{1,2}))?\b|\b([a-z]{1,2}\d{1,2})\b")


def _entry_point(h: dict) -> list[float]:
    """A model point on the hole's outermost circle at its entry face (where a callout attaches)."""
    seg = h["segments"][0]
    r = seg["diameter"] / 2
    d = h["dir"]
    k = max(range(3), key=lambda i: abs(d[i]))
    u = [0.0, 0.0, 0.0]
    u[(k + 1) % 3] = 1.0
    return [round(h["position"][i] + r * u[i], 4) for i in range(3)]


def annotation_actions(model: dict, views: list[dict], dims: dict, answers: dict, plan_id: str) -> tuple[list[dict], list[str]]:
    """The dimensioning and annotation actions a machining drawing needs, for the add-in's 0.15 actions:
    one hole callout per group of identical holes (in the main view, where the holes are circles), and the
    tolerances and surface texture symbols the designer gave in the answers. "@main" is the main view, resolved
    at build time. Returns (actions, notes on what was left out and why)."""
    acts: list[dict] = []
    skipped: list[str] = []
    if model.get("kind") != "part" or not views:
        return acts, skipped
    design = model.get("design") or {}
    cats = design.get("feature_categories") or {}
    if cats.get("weld_member") or cats.get("weldment") or design.get("cut_list"):
        # the weldment's own cut list (SOLIDWORKS' table of its cut-list items); never weld sizes, which only the designer gives
        acts.append({"do": "cut_list", "view": "@main", "at": "@top_right", "for": ["cut list"],
                     "why": "a fabricator cuts the members from the cut list: item, quantity, description and length from SOLIDWORKS"})
        skipped.append("weld symbols: placed joint by joint (sw_edit_drawing weld_symbol, confirmed_by) once the designer gives each "
                       "joint's weld; never chosen here")
    main = views[0]["orientation"]
    along = {"front": "z", "top": "y", "right": "x"}.get(main)
    holes = {h["id"]: h for b in _bodies(model) for h in b["holes"]}
    for c in dims.get("callouts", []):
        h = holes.get(c["holes"][0])
        if h is None:
            continue
        if h.get("axis") != along:
            skipped.append(f"callout for {', '.join(c['holes'])}: the holes are not seen as circles in the main view")
            continue
        acts.append({"do": "hole_callout", "view": "@main", "edge": _entry_point(h), "offset": [14, 10], "for": c["holes"],
                     "why": "the hole group's size, depth and counterbore or countersink in one associative callout"})
    who = f"answers given for plan {plan_id}"
    named = (model.get("design") or {}).get("dimensions") or []
    for feat, fit in (answers.get("fits") or {}).items():
        m = FIT_CODE.search(str(fit))
        if not m:
            skipped.append(f"fit for {feat}: no ISO 286 code found in {fit!r}")
            continue
        hole_fit, shaft_fit = (m.group(1), m.group(2)) if m.group(1) else (None, m.group(3))
        size = None
        num = __import__("re").search(r"(\d+(?:\.\d+)?)", str(fit).replace(hole_fit or "", "").replace(shaft_fit or "", ""))
        if num:
            size = float(num.group(1))
        elif feat in holes:
            size = holes[feat]["diameter"]
        dim = next((d for d in named if isinstance(d.get("value"), (int, float)) and size is not None and abs(d["value"] - size) <= 0.001), None)
        if dim is None:
            skipped.append(f"fit for {feat}: no model dimension of {size} to put it on (add it in the model's sketch)")
            continue
        if answers.get("apply_fits_to_model") is not True:
            # a model dimension keeps its tolerance in the part: setting it from the drawing changes the part
            skipped.append(f"fit {fit} for {feat}: it goes on the model dimension {dim['name']}, so it changes the part; answer "
                           "apply_fits_to_model=true to allow that, or set the tolerance in the part")
            continue
        act = {"do": "tolerance", "dimension": dim["name"], "type": "fit", "confirmed_by": who, "for": [feat], "model_change": True}
        if hole_fit:
            act["hole_fit"] = hole_fit
        if shaft_fit:
            act["shaft_fit"] = shaft_fit
        acts.append(act)
    for feat, value in (answers.get("surface_symbols") or {}).items():
        h = holes.get(feat)
        if h is None:
            skipped.append(f"surface symbol for {feat}: only hole features can be referenced for now")
            continue
        acts.append({"do": "surface_finish", "view": "@main", "edge": _entry_point(h), "offset": [-18, 12], "symbol": "machining_required",
                     "roughness_max": str(value), "confirmed_by": who, "for": [feat]})
    return acts, skipped


def _group_specs(threads: dict) -> dict[str, list[str]]:
    by: dict[str, list[str]] = {}
    for hid, spec in threads.items():
        by.setdefault(str(spec), []).append(str(hid))
    return by


def title_block(model: dict, answers: dict, profile: dict) -> tuple[dict, list[str]]:
    tb = {k: str(v) for k, v in (answers.get("title_block") or {}).items() if v}
    if "Title" not in tb and model.get("title"):
        tb["Title"] = str(model["title"]).replace("_", " ")
    mat = answers.get("material") or (model.get("overall") or {}).get("material")
    if mat and "Material" not in tb:
        tb["Material"] = str(mat)
    if answers.get("finish") and "Finish" not in tb:
        tb["Finish"] = str(answers["finish"])
    for k in ("CheckedBy", "ApprovedBy"):
        tb.pop(k, None)   # approvals are made by people, never filled by the tool
    missing = [f for f in profile["title_fields"] if f not in tb and f not in ("CheckedBy", "ApprovedBy")]
    return tb, missing


def questions(model: dict, reasoning: dict, dims: dict, answers: dict, tb_missing: list[str]) -> list[dict]:
    """Only what materially affects correctness, blocking first; nothing already answered."""
    out = []

    def add(qid, q, why, blocking, applies=None, options=None):
        if qid in answers or (qid == "title_block" and not tb_missing):
            return
        row = {"id": qid, "question": q, "why": why, "blocking": blocking}
        if applies:
            row["applies_to"] = applies
        if options:
            row["options"] = options
        out.append(row)

    part = model.get("kind") != "assembly"   # an assembly's materials and tolerances are on its parts' drawings
    if part and not answers.get("material") and not (model.get("overall") or {}).get("material"):
        add("material", "Material and its standard or grade?", "a manufacturing drawing must state it", True)
    if part:
        add("general_tolerance", "General tolerance for dimensions without their own tolerance?",
            "untoleranced dimensions otherwise have no limits", True, options=["ISO 2768-f", "ISO 2768-m", "ISO 2768-c", "company standard"])
    threads = [h["id"] for b in _bodies(model) for h in b["holes"] if h.get("possible_thread")]
    if threads:
        guess = sorted({h["possible_thread"]["thread"] for b in _bodies(model) for h in b["holes"] if h.get("possible_thread")})
        add("threads", f"Are holes {', '.join(threads)} tapped ({', '.join(guess)}?)? Give size, pitch, class and full-thread depth.",
            "the model holds plain holes at tapping-drill size", True, applies=threads)
    fit_items = [t["feature"] for t in dims.get("tolerance_candidates", [])]
    if fit_items:
        add("fits", "Fits or tolerances for: " + ", ".join(f"{t['feature']} ({t['what']})" for t in dims["tolerance_candidates"][:6]) + "?",
            "seats, locating bores and journals usually need tighter limits than the general tolerance", False, applies=fit_items)
    for n in reasoning.get("information_required", []):
        if n["blocking"] and "weld" in n["item"] and "welds" not in answers:
            add("welds", n["item"][0].upper() + n["item"][1:] + "?", n["why"], True)
            break
    fabricated = any(k in reasoning.get("by_discipline", {}) for k in ("piping", "weldment", "structural_steel"))
    if "surface_finish" not in answers and not fabricated and any(k in reasoning.get("by_discipline", {}) for k in ("milling_drilling", "turning", "cnc_machining")):
        add("surface_finish", "General surface finish (and any functional faces finer than it)?", "otherwise left to the shop", False)
    if tb_missing:
        add("title_block", "Title-block fields: " + ", ".join(tb_missing) + "?", "identifies and controls the drawing", False, applies=tb_missing)
    return out


def make_plan(model: dict, classification: dict, reasoning: dict, dims: dict, *, doc: str | None, standard: str | None = None,
              purpose: str | None = None, sheet: str | None = None, scale: str | None = None, isometric: bool | None = None,
              answers: dict | None = None, knowledge: list[dict] | None = None) -> dict[str, Any]:
    answers = answers or {}
    prof = standards.profile(standard)
    applies = classification["applies"]
    views, omitted = choose_views(model, applies, isometric)
    sections = choose_sections(model, views, applies)
    sh, sc, s, fill = choose_sheet_and_scale(model, views, sections, sheet, scale, prof)
    details = choose_details(model, s)
    notes, note_status = compose_notes(model, reasoning, answers, prof)
    tb, tb_missing = title_block(model, answers, prof)
    qs = questions(model, reasoning, dims, answers, tb_missing)
    kind = model.get("kind")
    if not purpose:
        purpose = ("assembly" if kind == "assembly" else
                   "fabrication" if any(a in applies for a in ("weldment", "structural_steel", "piping")) else "manufacturing")
    audience = {"manufacturing": "machinist or CNC programmer, and the inspector",
                "fabrication": "fabricator and welder, and the inspector",
                "assembly": "fitter assembling the parts", "installation": "installer", "inspection": "inspector",
                "maintenance": "service technician", "general_arrangement": "planner and installer"}.get(purpose, "workshop")
    package = [dict(p, status="this plan" if i == 0 else "planned") for i, p in enumerate(classification["package"])]
    for p in package:
        low = p["drawing"].lower()
        if p["status"] == "this plan":
            continue
        if any(w in low for w in ("flat pattern", "exploded", "joint details")):
            p["status"] = "needs an add-in capability not yet available"
        elif "cut list" in low:
            p["status"] = "planned: the cut-list table needs the add-in 0.15"
        elif "weld symbols" in low:
            p["status"] = "needs each joint's weld from the designer (weld symbols with the add-in 0.15)"
    blocking = [q for q in qs if q["blocking"]]
    orth = [v["orientation"] for v in views]
    create = {"doc": doc, "sheet": sh, "projection": prof["projection"], "views": orth, "scale": sc, "dimensions": True,
              "properties": tb or None, "notes": notes, "centre_marks": True}
    deferred = []
    if any(c.get("needs_confirmation") for c in dims.get("callouts", [])):
        deferred.append("thread callouts: a hole callout shows the thread only when the model defines it (Hole Wizard or a cosmetic thread)")
    plan_id = "pl_" + uuid.uuid4().hex[:12]
    ann_acts, ann_skipped = annotation_actions(model, views, dims, answers, plan_id)
    deferred += ann_skipped
    plan = {
        "plan_id": plan_id, "created": round(time.time(), 3), "engine": "drafting 0.1.0",
        "model": {"doc": doc, "title": model.get("title"), "kind": kind},
        "purpose": purpose, "audience": audience,
        "disciplines": {"applies": applies, "primary": classification["primary"], "overridden": classification["overridden"]},
        "standard": {"profile": prof["id"], "name": prof["name"], "statement": prof["statement"]},
        "package": package,
        "sheet": sh, "scale": sc, "projection": prof["projection"], "sheet_fill": round(fill, 3),
        "views": views, "omitted_views": omitted, "sections": sections, "details": details,
        "datums": next((r.get("datums") for r in reasoning.get("by_discipline", {}).values() if r.get("datums")), []),
        "dimensioning": {"scheme": dims["scheme"], "coverage": dims["coverage"]["coverage"],
                         "missing_in_model": dims["coverage"]["missing"], "redundancy": dims["redundancy"],
                         "callouts": dims["callouts"], "tolerance_candidates": dims["tolerance_candidates"]},
        "notes": notes, "notes_status": note_status,
        "title_block": tb, "title_block_missing": tb_missing,
        "questions": qs, "ready_to_build": True, "release_blocked": bool(blocking),
        "release_blocked_by": [q["id"] for q in blocking],
        "execution": {"create_drawing": create, "annotations": ann_acts, "annotations_need": "add-in 0.15", "then": [
            *[f"section {x['label']}-{x['label']}: {x['direction']} through {x['through']} in the {views[0]['orientation']} view" for x in sections],
            *[f"detail {x['label']} at {x['scale']} through {x['through']}" for x in details],
            "insert the model's dimensions into the new views, centre marks, arrange dimensions",
            "check the layout (sw_drafting_check) and correct non-critical problems (view moves only)"],
            "deferred": deferred},
        "knowledge": knowledge or [],
        "human_release": "required: this plan never marks a drawing manufacturing-ready",
    }
    return plan
