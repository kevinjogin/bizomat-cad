"""The pipeline: geometry -> engineering model -> disciplines -> reasoning -> knowledge -> dimensions -> plan, and the
benchmark evaluation. Pure Python except `recognise_part` / `recognise_assembly`, which run in the CAD worker.
"""

from __future__ import annotations

from typing import Any

from . import dimensioning, disciplines, features, knowledge, reasoning, strategy, understanding


# ----------------------------------------------------------------------------- in the CAD worker

def recognise_part(part_doc: dict) -> dict:
    """In the CAD worker: SOLIDWORKS' body (a part document holding its STEP) -> recognised features."""
    from . import facts
    f = facts.part_facts(part_doc)
    rec = features.recognise(f)
    rec["faces_total"] = sum(b["faces_total"] for b in f["bodies"])
    return rec


def recognise_assembly(asm_doc: dict, limit: int = 60) -> dict:
    """In the CAD worker: every unique part of an assembly recognised, with the components that use it."""
    from . import facts
    out = facts.assembly_facts(asm_doc, limit)
    return recognise_assembly_facts(out)


def recognise_assembly_facts(af: dict) -> dict:
    parts = {}
    for key, pf in af["parts"].items():
        if pf.get("error"):
            parts[key] = pf
            continue
        parts[key] = {"name": pf.get("name"), "recognised": features.recognise(pf)}
    bb_min = [min((p["recognised"]["bbox"]["min"][i] for p in parts.values() if "recognised" in p), default=0) for i in range(3)]
    bb_max = [max((p["recognised"]["bbox"]["max"][i] for p in parts.values() if "recognised" in p), default=0) for i in range(3)]
    return {"kind": "assembly", "parts": parts, "components": af["components"], "components_total": af.get("components_total"),
            "bbox": {"min": bb_min, "max": bb_max, "size": [round(bb_max[i] - bb_min[i], 3) for i in range(3)]}}


# ----------------------------------------------------------------------------- on the server

def analyse(kind: str, title: str | None, read: dict | None, numbers: dict | None, rec: dict,
            drawing_props: dict | None = None, override: list[str] | None = None, extra_knowledge: list[dict] | None = None) -> dict[str, Any]:
    model = understanding.build(kind, title, read, numbers, rec, drawing_props)
    cls = disciplines.classify(model, override)
    rsn = reasoning.reason(model, cls["applies"])
    topics = []
    for r in rsn["by_discipline"].values():
        topics += [t for t in r.get("knowledge_topics", []) if t not in topics]
    kb = knowledge.for_topics(topics, cls["primary"], extra=extra_knowledge, limit=10)
    dims = dimensioning.plan(model, cls["applies"])
    return {"model": model, "disciplines": cls, "reasoning": rsn, "knowledge": kb, "dimensioning": dims}


def plan(analysis: dict, **kw) -> dict:
    return strategy.make_plan(analysis["model"], analysis["disciplines"], analysis["reasoning"], analysis["dimensioning"],
                              knowledge=analysis["knowledge"], **kw)


