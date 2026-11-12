using System.Reflection;

namespace Kanjo.Core;

/// <summary>
/// 位置约定（Windows）。
/// - CLI 目录查找顺序：内置 `&lt;appdir&gt;\cli` → 仓库 `cli/`（仅 Debug）→ `%LOCALAPPDATA%\KanjoFamily\cli`。
/// - Python 查找顺序：内置 `&lt;appdir&gt;\python\python.exe` → `py -3` → PATH 上的 `python`。
/// </summary>
public static class DefaultPaths
{
    private static readonly Lazy<string?> RepoRootLazy = new(ResolveRepoRoot);

    /// <summary>仓库根目录（Debug 构建时才有值，免得把构建机的源码路径编进发布的二进制）。</summary>
    public static string? RepoRoot => RepoRootLazy.Value;

    /// <summary>应用所在目录（打包后是安装目录，开发时是 bin 目录）。</summary>
    public static string AppDirectory { get; set; } = AppContext.BaseDirectory;

    public static bool IsDebugBuild =>
        typeof(DefaultPaths).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "KanjoConfiguration")?.Value == "Debug";

    private static string? ResolveRepoRoot()
    {
        if (!IsDebugBuild) return null;
        var fromMetadata = typeof(DefaultPaths).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "KanjoRepoRoot")?.Value;
        if (!string.IsNullOrEmpty(fromMetadata) && Directory.Exists(fromMetadata)) return fromMetadata;
        // 兜底：从 bin 目录往上找带 ui/ 与 cli/ 的目录。
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "ui", "Sources", "KanjoCore")) &&
                Directory.Exists(Path.Combine(dir.FullName, "cli")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        return null;
    }

    /// <summary>示例数据：Debug 用仓库里的 fixtures/sample.json，否则用随包附带的 sample.json。</summary>
    public static string SampleFixture
    {
        get
        {
            var repo = RepoRoot is { } root ? Path.Combine(root, "ui", "fixtures", "sample.json") : null;
            if (repo is not null && File.Exists(repo)) return repo;
            var bundled = Path.Combine(AppDirectory, "sample.json");
            if (File.Exists(bundled)) return bundled;
            return repo ?? bundled;
        }
    }

    /// <summary>仓库里和 ui/ 并排的 cli/ 目录（仅 Debug）。</summary>
    public static string? RepoCliDirectory =>        RepoRoot is { } root ? Path.Combine(root, "cli") : null;

    /// <summary>随包附带的内置 CLI（`&lt;appdir&gt;\cli`）。</summary>
    public static string? BundledCliDirectory
    {
        get
        {
            var dir = Path.Combine(AppDirectory, "cli");
            return IsCliDirectory(dir) ? dir : null;
        }
    }

    /// <summary>install / 家庭版安装 CLI 的位置（`%LOCALAPPDATA%\KanjoFamily\cli`）。</summary>
    public static IReadOnlyList<string> InstalledCliDirectories()
    {
        var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        var baseDir = string.IsNullOrEmpty(local)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local")
            : local;
        return [Path.Combine(baseDir, "KanjoFamily", "cli")];
    }

    /// <summary>目录下有 `kanjo/__init__.py` 才算 CLI 目录。</summary>
    public static bool IsCliDirectory(string? dir) =>
        !string.IsNullOrEmpty(dir) && File.Exists(Path.Combine(dir, "kanjo", "__init__.py"));

    /// <summary>设置里工作目录留空时用的 CLI 目录。</summary>
    public static string? ResolvedCliDirectory(IEnumerable<string?>? candidates = null)
    {
        var list = candidates?.Where(c => c is not null).Select(c => c!) ??
                   new[] { BundledCliDirectory, RepoCliDirectory }.Where(c => c is not null).Select(c => c!)!
                       .Concat(InstalledCliDirectories());
        return list.FirstOrDefault(IsCliDirectory);
    }

    public static bool CliDirectoryExists => ResolvedCliDirectory() is not null;

    /// <summary>随包附带的内置 Python（`&lt;appdir&gt;\python\python.exe`）。</summary>
    public static string? BundledPython
    {
        get
        {
            var exe = OperatingSystem.IsWindows() ? "python.exe" : "python3";
            var path = Path.Combine(AppDirectory, "python", exe);
            return File.Exists(path) ? path : null;
        }
    }

    /// <summary>命令行覆盖：`--data &lt;path&gt;` 优先，其次环境变量 `KANJO_DATA`。</summary>
    public static string? DataOverride(
        IReadOnlyList<string>? arguments = null,
        IReadOnlyDictionary<string, string>? environment = null)
    {
        var args = arguments ?? Environment.GetCommandLineArgs();
        for (var i = 0; i < args.Count - 1; i++)
        {
            if (args[i] == "--data") return ResolvePath(args[i + 1]);
        }
        var env = environment ?? AppSettings.ReadEnvironment();
        if (env.TryGetValue("KANJO_DATA", out var value) && value.Length > 0) return ResolvePath(value);
        return null;
    }

    /// <summary>开发开关 `--disk-data &lt;path&gt;`：磁盘页读这个 JSON，不跑 `kanjo disk`。</summary>
    public static string? DiskDataOverride(IReadOnlyList<string>? arguments = null)
    {
        var args = arguments ?? Environment.GetCommandLineArgs();
        for (var i = 0; i < args.Count - 1; i++)
        {
            if (args[i] == "--disk-data") return ExpandTilde(args[i + 1]);
        }
        return null;
    }

    /// <summary>取某个 `--flag value` 参数。</summary>
    public static string? FlagValue(string flag, IReadOnlyList<string>? arguments = null)
    {
        var args = arguments ?? Environment.GetCommandLineArgs();
        for (var i = 0; i < args.Count; i++)
        {
            if (args[i] == flag && i + 1 < args.Count) return args[i + 1];
            if (args[i].StartsWith(flag + "=", StringComparison.Ordinal)) return args[i][(flag.Length + 1)..];
        }
        return null;
    }

    /// <summary>设置里的命令留空时用的默认导出命令：Windows 是 `py -3 -m kanjo export`，开发（macOS）是 `python3 -m kanjo export`。</summary>
    public static string DefaultCliCommand => OperatingSystem.IsWindows()
        ? "py -3 -m kanjo export"
        : "python3 -m kanjo export";

    /// <summary>`--flag value` 取参数（同 <see cref="FlagValue"/>）。</summary>
    public static string? Flag(string flag, IReadOnlyList<string>? arguments = null) =>
        FlagValue(flag, arguments);

    /// <summary>
    /// 覆盖路径解析成绝对路径（对应 Mac 的 URL(fileURLWithPath:relativeTo: currentDirectoryPath)）。
    /// 设置页的警告卡要显示解析后的绝对路径，不能显示命令行里写的相对路径。
    /// </summary>
    public static string ResolvePath(string path)
    {
        var expanded = ExpandTilde(path);
        try
        {
            return Path.GetFullPath(expanded);
        }
        catch (Exception)
        {
            return expanded;
        }
    }

    public static string ExpandTilde(string path)
    {
        if (path == "~") return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (path.StartsWith("~/", StringComparison.Ordinal) || path.StartsWith("~\\", StringComparison.Ordinal))
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), path[2..]);
        }
        return path;
    }
}
