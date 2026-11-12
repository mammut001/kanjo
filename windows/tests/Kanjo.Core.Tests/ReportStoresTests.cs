using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 发布到网站 / 家庭上报的存储层：命令行参数、令牌传递方式、结果解析、状态文案。
/// 执行器是假实现（<see cref="FakeReportRunner"/>），不跑真实 CLI。
/// </summary>
public sealed class ReportStoresTests : KanjoTestCase
{
    private const string DummyUrl = "https://usage.example.com";
    private static readonly DateTimeOffset Now = DateTimeOffset.FromUnixTimeSeconds(1_700_000_000);

    private AppSettings ConfiguredSettings(bool publish = true, bool family = true)
    {
        Settings.Set(SettingsKeys.PublishEnabled, publish);
        Settings.Set(SettingsKeys.PublishRepoPath, "/repo");
        Settings.Set(SettingsKeys.PublishFrequency, "weekly");
        Settings.Set(SettingsKeys.FamilyReportEnabled, family);
        Settings.Set(SettingsKeys.FamilyReportUrl, DummyUrl);
        Settings.Set(SettingsKeys.FamilyReportMemberLabel, "Alice");
        return Settings;
    }

    private static string? NoNetwork() => null;

    // MARK: - Publish

    [Fact]
    public void TestPublishCommandArguments()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner();
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        var call = Assert.Single(runner.Calls);
        Assert.Equal("publish-usage", call.Kind);
        Assert.Equal(["publish-usage", "--repo", "/repo", "--file", "src/data/token-usage.json",
            "--branch", "main"], call.Arguments);
        Assert.Null(call.Token);
    }

    [Fact]
    public void TestPublishCustomFileAndBranch()
    {
        var settings = ConfiguredSettings();
        settings.Set(SettingsKeys.PublishFilePath, "public/usage.json");
        settings.Set(SettingsKeys.PublishBranch, "gh-pages");
        var runner = new FakeReportRunner();
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        Assert.Equal(["publish-usage", "--repo", "/repo", "--file", "public/usage.json",
            "--branch", "gh-pages"], Assert.Single(runner.Calls).Arguments);
    }

    [Fact]
    public void TestPublishSuccessRecordsTimestampsAndStatus()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(0, "{\"status\":\"pushed\"}", "", false, "python"),
        };
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        Assert.Equal(Now, store.Activity.LastSuccessAt);
        Assert.Equal(Now, store.Activity.LastAttemptAt);
        Assert.Null(store.Activity.LastError);
        var (text, isError, isWarning) = store.StatusText();
        Assert.False(isError);
        Assert.False(isWarning);
        Assert.StartsWith("Last published", text);
    }

    [Fact]
    public void TestPublishUnchangedCountsAsSuccess()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(0, "{\"status\":\"unchanged\"}", "", false, "python"),
        };
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        Assert.Equal(Now, store.Activity.LastSuccessAt);
        Assert.Null(store.Activity.LastError);
    }

    [Fact]
    public void TestPublishErrorStatusRecordsMessage()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(0, "{\"status\": \"error\", \"message\": \"push rejected\"}",
                "", false, "python"),
        };
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        Assert.Equal("push rejected", store.Activity.LastError);
        var (text, isError, _) = store.StatusText();
        Assert.True(isError);
        Assert.Contains("push rejected", text);
    }

    [Fact]
    public void TestPublishNonZeroExitFallsBackToStderrThenCode()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(128, "", "fatal: not a git repository", false, "python"),
        };
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();
        Assert.Equal("fatal: not a git repository", store.Activity.LastError);

        runner.PublishResult = new CliResult(3, "", "  ", false, "python");
        store.PublishNow();
        Assert.Equal("Process failed with exit code 3", store.Activity.LastError);
    }

    [Fact]
    public void TestPublishTimeoutMessage()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(-1, "", "", true, "python"),
        };
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.PublishNow();

        Assert.Equal("Command timed out after 120s", store.Activity.LastError);
    }

    [Fact]
    public void TestPublishFailurePersistsErrorForNextLaunch()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            PublishResult = new CliResult(1, "", "boom", false, "python"),
        };
        new PublishStore(settings, () => runner, NoNetwork, () => Now).PublishNow();

        var reloaded = new PublishStore(settings, () => runner, NoNetwork, () => Now);
        Assert.Equal("boom", reloaded.Activity.LastError);
        Assert.Null(reloaded.Activity.LastSuccessAt);
    }

    [Fact]
    public void TestPublishSkippedWhenDisabledOrMissingRepoOrOffline()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner();
        var report = LoadFixture();

        new PublishStore(settings, () => runner, NoNetwork, () => Now).ReportDidRefresh(report);
        Assert.Single(runner.Calls);

        runner = new FakeReportRunner();
        settings.Set(SettingsKeys.PublishEnabled, false);
        new PublishStore(settings, () => runner, NoNetwork, () => Now).ReportDidRefresh(report);
        Assert.Empty(runner.Calls);

        settings.Set(SettingsKeys.PublishEnabled, true);
        settings.Set(SettingsKeys.PublishRepoPath, "  ");
        new PublishStore(settings, () => runner, NoNetwork, () => Now).ReportDidRefresh(report);
        Assert.Empty(runner.Calls);

        settings.Set(SettingsKeys.PublishRepoPath, "/repo");
        new PublishStore(settings, () => runner, () => "KANJO_NO_NETWORK=1", () => Now)
            .ReportDidRefresh(report);
        Assert.Empty(runner.Calls);
    }

    [Fact]
    public void TestPublishNotDueWithinBackoffOrInterval()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner();
        settings.SetDate(SettingsKeys.PublishLastSuccessAt, Now.AddHours(-23));
        settings.SetDate(SettingsKeys.PublishLastAttemptAt, Now.AddHours(-23));

        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);
        store.ReportDidRefresh(LoadFixture());
        Assert.Empty(runner.Calls);

        settings.SetDate(SettingsKeys.PublishLastSuccessAt, Now.AddDays(-8));
        settings.SetDate(SettingsKeys.PublishLastAttemptAt, Now.AddDays(-8));
        var due = new PublishStore(settings, () => runner, NoNetwork, () => Now);
        due.ReportDidRefresh(LoadFixture());
        Assert.Single(runner.Calls);
    }

    [Fact]
    public void TestPublishNoNetworkStatusIsWarning()
    {
        var settings = ConfiguredSettings();
        var store = new PublishStore(settings, () => new FakeReportRunner(), () => "offline", () => Now);
        var (_, isError, isWarning) = store.StatusText();
        Assert.False(isError);
        Assert.True(isWarning);
    }

    [Fact]
    public void TestPublishNeverPublishedStatus()
    {
        var settings = ConfiguredSettings();
        var store = new PublishStore(settings, () => new FakeReportRunner(), NoNetwork, () => Now);
        var (text, isError, isWarning) = store.StatusText();
        Assert.False(isError);
        Assert.False(isWarning);
        Assert.Equal(L10n.Tr("settings.publish.status.never"), text);
    }

    // MARK: - Family

    [Fact]
    public void TestFamilyCommandArgumentsAndTokenEnvironment()
    {
        var settings = ConfiguredSettings();
        var tokens = new InMemoryFamilyTokenStorage(initialToken: "secret-token");
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => Now);

        store.ReportNow();

        var call = Assert.Single(runner.Calls);
        Assert.Equal("report-family", call.Kind);
        Assert.Equal(["report-family", "--url", DummyUrl, "--member-label", "Alice"], call.Arguments);
        // 令牌只走环境变量，不进参数（和 Mac 传给 CLI 的方式一致）。
        Assert.Equal("secret-token", call.Token);
        Assert.DoesNotContain(call.Arguments, a => a.Contains("secret-token", StringComparison.Ordinal));
    }

    [Fact]
    public void TestFamilyReportWithoutLabelOmitsFlag()
    {
        var settings = ConfiguredSettings();
        settings.Set(SettingsKeys.FamilyReportMemberLabel, "");
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => runner, NoNetwork, () => Now);

        store.ReportNow();

        Assert.Equal(["report-family", "--url", DummyUrl], Assert.Single(runner.Calls).Arguments);
    }

    [Fact]
    public void TestFamilyMissingTokenRecordsFailure()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings, new InMemoryFamilyTokenStorage(), () => runner,
            NoNetwork, () => Now);

        Assert.False(store.HasToken);
        Assert.False(store.CanReportNow);
        store.ReportNow();

        Assert.Empty(runner.Calls);
        Assert.Equal("Token not configured", store.Activity.LastError);
    }

    [Fact]
    public void TestFamilyInvalidUrlSkipsWithoutRecording()
    {
        var settings = ConfiguredSettings();
        settings.Set(SettingsKeys.FamilyReportUrl, "http://insecure.example.com");
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => runner, NoNetwork, () => Now);

        Assert.False(store.CanReportNow);
        store.ReportNow();

        Assert.Empty(runner.Calls);
        Assert.Null(store.Activity.LastError);
    }

    [Fact]
    public void TestFamilySuccessAndStatusText()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            FamilyResult = new CliResult(0, "{\"status\":\"sent\"}", "", false, "python"),
        };
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => runner, NoNetwork, () => Now);

        store.ReportNow();

        Assert.Equal(Now, store.Activity.LastSuccessAt);
        var (text, kind) = store.StatusText();
        Assert.Equal(FamilyReportStatusStateKind.LastReported, kind);
        Assert.StartsWith("Last reported", text);
        Assert.Contains("just now", text);
    }

    [Fact]
    public void TestFamilyErrorStatusText()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            FamilyResult = new CliResult(1, "{\"status\": \"error\", \"message\": \"401 unauthorized\"}",
                "", false, "python"),
        };
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => runner, NoNetwork, () => Now);

        store.ReportNow();

        Assert.Equal("401 unauthorized", store.Activity.LastError);
        var (text, kind) = store.StatusText();
        Assert.Equal(FamilyReportStatusStateKind.Failed, kind);
        Assert.Contains("401 unauthorized", text);
    }

    [Fact]
    public void TestFamilyTimeoutMessage()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner
        {
            FamilyResult = new CliResult(-1, "", "", true, "python"),
        };
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => runner, NoNetwork, () => Now);

        store.ReportNow();

        Assert.Equal("Command timed out after 45s", store.Activity.LastError);
    }

    [Fact]
    public void TestFamilyReportDidRefreshRespectsSchedule()
    {
        var settings = ConfiguredSettings();
        var tokens = new InMemoryFamilyTokenStorage(initialToken: "t");
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => Now);

        store.ReportDidRefresh(LoadFixture());
        Assert.Single(runner.Calls);

        // 15 分钟内不重复上报。
        store.ReportDidRefresh(LoadFixture());
        Assert.Single(runner.Calls);

        // 30 分钟后（失败的退避时间过了）才重新算间隔。
        var later = Now.AddMinutes(16);
        var second = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => later);
        second.ReportDidRefresh(LoadFixture());
        Assert.Equal(2, runner.Calls.Count);
    }

    [Fact]
    public void TestFamilyNoTokenSkipsScheduledReport()
    {
        var settings = ConfiguredSettings();
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings, new InMemoryFamilyTokenStorage(), () => runner,
            NoNetwork, () => Now);

        store.ReportDidRefresh(LoadFixture());
        Assert.Empty(runner.Calls);
    }

    [Fact]
    public void TestFamilyTokenStorageRoundTrip()
    {
        var settings = ConfiguredSettings();
        var tokens = new InMemoryFamilyTokenStorage();
        var store = new FamilyReportStore(settings, tokens, () => new FakeReportRunner(), NoNetwork,
            () => Now);

        Assert.True(store.SetToken("abc"));
        Assert.True(store.HasToken);
        Assert.True(store.CanReportNow);

        Assert.True(store.ClearToken());
        Assert.False(store.HasToken);
        Assert.False(store.CanReportNow);
    }

    [Fact]
    public void TestFamilyNoNetworkStatus()
    {
        var settings = ConfiguredSettings();
        var store = new FamilyReportStore(settings,
            new InMemoryFamilyTokenStorage(initialToken: "t"), () => new FakeReportRunner(),
            () => "offline", () => Now);

        var (text, kind) = store.StatusText();
        Assert.Equal(FamilyReportStatusStateKind.NoNetwork, kind);
        Assert.Equal(L10n.Tr("settings.family.status.no_network"), text);
    }

    [Fact]
    public void TestRunnerMissingReportsLaunchFailure()
    {
        var settings = ConfiguredSettings();
        var publish = new PublishStore(settings, () => null, NoNetwork, () => Now);
        publish.PublishNow();
        Assert.Equal("Could not start command: Python not found.", publish.Activity.LastError);

        var family = new FamilyReportStore(settings, new InMemoryFamilyTokenStorage(initialToken: "t"),
            () => null, NoNetwork, () => Now);
        family.ReportNow();
        Assert.Equal("Could not start command: Python not found.", family.Activity.LastError);
    }

    [Fact]
    public void TestPublishFailureBackoffSkipsRetry()
    {
        var settings = ConfiguredSettings();
        // 上次尝试失败（没有成功记录），30 分钟前：publish 的退避是 1 小时，还没到。
        settings.SetDate(SettingsKeys.PublishLastAttemptAt, Now.AddMinutes(-30));
        var runner = new FakeReportRunner();
        var store = new PublishStore(settings, () => runner, NoNetwork, () => Now);

        store.ReportDidRefresh(LoadFixture());
        Assert.Empty(runner.Calls);

        // 一小时后才允许重试。
        var later = new PublishStore(settings, () => runner, NoNetwork, () => Now.AddHours(1.1));
        later.ReportDidRefresh(LoadFixture());
        Assert.Single(runner.Calls);
    }

    [Fact]
    public void TestFamilyReportRespectsFailureBackoff()
    {
        var settings = ConfiguredSettings();
        var tokens = new InMemoryFamilyTokenStorage(initialToken: "t");
        settings.SetDate(SettingsKeys.FamilyReportLastAttemptAt, Now.AddMinutes(-10));
        var runner = new FakeReportRunner();
        var store = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => Now);

        store.ReportDidRefresh(LoadFixture());
        Assert.Empty(runner.Calls); // 30 分钟退避内

        var later = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => Now.AddMinutes(31));
        later.ReportDidRefresh(LoadFixture());
        Assert.Single(runner.Calls);
    }

    [Fact]
    public void TestFamilyErrorKeepsLastSuccessForSchedule()
    {
        var settings = ConfiguredSettings();
        var tokens = new InMemoryFamilyTokenStorage(initialToken: "t");
        var runner = new FakeReportRunner
        {
            FamilyResult = new CliResult(0, "{\"status\":\"sent\"}", "", false, "python"),
        };
        new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => Now).ReportNow();
        Assert.Equal(Now, new ReportActivity(settings, SettingsKeys.FamilyReportLastAttemptAt,
            SettingsKeys.FamilyReportLastSuccessAt, SettingsKeys.FamilyReportLastResult).LastSuccessAt);

        // 之后一次失败只更新 attempt，不清掉 lastSuccess（和 Mac 一样）。
        var later = Now.AddHours(1);
        var failing = new FamilyReportStore(settings, tokens, () => runner, NoNetwork, () => later);
        runner.FamilyResult = new CliResult(1, "", "boom", false, "python");
        failing.ReportNow();

        Assert.Equal(Now, failing.Activity.LastSuccessAt);
        Assert.Equal(later, failing.Activity.LastAttemptAt);
        Assert.Equal("boom", failing.Activity.LastError);
    }
}
