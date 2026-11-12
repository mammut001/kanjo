using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 磁盘页（DiskView.swift）：Hero（总量 / 可回收 / 扫描时间 + 重扫提示 / ledger 说明）→ Older than 分段
/// → By agent（可展开、逐条勾选、状态徽章）→ 清理条 → dry-run 计划卡 → 结果卡。
/// </summary>
public sealed class DiskPage : Grid, ISnapshotPage
{
    /// <summary>截图模式：交出页面内容（不含滚动容器），由面板按整页高度渲染。</summary>
    public Control SnapshotBody
    {
        get
        {
            if (_page.Children.Count > 0 && _page.Children[0] is StackPanel container &&
                container.Children.Count > 0 && container.Children[0] is ScrollViewer scroll &&
                scroll.Content is Control content)
            {
                scroll.Content = null;
                // 选中条目时页面底部还有一条清除条，一起拼进整页高度。
                if (container.Children.Count > 1)
                {
                    container.Children.RemoveAt(0);
                    container.Children.Insert(0, content);
                    return container;
                }
                return content;
            }
            return _page;
        }
    }

    private readonly AppServices _services;
    private readonly bool _expandAll;
    private readonly bool _snapshot;
    private readonly Action _onBack;
    private readonly Action _onSettings;

    private readonly HashSet<string> _expanded = new(StringComparer.Ordinal);
    private readonly HashSet<string> _selected = new(StringComparer.Ordinal);
    private DiskAge _age = DiskAge.Any;
    private bool _checking;
    private bool _applying;
    private CleanResult? _pending;
    private CleanResult? _finished;
    private string? _actionError;

    private readonly StackPanel _page = new() { Orientation = Orientation.Vertical };
    private readonly Panel _overlay = new();

    public DiskPage(AppServices services, bool expandAll, bool snapshot, Action onBack, Action onSettings)
    {
        _services = services;
        _expandAll = expandAll;
        _snapshot = snapshot;
        _onBack = onBack;
        _onSettings = onSettings;

        if (expandAll && services.Disk.Report is { } report)
        {
            foreach (var agent in report.Agents) _expanded.Add(agent.Agent);
        }
        _selected.IntersectWith(Services.Disk.Report?.AllEntries.Where(e => e.IsReclaimable).Select(e => e.Id)
                                ?? []);

        RowDefinitions = new RowDefinitions("*");
        Children.Add(_page);
        Children.Add(_overlay);
        _services.Disk.Changed += OnDiskChanged;
        // 面板重建会换掉整个页面：脱离视觉树时退订，避免旧页面越积越多。
        DetachedFromVisualTree += (_, _) => _services.Disk.Changed -= OnDiskChanged;
        Rebuild();

        if (!snapshot && !_services.Disk.IsLoading &&
            ((!_services.Disk.HasReport && _services.Disk.Error is null) || _services.Disk.IsStale()))
        {
            _services.Disk.Refresh();
        }
    }

    private AppServices Services => _services;

    private void OnDiskChanged()
    {
        if (!Avalonia.Threading.Dispatcher.UIThread.CheckAccess())
        {
            Avalonia.Threading.Dispatcher.UIThread.Post(Rebuild);
            return;
        }
        Rebuild();
    }

    public void Rebuild()
    {
        if (_expandAll && _services.Disk.Report is { } r)
        {
            foreach (var agent in r.Agents) _expanded.Add(agent.Agent);
        }
        var reclaimable = _services.Disk.Report?.AllEntries.Where(e => e.IsReclaimable).Select(e => e.Id)
            .ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>(StringComparer.Ordinal);
        _selected.IntersectWith(reclaimable);

        _page.Children.Clear();
        if (_services.Disk.Report is { } report) _page.Children.Add(LoadedContent(report));
        else if (_services.Disk.Error is { } error) _page.Children.Add(Failure(error));
        else _page.Children.Add(Loading());

        RebuildOverlay();
    }

    private Control Back() => Widgets.BackButton(L10n.Tr("disk.navigation.overview"), _onBack);

