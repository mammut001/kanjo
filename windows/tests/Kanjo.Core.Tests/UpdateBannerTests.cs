using Avalonia.Controls;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 面板顶部更新横幅 / 设置页 Updates 卡片的规则与渲染：
/// 什么时候出现、文案是什么、点 ✕ 之后本次运行不再出现、非安装版的禁用态。
/// </summary>
public sealed class UpdateBannerTests : KanjoTestCase
{
    private static UpdateStatus Ready(string version = "0.5.3") =>
        new(UpdateState.Ready, version) { CurrentVersion = "0.5.2" };

    private static UpdateStatus Downloading(int progress = 42, string version = "0.5.3") =>
        new(UpdateState.Downloading, version, progress) { CurrentVersion = "0.5.2" };

    // MARK: - 显示规则

    [Fact]
    public void TestBannerShowsOnlyForReadyAndDownloading()
    {
        Assert.True(UpdateBanner.ShouldShow(Ready(), null));
        Assert.True(UpdateBanner.ShouldShow(Downloading(), null));

        // 已是最新 / 还没检查 / 失败 / 非安装版：一律不打扰。
        Assert.False(UpdateBanner.ShouldShow(new UpdateStatus(UpdateState.UpToDate), null));
        Assert.False(UpdateBanner.ShouldShow(new UpdateStatus(UpdateState.Idle), null));
        Assert.False(UpdateBanner.ShouldShow(new UpdateStatus(UpdateState.Checking), null));
        Assert.False(UpdateBanner.ShouldShow(new UpdateStatus(UpdateState.Failed, Error: "offline"), null));
        Assert.False(UpdateBanner.ShouldShow(UpdateStatus.NotInstalled("0.5.2"), null));
        Assert.False(UpdateBanner.ShouldShow(null, null));
    }

    /// <summary>✕ 关掉后同一次运行不再出现；换了新版本号 / 下次启动（dismissed 清空）会回来。</summary>
    [Fact]
    public void TestDismissedBannerIsHiddenUntilNextLaunch()
    {
        Assert.True(UpdateBanner.ShouldShow(Ready("0.5.3"), null));
        Assert.False(UpdateBanner.ShouldShow(Ready("0.5.3"), "0.5.3"));
        // 又发布了更新的版本：新版本的横幅照常出现。
        Assert.True(UpdateBanner.ShouldShow(Ready("0.5.4"), "0.5.3"));
    }

    [Fact]
    public void TestBannerText()
    {
        Assert.Equal("Kanjo 0.5.3 is ready", UpdateBanner.Title(Ready(), "en"));
        Assert.Equal("Kanjo 0.5.3 已就绪", UpdateBanner.Title(Ready(), "zh-Hans"));
        Assert.Equal("Kanjo 0.5.3 est prêt", UpdateBanner.Title(Ready(), "fr"));
        // 下载中没有标题（只有一句进度）。
        Assert.Null(UpdateBanner.Title(Downloading(), "en"));

        Assert.Equal("Downloading Kanjo 0.5.3… 42%", UpdateBanner.Message(Downloading(), "en"));
        Assert.Equal("正在下载 Kanjo 0.5.3… 42%", UpdateBanner.Message(Downloading(), "zh-Hans"));
        // 已下载时正文为空（按钮自己说明）。
        Assert.Null(UpdateBanner.Message(Ready(), "en"));

        Assert.True(UpdateBanner.ShowsProgress(Downloading()));
        Assert.False(UpdateBanner.ShowsProgress(Ready()));
    }

    /// <summary>设置页按钮的四种状态：检查 / 已是最新 / 下载中 / 已下载。</summary>
    [Fact]
    public void TestSettingsButtonStates()
    {
        var idle = new UpdateStatus(UpdateState.Idle);
        Assert.Equal("Check for updates", UpdateStatusText.Button(idle, "en"));
        Assert.True(UpdateStatusText.ButtonEnabled(idle));
        Assert.False(UpdateStatusText.ButtonIsPrimary(idle));

        var checking = new UpdateStatus(UpdateState.Checking);
        Assert.Equal("Checking for updates…", UpdateStatusText.Button(checking, "en"));
        Assert.False(UpdateStatusText.ButtonEnabled(checking));

        var upToDate = new UpdateStatus(UpdateState.UpToDate);
        Assert.Equal("You're up to date", UpdateStatusText.Description(upToDate, "en"));
        Assert.True(UpdateStatusText.ButtonEnabled(upToDate));

        Assert.Equal("Downloading…", UpdateStatusText.Button(Downloading(), "en"));
        Assert.False(UpdateStatusText.ButtonEnabled(Downloading()));

        // 已下载：按钮变成强调色的「Restart to update」。
        Assert.Equal("Restart to update", UpdateStatusText.Button(Ready(), "en"));
        Assert.True(UpdateStatusText.ButtonEnabled(Ready()));
        Assert.True(UpdateStatusText.ButtonIsPrimary(Ready()));

        var failed = new UpdateStatus(UpdateState.Failed, Error: "No such host is known.");
        Assert.Equal("Couldn't check for updates", UpdateStatusText.Description(failed, "en"));
        Assert.Equal("No such host is known.", UpdateStatusText.Detail(failed, "en"));
        Assert.True(UpdateStatusText.ButtonEnabled(failed));
    }

