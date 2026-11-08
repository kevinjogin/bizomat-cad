using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using OpenSketch.Sw.Core;
using Xunit;

namespace OpenSketch.Sw.Tests
{
    /// <summary>Documents\BIZOMAT CAD and the one-time copy of the old Documents\OpenSketch files (Core/UserFolders.cs).</summary>
    public class UserFoldersTests : IDisposable
    {
        readonly string home = Path.Combine(Path.GetTempPath(), "bzcad-test-" + Guid.NewGuid().ToString("N"));
        string Documents => Path.Combine(home, "OneDrive", "Documents");
        string Old => Path.Combine(Documents, "OpenSketch");
        string Root => Path.Combine(Documents, "BIZOMAT CAD");

        public UserFoldersTests() => Directory.CreateDirectory(Documents);

        public void Dispose()
        {
            try { Directory.Delete(home, true); } catch (Exception) { }
        }

        static void Write(string path, string text, DateTime? when = null)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, text);
            if (when != null) File.SetLastWriteTimeUtc(path, when.Value);
        }

        /// <summary>Every file under a folder with its SHA-256, by relative path.</summary>
        static Dictionary<string, string> Snapshot(string dir)
        {
            var d = new Dictionary<string, string>();
            if (!Directory.Exists(dir)) return d;
            foreach (var f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                using (var sha = SHA256.Create())
                    d[f.Substring(dir.Length + 1)] = Convert.ToBase64String(sha.ComputeHash(File.ReadAllBytes(f)));
            return d;
        }

        void OldFolder()
        {
            Write(Path.Combine(Old, "Bracket.SLDPRT"), "part", new DateTime(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc));
            Write(Path.Combine(Old, "selftest", "plate.SLDPRT"), "plate");
            Write(Path.Combine(Old, "selftest", "plate.PDF"), "pdf");
            Write(Path.Combine(Old, "Toolbox", "M6.SLDPRT"), "screw");
            Write(Path.Combine(Old, "OpenSketch.swb"), "old launcher");
            Write(Path.Combine(Old, "OpenSketch macro (paste into a new macro).txt"), "old launcher text");
        }

        [Fact]
        public void TheRootHasItsSubfoldersAndNoOpenSketchFolderIsMade()
        {
            var root = UserFolders.Ensure(Documents);
            Assert.Equal(Root, root);
            foreach (var s in new[] { "Settings", "Projects", "Templates", "Logs", "Cache", "Backups" })
                Assert.True(Directory.Exists(Path.Combine(root, s)), s);
            Assert.Equal(Path.Combine(Root, "Logs"), UserFolders.Sub("Logs", Documents));
            Assert.Throws<ArgumentException>(() => UserFolders.Sub("OpenSketch", Documents));
            var r = UserFolders.MigrateIfNeeded(null, Documents, home);
            Assert.Equal("none", r.State);
            Assert.False(Directory.Exists(Old));
            Assert.Empty(Directory.GetDirectories(home, "OpenSketch*", SearchOption.AllDirectories));
        }

        [Fact]
        public void OldFilesAreCopiedIntoProjectsAndTheOldFolderIsKeptUntouched()
        {
            OldFolder();
            var before = Snapshot(Old);
            var r = UserFolders.MigrateIfNeeded(null, Documents, home);
            Assert.Equal("complete", r.State);
            Assert.Equal(4, r.Copied);
            Assert.Equal(2, r.Skipped); // the old launcher files: the installer writes new ones
            var projects = Path.Combine(Root, "Projects");
            Assert.Equal("part", File.ReadAllText(Path.Combine(projects, "Bracket.SLDPRT")));
            Assert.Equal("plate", File.ReadAllText(Path.Combine(projects, "selftest", "plate.SLDPRT")));
            Assert.Equal("screw", File.ReadAllText(Path.Combine(projects, "Toolbox", "M6.SLDPRT")));
            Assert.False(File.Exists(Path.Combine(projects, "OpenSketch.swb")));
            Assert.Equal(new DateTime(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc), File.GetLastWriteTimeUtc(Path.Combine(projects, "Bracket.SLDPRT")));
            // nothing in the old folder changed or went: only the note was added
            var after = Snapshot(Old);
            Assert.True(after.Remove(UserFolders.MovedNote));
            Assert.Equal(before, after);
            Assert.Contains(projects, File.ReadAllText(Path.Combine(Old, UserFolders.MovedNote)));
            var record = Json.ParseObject(File.ReadAllText(Path.Combine(Root, "Backups", UserFolders.RecordName)));
            Assert.Equal("complete", J.Str(record, "state"));
            Assert.Empty(Directory.GetFiles(Root, "*.bizomat-copy", SearchOption.AllDirectories));
        }

        [Fact]
        public void ItRunsOnceAndARunAgainChangesNothing()
        {
            OldFolder();
            UserFolders.MigrateIfNeeded(null, Documents, home);
            var root = Snapshot(Root);
            var old = Snapshot(Old);
            Write(Path.Combine(Old, "later.SLDPRT"), "made after the move");
            var again = UserFolders.MigrateIfNeeded(null, Documents, home);
            Assert.Equal("complete", again.State);
            Assert.Equal(0, again.Copied);
            Assert.Equal(root, Snapshot(Root));
            Assert.Equal(old.Count + 1, Snapshot(Old).Count);
        }

        [Fact]
        public void ANewerOrDifferentFileIsNeverOverwrittenAndBothAreKept()
        {
            OldFolder();
            var projects = Path.Combine(Root, "Projects");
            Write(Path.Combine(projects, "Bracket.SLDPRT"), "my newer bracket", new DateTime(2026, 11, 7, 0, 0, 0, DateTimeKind.Utc));
            Write(Path.Combine(projects, "selftest", "plate.SLDPRT"), "plate"); // the same file: not copied twice
            var r = UserFolders.Migrate(new[] { Old }, UserFolders.Ensure(Documents));
            Assert.Equal("complete", r.State);
            Assert.Equal(1, r.KeptBoth);
            Assert.Equal(1, r.Identical);
            Assert.Equal("my newer bracket", File.ReadAllText(Path.Combine(projects, "Bracket.SLDPRT")));
            Assert.Equal("part", File.ReadAllText(Path.Combine(projects, "Bracket (from earlier folder).SLDPRT")));
            Assert.False(File.Exists(Path.Combine(projects, "selftest", "plate (from earlier folder).SLDPRT")));
            // an interrupted run that is repeated does not add more copies
            var again = UserFolders.Migrate(new[] { Old }, Root);
            Assert.Equal(0, again.KeptBoth + again.Copied);
            Assert.Single(Directory.GetFiles(projects, "Bracket (from earlier folder)*"));
        }

        [Fact]
        public void ALockedOrSyncingFileWaitsForTheNextStart()
        {
            OldFolder();
            var locked = Path.Combine(Old, "Bracket.SLDPRT");
            // held open by another program (SOLIDWORKS, or OneDrive still downloading it)
            using (new FileStream(locked, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                var r = UserFolders.MigrateIfNeeded(null, Documents, home);
                Assert.Equal("partial", r.State);
                Assert.Equal(new[] { "Bracket.SLDPRT" }, r.Pending.ToArray());
                Assert.False(File.Exists(Path.Combine(Old, UserFolders.MovedNote)), "no note until everything is copied");
                Assert.False(UserFolders.MigrationDone(Root));
            }
            var next = UserFolders.MigrateIfNeeded(null, Documents, home);
            Assert.Equal("complete", next.State);
            Assert.Equal(1, next.Copied);
            Assert.True(File.Exists(Path.Combine(Root, "Projects", "Bracket.SLDPRT")));
            Assert.True(File.Exists(locked), "the original stays");
        }

        [Fact]
        public void TheOldFolderIsFoundInLocalOrOneDriveDocumentsOnce()
        {
            var local = Path.Combine(home, "Documents", "OpenSketch");
            Directory.CreateDirectory(local);
            Directory.CreateDirectory(Old);
            var found = UserFolders.LegacyFolders(Documents, home);
            Assert.Equal(2, found.Count);
            Assert.Contains(Path.GetFullPath(Old), found);
            Assert.Contains(Path.GetFullPath(local), found);
            Assert.Single(UserFolders.LegacyFolders(Path.Combine(home, "Documents"), null));
        }
    }
}
