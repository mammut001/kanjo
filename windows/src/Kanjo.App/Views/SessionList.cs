using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 会话列表（SessionRow.swift 的 SessionList）：可按 Started / Cost 排序、可切换升降序，
/// 默认只展示前 25 条；右上角是 attribution 的「?」说明。
/// </summary>
public sealed class SessionList : StackPanel
{
    public enum SortKey
    {
        Started,
        Cost,
    }

    private const int InitialLimit = 25;

    private readonly AppServices _services;
    private readonly IReadOnlyList<Session> _sessions;
    private readonly double _threshold;
    private readonly string _currency;
    private readonly string? _idPrefix;
    private readonly StackPanel _list = new() { Orientation = Orientation.Vertical };
    private SortKey _sort = SortKey.Started;
    private bool _descending = true;
    private bool _showAll;
    private Control? _popover;

    public SessionList(AppServices services, IReadOnlyList<Session> sessions, double threshold,
        string currency, string? idPrefix = null)
    {
        _services = services;
        _sessions = sessions;
        _threshold = threshold;
        _currency = currency;
        _idPrefix = idPrefix;
        Orientation = Orientation.Vertical;
        Spacing = 4;
        Children.Add(Header());
        Children.Add(_list);
        Rebuild();
    }

    private Control Header()
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto") };
        var segmented = new SegmentedControl(
            [L10n.Tr("session.sort.started"), L10n.Tr("session.sort.cost")],
            _sort == SortKey.Started ? 0 : 1,
            index =>
            {
                _sort = index == 0 ? SortKey.Started : SortKey.Cost;
                _showAll = false;
                Rebuild();
            })
        {
            Width = 130,
        };
        Grid.SetColumn(segmented, 0);
        row.Children.Add(segmented);

        var direction = new Clickable(
            Icons.SortArrow(_descending, 9, Palette.Secondary),
            () =>
            {
                _descending = !_descending;
                Rebuild();
            },
            _descending ? L10n.Tr("session.sort.descending") : L10n.Tr("session.sort.ascending"), radius: 4)
        {
            Margin = new Thickness(6, 0, 0, 0),
        };
        Grid.SetColumn(direction, 1);
        row.Children.Add(direction);

        var attribution = new Clickable(
            AddLabel(Ui.H(3)),
            TogglePopover,
            L10n.Tr("session.attribution_button_help"), radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        Grid.SetColumn(attribution, 3);
        row.Children.Add(attribution);
        return row;
    }

    private Control AddLabel(StackPanel row)
    {
        // Mac 的 Label 放进 .borderless 按钮后会被再淡一层；用 Muted 才能对上参考图的浅灰。
        row.Children.Add(Icons.QuestionCircle(9, Palette.Muted));
        row.Children.Add(Ui.Text(L10n.Tr("session.attribution_button"), 10.5, null, Palette.Muted));
        return row;
    }

    private void TogglePopover()
    {
        if (_popover is not null)
        {
            Children.Remove(_popover);
            _popover = null;
            return;
        }
        var body = Ui.V(8);
        body.Children.Add(Ui.Text(L10n.Tr("session.attribution_popover_title"), 12, FontWeight.SemiBold));
        foreach (var value in SessionAttributionInfo.AllKnown)
        {
            var item = Ui.V(1);
            item.Children.Add(Ui.Text(value, 11, FontWeight.SemiBold, family: Type.Mono));
            var explanation = Ui.Text(SessionAttributionInfo.Explanation(value, _threshold), 11, null,
                Palette.Secondary, wrap: true);
            explanation.MaxWidth = 276;
            item.Children.Add(explanation);
            body.Children.Add(item);
        }
        _popover = Chrome.HoverCardChrome(body) is var card && card is Border border
            ? SetWidth(border)
            : body;
        _popover.Margin = new Thickness(0, 6, 0, 4);
        _popover.HorizontalAlignment = HorizontalAlignment.Stretch;
        Children.Insert(1, _popover);
    }

    private static Control SetWidth(Border border)
    {
        border.Width = 300;
        border.HorizontalAlignment = HorizontalAlignment.Left;
        return border;
    }

    private List<Session> Sorted()
    {
        var list = _sort switch
        {
            SortKey.Started => _sessions.OrderBy(s => s.StartedDate ?? DateTimeOffset.MinValue).ToList(),
            _ => _sessions.OrderBy(s => s.Cost).ToList(),
        };
        if (_descending) list.Reverse();
        return list;
    }

