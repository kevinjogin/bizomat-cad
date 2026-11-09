namespace OpenSketch.Sw.Core
{
    /// <summary>What Connect (or Reconnect) does. One plan for the task pane's button, the toolbar button and the menu,
    /// so they always behave the same (before 0.15 the pane's button only restarted the direct link: a Companion link
    /// that was stuck, refused or waiting was left as it was, and the Companion was not started). Pure, so it is
    /// unit-tested without SOLIDWORKS.</summary>
    public static class ConnectPlan
    {
        public sealed class Steps
        {
            /// <summary>Drop the Companion link first: it exists but is not connected (stuck, refused or waiting).</summary>
            public bool StopPipe;
            /// <summary>Start the Companion link (again).</summary>
            public bool StartPipe;
            /// <summary>Start the BIZOMAT Companion (one per Windows user: a second start only reaches the running one).</summary>
            public bool StartCompanion;
            /// <summary>Connect the direct link (a key is saved).</summary>
            public bool ConnectDirect;

            public override string ToString() =>
                $"stop link {StopPipe}, start link {StartPipe}, start Companion {StartCompanion}, direct link {ConnectDirect}";
        }

        /// <param name="pipeExists">The Companion link object exists (running or retrying).</param>
        /// <param name="pipeConnected">The Companion link is connected: it is never cut, so a running command is not lost.</param>
        /// <param name="keySaved">A direct-link key is saved.</param>
        /// <param name="companionInstalled">The BIZOMAT Companion is installed next to the add-in.</param>
        public static Steps For(bool pipeExists, bool pipeConnected, bool keySaved, bool companionInstalled) => new Steps
        {
            StopPipe = pipeExists && !pipeConnected,
            StartPipe = !pipeConnected,
            StartCompanion = !pipeConnected && companionInstalled,
            ConnectDirect = keySaved,
        };
    }
}
