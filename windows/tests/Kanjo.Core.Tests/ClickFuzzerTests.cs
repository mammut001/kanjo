using Avalonia;
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

    [Fact]
    public void RangePillsRebuildOverviewAndProjectForAllReports()
    {
        OnUi(() =>
        {
            foreach (var count in new[] { -1, 0, 1 })
            {
                var json = JsonNode.Parse(File.ReadAllText(FixturePath))!;
                if (count >= 0)
                {
                    var projects = json["projects"]!.AsArray();
                    while (projects.Count > count) projects.RemoveAt(projects.Count - 1);
                    if (count == 0)
                    {
                        json["totals"] = JsonNode.Parse("""{"cost":0,"tokens":{"input":0,"output":0,"cache_read":0,"cache_write":0,"thinking":0,"total":0},"sessions":0}""");
                        json["buckets"] = JsonNode.Parse("""{"unattributed":{"cost":0,"tokens":{},"sessions":0},"excluded":{"cost":0,"tokens":{},"sessions":0},"parse_failed":{"sessions":0,"files":[]}}""");
                    }
                }
                var path = Path.Combine(TempDir(), "report.json");
                File.WriteAllText(path, json.ToJsonString());
                var services = MakeServices(path);
                var routes = new List<AppRoute> { AppRoute.Overview };
                if (services.Report!.Projects.Count > 0)
                    routes.Add(AppRoute.Project(services.Report.Projects[0].Id, 0));
                foreach (var route in routes)
                {
                    var panel = new PanelView(services, route);
                    var window = TestWindows.Show(panel, Metrics.PanelWidth, Metrics.PanelHeight);
                    for (var i = 0; i < TimeRanges.All.Count; i++)
                    {
                        window.UpdateLayout();
                        var picker = ((Control)panel.CurrentPage!).GetVisualDescendants().OfType<RangePicker>().Single();
                        var chips = ((StackPanel)((ScrollViewer)picker.GetVisualDescendants().OfType<ScrollViewer>().First()).Content!).Children.OfType<Border>().ToArray();
                        Assert.Equal(7, chips.Length);
                        Release(chips[i], window);
                        Dispatcher.UIThread.RunJobs();
                        Assert.NotEmpty(((Control)panel.CurrentPage!).GetVisualDescendants().OfType<TextBlock>());
                    }
                    window.Close();
                }
            }
        });
    }

    [Fact]
    public void SettingsComboItemsSurviveRebuilds()
    {
        OnUi(() =>
        {
            var services = MakeServices(FixturePath);
            var panel = new PanelView(services, AppRoute.Settings);
            var window = TestWindows.Show(panel, Metrics.PanelWidth, Metrics.PanelHeight);
            window.UpdateLayout();
            var counts = ((Control)panel.CurrentPage!).GetVisualDescendants().OfType<ComboBox>().Select(c => c.ItemCount).ToArray();
            Assert.NotEmpty(counts);
            for (var i = 0; i < counts.Length; i++)
                for (var item = 0; item < counts[i]; item++)
                {
                    var combos = ((Control)panel.CurrentPage!).GetVisualDescendants().OfType<ComboBox>().ToArray();
                    Assert.True(i < combos.Length);
                    combos[i].SelectedIndex = item;
                    Dispatcher.UIThread.RunJobs();
                    window.UpdateLayout();
                    Assert.NotEmpty(((Control)panel.CurrentPage!).GetVisualDescendants().OfType<TextBlock>());
                }
        });
    }

    [Fact]
    public void UpdateStatesAcceptAvailableButtons()
    {
        OnUi(() =>
        {
            foreach (var state in new[] { UpdateState.NotInstalled, UpdateState.Checking, UpdateState.Downloading, UpdateState.Ready, UpdateState.Failed })
            {
                var services = MakeServices(FixturePath);
                using var updates = UpdateService.ForSnapshot(new UpdateStatus(state, "0.5.3") { CurrentVersion = "0.5.2", ProgressPercent = 42 });
                services.UseUpdates(updates);
                var page = new SettingsPage(services, null, null, snapshot: true, onBack: () => { });
                var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
                window.UpdateLayout();
                var label = UpdateStatusText.Button(updates.Status);
                var button = page.GetVisualDescendants().OfType<Button>().FirstOrDefault(b => b.Content as string == label);
                Assert.Equal(UpdateStatusText.ButtonEnabled(updates.Status), button is { IsEnabled: true });
                button?.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                Dispatcher.UIThread.RunJobs();
                Assert.NotEmpty(page.GetVisualDescendants().OfType<TextBlock>());
                if (state is UpdateState.Downloading or UpdateState.Ready)
                {
                    var restarted = 0;
                    var dismissed = 0;
                    var banner = UpdateBannerView.Make(updates, () => restarted++, () => dismissed++);
                    window.Content = banner;
                    window.UpdateLayout();
                    foreach (var action in banner.GetVisualDescendants().OfType<Button>().ToArray())
                        action.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    var close = banner.GetVisualDescendants().OfType<Clickable>().Single();
                    close.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyDownEvent, Key = Key.Enter });
                    Assert.Equal(1, dismissed);
                    Assert.Equal(state == UpdateState.Ready ? 1 : 0, restarted);
                }
                window.Close();
            }
        });
    }

    private sealed class PartialDiskSource(DiskReport report) : IDiskSource
    {
        public int Calls;
        public DiskReport Load() => report;
        public CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed, IReadOnlyList<string>? onlyPaths = null)
        {
            Calls++;
            var path = report.AllEntries.First(e => e.Id == ids[0]).Path;
            return new CleanResult([path], 123, [new CleanSkip("skipped", "locked")]);
        }
    }

    [Fact]
    public void DiskPartialCleanupRebuildsOnUiThread()
    {
        OnUi(() =>
        {
            var source = new PartialDiskSource(LoadDiskFixture());
            var services = MakeServices(FixturePath, source);
            services.Disk.RefreshBlocking();
            var page = new DiskPage(services, true, true, () => { }, () => { });
            var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
            window.UpdateLayout();
            var segmented = page.GetVisualDescendants().OfType<SegmentedControl>().Single();
            var ageCount = ((Grid)segmented.Child!).Children.Count;
            for (var i = 0; i < ageCount; i++)
            {
                segmented = page.GetVisualDescendants().OfType<SegmentedControl>().Single();
                Release((Control)((Grid)segmented.Child!).Children[i], window);
                window.UpdateLayout();
                Dispatcher.UIThread.RunJobs();
            }
            var check = page.GetVisualDescendants().OfType<CheckBox>().First();
            check.IsChecked = true;
            Assert.Single(page.Selected);
            window.UpdateLayout();
            var clean = page.GetVisualDescendants().OfType<Button>().Single(b => ToolTip.GetTip(b) as string == L10n.Tr("disk.clean_help"));
            clean.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            WaitForUi(() => page.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == WindowsL10n.Tr("disk.card.confirm_title")));
            Assert.All(page.GetVisualDescendants().OfType<CheckBox>(), c => Assert.False(c.IsEnabled));
            Assert.IsNotType<Button>(page.GetVisualDescendants().OfType<Control>().Single(c => ToolTip.GetTip(c) as string == L10n.Tr("disk.clean_help")));
            var move = page.GetVisualDescendants().OfType<Button>().Single(b => b.Content as string == WindowsL10n.Tr("disk.card.move_button"));
            Assert.True(move.IsEnabled);
            move.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            WaitForUi(() => page.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == WindowsL10n.Tr("disk.card.moved_title")));
            Assert.Equal(2, source.Calls);
            var done = page.GetVisualDescendants().OfType<Button>().Single(b => b.Content as string == L10n.Tr("common.done"));
            done.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.DoesNotContain(page.GetVisualDescendants().OfType<TextBlock>(), t => t.Text == WindowsL10n.Tr("disk.card.moved_title"));
        });
    }

    private static void WaitForUi(Func<bool> condition)
    {
        var timeout = System.Diagnostics.Stopwatch.StartNew();
        while (!condition() && timeout.Elapsed < TimeSpan.FromSeconds(5))
        {
            Dispatcher.UIThread.RunJobs();
            foreach (var window in Avalonia.Application.Current!.ApplicationLifetime is Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop ? desktop.Windows : []) window.UpdateLayout();
            Thread.Yield();
        }
        Assert.True(condition(), "UI state did not arrive");
    }

    private static AppServices MakeServices(string path, IDiskSource? diskSource = null)
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        var services = new AppServices(settings, ["--snapshot", "--data", path], TempDir(),
            new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor(),
            familyTokens: new InMemoryFamilyTokenStorage(), diskSource: diskSource);
        services.Config.Runner = () => throw new InvalidOperationException("No CLI in UI tests");
        services.UseReportRunner(new FakeReportRunner());
        services.LoadQuietly();
        return services;
    }

    private static void Release(Control control, Window window) => control.RaiseEvent(
        new PointerReleasedEventArgs(control, null!, window, new Point(), 0,
            new PointerPointProperties(), KeyModifiers.None, MouseButton.Left));

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
