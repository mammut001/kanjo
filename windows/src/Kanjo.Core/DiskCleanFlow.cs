namespace Kanjo.Core;

/// <summary>Dry-run 确认卡要冻结的参数：确认时不能再读可变的勾选 / Older than。</summary>
public sealed record DiskCleanPreview(
    RoList<string> Ids,
    string? OlderThan,
    CleanResult Result,
    bool Merged = false);

/// <summary>Disk 页清理流程的可测逻辑（Mac DiskView / Windows DiskPage 共用语义）。</summary>
public static class DiskCleanFlow
{
    /// <summary>部分成功后：整目录已进 moved 的条目取消勾选；跳过或只挪了部分文件的条目保留。</summary>
    public static HashSet<string> SelectionAfter(
        IReadOnlyCollection<string> selected,
        DiskReport report,
        CleanResult result)
    {
        var moved = result.Moved.ToHashSet(StringComparer.Ordinal);
        var byId = report.AllEntries.ToDictionary(e => e.Id, StringComparer.Ordinal);
        var next = new HashSet<string>(selected, StringComparer.Ordinal);
        foreach (var id in selected)
        {
            if (!byId.TryGetValue(id, out var entry))
            {
                next.Remove(id);
                continue;
            }
            if (moved.Contains(entry.Path)) next.Remove(id);
        }
        return next;
    }

    /// <summary>Move 只能点一次：已在执行，或 dry-run 没有可移动路径时都不能再开清理。</summary>
    public static bool CanBeginMove(bool applying, int movedCount) => !applying && movedCount > 0;

    /// <summary>CLI 退出 0 的清理结果（含部分 moved + skipped）一律进结果卡，不当总失败。</summary>
    public static bool PresentsAsResultCard(CleanResult result)
    {
        _ = result;
        return true;
    }

    /// <summary>结果卡要列出 moved。</summary>
    public static bool ResultShowsMovedPaths(CleanResult result) => result.Moved.Count > 0;
}
