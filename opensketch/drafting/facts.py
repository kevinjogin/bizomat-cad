"""Module A, geometry: facts about a solid, as plain data.

Runs in the person's CAD worker (OpenCascade holds the GIL). `part_facts(part_doc)` regenerates a BIZOMAT CAD part
document holding SOLIDWORKS' current body (sw_tools._geometry) and returns, per solid body:

- every face: type, area, centre, normal (planes), axis, radius and semi-angle (cylinders, cones, tori, spheres),
  whether a cylinder is concave (material outside it: a hole or bore) or convex (a shaft or boss), and its span
  along its axis (or along its normal for planes, as the face's plane offset);
- adjacency: which faces share an edge, and the angle between their normals there (0 = tangent);
- the body's volume, area, bounding box and centre of mass.

Nothing here interprets the geometry: features.py does that, from these facts alone, so it can be tested without
OpenCascade. Values are rounded to 1e-4 mm to keep the output stable.
"""

from __future__ import annotations

import math
from typing import Any

from .. import geometry


def _r(v: float, n: int = 4) -> float:
    return round(float(v), n) + 0.0


def _vec(v) -> list[float]:
    return [_r(x) for x in geometry.vlist(v)]


def _unit(v) -> list[float]:
    x, y, z = geometry.vlist(v)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return [_r(x / n, 6), _r(y / n, 6), _r(z / n, 6)]


def _kind(shape) -> str:
    return str(shape.geom_type).split(".")[-1].lower()


def _sample_points(face) -> list:
    """Points on the face's boundary (edge ends and midpoints): enough to bound its extent along a direction."""
    pts = []
    for e in face.edges():
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            try:
                pts.append(e.position_at(t))
            except Exception:
                pass
    return pts


def _face(i: int, f) -> dict[str, Any]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    t = _kind(f)
    c = f.center()
    out: dict[str, Any] = {"i": i, "type": t, "area": _r(f.area, 3), "center": _vec(c)}
    try:
        p = geometry.on_face_point(f)
    except Exception:
        p = c
    out["point"] = _vec(p)
    pts = _sample_points(f)
    try:
        n = f.normal_at(p)
    except Exception:
        n = None
    if t == "plane" and n is not None:
        nn = _unit(n)
        out["normal"] = nn
        out["offset"] = _r(sum(a * b for a, b in zip(nn, geometry.vlist(p))))
    if t in ("cylinder", "cone", "sphere", "torus"):
        try:
            ax = f.axis_of_rotation
            d = _unit(ax.direction)
            o = geometry.vlist(ax.position)
            out["axis"] = {"point": [_r(x) for x in o], "dir": d}
            ts = [sum((geometry.vlist(q)[k] - o[k]) * d[k] for k in range(3)) for q in pts] or [0.0]
            out["span"] = [_r(min(ts)), _r(max(ts))]
            if n is not None:
                pp = geometry.vlist(p)
                tp = sum((pp[k] - o[k]) * d[k] for k in range(3))
                radial = [pp[k] - (o[k] + tp * d[k]) for k in range(3)]
                dot = sum(radial[k] * geometry.vlist(n)[k] for k in range(3))
                out["concave"] = bool(dot < 0)  # the face's normal points at the axis: material outside it
        except Exception:
            pass
        try:
            s = BRepAdaptor_Surface(f.wrapped)
            if t == "cylinder":
                out["radius"] = _r(s.Cylinder().Radius())
            elif t == "cone":
                cone = s.Cone()
                out["semi_angle_deg"] = _r(abs(math.degrees(cone.SemiAngle())), 3)
                out["ref_radius"] = _r(cone.RefRadius())
                # radii at the span's two ends (a cone's radius changes along the axis)
                if "span" in out and "axis" in out:
                    o, d = out["axis"]["point"], out["axis"]["dir"]
                    rads = []
                    for q in pts:
                        qq = geometry.vlist(q)
                        tq = sum((qq[k] - o[k]) * d[k] for k in range(3))
                        rads.append((tq, math.sqrt(sum((qq[k] - (o[k] + tq * d[k])) ** 2 for k in range(3)))))
                    rads.sort()
                    out["radii"] = [_r(rads[0][1]), _r(rads[-1][1])]
            elif t == "sphere":
                out["radius"] = _r(s.Sphere().Radius())
            elif t == "torus":
                tor = s.Torus()
                out["major_radius"] = _r(tor.MajorRadius())
                out["radius"] = _r(tor.MinorRadius())
                loc = tor.Location()
                cen = [loc.X(), loc.Y(), loc.Z()]
                out["centre_of_revolution"] = [_r(x) for x in cen]
                # concave or convex against the tube's own centre circle, not the bend axis
                if n is not None and "axis" in out:
                    d = out["axis"]["dir"]
                    pp = geometry.vlist(p)
                    rel = [pp[k] - cen[k] for k in range(3)]
                    h = sum(rel[k] * d[k] for k in range(3))
                    inplane = [rel[k] - h * d[k] for k in range(3)]
                    ln = math.sqrt(sum(x * x for x in inplane)) or 1.0
                    circ = [cen[k] + tor.MajorRadius() * inplane[k] / ln for k in range(3)]
                    tube = [pp[k] - circ[k] for k in range(3)]
                    out["concave"] = bool(sum(tube[k] * geometry.vlist(n)[k] for k in range(3)) < 0)
        except Exception:
            pass
    if pts:
        xs, ys, zs = zip(*(geometry.vlist(q) for q in pts))
        out["bbox"] = [[_r(min(xs)), _r(min(ys)), _r(min(zs))], [_r(max(xs)), _r(max(ys)), _r(max(zs))]]
    out["loops"] = len(f.wires()) if hasattr(f, "wires") else 1
    return out


