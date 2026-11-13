namespace Kanjo.Core;

/// <summary>
/// 自动更新在界面上的状态。真正的网络动作在 <c>Kanjo.App.UpdateService</c>（Velopack），
/// 这里只描述「现在是什么情况」，界面据此显示横幅 / 设置卡片里的按钮。
/// </summary>
public enum UpdateState
{
    /// <summary>还没检查过（刚启动，或者用户从没点过「Check for updates」）。</summary>
    Idle,

    /// <summary>正在问更新源有没有新版本。</summary>
    Checking,

    /// <summary>问过了，已经是最新版本。</summary>
    UpToDate,

    /// <summary>发现新版本，正在后台下载（<see cref="UpdateStatus.ProgressPercent"/> 是 0–100）。</summary>
    Downloading,

    /// <summary>新版本已经下载完成，等用户点「Restart to update」（<see cref="UpdateStatus.Version"/> 是它）。</summary>
    Ready,

    /// <summary>检查 / 下载失败（<see cref="UpdateStatus.Error"/> 是一句短消息，可重试）。</summary>
    Failed,

    /// <summary>
    /// 不是 Velopack 装的（开发运行、解压出来的文件夹、便携版）：没有可应用的安装目录，
    /// 所以不检查也不下载，界面上只显示版本号和一句说明。
    /// </summary>
    NotInstalled,
}

/// <summary>
/// 一次更新状态快照（不可变）。界面只读这个，不碰 Velopack。
/// <see cref="Version"/> 是**新版本号**（发现 / 下载 / 已下载时才有），
/// 本进程的版本号在 <see cref="CurrentVersion"/>。
/// </summary>
public sealed record UpdateStatus(
    UpdateState State,
    string? Version = null,
    int ProgressPercent = 0,
    string? Error = null,
    DateTimeOffset? LastCheckedAt = null)
{
    /// <summary>本进程的版本号（`0.5.2`）：非安装版也能显示。</summary>
    public string CurrentVersion { get; init; } = "";

    /// <summary>没得检查（非安装版）：只带版本号。</summary>
    public static UpdateStatus NotInstalled(string version) =>
        new(UpdateState.NotInstalled, version) { CurrentVersion = version };

    /// <summary>能不能主动检查更新（只有非安装版不能）。</summary>
    public bool CanCheck => State != UpdateState.NotInstalled;

    /// <summary>正在检查 / 下载（按钮应该是禁用态）。</summary>
    public bool IsBusy => State is UpdateState.Checking or UpdateState.Downloading;

    /// <summary>进度（夹在 0–100，界面上直接画进度条）。</summary>
    public int Progress => Math.Clamp(ProgressPercent, 0, 100);
}

/// <summary>
/// Velopack 的 <c>UpdateManager</c> 的窄接口：状态机（<c>Kanjo.App.UpdateService</c>）只依赖这几件事。
/// 单测用假实现，不联网、不碰真实安装目录；真正跑 Velopack 的实现在
/// <c>Kanjo.App.VelopackUpdateManager</c>。
/// </summary>
public interface IUpdateManager
{
    /// <summary>当前安装的版本（没有版本信息时 null）。</summary>
    string? CurrentVersion { get; }

    /// <summary>已经下载好、等下次启动（或用户点重启）的版本；没有则为 null。</summary>
    string? PendingRestartVersion { get; }

    /// <summary>问更新源：有新版本返回它的版本号，已是最新返回 null。</summary>
    Task<string?> CheckForUpdateAsync();

    /// <summary>下载 <see cref="CheckForUpdateAsync"/> 刚发现的那个版本；percent 是 0–100。</summary>
    Task DownloadAsync(Action<int> progress, CancellationToken cancellationToken);

    /// <summary>装上已下载的版本并重启（进程在这里退出）。</summary>
    void RestartToApply();
}

/// <summary>
/// 面板顶部更新横幅的显示规则（纯逻辑，方便测试）：
/// 只有「已下载、等重启」和「正在下载」两种状态出现在面板里，别的时候都不打扰用户。
/// 关掉（✕）按版本号记：同一进程里不会再冒出来；
/// 下次启动（状态重新从 Idle 开始）如果更新还在，横幅照常出现。
/// </summary>
public static class UpdateBanner
{
    public static bool ShouldShow(UpdateStatus? status, string? dismissedVersion)
    {
        if (status is null) return false;
        if (status.State is not (UpdateState.Ready or UpdateState.Downloading)) return false;
        if (status.Version is not { Length: > 0 } version) return false;
        return !string.Equals(version, dismissedVersion, StringComparison.Ordinal);
    }

    /// <summary>标题（只有「已下载」有：`Kanjo 0.5.3 is ready`）。</summary>
    public static string? Title(UpdateStatus status, string? language = null) =>
        status.State == UpdateState.Ready && status.Version is { Length: > 0 } version
            ? WindowsL10n.TrL(language, "update.ready", version)
            : null;

    /// <summary>正文（下载中：`Downloading Kanjo 0.5.3… 42%`）；已下载时为 null（按钮自己说明）。</summary>
    public static string? Message(UpdateStatus status, string? language = null) =>
        status.State == UpdateState.Downloading && status.Version is { Length: > 0 } version
            ? WindowsL10n.TrL(language, "update.downloading", version, status.Progress)
            : null;

    /// <summary>下载中才画进度条。</summary>
    public static bool ShowsProgress(UpdateStatus status) =>
        status.State == UpdateState.Downloading && status.Version is { Length: > 0 };
}