    private void Rebuild()
    {
        _list.Children.Clear();
        if (_sessions.Count == 0)
        {
            _list.Children.Add(Ui.Text(L10n.Tr("session.empty"), 11, null, Palette.Secondary));
            return;
        }
        var sorted = Sorted();
        var shown = _showAll ? sorted : sorted.Take(InitialLimit).ToList();
        for (var i = 0; i < shown.Count; i++)
        {
            if (i > 0) _list.Children.Add(Widgets.RowDivider(0, 0));
            var hoverId = _idPrefix is null ? null : $"{_idPrefix}:session:{i}";
            _list.Children.Add(new SessionRowView(_services, shown[i], _threshold, _currency, hoverId));
        }
        if (sorted.Count > InitialLimit)
        {
            var button = Widgets.ShowAllButton(_showAll, sorted.Count, L10n.Tr("project.noun.sessions"), () =>
            {
                _showAll = !_showAll;
                Rebuild();
            });
            button.Margin = new Thickness(0, 4, 0, 0);
            _list.Children.Add(button);
        }
    }
}

/// <summary>
/// 一行会话（SessionRow）：标题 + 金额；agent · 时间 · 分支；attribution 徽章 + share + subagents，
/// 右侧模型列表。
/// </summary>
public sealed class SessionRowView : StackPanel
{
    public SessionRowView(AppServices services, Session session, double threshold, string currency,
        string? hoverId)
    {
        Orientation = Orientation.Vertical;
        Spacing = 3;
        // Mac：VStack(spacing: 3) + .padding(.vertical, 6)，行高约 68pt（含分隔线）。
        // Avalonia 的行高比 SF 紧，上下各留 10pt 才能落到同样的 68pt。
        Margin = new Thickness(0, 11, 0, 9);

        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Control title;
        if (!string.IsNullOrEmpty(session.Title))
        {
            title = Ui.Text(session.Title!, 12, maxLines: 2);
        }
        else
        {
            var untitled = Ui.Text(L10n.Tr("session.untitled"), 12, null, Palette.Secondary);
            untitled.FontStyle = FontStyle.Italic;
            title = untitled;
        }
        ToolTip.SetTip(title, session.Title ?? L10n.Tr("session.untitled"));
        Grid.SetColumn(title, 0);
        top.Children.Add(title);
        var cost = Ui.Text(Fmt.Money(session.Cost, currency), 12, FontWeight.Medium, family: Type.Rounded);
        cost.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(cost, 1);
        top.Children.Add(cost);
        Children.Add(top);

        var meta = new WrapPanel { Orientation = Orientation.Horizontal };
        {
            var agentLine = Ui.H(5);
            agentLine.Children.Add(Ui.Dot(session.Agent, 6));
            agentLine.Children.Add(Ui.Text(session.Label, 10.5, null, Palette.Secondary));
            agentLine.Children.Add(Ui.Text("·", 10.5, null, Palette.Secondary));
            agentLine.Children.Add(Ui.Text(Fmt.Timestamp(session.Started), 10.5, null, Palette.Secondary));
            if (!string.IsNullOrEmpty(session.Branch))
            {
                agentLine.Children.Add(Ui.Text("·", 10.5, null, Palette.Secondary));
                agentLine.Children.Add(Icons.Branch(8, Palette.Secondary));
                var branch = Ui.Text(session.Branch!, 10.5, null, Palette.Secondary, maxLines: 1);
                branch.TextTrimming = TextTrimming.CharacterEllipsis;
                agentLine.Children.Add(branch);
            }
            meta.Children.Add(agentLine);
            var rows = new List<HoverCardRowItem>
            {
                new(session.Agent, session.Label, session.Cost, session.Tokens.Total, 1.0),
            };
            var copy = session;
            if (hoverId is not null)
            {
                HoverLayer.Attach(agentLine, hoverId, () => HoverCards.AgentRows(copy.Label, copy.Agent, copy.Cost,
                    copy.Tokens.Total, currency, rows, Fmt.Timestamp(copy.Started)));
            }
            else
            {
                HoverLayer.Attach(agentLine, $"session:{session.Id}:agent", () => HoverCards.AgentRows(copy.Label,
                    copy.Agent, copy.Cost, copy.Tokens.Total, currency, rows, Fmt.Timestamp(copy.Started)));
            }
            ToolTip.SetTip(agentLine, TooltipBuilder.AgentLine(session.Label, session.Cost, session.Tokens.Total,
                currency));
        }
        Children.Add(meta);

        var bottom = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,*,Auto") };
        var split = session.Attribution == "split";
        var badge = Widgets.Badge(session.Attribution, split ? BadgeStyle.Warn : BadgeStyle.Neutral,
            SessionAttributionInfo.Explanation(session.Attribution, threshold));
        var badgeCell = new StackPanel { Orientation = Orientation.Horizontal };
        badgeCell.Children.Add(badge);
        Grid.SetColumn(badgeCell, 0);
        bottom.Children.Add(badgeCell);

        var share = Ui.Text(L10n.TrL(null, "session.share", Fmt.Percent(session.Share)), 10, null,
            Palette.Secondary);
        share.Margin = new Thickness(5, 0, 0, 0);
        ToolTip.SetTip(share, L10n.Tr("session.share_help"));
        Grid.SetColumn(share, 1);
        bottom.Children.Add(share);

        if (session.Subagents > 0)
        {
            var subs = Ui.Text(session.Subagents == 1
                ? L10n.TrL(null, "session.subagent.singular", session.Subagents)
                : L10n.TrL(null, "session.subagent.plural", session.Subagents), 10, null, Palette.Secondary);
            subs.Margin = new Thickness(5, 0, 0, 0);
            ToolTip.SetTip(subs, L10n.Tr("session.subagents_help"));
            Grid.SetColumn(subs, 2);
            bottom.Children.Add(subs);
        }

        // 模型列表占满剩下的宽度，超出时尾部省略（Mac: lineLimit(1) + truncationMode(.tail)）。
        var models = Ui.Text(string.Join(", ", session.Models), 9.5, null, Palette.Secondary,
            maxLines: 1, mono: true);
        models.TextAlignment = TextAlignment.Right;
        models.TextTrimming = TextTrimming.CharacterEllipsis;
        models.Margin = new Thickness(5, 0, 0, 0);
        ToolTip.SetTip(models, string.Join(", ", session.Models));
        var modelList = session.Models.ToList();
        HoverLayer.Attach(models, hoverId is null ? $"models:{session.Id}" : $"{hoverId}:models",
            () => ModelsCard(session.Agent, modelList));
        Grid.SetColumn(models, 3);
        bottom.Children.Add(models);
        Children.Add(bottom);
    }