    private Control Loading()
    {
        var box = Ui.V(8);
        box.Margin = new Thickness(Metrics.PagePadding, 12, Metrics.PagePadding, 0);
        var back = Back();
        back.Margin = new Thickness(Metrics.RowInset - 4 - Metrics.PagePadding, 0, 0, 0);
        box.Children.Add(back);
        box.Children.Add(new Panel { Height = 60 });
        var spinner = new Spinner(16) { HorizontalAlignment = HorizontalAlignment.Center };
        box.Children.Add(spinner);
        var text = Ui.Text(L10n.Tr("disk.loading"), 11, null, Palette.Secondary);
        text.TextAlignment = TextAlignment.Center;
        box.Children.Add(text);
        return box;
    }

    private Control Failure(string message)
    {
        var box = Ui.V(12);
        box.Margin = new Thickness(Metrics.PagePadding, 12, Metrics.PagePadding, 10);
        var back = Back();
        back.Margin = new Thickness(Metrics.RowInset - 4 - Metrics.PagePadding, 0, 0, 0);
        box.Children.Add(back);
        var title = Ui.H(4);
        title.Children.Add(Icons.WarnTriangle(11, Palette.Bad));
        title.Children.Add(Ui.Text(L10n.Tr("disk.error_title"), 14, FontWeight.SemiBold, Palette.Bad));
        box.Children.Add(title);
        box.Children.Add(new Border
        {
            Child = Ui.Text(message, 11, null, Palette.Foreground, wrap: true, mono: true),
            Padding = new Thickness(10),
            CornerRadius = new CornerRadius(8),
            Background = Palette.BadFill,
        });
        box.Children.Add(Ui.Text(L10n.TrL(null, "settings.current_source", _services.Disk.SourceDescription),
            10.5, null, Palette.Secondary, wrap: true));
        var actions = Ui.H(8);
        actions.Children.Add(Ui.ProminentButton(L10n.Tr("common.retry"), () => _services.Disk.Refresh(rescan: true)));
        actions.Children.Add(Ui.BorderedButton(L10n.Tr("menu.open_settings"), _onSettings));
        box.Children.Add(actions);
        box.Children.Add(Ui.Text(L10n.Tr("disk.expected_json"), 10.5, null, Palette.Secondary, wrap: true));
        return box;
    }

    private Control LoadedContent(DiskReport report)
    {
        var agents = report.Agents.OrderByDescending(a => a.Bytes).ToList();
        var maxBytes = agents.Count == 0 ? 0 : agents.Max(a => a.Bytes);

        var scroll = new ScrollViewer
        {
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            VerticalScrollBarVisibility = _snapshot
                ? Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled
                : Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
            Background = Brushes.Transparent,
        };

        var root = Ui.V(Metrics.SectionSpacing);
        var back = Back();
        back.Margin = new Thickness(Metrics.RowInset - 4 - Metrics.PagePadding, 0, 0, 0);
        root.Children.Add(back);
        root.Children.Add(Hero(report).WithMargin(Metrics.RowInset - Metrics.PagePadding, 0,
            Metrics.RowInset - Metrics.PagePadding, 0));
        root.Children.Add(AgePicker().WithMargin(Metrics.RowInset - Metrics.PagePadding, 0,
            Metrics.RowInset - Metrics.PagePadding, 0));

        var content = Ui.V(12);
        if (agents.Count == 0)
        {
            content.Children.Add(Ui.Text(L10n.Tr("disk.no_disk_usage"), 11, null, Palette.Secondary));
        }
        foreach (var agent in agents) content.Children.Add(AgentBlock(agent, maxBytes));
        var section = Chrome.Section(L10n.Tr("disk.by_agent"), content, padding: Metrics.RowInset);
        root.Children.Add(section);

        if (_actionError is { } banner && _pending is null)
        {
            root.Children.Add(Widgets.StatusBlock(true,
                [Ui.Text(banner, 10.5, null, Palette.Bad, wrap: true)])
                .WithMargin(Metrics.RowInset - Metrics.PagePadding, 0, Metrics.RowInset - Metrics.PagePadding, 0));
        }

        var footer = Ui.Text(
            L10n.TrL(null, "overview.generated_footer", Fmt.Timestamp(report.GeneratedAt), report.SchemaVersion),
            10, null, Palette.Tertiary);
        ToolTip.SetTip(footer, _services.Disk.SourceDescription);
        root.Children.Add(footer.WithMargin(Metrics.RowInset - Metrics.PagePadding, 0,
            Metrics.RowInset - Metrics.PagePadding, 0));

        root.Margin = new Thickness(Metrics.PagePadding, 12, Metrics.PagePadding, 10);
        scroll.Content = root;

        var container = Ui.V(0);
        container.Children.Add(scroll);
        if (_selected.Count > 0) container.Children.Add(CleanBar(report));
        return container;
    }

