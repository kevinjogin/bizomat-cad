"""Module A, recognition: engineering features from the geometry facts (facts.py), deterministically.

Pure Python (no OpenCascade), so it is tested on hand-made facts as well as on real bodies. Every feature carries
its geometric reference (faces, axis, position), its measured sizes, a confidence and its source ("geometry").
Nothing is guessed beyond what the faces show: a hole whose diameter matches a tapping drill is reported as a
plain hole with a `possible_thread` hint, never as a thread.

Recognised: holes (through, blind with flat or drilled bottom, counterbored, countersunk, stepped), hole patterns
(pitch circle, linear, grid, pair), slots, pockets and steps, a turned profile (diameters, shoulders, grooves,
tapers, end chamfers), bosses, fillets, chamfers, wall thickness, sheet-metal evidence (constant thickness, bends),
structural member evidence per body (elongated prismatic bodies: section class, length, end cuts) and body contacts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

TOL = 0.05          # mm: positions and sizes that are "the same"
ANG = 1.5           # degrees: directions that are "the same"

# Tapping drill diameters for ISO metric coarse threads (widely published workshop values; to be confirmed against
# the shop's own table). Used only as a hint that a plain hole may be meant to be tapped.
TAP_DRILL = {2.5: "M3", 3.3: "M4", 4.2: "M5", 5.0: "M6", 6.8: "M8", 8.5: "M10", 10.2: "M12", 12.0: "M14",
             14.0: "M16", 15.5: "M18", 17.5: "M20", 21.0: "M24", 26.5: "M30"}
# Clearance holes for metric bolts, ISO 273 series fine / medium / coarse (widely published values; verify).
CLEARANCE = {"M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0),
             "M8": (8.4, 9.0, 10.0), "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M16": (17.0, 17.5, 18.5),
             "M20": (21.0, 22.0, 24.0), "M24": (25.0, 26.0, 28.0), "M30": (31.0, 33.0, 35.0)}


# ----------------------------------------------------------------------------- small vector helpers

def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _mul(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a) or 1.0
    return [a[0] / n, a[1] / n, a[2] / n]


def _r(v, n=3) -> float:
    return round(float(v), n) + 0.0


def canon_dir(d) -> list[float]:
    """A direction with its sign fixed (largest component positive), so opposite directions compare equal."""
    d = _unit(d)
    k = max(range(3), key=lambda i: abs(d[i]))
    return d if d[k] > 0 else _mul(d, -1.0)


def axis_name(d) -> str | None:
    """'x', 'y' or 'z' when the direction is one of the model's axes."""
    d = canon_dir(d)
    for i, n in enumerate("xyz"):
        if abs(d[i]) > math.cos(math.radians(ANG)):
            return n
    return None


def _same_dir(a, b) -> bool:
    return abs(_dot(_unit(a), _unit(b))) > math.cos(math.radians(ANG))


def _line(axis: dict) -> tuple[list[float], list[float]]:
    """(canonical direction, foot point: the axis point nearest the origin)."""
    d = canon_dir(axis["dir"])
    p = axis["point"]
    foot = _sub(p, _mul(d, _dot(p, d)))
    return d, foot


def _abs_span(face: dict) -> tuple[float, float]:
    """The face's span along its canonical axis direction, in absolute coordinates (t = point . dir)."""
    d0 = _unit(face["axis"]["dir"])
    d = canon_dir(d0)
    s = 1.0 if _dot(d0, d) > 0 else -1.0
    base = _dot(face["axis"]["point"], d)
    a, b = face.get("span") or [0.0, 0.0]
    t1, t2 = base + s * a, base + s * b
    return (min(t1, t2), max(t1, t2))


def _line_key(d, foot) -> tuple:
    return (round(d[0], 3), round(d[1], 3), round(d[2], 3), round(foot[0], 2), round(foot[1], 2), round(foot[2], 2))


def _plane_t(face: dict, d) -> float | None:
    """A planar face's position along direction d, when its normal is parallel to d."""
    n = face.get("normal")
    if not n or not _same_dir(n, d):
        return None
    return _dot(face["point"], canon_dir(d))


# ----------------------------------------------------------------------------- surfaces of revolution

