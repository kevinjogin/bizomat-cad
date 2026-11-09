"""Module A, the engineering model: what the model is, from its geometry and from SOLIDWORKS' design information.

Inputs, all from existing commands: `read` (feature tree with SOLIDWORKS type names, sketch states, dimensions,
equations, body numbers), `read` with numbers (material, mass), the recognised features (features.py), and
optionally the drawing's title-block fields. Output: one structured object in which every statement says whether it
is CONFIRMED (stated by the model or the user), INFERRED (deduced, with its basis and a confidence) or UNKNOWN (the
model cannot say; a question for the user). Nothing is invented.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# SOLIDWORKS feature type names (IFeature.GetTypeName2) -> what they tell a drafter
SW_TYPES: dict[str, tuple[str, str]] = {
    "HoleWzd": ("hole_wizard", "Hole Wizard hole: its standard, size and thread are defined in SOLIDWORKS"),
    "AdvHoleWzd": ("hole_wizard", "Advanced Hole: its elements are defined in SOLIDWORKS"),
    "CosmeticThread": ("thread", "cosmetic thread: the thread is defined in the model"),
    "Thread": ("thread", "Thread feature: a modelled thread"),
    "ICE": ("cut_extrude", "cut extrude"), "Cut": ("cut_extrude", "cut extrude"),
    "Extrusion": ("boss_extrude", "boss extrude"), "Boss": ("boss_extrude", "boss extrude"),
    "Revolution": ("revolve", "revolved boss: suggests a turned shape"),
    "RevCut": ("revolve_cut", "revolved cut: suggests turning or boring"),
    "Fillet": ("fillet", "fillet"), "VarFillet": ("fillet", "variable fillet"), "Chamfer": ("chamfer", "chamfer"),
    "LPattern": ("pattern", "linear pattern"), "CirPattern": ("pattern", "circular pattern"),
    "MirrorPattern": ("pattern", "mirror"), "LocalLPattern": ("pattern", "linear pattern"),
    "LocalCirPattern": ("pattern", "circular pattern"), "SketchPattern": ("pattern", "sketch-driven pattern"),
    "TablePattern": ("pattern", "table-driven pattern"), "CurvePattern": ("pattern", "curve-driven pattern"),
    "Shell": ("shell", "shell: thin walls"), "Draft": ("draft", "draft: suggests casting or moulding"),
    "Rib": ("rib", "rib"), "Sweep": ("sweep", "sweep"), "SweepCut": ("sweep_cut", "swept cut"),
    "Blend": ("loft", "loft"), "BlendCut": ("loft_cut", "lofted cut"),
    "WeldMemberFeat": ("weld_member", "weldment structural member"), "WeldmentFeature": ("weldment", "weldment part"),
    "Weldment": ("weldment", "weldment part"), "FilletBead": ("weld_bead", "fillet weld bead"),
    "WeldBeadFeat": ("weld_bead", "weld bead"), "Gusset": ("gusset", "weldment gusset"), "EndCap": ("end_cap", "end cap"),
    "WeldCornerFeat": ("weld_trim", "weldment corner treatment"), "TrimExtendFeat": ("weld_trim", "trim/extend"),
    "SheetMetal": ("sheet_metal", "sheet-metal definition (thickness, bend radius, K-factor in SOLIDWORKS)"),
    "SMBaseFlange": ("sheet_metal", "base flange"), "EdgeFlange": ("sheet_metal", "edge flange"),
    "SketchBend": ("sheet_metal", "sketched bend"), "FlatPattern": ("flat_pattern", "flat pattern"),
    "SMMiteredFlange": ("sheet_metal", "mitre flange"), "Hem": ("sheet_metal", "hem"), "Jog": ("sheet_metal", "jog"),
    "OneBend": ("sheet_metal", "bend"), "ProcessBends": ("sheet_metal", "processed bends"),
    "FormToolInstance": ("sheet_metal", "forming tool"), "LoftedBend": ("sheet_metal", "lofted bend"),
    "Imported": ("imported", "imported body: no design history"), "BaseBody": ("imported", "imported body"),
    "Split": ("multibody", "split body"), "Combine": ("multibody", "combined bodies"),
    "MoveCopyBody": ("multibody", "moved or copied body"),
    "RefPlane": ("reference", "reference plane"), "RefAxis": ("reference", "reference axis"),
    "ProfileFeature": ("sketch", "sketch"), "3DProfileFeature": ("sketch", "3D sketch"),
    "Attribute": ("attribute", "attribute"),
}

# Words in feature and sketch names that state intent (names are the designer's own words)
INTENT_WORDS = [
    (r"\bM(\d{1,2})(?:\s*[x×]\s*(\d+(?:\.\d+)?))?\b", "metric_size"),
    (r"\btap(?:ped|ping)?\b|\bthread(?:ed)?\b", "thread"),
    (r"\bclear(?:ance)?\b|\bclr\b", "clearance"),
    (r"c'?bore|counter\s*bore", "counterbore"),
    (r"\bcsk\b|counter\s*sink", "countersink"),
    (r"\bream(?:ed)?\b|\bdowel\b|\b[HhGgFfJjKkMmNnPp]\d{1,2}\b(?=.*(?:fit|bore|hole|ream))|\bfit\b", "precision_fit"),
    (r"\bbearing\b|\bseat\b|\bbush(?:ing)?\b|\bjournal\b", "bearing_seat"),
    (r"\bweld\b|\bbead\b", "weld"),
    (r"\bbend\b|\bflange\b(?!.*pipe)|\bhem\b", "sheet_metal_word"),
    (r"\bpipe\b|\belbow\b|\bspool\b|\bnozzle\b", "piping"),
    (r"\blift(?:ing)?\b|\blug\b|\beye\b", "lifting"),
    (r"\blocat(?:e|ing|ion)\b|\bdatum\b|\bspigot\b", "locating"),
    (r"\bkey(?:way|seat)?\b|\bcirclip\b|\bretaining\b|\bgroove\b", "shaft_feature"),
]

FASTENER_WORDS = re.compile(r"(?i)\b(screw|bolt|nut|washer|stud|rivet|pin|circlip|iso\s*\d{3,5}|din\s*\d{2,5}|as\s*1111|as\s*1112|shcs|m\d{1,2}\s*[x×]\s*\d+)\b")
DENSITY_G_CM3 = {"steel": 7.85, "stainless": 7.95, "aluminium": 2.70, "aluminum": 2.70, "brass": 8.5, "bronze": 8.8,
                 "copper": 8.96, "titanium": 4.5, "cast iron": 7.2, "plastic": 1.2, "nylon": 1.14, "pa66": 1.14}


def _category(sw_type: str) -> tuple[str, str]:
    return SW_TYPES.get(sw_type, ("other", sw_type))


def dedupe_dimensions(dims: list[dict] | None) -> list[dict]:
    """The model's dimensions once each (the add-in lists a dimension once per feature that shows it)."""
    out, seen = [], set()
    for d in dims or []:
        n = d.get("name")
        if not n or n in seen:
            continue
        seen.add(n)
        parts = n.split("@")
        out.append({"name": n, "value": d.get("value"), "unit": d.get("unit", "mm"),
                    "dim": parts[0], "owner": parts[1] if len(parts) > 1 else None})
    return out


