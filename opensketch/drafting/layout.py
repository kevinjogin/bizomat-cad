"""Module H: drawing layout evaluation, from the real drawing (sw_get_drawing: sheet size and every view's outline
in sheet mm), and non-critical corrections.

Checks: views off the sheet or in the title block, overlapping views, views too close for dimensions, projected
views out of their projection position or misaligned, unbalanced or wasteful use of the sheet, dimensions on a
pictorial view. Corrections are view moves only ({"do": "move"} actions for sw_edit_drawing): they never change a
scale, a dimension or anything engineering-critical.
"""

from __future__ import annotations

from typing import Any

MARGIN = 5.0
MIN_GAP = 12.0          # sheet mm between views below which dimensions have no room
TITLE_W, TITLE_H = 185.0, 60.0   # a title block of about ISO 7200 size in the lower right corner
ALIGN_TOL = 1.0


def _box(v: dict) -> tuple[float, float, float, float] | None:
    o = v.get("outline_mm")
    if not o or len(o) != 4:
        return None
    x0, y0, x1, y1 = o
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _centre(b) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _orient(v: dict) -> str:
    return str(v.get("orientation") or "").strip("*").lower()


def _gap(a, b) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    if dx == 0 and dy == 0:
        return -min(a[2], b[2]) + max(a[0], b[0])  # overlapping: negative
    return max(dx, dy) if (dx == 0 or dy == 0) else (dx * dx + dy * dy) ** 0.5