def merge_revolved(body: dict) -> list[dict]:
    """Cylinders and cones of one body, with the halves a STEP export splits them into merged back together."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in body["faces"]:
        if f["type"] not in ("cylinder", "cone") or "axis" not in f:
            continue
        d, foot = _line(f["axis"])
        if f["type"] == "cylinder":
            size = round(f.get("radius", 0.0), 2)
        else:
            size = (round(f.get("semi_angle_deg", 0.0), 1),) + tuple(round(r, 2) for r in sorted(f.get("radii") or [0, 0]))
        key = _line_key(d, foot) + (f["type"], size, bool(f.get("concave")))
        groups[key].append(f)
    out = []
    for key, faces in groups.items():
        spans = sorted(_abs_span(f) for f in faces)
        # faces of one surface overlap in span (two halves) or touch (a surface cut in two by a cross feature)
        merged: list[list] = []
        for a, b in spans:
            if merged and a <= merged[-1][1] + TOL:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        f0 = faces[0]
        d, foot = _line(f0["axis"])
        for a, b in merged:
            ids = [f["i"] for f in faces if _abs_span(f)[0] >= a - TOL and _abs_span(f)[1] <= b + TOL]
            area = sum(f["area"] for f in faces if f["i"] in ids)
            row = {"type": f0["type"], "dir": d, "foot": foot, "t": [a, b], "faces": ids, "area": area,
                   "concave": bool(f0.get("concave"))}
            if f0["type"] == "cylinder":
                r = f0.get("radius", 0.0)
                row["radius"] = r
                full = 2 * math.pi * r * max(b - a, 1e-9)
                row["coverage"] = _r(area / full, 3) if full > 0 else 0.0  # 1 = a whole cylinder, 0.5 = a half
            else:
                row["semi_angle_deg"] = f0.get("semi_angle_deg")
                rr = f0.get("radii") or [0.0, 0.0]
                row["radii"] = sorted(rr)
            out.append(row)
    return out


def _on_axis(f: dict, d, foot, tol: float = 0.2) -> bool:
    """Is the planar face centred on the axis (d, foot)?"""
    c = f.get("center") or f["point"]
    off = _sub(c, foot)
    return _norm(_sub(off, _mul(d, _dot(off, d)))) <= tol


def _floor_at(body: dict, d, foot, t: float, radius: float) -> dict | None:
    """A flat-bottom face of a blind hole: a planar disc at t on the hole's axis, about pi r^2."""
    want = math.pi * radius * radius
    for f in body["faces"]:
        if f["type"] != "plane":
            continue
        pt = _plane_t(f, d)
        if pt is None or abs(pt - t) > TOL or not _on_axis(f, d, foot):
            continue
        if abs(f["area"] - want) <= max(0.02 * want, 0.05) and f.get("loops", 1) == 1:
            return f
    return None


def _annulus_at(body: dict, d, foot, t: float, r1: float, r2: float) -> dict | None:
    want = math.pi * abs(r2 * r2 - r1 * r1)
    for f in body["faces"]:
        if f["type"] != "plane":
            continue
        pt = _plane_t(f, d)
        if pt is not None and abs(pt - t) <= TOL and _on_axis(f, d, foot) and abs(f["area"] - want) <= max(0.03 * want, 0.1):
            return f
    return None


def _thread_hint(dia: float) -> dict | None:
    for drill, m in TAP_DRILL.items():
        if abs(dia - drill) <= 0.06:
            return {"thread": m, "basis": f"diameter {dia:g} mm is the usual tapping drill for {m} coarse",
                    "confidence": "low", "status": "inferred: confirm the thread and its depth"}
    return None


def _clearance_hint(dia: float) -> dict | None:
    for m, (fine, med, coarse) in CLEARANCE.items():
        for series, v in (("fine", fine), ("medium", med), ("coarse", coarse)):
            if abs(dia - v) <= 0.06:
                return {"bolt": m, "series": series, "basis": f"diameter {dia:g} mm is the ISO 273 {series} clearance for {m}",
                        "confidence": "low", "status": "inferred"}
    return None