    [Fact]
    public void TestEveryUpdateStringIsLocalized()
    {
        string[] keys =
        [
            "update.section", "update.version_label", "update.check", "update.checking",
            "update.downloading_button", "update.up_to_date", "update.downloading", "update.ready",
            "update.ready_hint", "update.failed", "update.idle", "update.last_checked",
            "update.never_checked", "update.not_installed", "update.dismiss", "update.restart_to_install",
        ];
        foreach (var key in keys)
        {
            Assert.True(WindowsL10n.HasOverride(key), $"{key} should have a Windows translation");
            foreach (var lang in new[] { "en", "zh-Hans", "fr" })
            {
                var text = WindowsL10n.TrL(lang, key);
                Assert.False(string.IsNullOrWhiteSpace(text) || text == key, $"{key} missing for {lang}");
            }
        }
    }

    /// <summary>进度格式里的 `%%` 必须真的变成一个百分号（L10n 的 printf 解析）。</summary>
    [Fact]
    public void TestPercentInDownloadingTextFormats()
    {
        Assert.Equal("Downloading Kanjo 0.5.3… 7%", WindowsL10n.TrL("en", "update.downloading", "0.5.3", 7));
        Assert.Equal("100% done", L10n.ToNetFormat("100% done"));
        Assert.Equal("Downloading {0}… {1}%", L10n.ToNetFormat("Downloading %@… %d%%"));
    }

    [Fact]
    public void TestNextPatchVersion()
    {
        Assert.Equal("0.5.3", UpdateStatusText.NextPatch("0.5.2"));
        Assert.Equal("0.99.100", UpdateStatusText.NextPatch("0.99.99"));
        // 读不懂的版本号原样返回（不抛异常）。
        Assert.Equal("weird", UpdateStatusText.NextPatch("weird"));
    }

    // MARK: - 设置页 / 面板渲染