/// <summary>
/// 设置页「Updates」卡片里的文字：状态说明、按钮标题、按钮能不能点。
/// 和横幅共用同一批 <see cref="WindowsL10n"/> 文案，所以三种语言只有一份翻译。
/// </summary>
public static class UpdateStatusText
{
    /// <summary>按钮标题（按状态变）。</summary>
    public static string Button(UpdateStatus status, string? language = null) => status.State switch
    {
        UpdateState.Ready => WindowsL10n.TrL(language, "update.restart_to_install"),
        UpdateState.Checking => WindowsL10n.TrL(language, "update.checking"),
        UpdateState.Downloading => WindowsL10n.TrL(language, "update.downloading_button"),
        _ => WindowsL10n.TrL(language, "update.check"),
    };

    /// <summary>按钮能不能点：检查中 / 下载中 / 非安装版都是禁用态。</summary>
    public static bool ButtonEnabled(UpdateStatus status) => status.CanCheck && !status.IsBusy;

    /// <summary>「已下载、可以重启」时按钮是主按钮（强调色），其它状态是标准按钮。</summary>
    public static bool ButtonIsPrimary(UpdateStatus status) => status.State == UpdateState.Ready;

    /// <summary>标题下面那一行状态说明。</summary>
    public static string Description(UpdateStatus status, string? language = null) => status.State switch
    {
        UpdateState.Checking => WindowsL10n.TrL(language, "update.checking"),
        UpdateState.UpToDate => WindowsL10n.TrL(language, "update.up_to_date"),
        UpdateState.Downloading => UpdateBanner.Message(status, language)
                                   ?? WindowsL10n.TrL(language, "update.checking"),
        UpdateState.Ready => UpdateBanner.Title(status, language)
                             ?? WindowsL10n.TrL(language, "update.ready_hint"),
        UpdateState.Failed => WindowsL10n.TrL(language, "update.failed"),
        UpdateState.NotInstalled => WindowsL10n.TrL(language, "update.not_installed"),
        _ => WindowsL10n.TrL(language, "update.idle"),
    };

    /// <summary>卡片里的第二行：上次检查时间 / 失败原因；没有可说的就不返回内容（调用方跳过这一行）。</summary>
    public static string Detail(UpdateStatus status, string? language = null)
    {
        // 非安装版的那句说明已经在第一行了，不重复。
        if (status.State == UpdateState.NotInstalled) return "";
        if (status.State == UpdateState.Failed && status.Error is { Length: > 0 } error)
        {
            return Shorten(error);
        }
        // 已下载：说明重启之后会发生什么（比「上次检查时间」更有用）。
        if (status.State == UpdateState.Ready) return WindowsL10n.TrL(language, "update.ready_hint");
        if (status.LastCheckedAt is { } at)
        {
            return WindowsL10n.TrL(language, "update.last_checked",
                at.ToLocalTime().ToString("HH:mm", System.Globalization.CultureInfo.InvariantCulture));
        }
        return status.State == UpdateState.Idle ? WindowsL10n.TrL(language, "update.never_checked") : "";
    }

    /// <summary>错误消息可能是一整段异常文本，界面上只留一句短的。</summary>
    public static string Shorten(string text)
    {
        var oneLine = text.Replace('\r', ' ').Replace('\n', ' ').Trim();
        while (oneLine.Contains("  ", StringComparison.Ordinal)) oneLine = oneLine.Replace("  ", " ");
        return oneLine.Length <= 120 ? oneLine : oneLine[..117] + "…";
    }

    /// <summary>下一个补丁版本（截图里的假更新用：0.5.2 → 0.5.3）。</summary>
    public static string NextPatch(string version)
    {
        var parts = version.Split('.');
        if (parts.Length >= 3 && int.TryParse(parts[2], out var patch)
            && int.TryParse(parts[0], out var major) && int.TryParse(parts[1], out var minor))
        {
            return $"{major}.{minor}.{patch + 1}";
        }
        return version;
    }
}

/// <summary>
/// `--snapshot-update ready|downloading|not-installed|idle`：截图时注入一个假的更新状态
/// （只有 `--snapshot` 模式下才生效，正常运行时更新状态一律来自 Velopack）。
/// 截图的「现在」必须是可复现的，所以假状态不带上次检查时间。
/// </summary>
public static class UpdateSnapshots
{
    public static readonly IReadOnlyList<string> KnownStates =
        ["idle", "up-to-date", "downloading", "ready", "not-installed"];

    /// <summary>解析成假状态；null / 无法识别时返回 null（调用方按默认处理）。</summary>
    public static UpdateStatus? Parse(string? raw, string currentVersion)
    {
        if (raw is null) return null;
        var next = UpdateStatusText.NextPatch(currentVersion);
        return raw switch
        {
            "idle" => new UpdateStatus(UpdateState.Idle) { CurrentVersion = currentVersion },
            "up-to-date" => new UpdateStatus(UpdateState.UpToDate) { CurrentVersion = currentVersion },
            "downloading" => new UpdateStatus(UpdateState.Downloading, next, 42) { CurrentVersion = currentVersion },
            "ready" => new UpdateStatus(UpdateState.Ready, next) { CurrentVersion = currentVersion },
            "not-installed" => UpdateStatus.NotInstalled(currentVersion),
            _ => null,
        };
    }

    /// <summary>截图默认注入的状态：装好的、刚启动还没检查过（不画横幅，卡片显示「Not checked yet」）。</summary>
    public static UpdateStatus Default(string currentVersion) =>
        Parse("idle", currentVersion)!;
}
