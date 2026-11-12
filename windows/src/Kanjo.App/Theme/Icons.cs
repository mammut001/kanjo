using System.Globalization;
using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Path = Avalonia.Controls.Shapes.Path;
using Avalonia.Media;

namespace Kanjo.App;

/// <summary>
/// 极简矢量图标（对应 Mac 版用到的 SF Symbols）。用 Path 画，不依赖字体 / emoji，
/// 因此 Windows、macOS 上外观一致，也不受系统 emoji 字体影响。
/// 每个图标都放在固定尺寸的 Viewbox 里，几何坐标写在 12×12（或 16×16）空间里，缩放自动完成。
/// 注意：不要用 Canvas 摆子元素——Canvas 的子元素不参与自动布局，离屏渲染时会全部堆在原点。
/// </summary>
public static class Icons
{
    private const double G = 12; // 图标几何坐标系边长

    private static Control Glyph(string data, double size, IBrush? brush, bool filled)
    {
        var path = new Path
        {
            Data = Geometry.Parse(data),
            Fill = filled ? brush ?? Palette.Foreground : null,
            Stroke = filled ? null : brush ?? Palette.Foreground,
            StrokeThickness = 1.1,
            StrokeLineCap = PenLineCap.Round,
            StrokeJoin = PenLineJoin.Round,
            Stretch = Stretch.None,
            Width = G,
            Height = G,
        };
        return new Viewbox
        {
            Width = size,
            Height = size,
            Stretch = Stretch.Uniform,
            Child = path,
            HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center,
            VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
        };
    }

    /// <summary>info.circle：圆圈 + 竖点 + 竖线（空心，和 SF Symbol 一致）。</summary>
    public static Control InfoCircle(double size = 11, IBrush? brush = null) => Glyph(
        "M6,0.9 A5.1,5.1 0 1 0 6,11.1 A5.1,5.1 0 1 0 6,0.9 Z " +
        "M6,4.6 L6,4.7 M6,6.3 L6,9.2",
        size, brush, filled: false);

    /// <summary>calendar。</summary>
    public static Control Calendar(double size = 10, IBrush? brush = null) => Glyph(
        "M1.5,3 L10.5,3 L10.5,10.5 L1.5,10.5 Z M1.5,5.2 L10.5,5.2 M4,1.4 L4,3.8 M8,1.4 L8,3.8",
        size, brush, filled: false);

    /// <summary>arrow.clockwise。</summary>
    public static Control Refresh(double size = 12, IBrush? brush = null) => Glyph(
        "M9.6,4.1 A4.3,4.3 0 1 1 6,1.7 M6,1.7 L6,-0.4 M6,1.7 L8,1.7",
        size, brush, filled: false);

    /// <summary>internaldrive：略带梯形的驱动器外壳 + 一条槽线 + 底部散热小格。</summary>
    public static Control Disk(double size = 12, IBrush? brush = null) => Glyph(
        "M2.4,1.9 L9.6,1.9 A1.25,1.25 0 0 1 10.85,3.15 L10.85,8.85 A1.25,1.25 0 0 1 9.6,10.1 " +
        "L2.4,10.1 A1.25,1.25 0 0 1 1.15,8.85 L1.15,3.15 A1.25,1.25 0 0 1 2.4,1.9 Z " +
        "M1.15,7.15 L10.85,7.15 " +
        "M3.5,8.6 L3.5,8.65 M4.7,8.6 L4.7,8.65 M5.9,8.6 L5.9,8.65 M7.1,8.6 L7.1,8.65 M8.3,8.6 L8.3,8.65",
        size, brush, filled: false);

    /// <summary>gearshape：8 齿齿轮（齿尖与齿根都带圆角）+ 中心孔。</summary>
    public static Control Gear(double size = 12, IBrush? brush = null) => Glyph(
        GearPath(8, 4.55, 5.55, 1.75), size, brush, filled: false);

