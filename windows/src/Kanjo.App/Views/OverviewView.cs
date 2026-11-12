using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 总览页（批次 1 完整实现，几何与 Mac 参考截图对齐）：
/// HERO（总额 + 范围分段控件 + 摘要 + 范围说明）→ 订阅价值卡 → 马赛克 → 项目列表 →
/// 按模型 → 不在项目里 → 对账 + 页脚。
/// 所有「左内容 + 右对齐数值」的行都用 Grid 的 `*,Auto` 列，和 SwiftUI 的 Spacer 等价。
/// </summary>
public sealed class OverviewView : ScrollViewer
{
    private readonly AppServices _services;

    public OverviewView(AppServices services)
    {
        _services = services;
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto;
        Background = Brushes.Transparent;
        Content = Build();
    }

    /// <summary>页面内容本身（不含滚动容器）：截图 / 面板快照模式直接用。</summary>
    public static Control BuildContent(AppServices services)
    {
        var view = new OverviewView(services);
        var content = view.Content as Control ?? new Panel();
        view.Content = null;
        return content;
    }

    private Control Build()
    {
        var root = Ui.V(Metrics.SectionSpacing);

        if (_services.Report is not { } report)
        {
            root.Children.Add(ErrorOrLoading());
            root.Margin = new Thickness(Metrics.ContentInset, 16, Metrics.ContentInset, 10);
            return root;
        }

        var ctx = new RangeContext(report, _services.Settings.GetString(SettingsKeys.TimeRange));
        var filtered = ctx.Filtered();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));
        var hidden = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
        var arranged = ArrangeProjects(filtered, ctx.IsAll, pinned, hidden);

        var heroBlock = Ui.V(TextListSpacing);
        heroBlock.Children.Add(Hero(report, ctx, filtered, arranged.Visible, arranged.Hidden.Count).WithMargin(ContentInset, 0));
        if (report.Subscriptions is { Count: > 0 })
        {
            heroBlock.Children.Add(SubscriptionValueCard(report));
        }
        if (arranged.Visible.Any(p => p.Cost > 0))
        {
            heroBlock.Children.Add(Mosaic(report, arranged.Visible));
        }
        root.Children.Add(heroBlock);

        root.Children.Add(ProjectsSection(report, filtered, arranged, ctx));
        root.Children.Add(ModelsSection(report, filtered));
        root.Children.Add(BucketsSection(report, filtered));

        var footer = Ui.V(4);
        if (ctx.IsAll) footer.Children.Add(ReconciliationLine(report));
        footer.Children.Add(Ui.Text(
            L10n.TrL(null, "overview.generated_footer", Fmt.Timestamp(report.GeneratedAt), report.SchemaVersion),
            10, null, Palette.Tertiary));
        footer.Margin = new Thickness(ContentInset, 0, ContentInset, 0);
        root.Children.Add(footer);

        root.Margin = new Thickness(0, 16, 0, 10);
        return root;
    }

    /// <summary>Swift 的 `VStack(spacing: 14)`：hero 与订阅卡之间。</summary>
    private const double TextListSpacing = 14;

    private const double ContentInset = Metrics.ContentInset;

    private Control ErrorOrLoading()
    {
        var box = Ui.V(10);
        box.Margin = new Thickness(0, 28, 0, 0);
        if (_services.Error is { } error)
        {
            box.Children.Add(Ui.Text(L10n.Tr("menu.error_title"), 14, FontWeight.SemiBold, Palette.Bad));
            box.Children.Add(new Border
            {
                Child = Ui.Text(error, 11, null, Palette.Foreground, wrap: true, mono: true),
                Padding = new Thickness(10),
                CornerRadius = new CornerRadius(8),
                Background = Palette.BadFill,
            });
            box.Children.Add(Ui.Text(
                L10n.TrL(null, "settings.current_source", _services.DescribeSource()),
                10.5, null, Palette.Secondary, wrap: true));
            box.Children.Add(Ui.Text(L10n.Tr("menu.expected_export_json"), 10.5, null, Palette.Secondary, wrap: true));
            return box;
        }
        box.Children.Add(Ui.Text(L10n.Tr("common.loading"), 11, FontWeight.Medium, Palette.Secondary));
        box.Children.Add(Ui.Text(FirstScanHint.Explanation(), 11, null, Palette.Secondary, wrap: true));
        return box;
    }

    private sealed record Lists(IReadOnlyList<Project> Visible, IReadOnlyList<Project> Hidden, int Idle);

    private static Lists ArrangeProjects(FilteredReport filtered, bool isAll, ISet<string> pinned, ISet<string> hidden)
    {
        var sorted = filtered.Projects.OrderByDescending(p => p.Cost).ToList();
        var arranged = ProjectPrefs.Arrange(sorted, p => p.Id, pinned, hidden);
        var shown = isAll ? arranged.Visible : arranged.Visible.Where(p => p.HasUsage).ToList();
        return new Lists(shown.Select(p => p.Projected).ToList(),
            arranged.Hidden.Select(p => p.Projected).ToList(),
            arranged.Visible.Count - shown.Count);
    }

    // MARK: - HERO

    private Control Hero(UsageReport report, RangeContext ctx, FilteredReport filtered,
        IReadOnlyList<Project> visible, int hiddenCount)
    {
        var box = Ui.V(3);

        var title = Ui.H(4);
        var titleText = Ui.Text(L10n.Tr("overview.total_cost"), 11, null, Palette.Secondary);
        // Mac 的这一行是 11pt 文本 + 11pt 图标，行高按 11 算，不要被 34pt 金额撑开。
        title.Children.Add(titleText);
        if (report.CostNoteDisplayText is { } note)
        {
            title.Children.Add(Icons.InfoCircle(11, Palette.Secondary));
            ToolTip.SetTip(title, note);
        }
        var picker = new RangePicker(
            _services.Settings.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange),
            ctx.Range, ctx.ResetAvailable, ctx.CycleAvailable,
            raw =>
            {
                _services.Settings.Set(SettingsKeys.TimeRange, raw);
                _services.NotifyChanged();
            });

        // 「Total cost」靠左，范围分段控件靠右（Swift: Spacer(minLength: 4)）。
        box.Children.Add(Ui.Columns(
            (title, new GridLength(1, GridUnitType.Star)),
            (picker, GridLength.Auto)));

        // 大号金额：34pt semibold，圆体 + 等宽数字。
        var amount = Ui.Text(Fmt.Money(filtered.Cost, report.Currency), 34, FontWeight.SemiBold,
            family: Type.Rounded);
        box.Children.Add(amount);

        var rangeText = filtered.FirstActive is null && !ctx.IsAll
            ? L10n.Tr("overview.no_usage")
            : ShortDate.Range(filtered.FirstActive, filtered.LastActive, compact: true);
        var summary = OverviewSummaryText.Make(ctx.Range, rangeText, visible.Count, filtered.Sessions,
            filtered.Tokens, hiddenCount);
        box.Children.Add(Ui.Text(summary, 11, null, Palette.Secondary));

        if (ctx.CaptionResult is { } caption)
        {
            box.Children.Add(new RangeCaptionLine(caption));
        }
        return box;
    }

    private Control Mosaic(UsageReport report, IReadOnlyList<Project> visible)
    {
        var width = Metrics.PanelWidth - Metrics.MosaicInset * 2;
        var host = new Panel { Height = MosaicLayout.DefaultHeight };
        host.Children.Add(new MosaicView(visible, width, report.Currency, report.AgentLabels()));
        return host.WithMargin(Metrics.MosaicInset, 0);
    }

    // MARK: - 订阅价值

    private Control SubscriptionValueCard(UsageReport report)
    {
        var rows = SubscriptionValue.Rows(report, _services.Now);
        var order = SubscriptionOrder.Parse(_services.Settings.Str(SettingsKeys.SubscriptionOrder, ""));
        var ordered = SubscriptionOrder.Apply(order, rows);

        var expanded = _services.SubscriptionCardExpanded;
        var visible = SubscriptionOrder.Visible(ordered, expanded, limit: 3);

        var section = Ui.V(0);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.subscription_value")));
        // Mac 的 PanelSection(flat:) 在标题和第一行之间还有一点点间距。
        section.Children.Add(new Panel { Height = 1 });

        for (var i = 0; i < visible.Count; i++)
        {
            if (i > 0) section.Children.Add(Ui.Hairline(ContentInset, ContentInset));
            section.Children.Add(SubscriptionLine(report, visible[i]).WithMargin(ContentInset, 4.5));
        }

        // "Show N more" / "Show less"（Mac: overview.subscription_value.show_more / show_less）
        if (ordered.Count > 3)
        {
            section.Children.Add(Ui.Hairline(ContentInset, ContentInset));
            var label = expanded
                ? L10n.Tr("overview.subscription_value.show_less")
                : L10n.TrL(null, "overview.subscription_value.show_more", ordered.Count - 3);
            var toggle = Ui.LinkButton(label, () =>
            {
                _services.SubscriptionCardExpanded = !_services.SubscriptionCardExpanded;
                _services.NotifyChanged();
            });
            section.Children.Add(toggle.WithMargin(ContentInset, 6, ContentInset, 6));
        }

        section.Children.Add(Ui.Text(L10n.Tr("overview.subscription_value.explanation"), 10.5, null,
                Palette.Tertiary, wrap: true)
            .WithMargin(ContentInset, 3, ContentInset, 6));

        // 续费日提醒：「Renewal days not set for … · Set now」+「×」关闭。
        if (RenewalNudgeLine(report) is { } nudge) section.Children.Add(nudge);
        return section;
    }

    private Control? RenewalNudgeLine(UsageReport report)
    {
        var subs = report.Subscriptions;
        if (subs is null || subs.Count == 0) return null;
        var dismissed = RenewalNudge.ParseDismissed(
            _services.Settings.Str(SettingsKeys.RenewalNudgeDismissed, SettingsDefaults.RenewalNudgeDismissed));
        var pending = RenewalNudge.PendingAgents(subs, dismissed);
        if (pending.Count == 0) return null;

        var names = string.Join(", ", pending.Select(a => subs[a].PlanLabel));
        var text = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 10.5,
            FontFamily = Type.Font,
            LineHeight = Math.Round(10.5 * 1.34, 1),
        };
        text.Inlines!.Add(new Avalonia.Controls.Documents.Run(L10n.TrL(null, "overview.renewal_not_set", names))
        {
            Foreground = Palette.Secondary,
        });
        text.Inlines.Add(new Avalonia.Controls.Documents.Run(L10n.Tr("overview.set_now"))
        {
            Foreground = Palette.Accent,
        });

        var setNow = new Clickable(text, () => _services.RequestNavigate(Route.Settings), radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
        };

        var dismiss = Ui.LinkButton("×", () =>
        {
            _services.Settings.Set(SettingsKeys.RenewalNudgeDismissed,
                RenewalNudge.SerializeDismissed(dismissed.Union(pending)));
            _services.NotifyChanged();
        }, 11, Palette.Secondary);
        ToolTip.SetTip(dismiss, L10n.Tr("overview.dismiss_renewal_reminder"));

        var row = Ui.Columns(
            (setNow, new GridLength(1, GridUnitType.Star)),
            (dismiss, GridLength.Auto));
        row.Margin = new Thickness(ContentInset, 0, ContentInset, 6);
        return row;
    }

    /// <summary>一行：色点 + 名称 + 月费 …… 用量 + 「·」+ 倍数（右侧两列）。</summary>
    private Control SubscriptionLine(UsageReport report, SubscriptionRow row, DateTimeOffset? now = null)
    {
        var box = Ui.V(2);

        var left = Ui.H(5);
        left.Children.Add(Ui.Dot(row.Agent));
        var plan = Ui.Text(row.PlanLabel, 12);
        plan.VerticalAlignment = VerticalAlignment.Center;
        left.Children.Add(plan);
        left.Children.Add(Ui.Text($"· {Fmt.PerMonth(row.MonthlyPriceUsd, report.Currency)}", 11, null, Palette.Secondary));
        if (row.ExtraUsageEnabled)
        {
            left.Children.Add(Badge(L10n.Tr("overview.extra_usage_on"), warn: true,
                L10n.Tr("overview.extra_usage_help")));
        }

        var amount = Ui.Text(Fmt.Money(row.Usage, report.Currency), 12, FontWeight.Medium);
        amount.TextAlignment = TextAlignment.Right;
        var dot = Ui.Text("·", 11, null, Palette.Tertiary);
        var multiple = Ui.Text(Fmt.Multiple(row.Multiplier), 11.5, FontWeight.Medium, Palette.Secondary);
        multiple.TextAlignment = TextAlignment.Right;
        multiple.MinWidth = 42;

        var top = Ui.Columns(
            (left, new GridLength(1, GridUnitType.Star)),
            (amount, GridLength.Auto),
            (dot.WithMargin(6, 0, 4, 0), GridLength.Auto),
            (multiple, GridLength.Auto));
        box.Children.Add(top);

        if (report.Subscriptions is { } subs && subs.TryGetValue(row.Agent, out var sub))
        {
            var timezone = RangeEngine.TimezoneOf(report);
            var caption = Fmt.CycleCaption(sub, timezone, now ?? _services.Now);
            var captionText = Ui.Text(caption, 10, null, Palette.Secondary, wrap: true)

                .WithMargin(11, 0, 0, 0);
            if (SubscriptionValue.NeedsRenewalDay(sub)) ToolTip.SetTip(captionText, SubscriptionValue.AssumedDayHelp);
            else ToolTip.SetTip(captionText, Fmt.CycleDates(sub, timezone));
            box.Children.Add(captionText);
        }
        return box;
    }

    // MARK: - 项目列表

    private Control ProjectsSection(UsageReport report, FilteredReport filtered, Lists lists, RangeContext ctx)
    {
        var section = Ui.V(0);
        section.Children.Add(SectionHeader(L10n.Tr("settings.section.projects")));

        var legend = LegendAgents(filtered);
        if (legend.Count > 0)
        {
            section.Children.Add(Legend(legend, report.Currency).WithMargin(ContentInset, 2, ContentInset - 8, 6));
        }

        if (lists.Visible.Count == 0)
        {
            var text = report.Projects.Count == 0
                ? L10n.Tr("overview.projects.empty")
                : lists.Idle > 0
                    ? L10n.Tr("overview.projects.no_usage_range")
                    : L10n.Tr("overview.projects.all_hidden");
            section.Children.Add(Ui.Text(text, 11, null, Palette.Secondary).WithMargin(ContentInset, 8));
        }

        var heatEnd = HeatEndDate(report);
        var timezone = RangeEngine.TimezoneOf(report);
        var labels = report.AgentLabels();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));

        for (var i = 0; i < lists.Visible.Count; i++)
        {
            if (i > 0) section.Children.Add(Ui.Hairline(ContentInset, ContentInset));
            section.Children.Add(ProjectRow(lists.Visible[i], report.Currency, heatEnd, timezone, labels,
                pinned.Contains(lists.Visible[i].Id)));
        }

        if (lists.Hidden.Count > 0)
        {
            if (lists.Visible.Count > 0) section.Children.Add(Ui.Hairline(ContentInset, ContentInset));
            section.Children.Add(HiddenFooter(report, lists.Hidden));
        }
        if (!ctx.IsAll && lists.Idle > 0)
        {
            section.Children.Add(Ui.Text(
                lists.Idle == 1
                    ? L10n.TrL(null, "overview.projects.idle.singular", lists.Idle)
                    : L10n.TrL(null, "overview.projects.idle.plural", lists.Idle),
                10.5, null, Palette.Tertiary).WithMargin(ContentInset, 6));
        }
        return section;
    }

    private static IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> LegendAgents(FilteredReport filtered)
    {
        var cost = new Dictionary<string, double>(StringComparer.Ordinal);
        var tokens = new Dictionary<string, long>(StringComparer.Ordinal);
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var p in filtered.Projects)
        {
            foreach (var a in p.ByAgent)
            {
                cost[a.Agent] = cost.GetValueOrDefault(a.Agent) + a.Cost;
                tokens[a.Agent] = tokens.GetValueOrDefault(a.Agent) + a.Tokens.Total;
                if (!labels.TryGetValue(a.Agent, out var existing) || existing == a.Agent) labels[a.Agent] = a.Label;
            }
        }
        return cost.Keys.Union(tokens.Keys, StringComparer.Ordinal)
            .Where(k => cost.GetValueOrDefault(k) > 0 || tokens.GetValueOrDefault(k) > 0)
            .OrderByDescending(k => cost.GetValueOrDefault(k))
            .ThenBy(k => k, StringComparer.Ordinal)
            .Select(k => (k, labels.GetValueOrDefault(k) ?? AgentColors.Label(k),
                cost.GetValueOrDefault(k), tokens.GetValueOrDefault(k)))
            .ToList();
    }

    /// <summary>agent 图例：色点 + 名称，流式折行，按花费降序。</summary>
    private static Control Legend(IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> items,
        string currency)
    {
        var wrap = new WrapPanel { Orientation = Orientation.Horizontal };
        foreach (var (agent, label, cost, tokens) in items)
        {
            var chip = Ui.H(4);
            chip.Margin = new Thickness(0, 0, 9, 3);
            chip.Children.Add(Ui.Dot(agent));
            chip.Children.Add(Ui.Text(label, 10, null, Palette.Secondary));
            ToolTip.SetTip(chip, TooltipBuilder.AgentLine(label, cost, tokens, currency));
            wrap.Children.Add(chip);
        }
        return wrap;
    }

    /// <summary>热力条的结束日期：generated_at → totals.last_active → now。</summary>
    private DateTimeOffset HeatEndDate(UsageReport report)
    {
        var timezone = RangeEngine.TimezoneOf(report);
        if (ReportDates.ParseTimestamp(report.GeneratedAt) is { } generated) return generated;
        if (ReportDates.ParseDay(report.Totals.LastActive) is { } day) return Time.AtDay(timezone, day);
        return _services.Now;
    }

    /// <summary>
    /// 项目行，两行：名称 + agent 色点 + local / path missing 标签 …… 金额（右上）；
    /// sessions · tokens · 最近活跃 …… 8 周热力条（右下）。悬停整行高亮。
    /// </summary>
    private Control ProjectRow(Project project, string currency, DateTimeOffset heatEnd, TimeZoneInfo timezone,
        IReadOnlyDictionary<string, string> labels, bool pinned)
    {
        var row = new Border
        {
            Padding = new Thickness(ContentInset, Metrics.RowPadV, ContentInset, Metrics.RowPadV),
            CornerRadius = new CornerRadius(Metrics.RowRadius),
            Background = Brushes.Transparent,
            Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
            Margin = new Thickness(0, 0, 0, 0),
        };
        ToolTip.SetTip(row, project.Id);

        var box = Ui.V(3);

        var topLeft = Ui.H(6);
        if (pinned)
        {
            topLeft.Children.Add(Icons.Pin(8.5, Palette.Pin));
            ToolTip.SetTip(topLeft.Children[^1], L10n.Tr("overview.badge.pinned"));
        }
        topLeft.Children.Add(Ui.Text(project.Name, 12.5, FontWeight.Medium));
        var used = project.ByAgent
            .Where(a => a.Sessions > 0 || a.Cost > 0 || a.Tokens.Total > 0)
            .OrderByDescending(a => a.Cost)
            .ToList();
        if (used.Count > 0)
        {
            var dots = Ui.H(3);
            foreach (var agent in used.Take(3)) dots.Children.Add(Ui.Dot(agent.Agent));
            ToolTip.SetTip(dots, string.Join("\n", TooltipBuilder.AgentLines(used, currency)));
            topLeft.Children.Add(dots);
        }
        if (project.PathMissing)
        {
            topLeft.Children.Add(Badge(L10n.Tr("overview.badge.path_missing"), warn: true,
                L10n.Tr("overview.badge.path_missing_help")));
        }
        if (project.Remote is null)
        {
            topLeft.Children.Add(Badge(L10n.Tr("overview.badge.local"), warn: false,
                L10n.Tr("overview.badge.local_help")));
        }

        var top = Ui.Columns(
            (topLeft, new GridLength(1, GridUnitType.Star)),
            (Ui.Text(Fmt.Money(project.Cost, currency), 12.5, FontWeight.Medium), GridLength.Auto));
        box.Children.Add(top);

        var sessions = project.Sessions == 1
            ? L10n.TrL(null, "overview.row.subtitle.singular", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive))
            : L10n.TrL(null, "overview.row.subtitle.plural", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive));
        var subtitle = Ui.Text(sessions, 10.5, null, Palette.Secondary);
        ToolTip.SetTip(subtitle, L10n.TrL(null, "overview.row.last_active", Fmt.Day(project.LastActive)));

        var weeks = HeatStrip.Weekly(project.ByDay, heatEnd,
            DominantAgent.Of(project.ByAgent)?.Agent ?? project.ByAgent.FirstOrDefault()?.Agent ?? "unknown",
            HeatStrip.DefaultWeeks, timezone);
        var strip = new HeatStripView(weeks, currency, labels);

        var bottom = Ui.Columns(
            (subtitle, new GridLength(1, GridUnitType.Star)),
            (strip, GridLength.Auto));
        box.Children.Add(bottom);

        row.Child = box;
        row.PointerEntered += (_, _) => row.Background = Palette.RowHover;
        row.PointerExited += (_, _) => row.Background = Brushes.Transparent;
        return row;
    }

    private static Control Badge(string text, bool warn, string? help)
    {
        var badge = new Border
        {
            Child = Ui.Text(text, 9, FontWeight.Medium, warn ? Palette.WarnInk : Palette.Secondary),
            Background = warn ? Palette.WarnFill : Palette.GroupFill,
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(5, 1, 5, 1),
            VerticalAlignment = VerticalAlignment.Center,
        };
        if (!string.IsNullOrEmpty(help)) ToolTip.SetTip(badge, help);
        return badge;
    }

    private Control HiddenFooter(UsageReport report, IReadOnlyList<Project> hidden)
    {
        var cost = hidden.Sum(p => p.Cost);
        var row = Ui.H(4);
        row.Margin = new Thickness(ContentInset, 8, ContentInset, 8);
        row.Children.Add(Ui.Text(
            L10n.TrL(null, "overview.hidden_footer", hidden.Count, Fmt.Money(cost, report.Currency)),
            10.5, null, Palette.Secondary));
        ToolTip.SetTip(row, string.Join("\n", hidden.Select(p => p.Name)));
        return row;
    }

    // MARK: - 按模型

    private Control ModelsSection(UsageReport report, FilteredReport filtered)
    {
        var models = ModelAggregation.Aggregate(filtered);
        var section = Ui.V(0);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.by_model")));
        if (models.Count == 0)
        {
            section.Children.Add(Ui.Text(L10n.Tr("overview.models.no_usage_range"), 11, null, Palette.Secondary)
                .WithMargin(ContentInset, 8));
            return section;
        }

        foreach (var model in models.Take(8))
        {
            section.Children.Add(ModelRow(model, report.Currency));
        }
        if (models.Count > 8)
        {
            section.Children.Add(Ui.LinkButton(
                L10n.TrL(null, "overview.models.more", models.Count - 8),
                () => _services.ModelsExpanded = !_services.ModelsExpanded)
                .WithMargin(ContentInset, 6));
        }
        return section;
    }

    /// <summary>模型行：色点 + 模型名 + [estimated] …… tokens + 金额（右侧相邻，间距 6）。</summary>
    private static Control ModelRow(ModelCost model, string currency)
    {
        var left = Ui.H(6);
        left.Children.Add(Ui.Dot(model.Agent));
        left.Children.Add(Ui.Text(model.Model, 11.5, null, Palette.Foreground, mono: true));
        if (model.Estimated)
        {
            left.Children.Add(Badge(L10n.Tr("project.estimated"), warn: true, L10n.Tr("project.estimated_help")));
        }

        // Mac：Spacer(minLength: 8) 之后 tokens 与 cost 紧挨着，间距 6。
        var tokens = Ui.Text(Fmt.Tokens(model.Tokens.Total), 11, FontWeight.Medium);
        tokens.TextAlignment = TextAlignment.Right;
        var cost = Ui.Text(Fmt.Money(model.Cost, currency), 10.5, null, Palette.Secondary)
            .WithMargin(6, 0, 0, 0);
        cost.TextAlignment = TextAlignment.Right;

        var row = Ui.Columns(
            (left, new GridLength(1, GridUnitType.Star)),
            (tokens, GridLength.Auto),
            (cost, GridLength.Auto));
        row.Margin = new Thickness(ContentInset, 6, ContentInset, 6);
        ToolTip.SetTip(row, TooltipBuilder.ModelTooltip(model.Model, model.Agent, model.Cost, model.Tokens.Total, currency));
        return row;
    }

    // MARK: - 不在项目里

    private Control BucketsSection(UsageReport report, FilteredReport filtered)
    {
        var section = Ui.V(0);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.not_in_project")));

        section.Children.Add(BucketRow(L10n.Tr("overview.unattributed"), L10n.Tr("overview.unattributed_desc"),
            filtered.Unattributed.Sessions, Fmt.Money(filtered.Unattributed.Cost, report.Currency)));
        section.Children.Add(BucketRow(L10n.Tr("overview.excluded"), L10n.Tr("overview.excluded_desc"),
            filtered.Excluded.Sessions, Fmt.Money(filtered.Excluded.Cost, report.Currency)));

        if (report.Buckets.ParseFailed.Sessions > 0)
        {
            section.Children.Add(new ParseFailedRow(report.Buckets.ParseFailed));
        }
        return section;
    }

    /// <summary>桶行：名称 …… sessions + 金额（右对齐）。</summary>
    private static Control BucketRow(string name, string desc, int sessions, string value)
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(ContentInset, 7, ContentInset, 7);

        var count = sessions == 1
            ? L10n.TrL(null, "overview.count.session.singular", sessions)
            : L10n.TrL(null, "overview.count.session.plural", sessions);
        var sessionsText = Ui.Text(count, 10.5, null, Palette.Secondary);
        sessionsText.TextAlignment = TextAlignment.Right;

        var valueText = Ui.Text(value, 12, FontWeight.Medium);
        valueText.TextAlignment = TextAlignment.Right;
        valueText.MinWidth = 52;

        box.Children.Add(Ui.Columns(
            (Ui.Text(name, 12), new GridLength(1, GridUnitType.Star)),
            (sessionsText, GridLength.Auto),
            (valueText.WithMargin(8, 0, 0, 0), GridLength.Auto)));
        box.Children.Add(Ui.Text(desc, 10, null, Palette.Secondary, wrap: true, maxLines: 2));
        return box;
    }

    // MARK: - 对账

    private static Control ReconciliationLine(UsageReport report)
    {
        var rec = new Reconciliation(report);
        var line = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 4,
            // Mac：ReconciliationView 直接在 .padding(.horizontal, listInset) 里，
            // 外层已经给了 ContentInset，这里不能再加，否则整行会缩进。
            Margin = new Thickness(0),
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        if (rec.Ok)
        {
            line.Children.Add(Icons.CheckCircle(10, Palette.Good));
            line.Children.Add(Ui.Text(L10n.TrL(null, "overview.reconciled", Fmt.Money(rec.Cost.Reported, report.Currency)),
                10.5, null, Palette.Good));
            ToolTip.SetTip(line, L10n.Tr("reconcile.contract_invariant"));
            return line;
        }
        line.Children.Add(Icons.WarnTriangle(10, Palette.Bad));
        line.Children.Add(Ui.Text(L10n.Tr("overview.reconcile_failed"), 12, FontWeight.SemiBold, Palette.Bad));
        return line;
    }

    // MARK: - 版式

    /// <summary>一节的小号全大写标题（左对齐，左右留 ContentInset）。</summary>
    private static Control SectionHeader(string title) =>
        Ui.SectionTitle(title).WithMargin(ContentInset, 0, ContentInset, 4);
}
