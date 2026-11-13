using Kanjo.Core;
using Velopack;
using Velopack.Sources;

namespace Kanjo.App;

/// <summary>
/// <see cref="IUpdateManager"/> 的真实实现：把 Velopack 的 <see cref="UpdateManager"/> 包一层。
/// 状态机（<see cref="UpdateCoordinator"/>，在 Core 里、有单测）只认识那个窄接口，
/// 所以「检查 / 下载 / 重启装上」的编排可以完全脱离网络和真实安装目录测试。
/// </summary>
public sealed class VelopackUpdateManager : IUpdateManager
{
    private readonly UpdateManager _manager;
    private UpdateInfo? _pending;

    public VelopackUpdateManager(UpdateManager manager) => _manager = manager;

    /// <summary>按通道（win-x64 / win-arm64）从 GitHub Releases 取更新。</summary>
    public static VelopackUpdateManager Create(string? channel = null) => new(new UpdateManager(
        new GithubSource(UpdatePolicy.RepositoryUrl, null, false),
        new UpdateOptions { ExplicitChannel = channel ?? UpdatePolicy.CurrentChannel }));

    public string? CurrentVersion => _manager.CurrentVersion?.ToFullString();

    public string? PendingRestartVersion => _manager.UpdatePendingRestart?.Version?.ToFullString();

    public async Task<string?> CheckForUpdateAsync()
    {
        // 上次「检查到了但没下载完」的结果作废：一次检查只对应一次下载。
        _pending = await _manager.CheckForUpdatesAsync().ConfigureAwait(false);
        return _pending?.TargetFullRelease.Version?.ToFullString();
    }

    public Task DownloadAsync(Action<int> progress, CancellationToken cancellationToken)
    {
        var update = _pending ?? throw new InvalidOperationException("Check for updates first.");
        return _manager.DownloadUpdatesAsync(update, progress, cancellationToken);
    }

    public void RestartToApply() =>
        // 优先用这次检查到的那份；没有（进程刚起、更新是上次下载好的）就用 Velopack 记着的待装包。
        _manager.ApplyUpdatesAndRestart(_pending?.TargetFullRelease ?? _manager.UpdatePendingRestart);
}
