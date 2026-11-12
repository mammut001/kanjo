namespace Kanjo.Core;

/// <summary>
/// 项目路径分类：把 agent 留下的临时目录（scratchpad、worktree、系统临时目录等）和用户真正的项目目录分开，
/// 详情页默认只展示后者。Windows 上额外识别 `%TEMP%` 与 `%LOCALAPPDATA%\Temp`。
/// </summary>
public static class PathKinds
{
    /// <summary>系统临时目录前缀。</summary>
    private static readonly string[] TemporaryRootPrefixes =
        ["/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"];

    /// <summary>相对 home 的 agent 数据目录前缀（`~/` 之后的部分）。</summary>
    private static readonly string[] TemporaryHomePrefixes = [".gemini/", ".claude/", ".codex/"];

    /// <summary>出现在任一路径分量里就算临时目录。</summary>
    private static readonly HashSet<string> TemporaryComponents =
        new(["scratchpad", "scratch", "worktrees", ".worktrees"], StringComparer.OrdinalIgnoreCase);

    /// <summary>Windows 临时目录（%TEMP%、%LOCALAPPDATA%\Temp）。</summary>
    public static IReadOnlyList<string> WindowsTempPrefixes()
    {
        var list = new List<string>();
        var temp = Environment.GetEnvironmentVariable("TEMP");
        if (string.IsNullOrEmpty(temp)) temp = Path.GetTempPath();
        if (!string.IsNullOrEmpty(temp)) list.Add(Normalize(temp));
        var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (!string.IsNullOrEmpty(local)) list.Add(Normalize(Path.Combine(local, "Temp")));
        return list.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static string Normalize(string path) =>
        path.Replace('\\', '/').TrimEnd('/');

    /// <summary>路径是否是临时目录。`~` 按 home 展开（默认当前用户 home）。</summary>
    public static bool IsTemporaryPath(string path, string? home = null)
    {
        home ??= Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        home = Normalize(home);
        var expanded = Normalize(ExpandTilde(path, home));
        var homeSlash = home.EndsWith("/", StringComparison.Ordinal) ? home : home + "/";
        var prefixes = TemporaryRootPrefixes
            .Concat(TemporaryHomePrefixes.Select(p => homeSlash + p))
            .Concat(WindowsTempPrefixes().Select(p => p + "/"))
            .ToList();

        foreach (var prefix in prefixes)
        {
            if (expanded.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return true;
            if (string.Equals(expanded, prefix.TrimEnd('/'), StringComparison.OrdinalIgnoreCase)) return true;
        }

        // Windows 盘符路径（C:/...）也要按分量判断。
        return expanded.Split('/', StringSplitOptions.RemoveEmptyEntries)
            .Any(part => TemporaryComponents.Contains(part));
    }

    /// <summary>按 <see cref="IsTemporaryPath"/> 拆成主路径和临时路径，两组各自保持原顺序。</summary>
    public static (IReadOnlyList<string> Primary, IReadOnlyList<string> Temporary) SplitPaths(
        IReadOnlyList<string> paths, string? home = null)
    {
        var primary = new List<string>();
        var temporary = new List<string>();
        foreach (var p in paths)
        {
            if (IsTemporaryPath(p, home)) temporary.Add(p);
            else primary.Add(p);
        }
        return (primary, temporary);
    }

    private static string ExpandTilde(string path, string home)
    {
        if (path == "~") return home;
        if (path.StartsWith("~/", StringComparison.Ordinal)) return home.TrimEnd('/') + path[1..];
        return path;
    }
}

/// <summary>隐藏 / 置顶项目：UI 存成换行分隔的 project id 字符串。这里只做纯解析与排列。</summary>
public static class ProjectPrefs
{
    /// <summary>换行分隔 → 集合。忽略空行和首尾空白。</summary>
    public static HashSet<string> Parse(string raw)
    {
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var line in SplitLines(raw))
        {
            var trimmed = line.Trim();
            if (trimmed.Length > 0) set.Add(trimmed);
        }
        return set;
    }

    private static IEnumerable<string> SplitLines(string raw) =>
        raw.Split(['\n', '\r'], StringSplitOptions.RemoveEmptyEntries);

    /// <summary>集合 → 换行分隔（排序后输出，保证稳定）。</summary>
    public static string Serialize(IEnumerable<string> ids) =>
        string.Join("\n", ids.OrderBy(i => i, StringComparer.Ordinal));

    /// <summary>在集合里加入 / 移除 id。</summary>
    public static HashSet<string> Toggle(string id, ISet<string> ids)
    {
        var s = new HashSet<string>(ids, StringComparer.Ordinal);
        if (!s.Remove(id)) s.Add(id);
        return s;
    }

    /// <summary>直接在存储字符串上切换。</summary>
    public static string Toggle(string id, string raw) => Serialize(Toggle(id, Parse(raw)));

    /// <summary>列表排列：隐藏的分出去；其余置顶的在前。两组内部都保持输入顺序。</summary>
    public static (List<T> Visible, List<T> Hidden) Arrange<T>(
        IEnumerable<T> items, Func<T, string> id, ISet<string> pinned, ISet<string> hidden)
    {
        var top = new List<T>();
        var rest = new List<T>();
        var gone = new List<T>();
        foreach (var item in items)
        {
            var i = id(item);
            if (hidden.Contains(i)) gone.Add(item);
            else if (pinned.Contains(i)) top.Add(item);
            else rest.Add(item);
        }
        top.AddRange(rest);
        return (top, gone);
    }
}

public sealed record SubscriptionRow(
    string Agent,
    string PlanLabel,
    double? MonthlyPriceUsd,
    double Usage,
    double? Multiplier,
    bool ExtraUsageEnabled,
    SubscriptionAccount? Account)
{
    public string Id => Agent;
}

public sealed record CycleShare(string Agent, string PlanLabel, double Share, double ProjectCost)
{
    public string Id => Agent;
}

public sealed record CycleUsage(
    IReadOnlyDictionary<string, double> TotalByAgent,
    IReadOnlyDictionary<string, IReadOnlyDictionary<string, double>> ProjectAgentCost)
{
    public double Total(string agent) => TotalByAgent.GetValueOrDefault(agent);

    public double Cost(string projectId, string agent) =>
        ProjectAgentCost.TryGetValue(projectId, out var map) ? map.GetValueOrDefault(agent) : 0;
}

/// <summary>订阅卡片自定义排序与折叠辅助函数。UI 存成逗号分隔的 agent id 字符串。</summary>
public static class SubscriptionOrder
{
    /// <summary>逗号分隔 → agent 数组。保持出现顺序，去除重复项与首尾空白。</summary>
    public static List<string> Parse(string raw)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var order = new List<string>();
        foreach (var item in raw.Split(',')
                     .Select(x => x.Trim())
                     .Where(x => x.Length > 0))
        {
            if (seen.Add(item)) order.Add(item);
        }
        return order;
    }

