// BIZOMAT CAD, Phase 2.1: the SOLIDWORKS calls of windows/make-test-copies.ps1. PowerShell 5.1 cannot late-bind
// SOLIDWORKS' COM methods (TYPE_E_ELEMENTNOTFOUND), so the script compiles this with Add-Type against the interop
// library of the SOLIDWORKS installation and calls it step by step; the hashing and the checks stay in the script.
// C# 5 only (the compiler of Windows PowerShell 5.1): no string interpolation, no ?. , no out var.
// It never saves, renames or edits an original: the original drawing is opened read-only, Pack and Go writes the
// copies, and CloseDoc (which never saves) closes only what this helper opened.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

namespace Bizomat.Phase21
{
    public static class PackHelper
    {
        const int DocDrawing = 3;          // swDocumentTypes_e.swDocDRAWING
        const int OpenSilent = 1;          // swOpenDocOptions_e.swOpenDocOptions_Silent
        const int OpenReadOnly = 2;        // swOpenDocOptions_e.swOpenDocOptions_ReadOnly

        static ISldWorks sw;
        static ModelDoc2 original;
        static PackAndGo pack;
        static bool openedOriginal;

        public static string Connect()
        {
            sw = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
            return sw.RevisionNumber();
        }

        /// <summary>The original drawing: already open (with no unsaved changes) or opened read-only. Returns
        /// "was_open" or "opened"; throws with SOLIDWORKS' own error otherwise.</summary>
        public static string OpenOriginal(string path)
        {
            original = sw.GetOpenDocumentByName(path) as ModelDoc2;
            if (original != null)
            {
                if (original.GetSaveFlag())
                    throw new InvalidOperationException("The original drawing is open with unsaved changes. Close it without saving (Window > Close All, Don't Save), then run this again.");
                openedOriginal = false;
                return "was_open";
            }
            int errors = 0, warnings = 0;
            original = sw.OpenDoc6(path, DocDrawing, OpenSilent | OpenReadOnly, "", ref errors, ref warnings);
            if (original == null)
                throw new InvalidOperationException(string.Format("SOLIDWORKS could not open the original drawing (error {0}, warning {1}).", errors, warnings));
            openedOriginal = true;
            return "opened";
        }

        public static bool OriginalReadOnly()
        {
            return original.IsOpenedReadOnly();
        }

        /// <summary>The files a document references (full paths): GetDependencies2 gives name, path, name, path...</summary>
        static string[] Paths(object deps)
        {
            var list = new List<string>();
            var a = deps as object[];
            if (a == null)
            {
                var s = deps as string[];
                if (s != null) a = s;
            }
            if (a != null)
                for (var i = 0; i + 1 < a.Length; i += 2)
                    list.Add(Convert.ToString(a[i + 1]));
            return list.ToArray();
        }

        public static string[] OriginalReferences()
        {
            return Paths(original.GetDependencies2(true, true, false));
        }

        /// <summary>Pack and Go, planned only: returns original|copy lines, nothing is written yet.</summary>
        public static string[] Plan(string destination, string suffix)
        {
            pack = original.Extension.GetPackAndGo();
            pack.IncludeDrawings = true;
            pack.IncludeSimulationResults = false;
            pack.IncludeToolboxComponents = false;
            pack.FlattenToSingleFolder = true;
            pack.AddSuffix = suffix;
            if (!pack.SetSaveToName(true, destination))
                throw new InvalidOperationException("Pack and Go did not accept the destination folder.");
            object names, saveTo, status;
            pack.GetDocumentNames(out names);
            pack.GetDocumentSaveToNames(out saveTo, out status);
            var n = names as object[];
            var t = saveTo as object[];
            var lines = new List<string>();
            if (n != null && t != null)
                for (var i = 0; i < n.Length && i < t.Length; i++)
                    lines.Add(Convert.ToString(n[i]) + "|" + Convert.ToString(t[i]));
            return lines.ToArray();
        }

        /// <summary>Pack and Go, saved: one swPackAndGoSaveStatus_e per document (0 = saved).</summary>
        public static int[] Save()
        {
            var res = original.Extension.SavePackAndGo(pack);
            var codes = res as int[];
            if (codes != null) return codes;
            var objs = res as object[];
            if (objs == null) return new int[0];
            var outCodes = new int[objs.Length];
            for (var i = 0; i < objs.Length; i++) outCodes[i] = Convert.ToInt32(objs[i]);
            return outCodes;
        }

        /// <summary>Closes the original only when this helper opened it (CloseDoc never saves).</summary>
        public static bool CloseOriginal()
        {
            if (!openedOriginal || original == null) return false;
            sw.CloseDoc(original.GetTitle());
            openedOriginal = false;
            return true;
        }

        public static bool IsLoaded(string path)
        {
            return sw.GetOpenDocumentByName(path) != null;
        }

        /// <summary>The copied drawing, opened to check it: its stored and resolved references and every view's model,
        /// as "stored|path", "resolved|path", "view|name|model" and "open|errors|warnings" lines. Closed again after.</summary>
        public static string[] CheckCopy(string path)
        {
            var lines = new List<string>();
            int errors = 0, warnings = 0;
            var copy = sw.OpenDoc6(path, DocDrawing, OpenSilent, "", ref errors, ref warnings);
            if (copy == null)
                throw new InvalidOperationException(string.Format("SOLIDWORKS could not open the copied drawing (error {0}, warning {1}).", errors, warnings));
            lines.Add("open|" + errors + "|" + warnings);
            try
            {
                foreach (var p in Paths(copy.GetDependencies2(true, false, false))) lines.Add("stored|" + p);
                foreach (var p in Paths(copy.GetDependencies2(true, true, false))) lines.Add("resolved|" + p);
                var drawing = copy as DrawingDoc;
                var sheets = drawing == null ? null : drawing.GetViews() as object[];
                if (sheets != null)
                    foreach (var sheet in sheets)
                    {
                        var views = sheet as object[];
                        if (views == null) continue;
                        for (var i = 1; i < views.Length; i++)   // [0] is the sheet itself
                        {
                            var v = views[i] as View;
                            if (v != null) lines.Add("view|" + v.GetName2() + "|" + v.GetReferencedModelName());
                        }
                    }
            }
            finally
            {
                sw.CloseDoc(copy.GetTitle());   // nothing was changed in it; the harness opens it again
            }
            return lines.ToArray();
        }
    }
}
