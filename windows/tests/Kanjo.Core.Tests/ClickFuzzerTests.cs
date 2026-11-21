using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Avalonia.VisualTree;
using System.Text.Json.Nodes;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

public sealed class ClickFuzzerTests : KanjoTestCase
{
    [Fact]
    public void SessionAttributionCardOpensAndEscapeClosesIt()
    {
        OnUi(() =>
        {
            var services = new AppServices(AppSettings.InMemory(), ["--snapshot", "--data", FixturePath],
                TempDir(), new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor(),
                familyTokens: new InMemoryFamilyTokenStorage());
            var list = new SessionList(services, [], 0.8, "USD");
            TestWindows.Show(list, 360, 620);
            var attribution = list.GetVisualDescendants().OfType<Clickable>()
                .First(c => ToolTip.GetTip(c) as string == L10n.Tr("session.attribution_button_help"));
            attribution.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Enter });
            Assert.Equal(3, list.Children.Count);
            attribution.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Escape });
            Assert.Equal(2, list.Children.Count);
        });
    }

    [Fact]
    public void ClickableSupportsKeyboardActivation()
    {
        OnUi(() =>
        {
            var count = 0;
            var target = new Clickable(new TextBlock { Text = "action" }, () => count++);
            TestWindows.Show(target, 300, 100);
            Assert.True(target.Focusable);
            Assert.True(target.Focus());
            foreach (var key in new[] { Key.Enter, Key.Space })
                target.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = key });
            Assert.Equal(2, count);
            target.IsEnabled = false;
            target.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Enter });
            Assert.Equal(2, count);
        });
    }

    [Fact]
    public void FixturePageControlsAcceptIndependentInteractions()
    {
        OnUi(() =>
        {
            ProjectActions.LaunchOverride = (_, _) => { };
            try
            {
                var report = LoadFixture();
                var routes = new List<AppRoute> { AppRoute.Overview, AppRoute.Disk, AppRoute.Settings,
                    AppRoute.BucketDetail("unattributed"), AppRoute.BucketDetail("excluded") };
                routes.AddRange(report.Projects.OrderByDescending(p => p.Cost)
                    .Select((p, i) => AppRoute.Project(p.Id, i)));
                var scenarios = routes.Select(route => (Route: route, Path: FixturePath)).ToList();
                foreach (var projectCount in new[] { 0, 1 })
                {
                    var json = JsonNode.Parse(File.ReadAllText(FixturePath))!;
                    var projects = json["projects"]!.AsArray();
                    while (projects.Count > projectCount) projects.RemoveAt(projects.Count - 1);
                    var path = Path.Combine(TempDir(), "report.json");
                    File.WriteAllText(path, json.ToJsonString());
                    scenarios.Add((AppRoute.Overview, path));
                }
                foreach (var (route, path) in scenarios)
                {
                    // Rebuild for each interaction: handlers may navigate or reconstruct their page.
                    var count = Controls(route, path).Count;
                    for (var i = 0; i < count; i++)
                    {
                        var controls = Controls(route, path);
                        var target = controls[i];
                        switch (target)
                        {
                            case Clickable clickable:
                                clickable.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Enter });
                                break;
                            case ToggleSwitch toggle:
                                toggle.IsChecked = !toggle.IsChecked;
                                break;
                            case ComboBox combo when combo.ItemCount > 1:
                                combo.SelectedIndex = (combo.SelectedIndex + 1) % combo.ItemCount;
                                Assert.InRange(combo.SelectedIndex, 0, combo.ItemCount - 1);
                                break;
                            case Button button:
                                button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                                break;
                        }
                        Dispatcher.UIThread.RunJobs();
                        TestWindows.CloseAll();
                    }
                }
            }
            finally { ProjectActions.LaunchOverride = null; }
        });
    }

    private static List<Control> Controls(AppRoute route, string reportPath)
    {
        TestWindows.CloseAll();
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        var disk = Path.Combine(DefaultPaths.RepoRoot!, "ui", "fixtures", "disk-sample.json");
        var services = new AppServices(settings, ["--snapshot", "--data", reportPath, "--disk-data", disk],
            TempDir(), new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor(),
            familyTokens: new InMemoryFamilyTokenStorage());
        services.Config.Runner = () => throw new InvalidOperationException("No CLI in UI tests");
        services.UseReportRunner(new FakeReportRunner());
        services.LoadQuietly();
        services.Disk.RefreshBlocking();
        var panel = new PanelView(services, route);
        var window = TestWindows.Show(panel, Metrics.PanelWidth, Metrics.PanelHeight);
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        return ((Control)panel.CurrentPage!).GetVisualDescendants().OfType<Control>()
            .Where(c => c.IsEffectivelyEnabled && c.IsEffectivelyVisible &&
                c is Button or ToggleSwitch or ComboBox or Clickable)
            .ToList();
    }
}