def summary(analysis: dict) -> dict[str, Any]:
    """The analysis in the shape an AI assistant reads: what was identified, by discipline, what needs confirming."""
    m = analysis["model"]
    rec = m["recognised"]
    bodies = rec.get("bodies") or [b for p in (rec.get("parts") or {}).values() for b in (p.get("recognised") or {}).get("bodies", [])]
    feats: list[str] = []
    for b in bodies:
        tp = b.get("turned_profile")
        if tp:
            feats.append(f"turned profile about {tp['axis']}: " + " / ".join(f"Ø{s['diameter']:g}x{s['length']:g}" for s in tp["steps"]))
            feats += [f"shoulder at {s['at']:g} (Ø{s['from_diameter']:g} to Ø{s['to_diameter']:g})" for s in tp["shoulders"]]
            feats += [f"groove Ø{g['diameter']:g} x {g['width']:g} wide at {g['at']:g}" for g in tp["grooves"]]
        groups: dict[str, int] = {}
        for h in b["holes"]:
            key = {"through": f"Ø{h['diameter']:g} through", "blind": f"Ø{h['diameter']:g} x {h.get('depth', 0):g} blind ({h.get('bottom')})",
                   "counterbore": f"Ø{h['diameter']:g} counterbored Ø{h['counterbore']['diameter']:g} x {h['counterbore']['depth']:g}" if h.get("counterbore") else "",
                   "countersink": f"Ø{h['diameter']:g} countersunk Ø{h['countersink']['diameter']:g} x {h['countersink']['angle_deg']:g}°" if h.get("countersink") else "",
                   "stepped": "stepped bore " + " / ".join(f"Ø{s['diameter']:g}x{s['length']:g}" for s in h["segments"])}[h["subtype"]]
            if h.get("possible_thread"):
                key += f" (tapping size for {h['possible_thread']['thread']}?)"
            groups[key] = groups.get(key, 0) + 1
        feats += [f"{n} x hole {k}" for k, n in groups.items()]
        feats += [f"hole pattern {p['pattern'].replace('_', ' ')} of {p['count']}" + (f" on Ø{p['pcd']:g} PCD" if p.get("pcd") else "") +
                  (f", spacing {p['spacing']}" if p.get("spacing") else "") for p in b["patterns"] if p["pattern"] != "pair"]
        feats += [f"pocket {' x '.join(f'{v:g}' for v in p.get('extent', []))} x {p['depth']:g} deep" for p in b["pockets"]]
        feats += [f"step {p['depth']:g} deep" for p in b["steps"]]
        feats += [f"slot {s['width']:g} x {s['length']:g}" for s in b["slots"]]
        feats += [f"{f['count']} x {f['kind']} R{f['radius']:g}" for f in b["fillets"]]
        if b["chamfers"]:
            feats.append(f"{len(b['chamfers'])} chamfer(s)")
        if b.get("sheet_metal"):
            sm = b["sheet_metal"]
            feats.append(f"sheet metal {sm['thickness']:g} mm, {sm['bend_count']} bend(s)")
        if b.get("member"):
            mm = b["member"]
            feats.append(f"member {mm['section']} {' x '.join(f'{v:g}' for v in mm['section_size'])} x {mm['length']:g}")
        feats += [f"elbow OD {e['outside_diameter']:g}, bend radius {e['bend_radius']:g}" for e in b.get("elbows", [])]
        if b.get("flange"):
            fl = b["flange"]
            feats.append(f"flange OD {fl['outside_diameter']:g}, {fl['bolt_holes']} holes on Ø{fl['pcd']:g} PCD")
    if rec.get("contacts"):
        feats.append(f"{len(rec['contacts'])} joint(s) between bodies")
    d = analysis["disciplines"]
    return {"identified": feats,
            "disciplines": [{"id": l["id"], "name": l["name"], "score": l["score"], "why": l["reasons"]} for l in d["labels"] if l["score"] >= 0.3],
            "primary": d["primary"], "overlaps": d["overlaps"], "package": d["package"],
            "confirmed": m["confirmed"], "inferred": m["inferred"], "unknown": m["unknown"], "problems": m["problems"],
            "information_required": analysis["reasoning"]["information_required"],
            "dimension_coverage": analysis["dimensioning"]["coverage"]["coverage"],
            "knowledge": analysis["knowledge"]}


# ----------------------------------------------------------------------------- benchmarks

