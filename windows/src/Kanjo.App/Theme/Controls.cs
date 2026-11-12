using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// InfoBar（WinUI 的 InfoBar）：左侧状态图标 + 正文，圆角 8、淡色底、1px 描边。
/// 设置页的 --data 警告用它（warning 严重级）。
/// </summary>
public sealed class InfoBar : Border
{
    public enum Level
    {
        Informational,
        Warning,
        Error,
        Success,
    }

    public InfoBar(string message, Level level = Level.Warning, string? title = null, Control? action = null)
    {
        var (fill, stroke, ink, glyph) = level switch
        {
            Level.Error => (Palette.BadFill, Palette.Bad, Palette.Bad, Icons.WarnTriangle(14, Palette.Bad)),
            Level.Success => (Palette.GoodFill, Palette.Good, Palette.Good, Icons.CheckCircle(14, Palette.Good)),
            Level.Informational => (Palette.GroupFill, Palette.CardBorder, Palette.Foreground,
                Icons.InfoCircle(14, Palette.Secondary)),
            _ => (Palette.InfoBarFill, Palette.InfoBarStroke, Palette.WarnInk, Icons.WarnTriangle(14, Palette.WarnInk)),
        };

        Background = fill;
        BorderBrush = stroke;
        BorderThickness = new Thickness(1);
        CornerRadius = new CornerRadius(Metrics.GroupRadius);

        var body = Ui.V(2);
        if (!string.IsNullOrEmpty(title))
        {
            body.Children.Add(Ui.Text(title!, Type.BodyStrongSize, FontWeight.SemiBold, ink));
        }
        var text = Ui.Text(message, Type.CaptionSize, null, ink, wrap: true);
        body.Children.Add(text);
        if (action is not null)
        {
            action.HorizontalAlignment = HorizontalAlignment.Left;
            action.Margin = new Thickness(0, 4, 0, 0);
            body.Children.Add(action);
        }

        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        glyph.VerticalAlignment = VerticalAlignment.Top;
        glyph.Margin = new Thickness(0, 2, 10, 0);
        Grid.SetColumn(glyph, 0);
        grid.Children.Add(glyph);
        Grid.SetColumn(body, 1);
        grid.Children.Add(body);

        // WinUI 的 InfoBar 左侧有一条状态色的竖条。
        var stripe = new Border
        {
            Width = 4,
            Background = stroke,
            CornerRadius = new CornerRadius(2),
            Margin = new Thickness(0, 0, 10, 0),
            VerticalAlignment = VerticalAlignment.Stretch,
        };
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*") };
        Grid.SetColumn(stripe, 0);
        row.Children.Add(stripe);
        Grid.SetColumn(grid, 1);
        row.Children.Add(grid);

        Child = row;
        Padding = new Thickness(12, 12, 14, 12);
    }
}

/// <summary>
/// Fluent 的分段控件 / SelectorBar：一排胶囊选项。选中项 = 强调色填充 + 强调色上的文字，
/// 未选中 = 透明底 + 次要色文字，悬停给淡底。默认铺满可用宽度（各段等宽）。
/// </summary>
public sealed class SegmentedControl : Border
{
    public SegmentedControl(IReadOnlyList<string> options, int selected, Action<int> onSelect,
        double fontSize = Type.CaptionSize, bool stretch = true)
    {
        Padding = new Thickness(3);
        CornerRadius = new CornerRadius(20);
        Background = Palette.GroupFill;
        BorderBrush = Palette.CardBorder;
        BorderThickness = new Thickness(1);
        HorizontalAlignment = stretch ? HorizontalAlignment.Stretch : HorizontalAlignment.Left;
        VerticalAlignment = VerticalAlignment.Center;

        var row = new Grid();
        for (var i = 0; i < options.Count; i++)
        {
            row.ColumnDefinitions.Add(new ColumnDefinition(
                stretch ? new GridLength(1, GridUnitType.Star) : GridLength.Auto));
        }
        for (var i = 0; i < options.Count; i++)
        {
            var index = i;
            var isSelected = i == selected;
            var label = Ui.Text(options[i], fontSize, isSelected ? FontWeight.SemiBold : FontWeight.Normal,
                isSelected ? Palette.ContrastOn(Palette.Accent) : Palette.Secondary);
            label.TextAlignment = TextAlignment.Center;
            label.VerticalAlignment = VerticalAlignment.Center;

            var chip = new Border
            {
                Child = label,
                CornerRadius = new CornerRadius(16),
                Padding = new Thickness(10, 4, 10, 4),
                Background = isSelected ? Palette.Accent : Brushes.Transparent,
                MinHeight = 26,
            };
            chip.Transitions = new Avalonia.Animation.Transitions
            {
                new Avalonia.Animation.BrushTransition
                {
                    Property = BackgroundProperty,
                    Duration = TimeSpan.FromMilliseconds(Metrics.StateTransitionMilliseconds),
                    Easing = new Avalonia.Animation.Easings.LinearEasing(),
                },
            };
            if (!isSelected)
            {
                chip.PointerEntered += (_, _) => chip.Background = Palette.RowHover;
                chip.PointerExited += (_, _) => chip.Background = Brushes.Transparent;
                chip.Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Arrow);
                chip.PointerReleased += (_, e) =>
                {
                    e.Handled = true;
                    onSelect(index);
                };
            }
            Grid.SetColumn(chip, i);
            row.Children.Add(chip);
        }
        Child = row;
    }
}

/// <summary>
/// Fluent 下拉（ComboBox）：最小宽 200、圆角 4。**注意**：控件自己声明 MinWidth，行布局据此决定
/// 是并排还是落到下一行，所以不要在调用点再改 MinWidth。
/// </summary>
public static class Picker
{
    public static ComboBox Make(IReadOnlyList<string> options, int selected, Action<int> onSelect,
        bool enabled = true, double minWidth = Metrics.ControlMinWidth)
    {
        var combo = new ComboBox
        {
            ItemsSource = options,
            SelectedIndex = Math.Clamp(selected, 0, Math.Max(options.Count - 1, 0)),
            MinWidth = minWidth,
            FontSize = Type.CaptionSize,
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Center,
            IsEnabled = enabled,
            CornerRadius = new CornerRadius(4),
            MinHeight = 32,
        };
        if (enabled)
        {
            combo.SelectionChanged += (_, _) =>
            {
                if (combo.SelectedIndex >= 0) onSelect(combo.SelectedIndex);
            };
        }
        return combo;
    }
}
/// <summary>
/// 开关行用的 <see cref="ToggleSwitch"/>（WinUI 的切换开关）。
/// 只在「开 / 关」语义的设置上用（Show total in menu bar / Publish / Family usage）；
/// 磁盘页那种「勾选若干条」仍然用 CheckBox。
/// </summary>
public static class Toggle
{
    public static ToggleSwitch Make(bool value, Action<bool> onToggle, bool enabled = true)
    {
        var toggle = new ToggleSwitch
        {
            IsChecked = value,
            OnContent = null,
            OffContent = null,
            MinWidth = 0,
            IsEnabled = enabled,
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        if (enabled)
        {
            toggle.IsCheckedChanged += (_, _) => onToggle(toggle.IsChecked == true);
        }
        return toggle;
    }
}

