namespace Kanjo.Core;

using System.Runtime.InteropServices;

/// <summary>
/// 自动更新策略（纯逻辑）：什么时候检查、什么时候允许 Velopack 在启动时应用更新。
/// 真正的网络 / 文件操作在 <c>Kanjo.App.UpdateService</c>（Velopack），这里只做判断，方便测试。
/// </summary>
public static class UpdatePolicy
{
    /// <summary>发布仓库（Velopack 的 GitHub 更新源）。</summary>
    public const string RepositoryUrl = "https://github.com/mammut001/kanjo";

    /// <summary>启动后多久做第一次检查（别和首帧 / 第一次刷新抢 CPU 和网络）。</summary>
    public static readonly TimeSpan InitialDelay = TimeSpan.FromSeconds(30);

    /// <summary>之后每隔多久检查一次。</summary>
    public static readonly TimeSpan Interval = TimeSpan.FromHours(6);

    /// <summary>
    /// 这些模式不碰更新：`--snapshot` 是离屏截图（进程马上退出，更新器会把 exe 换掉），
    /// `--window` 是开发预览，`--print-source` 是诊断（同样立刻退出）。
    /// </summary>
    public static bool IsDisabledMode(IReadOnlyList<string> args) =>
        args.Any(a => a is "--snapshot" or "--window" or "--print-source") ||
        args.Any(a => a.StartsWith("--snapshot=", StringComparison.Ordinal) ||
                      a.StartsWith("--print-source=", StringComparison.Ordinal));

    /// <summary>
    /// 是否应该检查 / 下载更新：必须是 Velopack 装的（否则没有可应用的目录）、不是 Debug 构建、
    /// 不在截图 / 预览模式。
    /// </summary>
    public static bool ShouldRun(IReadOnlyList<string> args, bool isDebugBuild, bool isInstalled) =>
        isInstalled && !isDebugBuild && !IsDisabledMode(args);

    /// <summary>
    /// Velopack 是否可以在启动时自动应用已下载的更新（用户「下次启动时装上」的路径）。
    /// Debug、截图、预览模式都不允许：那些进程不该被更新器接管 / 替换。
    /// </summary>
    public static bool ShouldAutoApplyOnStartup(IReadOnlyList<string> args, bool isDebugBuild) =>
        !isDebugBuild && !IsDisabledMode(args);

    /// <summary>
    /// 更新通道 = 打包时的 <c>--channel</c>，也等于 RID：x64 与 arm64 的更新包分开，互不覆盖。
    /// 用**进程**架构（不是 OS 架构）：Windows 11 on ARM 上跑的 x64 版继续走 win-x64 通道。
    /// </summary>
    public static string ChannelForArchitecture(Architecture architecture) => architecture switch
    {
        Architecture.Arm64 => "win-arm64",
        Architecture.X64 => "win-x64",
        _ => "win-" + architecture.ToString().ToLowerInvariant(),
    };

    /// <summary>当前进程的更新通道。</summary>
    public static string CurrentChannel =>
        ChannelForArchitecture(RuntimeInformation.ProcessArchitecture);
}
