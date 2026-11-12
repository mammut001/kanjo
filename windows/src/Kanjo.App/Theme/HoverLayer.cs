using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Threading;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// 悬停卡宿主（对应 Mac 的 <c>HoverCardOverlayHost</c> + <c>HoverCardModifier</c>）：
/// 悬停 0.35 秒后浮出卡片，位置用 <see cref="HoverCardLayout"/> 算（放不下就翻到上方，始终在安全边距内）。
/// 卡片画在面板顶层，不会被滚动区域裁掉。
/// </summary>
public sealed class HoverLayer : Panel
{
    public const double DelayMilliseconds = 350;
    public const double MaxCardWidth = 300;

    private readonly Dictionary<string, (WeakReference<Control> Anchor, Func<Control> Build)> _registered =
        new(StringComparer.Ordinal);

    private Control? _card;
    private Point _origin;
    private string? _shownId;
    private DispatcherTimer? _timer;

    /// <summary>当前面板的悬停层（快照 / 常规运行各有一个）。</summary>
    public static HoverLayer? Current { get; set; }

    /// <summary>`--route` 指定的固定悬停卡 id（截图用，不用真的悬停）。</summary>
    public static string? PinnedId { get; set; }

    /// <summary>卡片高度上限：面板高度减去上下安全边距。</summary>
    public double MaxCardHeight { get; set; } = 560;

    public HoverLayer()
    {
        ClipToBounds = false;
        IsHitTestVisible = false;
    }

    /// <summary>给一个锚点控件挂上悬停卡。</summary>
    public static void Attach(Control anchor, string id, Func<Control> build)
    {
        var layer = Current;
        layer?.Register(anchor, id, build);
    }

    public void Register(Control anchor, string id, Func<Control> build)
    {
        _registered[id] = (new WeakReference<Control>(anchor), build);
        anchor.PointerEntered += (_, _) => Schedule(id);
        anchor.PointerExited += (_, _) => Dismiss(id);
        anchor.DetachedFromVisualTree += (_, _) =>
        {
            if (_shownId == id) Hide();
        };
    }

    private void Schedule(string id)
    {
        _timer?.Stop();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(DelayMilliseconds) };
        _timer.Tick += (_, _) =>
        {
            _timer?.Stop();
            ShowRegistered(id);
        };
        _timer.Start();
    }

    private void Dismiss(string id)
    {
        if (_shownId != id) return;
        _timer?.Stop();
        Hide();
    }

    /// <summary>按 id 显示已注册的卡片（截图里的固定悬停卡走这里）。</summary>
    public bool ShowRegistered(string id)
    {
        if (!_registered.TryGetValue(id, out var entry)) return false;
        if (!entry.Anchor.TryGetTarget(out var anchor)) return false;
        if (anchor.Bounds.Width <= 0) return false;
        return Show(id, anchor, entry.Build);
    }

    /// <summary>在锚点下方（放不下则上方）显示卡片。</summary>
    public bool Show(string id, Control anchor, Func<Control> build)
    {
        if (anchor.TranslatePoint(new Point(0, 0), this) is not { } p) return false;
        var rect = new Rect(p, anchor.Bounds.Size);

        var card = Chrome.HoverCardChrome(build());
        card.HorizontalAlignment = HorizontalAlignment.Left;
        card.VerticalAlignment = VerticalAlignment.Top;
        card.MaxWidth = MaxCardWidth;
        card.Measure(new Size(MaxCardWidth, MaxCardHeight));
        var size = card.DesiredSize;

        var containerWidth = Bounds.Width > 0 ? Bounds.Width : Metrics.PanelWidth;
        var containerHeight = Bounds.Height > 0 ? Bounds.Height : Metrics.PanelHeight;
        var point = HoverCardLayout.Origin(
            new HoverRect(rect.X, rect.Y, Math.Max(rect.Width, 1), Math.Max(rect.Height, 1)),
            new HoverSize(size.Width, size.Height),
            new HoverSize(containerWidth, containerHeight));

        if (_card is not null) Children.Remove(_card);
        _card = card;
        _origin = new Point(point.X, point.Y);
        _shownId = id;
        Children.Add(card);
        card.Measure(new Size(MaxCardWidth, MaxCardHeight));
        // 直接摆好：截图时面板不会再走一遍布局。
        card.Arrange(new Rect(_origin, new Size(
            Math.Min(card.DesiredSize.Width, containerWidth),
            Math.Min(card.DesiredSize.Height, MaxCardHeight))));
        InvalidateMeasure();
        InvalidateArrange();
        UpdateLayout();
        return true;
    }

    public void Hide()
    {
        if (_card is not null) Children.Remove(_card);
        _card = null;
        _shownId = null;
        InvalidateMeasure();
        InvalidateArrange();
    }

    public string? ShownId => _shownId;

    protected override Size MeasureOverride(Size availableSize)
    {
        var width = double.IsFinite(availableSize.Width) && availableSize.Width > 0
            ? availableSize.Width
            : Metrics.PanelWidth;
        var height = double.IsFinite(availableSize.Height) && availableSize.Height > 0
            ? availableSize.Height
            : Metrics.PanelHeight;
        _card?.Measure(new Size(MaxCardWidth, MaxCardHeight));
        return new Size(width, height);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        // 不用 base：Panel 会把卡片摆到 (0,0) 铺满整个面板，这里要保持在算好的位置上。
        if (_card is not null)
        {
            _card.Arrange(new Rect(_origin, new Size(
                Math.Min(_card.DesiredSize.Width, finalSize.Width),
                Math.Min(_card.DesiredSize.Height, MaxCardHeight))));
        }
        return finalSize;
    }
}