def _overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def evaluate(drawing: dict, projection: str | None = None) -> dict[str, Any]:
    sheet = drawing.get("sheet") or {}
    W, H = float(sheet.get("width_mm") or 420), float(sheet.get("height_mm") or 297)
    proj = projection or ("first" if "first" in str(sheet.get("projection", "")) else "third")
    views = [v for v in drawing.get("views") or [] if _box(v)]
    findings: list[dict] = []
    moves: dict[str, list[float]] = {}

    def find(sev, check, msg, view=None, fix=None):
        row = {"severity": sev, "category": "presentation", "check": check, "message": msg}
        if view:
            row["view"] = view
        if fix:
            row["fix"] = fix
        findings.append(row)

    title = (W - TITLE_W, 0.0, W, TITLE_H)
    for v in views:
        b = _box(v)
        name = v["name"]
        if b[0] < MARGIN or b[1] < MARGIN or b[2] > W - MARGIN or b[3] > H - MARGIN:
            cx, cy = _centre(b)
            w, h = b[2] - b[0], b[3] - b[1]
            nx = min(max(cx, MARGIN + w / 2), W - MARGIN - w / 2)
            ny = min(max(cy, MARGIN + h / 2), H - MARGIN - h / 2)
            moves[name] = [round(nx, 1), round(ny, 1)]
            find("major", "off_sheet", f"{name} runs off the sheet.", name, {"do": "move", "view": name, "to": moves[name]})
        if _overlap_area(b, title) > 1.0:
            cx, cy = _centre(b)
            ny = TITLE_H + (b[3] - b[1]) / 2 + MIN_GAP
            moves[name] = [round(cx, 1), round(max(ny, cy), 1)]
            find("major", "title_block", f"{name} overlaps the title block area.", name, {"do": "move", "view": name, "to": moves[name]})
    for i, a in enumerate(views):
        for b in views[i + 1:]:
            ba, bb = _box(a), _box(b)
            if _overlap_area(ba, bb) > 1.0:
                find("major", "overlap", f"{a['name']} and {b['name']} overlap.", b["name"])
            elif 0 <= _gap(ba, bb) < MIN_GAP and _orient(a) != "isometric" and _orient(b) != "isometric":
                find("minor", "crowded", f"{a['name']} and {b['name']} are {_gap(ba, bb):.0f} mm apart: too little room for dimensions "
                                        f"(about {MIN_GAP:.0f} mm or more).", b["name"])
    by = {}
    for v in views:
        o = _orient(v)
        if v.get("type") in ("model", "projected", None) and o in ("front", "top", "right", "left", "bottom", "back"):
            by.setdefault(o, v)
    front = by.get("front")
    if front:
        fb = _box(front)
        fx, fy = _centre(fb)
        for o, want in (("top", "above" if proj == "third" else "below"), ("bottom", "below" if proj == "third" else "above"),
                        ("right", "right" if proj == "third" else "left"), ("left", "left" if proj == "third" else "right")):
            v = by.get(o)
            if not v:
                continue
            b = _box(v)
            cx, cy = _centre(b)
            ok = {"above": cy > fy, "below": cy < fy, "right": cx > fx, "left": cx < fx}[want]
            if not ok:
                w, h = b[2] - b[0], b[3] - b[1]
                gap = 2 * MIN_GAP
                to = {"above": [fx, fb[3] + gap + h / 2], "below": [fx, fb[1] - gap - h / 2],
                      "right": [fb[2] + gap + w / 2, fy], "left": [fb[0] - gap - w / 2, fy]}[want]
                nb = (to[0] - w / 2, to[1] - h / 2, to[0] + w / 2, to[1] + h / 2)
                others = [_box(x) for x in views if x is not v]
                fits = (nb[0] >= MARGIN and nb[1] >= MARGIN and nb[2] <= W - MARGIN and nb[3] <= H - MARGIN
                        and not any(_overlap_area(nb, ob) > 0 for ob in others) and _overlap_area(nb, title) <= 0)
                fix = None
                extra = None
                if not fits and want in ("above", "right"):
                    # no room on that side: shift the front view away by the overflow, then place the view beside it
                    over = (nb[3] - (H - MARGIN)) if want == "above" else (nb[2] - (W - MARGIN))
                    if over > 0:
                        sh = (0.0, -over) if want == "above" else (-over, 0.0)
                        f2 = (fb[0] + sh[0], fb[1] + sh[1], fb[2] + sh[0], fb[3] + sh[1])
                        nb2 = (nb[0] + sh[0], nb[1] + sh[1], nb[2] + sh[0], nb[3] + sh[1])
                        rest = [_box(x) for x in views if x is not v and x is not front]
                        if (min(f2[0], nb2[0]) >= MARGIN and min(f2[1], nb2[1]) >= MARGIN and _overlap_area(f2, title) <= 0
                                and _overlap_area(nb2, title) <= 0 and not any(_overlap_area(bx, ob) > 0 for bx in (f2, nb2) for ob in rest)):
                            fits = True
                            nb = nb2
                            to = [to[0] + sh[0], to[1] + sh[1]]
                            fx, fy = fx + sh[0], fy + sh[1]
                            fb = f2
                            moves[front["name"]] = [round(fx, 1), round(fy, 1)]
                            extra = {"do": "move", "view": front["name"], "to": moves[front["name"]]}
                if fits:
                    moves[v["name"]] = [round(to[0], 1), round(to[1], 1)]
                    fix = {"do": "move", "view": v["name"], "to": moves[v["name"]]}
                    if extra:
                        find("minor", "make_room", f"{front['name']} moves to make room for {v['name']}.", front["name"], extra)
                find("major", "projection_position", f"{v['name']} ({o}) should be {want} the front view in {proj} angle projection."
                     + ("" if fix else " There is no free room there: move or rescale views by hand."), v["name"], fix)
                continue
            vertical = o in ("top", "bottom")
            off = (cx - fx) if vertical else (cy - fy)
            if abs(off) > ALIGN_TOL and ok:
                to = [round(fx, 1), round(cy, 1)] if vertical else [round(cx, 1), round(fy, 1)]
                moves[v["name"]] = to
                find("minor", "alignment", f"{v['name']} ({o}) is {abs(off):.1f} mm out of line with the front view.", v["name"],
                     {"do": "move", "view": v["name"], "to": to})
    else:
        top = by.get("top")
        if top and by.get("front") is None:
            pass
    usable = (W - 2 * MARGIN) * (H - 2 * MARGIN) - TITLE_W * TITLE_H
    used = sum((_box(v)[2] - _box(v)[0]) * (_box(v)[3] - _box(v)[1]) for v in views)
    fill = used / usable if usable > 0 else 0
    if views and fill < 0.10:
        find("minor", "white_space", f"The views fill {fill:.0%} of the sheet: a larger preferred scale or a smaller sheet would read better.")
    if fill > 0.70:
        find("minor", "crowded_sheet", f"The views fill {fill:.0%} of the sheet: no room for dimensions and notes; a larger sheet or a smaller scale.")
    for v in views:
        if _orient(v) == "isometric" and (v.get("dimensions") or 0) > 0:
            find("minor", "pictorial_dimensions", f"{v['name']} (isometric) carries {v['dimensions']} dimension(s): pictorial views carry none.", v["name"])
    if views:
        xs = [c for v in views for c in (_box(v)[0], _box(v)[2])]
        ys = [c for v in views for c in (_box(v)[1], _box(v)[3])]
        gx, gy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        ux, uy = W / 2, (H + TITLE_H) / 2
        if abs(gx - ux) > 0.25 * W or abs(gy - uy) > 0.25 * H:
            find("info", "balance", "The views sit well off the centre of the drawing area.")
    corrections = [f["fix"] for f in findings if f.get("fix")]
    return {"sheet": {"width_mm": W, "height_mm": H, "projection": proj}, "views": len(views), "fill": round(fill, 3),
            "findings": findings, "corrections": corrections}


