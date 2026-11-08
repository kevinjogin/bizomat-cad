using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace OpenSketch.Sw.Core
{
    /// <summary>
    /// BIZOMAT CAD's folder in the user's Documents: Documents\BIZOMAT CAD, with Settings, Projects, Templates, Logs,
    /// Cache and Backups beneath it. Documents is resolved with the Windows known-folder API (FOLDERID_Documents), so it
    /// is the right place whether Documents is redirected to OneDrive or is local.
    ///
    /// Up to 0.13 the add-in used Documents\OpenSketch (exports and the launcher macro). <see cref="Migrate"/> copies
    /// that folder's files into Projects, once, and never deletes, moves or overwrites anything: the old folder stays
    /// as it is, as a backup, with a note saying where the files went. A file that is locked or still being synced by
    /// OneDrive is left for the next start (the record in Backups says which ones). Nothing here ever creates a folder
    /// called OpenSketch. Only file names and counts are logged, never file contents.
    /// </summary>
    public static class UserFolders
    {
        public const string RootName = "BIZOMAT CAD";
        public const string LegacyName = "OpenSketch";
        public static readonly string[] Subfolders = { "Settings", "Projects", "Templates", "Logs", "Cache", "Backups" };
        /// <summary>The launcher macro (Tools > Macro > Run), written to the root by the manual installer.</summary>
        public const string MacroFileName = "BIZOMAT CAD.swb";
        public const string MacroTextFileName = "BIZOMAT CAD macro (paste into a new macro).txt";
        /// <summary>The migration's record, in Backups.</summary>
        public const string RecordName = "Earlier folder migration.json";
        /// <summary>The note left in the old folder once everything is copied.</summary>
        public const string MovedNote = "MOVED TO BIZOMAT CAD.txt";
        /// <summary>Added before the extension when both folders hold a different file of the same name.</summary>
        public const string ConflictSuffix = " (from earlier folder)";
        /// <summary>The old folder's launcher files: not copied (the installer writes new ones); they stay in the old folder.</summary>
        static readonly string[] LegacyLauncherFiles = { "OpenSketch.swb", "OpenSketch macro (paste into a new macro).txt" };

        /// <summary>Where Documents is. Tests (and nothing else) replace it.</summary>
        public static Func<string> DocumentsResolver = KnownDocuments;

        public static string Root(string documents = null) => Path.Combine(documents ?? DocumentsResolver(), RootName);

        /// <summary>Makes the root and its subfolders (they may exist already) and returns the root.</summary>
        public static string Ensure(string documents = null)
        {
            var root = Root(documents);
            foreach (var s in Subfolders) Directory.CreateDirectory(Path.Combine(root, s));
            return root;
        }

        /// <summary>A subfolder of the root (Settings, Projects, Templates, Logs, Cache or Backups), made if missing.</summary>
        public static string Sub(string name, string documents = null)
        {
            if (!Subfolders.Contains(name)) throw new ArgumentException("not a BIZOMAT CAD folder: " + name, nameof(name));
            return Path.Combine(Ensure(documents), name);
        }

        // ------------------------------------------------------------------------------------------- Documents

        // FOLDERID_Documents: the user's Documents, wherever it has been redirected (OneDrive, a server share).
        static readonly Guid FolderIdDocuments = new Guid("FDD39AD0-238F-46AF-ADB4-6C85480369C7");

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        static extern int SHGetKnownFolderPath([MarshalAs(UnmanagedType.LPStruct)] Guid rfid, uint dwFlags, IntPtr hToken, out IntPtr ppszPath);

        /// <summary>Documents from the Windows known-folder API; elsewhere, or if it fails, .NET's own MyDocuments.</summary>
        public static string KnownDocuments()
        {
            if (Environment.OSVersion.Platform == PlatformID.Win32NT)
            {
                try
                {
                    if (SHGetKnownFolderPath(FolderIdDocuments, 0, IntPtr.Zero, out var p) == 0 && p != IntPtr.Zero)
                    {
                        try
                        {
                            var path = Marshal.PtrToStringUni(p);
                            if (!string.IsNullOrWhiteSpace(path)) return path;
                        }
                        finally
                        {
                            Marshal.FreeCoTaskMem(p);
                        }
                    }
                }
                catch (Exception)
                {
                    // fall back below
                }
            }
            return Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        }

        /// <summary>
        /// Where the old folder may be: in today's Documents, and, if Documents has been redirected since (to or from
        /// OneDrive), in the user profile's Documents and OneDrive\Documents. Existing folders only, each once.
        /// </summary>
        public static List<string> LegacyFolders(string documents, string userProfile)
        {
            var found = new List<string>();
            var candidates = new List<string> { Path.Combine(documents, LegacyName) };
            if (!string.IsNullOrEmpty(userProfile))
            {
                candidates.Add(Path.Combine(userProfile, "Documents", LegacyName));
                candidates.Add(Path.Combine(userProfile, "OneDrive", "Documents", LegacyName));
            }
            foreach (var c in candidates)
            {
                if (!Directory.Exists(c)) continue;
                var full = Path.GetFullPath(c).TrimEnd(Path.DirectorySeparatorChar);
                if (!found.Any(f => string.Equals(f, full, StringComparison.OrdinalIgnoreCase))) found.Add(full);
            }
            return found;
        }

        // ------------------------------------------------------------------------------------------- migration

        public sealed class MigrationResult
        {
            /// <summary>none (no old folder), complete, or partial (some files are left for the next start).</summary>
            public string State = "none";
            public int Copied, Identical, KeptBoth, Skipped;
            public readonly List<string> Pending = new List<string>();
            public readonly List<string> Sources = new List<string>();
            public override string ToString() =>
                $"{State}: {Copied} copied, {KeptBoth} kept beside a different file of the same name, {Identical} already there, " +
                $"{Skipped} old launcher files left, {Pending.Count} waiting (locked or syncing)";
        }

        /// <summary>True unless an earlier migration finished (its record in Backups says complete).</summary>
        public static bool MigrationDone(string root)
        {
            var record = Path.Combine(root, "Backups", RecordName);
            try
            {
                return File.Exists(record) && J.Str(Json.ParseObject(File.ReadAllText(record)), "state") == "complete";
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Runs the migration if there is an old folder and it has not finished before. Never throws.</summary>
        public static MigrationResult MigrateIfNeeded(Action<string> log = null, string documents = null, string userProfile = null)
        {
            try
            {
                documents = documents ?? DocumentsResolver();
                userProfile = userProfile ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                var root = Ensure(documents);
                if (MigrationDone(root)) return new MigrationResult { State = "complete" };
                var legacy = LegacyFolders(documents, userProfile);
                if (legacy.Count == 0) return new MigrationResult();
                var r = Migrate(legacy, root);
                log?.Invoke($"BIZOMAT CAD folder: {Path.Combine(documents, RootName)}; files from {string.Join(", ", legacy)}: {r}");
                return r;
            }
            catch (Exception ex)
            {
                log?.Invoke("BIZOMAT CAD folder: the copy of the earlier folder's files did not run (" + ex.Message + "); it is tried again at the next start");
                return new MigrationResult { State = "partial" };
            }
        }

        /// <summary>Copies the old folders' files into root\Projects (same relative paths) and records what it did.</summary>
        public static MigrationResult Migrate(IList<string> legacyFolders, string root)
        {
            var result = new MigrationResult();
            var projects = Path.Combine(root, "Projects");
            Directory.CreateDirectory(projects);
            Directory.CreateDirectory(Path.Combine(root, "Backups"));
            foreach (var legacy in legacyFolders)
            {
                if (!Directory.Exists(legacy)) continue;
                result.Sources.Add(legacy);
                foreach (var file in SafeFiles(legacy, result))
                {
                    var rel = Relative(legacy, file);
                    if (rel.IndexOf(Path.DirectorySeparatorChar) < 0 &&
                        (LegacyLauncherFiles.Any(n => string.Equals(n, rel, StringComparison.OrdinalIgnoreCase)) ||
                         string.Equals(rel, MovedNote, StringComparison.OrdinalIgnoreCase)))
                    {
                        result.Skipped++;
                        continue;
                    }
                    try
                    {
                        var target = Path.Combine(projects, rel);
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        if (File.Exists(target))
                        {
                            if (SameContent(file, target))
                            {
                                result.Identical++;
                                continue;
                            }
                            target = BesideName(file, target);
                            if (target == null)
                            {
                                result.Identical++; // copied beside it on an earlier run
                                continue;
                            }
                            CopyNew(file, target);
                            result.KeptBoth++;
                        }
                        else
                        {
                            CopyNew(file, target);
                            result.Copied++;
                        }
                    }
                    catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
                    {
                        result.Pending.Add(rel); // locked, or a OneDrive file that could not be downloaded yet
                    }
                }
            }
            result.State = result.Sources.Count == 0 ? "none" : result.Pending.Count == 0 ? "complete" : "partial";
            WriteRecord(root, result);
            if (result.State == "complete")
            {
                foreach (var legacy in result.Sources) LeaveNote(legacy, root);
            }
            return result;
        }

        /// <summary>Every file under the folder; a folder that cannot be listed is left for the next start.</summary>
        static IEnumerable<string> SafeFiles(string dir, MigrationResult result)
        {
            var stack = new Stack<string>();
            stack.Push(dir);
            while (stack.Count > 0)
            {
                var d = stack.Pop();
                string[] files, dirs;
                try
                {
                    files = Directory.GetFiles(d);
                    dirs = Directory.GetDirectories(d);
                }
                catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
                {
                    result.Pending.Add(Relative(dir, d) + Path.DirectorySeparatorChar);
                    continue;
                }
                foreach (var f in files.OrderBy(x => x, StringComparer.OrdinalIgnoreCase)) yield return f;
                foreach (var s in dirs.OrderByDescending(x => x, StringComparer.OrdinalIgnoreCase))
                {
                    // links and junctions are not followed (they may point anywhere, even back here)
                    if ((File.GetAttributes(s) & FileAttributes.ReparsePoint) != 0) continue;
                    stack.Push(s);
                }
            }
        }

        static string Relative(string root, string path)
        {
            var r = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var p = Path.GetFullPath(path);
            return p.StartsWith(r, StringComparison.OrdinalIgnoreCase) ? p.Substring(r.Length) : Path.GetFileName(p);
        }

        /// <summary>A free name beside target ("name (from earlier folder).ext", then " (2)"...), or null when one of those
        /// already holds the same content (an earlier run copied it).</summary>
        static string BesideName(string source, string target)
        {
            var dir = Path.GetDirectoryName(target);
            var stem = Path.GetFileNameWithoutExtension(target);
            var ext = Path.GetExtension(target);
            for (var i = 1; i < 1000; i++)
            {
                var candidate = Path.Combine(dir, stem + ConflictSuffix + (i == 1 ? "" : " (" + i + ")") + ext);
                if (!File.Exists(candidate)) return candidate;
                if (SameContent(source, candidate)) return null;
            }
            throw new IOException("too many copies of " + Path.GetFileName(target));
        }

        /// <summary>Copies to a temporary name, then renames, so a stop in the middle never leaves a half file under the
        /// real name; never overwrites; keeps the original's last-write time.</summary>
        static void CopyNew(string source, string target)
        {
            var temp = target + ".bizomat-copy";
            if (File.Exists(temp)) File.Delete(temp); // our own leftover from an interrupted copy
            File.Copy(source, temp, false);
            File.SetLastWriteTimeUtc(temp, File.GetLastWriteTimeUtc(source));
            File.Move(temp, target); // fails if target appeared meanwhile: then it is retried next time
        }

        static bool SameContent(string a, string b)
        {
            var fa = new FileInfo(a);
            var fb = new FileInfo(b);
            if (fa.Length != fb.Length) return false;
            using (var sha = SHA256.Create())
            using (var sa = File.OpenRead(a))
            using (var sb = File.OpenRead(b))
                return sha.ComputeHash(sa).SequenceEqual(SHA256.Create().ComputeHash(sb));
        }

        static void WriteRecord(string root, MigrationResult r)
        {
            var record = J.O(
                "state", r.State,
                "when", DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                "from", r.Sources.Cast<object>().ToList(),
                "to", Path.Combine(root, "Projects"),
                "copied", r.Copied, "kept_both", r.KeptBoth, "already_there", r.Identical, "old_launcher_files_left", r.Skipped,
                "waiting", r.Pending.Cast<object>().ToList(),
                "note", "Files are copied, never moved or deleted: the earlier folder is kept as a backup. Files listed under waiting were locked or still syncing and are tried again at the next start.");
            var path = Path.Combine(root, "Backups", RecordName);
            File.WriteAllText(path + ".tmp", Json.Write(record));
            if (File.Exists(path)) File.Delete(path);
            File.Move(path + ".tmp", path);
        }

        static void LeaveNote(string legacy, string root)
        {
            try
            {
                var note = Path.Combine(legacy, MovedNote);
                if (File.Exists(note)) return;
                File.WriteAllText(note,
                    "BIZOMAT CAD now keeps its files in:\r\n  " + Path.Combine(root, "Projects") + "\r\n\r\n" +
                    "Every file from this folder was copied there; nothing here was changed or deleted. Keep this folder as a\r\n" +
                    "backup until you have checked your files in BIZOMAT CAD, then you may delete it.\r\n" +
                    "Details: " + Path.Combine(root, "Backups", RecordName) + "\r\n");
            }
            catch (Exception)
            {
                // a note is a courtesy: a read-only or syncing folder simply gets none
            }
        }
    }
}