    private static Control ModelsCard(string agent, IReadOnlyList<string> models)
    {
        var box = Ui.V(6);
        var head = Ui.H(5);
        head.Children.Add(Ui.Dot(agent, 7));
        head.Children.Add(Ui.Text(L10n.Tr("project.noun.models"), 12, FontWeight.SemiBold));
        box.Children.Add(head);
        var list = Ui.V(3);
        foreach (var model in models) list.Children.Add(Ui.Text(model, 11, null, family: Type.Mono));
        box.Children.Add(list);
        return box;
    }
}

/// <summary>
/// 分段控件（自绘胶囊）：Started / Cost、Source File / CLI 之类。
/// 和 SwiftUI 的 `.pickerStyle(.segmented)` 一样，每段等宽并铺满可用宽度（固定宽度时由调用方给 Width，
/// 比如会话列表的 Started/Cost 是 130pt）。
/// </summary>
public sealed class SegmentedControl : Border
{
    public SegmentedControl(IReadOnlyList<string> options, int selected, Action<int> onSelect, double fontSize = 10.5)
    {
        Padding = new Thickness(1.5);
        CornerRadius = new CornerRadius(8);
        Background = new SolidColorBrush(Palette.ForegroundColor, 0.06);
        HorizontalAlignment = HorizontalAlignment.Stretch;
        VerticalAlignment = VerticalAlignment.Center;

        var row = new Grid();
        for (var i = 0; i < options.Count; i++) row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        for (var i = 0; i < options.Count; i++)
        {
            var index = i;
            var isSelected = i == selected;
            // SwiftUI 的 segmented picker 每段文字都是 label 色（不是次要色），只有底色区分选中。
            var label = Ui.Text(options[i], fontSize, isSelected ? FontWeight.SemiBold : FontWeight.Normal,
                isSelected ? Palette.Foreground : Palette.Secondary);
            label.TextAlignment = TextAlignment.Center;

            var cell = new Grid();
            // 未选中段之间有一条细分隔线（SwiftUI 的分段控件也一样）。
            if (i > 0 && !isSelected && i - 1 != selected)
            {
                var separator = new Border
                {
                    Width = 0.5,
                    Background = new SolidColorBrush(Palette.ForegroundColor, 0.12),
                    VerticalAlignment = VerticalAlignment.Center,
                    Height = 11,
                    HorizontalAlignment = HorizontalAlignment.Left,
                };
                cell.Children.Add(separator);
            }
            var chip = new Border
            {
                Child = label,
                CornerRadius = new CornerRadius(6.5),
                Padding = new Thickness(6, 2.5, 6, 2.5),
                Background = isSelected ? Palette.CardBackground : Brushes.Transparent,
                Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
            };
            if (!isSelected)
            {
                chip.PointerEntered += (_, _) => chip.Background = Palette.RowHover;
                chip.PointerExited += (_, _) => chip.Background = Brushes.Transparent;
            }
            chip.PointerReleased += (_, _) => onSelect(index);
            cell.Children.Add(chip);
            Grid.SetColumn(cell, i);
            row.Children.Add(cell);
        }
        Child = row;
    }
}
