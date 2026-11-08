"""Module B: multi-label drafting discipline classification, with the evidence for each label.

One model usually needs several disciplines (a machined weldment: weldment + structural + machining + assembly).
Each label gets a score 0..1 and the reasons that produced it; labels at 0.5 or more apply. The user can override
the result (`override`), which is then used as given and recorded as such.
"""

from __future__ import annotations

from typing import Any

LABELS: dict[str, str] = {
    "general_mechanical": "General mechanical drafting",
    "cnc_machining": "CNC machining",
    "turning": "Turning and lathe machining",
    "milling_drilling": "Milling and drilling",
    "precision": "Precision engineering (fits, tight tolerances)",
    "structural_steel": "Structural steel detailing",
    "weldment": "Weldment drafting",
    "welding_fabrication": "Welding and fabrication",
    "sheet_metal": "Sheet-metal drafting",
    "plate_fabrication": "Plate fabrication (profile cutting, drilling)",
    "mechanical_assembly": "Mechanical assemblies",
    "piping": "Piping and pipe spool drafting",
    "pressure_equipment": "Pressure equipment documentation",
    "general_arrangement": "General arrangement drawings",
    "installation": "Installation drawings",
    "maintenance": "Maintenance and service drawings",
    "manufacturing_inspection": "Manufacturing and inspection drawings",
}

PACKAGES: dict[str, list[str]] = {
    "turning": ["Turned part detail drawing (side view, diameters, details of grooves and undercuts)"],
    "milling_drilling": ["Machined part detail drawing (views, sections through hidden features, hole callouts)"],
    "plate_fabrication": ["Plate detail drawing (profile, hole positions from datums, thickness)"],
    "precision": ["Critical-dimension and fit table on the detail drawing (once fits are confirmed)"],
    "weldment": ["Weldment assembly drawing with member marks and cut list",
                 "Joint details at each weld once welds are specified"],
    "welding_fabrication": ["Fabrication notes: weld symbols, sequence and post-weld machining (once specified)"],
    "structural_steel": ["Member detail drawings (length, end cuts, hole positions)", "Connection details"],
    "sheet_metal": ["Formed part drawing (bends, thickness, inside radius)", "Flat pattern drawing"],
    "mechanical_assembly": ["Assembly drawing with bill of materials and balloons"],
    "piping": ["Pipe spool drawing (centre-line dimensions, fittings, flange orientation, cut lengths)"],
    "pressure_equipment": ["Pressure equipment documentation per the design code the owner names (not generated here)"],
    "general_arrangement": ["General arrangement drawing (envelope, interfaces, mounting, lifting, masses)"],
    "installation": ["Installation drawing (foundation and fixing interface, clearances)"],
    "maintenance": ["Service drawing (access, removal, replaceable parts)"],
    "manufacturing_inspection": ["Inspection notes and critical-dimension list (once tolerances are confirmed)"],
}


def _add(scores: dict, reasons: dict, label: str, score: float, why: str) -> None:
    scores[label] = min(1.0, max(scores.get(label, 0.0), score) + (0.05 if label in scores else 0.0))
    reasons.setdefault(label, []).append(why)


def _bodies(model: dict) -> list[dict]:
    rec = model.get("recognised") or {}
    if model.get("kind") == "assembly":
        out = []
        for p in (rec.get("parts") or {}).values():
            out += (p.get("recognised") or {}).get("bodies", [])
        return out
    return rec.get("bodies", [])


PRIORITY = ["piping", "weldment", "structural_steel", "sheet_metal", "turning", "milling_drilling", "plate_fabrication",
            "precision", "welding_fabrication", "mechanical_assembly", "general_arrangement"]
ASSEMBLY_LEVEL = {"mechanical_assembly", "general_arrangement", "installation", "maintenance"}


def _part_drawings(model: dict) -> list[dict]:
    """For an assembly: the discipline each unique part's own drawing needs."""
    out = []
    for key, p in ((model.get("recognised") or {}).get("parts") or {}).items():
        rec = p.get("recognised")
        if not rec:
            continue
        sub = {"kind": "part", "recognised": rec, "overall": {"size": rec["bbox"]["size"]}, "design": {}}
        c = classify(sub)
        out.append({"part": p.get("name") or key, "primary": c["primary"], "applies": c["applies"]})
    return out