def recognise_holes(body: dict, revolved: list[dict]) -> list[dict]:
    """Coaxial concave cylinders and cones, stacked along their axis, as holes."""
    lines: dict[tuple, list[dict]] = defaultdict(list)
    for s in revolved:
        if s["concave"]:
            lines[_line_key(s["dir"], s["foot"])].append(s)
    holes = []
    for key, segs in lines.items():
        cyl = sorted([s for s in segs if s["type"] == "cylinder" and s.get("coverage", 1) > 0.9], key=lambda s: s["t"][0])
        if not cyl:
            continue
        cones = [s for s in segs if s["type"] == "cone"]
        d, foot = cyl[0]["dir"], cyl[0]["foot"]
        # chains of segments that touch (or meet through a cone or a step)
        chains: list[list[dict]] = []
        for s in cyl:
            joined = False
            if chains:
                last = chains[-1][-1]
                gap = s["t"][0] - last["t"][1]
                if gap <= TOL or any(c["t"][0] >= last["t"][1] - TOL and c["t"][1] <= s["t"][0] + TOL for c in cones):
                    chains[-1].append(s)
                    joined = True
            if not joined:
                chains.append([s])
        for chain in chains:
            t0, t1 = chain[0]["t"][0], chain[-1]["t"][1]
            ends = {}
            for side, t, seg in (("low", t0, chain[0]), ("high", t1, chain[-1])):
                r = seg["radius"]
                cone = next((c for c in cones if abs((c["t"][0] if side == "high" else c["t"][1]) - t) <= TOL
                             and c["radii"][1] <= r + TOL), None)
                if cone is not None and 50 <= (cone.get("semi_angle_deg") or 0) <= 70 and cone["radii"][0] < 0.3 * r:
                    ends[side] = {"bottom": "drill_point", "angle_deg": _r(2 * cone["semi_angle_deg"], 1), "faces": cone["faces"]}
                    continue
                fl = _floor_at(body, d, foot, t, r)
                if fl is not None:
                    ends[side] = {"bottom": "flat", "faces": [fl["i"]]}
                    continue
                csk = next((c for c in cones if abs((c["t"][0] if side == "high" else c["t"][1]) - t) <= TOL
                            and abs(c["radii"][0] - r) <= TOL and c["radii"][1] > r + TOL), None)
                if csk is not None:
                    big = csk["radii"][1]
                    kind = "countersink" if big >= 1.25 * r else "chamfer"
                    ends[side] = {"bottom": "open", "entry": kind, "diameter": _r(2 * big),
                                  "angle_deg": _r(2 * (csk.get("semi_angle_deg") or 45), 1), "faces": csk["faces"]}
                    continue
                ends[side] = {"bottom": "open"}
            segs_out = [{"diameter": _r(2 * s["radius"]), "from": _r(s["t"][0]), "to": _r(s["t"][1]),
                         "length": _r(s["t"][1] - s["t"][0]), "faces": s["faces"]} for s in chain]
            open_ends = [k for k, v in ends.items() if v["bottom"] == "open"]
            closed = [k for k, v in ends.items() if v["bottom"] != "open"]
            through = len(open_ends) == 2
            if through:
                # a counterbore or countersink marks the side it is drilled from
                entry = "low" if (chain[0]["radius"] >= chain[-1]["radius"] and "entry" not in ends["high"]) \
                    or "entry" in ends["low"] else "high"
            else:
                entry = "high" if closed and closed[0] == "low" else "low"
            # the entry is the open end; order the segments from the entry inwards
            ordered = segs_out if entry == "low" else list(reversed(segs_out))
            main = ordered[-1] if not through else min(ordered, key=lambda s: s["diameter"])
            subtype = "through" if through else "blind"
            h: dict[str, Any] = {"kind": "hole", "axis": axis_name(d) or [_r(x, 4) for x in d], "dir": [_r(x, 4) for x in d],
                                 "line_key": key, "diameter": main["diameter"], "segments": ordered,
                                 "entry": entry, "faces": sorted({i for s in chain for i in s["faces"]} |
                                                                  {i for e in ends.values() for i in e.get("faces", [])}),
                                 "source": "geometry", "confidence": "high"}
            entry_t = t0 if entry == "low" else t1
            h["position"] = [_r(x) for x in _add(foot, _mul(d, entry_t))]
            h["entry_t"] = _r(entry_t)
            if len(ordered) >= 2 and ordered[0]["diameter"] > ordered[1]["diameter"] + TOL:
                step = _annulus_at(body, d, foot, ordered[0]["to"] if entry == "low" else ordered[0]["from"],
                                   ordered[0]["diameter"] / 2, ordered[1]["diameter"] / 2)
                h["counterbore"] = {"diameter": ordered[0]["diameter"], "depth": ordered[0]["length"]}
                if step is not None:
                    h["faces"] = sorted(set(h["faces"]) | {step["i"]})
                subtype = "counterbore" if len(ordered) == 2 else "stepped"
                h["diameter"] = ordered[1]["diameter"] if len(ordered) == 2 else main["diameter"]
            elif len(ordered) >= 2:
                subtype = "stepped"
            e_end = ends["low" if entry == "low" else "high"]
            if e_end.get("entry") == "countersink":
                h["countersink"] = {"diameter": e_end["diameter"], "angle_deg": e_end["angle_deg"]}
                if subtype in ("through", "blind"):
                    subtype = "countersink"
            elif e_end.get("entry") == "chamfer":
                h["entry_chamfer"] = {"diameter": e_end["diameter"], "angle_deg": e_end["angle_deg"]}
            if not through:
                far = ends["high" if entry == "low" else "low"]
                h["bottom"] = far["bottom"]
                if far.get("angle_deg"):
                    h["point_angle_deg"] = far["angle_deg"]
                h["depth"] = _r(abs(t1 - t0))
            h["through"] = through
            h["subtype"] = subtype
            th = _thread_hint(h["diameter"])
            if th and subtype in ("through", "blind"):
                h["possible_thread"] = th
            cl = _clearance_hint(h["diameter"])
            if cl:
                h["possible_clearance"] = cl
            h["blind_depth_ratio"] = None if through else _r(h["depth"] / max(1e-6, h["diameter"]), 2)
            holes.append(h)
    holes.sort(key=lambda h: (h["subtype"], h["diameter"], h["position"]))
    for n, h in enumerate(holes, 1):
        h["id"] = f"H{n}"
    return holes


def _signature(h: dict) -> tuple:
    return (h["subtype"], h["diameter"], h.get("depth"), tuple(round(x, 3) for x in canon_dir(h["dir"])),
            (h.get("counterbore") or {}).get("diameter"), (h.get("counterbore") or {}).get("depth"),
            (h.get("countersink") or {}).get("diameter"))


