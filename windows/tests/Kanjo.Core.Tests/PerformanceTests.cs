using System.Diagnostics;
using Kanjo.App;
using Kanjo.App.Views;
using Xunit;
using Xunit.Abstractions;

namespace Kanjo.Core.Tests;

public sealed class PerformanceTests(ITestOutputHelper output) : KanjoTestCase
{
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-10-25T10:00:00Z");

    [Fact]
    public void SyntheticBenchmark()
    {
        var path = Environment.GetEnvironmentVariable("KANJO_BENCHMARK");
        if (path is null) return;
        var bytes = File.ReadAllBytes(path);
        var report = ReportDecoder.Decode(bytes);
        Assert.Equal(300, report.Projects.Count);
        Assert.Equal(20000, report.Projects.Sum(p => p.SessionsDetail.Count));
        Assert.All(report.Projects, p => Assert.Equal(400, p.ByDay.Count));
        void Measure(string name, Action action)
        {
            action();
            var best = double.MaxValue;
            for (var i = 0; i < 3; i++)
            {
                var watch = Stopwatch.StartNew(); action(); watch.Stop();
                best = Math.Min(best, watch.Elapsed.TotalMilliseconds);
            }
            output.WriteLine($"{name}: {best:F2} ms");
        }
        Measure("decode", () => ReportDecoder.Decode(bytes));
        foreach (var range in TimeRanges.All)
        {
            Measure($"filter {range}", () => new RangeContext(report, range.RawValue(), Now).Filtered());
        }
        var all = new RangeContext(report, "all", Now);
        var filtered = all.Filtered();
        Measure("overview models", () => ModelAggregation.Aggregate(filtered));
        Measure("project detail model", () => all.Filter(report.Projects[0]));
        Measure("heat strips", () => { foreach (var p in report.Projects) HeatStrip.Weekly(p.ByDay, Now, RangeContext.FallbackAgent(p), timezone: all.Spec.Timezone); });
        Measure("weekly tokens", () => WeeklyTokens.Since(Now, report.Projects, all.Spec.Timezone));
        Measure("share summary / agent models", () => ShareSummary.Build(report, "all", Now));
        OnUi(() =>
        {
            var services = new AppServices(Settings, ["--snapshot", "--data", path], TempDir(),
                new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor());
            services.LoadQuietly();
            Measure("OverviewPage", () => new OverviewPage(services, null, false));
            Measure("ProjectDetailPage", () => new ProjectDetailPage(services, report.Projects[0], 0, null, () => { }));
        });
    }
}
