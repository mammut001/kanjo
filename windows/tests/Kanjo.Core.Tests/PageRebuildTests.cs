using System.Globalization;
using System.Reflection;
using Avalonia.Controls;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 面板不该因为磁盘扫描、家庭上报或发布进度把整页拆掉重建。
/// 那些事件只改页脚或设置页自己的状态；整页重建会丢掉磁盘页的选中和设置页的滚动位置。
/// 用各页的 <c>ConstructionCount</c> 计数，而不是看界面长得像不像。
/// </summary>
public sealed class PageRebuildTests : KanjoTestCase
{
    /// <summary>
    /// <c>--snapshot</c> 让设置页不要去跑 CLI 预热档位表。面板本身不是截图模式，页面实例还在。
    /// </summary>
    private static AppServices NewServices(string? diskPath = null)
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        L10n.Store = settings;
        L10n.ResetCache();
        var args = new List<string> { "--snapshot", "--data", FixturePath };
        if (diskPath is not null)
        {
            args.Add("--disk-data");
            args.Add(diskPath);
        }
        return new AppServices(settings, args.ToArray(), TempDir(),
            new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor());
    }

    /// <summary>磁盘样本的时间改成现在，打开磁盘页时不会因为过期再扫一次。</summary>
    private static string FreshDiskFile()
    {
        var root = DefaultPaths.RepoRoot ?? throw new InvalidOperationException("repo root unavailable");
        var text = File.ReadAllText(Path.Combine(root, "ui", "fixtures", "disk-sample.json"));
        var stamped = DateTimeOffset.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
        text = text.Replace("\"generated_at\": \"2026-10-25T10:00:00Z\"",
            "\"generated_at\": \"" + stamped + "\"", StringComparison.Ordinal);
        var path = Path.Combine(TempDir(), "disk.json");
        File.WriteAllText(path, text);
        return path;
    }

    private static PanelView Show(AppServices services, AppRoute route)
    {
        var panel = new PanelView(services, route);
        TestWindows.Show(panel, Metrics.PanelWidth, Metrics.PanelHeight);
        Dispatcher.UIThread.RunJobs();
        return panel;
    }

    [Fact]
    public void TestFamilyAndPublishActivityDoesNotRebuildOverview()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.LoadQuietly();
            var panel = Show(services, AppRoute.Overview);
            var page = panel.CurrentPage;
            var count = OverviewPage.ConstructionCount;

            services.Family.Activity.Notify();
            services.Publish.Activity.Notify();
            Dispatcher.UIThread.RunJobs();

            Assert.Same(page, panel.CurrentPage);
            Assert.Equal(count, OverviewPage.ConstructionCount);
        });
    }

    [Fact]
    public void TestDiskRefreshDoesNotReplaceDiskPage()
    {
        OnUi(() =>
        {
            var services = NewServices(FreshDiskFile());
            services.Disk.RefreshBlocking();
            var panel = Show(services, AppRoute.Disk);
            var page = panel.CurrentPage as DiskPage;
            Assert.NotNull(page);
            var count = DiskPage.ConstructionCount;

            services.Disk.RefreshBlocking();
            Dispatcher.UIThread.RunJobs();

            Assert.Same(page, panel.CurrentPage);
            Assert.Equal(count, DiskPage.ConstructionCount);
        });
    }

    [Fact]
    public void TestFamilyActivityDoesNotReplaceSettingsPage()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var panel = Show(services, AppRoute.Settings);
            var page = panel.CurrentPage;
            Assert.IsType<SettingsPage>(page);
            var count = SettingsPage.ConstructionCount;

            services.Family.Activity.Notify();
            Dispatcher.UIThread.RunJobs();

            Assert.Same(page, panel.CurrentPage);
            Assert.Equal(count, SettingsPage.ConstructionCount);
        });
    }

    [Fact]
    public void TestClosedPanelDoesNotRebuild()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.LoadQuietly();
            var panel = Show(services, AppRoute.Overview);
            var window = TopLevel.GetTopLevel(panel) as Window;
            Assert.NotNull(window);

            window!.Content = null;
            window.Close();
            Dispatcher.UIThread.RunJobs();
            var count = OverviewPage.ConstructionCount;

            services.NotifyChanged();
            Dispatcher.UIThread.RunJobs();

            Assert.Equal(count, OverviewPage.ConstructionCount);
        });
    }

    [Fact]
    public void TestFooterRefreshNotifiesTwice()
    {
        OnUi(() =>
        {
            var services = NewServices(FreshDiskFile());
            services.LoadQuietly();
            var panel = Show(services, AppRoute.Overview);
            var button = panel.GetVisualDescendants().OfType<Clickable>()
                .First(c => ToolTip.GetTip(c) as string == "Refresh now");
            var click = (Action)typeof(Clickable)
                .GetField("_onClick", BindingFlags.Instance | BindingFlags.NonPublic)!
                .GetValue(button)!;

            var seen = 0;
            var last = DateTime.UtcNow;
            var gate = new object();
            services.Changed += () =>
            {
                lock (gate)
                {
                    seen++;
                    last = DateTime.UtcNow;
                }
            };

            var before = OverviewPage.ConstructionCount;
            click();

            var deadline = DateTime.UtcNow.AddSeconds(5);
            while (DateTime.UtcNow < deadline)
            {
                Dispatcher.UIThread.RunJobs();
                int n;
                DateTime stamp;
                lock (gate)
                {
                    n = seen;
                    stamp = last;
                }
                if (n >= 2 && !services.IsLoading && DateTime.UtcNow - stamp >= TimeSpan.FromMilliseconds(80))
                    break;
                Thread.Sleep(20);
            }
            Dispatcher.UIThread.RunJobs();

            int total;
            lock (gate) total = seen;
            // 一次刷新开始、结束各通知一次。按钮自己不再多通知一次。
            Assert.Equal(2, total);
            Assert.Equal(before + total, OverviewPage.ConstructionCount);
        });
    }
}