def recognise_patterns(holes: list[dict], round_axes: list[tuple] | None = None) -> list[dict]:
    """Holes of the same kind and size: a pitch circle, a row, a grid or a pair. Holes on a circle are a pitch
    circle when the circle is centred on a round feature (a bore, a shaft, a boss) or when they do not form a grid;
    four holes at the corners of a rectangle are a grid, as a drafter dimensions them."""
    round_axes = round_axes or []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for h in holes:
        groups[_signature(h)].append(h)
    out = []
    for sig, hs in groups.items():
        if len(hs) < 2:
            continue
        d = canon_dir(hs[0]["dir"])
        pts = [h["position"] for h in hs]
        # positions in the plane across the axis
        proj = [_sub(p, _mul(d, _dot(p, d))) for p in pts]
        c = [sum(p[i] for p in proj) / len(proj) for i in range(3)]
        radii = [_norm(_sub(p, c)) for p in proj]
        pat: dict[str, Any] = {"kind": "hole_pattern", "holes": [h["id"] for h in hs], "count": len(hs),
                               "of": {"subtype": hs[0]["subtype"], "diameter": hs[0]["diameter"]},
                               "source": "geometry", "confidence": "high"}
        axes_in = [i for i in range(3) if abs(d[i]) < 0.5]
        coords0 = [sorted({round(p[i], 2) for p in pts}) for i in axes_in]
        is_grid = len(coords0) == 2 and len(coords0[0]) * len(coords0[1]) == len(hs) and len(coords0[0]) > 1 and len(coords0[1]) > 1
        on_round = any(_same_dir(ad, d) and _norm(_sub(_sub(af, _mul(d, _dot(af, d))), c)) <= 0.2 for ad, af in round_axes)
        if len(hs) >= 3 and max(radii) - min(radii) <= 0.05 and min(radii) > TOL and (on_round or not is_grid):
            angs = sorted(math.degrees(math.atan2(*_pc(_sub(p, c), d))) % 360 for p in proj)
            steps = [(angs[(i + 1) % len(angs)] - angs[i]) % 360 for i in range(len(angs))]
            pcd = 2 * sum(radii) / len(radii)
            pcd = round(pcd) if abs(pcd - round(pcd)) <= 0.005 else _r(pcd, 2)
            pat.update(pattern="pitch_circle", pcd=float(pcd), centre=[_r(x) for x in c],
                       equally_spaced=max(steps) - min(steps) <= 0.5,
                       angle_step_deg=_r(360 / len(hs), 3) if max(steps) - min(steps) <= 0.5 else None,
                       start_angle_deg=_r(angs[0], 3))
        else:
            axes = [i for i in range(3) if abs(d[i]) < 0.5]
            coords = [sorted({round(p[i], 2) for p in pts}) for i in axes]
            if len(hs) == 2:
                pat.update(pattern="pair", centre_distance=_r(_norm(_sub(proj[0], proj[1]))))
            elif any(len(cs) == 1 for cs in coords):
                vary = coords[0] if len(coords[1]) == 1 else coords[1]
                sp = [round(b - a, 3) for a, b in zip(vary, vary[1:])]
                pat.update(pattern="linear", spacing=sp[0] if len(set(sp)) == 1 else sp, pitch_equal=len(set(sp)) == 1)
            elif len(coords[0]) * len(coords[1]) == len(hs):
                sp = [[round(b - a, 3) for a, b in zip(cs, cs[1:])] for cs in coords]
                pat.update(pattern="grid", rows=len(coords[1]), columns=len(coords[0]),
                           spacing=[s[0] if len(set(s)) == 1 else s for s in sp])
            else:
                pat.update(pattern="scattered")
        out.append(pat)
    for n, p in enumerate(out, 1):
        p["id"] = f"P{n}"
    return out


def _pc(v, d):
    """Two in-plane coordinates of v across axis d (for angles on a pitch circle)."""
    ref = [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0]
    u = _unit(_sub(ref, _mul(d, _dot(ref, d))))
    w = [d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0]]
    return (_dot(v, w), _dot(v, u))


# ----------------------------------------------------------------------------- slots, pockets, steps

def recognise_slots(body: dict, revolved: list[dict], used: set[int]) -> list[dict]:
    """Two concave half cylinders of one radius with parallel axes and the same span: a slot."""
    halves = [s for s in revolved if s["type"] == "cylinder" and s["concave"] and 0.35 <= s.get("coverage", 1) <= 0.65
              and not (set(s["faces"]) & used)]
    out, taken = [], set()
    for i, a in enumerate(halves):
        if i in taken:
            continue
        for j in range(i + 1, len(halves)):
            b = halves[j]
            if j in taken or abs(a["radius"] - b["radius"]) > TOL or not _same_dir(a["dir"], b["dir"]):
                continue
            if abs(a["t"][0] - b["t"][0]) > TOL or abs(a["t"][1] - b["t"][1]) > TOL:
                continue
            dist = _norm(_sub(a["foot"], b["foot"]))
            if dist <= TOL:
                continue
            taken |= {i, j}
            w = 2 * a["radius"]
            out.append({"kind": "slot", "width": _r(w), "centre_distance": _r(dist), "length": _r(dist + w),
                        "depth": _r(a["t"][1] - a["t"][0]), "axis": axis_name(a["dir"]) or a["dir"],
                        "centre": [_r((a["foot"][k] + b["foot"][k]) / 2) for k in range(3)],
                        "faces": sorted(a["faces"] + b["faces"]), "source": "geometry", "confidence": "medium"})
            break
    for n, s in enumerate(out, 1):
        s["id"] = f"S{n}"
    return out


def _faces_in_front(body: dict, f: dict, k: int, sign: int) -> bool:
    """Is there a face looking back at f (normal opposite) in front of it, overlapping it? Then f is a wall of a
    gap (a pocket side, a slot side, a tube's inside), not a floor open to the outside."""
    fb = f.get("bbox")
    if not fb:
        return False
    for g in body["faces"]:
        if g is f or g["type"] != "plane" or not g.get("normal") or not g.get("bbox"):
            continue
        if g["normal"][k] * sign > -0.99:
            continue
        if (g["point"][k] - f["point"][k]) * sign <= TOL:
            continue
        gb = g["bbox"]
        if all(min(fb[1][i], gb[1][i]) - max(fb[0][i], gb[0][i]) > TOL for i in range(3) if i != k):
            return True
    return False


