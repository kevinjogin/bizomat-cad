"""Module F: dimension planning and checks.

The drawing's dimensions are the model's own (inserted associatively by the add-in), so planning starts from them:
each model dimension is classified (size, location, depth, overall, reference geometry) by matching its value to
the recognised features; then every feature is checked for the dimensions a workshop needs (coverage), and the set
is checked for duplicates, per-hole repetition that a pattern dimension would replace, pitch circles given as x/y
offsets, and closed chains. Callouts are proposed as text in ISO / AS style (standards.callout). No tolerance is
ever chosen here: features likely to need one are listed for the designer.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from . import standards

EPS = 0.011


def _near(a: float, b: float, eps: float = EPS) -> bool:
    return abs(a - b) <= eps


def classify_model_dimensions(model: dict) -> list[dict]:
    dims = (model.get("design") or {}).get("dimensions") or []
    feats = (model.get("design") or {}).get("features") or []
    kinds = {f["name"]: f["category"] for f in feats}
    size = (model.get("overall") or {}).get("size") or []
    bodies = (model.get("recognised") or {}).get("bodies", [])
    diam = set()
    depths = set()
    coords = set()
    for b in bodies:
        for h in b["holes"]:
            diam |= {h["diameter"]} | {s["diameter"] for s in h["segments"]}
            if h.get("counterbore"):
                diam.add(h["counterbore"]["diameter"])
                depths.add(h["counterbore"]["depth"])
            if h.get("countersink"):
                diam.add(h["countersink"]["diameter"])
            if h.get("depth"):
                depths.add(h["depth"])
            for s in h["segments"]:
                depths.add(s["length"])
            for v in h["position"]:
                coords.add(round(abs(v), 3))
        for p in b["patterns"]:
            if p.get("pcd"):
                diam.add(p["pcd"])
        tp = b.get("turned_profile")
        if tp:
            diam |= {s["diameter"] for s in tp["steps"]}
            depths |= {s["length"] for s in tp["steps"]}
        for p in b["pockets"] + b["steps"]:
            depths.add(p["depth"])
            coords |= {round(abs(v), 3) for v in p.get("extent", [])}
    out = []
    for d in dims:
        v = d.get("value")
        owner = d.get("owner") or ""
        row = dict(d)
        cat = kinds.get(owner)
        if not isinstance(v, (int, float)):
            row["role"] = "other"
        elif cat == "reference":
            row["role"] = "reference_geometry"
            row["note"] = "a reference plane offset: usually not shown on the drawing"
        elif any(_near(v, s) for s in size):
            row["role"] = "overall"
        elif any(_near(v, x) for x in diam):
            row["role"] = "size"
        elif any(_near(v, x) for x in depths) and cat in ("cut_extrude", "boss_extrude", "revolve", "revolve_cut", None):
            row["role"] = "depth"
        elif any(_near(v, x) for x in coords) or any(_near(v * 2, x) for x in coords):
            row["role"] = "location"
        else:
            row["role"] = "unmatched"
        out.append(row)
    return out


def coverage(model: dict, classified: list[dict]) -> dict[str, Any]:
    """For each recognised feature: the dimensions it needs and whether the model has a dimension of that value."""
    vals = [d["value"] for d in classified if isinstance(d.get("value"), (int, float)) and d["role"] != "reference_geometry"]

    def has(x: float) -> bool:
        return any(_near(v, x) for v in vals) or any(_near(v, x / 2) for v in vals)  # a diameter may be a radius

    rows, missing = [], []
    bodies = (model.get("recognised") or {}).get("bodies", [])
    for b in bodies:
        for h in b["holes"]:
            need = [("diameter", h["diameter"])]
            if h.get("depth"):
                need.append(("depth", h["depth"]))
            if h.get("counterbore"):
                need += [("counterbore diameter", h["counterbore"]["diameter"]), ("counterbore depth", h["counterbore"]["depth"])]
            if h.get("countersink"):
                need.append(("countersink diameter", h["countersink"]["diameter"]))
            got = [(n, v, has(v)) for n, v in need]
            rows.append({"feature": h["id"], "kind": f"hole ({h['subtype']})",
                         "needs": [{"what": n, "value": v, "in_model": ok} for n, v, ok in got]})
            missing += [{"feature": h["id"], "what": n, "value": v} for n, v, ok in got if not ok]
        for p in b["patterns"]:
            if p.get("pattern") == "pitch_circle":
                ok = has(p["pcd"])
                rows.append({"feature": p["id"], "kind": "pitch circle",
                             "needs": [{"what": "pitch circle diameter", "value": p["pcd"], "in_model": ok}]})
                if not ok:
                    missing.append({"feature": p["id"], "what": "pitch circle diameter", "value": p["pcd"]})
        tp = b.get("turned_profile")
        if tp:
            for s in tp["steps"]:
                ok = has(s["diameter"])
                rows.append({"feature": f"Ø{s['diameter']:g}", "kind": "turned diameter",
                             "needs": [{"what": "diameter", "value": s["diameter"], "in_model": ok}]})
                if not ok:
                    missing.append({"feature": f"Ø{s['diameter']:g}", "what": "diameter", "value": s["diameter"]})
            for g in tp["grooves"]:
                for what, v in (("groove diameter", g["diameter"]), ("groove width", g["width"])):
                    if not has(v):
                        missing.append({"feature": f"groove at {g['at']:g}", "what": what, "value": v})
        for p in b["pockets"] + b["steps"]:
            if not has(p["depth"]):
                missing.append({"feature": p["id"], "what": f"{p['kind']} depth", "value": p["depth"]})
    covered = sum(1 for r in rows for n in r["needs"] if n["in_model"])
    total = sum(len(r["needs"]) for r in rows)
    return {"features": rows, "missing": missing, "coverage": round(covered / total, 3) if total else None,
            "needed": total, "found": covered}


def redundancy(model: dict, classified: list[dict]) -> list[dict]:
    """Repetition a drafter would remove: the same value many times in one sketch (each hole located on its own),
    pitch circles given as x/y offsets, and closed chains on a turned profile."""
    out = []
    by_owner: dict[str, Counter] = defaultdict(Counter)
    for d in classified:
        if isinstance(d.get("value"), (int, float)) and d["role"] not in ("reference_geometry",):
            by_owner[d.get("owner") or ""][round(d["value"], 3)] += 1
    for owner, cnt in by_owner.items():
        reps = {v: n for v, n in cnt.items() if n >= 3}
        if reps:
            out.append({"kind": "repeated_locations", "owner": owner, "values": reps,
                        "advice": "each hole is located on its own in the sketch; on the drawing give the pattern once "
                                  "(count, spacing or PCD) so the same value is not repeated",
                        "knowledge": "K10-001"})
    bodies = (model.get("recognised") or {}).get("bodies", [])
    for b in bodies:
        for p in b["patterns"]:
            if p.get("pattern") != "pitch_circle":
                continue
            r = p["pcd"] / 2
            offs = {round(r * abs(math.cos(math.radians(a))), 2) for a in
                    [p.get("start_angle_deg", 0) + k * (p.get("angle_step_deg") or 0) for k in range(p["count"])]}
            vals = [d for d in classified if isinstance(d.get("value"), (int, float)) and any(_near(d["value"], o, 0.02) for o in offs)
                    and not _near(d["value"], p["pcd"])]
            owners = {d.get("owner") for d in vals}
            same = [d for d in classified if d.get("owner") in owners and isinstance(d.get("value"), (int, float))]
            if vals and not any(_near(d["value"], p["pcd"]) or _near(d["value"], r) for d in same):
                out.append({"kind": "pcd_as_offsets", "pattern": p["id"], "offsets": sorted({d["value"] for d in vals}),
                            "pcd": p["pcd"], "advice": f"the holes sit on a Ø{p['pcd']:g} pitch circle but the model gives x/y offsets "
                                                       f"({', '.join(f'{d:g}' for d in sorted({d['value'] for d in vals}))}); dimension the PCD "
                                                       "and the angles instead (change the sketch, so the drawing stays associative)",
                            "knowledge": "K10-004"})
        tp = b.get("turned_profile")
        if tp and len(tp["steps"]) >= 2:
            lengths = [s["length"] for s in tp["steps"]]
            vals = [d["value"] for d in classified if isinstance(d.get("value"), (int, float))]
            if all(any(_near(v, L) for v in vals) for L in lengths) and any(_near(v, tp["length"]) for v in vals):
                out.append({"kind": "closed_chain", "advice": "every step length and the overall length are dimensioned: leave "
                                                              "one step out or give lengths from one shoulder", "knowledge": "K10-002"})
    return out


def callouts(model: dict) -> list[dict]:
    """One proposed callout per group of identical holes, with where the group's position comes from."""
    out = []
    for b in (model.get("recognised") or {}).get("bodies", []):
        in_pattern = {}
        for p in b["patterns"]:
            for hid in p["holes"]:
                in_pattern[hid] = p
        done = set()
        for h in b["holes"]:
            if h["id"] in done:
                continue
            p = in_pattern.get(h["id"])
            members = p["holes"] if p else [h["id"]]
            done |= set(members)
            text = standards.callout(h, len(members))
            if p and p.get("pattern") == "pitch_circle":
                text += f" EQ SP ON Ø{p['pcd']:g} PCD" if p.get("equally_spaced") else f" ON Ø{p['pcd']:g} PCD"
            row = {"holes": members, "callout": text, "status": "proposed: the add-in has no hole-callout action yet; "
                                                             "the model's own dimensions are inserted instead"}
            if h.get("possible_thread"):
                row["callout_if_tapped"] = f"{len(members)}x {h['possible_thread']['thread']} (pitch, class and thread depth to confirm)"
                row["needs_confirmation"] = "thread"
            out.append(row)
    return out


