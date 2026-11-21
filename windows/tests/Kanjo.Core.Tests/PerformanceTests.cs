using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Kanjo.App;
using Kanjo.App.Views;
using Xunit;
using Xunit.Abstractions;

namespace Kanjo.Core.Tests;

public sealed class PerformanceTests(ITestOutputHelper output) : KanjoTestCase
{
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-10-25T10:00:00Z");

    private static string Fingerprint(object value) => Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(value)));

    private static string[] Results(UsageReport report) => TimeRanges.All.Select(range =>
    {
        var ctx = new RangeContext(report, range.RawValue(), Now);
        var filtered = ctx.Filtered();
        return Fingerprint(new
        {
            filtered.Projects, filtered.Unattributed, filtered.Excluded, filtered.Cost, filtered.Tokens,
            filtered.Sessions, filtered.FirstActive, filtered.LastActive,
            Models = ModelAggregation.Aggregate(filtered),
            Detail = ctx.Filter(report.Projects[0]),
            Heat = report.Projects.Select(p => HeatStrip.Weekly(p.ByDay, Now, RangeContext.FallbackAgent(p), timezone: ctx.Spec.Timezone)),
            Weekly = WeeklyTokens.Since(Now, report.Projects, ctx.Spec.Timezone),
            Share = ShareSummary.Build(report, range.RawValue(), Now),
            ctx.CaptionResult,
        });
    }).ToArray();

    [Fact]
    public void FixtureResultsMatchBaseline()
    {
        var actual = Results(LoadFixture());
        var baseline = Path.Combine(DefaultPaths.RepoRoot!, "windows", "tests", "Kanjo.Core.Tests", "performance-baseline.txt");
        Assert.Equal(File.ReadAllLines(baseline), actual);
    }

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
        var fingerprintPath = Path.Combine(DefaultPaths.RepoRoot!, "windows", "tests", "Kanjo.Core.Tests", "performance-synthetic-baseline.txt");
        var fingerprints = Results(report);
        Assert.Equal(File.ReadAllLines(fingerprintPath), fingerprints);
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
