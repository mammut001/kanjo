using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// Token 构成条：各段按比例、间距 1pt、整体裁成胶囊（Swift 的 `HStack(spacing: 1)` + `clipShape(Capsule)`）。
/// 每段最少 2pt，宽度按「可用宽度减去段间距」分配。
/// </summary>
public sealed class TokenBarControl : Panel
{
    private readonly List<(double Fraction, IBrush Color)> _parts = [];

    public TokenBarControl(IReadOnlyList<(double Fraction, IBrush Color, string Label, string Id)> parts, double height = 4)
    {
        Height = height;
        HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch;
        ClipToBounds = true;
        foreach (var part in parts)
        {
            if (part.Fraction <= 0) continue;
            _parts.Add((part.Fraction, part.Color));
            Children.Add(new Border { Background = part.Color, CornerRadius = new CornerRadius(height / 2) });
        }
    }

    protected override Size MeasureOverride(Size availableSize) => new(
        double.IsFinite(availableSize.Width) ? availableSize.Width : Metrics.PanelWidth - 40, Height);

    protected override Size ArrangeOverride(Size finalSize)
    {
        if (Children.Count == 0) return finalSize;
        var available = Math.Max(finalSize.Width - Math.Max(_parts.Count - 1, 0), 0);
        var total = _parts.Sum(p => p.Fraction);
        var x = 0.0;
        for (var i = 0; i < Children.Count; i++)
        {
            var width = total > 0 ? Math.Max(available * _parts[i].Fraction / total, 2) : 2;
            if (i == Children.Count - 1) width = Math.Max(finalSize.Width - x, 2);
            Children[i].Arrange(new Rect(x, 0, Math.Min(width, finalSize.Width - x), finalSize.Height));
            x += width + 1;
        }
        return finalSize;
    }
}