def free_spot(drawing: dict, w: float, h: float, near: str | None = None) -> list[float]:
    """A centre for a new w x h view where it overlaps nothing, preferring the space right of or above `near`."""
    sheet = drawing.get("sheet") or {}
    W, H = float(sheet.get("width_mm") or 420), float(sheet.get("height_mm") or 297)
    boxes = [_box(v) for v in drawing.get("views") or [] if _box(v)]
    title = (W - TITLE_W, 0.0, W, TITLE_H)
    anchor = next((_box(v) for v in drawing.get("views") or [] if v.get("name") == near and _box(v)), None)
    cands = []
    step = 5.0
    y = MARGIN + h / 2
    while y <= H - MARGIN - h / 2:
        x = MARGIN + w / 2
        while x <= W - MARGIN - w / 2:
            b = (x - w / 2 - MIN_GAP / 2, y - h / 2 - MIN_GAP / 2, x + w / 2 + MIN_GAP / 2, y + h / 2 + MIN_GAP / 2)
            if not any(_overlap_area(b, o) > 0 for o in boxes + [title]):
                if anchor:
                    ax, ay = _centre(anchor)
                    d = abs(x - ax) + abs(y - ay)
                else:
                    d = abs(x - W / 2) + abs(y - H / 2)
                cands.append((d, x, y))
            x += step
        y += step
    if not cands:
        return [round(W - MARGIN - w / 2, 1), round(H - MARGIN - h / 2, 1)]
    _, x, y = min(cands)
    return [round(x, 1), round(y, 1)]


MIN_TEXT = 2.5          # mm: a commonly used minimum lettering height on drawings (company standards may differ)


def _abox(a: dict):
    b = a.get("box_mm")
    if not b or len(b) != 4:
        return None
    return (min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3]))


