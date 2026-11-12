using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// `--route` 解析（DevRoutes）与固定悬停 / 滚动锚点。对应 MenuPanelView.swift 里的 DevRoute。
/// </summary>
public sealed class DevRouteTests : KanjoTestCase
{
    [Fact]
    public void TestSimpleRoutesDoNotNeedReport()
    {
        Assert.Equal(AppRouteKind.Settings, DevRoutes.Resolve("settings", null)!.Kind);
        Assert.Equal(RouteAnchors.SettingsBottom, DevRoutes.Resolve("settings-bottom", null)!.Anchor);
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("overview", null)!.Kind);
        Assert.Equal(AppRouteKind.Disk, DevRoutes.Resolve("disk", null)!.Kind);
        Assert.Equal(RouteAnchors.DiskExpanded, DevRoutes.Resolve("disk:expanded", null)!.Anchor);
        Assert.Equal(1.0, DevRoutes.Resolve("loading", null)!.LoadingSeconds);
        Assert.Equal(30.0, DevRoutes.Resolve("loading:30", null)!.LoadingSeconds);
        Assert.Equal(12.0, DevRoutes.Resolve("loading:x", null)!.LoadingSeconds);
    }

    [Fact]
    public void TestNullAndUnknownFallBackToOverview()
    {
        Assert.Null(DevRoutes.Resolve(null, null));
        // 报告还没到时，需要报告的取值一律返回 nil（等数据到了再解析）；
        // 有报告时未知取值回落到总览。
        Assert.Null(DevRoutes.Resolve("nonsense", null));
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("nonsense", LoadFixture())!.Kind);
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("bucket:whatever", LoadFixture())!.Kind);
        Assert.Null(DevRoutes.Resolve("bucket:whatever", null));
    }

    [Fact]
    public void TestReportRoutesWaitForReport()
    {
        Assert.Null(DevRoutes.Resolve("overview-bottom", null));
        Assert.Null(DevRoutes.Resolve("project:0", null));
        Assert.Null(DevRoutes.Resolve("bucket:unattributed", null));
        Assert.Null(DevRoutes.Resolve("overview:quota:claude", null));

        var report = LoadFixture();
        Assert.Equal(RouteAnchors.OverviewBottom, DevRoutes.Resolve("overview-bottom", report)!.Anchor);
        Assert.Equal("unattributed", DevRoutes.Resolve("bucket:unattributed", report)!.Bucket);
        Assert.Equal("excluded", DevRoutes.Resolve("bucket:excluded", report)!.Bucket);
        Assert.Equal("overview:quota:claude", DevRoutes.Resolve("overview:quota:claude", report)!.Anchor);
        Assert.Equal("overview:tile:2", DevRoutes.Resolve("overview:tile:2", report)!.Anchor);
        Assert.Equal("overview:hover:legend", DevRoutes.Resolve("overview:hover:legend", report)!.Anchor);
    }

    [Fact]
    public void TestProjectRouteResolvesByIdInCostOrder()
    {
        var report = LoadFixture();
        var sorted = report.Projects.OrderByDescending(p => p.Cost).ToList();
        var route = DevRoutes.Resolve("project:1", report)!;
        Assert.Equal(AppRouteKind.Project, route.Kind);
        Assert.Equal(sorted[1].Id, route.ProjectId);
        Assert.Equal(1, route.ProjectIndex);
        Assert.Null(route.Anchor);

        Assert.Equal(RouteAnchors.ProjectBottom, DevRoutes.Resolve("project:0:bottom", report)!.Anchor);
        Assert.Equal(RouteAnchors.ProjectLocationsOpen, DevRoutes.Resolve("project:0:locations", report)!.Anchor);
        Assert.Equal("project:0:hover:tokens", DevRoutes.Resolve("project:0:hover:tokens", report)!.Anchor);
        Assert.Equal("project:0:hover:model:3", DevRoutes.Resolve("project:0:hover:model:3", report)!.Anchor);
    }

    [Fact]
    public void TestProjectIndexOutOfRangeFallsBackToOverview()
    {
        var report = LoadFixture();
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("project:99", report)!.Kind);
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("project:x", report)!.Kind);
        Assert.Equal(AppRouteKind.Overview, DevRoutes.Resolve("project:", report)!.Kind);
    }

    [Fact]
    public void TestSubscriptionRoutesCarryAnchorAndEditingAgent()
    {
        var (agent, edit) = SubscriptionSettingsRoute.Parse("settings:subscriptions:codex:edit")!.Value;
        Assert.Equal("codex", agent);
        Assert.True(edit);

        var route = DevRoutes.Resolve("settings:subscriptions:codex", null)!;
        Assert.Equal(AppRouteKind.Settings, route.Kind);
        Assert.Equal("settings:subscriptions:codex", route.Anchor);
        Assert.Null(route.EditingAgent);

        var editRoute = DevRoutes.Resolve("settings:subscriptions:codex:edit", null)!;
        Assert.Equal("codex", editRoute.EditingAgent);
        Assert.Equal("settings:subscriptions:codex", editRoute.Anchor);
    }

    [Fact]
    public void TestDiskAndLoadingRouteClassification()
    {
        Assert.True(DevRoutes.NeedsDisk("disk"));
        Assert.True(DevRoutes.NeedsDisk("disk:expanded"));
        Assert.False(DevRoutes.NeedsDisk("overview"));
        Assert.True(DevRoutes.IsLoadingRoute("loading"));
        Assert.True(DevRoutes.IsLoadingRoute("loading:5"));
        Assert.False(DevRoutes.IsLoadingRoute("settings"));
    }

    [Fact]
    public void TestHoverAnchorHelpers()
    {
        Assert.Equal("claude", RouteAnchors.QuotaAgent("overview:quota:claude"));
        Assert.Null(RouteAnchors.QuotaAgent("overview:quota:"));
        Assert.Null(RouteAnchors.QuotaAgent("overview:tile:1"));
        Assert.Equal(3, RouteAnchors.MosaicIndex("overview:tile:3"));
        Assert.Null(RouteAnchors.MosaicIndex("overview:tile:x"));
        Assert.True(RouteAnchors.IsHoverAnchor("project:0:hover:day"));
        Assert.False(RouteAnchors.IsHoverAnchor("overview-bottom"));
    }
}
