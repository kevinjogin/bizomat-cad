"""Module C: manufacturing and fabrication reasoning, one module per discipline.

Each module reads the engineering model (understanding.py) and returns what a drafter needs to know for that
discipline: the operations implied by the features, a candidate datum scheme, the features that are probably
critical, the information that must come from the designer (with whether it blocks release), proposed notes (to be
approved, never applied silently) and the knowledge-base topics that explain the reasoning.

Nothing here sets a tolerance, a fit, a thread, a weld size or a surface finish: those are listed as information
required.
"""

from __future__ import annotations

from typing import Any, Callable


def _bodies(model: dict) -> list[dict]:
    rec = model.get("recognised") or {}
    if model.get("kind") == "assembly":
        return [b for p in (rec.get("parts") or {}).values() for b in (p.get("recognised") or {}).get("bodies", [])]
    return rec.get("bodies", [])


def _need(item: str, why: str, blocking: bool, features: list[str] | None = None) -> dict:
    out = {"item": item, "why": why, "blocking": blocking}
    if features:
        out["features"] = features
    return out


def _hole_ops(holes: list[dict]) -> list[str]:
    ops = []
    for h in holes:
        st = h["subtype"]
        if st == "counterbore":
            ops.append(f"{h['id']}: drill Ø{h['diameter']:g}, counterbore Ø{h['counterbore']['diameter']:g} x {h['counterbore']['depth']:g}")
        elif st == "countersink":
            ops.append(f"{h['id']}: drill Ø{h['diameter']:g}, countersink Ø{h['countersink']['diameter']:g} x {h['countersink']['angle_deg']:g}°")
        elif st == "blind":
            extra = f" (possibly tap {h['possible_thread']['thread']}: to confirm)" if h.get("possible_thread") else ""
            ops.append(f"{h['id']}: drill Ø{h['diameter']:g} x {h.get('depth', 0):g} deep, {h.get('bottom', 'flat')} bottom{extra}")
        elif st == "stepped":
            ops.append(f"{h['id']}: stepped bore " + ", ".join(f"Ø{s['diameter']:g} x {s['length']:g}" for s in h["segments"]))
        else:
            ops.append(f"{h['id']}: drill Ø{h['diameter']:g} through")
    return ops


def _prismatic_datums(body: dict) -> list[dict]:
    """A candidate 3-2-1 datum scheme: the largest flat face, then the two outside faces across the longest
    sizes. A candidate only: the designer's functional datums win."""
    size = body["bbox"]["size"]
    order = sorted(range(3), key=lambda i: size[i])
    thin, mid, long_ = order
    out = [{"datum": "A", "what": f"the largest flat face, normal to {'xyz'[thin]} (the seating face)",
            "basis": "largest planar face: usually the mounting or seating face", "confidence": "medium"},
           {"datum": "B", "what": f"an outside edge face normal to {'xyz'[mid]}", "basis": "locates along the longest size",
            "confidence": "low"},
           {"datum": "C", "what": f"an outside edge face normal to {'xyz'[long_]}", "basis": "stops rotation", "confidence": "low"}]
    centred = all(abs(body["bbox"]["min"][i] + body["bbox"]["max"][i]) <= 0.1 for i in (mid, long_))
    if centred:
        out[1]["what"] += " (the model is symmetric about its centre planes: hole positions may be given from them)"
    return out


