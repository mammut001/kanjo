using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 外观 / 全局资源在测试之间不能互相污染，也不能往已经拆掉的 Application 上写。
///
/// 真机上对应的场景：面板开着的时候用户在设置页切主题。Application 的资源变化会被
/// 广播给每个 TopLevel，TopLevel 递归遍历整棵逻辑树；只要遍历期间有控件换子节点，
/// 就会崩在 AvaloniaList.get_Item 上。这几条用例把那条路径钉住。
/// </summary>
public sealed class AppearanceIsolationTests : KanjoTestCase
{
    private static AppServices NewServices()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        L10n.Store = settings;
        L10n.ResetCache();
        var services = new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir());
        services.LoadQuietly();
        return services;
    }

    /// <summary>
    /// 反复切换外观、同时有窗口活着：不能抛（真机上就是「面板开着切主题」）。
    /// </summary>
    [Fact]
    public void TestSwitchingAppearanceWithLiveWindowsDoesNotThrow()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
            var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
            window.UpdateLayout();
            Dispatcher.UIThread.RunJobs();

            for (var i = 0; i < 6; i++)
            {
                Appearance.Force(i % 2 == 0 ? AppearanceChoice.Light : AppearanceChoice.Dark);
                Dispatcher.UIThread.RunJobs();
                window.UpdateLayout();
                Dispatcher.UIThread.RunJobs();
            }

            // 收尾恢复，别把深 / 浅色留给后面的用例。
            Appearance.Force(AppearanceChoice.Dark);
            Dispatcher.UIThread.RunJobs();
            Assert.True(Palette.IsDark);
        });
    }

    /// <summary>
    /// 写全局资源必须是一次性的（一次通知），不是每个 key 一次。
    ///
    /// 以前是 6 个 set_Item，等于向所有 TopLevel 广播 6 次「资源变了」，每次都遍历整棵逻辑树 ——
    /// CI 上偶发的 ArgumentOutOfRangeException 就是某一次遍历中途树被改了。
    /// </summary>
    [Fact]
    public void TestPaletteResourcesAreWrittenInOneBatch()
    {
        OnUi(() =>
        {
            var app = Application.Current!;
            var notifications = 0;
            void Count(object? sender, EventArgs e) => notifications++;
            app.ResourcesChanged += Count;
            try
            {
                // 先把资源刷成反的那一套，确保下面这次一定真的写。
                Appearance.Force(AppearanceChoice.Light);
                Dispatcher.UIThread.RunJobs();
                Assert.False(Palette.IsDark);

                notifications = 0;
                Appearance.Force(AppearanceChoice.Dark);
                Dispatcher.UIThread.RunJobs();

                Assert.True(Palette.IsDark);
                Assert.Equal(1, notifications);
            }
            finally
            {
                app.ResourcesChanged -= Count;
                Appearance.Force(AppearanceChoice.Dark);
                Dispatcher.UIThread.RunJobs();
            }
        });
    }

    /// <summary>
    /// 同一外观重复设置不重写资源：不该每次都广播「资源变了」。
    /// （启动时 Apply + 设置页那一下、以及每个用例里的复位，都会走这条。）
    /// </summary>
    [Fact]
    public void TestReapplyingSameAppearanceDoesNotRewriteResources()
    {
        OnUi(() =>
        {
            var app = Application.Current!;
            Appearance.Force(AppearanceChoice.Dark);
            Dispatcher.UIThread.RunJobs();

            var notifications = 0;
            void Count(object? sender, EventArgs e) => notifications++;
            app.ResourcesChanged += Count;
            try
            {
                for (var i = 0; i < 4; i++)
                {
                    Appearance.Force(AppearanceChoice.Dark);
                    Dispatcher.UIThread.RunJobs();
                }
                Assert.Equal(0, notifications);
            }
            finally
            {
                app.ResourcesChanged -= Count;
            }
        });
    }

    /// <summary>
    /// 从非 UI 线程设置外观（后台线程里读设置后兜底调用）必须切到 UI 线程再动手，
    /// 而且不能对着上一轮留下的、已经拆掉的 Application 动手。
    /// </summary>
    [Fact]
    public void TestAppearanceFromBackgroundThreadIsMarshalledToUiThread()
    {
        var appOnUiThread = 0;
        OnUi(() =>
        {
            appOnUiThread = Application.Current!.GetHashCode();

            // 从调度线程以外发起（这就是「测试线程上 ConfigureHeadless」的形状）。
            var done = new ManualResetEventSlim();
            _ = Task.Run(() =>
            {
                try
                {
                    Appearance.Force(AppearanceChoice.Light);
                }
                finally
                {
                    done.Set();
                }
            });
            done.Wait(TimeSpan.FromSeconds(10));

            // 等被 Post 过来的那次真正执行。
            Dispatcher.UIThread.RunJobs();
            Assert.False(Palette.IsDark, "the background call must actually take effect");
            Assert.Equal(appOnUiThread, Application.Current!.GetHashCode());
        });
    }
}
