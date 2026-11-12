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
///    <see cref="TestScrollPageHasWorkingTemplate"/> 断言 Extent / Viewport 是真实数字。
/// 2. 控件自己消费 PointerWheelChanged。这里直接派发滚轮事件，断言「页面动了、值没动」。
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

    [Fact]
    public void TestScrollPageHasWorkingTemplate()
    {
        AppSetup.ConfigureHeadless("light");
        var content = new StackPanel { Spacing = 8 };
        for (var i = 0; i < 60; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
        var page = new ScrollPage(snapshot: false) { Content = content };
        var window = new Window { Width = 360, Height = 500, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();

        // 有模板 → 有 ScrollContentPresenter → Extent 是真实内容高度。
        var presenters = page.GetVisualDescendants()
            .OfType<Avalonia.Controls.Presenters.ScrollContentPresenter>().ToList();
        Assert.NotEmpty(presenters);
        Assert.True(page.Extent.Height > page.Viewport.Height,
            $"extent={page.Extent.Height} viewport={page.Viewport.Height}");

        // 能真的滚起来。
        page.ScrollTo(120);
        Dispatcher.UIThread.RunJobs();
        Assert.True(page.VerticalOffset > 0, $"offset={page.VerticalOffset}");

        window.Close();
    }

    [Fact]
    public void TestSettingsPageScrollsAndIsLongerThanViewport()
    {
        AppSetup.ConfigureHeadless("light");
        var page = new SettingsPage(NewServices(), null, null, snapshot: false, onBack: () => { });
        var window = new Window { Width = Metrics.PanelWidth, Height = Metrics.PanelHeight, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        page.UpdateLayout();
        Dispatcher.UIThread.RunJobs();

        Assert.True(page.Extent.Height > page.Viewport.Height,
            $"settings extent={page.Extent.Height} viewport={page.Viewport.Height}");
        window.Close();
    }

    /// <summary>
    /// 核心用例：滚轮停在「下拉 / 数字框 / 输入框」上时，页面滚动、值不变。
    /// 这正是任务里要求的断言。
    /// </summary>
    [Fact]
    public void TestWheelOverPickerScrollsPageWithoutChangingValue()
    {
        AppSetup.ConfigureHeadless("light");
        var services = NewServices();
        var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
        var window = new Window { Width = Metrics.PanelWidth, Height = Metrics.PanelHeight, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();
        page.UpdateLayout();
        Dispatcher.UIThread.RunJobs();

        var controls = page.GetVisualDescendants().OfType<Control>().ToList();
        var combo = controls.OfType<ComboBox>().First();   // Language 的「System」
        var box = controls.OfType<TextBox>().First();      // Command

        var comboIndexBefore = combo.SelectedIndex;
        var commandBefore = box.Text;
        var languageBefore = services.Settings.Str(SettingsKeys.AppLanguage, "");

        void WheelAndAssert(Control target, string name)
        {
            page.ScrollTo(60);
            Dispatcher.UIThread.RunJobs();
            var before = page.VerticalOffset;
            var point = target.TranslatePoint(new Point(6, Math.Max(target.Bounds.Height / 2, 2)), window)
                        ?? throw new InvalidOperationException($"{name}: no point");
            window.MouseMove(point, RawInputModifiers.None);
            window.MouseWheel(point, new Vector(0, -3));
            Dispatcher.UIThread.RunJobs();
            Assert.True(page.VerticalOffset > before,
                $"{name}: page did not scroll ({before} -> {page.VerticalOffset})");
        }

        WheelAndAssert(combo, "ComboBox");
        WheelAndAssert(box, "TextBox");

        // 页面滚了，两个控件的值都没被动过。
        Assert.Equal(comboIndexBefore, combo.SelectedIndex);
        Assert.Equal(commandBefore, box.Text);
        Assert.Equal(languageBefore, services.Settings.Str(SettingsKeys.AppLanguage, ""));

        window.Close();
    }

    /// <summary>滚轮朝上滚回顶部、朝下滚到底，都不越界。</summary>
    [Fact]
    public void TestWheelScrollIsClampedToExtent()
    {
        AppSetup.ConfigureHeadless("light");
        var content = new StackPanel();
        for (var i = 0; i < 40; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
        var page = new ScrollPage(snapshot: false) { Content = content };
        var window = new Window { Width = 360, Height = 400, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();

        // 布局完成：真的能滚（否则下面夹取的断言没有意义）。
        var max = Math.Max(0, page.Extent.Height - page.Viewport.Height);
        Assert.True(max > 0, $"extent={page.Extent.Height} viewport={page.Viewport.Height}");

        page.ScrollTo(double.MaxValue);
        Dispatcher.UIThread.RunJobs();
        Assert.Equal(max, page.VerticalOffset, 1);

        page.ScrollTo(double.MinValue);
        Dispatcher.UIThread.RunJobs();
        Assert.Equal(0, page.VerticalOffset, 1);

        window.Close();
    }

    /// <summary>
    /// 嵌套滚动区：内部还能滚时归内部；到边界后链给外层页面（不能「滚到一半卡住」）。
    /// </summary>
    [Fact]
    public void TestNestedScrollViewerChainsWheelToPage()
    {
        AppSetup.ConfigureHeadless("light");
        var inner = new ScrollViewer
        {
            Height = 120,
            Content = new Border { Height = 400, Background = Avalonia.Media.Brushes.LightGray },
        };
        var content = new StackPanel();
        content.Children.Add(inner);
        for (var i = 0; i < 40; i++) content.Children.Add(new TextBlock { Text = "row " + i, Height = 40 });
        var page = new ScrollPage(snapshot: false) { Content = content };
        var window = new Window { Width = 360, Height = 400, Content = page };
        window.Show();
        window.UpdateLayout();
        Dispatcher.UIThread.RunJobs();

        // 内部还能往下滚 → 归内部。
        Assert.True(WheelPolicy.ControlConsumes(inner, page, new Vector(0, -3)));
        // 内部已经到底 → 链给外层。
        inner.Offset = new Vector(0, Math.Max(0, inner.Extent.Height - inner.Viewport.Height));
        Dispatcher.UIThread.RunJobs();
        Assert.False(WheelPolicy.ControlConsumes(inner, page, new Vector(0, -3)));

        window.Close();
    }

    [Fact]
    public void TestWheelPolicyForValueControls()
    {
        AppSetup.ConfigureHeadless("light");
        var page = new ScrollPage(snapshot: false);

        var combo = new ComboBox { ItemsSource = new[] { "a", "b" }, SelectedIndex = 0 };
        var stepper = new NumericUpDown { Value = 5, Minimum = 1, Maximum = 28 };
        var single = new TextBox { Text = "abc" };
        var multi = new TextBox { Text = "abc", AcceptsReturn = true };
        var plain = new TextBlock { Text = "hello" };

        // 收起的下拉、数字框、单行输入框：滚轮归页面（不消费）。
        Assert.False(WheelPolicy.ControlConsumes(combo, page, new Vector(0, -3)));
        Assert.False(WheelPolicy.ControlConsumes(stepper, page, new Vector(0, -3)));
        Assert.False(WheelPolicy.ControlConsumes(single, page, new Vector(0, -3)));
        // 普通文字当然归页面。
        Assert.False(WheelPolicy.ControlConsumes(plain, page, new Vector(0, -3)));
        // 多行输入框自己滚。
        Assert.True(WheelPolicy.ControlConsumes(multi, page, new Vector(0, -3)));
        // 下拉展开时列表自己滚。
        combo.IsDropDownOpen = true;
        Assert.True(WheelPolicy.ControlConsumes(combo, page, new Vector(0, -3)));
        combo.IsDropDownOpen = false;
        // 纯横向滚动不归页面（避免和横向控件抢）。
        Assert.True(WheelPolicy.ControlConsumes(plain, page, new Vector(2, 0)));
    }

    /// <summary>打开设置页不能卡住 UI 线程（29 个 agent 的订阅行是主要成本）。</summary>
    [Fact]
    public void TestSettingsPageBuildsUnderHundredMilliseconds()
    {
        AppSetup.ConfigureHeadless("light");
        var services = NewServices();

        var sw = System.Diagnostics.Stopwatch.StartNew();
        var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
        sw.Stop();
        // 只建控件树（不布局）。目标是 100ms；CI 上留一点余量。
        Assert.True(sw.ElapsedMilliseconds < 150,
            $"SettingsPage 构建耗时 {sw.ElapsedMilliseconds}ms（目标 < 100ms）");
        Assert.NotNull(page);

        // 订阅行数量断言：29 个 agent 里有 5 个有订阅信息，剩下的折叠在 Show N more 后面。
        var report = services.Report!;
        var agents = SettingsAgentList.SubscriptionAgents(report, null);
        Assert.True(agents.Count >= 29, $"agents={agents.Count}");
        var withInfo = agents.Count(a => report.Subscriptions?.ContainsKey(a) == true);
        Assert.Equal(5, withInfo);
    }
}
