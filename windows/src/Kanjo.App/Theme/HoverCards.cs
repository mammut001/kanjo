using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 悬停卡内容（对应 HoverCard.swift 里的几种卡片）。全部是纯静态构建，
/// 卡片外观（内边距 / 描边 / 阴影）由 <see cref="Chrome.HoverCardChrome"/> 负责。
/// </summary>
public static class HoverCards
{
    /// <summary>纯文本卡片（PlainHoverCard）。</summary>
    public static Control Plain(string text)
    {
        var block = Ui.Text(text, 11, null, Palette.Secondary, wrap: true, maxLines: 0);
        block.MaxWidth = HoverLayer.MaxCardWidth - 24;
        return block;
    }

    /// <summary>标题行：可选色点 + 标题 + 右侧金额。</summary>
    private static Control Header(string title, string? dotAgent, IBrush? dotColor, string? money,
        bool mono = false)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var left = Ui.H(6);
        if (dotColor is not null)
        {
            left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
            {
                Width = 7, Height = 7, Fill = dotColor, VerticalAlignment = VerticalAlignment.Center,
            });
        }
        else if (dotAgent is not null)
        {
            left.Children.Add(Ui.Dot(dotAgent, 7));
        }
        left.Children.Add(Ui.Text(title, 12, FontWeight.SemiBold, family: mono ? Type.Mono : null));
        Grid.SetColumn(left, 0);
        row.Children.Add(left);
        if (!string.IsNullOrEmpty(money))
        {
            var value = Ui.Text(money!, 12, FontWeight.SemiBold, family: Type.Rounded);
            value.TextAlignment = TextAlignment.Right;
            Grid.SetColumn(value, 2);
            row.Children.Add(value);
        }
        return row;
    }

    private static Control SubtitleLine(string? tokensText, string? subtitle, bool indented)
    {
        var line = Ui.H(6);
        if (!string.IsNullOrEmpty(tokensText)) line.Children.Add(Ui.Text(tokensText!, 10, null, Palette.Secondary));
        if (!string.IsNullOrEmpty(subtitle)) line.Children.Add(Ui.Text(subtitle!, 10, null, Palette.Secondary));
        if (indented) line.Margin = new Thickness(13, 0, 0, 0);
        return line;
    }

    /// <summary>一行：色点、名字、金额、token、下方细条。</summary>
    private static Control BarRow(string label, IBrush color, double cost, long tokens, double fraction,
        string currency, bool showZero = false)
    {
        var box = Ui.V(3);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto") };
        var left = Ui.H(6);
        left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
        {
            Width = 6, Height = 6, Fill = color, VerticalAlignment = VerticalAlignment.Center,
        });
        left.Children.Add(Ui.Text(label, 11, maxLines: 1));
        Grid.SetColumn(left, 0);
        row.Children.Add(left);
        if (cost > 0 || showZero)
        {
            var money = Ui.Text(Fmt.Money(cost, currency), 11, FontWeight.Medium, family: Type.Rounded);
            money.TextAlignment = TextAlignment.Right;
            money.Margin = new Thickness(8, 0, 0, 0);
            Grid.SetColumn(money, 2);
            row.Children.Add(money);
        }
        if (tokens > 0)
        {
            var count = Ui.Text(L10n.TrL(null, "overview.tokens_count", Fmt.Tokens(tokens)), 10, null,
                Palette.Secondary);
            count.TextAlignment = TextAlignment.Right;
            count.MinWidth = 62;
            count.Margin = new Thickness(6, 0, 0, 0);
            Grid.SetColumn(count, 3);
            row.Children.Add(count);
        }
        box.Children.Add(row);
        var bar = new QuotaBar(fraction, color, 3) { Margin = new Thickness(12, 0, 0, 0) };
        box.Children.Add(bar);
        return box;
    }

    /// <summary>agent 列表卡：AgentDots / 图例 / 热力条 / 日图 / 会话行共用。</summary>
    public static Control AgentRows(
        string title,
        string? dotAgent,
        double cost,
        long tokens,
        string currency,
        IReadOnlyList<HoverCardRowItem> rows,
        string? subtitle = null)
    {
        var content = Ui.V(8).WithMargin(0, 0, 0, 0);
        var head = Ui.V(1);
        head.Children.Add(Header(title, dotAgent, null, cost > 0 ? Fmt.Money(cost, currency) : null));
        head.Children.Add(SubtitleLine(
            tokens > 0 ? L10n.TrL(null, "overview.tokens_count", Fmt.Tokens(tokens)) : null,
            subtitle, dotAgent is not null));
        content.Children.Add(head);

        if (rows.Count > 0)
        {
            var list = Ui.V(3);
            foreach (var row in rows.Take(6))
            {
                list.Children.Add(BarRow(row.Label, Palette.Agent(row.Id), row.Cost, row.Tokens, row.Fraction, currency));
            }
            if (rows.Count > 6)
            {
                list.Children.Add(Ui.Text($"+{rows.Count - 6}", 10, null, Palette.Tertiary));
            }
            content.Children.Add(list);
        }
        return content;
    }

    /// <summary>模型卡：模型名 + 金额，下面是各类 token 的构成。</summary>
    public static Control Model(string model, string agent, double cost, Tokens tokens, string currency)
    {
        var content = Ui.V(8);
        var head = Ui.V(1);
        head.Children.Add(Header(model, null, Palette.Agent(agent), Fmt.Money(cost, currency), mono: true));
        head.Children.Add(SubtitleLine(
            L10n.TrL(null, "overview.tokens_count", Fmt.Tokens(tokens.Total)), null, true));
        content.Children.Add(head);

        var rows = HoverCardRowBuilder.TokenRows(tokens);
        if (rows.Count > 0)
        {
            var list = Ui.V(3);
            foreach (var row in rows)
            {
                list.Children.Add(TokenRow(row.Id, row.LabelKey, row.Count, row.Fraction, 1));
            }
            content.Children.Add(list);
        }
        return content;
    }

    private static IBrush TokenColor(string id) => id switch
    {
        "input" => Palette.TokenInput,
        "output" => Palette.TokenOutput,
        "cache_read" => Palette.TokenCacheRead,
        "cache_write" => Palette.TokenCacheWrite,
        _ => Palette.Secondary,
    };

    private static Control TokenRow(string id, string labelKey, long count, double fraction, double opacity)
    {
        var box = Ui.V(3);
        box.Opacity = opacity;
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto") };
        var left = Ui.H(6);
        left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
        {
            Width = 6, Height = 6, Fill = TokenColor(id), VerticalAlignment = VerticalAlignment.Center,
        });
        left.Children.Add(Ui.Text(L10n.Tr(labelKey), 11, maxLines: 1));
        Grid.SetColumn(left, 0);
        row.Children.Add(left);
        var value = Ui.Text(Fmt.Tokens(count), 10.5, FontWeight.Medium, family: Type.Rounded);
        value.TextAlignment = TextAlignment.Right;
        value.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetColumn(value, 2);
        row.Children.Add(value);
        var percent = Ui.Text(Fmt.Percent(fraction), 10, null, Palette.Secondary);
        percent.TextAlignment = TextAlignment.Right;
        percent.MinWidth = 42;
        percent.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(percent, 3);
        row.Children.Add(percent);
        box.Children.Add(row);
        box.Children.Add(new QuotaBar(fraction, TokenColor(id), 3) { Margin = new Thickness(12, 0, 0, 0) });
        return box;
    }

    /// <summary>token 构成卡：四类计费 token（thinking 是 output 子集，只作参考）。</summary>
    public static Control TokensBreakdown(Tokens tokens, string? highlightedType = null)
    {
        var content = Ui.V(8);
        var head = Ui.V(1);
        head.Children.Add(Header(L10n.Tr("project.section.tokens"), null, null, Fmt.Tokens(tokens.Total)));
        if (tokens.Thinking > 0)
        {
            head.Children.Add(Ui.Text(L10n.Tr("project.token.thinking") + ": " + Fmt.Tokens(tokens.Thinking), 10,
                null, Palette.Secondary));
        }
        content.Children.Add(head);
        foreach (var row in HoverCardRowBuilder.TokenRows(tokens))
        {
            var dim = highlightedType is not null && highlightedType != row.Id ? 0.45 : 1.0;
            content.Children.Add(TokenRow(row.Id, row.LabelKey, row.Count, row.Fraction, dim));
        }
        return content;
    }

    /// <summary>额度卡：agent 色点 + 档位名，每个窗口一行（细条、百分比、重置时间）。</summary>
    public static Control Quota(string agent, string planLabel, IReadOnlyList<QuotaRow> rows)
    {
        var content = Ui.V(9);
        content.Children.Add(Header(planLabel, agent, null, null));
        foreach (var row in rows)
        {
            var box = Ui.V(4);
            var line = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            line.Children.Add(Ui.Text(row.Title, 11, FontWeight.Medium));
            var pct = Ui.Text(row.Percent is { } p ? ((int)Math.Round(p, MidpointRounding.AwayFromZero)) + "%" : "—",
                11.5, FontWeight.SemiBold, row.Percent is null ? Palette.Tertiary : Palette.Foreground,
                family: Type.Rounded);
            pct.TextAlignment = TextAlignment.Right;
            pct.Margin = new Thickness(8, 0, 0, 0);
            Grid.SetColumn(pct, 1);
            line.Children.Add(pct);
            box.Children.Add(line);

            var color = row.Percent is null
                ? Palette.Secondary
                : SubscriptionValue.Level(row.Percent) switch
                {
                    QuotaLevel.Critical => Palette.Bad,
                    QuotaLevel.Warning => Palette.QuotaWarn,
                    _ => Palette.Agent(agent),
                };
            box.Children.Add(new QuotaBar((row.Percent ?? 0) / 100, color, 4));
            var detail = Ui.Text(row.Detail, 10, null, Palette.Secondary);
            detail.TextWrapping = TextWrapping.NoWrap;
            box.Children.Add(detail);
            content.Children.Add(box);
        }
        return content;
    }

    /// <summary>订阅价值说明卡：档位、账号、月费、账期用量、倍数说明。</summary>
    public static Control Subscription(SubscriptionRow row, string currency)
    {
        var content = Ui.V(6);
        var head = Header(row.PlanLabel, row.Agent, null, row.Multiplier is { } m ? Fmt.Multiple(m) : null);
        content.Children.Add(head);

        var lines = Ui.V(3);
        if (row.Account is { } account)
        {
            lines.Children.Add(KeyValue(L10n.Tr("overview.account"),
                string.IsNullOrEmpty(account.Name) ? account.Email : $"{account.Email} ({account.Name})"));
        }
        var price = Fmt.PerMonth(row.MonthlyPriceUsd, currency);
        var usage = Fmt.Money(row.Usage, currency);
        lines.Children.Add(KeyValue(L10n.Tr("settings.subscriptions.price"), price));
        lines.Children.Add(KeyValue(L10n.Tr("overview.cycle_usage"), usage));
        content.Children.Add(lines);

        var help = row.Multiplier is { } multiple
            ? L10n.TrL(null, "overview.sub_help_multiplier", row.PlanLabel, price, usage, Fmt.Multiple(multiple))
            : L10n.TrL(null, "overview.sub_help_unknown", row.PlanLabel, usage);
        content.Children.Add(Ui.Text(help, 10.5, null, Palette.Secondary, wrap: true));
        return content;
    }

    private static Control KeyValue(string label, string value)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        row.Children.Add(Ui.Text(label, 10.5, null, Palette.Secondary));
        var v = Ui.Text(value, 10.5, family: Type.Rounded);
        v.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(v, 1);
        row.Children.Add(v);
        return row;
    }
}
