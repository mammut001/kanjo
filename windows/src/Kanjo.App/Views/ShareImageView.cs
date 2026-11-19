using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 用量分享图（Mac <c>MultiImageView</c>）：固定 640pt 的深色卡片，不跟应用外观走。
/// 没有悬停、没有点击。马赛克沿用 <see cref="MosaicLayout"/>，方块够大时才画名字和金额。
/// </summary>
public sealed class ShareImageView : Border
{
    public const double CardWidth = 640;
    public const double Pad = 18;
    public const double ColumnGap = 16;
    public const double MosaicHeight = 230;

    private static Bitmap? _icon;
    private static bool _iconTried;

    public ShareImageView(ShareSummary summary)
    {
        var ink = Brush(Colors.White);
        var secondary = Brush(Color.FromRgb(0xAE, 0xAE, 0xB2));
        var costInk = Brush(Color.FromArgb(204, 255, 255, 255));

        Width = CardWidth;
        Background = Brush(Color.FromRgb(0x1C, 0x1C, 0x1C));
        Padding = new Thickness(Pad);

        var columns = CardWidth - Pad * 2 - ColumnGap;
        var mosaicW = Math.Round(columns * 0.52, MidpointRounding.AwayFromZero);
        var agentsW = columns - mosaicW;

        var body = Ui.V(18);
        body.Children.Add(Header(summary, ink, secondary));
        body.Children.Add(Columns(summary, mosaicW, agentsW, ink, secondary, costInk));
        body.Children.Add(Chips(summary, ink, secondary));
        body.Children.Add(Footer(summary, secondary));
        Child = body;
    }

