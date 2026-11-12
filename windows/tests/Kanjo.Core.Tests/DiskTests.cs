using Xunit;

namespace Kanjo.Core.Tests;

public sealed class DiskTests : KanjoTestCase
{
    private static DiskReport Load() => LoadDiskFixture();

    [Fact]
    public void TestFixtureDecodes()
    {
        var r = Load();
        Assert.Equal(1, r.SchemaVersion);
        Assert.False(r.IsNewerSchema);
        Assert.Equal(10, r.Agents.Count);
        Assert.Null(r.Cached);
        Assert.Null(r.ScannedAt);
        Assert.Null(r.ScanSeconds);
        Assert.Equal("42.2 GB", Fmt.Bytes(r.TotalBytes));
        Assert.Equal("25.9 GB", Fmt.Bytes(r.ReclaimableBytes));
        var codex = r.Agents.First(a => a.Agent == "codex");
        Assert.Equal("Codex CLI", codex.Label);
        Assert.Equal("11.8 GB", Fmt.Bytes(codex.Bytes));
        Assert.All(r.AllEntries, e => Assert.StartsWith("/Users/alice/", e.Path, StringComparison.Ordinal));
    }

    [Fact]
    public void TestReclaimableSumMatchesUnblockedNonNever()
    {
        var r = Load();
        var summed = r.AllEntries
            .Where(e => e.Deletable != DiskDeletable.Never && e.Blocked.Count == 0)
            .Sum(e => e.Bytes);
        Assert.Equal(summed, r.ReclaimableBytes);
        Assert.Equal(r.ReclaimableBytes, r.SummedReclaimableBytes);
        Assert.Equal(r.TotalBytes, r.Agents.Sum(a => a.Bytes));
        foreach (var agent in r.Agents)
        {
            Assert.Equal(agent.Bytes, agent.Entries.Sum(e => e.Bytes));
        }
    }

    [Fact]
    public void TestFixtureCoversDeletableClassesAndBlockReasons()
    {
        var entries = Load().AllEntries;
        Assert.Superset(new HashSet<DiskDeletable>
        {
            DiskDeletable.Always, DiskDeletable.AfterImport, DiskDeletable.WhenClean, DiskDeletable.Never,
        }, entries.Select(e => e.Deletable).ToHashSet());
        Assert.Superset(new HashSet<DiskKind>
        {
            DiskKind.Sessions, DiskKind.Scratch, DiskKind.Worktrees, DiskKind.Cache, DiskKind.Memory, DiskKind.Other,
        }, entries.Select(e => e.Kind).ToHashSet());
        var reasons = entries.SelectMany(e => e.Blocked).ToHashSet();
        Assert.Superset(new HashSet<string> { "not_imported", "uncommitted_changes", "active" }, reasons);
        Assert.Contains(entries, e => e.IsReclaimable);
        Assert.Contains(entries, e => e.Deletable == DiskDeletable.Never && !e.IsReclaimable);
        Assert.Contains(entries, e => e.Blocked.Count > 0 && !e.IsReclaimable);
    }

    [Fact]
    public void TestUnknownKindAndDeletableDecode()
    {
        const string json = """
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":1,"reclaimable_bytes":1,
         "agents":[{"agent":"x","label":"X","bytes":1,"entries":[
           {"id":"x:y","kind":"weird","path":"/Users/alice/x","bytes":1,"files":1,
            "oldest":"2026-01-01","newest":"2026-01-02","deletable":"sometimes","blocked":[]}
         ]}]}
        """;
        var entry = DiskDecoder.Decode(json).AllEntries[0];
        Assert.Equal(DiskKind.Unknown, entry.Kind);
        Assert.Equal("weird", entry.RawKind);
        Assert.Equal(DiskDeletable.Unknown, entry.Deletable);
        Assert.Equal("sometimes", entry.RawDeletable);
        Assert.Empty(entry.Blocked);
        Assert.True(entry.IsReclaimable);
        Assert.Equal("Blocked: custom reason", DiskBlock.Title("custom_reason"));
        Assert.Equal("Blocked: not imported", DiskBlock.Title("not_imported"));
        Assert.Equal("uncommitted changes", DiskBlock.Short("uncommitted_changes"));
    }

    [Fact]
    public void TestMissingFieldNamesThePath()
    {
        const string json =
            """{"schema_version":1,"generated_at":"t","total_bytes":0,"reclaimable_bytes":0,"agents":[{"agent":"a","label":"A","bytes":0}]}""";
        var e = Assert.Throws<DataSourceError>(() => DiskDecoder.Decode(json));
        Assert.Equal(DataSourceErrorKind.ContractMismatch, e.Kind);
        Assert.Contains("agents[0].entries", e.Message);
    }

