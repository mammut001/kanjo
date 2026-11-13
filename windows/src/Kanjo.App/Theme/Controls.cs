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
        // 横向不伸出去：正文在卡片里折行，而不是把卡片撑出窗口。
        ClipToBounds = true;

        var body = Ui.V(2);
        if (!string.IsNullOrEmpty(title))
        {
            body.Children.Add(Ui.Text(title!, Type.BodyStrongSize, FontWeight.SemiBold, ink, wrap: true));
        }
        var text = Ui.Text(message, Type.CaptionSize, null, ink, wrap: true);
        // 消息里有文件路径这种长串无空格文本：`Wrap` 会在放不下时按字符断开（旧版就是这样折的）。
        text.TextWrapping = TextWrapping.Wrap;
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
        // 关键的 `*` 列宽：让正文有确定的可用宽度去折行，而不是按内容想多宽就多宽。
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        Grid.SetColumn(stripe, 0);
        row.Children.Add(stripe);
        Grid.SetColumn(grid, 1);
        row.Children.Add(grid);

        Child = row;
        Padding = new Thickness(12, 12, 12, 12);
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
            if (!Motion.Snapshot)
            {
                chip.Transitions = new Avalonia.Animation.Transitions
                {
                    new Avalonia.Animation.BrushTransition
                    {
                        Property = BackgroundProperty,
                        Duration = TimeSpan.FromMilliseconds(Metrics.StateTransitionMilliseconds),
                        Easing = new Avalonia.Animation.Easings.LinearEasing(),
                    },
                };
            }
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
            // 选中的值是这个控件的主要内容，启用时必须用正文色。
            // 不显式给的话模板会走主题里的 ComboBoxForeground，某些状态（禁用 / 失焦）下是灰的，
            // 一眼看上去像「控件坏了」而不是「值是这个」。
            Foreground = enabled ? Palette.Foreground : Palette.Secondary,
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

/// <summary>
/// 可以在运行时切换启用态的按钮（「输入框有内容才能点」这种）。
/// 启用时是真 <see cref="Button"/>（Fluent 自带悬停 / 按下 / 聚焦三态）；禁用时换成
/// <see cref="Ui.DisabledButton"/> 的静态外观 —— 和 <see cref="Ui.AccentButton"/> /
/// <see cref="Ui.StandardButton"/> 在构造时按 `enabled: false` 给的样子**完全一致**，
/// 所以「先灰着、输入后亮起来」和「一开始就是启用的」看起来是同一个按钮。
///
/// 为什么需要它：那两个构造函数的 `enabled` 只在建控件时看一次。提示框里的按钮通常是在
/// 输入框还空着的时候建的，之后再输入也不会回头改外观 —— 家庭令牌的保存按钮就卡在这里
/// （真机上粘贴令牌后一直点不了）。
/// </summary>
public sealed class StateButton : Border
{
    private readonly string _text;
    private readonly Action _onClick;
    private readonly bool _accent;
    private readonly double _size;
    private readonly bool _compact;
    private bool _built;
    private bool _current;

    public StateButton(string text, Action onClick, bool enabled = true, bool accent = true,
        double size = Type.BodySize, bool compact = false)
    {
        _text = text;
        _onClick = onClick;
        _accent = accent;
        _size = size;
        _compact = compact;
        BorderThickness = new Thickness(0);
        HorizontalAlignment = HorizontalAlignment.Left;
        VerticalAlignment = VerticalAlignment.Center;
        SetEnabled(enabled);
    }

    /// <summary>
    /// 切换启用态：外观和 <see cref="Control.IsEnabled"/> 一起换（只改 IsEnabled 会留下强调色底）。
    /// 状态没变就不动控件树 —— 这个函数会被输入框的每次按键调用。
    /// </summary>
    public void SetEnabled(bool enabled)
    {
        if (_built && _current == enabled) return;
        _built = true;
        _current = enabled;
        IsEnabled = enabled;
        Child = enabled ? EnabledButton() : Ui.DisabledButton(_text, _size, _compact);
    }

    private Control EnabledButton() => _accent
        ? Ui.AccentButton(_text, _onClick, size: _size)
        : Ui.StandardButton(_text, _onClick, size: _size, compact: _compact);
}
