using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using Kanjo.Core;
using Velopack;

namespace Kanjo.App;

public static class Program
{
    /// <summary>
    /// 启动模式：
    /// - `--snapshot &lt;out.png&gt; [...]`：离屏渲染成 PNG 后退出 0（macOS 上也能跑，用于开发对图）。
    /// - `--window`：普通窗口（开发调试用）。
    /// - 默认：托盘应用（Windows 上是通知区域图标 + 弹出面板）。
    /// </summary>
    [STAThread]
    public static int Main(string[] args)
    {
        // Velopack 必须第一个跑：安装后首次启动 / 更新后的钩子、启动时应用已下载的更新都靠它。
        // 开发运行（Debug）和截图 / 预览模式不允许它接管进程（见 UpdatePolicy）。
        var velopack = VelopackApp.Build()
            .SetAutoApplyOnStartup(UpdatePolicy.ShouldAutoApplyOnStartup(args, DefaultPaths.IsDebugBuild));
        if (OperatingSystem.IsWindows())
        {
            // 卸载钩子：清掉可能存在的开机自启项（App 默认不写它，见 WindowsStartup；这里只是兜底）。
            // 用户数据 %APPDATA%\Kanjo 和 %LOCALAPPDATA%\kanjo 一律保留，和 Mac 的 zap 规则一致。
            velopack = velopack.OnBeforeUninstallFastCallback(_ => WindowsStartup.RemoveRunEntry());
        }
        velopack.Run();

        L10n.Store ??= AppSettings.ForLaunch(args, AppSettings.ReadEnvironment());
        L10n.ResetCache();

        // 诊断：`--print-source[=<file>]` 打印解析出来的 python / CLI 目录 / 数据源后退出 0。
        // 读的是真实设置（和托盘运行时同一份），但只读不写；冒烟测试用它对安装版做断言。
        if (args.Contains("--print-source") ||
            args.Any(a => a.StartsWith("--print-source=", StringComparison.Ordinal)))
        {
            return SourceDiagnostics.Print(Console.Out, args);
        }

        if (DefaultPaths.FlagValue("--snapshot", args) is { } snapshotPath)
        {
            var route = DefaultPaths.FlagValue("--route", args) ?? "overview";
            var scale = SnapshotRunner.ParseScale(DefaultPaths.FlagValue("--snapshot-scale", args));
            var appearance = SnapshotRunner.ParseAppearance(DefaultPaths.FlagValue("--snapshot-appearance", args));
            return SnapshotRunner.Run(snapshotPath, route, scale, appearance);
        }

        // 单实例：托盘应用第二次启动时把「激活面板」发给已运行的实例，然后自己退出。
        // --window（开发预览）不限制，方便同时开窗口和托盘。
        SingleInstanceCoordinator? single = null;
        if (!args.Contains("--window"))
        {
            single = new SingleInstanceCoordinator();
            if (!single.IsPrimary)
            {
                single.RequestActivation();
                single.Dispose();
                return 0;
            }
        }

        // 主实例：协调器交给 KanjoApplication，收到「激活」时把面板弹出来。
        KanjoApplication.SingleInstance = single;

        try
        {
            return AppBuilder.Configure<KanjoApplication>()
                .UsePlatformDetect()
                .WithInterFont()
                .LogToTrace()
                .StartWithClassicDesktopLifetime(args);
        }
        catch (Exception e)
        {
            // 无显示器 / 沙箱环境（远程 CI、没有窗口服务器的会话）里原生后端起不来。
            // 截图模式不需要窗口，用 --snapshot；这里给出可读的提示而不是一串堆栈。
            Console.Error.WriteLine($"Kanjo could not start the desktop backend: {e.Message}");
            Console.Error.WriteLine("If this machine has no display, use --snapshot <out.png> instead.");
            return 1;
        }
        finally
        {
            single?.Dispose();
        }
    }
}

/// <summary>Fluent 主题 + 面板样式 + 托盘 / 窗口的启动编排。</summary>
public sealed class KanjoApplication : Application
{
    /// <summary>主实例的单实例协调器（<see cref="Program.Main"/> 创建，收到「激活」时弹出面板）。</summary>
    public static SingleInstanceCoordinator? SingleInstance { get; set; }

    private TrayController? _tray;
    private AppServices? _services;
    private UpdateService? _updates;

    public override void Initialize()
    {
        Styles.Add(new FluentTheme());
        RequestedThemeVariant = Avalonia.Styling.ThemeVariant.Default;

        Styles.Add(new Style(x => x.OfType<TextBlock>())
        {
            Setters =
            {
                new Setter(TextBlock.FontFamilyProperty, Type.Font),
                new Setter(TextBlock.ForegroundProperty, Palette.Foreground),
            },
        });
        Styles.Add(new Style(x => x.OfType<Window>())
        {
            Setters = { new Setter(Avalonia.Controls.Window.BackgroundProperty, Palette.PanelBackground) },
        });
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
        {
            base.OnFrameworkInitializationCompleted();
            return;
        }

        var args = desktop.Args ?? Environment.GetCommandLineArgs();
        _services = AppServices.Create(args);
        var services = _services;
        L10n.Store = services.Settings;
        L10n.ResetCache();
        Palette.IsDark = ActualThemeVariant == Avalonia.Styling.ThemeVariant.Dark;
        desktop.Exit += (_, _) => DisposeServices();

        if (args.Contains("--window"))
        {
            // 开发预览：可以带 --route 直接打开某一页（和 Mac 的 --window --route 一致）。
            // 后台行为（监听 / 定时器）在预览模式下也运行（Mac 的 ReportStore 是单例）。
            desktop.Startup += async (_, _) =>
            {
                await Task.Run(services.StartBackground);
                services.NotifyChanged();
            };
            var rawRoute = DefaultPaths.FlagValue("--route", args);
            var route = DevRoutes.Resolve(rawRoute, services.Report) ?? AppRoute.Overview;
            desktop.MainWindow = new PanelWindow(services, taskbar: true, route: route)
            {
                Title = "Kanjo",
                WindowStartupLocation = WindowStartupLocation.CenterScreen,
            };
            desktop.MainWindow.Show();
            ShortDate.ReferenceNow = null;
        }
        else
        {
            // 纯托盘应用：不占任务栏按钮，关掉主窗口也不会退出。
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;

            // 自动更新（只在 Velopack 装出来的正式版里跑；见 UpdatePolicy）。
            // Mac 版没有更新界面，所以这里也不提示：后台下载，下次启动装上，
            // 托盘菜单只在「已经下载好、可以立刻重启装上」时多一项。
            _updates = UpdateService.Create(args);
            _tray = new TrayController(services, _updates);

            // 第二次启动的实例请求激活：把已运行实例的面板弹出来。
            if (SingleInstance is { IsPrimary: true } coordinator)
            {
                coordinator.ActivateRequested += () => _tray?.ActivateFromSecondLaunch();
                coordinator.FlushPending();
            }

            // 后台行为：先出托盘图标，再跑第一次刷新 / 兜底定时器 / 日志监听（不阻塞首帧）。
            desktop.Startup += async (_, _) =>
            {
                _updates?.Start();
                await Task.Run(services.StartBackground);
                services.NotifyChanged();
            };
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void DisposeServices()
    {
        _services?.Background.Dispose();
        _services?.DiskPrefetch.Dispose();
        _updates?.Dispose();
        SingleInstance?.Dispose();
        _tray?.Dispose();
    }
}