def _count_features(rec: dict) -> dict[str, int]:
    c: dict[str, int] = {}

    def inc(k, n=1):
        c[k] = c.get(k, 0) + n
    bodies = rec.get("bodies") or []
    if rec.get("kind") == "assembly":
        inc("component", len(rec.get("components") or []))
        names = [str(x.get("name")) for x in rec.get("components") or []]
        inc("fastener", sum(1 for n in names if understanding.FASTENER_WORDS.search(n)))
        bodies = [b for p in (rec.get("parts") or {}).values() for b in (p.get("recognised") or {}).get("bodies", [])]
    for b in bodies:
        for h in b["holes"]:
            inc(f"hole:{h['subtype']}")
        for p in b["patterns"]:
            inc(f"pattern:{p['pattern']}")
        if b.get("turned_profile"):
            inc("turned_profile")
            inc("shoulder", len(b["turned_profile"]["shoulders"]))
            inc("groove", len(b["turned_profile"]["grooves"]))
        inc("pocket", len(b["pockets"]))
        inc("step", len(b["steps"]))
        inc("slot", len(b["slots"]))
        if b.get("sheet_metal"):
            inc("sheet_metal")
        if b.get("member"):
            inc("member")
            inc(f"member:{b['member']['section']}")
        inc("elbow", len(b.get("elbows", [])))
        if b.get("flange"):
            inc("flange")
    inc("contact", len(rec.get("contacts") or []))
    return c


def evaluate_case(case: dict) -> dict[str, Any]:
    """One benchmark case through recognition, classification and view selection, scored against its `expect`."""
    from . import benchmarks
    f = benchmarks.build_facts(case)
    if f.get("kind") == "assembly":
        rec = recognise_assembly_facts(f)
        kind = "assembly"
        read = {"features": []}
    else:
        rec = features.recognise(f)
        kind = "part"
        read = {"features": []}
    ana = analyse(kind, case["name"], read, {}, rec)
    pl = plan(ana, doc=None)
    exp = case["expect"]
    got = _count_features(rec)
    feat_hits, feat_total = 0, 0
    misses = []
    for k, n in exp["features"].items():
        alts = k.split("|") if ":" not in k or "|" not in k.split(":")[1] else [k.split(":")[0] + ":" + s for s in k.split(":")[1].split("|")]
        have = sum(got.get(a, 0) for a in alts)
        feat_total += n
        feat_hits += min(n, have)
        if have < n:
            misses.append(f"{k}: {have} of {n}")
    applies = ana["disciplines"]["applies"]
    disc_ok = all(d in applies for d in exp["disciplines"])
    main = pl["views"][0]["orientation"] if pl["views"] else None
    if exp["main_view"] == "assembly":
        view_ok = kind == "assembly"
    else:
        allowed = {strategy.VIEW_ALONG[a] for a in exp["main_view"].split("|")}
        if any(b.get("turned_profile") for b in rec.get("bodies", [])):
            allowed |= {"front", "right"}
        view_ok = main in allowed
    sec_ok = bool(pl["sections"]) == bool(exp["sections"])
    return {"name": case["name"], "category": case["category"], "label": "synthetic",
            "feature_recall": round(feat_hits / feat_total, 3) if feat_total else 1.0, "feature_misses": misses,
            "disciplines_ok": disc_ok, "disciplines": applies, "expected_disciplines": exp["disciplines"],
            "main_view_ok": view_ok, "main_view": main, "views": [v["orientation"] for v in pl["views"]],
            "sections_ok": sec_ok, "sections": len(pl["sections"]), "questions": [q["id"] for q in pl["questions"]],
            "release_blocked": pl["release_blocked"]}


def run_benchmarks(names: list[str] | None = None) -> dict[str, Any]:
    from . import benchmarks
    cases = [c for c in benchmarks.CASES if not names or c["name"] in names]
    rows = [evaluate_case(c) for c in cases]
    n = len(rows) or 1
    return {"label": benchmarks.SYNTHETIC, "cases": rows,
            "feature_recall": round(sum(r["feature_recall"] for r in rows) / n, 3),
            "discipline_accuracy": round(sum(r["disciplines_ok"] for r in rows) / n, 3),
            "main_view_accuracy": round(sum(r["main_view_ok"] for r in rows) / n, 3),
            "section_decision_accuracy": round(sum(r["sections_ok"] for r in rows) / n, 3)}