def recognise_pockets_and_steps(body: dict, used: set[int], skip_axis: str | None = None) -> list[dict]:
    """Floors inside the body's extent along their normal, open to the outside in front of them: pockets (closed
    all round in plan) and steps (reaching the outside edge). The large faces that make the body's own shape (an
    L bracket's two legs) are not features. Touching floors and walls make one feature."""
    lo, hi = body["bbox"]["min"], body["bbox"]["max"]
    total = sum(f["area"] for f in body["faces"]) or 1.0
    cand = []
    for f in body["faces"]:
        if f["type"] != "plane" or f["i"] in used or not f.get("normal"):
            continue
        ax = axis_name(f["normal"])
        if ax is None or ax == skip_axis:
            continue
        k = "xyz".index(ax)
        pos = f["point"][k]
        sign = 1 if f["normal"][k] > 0 else -1
        far = hi[k] if sign > 0 else lo[k]
        depth = abs(far - pos)
        if depth <= TOL or abs(pos - (lo[k] if sign > 0 else hi[k])) <= TOL:
            continue  # an outside face, or the opposite outside face
        if f["area"] < 1.0 or f["area"] / total > 0.15:
            continue
        if _faces_in_front(body, f, k, sign):
            continue
        cand.append((f, ax, k, sign, depth))
    # touching candidates (a step's floor and its wall) are one feature: keep the floor across the thinnest axis
    thin = min(range(3), key=lambda i: body["bbox"]["size"][i])
    adj = {(a["a"], a["b"]) for a in body.get("adjacency", [])} | {(a["b"], a["a"]) for a in body.get("adjacency", [])}
    groups: list[list] = []
    for c in cand:
        for g in groups:
            if any((c[0]["i"], o[0]["i"]) in adj for o in g):
                g.append(c)
                break
        else:
            groups.append([c])
    out = []
    for g in groups:
        g.sort(key=lambda c: (c[2] != thin, -c[0]["area"]))
        f, ax, k, sign, depth = g[0]
        fb = f.get("bbox")
        others = [i for i in range(3) if i != k]
        open_sides = []
        if fb:
            for i in others:
                if abs(fb[0][i] - lo[i]) <= TOL:
                    open_sides.append(f"-{'xyz'[i]}")
                if abs(fb[1][i] - hi[i]) <= TOL:
                    open_sides.append(f"+{'xyz'[i]}")
        kind = "step" if open_sides else "pocket"
        row = {"kind": kind, "floor_face": f["i"], "faces": [c[0]["i"] for c in g], "normal": ax if sign > 0 else "-" + ax,
               "depth": _r(depth), "floor_area": _r(f["area"], 1), "source": "geometry", "confidence": "medium"}
        if fb:
            row["extent"] = [_r(fb[1][i] - fb[0][i]) for i in others]
            row["at"] = [_r((fb[0][i] + fb[1][i]) / 2) for i in range(3)]
        if open_sides:
            row["open_to"] = open_sides
        out.append(row)
    for n, p in enumerate(out, 1):
        p["id"] = ("ST" if p["kind"] == "step" else "PK") + str(n)
    return out


# ----------------------------------------------------------------------------- blends

def recognise_blends(body: dict, used: set[int]) -> tuple[list[dict], list[dict]]:
    """Fillets (partial cylinders and tori tangent to their neighbours) and chamfers (narrow faces at about 45
    degrees to two neighbours, and short cones at the ends of holes and shafts)."""
    faces = {f["i"]: f for f in body["faces"]}
    nbrs: dict[int, list[tuple[int, float | None]]] = defaultdict(list)
    for a in body.get("adjacency", []):
        nbrs[a["a"]].append((a["b"], a["angle"]))
        nbrs[a["b"]].append((a["a"], a["angle"]))
    fillets, chamfers = [], []
    total = sum(f["area"] for f in body["faces"]) or 1.0
    for i, f in faces.items():
        if i in used:
            continue
        ns = nbrs.get(i, [])
        if f["type"] in ("cylinder", "torus") and len(ns) >= 2:
            tangent = [b for b, ang in ns if ang is not None and ang < 3.0]
            if len(tangent) >= 2:
                r = f.get("radius", 0.0)
                fillets.append({"kind": "fillet" if f.get("concave") else "round", "radius": _r(r), "faces": [i],
                                "source": "geometry", "confidence": "medium"})
        elif f["type"] == "plane" and len(ns) >= 2 and f["area"] / total < 0.03:
            angs = [ang for _, ang in ns if ang is not None]
            near45 = [a for a in angs if 30 <= a <= 60]
            if len(near45) >= 2:
                chamfers.append({"kind": "chamfer", "faces": [i], "angle_deg": _r(sum(near45[:2]) / 2, 1),
                                 "area": _r(f["area"], 2), "source": "geometry", "confidence": "medium"})
    # group equal fillet radii: a drawing states "ALL FILLETS R3" or each radius once
    by_r: dict[tuple, dict] = {}
    for fl in fillets:
        key = (fl["kind"], fl["radius"])
        if key in by_r:
            by_r[key]["faces"] += fl["faces"]
            by_r[key]["count"] += 1
        else:
            by_r[key] = dict(fl, count=1)
    fillets = list(by_r.values())
    for n, x in enumerate(fillets, 1):
        x["id"] = f"F{n}"
    for n, x in enumerate(chamfers, 1):
        x["id"] = f"C{n}"
    return fillets, chamfers


# ----------------------------------------------------------------------------- turned parts and bosses

