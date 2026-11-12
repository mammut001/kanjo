using Microsoft.Win32;

namespace Kanjo.Core;

/// <summary>
/// 开机自启（<c>HKCU\Software\Microsoft\Windows\CurrentVersion\Run</c>）。
///
/// Mac 版没有开机自启（`ui/` 里没有 `SMAppService` / Login Item 注册，设置里也没有这一项），
/// 所以 Windows 版**默认也不写这个键**——只有用户自己在「任务管理器 → 启动」里打开才生效。
/// 这里只提供读 / 删两个操作：卸载钩子用它把可能存在的旧值清掉，绝不留下指向已删除目录的
/// `Run` 项（那会让登录时报错）。
/// </summary>
public static class WindowsStartup
{
    /// <summary>值和键名都用 Kanjo（和安装包的产品名一致）。</summary>
    public const string ValueName = "Kanjo";

    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";

    /// <summary>当前是否注册了开机自启（测试 / 文档用）。</summary>
    public static bool IsRegistered()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: false);
            return key?.GetValue(ValueName) is string { Length: > 0 };
        }
        catch (Exception)
        {
            // 组策略可能禁止读这个键：当作没有。
            return false;
        }
    }

    /// <summary>
    /// 删掉 <c>Run\Kanjo</c>（没有就什么都不做）。Velopack 的卸载钩子会调用它；
    /// 用户数据目录不在这里处理，卸载时原样保留。
    /// </summary>
    public static bool RemoveRunEntry()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true);
            if (key is null) return false;
            if (key.GetValue(ValueName) is null) return false;
            key.DeleteValue(ValueName, throwOnMissingValue: false);
            return true;
        }
        catch (Exception)
        {
            // 删不掉也不该让卸载失败。
            return false;
        }
    }
}