    private Control Hero(DiskReport report)
    {
        var box = Ui.V(6);
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var left = Ui.V(1);
        left.Children.Add(Ui.Text(L10n.Tr("disk.total"), 11, null, Palette.Secondary));
        left.Children.Add(Widgets.HeroAmount(Fmt.Bytes(report.TotalBytes), 28));
        Grid.SetColumn(left, 0);
        top.Children.Add(left);

        var right = Ui.V(1);
        right.HorizontalAlignment = HorizontalAlignment.Right;
        var reclaimLabel = Ui.Text(L10n.Tr("disk.reclaimable"), 11, null, Palette.Secondary);
        reclaimLabel.TextAlignment = TextAlignment.Right;
        right.Children.Add(reclaimLabel);
        var reclaim = Widgets.HeroAmount(Fmt.Bytes(report.ReclaimableBytes), 28, Palette.Accent);
        reclaim.TextAlignment = TextAlignment.Right;
        right.Children.Add(reclaim);
        Grid.SetColumn(right, 1);
        top.Children.Add(right);
        box.Children.Add(top);

        var captionRow = Ui.H(4);
        // 和 Mac 一样按真实时钟算「Scanned N min ago」（DiskView 里是 TimelineView(.now)），
        // 不用截图模式的固定时间：扫描时间本身就是数据里的值。
        captionRow.Children.Add(Ui.Text(DiskScanCaption.Text(report, DateTimeOffset.UtcNow), 10.5, null,
            Palette.Secondary));
        if (_services.Disk.IsRescanning)
        {
            captionRow.Children.Add(Ui.Text(L10n.Tr("disk.rescanning"), 10.5, null, Palette.Secondary));
            captionRow.Children.Add(new Spinner(9));
        }
        box.Children.Add(captionRow);

        var note = Ui.H(4);
        note.Children.Add(Icons.InfoCircle(10, Palette.Tertiary));
        note.Children.Add(Ui.Text(L10n.Tr("disk.ledger_note"), 10.5, null, Palette.Tertiary, wrap: true));
        box.Children.Add(note);
        return box;
    }

