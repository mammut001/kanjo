namespace Kanjo.Core;

/// <summary>面板上的页面（对应 Mac 的 <c>Route</c>）。</summary>
public enum AppRouteKind
{
    Overview,
    Project,
    Bucket,
    Disk,
    Settings,
    Loading,
}

/// <summary>
/// 解析后的启动路由：页面 + 滚动锚点 + 订阅编辑 agent。
/// 对应 Mac 版 <c>DevRoute.resolve</c> 的返回值。
/// </summary>
public sealed record AppRoute(
    AppRouteKind Kind,
    string? ProjectId = null,
    int ProjectIndex = 0,
    string? Bucket = null,
    string? Anchor = null,
    string? EditingAgent = null,
    double LoadingSeconds = 12)
{
    public static readonly AppRoute Overview = new(AppRouteKind.Overview);
    public static readonly AppRoute Disk = new(AppRouteKind.Disk);
    public static readonly AppRoute Settings = new(AppRouteKind.Settings);

    public static AppRoute Loading(double seconds) => new(AppRouteKind.Loading, LoadingSeconds: seconds);

    public static AppRoute Project(string id, int index, string? anchor = null) =>
        new(AppRouteKind.Project, id, index, Anchor: anchor);

    public static AppRoute BucketDetail(string kind) => new(AppRouteKind.Bucket, Bucket: kind, Anchor: null);

    public string? PinnedHoverId => Anchor;
}

/// <summary>滚动 / 固定悬停卡的锚点字符串（和 Mac 版逐字一致，方便对照）。</summary>
public static class RouteAnchors
{
    public const string OverviewBottom = "overview-bottom";
    public const string ProjectBottom = "detail-bottom";
    public const string ProjectLocationsOpen = "detail-locations-open";
    public const string SettingsBottom = "settings-bottom";
    public const string DiskExpanded = "expanded";

    public const string QuotaPrefix = "overview:quota:";
    public const string MosaicPrefix = "overview:tile:";
    public const string OverviewHoverPrefix = "overview:hover:";

    /// <summary>`overview:quota:&lt;agent&gt;`：订阅行的额度卡固定展开。</summary>
    public static string? QuotaAgent(string? anchor)
    {
        if (anchor is null || !anchor.StartsWith(QuotaPrefix, StringComparison.Ordinal)) return null;
        var agent = anchor[QuotaPrefix.Length..];
        return agent.Length == 0 ? null : agent;
    }

    /// <summary>`overview:tile:&lt;n&gt;`：马赛克第 n 块的悬停卡固定展开。</summary>
    public static int? MosaicIndex(string? anchor)
    {
        if (anchor is null || !anchor.StartsWith(MosaicPrefix, StringComparison.Ordinal)) return null;
        return int.TryParse(anchor[MosaicPrefix.Length..], out var n) ? n : null;
    }

    /// <summary>`project:&lt;i&gt;:hover:day` → `project:&lt;i&gt;:hover:day` 本身即悬停卡 id。</summary>
    public static bool IsHoverAnchor(string? anchor) =>
        anchor is not null && anchor.Contains(":hover:", StringComparison.Ordinal);
}

/// <summary>
/// `--route` 解析（对应 MenuPanelView.swift 里的 DevRoute）。
/// 需要报告才能解析的取值（project / bucket / overview 的悬停锚点）在报告为空时返回 null。
/// </summary>
public static class DevRoutes
{
    public static readonly IReadOnlyList<string> KnownRoutes =
    [
        "overview", "overview-bottom", "disk", "disk:expanded", "settings", "settings-bottom",
        "loading", "bucket:unattributed", "bucket:excluded",
    ];

    public static AppRoute? Resolve(string? raw, UsageReport? report)
    {
        if (raw is null) return null;
        switch (raw)
        {
            case "settings": return AppRoute.Settings;
            case "settings-bottom": return AppRoute.Settings with { Anchor = RouteAnchors.SettingsBottom };
            case "overview": return AppRoute.Overview;
            case "overview-bottom":
                return report is null ? null : AppRoute.Overview with { Anchor = RouteAnchors.OverviewBottom };
            case "disk": return AppRoute.Disk;
            case "disk:expanded": return AppRoute.Disk with { Anchor = RouteAnchors.DiskExpanded };
            case "loading": return AppRoute.Loading(1.0);
        }

        if (raw.StartsWith("loading:", StringComparison.Ordinal))
        {
            var value = double.TryParse(raw["loading:".Length..], System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var sec)
                ? sec
                : 12.0;
            return AppRoute.Loading(value);
        }

        if (RouteAnchors.QuotaAgent(raw) is not null || RouteAnchors.MosaicIndex(raw) is not null ||
            raw.StartsWith(RouteAnchors.OverviewHoverPrefix, StringComparison.Ordinal))
        {
            return report is null ? null : AppRoute.Overview with { Anchor = raw };
        }

        if (SubscriptionSettingsRoute.Parse(raw) is { } sub)
        {
            return AppRoute.Settings with
            {
                Anchor = SubscriptionSettingsRoute.Anchor(sub.Agent),
                EditingAgent = sub.IsEdit ? sub.Agent : null,
            };
        }

        if (report is null) return null;

        if (raw.StartsWith("project:", StringComparison.Ordinal))
        {
            var rest = raw["project:".Length..];
            var split = rest.Split(':', 2);
            if (!int.TryParse(split[0], out var index)) return AppRoute.Overview;
            var sorted = report.Projects.OrderByDescending(p => p.Cost).ToList();
            if (index < 0 || index >= sorted.Count) return AppRoute.Overview;

            string? anchor = null;
            if (split.Length > 1)
            {
                var tail = split[1];
                anchor = tail switch
                {
                    "bottom" => RouteAnchors.ProjectBottom,
                    "locations" => RouteAnchors.ProjectLocationsOpen,
                    _ => tail.StartsWith("hover:", StringComparison.Ordinal) ? raw : null,
                };
            }
            return AppRoute.Project(sorted[index].Id, index, anchor);
        }

        if (raw.StartsWith("bucket:", StringComparison.Ordinal))
        {
            var kind = raw["bucket:".Length..];
            if (kind is "unattributed" or "excluded") return AppRoute.BucketDetail(kind);
        }

        return AppRoute.Overview;
    }

    /// <summary>路由是否属于磁盘页（截图要预先加载磁盘报告）。</summary>
    public static bool NeedsDisk(string? raw) =>
        raw is not null && (raw == "disk" || raw.StartsWith("disk:", StringComparison.Ordinal));

    /// <summary>路由是否是加载页（截图时不等待数据）。</summary>
    public static bool IsLoadingRoute(string? raw) =>
        raw is not null && (raw == "loading" || raw.StartsWith("loading:", StringComparison.Ordinal));
}
