using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Media;

namespace Kanjo.App;

/// <summary>
/// 极简矢量图标（对应 Mac 版用到的 SF Symbols）。用 Path 画，不依赖字体 / emoji，
/// 因此 Windows、macOS 上外观一致，也不受系统 emoji 字体影响。
/// </summary>
public static class Icons
{
    public static Avalonia.Controls.Shapes.Path Make(string data, double size, IBrush? brush = null, bool filled = true) => new()
    {
        Data = Geometry.Parse(data),
        Width = size,
        Height = size,
        Stretch = Stretch.Uniform,
        Fill = filled ? brush ?? Palette.Foreground : null,
        Stroke = filled ? null : brush ?? Palette.Foreground,
        StrokeThickness = filled ? 0 : 1.4,
        StrokeLineCap = PenLineCap.Round,
        VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center,
    };

    /// <summary>info.circle：圆圈 + 竖点 + 竖线。</summary>
    public static Control InfoCircle(double size = 10, IBrush? brush = null) => new Canvas
    {
        Width = size,
        Height = size,
        Children =
        {
            Make("M8,1 A7,7 0 1 0 8,15 A7,7 0 1 0 8,1 Z", size, brush, filled: false),
            Make("M8,7 L8,11.5", size, brush, filled: false),
            Make("M8,4.6 L8,5.4", size, brush, filled: false),
        },
    };

    /// <summary>calendar。</summary>
    public static Control Calendar(double size = 10, IBrush? brush = null) => Make(
        "M2,4 L14,4 L14,14 L2,14 Z M2,7 L14,7 M5.5,2 L5.5,5 M10.5,2 L10.5,5", size, brush, filled: false);

    /// <summary>arrow.clockwise。</summary>
    public static Control Refresh(double size = 12, IBrush? brush = null) => Make(
        "M13,8 A5,5 0 1 1 8,3 M8,3 L8,0.5 M8,3 L10.5,3", size, brush, filled: false);

    /// <summary>internaldrive：圆角矩形 + 一条缝。</summary>
    public static Control Disk(double size = 12, IBrush? brush = null) => Make(
        "M2.5,5 L13.5,5 L13.5,11.5 L2.5,11.5 Z M2.5,5 L4.5,2 L11.5,2 L13.5,5 M10,8.5 L11.5,8.5",
        size, brush, filled: false);

    /// <summary>gearshape（简化：圆 + 外圈齿）。</summary>
    public static Control Gear(double size = 12, IBrush? brush = null) => new Canvas
    {
        Width = size,
        Height = size,
        Children =
        {
            Make("M8,4.6 A3.4,3.4 0 1 0 8,11.4 A3.4,3.4 0 1 0 8,4.6 Z", size, brush, filled: false),
            Make("M8,1.2 L8,3.2 M8,12.8 L8,14.8 M1.2,8 L3.2,8 M12.8,8 L14.8,8 " +
                 "M3.2,3.2 L4.6,4.6 M11.4,11.4 L12.8,12.8 M12.8,3.2 L11.4,4.6 M4.6,11.4 L3.2,12.8",
                size, brush, filled: false),
        },
    };

    /// <summary>power。</summary>
    public static Control Power(double size = 12, IBrush? brush = null) => Make(
        "M8,2 L8,7.5 M11.8,5.2 A4.8,4.8 0 1 1 4.2,5.2", size, brush, filled: false);

    /// <summary>pin.fill。</summary>
    public static Control Pin(double size = 8.5, IBrush? brush = null) => Make(
        "M9.6,1.2 L14.8,6.4 L13,7.2 L9.6,10.6 L9.6,13.4 L6.6,10.4 L2.6,14.4 L1.6,13.4 L5.6,9.4 L2.6,6.4 " +
        "L5.4,6.4 L8.8,3 Z",
        size, brush, filled: true);

    /// <summary>eye.slash。</summary>
    public static Control EyeSlash(double size = 10, IBrush? brush = null) => Make(
        "M1,8 C4,3.5 12,3.5 15,8 C12,12.5 4,12.5 1,8 Z M1,14 L15,2", size, brush, filled: false);

    /// <summary>checkmark.circle.fill。</summary>
    public static Control CheckCircle(double size = 10, IBrush? brush = null) => new Canvas
    {
        Width = size,
        Height = size,
        Children =
        {
            Make("M8,0.6 A7.4,7.4 0 1 0 8,15.4 A7.4,7.4 0 1 0 8,1.4 Z", size, brush, filled: true),
            Make("M4.6,8.2 L7,10.6 L11.4,5.6", size, Brushes.White, filled: false),
        },
    };

    /// <summary>exclamationmark.triangle.fill。</summary>
    public static Control WarnTriangle(double size = 10, IBrush? brush = null) => new Canvas
    {
        Width = size,
        Height = size,
        Children =
        {
            Make("M8,1.2 L15.2,14 L0.8,14 Z", size, brush, filled: true),
            Make("M8,5.6 L8,9.8", size, Brushes.White, filled: false),
            Make("M8,11.4 L8,12.2", size, Brushes.White, filled: false),
        },
    };

    /// <summary>chevron.left。</summary>
    public static Control ChevronLeft(double size = 11, IBrush? brush = null) => Make(
        "M10,2 L4,8 L10,14", size, brush, filled: false);

    /// <summary>状态小点（托盘状态 / 圆点）。</summary>
    public static Control StatusDot(IBrush brush, double size = 6) => new Ellipse
    {
        Width = size,
        Height = size,
        Fill = brush,
        VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
    };
}
