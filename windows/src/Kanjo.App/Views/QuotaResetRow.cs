using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 额度重置行（QuotaResetSettingsRow）：agent 色点 + 名称 + 来源；下一重置时刻与窗口起点；
/// 星期 / 时刻下拉 + Apply / Reset。重置值通过 CLI 写入（`quota_windows.<agent>.weekly_reset`）。
/// 下拉是 Fluent ComboBox，指针停在上面的滚轮滚页面而不是改值（见 <see cref="WheelPolicy"/>）。
/// </summary>
public sealed class QuotaResetRow : StackPanel
{
    private static readonly (string Key, string LabelKey)[] Weekdays =
    [
        ("mon", "weekday.mon"), ("tue", "weekday.tue"), ("wed", "weekday.wed"),
        ("thu", "weekday.thu"), ("fri", "weekday.fri"), ("sat", "weekday.sat"), ("sun", "weekday.sun"),
    ];

    private readonly AppServices _services;
    private readonly string _agent;
    private readonly QuotaWindow? _quota;
    private readonly TimeZoneInfo _timezone;
    private string _weekday;
    private string _time;
    private bool _saving;
    private string? _error;

    public QuotaResetRow(AppServices services, string agent, UsageReport report)
    {
        _services = services;
        _agent = agent;
        _timezone = RangeEngine.TimezoneOf(report);
        report.QuotaWindows?.TryGetValue(agent, out _quota);
        var label = report.AgentLabels().GetValueOrDefault(agent)
                    ?? AgentColors.DefaultLabels.GetValueOrDefault(agent, agent);
        (_weekday, _time) = QuotaResetValue.Parse(_quota, _timezone);

        Orientation = Orientation.Vertical;
        Spacing = 4;
        Build(label);
    }

