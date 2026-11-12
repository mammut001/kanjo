using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.TextFormatting;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// by_day 时间线（DayChart.swift）：每个活跃日一根柱，x 轴是真实时间（空白日自然留空）。
/// 悬停显示当天金额与 token（其他柱子变淡），0.35 秒后浮出按 agent 的悬停卡。
/// 轴：左侧 3 档金额网格线，下方约 4 个日期标签。
/// </summary>
public sealed class DayChartView : Panel
{
    private const double ChartHeight = 110;
    private const double AxisLabelHeight = 12;
    private const double YAxisWidth = 30;
    private const int YTicks = 3;

    public sealed record DayPoint(string Day, DateOnly Date, double Cost, long Tokens,
        IReadOnlyDictionary<string, double>? ByAgent, IReadOnlyDictionary<string, long>? ByAgentTokens);

    private readonly List<DayPoint> _points;
    private readonly string _currency;
    private readonly IReadOnlyDictionary<string, string> _labels;
    private readonly string _pinnedId;
    private readonly TextBlock _summaryText;
    private readonly BarArea _area;

    public DayChartView(IReadOnlyList<DayCost> days, string currency, IBrush color,
        IReadOnlyDictionary<string, string> labels, string? pinnedId = null)
    {
        _currency = currency;
        _labels = labels;
        _pinnedId = pinnedId ?? "";
        _points = days
            .Select(d => ReportDates.ParseDay(d.Day) is { } date
                ? new DayPoint(d.Day, date, d.Cost, d.Tokens, d.ByAgent?.ToDictionary(), d.ByAgentTokens?.ToDictionary())
                : null)
            .Where(p => p is not null)
            .Select(p => p!)
            .OrderBy(p => p.Date)
            .ToList();

        var box = Ui.V(6);
        _summaryText = Ui.Text("", 12);
        box.Children.Add(_summaryText);
        _area = new BarArea(_points, color, this) { Height = ChartHeight };
        box.Children.Add(_area);
        Children.Add(box);
        UpdateSummary(null);
    }

    public IReadOnlyList<DayPoint> Points => _points;

    private void UpdateSummary(DayPoint? highlight)
    {
        if (highlight is { } h)
        {
            _summaryText.Text = $"{Fmt.Day(h.Day)} · {Fmt.Money(h.Cost, _currency)} · " +
                                L10n.TrL(null, "overview.tokens_count", Fmt.Tokens(h.Tokens));
            _summaryText.Foreground = Palette.Foreground;
            _area.Highlight = h;
            return;
        }
        _summaryText.Text = _points.Count == 1
            ? L10n.TrL(null, "chart.active_day.singular", _points.Count)
            : L10n.TrL(null, "chart.active_day.plural", _points.Count);
        _summaryText.Foreground = Palette.Secondary;
        _area.Highlight = null;
    }

    /// <summary>`--route` 里固定的悬停卡：高亮最近一个有花费的柱子并展开卡片。</summary>
    public void PinHover()
    {
        if (_points.Count == 0) return;
        var point = _points.LastOrDefault(p => p.Cost > 0 || p.Tokens > 0) ?? _points[^1];
        UpdateSummary(point);
        _area.ShowCard(point);
    }

    /// <summary>柱子区域：底层自绘网格 / 柱子 / 竖线，上层是悬停卡的透明锚点。</summary>
    private sealed class BarArea : Panel
    {
        private readonly List<DayPoint> _points;
        private readonly DayChartView _owner;
        private readonly Surface _surface;
        private DayPoint? _highlight;

        public BarArea(List<DayPoint> points, IBrush color, DayChartView owner)
        {
            _points = points;
            _owner = owner;
            ClipToBounds = false;
            _surface = new Surface(this, color);
            Children.Add(_surface);
            PointerMoved += OnPointerMoved;
            PointerExited += (_, _) => Clear();
        }

        public DayPoint? Highlight
        {
            get => _highlight;
            set
            {
                _highlight = value;
                _surface.InvalidateVisual();
            }
        }

