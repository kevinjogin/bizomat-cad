"""Module J: the benchmark set. Twelve SYNTHETIC models with the results a drafter would expect.

These are NOT expert-reviewed professional drawings. They are clearly labelled test cases, built here with
build123d so that feature recognition, discipline classification and view selection can be measured and kept
from regressing. Expected values were written by hand from the geometry each builder makes. When real
expert-reviewed drawings are added (learning.py, examples approved by a reviewer), they are evaluated the same way.

Each case: name, category, a builder returning a build123d shape (or several, for an assembly), and `expect`:
  features      {kind/subtype: count} the recognition must find (at least these)
  disciplines   labels that must be among the classification's top results
  main_view     the model axis the main view must look along (or "assembly")
  sections      True when a section view is expected
"""

from __future__ import annotations

from typing import Any, Callable

SYNTHETIC = "synthetic test case, not an expert-reviewed drawing"


def _x(shape):
    """A Z-axis primitive turned to lie along X."""
    from build123d import Rot
    return Rot(0, 90, 0) * shape


def stepped_shaft():
    from build123d import Cylinder, Pos
    a = Pos(20, 0, 0) * _x(Cylinder(15, 40))
    b = Pos(70, 0, 0) * _x(Cylinder(20, 60))
    c = Pos(125, 0, 0) * _x(Cylinder(15, 50))
    s = a + b + c
    groove = Pos(140, 0, 0) * _x(Cylinder(16, 2) - Cylinder(13.5, 2))
    s = s - groove
    cross = Pos(70, 0, 0) * Cylinder(3, 50)          # a cross hole through the middle diameter
    return s - cross


def flanged_shaft():
    from build123d import Cylinder, Pos
    import math
    shaft = Pos(0, 0, 56) * Cylinder(12.5, 100)
    flange = Pos(0, 0, 6) * Cylinder(45, 12)
    s = shaft + flange
    for k in range(4):
        a = math.radians(45 + 90 * k)
        s = s - Pos(35 * math.cos(a), 35 * math.sin(a), 6) * Cylinder(4.5, 12)
    return s


def bearing_housing():
    from build123d import Box, Cylinder, Pos, Rot
    body = Pos(0, 0, 35) * Box(120, 80, 70)
    bore_big = Pos(0, -20, 35) * Rot(90, 0, 0) * Cylinder(26, 40)    # a bearing seat 40 deep from the front
    bore_small = Pos(0, 20, 35) * Rot(90, 0, 0) * Cylinder(22.5, 40)
    s = body - bore_big - bore_small
    for x in (-50, 50):
        for y in (-30, 30):
            s = s - Pos(x, y, 62.5) * Cylinder(3.4, 15)                  # blind, M8 tapping size, from the top
    return s


def machined_block():
    from build123d import Box, Cylinder, Pos
    s = Pos(0, 0, 20) * Box(100, 60, 40)
    s = s - Pos(0, 0, 35) * Box(50, 30, 10)                              # a pocket 10 deep in the top
    s = s - Pos(45, 0, 35) * Box(10, 60, 10)                             # a step along one end
    for x in (-35, 35):
        s = s - Pos(x, 20, 20) * Cylinder(3, 40)                         # dowel holes through
    return s


def multi_hole_plate():
    from build123d import Box, Cone, Cylinder, Pos
    s = Pos(0, 0, 10) * Box(150, 100, 20)
    s = s - Pos(-55, 35, 10) * Cylinder(4.5, 20) - Pos(55, 35, 10) * Cylinder(4.5, 20)            # 2x through 9
    for x in (-55, 55):                                                                               # 2x counterbore
        s = s - Pos(x, 0, 10) * Cylinder(5.5, 20) - Pos(x, 0, 14.5) * Cylinder(9, 11)
    for x in (-55, 55):                                                                               # 2x countersink
        s = s - Pos(x, -35, 10) * Cylinder(3.3, 20) - Pos(x, -35, 18.4) * Cone(3.3, 6.5, 3.2)
    for x in (-15, 15):                                                                               # 2x blind 5 x 12
        s = s - Pos(x, 0, 14) * Cylinder(2.5, 12)
    return s


def bracket():
    from build123d import Box, Cylinder, Pos, Rot
    base = Pos(0, 0, 4) * Box(100, 60, 8)
    up = Pos(0, -26, 44) * Box(100, 8, 80)
    s = base + up
    for x in (-35, 35):
        s = s - Pos(x, 10, 4) * Cylinder(4.5, 8)
        s = s - Pos(x, -26, 60) * Rot(90, 0, 0) * Cylinder(4.5, 8)
    return s


