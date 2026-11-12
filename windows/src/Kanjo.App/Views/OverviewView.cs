using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 总览页（批次 1 完整实现）：HERO（总额 + 范围分段控件 + 摘要行 + 范围说明）、
/// 成本说明、订阅价值卡、马赛克、项目列表（名称 / agent 色点 / 金额 / sessions·tokens·最近活跃 / 热力条）、
/// 按模型、不在项目里、对账与页脚。项目详情 / 桶页 / 磁盘 / 设置在后续批次。
/// </summary>
public sealed class OverviewView : ScrollViewer
{
    private readonly AppServices _services;

    public OverviewView(AppServices services)
    {
        _services = services;
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto;
        Content = Build();
    }

    /// <summary>页面内容本身（不含滚动容器）：截图 / 打印 / 面板快照模式直接用。</summary>
    public static Control BuildContent(AppServices services)
    {
        var view = new OverviewView(services);
        var content = view.Content as Control ?? new Panel();
        // 从 ScrollViewer 上摘下来，才能挂到别的容器（快照模式不滚动）。
        view.Content = null;
        return content;
    }

    private Control Build()
    {
        var root = Ui.V(Metrics.SectionSpacing);
        root.Margin = new Thickness(Metrics.FlatPagePadding, 16, Metrics.FlatPagePadding, 10);

        if (_services.Report is not { } report)
        {
            root.Children.Add(ErrorOrLoading());
            return root;
        }

        var ctx = new RangeContext(report, _services.Settings.GetString(SettingsKeys.TimeRange));
        var filtered = ctx.Filtered();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));
        var hidden = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
        var arranged = ArrangeProjects(filtered, ctx.IsAll, pinned, hidden);

        var heroBlock = Ui.V(14);
        heroBlock.Children.Add(Hero(report, ctx, filtered, arranged.Visible, arranged.Hidden.Count));
        if (report.Subscriptions is { Count: > 0 })
        {
            heroBlock.Children.Add(SubscriptionValueCard(report));
        }
        if (arranged.Visible.Any(p => p.Cost > 0))
        {
            heroBlock.Children.Add(MosaicViewFor(arranged.Visible));
        }
        root.Children.Add(heroBlock);

        root.Children.Add(ProjectsSection(report, filtered, arranged, ctx));
        root.Children.Add(ModelsSection(report, filtered));
        root.Children.Add(BucketsSection(report, filtered));

        var footer = Ui.V(8);
        if (ctx.IsAll) footer.Children.Add(ReconciliationLine(report));
        footer.Children.Add(Ui.Text(
            L10n.TrL(null, "overview.generated_footer", Fmt.Timestamp(report.GeneratedAt), report.SchemaVersion),
            10, null, Palette.Tertiary));
        footer.Margin = new Thickness(Metrics.ListInset, 0, Metrics.ListInset, 0);
        root.Children.Add(footer);
        return root;
    }

    private Control ErrorOrLoading()
    {
        var box = Ui.V(10);
        box.Margin = new Thickness(Metrics.PagePadding, 40, Metrics.PagePadding, 0);
        if (_services.Error is { } error)
        {
            box.Children.Add(Ui.Text(L10n.Tr("menu.error_title"), 14, FontWeight.SemiBold, Palette.Bad));
            var err = Ui.Text(error, 11, null, Palette.Foreground, wrap: true, mono: true);
            var errBox = new Border
            {
                Child = err,
                Padding = new Thickness(10),
                CornerRadius = new CornerRadius(8),
                Background = Palette.BadFill,
            };
            box.Children.Add(errBox);
            box.Children.Add(Ui.Text(
                L10n.TrL(null, "settings.current_source", _services.DescribeSource()), 10.5, null, Palette.Secondary, wrap: true));
            box.Children.Add(Ui.Text(
                L10n.Tr("menu.expected_export_json"), 10.5, null, Palette.Secondary, wrap: true));
            return box;
        }
        box.Children.Add(Ui.Text(L10n.Tr("common.loading"), 11, FontWeight.Medium, Palette.Secondary));
        box.Children.Add(Ui.Text(FirstScanHint.Explanation(), 11, null, Palette.Secondary, wrap: true));
        return box;
    }

    private sealed record Lists(IReadOnlyList<Project> Visible, IReadOnlyList<Project> Hidden, int Idle);

    /// <summary>列表里的项目都是按当前范围过滤后的值；按范围内 cost 降序，置顶在前，隐藏的分出去。</summary>
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

    private Control Hero(UsageReport report, RangeContext ctx, FilteredReport filtered, IReadOnlyList<Project> visible, int hiddenCount)
    {
        var box = Ui.V(3);
        box.Margin = new Thickness(Metrics.ListInset, 0, Metrics.ListInset, 0);

        var title = Ui.Text(L10n.Tr("overview.total_cost"), 11, null, Palette.Secondary);
        var titleRow = Ui.H(4);
        titleRow.Children.Add(title);
        if (report.CostNoteDisplayText is { } note)
        {
            titleRow.Children.Add(Icons.InfoCircle(10, Palette.Secondary));
            ToolTip.SetTip(titleRow, note);
        }
        var picker = new RangePicker(
            _services.Settings.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange),
            ctx.Range, ctx.ResetAvailable, ctx.CycleAvailable,
            raw =>
            {
                _services.Settings.Set(SettingsKeys.TimeRange, raw);
                _services.NotifyChanged();
            });

        var headerRow = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        Grid.SetColumn(titleRow, 0);
        Grid.SetColumn(picker, 2);
        headerRow.Children.Add(titleRow);
        headerRow.Children.Add(picker);
        box.Children.Add(headerRow);

        var amount = Ui.Text(Fmt.Money(filtered.Cost, report.Currency), 34, FontWeight.SemiBold);
        box.Children.Add(amount);

        var rangeText = filtered.FirstActive is null && !ctx.IsAll
            ? L10n.Tr("overview.no_usage")
            : ShortDate.Range(filtered.FirstActive, filtered.LastActive, compact: true);
        var summary = OverviewSummaryText.Make(ctx.Range, rangeText, visible.Count, filtered.Sessions, filtered.Tokens, hiddenCount);
        box.Children.Add(Ui.Text(summary, 11, null, Palette.Secondary));

        if (ctx.CaptionResult is { } caption)
        {
            box.Children.Add(new RangeCaptionLine(caption));
        }
        return box;
    }

    private static Control MosaicViewFor(IReadOnlyList<Project> visible)
    {
        var host = new Panel
        {
            Height = MosaicView.Height_,
            Margin = new Thickness(Metrics.ListInset - Metrics.FlatPagePadding, 0, Metrics.ListInset - Metrics.FlatPagePadding, 0),
        };
        host.Children.Add(new MosaicView(visible, Metrics.PanelWidth - Metrics.ListInset * 2));
        return host;
    }

    // MARK: - 订阅价值

    private Control SubscriptionValueCard(UsageReport report)
    {
        var now = _services.Now;
        var rows = SubscriptionValue.Rows(report, now);
        var order = SubscriptionOrder.Parse(_services.Settings.Str(SettingsKeys.SubscriptionOrder, ""));
        var ordered = SubscriptionOrder.Apply(order, rows);
        var visible = SubscriptionOrder.Visible(ordered, expanded: false, limit: 3);

        var section = Section(L10n.Tr("overview.section.subscription_value"));
        for (var i = 0; i < visible.Count; i++)
        {
            if (i > 0) section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            section.Children.Add(SubscriptionLine(report, visible[i], _services.Now));
        }
        section.Children.Add(WithMargin(
            Ui.Text(L10n.Tr("overview.subscription_value.explanation"), 10.5, null, Palette.Tertiary, wrap: true),
            Metrics.ListInset, 3, Metrics.ListInset, 6));
        return section;
    }

    private static Control SubscriptionLine(UsageReport report, SubscriptionRow row, DateTimeOffset now)
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(Metrics.ListInset, 4, Metrics.ListInset, 4);

        var top = Ui.H(5);
        top.Children.Add(Ui.Dot(row.Agent));
        top.Children.Add(Ui.Text(row.PlanLabel, 12));
        top.Children.Add(Ui.Text($"· {Fmt.PerMonth(row.MonthlyPriceUsd, report.Currency)}", 11, null, Palette.Secondary));
        if (row.ExtraUsageEnabled)
        {
            var badge = new Border
            {
                Child = Ui.Text(L10n.Tr("overview.extra_usage_on"), 9, FontWeight.Medium, Palette.WarnInk),
                Background = Palette.WarnFill,
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(5, 1, 5, 1),
            };
            ToolTip.SetTip(badge, L10n.Tr("overview.extra_usage_help"));
            top.Children.Add(badge);
        }
        top.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        top.Children.Add(Ui.Text(Fmt.Money(row.Usage, report.Currency), 12, FontWeight.Medium));
        top.Children.Add(Ui.Text("·", 11, null, Palette.Tertiary));
        var multiple = Ui.Text(Fmt.Multiple(row.Multiplier), 11.5, FontWeight.Medium, Palette.Secondary);
        multiple.MinWidth = 42;
        multiple.TextAlignment = TextAlignment.Right;
        top.Children.Add(multiple);
        box.Children.Add(top);

        if (report.Subscriptions is { } subs && subs.TryGetValue(row.Agent, out var sub))
        {
            var timezone = RangeEngine.TimezoneOf(report);
            var caption = Fmt.CycleCaption(sub, timezone, now);
            var captionText = Ui.Text(caption, 10, null, Palette.Secondary, wrap: true);
            captionText.Margin = new Thickness(11, 0, 0, 0);
            if (SubscriptionValue.NeedsRenewalDay(sub)) ToolTip.SetTip(captionText, SubscriptionValue.AssumedDayHelp);
            else ToolTip.SetTip(captionText, Fmt.CycleDates(sub, timezone));
            box.Children.Add(captionText);
        }
        return box;
    }

    // MARK: - 项目列表

    private Control ProjectsSection(UsageReport report, FilteredReport filtered, Lists lists, RangeContext ctx)
    {
        var section = Section(L10n.Tr("settings.section.projects"));
        var legend = LegendAgents(filtered);
        if (legend.Count > 0)
        {
            var legendRow = new WrapPanel { Orientation = Orientation.Horizontal, ItemWidth = double.NaN };
            legendRow.Margin = new Thickness(Metrics.ListInset, 2, Metrics.ListInset, 6);
            foreach (var (agent, label, cost, tokens) in legend)
            {
                var chip = Ui.H(4);
                chip.Margin = new Thickness(0, 0, 9, 4);
                chip.Children.Add(Ui.Dot(agent));
                chip.Children.Add(Ui.Text(label, 10, null, Palette.Secondary));
                ToolTip.SetTip(chip, TooltipBuilder.AgentLine(label, cost, tokens));
                legendRow.Children.Add(chip);
            }
            section.Children.Add(legendRow);
        }

        if (lists.Visible.Count == 0)
        {
            var text = report.Projects.Count == 0
                ? L10n.Tr("overview.projects.empty")
                : lists.Idle > 0
                    ? L10n.Tr("overview.projects.no_usage_range")
                    : L10n.Tr("overview.projects.all_hidden");
            var empty = Ui.Text(text, 11, null, Palette.Secondary);
            empty.Margin = new Thickness(Metrics.ListInset, 8, Metrics.ListInset, 8);
            section.Children.Add(empty);
        }

        var end = HeatEndDate(report);
        var timezone = RangeEngine.TimezoneOf(report);
        var labels = report.AgentLabels();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));
        for (var i = 0; i < lists.Visible.Count; i++)
        {
            if (i > 0) section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            section.Children.Add(ProjectRow(lists.Visible[i], report.Currency, end, timezone, labels, pinned.Contains(lists.Visible[i].Id)));
        }

        if (lists.Hidden.Count > 0)
        {
            if (lists.Visible.Count > 0) section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            section.Children.Add(HiddenFooter(report, lists.Hidden));
        }
        if (!ctx.IsAll && lists.Idle > 0)
        {
            var idle = Ui.Text(
                lists.Idle == 1
                    ? L10n.TrL(null, "overview.projects.idle.singular", lists.Idle)
                    : L10n.TrL(null, "overview.projects.idle.plural", lists.Idle),
                10.5, null, Palette.Tertiary);
            idle.Margin = new Thickness(Metrics.ListInset, 6, Metrics.ListInset, 6);
            section.Children.Add(idle);
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
            .Select(k => (k, labels.GetValueOrDefault(k) ?? AgentColors.Label(k), cost.GetValueOrDefault(k), tokens.GetValueOrDefault(k)))
            .ToList();
    }

    /// <summary>热力条的结束日期：generated_at → totals.last_active → now。</summary>
    private static DateTimeOffset HeatEndDate(UsageReport report)
    {
        if (ReportDates.ParseTimestamp(report.GeneratedAt) is { } generated) return generated;
        if (ReportDates.ParseDay(report.Totals.LastActive) is { } day)
        {
            return Time.AtDay(RangeEngine.TimezoneOf(report), day);
        }
        return DateTimeOffset.UtcNow;
    }

    private Control ProjectRow(Project project, string currency, DateTimeOffset heatEnd, TimeZoneInfo timezone,
        IReadOnlyDictionary<string, string> labels, bool pinned)
    {
        var row = new Border
        {
            Padding = new Thickness(Metrics.ListInset, 7, Metrics.ListInset, 7),
            CornerRadius = new CornerRadius(Metrics.RowRadius),
            Background = Brushes.Transparent,
            Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand),
        };
        ToolTip.SetTip(row, project.Id);

        var box = Ui.V(3);

        var top = Ui.H(6);
        if (pinned)
        {
            top.Children.Add(Icons.Pin(8.5, Palette.Pin));
        }
        var name = Ui.Text(project.Name, 12.5, FontWeight.Medium);
        name.MaxWidth = 190;
        top.Children.Add(name);

        var used = project.ByAgent
            .Where(a => a.Sessions > 0 || a.Cost > 0 || a.Tokens.Total > 0)
            .OrderByDescending(a => a.Cost)
            .ToList();
        foreach (var agent in used.Take(3))
        {
            top.Children.Add(Ui.Dot(agent.Agent));
        }
        if (used.Count > 0)
        {
            ToolTip.SetTip(top.Children[^1], string.Join("\n",
                TooltipBuilder.AgentLines(used, currency)));
        }
        if (project.PathMissing)
        {
            top.Children.Add(Badge(L10n.Tr("overview.badge.path_missing"), warn: true, L10n.Tr("overview.badge.path_missing_help")));
        }
        if (project.Remote is null)
        {
            top.Children.Add(Badge(L10n.Tr("overview.badge.local"), warn: false, L10n.Tr("overview.badge.local_help")));
        }
        top.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        top.Children.Add(Ui.Text(Fmt.Money(project.Cost, currency), 12.5, FontWeight.Medium));
        box.Children.Add(top);

        var bottom = Ui.H(8);
        var sessions = project.Sessions == 1
            ? L10n.TrL(null, "overview.row.subtitle.singular", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive))
            : L10n.TrL(null, "overview.row.subtitle.plural", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive));
        var subtitle = Ui.Text(sessions, 10.5, null, Palette.Secondary);
        ToolTip.SetTip(subtitle, L10n.TrL(null, "overview.row.last_active", Fmt.Day(project.LastActive)));
        bottom.Children.Add(subtitle);
        bottom.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });

        var weeks = HeatStrip.Weekly(project.ByDay, heatEnd,
            DominantAgent.Of(project.ByAgent)?.Agent ?? project.ByAgent.FirstOrDefault()?.Agent ?? "unknown",
            HeatStrip.DefaultWeeks, timezone);
        bottom.Children.Add(new HeatStripView(weeks));
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

    /// <summary>「N hidden · $X」；展开后列出隐藏项目的交互留到批次 2。</summary>
    private Control HiddenFooter(UsageReport report, IReadOnlyList<Project> hidden)
    {
        var cost = hidden.Sum(p => p.Cost);
        var row = Ui.H(4);
        row.Margin = new Thickness(Metrics.ListInset, 8, Metrics.ListInset, 8);
        row.Children.Add(Ui.Text(L10n.TrL(null, "overview.hidden_footer", hidden.Count, Fmt.Money(cost, report.Currency)),
            10.5, null, Palette.Secondary));
        ToolTip.SetTip(row, string.Join("\n", hidden.Select(p => p.Name)));
        return row;
    }

    // MARK: - 按模型

    private Control ModelsSection(UsageReport report, FilteredReport filtered)
    {
        var models = ModelAggregation.Aggregate(filtered);
        var section = Section(L10n.Tr("overview.section.by_model"));
        if (models.Count == 0)
        {
            var empty = Ui.Text(L10n.Tr("overview.models.no_usage_range"), 11, null, Palette.Secondary);
            empty.Margin = new Thickness(Metrics.ListInset, 8, Metrics.ListInset, 8);
            section.Children.Add(empty);
            return section;
        }

        var shown = models.Take(8).ToList();
        for (var i = 0; i < shown.Count; i++)
        {
            if (i > 0) section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            section.Children.Add(ModelRow(shown[i], report.Currency, filtered));
        }
        if (models.Count > 8)
        {
            section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            var more = Ui.Text(L10n.TrL(null, "overview.models.more", models.Count - 8), 10.5, null, Palette.Accent);
            more.Margin = new Thickness(Metrics.ListInset, 6, Metrics.ListInset, 6);
            section.Children.Add(more);
        }
        return section;
    }

    private static Control ModelRow(ModelCost model, string currency, FilteredReport filtered)
    {
        var row = Ui.H(6);
        row.Margin = new Thickness(Metrics.ListInset, 6, Metrics.ListInset, 6);
        row.Children.Add(Ui.Dot(model.Agent));
        var name = Ui.Text(model.Model, 11.5, null, Palette.Foreground, mono: true);
        name.MaxWidth = 168;
        if (name.Text is { } text && Type.MeasureWidth(text, 11.5) > 168)
        {
            var keep = Math.Max(6, text.Length * 168 / Math.Max(1, (int)Type.MeasureWidth(text, 11.5)) - 1);
            name.Text = text[..Math.Min(keep, text.Length)] + "…" + text[^Math.Min(6, text.Length)..];
        }
        row.Children.Add(name);
        if (model.Estimated)
        {
            row.Children.Add(Badge(L10n.Tr("project.estimated"), warn: true, L10n.Tr("project.estimated_help")));
        }
        row.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        row.Children.Add(Ui.Text(Fmt.Tokens(model.Tokens.Total), 11, FontWeight.Medium));
        row.Children.Add(Ui.Text(Fmt.Money(model.Cost, currency), 10.5, null, Palette.Secondary));
        ToolTip.SetTip(row, TooltipBuilder.ModelTooltip(model.Model, model.Agent, model.Cost, model.Tokens.Total));
        return row;
    }

    // MARK: - 不在项目里

    private Control BucketsSection(UsageReport report, FilteredReport filtered)
    {
        var section = Section(L10n.Tr("overview.section.not_in_project"));
        var buckets = report.Buckets;
        section.Children.Add(BucketRow(L10n.Tr("overview.unattributed"), L10n.Tr("overview.unattributed_desc"),
            filtered.Unattributed.Sessions, Fmt.Money(filtered.Unattributed.Cost, report.Currency)));
        section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
        section.Children.Add(BucketRow(L10n.Tr("overview.excluded"), L10n.Tr("overview.excluded_desc"),
            filtered.Excluded.Sessions, Fmt.Money(filtered.Excluded.Cost, report.Currency)));
        if (buckets.ParseFailed.Sessions > 0)
        {
            section.Children.Add(Ui.Hairline(Metrics.ListInset, Metrics.ListInset));
            section.Children.Add(BucketRow(L10n.Tr("overview.parse_failed"), L10n.Tr("overview.parse_failed_desc"),
                buckets.ParseFailed.Sessions, "—", true));
        }
        return section;
    }

    private static Control BucketRow(string name, string desc, int sessions, string value, bool warn = false)
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(Metrics.ListInset, 7, Metrics.ListInset, 7);

        var top = Ui.H(8);
        top.Children.Add(Ui.Text(name, 12));
        top.Children.Add(new Panel { HorizontalAlignment = HorizontalAlignment.Stretch });
        var count = sessions == 1
            ? L10n.TrL(null, "overview.count.session.singular", sessions)
            : L10n.TrL(null, "overview.count.session.plural", sessions);
        top.Children.Add(Ui.Text(count, 10.5, null, Palette.Secondary));
        var valueText = Ui.Text(value, 12, FontWeight.Medium, warn ? Palette.Secondary : Palette.Foreground);
        valueText.MinWidth = 52;
        valueText.TextAlignment = TextAlignment.Right;
        top.Children.Add(valueText);
        box.Children.Add(top);
        box.Children.Add(Ui.Text(desc, 10, null, Palette.Secondary, wrap: true, maxLines: 2));
        return box;
    }

    // MARK: - 对账

    private static Control ReconciliationLine(UsageReport report)
    {
        var rec = new Reconciliation(report);
        var line = Ui.H(4);
        line.Margin = new Thickness(Metrics.ListInset, 0, Metrics.ListInset, 0);
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

    /// <summary>一节：小号全大写标题 + 内容（直接放在面板上，没有分组底色）。</summary>
    private static StackPanel Section(string title)
    {
        var box = Ui.V(2);
        var heading = Ui.SectionTitle(title);
        heading.Margin = new Thickness(Metrics.ListInset, 0, Metrics.ListInset, 4);
        box.Children.Add(heading);
        return box;
    }

    private static Control WithMargin(Control control, double left, double top, double right, double bottom)
    {
        control.Margin = new Thickness(left, top, right, bottom);
        return control;
    }
}
