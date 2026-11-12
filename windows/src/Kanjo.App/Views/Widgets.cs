using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>跨页面共用的小组件（对应 Primitives.swift / ProjectActions.swift 里的视图部分）。</summary>
public static class Widgets
{
    /// <summary>徽章：小号胶囊。style：neutral / good / warn / bad。文字用实色，对比度 ≥ 4.5:1。</summary>
    public static Control Badge(string text, BadgeStyle style = BadgeStyle.Neutral, string? help = null)
    {
        var (fg, bg, border) = style switch
        {
            BadgeStyle.Good => (Palette.Good, Palette.GoodFill, Palette.Good),
            BadgeStyle.Warn => (Palette.WarnInk, Palette.WarnFill, Palette.WarnInk),
            BadgeStyle.Bad => (Palette.Bad, Palette.BadFill, Palette.Bad),
            _ => (Palette.Secondary, Palette.GroupFill, Palette.CardBorder),
        };
        var badge = new Border
        {
            Child = Ui.Text(text, 12, FontWeight.Medium, fg),
            Background = bg,
            BorderBrush = border,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(7, 1, 7, 1),
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        if (!string.IsNullOrEmpty(help)) ToolTip.SetTip(badge, help);
        return badge;
    }

    /// <summary>返回按钮：`‹ 标题`，链接色 + 手型光标（Windows 11 的返回是文字链接）。</summary>
    public static Control BackButton(string title, Action action)
    {
        var row = Ui.H(4);
        row.Children.Add(Icons.ChevronLeft(12, Palette.Link));
        row.Children.Add(Ui.Text(title, Type.CaptionSize, FontWeight.Medium, Palette.Link));
        return new Clickable(row, action, radius: 4, hand: true)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            Padding = new Thickness(0, 4, 6, 4),
        };
    }

    /// <summary>大号金额（Title 档，Display 字体 + 半粗）。</summary>
    public static TextBlock HeroAmount(string text, double size = 34, IBrush? color = null) =>
        Ui.Text(text, size, FontWeight.SemiBold, color ?? Palette.Foreground, family: Type.Rounded);

    /// <summary>说明文字（Caption 12、次要色、可折行）。</summary>
    public static TextBlock Note(string text) => Ui.Text(text, Type.CaptionSize, null, Palette.Secondary, wrap: true);

    /// <summary>行间细分割线（两端缩进）。</summary>
    public static Control RowDivider(double leading = Metrics.ListInset, double trailing = Metrics.ListInset,
        double opacity = 0.6) => new Border
    {
        Height = 1,
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
            toggle, Type.CaptionSize);

    /// <summary>一行 agent 色点（最多 3 个），悬停显示每个 agent 的金额和 token。</summary>
    public static Control AgentDots(IReadOnlyList<AgentCost> agents, string currency, double size = 8,
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

    /// <summary>状态块（schema 警告 / 刷新失败）：一律画成 InfoBar（圆角 + 状态图标）。</summary>
    public static Control StatusBlock(bool bad, IEnumerable<Control> content)
    {
        var box = Ui.V(3);
        foreach (var c in content) box.Children.Add(c);
        var border = new Border
        {
            Child = box,
            Background = bad ? Palette.BadFill : Palette.InfoBarFill,
            BorderBrush = bad ? Palette.Bad : Palette.InfoBarStroke,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(Metrics.GroupRadius),
            Padding = new Thickness(14, 10, 14, 10),
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        return border;
    }

    /// <summary>agent 图例：色点 + 名称，流式折行，按花费降序。</summary>
    public static Control Legend(IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> items,
        string currency)
    {
        var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
        for (var i = 0; i < items.Count; i++)
        {
            var (agent, label, cost, tokens) = items[i];
            var chip = Ui.H(5);
            chip.Margin = new Thickness(0, 0, 12, 4);
            chip.Children.Add(Ui.Dot(agent, 8));
            chip.Children.Add(Ui.Text(label, Type.CaptionSize, null, Palette.Secondary));
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