def turned_profile(body: dict, revolved: list[dict]) -> dict | None:
    """When the outside of the body turns about one axis: its diameters along that axis, shoulders, grooves,
    tapers and end chamfers. None for a part that is not mainly turned."""
    convex = [s for s in revolved if not s["concave"]]
    if not convex:
        return None
    by_line: dict[tuple, list[dict]] = defaultdict(list)
    for s in convex:
        by_line[_line_key(s["dir"], s["foot"])].append(s)
    key, segs = max(by_line.items(), key=lambda kv: sum(s["area"] for s in kv[1]))
    total = sum(f["area"] for f in body["faces"]) or 1.0
    rev_area = sum(s["area"] for s in segs) + sum(s["area"] for s in revolved if s["concave"] and
                                                    _line_key(s["dir"], s["foot"]) == key)
    d = segs[0]["dir"]
    planar_ok = 0.0
    for f in body["faces"]:
        if f["type"] == "plane" and f.get("normal") and _same_dir(f["normal"], d):
            planar_ok += f["area"]
    share = (rev_area + planar_ok) / total
    length = None
    cyl = sorted([s for s in segs if s["type"] == "cylinder" and s.get("coverage", 1) > 0.9], key=lambda s: s["t"][0])
    if len(cyl) == 0 or share < 0.7:
        return None
    t_lo = min(s["t"][0] for s in segs)
    t_hi = max(s["t"][1] for s in segs)
    length = t_hi - t_lo
    max_d = max(2 * s["radius"] for s in cyl)
    steps = [{"diameter": _r(2 * s["radius"]), "from": _r(s["t"][0] - t_lo), "to": _r(s["t"][1] - t_lo),
              "length": _r(s["t"][1] - s["t"][0])} for s in cyl]
    grooves, shoulders = [], []
    for i in range(1, len(steps) - 1):
        a, b, c = steps[i - 1], steps[i], steps[i + 1]
        if b["diameter"] < a["diameter"] - TOL and b["diameter"] < c["diameter"] - TOL:
            depth = (min(a["diameter"], c["diameter"]) - b["diameter"]) / 2
            if b["length"] <= max(3.0, 0.35 * min(a["diameter"], c["diameter"])) and depth <= 0.15 * max_d:
                grooves.append({"kind": "groove", "diameter": b["diameter"], "width": b["length"], "at": b["from"],
                                "depth": _r(depth), "source": "geometry", "confidence": "medium"})
    groove_at = {(g["at"], _r(g["at"] + g["width"])) for g in grooves}
    for a, b in zip(steps, steps[1:]):
        if any(abs(a["to"] - x) <= TOL for ga in groove_at for x in ga):
            continue  # a groove's side walls are not shoulders
        if abs(a["diameter"] - b["diameter"]) > TOL and abs(a["to"] - b["from"]) <= TOL:
            shoulders.append({"kind": "shoulder", "at": a["to"], "from_diameter": a["diameter"],
                              "to_diameter": b["diameter"], "source": "geometry", "confidence": "high"})
    tapers, chamfers = [], []
    for s in segs:
        if s["type"] != "cone":
            continue
        ang = s.get("semi_angle_deg") or 0
        ln = s["t"][1] - s["t"][0]
        row = {"from": _r(s["t"][0] - t_lo), "to": _r(s["t"][1] - t_lo), "diameters": [_r(2 * r) for r in s["radii"]],
               "included_angle_deg": _r(2 * ang, 2), "source": "geometry"}
        if 30 <= ang <= 60 and ln <= 0.15 * max_d + 1:
            chamfers.append(dict(row, kind="chamfer", confidence="medium"))
        else:
            tapers.append(dict(row, kind="taper", confidence="medium"))
    return {"kind": "turned_profile", "axis": axis_name(d) or [_r(x, 4) for x in d], "dir": [_r(x, 4) for x in d],
            "length": _r(length), "max_diameter": _r(max_d), "steps": steps, "shoulders": shoulders,
            "grooves": grooves, "tapers": tapers, "chamfers": chamfers, "share_of_area": _r(share, 3),
            "source": "geometry", "confidence": "high" if share > 0.9 else "medium"}


def recognise_bosses(body: dict, revolved: list[dict], profile: dict | None) -> list[dict]:
    if profile is not None:
        return []
    out = []
    for s in revolved:
        if s["type"] == "cylinder" and not s["concave"] and s.get("coverage", 1) > 0.9:
            out.append({"kind": "boss", "diameter": _r(2 * s["radius"]), "height": _r(s["t"][1] - s["t"][0]),
                        "axis": axis_name(s["dir"]) or s["dir"], "at": [_r(x) for x in s["foot"]], "faces": s["faces"],
                        "source": "geometry", "confidence": "medium"})
    for n, b in enumerate(out, 1):
        b["id"] = f"B{n}"
    return out


# ----------------------------------------------------------------------------- walls, sheet metal, members

def wall_thickness(body: dict) -> dict | None:
    """The thinnest wall between opposite parallel planar faces that overlap across each other."""
    planes = [f for f in body["faces"] if f["type"] == "plane" and f.get("normal") and f.get("bbox")]
    best = None
    pairs: dict[float, float] = defaultdict(float)
    for i, a in enumerate(planes):
        for b in planes[i + 1:]:
            if _dot(a["normal"], b["normal"]) > -math.cos(math.radians(ANG)):
                continue
            n = a["normal"]
            t = abs(_dot(_sub(a["point"], b["point"]), n))
            if t <= TOL:
                continue
            # the two faces must overlap when seen along the normal, and face each other with material between
            if not _overlap(a["bbox"], b["bbox"], n):
                continue
            if _dot(_sub(b["point"], a["point"]), n) > 0:
                continue  # their normals point at each other: a gap (a slot), not a wall
            pairs[round(t, 2)] += min(a["area"], b["area"])
            if best is None or t < best["thickness"]:
                best = {"thickness": _r(t), "faces": [a["i"], b["i"]]}
    if best is None:
        return None
    best["thickness_area"] = {str(k): _r(v, 1) for k, v in sorted(pairs.items())[:6]}
    return best


