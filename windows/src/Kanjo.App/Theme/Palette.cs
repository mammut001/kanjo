using Avalonia;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 全部颜色在这里定义，逐条对应 Mac 版 AgentPalette：
/// 文字用前景色 / 次要色，这里的颜色只给色块、细条、图表用；agent 色跟着 agent 走；
/// 状态色（警告 / 错误）只在真的出问题时出现。
/// </summary>
public static class Palette
{
    /// <summary>当前外观（启动时决定；跟随系统或 --snapshot-appearance）。</summary>
    public static bool IsDark { get; set; }

    public static void ApplyAppearance(string? appearance)
    {
        if (appearance is "dark") IsDark = true;
        else if (appearance is "light") IsDark = false;
        else IsDark = Application.Current?.ActualThemeVariant == Avalonia.Styling.ThemeVariant.Dark;
    }

    public static Color AgentColor(string agent)
    {
        var pair = AgentColors.Pair(agent);
        return FromHex(IsDark ? pair.Dark : pair.Light);
    }

    public static IBrush Agent(string agent) => new SolidColorBrush(AgentColor(agent));

    public static Color FromHex(uint hex) => Color.FromRgb(
        (byte)((hex >> 16) & 0xFF), (byte)((hex >> 8) & 0xFF), (byte)(hex & 0xFF));

    private static Color Hex(uint light, uint dark) => FromHex(IsDark ? dark : light);

    // MARK: - 文字与底色

    public static IBrush Foreground => IsDark
        ? new SolidColorBrush(Color.FromRgb(0xF2, 0xF2, 0xF5))
        : new SolidColorBrush(Color.FromRgb(0x1A, 0x1A, 0x1C));

    public static IBrush Secondary => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x9E, 0xF2, 0xF2, 0xF5)
        : Color.FromArgb(0x9E, 0x1A, 0x1A, 0x1C));

    public static IBrush Tertiary => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x70, 0xF2, 0xF2, 0xF5)
        : Color.FromArgb(0x70, 0x1A, 0x1A, 0x1C));

    /// <summary>面板根背景。Windows 11 上由窗口 Mica 透出，其它平台用近似材质色。</summary>
    public static IBrush PanelBackground => new SolidColorBrush(IsDark
        ? Color.FromRgb(0x24, 0x24, 0x26)
        : Color.FromRgb(0xF4, 0xF4, 0xF6));

    /// <summary>分组底色：一层很淡的填充，替代卡片描边。</summary>
    public static IBrush GroupFill => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x0F, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x0A, 0x00, 0x00, 0x00));

    public static IBrush RowHover => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x0F, 0x00, 0x00, 0x00));

    public static IBrush Separator => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x1F, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x1F, 0x00, 0x00, 0x00));

    // MARK: - Agent 色

    public static IBrush Neutral => new SolidColorBrush(Hex(AgentColors.NeutralLight, AgentColors.NeutralDark));

    /// <summary>Token 构成：input / output / cache write 借用三个 agent 色，cache read 用更浅更安静的蓝。</summary>
    public static IBrush TokenInput => new SolidColorBrush(Hex(0x3E79D6, 0x6FA0F0));
    public static IBrush TokenOutput => new SolidColorBrush(Hex(0xD97757, 0xE8926F));
    public static IBrush TokenCacheRead => new SolidColorBrush(Hex(0xB9CDEE, 0x3D5478));
    public static IBrush TokenCacheWrite => new SolidColorBrush(Hex(0x7A6AD8, 0x9B8DF0));

    /// <summary>图表默认色：中性的石板色。</summary>
    public static IBrush ChartBar => new SolidColorBrush(Hex(0x8796B0, 0x7E8EAA));

    /// <summary>置顶：琥珀色。</summary>
    public static IBrush Pin => new SolidColorBrush(Hex(0xC2861A, 0xE8B44F));

    /// <summary>热力条空周的底色。</summary>
    public static IBrush HeatEmpty => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x1F, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x14, 0x00, 0x00, 0x00));

    // MARK: - 状态色

    public static IBrush Good => new SolidColorBrush(Hex(0x2E7D4A, 0x74C98F));
    public static IBrush GoodFill => new SolidColorBrush(Hex(0x2E7D4A, 0x74C98F), IsDark ? 0.20 : 0.14);
    public static IBrush Bad => new SolidColorBrush(Hex(0xB3261E, 0xFF8A80));
    public static IBrush BadFill => new SolidColorBrush(FromHex(0xE5484D), IsDark ? 0.18 : 0.10);
    public static IBrush QuotaWarn => new SolidColorBrush(Hex(0xD08A12, 0xF0B248));
    public static IBrush WarnInk => new SolidColorBrush(Hex(0x6E5512, 0xE8CF94));
    public static IBrush WarnFill => new SolidColorBrush(FromHex(0xD9A53A), IsDark ? 0.18 : 0.16);

    /// <summary>强调色（链接 / 可点文字）。</summary>
    public static IBrush Accent => IsDark
        ? new SolidColorBrush(Color.FromRgb(0x6F, 0xA8, 0xFF))
        : new SolidColorBrush(Color.FromRgb(0x1F, 0x6F, 0xEB));

    /// <summary>Mosaic 方块上的文字颜色。</summary>
    public static IBrush OnTile => new SolidColorBrush(Color.FromArgb(0xEB, 0xFF, 0xFF, 0xFF));
}

/// <summary>版式常量：整个面板只用这几档字号，层级靠字号 / 字重 / 次要色，不靠边框。</summary>
public static class Metrics
{
    public const double PagePadding = 14;
    public const double SectionSpacing = 18;
    public const double RowInset = 10;
    public const double GroupRadius = 10;

    // 总览：列表行直接放在面板上（没有分组底色）。页边距更窄，行内缩进更大。
    public const double FlatPagePadding = 8;
    public const double ListInset = 16;
    public const double RowRadius = 6;

    public const double PanelWidth = 360;
    public const double PanelHeight = 620;
}
