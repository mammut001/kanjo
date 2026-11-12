using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 紧凑的分段控件（自绘胶囊）：All · Today · 7d · 30d · Last week · Since reset · Cycle。
/// 「Since reset」不可用时画成三级色、不可点；「Cycle」同理。
/// </summary>
public sealed class RangePicker : Border
{
    public RangePicker(string rangeRaw, TimeRange effective, bool resetAvailable, bool cycleAvailable, Action<string> onChange)
    {
        Padding = new Thickness(1.5);
        CornerRadius = new CornerRadius(12);
        Background = new SolidColorBrush(Palette.Secondary is ISolidColorBrush s ? s.Color : Colors.Transparent, 0.12);
        HorizontalAlignment = HorizontalAlignment.Right;
        VerticalAlignment = VerticalAlignment.Center;

        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 0 };
        foreach (var range in TimeRanges.All)
        {
            var selected = range == effective;
            var label = Ui.Text(range.ShortLabel(), 9.5, selected ? FontWeight.SemiBold : FontWeight.Normal,
                selected ? Palette.Foreground : Palette.Secondary);
            var chip = new Border
            {
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(4, 2.5, 4, 2.5),
                Background = selected
                    ? new SolidColorBrush(((ISolidColorBrush)Palette.Foreground).Color, 0.13)
                    : Brushes.Transparent,
                Child = label,
                Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
            };

            var unavailable = Unavailable(range, resetAvailable, cycleAvailable);
            if (unavailable is not null)
            {
                label.Foreground = Palette.Tertiary;
                ToolTip.SetTip(chip, unavailable);
            }
            else
            {
                ToolTip.SetTip(chip, range.LongLabel());
                chip.PointerReleased += (_, _) =>
                {
                    onChange(range.RawValue());
                };
                chip.PointerEntered += (_, _) => chip.Background = Palette.RowHover;
                chip.PointerExited += (_, _) =>
                {
                    chip.Background = selected
                        ? new SolidColorBrush(((ISolidColorBrush)Palette.Foreground).Color, 0.13)
                        : Brushes.Transparent;
                };
            }
            row.Children.Add(chip);
        }
        Child = row;
    }

    private static string? Unavailable(TimeRange r, bool resetAvailable, bool cycleAvailable)
    {
        if (r == TimeRange.SinceReset && !resetAvailable) return L10n.Tr("timerange.tooltip.no_reset_info");
        if (r == TimeRange.BillingCycle && !cycleAvailable) return L10n.Tr("timerange.tooltip.no_subscription_info");
        return null;
    }
}

/// <summary>范围说明行：caption 字号、次要色、可折行。</summary>
public sealed class RangeCaptionLine : StackPanel
{
    public RangeCaptionLine(RangeCaptionResult caption)
    {
        Orientation = Orientation.Horizontal;
        Spacing = 4;
        Children.Add(Icons.Calendar(10, Palette.Secondary));
        Children.Add(Ui.Text(caption.Text, 10.5, null, Palette.Secondary, wrap: true));
        if (!string.IsNullOrEmpty(caption.Help)) ToolTip.SetTip(this, caption.Help);
    }
}

/// <summary>一行：色点 + 标签 + 明细 + 数值，下方一根按比例的细条（无底轨）。</summary>
public sealed class HBarRow : StackPanel
{
    public HBarRow(string label, IBrush color, double fraction, string value, string? detail = null, string? tip = null)
    {
        Orientation = Orientation.Vertical;
        Spacing = 5;

        var top = Ui.H(6);
        var dot = new Avalonia.Controls.Shapes.Ellipse { Width = 6, Height = 6, Fill = color, VerticalAlignment = VerticalAlignment.Center };
        top.Children.Add(dot);
        top.Children.Add(Ui.Text(label, 12));
        top.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        if (!string.IsNullOrEmpty(detail))
        {
            var detailText = Ui.Text(detail, 10.5, null, Palette.Secondary);
            top.Children.Add(detailText);
        }
        top.Children.Add(Ui.Text(value, 12, FontWeight.Medium));
        Children.Add(top);

        var track = new Border
        {
            Height = 3,
            CornerRadius = new CornerRadius(2),
            HorizontalAlignment = HorizontalAlignment.Left,
            Background = color,
            Width = Math.Max(0, Math.Min(fraction, 1) * 320),
            MinWidth = 3,
        };
        var trackHost = new Panel { Height = 3, HorizontalAlignment = HorizontalAlignment.Stretch };
        trackHost.Children.Add(track);
        Children.Add(trackHost);

        if (!string.IsNullOrEmpty(tip)) ToolTip.SetTip(this, tip);
    }
}
