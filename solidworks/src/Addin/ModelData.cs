using System;
using System.Collections.Generic;
using System.Linq;
using OpenSketch.Sw.Core;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace OpenSketch.Sw
{
    /// <summary>The model's data for drafting (sw_get_document details=true, add-in 0.15): units, the mass-property
    /// chain with explicit units, material per configuration, configurations, custom properties, Hole Wizard and
    /// cosmetic-thread definitions, feature parameters, every dimension with its tolerance, reference geometry and
    /// weldment cut-list items. Everything is read, nothing is changed: the mass properties are read through a
    /// fresh IMassProperty with UseSystemUnits set explicitly, and the value it had before is reported.</summary>
    public sealed partial class Commands
    {
        static readonly Dictionary<int, string> UnitSystems = new Dictionary<int, string>
        {
            [1] = "CGS", [2] = "MKS", [3] = "IPS", [4] = "Custom", [5] = "MMGS",
        };

        static readonly Dictionary<int, string> LengthUnits = new Dictionary<int, string>
        {
            [0] = "mm", [1] = "cm", [2] = "m", [3] = "in", [4] = "ft", [5] = "ft-in", [6] = "angstrom", [7] = "nm", [8] = "micron", [9] = "mil", [10] = "uin",
        };

        static readonly Dictionary<int, string> HoleTypes = Enum.GetValues(typeof(swWzdHoleTypes_e)).Cast<swWzdHoleTypes_e>()
            .GroupBy(e => (int)e).ToDictionary(g => g.Key, g => g.First().ToString().Replace("sw", ""));

        Dictionary<string, object> Details(IModelDoc2 m)
        {
            var o = J.O("units", UnitsOf(m), "configurations", Configurations(m), "custom_properties", Properties(m, ""));
            var active = (m.GetActiveConfiguration() as IConfiguration)?.Name;
            if (!string.IsNullOrEmpty(active)) o["configuration_properties"] = J.O("configuration", active, "properties", Properties(m, active));
            if (Kind(m) == "part")
            {
                o["material"] = Material(m);
                o["mass_properties"] = MassProperties(m);
                o["holes"] = HoleWizard(m);
                o["threads"] = CosmeticThreads(m);
                o["feature_parameters"] = FeatureParameters(m);
                o["cut_list"] = CutList(m);
            }
            o["dimensions"] = DimensionsDetailed(m);
            o["reference_geometry"] = Tree(m).Where(f => f.GetTypeName2() == "RefPlane" || f.GetTypeName2() == "RefAxis" || f.GetTypeName2() == "CoordSys")
                                             .Select(f => (object)J.O("name", f.Name, "type", f.GetTypeName2())).ToList();
            return o;
        }

        static Dictionary<string, object> UnitsOf(IModelDoc2 m)
        {
            var ext = m.Extension;
            int sys = ext.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitSystem, 0);
            int len = ext.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitsLinear, 0);
            int ang = ext.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitsAngular, 0);
            int massLen = ext.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitsMassPropLength, 0);
            int mass = ext.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitsMassPropMass, 0);
            return J.O("system", UnitSystems.TryGetValue(sys, out var s) ? s : "unit system " + sys,
                       "length", LengthUnits.TryGetValue(len, out var l) ? l : "length unit " + len,
                       "angle", ang == 0 ? "deg" : ang == 2 ? "rad" : "angle unit " + ang,
                       "mass_property_length", LengthUnits.TryGetValue(massLen, out var ml) ? ml : "length unit " + massLen,
                       "mass_property_mass_code", mass,
                       "values_returned_in", "mm, deg, g and the units each value names (the add-in converts from SOLIDWORKS' system units)");
        }

        static List<object> Configurations(IModelDoc2 m)
        {
            var active = (m.GetActiveConfiguration() as IConfiguration)?.Name;
            return (m.GetConfigurationNames() as object[] ?? new object[0]).OfType<string>()
                .Select(n => (object)J.O("name", n, "active", n == active)).ToList();
        }

        static List<object> Properties(IModelDoc2 m, string config)
        {
            var o = new List<object>();
            try
            {
                var cpm = m.Extension.get_CustomPropertyManager(config);
                if (cpm == null) return o;
                object names = null, types = null, values = null, resolved = null, links = null;
                cpm.GetAll3(ref names, ref types, ref values, ref resolved, ref links);
                var n = names as object[] ?? new object[0];
                var v = values as object[] ?? new object[0];
                var r = resolved as object[] ?? new object[0];
                for (var i = 0; i < n.Length; i++)
                    o.Add(J.O("name", n[i] as string, "value", i < v.Length ? v[i] as string : null, "resolved", i < r.Length ? r[i] as string : null));
            }
            catch (Exception)
            {
            }
            return o;
        }

        static Dictionary<string, object> Material(IModelDoc2 m)
        {
            var part = (IPartDoc)m;
            var per = new List<object>();
            foreach (var c in (m.GetConfigurationNames() as object[] ?? new object[0]).OfType<string>())
            {
                var name = part.GetMaterialPropertyName2(c, out var db) ?? "";
                per.Add(J.O("configuration", c, "name", name, "database", string.IsNullOrEmpty(db) ? null : db, "assigned", name.Length > 0));
            }
            var activeName = part.GetMaterialPropertyName2("", out var adb) ?? "";
            // the density SOLIDWORKS uses when no material is assigned (Document Properties > Material Properties)
            var docDensity = m.Extension.GetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swMaterialPropertyDensity, 0);
            return J.O("active", J.O("name", activeName, "database", string.IsNullOrEmpty(adb) ? null : adb, "assigned", activeName.Length > 0),
                       "per_configuration", per, "document_density", DrawingMath.Q(docDensity, "kg/m^3", 6),
                       "note", "assigned=false means SOLIDWORKS reports no material for that configuration; the mass then uses document_density");
        }

        static Dictionary<string, object> MassProperties(IModelDoc2 m)
        {
            var mp = m.Extension.CreateMassProperty() as IMassProperty;
            if (mp == null) return J.O("error", "SOLIDWORKS gave no mass properties (no solid body?)");
            var before = mp.UseSystemUnits;
            mp.UseSystemUnits = true;
            return DrawingMath.MassChain(mp.Mass, mp.Volume, mp.Density, mp.SurfaceArea, before, mp.OverrideMass, mp.UserAssigned);
        }

        List<object> HoleWizard(IModelDoc2 m)
        {
            var o = new List<object>();
            foreach (var f in Tree(m))
            {
                var t = f.GetTypeName2();
                if (t != "HoleWzd" && t != "AdvHoleWzd") continue;
                try
                {
                    if (!(f.GetDefinition() is IWizardHoleFeatureData2 h))
                    {
                        o.Add(J.O("feature", f.Name, "type", t, "note", "an Advanced Hole: its elements are not read yet"));
                        continue;
                    }
                    double mm(double v) => R(v * 1000, 4);
                    var row = J.O("feature", f.Name, "hole_type", HoleTypes.TryGetValue(h.Type, out var ht) ? ht : h.Type.ToString(),
                                  "standard", h.Standard, "fastener_type", h.FastenerType, "size", h.FastenerSize,
                                  "thread_class", string.IsNullOrEmpty(h.ThreadClass) ? null : h.ThreadClass,
                                  "end_condition", Enum.GetName(typeof(swEndConditions_e), h.EndCondition) ?? h.EndCondition.ToString(),
                                  "instances", h.GetSketchPointCount(), "unit", "mm");
                    void put(string key, double v) { if (v > 0) row[key] = mm(v); }
                    put("hole_diameter", h.HoleDiameter);
                    put("hole_depth", h.HoleDepth);
                    put("thru_hole_diameter", h.ThruHoleDiameter);
                    put("tap_drill_diameter", h.TapDrillDiameter);
                    put("tap_drill_depth", h.TapDrillDepth);
                    put("thread_diameter", h.ThreadDiameter);
                    put("thread_depth", h.ThreadDepth);
                    put("counterbore_diameter", h.CounterBoreDiameter);
                    put("counterbore_depth", h.CounterBoreDepth);
                    put("countersink_diameter", h.CounterSinkDiameter);
                    if (h.CounterSinkAngle > 0) row["countersink_angle_deg"] = R(Units.Deg(h.CounterSinkAngle), 3);
                    if (h.DrillAngle > 0) row["drill_angle_deg"] = R(Units.Deg(h.DrillAngle), 3);
                    // a thread only when SOLIDWORKS says the hole is tapped (its type), or gives a thread size and depth:
                    // a tap-drill value alone is not taken as a thread
                    var tappedType = (row["hole_type"] as string ?? "").IndexOf("Tap", StringComparison.OrdinalIgnoreCase) >= 0;
                    row["threaded"] = tappedType || (h.ThreadDepth > 0 && h.ThreadDiameter > 0);
                    row["threaded_basis"] = tappedType ? "hole type" : (bool)row["threaded"] ? "thread diameter and depth" : null;
                    o.Add(row);
                }
                catch (Exception ex)
                {
                    o.Add(J.O("feature", f.Name, "type", t, "error", ex.Message));
                }
            }
            return o;
        }

        List<object> CosmeticThreads(IModelDoc2 m)
        {
            var o = new List<object>();
            foreach (var f in AllFeatures(m))
            {
                if (f.GetTypeName2() != "CosmeticThread") continue;
                try
                {
                    if (!(f.GetDefinition() is ICosmeticThreadFeatureData c)) continue;
                    o.Add(J.O("feature", f.Name, "callout", c.ThreadCallout, "size", c.Size, "standard_type", c.StandardType,
                              "diameter", DrawingMath.Q(c.Diameter * 1000, "mm", 4), "depth", c.BlindDepth > 0 ? DrawingMath.Q(c.BlindDepth * 1000, "mm", 4) : null,
                              "end_condition", c.EndCondition));
                }
                catch (Exception ex)
                {
                    o.Add(J.O("feature", f.Name, "error", ex.Message));
                }
            }
            return o;
        }

        /// <summary>The tree with sub-features (cosmetic threads sit under the holes they belong to).</summary>
        static List<IFeature> AllFeatures(IModelDoc2 m)
        {
            var o = new List<IFeature>();
            foreach (var f in Tree(m))
            {
                o.Add(f);
                var guard = 0;
                for (var s = f.GetFirstSubFeature() as IFeature; s != null && guard++ < 1000; s = s.GetNextSubFeature() as IFeature) o.Add(s);
            }
            return o;
        }

        List<object> FeatureParameters(IModelDoc2 m)
        {
            var o = new List<object>();
            foreach (var f in Tree(m))
            {
                var t = f.GetTypeName2();
                try
                {
                    switch (t)
                    {
                        case "Extrusion":
                        case "ICE":
                        case "Boss":
                        case "Cut":
                            if (f.GetDefinition() is IExtrudeFeatureData2 e)
                                o.Add(J.O("feature", f.Name, "type", t, "depth", DrawingMath.Q(e.GetDepth(true) * 1000, "mm", 4),
                                          "end_condition", Enum.GetName(typeof(swEndConditions_e), e.GetEndCondition(true)) ?? e.GetEndCondition(true).ToString()));
                            break;
                        case "Fillet":
                            if (f.GetDefinition() is ISimpleFilletFeatureData2 fl)
                                o.Add(J.O("feature", f.Name, "type", t, "radius", DrawingMath.Q(fl.DefaultRadius * 1000, "mm", 4)));
                            break;
                        case "Chamfer":
                            if (f.GetDefinition() is IChamferFeatureData2 ch)
                                o.Add(J.O("feature", f.Name, "type", t, "distance", DrawingMath.Q(ch.GetEdgeChamferDistance(0) * 1000, "mm", 4),
                                          "angle", DrawingMath.Q(Units.Deg(ch.EdgeChamferAngle), "deg", 3)));
                            break;
                    }
                }
                catch (Exception ex)
                {
                    o.Add(J.O("feature", f.Name, "type", t, "error", ex.Message));
                }
            }
            return o;
        }

        /// <summary>Every model dimension once (by full name) with its value and tolerance.</summary>
        List<object> DimensionsDetailed(IModelDoc2 m)
        {
            var o = new List<object>();
            var seen = new HashSet<string>();
            foreach (var f in AllFeatures(m))
            {
                var guard = 0;
                for (var dd = f.GetFirstDisplayDimension() as IDisplayDimension; dd != null && guard++ < 500; dd = f.GetNextDisplayDimension(dd) as IDisplayDimension)
                {
                    var d = dd.GetDimension2(0) as IDimension;
                    if (d == null || !seen.Add(d.FullName)) continue;
                    var angle = d.GetType() == (int)swDimensionParamType_e.swDimensionParamTypeDoubleAngular;
                    double scale(double v) => angle ? Units.Deg(v) : v * 1000;
                    var unit = angle ? "deg" : "mm";
                    var row = J.O("name", d.FullName, "value", R(scale(d.SystemValue), 6), "unit", unit, "feature", f.Name,
                                  "driven", d.DrivenState == (int)swDimensionDrivenState_e.swDimensionDriven, "reference", d.IsReference());
                    var tol = d.Tolerance;
                    if (tol != null && tol.Type != (int)swTolType_e.swTolNONE)
                    {
                        var t = J.O("type", DrawingMath.ToleranceName(tol.Type), "unit", unit);
                        if (tol.GetMinValue2(out var lo) == 0 || lo != 0) t["lower"] = R(scale(lo), 6);
                        if (tol.GetMaxValue2(out var hi) == 0 || hi != 0) t["upper"] = R(scale(hi), 6);
                        var hf = tol.GetHoleFitValue();
                        var sf = tol.GetShaftFitValue();
                        if (!string.IsNullOrEmpty(hf)) t["hole_fit"] = hf;
                        if (!string.IsNullOrEmpty(sf)) t["shaft_fit"] = sf;
                        row["tolerance"] = t;
                    }
                    o.Add(row);
                    if (o.Count >= 500) return o;
                }
            }
            return o;
        }

        /// <summary>Weldment cut-list items: each solid-body folder with its type, body count and custom properties
        /// (LENGTH, DESCRIPTION, ANGLE1/2 ... as SOLIDWORKS' weldment profiles define them).</summary>
        List<object> CutList(IModelDoc2 m)
        {
            var o = new List<object>();
            foreach (var f in AllFeatures(m))
            {
                if (f.GetTypeName2() != "CutListFolder") continue;
                try
                {
                    if (!(f.GetSpecificFeature2() is IBodyFolder bf)) continue;
                    var props = new List<object>();
                    var cpm = f.CustomPropertyManager;
                    if (cpm != null)
                    {
                        object names = null, types = null, values = null, resolved = null, links = null;
                        cpm.GetAll3(ref names, ref types, ref values, ref resolved, ref links);
                        var n = names as object[] ?? new object[0];
                        var r = resolved as object[] ?? new object[0];
                        var v = values as object[] ?? new object[0];
                        for (var i = 0; i < n.Length; i++)
                            props.Add(J.O("name", n[i] as string, "value", i < r.Length && r[i] is string rs && rs.Length > 0 ? rs : (i < v.Length ? v[i] as string : null)));
                    }
                    o.Add(J.O("folder", f.Name, "type", bf.GetCutListType(), "bodies", bf.GetBodyCount(), "properties", props));
                }
                catch (Exception ex)
                {
                    o.Add(J.O("folder", f.Name, "error", ex.Message));
                }
            }
            return o;
        }
    }
}
