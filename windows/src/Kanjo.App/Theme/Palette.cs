using Avalonia;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// Fluent 色板：界面用到的每一个颜色都在这里定义，视图里不出现裸 16 进制。
/// 分两组 —— 「表面」（背景 / 卡片 / 描边）和「文字」（primary / secondary / tertiary / disabled），
/// 外加 agent 色与状态色。所有成对的对比度在 <c>ContrastTests</c> 里按 WCAG 2.1 公式断言：
///   primary ≥ 12:1，secondary / tertiary ≥ 4.5:1（卡片上 和 背景上都算），
///   disabled 文字与控制描边 ≥ 3:1，分割线 / 卡片描边 ≥ 1.5:1。
/// light 下底色 #F3F3F3 / 卡片 #FFFFFF，dark 下 #202020 / #2B2B2B（WinUI 的 layer 值）。
/// 文字一律用实色，不用「前景色 + alpha」叠在灰底上（那正是旧版几乎看不清的原因）。
/// </summary>
public static class Palette
{
    /// <summary>当前外观（启动 / 截图时决定）。</summary>
    public static bool IsDark { get; set; }

    /// <summary>
    /// 系统强调色（Windows 设置里的「个性化 → 颜色」）。由 <see cref="ApplyPlatformAccent"/> 在启动时读取；
    /// 拿不到就用 Windows 11 默认的 #005FB8 / #60CDFF。
    /// </summary>
    private static Color? _platformAccent;

    public static void ApplyAppearance(string? appearance)
    {
        if (appearance is "dark") IsDark = true;
        else if (appearance is "light") IsDark = false;
        else IsDark = Application.Current?.ActualThemeVariant == Avalonia.Styling.ThemeVariant.Dark;
    }