    private static Control Header(ShareSummary summary, IBrush ink, IBrush secondary)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };

        var left = Ui.H(8);
        if (AppIcon() is { } icon)
        {
            left.Children.Add(new Image
            {
                Source = icon,
                Width = 28,
                Height = 28,
                Stretch = Stretch.Uniform,
            });
        }

        var titles = Ui.V(1);
        titles.Children.Add(Ui.Text("Kanjo", 15, FontWeight.SemiBold, ink));
        titles.Children.Add(Ui.Text(summary.RangeLabel, 11, null, secondary, maxLines: 1));
        left.Children.Add(titles);
        grid.Children.Add(left);

        var amount = Ui.Text(
            Fmt.Money(summary.Totals.Cost, summary.Currency), 24, FontWeight.SemiBold, ink, family: Type.Rounded);
        amount.HorizontalAlignment = HorizontalAlignment.Right;
        var sessions = Ui.Text(
            L10n.Tr("share.tokens_sessions", Fmt.Tokens(summary.Totals.Tokens), summary.Totals.Sessions),
            11, null, secondary, maxLines: 1);
        sessions.HorizontalAlignment = HorizontalAlignment.Right;
        var right = Ui.V(1);
        right.HorizontalAlignment = HorizontalAlignment.Right;
        right.Children.Add(amount);
        right.Children.Add(sessions);
        Grid.SetColumn(right, 1);
        grid.Children.Add(right);
        return grid;
    }

    private static Control Columns(
        ShareSummary summary, double mosaicW, double agentsW, IBrush ink, IBrush secondary, IBrush costInk)
    {
        var row = Ui.H(ColumnGap);
        row.VerticalAlignment = VerticalAlignment.Top;

        var left = Ui.V(8);
        left.Width = mosaicW;
        left.Children.Add(Ui.Text(L10n.Tr("share.top_projects"), 11, FontWeight.SemiBold, secondary));
        left.Children.Add(Mosaic(summary.MosaicProjects, mosaicW, summary.Currency, ink, costInk));

        var right = Ui.V(8);
        right.Width = agentsW;
        right.Children.Add(Ui.Text(L10n.Tr("share.agents"), 11, FontWeight.SemiBold, secondary));
        right.Children.Add(new Border
        {
            Height = 6,
            CornerRadius = new CornerRadius(3),
            ClipToBounds = true,
            Child = new ShareProportionBar(summary.AgentRows, summary.Totals.Tokens),
        });
        right.Children.Add(AgentTable(summary, ink, secondary));

        row.Children.Add(left);
        row.Children.Add(right);
        return row;
    }

    /// <summary>和总览同一套方块，但标签规则是分享图自己的：宽 ≥ 56 且高 ≥ 30 才画名字 + 金额。</summary>
    private static Control Mosaic(
        IReadOnlyList<Project> projects, double width, string currency, IBrush ink, IBrush costInk)
    {
        var host = new Panel
        {
            Width = width,
            Height = MosaicHeight,
            ClipToBounds = true,
        };
        foreach (var tile in MosaicLayout.Build(projects, width, MosaicHeight))
        {
            var color = tile.AgentKey is { } agent
                ? Palette.FromHex(AgentColors.Pair(agent).Dark)
                : Palette.FromHex(AgentColors.NeutralDark);
            var shape = new Border
            {
                Width = tile.Rect.Width,
                Height = tile.Rect.Height,
                CornerRadius = new CornerRadius(MosaicLayout.CornerRadius),
                Background = Brush(color),
                ClipToBounds = true,
                Margin = new Thickness(tile.Rect.X, tile.Rect.Y, 0, 0),
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Top,
            };
            if (tile.Rect.Width >= 56 && tile.Rect.Height >= 30)
            {
                var name = tile.Project?.Name ?? $"+{tile.Merged.Count}";
                var box = new StackPanel
                {
                    Orientation = Orientation.Vertical,
                    Spacing = 0,
                    Margin = new Thickness(6),
                };
                box.Children.Add(Ui.Text(name, 11, FontWeight.SemiBold, ink, maxLines: 1));
                box.Children.Add(Ui.Text(Fmt.Money(tile.Cost, currency), 10, null, costInk, mono: true, maxLines: 1));
                shape.Child = box;
            }
            host.Children.Add(shape);
        }
        return host;
    }

    private static Control AgentTable(ShareSummary summary, IBrush ink, IBrush secondary)
    {
        const int maxShown = 7;
        var grid = new Grid
        {
            ColumnSpacing = 6,
            RowSpacing = 8,
            ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,Auto"),
        };
        var shown = summary.AgentRows.Take(maxShown).ToList();
        for (var i = 0; i < shown.Count; i++)
        {
            var row = shown[i];
            var multiplier = row.Multiplier is > 0 ? Fmt.Multiple(row.Multiplier) : " ";
            var multiplierBrush = row.Multiplier is > 0 ? AgentBrush(row.Agent) : Brushes.Transparent;
            AddRow(grid, i,
                DotLabel(row.Label, AgentBrush(row.Agent), ink),
                Ui.Text(Fmt.Tokens(row.Tokens), 13, null, secondary, mono: true, maxLines: 1),
                Ui.Text(Fmt.Money(row.Cost, summary.Currency), 13, null, ink, mono: true, maxLines: 1),
                Ui.Text(multiplier, 13, FontWeight.SemiBold, multiplierBrush, mono: true, maxLines: 1));
        }

        var overflow = summary.AgentRows.Count - shown.Count;
        if (overflow > 0)
        {
            var cost = summary.AgentRows.Skip(maxShown).Sum(row => row.Cost);
            var dot = new Ellipse
            {
                Width = 6,
                Height = 6,
                Fill = secondary,
                Opacity = 0.5,
                VerticalAlignment = VerticalAlignment.Center,
            };
            AddRow(grid, shown.Count,
                DotLabel(L10n.Tr("share.more_agents", overflow), null, secondary, dot),
                Ui.Text(" ", 13, null, secondary, mono: true),
                Ui.Text(Fmt.Money(cost, summary.Currency), 13, null, ink, mono: true, maxLines: 1),
                Ui.Text(" ", 13, FontWeight.SemiBold, Brushes.Transparent, mono: true));
        }
        return grid;
    }

    private static Control DotLabel(string text, IBrush? dotFill, IBrush foreground, Ellipse? dot = null)
    {
        var row = Ui.H(6);
        row.Children.Add(dot ?? new Ellipse
        {
            Width = 6,
            Height = 6,
            Fill = dotFill,
            VerticalAlignment = VerticalAlignment.Center,
        });
        row.Children.Add(Ui.Text(text, 13, null, foreground, maxLines: 1));
        return row;
    }

    private static void AddRow(Grid grid, int index, Control label, Control tokens, Control cost, Control multiplier)
    {
        grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        Place(grid, label, index, 0, right: false);
        Place(grid, tokens, index, 1, right: true);
        Place(grid, cost, index, 2, right: true);
        Place(grid, multiplier, index, 3, right: true);
    }

    private static void Place(Grid grid, Control child, int row, int column, bool right)
    {
        if (right)
        {
            child.HorizontalAlignment = HorizontalAlignment.Stretch;
            if (child is TextBlock block) block.TextAlignment = TextAlignment.Right;
        }
        child.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetRow(child, row);
        Grid.SetColumn(child, column);
        grid.Children.Add(child);
    }

    private static Control Chips(ShareSummary summary, IBrush ink, IBrush secondary)
    {
        var denom = summary.Totals.Input + summary.Totals.CacheRead;
        var hit = denom > 0 ? (double)summary.Totals.CacheRead / denom : 0;
        var row = Ui.H(20);
        row.Margin = new Thickness(18, 0, 18, 0);
        row.Children.Add(Chip(L10n.Tr("share.input"), Fmt.Tokens(summary.Totals.Input), ink, secondary));
        row.Children.Add(Chip(L10n.Tr("share.output"), Fmt.Tokens(summary.Totals.Output), ink, secondary));
        row.Children.Add(Chip(L10n.Tr("share.cache_read"), Fmt.Tokens(summary.Totals.CacheRead), ink, secondary));
        row.Children.Add(Chip(L10n.Tr("share.cache_hit"), Fmt.Percent(hit), ink, secondary));
        return row;
    }

    private static Control Chip(string label, string value, IBrush ink, IBrush secondary)
    {
        var box = Ui.V(2);
        box.Children.Add(Ui.Text(label, 10, null, secondary));
        box.Children.Add(Ui.Text(value, 13, FontWeight.SemiBold, ink, mono: true, maxLines: 1));
        return box;
    }

    private static Control Footer(ShareSummary summary, IBrush secondary)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        grid.Children.Add(Ui.Text(
            L10n.Tr("share.updated_format", Fmt.Clock(summary.Updated)), 10, null, secondary, maxLines: 1));
        var link = Ui.Text("github.com/mammut001/kanjo", 10, null, secondary, mono: true, maxLines: 1);
        link.HorizontalAlignment = HorizontalAlignment.Right;
        Grid.SetColumn(link, 1);
        grid.Children.Add(link);
        return grid;
    }

    private static IBrush AgentBrush(string agent) => Brush(Palette.FromHex(AgentColors.Pair(agent).Dark));

    private static SolidColorBrush Brush(Color color) => new(color);

    /// <summary>图标资源缺失时就不画（和 Mac 一样），卡片其余部分照常。</summary>
    private static Bitmap? AppIcon()
    {
        if (_iconTried) return _icon;
        _iconTried = true;
        try
        {
            var uri = new Uri("avares://Kanjo/Assets/Kanjo-icon.png");
            if (!AssetLoader.Exists(uri)) return null;
            using var stream = AssetLoader.Open(uri);
            _icon = new Bitmap(stream);
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: share icon missing: {e.Message}");
        }
        return _icon;
    }

    /// <summary>6pt 的比例条：每个 agent 一段，间距 1.5，最短 2，圆角由外层裁切。</summary>
    private sealed class ShareProportionBar : Panel
    {
        private readonly double[] _shares;

        public ShareProportionBar(IReadOnlyList<ShareSummary.AgentRow> rows, long totalTokens)
        {
            Height = 6;
            ClipToBounds = true;
            _shares = new double[rows.Count];
            for (var i = 0; i < rows.Count; i++)
            {
                _shares[i] = totalTokens > 0 ? rows[i].Tokens / (double)totalTokens : 0;
                Children.Add(new Border
                {
                    Background = AgentBrush(rows[i].Agent),
                    Height = 6,
                });
            }
        }

        protected override Size MeasureOverride(Size available)
        {
            var width = double.IsFinite(available.Width) ? available.Width : 0;
            foreach (var child in Children) child.Measure(new Size(width, 6));
            return new Size(width, 6);
        }

        protected override Size ArrangeOverride(Size finalSize)
        {
            const double gap = 1.5;
            var count = Children.Count;
            var avail = Math.Max(finalSize.Width - Math.Max(count - 1, 0) * gap, 0);
            var x = 0.0;
            for (var i = 0; i < count; i++)
            {
                var width = Math.Max(avail * _shares[i], count > 0 ? 2 : 0);
                Children[i].Arrange(new Rect(x, 0, width, 6));
                x += width + gap;
            }
            return new Size(finalSize.Width, 6);
        }
    }
}
