namespace Kanjo.Core;

/// <summary>
/// 文件监听的准入规则（Mac 的 <c>ReportStore.setupWatcher</c>）：只有 CLI 数据源、且没有 `--data` 覆盖时
/// 才监听日志目录；路径来自 CLI 的 `paths --json`，多 agent 重复的目录只留一份。
/// </summary>
public static class LogWatchPaths
{
    public static bool ShouldWatch(bool hasDataOverride, SourceKind sourceKind) =>
        !hasDataOverride && sourceKind == SourceKind.Cli;

    /// <summary>所有 agent 的日志目录去重（忽略大小写：Windows 路径不区分大小写）。</summary>
    public static IReadOnlyList<string> Flatten(IReadOnlyDictionary<string, IReadOnlyList<string>>? map)
    {
        if (map is null) return [];
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var paths in map.Values)
        {
            foreach (var path in paths)
            {
                if (string.IsNullOrWhiteSpace(path)) continue;
                if (seen.Add(path)) result.Add(path);
            }
        }
        return result;
    }

    /// <summary>只留下真实存在的目录（Mac 的 <c>LogWatcher.start</c> 也会过滤掉不存在的路径）。</summary>
    public static IReadOnlyList<string> Existing(IEnumerable<string> paths) =>
        paths.Where(p => !string.IsNullOrWhiteSpace(p) && Directory.Exists(p)).ToList();
}