def machining(model: dict) -> dict[str, Any]:
    bodies = _bodies(model)
    holes = [h for b in bodies for h in b["holes"]]
    pockets = [p for b in bodies for p in b["pockets"]]
    steps = [p for b in bodies for p in b["steps"]]
    slots = [s for b in bodies for s in b["slots"]]
    ops = []
    if bodies:
        ops.append("face and square the outside to size")
    ops += [f"{p['id']}: mill pocket {' x '.join(f'{v:g}' for v in p.get('extent', []))}, {p['depth']:g} deep" for p in pockets]
    ops += [f"{p['id']}: mill step {p['depth']:g} deep" for p in steps]
    ops += [f"{s['id']}: mill slot {s['width']:g} wide x {s['length']:g} long" for s in slots]
    ops += _hole_ops(holes)
    critical, needs = [], []
    pats = [p for b in bodies for p in b["patterns"]]
    for p in pats:
        if p.get("pattern") == "pitch_circle":
            critical.append(f"{p['id']}: {p['count']} holes on Ø{p['pcd']:g} pitch circle (position relative to the centre feature)")
    seats = [h for h in holes if h.get("counterbore") and h["counterbore"]["diameter"] >= 30]
    for h in seats:
        critical.append(f"{h['id']}: stepped bore Ø{h['counterbore']['diameter']:g}: a seat or locating diameter is usually a fit")
    threads = [h["id"] for h in holes if h.get("possible_thread")]
    if threads:
        needs.append(_need("thread specification (size, pitch, class, thread depth) for possibly tapped holes",
                           "plain holes at tapping-drill size; the model does not say they are threaded", True, threads))
    if seats:
        needs.append(_need("fit or tolerance for seats and locating bores", "a seat without a fit cannot be inspected",
                           True, [h["id"] for h in seats]))
    needs.append(_need("surface finish for functional faces (or a general surface finish)",
                       "machined faces default to the shop's practice when nothing is stated", False))
    needs.append(_need("edge treatment (break sharp edges, chamfer size)", "stated once in the general notes", False))
    return {"discipline": "milling_drilling", "operations": ops,
            "datums": _prismatic_datums(bodies[0]) if bodies else [], "critical_features": critical,
            "information_required": needs,
            "proposed_notes": ["REMOVE BURRS AND BREAK SHARP EDGES (size to confirm)"],
            "knowledge_topics": ["datum selection", "hole callouts", "counterbore", "pitch circle", "section views",
                                 "general tolerance", "surface texture"]}


def turning(model: dict) -> dict[str, Any]:
    bodies = [b for b in _bodies(model) if b.get("turned_profile")]
    if not bodies:
        return {"discipline": "turning", "operations": [], "information_required": [], "critical_features": []}
    tp = bodies[0]["turned_profile"]
    ops = ["face both ends, turn to length " + f"{tp['length']:g}"]
    ops += [f"turn Ø{s['diameter']:g} for {s['length']:g}" for s in tp["steps"]]
    ops += [f"groove Ø{g['diameter']:g} x {g['width']:g} wide at {g['at']:g}" for g in tp["grooves"]]
    ops += [f"chamfer {c['included_angle_deg'] / 2:g}° at {c['from']:g}" for c in tp["chamfers"]]
    cross = [h for h in bodies[0]["holes"] if h.get("axis") != tp.get("axis")]
    ops += [f"{h['id']}: cross-drill Ø{h['diameter']:g}" for h in cross]
    needs = [_need("fits for journal, seat and locating diameters", "turned diameters that carry bearings or hubs need fits", True,
                   [f"Ø{s['diameter']:g}" for s in tp["steps"]]),
             _need("surface finish for running and seating diameters", "journals are usually specified finer than the general finish", False),
             _need("centre holes permitted or not", "between-centres turning leaves centre holes", False)]
    if tp["grooves"]:
        needs.append(_need("retaining ring or undercut standard for each groove", "groove width, diameter and edge radius follow the ring maker's table",
                           True, [f"groove at {g['at']:g}" for g in tp["grooves"]]))
    return {"discipline": "turning", "operations": ops,
            "datums": [{"datum": "A", "what": "the axis (common axis of the bearing diameters, to confirm)", "confidence": "medium",
                        "basis": "turned parts are made and checked about their axis"},
                       {"datum": "B", "what": "the main shoulder face (axial location)", "confidence": "low",
                        "basis": "lengths are best given from one shoulder"}],
            "critical_features": [f"Ø{s['diameter']:g} for {s['length']:g}" for s in tp["steps"] if s["length"] > 0],
            "information_required": needs,
            "proposed_notes": ["UNDERCUTS AND GROOVES AS DETAILED (sizes to confirm)"],
            "knowledge_topics": ["turned part views", "shaft dimensioning", "groove detail", "fits", "runout"]}