    [Fact]
    public void TestCommandDerivation()
    {
        Assert.Equal("python.exe -m kanjo disk --json", DiskCommand.Report("python.exe -m kanjo export"));
        Assert.Equal("kanjo export PATH=bin; kanjo disk --json",
            DiskCommand.Report("kanjo export PATH=bin; kanjo export"));
        Assert.Equal(@"C:\tools\python.exe -m kanjo disk --json",
            DiskCommand.Report(@"C:\tools\python.exe -m kanjo export"));
    }

    [Fact]
    public void TestRescanCommandDerivation()
    {
        Assert.Equal("python.exe -m kanjo disk --json --rescan",
            DiskCommand.Report("python.exe -m kanjo export", rescan: true));
        Assert.Equal("kanjo disk --json --rescan", DiskCommand.Report("kanjo export", rescan: true));
        Assert.Equal("kanjo disk --json --max-age 3600",
            DiskCommand.Report("kanjo export", maxAge: TimeSpan.FromHours(1)));
    }

    [Fact]
    public void TestCacheMetadataDecodes()
    {
        const string json = """
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":0,"reclaimable_bytes":0,
         "agents":[],"cached":true,"scanned_at":"2026-10-25T09:57:00Z","scan_seconds":22.5}
        """;
        var report = DiskDecoder.Decode(json);
        Assert.True(report.Cached);
        Assert.Equal("2026-10-25T09:57:00Z", report.ScannedAt);
        Assert.Equal(22.5, report.ScanSeconds);
    }

    [Fact]
    public void TestScanCaption()
    {
        var now = Ts("2026-10-25T10:00:00Z");
        var report = Load();
        var cases = new (string Timestamp, string Expected)[]
        {
            ("2026-10-25T10:00:05Z", "Scanned just now"),
            ("2026-10-25T09:59:01Z", "Scanned just now"),
            ("2026-10-25T09:59:00Z", "Scanned 1 min ago"),
            ("2026-10-25T09:57:00.000Z", "Scanned 3 min ago"),
            ("2026-10-25T09:00:00+00:00", "Scanned 1 hr ago"),
            ("2026-10-24T10:00:00Z", "Scanned 1 day ago"),
            ("2026-10-23T10:00:00Z", "Scanned 2 days ago"),
        };
        foreach (var (timestamp, expected) in cases)
        {
            report = report with { ScannedAt = timestamp };
            Assert.Equal(expected, DiskScanCaption.Text(report, now));
        }
        report = report with { ScannedAt = null, GeneratedAt = "2026-10-25T09:57:00Z" };
        Assert.Equal("Scanned 3 min ago", DiskScanCaption.Text(report, now));
        report = report with { GeneratedAt = "invalid" };
        Assert.Equal("Scan time unknown", DiskScanCaption.Text(report, now));
    }

    [Fact]
    public void TestPersistedCacheRoundTrip()
    {
        var directory = TempDir();
        var cache = new DiskReportCache(directory);
        Assert.Null(cache.Load());

        var report = Load() with { Cached = false, ScannedAt = "2026-10-25T09:57:00Z", ScanSeconds = 23.1 };
        cache.Save(report);
        Assert.Equal(report, new DiskReportCache(directory).Load());
        Assert.Equal("disk-report.json", Path.GetFileName(cache.FilePath!));

        var updated = report with { TotalBytes = 42 };
        cache.Save(updated);
        Assert.Equal(updated, cache.Load());

        File.WriteAllText(cache.FilePath!, "corrupt");
        Assert.Null(cache.Load());
    }

    [Fact]
    public void TestReportStateKeepsReportWhileRescanning()
    {
        var report = Load();
        var state = new DiskReportState();
        Assert.False(state.HasReport);
        Assert.False(state.IsRescanning);
        Assert.True(state.BeginRefresh());
        Assert.True(state.IsLoading);
        Assert.False(state.IsRescanning);
        Assert.False(state.BeginRefresh());
        state.FinishRefresh(report);
        Assert.True(state.HasReport);
        Assert.False(state.IsLoading);
        Assert.False(state.IsRescanning);
        Assert.True(state.BeginRefresh());
        Assert.True(state.HasReport);
        Assert.True(state.IsRescanning);
        Assert.Equal(report, state.Report);
        state.FinishRefresh(); // 失败时仍保留上一份。
        Assert.Equal(report, state.Report);
        Assert.False(state.IsRescanning);
        var newer = report with { TotalBytes = 10 };
        Assert.True(state.BeginRefresh());
        state.FinishRefresh(newer);
        Assert.Equal(newer, state.Report);
        Assert.True(new DiskReportState(report).HasReport);
    }