def tolerance_candidates(model: dict, disciplines: list[str] | None = None) -> list[dict]:
    """Features whose function probably needs a tolerance tighter than the general one. Listed, never toleranced."""
    out = []
    fabricated = any(d in (disciplines or []) for d in ("piping", "weldment", "structural_steel"))
    for b in (model.get("recognised") or {}).get("bodies", []):
        for h in b["holes"]:
            if h.get("counterbore") and h["counterbore"]["diameter"] >= 30:
                out.append({"feature": h["id"], "what": f"Ø{h['counterbore']['diameter']:g} seat / locating bore", "why": "a seat or spigot locates a mating part"})
            if any(i["kind"] in ("precision_fit", "bearing_seat", "locating") for i in h.get("name_intent", [])):
                out.append({"feature": h["id"], "what": f"Ø{h['diameter']:g}", "why": "named as a fit, seat or locating feature"})
        for p in b["patterns"]:
            if p.get("pattern") == "pitch_circle" and not fabricated:
                out.append({"feature": p["id"], "what": f"Ø{p['pcd']:g} PCD position", "why": "holes that pick up a mating part's bolt circle"})
        tp = b.get("turned_profile")
        if tp and not fabricated and not b.get("flange"):
            for s in tp["steps"]:
                out.append({"feature": f"Ø{s['diameter']:g}", "what": "turned diameter", "why": "journals and seats on a shaft are usually fits"})
    return out


