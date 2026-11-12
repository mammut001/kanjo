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

    public static IBrush ForegroundBrush => Foreground;

    /// <summary>前景色的原始 Color（自绘图表要按 alpha 调淡）。</summary>
    public static Color ForegroundColor => ((ISolidColorBrush)Foreground).Color;

    /// <summary>强调色（链接 / 可点文字 / 拖拽高亮）。</summary>
    public static Color AccentColor => IsDark
        ? Color.FromRgb(0x6F, 0xA8, 0xFF)
        : Color.FromRgb(0x1F, 0x6F, 0xEB);

    /// <summary>系统语义前景色（Mac 是 .primary）。</summary>
    public static IBrush Foreground => IsDark
        ? new SolidColorBrush(Color.FromRgb(0xF2, 0xF2, 0xF5))
        : new SolidColorBrush(Color.FromRgb(0x1A, 0x1A, 0x1C));

    public static IBrush Secondary => new SolidColorBrush(IsDark
        ? Color.FromArgb(0xA0, 0xF2, 0xF2, 0xF5)
        : Color.FromArgb(0xA0, 0x1A, 0x1A, 0x1C));

    public static IBrush Tertiary => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x66, 0xF2, 0xF2, 0xF5)
        : Color.FromArgb(0x66, 0x1A, 0x1A, 0x1C));

    /// <summary>面板根背景：Mac 的 .regularMaterial 浅色下约为 #F1F1F1。</summary>
    public static IBrush PanelBackground => new SolidColorBrush(IsDark
        ? Color.FromRgb(0x22, 0x22, 0x24)
        : Color.FromRgb(0xF1, 0xF1, 0xF1));

    /// <summary>分组底色：一层很淡的填充，替代卡片描边。</summary>
    public static IBrush GroupFill => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x0F, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x0A, 0x00, 0x00, 0x00));

    public static IBrush RowHover => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x0F, 0x00, 0x00, 0x00));

    /// <summary>行上的小按钮按下态（RowIconButton 的 hover 底色）。</summary>
    public static IBrush RowPressed => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x1F, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x14, 0x00, 0x00, 0x00));

    /// <summary>悬停卡 / 弹出层的底色（实底，不透明，免得透出后面的内容）。</summary>
    public static IBrush CardBackground => new SolidColorBrush(IsDark
        ? Color.FromRgb(0x2C, 0x2C, 0x2F)
        : Color.FromRgb(0xFB, 0xFB, 0xFC));

    public static IBrush CardBorder => new SolidColorBrush(IsDark
        ? Color.FromArgb(0x26, 0xFF, 0xFF, 0xFF)
        : Color.FromArgb(0x1A, 0x00, 0x00, 0x00));

    public static BoxShadows CardShadow => IsDark
        ? BoxShadows.Parse("0 4 10 0 #40000000")
        : BoxShadows.Parse("0 4 10 0 #29000000");

    /// <summary>弹出层背后的遮罩（清理确认 / 计划卡）。</summary>
    public static IBrush Scrim => new SolidColorBrush(Colors.Black, 0.28);

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

    /// <summary>热力条空周的底色：Color.primary.opacity(0.08)。</summary>
    public static IBrush HeatEmpty => new SolidColorBrush(
        IsDark ? Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF) : Color.FromArgb(0x14, 0x00, 0x00, 0x00));

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

    /// <summary>Mosaic 方块上的文字颜色：Color.white.opacity(0.92)。</summary>
    public static IBrush OnTile => new SolidColorBrush(Color.FromArgb(0xEB, 0xFF, 0xFF, 0xFF));
}

/// <summary>
/// 版式常量。前四个照抄 Mac 的 Metrics；总览页用的是「扁平」一套。
/// <see cref="ContentInset"/> / <see cref="MosaicInset"/> 与 Mac 参考截图一致：
/// 文字区块左右留 10pt，马赛克几乎满宽（留 1.5pt 给圆角）。
/// </summary>
public static class Metrics
{
    public const double PagePadding = 14;
    public const double SectionSpacing = 18;
    public const double RowInset = 10;
    public const double GroupRadius = 10;

    // 总览：列表行直接放在面板上（没有分组底色）。
    public const double FlatPagePadding = 8;
    public const double ListInset = 16;
    public const double RowRadius = 6;

    /// <summary>总览文字区块的左右留白（参考截图 10pt）。</summary>
    public const double ContentInset = 10;

    /// <summary>马赛克与面板边缘的距离（参考截图 1.5pt，视觉上几乎满宽）。</summary>
    public const double MosaicInset = 1.5;

    /// <summary>项目行内上下留白（Swift ProjectRow.padV）。</summary>
    public const double RowPadV = 7;

    public const double PanelWidth = 360;
    public const double PanelHeight = 620;
}
