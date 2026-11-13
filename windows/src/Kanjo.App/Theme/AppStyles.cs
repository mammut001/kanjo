using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Presenters;
using Avalonia.Controls.Primitives;
using Avalonia.Media;
using Avalonia.Styling;

namespace Kanjo.App;

/// <summary>
/// 全局控件样式（Fluent 主题之上的一层）。
///
/// **两个 Application 必须共用这一份**：真实运行的 <see cref="KanjoApplication"/> 和
/// 截图 / 单测用的 <see cref="HeadlessApplication"/>。以前这些样式只加在前者上，
/// 于是快照里的禁用下拉、占位符、圆角全都和真机不一样 —— 看到的问题和实际行为对不上。
/// </summary>
public static class AppStyles
{
    public static void Install(Application app)
    {
        // 全局字体。**不要**在这里写死 Foreground：样式里的画笔是在 Install 那一刻取值的，
        // 之后切换成深色时它会一直停在浅色 #1A1A1A —— 下拉项文字在深色底上就只剩 2:1。
        // 正文色一律由 Ui.Text / Palette 在构造时给出；控件模板里的颜色交给 Fluent 主题按外观走。
        app.Styles.Add(new Style(x => x.OfType<TextBlock>())
        {
            Setters =
            {
                new Setter(TextBlock.FontFamilyProperty, Type.Font),
            },
        });
        app.Styles.Add(new Style(x => x.OfType<Window>())
        {
            Setters = { new Setter(Window.BackgroundProperty, Palette.PanelBackground) },
        });

        // 输入类控件统一 Fluent 的圆角 + 高度（深浅色一致）。
        // 占位符不用原生 Watermark（主题给的是极淡的 tertiary，白卡上约 1.9:1），
        // 由 Ui.TextField 自己画一层 secondary 实色。
        foreach (var style in new[]
                 {
                     InputStyle<TextBox>(), InputStyle<ComboBox>(),
                 })
        {
            app.Styles.Add(style);
        }
        app.Styles.Add(new Style(x => x.OfType<Button>())
        {
            Setters =
            {
                new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(4)),
                new Setter(TemplatedControl.FontSizeProperty, Type.BodySize),
            },
        });

        // 禁用按钮：模板默认是 #CCCCCC 底 + 半透明字（2.7:1），改成我们的禁用色。
        app.Styles.Add(new Style(x => x.OfType<Button>().Class(":disabled").Template()
            .OfType<ContentPresenter>().Name("PART_ContentPresenter"))
        {
            Setters =
            {
                new Setter(ContentPresenter.BackgroundProperty, Palette.DisabledFill),
                new Setter(ContentPresenter.ForegroundProperty, Palette.Disabled),
                new Setter(ContentPresenter.BorderBrushProperty, Palette.DisabledStroke),
            },
        });
        app.Styles.Add(new Style(x => x.OfType<Button>().Class(":disabled"))
        {
            Setters = { new Setter(Visual.OpacityProperty, 1.0) },
        });

