using System;
using System.Collections.Generic;
using OpenSketch.Sw.Core;
using Xunit;

namespace OpenSketch.Sw.Tests
{
    /// <summary>The pure helpers behind the 0.15 model-data reads and drawing annotations (Core/DrawingMath.cs).</summary>
    public class DrawingMathTests
    {
        [Fact]
        public void TheMassChainKeepsNativeUnitsAndConvertsThemOnce()
        {
            // a 346 x 246 x 27 mm block of steel: 2.2981 dm^3, 7850 kg/m^3
            var v = 0.346 * 0.246 * 0.027;
            var o = DrawingMath.MassChain(v * 7850, v, 7850, 0.2, useSystemUnitsBefore: false, overrideMass: false, userAssigned: false);
            var native = (Dictionary<string, object>)o["native"];
            Assert.Equal("kg", ((Dictionary<string, object>)native["mass"])["unit"]);
            Assert.Equal("m^3", ((Dictionary<string, object>)native["volume"])["unit"]);
            Assert.Equal(false, native["use_system_units_was"]);
            var g = (Dictionary<string, object>)o["mass"];
            Assert.Equal("g", g["unit"]);
            Assert.Equal(Math.Round(v * 7850 * 1000, 6), g["value"]);
            Assert.Equal(Math.Round(v * 1e9, 3), ((Dictionary<string, object>)o["volume"])["value"]);
            Assert.Equal(7.85, ((Dictionary<string, object>)o["density"])["value"]);
            Assert.Equal(true, o["consistent"]);
        }

        [Fact]
        public void AnOverriddenMassShowsAsInconsistentWithTheDensity()
        {
            // a mass of 2.256 g for 2.256 dm^3 is 1 kg/m^3; if SOLIDWORKS at the same time reports a density of
            // 1000 kg/m^3, mass and density disagree: that points at an overridden mass, not at a missing material
            var o = DrawingMath.MassChain(0.002256, 0.002256, 1000, 0.2, true, overrideMass: true, userAssigned: false);
            Assert.Equal(false, o["consistent"]);
            Assert.Equal(1.0, ((Dictionary<string, object>)o["density_from_mass_and_volume"])["value"]);
            Assert.Equal(true, o["override_mass"]);
        }

        [Fact]
        public void EnumValuesMatchTheSolidworks2022Interop()
        {
            Assert.Equal(2, DrawingMath.ToleranceTypes["bilateral"]);
            Assert.Equal(7, DrawingMath.ToleranceTypes["fit"]);
            Assert.Equal("symmetric", DrawingMath.ToleranceName(4));
            Assert.Equal(23, DrawingMath.GtolSymbols["position"]);
            Assert.Equal(15, DrawingMath.GtolSymbols["flatness"]);
            Assert.Equal(1, DrawingMath.MaterialConditions["M"]);
            Assert.Equal(1, DrawingMath.SurfaceSymbols["machining_required"]);
            Assert.Equal(4, DrawingMath.CentreMarkStyles["circular"]);
            var ex = Assert.Throws<ArgumentException>(() => DrawingMath.Lookup(DrawingMath.GtolSymbols, "wobble", "symbol"));
            Assert.Contains("position", ex.Message);
        }

        [Fact]
        public void WeldSymbolCodesPassThroughOrAreBuiltFromTheName()
        {
            Assert.Equal("<ISOWELD-FILLET>", DrawingMath.WeldSymbolCode("fillet", true));
            Assert.Equal("<WELD-FLARE-V>", DrawingMath.WeldSymbolCode("flare_v", false));
            Assert.Equal("<MY-CODE>", DrawingMath.WeldSymbolCode("<MY-CODE>", true));
            Assert.Equal("", DrawingMath.WeldSymbolCode(" ", true));
        }

        [Fact]
        public void BoundsAreInMillimetresAroundLinesAndText()
        {
            var pts = new List<double[]>();
            pts.AddRange(DrawingMath.LinePoints(new[] { 0.010, 0.020, 0, 0.050, 0.020, 0 }));
            pts.AddRange(DrawingMath.TextCorners(0.020, 0.022, 0.0035, 4));
            var b = DrawingMath.Bounds(pts);
            Assert.Equal(new[] { 10.0, 20.0, 50.0, 25.5 }, b);
            Assert.Null(DrawingMath.Bounds(new List<double[]>()));
            Assert.Empty(DrawingMath.LinePoints(new[] { 1.0, 2.0 }));
        }
    }
}
