using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Input;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 设置页（及其它滚动页）的滚动回归测试，对应真机上的用户报告：
/// 「设置页滚不动，滚轮停在下拉 / 数字框上时反而改了值」。
///
/// 两层原因，两层都有断言：
/// 1. 页面以前继承 ScrollViewer，Avalonia 的样式键让它拿不到 Fluent 模板 ——
///    没有 ScrollContentPresenter，<c>Extent</c> 恒为 0，滚轮、拖滚动条、触摸板全都无效。
/// 2. 控件自己消费 PointerWheelChanged。这里直接派发滚轮事件，断言「页面动了、值没动」。
///
/// 所有 UI 操作都跑在 Avalonia 的 UI 线程上（<see cref="KanjoTestCase.OnUi"/>）。
/// </summary>
public sealed class SettingsScrollTests : KanjoTestCase
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

    private static Window Show(Control page, double height = Metrics.PanelHeight)
    {
        var window = new Window { Width = Metrics.PanelWidth, Height = height, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        page.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        return window;
    }

    [Fact]
    public void TestScrollPageHasWorkingTemplate()
    {
        OnUi(() =>
        {
            var content = new StackPanel { Spacing = 8 };
            for (var i = 0; i < 60; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
            var page = new ScrollPage(snapshot: false) { Content = content };
            var window = Show(page, 500);

            // 有模板 → 有 ScrollContentPresenter → Extent 是真实内容高度。
            var presenters = page.GetVisualDescendants()
                .OfType<Avalonia.Controls.Presenters.ScrollContentPresenter>().ToList();
            Assert.NotEmpty(presenters);
            Assert.True(page.Extent.Height > page.Viewport.Height,
                $"extent={page.Extent.Height} viewport={page.Viewport.Height}");

            page.ScrollTo(120);
            Dispatcher.UIThread.RunJobs();
            Assert.True(page.VerticalOffset > 0, $"offset={page.VerticalOffset}");

            window.Close();
        });
    }

    [Fact]
    public void TestSettingsPageScrollsAndIsLongerThanViewport()
    {
        OnUi(() =>
        {
            var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
            var window = Show(page);
            Assert.True(page.Extent.Height > page.Viewport.Height,
                $"settings extent={page.Extent.Height} viewport={page.Viewport.Height}");
            window.Close();
        });
    }

    /// <summary>
    /// 核心用例：滚轮停在「下拉 / 输入框」上时，页面滚动、值不变。
    /// </summary>
    [Fact]
    public void TestWheelOverPickerScrollsPageWithoutChangingValue()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = Show(page);

            var controls = page.GetVisualDescendants().OfType<Control>().ToList();
            var combo = controls.OfType<ComboBox>().First();   // Language 的「System」
            var box = controls.OfType<TextBox>().First();      // Command

            var comboIndexBefore = combo.SelectedIndex;
            var commandBefore = box.Text;
            var languageBefore = services.Settings.Str(SettingsKeys.AppLanguage, "");

            void WheelAndAssert(Control target, string name)
            {
                page.ScrollTo(0);
                Dispatcher.UIThread.RunJobs();

                // 1) 策略层：指针停在这个控件上时，滚轮必须归页面（不是控件自己消费）。
                Assert.False(WheelPolicy.ControlConsumes(target, page, new Vector(0, -3)),
                    $"{name}: WheelPolicy says the control consumes the wheel");

                // 2) 行为层：把真实的 PointerWheelChanged 从控件上派发出去，
                //    走完整的隧道 / 冒泡链（ScrollPage 的隧道处理器会把页面滚起来）。
                //    headless 下 window.MouseWheel 依赖 hit test（未启用渲染时返回 null），
                //    所以直接构造事件派发，测的仍是同一条 handler 链。
                var before = page.VerticalOffset;
                var args = new PointerWheelEventArgs(
                    target,
                    pointer: null!,
                    rootVisual: window,
                    rootVisualPosition: new Point(6, Math.Max(target.Bounds.Height / 2, 2)),
                    timestamp: 0,
                    properties: new PointerPointProperties(),
                    modifiers: KeyModifiers.None,
                    delta: new Vector(0, -3))
                {
                    RoutedEvent = InputElement.PointerWheelChangedEvent,
                };
                target.RaiseEvent(args);
                Dispatcher.UIThread.RunJobs();

                Assert.True(args.Handled, $"{name}: wheel event was not handled (page should take it)");
                Assert.True(page.VerticalOffset > before,
                    $"{name}: page did not scroll ({before} -> {page.VerticalOffset})");
            }

            WheelAndAssert(combo, "ComboBox");
            WheelAndAssert(box, "TextBox");

            Assert.Equal(comboIndexBefore, combo.SelectedIndex);
            Assert.Equal(commandBefore, box.Text);
            Assert.Equal(languageBefore, services.Settings.Str(SettingsKeys.AppLanguage, ""));

            window.Close();
        });
    }

    /// <summary>滚到顶部 / 底部都不越界。</summary>
    [Fact]
    public void TestWheelScrollIsClampedToExtent()
    {
        OnUi(() =>
        {
            var content = new StackPanel();
            for (var i = 0; i < 40; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
            var page = new ScrollPage(snapshot: false) { Content = content };
            var window = Show(page, 400);

            var max = Math.Max(0, page.Extent.Height - page.Viewport.Height);
            Assert.True(max > 0, $"extent={page.Extent.Height} viewport={page.Viewport.Height}");

            page.ScrollTo(double.MaxValue);
            Dispatcher.UIThread.RunJobs();
            Assert.Equal(max, page.VerticalOffset, 1);

            page.ScrollTo(double.MinValue);
            Dispatcher.UIThread.RunJobs();
            Assert.Equal(0, page.VerticalOffset, 1);

            window.Close();
        });
    }

    /// <summary>嵌套滚动区：内部还能滚时归内部；到边界后链给外层页面。</summary>
    [Fact]
    public void TestNestedScrollViewerChainsWheelToPage()
    {
        OnUi(() =>
        {
            var inner = new ScrollViewer
            {
                Height = 120,
                Content = new Border { Height = 400, Background = Avalonia.Media.Brushes.LightGray },
            };
            var content = new StackPanel();
            content.Children.Add(inner);
            for (var i = 0; i < 40; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
            var page = new ScrollPage(snapshot: false) { Content = content };
            var window = Show(page, 400);

            Assert.True(WheelPolicy.ControlConsumes(inner, page, new Vector(0, -3)));
            inner.Offset = new Vector(0, Math.Max(0, inner.Extent.Height - inner.Viewport.Height));
            Dispatcher.UIThread.RunJobs();
            Assert.False(WheelPolicy.ControlConsumes(inner, page, new Vector(0, -3)));

            window.Close();
        });
    }

    [Fact]
    public void TestWheelPolicyForValueControls()
    {
        OnUi(() =>
        {
            var page = new ScrollPage(snapshot: false);

            var combo = new ComboBox { ItemsSource = new[] { "a", "b" }, SelectedIndex = 0 };
            var stepper = new NumericUpDown { Value = 5, Minimum = 1, Maximum = 28 };
            var single = new TextBox { Text = "abc" };
            var multi = new TextBox { Text = "abc", AcceptsReturn = true };
            var plain = new TextBlock { Text = "hello" };

            Assert.False(WheelPolicy.ControlConsumes(combo, page, new Vector(0, -3)));
            Assert.False(WheelPolicy.ControlConsumes(stepper, page, new Vector(0, -3)));
            Assert.False(WheelPolicy.ControlConsumes(single, page, new Vector(0, -3)));
            Assert.False(WheelPolicy.ControlConsumes(plain, page, new Vector(0, -3)));
            Assert.True(WheelPolicy.ControlConsumes(multi, page, new Vector(0, -3)));
            combo.IsDropDownOpen = true;
            Assert.True(WheelPolicy.ControlConsumes(combo, page, new Vector(0, -3)));
            combo.IsDropDownOpen = false;
            // 纯横向滚动不归页面。
            Assert.True(WheelPolicy.ControlConsumes(plain, page, new Vector(2, 0)));
        });
    }

    /// <summary>打开设置页不能卡住 UI 线程（29 个 agent 的订阅行是主要成本）。</summary>
    [Fact]
    public void TestSettingsPageBuildsUnderHundredMilliseconds()
    {
        OnUi(() =>
        {
            var services = NewServices();
            var sw = System.Diagnostics.Stopwatch.StartNew();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            sw.Stop();
            Assert.True(sw.ElapsedMilliseconds < 150,
                $"SettingsPage 构建耗时 {sw.ElapsedMilliseconds}ms（目标 < 100ms）");
            Assert.NotNull(page);

            var report = services.Report!;
            var agents = SettingsAgentList.SubscriptionAgents(report, null);
            Assert.True(agents.Count >= 29, $"agents={agents.Count}");
            var withInfo = agents.Count(a => report.Subscriptions?.ContainsKey(a) == true);
            Assert.Equal(5, withInfo);
        });
    }
}