def _overlap(ba, bb, n) -> bool:
    axes = [i for i in range(3) if abs(n[i]) < 0.9]
    for i in axes:
        lo = max(ba[0][i], bb[0][i])
        hi = min(ba[1][i], bb[1][i])
        if hi - lo < -TOL:
            return False
    return True


def sheet_metal_evidence(body: dict, revolved: list[dict], wall: dict | None) -> dict | None:
    """A body of one constant thickness with bends (coaxial convex and concave partial cylinders t apart)."""
    if wall is None:
        return None
    t = wall["thickness"]
    total = sum(f["area"] for f in body["faces"]) or 1.0
    at_t = sum(v for k, v in wall["thickness_area"].items() if abs(float(k) - t) <= 0.02)
    bends = []
    conv = [s for s in revolved if s["type"] == "cylinder" and not s["concave"] and s.get("coverage", 1) < 0.9]
    conc = [s for s in revolved if s["type"] == "cylinder" and s["concave"] and s.get("coverage", 1) < 0.9]
    for a in conv:
        for b in conc:
            if _line_key(a["dir"], a["foot"]) == _line_key(b["dir"], b["foot"]) and abs((a["radius"] - b["radius"]) - t) <= 0.02:
                bends.append({"inside_radius": _r(b["radius"]), "axis": axis_name(a["dir"]) or a["dir"],
                              "angle_deg": _r(min(180.0, 360.0 * b.get("coverage", 0.25)), 1)})
    size = max(body["bbox"]["size"])
    share = (2 * at_t) / total
    if t > 0.04 * size or share < 0.6:
        return None
    return {"kind": "sheet_metal_evidence", "thickness": t, "bends": bends, "bend_count": len(bends),
            "share_of_area_at_thickness": _r(share, 3), "source": "geometry",
            "confidence": "high" if bends and share > 0.8 else "medium"}


def member_evidence(body: dict, revolved: list[dict]) -> dict | None:
    """An elongated prismatic body (a structural member or bar): its long axis, length, section class and size."""
    size = body["bbox"]["size"]
    order = sorted(range(3), key=lambda i: size[i])
    long_i = order[2]
    if size[long_i] < 4 * size[order[1]]:
        return None
    L = size[long_i]
    b, h = size[order[0]], size[order[1]]
    d = [0.0, 0.0, 0.0]
    d[long_i] = 1.0
    along = sum(f["area"] for f in body["faces"]
                if (f["type"] == "plane" and f.get("normal") and abs(f["normal"][long_i]) < 0.02)
                or (f["type"] in ("cylinder", "cone") and "axis" in f and _same_dir(f["axis"]["dir"], d)))
    total = sum(f["area"] for f in body["faces"]) or 1.0
    if along / total < 0.8:
        return None
    area = body["volume"] / L if L else 0.0
    fill = area / (b * h) if b * h else 0.0
    ends = [f for f in body["faces"] if f["type"] == "plane" and f.get("normal") and abs(f["normal"][long_i]) > 0.02
            and f["area"] > 0.1 * area]
    inner = any(f.get("loops", 1) > 1 for f in ends)
    round_out = any(s["type"] == "cylinder" and not s["concave"] and _same_dir(s["dir"], d) and abs(2 * s["radius"] - h) <= 0.1
                    for s in revolved)
    along_planes = [f for f in body["faces"] if f["type"] == "plane" and f.get("normal") and abs(f["normal"][long_i]) < 0.02]
    if round_out and inner:
        section, conf = "CHS", "high"
    elif round_out:
        section, conf = "round_bar", "high"
    elif inner:
        section, conf = ("SHS" if abs(b - h) <= TOL else "RHS"), "high"
    elif fill > 0.97:
        section, conf = ("square_bar" if abs(b - h) <= TOL else "flat_bar"), "high"
    else:
        n = len(along_planes)
        section = {6: "angle", 8: "channel", 12: "I_or_H"}.get(n, "open_section")
        conf = "medium" if n in (6, 8, 12) else "low"
    cuts = []
    for f in ends:
        ang = math.degrees(math.acos(min(1.0, abs(f["normal"][long_i]))))
        cuts.append({"angle_deg": _r(ang, 2), "square": ang < 0.5})
    return {"kind": "member_evidence", "long_axis": "xyz"[long_i], "length": _r(L), "section": section,
            "section_size": [_r(h), _r(b)], "section_area": _r(area, 1), "fill": _r(fill, 3),
            "wall": _r(area / (2 * (b + h)), 2) if inner and not round_out else None, "end_cuts": cuts,
            "source": "geometry", "confidence": conf}


def body_contacts(bodies: list[dict]) -> list[dict]:
    """Bodies whose boxes touch or overlap: where a weldment's members meet (joints to detail)."""
    out = []
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            lo = [max(a["bbox"]["min"][k], b["bbox"]["min"][k]) for k in range(3)]
            hi = [min(a["bbox"]["max"][k], b["bbox"]["max"][k]) for k in range(3)]
            if all(hi[k] - lo[k] >= -0.1 for k in range(3)):
                out.append({"bodies": [a["body"], b["body"]], "at": [_r((lo[k] + hi[k]) / 2) for k in range(3)],
                            "overlap": [_r(max(0.0, hi[k] - lo[k])) for k in range(3)], "source": "geometry",
                            "confidence": "medium"})
    return out


# ----------------------------------------------------------------------------- one body, all of it