        public void ShowCard(DayPoint point)
        {
            var x = XFor(point);
            var anchor = new Border
            {
                Width = 14,
                Height = ChartHeight,
                Margin = new Thickness(x - 7, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Top,
                HorizontalAlignment = HorizontalAlignment.Left,
                Background = Brushes.Transparent,
            };
            Children.Add(anchor);
            HoverLayer.Attach(anchor, _owner._pinnedId, () => Card(point));
            HoverLayer.Current?.ShowRegistered(_owner._pinnedId);
        }

        private Control Card(DayPoint point)
        {
            var rows = new List<HoverCardRowItem>();
            if (point.ByAgent is { Count: > 0 } byAgent)
            {
                rows = HoverCardRowBuilder.AgentRows(byAgent.Select(kv =>
                (
                    kv.Key,
                    _owner._labels.GetValueOrDefault(kv.Key) ?? AgentColors.Label(kv.Key),
                    kv.Value,
                    point.ByAgentTokens?.GetValueOrDefault(kv.Key) ?? 0
                ))).ToList();
            }
            return HoverCards.AgentRows(Fmt.Day(point.Day), null, point.Cost, point.Tokens,
                _owner._currency, rows);
        }

        private void OnPointerMoved(object? sender, PointerEventArgs e)
        {
            var point = Nearest(e.GetPosition(this).X);
            if (point?.Day == _highlight?.Day) return;
            _owner.UpdateSummary(point);
        }

        private void Clear()
        {
            if (_highlight is null) return;
            _owner.UpdateSummary(null);
        }

        private double PlotWidth => Math.Max(Bounds.Width - YAxisWidth, 1);

        private (int Lo, int Span) Domain()
        {
            if (_points.Count == 0) return (0, 1);
            var lo = _points[0].Date.DayNumber - 1;
            var hi = _points[^1].Date.DayNumber + 1;
            return (lo, Math.Max(hi - lo, 1));
        }

        public double XFor(DayPoint point)
        {
            var (lo, span) = Domain();
            return YAxisWidth + (point.Date.DayNumber - lo) / (double)span * PlotWidth;
        }

        private DayPoint? Nearest(double x)
        {
            if (_points.Count == 0) return null;
            DayPoint? best = null;
            var bestDistance = double.MaxValue;
            foreach (var point in _points)
            {
                var distance = Math.Abs(XFor(point) - x);
                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    best = point;
                }
            }
            var (_, span) = Domain();
            var dayWidth = PlotWidth / span;
            return bestDistance <= dayWidth * 1.2 ? best : null;
        }

        protected override Size MeasureOverride(Size availableSize)
        {
            var width = double.IsFinite(availableSize.Width) ? availableSize.Width : Metrics.PanelWidth - 40;
            _surface.Measure(new Size(width, ChartHeight));
            foreach (var child in Children) child.Measure(new Size(width, ChartHeight));
            return new Size(width, ChartHeight);
        }

        protected override Size ArrangeOverride(Size finalSize)
        {
            _surface.Arrange(new Rect(0, 0, finalSize.Width, finalSize.Height));
            foreach (var child in Children)
            {
                if (ReferenceEquals(child, _surface)) continue;
                var m = child.Margin;
                child.Arrange(new Rect(m.Left, m.Top, Math.Min(child.DesiredSize.Width, finalSize.Width),
                    finalSize.Height));
            }
            return finalSize;
        }

        /// <summary>真正画图的那一层（Panel 的 Render 被封印，所以单独一层 Control）。</summary>
        private sealed class Surface : Control
        {
            private readonly BarArea _area;
            private readonly IBrush _color;

            public Surface(BarArea area, IBrush color)
            {
                _area = area;
                _color = color;
                HorizontalAlignment = HorizontalAlignment.Stretch;
                VerticalAlignment = VerticalAlignment.Stretch;
                IsHitTestVisible = false;
            }

            protected override Size MeasureOverride(Size availableSize) => new(
                double.IsFinite(availableSize.Width) && availableSize.Width > 0
                    ? availableSize.Width
                    : Metrics.PanelWidth - 40,
                ChartHeight);

