using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 外观设置（Windows 专有）的回归测试：默认 Dark、持久化、System → ThemeVariant.Default、
/// 切换时同时更新 Application.RequestedThemeVariant 与代码里的 Palette 色板。
///
/// macOS 版不读这个键（永远跟随系统），所以这里只断言 Windows 侧的行为。
/// </summary>
public sealed class AppearanceTests : KanjoTestCase
{
    private static Application App => Application.Current!;

    /// <summary>每个用例结束后把外观与覆盖复位，避免影响别的测试。</summary>
    private static void Reset()
    {
        Appearance.Override = null;
        Appearance.Force(AppearanceChoice.Dark);
    }

    /// <summary>等外观通知里的 UI 重建跑完（Appearance 会把非 UI 线程的调用 Post 过去）。</summary>
    private static void Flush()
    {
        Avalonia.Threading.Dispatcher.UIThread.RunJobs();
    }

    [Fact]
    public void TestDefaultAppearanceIsDarkWhenUnset()
    {
        // 缺省值就是 Dark：设置里没有这个键时，解析结果必须是 Dark（不是 System、不是 Light）。
        var settings = AppSettings.InMemory();
        Assert.Null(settings.GetString(SettingsKeys.Appearance));
        Assert.Equal("dark", SettingsDefaults.Appearance);
        Assert.Equal(AppearanceChoice.Dark, Appearance.FromSettings(settings));

        // 无法识别的值同样回落到 Dark（老版本写坏 / 手改 settings.json）。
        settings.Set(SettingsKeys.Appearance, "sepia");
        Assert.Equal(AppearanceChoice.Dark, Appearance.FromSettings(settings));
        Assert.Equal("dark", AppearanceChoices.Normalize("sepia"));
        Assert.Equal("dark", AppearanceChoices.Normalize(null));
        Assert.Equal("dark", AppearanceChoices.Normalize(""));
    }

    [Fact]
    public void TestAppearanceRoundTripsThroughSettingsFile()
    {
        // 持久化：写进真实的 settings.json，再新建一个 AppSettings 读回来。
        var dir = TempDir();
        var path = Path.Combine(dir, "settings.json");
        var first = new AppSettings(path);
        L10n.Store = first;
        L10n.ResetCache();

        foreach (var choice in AppearanceChoices.All)
        {
            first.Set(SettingsKeys.Appearance, choice.RawValue());
            var reloaded = new AppSettings(path);
            Assert.Equal(choice.RawValue(), reloaded.GetString(SettingsKeys.Appearance));
            Assert.Equal(choice, AppearanceChoices.Parse(reloaded.GetString(SettingsKeys.Appearance)));
            Assert.Equal(choice, Appearance.FromSettings(reloaded));
        }

        // 三个原始值保持稳定（settings.json 里的字段值不能变）。
        Assert.Equal("dark", AppearanceChoice.Dark.RawValue());
        Assert.Equal("light", AppearanceChoice.Light.RawValue());
        Assert.Equal("system", AppearanceChoice.System.RawValue());
    }