    /// <summary>agent 数组 → 逗号分隔。</summary>
    public static string Serialize(IEnumerable<string> order) => string.Join(",", order);

    /// <summary>应用保存的顺序：保存顺序中的 agent 在前，未保存的保持默认排序，未知的忽略。</summary>
    public static List<SubscriptionRow> Apply(IReadOnlyList<string> order, IReadOnlyList<SubscriptionRow> rows)
    {
        var rowMap = new Dictionary<string, SubscriptionRow>(StringComparer.Ordinal);
        foreach (var row in rows) rowMap[row.Agent] = row;

        var result = new List<SubscriptionRow>();
        var placed = new HashSet<string>(StringComparer.Ordinal);
        foreach (var agent in order)
        {
            if (rowMap.TryGetValue(agent, out var row) && placed.Add(agent)) result.Add(row);
        }
        foreach (var row in rows)
        {
            if (!placed.Contains(row.Agent)) result.Add(row);
        }
        return result;
    }

    /// <summary>将 source 移动到 target 的位置（移除后插入到 target 原本所在位置）。</summary>
    public static List<string> Move(string source, string target, IReadOnlyList<string> list)
    {
        var fromIndex = -1;
        var toIndex = -1;
        for (var i = 0; i < list.Count; i++)
        {
            if (list[i] == source) fromIndex = i;
            if (list[i] == target) toIndex = i;
        }
        if (fromIndex < 0 || toIndex < 0 || fromIndex == toIndex) return list.ToList();
        var result = list.ToList();
        var item = result[fromIndex];
        result.RemoveAt(fromIndex);
        result.Insert(toIndex, item);
        return result;
    }

    public static List<SubscriptionRow> Move(string source, string target, IReadOnlyList<SubscriptionRow> rows)
    {
        var fromIndex = -1;
        var toIndex = -1;
        for (var i = 0; i < rows.Count; i++)
        {
            if (rows[i].Agent == source) fromIndex = i;
            if (rows[i].Agent == target) toIndex = i;
        }
        if (fromIndex < 0 || toIndex < 0 || fromIndex == toIndex) return rows.ToList();
        var result = rows.ToList();
        var item = result[fromIndex];
        result.RemoveAt(fromIndex);
        result.Insert(toIndex, item);
        return result;
    }

    /// <summary>基于下标的通用移动操作。</summary>
    public static List<T> Move<T>(int sourceIndex, int targetIndex, IReadOnlyList<T> list)
    {
        if (sourceIndex == targetIndex || sourceIndex < 0 || sourceIndex >= list.Count ||
            targetIndex < 0 || targetIndex >= list.Count)
        {
            return list.ToList();
        }
        var result = list.ToList();
        var item = result[sourceIndex];
        result.RemoveAt(sourceIndex);
        result.Insert(targetIndex, item);
        return result;
    }

    /// <summary>折叠/展开辅助函数：未展开时最多返回 limit 行（默认 3 行）；展开时返回全部。</summary>
    public static List<T> Visible<T>(IReadOnlyList<T> items, bool expanded, int limit = 3) =>
        expanded || items.Count <= limit ? items.ToList() : items.Take(Math.Max(0, limit)).ToList();
}
