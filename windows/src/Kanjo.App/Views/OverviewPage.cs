using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 总览页：HERO（总额 + 范围分段控件 + 摘要 + 范围说明）→ 订阅价值卡 → 马赛克 → 项目列表 →
/// 按模型 → 不在项目里 → 对账 + 页脚。几何与 Mac 参考截图对齐。
/// 所有「左内容 + 右对齐数值」的行都用 Grid 的 `*,Auto` 列，和 SwiftUI 的 Spacer 等价。
/// </summary>
public sealed class OverviewPage : ScrollPage
{
    private readonly AppServices _services;
    private readonly string? _anchor;
    private readonly bool _snapshot;
    private bool _showHidden;
    private bool _showAllModels;

    public OverviewPage(AppServices services, string? anchor, bool snapshot) : base(snapshot)
    {
        _services = services;
        _anchor = anchor;
        _snapshot = snapshot;
        Content = _services.Report is null ? ErrorOrLoading() : LoadedContent();
        if (snapshot)
        {
            Content = _services.Report is null ? ErrorOrLoading() : BuildStatic();
        }
    }

    /// <summary>页面内容本身（不含滚动容器）：截图 / 面板快照模式直接用。</summary>
    public static Control BuildContent(AppServices services, string? anchor = null)
    {
        var page = new OverviewPage(services, anchor, snapshot: true);
        var content = page.Content as Control ?? new Panel();
        page.Content = null;
        return content;
    }

    private UsageReport Report => _services.Report!;

    private const double TextListSpacing = 14;

    private const double ContentInset = Metrics.ContentInset;

