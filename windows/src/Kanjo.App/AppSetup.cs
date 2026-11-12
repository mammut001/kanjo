using Avalonia;
using Avalonia.Headless;
using Avalonia.Styling;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>截图（headless）用的启动引导：装样式、定外观、指向隔离设置。</summary>
public static class AppSetup
{
    public static void ConfigureHeadless(string? appearance)
    {
        if (Application.Current is null)
        {
            AppBuilder.Configure<HeadlessApplication>()
                .UseSkia()
                .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
                .SetupWithoutStarting();
        }
        // 截图模式一律不做动画（可复现）。
        Motion.Snapshot = true;
        ApplyAppearance(appearance);
        Palette.ApplyPlatformAccent();
        L10n.Store ??= AppSettings.InMemory();
        L10n.ResetCache();
    }

    public static void ApplyAppearance(string? appearance)
    {
        if (Application.Current is not { } app) return;
        // Avalonia 的 Application 属性带线程校验：如果当前不在 UI 线程（例如某个测试
        // 先建了 headless 会话，后续测试在测试线程上跑），直接改会抛
        // "Call from invalid thread"。这种情况下只更新 Palette（纯静态），
        // 主题变体由已经建立会话的那个线程负责。
        void Apply()
        {
            if (appearance is "dark")
            {
                app.RequestedThemeVariant = ThemeVariant.Dark;
                Palette.IsDark = true;
            }
            else if (appearance is "light")
            {
                app.RequestedThemeVariant = ThemeVariant.Light;
                Palette.IsDark = false;
            }
            else
            {
                Palette.IsDark = app.ActualThemeVariant == ThemeVariant.Dark;
            }
            // 禁用态资源是「按当时的色板取值的画笔」：外观一变必须重写，
            // 否则深色快照里的禁用下拉仍是浅色底（看起来像一块白板）。
            AppStyles.RefreshPaletteResources(app);
        }

        if (Avalonia.Threading.Dispatcher.UIThread.CheckAccess()) Apply();
        else Palette.IsDark = appearance is "dark";
    }
}

/// <summary>不带托盘的 Application（headless 截图与单元级渲染共用）。</summary>
public sealed class HeadlessApplication : Application
{
    public override void Initialize()
    {
        Styles.Add(new Avalonia.Themes.Fluent.FluentTheme());
        RequestedThemeVariant = ThemeVariant.Default;
        // 和真实应用共用同一份控件样式（否则快照里的禁用态 / 圆角和真机对不上）。
        AppStyles.Install(this);
    }
}
