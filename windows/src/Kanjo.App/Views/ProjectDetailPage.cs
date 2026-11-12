using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 详情页骨架（ProjectDetailView.swift 的 DetailPage）：返回按钮 + 各节，等间距排列。
/// </summary>
public static class DetailPage
{
    public const double Spacing = Metrics.SectionSpacing;

    public static Control Build(string backTitle, Action onBack, IEnumerable<Control> sections)
    {
        var root = Ui.V(Spacing);
        var back = Widgets.BackButton(backTitle, onBack);
        back.Margin = new Thickness(-2, 0, 0, 2);
        root.Children.Add(back);
        foreach (var section in sections) root.Children.Add(section);
        root.Margin = new Thickness(Metrics.PagePadding, 8, Metrics.PagePadding, 16);
        return root;
    }
}

/// <summary>
/// 项目详情（ProjectDetailView.swift）：头部、Tokens、By agent、By model、By day、By branch、
/// Sessions、Locations。非 All 范围下 tokens 只显示总额，By model / By branch 标「All time」。
/// </summary>
public sealed class ProjectDetailPage : ScrollPage
{
    private readonly AppServices _services;
    private readonly Project _project;
    private readonly int _projectIndex;
    private readonly string? _anchor;
    private readonly Action _onBack;
    private readonly bool _snapshot;

