using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;

namespace Kanjo.App;

/// <summary>用代码画托盘 / 窗口图标（不引入二进制资源）：Kanjo 的标志 + 状态色。</summary>
public static class TrayIconFactory
{
    public const int Size = 32;

    /// <summary>正常（强调色）/ 出错（红色）/ 加载中（灰）。</summary>
    public static WindowIcon Create(Core.TrayStatus status)
    {
        var bitmap = Render(status);
        return new WindowIcon(bitmap);
    }

    public static RenderTargetBitmap Render(Core.TrayStatus status)
    {
        var bitmap = new RenderTargetBitmap(new PixelSize(Size, Size), new Vector(96, 96));
        using (var ctx = bitmap.CreateDrawingContext())
        {
            var color = status switch
            {
                Core.TrayStatus.Error => Color.FromRgb(0xD9, 0x3B, 0x3B),
                Core.TrayStatus.Loading => Color.FromRgb(0x8A, 0x8A, 0x8E),
                _ => Color.FromRgb(0x2E, 0x2E, 0x32),
            };
            if (Palette.IsDark && status == Core.TrayStatus.Normal) color = Color.FromRgb(0xF2, 0xF2, 0xF5);

            // 外圈 + 中间一个「勘」字的抽象：竖笔 + 横笔（不依赖字体渲染）。
            var brush = new SolidColorBrush(color);
            var pen = new Pen(brush, 2.4);
            ctx.DrawEllipse(null, pen, new Point(Size / 2.0, Size / 2.0), 12, 12);
            ctx.FillRectangle(brush, new Rect(Size / 2.0 - 1.2, 9, 2.4, 14));
            ctx.FillRectangle(brush, new Rect(9, Size / 2.0 - 1.2, 14, 2.4));
        }
        return bitmap;
    }
}
