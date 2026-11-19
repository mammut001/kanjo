using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 版式回归测试（review 里逐条列出的裁剪 / 挤压问题）。
/// 这些用例直接量布局，避免以后再被「页面留白 + 卡片内边距」双重内缩悄悄挤坏。
///
/// 所有 UI 构造与测量都必须跑在 Avalonia 的 UI 线程上（<see cref="HeadlessUnitTestSession"/>），
/// 否则一旦 headless 会话建立，在测试线程上 new 控件会抛 "Call from invalid thread"。
/// </summary>
public sealed class LayoutTests : KanjoTestCase
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

    /// <summary>建页面 + 窗口并完成布局。</summary>
    private static Window Show(Control page)
    {
        var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        page.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        return window;
    }

    /// <summary>页面横向留白 12、卡片内边距 12：两者都不能再被调大，否则内容会被挤。</summary>
    [Fact]
    public void TestGlobalHorizontalInsetIsTwelvePlusTwelve()
    {
        Assert.Equal(12, Metrics.PagePadding);
        Assert.Equal(12, Metrics.RowInset);
        Assert.True(Metrics.RowContentWidth >= 300, $"row content width = {Metrics.RowContentWidth}");
    }

    /// <summary>
    /// 概览 hero：标题独占一行；7 个范围胶囊全部存在、每个都完整（不折行、不切词），
    /// 放不下时靠横向滚动都能到达（不画滚动条）。
    /// </summary>
    [Fact]
    public void TestOverviewRangePillsAllReachableAndNotTruncated()
    {
        OnUi(() =>
        {
            var page = new OverviewPage(NewServices(), null, snapshot: false);
            var window = Show(page);

            var picker = page.GetVisualDescendants().OfType<RangePicker>().First();
            Assert.True(picker.Bounds.Width > 0);
            Assert.NotNull(picker.PillsScroller);

            var chips = picker.GetVisualDescendants().OfType<Border>()
                .Where(b => b.Child is TextBlock { Text.Length: > 0 } tb && tb.FontSize == 11)
                .ToList();
            Assert.Equal(TimeRanges.All.Count, chips.Count);

            // 每个胶囊的文字都必须完整（宽度 >= 测量宽度，且没有被省略号）。
            foreach (var chip in chips)
            {
                var text = (TextBlock)chip.Child!;
                var measured = Kanjo.App.Type.MeasureWidth(text.Text!, 11);
                Assert.True(text.Bounds.Width >= measured - 0.5,
                    $"pill '{text.Text}' text width {text.Bounds.Width:F1} < measured {measured:F1}");
                Assert.True(chip.Bounds.Width >= text.Bounds.Width,
                    $"pill '{text.Text}' chip narrower than its text");
            }

            // 最后一个胶囊仍然完整，且通过滚动可以到达（滚动范围覆盖它的右边界）。
            var last = chips[^1];
            var lastRight = last.Bounds.Right;
            var scroller = picker.PillsScroller!;
            var maxScroll = Math.Max(0, scroller.Extent.Width - scroller.Viewport.Width);
            Assert.True(lastRight <= scroller.Viewport.Width + maxScroll + 1,
                $"last pill right {lastRight:F1} unreachable (viewport {scroller.Viewport.Width:F1} + scroll {maxScroll:F1})");

            // 英文词本身放得下时，整行必须落在视口里（不需要横向滚动，Cycle 不被右缘裁掉）。
            // 有的 headless 字体每个字形都是固定宽度，七个英文词加起来比视口还宽，那种情况只能滚动。
            AssertEnglishPillsFitWhenLabelsFit(chips, scroller);

            window.Close();
        });
    }

    /// <summary>简体中文的七个范围胶囊也必须放进 360pt 的视口，不靠滚动。</summary>
    [Fact]
    public void TestOverviewRangePillsFitInChineseWithoutScrolling()
    {
        OnUi(() =>
        {
            var settings = AppSettings.InMemory();
            settings.Set(SettingsKeys.AppLanguage, "zh-Hans");
            L10n.Store = settings;
            L10n.ResetCache();
            var services = new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir());
            services.LoadQuietly();
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var picker = page.GetVisualDescendants().OfType<RangePicker>().First();
            var chips = PillChips(picker);
            Assert.Equal(TimeRanges.All.Count, chips.Count);
            var scroller = picker.PillsScroller!;
            AssertPillsFitWhenLabelsFit(chips, scroller, "zh-Hans");

            window.Close();
        });
    }

    private static List<Border> PillChips(RangePicker picker) =>
        picker.GetVisualDescendants().OfType<Border>()
            .Where(b => b.Child is TextBlock { Text.Length: > 0 } tb && Math.Abs(tb.FontSize - 11) < 0.1)
            .ToList();

    private static void AssertEnglishPillsFitWhenLabelsFit(IReadOnlyList<Border> chips, ScrollViewer scroller) =>
        AssertPillsFitWhenLabelsFit(chips, scroller, "en");

    /// <summary>
    /// 最小内边距下文字放得进视口时，extent 不能宽过 viewport。
    /// 放不进（stub 字体）则只要求没有为了「撑满」而把内边距加大到不得不滚。
    /// </summary>
    private static void AssertPillsFitWhenLabelsFit(IReadOnlyList<Border> chips, ScrollViewer scroller, string language)
    {
        double text = 0;
        foreach (var chip in chips)
        {
            var block = (TextBlock)chip.Child!;
            text += Kanjo.App.Type.MeasureWidth(block.Text!, block.FontSize, block.FontWeight);
        }
        const double minPad = 4;
        var viewport = scroller.Viewport.Width;
        var minRow = text + chips.Count * minPad * 2;
        if (minRow <= viewport)
        {
            Assert.True(scroller.Extent.Width <= viewport + 0.5,
                $"{language} pills scroll: extent {scroller.Extent.Width:F1} viewport {viewport:F1} " +
                $"pad={chips[0].Padding.Left:F1} text={text:F1}");
        }
        else
        {
            Assert.True(chips[0].Padding.Left <= minPad + 0.05,
                $"{language} labels ({text:F1}) exceed viewport {viewport:F1} but pad is {chips[0].Padding.Left:F1}");
        }
    }

    /// <summary>概览 hero 里的 "Total cost" 标签必须在胶囊那一行之上（不能挤在一起）。</summary>
    [Fact]
    public void TestOverviewTotalCostLabelIsOnItsOwnLine()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var picker = page.GetVisualDescendants().OfType<RangePicker>().First();
            var label = page.GetVisualDescendants().OfType<TextBlock>()
                .First(t => t.Text == L10n.Tr("overview.total_cost"));

            var pickerTop = picker.TranslatePoint(new Point(0, 0), page) ?? default;
            var labelBottom = label.TranslatePoint(new Point(0, label.Bounds.Height), page) ?? default;
            Assert.True(labelBottom.Y <= pickerTop.Y + 1,
                $"total cost label bottom {labelBottom.Y:F1} must be above picker top {pickerTop.Y:F1}");

            window.Close();
        });
    }

    /// <summary>
    /// 项目行：副标题必须在热力条之前截断，不能画到热力条下面。
    /// </summary>
    [Fact]
    public void TestProjectRowSubtitleDoesNotOverlapHeatStrip()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var strips = page.GetVisualDescendants().OfType<HeatStripView>().ToList();
            Assert.NotEmpty(strips);

            var subtitles = page.GetVisualDescendants().OfType<TextBlock>()
                .Where(t => t.FontSize == 12 && t.TextWrapping == TextWrapping.NoWrap &&
                            (t.Text?.Contains("sessions", StringComparison.Ordinal) ?? false))
                .ToList();
            Assert.NotEmpty(subtitles);
            foreach (var text in subtitles)
            {
                // 最近活跃在最前面，可见宽度至少要容得下这一段。
                var head = text.Text!.Split(" · ", 2)[0];
                var headWidth = Kanjo.App.Type.MeasureWidth(head, 12);
                Assert.True(text.Bounds.Width + 0.5 >= headWidth,
                    $"subtitle '{text.Text}' hides last-active '{head}' ({text.Bounds.Width:F1} < {headWidth:F1})");
            }

            foreach (var strip in strips)
            {
                var stripLeft = strip.TranslatePoint(new Point(0, 0), page)?.X ?? 0;
                var stripTop = strip.TranslatePoint(new Point(0, 0), page)?.Y ?? 0;
                foreach (var text in subtitles)
                {
                    var p = text.TranslatePoint(new Point(0, 0), page);
                    if (p is null || Math.Abs(p.Value.Y - stripTop) > 30) continue;
                    Assert.True(p.Value.X + text.Bounds.Width <= stripLeft + 1,
                        $"subtitle '{text.Text}' right edge {p.Value.X + text.Bounds.Width:F1} crosses strip at {stripLeft:F1}");
                }
            }

            window.Close();
        });
    }

    /// <summary>马赛克卡片横向铺满面板（出血），色块因此拿回原来的宽度。</summary>
    [Fact]
    public void TestTreemapCardBleedsToPanelEdges()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var mosaic = page.GetVisualDescendants().OfType<MosaicView>().FirstOrDefault();
            Assert.NotNull(mosaic);
            var left = mosaic!.TranslatePoint(new Point(0, 0), page)!.Value.X;
            Assert.True(left <= 2, $"mosaic left = {left:F1}");
            Assert.True(left + mosaic.Bounds.Width >= Metrics.PanelWidth - 2,
                $"mosaic right = {left + mosaic.Bounds.Width:F1}");
            // 宽度必须够让 HabitGarden 这种方块继续显示标签（实测门槛 348）。
            Assert.True(mosaic.Bounds.Width >= 348,
                $"mosaic width = {mosaic.Bounds.Width:F1} (needs >= 348 for tile labels)");

            window.Close();
        });
    }

    /// <summary>设置页的 --data InfoBar 必须折行落在卡片内，不能横向越界。</summary>
    [Fact]
    public void TestSettingsInfoBarWrapsInsideCard()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            var bar = page.GetVisualDescendants().OfType<InfoBar>().FirstOrDefault();
            Assert.NotNull(bar);
            var right = bar!.TranslatePoint(new Point(0, 0), page)!.Value.X + bar.Bounds.Width;
            Assert.True(right <= Metrics.PanelWidth - Metrics.PagePadding + 1,
                $"InfoBar right edge {right:F1} exceeds the page margin");

            // 正文是多行（折过），不是一行超长。
            var body = bar.GetVisualDescendants().OfType<TextBlock>()
                .First(t => (t.Text?.Length ?? 0) > 40);
            Assert.True(body.Bounds.Height > body.FontSize * 1.4,
                $"InfoBar text should wrap, height={body.Bounds.Height:F1}");

            window.Close();
        });
    }

    /// <summary>
    /// 额度重置行：按钮右对齐且完整落在卡片内；禁用的下拉必须保持普通控件底色
    /// （不能画成一块死灰，那样看起来像控件坏了）。
    /// </summary>
    [Fact]
    public void TestQuotaResetRowButtonsFitAndPickersKeepNormalFill()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            var rows = page.GetVisualDescendants().OfType<QuotaResetRow>().ToList();
            Assert.NotEmpty(rows);
            var row = rows[0];

            var pickers = row.GetVisualDescendants().OfType<ComboBox>().ToList();
            Assert.NotEmpty(pickers);
            // 禁用态必须用和启用态**同一个底**：只有字变淡，控件本身不该变成另一种外观
            // （深色下若用 ControlFill #303030，禁用控件会比启用态 #1A1A1A 还亮）。
            var surface = Palette.ControlSurfaceColor;
            foreach (var picker in pickers)
            {
                Assert.False(picker.IsEnabled, "quota pickers are disabled when subscriptions cannot be edited");
                var presenter = picker.GetVisualDescendants()
                    .OfType<Avalonia.Controls.Presenters.ContentPresenter>().FirstOrDefault();
                if (presenter?.Background is ISolidColorBrush b) Assert.Equal(surface, b.Color);
                // 主题资源必须被覆盖，否则模板里那层 #33000000 会盖上来。
                Assert.Equal(surface, ((ISolidColorBrush)Application.Current!.FindResource(
                    "ComboBoxBackgroundDisabled")!).Color);
                // 禁用底不能比启用底更亮（否则禁用比启用还抢眼）。
                Assert.True(Palette.Luminance(surface) <= Palette.Luminance(Palette.CardColor) + 0.001,
                    "disabled control surface should not be brighter than the card");
            }

            foreach (var control in row.GetVisualDescendants().OfType<Control>()
                         .Where(c => c is Button || c is Border { IsEnabled: false, Child: TextBlock }))
            {
                var p = control.TranslatePoint(new Point(0, 0), page);
                if (p is null) continue;
                Assert.True(p.Value.X + control.Bounds.Width <= Metrics.PanelWidth - Metrics.PagePadding + 0.5,
                    $"control right edge {p.Value.X + control.Bounds.Width:F1} exceeds the card");
            }

            window.Close();
        });
    }

    /// <summary>订阅行：Apply / Reset / Edit 三个按钮全部完整落在卡片内。</summary>
    [Fact]
    public void TestSubscriptionRowButtonsAreNotClipped()
    {
        OnUi(() =>
        {
            // 带着 anchor 打开设置页，保证订阅行处于展示形态（含 Edit 按钮）。
            var page = new SettingsPage(NewServices(), null, "codex", snapshot: false, onBack: () => { });
            var window = Show(page);

            var rows = page.GetVisualDescendants().OfType<SubscriptionSettingsRow>().ToList();
            Assert.NotEmpty(rows);

            foreach (var row in rows)
            {
                var buttons = row.GetVisualDescendants().OfType<Control>()
                    .Where(c => c is Button || c is Border { IsEnabled: false, Child: TextBlock })
                    .ToList();
                foreach (var button in buttons)
                {
                    var p = button.TranslatePoint(new Point(0, 0), page);
                    if (p is null) continue;
                    var right = p.Value.X + button.Bounds.Width;
                    var label = (button as ContentControl)?.Content?.ToString()
                                ?? (button as Border)?.Child?.GetType().Name ?? "?";
                    Assert.True(right <= Metrics.PanelWidth - Metrics.PagePadding + 0.5,
                        $"button '{label}' right edge {right:F1} exceeds the card content area");
                }
            }

            window.Close();
        });
    }

    /// <summary>
    /// 续费日的步进控件要「正常尺寸、看得清」：两个 30×30 的按钮、箭头不小于 12px、
    /// 启用时箭头用次要色（卡片上 6.6:1），不是原来 26×22 + 9px 小箭头 + 低对比度的组合。
    /// </summary>
    [Fact]
    public void TestSubscriptionStepperIsVisibleAndFullSize()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, "codex", snapshot: false, onBack: () => { });
            var window = Show(page);

            var row = page.GetVisualDescendants().OfType<SubscriptionSettingsRow>().First();
            // 步进按钮是 30×30 的可点区域（原来的箭头是 26×22 且几乎看不见）。
            var spins = row.GetVisualDescendants().OfType<Clickable>()
                .Where(c => Math.Abs(c.Bounds.Width - 30) < 0.5 && Math.Abs(c.Bounds.Height - 30) < 0.5)
                .ToList();
            Assert.True(spins.Count >= 2, $"expected two 30x30 step buttons, found {spins.Count}");

            foreach (var spin in spins)
            {
                // 有实底 + 描边，不是透明的一小块。
                Assert.NotNull(spin.Background);
                Assert.IsType<SolidColorBrush>(spin.Background);
                Assert.Equal(1, spin.BorderThickness.Left);
                // 箭头本身不小于 12px。
                var glyph = spin.GetVisualDescendants().OfType<Control>()
                    .FirstOrDefault(c => c.Bounds.Width > 0 && c.Bounds.Height > 0);
                Assert.NotNull(glyph);
                Assert.True(glyph!.Bounds.Width >= 10 && glyph.Bounds.Height >= 10,
                    $"arrow glyph is {glyph.Bounds.Width:F1}x{glyph.Bounds.Height:F1}, too small to see");
            }

            window.Close();
        });
    }

    /// <summary>
    /// 订阅行的禁用态规则（对齐 macOS 的 SubscriptionSettingsRow）：
    /// Apply / Reset 需要「可以编辑」，Edit 只是打开本地编辑表单所以**始终可用**。
    /// </summary>
    [Fact]
    public void TestSubscriptionButtonsFollowMacEnabledRules()
    {
        OnUi(() =>
        {
            // --data 覆盖 ⇒ CanEditSubscriptions = false（和 Mac 的 dataOverride != nil 一样）。
            var page = new SettingsPage(NewServices(), null, "codex", snapshot: false, onBack: () => { });
            var window = Show(page);

            var row = page.GetVisualDescendants().OfType<SubscriptionSettingsRow>().First();
            Control? Find(string label) => row.GetVisualDescendants().OfType<Control>()
                .FirstOrDefault(c =>
                    (c is ContentControl cc && Equals(cc.Content, label)) ||
                    (c is Border { Child: TextBlock tb } && tb.Text == label));

            // Edit 永远可用，而且用的是启用态样式（真正的 Button，不是灰掉的静态 Border）。
            var edit = Find(L10n.Tr("settings.edit"));
            Assert.NotNull(edit);
            Assert.IsType<Button>(edit);
            Assert.True(edit!.IsEnabled, "Edit only opens the local form, so it must stay enabled");
            Assert.Equal(Palette.ForegroundColor, ((ISolidColorBrush)((Button)edit).Foreground!).Color);

            // Apply / Reset 写配置，在不能编辑时是禁用外观。
            foreach (var label in new[] { L10n.Tr("common.apply"), L10n.Tr("common.reset") })
            {
                var button = Find(label);
                Assert.NotNull(button);
                Assert.False(button!.IsEnabled, $"'{label}' must be disabled when subscriptions can't be edited");
            }

            window.Close();
        });
    }

    /// <summary>
    /// 下拉里显示的「当前值」必须读得出：启用时是正文色，禁用时也只用次要色
    /// （卡片上 6.6:1），不能淡成「控件坏了」的 3:1 灰。
    /// </summary>
    [Fact]
    public void TestPickerShowsItsValueInReadableColour()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            var combos = page.GetVisualDescendants().OfType<ComboBox>().ToList();
            Assert.NotEmpty(combos);
            foreach (var combo in combos)
            {
                var brush = combo.Foreground as ISolidColorBrush;
                Assert.NotNull(brush);
                var color = brush!.Color;
                // 只允许两种：正文色（启用）或次要色（禁用）。
                Assert.True(color == Palette.ForegroundColor || color == Palette.SecondaryColor,
                    $"combo '{combo.SelectedItem}' uses {color}, expected primary or secondary text");
                // 两种都能在卡片上读（≥ 4.5:1）。
                Assert.True(Palette.Contrast(color, Palette.CardColor) >= 4.5,
                    $"combo text {color} has contrast {Palette.Contrast(color, Palette.CardColor):F2}:1");
            }

            window.Close();
        });
    }

    /// <summary>
    /// 长套餐名不能压到右侧金额上。月费在说明行里，金额和倍数各自右对齐、各行对齐，中间没有单独的「·」。
    /// </summary>
    [Fact]
    public void TestSubscriptionRowLongPlanDoesNotOverlapAmount()
    {
        OnUi(() =>
        {
            var services = NewServices();
            services.SubscriptionCardExpanded = true;
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var plan = page.GetVisualDescendants().OfType<TextBlock>()
                .First(t => t.Text == "Google AI Ultra + Google AI Pro");
            Assert.DoesNotContain("/mo", plan.Text, StringComparison.Ordinal);
            var planPos = plan.TranslatePoint(new Point(0, 0), page)!.Value;
            var planRight = planPos.X + plan.Bounds.Width;

            // 订阅金额设了固定 Width；项目行的金额没有，不能混进来比右缘。
            var amounts = page.GetVisualDescendants().OfType<TextBlock>()
                .Where(t => t.FontSize == 14 && t.FontWeight == FontWeight.Medium &&
                            !double.IsNaN(t.Width) && t.Width > 0 &&
                            t.Text != null && t.Text.StartsWith('$'))
                .ToList();
            Assert.True(amounts.Count >= 2, $"expected aligned subscription amounts, found {amounts.Count}");

            var amount = amounts
                .Select(a => (Block: a, Pos: a.TranslatePoint(new Point(0, 0), page)!.Value))
                .First(t => Math.Abs(t.Pos.Y - planPos.Y) < 14);
            Assert.True(planRight <= amount.Pos.X + 0.5,
                $"plan right {planRight:F1} overlaps amount at {amount.Pos.X:F1} ('{amount.Block.Text}')");
            var amountMeasured = Kanjo.App.Type.MeasureWidth(amount.Block.Text!, 14, FontWeight.Medium,
                Kanjo.App.Type.Rounded);
            Assert.True(amount.Block.Bounds.Width + 0.5 >= amountMeasured,
                $"amount '{amount.Block.Text}' clipped");
            var amountRight = amount.Pos.X + amount.Block.Bounds.Width;
            Assert.True(amountRight <= Metrics.PanelWidth - Metrics.PagePadding + 1,
                $"amount right {amountRight:F1} leaves the panel");

            var captions = page.GetVisualDescendants().OfType<TextBlock>()
                .Where(t => t.Text?.Contains("/mo", StringComparison.Ordinal) == true)
                .Select(t => (Block: t, Pos: t.TranslatePoint(new Point(0, 0), page)!.Value))
                .ToList();
            Assert.Contains(captions, t => t.Pos.Y > planPos.Y && t.Block.Text!.Contains("$269.98/mo",
                StringComparison.Ordinal));
            AssertSubscriptionCaptionDoesNotOrphan(page);

            var loneDots = page.GetVisualDescendants().OfType<TextBlock>().Where(t => t.Text == "·").ToList();
            Assert.Empty(loneDots);

            static double Right(TextBlock block, Control root)
            {
                var p = block.TranslatePoint(new Point(block.Bounds.Width, 0), root)!.Value;
                return p.X;
            }

            var amountRights = amounts.Select(a => Right(a, page)).ToList();
            Assert.True(amountRights.Max() - amountRights.Min() < 1.5,
                $"amount right edges {amountRights.Min():F1}…{amountRights.Max():F1}");

            var multiples = page.GetVisualDescendants().OfType<TextBlock>()
                .Where(t => t.FontSize == 13 && t.FontWeight == FontWeight.Medium &&
                            t.Text != null && (t.Text.EndsWith('×') || t.Text == "—"))
                .ToList();
            Assert.Equal(amounts.Count, multiples.Count);
            var multipleRights = multiples.Select(m => Right(m, page)).ToList();
            Assert.True(multipleRights.Max() - multipleRights.Min() < 1.5,
                $"multiplier right edges {multipleRights.Min():F1}…{multipleRights.Max():F1}");
            Assert.True(multipleRights.Min() > amountRights.Max() - 0.5,
                "multiplier column should sit to the right of the amounts");

            window.Close();
        });
    }

    /// <summary>法文短标签也必须在一行里完整可见；放不下时滚动范围要盖住最后一个，选中项在视口内。</summary>
    [Fact]
    public void TestOverviewRangePillsNotClippedInFrench()
    {
        OnUi(() =>
        {
            var settings = AppSettings.InMemory();
            settings.Set(SettingsKeys.AppLanguage, "fr");
            settings.Set(SettingsKeys.TimeRange, "billingCycle");
            L10n.Store = settings;
            L10n.ResetCache();
            var services = new AppServices(settings, ["--snapshot", "--data", FixturePath], TempDir());
            services.LoadQuietly();
            var page = new OverviewPage(services, null, snapshot: false);
            var window = Show(page);

            var picker = page.GetVisualDescendants().OfType<RangePicker>().First();
            var chips = picker.GetVisualDescendants().OfType<Border>()
                .Where(b => b.Child is TextBlock { Text.Length: > 0 } tb && tb.FontSize == 11)
                .ToList();
            Assert.Equal(TimeRanges.All.Count, chips.Count);

            var ys = chips.Select(c => c.Bounds.Y).ToList();
            Assert.True(ys.Max() - ys.Min() < 1, "French pills wrapped onto a second row");

            foreach (var chip in chips)
            {
                var text = (TextBlock)chip.Child!;
                Assert.Equal(TextWrapping.NoWrap, text.TextWrapping);
                var measured = Kanjo.App.Type.MeasureWidth(text.Text!, 11, text.FontWeight);
                Assert.True(text.Bounds.Width + 0.5 >= measured,
                    $"pill '{text.Text}' text width {text.Bounds.Width:F1} < measured {measured:F1}");
                Assert.True(chip.Bounds.Right <= (picker.PillsScroller?.Extent.Width ?? 0) + 1,
                    $"pill '{text.Text}' sits outside the scroll extent");
            }

            var scroller = picker.PillsScroller!;
            var maxScroll = Math.Max(0, scroller.Extent.Width - scroller.Viewport.Width);
            var lastRight = chips[^1].Bounds.Right;
            Assert.True(lastRight <= scroller.Viewport.Width + maxScroll + 1,
                $"last pill right {lastRight:F1} unreachable (viewport {scroller.Viewport.Width:F1} + scroll {maxScroll:F1})");

            var selected = chips.First(c => ((TextBlock)c.Child!).FontWeight == FontWeight.SemiBold);
            var offset = scroller.Offset.X;
            var viewRight = offset + scroller.Viewport.Width;
            Assert.True(selected.Bounds.X >= offset - 1 && selected.Bounds.Right <= viewRight + 1,
                $"selected '{((TextBlock)selected.Child!).Text}' x {selected.Bounds.X:F1}–{selected.Bounds.Right:F1} " +
                $"outside view {offset:F1}–{viewRight:F1}");

            window.Close();
        });
    }

    /// <summary>图例每一项按内容排开，文字的排列宽度不小于期望宽度（不裁切）。</summary>
    [Fact]
    public void TestOverviewLegendLabelsAreNotClipped()
    {
        OnUi(() =>
        {
            var page = new OverviewPage(NewServices(), null, snapshot: false);
            var window = Show(page);

            var legend = page.GetVisualDescendants().OfType<AgentLegend>().First();
            var chips = legend.Children.OfType<Control>().ToList();
            Assert.NotEmpty(chips);
            AssertLegendSpacing(chips);

            foreach (var row in chips.GroupBy(c => Math.Round(c.Bounds.Y)))
            {
                var top = row.Min(c => c.Bounds.Y);
                Assert.All(row, c => Assert.True(Math.Abs(c.Bounds.Y - top) < 0.5,
                    "legend items on one row are not vertically aligned"));
            }

            foreach (var chip in chips)
            {
                var label = chip.GetVisualDescendants().OfType<TextBlock>().First();
                Assert.Equal(TextWrapping.NoWrap, label.TextWrapping);
                Assert.Equal(TextTrimming.None, label.TextTrimming);
                Assert.True(label.Bounds.Width >= label.DesiredSize.Width - 0.5,
                    $"legend '{label.Text}' arranged {label.Bounds.Width:F1} < desired {label.DesiredSize.Width:F1}");
            }

            window.Close();
        });
    }

    /// <summary>色点到文字约 4pt，相邻项约 10pt。</summary>
    private static void AssertLegendSpacing(IReadOnlyList<Control> chips)
    {
        double? itemGap = null;
        for (var i = 0; i < chips.Count; i++)
        {
            var dot = chips[i].GetVisualDescendants().OfType<Avalonia.Controls.Shapes.Ellipse>().First();
            var label = chips[i].GetVisualDescendants().OfType<TextBlock>().First();
            var dotToLabel = label.Bounds.X - (dot.Bounds.X + dot.Bounds.Width);
            Assert.InRange(dotToLabel, 3.0, 5.5);
            if (i + 1 < chips.Count && Math.Abs(chips[i + 1].Bounds.Y - chips[i].Bounds.Y) < 1)
            {
                itemGap = chips[i + 1].Bounds.X - chips[i].Bounds.Right;
                Assert.InRange(itemGap.Value, 8.0, 12.0);
            }
        }
        Assert.NotNull(itemGap);
    }

    /// <summary>
    /// 「$269.98/mo · Last 30 days · set renewal day for exact cycle」只能在「 · 」处断行，
    /// 不能把 cycle 一个词单独留在下一行。
    /// </summary>
    private static void AssertSubscriptionCaptionDoesNotOrphan(Control page)
    {
        const string caption = "$269.98/mo · Last 30 days · set renewal day for exact cycle";
        var segments = caption.Split(" · ");
        var blocks = page.GetVisualDescendants().OfType<TextBlock>()
            .Select(block => (Block: block, Y: block.TranslatePoint(new Point(0, 0), page)?.Y ?? 0))
            .ToList();
        var headY = blocks.Where(t => t.Block.Text?.Contains("$269.98/mo", StringComparison.Ordinal) == true)
            .Select(t => t.Y)
            .DefaultIfEmpty(double.NaN)
            .Min();
        Assert.True(double.IsFinite(headY), "missing $269.98/mo caption");

        var lines = new List<string>();
        foreach (var (block, y) in blocks.Where(t => Math.Abs(t.Y - headY) < 36).OrderBy(t => t.Y))
        {
            var text = block.Text ?? "";
            if (text.Length == 0 || !caption.Contains(text, StringComparison.Ordinal)) continue;
            if (block.TextLayout is { TextLines.Count: > 0 } layout)
            {
                foreach (var line in layout.TextLines)
                {
                    var start = Math.Clamp(line.FirstTextSourceIndex, 0, text.Length);
                    var len = Math.Clamp(line.Length, 0, text.Length - start);
                    var piece = text.Substring(start, len).Trim();
                    if (piece.Length > 0) lines.Add(piece);
                }
            }
            else
            {
                lines.Add(text.Trim());
            }
        }

        Assert.NotEmpty(lines);
        Assert.DoesNotContain(lines, line => line == "cycle");
        foreach (var line in lines)
        {
            foreach (var part in line.Split(" · ", StringSplitOptions.RemoveEmptyEntries))
                Assert.Contains(segments, segment => segment == part);
        }
        Assert.Equal(caption, string.Join(" · ", lines));
    }
}