def recognise_elbows(body: dict) -> list[dict]:
    """Pipe bends: a convex and a concave torus on one centre and major radius (outside and bore of an elbow)."""
    tori = [f for f in body["faces"] if f["type"] == "torus" and f.get("major_radius")]
    out = []
    for a in tori:
        if a.get("concave"):
            continue
        for b in tori:
            if b.get("concave") and abs(b["major_radius"] - a["major_radius"]) <= TOL and b.get("radius", 0) < a.get("radius", 0):
                R, r = a["major_radius"], a["radius"]
                ang = 360.0 * a["area"] / (4 * math.pi * math.pi * R * r) if R and r else None
                out.append({"kind": "elbow", "outside_diameter": _r(2 * r), "bore": _r(2 * b["radius"]),
                            "wall": _r(r - b["radius"]), "bend_radius": _r(R), "angle_deg": _r(ang, 1) if ang else None,
                            "faces": [a["i"], b["i"]], "source": "geometry", "confidence": "high"})
                break
    return out


def recognise_flange(body: dict, profile: dict | None, holes: list[dict], patterns: list[dict]) -> dict | None:
    """A disc (short turned body) with a central bore and a pitch circle of bolt holes."""
    if not profile or profile["length"] > 0.35 * profile["max_diameter"]:
        return None
    pcd = next((p for p in patterns if p.get("pattern") == "pitch_circle" and p["count"] >= 4), None)
    bore = max((h for h in holes if h.get("through") and h["diameter"] > 0.25 * profile["max_diameter"]),
               key=lambda h: h["diameter"], default=None)
    if pcd is None:
        return None
    return {"kind": "flange", "outside_diameter": profile["max_diameter"], "thickness": profile["length"],
            "bore": bore["diameter"] if bore else None, "bolt_holes": pcd["count"], "pcd": pcd.get("pcd"),
            "bolt_hole_diameter": pcd["of"]["diameter"], "source": "geometry", "confidence": "high"}


def recognise_body(body: dict) -> dict:
    rev = merge_revolved(body)
    member = member_evidence(body, rev)
    holes = recognise_holes(body, rev)
    member_bore = None
    if member:
        long_d = [0.0, 0.0, 0.0]
        long_d["xyz".index(member["long_axis"])] = 1.0
        bores = [h for h in holes if h.get("through") and _same_dir(h["dir"], long_d)]
        if bores:
            member_bore = max(bores, key=lambda h: h["diameter"])
            holes = [h for h in holes if h is not member_bore]
            member["bore"] = member_bore["diameter"]
    used = {i for h in holes for i in h["faces"]} | (set(member_bore["faces"]) if member_bore else set())
    # a round bar is turned: keep both readings (a plain bar in a frame is a member; on its own it is a turned part)
    profile = turned_profile(body, rev) if (not member or member["section"] == "round_bar") else None
    round_axes = [(s["dir"], s["foot"]) for s in rev if s["type"] == "cylinder" and s.get("coverage", 1) > 0.9]
    patterns = recognise_patterns(holes, round_axes)
    slots = recognise_slots(body, rev, used)
    used |= {i for s in slots for i in s["faces"]}
    if profile:
        used |= {i for s in rev if not s["concave"] for i in s["faces"]}
    bosses = recognise_bosses(body, rev, profile) if not member else []
    used |= {i for b in bosses for i in b["faces"]}
    wall = wall_thickness(body)
    sheet = sheet_metal_evidence(body, rev, wall) if not member else None
    if sheet:
        fillets, chamfers = [], []   # in sheet metal, the "fillets" are the bends
    else:
        fillets, chamfers = recognise_blends(body, used)
    used |= {i for f in fillets for i in f["faces"]} | {i for c in chamfers for i in c["faces"]}
    pockets = [] if (member or sheet) else recognise_pockets_and_steps(body, used, profile["axis"] if profile else None)
    elbows = recognise_elbows(body)
    flange = recognise_flange(body, profile, holes, patterns)
    out = {"body": body["body"], "bbox": body["bbox"], "volume": body["volume"], "holes": holes, "patterns": patterns,
           "slots": slots, "pockets": [p for p in pockets if p["kind"] == "pocket"],
           "steps": [p for p in pockets if p["kind"] == "step"], "bosses": bosses, "fillets": fillets,
           "chamfers": chamfers + (profile or {}).get("chamfers", []), "turned_profile": profile, "wall": wall,
           "sheet_metal": sheet, "member": member, "elbows": elbows, "flange": flange}
    out["directions"] = feature_directions(out)
    return out


def feature_directions(rec: dict) -> dict[str, list[str]]:
    """Which features are seen true shape (circles, slot outlines) when looking along each model axis."""
    out: dict[str, list[str]] = defaultdict(list)
    for h in rec["holes"]:
        if isinstance(h["axis"], str):
            out[h["axis"]].append(h["id"])
    for s in rec["slots"]:
        if isinstance(s["axis"], str):
            out[s["axis"]].append(s["id"])
    for p in rec["pockets"] + rec["steps"]:
        out[p["normal"].lstrip("-")].append(p["id"])
    for b in rec["bosses"]:
        if isinstance(b["axis"], str):
            out[b["axis"]].append(b["id"])
    return dict(out)


def recognise(facts: dict) -> dict:
    bodies = [recognise_body(b) for b in facts["bodies"]]
    out = {"bodies": bodies, "body_count": len(bodies), "bbox": facts["bbox"], "volume": facts["volume"]}
    if len(facts["bodies"]) > 1:
        out["contacts"] = body_contacts(facts["bodies"])
    return out
