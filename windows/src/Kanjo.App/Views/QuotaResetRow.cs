using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 额度重置行（QuotaResetSettingsRow）：agent 色点 + 名称 + 来源；下一重置时刻与窗口起点；
/// 星期 / 时刻下拉 + Apply / Reset。重置值通过 CLI 写入（`quota_windows.<agent>.weekly_reset`）。
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
        var left = Ui.H(5);
        left.Children.Add(Ui.Dot(_agent, 6));
        left.Children.Add(Ui.Text(label, 11.5, maxLines: 1));
        Grid.SetColumn(left, 0);
        header.Children.Add(left);
        var source = Ui.Text(_quota?.Source ?? "none", 10, null,
            _quota is null ? Palette.Tertiary : Palette.Secondary, mono: true);
        source.TextAlignment = TextAlignment.Right;
        Grid.SetColumn(source, 2);
        header.Children.Add(source);
        Children.Add(header);

        if (_quota is { } quota && ReportDates.ParseTimestamp(quota.WeeklyResetsAt) is { } reset)
        {
            var row = Ui.H(4);
            row.Margin = new Thickness(11, 0, 0, 0);
            row.Children.Add(Ui.Text(Stamp(reset, _timezone), 10.5, null, Palette.Foreground));
            if (RangeEngine.WindowStart(quota, DateTimeOffset.UtcNow, _timezone) is { } start)
            {
                row.Children.Add(Ui.Text(
                    "· " + L10n.TrL(null, "settings.quota_window_since", Stamp(start, _timezone),
                        quota.WeeklyWindowHours), 10, null, Palette.Secondary));
            }
            Children.Add(row);
        }
        else
        {
            var none = Ui.Text(L10n.Tr("settings.no_reset_info"), 10.5, null, Palette.Tertiary);
            none.Margin = new Thickness(11, 0, 0, 0);
            Children.Add(none);
        }

        var controls = Ui.H(6);
        controls.Margin = new Thickness(11, 0, 0, 0);
        var weekdayLabels = Weekdays.Select(w => L10n.Tr(w.LabelKey)).ToList();
        var weekdayIndex = Array.FindIndex(Weekdays, w => w.Key == _weekday);
        controls.Children.Add(new DropdownControl(weekdayLabels[Math.Max(weekdayIndex, 0)], weekdayLabels,
            index =>
            {
                _weekday = Weekdays[index].Key;
                Save($"{_weekday} {_time}");
            }, enabled: CanEdit, width: 68));

        var times = AvailableTimes;
        var timeIndex = times.IndexOf(_time);
        controls.Children.Add(new DropdownControl(times[Math.Max(timeIndex, 0)], times, index =>
        {
            _time = times[index];
            Save($"{_weekday} {_time}");
        }, enabled: CanEdit, width: 64));

        controls.Children.Add(Ui.BorderedButton(L10n.Tr("common.apply"),
            () => Save($"{_weekday} {_time}"), enabled: CanEdit));
        controls.Children.Add(Ui.BorderedButton(L10n.Tr("common.reset"),
            () => Save(null), enabled: CanEdit && _quota?.Source == "manual"));
        if (!CanEdit)
        {
            controls.Opacity = 0.6;
            ToolTip.SetTip(controls, L10n.Tr("settings.renews_day_disabled_help"));
        }
        Children.Add(controls);

        if (_saving)
        {
            var saving = Ui.Text(L10n.Tr("settings.saving"), 10, null, Palette.Secondary);
            saving.Margin = new Thickness(11, 0, 0, 0);
            Children.Add(saving);
        }
        if (_error is { } error)
        {
            var block = Widgets.StatusBlock(true,
            [
                Ui.Text(error, 10.5, null, Palette.Bad, wrap: true),
            ]);
            block.Margin = new Thickness(11, 0, 0, 0);
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
