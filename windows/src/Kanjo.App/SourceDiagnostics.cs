using System.Text;
using Kanjo.Core;

namespace Kanjo.App;

/// <summary>
/// `--print-source`：打印这个进程实际会用的 python、CLI 目录和数据源，然后退出 0。
///
/// 用途是安装后的冒烟测试（`windows/scripts/smoke.ps1`）能断言「用的是包里的 python 和 cli」，
/// 而不是 `py -3` / PATH 上的 Python，也不是示例数据。输出是 `key=value` 一行一条，
/// 不本地化、不带颜色，方便脚本解析。
///
/// 只读：不跑 CLI，也不写任何设置（<see cref="AppSettings"/> 只在显式 Set 时落盘）。
/// </summary>
public static class SourceDiagnostics
{
    public static int Print(TextWriter output, IReadOnlyList<string> args)
    {
        var settings = AppSettings.ForLaunch(args, AppSettings.ReadEnvironment());
        var storedKind = settings.GetString(SettingsKeys.SourceKind);
        var kind = SourceResolution.Resolve(storedKind);

        var python = CliRunner.ResolvePython();
        var cliDirectory = CliRunner.ResolveCliDirectory();
        var configuredWorkingDirectory = settings.Str(SettingsKeys.CliWorkingDirectory, "").Trim();
        var configuredCommand = settings.Str(SettingsKeys.CliCommand, "").Trim();

        var text = new StringBuilder();
        void Line(string key, string? value) => text.Append(key).Append('=').Append(value ?? "").Append('\n');

        Line("appDir", DefaultPaths.AppDirectory);
        Line("installRoot", AppPaths.InstallRoot);
        Line("settingsFile", settings.FilePath ?? "");
        Line("source", kind == SourceKind.Cli ? "cli" : "file");
        Line("sourceStored", storedKind ?? "");
        Line("sampleData", SourceResolution.UsesSampleData(storedKind, settings.GetString(SettingsKeys.FilePath))
            ? "true"
            : "false");
        Line("python", python?.Executable ?? "");
        Line("pythonArgs", python is null ? "" : string.Join(' ', python.Value.Prefix));
        Line("bundledPython", DefaultPaths.BundledPython ?? "");
        Line("cliDir", cliDirectory ?? "");
        Line("bundledCli", DefaultPaths.BundledCliDirectory ?? "");
        Line("cliVersion", cliDirectory is null ? "" : CliVersion(cliDirectory));
        Line("workingDirectorySetting", configuredWorkingDirectory);
        Line("commandSetting", configuredCommand);
        Line("defaultCommand", DefaultPaths.DefaultCliCommand);
        Line("file", kind == SourceKind.File
            ? SourceResolution.FileFor(settings.GetString(SettingsKeys.FilePath))
            : "");

        // `--print-source=<file>` 直接写文件：Windows 上 Kanjo.exe 是 GUI 程序（WinExe），
        // 双击 / 非重定向启动时没有控制台，stdout 会被丢掉。冒烟测试用这个形式最稳。
        var target = args.FirstOrDefault(a => a.StartsWith("--print-source=", StringComparison.Ordinal));
        if (target is not null)
        {
            var path = target["--print-source=".Length..].Trim().Trim('"');
            if (path.Length > 0)
            {
                var dir = Path.GetDirectoryName(Path.GetFullPath(path));
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(path, text.ToString(), new UTF8Encoding(false));
                return 0;
            }
        }

        output.Write(text.ToString());
        output.Flush();
        return 0;
    }

    /// <summary>内置 CLI 的版本（cli\VERSION，和设置页显示的一致）。</summary>
    private static string CliVersion(string cliDirectory)
    {
        try
        {
            var file = Path.Combine(cliDirectory, "VERSION");
            if (File.Exists(file))
            {
                var text = File.ReadAllText(file).Trim();
                if (text.Length > 0) return text;
            }
        }
        catch (Exception)
        {
            // 读不到就退回 __version__。
        }
        try
        {
            var init = Path.Combine(cliDirectory, "kanjo", "__init__.py");
            if (!File.Exists(init)) return "";
            var match = System.Text.RegularExpressions.Regex.Match(
                File.ReadAllText(init), "__version__\\s*=\\s*\"([^\"]+)\"");
            return match.Success ? match.Groups[1].Value : "";
        }
        catch (Exception)
        {
            return "";
        }
    }
}
