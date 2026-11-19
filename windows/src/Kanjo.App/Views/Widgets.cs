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

    /// <summary>agent 图例：色点 + 名称，按花费降序，尽量两行排完。</summary>
    public static Control Legend(IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> items,
        string currency) =>
        new AgentLegend(items, currency);
}

/// <summary>
/// 项目卡顶部的 agent 图例。色点到文字约 4pt，项与项约 10pt；
/// 360px 的样例放不进两行时先收字号，再收间距。
/// 悬停 id 与原来的 WrapPanel 一致（第一项 <c>overview:hover:legend</c>）。
/// </summary>
public sealed class AgentLegend : Panel
{
    private readonly record struct Style(double Font, double Gap, double Inner, double Dot);

    // 从宽松到紧。间距先保持 4 / 10，字号收到 8.5 时 9 个英文名能排成两行。
    private static readonly Style[] Fits =
    [
        new(9, 10, 4, 6),
        new(8.5, 10, 4, 6),
        new(8, 10, 4, 6),
        new(8, 8, 4, 6),
        new(8, 6, 4, 5),
        new(8, 4, 3, 5),
    ];

    private const double RowGap = 2;

    private readonly List<StackPanel> _chips = [];
    private readonly List<TextBlock> _labels = [];
    private readonly List<Control> _dots = [];
    private double _gap = 6;
    private int _applied = -1;

    public AgentLegend(IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> items, string currency)
    {
        for (var i = 0; i < items.Count; i++)
        {
            var (agent, label, cost, tokens) = items[i];
            var dot = Ui.Dot(agent, 6);
            var text = Ui.Text(label, 10, null, Palette.Secondary, maxLines: 1);
            var chip = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 4,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            chip.Children.Add(dot);
            chip.Children.Add(text);
            var rows = new List<HoverCardRowItem> { new(agent, label, cost, tokens, 1.0) };
            HoverLayer.Attach(chip, i == 0 ? "overview:hover:legend" : $"overview:hover:legend:{agent}",
                () => HoverCards.AgentRows(label, agent, cost, tokens, currency, rows));
            ToolTip.SetTip(chip, TooltipBuilder.AgentLine(label, cost, tokens, currency));
            Children.Add(chip);
            _chips.Add(chip);
            _labels.Add(text);
            _dots.Add(dot);
        }
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        var width = availableSize.Width;
        if (!double.IsFinite(width) || width <= 1) width = Metrics.RowContentWidth;

        // 每次都从最松的一档重新挑。前一轮测量时字体可能还没就绪（字形更宽），
        // 如果沿用那一档，后面变窄了也不会把间距放回 4 / 10。
        var chosen = Fits.Length - 1;
        for (var i = 0; i < Fits.Length; i++)
        {
            if (_applied != i) Apply(Fits[i]);
            _applied = i;
            foreach (var chip in _chips)
                chip.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            if (RowCount(width) <= 2)
            {
                chosen = i;
                break;
            }
        }
        _applied = chosen;
        _gap = Fits[chosen].Gap;
        return WrappedSize(width);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        double x = 0, y = 0, rowH = 0;
        var row = new List<Control>();
        void Flush()
        {
            double cx = 0;
            foreach (var chip in row)
            {
                var w = chip.DesiredSize.Width;
                var h = chip.DesiredSize.Height;
                chip.Arrange(new Rect(cx, y + Math.Max(0, (rowH - h) / 2), w, h));
                cx += w + _gap;
            }
            row.Clear();
        }

        foreach (var chip in _chips)
        {
            var w = chip.DesiredSize.Width;
            var h = chip.DesiredSize.Height;
            if (x > 0 && x + _gap + w > finalSize.Width + 0.5)
            {
                Flush();
                y += rowH + RowGap;
                x = 0;
                rowH = 0;
            }
            if (x > 0) x += _gap;
            x += w;
            rowH = Math.Max(rowH, h);
            row.Add(chip);
        }
        Flush();
        return finalSize;
    }

    private void Apply(Style style)
    {
        _gap = style.Gap;
        for (var i = 0; i < _chips.Count; i++)
        {
            _labels[i].FontSize = style.Font;
            _labels[i].LineHeight = Math.Round(style.Font * 1.35, 1);
            _chips[i].Spacing = style.Inner;
            _dots[i].Width = style.Dot;
            _dots[i].Height = style.Dot;
        }
    }

    private int RowCount(double width)
    {
        if (_chips.Count == 0) return 0;
        var rows = 1;
        double x = 0;
        foreach (var chip in _chips)
        {
            var w = chip.DesiredSize.Width;
            if (x > 0 && x + _gap + w > width + 0.5)
            {
                rows++;
                x = w;
            }
            else
            {
                x = x > 0 ? x + _gap + w : w;
            }
        }
        return rows;
    }

    private Size WrappedSize(double width)
    {
        double x = 0, y = 0, rowH = 0;
        foreach (var chip in _chips)
        {
            var w = chip.DesiredSize.Width;
            var h = chip.DesiredSize.Height;
            if (x > 0 && x + _gap + w > width + 0.5)
            {
                y += rowH + RowGap;
                x = 0;
                rowH = 0;
            }
            if (x > 0) x += _gap;
            x += w;
            rowH = Math.Max(rowH, h);
        }
        return new Size(width, y + rowH);
    }
}

public enum BadgeStyle
{
    Neutral,
    Good,
    Warn,
    Bad,
}
