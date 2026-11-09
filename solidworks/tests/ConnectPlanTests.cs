using OpenSketch.Sw.Core;
using Xunit;

namespace OpenSketch.Sw.Tests
{
    /// <summary>Connect / Reconnect from the task pane, the toolbar and the menu (Core/ConnectPlan.cs).</summary>
    public class ConnectPlanTests
    {
        [Fact]
        public void AStuckCompanionLinkIsDroppedAndStartedAgainWithTheCompanion()
        {
            // the case the task pane's button missed before 0.15: the link object exists but is not connected
            var p = ConnectPlan.For(pipeExists: true, pipeConnected: false, keySaved: false, companionInstalled: true);
            Assert.True(p.StopPipe);
            Assert.True(p.StartPipe);
            Assert.True(p.StartCompanion);
            Assert.False(p.ConnectDirect);
        }

        [Fact]
        public void AConnectedCompanionLinkIsNeverCut()
        {
            var p = ConnectPlan.For(pipeExists: true, pipeConnected: true, keySaved: true, companionInstalled: true);
            Assert.False(p.StopPipe);
            Assert.False(p.StartPipe);
            Assert.False(p.StartCompanion);
            Assert.True(p.ConnectDirect);
        }

        [Fact]
        public void NoLinkYetStartsOneAndOnlyAnInstalledCompanion()
        {
            var p = ConnectPlan.For(pipeExists: false, pipeConnected: false, keySaved: true, companionInstalled: false);
            Assert.False(p.StopPipe);
            Assert.True(p.StartPipe);
            Assert.False(p.StartCompanion);
            Assert.True(p.ConnectDirect);
        }
    }
}
