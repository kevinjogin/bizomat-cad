using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using OpenSketch.Sw.Core;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace OpenSketch.Sw
{
    /// <summary>Drawing annotations (add-in 0.15): reading every annotation of a drawing with its text, tolerance,
    /// position and bounding box (read_drawing annotations=true), and the dimensioning and annotation actions of
    /// edit_drawing: model-associated dimensions (smart, horizontal, vertical, diameter, radius, angular), ordinate
    /// dimensions, hole and chamfer callouts, centre lines and marks, dimension tolerances, surface texture symbols,
    /// datum symbols, geometric tolerance frames, weld symbols, revision, hole and weldment cut-list tables. All use
    /// SOLIDWORKS' own annotation objects (never text standing in for a symbol). Model points are model mm on the
    /// view's part; the nearest edge or face of that kind is selected in the view, so the annotation stays attached
    /// to the model geometry. Engineering values (tolerances, roughness, frames, weld sizes) come from the request
    /// as given; the server only sends them when a person confirmed them.</summary>
    public sealed partial class Commands
    {
        static readonly Dictionary<int, string> AnnotationTypes = new Dictionary<int, string>
        {
            [1] = "cosmetic_thread", [2] = "datum", [3] = "datum_target", [4] = "dimension", [5] = "gtol", [6] = "note", [7] = "surface_finish",
            [8] = "weld_symbol", [9] = "custom_symbol", [10] = "dowel_symbol", [11] = "leader", [12] = "block", [13] = "centre_mark",
            [14] = "table", [15] = "centre_line", [16] = "datum_origin", [17] = "weld_bead", [18] = "revision_cloud",
        };

        static readonly Dictionary<int, string> TableTypes = new Dictionary<int, string>
        {
            [0] = "general", [1] = "hole", [2] = "bom", [3] = "revision", [4] = "weldment_cut_list", [5] = "title_block", [6] = "weld",
            [7] = "bend", [8] = "punch", [9] = "general_tolerance",
        };

        // ------------------------------------------------------------------------- reading

        /// <summary>Every annotation on the current sheet, per view (the sheet itself is "Sheet"), with positions and
        /// boxes in sheet mm.</summary>
        List<object> Annotations(IDrawingDoc drw)
        {
            var o = new List<object>();
            var sheetView = drw.GetFirstView() as IView;
            var all = new List<IView>();
            if (sheetView != null) all.Add(sheetView);
            all.AddRange(Views(drw));
            var total = 0;
            foreach (var v in all)
            {
                var rows = new List<object>();
                foreach (var a in (v.GetAnnotations() as object[] ?? new object[0]).OfType<IAnnotation>())
                {
                    if (total++ > 1500) break;
                    try
                    {
                        rows.Add(AnnotationInfo(a));
                    }
                    catch (Exception ex)
                    {
                        rows.Add(J.O("error", ex.Message));
                    }
                }
                var tables = new List<object>();
                foreach (var t in (v.GetTableAnnotations() as object[] ?? new object[0]).OfType<ITableAnnotation>())
                    tables.Add(TableInfo(t));
                o.Add(J.O("view", ReferenceEquals(v, sheetView) ? "Sheet" : v.Name, "annotations", rows, "tables", tables));
            }
            return o;
        }

        Dictionary<string, object> AnnotationInfo(IAnnotation a)
        {
            var type = AnnotationTypes.TryGetValue(a.GetType(), out var tn) ? tn : "type " + a.GetType();
            var row = J.O("type", type, "name", a.GetName());
            if (a.GetPosition() is double[] p && p.Length >= 2) row["at"] = J.L(R(p[0] * 1000, 2), R(p[1] * 1000, 2));
            var box = AnnotationBox(a);
            if (box != null) row["box_mm"] = J.L(box[0], box[1], box[2], box[3]);
            var spec = a.GetSpecificAnnotation();
            switch (spec)
            {
                case INote n:
                    row["text"] = n.GetText();
                    if (n.GetExtent() is double[] e && e.Length >= 6)
                        row["box_mm"] = J.L(R(Math.Min(e[0], e[3]) * 1000, 2), R(Math.Min(e[1], e[4]) * 1000, 2), R(Math.Max(e[0], e[3]) * 1000, 2), R(Math.Max(e[1], e[4]) * 1000, 2));
                    if (n.GetTextCount() > 0) row["height_mm"] = R(n.GetTextHeightAtIndex(1) * 1000, 2);
                    break;
                case IDisplayDimension dd:
                {
                    var d = dd.GetDimension2(0) as IDimension;
                    row["kind"] = Enum.GetName(typeof(swDimensionType_e), dd.GetType())?.Replace("sw", "") ?? dd.GetType().ToString();
                    row["reference"] = dd.IsReferenceDim();
                    if (d != null)
                    {
                        var angle = d.GetType() == (int)swDimensionParamType_e.swDimensionParamTypeDoubleAngular;
                        row["dimension"] = d.FullName;
                        row["value"] = R(angle ? Units.Deg(d.SystemValue) : d.SystemValue * 1000, 6);
                        row["unit"] = angle ? "deg" : "mm";
                        var tol = d.Tolerance;
                        if (tol != null && tol.Type != (int)swTolType_e.swTolNONE)
                        {
                            var t = J.O("type", DrawingMath.ToleranceName(tol.Type));
                            if (tol.GetMinValue2(out var lo) == 0) t["lower"] = R(angle ? Units.Deg(lo) : lo * 1000, 6);
                            if (tol.GetMaxValue2(out var hi) == 0) t["upper"] = R(angle ? Units.Deg(hi) : hi * 1000, 6);
                            if (!string.IsNullOrEmpty(tol.GetHoleFitValue())) t["hole_fit"] = tol.GetHoleFitValue();
                            if (!string.IsNullOrEmpty(tol.GetShaftFitValue())) t["shaft_fit"] = tol.GetShaftFitValue();
                            row["tolerance"] = t;
                        }
                    }
                    var prefix = dd.GetText((int)swDimensionTextParts_e.swDimensionTextPrefix);
                    var suffix = dd.GetText((int)swDimensionTextParts_e.swDimensionTextSuffix);
                    if (!string.IsNullOrEmpty(prefix)) row["prefix"] = prefix;
                    if (!string.IsNullOrEmpty(suffix)) row["suffix"] = suffix;
                    break;
                }
                case IGtol g:
                {
                    var frames = new List<object>();
                    for (short i = 1; i <= g.GetFrameCount(); i++)
                        frames.Add(J.O("values", (g.GetFrameValues(i) as object[])?.OfType<string>().ToList()));
                    row["frames"] = frames;
                    break;
                }
                case IDatumTag dt:
                    row["label"] = dt.GetLabel();
                    break;
                case ISFSymbol sf:
                {
                    var texts = new List<object>();
                    for (var i = 0; i < sf.GetTextCount(); i++) texts.Add(sf.GetTextAtIndex(i));
                    row["texts"] = texts;
                    break;
                }
                case IWeldSymbol ws:
                {
                    var texts = new List<object>();
                    for (var i = 0; i < ws.GetTextCount(); i++) texts.Add(ws.GetTextAtIndex(i));
                    row["texts"] = texts;
                    break;
                }
            }
            return row;
        }

        /// <summary>An annotation's box in sheet mm from its display data (lines, arcs and text), or null.</summary>
        static double[] AnnotationBox(IAnnotation a)
        {
            if (!(a.GetDisplayData() is IDisplayData dd)) return null;
            var pts = new List<double[]>();
            for (var i = 0; i < dd.GetLineCount(); i++)
                pts.AddRange(DrawingMath.LinePoints(dd.GetLineAtIndex3(i) as double[]));
            for (var i = 0; i < dd.GetTextCount(); i++)
            {
                if (!(dd.GetTextPositionAtIndex(i) is double[] tp) || tp.Length < 2) continue;
                var h = dd.GetTextHeightAtIndex(i);
                var s = dd.GetTextAtIndex(i) ?? "";
                pts.AddRange(DrawingMath.TextCorners(tp[0], tp[1], h, s.Length));
            }
            return DrawingMath.Bounds(pts);
        }

        static Dictionary<string, object> TableInfo(ITableAnnotation t)
        {
            var rows = new List<object>();
            for (var r = 0; r < Math.Min(t.RowCount, 60); r++)
            {
                var cells = new List<object>();
                for (var c = 0; c < Math.Min(t.ColumnCount, 20); c++) cells.Add(t.get_Text(r, c));
                rows.Add(cells);
            }
            var row = J.O("type", TableTypes.TryGetValue(t.Type, out var tn) ? tn : "type " + t.Type, "rows", t.RowCount, "columns", t.ColumnCount, "cells", rows);
            var box = t.GetAnnotation() is IAnnotation an ? AnnotationBox(an) : null;
            if (box != null) row["box_mm"] = J.L(box[0], box[1], box[2], box[3]);
            return row;
        }

        // ------------------------------------------------------------------------- selecting model geometry in a view

        /// <summary>The part shown in a view (parts only for now).</summary>
        static IPartDoc PartOf(IView v)
        {
            var doc = v.ReferencedDocument as IModelDoc2 ?? throw new UserError($"{v.Name} shows no model.");
            if (!(doc is IPartDoc p)) throw new UserError($"{v.Name} shows an assembly: dimensions and annotations on model geometry work on part views for now.");
            return p;
        }

        static double[] Mm3(List<object> p)
        {
            if (p == null || p.Count != 3) throw new UserError("A model point is [x, y, z] in model mm.");
            return p.Select(x => Convert.ToDouble(x, CultureInfo.InvariantCulture) / 1000).ToArray();
        }

        /// <summary>The model edge nearest a model point (mm), of a kind: "circle", "line" or "any".</summary>
        static IEdge NearestEdge(IView v, List<object> point, string kind)
        {
            var q = Mm3(point);
            IEdge best = null;
            var bestD = double.MaxValue;
            foreach (var b in (PartOf(v).GetBodies2((int)swBodyType_e.swSolidBody, true) as object[] ?? new object[0]).OfType<IBody2>())
            {
                foreach (var e in (b.GetEdges() as object[] ?? new object[0]).OfType<IEdge>())
                {
                    var c = e.GetCurve() as ICurve;
                    if (c == null) continue;
                    if (kind == "circle" && !c.IsCircle()) continue;
                    if (kind == "line" && !c.IsLine()) continue;
                    if (!(e.GetClosestPointOn(q[0], q[1], q[2]) is double[] p) || p.Length < 3) continue;
                    var d = Math.Sqrt((p[0] - q[0]) * (p[0] - q[0]) + (p[1] - q[1]) * (p[1] - q[1]) + (p[2] - q[2]) * (p[2] - q[2]));
                    if (d < bestD)
                    {
                        bestD = d;
                        best = e;
                    }
                }
            }
            if (best == null || bestD > 0.002)
                throw new UserError($"No {(kind == "any" ? "" : kind + " ")}edge within 2 mm of [{string.Join(", ", point)}] in {v.Name}'s part.");
            return best;
        }

        static IFace2 NearestFace(IView v, List<object> point)
        {
            var q = Mm3(point);
            IFace2 best = null;
            var bestD = double.MaxValue;
            foreach (var b in (PartOf(v).GetBodies2((int)swBodyType_e.swSolidBody, true) as object[] ?? new object[0]).OfType<IBody2>())
                foreach (var f in (b.GetFaces() as object[] ?? new object[0]).OfType<IFace2>())
                {
                    if (!(f.GetClosestPointOn(q[0], q[1], q[2]) is double[] p) || p.Length < 3) continue;
                    var d = Math.Sqrt((p[0] - q[0]) * (p[0] - q[0]) + (p[1] - q[1]) * (p[1] - q[1]) + (p[2] - q[2]) * (p[2] - q[2]));
                    if (d < bestD)
                    {
                        bestD = d;
                        best = f;
                    }
                }
            if (best == null || bestD > 0.002) throw new UserError($"No face within 2 mm of [{string.Join(", ", point)}] in {v.Name}'s part.");
            return best;
        }

        /// <summary>Select model edges (or a face) in the view, the view active, nothing else selected.</summary>
        void SelectInView(IModelDoc2 m, IDrawingDoc drw, IView v, IEnumerable<List<object>> points, string kind, bool face = false)
        {
            if (!drw.ActivateView(v.Name)) throw new UserError($"Could not activate {v.Name}.");
            m.ClearSelection2(true);
            var first = true;
            foreach (var p in points)
            {
                var ent = face ? (object)NearestFace(v, p) : NearestEdge(v, p, kind);
                if (!v.SelectEntity(ent, !first)) throw new UserError($"{v.Name} does not show the {(face ? "face" : "edge")} at [{string.Join(", ", p)}] (hidden in this view?).");
                first = false;
            }
        }

        static List<List<object>> PointList(Dictionary<string, object> act, string key, int min, int max)
        {
            var arr = J.Arr(act, key) ?? throw new UserError($"{key}: a list of model points [x, y, z] (mm).");
            var o = arr.Select(x => x as List<object>).ToList();
            if (o.Count < min || o.Count > max || o.Any(x => x == null || x.Count != 3))
                throw new UserError($"{key}: {min} to {max} model points [x, y, z] (mm).");
            return o;
        }

        /// <summary>Where an annotation's text goes: "at" (sheet mm), else the first referenced model point's place on
        /// the sheet plus "offset" (sheet mm, default 12 right and 12 up), so the leader stays short.</summary>
        double[] PlaceNear(IView v, Dictionary<string, object> act, List<object> modelPoint)
        {
            if (J.Arr(act, "at") != null) return Pt(act, "at");
            var p = SheetPoint(v, modelPoint);
            var off = J.Arr(act, "offset");
            double dx = 12, dy = 12;
            if (off != null && off.Count >= 2)
            {
                dx = Convert.ToDouble(off[0], CultureInfo.InvariantCulture);
                dy = Convert.ToDouble(off[1], CultureInfo.InvariantCulture);
            }
            return new[] { p[0] + dx, p[1] + dy };
        }

        Dictionary<string, object> DimensionResult(object created, string what)
        {
            if (!(created is IDisplayDimension dd)) throw new UserError($"SOLIDWORKS did not add the {what} (check the selection and the view).");
            var a = dd.GetAnnotation() as IAnnotation;
            var o = a != null ? AnnotationInfo(a) : J.O();
            o["added"] = what;
            return o;
        }

        // ------------------------------------------------------------------------- actions

        /// <summary>The 0.15 actions; null when `what` is not one of them.</summary>
        Dictionary<string, object> ActAnnotation(IModelDoc2 m, IDrawingDoc drw, string what, Dictionary<string, object> act)
        {
            switch (what)
            {
                case "dimension": return ActDimension(m, drw, act);
                case "ordinate": return ActOrdinate(m, drw, act);
                case "hole_callout":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    var edge = PointList(act, "edge", 1, 1);
                    SelectInView(m, drw, v, edge, "circle");
                    var at = PlaceNear(v, act, edge[0]);
                    return DimensionResult(drw.AddHoleCallout2(at[0] / 1000, at[1] / 1000, 0), "hole callout");
                }
                case "chamfer_dimension":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    SelectInView(m, drw, v, PointList(act, "edges", 2, 2), "line");
                    var at = Pt(act, "at");
                    return DimensionResult(drw.AddChamferDim(at[0] / 1000, at[1] / 1000, 0), "chamfer dimension");
                }
                case "centre_line":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    if (J.Arr(act, "face") != null) SelectInView(m, drw, v, PointList(act, "face", 1, 1), "any", face: true);
                    else SelectInView(m, drw, v, PointList(act, "edges", 2, 2), "line");
                    if (drw.InsertCenterLine2() == null) throw new UserError("SOLIDWORKS did not add the centre line (a cylindrical face, or two edges, seen in the view).");
                    return J.O("added", "centre line");
                }
                case "centre_mark":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    SelectInView(m, drw, v, PointList(act, "edge", 1, 1), "circle");
                    var style = DrawingMath.Lookup(DrawingMath.CentreMarkStyles, J.Str(act, "style", "single"), "style");
                    if (drw.InsertCenterMark3(style, J.Bool(act, "propagate"), false) == null) throw new UserError("SOLIDWORKS did not add the centre mark.");
                    return J.O("added", "centre mark");
                }
                case "move_annotation":
                {
                    // presentation only: the annotation's position changes, never its value or what it is attached to
                    var name = J.Str(act, "name") ?? throw new UserError("name: the annotation's name (sw_get_drawing annotations=true).");
                    var at = Pt(act, "to");
                    var views = new List<IView>();
                    if (drw.GetFirstView() is IView sv) views.Add(sv);
                    views.AddRange(Views(drw));
                    foreach (var v in views)
                        foreach (var an in (v.GetAnnotations() as object[] ?? new object[0]).OfType<IAnnotation>())
                            if (string.Equals(an.GetName(), name, StringComparison.OrdinalIgnoreCase))
                            {
                                if (!an.SetPosition2(at[0] / 1000, at[1] / 1000, 0)) throw new UserError($"SOLIDWORKS did not move {name}.");
                                return AnnotationInfo(an);
                            }
                    throw new UserError($"No annotation named {name} on this sheet.");
                }
                case "tolerance": return ActTolerance(drw, act);
                case "surface_finish": return ActSurfaceFinish(m, drw, act);
                case "datum": return ActDatum(m, drw, act);
                case "gtol": return ActGtol(m, drw, act);
                case "weld_symbol": return ActWeld(m, drw, act);
                case "revision_table":
                {
                    var at = Pt(act, "at");
                    var sheet = drw.GetCurrentSheet() as ISheet ?? throw new UserError("No current sheet.");
                    var tmpl = TableTemplate(swUserPreferenceStringValue_e.swFileLocationsRevisionTableTemplates, "*.sldrevtbt", "standard revision");
                    var t = sheet.InsertRevisionTable2(true, at[0] / 1000, at[1] / 1000, (int)swBOMConfigurationAnchorType_e.swBOMConfigurationAnchor_TopRight,
                                                        tmpl ?? "", (int)swRevisionTableSymbolShape_e.swRevisionTable_CircleSymbol, true);
                    if (t == null) throw new UserError("SOLIDWORKS did not insert the revision table" + (tmpl == null ? " (no revision table template in its file locations)." : "."));
                    return J.O("added", "revision table", "template", tmpl);
                }
                case "hole_table":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    // the datum: an edge (or vertex) for the origin, then the face whose holes are listed
                    SelectInView(m, drw, v, PointList(act, "origin", 1, 1), "line");
                    var face = NearestFace(v, PointList(act, "face", 1, 1)[0]);
                    if (!v.SelectEntity(face, true)) throw new UserError("The view does not show that face.");
                    var at = Pt(act, "at");
                    var tmpl = TableTemplate(swUserPreferenceStringValue_e.swFileLocationsHoleTableTemplates, "*.sldholtbt", "standard hole");
                    var t = v.InsertHoleTable2(true, at[0] / 1000, at[1] / 1000, (int)swBOMConfigurationAnchorType_e.swBOMConfigurationAnchor_TopLeft,
                                               J.Str(act, "start", "A"), tmpl ?? "");
                    if (t == null) throw new UserError("SOLIDWORKS did not insert the hole table" + (tmpl == null ? " (no hole table template in its file locations)." : "."));
                    return J.O("added", "hole table", "template", tmpl, "table", TableInfo((ITableAnnotation)t));
                }
                case "cut_list":
                {
                    var v = ViewNamed(drw, J.Str(act, "view"));
                    var at = Pt(act, "at");
                    var tmpl = TableTemplate(swUserPreferenceStringValue_e.swFileLocationsWeldmentCutListTemplates, "*.sldwldtbt", "cut list");
                    var config = (PartOf(v) as IModelDoc2)?.GetActiveConfiguration() is IConfiguration c ? c.Name : "";
                    var t = v.InsertWeldmentTable(true, at[0] / 1000, at[1] / 1000, (int)swBOMConfigurationAnchorType_e.swBOMConfigurationAnchor_TopRight, config, tmpl ?? "");
                    if (t == null) throw new UserError("SOLIDWORKS did not insert the cut list (is the part a weldment?)" + (tmpl == null ? " No cut-list template in its file locations." : ""));
                    return J.O("added", "weldment cut list", "template", tmpl, "table", TableInfo((ITableAnnotation)t));
                }
                default:
                    return null;
            }
        }

        Dictionary<string, object> ActDimension(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            var kind = J.Str(act, "kind", "smart");
            var at = PlaceNear(v, act, PointList(act, "edges", 1, 30)[0]);
            double x = at[0] / 1000, y = at[1] / 1000;
            switch (kind)
            {
                case "diameter":
                    SelectInView(m, drw, v, PointList(act, "edges", 1, 1), "circle");
                    return DimensionResult(m.AddDiameterDimension2(x, y, 0), "diameter dimension");
                case "radius":
                    SelectInView(m, drw, v, PointList(act, "edges", 1, 1), "circle");
                    return DimensionResult(m.AddRadialDimension2(x, y, 0), "radius dimension");
                case "horizontal":
                    SelectInView(m, drw, v, PointList(act, "edges", 1, 2), "any");
                    return DimensionResult(m.AddHorizontalDimension2(x, y, 0), "horizontal dimension");
                case "vertical":
                    SelectInView(m, drw, v, PointList(act, "edges", 1, 2), "any");
                    return DimensionResult(m.AddVerticalDimension2(x, y, 0), "vertical dimension");
                case "angular":
                    SelectInView(m, drw, v, PointList(act, "edges", 2, 2), "line");
                    return DimensionResult(m.AddDimension2(x, y, 0), "angular dimension");
                case "smart":
                case "linear":
                    SelectInView(m, drw, v, PointList(act, "edges", 1, 2), "any");
                    return DimensionResult(m.AddDimension2(x, y, 0), "dimension");
                default:
                    throw new UserError("kind: smart, linear, horizontal, vertical, diameter, radius or angular.");
            }
        }

        /// <summary>Ordinate dimensions: the first edge is the zero, the others are measured from it.</summary>
        Dictionary<string, object> ActOrdinate(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            var pts = PointList(act, "edges", 2, 30);
            var dir = J.Str(act, "direction", "horizontal") == "vertical" ? swAddOrdinateDims_e.swVerticalOrdinate : swAddOrdinateDims_e.swHorizontalOrdinate;
            SelectInView(m, drw, v, pts, "any");
            var at = Pt(act, "at");
            var status = drw.AddOrdinateDimension2((int)dir, at[0] / 1000, at[1] / 1000, 0);
            if (status != 0) throw new UserError($"SOLIDWORKS did not add the ordinate dimensions (status {status}).");
            return J.O("added", "ordinate dimensions", "edges", pts.Count, "direction", dir == swAddOrdinateDims_e.swVerticalOrdinate ? "vertical" : "horizontal");
        }

        /// <summary>A tolerance on a dimension shown in the drawing, by the dimension's full name. On a model dimension
        /// this sets the model's own tolerance (it is the same dimension): the server sends it only with the
        /// person's confirmation.</summary>
        Dictionary<string, object> ActTolerance(IDrawingDoc drw, Dictionary<string, object> act)
        {
            var name = J.Str(act, "dimension") ?? throw new UserError("dimension: the dimension's full name (sw_get_drawing annotations=true lists them).");
            IDimension dim = null;
            foreach (var v in Views(drw))
            {
                for (var dd = v.GetFirstDisplayDimension5() as IDisplayDimension; dd != null && dim == null; dd = dd.GetNext5() as IDisplayDimension)
                {
                    var d = dd.GetDimension2(0) as IDimension;
                    if (d != null && (string.Equals(d.FullName, name, StringComparison.OrdinalIgnoreCase) || d.FullName.StartsWith(name + "@", StringComparison.OrdinalIgnoreCase)))
                        dim = d;
                }
                if (dim != null) break;
            }
            if (dim == null) throw new UserError($"No dimension {name} on this drawing.");
            // a model dimension (driving or driven) keeps its tolerance in the part: changing it here changes the part,
            // so only when the designer has agreed to that change (model_change=true). Only a dimension the drawing
            // itself owns ("RD1@Drawing View1") is free; anything not shown to be the drawing's counts as the model's.
            var drawingOwned = Views(drw).Any(v => dim.FullName.EndsWith("@" + v.GetName2(), StringComparison.OrdinalIgnoreCase));
            if (!drawingOwned && !J.Bool(act, "model_change"))
                throw new UserError($"{dim.FullName} is a model dimension: its tolerance is stored in the part, so setting it here " +
                                    "changes the part. Set it in the part, or pass model_change=true once the designer agrees.");
            var type = DrawingMath.Lookup(DrawingMath.ToleranceTypes, J.Str(act, "type"), "type");
            var tol = dim.Tolerance ?? throw new UserError("SOLIDWORKS gave no tolerance object for that dimension.");
            tol.Type = type;
            var ok = true;
            if (type == (int)swTolType_e.swTolFIT || type == (int)swTolType_e.swTolFITWITHTOL || type == (int)swTolType_e.swTolFITTOLONLY)
                ok = tol.SetFitValues(J.Str(act, "hole_fit", ""), J.Str(act, "shaft_fit", ""));
            if (act.ContainsKey("lower") || act.ContainsKey("upper"))
                ok &= tol.SetValues2(J.Num(act, "lower") / 1000, J.Num(act, "upper") / 1000, (int)swSetValueInConfiguration_e.swSetValue_InThisConfiguration, null);
            if (!ok) throw new UserError("SOLIDWORKS refused those tolerance values.");
            return J.O("dimension", dim.FullName, "tolerance", DrawingMath.ToleranceName(tol.Type), "applies_to_model", !drawingOwned,
                       "note", drawingOwned ? null : "a model dimension: the part now holds this tolerance and is changed (not saved: sw_save saves it)");
        }

        Dictionary<string, object> ActSurfaceFinish(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            var edge = PointList(act, "edge", 1, 1);
            SelectInView(m, drw, v, edge, "any");
            var at = PlaceNear(v, act, edge[0]);
            var sym = DrawingMath.Lookup(DrawingMath.SurfaceSymbols, J.Str(act, "symbol", "machining_required"), "symbol");
            var sf = m.Extension.InsertSurfaceFinishSymbol3(sym, (int)swLeaderStyle_e.swSTRAIGHT, at[0] / 1000, at[1] / 1000, 0,
                                                             (int)swSFLaySym_e.swSFNone, (int)swArrowStyle_e.swDOT_ARROWHEAD,
                                                             J.Str(act, "allowance", ""), J.Str(act, "other", ""), J.Str(act, "method", ""),
                                                             J.Str(act, "sampling", ""), J.Str(act, "roughness_max", ""), J.Str(act, "roughness_min", ""), "");
            if (sf == null) throw new UserError("SOLIDWORKS did not add the surface texture symbol.");
            return AnnotationInfo((IAnnotation)sf.GetAnnotation());
        }

        Dictionary<string, object> ActDatum(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            SelectInView(m, drw, v, PointList(act, "edge", 1, 1), "any");
            var dt = m.InsertDatumTag2() as IDatumTag ?? throw new UserError("SOLIDWORKS did not add the datum symbol.");
            var label = J.Str(act, "label", "A");
            if (!dt.SetLabel(label)) throw new UserError($"SOLIDWORKS did not take the datum label {label}.");
            var an = dt.GetAnnotation() as IAnnotation;
            if (an != null && J.Arr(act, "at") != null)
            {
                var at = Pt(act, "at");
                an.SetPosition2(at[0] / 1000, at[1] / 1000, 0);
            }
            return an != null ? AnnotationInfo(an) : J.O("added", "datum", "label", label);
        }

        Dictionary<string, object> ActGtol(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            if (J.Arr(act, "edge") != null) SelectInView(m, drw, v, PointList(act, "edge", 1, 1), "any");
            var frames = J.Arr(act, "frames") ?? throw new UserError("frames: [{symbol, tolerance, diameter, material_condition, datums}].");
            if (frames.Count < 1 || frames.Count > 3) throw new UserError("frames: 1 to 3.");
            var g = m.InsertGtol() as IGtol ?? throw new UserError("SOLIDWORKS did not add the geometric tolerance.");
            for (var i = 0; i < frames.Count; i++)
            {
                var f = J.Obj(frames[i]) ?? throw new UserError("Each frame is an object.");
                var sym = DrawingMath.Lookup(DrawingMath.GtolSymbols, J.Str(f, "symbol"), "symbol");
                var mc = DrawingMath.Lookup(DrawingMath.MaterialConditions, J.Str(f, "material_condition", ""), "material_condition");
                var datums = (J.Arr(f, "datums") ?? new List<object>()).Select(x => Convert.ToString(x, CultureInfo.InvariantCulture)).ToList();
                while (datums.Count < 3) datums.Add("");
                var no = (short)(i + 1);
                g.SetFrameSymbols(no, (short)sym, J.Bool(f, "diameter"), (short)mc, false, 0, 0, 0, 0);
                if (!g.SetFrameValues2(no, J.Str(f, "tolerance", ""), "", datums[0], datums[1], datums[2]))
                    throw new UserError($"SOLIDWORKS did not take frame {i + 1}'s values.");
            }
            if (J.Arr(act, "at") != null)
            {
                var at = Pt(act, "at");
                g.SetPosition(at[0] / 1000, at[1] / 1000, 0);
            }
            return AnnotationInfo((IAnnotation)g.GetAnnotation());
        }

        Dictionary<string, object> ActWeld(IModelDoc2 m, IDrawingDoc drw, Dictionary<string, object> act)
        {
            var v = ViewNamed(drw, J.Str(act, "view"));
            SelectInView(m, drw, v, PointList(act, "edge", 1, 1), "any");
            var ws = m.InsertWeldSymbol3() as IWeldSymbol ?? throw new UserError("SOLIDWORKS did not add the weld symbol.");
            var iso = J.Str(act, "standard", "iso") != "ansi";
            var side = J.Str(act, "side", "arrow");
            var code = DrawingMath.WeldSymbolCode(J.Str(act, "symbol"), iso);
            var size = J.Str(act, "size", "");
            var length = J.Str(act, "length", "");
            var ok = true;
            if (side == "arrow" || side == "both") ok &= ws.SetText(true, size, code, length, "", (int)swWeldSymbolContourTypes_e.swWeldContourNone);
            if (side == "other" || side == "both") ok &= ws.SetText(false, size, code, length, "", (int)swWeldSymbolContourTypes_e.swWeldContourNone);
            if (J.Bool(act, "field")) ok &= ws.SetFieldWeld((int)swWeldSymbolField_e.swFieldWeldUp);
            if (!string.IsNullOrEmpty(J.Str(act, "process"))) ok &= ws.SetProcess(true, J.Str(act, "process"), false);
            var an = ws.GetAnnotation() as IAnnotation;
            if (an != null && J.Bool(act, "all_around"))
                an.SetLeader2(true, (int)swLeaderSide_e.swLS_SMART, true, false, false, true);
            if (an != null && J.Arr(act, "at") != null)
            {
                var at = Pt(act, "at");
                an.SetPosition2(at[0] / 1000, at[1] / 1000, 0);
            }
            var o = an != null ? AnnotationInfo(an) : J.O("added", "weld symbol");
            o["symbol_code_sent"] = code;
            o["set_ok"] = ok;
            o["note"] = "symbol codes are checked in the live test: compare symbol_code_sent with texts read back";
            return o;
        }

        /// <summary>A table template from SOLIDWORKS' file locations (the one whose name starts with `prefer`, else the
        /// first), or null.</summary>
        string TableTemplate(swUserPreferenceStringValue_e where, string pattern, string prefer)
        {
            var dirs = (app.GetUserPreferenceStringValue((int)where) ?? "").Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var d in dirs)
            {
                try
                {
                    if (!Directory.Exists(d)) continue;
                    var files = Directory.GetFiles(d, pattern);
                    var pick = files.FirstOrDefault(f => Path.GetFileName(f).StartsWith(prefer, StringComparison.OrdinalIgnoreCase)) ?? files.FirstOrDefault();
                    if (pick != null) return pick;
                }
                catch (Exception)
                {
                }
            }
            return null;
        }
    }
}
