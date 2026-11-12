using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// CLI 运行器：用极小的假 python 脚本（Windows 上是 .cmd / .bat，其它平台是 sh 脚本）验证
/// 参数传递、工作目录、环境变量、stdin 关闭、超时、输出与退出码，不碰真实 CLI。
/// </summary>
public sealed class CliRunnerTests : KanjoTestCase
{
    /// <summary>造一个只认 `-m kanjo <args...>` 的假 python。返回可执行文件路径。</summary>
    private static string FakePython(params (string Args, int Exit, string Stdout, string Stderr)[] cases)
    {
        var dir = TempDir();
        var casesPath = Path.Combine(dir, "cases.json");
        File.WriteAllText(casesPath, System.Text.Json.JsonSerializer.Serialize(
            cases.Select(c => new { args = c.Args, exit = c.Exit, stdout = c.Stdout, stderr = c.Stderr })));

        if (OperatingSystem.IsWindows())
        {
            var cmd = Path.Combine(dir, "python.cmd");
            File.WriteAllText(cmd, $"""
                @echo off
                findstr /C:"{cases[0].Args}" "%~dp0cases.json" >nul
                echo {cases[0].Stdout}
                exit /b {cases[0].Exit}
                """);
            return cmd;
        }

        var script = Path.Combine(dir, "python");
        var body = new System.Text.StringBuilder();
        body.AppendLine("#!/bin/sh");
        body.AppendLine("args=\"$*\"");
        foreach (var c in cases)
        {
            body.AppendLine($"if [ \"$args\" = \"{c.Args}\" ]; then");
            if (c.Stdout.Length > 0) body.AppendLine($"  printf '%s\\n' '{c.Stdout.Replace("'", "'\\''")}'");
            if (c.Stderr.Length > 0) body.AppendLine($"  printf '%s\\n' '{c.Stderr.Replace("'", "'\\''")}' >&2");
            body.AppendLine($"  exit {c.Exit}");
            body.AppendLine("fi");
        }
        if (cases.Length == 0)
        {
            body.AppendLine("exit 0");
        }
        else
        {
            body.AppendLine("echo unknown-args >&2");
            body.AppendLine("exit 9");
        }
        File.WriteAllText(script, body.ToString());
        File.SetUnixFileMode(script,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
            UnixFileMode.GroupRead | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
        return script;
    }

    private static string FakeCliDir()
    {
        var dir = TempDir();
        Directory.CreateDirectory(Path.Combine(dir, "kanjo"));
        File.WriteAllText(Path.Combine(dir, "kanjo", "__init__.py"), "");
        return dir;
    }

    [Fact]
    public void TestCliDataSourceReadsStdout()
    {
        var python = FakePython(("-m kanjo export", 0, """{"ok":1}""", ""));
        var cli = FakeCliDir();
        var runner = new CliRunner { PythonExecutable = python, WorkingDirectory = cli };
        var result = runner.Run(["export"]);
        Assert.Equal(0, result.ExitCode);
        Assert.Equal("""{"ok":1}""", result.Stdout.Trim());
        Assert.False(result.TimedOut);
    }

    [Fact]
    public void TestCliDataSourceReportsFailure()
    {
        var python = FakePython(("-m kanjo export", 3, "", "boom"));
        var runner = new CliRunner { PythonExecutable = python, WorkingDirectory = FakeCliDir() };
        var e = Assert.Throws<DataSourceError>(() => runner.RunChecked(["export"]));
        Assert.Equal(DataSourceErrorKind.CommandFailed, e.Kind);
        Assert.Contains("boom", e.Message);
        Assert.Contains("status 3", e.Message);
    }

    [Fact]
    public void TestTimeoutKillsProcess()
    {
        var dir = TempDir();
        string python;
        if (OperatingSystem.IsWindows())
        {
            python = Path.Combine(dir, "python.cmd");
            File.WriteAllText(python, "@echo off\r\nping -n 30 127.0.0.1 >nul\r\nexit /b 0\r\n");
        }
        else
        {
            python = Path.Combine(dir, "python");
            File.WriteAllText(python, "#!/bin/sh\nsleep 30\n");
            File.SetUnixFileMode(python,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }

        var runner = new CliRunner
        {
            PythonExecutable = python,
            WorkingDirectory = FakeCliDir(),
            Timeout = TimeSpan.FromMilliseconds(500),
        };
        var e = Assert.Throws<DataSourceError>(() => runner.RunChecked(["export"]));
        Assert.Equal(DataSourceErrorKind.CommandTimedOut, e.Kind);
    }

    [Fact]
    public void TestMissingWorkingDirectoryRejected()
    {
        var python = FakePython(("-m kanjo export", 0, "x", ""));
        var runner = new CliRunner { PythonExecutable = python, WorkingDirectory = "/nonexistent/cli-dir" };
        var e = Assert.Throws<DataSourceError>(() => runner.Run(["export"]));
        Assert.Equal(DataSourceErrorKind.LaunchFailed, e.Kind);
    }

    [Fact]
    public void TestWorkingDirectoryAndEnvAreUsed()
    {
        var dir = TempDir();
        var cli = FakeCliDir();
        string python;
        if (OperatingSystem.IsWindows())
        {
            python = Path.Combine(dir, "python.cmd");
            File.WriteAllText(python, "@echo off\r\necho %CD%|%PYTHONDONTWRITEBYTECODE%\r\n");
        }
        else
        {
            python = Path.Combine(dir, "python");
            File.WriteAllText(python, "#!/bin/sh\necho \"$PWD|$PYTHONDONTWRITEBYTECODE\"\n");
            File.SetUnixFileMode(python,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        var runner = new CliRunner { PythonExecutable = python, WorkingDirectory = cli };
        var result = runner.Run(["export"]);
        var parts = result.Stdout.Trim().Split('|');
        // 比较目录名（/var 与 /private/var 在 macOS 上互为软链）
        Assert.Equal(Path.GetFileName(Path.GetFullPath(cli)), Path.GetFileName(Path.GetFullPath(parts[0])));
        Assert.Equal("1", parts[1]);
    }

    [Fact]
    public void TestExportDecodesReport()
    {
        // 用 dotnet 自身当进程：把一份契约 JSON 写到 stdout。
        var sample = File.ReadAllText(FixturePath);
        var dir = TempDir();
        var echoScript = Path.Combine(dir, "python");
        string python;
        if (OperatingSystem.IsWindows())
        {
            // Windows：cmd 的 echo 处理长 JSON 不可靠，用 dotnet 起一个小程序代价太大；
            // 这条用例的意义是「进程输出能解码」，所以在 Windows 上直接用 cat 等价物（type）。
            python = Path.Combine(dir, "python.cmd");
            File.WriteAllText(python, "@echo off\r\ntype \"%KANJO_TEST_FIXTURE%\"\r\n");
        }
        else
        {
            python = echoScript;
            File.WriteAllText(python, "#!/bin/sh\ncat \"$KANJO_TEST_FIXTURE\"\n");
            File.SetUnixFileMode(python,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        var runner = new CliRunner
        {
            PythonExecutable = python,
            WorkingDirectory = FakeCliDir(),
            Environment = new Dictionary<string, string> { ["KANJO_TEST_FIXTURE"] = FixturePath },
        };
        var report = runner.Export();
        Assert.Equal(1, report.SchemaVersion);
        Assert.Equal(System.Text.Json.JsonDocument.Parse(sample).RootElement.GetProperty("currency").GetString(),
            report.Currency);
    }

    [Fact]
    public void TestEmptyOutputIsReported()
    {
        var python = FakePython(("-m kanjo export", 0, "", ""));
        var runner = new CliRunner { PythonExecutable = python, WorkingDirectory = FakeCliDir() };
        var e = Assert.Throws<DataSourceError>(() => runner.RunChecked(["export"]));
        Assert.Equal(DataSourceErrorKind.EmptyInput, e.Kind);
    }

    [Fact]
    public void TestCliDirectoryLookupOrder()
    {
        var root = TempDir();
        var bundled = Path.Combine(root, "bundle", "cli");
        var repo = Path.Combine(root, "repo", "cli");
        var user = Path.Combine(root, "local", "KanjoFamily", "cli");

        Assert.Null(DefaultPaths.ResolvedCliDirectory([bundled, repo, user]));

        Directory.CreateDirectory(Path.Combine(user, "kanjo"));
        File.WriteAllText(Path.Combine(user, "kanjo", "__init__.py"), "");
        Assert.Equal(user, DefaultPaths.ResolvedCliDirectory([bundled, repo, user]));

        Directory.CreateDirectory(Path.Combine(repo, "kanjo"));
        File.WriteAllText(Path.Combine(repo, "kanjo", "__init__.py"), "");
        Assert.Equal(repo, DefaultPaths.ResolvedCliDirectory([bundled, repo, user]));

        Directory.CreateDirectory(Path.Combine(bundled, "kanjo"));
        File.WriteAllText(Path.Combine(bundled, "kanjo", "__init__.py"), "");
        Assert.Equal(bundled, DefaultPaths.ResolvedCliDirectory([bundled, repo, user]));

        // 配置里的目录优先
        Assert.Equal(bundled, CliRunner.ResolveCliDirectory(bundled));
        Assert.Null(CliRunner.ResolveCliDirectory(Path.Combine(root, "nope")));
    }

    [Fact]
    public void TestPythonLookupOrder()
    {
        // 显式指定：原样使用
        var resolved = CliRunner.ResolvePython("/custom/python");
        Assert.NotNull(resolved);
        Assert.Equal("/custom/python", resolved!.Value.Executable);
        Assert.Empty(resolved.Value.Prefix);
    }

    [Fact]
    public void TestWhichOnPath()
    {
        var dir = TempDir();
        var name = OperatingSystem.IsWindows() ? "kanjo-fake-python.exe" : "kanjo-fake-python";
        var file = Path.Combine(dir, name);
        File.WriteAllText(file, "");
        var old = Environment.GetEnvironmentVariable("PATH");
        try
        {
            Environment.SetEnvironmentVariable("PATH", dir);
            Assert.Equal(file, CliRunner.WhichOnPath(name));
            Assert.Null(CliRunner.WhichOnPath("definitely-not-a-real-binary-xyz"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("PATH", old);
        }
    }
}
