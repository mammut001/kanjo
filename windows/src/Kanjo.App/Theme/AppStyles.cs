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
        // 禁用态用和启用态**同一个底**（Palette.ControlSurfaceColor），只有文字与描边变淡。
        // Mac 上禁用就是这个观感：控件还在，只是不能点。若用 ControlFill（比启用底更深/更浅的
        // 一层），深色下禁用控件会比启用的还亮，反而更抢眼。
        app.Resources["ComboBoxBackgroundDisabled"] = new SolidColorBrush(Palette.ControlSurfaceColor);
        app.Resources["ComboBoxBorderBrushDisabled"] = Palette.CardBorder;
        app.Resources["ComboBoxForegroundDisabled"] = Palette.Disabled;
        app.Resources["TextControlBackgroundDisabled"] = new SolidColorBrush(Palette.ControlSurfaceColor);
        app.Resources["TextControlBorderBrushDisabled"] = Palette.CardBorder;
        app.Resources["TextControlForegroundDisabled"] = Palette.Disabled;
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