    /// <summary>
    /// 读取系统强调色（<c>PlatformSettings.GetColorValues().AccentColor1</c>）。
    /// 必须在渲染后端起来之后调用；headless / 无平台设置时静默保留默认值。
    /// </summary>
    public static void ApplyPlatformAccent()
    {
        try
        {
            var values = Application.Current?.PlatformSettings?.GetColorValues();
            if (values is not { } v) return;
            var accent = v.AccentColor1;
            if (accent.A == 0) return;
            // headless 后端会回一个纯黑占位值；那不是真的强调色，忽略。
            if (accent is { R: 0, G: 0, B: 0 }) return;
            _platformAccent = Color.FromRgb(accent.R, accent.G, accent.B);
        }
        catch (Exception)
        {
            // 没有平台设置（headless / 单元测试）：用默认强调色。
        }
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

    // MARK: - 表面

    /// <summary>窗口 / 页面底色。Mica 不可用时（Windows 10 / Server 2022）也是这一层实底。</summary>
    public static Color BackgroundColor => Hex(0xF3F3F3, 0x202020);

    /// <summary>卡片底：设置项、分组、悬停卡都坐在这上面。</summary>
    public static Color CardColor => Hex(0xFFFFFF, 0x2B2B2B);

    public static IBrush PanelBackground => new SolidColorBrush(BackgroundColor);

    public static IBrush CardBackground => new SolidColorBrush(CardColor);

    /// <summary>
    /// 卡片描边（CardStrokeColorDefault）。WinUI 的 #E5E5E5 / #1D1D1D 对卡片只有 1.24:1，
    /// 低于我们 1.5:1 的下限，所以这里取更深一档：light #CFCFCF（1.56:1）/ dark #4C4C4C（1.65:1）。
    /// </summary>
    public static Color CardStrokeColor => Hex(0xCFCFCF, 0x4C4C4C);

    public static IBrush CardBorder => new SolidColorBrush(CardStrokeColor);

    /// <summary>分组之间的细分割线：和卡片描边同色，足够看见。</summary>
    public static IBrush Separator => new SolidColorBrush(CardStrokeColor);

    /// <summary>行 / 按钮的悬停填充（Windows 11 用一层很淡的中性色，不是强调色）。</summary>
    public static IBrush RowHover => new SolidColorBrush(Hex(0xF0F0F0, 0x333333));

    /// <summary>按下态：比悬停再深一点。</summary>
    public static IBrush RowPressed => new SolidColorBrush(Hex(0xE6E6E6, 0x3B3B3B));

    /// <summary>卡片内再分组的淡底（比如订阅行之间），只在卡片内部使用。</summary>
    public static Color GroupFillColor => Hex(0xF7F7F7, 0x323232);

    public static IBrush GroupFill => new SolidColorBrush(GroupFillColor);

    /// <summary>控件底（TextBox / ComboBox 未聚焦时）：比卡片略深，能在白卡上看出输入区。</summary>
    public static IBrush ControlFill => new SolidColorBrush(Hex(0xFBFBFB, 0x303030));

    /// <summary>
    /// 输入控件的「表面」：Fluent 主题给 ComboBox / TextBox 用的启用态底色
    /// （light 纯白 / dark #1A1A1A）。禁用态要用**同一个底**，只把字变淡 ——
    /// 否则深色下禁用控件比启用的还亮（#303030 vs #1A1A1A），看起来像另一套控件。
    /// </summary>
    public static Color ControlSurfaceColor => Hex(0xFFFFFF, 0x1A1A1A);

    /// <summary>悬停卡 / 弹出层的阴影（离屏渲染下用偏移的半透明圆角矩形模拟）。</summary>
    public static BoxShadows CardShadow => IsDark
        ? BoxShadows.Parse("0 4 10 0 #40000000")
        : BoxShadows.Parse("0 4 10 0 #29000000");

    /// <summary>弹出层背后的遮罩（清理确认 / 计划卡）。</summary>
    public static IBrush Scrim => new SolidColorBrush(Colors.Black, 0.32);

    // MARK: - 文字

    /// <summary>正文 / 标题（primary）：卡片上 17.4:1，背景上 15.7:1（dark 反向 14.2 / 16.3）。</summary>
    public static Color ForegroundColor => Hex(0x1A1A1A, 0xFFFFFF);

    public static IBrush Foreground => new SolidColorBrush(ForegroundColor);

    /// <summary>次要文字：卡片 6.6:1，背景 5.9:1（dark 8.5 / 9.7）。</summary>
    public static Color SecondaryColor => Hex(0x5D5D5D, 0xC8C8C8);

    public static IBrush Secondary => new SolidColorBrush(SecondaryColor);

    /// <summary>说明 / 脚注（caption）：卡片 6.2:1，背景 5.6:1（dark 7.7 / 8.9）。</summary>
    public static Color TertiaryColor => Hex(0x616161, 0xBFBFBF);

    public static IBrush Tertiary => new SolidColorBrush(TertiaryColor);

    /// <summary>比 tertiary 更淡的一档（旧版 .borderless 按钮里的观感），同样按 tertiary 的实色走。</summary>
    public static Color MutedColor => TertiaryColor;

    public static IBrush Muted => new SolidColorBrush(MutedColor);

    /// <summary>禁用文字：卡片 3.4:1，背景 3.1:1（dark 4.1 / 4.7）—— 旧版 0.26 alpha 只有 1.9:1。</summary>
    public static Color DisabledColor => Hex(0x8A8A8A, 0x8A8A8A);

    public static IBrush Disabled => new SolidColorBrush(DisabledColor);

    /// <summary>禁用控件 / 输入框的描边（≥ 3:1）。</summary>
    public static IBrush DisabledStroke => new SolidColorBrush(DisabledColor);

    /// <summary>
    /// 禁用控件的填充：和卡片几乎同色，但描边用 <see cref="DisabledColor"/> 看得见。
    /// （Fluent 主题自带的禁用底 #CCCCCC 太深，配它自己的灰字只有 2.7:1。）
    /// </summary>
    public static IBrush DisabledFill => new SolidColorBrush(Hex(0xF2F2F2, 0x2A2A2A));

    // MARK: - 强调色

    /// <summary>强调色（链接 / 主按钮 / 选中态）。默认 #005FB8 light / #60CDFF dark，有系统色时用系统色。</summary>
    public static Color AccentColor => _platformAccent ?? Hex(0x005FB8, 0x60CDFF);

    /// <summary>
    /// 强调色填充（主按钮底）：为了「强调色上的文字 ≥ 4.5:1」，必要时把系统强调色
    /// 朝远离文字色的方向微调一点点（最多 25%）。没有系统色时就是原值。
    /// </summary>
    public static Color AccentFillColor
    {
        get
        {
            var accent = AccentColor;
            var text = PickOnAccent(accent);
            if (Contrast(text, accent) >= 4.5) return accent;
            // 文字是白就压暗填充，是近黑就提亮填充。
            var target = text == Colors.White ? Colors.Black : Colors.White;
            for (var step = 1; step <= 25; step++)
            {
                var candidate = Blend(target, accent, step / 100.0);
                if (Contrast(text, candidate) >= 4.5) return candidate;
            }
            return accent;
        }
    }

    /// <summary>
    /// 链接文字色：系统强调色可能很浅（比如黄色），直接当文字读不出来。
    /// 这里在保证 ≥ 4.5:1（卡片上和背景上都算）的前提下尽量贴近系统色。
    /// </summary>
    public static Color LinkColor
    {
        get
        {
            var accent = AccentColor;
            if (LinkRatio(accent) >= 4.5) return accent;
            // light 变暗、dark 变亮，最多 45%。
            var target = IsDark ? Colors.White : Colors.Black;
            for (var step = 1; step <= 45; step++)
            {
                var candidate = Blend(target, accent, step / 100.0);
                if (LinkRatio(candidate) >= 4.5) return candidate;
            }
            return accent;
        }
    }

    /// <summary>链接色在「卡片」和「背景」两种表面上都能到 4.5:1 才算过。</summary>
    private static double LinkRatio(Color color) => Math.Min(
        Contrast(color, CardColor), Contrast(color, BackgroundColor));

    private static Color PickOnAccent(Color accent)
    {
        var white = Colors.White;
        var ink = Color.FromRgb(0x10, 0x10, 0x10);
        return Contrast(white, accent) >= Contrast(ink, accent) ? white : ink;
    }

    /// <summary>强调色填充（主按钮底）。</summary>
    public static IBrush Accent => new SolidColorBrush(AccentFillColor);

    /// <summary>强调色上的文字：按填充亮度在白与近黑之间取对比度更高的一个（≥ 4.5:1）。</summary>
    public static Color OnAccentColor => PickOnAccent(AccentFillColor);

    /// <summary>任意填充上的文字色：按填充亮度在白与近黑之间选对比度更高的那个。</summary>
    public static IBrush ContrastOn(IBrush fill)
    {
        if (fill is not ISolidColorBrush solid) return new SolidColorBrush(Colors.White);
        var color = solid.Color;
        var ink = Color.FromRgb(0x10, 0x10, 0x10);
        return new SolidColorBrush(Contrast(Colors.White, color) >= Contrast(ink, color)
            ? Colors.White
            : ink);
    }

    public static IBrush OnAccent => new SolidColorBrush(OnAccentColor);

    /// <summary>强调色的淡填充（选中胶囊 / 拖拽落点）。</summary>
    public static IBrush AccentSubtle => new SolidColorBrush(AccentFillColor, IsDark ? 0.22 : 0.12);

    /// <summary>链接文字：系统强调色按需加深 / 提亮，保证 4.5:1 以上。</summary>
    public static IBrush Link => new SolidColorBrush(LinkColor);

    // MARK: - 状态色

    /// <summary>成功 / 已对账。light #1B6B3A（卡片 6.3:1）/ dark #74C98F（卡片 8.3:1）。</summary>
    public static Color GoodColor => Hex(0x1B6B3A, 0x74C98F);

    public static IBrush Good => new SolidColorBrush(GoodColor);

    public static IBrush GoodFill => new SolidColorBrush(FromHex(0x2E7D4A), IsDark ? 0.22 : 0.10);

    /// <summary>错误。light #B3261E（卡片 6.2:1）/ dark #FF8A80。</summary>
    public static Color BadColor => Hex(0xB3261E, 0xFF8A80);

    public static IBrush Bad => new SolidColorBrush(BadColor);

    public static IBrush BadFill => new SolidColorBrush(FromHex(0xE5484D), IsDark ? 0.20 : 0.10);

    /// <summary>警告图标 / 进度（不是文字）。</summary>
    public static IBrush QuotaWarn => new SolidColorBrush(Hex(0x9A6400, 0xF0B248));

    /// <summary>警告色文字（InfoBar / 徽章）：light #6E5512（卡片 7.1:1）/ dark #E8CF94。</summary>
    public static Color WarnInkColor => Hex(0x6E5512, 0xE8CF94);

    public static IBrush WarnInk => new SolidColorBrush(WarnInkColor);

    public static IBrush WarnFill => new SolidColorBrush(FromHex(0xD9A53A), IsDark ? 0.20 : 0.14);

    /// <summary>InfoBar（警告）的底色与描边：淡琥珀 + 一条实色左边框。</summary>
    public static Color InfoBarFillColor => Hex(0xFFF8E6, 0x3A3222);

    public static Color InfoBarStrokeColor => Hex(0xD9C48A, 0x6B5C34);

    public static IBrush InfoBarFill => new SolidColorBrush(InfoBarFillColor);

    public static IBrush InfoBarStroke => new SolidColorBrush(InfoBarStrokeColor);

    // MARK: - Agent 色

    public static IBrush Neutral => new SolidColorBrush(Hex(AgentColors.NeutralLight, AgentColors.NeutralDark));

    /// <summary>Token 构成：input / output / cache write 借用三个 agent 色，cache read 用更浅更安静的蓝。</summary>
    public static Color TokenInputColor => Hex(0x3E79D6, 0x6FA0F0);

    public static Color TokenOutputColor => Hex(0xD97757, 0xE8926F);

    public static Color TokenCacheReadColor => Hex(0xB9CDEE, 0x3D5478);

    public static Color TokenCacheWriteColor => Hex(0x7A6AD8, 0x9B8DF0);

    public static IBrush TokenInput => new SolidColorBrush(TokenInputColor);

    public static IBrush TokenOutput => new SolidColorBrush(TokenOutputColor);

    public static IBrush TokenCacheRead => new SolidColorBrush(TokenCacheReadColor);

    public static IBrush TokenCacheWrite => new SolidColorBrush(TokenCacheWriteColor);

    /// <summary>图表默认色：中性的石板色。</summary>
    public static Color ChartBarColor => Hex(0x8796B0, 0x7E8EAA);

    public static IBrush ChartBar => new SolidColorBrush(ChartBarColor);

    /// <summary>置顶：琥珀色。</summary>
    public static IBrush Pin => new SolidColorBrush(Hex(0xC2861A, 0xE8B44F));

    /// <summary>热力条空周的底色。</summary>
    public static IBrush HeatEmpty => new SolidColorBrush(Hex(0xEDEDED, 0x363636));

    /// <summary>色块上的白字（旧的固定值；马赛克现在按 <see cref="TileInk"/> 逐块选色）。</summary>
    public static IBrush OnTile => new SolidColorBrush(Colors.White);

    /// <summary>
    /// 色块（马赛克）上的标签文字：在白与近黑里选对比度更高的一个；两者都不够 4.5:1 时
    /// 把色块朝相反方向微调（最多 4%），保证文字永远可读。色块本身的色相不变，agent 识别不受影响。
    /// </summary>
    public static Color TileInk(Color tile) => TileInk(tile, out _);

    /// <summary>同上，并输出为达到 4.5:1 实际要用的色块颜色（一般就是原色）。</summary>
    public static Color TileInk(Color tile, out Color adjustedTile)
    {
        var white = Colors.White;
        var ink = Color.FromRgb(0x10, 0x10, 0x10);
        var onWhite = Contrast(white, tile);
        var onInk = Contrast(ink, tile);
        var text = onWhite >= onInk ? white : ink;
        adjustedTile = tile;
        if (Math.Max(onWhite, onInk) >= 4.5) return text;

        // 朝远离文字色的方向微调色块，直到够 4.5:1（实测最多 4%）。
        var target = text == white ? Colors.Black : Colors.White;
        for (var step = 1; step <= 20; step++)
        {
            var alpha = step / 100.0;
            var candidate = Blend(target, tile, alpha);
            if (Contrast(text, candidate) < 4.5) continue;
            adjustedTile = candidate;
            return text;
        }
        return text;
    }

    // MARK: - 对比度工具（ContrastTests 与 TileInk 共用）

    public static double Contrast(Color a, Color b)
    {
        var la = Luminance(a);
        var lb = Luminance(b);
        var hi = Math.Max(la, lb);
        var lo = Math.Min(la, lb);
        return (hi + 0.05) / (lo + 0.05);
    }

    public static double Luminance(Color color)
    {
        static double Channel(byte value)
        {
            var c = value / 255.0;
            return c <= 0.04045 ? c / 12.92 : Math.Pow((c + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * Channel(color.R) + 0.7152 * Channel(color.G) + 0.0722 * Channel(color.B);
    }

    /// <summary>把 <paramref name="foreground"/> 按 <paramref name="alpha"/> 压到 <paramref name="background"/> 上。</summary>
    public static Color Blend(Color foreground, Color background, double alpha)
    {
        static byte Mix(byte fg, byte bg, double a) =>
            (byte)Math.Clamp(Math.Round(fg * a + bg * (1 - a)), 0, 255);
        var clamped = Math.Clamp(alpha, 0, 1);
        return Color.FromRgb(Mix(foreground.R, background.R, clamped),
            Mix(foreground.G, background.G, clamped), Mix(foreground.B, background.B, clamped));
    }
}

/// <summary>
/// 版式常量。卡片 / 间距照 Windows 11 设置页的节奏：卡片圆角 8、内边距 16、
/// 同一分组内卡片间距 4、分组之间 24。
/// </summary>
public static class Metrics
{
    /// <summary>
    /// 页面左右留白（12）。卡片再各自有 12 的内边距，所以内容距窗口边缘 24 ——
    /// 360px 的面板里再宽就会出现「内容被两侧内缩两次」的挤压。
    /// </summary>
    public const double PagePadding = 12;

    /// <summary>分组之间（24px）。</summary>
    public const double SectionSpacing = 24;

    /// <summary>卡片内的左右内边距（12px）。</summary>
    public const double RowInset = 12;

    /// <summary>返回按钮的左缩进（抵消自绘 chevron 的空白）。</summary>
    public const double BackInset = RowInset - 13;

    /// <summary>卡片圆角（Windows 11 卡片是 8）。</summary>
    public const double GroupRadius = 8;

    /// <summary>卡片内边距（上下）。</summary>
    public const double CardPaddingV = 12;

    /// <summary>同一分组里堆叠卡片之间的缝（4px）。</summary>
    public const double CardGap = 4;

    /// <summary>设置行的最小高度（Windows 11 的 52px 行高，留一点余量给两行文字）。</summary>
    public const double SettingRowMinHeight = 52;

    /// <summary>右侧控件的固定最小宽度（任务要求 200）。</summary>
    public const double ControlMinWidth = 200;

    /// <summary>一行内容可用的宽度：面板宽 − 两侧页面留白 − 卡片描边 − 卡片左右内边距。</summary>
    public const double RowContentWidth = PanelWidth - PagePadding * 2 - 2 - RowInset * 2;

    // 总览的扁平列表（保留旧名字，值改成卡片的节奏）。
    public const double FlatPagePadding = 8;
    public const double ListInset = 12;
    public const double RowRadius = 6;

    /// <summary>总览文字区块的左右留白。</summary>
    public const double ContentInset = 16;

    /// <summary>马赛克与卡片边缘的距离。</summary>
    public const double MosaicInset = 1.5;

    public const double RowPadV = 7;

    public const double PanelWidth = 360;

    /// <summary>面板高度：Windows 11 的托盘面板稍高一点，能放下标题栏 + 内容 + 底栏。</summary>
    public const double PanelHeight = 620;

    /// <summary>页面切换动画时长。</summary>
    public const double PageTransitionMilliseconds = 150;

    /// <summary>页面切换时的位移（8px 上滑）。</summary>
    public const double PageTransitionOffset = 8;

    /// <summary>面板弹出时的位移。</summary>
    public const double PanelTransitionOffset = 12;

    /// <summary>悬停 / 按下状态的过渡时长上限（任务要求 ≤ 100ms）。</summary>
    public const double StateTransitionMilliseconds = 90;
}
