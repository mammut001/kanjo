using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>跨页面共用的小组件（对应 Primitives.swift / ProjectActions.swift 里的视图部分）。</summary>
public static class Widgets
{
    /// <summary>徽章：小号 9pt、胶囊底色。style：neutral / good / warn / bad。</summary>
    public static Control Badge(string text, BadgeStyle style = BadgeStyle.Neutral, string? help = null)
    {
        var (fg, bg) = style switch
        {
            BadgeStyle.Good => (Palette.Good, Palette.GoodFill),
            BadgeStyle.Warn => (Palette.WarnInk, Palette.WarnFill),
            BadgeStyle.Bad => (Palette.Bad, Palette.BadFill),
            _ => (Palette.Secondary, Palette.GroupFill),
        };
        var badge = new Border
        {
            Child = Ui.Text(text, 9, FontWeight.Medium, fg),
            Background = bg,
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(5, 1, 5, 1),
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        if (!string.IsNullOrEmpty(help)) ToolTip.SetTip(badge, help);
        return badge;
    }

    /// <summary>返回按钮：`‹ 标题`，强调色。</summary>
    public static Control BackButton(string title, Action action)
    {
        var row = Ui.H(2);
        row.Children.Add(Icons.ChevronLeft(11, Palette.Accent));
        row.Children.Add(Ui.Text(title, 12, null, Palette.Accent));
        return new Clickable(row, action, radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            Padding = new Thickness(2, 1, 4, 1),
        };
    }

    /// <summary>大号金额：圆体 + 等宽数字。</summary>
    public static TextBlock HeroAmount(string text, double size = 34, IBrush? color = null) =>
        Ui.Text(text, size, FontWeight.SemiBold, color ?? Palette.Foreground, family: Type.Rounded);

    /// <summary>说明文字（caption 字号、次要色、可折行）。</summary>
    public static TextBlock Note(string text) => Ui.Text(text, 10.5, null, Palette.Secondary, wrap: true);

    /// <summary>行间细分割线（两端缩进）。</summary>
    public static Control RowDivider(double leading = Metrics.ListInset, double trailing = Metrics.ListInset,
        double opacity = 0.6) => new Border
    {
        Height = 0.6,
        Background = Palette.Separator,
        Opacity = opacity,
        Margin = new Thickness(leading, 0, trailing, 0),
        HorizontalAlignment = HorizontalAlignment.Stretch,
    };

    /// <summary>「Show all N …」/「Show fewer」文字按钮。</summary>
    public static Control ShowAllButton(bool expanded, int total, string noun, Action toggle) =>
        Ui.LinkButton(
            expanded
                ? L10n.Tr("common.show_fewer")
                : L10n.TrL(null, "common.show_all", total, noun),
            toggle, 11);

    /// <summary>一行 agent 色点（最多 3 个），悬停显示每个 agent 的金额和 token。</summary>
    public static Control AgentDots(IReadOnlyList<AgentCost> agents, string currency, double size = 6,
        string? hoverId = null)
    {
        var used = agents
            .Where(a => a.Sessions > 0 || a.Cost > 0 || a.Tokens.Total > 0)
            .OrderByDescending(a => a.Cost)
            .ToList();
        if (used.Count == 0) return new Panel();

        var row = Ui.H(3);
        foreach (var agent in used.Take(3)) row.Children.Add(Ui.Dot(agent.Agent, size));

        var totalCost = used.Sum(a => a.Cost);
        var totalTokens = used.Sum(a => a.Tokens.Total);
        var rows = HoverCardRowBuilder.AgentRows(used.Select(a => (a.Agent, a.Label, a.Cost, a.Tokens.Total)));
        var help = string.Join("\n", TooltipBuilder.AgentLines(used, currency));
        string id = hoverId ?? "dots:" + string.Join(",", used.Select(a => a.Agent));
        HoverLayer.Attach(row, id, () => HoverCards.AgentRows(L10n.Tr("project.section.by_agent"), null,
            totalCost, totalTokens, currency, rows));
        ToolTip.SetTip(row, help);
        return row;
    }

    /// <summary>状态块（schema 警告 / 刷新失败）：淡色填充 + 状态色文字。</summary>
    public static Control StatusBlock(bool bad, IEnumerable<Control> content)
    {
        var box = Ui.V(3);
        foreach (var c in content) box.Children.Add(c);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        var glyph = Icons.WarnTriangle(11, bad ? Palette.Bad : Palette.WarnInk);
        glyph.Margin = new Thickness(0, 2, 6, 0);
        glyph.VerticalAlignment = VerticalAlignment.Top;
        Grid.SetColumn(glyph, 0);
        row.Children.Add(glyph);
        Grid.SetColumn(box, 1);
        row.Children.Add(box);
        return new Border
        {
            Child = row,
            Background = bad ? Palette.BadFill : Palette.WarnFill,
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(10, 8, 10, 8),
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
    }

    /// <summary>agent 图例：色点 + 名称，流式折行，按花费降序。</summary>
    public static Control Legend(IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> items,
        string currency)
    {
        var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
        for (var i = 0; i < items.Count; i++)
        {
            var (agent, label, cost, tokens) = items[i];
            var chip = Ui.H(4);
            chip.Margin = new Thickness(0, 0, 9, 3);
            chip.Children.Add(Ui.Dot(agent));
            chip.Children.Add(Ui.Text(label, 10, null, Palette.Secondary));
            var rows = new List<HoverCardRowItem> { new(agent, label, cost, tokens, 1.0) };
            HoverLayer.Attach(chip, i == 0 ? "overview:hover:legend" : $"overview:hover:legend:{agent}",
                () => HoverCards.AgentRows(label, agent, cost, tokens, currency, rows));
            ToolTip.SetTip(chip, TooltipBuilder.AgentLine(label, cost, tokens, currency));
            wrap.Children.Add(chip);
        }
        return wrap;
    }
}

public enum BadgeStyle
{
    Neutral,
    Good,
    Warn,
    Bad,
}

/// <summary>自绘复选框（离屏渲染时不依赖控件模板）：选中时强调色方块 + 白色对勾。</summary>
public sealed class CheckBoxControl : Border
{
    public CheckBoxControl(bool isChecked, bool disabled, Action onToggle)
    {
        Width = 16;
        Height = 16;
        CornerRadius = new CornerRadius(4);
        VerticalAlignment = VerticalAlignment.Center;
        HorizontalAlignment = HorizontalAlignment.Left;
        Background = isChecked ? Palette.Accent : Brushes.Transparent;
        BorderBrush = isChecked ? Palette.Accent : Palette.Tertiary;
        BorderThickness = new Thickness(1);
        Opacity = disabled ? 0.5 : 1;
        if (isChecked)
        {
            Child = new Avalonia.Controls.Shapes.Path
            {
                Data = Geometry.Parse("M3,6.4 L5.2,8.6 L9,4.6"),
                Stroke = Brushes.White,
                StrokeThickness = 1.4,
                StrokeLineCap = PenLineCap.Round,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
        }
        if (disabled) return;
        Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand);
        PointerReleased += (_, e) =>
        {
            e.Handled = true;
            onToggle();
        };
    }
}

/// <summary>
/// 下拉菜单（Picker(.menu) 近似）：左侧标签 + 右侧当前值 + 上下箭头，点开是原生菜单。
/// 用 Avalonia MenuFlyout 承载选项，按钮本身自绘（离屏渲染也能画出来）。
/// </summary>
public sealed class DropdownControl : Border
{
    public DropdownControl(string? current, IReadOnlyList<string> options, Action<int> onSelect,
        bool enabled = true, double width = double.NaN)
    {
        CornerRadius = new CornerRadius(6);
        Background = Palette.GroupFill;
        BorderBrush = Palette.CardBorder;
        BorderThickness = new Thickness(0.5);
        Padding = new Thickness(8, 3, 6, 3);
        if (!double.IsNaN(width)) Width = width;
        HorizontalAlignment = HorizontalAlignment.Left;
        Opacity = enabled ? 1 : 0.55;

        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var label = Ui.Text(current ?? "", 11, maxLines: 1);
        label.TextTrimming = TextTrimming.CharacterEllipsis;
        Grid.SetColumn(label, 0);
        row.Children.Add(label);
        var chevron = Icons.ChevronDownUp(8, Palette.Secondary);
        chevron.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(chevron, 1);
        row.Children.Add(chevron);
        Child = row;

        if (!enabled) return;
        Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand);
        PointerEntered += (_, _) => Background = Palette.RowHover;
        PointerExited += (_, _) => Background = Palette.GroupFill;
        PointerReleased += (_, e) =>
        {
            e.Handled = true;
            var flyout = new MenuFlyout();
            for (var i = 0; i < options.Count; i++)
            {
                var index = i;
                var item = new MenuItem { Header = options[i] };
                item.Click += (_, _) => onSelect(index);
                flyout.Items.Add(item);
            }
            flyout.ShowAt(this);
        };
    }
}