    public ProjectDetailPage(AppServices services, Project project, int index, string? anchor, Action onBack,
        bool snapshot = false, bool openLocations = false) : base(snapshot)
    {
        _services = services;
        _project = project;
        _projectIndex = index;
        _anchor = anchor;
        _onBack = onBack;
        _snapshot = snapshot;
        _showLocations = openLocations;

        Content = Build();

        if (snapshot && anchor is RouteAnchors.ProjectBottom or RouteAnchors.ProjectLocationsOpen)
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(() =>
            {
                UpdateLayout();
                ScrollTo(Math.Max(0, Extent.Height - Viewport.Height));
            }, Avalonia.Threading.DispatcherPriority.Loaded);
        }
        else if (snapshot && anchor is not null && anchor.Contains(":hover:", StringComparison.Ordinal))
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(() => PinHover(anchor), Avalonia.Threading.DispatcherPriority.Loaded);
        }
    }

    private UsageReport Report => _services.Report!;

    private string Currency => Report.Currency;

    private Control Build()
    {
        var ctx = new RangeContext(Report, _services.Settings.GetString(SettingsKeys.TimeRange), _services.Now);
        var filtered = ctx.Filter(_project);
        var shown = filtered.Projected;

        var sections = new List<Control>
        {
            Header(ctx, filtered),
            TokensSection(filtered, ctx.IsAll),
            AgentsSection(filtered),
            ModelsSection(ctx.IsAll),
            ByDaySection(filtered),
            BranchesSection(ctx.IsAll),
            SessionsSection(filtered),
            LocationsSection(),
        };
        return DetailPage.Build(L10n.Tr("project.navigation.projects"), _onBack, sections);
    }

    // MARK: - 头部

    private Control Header(RangeContext ctx, FilteredProject filtered)
    {
        var shown = filtered.Projected;
        var box = Ui.V(3);

        var titleRow = new WrapPanel
        {
            Orientation = Orientation.Horizontal,
            // 用 Stretch 而不是按内容收缩：下面的胶囊条靠父级宽度铺满，
            // 如果这一行按内容收缩，整个 StackPanel 的"自然宽度"就会偏窄。
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        var name = Ui.Text(_project.Name, Type.TitleSize, FontWeight.SemiBold, maxLines: 2,
            family: Type.Display);
        name.Margin = new Thickness(0, 0, 6, 0);
        titleRow.Children.Add(name);
        if (_project.PathMissing)
        {
            titleRow.Children.Add(Widgets.Badge(L10n.Tr("overview.badge.path_missing"), BadgeStyle.Warn,
                L10n.Tr("overview.badge.path_missing_help")));
        }
        if (_project.Remote is null)
        {
            titleRow.Children.Add(Widgets.Badge(L10n.Tr("overview.badge.local"), BadgeStyle.Neutral,
                L10n.Tr("overview.badge.local_help")));
        }
        box.Children.Add(titleRow);

        var picker = new RangePicker(
            _services.Settings.Str(SettingsKeys.TimeRange, SettingsDefaults.TimeRange),
            ctx.Range, ctx.ResetAvailable, ctx.CycleAvailable,
            raw =>
            {
                _services.Settings.Set(SettingsKeys.TimeRange, raw);
                _services.NotifyChanged();
            });
        picker.Margin = new Thickness(0, 4, 0, 2);
        box.Children.Add(picker);

        // 金额 + ⓘ（右侧 8 周热力条）
        var amountRow = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var amount = Ui.H(4);
        amount.Children.Add(Widgets.HeroAmount(Fmt.Money(shown.Cost, Currency), 30));
        if (Report.CostNoteDisplayText is { } note)
        {
            var info = Icons.InfoCircle(10, Palette.Secondary);
            info.Margin = new Thickness(0, 4, 0, 0);
            amount.Children.Add(info);
            ToolTip.SetTip(info, note);
        }
        Grid.SetColumn(amount, 0);
        amountRow.Children.Add(amount);

        var heat = Ui.V(3);
        heat.HorizontalAlignment = HorizontalAlignment.Right;
        var heatTitle = Ui.Text(L10n.Tr("project.last_8_weeks"), 12, null, Palette.Secondary);
        heatTitle.TextAlignment = TextAlignment.Right;
        heat.Children.Add(heatTitle);
        var weeks = HeatStrip.Weekly(shown.ByDay, HeatEndDate(Report), RangeContext.FallbackAgent(_project),
            HeatStrip.DefaultWeeks, RangeEngine.TimezoneOf(Report));
        heat.Children.Add(new HeatStripView(weeks, Currency, Report.AgentLabels(),
            cellWidth: 12, cellHeight: 20, radius: 3));
        heat.Margin = new Thickness(0, 0, 0, 5);
        Grid.SetColumn(heat, 2);
        amountRow.Children.Add(heat);
        amountRow.Margin = new Thickness(0, 0, 0, 0);
        box.Children.Add(amountRow);

        var usageText = shown.FirstActive is null
            ? L10n.Tr("project.no_usage")
            : ShortDate.Range(shown.FirstActive, shown.LastActive);
        box.Children.Add(Ui.Text(
            ProjectSubtitleText.Make(ctx.Range, shown.Sessions, usageText), 12, null, Palette.Secondary));

        if (ctx.CaptionResult is { } caption)
        {
            var line = new RangeCaptionLine(caption);
            line.Margin = new Thickness(0, 1, 0, 0);
            box.Children.Add(line);
        }

        var remote = Ui.H(4);
        if (_project.Remote is { } r)
        {
            remote.Children.Add(Icons.Link(9, Palette.Secondary));
            var text = Ui.Text(r, 12, null, Palette.Secondary, maxLines: 1);
            text.TextTrimming = TextTrimming.CharacterEllipsis;
            remote.Children.Add(text);
            ToolTip.SetTip(remote, r);
        }
        else
        {
            remote.Children.Add(Icons.Disk(9, Palette.Secondary));
            remote.Children.Add(Ui.Text(L10n.Tr("project.local_repo"), 12, null, Palette.Secondary));
        }
        remote.Margin = new Thickness(0, 8, 0, 0);
        box.Children.Add(remote);

        return Chrome.Card(box, Metrics.RowInset, 14);
    }

    private static DateTimeOffset HeatEndDate(UsageReport report)
    {
        var tz = RangeEngine.TimezoneOf(report);
        if (ReportDates.ParseTimestamp(report.GeneratedAt) is { } generated) return generated;
        if (ReportDates.ParseDay(report.Totals.LastActive) is { } day) return Time.AtDay(tz, day);
        return DateTimeOffset.UtcNow;
    }

    // MARK: - Tokens

    private Control TokensSection(FilteredProject filtered, bool isAll)
    {
        var tokens = filtered.Projected.Tokens;
        var headerRight = Ui.Text(L10n.TrL(null, "project.tokens_total", Fmt.Tokens(tokens.Total)), 12, null,
            Palette.Secondary);
        headerRight.VerticalAlignment = VerticalAlignment.Center;

        if (!isAll)
        {
            var body = Ui.H(8);
            body.Children.Add(Ui.Text(Fmt.Tokens(tokens.Total), 15, FontWeight.Medium, family: Type.Rounded));
            var note = Ui.Text(L10n.Tr("project.breakdown_all_only"), 12, null, Palette.Secondary, wrap: true);
            body.Children.Add(note);
            return Section(L10n.Tr("project.section.tokens"), body, headerRight);
        }

        var content = Ui.V(8);
        content.Children.Add(TokenBar(tokens));
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*") };
        grid.RowDefinitions = new RowDefinitions("Auto,Auto");
        var cells = new (string Label, long Value, IBrush? Color, string Help, int Row, int Column)[]
        {
            (L10n.Tr("project.token.input"), tokens.Input, Palette.TokenInput, L10n.Tr("project.token.input_help"), 0, 0),
            (L10n.Tr("project.token.output"), tokens.Output, Palette.TokenOutput, L10n.Tr("project.token.output_help"), 0, 1),
            (L10n.Tr("project.token.thinking"), tokens.Thinking, null, L10n.Tr("project.token.thinking_help"), 0, 2),
            (L10n.Tr("project.token.cache_read"), tokens.CacheRead, Palette.TokenCacheRead, L10n.Tr("project.token.cache_read_help"), 1, 0),
            (L10n.Tr("project.token.cache_write"), tokens.CacheWrite, Palette.TokenCacheWrite, L10n.Tr("project.token.cache_write_help"), 1, 1),
        };
        foreach (var cell in cells)
        {
            var control = TokenCell(cell.Label, cell.Value, cell.Color, cell.Help, tokens);
            control.Margin = new Thickness(0, 0, 10, 8);
            Grid.SetRow(control, cell.Row);
            Grid.SetColumn(control, cell.Column);
            grid.Children.Add(control);
        }
        content.Children.Add(grid);
        return Section(L10n.Tr("project.section.tokens"), content, headerRight);
    }

    private static Control Section(string title, Control content, Control? trailing = null) =>
        Chrome.LegacySection(title, content, trailing: trailing);

    private Control TokenCell(string label, long value, IBrush? color, string help, Tokens tokens)
    {
        var box = Ui.V(1);
        var top = Ui.H(4);
        if (color is not null)
        {
            top.Children.Add(new Avalonia.Controls.Shapes.Ellipse
            {
                Width = 6, Height = 6, Fill = color, VerticalAlignment = VerticalAlignment.Center,
            });
        }
        else
        {
            top.Children.Add(new Avalonia.Controls.Shapes.Ellipse
            {
                Width = 6, Height = 6,
                Stroke = Palette.Secondary, StrokeThickness = 1,
                VerticalAlignment = VerticalAlignment.Center,
            });
        }
        top.Children.Add(Ui.Text(label, 12, null, Palette.Secondary));
        box.Children.Add(top);
        box.Children.Add(Ui.Text(Fmt.Tokens(value), 15, FontWeight.Medium, family: Type.Rounded));
        ToolTip.SetTip(box, help + " · " + L10n.TrL(null, "overview.tokens_count", Fmt.Tokens(value)));

        var cardLabel = label;
        HoverLayer.Attach(box, $"project:{_projectIndex}:hover:token:{cardLabel}",
            () => TokenCellCard(cardLabel, value, color, help));
        return box;
    }

    private static Control TokenCellCard(string label, long value, IBrush? color, string help)
    {
        var box = Ui.V(6);
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var left = Ui.H(5);
        if (color is not null)
        {
            left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
            {
                Width = 7, Height = 7, Fill = color, VerticalAlignment = VerticalAlignment.Center,
            });
        }
        else
        {
            left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
            {
                Width = 7, Height = 7, Stroke = Palette.Secondary, StrokeThickness = 1,
                VerticalAlignment = VerticalAlignment.Center,
            });
        }
        left.Children.Add(Ui.Text(label, 14, FontWeight.SemiBold));
        Grid.SetColumn(left, 0);
        top.Children.Add(left);
        var count = Ui.Text(Fmt.Tokens(value), 14, FontWeight.SemiBold, family: Type.Rounded);
        count.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(count, 2);
        top.Children.Add(count);
        box.Children.Add(top);
        box.Children.Add(Ui.Text(help, 12, null, Palette.Secondary, wrap: true));
        return box;
    }

    /// <summary>四类计费 token 的构成条（thinking 是 output 子集，不单列）。</summary>
    private Control TokenBar(Tokens tokens)
    {
        var parts = new (long Value, IBrush Color, string Label, string Id)[]
        {
            (tokens.Input, Palette.TokenInput, L10n.Tr("project.token.input"), "input"),
            (tokens.Output, Palette.TokenOutput, L10n.Tr("project.token.output"), "output"),
            (tokens.CacheRead, Palette.TokenCacheRead, L10n.Tr("project.token.cache_read"), "cache_read"),
            (tokens.CacheWrite, Palette.TokenCacheWrite, L10n.Tr("project.token.cache_write"), "cache_write"),
        };
        var total = Math.Max(parts.Sum(p => p.Value), 1);
        var bar = new TokenBarControl(parts.Where(p => p.Value > 0)
            .Select(p => (p.Value / (double)total, p.Color, p.Label, p.Id)).ToList());
        ToolTip.SetTip(bar, string.Join("\n", parts.Where(p => p.Value > 0).Select(p =>
            $"● {p.Label}  {Fmt.Tokens(p.Value)} ({Fmt.Percent(p.Value / (double)total)})")));
        HoverLayer.Attach(bar, $"project:{_projectIndex}:hover:tokens", () => HoverCards.TokensBreakdown(tokens));
        return bar;
    }

    // MARK: - By agent

    private Control AgentsSection(FilteredProject filtered)
    {
        var shown = filtered.Projected;
        var maxCost = shown.ByAgent.Count == 0 ? 0 : shown.ByAgent.Max(a => a.Cost);
        var shares = SubscriptionValue.Shares(_project.Id, Report, _services.Now);

        var content = Ui.V(10);
        if (shown.ByAgent.Count == 0)
        {
            content.Children.Add(Ui.Text(L10n.Tr("project.no_usage_range"), 12, null, Palette.Secondary));
        }
        foreach (var agent in shown.ByAgent)
        {
            var detail = L10n.TrL(null, "project.agent_detail", agent.Sessions, Fmt.Tokens(agent.Tokens.Total),
                Fmt.Percent(shown.Cost > 0 ? agent.Cost / shown.Cost : 0));
            var rows = new List<HoverCardRowItem>
            {
                new(agent.Agent, agent.Label, agent.Cost, agent.Tokens.Total, 1.0),
            };
            var hoverId = $"project:{_projectIndex}:hover:agent:{agent.Agent}";
            var subtitle = agent.Sessions == 1
                ? L10n.TrL(null, "overview.count.session.singular", agent.Sessions)
                : L10n.TrL(null, "overview.count.session.plural", agent.Sessions);
            content.Children.Add(HBarRow(agent.Label, Palette.Agent(agent.Agent),
                maxCost > 0 ? agent.Cost / maxCost : 0, Fmt.Money(agent.Cost, Currency), detail, hoverId,
                () => HoverCards.AgentRows(agent.Label, agent.Agent, agent.Cost, agent.Tokens.Total, Currency,
                    rows, subtitle)));
        }

        if (shares.Count > 0)
        {
            var shareBox = Ui.V(3);
            shareBox.Margin = new Thickness(0, 1, 0, 0);
            foreach (var share in shares)
            {
                var cycleText = Report.Subscriptions?[share.Agent] is { } sub
                    ? Fmt.CycleCaption(sub, RangeEngine.TimezoneOf(Report), _services.Now)
                    : L10n.Tr("fmt.cycle_dates_unavailable");
                var text = Ui.Text(
                    L10n.TrL(null, "project.cycle_share", ShareText(share.Share), share.PlanLabel),
                    10.5, null, Palette.Secondary, wrap: true);
                ToolTip.SetTip(text, cycleText);
                var copyShare = share;
                HoverLayer.Attach(text, $"project:{_projectIndex}:hover:share:{share.Agent}",
                    () => ShareCard(copyShare, cycleText));
                shareBox.Children.Add(text);
            }
            content.Children.Add(shareBox);
        }
        return Section(L10n.Tr("project.section.by_agent"), content);
    }

    private Control ShareCard(CycleShare share, string cycleText)
    {
        var box = Ui.V(4);
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var left = Ui.H(5);
        left.Children.Add(Ui.Dot(share.Agent, 7));
        left.Children.Add(Ui.Text(share.PlanLabel, 14, FontWeight.SemiBold));
        Grid.SetColumn(left, 0);
        top.Children.Add(left);
        var value = Ui.Text(ShareText(share.Share), 13, FontWeight.SemiBold, family: Type.Rounded);
        value.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(value, 2);
        top.Children.Add(value);
        box.Children.Add(top);
        box.Children.Add(Ui.Text(cycleText, 12, null, Palette.Secondary));
        return box;
    }

    private static string ShareText(double share) => share == 0 ? "0%" : Fmt.Percent(share);

    /// <summary>一行：色点 + 标签 + 明细 + 数值，下方按比例的细条。</summary>
    private Control HBarRow(string label, IBrush color, double fraction, string value, string? detail,
        string hoverId, Func<Control> card)
    {
        var box = Ui.V(5);
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto") };
        var left = Ui.H(6);
        left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
        {
            Width = 6, Height = 6, Fill = color, VerticalAlignment = VerticalAlignment.Center,
        });
        left.Children.Add(Ui.Text(label, 12));
        Grid.SetColumn(left, 0);
        top.Children.Add(left);
        if (!string.IsNullOrEmpty(detail))
        {
            var detailText = Ui.Text(detail!, 12, null, Palette.Secondary);
            detailText.TextAlignment = TextAlignment.Right;
            detailText.Margin = new Thickness(6, 0, 0, 0);
            Grid.SetColumn(detailText, 2);
            top.Children.Add(detailText);
        }
        var amount = Ui.Text(value, 14, FontWeight.Medium, family: Type.Rounded);
        amount.TextAlignment = TextAlignment.Right;
        amount.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(amount, 3);
        top.Children.Add(amount);
        box.Children.Add(top);
        box.Children.Add(new FractionBar(color, fraction));
        HoverLayer.Attach(box, hoverId, card);
        return box;
    }

    // MARK: - By model

    private Control ModelsSection(bool isAll)
    {
        // 和 Mac 一样按数据里的顺序（契约里已经按花费排好），不重新排序。
        var all = _project.ByModel.ToList();
        var content = Ui.V(6);
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto") };
        var row = 0;
        grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        var headerModel = Ui.Text(L10n.Tr("project.model"), 12, null, Palette.Tertiary);
        var headerTokens = Ui.Text(L10n.Tr("project.section.tokens"), 12, null, Palette.Tertiary);
        headerTokens.TextAlignment = TextAlignment.Right;
        headerTokens.Margin = new Thickness(8, 0, 0, 0);
        var headerCost = Ui.Text(L10n.Tr("project.cost"), 12, null, Palette.Tertiary);
        headerCost.TextAlignment = TextAlignment.Right;
        headerCost.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetRow(headerModel, 0); Grid.SetColumn(headerModel, 0); grid.Children.Add(headerModel);
        Grid.SetRow(headerTokens, 0); Grid.SetColumn(headerTokens, 1); grid.Children.Add(headerTokens);
        Grid.SetRow(headerCost, 0); Grid.SetColumn(headerCost, 2); grid.Children.Add(headerCost);

        if (all.Count == 0)
        {
            content.Children.Add(Ui.Text(L10n.Tr("overview.models.no_usage_range"), 12, null, Palette.Secondary));
        }
        for (var j = 0; j < all.Count; j++)
        {
            var model = all[j];
            row++;
            grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            var left = Ui.H(5);
            left.Children.Add(Ui.Dot(model.Agent, 6));
            var name = Ui.Text(model.Model, 12, family: Type.Mono, maxLines: 1);
            name.TextTrimming = TextTrimming.CharacterEllipsis;
            left.Children.Add(name);
            if (model.Estimated)
            {
                left.Children.Add(Widgets.Badge(L10n.Tr("project.estimated"), BadgeStyle.Warn,
                    L10n.Tr("project.estimated_help")));
            }
            left.Margin = new Thickness(0, 3, 0, 3);
            left.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(left, row); Grid.SetColumn(left, 0);
            grid.Children.Add(left);
            var copy = model;
            var hoverId = j;
            HoverLayer.Attach(left, $"project:{_projectIndex}:hover:model:{j}",
                () => HoverCards.Model(copy.Model, copy.Agent, copy.Cost, copy.Tokens, Currency));

            var tokens = Ui.Text(Fmt.Tokens(model.Tokens.Total), 12, null, Palette.Secondary);
            tokens.TextAlignment = TextAlignment.Right;
            tokens.Margin = new Thickness(8, 0, 0, 0);
            tokens.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(tokens, row); Grid.SetColumn(tokens, 1);
            grid.Children.Add(tokens);

            var cost = Ui.Text(Fmt.Money(model.Cost, Currency), 12, FontWeight.Medium, family: Type.Rounded);
            cost.TextAlignment = TextAlignment.Right;
            cost.Margin = new Thickness(8, 0, 0, 0);
            cost.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(cost, row); Grid.SetColumn(cost, 2);
            grid.Children.Add(cost);
            _ = hoverId;
        }
        content.Children.Add(grid);

        if (all.Count > CollapsedLimit)
        {
            content.Children.Add(Widgets.ShowAllButton(_modelsExpanded, all.Count, L10n.Tr("project.noun.models"), () =>
            {
                _modelsExpanded = !_modelsExpanded;
                _services.NotifyChanged();
            }));
        }

        return Section(L10n.Tr("project.section.by_model"), content,
            isAll ? null : AllTimeBadge(L10n.Tr("project.noun.models")));
    }

    private const int CollapsedLimit = 8;
    private bool _modelsExpanded;
    private bool _branchesExpanded;
    private bool _showLocations;
    private bool _showTemporary;
    private DayChartView? _dayChart;

    private static Control AllTimeBadge(string what) => Widgets.Badge(L10n.Tr("project.badge.all_time"),
        BadgeStyle.Neutral, L10n.TrL(null, "project.badge.all_time_help", what));

    // MARK: - By day

    private Control ByDaySection(FilteredProject filtered)
    {
        _dayChart = new DayChartView(
            filtered.Projected.ByDay,
            Currency,
            DominantAgent.Of(_project.ByAgent) is { } d ? Palette.Agent(d.Agent) : Palette.ChartBar,
            Report.AgentLabels(),
            $"project:{_projectIndex}:hover:day");
        return Section(L10n.Tr("project.section.by_day"), _dayChart);
    }

    // MARK: - By branch

    private Control BranchesSection(bool isAll)
    {
        var all = _project.ByBranch.ToList();
        var content = Ui.V(6);
        if (all.Count == 0)
        {
            content.Children.Add(Ui.Text(L10n.Tr("project.no_branch_info"), 12, null, Palette.Secondary));
            return Section(L10n.Tr("project.section.by_branch"), content,
                isAll ? null : AllTimeBadge(L10n.Tr("project.noun.branches")));
        }
        var shown = _branchesExpanded ? all : all.Take(CollapsedLimit).ToList();
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto") };
        grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        var hBranch = Ui.Text(L10n.Tr("project.branch"), 12, null, Palette.Tertiary);
        var hSessions = Ui.Text(Capitalize(L10n.Tr("project.noun.sessions")), 12, null, Palette.Tertiary);
        hSessions.TextAlignment = TextAlignment.Right;
        hSessions.Margin = new Thickness(8, 0, 0, 0);
        var hCost = Ui.Text(L10n.Tr("project.cost"), 12, null, Palette.Tertiary);
        hCost.TextAlignment = TextAlignment.Right;
        hCost.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetRow(hBranch, 0); Grid.SetColumn(hBranch, 0); grid.Children.Add(hBranch);
        Grid.SetRow(hSessions, 0); Grid.SetColumn(hSessions, 1); grid.Children.Add(hSessions);
        Grid.SetRow(hCost, 0); Grid.SetColumn(hCost, 2); grid.Children.Add(hCost);

        var row = 0;
        for (var j = 0; j < shown.Count; j++)
        {
            var branch = shown[j];
            row++;
            grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            var unknown = branch.Branch == "(unknown)";
            var name = Ui.Text(unknown ? L10n.Tr("common.unknown") : branch.Branch, 12,
                null, unknown ? Palette.Secondary : Palette.Foreground, maxLines: 1, mono: true);
            name.TextTrimming = TextTrimming.CharacterEllipsis;
            name.Margin = new Thickness(0, 3, 0, 3);
            name.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(name, row); Grid.SetColumn(name, 0);
            grid.Children.Add(name);

            var sessions = _project.SessionsDetail
                .Where(s => unknown
                    ? string.IsNullOrEmpty(s.Branch) || s.Branch == "(unknown)"
                    : s.Branch == branch.Branch)
                .ToList();
            var branchTokens = sessions.Sum(s => s.Tokens.Total);
            var rows = BranchAgentRows(sessions, Report.AgentLabels());
            var copy = branch;
            var copySessions = sessions;
            var subtitle = branch.Sessions == 1
                ? L10n.Tr("project.noun.sessions") + " 1"
                : $"{branch.Sessions} " + L10n.Tr("project.noun.sessions");
            HoverLayer.Attach(name, $"project:{_projectIndex}:hover:branch:{j}",
                () => HoverCards.AgentRows(unknown ? L10n.Tr("common.unknown") : copy.Branch, null, copy.Cost,
                    branchTokens, Currency, rows, subtitle));
            ToolTip.SetTip(name, $"{branch.Branch} · {Fmt.CostAndTokens(branch.Cost, branchTokens, Currency)}");

            var sessionText = Ui.Text(branch.Sessions.ToString(System.Globalization.CultureInfo.InvariantCulture), 12, null, Palette.Secondary);
            sessionText.TextAlignment = TextAlignment.Right;
            sessionText.Margin = new Thickness(8, 0, 0, 0);
            sessionText.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(sessionText, row); Grid.SetColumn(sessionText, 1);
            grid.Children.Add(sessionText);

            var cost = Ui.Text(Fmt.Money(branch.Cost, Currency), 12, FontWeight.Medium, family: Type.Rounded);
            cost.TextAlignment = TextAlignment.Right;
            cost.Margin = new Thickness(8, 0, 0, 0);
            cost.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetRow(cost, row); Grid.SetColumn(cost, 2);
            grid.Children.Add(cost);
            HoverLayer.Attach(cost, $"project:{_projectIndex}:hover:branchcost:{j}",
                () => HoverCards.AgentRows(unknown ? L10n.Tr("common.unknown") : copy.Branch, null, copy.Cost,
                    copySessions.Sum(s => s.Tokens.Total), Currency, rows, subtitle));
        }

        var body = Ui.V(6);
        body.Children.Add(grid);
        if (all.Count > CollapsedLimit)
        {
            body.Children.Add(Widgets.ShowAllButton(_branchesExpanded, all.Count,
                L10n.Tr("project.noun.branches"), () =>
                {
                    _branchesExpanded = !_branchesExpanded;
                    _services.NotifyChanged();
                }));
        }
        content.Children.Add(body);
        return Section(L10n.Tr("project.section.by_branch"), content,
            isAll ? null : AllTimeBadge(L10n.Tr("project.noun.branches")));
    }

    private static IReadOnlyList<HoverCardRowItem> BranchAgentRows(IReadOnlyList<Session> sessions,
        IReadOnlyDictionary<string, string> labels)
    {
        var cost = new Dictionary<string, double>(StringComparer.Ordinal);
        var tokens = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var s in sessions)
        {
            cost[s.Agent] = cost.GetValueOrDefault(s.Agent) + s.Cost;
            tokens[s.Agent] = tokens.GetValueOrDefault(s.Agent) + s.Tokens.Total;
        }
        return HoverCardRowBuilder.AgentRows(cost.Keys.Union(tokens.Keys, StringComparer.Ordinal)
            .Select(a => (a, labels.GetValueOrDefault(a) ?? AgentColors.Label(a),
                cost.GetValueOrDefault(a), tokens.GetValueOrDefault(a))));
    }

    private static string Capitalize(string s) => s.Length == 0 ? s : char.ToUpperInvariant(s[0]) + s[1..];

    // MARK: - Sessions

    private Control SessionsSection(FilteredProject filtered)
    {
        var content = new SessionList(_services, filtered.SessionsDetail, Report.Config.DominantThreshold,
            Currency, $"project:{_projectIndex}:hover");
        return Section(L10n.TrL(null, "project.section.sessions", filtered.SessionsDetail.Count), content);
    }

    // MARK: - Locations

    private Control LocationsSection()
    {
        var split = PathKinds.SplitPaths(_project.Paths.ToList());
        var primary = split.Primary;
        var temporary = split.Temporary;

        var box = Ui.V(6);
        box.Children.Add(Ui.SectionTitle(L10n.Tr("project.section.locations")));
        var captionRow = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto") };
        var caption = Ui.Text(LocationsCaption(primary.Count, temporary.Count), 12, null, Palette.Secondary);
        Grid.SetColumn(caption, 0);
        captionRow.Children.Add(caption);
        if (_project.PathMissing)
        {
            var badge = Widgets.Badge(L10n.Tr("overview.badge.path_missing"), BadgeStyle.Warn,
                L10n.Tr("overview.badge.path_missing_help"));
            badge.Margin = new Thickness(6, 0, 0, 0);
            Grid.SetColumn(badge, 1);
            captionRow.Children.Add(badge);
        }
        if (_project.Paths.Count > 0)
        {
            var showRow = Ui.H(3);
            showRow.Children.Add(Ui.Text(_showLocations ? L10n.Tr("common.hide") : L10n.Tr("common.show"),
                Type.CaptionSize, null, Palette.Link));
            showRow.Children.Add(Icons.Chevron(_showLocations, 10, Palette.Link));
            var toggle = new Clickable(showRow, () =>
            {
                _showLocations = !_showLocations;
                _services.NotifyChanged();
            }, radius: 4, hand: true);
            Grid.SetColumn(toggle, 3);
            captionRow.Children.Add(toggle);
        }
        box.Children.Add(captionRow);

        if (_showLocations && _project.Paths.Count > 0)
        {
            box.Children.Add(PathsView(primary, temporary));
        }
        return Chrome.Card(box, Metrics.RowInset, 12);
    }

    private Control PathsView(IReadOnlyList<string> primary, IReadOnlyList<string> temporary)
    {
        var box = Ui.V(2);
        box.Margin = new Thickness(0, 2, 0, 0);
        if (primary.Count == 0) _showTemporary = true;
        foreach (var path in primary) box.Children.Add(PathRow(path, 10));
        if (temporary.Count == 0) return box;

        var toggleRow = Ui.H(3);
        toggleRow.Children.Add(Icons.Chevron(_showTemporary, 7.5, Palette.Secondary));
        var noun = temporary.Count == 1
            ? L10n.TrL(null, "project.locations.temporary.singular", temporary.Count)
            : L10n.TrL(null, "project.locations.temporary.plural", temporary.Count);
        var title = _showTemporary
            ? (temporary.Count == 1
                ? L10n.TrL(null, "project.locations.hide_temp.singular", temporary.Count)
                : L10n.TrL(null, "project.locations.hide_temp.plural", temporary.Count))
            : noun;
        toggleRow.Children.Add(Ui.Text(title, 12, null, Palette.Secondary));
        var toggle = new Clickable(toggleRow, () =>
        {
            _showTemporary = !_showTemporary;
            _services.NotifyChanged();
        }, L10n.Tr("project.locations.temporary_help"), radius: 4)
        {
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        toggle.Margin = new Thickness(0, 1, 0, 0);
        box.Children.Add(toggle);

        if (_showTemporary)
        {
            var temp = Ui.V(2);
            temp.Margin = new Thickness(10, 0, 0, 0);
            foreach (var path in temporary) temp.Children.Add(PathRow(path, 9.5));
            box.Children.Add(temp);
        }
        return box;
    }

    private Control PathRow(string path, double size)
    {
        var text = new MiddleTruncatedText(path, size, Palette.Secondary);
        text.TextDecorations = _project.PathMissing ? TextDecorations.Strikethrough : null;
        ToolTip.SetTip(text, path);
        return text;
    }

    private static string LocationsCaption(int primary, int temporary)
    {
        if (primary + temporary == 0) return L10n.Tr("project.locations.no_local_paths");
        if (primary == 0)
        {
            return temporary == 1
                ? L10n.TrL(null, "project.locations.temporary.singular", temporary)
                : L10n.TrL(null, "project.locations.temporary.plural", temporary);
        }
        var main = primary == 1
            ? L10n.TrL(null, "project.locations.path.singular", primary)
            : L10n.TrL(null, "project.locations.path.plural", primary);
        return temporary == 0 ? main : L10n.TrL(null, "project.locations.combined", main, temporary);
    }

    /// <summary>`--route project:N:locations`：展开 Locations。</summary>
    public void OpenLocations()
    {
        if (_showLocations) return;
        _showLocations = true;
        _services.NotifyChanged();
    }

    /// <summary>固定某个悬停卡（`project:N:hover:tokens|model:j|branch:j|day|session:j`）。</summary>
    public void PinHover(string anchor)
    {
        var id = anchor.StartsWith("project:", StringComparison.Ordinal) ? anchor : $"project:{_projectIndex}:{anchor}";
        if (id.Contains(":hover:day", StringComparison.Ordinal))
        {
            _dayChart?.PinHover();
            return;
        }
        HoverLayer.PinnedId = id;
        HoverLayer.Current?.ShowRegistered(id);
    }

    public bool LocationsOpen => _showLocations;

    public string? Anchor => _anchor;
}