    /// <summary>生成 n 齿齿轮的轮廓（外半径 ro、齿根半径 ri、中心孔 rHole），坐标在 12×12 空间里。</summary>
    private static string GearPath(int teeth, double rootRadius, double outerRadius, double holeRadius)
    {
        const double cx = 6, cy = 6;
        var sb = new StringBuilder();
        var step = 2 * Math.PI / teeth;
        // 每个齿占一个 step：0.22 齿顶、0.22 齿根、其余过渡。
        var topHalf = step * 0.20;
        var rootHalf = step * 0.24;
        for (var i = 0; i < teeth; i++)
        {
            var center = i * step - Math.PI / 2;
            Append(sb, center - topHalf, outerRadius, first: i == 0 && sb.Length == 0);
            Append(sb, center + topHalf, outerRadius);
            Append(sb, center + step / 2 - rootHalf, rootRadius);
            Append(sb, center + step / 2 + rootHalf, rootRadius);
        }
        sb.Append(" Z ");
        // 中心孔（反向绕，形成孔洞）。
        sb.Append($"M{cx - holeRadius:0.###},{cy:0.###} A{holeRadius:0.###},{holeRadius:0.###} 0 1 0 " +
                  $"{cx + holeRadius:0.###},{cy:0.###} A{holeRadius:0.###},{holeRadius:0.###} 0 1 0 " +
                  $"{cx - holeRadius:0.###},{cy:0.###} Z");
        return sb.ToString();

        void Append(StringBuilder b, double angle, double r, bool first = false)
        {
            var x = cx + r * Math.Cos(angle);
            var y = cy + r * Math.Sin(angle);
            if (first) b.Append($"M{x:0.###},{y:0.###} ");
            else b.Append($"L{x:0.###},{y:0.###} ");
        }
    }

    /// <summary>power。</summary>
    public static Control Power(double size = 12, IBrush? brush = null) => Glyph(
        "M6,1.2 L6,5.6 M9.1,3.1 A4.2,4.2 0 1 1 2.9,3.1",
        size, brush, filled: false);

    /// <summary>pin.fill。</summary>
    public static Control Pin(double size = 8.5, IBrush? brush = null) => Glyph(
        "M7.2,1 L11,4.8 L9.6,5.4 L7.2,7.8 L7.2,9.9 L5,7.7 L2,10.7 L1.3,10 L4.3,7 L2.1,4.8 " +
        "L4.2,4.8 L6.6,2.4 Z",
        size, brush, filled: true);

    /// <summary>eye.slash。</summary>
    public static Control EyeSlash(double size = 10, IBrush? brush = null) => Glyph(
        "M0.8,6 C3,2.6 9,2.6 11.2,6 C9,9.4 3,9.4 0.8,6 Z M1,10.5 L11,1.5",
        size, brush, filled: false);

    /// <summary>eye。</summary>
    public static Control Eye(double size = 10, IBrush? brush = null) => Glyph(
        "M0.8,6 C3,2.6 9,2.6 11.2,6 C9,9.4 3,9.4 0.8,6 Z M6,4.2 A1.8,1.8 0 1 0 6,7.8 A1.8,1.8 0 1 0 6,4.2 Z",
        size, brush, filled: false);

    /// <summary>chevron.right / chevron.down（ParseFailedRow 用）。</summary>
    public static Control Chevron(bool down, double size = 7, IBrush? brush = null) => Glyph(
        down ? "M1.5,3.5 L4.5,6.5 L7.5,3.5" : "M3.5,1.5 L6.5,4.5 L3.5,7.5",
        size, brush, filled: false);

    /// <summary>只要 Path（切换方向时用），不要外面的 Viewbox。</summary>
    public static Shape ChevronPath(bool down, double size, IBrush? brush) => new Path
    {
        Data = Geometry.Parse(down ? "M1.5,3.5 L4.5,6.5 L7.5,3.5" : "M3.5,1.5 L6.5,4.5 L3.5,7.5"),
        Stroke = brush ?? Palette.Foreground,
        StrokeThickness = 1.3,
        StrokeLineCap = PenLineCap.Round,
        StrokeJoin = PenLineJoin.Round,
        Stretch = Stretch.Uniform,
    };

    /// <summary>checkmark.circle.fill。</summary>
    public static Control CheckCircle(double size = 10, IBrush? brush = null) => new Grid
    {
        Width = size,
        Height = size,
        Children =
        {
            Glyph("M6,0.6 A5.4,5.4 0 1 0 6,11.4 A5.4,5.4 0 1 0 6,0.6 Z", size, brush, filled: true)
                .FillStretch(),
            Glyph("M3.4,6.2 L5.2,8 L8.7,4.2", size, Brushes.White, filled: false).FillStretch(),
        },
    };

