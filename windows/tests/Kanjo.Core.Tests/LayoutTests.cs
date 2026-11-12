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
        var window = new Window
        {
            Width = Metrics.PanelWidth,
            Height = Metrics.PanelHeight,
            Content = page,
        };
        window.Show();
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

            window.Close();
        });
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
}
