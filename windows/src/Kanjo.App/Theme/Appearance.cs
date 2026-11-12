using Avalonia;
using Avalonia.Styling;
using Avalonia.Threading;
using Kanjo.App.Views;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 明暗外观（Windows 专有设置，见 <see cref="SettingsKeys.Appearance"/>）。
///
/// 两件事必须一起做，否则会出现「一半深色一半浅色」的界面：
/// 1. <see cref="Application.RequestedThemeVariant"/> —— 决定 Fluent 模板（ComboBox 底、滚动条、
///    按钮三态）用哪套资源。
/// 2. <see cref="Palette.IsDark"/> + <see cref="AppStyles.RefreshPaletteResources"/> —— 决定我们
///    自己在代码里取色的那一层（卡片底、文字、描边、强调色、禁用态资源）。
///
/// 代码里所有画笔都是**构造时**取值的（<c>new SolidColorBrush(Palette.X)</c>），所以换外观之后
/// 必须重建界面：<see cref="Changed"/> 由 <see cref="Views.PanelView"/> 订阅，整页重建一次。
/// </summary>
public static class Appearance
{
    /// <summary>当前生效的外观（缺省 Dark）。</summary>
    public static AppearanceChoice Current { get; private set; } = AppearanceChoice.Dark;

    /// <summary>
    /// 显式覆盖（截图脚本 / 单测用）。非 null 时优先于设置，且**不写**设置：
    /// `--snapshot-appearance light` 必须能出浅色图，哪怕用户设置是深色。
    /// </summary>
    public static AppearanceChoice? Override { get; set; }

    /// <summary>外观真的变了之后触发（已切好所有色板 + 主题资源）。测试 / 一次性监听用。</summary>
    public static event Action? Changed;

    /// <summary>
    /// 面板的弱引用订阅。面板每次导航都会重建，直接挂在静态事件上就会一路泄漏；
    /// 而且没有挂到窗口的旧面板被回调重建会在线程上出错（单测里就是 "Call from invalid thread"）。
    /// </summary>
    private static readonly List<(WeakReference<PanelView> Target, Action<PanelView> Handler)> Panels = [];

    /// <summary>让某个面板跟随外观变化（弱引用，面板被回收后自动失效）。</summary>
    public static void Watch(PanelView panel, Action<PanelView> handler) =>
        Panels.Add((new WeakReference<PanelView>(panel), handler));

    /// <summary>解除订阅（面板从可视树摘下时调用）。</summary>
    public static void Unwatch(PanelView panel) =>
        Panels.RemoveAll(entry => !entry.Target.TryGetTarget(out var live) || ReferenceEquals(live, panel));

    private static void NotifyPanels()
    {
        foreach (var (reference, handler) in Panels.ToList())
        {
            if (reference.TryGetTarget(out var panel)) handler(panel);
        }
        Panels.RemoveAll(entry => !entry.Target.TryGetTarget(out _));
    }

    /// <summary>设置里的外观；缺省 / 无法识别都按 Dark。</summary>
    public static AppearanceChoice FromSettings(AppSettings settings) =>
        AppearanceChoices.Parse(settings.GetString(SettingsKeys.Appearance)) ?? AppearanceChoice.Dark;

    /// <summary>实际要用的外观（覆盖优先）。</summary>
    public static AppearanceChoice Resolve(AppSettings settings) => Override ?? FromSettings(settings);

    /// <summary>按设置应用（启动、以及任何「设置变了」之后的兜底调用）。</summary>
    public static void Apply(AppSettings settings) => Set(Resolve(settings));

    /// <summary>用户在设置页选了新外观：写设置 + 立即生效（不重启）。</summary>
    public static void Choose(AppSettings settings, AppearanceChoice choice)
    {
        settings.Set(SettingsKeys.Appearance, choice.RawValue());
        Set(choice);
    }

    /// <summary>直接把外观设成某个值（截图 / 测试）。</summary>
    public static void Force(AppearanceChoice choice) => Set(choice);

    private static void Set(AppearanceChoice choice)
    {
        Current = choice;
        var app = Application.Current;
        if (app is null)
        {
            // 没有 Application（纯 Core 测试）：只更新色板。
            Palette.IsDark = IsDark(choice, null);
            Changed?.Invoke();
            NotifyPanels();
            return;
        }

        void ApplyNow()
        {
            app.RequestedThemeVariant = choice switch
            {
                AppearanceChoice.Dark => ThemeVariant.Dark,
                AppearanceChoice.Light => ThemeVariant.Light,
                // 跟随 Windows：Application 的 Default 会解析成系统的浅 / 深。
                _ => ThemeVariant.Default,
            };
            Palette.IsDark = IsDark(choice, app);
            // 禁用态资源是按色板取值的画笔，换外观后必须重写（否则深色下禁用下拉是浅色底）。
            AppStyles.RefreshPaletteResources(app);
            Changed?.Invoke();
            NotifyPanels();
        }

        // Application.RequestedThemeVariant 有线程校验（见 AppSetup.ApplyAppearance 的注释）。
        if (Dispatcher.UIThread.CheckAccess()) ApplyNow();
        else Dispatcher.UIThread.Post(ApplyNow);
    }

    /// <summary>这个外观是不是深色。System 读平台设置（拿不到就按浅色）。</summary>
    private static bool IsDark(AppearanceChoice choice, Application? app) => choice switch
    {
        AppearanceChoice.Dark => true,
        AppearanceChoice.Light => false,
        _ => app?.PlatformSettings?.GetColorValues().ThemeVariant
             == Avalonia.Platform.PlatformThemeVariant.Dark,
    };
}