def weldment(model: dict) -> dict[str, Any]:
    bodies = _bodies(model)
    members = [(b["body"], b["member"]) for b in bodies if b.get("member")]
    groups: dict[tuple, list[int]] = {}
    for i, m in members:
        key = (m["section"], tuple(m["section_size"]), m["length"], tuple(c["angle_deg"] for c in m["end_cuts"]))
        groups.setdefault(key, []).append(i)
    cut_list = [{"item": n, "section": k[0], "size": "x".join(f"{v:g}" for v in k[1]), "length": k[2],
                 "end_cuts_deg": list(k[3]), "qty": len(v), "bodies": v, "designation": "to confirm (inferred from geometry)"}
                for n, (k, v) in enumerate(sorted(groups.items()), 1)]
    contacts = (model.get("recognised") or {}).get("contacts") or []
    joints = [{"joint": f"J{n}", "bodies": c["bodies"], "at": c["at"]} for n, c in enumerate(contacts, 1)]
    needs = [_need("weld type, size, length and symbol for every joint", "weld sizes come from the design, never from drafting", True,
                   [j["joint"] for j in joints]),
             _need("welding standard and weld category or quality level", "sets inspection and acceptance", True),
             _need("member designations and steel grade", "geometry shows the size, not the grade or the standard section", True),
             _need("post-weld machining (faces, holes to be machined after welding)", "decides the drawing sequence", False),
             _need("surface treatment (paint, galvanizing) and fabrication tolerances", "stated in the fabrication notes", False)]
    return {"discipline": "weldment", "cut_list": cut_list, "joints": joints,
            "operations": ["cut members to length (end cuts per cut list)", "fit up and tack", "weld (per weld symbols, once specified)",
                           "clean and inspect", "machine after welding if required"],
            "critical_features": [f"overall frame size {' x '.join(f'{v:g}' for v in (model.get('overall') or {}).get('size') or [])}"],
            "information_required": needs,
            "proposed_notes": ["MEMBER LENGTHS ARE CUT LENGTHS", "REMOVE WELD SPATTER AND SHARP EDGES"],
            "knowledge_topics": ["cut list", "member marks", "weld symbols", "weld information", "distortion"]}


def structural(model: dict) -> dict[str, Any]:
    bodies = _bodies(model)
    members = [b["member"] for b in bodies if b.get("member")]
    plates = [b for b in bodies if not b.get("member") and b["holes"]]
    bolts = []
    for b in plates:
        for p in b["patterns"]:
            bolts.append({"pattern": p["id"], "count": p["count"], "hole": p["of"]["diameter"],
                          "bolt_size_hint": next((h.get("possible_clearance", {}).get("bolt") for h in b["holes"]
                                                  if h["id"] in p["holes"] and h.get("possible_clearance")), None)})
    needs = [_need("member designations, steel grade and the design standard", "set by the structural engineer", True),
             _need("bolt grade and tightening category for each bolt group", "never inferred from hole size", True,
                   [x["pattern"] for x in bolts]),
             _need("coating and member marks", "erection and corrosion protection", False)]
    return {"discipline": "structural_steel",
            "members": [{"section": m["section"], "size": m["section_size"], "length": m["length"], "end_cuts": m["end_cuts"]} for m in members],
            "bolt_groups": bolts,
            "operations": ["cut members, drill or punch holes", "fabricate connection plates", "assemble and weld connections (as specified)",
                           "coat", "erect"],
            "critical_features": ["hole positions in connection plates (gauges and pitches)", "member lengths between connections"],
            "information_required": needs,
            "proposed_notes": ["ALL HOLES 2 mm OVERSIZE U.N.O. (to confirm: practice differs by standard)"],
            "knowledge_topics": ["member detail", "connection detail", "bolt group", "gauge lines", "erection marks"]}


def sheet_metal(model: dict) -> dict[str, Any]:
    bodies = [b for b in _bodies(model) if b.get("sheet_metal")]
    cats = (model.get("design") or {}).get("feature_categories") or {}
    if not bodies:
        return {"discipline": "sheet_metal", "information_required": [], "operations": []}
    sm = bodies[0]["sheet_metal"]
    t = sm["thickness"]
    checks = []
    for b in bodies:
        radii = {x["inside_radius"] for x in b["sheet_metal"]["bends"]}
        for h in b["holes"]:
            if h["diameter"] < t:
                checks.append(f"{h['id']}: hole Ø{h['diameter']:g} is smaller than the thickness {t:g}: punching may not hold it")
        if radii and min(radii) < t:
            checks.append(f"inside bend radius {min(radii):g} is less than the thickness {t:g}: check the material allows it")
    native = bool(cats.get("sheet_metal"))
    needs = [_need("material, temper and finish", "bend radius and K-factor depend on them", True),
             _need("bend allowance or K-factor used", "the flat pattern size depends on it" + (" (held in SOLIDWORKS, not read by the add-in)" if native else ""), not native)]
    if not native:
        needs.append(_need("convert to a SOLIDWORKS sheet-metal part", "without sheet-metal features SOLIDWORKS cannot make the flat pattern", True))
    return {"discipline": "sheet_metal", "thickness": t, "bends": sm["bends"],
            "operations": ["cut blank (laser or punch) from the flat pattern", f"bend ({sm['bend_count']} bend(s), inside radius as modelled)",
                           "fit hardware, finish"],
            "checks": checks, "critical_features": ["formed dimensions between functional faces", "hole positions relative to bends"],
            "information_required": needs, "proposed_notes": [f"MATERIAL THICKNESS {t:g} mm", "INSIDE BEND RADII AS MODELLED"],
            "knowledge_topics": ["flat pattern", "bend radius", "hole to bend distance", "formed dimensions"]}


