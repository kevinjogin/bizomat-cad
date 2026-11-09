using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace OpenSketch.Sw.Core
{
    /// <summary>Pure helpers for the add-in's model-data reads and drawing annotations (no SOLIDWORKS reference, so
    /// they are unit-tested on Linux): SOLIDWORKS enum values by name, the mass-property unit chain with explicit
    /// units, and bounding boxes of annotation geometry. Enum numbers are the SOLIDWORKS 2022 (30.5) interop's own
    /// (swTolType_e, swGtolGeomCharSymbol_e, swGtolMatCondition_e, swSFSymType_e, swCenterMarkStyle_e).</summary>
    public static class DrawingMath
    {
        public static readonly Dictionary<string, int> ToleranceTypes = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["none"] = 0, ["basic"] = 1, ["bilateral"] = 2, ["limit"] = 3, ["symmetric"] = 4, ["min"] = 5, ["max"] = 6,
            ["fit"] = 7, ["fit_with_tolerance"] = 8, ["fit_tolerance_only"] = 9, ["general"] = 11,
        };

        public static string ToleranceName(int type)
        {
            foreach (var kv in ToleranceTypes)
                if (kv.Value == type) return kv.Key;
            return type == 10 ? "block" : "type " + type;
        }

        public static readonly Dictionary<string, int> GtolSymbols = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["none"] = 12, ["symmetry"] = 13, ["straightness"] = 14, ["flatness"] = 15, ["circularity"] = 16, ["cylindricity"] = 17,
            ["profile_of_a_line"] = 18, ["profile_of_a_surface"] = 19, ["angularity"] = 20, ["perpendicularity"] = 21,
            ["parallelism"] = 22, ["position"] = 23, ["concentricity"] = 24, ["circular_runout"] = 25, ["total_runout"] = 26,
        };

        public static readonly Dictionary<string, int> MaterialConditions = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            [""] = 0, ["none"] = 0, ["M"] = 1, ["MMC"] = 1, ["RFS"] = 2, ["S"] = 2, ["L"] = 3, ["LMC"] = 3,
        };

        public static readonly Dictionary<string, int> SurfaceSymbols = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["basic"] = 0, ["machining_required"] = 1, ["no_machining"] = 2,
        };

        public static readonly Dictionary<string, int> CentreMarkStyles = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["single"] = 2, ["linear"] = 3, ["circular"] = 4,
        };

        /// <summary>Weld symbols by name, as codes of SOLIDWORKS' symbol library (gtol.sym). UNVERIFIED until the live
        /// test: the add-in reads the text back from SOLIDWORKS after setting it, so a wrong code shows at once.</summary>
        public static readonly string[] WeldSymbolNames = { "fillet", "square", "v", "bevel", "u", "j", "flare_v", "flare_bevel", "plug", "spot", "seam", "backing" };

        public static string WeldSymbolCode(string name, bool iso)
        {
            if (string.IsNullOrWhiteSpace(name)) return "";
            if (name.StartsWith("<", StringComparison.Ordinal)) return name;   // a library code given as is
            var n = name.Trim().ToUpperInvariant().Replace("_", "-");
            return iso ? "<ISOWELD-" + n + ">" : "<WELD-" + n + ">";
        }

        public static int Lookup(Dictionary<string, int> table, string name, string what)
        {
            if (name != null && table.TryGetValue(name.Trim(), out var v)) return v;
            throw new ArgumentException($"{what} is one of: {string.Join(", ", table.Keys.Where(k => k.Length > 0))}.");
        }

        /// <summary>A number with its unit, rounded for reading.</summary>
        public static Dictionary<string, object> Q(double value, string unit, int digits = 6)
            => new Dictionary<string, object> { ["value"] = Math.Round(value, digits), ["unit"] = unit };

        /// <summary>The mass-property chain in explicit units. SOLIDWORKS gives system units (kg, m^3, kg/m^3, m^2) when
        /// IMassProperty.UseSystemUnits is true; this records them as given, then the converted values, then whether
        /// density x volume agrees with the mass (it does not when the mass is overridden or user-assigned).</summary>
        public static Dictionary<string, object> MassChain(double massKg, double volumeM3, double densityKgM3, double areaM2,
                                                           bool useSystemUnitsBefore, bool overrideMass, bool userAssigned)
        {
            var o = new Dictionary<string, object>
            {
                ["native"] = new Dictionary<string, object>
                {
                    ["mass"] = Q(massKg, "kg", 9), ["volume"] = Q(volumeM3, "m^3", 12), ["density"] = Q(densityKgM3, "kg/m^3", 6),
                    ["surface_area"] = Q(areaM2, "m^2", 9), ["use_system_units_was"] = useSystemUnitsBefore, ["read_with_system_units"] = true,
                },
                ["mass"] = Q(massKg * 1000, "g", 6),
                ["volume"] = Q(volumeM3 * 1e9, "mm^3", 3),
                ["density"] = Q(densityKgM3 / 1000, "g/cm^3", 6),
                ["surface_area"] = Q(areaM2 * 1e6, "mm^2", 3),
                ["override_mass"] = overrideMass,
                ["user_assigned"] = userAssigned,
            };
            if (volumeM3 > 0)
            {
                var implied = massKg / volumeM3;
                o["density_from_mass_and_volume"] = Q(implied, "kg/m^3", 6);
                o["consistent"] = densityKgM3 <= 0 || Math.Abs(implied - densityKgM3) <= 1e-6 * Math.Max(1.0, densityKgM3);
            }
            return o;
        }

        /// <summary>The box [x0, y0, x1, y1] in mm around points given in metres, or null.</summary>
        public static double[] Bounds(IEnumerable<double[]> pointsM)
        {
            double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
            var any = false;
            foreach (var p in pointsM ?? Enumerable.Empty<double[]>())
            {
                if (p == null || p.Length < 2 || double.IsNaN(p[0]) || double.IsNaN(p[1])) continue;
                any = true;
                x0 = Math.Min(x0, p[0]); y0 = Math.Min(y0, p[1]); x1 = Math.Max(x1, p[0]); y1 = Math.Max(y1, p[1]);
            }
            if (!any) return null;
            return new[] { Math.Round(x0 * 1000, 2), Math.Round(y0 * 1000, 2), Math.Round(x1 * 1000, 2), Math.Round(y1 * 1000, 2) };
        }

        /// <summary>The corners of a text line in metres: anchored at (x, y), height h, about 0.62 h per character
        /// (an estimate used only when SOLIDWORKS gives the text's position and height but not its extent).</summary>
        public static IEnumerable<double[]> TextCorners(double x, double y, double h, int chars)
        {
            var w = Math.Max(1, chars) * 0.62 * h;
            yield return new[] { x, y };
            yield return new[] { x + w, y + h };
        }

        /// <summary>Line endpoints from IDisplayData.GetLineAtIndex3's array (start x, y, z, end x, y, z, ...).</summary>
        public static IEnumerable<double[]> LinePoints(double[] data)
        {
            if (data == null || data.Length < 6) yield break;
            yield return new[] { data[0], data[1] };
            yield return new[] { data[3], data[4] };
        }

        public static string Mm(double metres) => (metres * 1000).ToString("0.###", CultureInfo.InvariantCulture);
    }
}
