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

    /// <summary>
    /// 设定当前外观。`dark` / `light` 是**显式覆盖**（截图脚本、单测），优先于设置且不写设置；
    /// 传 null / 无法识别的值时清掉覆盖，改为跟随设置（缺省 Dark）。
    ///
    /// 主题变体、色板、禁用态资源三者的同步都在 <see cref="Theme.Appearance"/> 里做。
    /// </summary>
    public static void ApplyAppearance(string? appearance)
    {
        if (AppearanceChoices.Parse(appearance) is { } explicitChoice)
        {
            Appearance.Override = explicitChoice;
            Appearance.Force(explicitChoice);
            return;
        }
        // 没有显式外观：跟随设置。此时 Application 可能还没有（更别说设置），先按默认 Dark 起，
        // 等 AppServices 建好之后 SnapshotRunner / KanjoApplication 会再 Apply(settings) 一次。
        Appearance.Override = null;
        Appearance.Force(AppearanceChoice.Dark);
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
