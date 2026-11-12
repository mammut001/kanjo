namespace Kanjo.Core;

public interface IUsageDataSource
{
    UsageReport Load();
}

/// <summary>读一个已导出的 JSON 文件。</summary>
public sealed class FileDataSource(string path) : IUsageDataSource
{
    public string Path { get; } = path;

    public UsageReport Load()
    {
        if (!File.Exists(Path)) throw DataSourceError.FileNotFound(Path);
        byte[] data;
        try
        {
            data = File.ReadAllBytes(Path);
        }
        catch (Exception e)
        {
            throw DataSourceError.Unreadable(Path, e.Message);
        }
        if (data.Length == 0) throw DataSourceError.EmptyInput(System.IO.Path.GetFileName(Path));
        return ReportDecoder.Decode(data);
    }
}

public interface IDiskSource
{
    DiskReport Load();

    CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed);
}

/// <summary>跑 `kanjo disk --json` 和 `kanjo disk clean`。</summary>
public sealed class CliDiskSource(CliRunner runner) : IDiskSource
{
    public DiskReport Load() => runner.Disk();

    public DiskReport Load(bool rescan) => runner.Disk(rescan);

    public CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed) =>
        runner.DiskClean(ids, olderThan, confirmed);
}

/// <summary>`--disk-data` 指定的 JSON 文件。清理不会在这里动磁盘：没有 CLI 可调用，直接拒绝。</summary>
public sealed class FileDiskSource(string path) : IDiskSource
{
    public string Path { get; } = path;

    public DiskReport Load()
    {
        if (!File.Exists(Path)) throw DataSourceError.FileNotFound(Path);
        byte[] data;
        try
        {
            data = File.ReadAllBytes(Path);
        }
        catch (Exception e)
        {
            throw DataSourceError.Unreadable(Path, e.Message);
        }
        if (data.Length == 0) throw DataSourceError.EmptyInput(System.IO.Path.GetFileName(Path));
        return DiskDecoder.Decode(data);
    }

    public CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed) =>
        throw DataSourceError.LaunchFailed(
            "Disk cleanup only runs through the kanjo CLI (disk clean). This report was loaded from a JSON file, so nothing was moved.");
}

/// <summary>磁盘报告缓存：读写失败都忽略，CLI 仍是报告的来源。目录可注入供测试隔离。</summary>
public sealed class DiskReportCache
{
    public string? FilePath { get; }

    public DiskReportCache(string? directory = null)
    {
        var baseDir = directory ?? Path.Combine(LocalAppData(), "Kanjo");
        FilePath = Path.Combine(baseDir, "disk-report.json");
    }

    private static string LocalAppData()
    {
        var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (!string.IsNullOrEmpty(local)) return local;
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
    }

    public DiskReport? Load()
    {
        if (FilePath is null || !File.Exists(FilePath)) return null;
        try
        {
            return DiskDecoder.Decode(File.ReadAllBytes(FilePath));
        }
        catch (Exception)
        {
            return null;
        }
    }

    public void Save(DiskReport report)
    {
        if (FilePath is null) return;
        try
        {
            var dir = Path.GetDirectoryName(FilePath);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            File.WriteAllText(FilePath, DiskJson.Write(report));
        }
        catch (Exception)
        {
            // 缓存不可写不影响内存中的报告。
        }
    }
}

/// <summary>把 <see cref="DiskReport"/> 写成契约 JSON（缓存用；不追求字节级一致，只要能读回来）。</summary>
public static class DiskJson
{
    public static string Write(DiskReport report)
    {
        using var stream = new MemoryStream();
        using (var w = new System.Text.Json.Utf8JsonWriter(stream, new System.Text.Json.JsonWriterOptions { Indented = true }))
        {
            w.WriteStartObject();
            w.WriteNumber("schema_version", report.SchemaVersion);
            w.WriteString("generated_at", report.GeneratedAt);
            w.WriteNumber("total_bytes", report.TotalBytes);
            w.WriteNumber("reclaimable_bytes", report.ReclaimableBytes);
            if (report.Cached is { } c) w.WriteBoolean("cached", c);
            if (report.ScannedAt is { } s) w.WriteString("scanned_at", s);
            if (report.ScanSeconds is { } secs) w.WriteNumber("scan_seconds", secs);
            w.WriteStartArray("agents");
            foreach (var agent in report.Agents)
            {
                w.WriteStartObject();
                w.WriteString("agent", agent.Agent);
                w.WriteString("label", agent.Label);
                w.WriteNumber("bytes", agent.Bytes);
                w.WriteStartArray("entries");
                foreach (var e in agent.Entries)
                {
                    w.WriteStartObject();
                    w.WriteString("id", e.Id);
                    w.WriteString("kind", e.RawKind);
                    w.WriteString("path", e.Path);
                    w.WriteNumber("bytes", e.Bytes);
                    w.WriteNumber("files", e.Files);
                    w.WriteString("oldest", e.Oldest);
                    w.WriteString("newest", e.Newest);
                    w.WriteString("deletable", e.RawDeletable);
                    w.WriteStartArray("blocked");
                    foreach (var b in e.Blocked) w.WriteStringValue(b);
                    w.WriteEndArray();
                    if (e.Note is { } note) w.WriteString("note", note);
                    w.WriteEndObject();
                }
                w.WriteEndArray();
                w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteEndObject();
        }
        return System.Text.Encoding.UTF8.GetString(stream.ToArray());
    }
}
