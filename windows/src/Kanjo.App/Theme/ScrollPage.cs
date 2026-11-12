using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;

namespace Kanjo.App;

/// <summary>
/// 可滚动页面（总览 / 详情 / 桶 / 磁盘 / 设置）的基类。
///
/// 这里修的就是用户报的「设置页滚不动」：这些页面以前直接继承 <see cref="ScrollViewer"/>。
/// Avalonia 用「样式键」决定套哪个 ControlTheme，子类的样式键是子类自己，于是
/// Fluent 主题里 <c>ScrollViewer</c> 的模板（含 ScrollContentPresenter 和两条滚动条）根本没套上 ——
/// 页面只剩一个 ContentPresenter，<c>Extent</c> 永远是 0，滚轮、拖滚动条、触摸板全都无效。
/// 覆写 <see cref="StyleKeyOverride"/> 拿回父类的模板即可。
///
/// 另外还有第二层问题（滚轮被控件吃掉），见 <see cref="WheelPolicy"/>：
/// ComboBox / NumericUpDown / Slider / TextBox 自己会处理 PointerWheelChanged，
/// 指针停在它们上面时滚轮是在改值而不是滚页面。这里在隧道路由里先判断，
/// 不该给控件的滚轮直接滚页面并标记已处理。
/// </summary>
public class ScrollPage : ScrollViewer
{
    /// <summary>一格滚轮的位移（Windows 上是 3 行文本 ≈ 48–56px，这里取 56）。</summary>
    public const double WheelStep = 56;

    /// <summary>等布局完成后要恢复的滚动位置（返回上一页时用）。</summary>
    private double? _pendingOffset;

    public ScrollPage(bool snapshot)
    {
        HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = snapshot ? ScrollBarVisibility.Disabled : ScrollBarVisibility.Auto;
        // 触摸板 / 触摸屏的平移带惯性（Windows 11 的手感）。
        IsScrollInertiaEnabled = true;
        // Fluent 的自动隐藏悬浮滚动条：静止时几乎透明，悬停时展开变宽。
        AllowAutoHide = true;
        Background = Brushes.Transparent;
        // 隧道：比控件自己的处理更早拿到滚轮事件。
        AddHandler(PointerWheelChangedEvent, OnWheelTunneled, RoutingStrategies.Tunnel);
    }

    /// <summary>用父类的样式键，让 Fluent 的 ScrollViewer 模板生效（否则整页不可滚动）。</summary>
    protected override System.Type StyleKeyOverride => typeof(ScrollViewer);

    /// <summary>页面内容本身（不含滚动容器）：快照模式交给面板按整页高度渲染。</summary>
    public Control SnapshotBody
    {
        get
        {
            var content = Content as Control ?? new Panel();
            Content = null;
            return content;
        }
    }

    /// <summary>布局完成后把滚动位置恢复到这里（返回上一页时保持原来的位置）。</summary>
    public void RestoreOffsetLater(double offset)
    {
        _pendingOffset = offset;
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            UpdateLayout();
            if (_pendingOffset is not { } pending) return;
            _pendingOffset = null;
            ScrollTo(pending);
        }, Avalonia.Threading.DispatcherPriority.Loaded);
    }

    /// <summary>当前滚动位置（0 起）。</summary>
    public double VerticalOffset => Offset.Y;

    private void OnWheelTunneled(object? sender, PointerWheelEventArgs e)
    {
        if (e.Handled) return;
        if (e.Source is not Control source) return;
        if (WheelPolicy.ControlConsumes(source, this, e.Delta)) return;
        ScrollByLines(e.Delta.Y);
        e.Handled = true;
    }

    /// <summary>按「格」滚动（正值向下）。</summary>
    public void ScrollByLines(double lines)
    {
        if (Math.Abs(lines) < 0.001) return;
        var max = Math.Max(0, Extent.Height - Viewport.Height);
        ScrollTo(Offset.Y - lines * WheelStep, max);
    }

    /// <summary>滚到某个绝对位置（越界自动夹住）。</summary>
    public void ScrollTo(double y, double? max = null)
    {
        var limit = max ?? Math.Max(0, Extent.Height - Viewport.Height);
        Offset = new Vector(Offset.X, Math.Clamp(y, 0, limit));
    }
}

/// <summary>
/// 滚轮该归谁：页面还是指针下面的控件。
/// 规则对齐 Windows 11 设置页 ——
/// 1. 指针在未展开的 ComboBox、NumericUpDown、Slider、单行 TextBox 上：滚页面，控件值不变；
///    但它们已经获得键盘焦点时保留原生行为（键盘用户本来就在操作它）。
/// 2. 展开的 ComboBox 下拉列表自己滚（它在独立 Popup 里，本来也不会走到这里）。
/// 3. 嵌套 ScrollViewer：它还能往这个方向滚就归它，已经到头就链给页面（避免「滚到一半卡住」）。
/// </summary>
public static class WheelPolicy
{
    /// <summary>指针下的控件是否要自己消费这次滚轮（true = 页面别管）。</summary>
    public static bool ControlConsumes(Control source, ScrollViewer page, Vector delta)
    {
        // 页面只做纵向滚动：纯横向的滚轮（横向触摸板 / 横向滚轮）不拦，交给控件自己。
        if (Math.Abs(delta.Y) < 0.001) return true;

        for (Control? control = source; control is not null && !ReferenceEquals(control, page);
             control = control.Parent as Control)
        {
            switch (control)
            {
                // 展开中的下拉列表自己滚（列表在 Popup 里，本来不会走到这里，留着防御）。
                case ComboBox combo when combo.IsDropDownOpen:
                    return true;
                // 值控件 / 输入框已经拿到键盘焦点时，滚轮归它（键盘用户正在操作它）。
                case ComboBox or NumericUpDown or Slider when control.IsKeyboardFocusWithin:
                    return true;
                // 多行输入框自己内部滚动，不管焦点。
                case TextBox text when text.AcceptsReturn:
                    return true;
                case ComboBox or NumericUpDown or Slider or TextBox:
                    continue;
                case ScrollViewer inner:
                    if (Math.Abs(delta.Y) < 0.001) return true;
                    var max = Math.Max(0, inner.Extent.Height - inner.Viewport.Height);
                    if (max <= 0.5) continue;
                    // 还能往滚轮方向走 → 归它；已经到头 → 链给外层页面。
                    var atEdge = delta.Y < 0 ? inner.Offset.Y >= max - 0.5 : inner.Offset.Y <= 0.5;
                    return !atEdge;
            }
        }
        return false;
    }

    /// <summary>指针下的控件是否应该让页面接管这次滚轮（<see cref="ControlConsumes"/> 的反面）。</summary>
    public static bool ShouldPageScroll(Control source, ScrollViewer page, Vector delta) =>
        !ControlConsumes(source, page, delta);
}
