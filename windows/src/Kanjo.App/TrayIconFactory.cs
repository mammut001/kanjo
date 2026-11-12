using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;

namespace Kanjo.App;

/// <summary>
/// 托盘 / 窗口图标。正常与出错两档用 <c>Assets/Tray.ico</c> / <c>Assets/TrayError.ico</c>
/// （由 <c>scripts/make-icons.py</c> 逐尺寸生成：16 / 20 / 24 / 32 … 每档单独排版，
/// Windows 按 DPI 取最合适的一档）。
///
/// Windows 的托盘**不能**像 Mac 菜单栏那样用模板图标自动反色，所以这里画的是 Kanjo 标志本身
/// （深色圆角方块 + 三块马赛克色块），深色 / 浅色任务栏上都看得清。加载中（还没有任何报告）
/// 用同一个标志的灰度版，由代码画，不额外存一份灰色 .ico。
/// </summary>
public static class TrayIconFactory
{
    public const int Size = 32;

    private const uint Clay = 0xD97757;   // Claude Code
    private const uint Blue = 0x3E79D6;   // Codex CLI
    private const uint Violet = 0x7A6AD8; // Antigravity CLI
    private const uint ErrorRed = 0xD93B3B;

    /// <summary>正常 / 出错 / 加载中。</summary>
    public static WindowIcon Create(Core.TrayStatus status)
    {
        // 加载中是灰度版，没有对应的 .ico：直接用代码画。
        if (status == Core.TrayStatus.Loading) return new WindowIcon(Render(status));

        var uri = new Uri(status == Core.TrayStatus.Error
            ? "avares://Kanjo/Assets/TrayError.ico"
            : "avares://Kanjo/Assets/Tray.ico");
        try
        {
            if (AssetLoader.Exists(uri))
            {
                using var stream = AssetLoader.Open(uri);
                return new WindowIcon(stream);
            }
        }
        catch (Exception)
        {
            // 资源不可用（例如还没跑 make-icons.py）：退回自绘。
        }
        return new WindowIcon(Render(status));
    }

    /// <summary>自绘兜底 / 加载中：深色圆角方块 + 三块马赛克，和 Tray.ico 同一套画法。</summary>
    public static RenderTargetBitmap Render(Core.TrayStatus status)
    {
        var bitmap = new RenderTargetBitmap(new PixelSize(Size, Size), new Vector(96, 96));
        using (var ctx = bitmap.CreateDrawingContext())
        {
            // 加载中：整体灰度（还没读到任何数据）。
            var loading = status == Core.TrayStatus.Loading;
            var background = new SolidColorBrush(loading ? Color.FromRgb(0x3A, 0x3A, 0x3E)
                                                         : Color.FromRgb(0x1C, 0x1C, 0x1E));
            var corner = new RectangleGeometry(new Rect(0, 0, Size, Size), 7, 7);
            ctx.DrawGeometry(background, null, corner);

            // 和 make-icons.py 的小尺寸布局一致：左大块 53%，右侧两块。
            var inset = 3.0;
            var area = Size - inset * 2;
            var gap = 1.5;
            Tile(ctx, loading, inset, inset, area * 0.53 - gap, area, Clay);
            Tile(ctx, loading, inset + area * 0.565, inset, area * 0.435 - gap,
                area * 0.47 - gap, Blue);
            Tile(ctx, loading, inset + area * 0.565, inset + area * 0.515,
                area * 0.435 - gap, area * 0.485 - gap, Violet);

            if (status == Core.TrayStatus.Error)
            {
                // 右下角红点（TrayError.ico 同一个位置）。
                var radius = area * 0.19;
                var cx = Size - 3.5 - radius;
                var cy = Size - 3.5 - radius;
                ctx.DrawEllipse(background, null, new Point(cx, cy), radius + 1, radius + 1);
                ctx.DrawEllipse(new SolidColorBrush(FromHex(ErrorRed)), null, new Point(cx, cy), radius, radius);
            }
        }
        return bitmap;
    }

    /// <summary>画一块马赛克（圆角 22%）。</summary>
    private static void Tile(DrawingContext ctx, bool loading, double x, double y, double w, double h, uint color)
    {
        if (w <= 0 || h <= 0) return;
        var rect = new Rect(x, y, w, h);
        var radius = Math.Min(w, h) * 0.22;
        var brush = new SolidColorBrush(loading ? Gray(FromHex(color)) : FromHex(color));
        ctx.DrawGeometry(brush, null, new RectangleGeometry(rect, radius, radius));
    }

    private static Color FromHex(uint hex) => Color.FromRgb(
        (byte)((hex >> 16) & 0xFF), (byte)((hex >> 8) & 0xFF), (byte)(hex & 0xFF));

    /// <summary>灰度：加载中还没数据，颜色没有意义。</summary>
    private static Color Gray(Color color)
    {
        var value = (byte)Math.Round(0.299 * color.R + 0.587 * color.G + 0.114 * color.B);
        return Color.FromArgb(0xB0, value, value, value);
    }
}
