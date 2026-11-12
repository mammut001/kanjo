using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;

namespace Kanjo.App;

/// <summary>
/// 托盘 / 窗口图标。正常与出错两档用 <c>Assets/Tray.ico</c> / <c>Assets/TrayError.ico</c>
/// （由 <c>scripts/make-icons.py</c> 生成，多尺寸 16–256，Windows 会按 DPI 取最合适的一档）；
/// 资源缺失时才退回用代码画。
/// </summary>
public static class TrayIconFactory
{
    public const int Size = 32;

    /// <summary>正常 / 出错 / 加载中。</summary>
    public static WindowIcon Create(Core.TrayStatus status)
    {
        // 加载中是灰色圆环，没有对应的 .ico：直接用代码画（下面 Render 的 Loading 分支）。
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

    /// <summary>自绘兜底：外圈 + 中间十字笔，和 Tray.ico 的画法一致。</summary>
    public static RenderTargetBitmap Render(Core.TrayStatus status)
    {
        var bitmap = new RenderTargetBitmap(new PixelSize(Size, Size), new Vector(96, 96));
        using (var ctx = bitmap.CreateDrawingContext())
        {
            var color = status switch
            {
                Core.TrayStatus.Error => Color.FromRgb(0xD9, 0x3B, 0x3B),
                Core.TrayStatus.Loading => Color.FromRgb(0x8A, 0x8A, 0x8E),
                _ => Color.FromRgb(0xD9, 0x77, 0x57),
            };

            var brush = new SolidColorBrush(color);
            var pen = new Pen(brush, 2.4);
            ctx.DrawEllipse(null, pen, new Point(Size / 2.0, Size / 2.0), 12, 12);
            ctx.FillRectangle(brush, new Rect(Size / 2.0 - 1.2, 9, 2.4, 14));
            ctx.FillRectangle(brush, new Rect(9, Size / 2.0 - 1.2, 14, 2.4));
        }
        return bitmap;
    }
}