        RefreshPaletteResources(app);
    }

    /// <summary>
    /// 上一次真的把外观「画」进了哪个 Application、画的是深色还是浅色。
    ///
    /// 用来避免没必要的重写：同一外观重复设置（启动时 Install + Apply、设置页再点一下相同的值、
    /// 单测里每个用例复位一次）不该再把全局资源刷一遍 —— 每次刷都是向所有 TopLevel
    /// 广播一次「资源变了」。必须连 Application 一起记：headless 单测每一轮 Dispatch 都是新的
    /// Application，它的 Resources 是空的，哪怕外观没变也得重新写进去。
    /// </summary>
    private static WeakReference<Application>? _paintedApp;
    private static bool _paintedDark;

    private static bool NeedsRepaint(Application app, bool dark) =>
        !(_paintedApp?.TryGetTarget(out var painted) == true && ReferenceEquals(painted, app)) ||
        _paintedDark != dark;

    /// <summary>
    /// 禁用控件的主题资源。必须在外观（<see cref="Palette.IsDark"/>）变化后重新调用：
    /// 资源是**按当时的色板取值的画笔**，只在 Install 时写一次的话，深色模式下禁用下拉会
    /// 拿着浅色 #FBFBFB 的底 —— 快照里就是白块。
    ///
    /// 为什么改资源而不是打模板：Fluent 主题的禁用填充 / 描边是半透明黑（<c>#33000000</c>，
    /// 叠在白卡上 ≈ <c>#CCCCCC</c>），看起来像「整块控件坏掉了」，配它自己的灰字只有 2.7:1。
    /// 改资源后禁用态仍是普通控件底 + 3:1 以上的灰字，和 Mac 的观感一致。
    /// </summary>
    public static void RefreshPaletteResources(Application app)
    {
        // 已经写过同一套色板就不重复写：每次写都是一次全局「资源变了」广播，
        // 所有 TopLevel 都要重走一遍逻辑树（见下面的注释）。
        if (!NeedsRepaint(app, Palette.IsDark)) return;
        // 禁用态用和启用态**同一个底**（Palette.ControlSurfaceColor），只有文字与描边变淡。
        // Mac 上禁用就是这个观感：控件还在，只是不能点。若用 ControlFill（比启用底更深/更浅的
        // 一层），深色下禁用控件会比启用的还亮，反而更抢眼。
        //
        // 禁用文字用 Secondary（卡片上 6.6:1 / 背景上 5.9:1）而不是 Disabled（3.1:1）：
        // 下拉里显示的是**当前值**（"Fri"、"16:40"），那是要读的信息，不该淡成「控件坏了」的灰。
        // 真正的禁用按钮（Apply / Reset）走 <see cref="Ui.DisabledButton"/>，仍是明确的灰。
        var values = new Dictionary<object, object?>
        {
            ["ComboBoxBackgroundDisabled"] = new SolidColorBrush(Palette.ControlSurfaceColor),
            ["ComboBoxBorderBrushDisabled"] = Palette.CardBorder,
            ["ComboBoxForegroundDisabled"] = Palette.Secondary,
            ["TextControlBackgroundDisabled"] = new SolidColorBrush(Palette.ControlSurfaceColor),
            ["TextControlBorderBrushDisabled"] = Palette.CardBorder,
            ["TextControlForegroundDisabled"] = Palette.Secondary,
        };

        // **一次性写入**，不要一个个 set_Item。
        //
        // 每个 set_Item 都会 RaiseResourcesChanged，也就是「全局资源变了」——Application 把它
        // 广播给每个 TopLevel，TopLevel 再递归遍历整棵逻辑树（StyledElement.NotifyChildResourcesChanged
        // 先取 count、再按下标取子节点）。连发 6 次就等于把整棵树遍历 6 遍，而中间任何一次通知里
        // 有控件重建模板 / 改子节点，后面那几遍的 `count` 就对不上了 —— CI 上偶发的
        // ArgumentOutOfRangeException 就是 AvaloniaList.get_Item 崩在这条路径上。
        // SetItems 只在写完之后发一次通知，窗口小得多。
        if (app.Resources is ResourceDictionary dictionary) dictionary.SetItems(values);
        else foreach (var (key, value) in values) app.Resources[key] = value;

        // 记账：这次写进去的是哪一套色板。Appearance 靠它跳过没必要的重写（见 NeedsRepaint）。
        _paintedApp = new WeakReference<Application>(app);
        _paintedDark = Palette.IsDark;
    }

    private static Style InputStyle<T>() where T : Control => new(x => x.OfType<T>())
    {
        Setters =
        {
            new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(4)),
            new Setter(TemplatedControl.FontSizeProperty, Type.CaptionSize),
            new Setter(TemplatedControl.MinHeightProperty, 32.0),
        },
    };
}