    private void Build(string label)
    {
        Children.Clear();
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        var left = Ui.H(6);
        left.Children.Add(Ui.Dot(_agent, 8));
        left.Children.Add(Ui.Text(label, Type.BodySize, maxLines: 1));
        Grid.SetColumn(left, 0);
        header.Children.Add(left);
        var source = Ui.Text(_quota?.Source ?? "none", Type.CaptionSize, null, Palette.Secondary, mono: true);
        source.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(source, 2);
        header.Children.Add(source);
        Children.Add(new Border
        {
            Child = header,
            Padding = new Thickness(Metrics.RowInset, 10, Metrics.RowInset, 2),
        });

        if (_quota is { } quota && ReportDates.ParseTimestamp(quota.WeeklyResetsAt) is { } reset)
        {
            // 日期行可能很长（「Fri, Oct 30 at 16:40 · window since …」），必须能折行，
            // 否则会画出卡片右边界。
            var line = new TextBlock
            {
                FontSize = Type.CaptionSize,
                FontFamily = Type.Font,
                LineHeight = Math.Round(Type.CaptionSize * 1.35, 1),
                TextWrapping = TextWrapping.Wrap,
            };
            line.Inlines!.Add(new Avalonia.Controls.Documents.Run(Stamp(reset, _timezone))
            {
                Foreground = Palette.Foreground,
            });
            if (RangeEngine.WindowStart(quota, DateTimeOffset.UtcNow, _timezone) is { } start)
            {
                line.Inlines.Add(new Avalonia.Controls.Documents.Run(
                    " · " + L10n.TrL(null, "settings.quota_window_since", Stamp(start, _timezone),
                        quota.WeeklyWindowHours))
                {
                    Foreground = Palette.Secondary,
                });
            }
            Children.Add(new Border
            {
                Child = line,
                Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 6),
            });
        }
        else
        {
            Children.Add(new Border
            {
                Child = Ui.Text(L10n.Tr("settings.no_reset_info"), Type.CaptionSize, null, Palette.Secondary),
                Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 6),
            });
        }

        // 控件放第二行（和 Mac 一致：日期在上、控件在下），按钮右对齐单独一行。
        // 360px 里「星期 + 时刻 + Apply + Reset」一行放不下，"Reset" 会被切掉。
        var pickers = Ui.H(8);
        var weekdayLabels = Weekdays.Select(w => L10n.Tr(w.LabelKey)).ToList();
        var weekdayIndex = Array.FindIndex(Weekdays, w => w.Key == _weekday);
        pickers.Children.Add(Picker.Make(weekdayLabels, Math.Max(weekdayIndex, 0), index =>
        {
            _weekday = Weekdays[index].Key;
            Save($"{_weekday} {_time}");
        }, enabled: CanEdit, minWidth: 96));

        var times = AvailableTimes;
        var timeIndex = times.IndexOf(_time);
        pickers.Children.Add(Picker.Make(times, Math.Max(timeIndex, 0), index =>
        {
            _time = times[index];
            Save($"{_weekday} {_time}");
        }, enabled: CanEdit, minWidth: 92));

        var buttons = Ui.H(8);
        buttons.HorizontalAlignment = HorizontalAlignment.Right;
        buttons.Children.Add(Ui.StandardButton(L10n.Tr("common.apply"),
            () => Save($"{_weekday} {_time}"), enabled: CanEdit));
        buttons.Children.Add(Ui.StandardButton(L10n.Tr("common.reset"),
            () => Save(null), enabled: CanEdit && _quota?.Source == "manual"));

        var controls = Ui.V(8);
        controls.Children.Add(pickers);
        // 按钮右对齐，占满整行宽度，不会被右边的卡片边缘切掉。
        var buttonRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Grid.SetColumn(buttons, 1);
        buttonRow.Children.Add(buttons);
        controls.Children.Add(buttonRow);
        if (!CanEdit && _services.CanEditSubscriptions == false)
        {
            ToolTip.SetTip(controls, L10n.Tr("settings.renews_day_disabled_help"));
        }
        Children.Add(new Border
        {
            Child = controls,
            Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10),
        });

        if (_saving)
        {
            Children.Add(new Border
            {
                Child = Ui.Text(L10n.Tr("settings.saving"), Type.CaptionSize, null, Palette.Secondary),
                Padding = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 8),
            });
        }
        if (_error is { } error)
        {
            var block = Widgets.StatusBlock(true,
            [
                Ui.Text(error, Type.CaptionSize, null, Palette.Bad, wrap: true),
            ]);
            block.Margin = new Thickness(Metrics.RowInset, 0, Metrics.RowInset, 10);
            Children.Add(block);
        }
    }

    private bool CanEdit => _services.CanEditSubscriptions && !_saving && !_services.IsLoading;

    private List<string> AvailableTimes => QuotaResetValue.Times(_time);

    private void Save(string? value)
    {
        if (!CanEdit) return;
        _saving = true;
        _error = null;
        Build(Label());
        Task.Run(() =>
        {
            try
            {
                _services.Config.SetWeeklyReset(_agent, value);
                _services.Refresh();
            }
            catch (Exception e)
            {
                _error = e.Message;
            }
            _saving = false;
            _services.NotifyChanged();
        });
    }

    private string Label() => _agent;

    /// <summary>`Sat, Oct 31 at 10:40`（Swift 的 EEEMMMdHHmm 模板）。</summary>
    public static string Stamp(DateTimeOffset date, TimeZoneInfo timezone)
    {
        var local = TimeZoneInfo.ConvertTime(date, timezone);
        var culture = Fmt.CultureFor(null);
        var weekday = culture.DateTimeFormat.GetAbbreviatedDayName(local.DayOfWeek);
        var month = culture.DateTimeFormat.GetAbbreviatedMonthName(local.Month);
        var lang = L10n.CurrentLanguage;
        if (lang.StartsWith("zh", StringComparison.Ordinal))
        {
            return $"{local.Month}月{local.Day}日 {weekday} {local:HH:mm}";
        }
        return $"{weekday}, {month} {local.Day} at {local:HH:mm}";
    }
}