            public override void Render(DrawingContext context)
            {
                var width = Bounds.Width;
                var height = Bounds.Height;
                if (width <= 0 || height <= 0) return;

                var points = _area._points;
                var plotHeight = height - AxisLabelHeight;
                var max = points.Count == 0 ? 0 : points.Max(p => p.Cost);
                var scaleMax = NiceMax(max);
                var foreground = Palette.ForegroundColor;

                var ticks = DateTicks(points);
                var tickPositions = ticks.Select(d => XForDay(points, d)).ToList();

                // 竖直网格线：和 Swift Charts 的 AxisGridLine 一样落在日期刻度上，用虚线。
                var gridPen = new Pen(new SolidColorBrush(foreground, 0.06), 1,
                    new DashStyle([2, 2], 0));
                foreach (var x in tickPositions)
                {
                    context.DrawLine(gridPen, new Point(Math.Round(x) + 0.5, 0),
                        new Point(Math.Round(x) + 0.5, plotHeight));
                }

                for (var i = 0; i < YTicks; i++)
                {
                    var value = scaleMax * i / (YTicks - 1);
                    var y = plotHeight - (scaleMax > 0 ? value / scaleMax * plotHeight : 0);
                    var pen = new Pen(new SolidColorBrush(foreground, i == 0 ? 0.10 : 0.08), 1);
                    context.DrawLine(pen, new Point(YAxisWidth, Math.Round(y) + 0.5),
                        new Point(width, Math.Round(y) + 0.5));
                    // Mac 的 y 轴标签贴着卡片内容区左缘（左对齐），不右对齐到绘图区。
                    DrawText(context, AxisMoney(value), 9, 0, y - 6, rightAligned: false);
                }

                // Mac 的柱子在 360pt 面板里约 3pt 宽（Swift Charts 自动宽度），不要按天数拉伸。
                const double barWidth = 3;
                var active = _area._highlight;
                foreach (var point in points)
                {
                    if (point.Cost <= 0 && point.Tokens <= 0) continue;
                    var x = _area.XFor(point) - barWidth / 2;
                    var h = scaleMax > 0 ? point.Cost / scaleMax * (plotHeight - 2) : 0;
                    if (h < 1) h = 1;
                    var opacity = active is null || active.Day == point.Day ? 0.9 : 0.45;
                    var brush = _color is ISolidColorBrush solid ? new SolidColorBrush(solid.Color, opacity) : _color;
                    context.DrawRectangle(brush, null,
                        new RoundedRect(new Rect(x, plotHeight - h, barWidth, h), 1.5));
                }

                if (active is { } highlighted)
                {
                    var x = _area.XFor(highlighted);
                    var pen = new Pen(new SolidColorBrush(foreground, 0.22), 1);
                    context.DrawLine(pen, new Point(x, 0), new Point(x, plotHeight));
                }

                // 日期标签画在刻度线左侧偏移一点，和 Swift Charts 的 centered: false 一致。
                foreach (var day in ticks)
                {
                    var date = DateOnly.FromDayNumber(day);
                    var label = Fmt.MonthDay(Time.AtDay(TimeZoneInfo.Utc, date), TimeZoneInfo.Utc, null);
                    var x = XForDay(points, day);
                    var textWidth = Type.MeasureWidth(label, 9);
                    var clamped = Math.Min(Math.Max(x, 0), Math.Max(width - textWidth, 0));
                    DrawText(context, label, 9, clamped + 2, plotHeight + 2, rightAligned: false);
                }
            }

            private double XForDay(List<DayPoint> points, int day)
            {
                if (points.Count == 0) return 0;
                var lo = points[0].Date.DayNumber - 1;
                var hi = points[^1].Date.DayNumber + 1;
                var span = Math.Max(hi - lo, 1);
                return _area.PlotWidth == 0 ? 0 : (day - lo) / (double)span * _area.PlotWidth;
            }

            /// <summary>和 Swift Charts 的自动刻度类似：选一个「整周」步长，刻度对齐到周日，从右往左排。</summary>
            private static List<int> DateTicks(List<DayPoint> points)
            {
                var ticks = new List<int>();
                if (points.Count == 0) return ticks;
                var lo = points[0].Date.DayNumber - 1;
                var hi = points[^1].Date.DayNumber + 1;
                var span = Math.Max(hi - lo, 1);

                int[] steps = [1, 2, 3, 7, 14, 28, 56];
                var step = steps[^1];
                foreach (var candidate in steps)
                {
                    step = candidate;
                    if (span / (double)candidate <= 6) break;
                }
                var last = DateOnly.FromDayNumber(hi);
                if (step % 7 == 0)
                {
                    var offset = ((int)last.DayOfWeek + 7) % 7;
                    last = last.AddDays(-offset);
                }
                for (var date = last; date.DayNumber > lo && ticks.Count < 6; date = date.AddDays(-step))
                {
                    ticks.Add(date.DayNumber);
                }
                ticks.Reverse();
                return ticks;
            }

            private static void DrawText(DrawingContext context, string text, double size, double x, double y,
                bool rightAligned)
            {
                var brush = Palette.Secondary is ISolidColorBrush b ? b : Brushes.Gray;
                var layout = new TextLayout(text,
                    new Typeface(Type.Font, FontStyle.Normal, FontWeight.Normal), size, brush,
                    TextAlignment.Left, TextWrapping.NoWrap, TextTrimming.None,
                    maxWidth: 200, maxHeight: 40);
                var drawX = rightAligned ? x - layout.Width : x;
                using (context.PushTransform(Matrix.CreateTranslation(drawX, Math.Max(y, 0))))
                {
                    layout.Draw(context, new Point(0, 0));
                }
            }
        }
    }

    /// <summary>金额轴的上界：取整到 1 / 2 / 5 × 10^n，让刻度好看（和 Swift Charts 的自动刻度类似）。</summary>
    internal static double NiceMax(double max)
    {
        if (max <= 0) return 1;
        var magnitude = Math.Pow(10, Math.Floor(Math.Log10(max)));
        var normalized = max / magnitude;
        var nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
        return nice * magnitude;
    }

    internal static string AxisMoney(double v)
    {
        if (Math.Abs(v - Math.Round(v)) < 1e-9)
        {
            return "$" + ((long)Math.Round(v)).ToString(CultureInfo.InvariantCulture);
        }
        return "$" + v.ToString("0.0", CultureInfo.InvariantCulture);
    }
}
