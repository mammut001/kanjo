using System.Text.Json;

namespace Kanjo.Core;

public enum DiskKind
{
    Sessions,
    Scratch,
    Worktrees,
    Cache,
    Memory,
    Other,
    Unknown,
}

public enum DiskDeletable
{
    Always,
    AfterImport,
    WhenClean,
    Never,
    Unknown,
}

/// <summary>CONTRACT.md §10。kind / deletable 遇到不认识的字符串不失败，原样留下（见 Raw 字段）。</summary>
public sealed record DiskEntry(
    string Id,
    DiskKind Kind,
    string Path,
    long Bytes,
    int Files,
    string Oldest,
    string Newest,
    DiskDeletable Deletable,
    RoList<string> Blocked,
    string? Note,
    string RawKind,
    string RawDeletable)
{
    /// <summary>现在可以交给 `disk clean` 的条目。never 永久留下；blocked 非空时 CLI 会跳过。</summary>
    public bool IsReclaimable => Deletable != DiskDeletable.Never && Blocked.Count == 0;

    public string KindRaw => RawKind;

    public string DeletableRaw => RawDeletable;

    public static DiskEntry Decode(JsonElement e, string path)
    {
        var rawKind = J.String(e, "kind", path);
        var rawDeletable = J.String(e, "deletable", path);
        return new DiskEntry(
            J.String(e, "id", path),
            ParseKind(rawKind),
            J.String(e, "path", path),
            J.LongOrNull(e, "bytes", path) ?? 0,
            J.IntOrNull(e, "files", path) ?? 0,
            J.StringOrNull(e, "oldest", path) ?? string.Empty,
            J.StringOrNull(e, "newest", path) ?? string.Empty,
            ParseDeletable(rawDeletable),
            J.List(J.ArrayOrNull(e, "blocked", path), J.Child(path, "blocked"), (i, p) => J.ToString(i, p)),
            J.StringOrNull(e, "note", path),
            rawKind,
            rawDeletable);
    }

    public static DiskKind ParseKind(string raw) => raw switch
    {
        "sessions" => DiskKind.Sessions,
        "scratch" => DiskKind.Scratch,
        "worktrees" => DiskKind.Worktrees,
        "cache" => DiskKind.Cache,
        "memory" => DiskKind.Memory,
        "other" => DiskKind.Other,
        _ => DiskKind.Unknown,
    };

    public static DiskDeletable ParseDeletable(string raw) => raw switch
    {
        "always" => DiskDeletable.Always,
        "after_import" => DiskDeletable.AfterImport,
        "when_clean" => DiskDeletable.WhenClean,
        "never" => DiskDeletable.Never,
        _ => DiskDeletable.Unknown,
    };
}

public sealed record DiskAgent(string Agent, string Label, long Bytes, RoList<DiskEntry> Entries)
{
    public string Id => Agent;

    public static DiskAgent Decode(JsonElement e, string path) => new(
        J.String(e, "agent", path),
        J.String(e, "label", path),
        J.LongOrNull(e, "bytes", path) ?? 0,
        J.List(J.Array(e, "entries", path), J.Child(path, "entries"), DiskEntry.Decode));
}

public sealed record DiskReport(
    int SchemaVersion,
    string GeneratedAt,
    long TotalBytes,
    long ReclaimableBytes,
    RoList<DiskAgent> Agents,
    bool? Cached,
    string? ScannedAt,
    double? ScanSeconds)
{
    public static readonly DiskReport Empty = new(1, string.Empty, 0, 0, [], null, null, null);

    public bool IsNewerSchema => SchemaVersion > Contract.SupportedSchemaVersion;

    public RoList<DiskEntry> AllEntries => Agents.SelectMany(a => a.Entries).ToList();

    /// <summary>所有 deletable != never 且 blocked 为空的条目字节之和。应等于 reclaimable_bytes。</summary>
    public long SummedReclaimableBytes => AllEntries.Where(e => e.IsReclaimable).Sum(e => e.Bytes);

    public static DiskReport Decode(JsonElement e, string path = "") => new(
        J.Int(e, "schema_version", path),
        J.String(e, "generated_at", path),
        J.LongOrNull(e, "total_bytes", path) ?? 0,
        J.LongOrNull(e, "reclaimable_bytes", path) ?? 0,
        J.List(J.Array(e, "agents", path), J.Child(path, "agents"), DiskAgent.Decode),
        J.BoolOrNull(e, "cached", path),
        J.StringOrNull(e, "scanned_at", path),
        J.NumberOrNull(e, "scan_seconds", path));
}

public sealed record CleanSkip(string Id, string Reason)
{
    public static CleanSkip Decode(JsonElement e, string path) => new(
        J.String(e, "id", path),
        J.String(e, "reason", path));
}

public sealed record CleanResult(RoList<string> Moved, long FreedBytes, RoList<CleanSkip> Skipped)
{
    public static CleanResult Decode(JsonElement e, string path = "") => new(
        J.List(J.ArrayOrNull(e, "moved", path), J.Child(path, "moved"), (i, p) => J.ToString(i, p)),
        J.LongOrNull(e, "freed_bytes", path) ?? 0,
        J.List(J.ArrayOrNull(e, "skipped", path), J.Child(path, "skipped"), CleanSkip.Decode));
}