def intent_from_name(name: str) -> list[dict]:
    hits = []
    for pat, kind in INTENT_WORDS:
        m = re.search(pat, name, flags=re.IGNORECASE)
        if m:
            row = {"kind": kind, "text": m.group(0)}
            if kind == "metric_size":
                row["size"] = f"M{m.group(1)}" + (f"x{m.group(2)}" if m.group(2) else "")
            hits.append(row)
    return hits


def _material_class(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if re.search(r"\b1\.\d{4}\b|\bc\d{2}\b|\bs\d{3}\b|\bsteel\b|\b(4140|1045|1020|350|300plus|aisi|en\d+)\b", t):
        return "stainless" if re.search(r"stainless|\b1\.4\d{3}\b|\b30[0-9]\b|\b316\b", t) else "steel"
    for k in ("aluminium", "aluminum", "brass", "bronze", "copper", "titanium", "cast iron", "nylon", "pa66", "plastic"):
        if k in t:
            return k
    if re.search(r"\b(5083|6061|6082|7075|2024)\b", t):
        return "aluminium"
    return None


def _holes_named(rec: dict, read: dict, dims: list[dict]) -> None:
    """Attach the names of the sketches and cut features that made each hole (matched by diameter and depth to the
    dimensions those features own), with the intent their names state."""
    by_owner: dict[str, list[float]] = {}
    for d in dims:
        if d.get("owner") and isinstance(d.get("value"), (int, float)):
            by_owner.setdefault(d["owner"], []).append(float(d["value"]))
    feats = (read or {}).get("features") or []
    uses = {f.get("name"): f.get("uses") or [] for f in feats}
    for b in rec.get("bodies", []):
        for h in b.get("holes", []):
            sizes = {h["diameter"]} | {s["diameter"] for s in h.get("segments", [])}
            if h.get("counterbore"):
                sizes.add(h["counterbore"]["diameter"])
            depths = {h.get("depth"), (h.get("counterbore") or {}).get("depth")} - {None}
            named = []
            for owner, vals in by_owner.items():
                if any(abs(v - s) <= 0.01 for v in vals for s in sizes):
                    named.append(owner)
            # a cut feature's depth, through the sketch it uses
            for fname, sk in uses.items():
                if any(s in named for s in sk) and any(abs(v - dp) <= 0.01 for v in by_owner.get(fname, []) for dp in depths):
                    named.append(fname)
            if named:
                h["named_by"] = sorted(set(named))
                intents = [i for n in named for i in intent_from_name(n)]
                if intents:
                    h["name_intent"] = intents
                    sizes_named = [i["size"] for i in intents if i["kind"] == "metric_size"]
                    threaded = any(i["kind"] == "thread" for i in intents)
                    if h.get("possible_thread") and threaded:
                        th = h["possible_thread"]
                        if not sizes_named or th["thread"] in [s.split("x")[0] for s in sizes_named]:
                            th["confidence"] = "medium"
                            th["basis"] += f"; the feature is named {', '.join(sorted(set(named)))}"
                    if any(i["kind"] == "clearance" for i in intents) and h.get("possible_clearance"):
                        h["possible_clearance"]["confidence"] = "medium"


def build(kind: str, title: str | None, read: dict | None, numbers: dict | None, rec: dict,
          drawing_props: dict | None = None) -> dict[str, Any]:
    confirmed: list[dict] = []
    inferred: list[dict] = []
    unknown: list[dict] = []
    problems: list[dict] = []
    read = read or {}
    numbers = numbers or {}
    dims = dedupe_dimensions(read.get("dimensions"))
    feats = []
    for f in read.get("features") or []:
        cat, what = _category(str(f.get("type")))
        row = {"name": f.get("name"), "sw_type": f.get("type"), "category": cat, "what": what}
        if f.get("suppressed"):
            row["suppressed"] = True
        if f.get("state"):
            row["state"] = f["state"]
            problems.append({"kind": "rebuild", "feature": f.get("name"), "state": f["state"], "reason": f.get("reason"),
                             "severity": "blocker" if f["state"] == "error" else "major"})
        intents = intent_from_name(str(f.get("name") or ""))
        if intents:
            row["name_intent"] = intents
        feats.append(row)
    cats = Counter(f["category"] for f in feats if not f.get("suppressed"))
    sketches = read.get("sketches") or {}
    sk_states = Counter((v or {}).get("state", "unknown") for v in sketches.values())
    for name, v in sketches.items():
        st = (v or {}).get("state")
        if st and st != "fully defined":
            problems.append({"kind": "sketch", "sketch": name, "state": st, "severity": "minor",
                             "why": "an under- or over-defined sketch can move when the model changes, and the drawing with it"})
    if kind == "part":
        _holes_named(rec, read, dims)
    body = numbers.get("body") or read.get("body") or {}
    details = read.get("details") or numbers.get("details") or {}
    tb_material = (drawing_props or {}).get("Material")
    vol = body.get("volume_mm3") or rec.get("volume")
    mass_g = body.get("mass_g")
    material, material_read = _material_and_mass(kind, read, numbers, details, tb_material, body, vol, mass_g,
                                                 confirmed, inferred, unknown, problems)
    size = (rec.get("bbox") or {}).get("size") or body.get("bbox", {}).get("size")
    if size:
        confirmed.append({"what": "overall size", "value": size, "unit": "mm", "source": "geometry (bounding box)"})
    # thread, fit and weld intent: inferred, never confirmed, unless SOLIDWORKS defines it
    if cats.get("thread") or cats.get("hole_wizard"):
        confirmed.append({"what": "threads or standard holes", "value": f"{cats.get('thread', 0)} thread and "
                                                                       f"{cats.get('hole_wizard', 0)} Hole Wizard feature(s)",
                          "source": "SOLIDWORKS feature tree"})
    grouped: dict[tuple, dict] = {}
    for b in rec.get("bodies", []):
        for h in b.get("holes", []):
            for key, what in (("possible_thread", "may be tapped {thread}"), ("possible_clearance", "may be clearance holes for {bolt}")):
                if h.get(key):
                    hint = h[key]
                    k = (key, hint.get("thread") or hint.get("bolt"), hint["confidence"], h["diameter"])
                    row = grouped.setdefault(k, {"what": what.format(**hint), "basis": hint["basis"], "confidence": hint["confidence"],
                                                 "features": []})
                    row["features"].append(h["id"])
    for row in grouped.values():
        row["what"] = f"hole(s) {', '.join(row['features'])} " + row["what"]
        inferred.append(row)
    defined = _thread_definitions(details, rec, confirmed)
    threads_unconfirmed = [h["id"] for b in rec.get("bodies", []) for h in b.get("holes", []) if h.get("possible_thread")
                           and h["id"] not in defined]
    if threads_unconfirmed and not cats.get("thread"):
        why = "the geometry holds plain holes at tapping-drill size; a workshop cannot guess a thread"
        if cats.get("hole_wizard"):
            why += " (the model has Hole Wizard holes, whose thread specification the add-in does not read yet)"
        unknown.append({"what": "threads", "features": threads_unconfirmed, "blocking": True,
                        "question": "Are these holes tapped? If so: thread size, pitch, class and full-thread depth.", "why": why})
    if cats.get("weld_member") or cats.get("weldment") or (rec.get("body_count", 1) > 1 and rec.get("contacts")):
        if not cats.get("weld_bead"):
            unknown.append({"what": "welds", "blocking": True,
                            "question": "Weld type, size, length and quality requirements for each joint (and the welding standard).",
                            "why": "weld sizes and quality come from the design, never from the drawing tool"})
    unknown.append({"what": "general tolerance", "blocking": True,
                    "question": "Which general tolerance applies to dimensions without their own tolerance?",
                    "why": "every manufacturing drawing needs one; it is not stored in the model"})
    units = details.get("units") or {}
    if units and units.get("length") not in (None, "mm"):
        problems.append({"kind": "units", "severity": "major",
                         "why": f"The document's length unit is {units.get('length')}: the drawing's dimensions show in it. Confirm that is intended."})
    tolerances = {d["name"]: d["tolerance"] for d in details.get("dimensions") or [] if d.get("tolerance")}
    if tolerances:
        confirmed.append({"what": "dimension tolerances in the model", "value": len(tolerances), "source": "SOLIDWORKS dimensions",
                          "dimensions": tolerances})
    out = {
        "kind": kind, "title": title, "units": "mm",
        "overall": {"size": size, "volume_mm3": vol, "mass_g": mass_g, "material": material or tb_material,
                    "material_read_from_part": material_read,
                    "body_count": rec.get("body_count", 1) if kind == "part" else None},
        "design": {"features": feats, "feature_categories": dict(cats), "sketches": {"total": len(sketches), **dict(sk_states)},
                   "dimensions": dims, "dimension_count": len(dims), "equations": read.get("equations") or [],
                   "configurations": details.get("configurations", "not read (add-in 0.15 reads them with details=true)"),
                   "custom_properties": details.get("custom_properties", "not read (add-in 0.15 reads them with details=true)"),
                   "units": units or "not read", "tolerances": tolerances, "hole_wizard": details.get("holes") or [],
                   "cosmetic_threads": details.get("threads") or [], "cut_list": details.get("cut_list") or [],
                   "details_read": bool(details)},
        "recognised": rec,
        "confirmed": confirmed, "inferred": inferred, "unknown": unknown, "problems": problems,
    }
    if kind == "assembly":
        comps = rec.get("components") or []
        fasteners = [c["name"] for c in comps if FASTENER_WORDS.search(str(c.get("name") or ""))]
        out["assembly"] = {"components": len(comps), "fasteners": fasteners,
                           "unique_parts": len(rec.get("parts") or {}),
                           "mates": (read.get("mates") if isinstance(read.get("mates"), list) else None)}
    return out


def _material_and_mass(kind, read, numbers, details, tb_material, body, vol, mass_g, confirmed, inferred, unknown, problems):
    """Material and mass from what SOLIDWORKS reported, and only that. Returns (material, read_from_part).

    With details (add-in 0.15): the material per configuration with an explicit `assigned`, and the mass chain in
    stated units (mass, volume, density, overrides). Without them (older add-ins), an empty material is simply
    left out of the read, so a missing material is NOT evidence that none is assigned, and nothing is claimed."""
    if kind != "part":
        return None, False
    mat = (details.get("material") or {}).get("active") if details else None
    material = None
    read_from_part = False
    if mat is not None:
        read_from_part = True
        if mat.get("assigned"):
            material = mat.get("name")
            confirmed.append({"what": "material", "value": material, "source": "SOLIDWORKS part material (read with details)",
                              "database": mat.get("database")})
        elif tb_material:
            confirmed.append({"what": "material", "value": tb_material, "source": "drawing title block"})
            problems.append({"kind": "material", "severity": "major",
                             "why": f"SOLIDWORKS reports no material assigned in the part, while the title block says {tb_material}: "
                                    "mass properties and the bill of materials do not know it (Edit Material in SOLIDWORKS)."})
        else:
            unknown.append({"what": "material", "question": "What is the material (and its standard or grade)?", "blocking": True,
                            "why": "SOLIDWORKS reports no material assigned, and a manufacturing drawing must state it"})
    else:
        material = numbers.get("material") or (read.get("material") if isinstance(read.get("material"), str) else None)
        if material:
            read_from_part = True
            confirmed.append({"what": "material", "value": material, "source": "SOLIDWORKS part material"})
        elif tb_material:
            confirmed.append({"what": "material", "value": tb_material, "source": "drawing title block"})
            problems.append({"kind": "material_unverified", "severity": "info",
                             "why": "The part's own material was not read: add-ins before 0.15 leave an empty material out of the read, so "
                                    "whether one is assigned is not known. Read with details (add-in 0.15) to check."})
        else:
            unknown.append({"what": "material", "question": "What is the material (and its standard or grade)?", "blocking": True,
                            "why": "no material was read from the part or the title block"})
    stated = material or tb_material
    cls = _material_class(stated)
    expect = DENSITY_G_CM3.get(cls) if cls else None
    mp = details.get("mass_properties") if details else None
    if mp and not mp.get("error"):
        dens = (mp.get("density") or {}).get("value")              # g/cm3, as SOLIDWORKS uses it
        implied = (mp.get("density_from_mass_and_volume") or {}).get("value")   # kg/m3
        inferred.append({"what": "mass properties", "source": "SOLIDWORKS IMassProperty, system units, converted by the add-in",
                         "mass": mp.get("mass"), "volume": mp.get("volume"), "density": mp.get("density"),
                         "override_mass": mp.get("override_mass"), "confidence": "high"})
        if mp.get("override_mass") or mp.get("user_assigned"):
            problems.append({"kind": "mass", "severity": "info",
                             "why": "The mass is overridden or assigned by hand in SOLIDWORKS: it is not computed from the geometry and material."})
        elif mp.get("consistent") is False:
            problems.append({"kind": "mass", "severity": "major",
                             "why": f"SOLIDWORKS' mass and density disagree (density {dens} g/cm3, mass/volume {implied} kg/m3): check "
                                    "Evaluate > Mass Properties for an override."})
        doc_dens = ((details.get("material") or {}).get("document_density") or {}).get("value")   # kg/m3
        if mat is not None and not mat.get("assigned") and doc_dens and dens and abs(doc_dens / 1000.0 - dens) <= 1e-6 * max(1.0, dens):
            problems.append({"kind": "mass", "severity": "info",
                             "why": f"No material is assigned, so SOLIDWORKS computes the mass with the document density of {doc_dens:g} "
                                    "kg/m3 (Document Properties > Material Properties). The mass is not the part's real mass."})
        if expect and dens and not (0.6 * expect <= dens <= 1.5 * expect):
            problems.append({"kind": "mass", "severity": "major",
                             "why": f"SOLIDWORKS uses a density of {dens} g/cm3 for this part; {stated} is about {expect} g/cm3. The "
                                    "assigned material (or the document density used when none is assigned) does not match the stated material."})
    elif vol and mass_g is not None and vol > 0:
        dens = mass_g / (vol / 1000.0)
        inferred.append({"what": "density from mass and volume", "value": round(dens, 6), "unit": "g/cm3", "confidence": "medium",
                         "source": "SOLIDWORKS mass and volume as an add-in before 0.15 reports them",
                         "basis": f"{mass_g:g} g / {vol / 1000:.1f} cm3"})
        if expect and not (0.6 * expect <= dens <= 1.5 * expect):
            problems.append({"kind": "mass_unverified", "severity": "info",
                             "why": f"SOLIDWORKS reports {mass_g:g} g for {vol / 1000:.1f} cm3 ({dens:.4g} g/cm3); {stated} is about {expect} g/cm3. "
                                    "The cause is not known from this read (material, document density or a mass override): read with "
                                    "details (add-in 0.15), which reports the material, the density and any override."})
    return material, read_from_part


def _thread_definitions(details: dict, rec: dict, confirmed: list) -> set[str]:
    """Holes whose threads SOLIDWORKS defines (Hole Wizard tapped holes, cosmetic threads), matched to recognised
    holes by tap-drill diameter. Returns the ids of the holes that are confirmed."""
    out: set[str] = set()
    specs = []
    for h in (details or {}).get("holes") or []:
        if h.get("threaded"):
            specs.append({"size": h.get("size"), "class": h.get("thread_class"), "depth": h.get("thread_depth"),
                          "drill": h.get("tap_drill_diameter") or h.get("hole_diameter"), "source": f"Hole Wizard {h.get('feature')}",
                          "standard": h.get("standard")})
    for c in (details or {}).get("threads") or []:
        specs.append({"size": c.get("size"), "callout": c.get("callout"), "depth": (c.get("depth") or {}).get("value"),
                      "drill": None, "source": f"cosmetic thread {c.get('feature')}"})
    if not specs:
        return out
    for sp in specs:
        confirmed.append({"what": "thread", "value": sp.get("callout") or " ".join(str(x) for x in (sp.get("size"), sp.get("class")) if x),
                          "depth_mm": sp.get("depth"), "source": sp["source"]})
    for b in rec.get("bodies", []):
        for h in b.get("holes", []):
            for sp in specs:
                if sp.get("drill") and abs(h["diameter"] - float(sp["drill"])) <= 0.05:
                    h["thread_spec"] = sp
                    out.add(h["id"])
    return out
