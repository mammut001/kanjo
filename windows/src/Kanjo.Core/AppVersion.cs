using System.Reflection;

namespace Kanjo.Core;

/// <summary>
/// 本进程的版本号（设置页「Current version」、更新横幅、截图里的假更新都用它）。
/// 来自 <see cref="AssemblyInformationalVersionAttribute"/>（csproj 从仓库根目录的 VERSION 读，三段式，
/// 不含 git 哈希），非安装版（开发运行 / 便携版）也能显示；读不到时回落到程序集版本的前三段。
/// </summary>
public static class AppVersion
{
    public static string Current { get; } = Resolve();

    private static string Resolve()
    {
        var assembly = typeof(AppVersion).Assembly;
        var informational = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (Normalize(informational) is { Length: > 0 } text) return text;
        var version = assembly.GetName().Version;
        return version is null ? "0.0.0" : $"{version.Major}.{version.Minor}.{Math.Max(version.Build, 0)}";
    }

    /// <summary>去掉 `+` 后缀（SDK 有时会附加 build metadata）和空白。</summary>
    private static string? Normalize(string? raw)
    {
        if (raw is null) return null;
        var plus = raw.IndexOf('+');
        var text = (plus >= 0 ? raw[..plus] : raw).Trim();
        return text.Length == 0 ? null : text;
    }
}