/// <summary>blocked 原因的界面短句。不认识的原因保留原文（下划线换成空格）。</summary>
public static class DiskBlock
{
    public static string Short(string reason) => reason switch
    {
        "not_imported" => L10n.Tr("disk.block.not_imported"),
        "uncommitted_changes" => L10n.Tr("disk.block.uncommitted_changes"),
        "active" => L10n.Tr("disk.block.active"),
        _ => reason.Replace("_", " ", StringComparison.Ordinal),
    };

    public static string Title(string reason) => L10n.Tr("disk.blocked_reason", Short(reason));

    public static string Explanation(string reason) => reason switch
    {
        "not_imported" => L10n.Tr("disk.block.explanation.not_imported"),
        "uncommitted_changes" => L10n.Tr("disk.block.explanation.uncommitted_changes"),
        "active" => L10n.Tr("disk.block.explanation.active"),
        _ => L10n.Tr("disk.block.explanation.default"),
    };
}

/// <summary>dry-run 结果的可读计划：路径按条目分组，附数量和大小。确认页和测试共用这一份。</summary>
public sealed record CleanPlanGroup(string EntryId, string Title, RoList<string> Paths, long? Bytes);

public static class CleanPlan
{
    public static RoList<CleanPlanGroup> Groups(DiskReport report, RoList<string> moved)
    {
        var index = report.Agents
            .SelectMany(agent => agent.Entries.Select(entry => (Entry: entry, Title: $"{agent.Label} · {entry.RawKind}")))
            .ToList();

        var buckets = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        var order = new List<string>();
        var other = new List<string>();

        foreach (var path in moved)
        {
            var hits = index.Where(i => Owns(i.Entry, path)).ToList();
            if (hits.Count == 0)
            {
                other.Add(path);
                continue;
            }
            var hit = hits.OrderBy(h => h.Entry.Path.Length).Last();
            if (!buckets.TryGetValue(hit.Entry.Id, out var list))
            {
                list = [];
                buckets[hit.Entry.Id] = list;
                order.Add(hit.Entry.Id);
            }
            list.Add(path);
        }

        var indexOrder = index.Select(i => i.Entry.Id).ToList();
        var ids = order.OrderBy(id => indexOrder.IndexOf(id) is var i && i >= 0 ? i : int.MaxValue).ToList();

        var result = new List<CleanPlanGroup>();
        foreach (var id in ids)
        {
            var entry = index.First(i => i.Entry.Id == id).Entry;
            var paths = buckets[id];
            var whole = paths.Count == 1 && paths[0] == entry.Path;
            result.Add(new CleanPlanGroup(id, index.First(i => i.Entry.Id == id).Title, paths, whole ? entry.Bytes : null));
        }
        if (other.Count > 0)
        {
            result.Add(new CleanPlanGroup(string.Empty, "Other", other, null));
        }
        return result;
    }

    public static string Text(DiskReport report, CleanResult result)
    {
        var blocks = Groups(report, result.Moved).Select(GroupText).ToList();
        blocks.Add($"Total {CountAndSize(result.Moved.Count, result.FreedBytes)}");
        var body = string.Join("\n\n", blocks);
        if (result.Skipped.Count > 0)
        {
            var lines = result.Skipped.Select(s => $"{s.Id} — {DiskBlock.Short(s.Reason)}");
            body += "\n\nSkipped\n" + string.Join("\n", lines);
        }
        return body;
    }

    public static string GroupText(CleanPlanGroup g) =>
        string.Join("\n", new[] { g.Title }.Concat(g.Paths).Append(CountAndSize(g.Paths.Count, g.Bytes)));

    /// <summary>`1 path · 4.6 GB`，没有大小时只写数量（`2 paths`）。</summary>
    public static string CountAndSize(int count, long? bytes)
    {
        var noun = count == 1 ? "path" : "paths";
        return bytes is { } b ? $"{count} {noun} · {Fmt.Bytes(b)}" : $"{count} {noun}";
    }

    private static bool Owns(DiskEntry entry, string path)
    {
        if (path == entry.Path) return true;
        // POSIX reports list "<entry.Path>/<file>"; on Windows disk clean reports the
        // same tree with "\", so both separators count and the drive letter is folded.
        var comparison = IsWindowsPath(entry.Path) ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        foreach (var separator in IsWindowsPath(entry.Path) ? new[] { '\\', '/' } : ['/'])
        {
            var prefix = entry.Path.TrimEnd('/', '\\') + separator;
            if (path.Length > prefix.Length && path.StartsWith(prefix, comparison)) return true;
        }
        return false;
    }

    /// <summary>"C:\..." or "\\server\share": a path whose separator is "\".</summary>
    private static bool IsWindowsPath(string path) =>
        path.StartsWith(@"\\", StringComparison.Ordinal)
        || (path.Length >= 3 && path[1] == ':' && (path[2] == '\\' || path[2] == '/'));
}
