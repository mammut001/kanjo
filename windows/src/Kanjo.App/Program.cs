using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using Kanjo.Core;

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
        L10n.Store ??= AppSettings.ForLaunch(args, AppSettings.ReadEnvironment());
        L10n.ResetCache();

        if (DefaultPaths.FlagValue("--snapshot", args) is { } snapshotPath)
        {
            var route = DefaultPaths.FlagValue("--route", args) ?? "overview";
            var scale = SnapshotRunner.ParseScale(DefaultPaths.FlagValue("--snapshot-scale", args));
            var appearance = SnapshotRunner.ParseAppearance(DefaultPaths.FlagValue("--snapshot-appearance", args));
            return SnapshotRunner.Run(snapshotPath, route, scale, appearance);
        }

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
    }
}

/// <summary>Fluent 主题 + 面板样式 + 托盘 / 窗口的启动编排。</summary>
public sealed class KanjoApplication : Application
{
    private TrayController? _tray;

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
        var services = AppServices.Create(args);
        L10n.Store = services.Settings;
        L10n.ResetCache();
        Palette.IsDark = ActualThemeVariant == Avalonia.Styling.ThemeVariant.Dark;

        // 数据加载放到首帧之后：先出面板（loading 态），不阻塞窗口出现。
        desktop.Startup += async (_, _) =>
        {
            await Task.Run(services.LoadQuietly);
            services.NotifyChanged();
        };

        if (args.Contains("--window"))
        {
            desktop.MainWindow = new PanelWindow(services, taskbar: true)
            {
                Title = "Kanjo",
                WindowStartupLocation = WindowStartupLocation.CenterScreen,
            };
            desktop.MainWindow.Show();
        }
        else
        {
            // 纯托盘应用：不占任务栏按钮，关掉主窗口也不会退出。
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            _tray = new TrayController(services);
        }

        base.OnFrameworkInitializationCompleted();
    }
}
