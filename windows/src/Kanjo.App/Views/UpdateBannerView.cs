using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 面板顶部的更新横幅（Fluent InfoBar 的版式）：左边一条强调色竖条 + 状态图标，
/// 中间标题 / 说明 / 进度条 / 按钮，右上角 ✕ 关掉。
///
/// 只在两种状态下出现（规则在 <see cref="UpdateBanner"/> 里，有单测）：
/// <list type="bullet">
/// <item>已下载：`Kanjo 0.5.3 is ready` + 「Restart to update」（强调色主按钮）；</item>
/// <item>下载中：`Downloading Kanjo 0.5.3… 42%` + 一条不会动的进度条（截图可复现）。</item>
/// </list>
/// 底色用卡片色（不是淡琥珀）：这是通知，不是警告；深色 / 浅色下都和周围的卡片同一层。
/// </summary>
public static class UpdateBannerView
{
    /// <summary>面板顶部那张横幅；调用方负责按 <see cref="UpdateBanner.ShouldShow"/> 判断要不要加。</summary>
    public static Control Make(UpdateService updates, Action onRestart, Action onDismiss)
    {
        var status = updates.Status;
        var ready = status.State == UpdateState.Ready;
        var ink = Palette.Foreground;

        var body = Ui.V(3);
        if (UpdateBanner.Title(status) is { } title)
        {
            body.Children.Add(Ui.Text(title, Type.BodyStrongSize, FontWeight.SemiBold, ink, wrap: true));
        }
        if (UpdateBanner.Message(status) is { } message)
        {
            body.Children.Add(Ui.Text(message, Type.CaptionSize, null, Palette.Secondary, wrap: true));
        }
        if (UpdateBanner.ShowsProgress(status))
        {
            body.Children.Add(ProgressLine(status.Progress));
        }

        var action = ready
            ? Ui.AccentButton(WindowsL10n.Tr("update.restart_to_install"), onRestart, size: Type.CaptionSize)
            : null;
        if (action is not null)
        {
            action.Margin = new Thickness(0, 4, 0, 0);
            body.Children.Add(action);
        }

        var glyph = ready
            ? Icons.UpdateArrow(14, Palette.Link)
            : Icons.UpdateArrow(14, Palette.Secondary);

        var stripe = new Border
        {
            Width = 4,
            Background = ready ? Palette.Accent : Palette.CardBorder,
            CornerRadius = new CornerRadius(2),
            Margin = new Thickness(0, 0, 10, 0),
            VerticalAlignment = VerticalAlignment.Stretch,
        };

        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        glyph.VerticalAlignment = VerticalAlignment.Top;
        glyph.Margin = new Thickness(0, 3, 10, 0);
        Grid.SetColumn(glyph, 0);
        grid.Children.Add(glyph);
        Grid.SetColumn(body, 1);
        grid.Children.Add(body);

        var close = Ui.IconButton(Icons.Close(9, Palette.Secondary), onDismiss,
            WindowsL10n.Tr("update.dismiss"));
        close.VerticalAlignment = VerticalAlignment.Top;
        close.Margin = new Thickness(4, -8, -8, 0);

        var inner = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(grid, 0);
        inner.Children.Add(grid);
        Grid.SetColumn(close, 1);
        inner.Children.Add(close);

        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        Grid.SetColumn(stripe, 0);
        row.Children.Add(stripe);
        Grid.SetColumn(inner, 1);
        row.Children.Add(inner);

        return new Border
        {
            Child = row,
            Background = Palette.CardBackground,
            BorderBrush = Palette.CardBorder,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(Metrics.GroupRadius),
            Padding = new Thickness(12, 10, 12, 10),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            ClipToBounds = true,
        };
    }

    /// <summary>
    /// 进度条：两列 `N*` / `(100-N)*` 的 Grid，宽度由布局算出来 ——
    /// 不用动画、也不用等布局完成再改宽度，所以截图和真机一致。
    /// </summary>
    public static Control ProgressLine(int percent)
    {
        var value = Math.Clamp(percent, 0, 100);
        var fill = new Border
        {
            Background = Palette.Accent,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        var track = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions($"{Math.Max(value, 0)}*,{Math.Max(100 - value, 0)}*"),
            Children = { fill },
        };
        return new Border
        {
            Child = track,
            Height = 4,
            Margin = new Thickness(0, 4, 0, 0),
            Background = Palette.HeatEmpty,
            CornerRadius = new CornerRadius(2),
            ClipToBounds = true,
        };
    }
}