    /// <summary>exclamationmark.triangle.fill。</summary>
    public static Control WarnTriangle(double size = 10, IBrush? brush = null) => new Grid
    {
        Width = size,
        Height = size,
        Children =
        {
            Glyph("M6,0.9 L11.6,10.6 L0.4,10.6 Z", size, brush, filled: true).FillStretch(),
            Glyph("M6,4.2 L6,7.4 M6,8.7 L6,9", size, Brushes.White, filled: false).FillStretch(),
        },
    };

    /// <summary>chevron.left。</summary>
    public static Control ChevronLeft(double size = 11, IBrush? brush = null) => Glyph(
        "M7.5,1.5 L4,6 L7.5,10.5", size, brush, filled: false);

    /// <summary>link：两个斜扣。</summary>
    public static Control Link(double size = 9, IBrush? brush = null) => Glyph(
        "M4.9,7.1 L7.1,4.9 M5.6,3.2 L6.9,1.9 A1.9,1.9 0 0 1 9.6,4.6 L8.3,5.9 " +
        "M6.4,8.8 L5.1,10.1 A1.9,1.9 0 0 1 2.4,7.4 L3.7,6.1",
        size, brush, filled: false);

    /// <summary>arrow.triangle.branch：一条主干 + 分出去的一支。</summary>
    public static Control Branch(double size = 8, IBrush? brush = null) => Glyph(
        // arrow.triangle.branch：一条主干向上分成两叉，两叉顶端各有一个箭头。
        "M6,10.2 L6,5.9 M6,5.9 L3.2,3.1 M6,5.9 L8.8,3.1 " +
        "M2,4.4 L3.2,3 L3.6,4.7 M10,4.4 L8.8,3 L8.4,4.7",
        size, brush, filled: false);

    /// <summary>questionmark.circle。</summary>
    public static Control QuestionCircle(double size = 9, IBrush? brush = null) => Glyph(
        "M6,0.9 A5.1,5.1 0 1 0 6,11.1 A5.1,5.1 0 1 0 6,0.9 Z " +
        "M4.6,4.6 A1.45,1.45 0 1 1 6.6,5.9 C6.2,6.1 6,6.4 6,6.9 M6,8.4 L6,8.5",
        size, brush, filled: false);

    /// <summary>arrow.down / arrow.up（排序方向）。</summary>
    public static Control SortArrow(bool down, double size = 9, IBrush? brush = null) => Glyph(
        down ? "M6,2.2 L6,9.8 M3.2,7 L6,9.8 L8.8,7" : "M6,9.8 L6,2.2 M3.2,5 L6,2.2 L8.8,5",
        size, brush, filled: false);

    /// <summary>chevron.up.chevron.down（下拉菜单的小箭头）。</summary>
    public static Control ChevronDownUp(double size = 8, IBrush? brush = null) => Glyph(
        "M3.2,4.6 L6,1.8 L8.8,4.6 M3.2,7.4 L6,10.2 L8.8,7.4", size, brush, filled: false);

    /// <summary>chevron.down / chevron.up（步进器的小箭头）。</summary>
    public static Control ChevronUp(double size = 7, IBrush? brush = null) => Glyph(
        "M1.5,6.5 L4.5,3.5 L7.5,6.5", size, brush, filled: false);

    public static Control ChevronDown(double size = 7, IBrush? brush = null) => Glyph(
        "M1.5,3.5 L4.5,6.5 L7.5,3.5", size, brush, filled: false);

    /// <summary>状态小点（托盘状态 / 圆点）。</summary>
    public static Control StatusDot(IBrush brush, double size = 6) => new Ellipse
    {
        Width = size,
        Height = size,
        Fill = brush,
        VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
    };
}

internal static class IconHelpers
{
    /// <summary>Viewbox 里的图标撑满父容器（叠放层用）。</summary>
    public static Control FillStretch(this Control control)
    {
        control.HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch;
        control.VerticalAlignment = Avalonia.Layout.VerticalAlignment.Stretch;
        return control;
    }
}
