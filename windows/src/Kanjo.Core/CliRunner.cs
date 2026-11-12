using System.Diagnostics;
using System.Text;

namespace Kanjo.Core;

/// <summary>一次 CLI 调用的结果。</summary>
public sealed record CliResult(int ExitCode, string Stdout, string Stderr, bool TimedOut, string FileName)
{
    public byte[] StdoutBytes => Encoding.UTF8.GetBytes(Stdout);
}

/// <summary>
/// 直接运行进程（不经过 shell），与 Mac 版 `CLIDataSource.run` 的语义一致：
/// 两路输出并发读取、stdin 关闭、`PYTHONDONTWRITEBYTECODE=1`、超时后杀掉整个进程树。
/// Windows 上跑内置 Python：`&lt;python.exe&gt; -m kanjo export`。
/// </summary>
public static class ProcessRunner
{
    public static CliResult Run(
        string fileName,
        IReadOnlyList<string> arguments,
        string? workingDirectory = null,
        TimeSpan? timeout = null,
        IReadOnlyDictionary<string, string>? extraEnvironment = null,
        string? stdinText = null)
    {
        if (!string.IsNullOrEmpty(workingDirectory) && !Directory.Exists(workingDirectory))
        {
            throw DataSourceError.LaunchFailed($"working directory does not exist: {workingDirectory}");
        }

        var psi = new ProcessStartInfo(fileName)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = workingDirectory ?? string.Empty,
        };
        foreach (var arg in arguments) psi.ArgumentList.Add(arg);

        psi.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        if (extraEnvironment is not null)
        {
            foreach (var (k, v) in extraEnvironment) psi.Environment[k] = v;
        }

        var stdout = new StringBuilder();
        var stderr = new StringBuilder();

        Process process;
        try
        {
            process = Process.Start(psi) ?? throw DataSourceError.LaunchFailed($"could not start {fileName}");
        }
        catch (Exception e) when (e is not DataSourceError)
        {
            throw DataSourceError.LaunchFailed(e.Message);
        }

        using (process)
        {
            var stdoutTask = process.StandardOutput.ReadToEndAsync();
            var stderrTask = process.StandardError.ReadToEndAsync();
            try
            {
                if (stdinText is null)
                {
                    // stdin 关闭：CLI 里任何交互提示都不会挂住。
                    process.StandardInput.Close();
                }
                else
                {
                    process.StandardInput.Write(stdinText);
                    process.StandardInput.Close();
                }
            }
            catch (IOException)
            {
                // 子进程可能已经退出。
            }

            var wait = timeout ?? TimeSpan.FromSeconds(300);
            var exited = process.WaitForExit((int)Math.Min(wait.TotalMilliseconds, int.MaxValue));
            if (!exited)
            {
                try
                {
                    process.Kill(entireProcessTree: true);
                }
                catch (Exception)
                {
                    // 已经退出。
                }
                process.WaitForExit(5000);
                try
                {
                    Task.WaitAll([stdoutTask, stderrTask], TimeSpan.FromSeconds(5));
                }
                catch (AggregateException)
                {
                    // 流已被杀掉。
                }
                return new CliResult(-1, SafeResult(stdoutTask), SafeResult(stderrTask), true, fileName);
            }

            Task.WaitAll([stdoutTask, stderrTask], TimeSpan.FromSeconds(5));
            stdout.Append(SafeResult(stdoutTask));
            stderr.Append(SafeResult(stderrTask));
            return new CliResult(process.ExitCode, stdout.ToString(), stderr.ToString(), false, fileName);
        }
    }

    private static string SafeResult(Task<string> task)
    {
        try
        {
            return task.IsCompletedSuccessfully ? task.Result : string.Empty;
        }
        catch (Exception)
        {
            return string.Empty;
        }
    }
}

/// <summary>
/// CLI 运行器：Python 解释器 + `-m kanjo &lt;args&gt;`。
/// Python 查找顺序：内置 `&lt;appdir&gt;\python\python.exe` → `py -3` → PATH 上的 `python`。
/// CLI 目录查找顺序：内置 `&lt;appdir&gt;\cli` → 仓库 `cli/`（仅 Debug）→ `%LOCALAPPDATA%\KanjoFamily\cli`。
/// </summary>
public sealed class CliRunner
{
    public const string DefaultModule = "kanjo";

    /// <summary>设置里命令留空时用的默认导出命令（Windows 上是 py -3）。</summary>
    public const string DefaultCliCommand = "py -3 -m kanjo export";