    private Control AgePicker()
    {
        var box = Ui.V(4);
        box.Children.Add(Ui.Text(L10n.Tr("disk.older_than"), 11, null, Palette.Secondary));
        var options = DiskAges.All.Select(a => a.Label()).ToList();
        var segmented = new SegmentedControl(options, DiskAges.All.ToList().IndexOf(_age), index =>
        {
            _age = DiskAges.All[index];
            Rebuild();
        })
        {
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        if (_checking || _applying || _pending is not null)
        {
            segmented.Opacity = 0.55;
        }
        ToolTip.SetTip(segmented, L10n.Tr("disk.age_help"));
        box.Children.Add(segmented);
        return box;
    }

    private Control AgentBlock(DiskAgent agent, long maxBytes)
    {
        var open = _expanded.Contains(agent.Agent);
        var fraction = maxBytes > 0 ? agent.Bytes / (double)maxBytes : 0;

        var box = Ui.V(6);
        var header = Ui.V(5);
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto") };
        var left = Ui.H(6);
        left.Children.Add(new Avalonia.Controls.Shapes.Ellipse
        {
            Width = 6, Height = 6, Fill = Palette.Agent(agent.Agent), VerticalAlignment = VerticalAlignment.Center,
        });
        left.Children.Add(Ui.Text(agent.Label, 12));
        left.Children.Add(Ui.Text("·", 12, null, Palette.Tertiary));
        left.Children.Add(Ui.Text(Fmt.Bytes(agent.Bytes), 12, FontWeight.Medium, family: Type.Rounded));
        Grid.SetColumn(left, 0);
        line.Children.Add(left);
        var chevron = Icons.Chevron(open, 9, Palette.Tertiary);
        chevron.HorizontalAlignment = HorizontalAlignment.Right;
        Grid.SetColumn(chevron, 3);
        line.Children.Add(chevron);
        header.Children.Add(line);
        header.Children.Add(new FractionBar(Palette.Agent(agent.Agent), fraction));

        var toggle = new Clickable(header, () =>
        {
            if (!_expanded.Remove(agent.Agent)) _expanded.Add(agent.Agent);
            Rebuild();
        }, open ? L10n.TrL(null, "disk.hide_agent_entries", agent.Label)
            : L10n.TrL(null, "disk.show_agent_entries", agent.Label), radius: 4);
        box.Children.Add(toggle);

        if (open)
        {
            var list = Ui.V(0);
            list.Margin = new Thickness(0, 2, 0, 0);
            for (var i = 0; i < agent.Entries.Count; i++)
            {
                list.Children.Add(EntryRow(agent.Entries[i]));
                if (i < agent.Entries.Count - 1) list.Children.Add(Widgets.RowDivider(0, 0));
            }
            box.Children.Add(list);
        }
        return box;
    }

    private Control EntryRow(DiskEntry entry)
    {
        const double slot = 16;
        var box = Ui.V(3);
        box.Margin = new Thickness(0, 6, 0, 6);

        var top = new Grid { ColumnDefinitions = new ColumnDefinitions($"{slot},Auto,*,Auto") };
        if (entry.IsReclaimable)
        {
            var checkedNow = _selected.Contains(entry.Id);
            var check = new CheckBoxControl(checkedNow, _checking || _applying || _pending is not null, () =>
            {
                if (!_selected.Remove(entry.Id)) _selected.Add(entry.Id);
                Rebuild();
            });
            ToolTip.SetTip(check, L10n.TrL(null, "disk.clean_path", entry.Path));
            check.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(check, 0);
            top.Children.Add(check);
        }
        else
        {
            var spacer = new Panel { Width = slot, Height = slot };
            Grid.SetColumn(spacer, 0);
            top.Children.Add(spacer);
        }

        var badge = Widgets.Badge(entry.RawKind);
        badge.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(badge, 1);
        top.Children.Add(badge);

        var pill = StatePill(entry);
        pill.HorizontalAlignment = HorizontalAlignment.Right;
        Grid.SetColumn(pill, 3);
        top.Children.Add(pill);
        box.Children.Add(top);

        var detail = Ui.V(2);
        detail.Margin = new Thickness(slot + 6, 0, 0, 0);
        var path = Ui.Text(entry.Path, 10.5, null, Palette.Secondary, maxLines: 1, mono: true);
        path.TextTrimming = TextTrimming.CharacterEllipsis;
        ToolTip.SetTip(path, entry.Path);
        detail.Children.Add(path);
        var key = entry.Files == 1 ? "disk.file.singular" : "disk.file.plural";
        var meta = Ui.Text(
            $"{Fmt.Bytes(entry.Bytes)} · {L10n.TrL(null, key, entry.Files)} · {ShortDate.Day(entry.Newest)}",
            10.5, null, Palette.Secondary);
        if (!string.IsNullOrEmpty(entry.Note)) ToolTip.SetTip(meta, entry.Note);
        detail.Children.Add(meta);
        box.Children.Add(detail);
        return box;
    }

    private static Control StatePill(DiskEntry entry)
    {
        if (entry.Deletable == DiskDeletable.Never)
        {
            return Widgets.Badge(L10n.Tr("disk.badge.kept"), BadgeStyle.Neutral,
                L10n.Tr("disk.badge.kept_help"));
        }
        if (entry.Blocked.Count == 0)
        {
            return Widgets.Badge(L10n.Tr("disk.badge.reclaimable"), BadgeStyle.Good,
                L10n.Tr("disk.badge.reclaimable_help"));
        }
        var column = Ui.V(2);
        foreach (var reason in entry.Blocked)
        {
            var badge = Widgets.Badge(L10n.TrL(null, "disk.blocked_reason", DiskBlock.Short(reason)),
                BadgeStyle.Warn, DiskBlock.Explanation(reason));
            badge.HorizontalAlignment = HorizontalAlignment.Right;
            column.Children.Add(badge);
        }
        return column;
    }

    private Control CleanBar(DiskReport report)
    {
        var entries = report.AllEntries.Where(e => _selected.Contains(e.Id)).ToList();
        var bytes = entries.Sum(e => e.Bytes);
        var n = entries.Count;
        var title = _checking
            ? L10n.Tr("disk.checking")
            : L10n.TrL(null, n == 1 ? "disk.clean_button.singular" : "disk.clean_button.plural", n,
                Fmt.Bytes(bytes));

        var button = Ui.ProminentButton(title, DryRun);
        button.HorizontalAlignment = HorizontalAlignment.Stretch;
        if (_checking || _applying) button.Opacity = 0.6;
        ToolTip.SetTip(button, L10n.Tr("disk.clean_help"));

        var box = Ui.V(0);
        box.Children.Add(Widgets.RowDivider(0, 0));
        var pad = new Border
        {
            Child = button,
            Padding = new Thickness(12, 8, 12, 8),
        };
        box.Children.Add(pad);
        return new Border
        {
            Child = box,
            Background = Palette.PanelBackground,
        };
    }

    // MARK: - 计划 / 结果卡

    private void RebuildOverlay()
    {
        _overlay.Children.Clear();
        if (_pending is null && _finished is null) return;
        _overlay.Background = Palette.Scrim;
        var card = new Border
        {
            Child = _finished is { } finished ? ResultCard(finished) : PlanCard(_pending!),
            Background = Palette.CardBackground,
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(14),
            Margin = new Thickness(12),
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        _overlay.Children.Add(card);
    }

    private Control PlanCard(CleanResult result)
    {
        var box = Ui.V(10);
        box.Children.Add(Ui.Text(WindowsL10n.Tr("disk.card.confirm_title"), 14, FontWeight.SemiBold));
        box.Children.Add(Ui.Text(_age.Caption(), 10.5, null, Palette.Secondary));

        var body = Ui.V(8);
        var groups = CleanPlan.Groups(_services.Disk.Report ?? DiskReport.Empty, result.Moved);
        if (result.Moved.Count == 0)
        {
            body.Children.Add(Ui.Text(L10n.Tr("disk.card.nothing_moved"), 12, null, Palette.Secondary));
        }
        foreach (var group in groups)
        {
            var block = Ui.V(2);
            block.Children.Add(Ui.Text(group.Title, 12, FontWeight.Medium));
            foreach (var path in group.Paths)
            {
                var text = Ui.Text(path, 10, null, Palette.Secondary, maxLines: 1, mono: true);
                text.TextTrimming = TextTrimming.CharacterEllipsis;
                ToolTip.SetTip(text, path);
                block.Children.Add(text);
            }
            block.Children.Add(Ui.Text(CleanPlan.CountAndSize(group.Paths.Count, group.Bytes), 10.5, null,
                Palette.Secondary));
            body.Children.Add(block);
        }
        body.Children.Add(Ui.Text(L10n.TrL(null, "disk.card.total",
                CleanPlan.CountAndSize(result.Moved.Count, result.FreedBytes)), 11, FontWeight.Medium));
        body.Children.Add(SkippedList(result));

        var scroll = new ScrollViewer
        {
            Content = body,
            MaxHeight = 320,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
        };
        box.Children.Add(scroll);
        box.Children.Add(Ui.Text(WindowsL10n.Tr("disk.card.warning"), 10.5, null, Palette.Secondary, wrap: true));
        if (_actionError is { } error)
        {
            box.Children.Add(Ui.Text(error, 10.5, null, Palette.Bad, wrap: true, mono: true));
        }

        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var cancel = Ui.BorderedButton(L10n.Tr("common.cancel"), () =>
        {
            _pending = null;
            _actionError = null;
            Rebuild();
        }, enabled: !_applying);
        Grid.SetColumn(cancel, 0);
        actions.Children.Add(cancel);
        var move = Ui.ProminentButton(WindowsL10n.Tr("disk.card.move_button"), Move, Palette.Bad);
        Grid.SetColumn(move, 2);
        actions.Children.Add(move);
        if (_applying)
        {
            move.Opacity = 0.6;
            actions.Children.Add(new Spinner(10) { HorizontalAlignment = HorizontalAlignment.Right });
        }
        else if (result.Moved.Count == 0)
        {
            move.Opacity = 0.5;
        }
        box.Children.Add(actions);
        return box;
    }

    private Control ResultCard(CleanResult result)
    {
        var box = Ui.V(10);
        box.Children.Add(Ui.Text(WindowsL10n.Tr("disk.card.moved_title"), 14, FontWeight.SemiBold));
        box.Children.Add(Widgets.HeroAmount(
            L10n.TrL(null, "disk.card.freed", Fmt.Bytes(result.FreedBytes)), 20, Palette.Accent));
        box.Children.Add(SkippedList(result));
        var done = Ui.ProminentButton(L10n.Tr("common.done"), () =>
        {
            _finished = null;
            _actionError = null;
            Rebuild();
        });
        done.HorizontalAlignment = HorizontalAlignment.Right;
        box.Children.Add(done);
        return box;
    }

    private static Control SkippedList(CleanResult result)
    {
        var box = Ui.V(3);
        if (result.Skipped.Count == 0) return box;
        box.Children.Add(Ui.Text(L10n.Tr("disk.card.skipped"), 10, FontWeight.SemiBold, Palette.Secondary));
        foreach (var skip in result.Skipped)
        {
            var item = Ui.V(1);
            item.Children.Add(Ui.Text($"{skip.Id} — {DiskBlock.Short(skip.Reason)}", 11, null,
                Palette.WarnInk, wrap: true));
            item.Children.Add(Ui.Text(DiskBlock.Explanation(skip.Reason), 10, null, Palette.Secondary,
                wrap: true));
            box.Children.Add(item);
        }
        return box;
    }

    /// <summary>先 dry-run 出计划；用户看过之后再带 --yes。</summary>
    private void DryRun()
    {
        if (_checking || _applying) return;
        var ids = _selected.OrderBy(i => i, StringComparer.Ordinal).ToList();
        if (ids.Count == 0) return;
        _checking = true;
        _actionError = null;
        Rebuild();
        var older = _age.Argument();
        Task.Run(() =>
        {
            try
            {
                _pending = _services.Disk.Clean(ids, older, confirmed: false);
            }
            catch (Exception e)
            {
                _actionError = e.Message;
            }
            _checking = false;
            Rebuild();
        });
    }

    /// <summary>用户已经看过 dry-run 计划，这一步才带 --yes。</summary>
    private void Move()
    {
        if (_applying) return;
        _applying = true;
        _actionError = null;
        Rebuild();
        var ids = _selected.OrderBy(i => i, StringComparer.Ordinal).ToList();
        var older = _age.Argument();
        Task.Run(() =>
        {
            try
            {
                var result = _services.Disk.Clean(ids, older, confirmed: true);
                _pending = null;
                _finished = result;
                _selected.Clear();
                _services.Disk.Refresh(rescan: true);
            }
            catch (Exception e)
            {
                _actionError = e.Message;
            }
            _applying = false;
            Rebuild();
        });
    }

    /// <summary>Esc 取消计划 / Enter 关闭结果卡（面板窗口转发键事件到页面）。</summary>
    public bool HandleKey(Key key)
    {
        if (key == Key.Escape && _pending is not null && !_applying)
        {
            _pending = null;
            _actionError = null;
            Rebuild();
            return true;
        }
        if (key is Key.Enter or Key.Return && _finished is not null)
        {
            _finished = null;
            _actionError = null;
            Rebuild();
            return true;
        }
        return false;
    }

    /// <summary>测试 / 截图用：当前选中的条目。</summary>
    public IReadOnlyCollection<string> Selected => _selected;
}
