using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Kanjo.Core;

namespace Kanjo.App.Views;

/// <summary>
/// 「Parse failed」行：名称 + 箭头（可展开看失败的文件列表）…… sessions + 「—」。
/// 对应 Mac 的 ParseFailedRow。
/// </summary>
public sealed class ParseFailedRow : StackPanel
{
    private readonly ParseFailedBucket _bucket;
    private readonly Panel _files = new() { IsVisible = false };
    private readonly Geometry _chevronDown = Geometry.Parse("M1,2 L6,7 L11,2");
    private Avalonia.Controls.Shapes.Path _chevron = null!;
    private bool _expanded;

    public ParseFailedRow(ParseFailedBucket bucket)
    {
        _bucket = bucket;
        Orientation = Orientation.Vertical;
        Spacing = 0;

        var name = Ui.Text(L10n.Tr("overview.parse_failed"), 12);
        var titleRow = Ui.H(4);
        titleRow.Children.Add(name);

        if (bucket.Files.Count > 0)
        {
            _chevron = (Avalonia.Controls.Shapes.Path)Icons.ChevronPath(down: false, size: 8, Palette.Secondary);
            titleRow.Children.Add(new Viewbox
            {
                Width = 8,
                Height = 8,
                Stretch = Stretch.Uniform,
                Child = _chevron,
                VerticalAlignment = VerticalAlignment.Center,
            });
        }

        var count = bucket.Sessions == 1
            ? L10n.TrL(null, "overview.count.session.singular", bucket.Sessions)
            : L10n.TrL(null, "overview.count.session.plural", bucket.Sessions);
        var sessions = Ui.Text(count, 12, null, Palette.Secondary);
        sessions.TextAlignment = TextAlignment.Right;
        var dash = Ui.Text("—", 14, FontWeight.Medium, Palette.Secondary);
        dash.TextAlignment = TextAlignment.Right;
        dash.MinWidth = 52;
        ToolTip.SetTip(dash, L10n.Tr("overview.parse_failed_help"));

        var header = Ui.Columns(
            (titleRow, new GridLength(1, GridUnitType.Star)),
            (sessions, GridLength.Auto),
            (dash.WithMargin(8, 0, 0, 0), GridLength.Auto));

        var body = Ui.V(2);
        body.Children.Add(header);
        body.Children.Add(Ui.Text(L10n.Tr("overview.parse_failed_desc"), 12, null, Palette.Secondary,
            wrap: true, maxLines: 2));
        body.Margin = new Thickness(Metrics.ContentInset, 7, Metrics.ContentInset, 7);

        var clickable = new Clickable(body, Toggle, radius: Metrics.RowRadius);
        if (bucket.Files.Count == 0) clickable.IsEnabled = false;

        Children.Add(clickable);

        var fileList = Ui.V(3);
        fileList.Margin = new Thickness(Metrics.ContentInset, 0, Metrics.ContentInset, 8);
        foreach (var file in bucket.Files)
        {
            fileList.Children.Add(Ui.Text(file, 12, null, Palette.Secondary, wrap: true, mono: true));
        }
        _files.Children.Add(fileList);
        Children.Add(_files);
    }

    private void Toggle()
    {
        _expanded = !_expanded;
        _files.IsVisible = _expanded;
        if (_chevron is not null)
        {
            _chevron.Data = Geometry.Parse(_expanded ? "M1.5,3.5 L4.5,6.5 L7.5,3.5" : "M3.5,1.5 L6.5,4.5 L3.5,7.5");
        }
    }

    /// <summary>测试 / 截图用：展开当前状态。</summary>
    public bool IsExpanded => _expanded;

    public void Expand()
    {
        if (!_expanded) Toggle();
    }
}