def _rhs(L, b=40.0, h=40.0, t=3.0):
    from build123d import Box
    return Box(b, h, L) - Box(b - 2 * t, h - 2 * t, L)


def welded_frame():
    from build123d import Compound, Pos, Rot
    long1 = Pos(0, -130, 20) * Rot(0, 90, 0) * _rhs(500)
    long2 = Pos(0, 130, 20) * Rot(0, 90, 0) * _rhs(500)
    short1 = Pos(-230, 0, 20) * Rot(90, 0, 0) * _rhs(220)
    short2 = Pos(230, 0, 20) * Rot(90, 0, 0) * _rhs(220)
    return Compound(children=[long1, long2, short1, short2])


def beam_connection():
    from build123d import Box, Compound, Cylinder, Pos, Rot
    flange_t, web_t, d, b, L = 12.0, 8.0, 200.0, 100.0, 1000.0
    beam = (Pos(L / 2, 0, d / 2 - flange_t / 2) * Box(L, b, flange_t) + Pos(L / 2, 0, -d / 2 + flange_t / 2) * Box(L, b, flange_t)
            + Pos(L / 2, 0, 0) * Box(L, web_t, d - 2 * flange_t))
    plate = Pos(-6, 0, 0) * Box(12, 120, 220)
    for y in (-35, 35):
        for z in (-75, 75):
            plate = plate - Pos(-6, y, z) * Rot(0, 90, 0) * Cylinder(11, 12)
    return Compound(children=[beam, plate])


def sheet_metal_enclosure():
    from build123d import Axis, Box, Cylinder, GeomType, Pos, Rot, fillet, offset
    box = Pos(0, 0, 30) * Box(200, 100, 60)
    box = fillet(box.edges().filter_by(GeomType.LINE).filter_by(Axis.X).group_by(Axis.Z)[0], 4)
    top = box.faces().sort_by(Axis.Z)[-1]
    shell = offset(box, amount=-2, openings=[top])
    for x in (-60, -20, 20, 60):
        shell = shell - Pos(x, -50, 30) * Rot(90, 0, 0) * Cylinder(2.5, 10)
    return shell


def pipe_spool():
    from build123d import Box, Compound, Cylinder, Pos, Torus
    import math
    od, t = 60.3, 3.9
    pipe = Pos(200, 0, 0) * _x(Cylinder(od / 2, 400) - Cylinder(od / 2 - t, 400))
    ring = Torus(76.0, od / 2) - Torus(76.0, od / 2 - t)
    elbow = Pos(0, 76.0, 0) * (ring & Pos(-50, -50, 0) * Box(100, 100, 80))
    flange = Pos(400 + 9, 0, 0) * _x(Cylinder(75, 18) - Cylinder(od / 2 - t, 18))
    for k in range(4):
        a = math.radians(45 + 90 * k)
        flange = flange - Pos(409, 60 * math.cos(a), 60 * math.sin(a)) * _x(Cylinder(9, 18))
    return Compound(children=[pipe, elbow, flange])


def mechanical_assembly() -> dict[str, Any]:
    from build123d import Box, Cylinder, Pos
    base = Pos(0, 0, 5) * Box(120, 80, 10) - Pos(0, 0, 5) * Cylinder(10.1, 10)
    shaft = Pos(0, 0, 40) * Cylinder(10, 80)
    collar = Pos(0, 0, 15) * (Cylinder(18, 10) - Cylinder(10, 10))
    return {"assembly": [("Base-1", base), ("Shaft-1", shaft), ("Collar-1", collar), ("ISO 4762 M6x16-1", Pos(50, 30, 18) * Cylinder(3, 16)),
                         ("ISO 4762 M6x16-2", Pos(-50, 30, 18) * Cylinder(3, 16))]}


def equipment_assembly() -> dict[str, Any]:
    from build123d import Box, Cylinder, Pos, Rot
    skid = Pos(0, 0, 50) * (Box(1200, 600, 100) - Box(1100, 500, 100))
    motor = Pos(-300, 0, 250) * Rot(0, 90, 0) * Cylinder(150, 400)
    pump = Pos(300, 0, 250) * Box(300, 300, 300)
    lug = Pos(0, 280, 200) * (Box(100, 20, 100) - Rot(90, 0, 0) * Cylinder(20, 20))
    return {"assembly": [("Skid-1", skid), ("Motor-1", motor), ("Pump-1", pump), ("Lifting lug-1", lug)]}