    [Fact]
    public void TestLabelsAreLocalizedInEveryLanguage()
    {
        // 外观的标题、说明与三个选项都要有本地化文案（和别的设置标签同一套机制）。
        string[] keys =
        [
            "settings.section.appearance", "settings.appearance", "settings.appearance.note",
            "settings.appearance.dark", "settings.appearance.light", "settings.appearance.system",
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
        Assert.Equal("Dark", WindowsL10n.TrL("en", "settings.appearance.dark"));
        Assert.Equal("深色", WindowsL10n.TrL("zh-Hans", "settings.appearance.dark"));
        Assert.Equal("Sombre", WindowsL10n.TrL("fr", "settings.appearance.dark"));
    }

    [Fact]
    public void TestChoicePersistsAndMapsToThemeVariant()
    {
        OnUi(() =>
        {
            try
            {
                var settings = AppSettings.InMemory();

                Appearance.Choose(settings, AppearanceChoice.Dark);
                Assert.Equal(ThemeVariant.Dark, App.RequestedThemeVariant);
                Assert.True(Palette.IsDark);
                Assert.Equal("dark", settings.GetString(SettingsKeys.Appearance));

                Appearance.Choose(settings, AppearanceChoice.Light);
                Assert.Equal(ThemeVariant.Light, App.RequestedThemeVariant);
                Assert.False(Palette.IsDark);
                Assert.Equal("light", settings.GetString(SettingsKeys.Appearance));

                // System 映射到 ThemeVariant.Default（即跟随 Windows），不是写死某个值。
                Appearance.Choose(settings, AppearanceChoice.System);
                Assert.Equal(ThemeVariant.Default, App.RequestedThemeVariant);
                Assert.Equal("system", settings.GetString(SettingsKeys.Appearance));
            }
            finally
            {
                Reset();
            }
        });
    }

    [Fact]
    public void TestPaletteResourcesFollowTheVariant()
    {
        OnUi(() =>
        {
            try
            {
                Appearance.Choose(AppSettings.InMemory(), AppearanceChoice.Dark);
                var dark = ((ISolidColorBrush)App.FindResource("ComboBoxBackgroundDisabled")!).Color;
                Assert.Equal(Palette.ControlSurfaceColor, dark);
                Assert.True(Palette.IsDark);

                Appearance.Choose(AppSettings.InMemory(), AppearanceChoice.Light);
                var light = ((ISolidColorBrush)App.FindResource("ComboBoxBackgroundDisabled")!).Color;
                Assert.Equal(Palette.ControlSurfaceColor, light);
                Assert.False(Palette.IsDark);

                // 两个外观下必须是不同的画笔，否则就是「停在上一套颜色」。
                Assert.NotEqual(dark, light);
            }
            finally
            {
                Reset();
            }
        });
    }

    /// <summary>
    /// 换外观后已经建出来的界面必须跟着换色 —— 代码里所有画笔都是构造时取值的，
    /// 所以 <see cref="Appearance.Changed"/> 必须让面板整页重建。
    ///
    /// 这里不断言「旧控件变成新颜色」（那本来就不会发生，所以才要重建），而是断言：
    /// 通知确实发出去了、面板挂上了这个订阅、重建后的新树用的是新色板。
    /// headless 里不挂真窗口：模板控件的 DynamicResource 在主题变体切换后会启动过渡，
    /// 而 headless 没有渲染循环，那个过渡时钟会抛跨线程异常（真机上窗口始终有渲染循环）。
    /// </summary>
    [Fact]
    public void TestPanelRebuildsWithNewPaletteOnAppearanceChange()
    {
        OnUi(() =>
        {
            try
            {
                var settings = AppSettings.InMemory();
                settings.Set(SettingsKeys.AppLanguage, "en");
                L10n.Store = settings;
                L10n.ResetCache();
                Appearance.Force(AppearanceChoice.Light);

                var services = new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir());
                services.LoadQuietly();
                var panel = new PanelView(services, AppRoute.Settings, snapshotMode: true);

                var rebuilds = 0;
                void Count() => rebuilds++;
                Appearance.Changed += Count;
                try
                {
                    Flush();
                    Assert.Equal(Palette.BackgroundColor, ((ISolidColorBrush)panel.Background!).Color);
                    Assert.Contains(CardColors(panel), c => c == Palette.CardColor);
                    // 浅色下卡片是纯白。
                    Assert.Equal(Avalonia.Media.Colors.White, Palette.CardColor);
                    Assert.Contains(TextColors(panel), c => c == Palette.SecondaryColor);

                    Appearance.Force(AppearanceChoice.Dark);
                    Flush();

                    Assert.True(rebuilds > 0, "PanelView must rebuild when the appearance changes");
                    Assert.True(Palette.IsDark);
                    Assert.Equal(Palette.BackgroundColor, ((ISolidColorBrush)panel.Background!).Color);
                    // 卡片底换成了深色 #2B2B2B，且树里不再有浅色那套的白卡片 / 黑字。
                    Assert.Equal(Palette.CardColor, Avalonia.Media.Color.FromRgb(0x2B, 0x2B, 0x2B));
                    Assert.Contains(CardColors(panel), c => c == Palette.CardColor);
                    Assert.DoesNotContain(CardColors(panel), c => c == Avalonia.Media.Colors.White);
                    Assert.Contains(TextColors(panel), c => c == Palette.SecondaryColor);
                    Assert.DoesNotContain(TextColors(panel), c => c == Palette.ForegroundColor);
                }
                finally
                {
                    Appearance.Changed -= Count;
                }
            }
            finally
            {
                Reset();
            }
        });
    }

    private static List<Color> CardColors(Visual root) =>
        root.GetVisualDescendants().OfType<Border>()
            .Select(b => b.Background)
            .OfType<ISolidColorBrush>()
            .Select(b => b.Color)
            .ToList();

    private static List<Color> TextColors(Visual root) =>
        root.GetVisualDescendants().OfType<TextBlock>()
            .Select(t => t.Foreground)
            .OfType<ISolidColorBrush>()
            .Select(b => b.Color)
            .ToList();

    /// <summary>截图模式必须仍然能出浅 / 深两种图：显式覆盖优先于设置，且不写设置。</summary>
    [Fact]
    public void TestSnapshotOverrideBeatsSetting()
    {
        OnUi(() =>
        {
            try
            {
                var settings = AppSettings.InMemory();
                // 设置是深色，但截图要浅色。
                settings.Set(SettingsKeys.Appearance, "dark");
                AppSetup.ApplyAppearance("light");

                Assert.Equal(AppearanceChoice.Light, Appearance.Override);
                Assert.Equal(AppearanceChoice.Light, Appearance.Resolve(settings));
                Assert.Equal(ThemeVariant.Light, App.RequestedThemeVariant);
                Assert.False(Palette.IsDark);
                // 设置本身没被改写。
                Assert.Equal("dark", settings.GetString(SettingsKeys.Appearance));

                AppSetup.ApplyAppearance("dark");
                Assert.Equal(ThemeVariant.Dark, App.RequestedThemeVariant);
                Assert.True(Palette.IsDark);

                // 没有显式外观时回到设置（这里 Application 还没有设置，按默认 Dark 起）。
                AppSetup.ApplyAppearance(null);
                Assert.Null(Appearance.Override);
            }
            finally
            {
                Reset();
            }
        });
    }
}
