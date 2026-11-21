using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

public sealed class HoverSweepTests : KanjoTestCase
{
    [Fact]
    public void FixturePagesAcceptPointerEntryAndExit()
    {
        OnUi(() =>
        {
            var diskPath = Path.Combine(DefaultPaths.RepoRoot!, "ui", "fixtures", "disk-sample.json");
            var report = LoadFixture();
            var routes = new List<AppRoute> { AppRoute.Overview, AppRoute.Disk, AppRoute.Settings,
                AppRoute.BucketDetail("unattributed"), AppRoute.BucketDetail("excluded") };
            routes.AddRange(report.Projects.OrderByDescending(p => p.Cost)
                .Select((p, i) => AppRoute.Project(p.Id, i)));

            foreach (var route in routes)
            {
                var settings = AppSettings.InMemory();
                settings.Set(SettingsKeys.AppLanguage, "en");
                var services = new AppServices(settings, ["--snapshot", "--data", FixturePath,
                    "--disk-data", diskPath], TempDir(), new FakeBackgroundScheduler(),
                    new FakeLogWatcherFactory(), new FakePowerMonitor(), familyTokens: new InMemoryFamilyTokenStorage());
                services.LoadQuietly();
                services.Disk.RefreshBlocking();
                var panel = new PanelView(services, route);
                var window = TestWindows.Show(panel, Metrics.PanelWidth, Metrics.PanelHeight);
                window.UpdateLayout();
                Dispatcher.UIThread.RunJobs();
                var controls = ((Control)panel.CurrentPage!).GetVisualDescendants().OfType<Control>()
                    .Where(c => c.IsEffectivelyEnabled && c.IsEffectivelyVisible).ToArray();
                Assert.NotEmpty(controls);
                foreach (var control in controls)
                {
                    foreach (var ev in new[] { InputElement.PointerEnteredEvent, InputElement.PointerExitedEvent })
                    {
                        control.RaiseEvent(new PointerEventArgs(ev, control, null!, window, new Point(), 0,
                            new PointerPointProperties(), KeyModifiers.None));
                    }
                }
                window.Close();
                Dispatcher.UIThread.RunJobs();
            }
        });
    }
}