def evaluate_annotations(drawing: dict) -> dict[str, Any]:
    """Checks on the annotations themselves (sw_get_drawing annotations=true): overlaps between annotations, text
    off the sheet or in the title block, text below the minimum height, dimensions on a pictorial view. Fixes move
    an annotation's text only ({"do": "move_annotation"}), never its value or what it is attached to."""
    sheet = drawing.get("sheet") or {}
    W, H = float(sheet.get("width_mm") or 420), float(sheet.get("height_mm") or 297)
    title = (W - TITLE_W, 0.0, W, TITLE_H)
    findings: list[dict] = []
    rows = []
    iso_views = {str(v.get("name")) for v in drawing.get("views") or [] if _orient(v) == "isometric"}
    for grp in drawing.get("annotations") or []:
        for a in grp.get("annotations") or []:
            if a.get("error"):
                continue
            rows.append((grp.get("view"), a))
            if grp.get("view") in iso_views and a.get("type") == "dimension":
                findings.append({"severity": "minor", "category": "presentation", "check": "pictorial_dimensions",
                                 "message": f"{a.get('name')} is a dimension on the isometric {grp.get('view')}: pictorial views carry none.",
                                 "view": grp.get("view")})
    taken = []
    for view, a in rows:
        b = _abox(a)
        if b is None:
            continue
        name = a.get("name") or a.get("type")
        if b[0] < 0 or b[1] < 0 or b[2] > W or b[3] > H:
            findings.append({"severity": "major", "category": "presentation", "check": "annotation_off_sheet",
                             "message": f"{name} ({a.get('type')}) runs off the sheet.", "view": view})
        elif _overlap_area(b, title) > 1.0 and view != "Sheet":
            findings.append({"severity": "minor", "category": "presentation", "check": "annotation_title_block",
                             "message": f"{name} ({a.get('type')}) sits in the title block area.", "view": view})
        h = a.get("height_mm")
        if isinstance(h, (int, float)) and 0 < h < MIN_TEXT - 0.05:
            findings.append({"severity": "minor", "category": "presentation", "check": "text_height",
                             "message": f"{name}: text {h:g} mm high, under the {MIN_TEXT:g} mm minimum commonly used on drawings.", "view": view})
        for vb, other in taken:
            ov = _overlap_area(b, vb)
            if ov > 0.5:
                fix = None
                at = a.get("at")
                if at and a.get("name") and a.get("type") in ("dimension", "note", "gtol", "datum", "surface_finish"):
                    # the shortest move that clears the other box, plus a 1.5 mm gap
                    dx_r, dx_l = vb[2] - b[0] + 1.5, b[2] - vb[0] + 1.5
                    dy_u, dy_d = vb[3] - b[1] + 1.5, b[3] - vb[1] + 1.5
                    shift = min(((dx_r, 0), (-dx_l, 0), (0, dy_u), (0, -dy_d)), key=lambda d: abs(d[0]) + abs(d[1]))
                    nb = (b[0] + shift[0], b[1] + shift[1], b[2] + shift[0], b[3] + shift[1])
                    if nb[0] >= 0 and nb[1] >= 0 and nb[2] <= W and nb[3] <= H and not any(_overlap_area(nb, t) > 0.5 for t, _ in taken):
                        fix = {"do": "move_annotation", "name": a["name"], "to": [round(at[0] + shift[0], 2), round(at[1] + shift[1], 2)]}
                        b = nb
                findings.append({"severity": "minor", "category": "presentation", "check": "annotation_overlap",
                                 "message": f"{name} overlaps {other.get('name') or other.get('type')}.", "view": view,
                                 **({"fix": fix} if fix else {})})
                if fix:
                    break
        taken.append((b, a))
    counts = {}
    for _, a in rows:
        counts[a.get("type")] = counts.get(a.get("type"), 0) + 1
    tables = [t for g in drawing.get("annotations") or [] for t in g.get("tables") or []]
    for t in tables:
        tb = _abox(t)
        if tb is None:
            continue
        if tb[0] < 0 or tb[1] < 0 or tb[2] > W or tb[3] > H:
            findings.append({"severity": "major", "category": "presentation", "check": "table_off_sheet",
                             "message": f"The {t.get('type')} table runs off the sheet."})
        for v in drawing.get("views") or []:
            o = v.get("outline_mm")
            if o and _overlap_area(tb, (min(o[0], o[2]), min(o[1], o[3]), max(o[0], o[2]), max(o[1], o[3]))) > 1.0:
                findings.append({"severity": "major", "category": "presentation", "check": "table_overlaps_view",
                                 "message": f"The {t.get('type')} table covers part of {v.get('name')}: move the view or the table.",
                                 "view": v.get("name")})
    return {"findings": findings, "corrections": [f["fix"] for f in findings if f.get("fix")], "counts": counts,
            "tables": [t.get("type") for t in tables],
            "notes": [a.get("text") for _, a in rows if a.get("type") == "note" and a.get("text")]}