def _angle(e, fa, fb) -> float | None:
    try:
        m = e.position_at(0.5)
        na, nb = fa.normal_at(m), fb.normal_at(m)
        return _r(math.degrees(math.acos(max(-1.0, min(1.0, na.dot(nb))))), 2)
    except Exception:
        return None


def solid_facts(solid, index: int = 0) -> dict[str, Any]:
    faces = solid.faces()
    edges = solid.edges()
    rows = [_face(i, f) for i, f in enumerate(faces)]
    eidx = {hash(e): j for j, e in enumerate(edges)}
    owners: dict[int, list[int]] = {}
    for fi, f in enumerate(faces):
        for e in f.edges():
            j = eidx.get(hash(e))
            if j is not None and fi not in owners.setdefault(j, []):
                owners[j].append(fi)
    adj: list[dict] = []
    seen = set()
    for j, fs in owners.items():
        if len(fs) != 2:
            continue
        a, b = sorted(fs)
        ang = _angle(edges[j], faces[a], faces[b])
        key = (a, b)
        if key in seen:
            # several edges between the same two faces: keep the sharpest angle
            for row in adj:
                if (row["a"], row["b"]) == key and ang is not None and (row["angle"] is None or ang > row["angle"]):
                    row["angle"] = ang
            continue
        seen.add(key)
        adj.append({"a": a, "b": b, "angle": ang, "edge": _kind(edges[j])})
    bb = solid.bounding_box()
    try:
        com = _vec(solid.center())
    except Exception:
        com = None
    edge_types: dict[str, int] = {}
    for e in edges:
        k = _kind(e)
        edge_types[k] = edge_types.get(k, 0) + 1
    return {"body": index, "volume": _r(solid.volume, 3), "area": _r(solid.area, 3),
            "bbox": {"min": _vec(bb.min), "max": _vec(bb.max), "size": _vec(bb.size)}, "center_of_mass": com,
            "faces": rows, "adjacency": adj, "edge_types": edge_types, "faces_total": len(faces),
            "edges_total": len(edges)}


def shape_facts(shape) -> dict[str, Any]:
    """Facts for every solid of a shape (a part may hold several bodies: a weldment or a multi-body part)."""
    solids = list(shape.solids()) if hasattr(shape, "solids") else [shape]
    if not solids:
        raise ValueError("The model has no solid body.")
    bodies = [solid_facts(s, i) for i, s in enumerate(solids)]
    bb = shape.bounding_box()
    return {"bodies": bodies, "bbox": {"min": _vec(bb.min), "max": _vec(bb.max), "size": _vec(bb.size)},
            "volume": _r(sum(b["volume"] for b in bodies), 3), "units": "mm"}


def part_facts(part_doc: dict) -> dict[str, Any]:
    """In the CAD worker: facts of a BIZOMAT CAD part document (SOLIDWORKS' body imported from its STEP)."""
    st, _ = geometry.regen(part_doc)
    if st.part is None:
        raise ValueError("The model has no solid body.")
    return shape_facts(st.part)


def assembly_facts(asm_doc: dict, limit: int = 40) -> dict[str, Any]:
    """In the CAD worker: per component, its part's facts summary and its placement (assembly coordinates)."""
    parts_out: dict[str, Any] = {}
    for key, pdoc in (asm_doc.get("parts") or {}).items():
        try:
            f = part_facts(pdoc)
        except Exception as exc:  # a component without a body (a sketch-only part) is reported, not fatal
            parts_out[key] = {"error": str(exc), "name": pdoc.get("name")}
            continue
        f["name"] = pdoc.get("name")
        parts_out[key] = f
    comps = []
    for c in (asm_doc.get("components") or [])[:max(1, limit)]:
        comps.append({"name": c.get("name"), "part": c.get("part"), "position": c.get("position"),
                      "rotation": c.get("rotation"), "suppressed": bool(c.get("suppressed")),
                      "hidden": bool(c.get("hidden"))})
    return {"kind": "assembly", "parts": parts_out, "components": comps,
            "components_total": len(asm_doc.get("components") or [])}