def scheme(model: dict, disciplines: list[str]) -> dict[str, Any]:
    """The dimensioning method a drafter would use for this part."""
    bodies = (model.get("recognised") or {}).get("bodies", [])
    holes = sum(len(b["holes"]) for b in bodies)
    if model.get("kind") == "assembly":
        return {"method": "assembly", "why": "overall sizes and interface dimensions only; parts are detailed on their own drawings"}
    if any(b.get("turned_profile") for b in bodies):
        return {"method": "baseline from one shoulder; diameters on the side view",
                "why": "lengths from one datum shoulder stop tolerances stacking; diameters are seen true in the side view",
                "knowledge": ["K10-002", "K17-002"]}
    if "weldment" in disciplines or "structural_steel" in disciplines:
        return {"method": "member lengths and positions from working points; cut list for lengths",
                "why": "fabricators set out from working points and cut from the list", "knowledge": ["K04-001", "K05-002"]}
    if holes >= 8:
        return {"method": "ordinate from the datum corner, or a hole table",
                "why": f"{holes} holes: linear dimensions would crowd the view", "knowledge": ["K10-005"]}
    return {"method": "baseline from datums", "why": "positions from the functional datums, each once", "knowledge": ["K03-001"]}


def plan(model: dict, disciplines: list[str]) -> dict[str, Any]:
    classified = classify_model_dimensions(model)
    cov = coverage(model, classified)
    return {"scheme": scheme(model, disciplines), "model_dimensions": len(classified),
            "roles": dict(Counter(d["role"] for d in classified)), "coverage": cov,
            "redundancy": redundancy(model, classified), "callouts": callouts(model),
            "tolerance_candidates": tolerance_candidates(model, disciplines),
            "associativity": "the model's dimensions are inserted into the views (associative); missing ones belong in the "
                             "model's sketches so the drawing stays associative"}