    private Control LoadedContent()
    {
        var ctx = new RangeContext(Report, _services.Settings.GetString(SettingsKeys.TimeRange), _services.Now);
        var filtered = ctx.Filtered();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));
        var hidden = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
        var arranged = ArrangeProjects(filtered, ctx.IsAll, pinned, hidden);

        var root = BuildStatic(ctx, filtered, arranged);
        if (_anchor == RouteAnchors.OverviewBottom)
        {
            // 路由要求滚到底部：等布局完成后滚。
            Avalonia.Threading.Dispatcher.UIThread.Post(() =>
            {
                UpdateLayout();
                var extent = Extent.Height;
                var viewport = Viewport.Height;
                Offset = new Vector(0, Math.Max(0, extent - viewport));
            }, Avalonia.Threading.DispatcherPriority.Loaded);
        }
        return root;
    }

    /// <summary>页面内容，供快照模式复用。</summary>
    private Control BuildStatic()
    {
        var ctx = new RangeContext(Report, _services.Settings.GetString(SettingsKeys.TimeRange), _services.Now);
        var filtered = ctx.Filtered();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));
        var hidden = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
        var arranged = ArrangeProjects(filtered, ctx.IsAll, pinned, hidden);
        return BuildStatic(ctx, filtered, arranged);
    }

    private Control BuildStatic(RangeContext ctx, FilteredReport filtered, Lists arranged)
    {
        var report = Report;
        var root = Ui.V(Metrics.SectionSpacing);

        // Hero 卡片：标题 + 范围胶囊 + 大号金额 + 摘要 + 范围说明。
        var heroBlock = Ui.V(10);
        heroBlock.Children.Add(Hero(report, ctx, filtered, arranged.Visible, arranged.Hidden.Count));
        root.Children.Add(Chrome.Card(heroBlock, Metrics.RowInset, 14));

        if (report.Subscriptions is { Count: > 0 })
        {
            root.Children.Add(SubscriptionValueCard(report));
        }
        if (arranged.Visible.Any(p => p.Cost > 0))
        {
            root.Children.Add(MosaicCard(report, arranged.Visible));
        }

        root.Children.Add(ProjectsSection(report, filtered, arranged, ctx));
        root.Children.Add(ModelsSection(report, filtered));
        root.Children.Add(BucketsSection(report, filtered));

        var footer = Ui.V(4);
        if (ctx.IsAll) footer.Children.Add(ReconciliationLine(report));
        footer.Children.Add(Ui.Text(
            L10n.TrL(null, "overview.generated_footer", Fmt.Timestamp(report.GeneratedAt), report.SchemaVersion),
            Type.CaptionSize, null, Palette.Tertiary));
        footer.Margin = new Thickness(4, 0, 4, 0);
        root.Children.Add(footer);

        root.Margin = new Thickness(Metrics.PagePadding, 16, Metrics.PagePadding, 16);
        return root;
    }

    private Control ErrorOrLoading()
    {
        var box = Ui.V(10);
        box.Margin = new Thickness(ContentInset, 28, ContentInset, 0);
        if (_services.Error is { } error)
        {
            box.Children.Add(Ui.Text(L10n.Tr("menu.error_title"), 15, FontWeight.SemiBold, Palette.Bad));
            box.Children.Add(new Border
            {
                Child = Ui.Text(error, 12, null, Palette.Foreground, wrap: true, mono: true),
                Padding = new Thickness(10),
                CornerRadius = new CornerRadius(8),
                Background = Palette.BadFill,
            });
            box.Children.Add(Ui.Text(
                L10n.TrL(null, "settings.current_source", _services.DescribeSource()),
                10.5, null, Palette.Secondary, wrap: true));
            var actions = Ui.H(8);
            actions.Children.Add(Ui.ProminentButton(L10n.Tr("common.retry"), () =>
            {
                Task.Run(() =>
                {
                    _services.Refresh();
                    _services.NotifyChanged();
                });
            }));
            actions.Children.Add(Ui.BorderedButton(L10n.Tr("menu.open_settings"), () => _services.RequestNavigate(AppRoute.Settings)));
            box.Children.Add(actions);
            box.Children.Add(Ui.Text(L10n.Tr("menu.expected_export_json"), 12, null, Palette.Secondary, wrap: true));
            return box;
        }
        box.Children.Add(Ui.Text(L10n.Tr("common.loading"), 12, FontWeight.Medium, Palette.Secondary));
        box.Children.Add(Ui.Text(FirstScanHint.Explanation(), 12, null, Palette.Secondary, wrap: true));
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
        var box = Ui.V(4);

        var title = Ui.H(6);
        title.Children.Add(Ui.Text(L10n.Tr("overview.total_cost"), Type.CaptionSize, FontWeight.SemiBold,
            Palette.Secondary));
        if (report.CostNoteDisplayText is { } note)
        {
            title.Children.Add(Icons.InfoCircle(12, Palette.Secondary));
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

        var titleRow = Ui.Columns(
            (title, new GridLength(1, GridUnitType.Star)),
            (picker, GridLength.Auto));
        box.Children.Add(titleRow);

        box.Children.Add(Widgets.HeroAmount(Fmt.Money(filtered.Cost, report.Currency), 36));

        var rangeText = filtered.FirstActive is null && !ctx.IsAll
            ? L10n.Tr("overview.no_usage")
            : ShortDate.Range(filtered.FirstActive, filtered.LastActive, compact: true);
        var summary = OverviewSummaryText.Make(ctx.Range, rangeText, visible.Count, filtered.Sessions,
            filtered.Tokens, hiddenCount);
        box.Children.Add(Ui.Text(summary, Type.CaptionSize, null, Palette.Secondary, wrap: true));

        if (ctx.CaptionResult is { } caption)
        {
            box.Children.Add(new RangeCaptionLine(caption));
        }
        return box;
    }

    /// <summary>马赛克卡片：白卡 + 圆角，色块本身贴着卡片内侧。</summary>
    private Control MosaicCard(UsageReport report, IReadOnlyList<Project> visible)
    {
        var width = Metrics.PanelWidth - Metrics.PagePadding * 2 - Metrics.RowInset * 2;
        var host = new Panel { Height = MosaicLayout.DefaultHeight };
        host.Children.Add(new MosaicView(visible, width, report.Currency, report.AgentLabels()));
        return Chrome.Card(host, Metrics.RowInset, Metrics.RowInset);
    }

    // MARK: - 订阅价值

    private Control SubscriptionValueCard(UsageReport report)
    {
        var rows = SubscriptionValue.Rows(report, _services.Now);
        var order = SubscriptionOrder.Parse(_services.Settings.Str(SettingsKeys.SubscriptionOrder, ""));
        var ordered = SubscriptionOrder.Apply(order, rows);

        var pinnedAgent = RouteAnchors.QuotaAgent(_anchor);
        var autoExpand = pinnedAgent is not null && ordered.Any(r => r.Agent == pinnedAgent);
        var expanded = _services.SubscriptionCardExpanded || autoExpand;
        var visible = SubscriptionOrder.Visible(ordered, expanded, limit: 3);

        var body = Ui.V(0);
        body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));

        for (var i = 0; i < visible.Count; i++)
        {
            if (i > 0) body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
            var line = SubscriptionLine(report, visible[i]).WithMargin(Metrics.RowInset, 8, Metrics.RowInset, 8);
            MakeReorderable(line, visible[i].Agent, ordered.Select(r => r.Agent).ToList());
            body.Children.Add(line);
        }

        if (ordered.Count > 3)
        {
            body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
            var label = expanded
                ? L10n.Tr("overview.subscription_value.show_less")
                : L10n.TrL(null, "overview.subscription_value.show_more", ordered.Count - 3);
            var toggle = Ui.LinkButton(label, () =>
            {
                _services.SubscriptionCardExpanded = !_services.SubscriptionCardExpanded;
                _services.NotifyChanged();
            });
            body.Children.Add(toggle.WithMargin(Metrics.RowInset, 8, Metrics.RowInset, 8));
        }

        var explanation = Ui.Text(L10n.Tr("overview.subscription_value.explanation"), Type.CaptionSize, null,
            Palette.Tertiary, wrap: true);
        body.Children.Add(explanation.WithMargin(Metrics.RowInset, 4, Metrics.RowInset, 10));

        if (RenewalNudgeLine(report) is { } nudge) body.Children.Add(nudge);

        var section = Ui.V(8);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.subscription_value")));
        section.Children.Add(Chrome.CardBare(body));
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

        var setNow = new Clickable(text, () => _services.RequestNavigate(AppRoute.Settings with
            {
                Anchor = SubscriptionSettingsRoute.Anchor(pending[0]),
            }), radius: 4)
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

    /// <summary>
    /// 订阅行拖拽排序（Mac 的 .draggable / .dropDestination）：按住行拖到另一行上，交换顺序并存进设置。
    /// 拖拽目标高亮；放下后写 `subscriptionOrder`。
    /// </summary>
    private void MakeReorderable(Control row, string agent, IReadOnlyList<string> order)
    {
        if (row is not Border border) return;
        var target = new DropTarget(border, agent);
        border.PointerPressed += (_, e) =>
        {
            if (e.GetCurrentPoint(border).Properties.IsLeftButtonPressed) target.BeginDrag(e);
        };
        target.Dropped += source =>
        {
            if (source == agent) return;
            var moved = SubscriptionOrder.Move(source, agent, order);
            _services.Settings.Set(SettingsKeys.SubscriptionOrder, SubscriptionOrder.Serialize(moved));
            _services.NotifyChanged();
        };
    }

    /// <summary>订阅行的额度卡 / 说明卡（悬停 0.35 秒后浮出）。</summary>
    private void AttachSubscriptionHover(Control anchor, UsageReport report, SubscriptionRow row)
    {
        if (report.QuotaWindows?.TryGetValue(row.Agent, out var window) == true)
        {
            var quota = SubscriptionValue.QuotaRows(window, RangeEngine.TimezoneOf(report), _services.Now);
            if (quota.Count > 0)
            {
                HoverLayer.Attach(anchor, $"overview:quota:{row.Agent}",
                    () => HoverCards.Quota(row.Agent, row.PlanLabel, quota));
                return;
            }
        }
        HoverLayer.Attach(anchor, $"overview:sub:{row.Agent}",
            () => HoverCards.Subscription(row, report.Currency));
    }

    /// <summary>一行：色点 + 名称 + 月费 …… 用量 + 「·」+ 倍数（右侧两列）。</summary>
    private Control SubscriptionLine(UsageReport report, SubscriptionRow row)
    {
        var box = Ui.V(2);

        var left = Ui.H(5);
        left.Children.Add(Ui.Dot(row.Agent));
        var plan = Ui.Text(row.PlanLabel, 12);
        plan.VerticalAlignment = VerticalAlignment.Center;
        left.Children.Add(plan);
        left.Children.Add(Ui.Text($"· {Fmt.PerMonth(row.MonthlyPriceUsd, report.Currency)}", 12, null,
            Palette.Secondary));
        if (row.ExtraUsageEnabled)
        {
            left.Children.Add(Widgets.Badge(L10n.Tr("overview.extra_usage_on"), BadgeStyle.Warn,
                L10n.Tr("overview.extra_usage_help")));
        }

        var amount = Ui.Text(Fmt.Money(row.Usage, report.Currency), 14, FontWeight.Medium, family: Type.Rounded);
        amount.TextAlignment = TextAlignment.Right;
        var dot = Ui.Text("·", 12, null, Palette.Tertiary);
        var multiple = Ui.Text(Fmt.Multiple(row.Multiplier), 13, FontWeight.Medium, Palette.Secondary);
        multiple.TextAlignment = TextAlignment.Right;
        multiple.MinWidth = 42;

        var top = Ui.Columns(
            (left, new GridLength(1, GridUnitType.Star)),
            (amount, GridLength.Auto),
            (dot.WithMargin(6, 0, 4, 0), GridLength.Auto),
            (multiple, GridLength.Auto));
        box.Children.Add(top);

        // 额度卡（有 quota_windows 才挂）：悬停 0.35 秒后浮出。
        AttachSubscriptionHover(top, report, row);

        if (report.Subscriptions is { } subs && subs.TryGetValue(row.Agent, out var sub))
        {
            var timezone = RangeEngine.TimezoneOf(report);
            var caption = Fmt.CycleCaption(sub, timezone, _services.Now);
            var captionText = Ui.Text(caption, 12, null, Palette.Secondary, wrap: true)
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
        var body = Ui.V(0);

        var legend = LegendAgents(filtered);
        if (legend.Count > 0)
        {
            body.Children.Add(Widgets.Legend(legend, report.Currency)
                .WithMargin(Metrics.RowInset, 10, Metrics.RowInset - 6, 4));
        }

        if (lists.Visible.Count == 0)
        {
            var text = report.Projects.Count == 0
                ? L10n.Tr("overview.projects.empty")
                : lists.Idle > 0
                    ? L10n.Tr("overview.projects.no_usage_range")
                    : L10n.Tr("overview.projects.all_hidden");
            body.Children.Add(Ui.Text(text, Type.CaptionSize, null, Palette.Secondary)
                .WithMargin(Metrics.RowInset, 10, Metrics.RowInset, 12));
        }

        var heatEnd = HeatEndDate(report);
        var timezone = RangeEngine.TimezoneOf(report);
        var labels = report.AgentLabels();
        var pinned = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.PinnedProjects, ""));

        for (var i = 0; i < lists.Visible.Count; i++)
        {
            if (i > 0 || legend.Count > 0) body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
            body.Children.Add(ProjectRow(lists.Visible[i], report.Currency, heatEnd, timezone, labels,
                pinned.Contains(lists.Visible[i].Id), i));
        }

        if (lists.Hidden.Count > 0)
        {
            if (lists.Visible.Count > 0) body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
            body.Children.Add(HiddenFooter(report, lists.Hidden));
        }
        if (!ctx.IsAll && lists.Idle > 0)
        {
            body.Children.Add(Ui.Text(
                lists.Idle == 1
                    ? L10n.TrL(null, "overview.projects.idle.singular", lists.Idle)
                    : L10n.TrL(null, "overview.projects.idle.plural", lists.Idle),
                Type.CaptionSize, null, Palette.Tertiary).WithMargin(Metrics.RowInset, 8, Metrics.RowInset, 10));
        }

        var section = Ui.V(8);
        section.Children.Add(SectionHeader(L10n.Tr("settings.section.projects")));
        section.Children.Add(Chrome.CardBare(body));
        return section;
    }

    private static IReadOnlyList<(string Agent, string Label, double Cost, long Tokens)> LegendAgents(
        FilteredReport filtered)
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

    /// <summary>热力条的结束日期：generated_at → totals.last_active → now。</summary>
    private static DateTimeOffset HeatEndDate(UsageReport report)
    {
        var timezone = RangeEngine.TimezoneOf(report);
        if (ReportDates.ParseTimestamp(report.GeneratedAt) is { } generated) return generated;
        if (ReportDates.ParseDay(report.Totals.LastActive) is { } day) return Time.AtDay(timezone, day);
        return DateTimeOffset.UtcNow;
    }

    /// <summary>
    /// 项目行，两行：名称 + agent 色点 + local / path missing 标签 …… 金额（右上）；
    /// sessions · tokens · 最近活跃 …… 8 周热力条（右下）。悬停整行高亮并显示置顶 / 隐藏按钮，
    /// 右键菜单有更多动作。
    /// </summary>
    private Control ProjectRow(Project project, string currency, DateTimeOffset heatEnd, TimeZoneInfo timezone,
        IReadOnlyDictionary<string, string> labels, bool pinned, int index)
    {
        var row = new Border
        {
            Padding = new Thickness(ContentInset, Metrics.RowPadV, ContentInset, Metrics.RowPadV),
            CornerRadius = new CornerRadius(Metrics.RowRadius),
            Background = Brushes.Transparent,
            // 指针默认是箭头：Windows 只在链接上用小手，列表行不是链接。
            Cursor = new Cursor(StandardCursorType.Arrow),
        };
        ToolTip.SetTip(row, project.Id);

        var box = Ui.V(3);

        var topLeft = Ui.H(6);
        if (pinned)
        {
            topLeft.Children.Add(Icons.Pin(8.5, Palette.Pin));
            ToolTip.SetTip(topLeft.Children[^1], L10n.Tr("overview.badge.pinned"));
        }
        topLeft.Children.Add(Ui.Text(project.Name, 14, FontWeight.Medium));
        var dots = Widgets.AgentDots(project.ByAgent, currency, 6, $"overview:hover:dots:{index}");
        topLeft.Children.Add(dots);
        if (project.PathMissing)
        {
            topLeft.Children.Add(Widgets.Badge(L10n.Tr("overview.badge.path_missing"), BadgeStyle.Warn,
                L10n.Tr("overview.badge.path_missing_help")));
        }
        if (project.Remote is null)
        {
            topLeft.Children.Add(Widgets.Badge(L10n.Tr("overview.badge.local"), BadgeStyle.Neutral,
                L10n.Tr("overview.badge.local_help")));
        }

        var top = Ui.Columns(
            (topLeft, new GridLength(1, GridUnitType.Star)),
            (Ui.Text(Fmt.Money(project.Cost, currency), 14, FontWeight.Medium), GridLength.Auto));
        box.Children.Add(top);

        var sessions = project.Sessions == 1
            ? L10n.TrL(null, "overview.row.subtitle.singular", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive))
            : L10n.TrL(null, "overview.row.subtitle.plural", project.Sessions,
                Fmt.Tokens(project.Tokens.Total), ShortDate.Relative(project.LastActive));
        var subtitle = Ui.Text(sessions, 12, null, Palette.Secondary);
        ToolTip.SetTip(subtitle, L10n.TrL(null, "overview.row.last_active", Fmt.Day(project.LastActive)));

        var weeks = HeatStrip.Weekly(project.ByDay, heatEnd, RangeContext.FallbackAgent(project),
            HeatStrip.DefaultWeeks, timezone);
        var strip = new HeatStripView(weeks, currency, labels, idPrefix: $"overview:hover:heat:{index}");

        // 悬停时出现的置顶 / 隐藏按钮（放在热力条左边）。
        var actions = Ui.H(0);
        actions.Children.Add(RowIconButton(pinned ? Icons.Pin(10, Palette.Pin) : Icons.Pin(10, Palette.Secondary),
            pinned ? L10n.Tr("overview.action.unpin") : L10n.Tr("overview.action.pin"),
            () => TogglePin(project.Id)));
        actions.Children.Add(RowIconButton(Icons.EyeSlash(10, Palette.Secondary),
            L10n.Tr("overview.action.hide"), () => Hide(project.Id)));
        actions.IsVisible = false;
        actions.VerticalAlignment = VerticalAlignment.Center;

        var bottom = Ui.Columns(
            (subtitle, new GridLength(1, GridUnitType.Star)),
            (actions, GridLength.Auto),
            (strip, GridLength.Auto));
        box.Children.Add(bottom);

        row.Child = box;
        row.PointerEntered += (_, _) =>
        {
            row.Background = Palette.RowHover;
            actions.IsVisible = true;
        };
        row.PointerExited += (_, _) =>
        {
            row.Background = Brushes.Transparent;
            actions.IsVisible = false;
        };
        row.PointerReleased += (_, e) =>
        {
            if (e.InitialPressMouseButton == MouseButton.Left)
            {
                _services.RequestNavigate(AppRoute.Project(project.Id, index));
            }
        };
        row.ContextMenu = ProjectContextMenu(project, pinned, hidden: false,
            () => TogglePin(project.Id), () => Hide(project.Id));
        return row;
    }

    private static Control RowIconButton(Control glyph, string help, Action action)
    {
        var inner = new Border
        {
            Width = 20,
            Height = 18,
            CornerRadius = new CornerRadius(4),
            Child = new Panel { Children = { glyph } },
        };
        glyph.HorizontalAlignment = HorizontalAlignment.Center;
        glyph.VerticalAlignment = VerticalAlignment.Center;
        var button = new Clickable(inner, action, help, radius: 4);
        button.VerticalAlignment = VerticalAlignment.Center;
        return button;
    }

    /// <summary>右键菜单：Pin/Unpin、Hide/Unhide、Open in Terminal、Show in Finder、Copy path、Copy remote。</summary>
    private static ContextMenu ProjectContextMenu(Project project, bool pinned, bool hidden,
        Action onTogglePin, Action onToggleHidden)
    {
        var menu = new ContextMenu();
        var items = new List<Control>();

        MenuItem Item(string header, Action action, bool enabled = true)
        {
            var item = new MenuItem { Header = header, IsEnabled = enabled };
            item.Click += (_, _) => action();
            return item;
        }

        var existing = ProjectActions.ExistingPath(project);
        var path = ProjectActions.DisplayPath(project);
        if (!hidden) items.Add(Item(pinned ? L10n.Tr("context.unpin") : L10n.Tr("context.pin"), onTogglePin));
        items.Add(Item(hidden ? L10n.Tr("context.unhide") : L10n.Tr("context.hide"), onToggleHidden));
        items.Add(new Separator());
        items.Add(Item(L10n.Tr("context.open_in_terminal"),
            () => { if (existing is not null) ProjectActions.OpenInTerminal(existing); }, existing is not null));
        items.Add(Item(L10n.Tr("context.show_in_explorer"),
            () => { if (existing is not null) ProjectActions.ShowInExplorer(existing); }, existing is not null));
        items.Add(new Separator());
        items.Add(Item(L10n.Tr("context.copy_path"),
            () => { if (path is not null) ProjectActions.Copy(path); }, path is not null));
        items.Add(Item(L10n.Tr("context.copy_remote"),
            () => { if (project.Remote is { } remote) ProjectActions.Copy(remote); }, project.Remote is not null));
        menu.ItemsSource = items;
        return menu;
    }

    private void TogglePin(string id)
    {
        var raw = _services.Settings.Str(SettingsKeys.PinnedProjects, "");
        _services.Settings.Set(SettingsKeys.PinnedProjects, ProjectPrefs.Toggle(id, raw));
        _services.NotifyChanged();
    }

    private void Hide(string id)
    {
        var raw = _services.Settings.Str(SettingsKeys.HiddenProjects, "");
        _services.Settings.Set(SettingsKeys.HiddenProjects, ProjectPrefs.Toggle(id, raw));
        _services.NotifyChanged();
    }

    private void Unhide(string id)
    {
        var set = ProjectPrefs.Parse(_services.Settings.Str(SettingsKeys.HiddenProjects, ""));
        set.Remove(id);
        _services.Settings.Set(SettingsKeys.HiddenProjects, ProjectPrefs.Serialize(set));
        _services.NotifyChanged();
    }

    /// <summary>「N hidden · $X · Show」；展开后在下面列出隐藏的项目，每行可取消隐藏。</summary>
    private Control HiddenFooter(UsageReport report, IReadOnlyList<Project> hidden)
    {
        var box = Ui.V(0);
        var cost = hidden.Sum(p => p.Cost);
        var row = Ui.H(4);
        row.Children.Add(Icons.EyeSlash(9, Palette.Secondary));
        row.Children.Add(Ui.Text(
            L10n.TrL(null, "overview.hidden_footer", hidden.Count, Fmt.Money(cost, report.Currency)),
            10.5, null, Palette.Secondary));
        row.Children.Add(Ui.LinkButton(_showHidden ? L10n.Tr("common.hide") : L10n.Tr("common.show"), () =>
        {
            _showHidden = !_showHidden;
            _services.NotifyChanged();
        }, 10.5));
        row.Margin = new Thickness(ContentInset, 8, ContentInset, 8);
        ToolTip.SetTip(row, string.Join("\n", hidden.Select(p => p.Name)));
        box.Children.Add(row);

        if (_showHidden)
        {
            for (var i = 0; i < hidden.Count; i++)
            {
                var project = hidden[i];
                if (i > 0) box.Children.Add(Widgets.RowDivider(ContentInset, ContentInset));
                var hiddenRow = Ui.H(6);
                hiddenRow.Margin = new Thickness(ContentInset, 5, ContentInset - 4, 5);
                var name = Ui.Text(project.Name, 13, null, Palette.Secondary, maxLines: 1);
                hiddenRow.Children.Add(name);
                var spacer = new Panel { HorizontalAlignment = HorizontalAlignment.Stretch };
                hiddenRow.Children.Add(spacer);
                hiddenRow.Children.Add(Ui.Text(Fmt.Money(project.Cost, report.Currency), 13, null,
                    Palette.Secondary, family: Type.Rounded));
                hiddenRow.Children.Add(RowIconButton(Icons.Eye(10, Palette.Secondary),
                    L10n.Tr("overview.action.unhide"), () => Unhide(project.Id)));
                ToolTip.SetTip(hiddenRow, project.Id);
                box.Children.Add(hiddenRow);
            }
        }
        return box;
    }

    // MARK: - 按模型

    private Control ModelsSection(UsageReport report, FilteredReport filtered)
    {
        var models = ModelAggregation.Aggregate(filtered);
        var body = Ui.V(0);
        if (models.Count == 0)
        {
            body.Children.Add(Ui.Text(L10n.Tr("overview.models.no_usage_range"), Type.CaptionSize, null,
                Palette.Secondary).WithMargin(Metrics.RowInset, 10, Metrics.RowInset, 12));
        }
        else
        {
            var shown = _showAllModels ? models : models.Take(8).ToList();
            for (var i = 0; i < shown.Count; i++)
            {
                if (i > 0) body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
                body.Children.Add(ModelRow(shown[i], report.Currency, i));
            }
            if (models.Count > 8)
            {
                body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
                var label = _showAllModels
                    ? L10n.Tr("common.show_fewer")
                    : L10n.TrL(null, "overview.models.more", models.Count - 8);
                body.Children.Add(Ui.LinkButton(label, () =>
                {
                    _showAllModels = !_showAllModels;
                    _services.NotifyChanged();
                }, Type.CaptionSize).WithMargin(Metrics.RowInset, 8, Metrics.RowInset, 8));
            }
        }

        var section = Ui.V(8);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.by_model")));
        section.Children.Add(Chrome.CardBare(body));
        return section;
    }

    /// <summary>模型行：色点 + 模型名 + [estimated] …… tokens + 金额（右侧相邻，间距 6）。</summary>
    private static Control ModelRow(ModelCost model, string currency, int index)
    {
        var left = Ui.H(6);
        left.Children.Add(Ui.Dot(model.Agent));
        var name = Ui.Text(model.Model, 13, family: Type.Mono, maxLines: 1);
        name.TextTrimming = TextTrimming.CharacterEllipsis;
        left.Children.Add(name);
        if (model.Estimated)
        {
            left.Children.Add(Widgets.Badge(L10n.Tr("project.estimated"), BadgeStyle.Warn,
                L10n.Tr("project.estimated_help")));
        }

        var tokens = Ui.Text(Fmt.Tokens(model.Tokens.Total), 12, FontWeight.Medium);
        tokens.TextAlignment = TextAlignment.Right;
        var cost = Ui.Text(Fmt.Money(model.Cost, currency), 12, null, Palette.Secondary)
            .WithMargin(6, 0, 0, 0);
        cost.TextAlignment = TextAlignment.Right;

        var row = Ui.Columns(
            (left, new GridLength(1, GridUnitType.Star)),
            (tokens, GridLength.Auto),
            (cost, GridLength.Auto));
        row.Margin = new Thickness(ContentInset, 6, ContentInset, 6);
        var copy = model;
        var id = index;
        HoverLayer.Attach(row, $"overview:hover:model:{index}",
            () => HoverCards.Model(copy.Model, copy.Agent, copy.Cost, copy.Tokens, currency));
        ToolTip.SetTip(row, TooltipBuilder.ModelTooltip(model.Model, model.Agent, model.Cost,
            model.Tokens.Total, currency));
        _ = id;
        return row;
    }

    // MARK: - 不在项目里

    private Control BucketsSection(UsageReport report, FilteredReport filtered)
    {
        var body = Ui.V(0);
        body.Children.Add(BucketRow(L10n.Tr("overview.unattributed"), L10n.Tr("overview.unattributed_desc"),
            filtered.Unattributed.Sessions, Fmt.Money(filtered.Unattributed.Cost, report.Currency),
            filtered.Unattributed.SessionsDetail.Count == 0
                ? null
                : () => _services.RequestNavigate(AppRoute.BucketDetail("unattributed"))));
        body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
        body.Children.Add(BucketRow(L10n.Tr("overview.excluded"), L10n.Tr("overview.excluded_desc"),
            filtered.Excluded.Sessions, Fmt.Money(filtered.Excluded.Cost, report.Currency),
            filtered.Excluded.SessionsDetail.Count == 0
                ? null
                : () => _services.RequestNavigate(AppRoute.BucketDetail("excluded"))));

        if (report.Buckets.ParseFailed.Sessions > 0)
        {
            body.Children.Add(Widgets.RowDivider(Metrics.RowInset, Metrics.RowInset));
            body.Children.Add(new ParseFailedRow(report.Buckets.ParseFailed));
        }

        var section = Ui.V(8);
        section.Children.Add(SectionHeader(L10n.Tr("overview.section.not_in_project")));
        section.Children.Add(Chrome.CardBare(body));
        return section;
    }

    /// <summary>桶行：名称 …… sessions + 金额（右对齐）。</summary>
    private static Control BucketRow(string name, string desc, int sessions, string value, Action? action)
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(ContentInset, 7, ContentInset, 7);

        var count = sessions == 1
            ? L10n.TrL(null, "overview.count.session.singular", sessions)
            : L10n.TrL(null, "overview.count.session.plural", sessions);
        var sessionsText = Ui.Text(count, 12, null, Palette.Secondary);
        sessionsText.TextAlignment = TextAlignment.Right;

        var valueText = Ui.Text(value, 14, FontWeight.Medium, family: Type.Rounded);
        valueText.TextAlignment = TextAlignment.Right;
        valueText.MinWidth = 52;

        box.Children.Add(Ui.Columns(
            (Ui.Text(name, 12), new GridLength(1, GridUnitType.Star)),
            (sessionsText, GridLength.Auto),
            (valueText.WithMargin(8, 0, 0, 0), GridLength.Auto)));
        box.Children.Add(Ui.Text(desc, 12, null, Palette.Secondary, wrap: true, maxLines: 2));

        if (action is null) return box;
        var clickable = new Clickable(box, action, L10n.Tr("overview.show_these_sessions"),
            Metrics.RowRadius);
        clickable.Padding = new Thickness(0);
        return clickable;
    }

    // MARK: - 对账

    private static Control ReconciliationLine(UsageReport report)
    {
        var rec = new Reconciliation(report);
        var line = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 4,
            Margin = new Thickness(0),
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        if (rec.Ok)
        {
            line.Children.Add(Icons.CheckCircle(10, Palette.Good));
            line.Children.Add(Ui.Text(
                L10n.TrL(null, "overview.reconciled", Fmt.Money(rec.Cost.Reported, report.Currency)),
                10.5, null, Palette.Good));
            ToolTip.SetTip(line, L10n.Tr("reconcile.contract_invariant"));
            return line;
        }
        line.Children.Add(Icons.WarnTriangle(10, Palette.Bad));
        line.Children.Add(Ui.Text(L10n.Tr("overview.reconcile_failed"), 14, FontWeight.SemiBold, Palette.Bad));
        return line;
    }

    // MARK: - 版式

    /// <summary>一节的标题（BodyStrong 14 semibold、正文色，句首大写），左对齐。</summary>
    private static Control SectionHeader(string title)
    {
        var label = Ui.SectionTitle(title);
        label.Margin = new Thickness(2, 0, 2, 0);
        return label;
    }
}