def assembly(model: dict) -> dict[str, Any]:
    asm = model.get("assembly") or {}
    return {"discipline": "mechanical_assembly",
            "operations": ["assemble per the assembly drawing", "fit fasteners (torques when specified)"],
            "bom": {"components": asm.get("components"), "unique_parts": asm.get("unique_parts"), "fasteners": asm.get("fasteners")},
            "critical_features": ["interfaces between components", "clearances that must be kept"],
            "information_required": [_need("tightening torques and thread locking", "never assumed", False),
                                     _need("assembly sequence or special instructions", "only when the order matters", False)],
            "checks": ["run sw_check_interference before releasing the assembly drawing"],
            "proposed_notes": [],
            "knowledge_topics": ["assembly drawing", "balloons", "bill of materials", "exploded view"]}


def piping(model: dict) -> dict[str, Any]:
    bodies = _bodies(model)
    pipes = [b["member"] for b in bodies if b.get("member") and b["member"]["section"] == "CHS"]
    elbows = [e for b in bodies for e in b.get("elbows", [])]
    flanges = [b["flange"] for b in bodies if b.get("flange")]
    hints = []
    for p in pipes:
        od = p["section_size"][0]
        hints.append(f"pipe OD {od:g}" + (f", bore {p['bore']:g}" if p.get("bore") else "") + " (pipe size and schedule to confirm)")
    for e in elbows:
        ratio = e["bend_radius"] / e["outside_diameter"] if e["outside_diameter"] else 0
        hints.append(f"elbow OD {e['outside_diameter']:g}, bend radius {e['bend_radius']:g} ({ratio:.2f} x OD)")
    return {"discipline": "piping", "items": hints,
            "flanges": [{"od": f["outside_diameter"], "pcd": f["pcd"], "bolt_holes": f["bolt_holes"], "hole": f["bolt_hole_diameter"]} for f in flanges],
            "operations": ["cut pipe to length", "fit fittings and flanges (bolt holes straddling centre lines unless stated)", "weld", "test (as specified)"],
            "critical_features": ["centre-line dimensions between interfaces", "flange face to face and orientation"],
            "information_required": [_need("pipe specification (size, schedule, material) and flange rating", "geometry gives sizes, not the rating", True),
                                     _need("design code, weld procedure, NDT and test pressure", "pressure equipment requirements come from the owner's code", True),
                                     _need("supports and installation clearances", "for the installation drawing", False)],
            "proposed_notes": ["DIMENSIONS ARE TO PIPE CENTRE LINES AND FLANGE FACES"],
            "knowledge_topics": ["pipe spool", "centre line dimensions", "flange orientation"]}


def general_arrangement(model: dict) -> dict[str, Any]:
    size = (model.get("overall") or {}).get("size")
    return {"discipline": "general_arrangement",
            "content": ["overall envelope" + (f" {' x '.join(f'{v:.0f}' for v in size)} mm" if size else ""),
                        "equipment positions and orientation", "mounting interfaces and fixing points",
                        "lifting points", "access and service clearances", "masses (when known)"],
            "information_required": [_need("total mass and centre of gravity", "lifting and foundations need them; mass properties need materials", False),
                                     _need("interfaces the installer must connect (services, foundations)", "only the designer knows them", False)],
            "operations": [], "critical_features": ["interface positions"],
            "proposed_notes": [], "knowledge_topics": ["general arrangement", "installation drawing"]}


MODULES: dict[str, Callable[[dict], dict]] = {
    "milling_drilling": machining, "cnc_machining": machining, "plate_fabrication": machining, "precision": machining,
    "turning": turning, "weldment": weldment, "welding_fabrication": weldment, "structural_steel": structural,
    "sheet_metal": sheet_metal, "mechanical_assembly": assembly, "piping": piping, "general_arrangement": general_arrangement,
    "installation": general_arrangement,
}


def reason(model: dict, applies: list[str]) -> dict[str, Any]:
    out, done = {}, set()
    for label in applies:
        fn = MODULES.get(label)
        if fn is None or fn in done:
            continue
        done.add(fn)
        out[label] = fn(model)
    needs, seen = [], set()
    for r in out.values():
        for n in r.get("information_required", []):
            if n["item"] not in seen:
                seen.add(n["item"])
                needs.append(n)
    return {"by_discipline": out, "information_required": needs}