    public string? PythonExecutable { get; init; }
    public IReadOnlyList<string> PythonPrefixArguments { get; init; } = [];
    public string? WorkingDirectory { get; init; }
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(300);
    public IReadOnlyDictionary<string, string> Environment { get; init; } = new Dictionary<string, string>();

    /// <summary>按查找顺序解析 Python。找不到时返回 null（调用方给出可读错误）。</summary>
    public static (string Executable, IReadOnlyList<string> Prefix)? ResolvePython(string? preferred = null)
    {
        if (preferred is { Length: > 0 })
        {
            return (preferred, Array.Empty<string>());
        }
        if (DefaultPaths.BundledPython is { } bundled) return (bundled, Array.Empty<string>());
        if (OperatingSystem.IsWindows())
        {
            // py -3：官方 launcher，装在 PATH 上。
            if (WhichOnPath("py.exe") is not null || WhichOnPath("py") is not null)
            {
                return ("py", ["-3"]);
            }
            if (WhichOnPath("python.exe") is { } python) return (python, Array.Empty<string>());
            return null;
        }
        if (WhichOnPath("python3") is { } py3) return (py3, Array.Empty<string>());
        if (WhichOnPath("python") is { } py) return (py, Array.Empty<string>());
        return null;
    }

    public static string? WhichOnPath(string name)
    {
        var path = System.Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (var dir in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(dir.Trim('"'), name);
                if (File.Exists(candidate)) return candidate;
                if (!OperatingSystem.IsWindows() && File.Exists(candidate + ".exe")) return candidate + ".exe";
            }
            catch (ArgumentException)
            {
                // PATH 里有非法字符。
            }
        }
        return null;
    }

    /// <summary>按查找顺序找 CLI 目录（含 `kanjo/__init__.py`）。</summary>
    public static string? ResolveCliDirectory(string? configured = null)
    {
        if (!string.IsNullOrWhiteSpace(configured))
        {
            var dir = DefaultPaths.ExpandTilde(configured.Trim());
            return Directory.Exists(dir) ? dir : null;
        }
        return DefaultPaths.ResolvedCliDirectory();
    }

    public bool CanRun(out string error)
    {
        if (PythonExecutable is null && ResolvePython() is null)
        {
            error = "Python not found: bundle <appdir>\\python\\python.exe, or install Python 3.";
            return false;
        }
        if (ResolveCliDirectory(WorkingDirectory) is null)
        {
            error = "Kanjo CLI directory not found: bundle <appdir>\\cli, repo cli/, or %LOCALAPPDATA%\\KanjoFamily\\cli.";
            return false;
        }
        error = string.Empty;
        return true;
    }

    /// <summary>运行 `kanjo &lt;args...&gt;`。返回 stdout / stderr / 退出码。</summary>
    public CliResult Run(IReadOnlyList<string> arguments)
    {
        var python = PythonExecutable is null ? ResolvePython() : (PythonExecutable, PythonPrefixArguments);
        if (python is not { } py)
        {
            throw DataSourceError.LaunchFailed("Python not found: bundle <appdir>\\python\\python.exe, or install Python 3.");
        }
        var cwd = ResolveCliDirectory(WorkingDirectory);
        if (cwd is null)
        {
            throw DataSourceError.LaunchFailed(
                "Kanjo CLI directory not found: bundle <appdir>\\cli, repo cli/, or %LOCALAPPDATA%\\KanjoFamily\\cli.");
        }
        var fullArgs = py.Item2.Concat(["-m", DefaultModule]).Concat(arguments).ToList();
        return ProcessRunner.Run(py.Item1, fullArgs, cwd, Timeout, Environment);
    }

    /// <summary>运行并把失败 / 超时 / 空输出转成 <see cref="DataSourceError"/>。</summary>
    public CliResult RunChecked(IReadOnlyList<string> arguments, string emptyWhat = "Command output")
    {
        var display = "python -m kanjo " + string.Join(" ", arguments);
        var result = Run(arguments);
        if (result.TimedOut)
        {
            throw DataSourceError.CommandTimedOut(display, (int)Timeout.TotalSeconds);
        }
        if (result.ExitCode != 0)
        {
            throw DataSourceError.CommandFailed(display, result.ExitCode, result.Stderr);
        }
        if (result.Stdout.Length == 0)
        {
            throw DataSourceError.EmptyInput(emptyWhat);
        }
        return result;
    }

    public UsageReport Export()
    {
        var result = RunChecked(["export"]);
        return ReportDecoder.Decode(result.StdoutBytes);
    }

    public DiskReport Disk(bool rescan = false, TimeSpan? maxAge = null)
    {
        var args = new List<string> { "disk", "--json" };
        if (rescan) args.Add("--rescan");
        else if (maxAge is { } age) args.AddRange(["--max-age", ((int)age.TotalSeconds).ToString()]);
        var result = RunChecked(args);
        return DiskDecoder.Decode(result.StdoutBytes);
    }

    public CleanResult DiskClean(IReadOnlyList<string> ids, string? olderThan, bool confirmed)
    {
        var args = new List<string> { "disk", "clean" };
        args.AddRange(ids);
        if (!string.IsNullOrEmpty(olderThan)) args.AddRange(["--older-than", olderThan]);
        args.Add(confirmed ? "--yes" : "--dry-run");
        var result = RunChecked(args);
        return DiskDecoder.DecodeClean(result.StdoutBytes);
    }

    public IReadOnlyDictionary<string, IReadOnlyList<string>> Paths()
    {
        var result = RunChecked(["paths", "--json"]);
        return ReportDecoder.DecodePathsJson(result.StdoutBytes);
    }

    public IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>> KnownPlans()
    {
        try
        {
            var result = Run(["config", "plans", "--json"]);
            if (result.TimedOut || result.ExitCode != 0) return KnownPlan.FallbackPlans;
            var decoded = ReportDecoder.DecodeKnownPlans(result.StdoutBytes);
            return decoded.Count == 0 ? KnownPlan.FallbackPlans : decoded;
        }
        catch (DataSourceError)
        {
            return KnownPlan.FallbackPlans;
        }
    }

    public void ConfigSet(string key, string value) => RunChecked(["config", "set", key, value], "config output");

    public void ConfigUnset(string key) => RunChecked(["config", "unset", key], "config output");

    /// <summary>运行 `kanjo &lt;args...&gt;`，可以临时覆盖超时并附加环境变量。</summary>
    public CliResult RunDetailed(IReadOnlyList<string> arguments, string emptyWhat, TimeSpan? timeout = null,
        IReadOnlyDictionary<string, string>? extraEnvironment = null)
    {
        var python = PythonExecutable is null ? ResolvePython() : (PythonExecutable, PythonPrefixArguments);
        if (python is not { } py)
        {
            throw DataSourceError.LaunchFailed("Python not found: bundle <appdir>\\python\\python.exe, or install Python 3.");
        }
        var cwd = ResolveCliDirectory(WorkingDirectory);
        if (cwd is null)
        {
            throw DataSourceError.LaunchFailed(
                "Kanjo CLI directory not found: bundle <appdir>\\cli, repo cli/, or %LOCALAPPDATA%\\KanjoFamily\\cli.");
        }
        var env = new Dictionary<string, string>(Environment, StringComparer.Ordinal);
        if (extraEnvironment is not null)
        {
            foreach (var (key, value) in extraEnvironment) env[key] = value;
        }
        var limit = timeout ?? Timeout;
        var fullArgs = py.Item2.Concat(["-m", DefaultModule]).Concat(arguments).ToList();
        var result = ProcessRunner.Run(py.Item1, fullArgs, cwd, limit, env);
        var display = "python -m kanjo " + string.Join(" ", arguments);
        if (result.TimedOut) throw DataSourceError.CommandTimedOut(display, (int)limit.TotalSeconds);
        if (result.ExitCode != 0) throw DataSourceError.CommandFailed(display, result.ExitCode, result.Stderr);
        if (result.Stdout.Length == 0) throw DataSourceError.EmptyInput(emptyWhat);
        return result;
    }

    /// <summary>`kanjo publish-usage --repo … [--file …] [--branch …]`（超时 120 秒）。</summary>
    public string PublishUsage(string repo, string? file, string? branch)
    {
        var args = new List<string> { "publish-usage", "--repo", repo.Trim() };
        if (!string.IsNullOrWhiteSpace(file)) args.AddRange(["--file", file.Trim()]);
        if (!string.IsNullOrWhiteSpace(branch)) args.AddRange(["--branch", branch.Trim()]);
        return RunDetailed(args, "publish output", TimeSpan.FromSeconds(120)).Stdout;
    }

    /// <summary>`kanjo report-family --url … [--member-label …]`（超时 45 秒），令牌只走环境变量。</summary>
    public string ReportFamily(string url, string? memberLabel, string token)
    {
        var args = new List<string> { "report-family", "--url", url.Trim() };
        if (!string.IsNullOrWhiteSpace(memberLabel)) args.AddRange(["--member-label", memberLabel.Trim()]);
        var env = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["KANJO_FAMILY_TOKEN"] = token.Trim(),
        };
        return RunDetailed(args, "family report output", TimeSpan.FromSeconds(45), env).Stdout;
    }
}