    /// <summary>
    /// 隔离的服务：内存里的设置（语言固定英文）+ 仓库里的 sample.json。
    /// 不碰真实的 preview 设置文件 —— 那份文件的语言 / 外观取决于上次是谁跑的，断言会随机失败。
    /// </summary>
    private static AppServices NewServices()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        L10n.Store = settings;
        L10n.ResetCache();
        return new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir());
    }

    /// <summary>
    /// 设置页是 ScrollPage（ScrollViewer 模板）：内容只有在窗口里、套上模板之后才建出来，
    /// 所以要挂一个不显示的 Window 并把排队的布局任务跑完再查可视树
    /// （和 SettingsScrollTests 一样的做法；headless 下模板首次加载是异步排队的）。
    /// </summary>
    private static Window Show(Control page)
    {
        var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
        for (var i = 0; i < 3; i++)
        {
            window.UpdateLayout();
            page.UpdateLayout();
            Dispatcher.UIThread.RunJobs();
        }
        return window;
    }

    [Fact]
    public void TestSettingsShowsUpdateCardInEachState()
    {
        OnUi(() =>
        {
            foreach (var (status, expectedButton, expectedVersion) in new[]
                     {
                         (Ready(), "Restart to update", "0.5.3"),
                         (Downloading(), "Downloading…", "0.5.2"),
                         (new UpdateStatus(UpdateState.UpToDate) { CurrentVersion = "0.5.2" },
                             "Check for updates", "0.5.2"),
                         (UpdateStatus.NotInstalled("0.5.2"), "Check for updates", "0.5.2"),
                     })
            {
                var services = NewServices();
                services.UseUpdates(UpdateService.ForSnapshot(status));
                var page = new SettingsPage(services, null, null, snapshot: true, onBack: () => { });
                var window = Show(page);
                try
                {
                    var texts = page.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text).ToList();
                    Assert.Contains("Updates", texts);
                    Assert.Contains("Current version", texts);
                    Assert.Contains(expectedButton, texts);
                    // 版本号那一格：当前版本永远显示。
                    Assert.Contains("0.5.2", texts);
                    // 已下载时卡片里还有新版本号（0.5.3），下载中也有。
                    Assert.Contains(texts, t => t is not null && t.Contains(expectedVersion, StringComparison.Ordinal));
                }
                finally
                {
                    window.Close();
                }
            }
        });
    }

    [Fact]
    public void TestNotInstalledCardExplainsWhy()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.UseUpdates(UpdateService.ForSnapshot(UpdateStatus.NotInstalled("0.5.2")));
            var page = new SettingsPage(services, null, null, snapshot: true, onBack: () => { });
            var window = Show(page);
            try
            {
                var texts = page.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text).ToList();
                Assert.Contains("Updates are only available in the installed version", texts);
                // 这句只出现一次（说明行不重复）。
                Assert.Single(texts, t => t == "Updates are only available in the installed version");

                // 按钮是禁用外观（静态 Border + 禁用色文字），不是可点的 Button。
                Assert.DoesNotContain(page.GetVisualDescendants().OfType<Button>(),
                    b => (b.Content as string) == "Check for updates");
            }
            finally
            {
                window.Close();
            }
        });
    }

    [Fact]
    public void TestSettingsReadyButtonIsAccent()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.UseUpdates(UpdateService.ForSnapshot(Ready()));
            var page = new SettingsPage(services, null, null, snapshot: true, onBack: () => { });
            var window = Show(page);
            try
            {
                var button = page.GetVisualDescendants().OfType<Button>()
                    .First(b => (b.Content as string) == "Restart to update");
                var fill = Assert.IsAssignableFrom<Avalonia.Media.ISolidColorBrush>(button.Background);
                Assert.Equal(Palette.AccentFillColor, fill.Color);
            }
            finally
            {
                window.Close();
            }
        });
    }

    /// <summary>横幅在面板里，✕ 关掉后重建的面板不再有它（同一次运行）。</summary>
    [Fact]
    public void TestPanelBannerAppearsAndDismisses()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var updates = UpdateService.ForSnapshot(Ready());
            services.UseUpdates(updates);

            var panel = new PanelView(services, AppRoute.Overview, snapshotMode: true);
            Assert.Contains("Kanjo 0.5.3 is ready", Texts(panel));

            updates.DismissBanner();
            panel.Rebuild();
            Assert.DoesNotContain("Kanjo 0.5.3 is ready", Texts(panel));
            Assert.Equal("0.5.3", updates.DismissedVersion);
        });
    }

    [Fact]
    public void TestPanelHasNoBannerWhenUpToDate()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.UseUpdates(UpdateService.ForSnapshot(
                new UpdateStatus(UpdateState.UpToDate) { CurrentVersion = "0.5.2" }));
            var panel = new PanelView(services, AppRoute.Overview, snapshotMode: true);

            Assert.DoesNotContain(Texts(panel), t => t is not null && t.Contains("is ready", StringComparison.Ordinal));
            Assert.DoesNotContain(Texts(panel), t => t is not null && t.Contains("Downloading Kanjo", StringComparison.Ordinal));
        });
    }

    /// <summary>
    /// 更新状态变化只重建横幅，不重建整页（否则下载进度每跳一次，设置页的滚动位置就被清零）。
    /// </summary>
    [Fact]
    public void TestBannerAppearsWithoutRebuildingThePage()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.UseUpdates(UpdateService.ForSnapshot(
                new UpdateStatus(UpdateState.Idle) { CurrentVersion = "0.5.2" }));
            var panel = new PanelView(services, AppRoute.Overview, snapshotMode: true);
            Assert.DoesNotContain("Kanjo 0.5.3 is ready", Texts(panel));

            // 模拟下载完成：换成 Ready 的更新服务，只重建横幅。
            services.UseUpdates(UpdateService.ForSnapshot(Ready()));
            Assert.Contains("Kanjo 0.5.3 is ready", Texts(panel));
        });
    }

    /// <summary>下载中的横幅带进度文案（42%），而且出现在总览以外的页面（这里用设置页）。</summary>
    [Fact]
    public void TestBannerShowsOnSettingsPageWhileDownloading()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.UseUpdates(UpdateService.ForSnapshot(Downloading(42)));
            var panel = new PanelView(services, AppRoute.Settings, snapshotMode: true);

            Assert.Contains("Downloading Kanjo 0.5.3… 42%", Texts(panel));
        });
    }

    private static List<string?> Texts(Control root) =>
        root.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text).ToList();
}