def classify(model: dict, override: list[str] | None = None) -> dict[str, Any]:
    if override:
        bad = [o for o in override if o not in LABELS]
        if bad:
            raise ValueError(f"Unknown discipline(s): {', '.join(bad)}. Known: {', '.join(LABELS)}")
        labels = [{"id": o, "name": LABELS[o], "score": 1.0, "reasons": ["chosen by the user"]} for o in override]
        return {"labels": labels, "applies": override, "primary": override[0], "overridden": True,
                "overlaps": _overlaps(override), "package": _package(override)}
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    cats = (model.get("design") or {}).get("feature_categories") or {}
    bodies = _bodies(model)
    size = (model.get("overall") or {}).get("size") or [0, 0, 0]
    kind = model.get("kind")
    if kind == "assembly":
        asm = model.get("assembly") or {}
        n = asm.get("components", 0)
        _add(scores, reasons, "mechanical_assembly", 0.9, f"an assembly of {n} components")
        if asm.get("fasteners"):
            _add(scores, reasons, "mechanical_assembly", 0.9, f"{len(asm['fasteners'])} fastener(s) by name")
            _add(scores, reasons, "maintenance", 0.35, "fasteners: parts can be removed and replaced")
        big = max(size or [0]) >= 1000
        names = " ".join(str(c.get("name") or "") for c in ((model.get("recognised") or {}).get("components") or [])).lower()
        if big or n >= 8 or any(w in names for w in ("skid", "frame", "motor", "pump", "tank", "conveyor")):
            _add(scores, reasons, "general_arrangement", 0.75,
                 "a large envelope or equipment-like components" + (f" (largest size {max(size):.0f} mm)" if size else ""))
        if any(w in names for w in ("lug", "lifting", "eye")):
            _add(scores, reasons, "general_arrangement", 0.8, "lifting provisions by name")
            _add(scores, reasons, "installation", 0.5, "lifting provisions: installation and handling information")
    else:
        _add(scores, reasons, "general_mechanical", 0.5, "a part to be made")
        _add(scores, reasons, "manufacturing_inspection", 0.55, "every part drawing carries inspection information")
    turned = [b for b in bodies if b.get("turned_profile")]
    holes = [h for b in bodies for h in b.get("holes", [])]
    pockets = [p for b in bodies for p in b.get("pockets", []) + b.get("steps", [])]
    slots = [s for b in bodies for s in b.get("slots", [])]
    members = [b["member"] for b in bodies if b.get("member")]
    sheets = [b["sheet_metal"] for b in bodies if b.get("sheet_metal")]
    elbows = [e for b in bodies for e in b.get("elbows", [])]
    flanges = [b["flange"] for b in bodies if b.get("flange")]
    if kind == "assembly":
        # the parts' own disciplines belong to their part drawings (part_drawings), not to the assembly drawing
        members, sheets, elbows, flanges = [], [], [], []
        holes, pockets, slots, turned = [], [], [], []
    if turned:
        t = turned[0]["turned_profile"]
        _add(scores, reasons, "turning", 0.9 if t["confidence"] == "high" else 0.7,
             f"turned outside about one axis ({t['share_of_area']:.0%} of the surface), {len(t['steps'])} diameter step(s)")
    if cats.get("revolve") or cats.get("revolve_cut"):
        _add(scores, reasons, "turning", 0.6, "revolved features in the feature tree")
    if holes or pockets or slots:
        n = len(holes)
        bits = [f"{n} hole(s)"] if n else []
        if pockets:
            bits.append(f"{len(pockets)} pocket(s) or step(s)")
        if slots:
            bits.append(f"{len(slots)} slot(s)")
        sc = 0.8 if (pockets or slots or n >= 2) else 0.6
        if not (members and not pockets and not slots) and not sheets:
            _add(scores, reasons, "milling_drilling", sc, ", ".join(bits))
    if turned or any(r in scores for r in ("milling_drilling",)):
        _add(scores, reasons, "cnc_machining", 0.7, "machined features (turning, milling or drilling)")
    # precision: only from evidence (names stating a fit, bearing seats, dowels), never from size alone
    named_fit = [h for h in holes if any(i["kind"] in ("precision_fit", "bearing_seat", "locating") for i in h.get("name_intent", []))]
    seats = [h for h in holes if h.get("counterbore") and h["counterbore"]["diameter"] >= 30 and h["counterbore"]["depth"] >= 8]
    if named_fit:
        _add(scores, reasons, "precision", 0.75, f"{len(named_fit)} feature(s) named as fits, seats or locations")
    if seats:
        _add(scores, reasons, "precision", 0.55, f"{len(seats)} stepped bore(s) shaped like a bearing or bush seat (confirm the fit)")
    if turned and any(t.get("grooves") for t in turned):
        _add(scores, reasons, "precision", 0.5, "a shaft with retaining-ring or undercut grooves (journal fits likely; confirm)")
    plate_like = size and sorted(size)[0] <= 0.2 * sorted(size)[1] and sorted(size)[0] >= 3
    if kind == "part" and plate_like and not sheets and not members and len(bodies) == 1:
        _add(scores, reasons, "plate_fabrication", 0.6, f"a plate {sorted(size)[0]:g} mm thick")
    if sheets or cats.get("sheet_metal"):
        why = f"constant thickness {sheets[0]['thickness']:g} mm with {sheets[0]['bend_count']} bend(s)" if sheets else "sheet-metal features"
        _add(scores, reasons, "sheet_metal", 0.95 if cats.get("sheet_metal") else 0.8, why)
    if members:
        secs = sorted({m["section"] for m in members})
        if len(bodies) > 1 or cats.get("weld_member"):
            _add(scores, reasons, "weldment", 0.9 if cats.get("weld_member") else 0.8,
                 f"{len(members)} member(s) ({', '.join(secs)}) in a multi-body part")
            _add(scores, reasons, "welding_fabrication", 0.75, "members meeting at joints to be welded or bolted")
        structural = [m for m in members if m["section"] in ("I_or_H", "channel", "angle", "RHS", "SHS", "CHS") and m["length"] >= 300]
        if structural and not elbows:
            _add(scores, reasons, "structural_steel", 0.8 if len(structural) >= 2 or any(m["section"] == "I_or_H" for m in structural) else 0.6,
                 f"structural sections: {', '.join(sorted({m['section'] for m in structural}))}")
    if kind != "assembly" and len(bodies) > 1 and (model.get("recognised") or {}).get("contacts"):
        n = len(model["recognised"]["contacts"])
        _add(scores, reasons, "welding_fabrication", 0.7, f"{len(bodies)} bodies meeting at {n} joint(s)")
        big_holes = [h for h in holes if h["diameter"] >= 18]
        if big_holes:
            _add(scores, reasons, "structural_steel", 0.75, f"{len(big_holes)} bolt hole(s) of 18 mm or more in a connection")
    if cats.get("weld_bead"):
        _add(scores, reasons, "welding_fabrication", 0.9, "weld beads in the model")
    chs = [m for m in members if m["section"] == "CHS"]
    if elbows or (chs and flanges):
        _add(scores, reasons, "piping", 0.95, f"pipe ({len(chs)} straight), {len(elbows)} elbow(s), {len(flanges)} flange(s)")
        _add(scores, reasons, "pressure_equipment", 0.3,
             "pipework may be pressure equipment: only the owner can say which design code applies")
        scores.pop("structural_steel", None)
        reasons.pop("structural_steel", None)
    rank = {k: i for i, k in enumerate(PRIORITY)}
    labels = sorted(({"id": k, "name": LABELS[k], "score": round(v, 2), "reasons": reasons[k]} for k, v in scores.items()),
                    key=lambda r: (-r["score"], rank.get(r["id"], 99)))
    applies = [r["id"] for r in labels if r["score"] >= 0.5]
    # the umbrella labels never lead when a specific one applies
    order = [a for a in applies if a not in ("general_mechanical", "manufacturing_inspection", "cnc_machining")] or ["general_mechanical"]
    out = {"labels": labels, "applies": applies, "primary": order[0] if order else "general_mechanical",
           "overridden": False, "overlaps": _overlaps(applies), "package": _package(applies),
           "suggested": [r["id"] for r in labels if 0.3 <= r["score"] < 0.5]}
    if kind == "assembly":
        out["part_drawings"] = _part_drawings(model)
    return out


def _overlaps(applies: list[str]) -> list[str]:
    out = []
    pairs = [("weldment", "milling_drilling", "a weldment that is machined after welding needs a post-weld machining drawing"),
             ("structural_steel", "weldment", "structural members welded together: member details and weld details"),
             ("turning", "milling_drilling", "a turned part with milled or drilled features: one drawing, both operations"),
             ("sheet_metal", "mechanical_assembly", "a sheet-metal assembly: formed parts and an assembly drawing"),
             ("piping", "structural_steel", "pipework with supports"),
             ("mechanical_assembly", "general_arrangement", "an assembly drawing and a general arrangement serve different readers")]
    for a, b, why in pairs:
        if a in applies and b in applies:
            out.append(why)
    return out


def _package(applies: list[str]) -> list[dict]:
    seen, out = set(), []
    for a in applies:
        for d in PACKAGES.get(a, []):
            if d not in seen:
                seen.add(d)
                out.append({"drawing": d, "for": a})
    return out
