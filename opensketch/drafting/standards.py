"""Module G: standards profiles.

A profile says which conventions a drawing follows: projection, units, the title-block fields it needs, the notes
a drawing must state, and which symbols SOLIDWORKS can draw through the existing add-in. Standards are named by
number and title only; no text of any standard is reproduced, and no edition is claimed as verified: `verified`
stays False until the owner checks the profile against licensed copies (company knowledge, knowledge.py).

Compliance is never claimed: a drawing that uses a profile's conventions is "drawn to the conventions of" it.
"""

from __future__ import annotations

from typing import Any

COMMON_FIELDS = ["Title", "DrawingNo", "Revision", "Material", "Finish", "DrawnBy", "Date", "CheckedBy", "ApprovedBy"]
REQUIRED_FIELDS = ["Title", "DrawingNo", "Revision", "Material"]

# What the add-in can put on a drawing today (DrawingEdits.cs and Drawings.cs), and what it cannot yet.
SUPPORTED = ["model views", "projected views", "section views", "detail views", "model dimensions (associative)",
             "centre marks and centre lines", "notes", "title-block custom properties", "bill of materials with balloons",
             "sheet scale and projection"]
NOT_YET = ["new dimensions between picked entities", "hole callouts", "ordinate and baseline dimension sets", "hole tables",
           "weld symbols", "geometric tolerance frames and datum symbols", "surface texture symbols", "revision tables",
           "weldment cut-list tables", "flat-pattern views", "exploded views", "break lines"]

PROFILES: dict[str, dict[str, Any]] = {
    "AS1100": {
        "name": "Australian technical drawing conventions (AS 1100 series)",
        "projection": "third", "units": "mm",
        "references": [
            {"standard": "AS 1100.101", "title": "Technical drawing: General principles", "use": "sheets, lines, lettering, projection, scales"},
            {"standard": "AS 1100.201", "title": "Technical drawing: Mechanical engineering drawing", "use": "views, sections, dimensioning, tolerancing of mechanical parts"},
            {"standard": "AS/NZS 1554 series", "title": "Structural steel welding", "use": "weld categories and quality: named by the designer, never chosen here"},
            {"standard": "AS 4100", "title": "Steel structures", "use": "structural design: the engineer's responsibility, not the drawing tool's"},
            {"standard": "ISO 2553", "title": "Welding and allied processes: symbolic representation on drawings", "use": "weld symbols (not yet drawn by the add-in)"},
            {"standard": "ISO 2768-1", "title": "General tolerances for linear and angular dimensions", "use": "a common general tolerance note: only when the designer confirms it"},
            {"standard": "ISO 286-1/-2", "title": "ISO code system for tolerances on linear sizes (fits)", "use": "fit designations such as H7/g6: only from the designer"},
        ],
        "required_notes": ["units", "general tolerance", "scale or do-not-scale", "material", "edge treatment"],
        "preferred_scales": ["10:1", "5:1", "2:1", "1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100"],
    },
    "ISO": {
        "name": "ISO technical product documentation conventions",
        "projection": "first", "units": "mm",
        "references": [
            {"standard": "ISO 128 series", "title": "Technical product documentation: General principles of representation", "use": "views, lines, sections"},
            {"standard": "ISO 129-1", "title": "Indication of dimensions and tolerances", "use": "dimensioning"},
            {"standard": "ISO 5456-2", "title": "Projection methods: Orthographic representations", "use": "first and third angle"},
            {"standard": "ISO 1101", "title": "Geometrical tolerancing", "use": "feature control frames (not yet drawn by the add-in)"},
            {"standard": "ISO 21920-1", "title": "Surface texture: indication", "use": "surface texture symbols (not yet drawn by the add-in)"},
            {"standard": "ISO 2768-1", "title": "General tolerances", "use": "general tolerance note when confirmed"},
            {"standard": "ISO 286-1/-2", "title": "Fits", "use": "fit designations when given by the designer"},
            {"standard": "ISO 2553", "title": "Weld symbols", "use": "weld symbols"},
            {"standard": "ISO 7200", "title": "Title blocks", "use": "title-block fields"},
        ],
        "required_notes": ["units", "general tolerance", "material"],
        "preferred_scales": ["10:1", "5:1", "2:1", "1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100"],
    },
    "ASME": {
        "name": "ASME drawing conventions (Y14 series)",
        "projection": "third", "units": "mm",
        "references": [
            {"standard": "ASME Y14.5", "title": "Dimensioning and tolerancing", "use": "dimensions and GD&T"},
            {"standard": "ASME Y14.3", "title": "Orthographic and pictorial views", "use": "views and sections"},
            {"standard": "ASME Y14.100", "title": "Engineering drawing practices", "use": "drawing content"},
        ],
        "required_notes": ["units", "tolerance block or general tolerance", "material", "interpretation per the dimensioning standard"],
        "preferred_scales": ["10:1", "4:1", "2:1", "1:1", "1:2", "1:4", "1:5", "1:10", "1:20"],
    },
}


def profile(name: str | None) -> dict[str, Any]:
    key = (name or "AS1100").upper().replace(" ", "")
    if key not in PROFILES:
        raise ValueError(f"Unknown standards profile {name!r}: one of {', '.join(PROFILES)}")
    p = dict(PROFILES[key], id=key)
    p["title_fields"] = COMMON_FIELDS
    p["required_fields"] = REQUIRED_FIELDS
    p["supported_symbols"] = SUPPORTED
    p["not_yet_supported"] = NOT_YET
    p["verified"] = False
    p["statement"] = (f"Drawn to the conventions of {p['name']}. Compliance with any standard is not claimed: a qualified "
                      "person checks the drawing against the licensed standard before release.")
    return p


def callout(h: dict, count: int = 1) -> str:
    """A hole callout in the ISO / AS style (text proposal: the add-in has no hole-callout action yet)."""
    n = f"{count}x " if count > 1 else ""
    if h["subtype"] == "counterbore":
        cb = h["counterbore"]
        s = f"{n}Ø{h['diameter']:g} THRU, ⌴Ø{cb['diameter']:g} ↧{cb['depth']:g}" if h.get("through") else \
            f"{n}Ø{h['diameter']:g} ↧{h.get('depth', 0):g}, ⌴Ø{cb['diameter']:g} ↧{cb['depth']:g}"
    elif h["subtype"] == "countersink":
        cs = h["countersink"]
        s = f"{n}Ø{h['diameter']:g} THRU, ⌵Ø{cs['diameter']:g} x {cs['angle_deg']:g}°"
    elif h["subtype"] == "blind":
        s = f"{n}Ø{h['diameter']:g} ↧{h.get('depth', 0):g}"
    elif h["subtype"] == "stepped":
        s = n + ", ".join(f"Ø{x['diameter']:g} ↧{x['length']:g}" for x in h["segments"])
    else:
        s = f"{n}Ø{h['diameter']:g} THRU"
    return s