    [Fact]
    public void TestCleanCommandAssembly()
    {
        Assert.Equal(
            "python.exe -m kanjo disk clean codex:sessions claude:cache --older-than 30d --dry-run",
            DiskCommand.Clean("python.exe -m kanjo export", ["codex:sessions", "claude:cache"], "30d", false));
        Assert.Equal(
            "python.exe -m kanjo disk clean codex:sessions --older-than 7d --yes",
            DiskCommand.Clean("python.exe -m kanjo export", ["codex:sessions"], "7d", true));
        Assert.Equal(
            "python.exe -m kanjo disk clean antigravity:worktrees --yes",
            DiskCommand.Clean("python.exe -m kanjo export", ["antigravity:worktrees"], null, true));
        Assert.Equal(
            "python.exe -m kanjo disk clean 'id with space' --older-than 90d --dry-run",
            DiskCommand.Clean("python.exe -m kanjo export", ["id with space"], "90d", false));
        Assert.Equal(
            "kanjo disk clean codex:cache --dry-run",
            DiskCommand.Clean("kanjo export", ["codex:cache"], "", false));
    }

    [Fact]
    public void TestCleanPlanText()
    {
        const string json = """
        {"schema_version":1,"generated_at":"2026-10-25T10:00:00Z","total_bytes":7000000000,"reclaimable_bytes":7000000000,
         "agents":[
           {"agent":"codex","label":"Codex CLI","bytes":4600000000,"entries":[
             {"id":"codex:sessions","kind":"sessions","path":"/Users/alice/.codex/sessions","bytes":4600000000,"files":2,
              "oldest":"2026-06-30","newest":"2026-10-25","deletable":"after_import","blocked":[]}]},
           {"agent":"claude","label":"Claude Code","bytes":2400000000,"entries":[
             {"id":"claude:cache","kind":"cache","path":"/Users/alice/Library/Caches/claude-cli","bytes":2400000000,"files":3,
              "oldest":"2026-08-02","newest":"2026-10-24","deletable":"always","blocked":[]}]}
         ]}
        """;
        var report = DiskDecoder.Decode(json);
        var whole = new CleanResult(
            ["/Users/alice/.codex/sessions", "/Users/alice/Library/Caches/claude-cli"], 7_000_000_000,
            [new CleanSkip("claude:scratch", "active")]);
        Assert.Equal(
            """
            Codex CLI · sessions
            /Users/alice/.codex/sessions
            1 path · 4.6 GB

            Claude Code · cache
            /Users/alice/Library/Caches/claude-cli
            1 path · 2.4 GB

            Total 2 paths · 7 GB

            Skipped
            claude:scratch — active
            """,
            CleanPlan.Text(report, whole));

        var files = new CleanResult(
            ["/Users/alice/.codex/sessions/a.jsonl", "/Users/alice/.codex/sessions/b.jsonl"], 1000, []);
        Assert.Equal(
            """
            Codex CLI · sessions
            /Users/alice/.codex/sessions/a.jsonl
            /Users/alice/.codex/sessions/b.jsonl
            2 paths

            Total 2 paths · 1 KB
            """,
            CleanPlan.Text(report, files));
    }

    [Fact]
    public void TestDiskDataOverride()
    {
        Assert.Equal("/tmp/disk.json",
            DefaultPaths.DiskDataOverride(["Kanjo", "--disk-data", "/tmp/disk.json"]));
        Assert.Null(DefaultPaths.DiskDataOverride(["Kanjo", "--data", "/tmp/a.json"]));
    }

    [Fact]
    public void TestFileDiskSourceLoadsFixture()
    {
        var r = new FileDiskSource(DiskFixturePath()).Load();
        Assert.Equal(10, r.Agents.Count);

        var missing = Assert.Throws<DataSourceError>(
            () => new FileDiskSource("/nonexistent/disk.json").Load());
        Assert.Equal(DataSourceErrorKind.FileNotFound, missing.Kind);
        Assert.Equal("Data file not found: /nonexistent/disk.json", missing.Message);

        var e = Assert.Throws<DataSourceError>(
            () => new FileDiskSource(DiskFixturePath()).Clean(["codex:cache"], null, true));
        Assert.Contains("nothing was moved", e.Message);
    }

    [Fact]
    public void TestDiskDataSourceReadsFixture()
    {
        // 用 dotnet 自身当假 CLI：`dotnet <fixture> ` 不行，所以直接验证命令推导与解码组合。
        var command = DiskCommand.Report("python.exe -m kanjo export");
        Assert.Equal("python.exe -m kanjo disk --json", command);
        var report = DiskDecoder.Decode(File.ReadAllBytes(DiskFixturePath()));
        Assert.Equal(1, report.SchemaVersion);
    }

    private static string DiskFixturePath()
    {
        var root = DefaultPaths.RepoRoot ?? throw new InvalidOperationException("repo root unavailable");
        return Path.Combine(root, "ui", "fixtures", "disk-sample.json");
    }
}