CASES: list[dict[str, Any]] = [
    {"name": "stepped_shaft", "category": "Stepped shaft", "build": stepped_shaft,
     "expect": {"features": {"turned_profile": 1, "shoulder": 2, "groove": 1, "hole:through": 1},
                "disciplines": ["turning"], "main_view": "y|z", "sections": True}},
    {"name": "flanged_shaft", "category": "Flanged shaft", "build": flanged_shaft,
     "expect": {"features": {"turned_profile": 1, "hole:through": 4, "pattern:pitch_circle": 1},
                "disciplines": ["turning", "milling_drilling"], "main_view": "x|y", "sections": False}},
    {"name": "bearing_housing", "category": "Bearing housing", "build": bearing_housing,
     "expect": {"features": {"hole:stepped|counterbore": 1, "hole:blind": 4, "pattern:grid": 1},
                "disciplines": ["milling_drilling", "precision"], "main_view": "y", "sections": True}},
    {"name": "machined_block", "category": "Machined block", "build": machined_block,
     "expect": {"features": {"pocket": 1, "step": 1, "hole:through": 2},
                "disciplines": ["milling_drilling"], "main_view": "z", "sections": True}},
    {"name": "multi_hole_plate", "category": "Component with multiple hole types", "build": multi_hole_plate,
     "expect": {"features": {"hole:through": 2, "hole:counterbore": 2, "hole:countersink": 2, "hole:blind": 2},
                "disciplines": ["milling_drilling", "plate_fabrication"], "main_view": "z", "sections": True}},
    {"name": "bracket", "category": "Bracket", "build": bracket,
     "expect": {"features": {"hole:through": 4}, "disciplines": ["milling_drilling"], "main_view": "y|z|x", "sections": False}},
    {"name": "welded_frame", "category": "Welded frame", "build": welded_frame,
     "expect": {"features": {"member": 4, "contact": 4}, "disciplines": ["weldment", "structural_steel"],
                "main_view": "z", "sections": False}},
    {"name": "beam_connection", "category": "Structural beam connection", "build": beam_connection,
     "expect": {"features": {"member": 1, "hole:through": 4, "contact": 1},
                "disciplines": ["structural_steel"], "main_view": "y|z", "sections": False}},
    {"name": "sheet_metal_enclosure", "category": "Sheet-metal enclosure", "build": sheet_metal_enclosure,
     "expect": {"features": {"sheet_metal": 1, "hole:through": 4}, "disciplines": ["sheet_metal"], "main_view": "z|y",
                "sections": False}},
    {"name": "mechanical_assembly", "category": "Mechanical assembly", "build": mechanical_assembly,
     "expect": {"features": {"component": 5, "fastener": 2}, "disciplines": ["mechanical_assembly"], "main_view": "assembly",
                "sections": False}},
    {"name": "pipe_spool", "category": "Pipe spool", "build": pipe_spool,
     "expect": {"features": {"member:CHS": 1, "contact": 2}, "disciplines": ["piping"], "main_view": "z|y", "sections": False}},
    {"name": "equipment_assembly", "category": "General equipment assembly", "build": equipment_assembly,
     "expect": {"features": {"component": 4}, "disciplines": ["general_arrangement", "mechanical_assembly"],
                "main_view": "assembly", "sections": False}},
]


def build_facts(case: dict[str, Any]) -> dict[str, Any]:
    """Facts of a benchmark case, as the CAD worker produces them for a real SOLIDWORKS body."""
    from . import facts
    shape = case["build"]()
    if isinstance(shape, dict) and "assembly" in shape:
        parts, comps = {}, []
        for n, (name, s) in enumerate(shape["assembly"], 1):
            key = f"p{n}"
            f = facts.shape_facts(s)
            f["name"] = name.rsplit("-", 1)[0]
            parts[key] = f
            comps.append({"name": name, "part": key, "position": [0, 0, 0], "rotation": [0, 0, 0],
                          "suppressed": False, "hidden": False})
        return {"kind": "assembly", "parts": parts, "components": comps, "components_total": len(comps)}
    out = facts.shape_facts(shape)
    out["kind"] = "part"
    return out


def builders() -> dict[str, Callable]:
    return {c["name"]: c["build"] for c in CASES}
