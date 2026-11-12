namespace Kanjo.Core;

/// <summary>
/// Windows 上各目录的唯一事实来源：安装根目录、设置目录、CLI 数据 / 缓存目录。
///
/// **安装根目录必须和任何数据目录不同。** Windows 路径不区分大小写，所以
/// <c>%LOCALAPPDATA%\Kanjo</c>（Velopack 的安装根）和 <c>%LOCALAPPDATA%\kanjo</c>
/// （CLI 的数据 / 缓存目录，批次 4 起就在这里）其实是**同一个文件夹**：
/// 先用过 CLI / 家庭上报的机器上 Setup.exe 会因为「已安装」而失败，而且卸载会连账本一起删掉。
/// 因此包的 id 是 <see cref="InstallRootName"/>（`KanjoApp`，产品名仍然是 Kanjo），
/// 数据目录则保持原样，老用户的数据不受影响。
/// </summary>
public static class AppPaths
{
    /// <summary>Velopack 的 packId，也是安装根目录名：`%LOCALAPPDATA%\KanjoApp`。</summary>
    public const string InstallRootName = "KanjoApp";

    /// <summary>产品名（开始菜单快捷方式、应用列表、窗口标题）。</summary>
    public const string ProductName = "Kanjo";

    /// <summary>App 设置的目录名：`%APPDATA%\Kanjo`。</summary>
    public const string SettingsDirectoryName = "Kanjo";

    /// <summary>CLI 自己的目录名（配置 / 数据 / 缓存）：`%APPDATA%\kanjo`、`%LOCALAPPDATA%\kanjo`。</summary>
    public const string CliDirectoryName = "kanjo";

    /// <summary>家庭上报 PowerShell 脚本的安装目录名：`%LOCALAPPDATA%\KanjoFamily`。</summary>
    public const string FamilyInstallDirectoryName = "KanjoFamily";

    /// <summary>安装根目录（`%LOCALAPPDATA%\KanjoApp`）。</summary>
    public static string InstallRoot => Path.Combine(LocalAppData(), InstallRootName);

    /// <summary>
    /// 所有会被写入数据的目录（相对 <c>%LOCALAPPDATA%</c> 或 <c>%APPDATA%</c> 的子路径）。
    /// App、CLI、家庭上报脚本各一份；安装根目录不能和其中任何一个相同。
    /// </summary>
    public static IReadOnlyList<(string Root, string Relative)> DataDirectories() =>
    [
        // App：设置（Roaming）+ 磁盘报告缓存（Local，和 CLI 的目录是同一个，只能读不能占）
        ("APPDATA", SettingsDirectoryName),
        ("LOCALAPPDATA", SettingsDirectoryName),
        // CLI：配置（Roaming）+ 账本 / 缓存（Local）
        ("APPDATA", CliDirectoryName),
        ("LOCALAPPDATA", Path.Combine(CliDirectoryName, "data")),
        ("LOCALAPPDATA", Path.Combine(CliDirectoryName, "cache")),
        // 家庭上报脚本（和 App 共用同一份 CLI 与凭据）
        ("LOCALAPPDATA", FamilyInstallDirectoryName),
    ];

    /// <summary>环境变量里的 <c>%LOCALAPPDATA%</c>（非 Windows 下退回用户目录，便于在 Mac 上跑测试）。</summary>
    public static string LocalAppData() => Root("LOCALAPPDATA", "AppData", "Local");

    /// <summary>环境变量里的 <c>%APPDATA%</c>。</summary>
    public static string AppData() => Root("APPDATA", "AppData", "Roaming");

    private static string Root(string variable, params string[] fallback)
    {
        var value = Environment.GetEnvironmentVariable(variable);
        if (!string.IsNullOrEmpty(value)) return value;
        var parts = new List<string> { Environment.GetFolderPath(Environment.SpecialFolder.UserProfile) };
        parts.AddRange(fallback);
        return Path.Combine([.. parts]);
    }

    /// <summary>
    /// 两个路径在 Windows 语义下是不是同一个目录（不区分大小写、忽略末尾分隔符）。
    /// 在 macOS / Linux 上也按不区分大小写比较：要保证的正是「Windows 上不撞车」。
    /// </summary>
    public static bool SameDirectory(string? a, string? b)
    {
        if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b)) return false;
        return string.Equals(Normalize(a), Normalize(b), StringComparison.OrdinalIgnoreCase);
    }

    private static string Normalize(string path)
    {
        var full = path.Replace('\\', '/');
        while (full.Length > 1 && full.EndsWith('/')) full = full[..^1];
        return full;
    }
}
