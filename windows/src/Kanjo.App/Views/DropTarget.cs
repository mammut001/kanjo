using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;

namespace Kanjo.App.Views;

/// <summary>
/// 拖拽排序的落点处理（对应 SwiftUI 的 `.draggable` + `.dropDestination`）：
/// 按下记下要拖的 id，指针进入 / 离开时高亮，松手时按落点 id 回调。
/// 没有系统级 drag-and-drop（离屏渲染下也不需要），只用指针事件。
/// </summary>
public sealed class DropTarget
{
    private static DropTarget? _active;
    private static string? _source;
    private static Point _pressPoint;
    private static bool _dragging;

    private readonly Border _border;
    private readonly string _id;
    private readonly IBrush _normal;

    public DropTarget(Border border, string id)
    {
        _border = border;
        _id = id;
        _normal = border.Background ?? Brushes.Transparent;
        border.PointerEntered += (_, _) =>
        {
            if (_dragging && _source != _id) border.Background = new SolidColorBrush(Palette.AccentFillColor, 0.18);
        };
        border.PointerExited += (_, _) =>
        {
            if (_dragging) border.Background = _normal;
        };
        border.PointerReleased += (_, _) =>
        {
            if (!_dragging || _source is null) return;
            var source = _source;
            EndDrag();
            if (source != _id) Dropped?.Invoke(source);
        };
    }

    public event Action<string>? Dropped;

    public void BeginDrag(PointerPressedEventArgs e)
    {
        _active = this;
        _source = _id;
        _pressPoint = e.GetPosition(_border);
        _dragging = true;
        var top = TopLevel.GetTopLevel(_border);
        if (top is not null) top.PointerReleased += OnGlobalRelease;
    }

    private static void OnGlobalRelease(object? sender, PointerReleasedEventArgs e)
    {
        if (sender is TopLevel top) top.PointerReleased -= OnGlobalRelease;
        EndDrag();
    }

    private static void EndDrag()
    {
        if (_active is { } active) active._border.Background = active._normal;
        _active = null;
        _source = null;
        _dragging = false;
    }

    /// <summary>测试 / 调试：当前正在拖的 id。</summary>
    public static string? DraggingId => _dragging ? _source : null;

    /// <summary>测试 / 调试：按下点到松手的距离（用来区分点击和拖拽）。</summary>
    public static double DistanceFrom(Point point) =>
        Math.Sqrt(Math.Pow(point.X - _pressPoint.X, 2) + Math.Pow(point.Y - _pressPoint.Y, 2));
}
