using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 更新状态机（<see cref="UpdateCoordinator"/>）与界面规则（横幅可见性、按钮标题、非安装版）：
/// 用假的 <see cref="IUpdateManager"/> 驱动，不联网、不碰 Velopack 的真安装目录。
/// </summary>
public sealed class UpdateCoordinatorTests : KanjoTestCase
{
    /// <summary>假管理器：检查结果 / 下载进度 / 抛什么异常都由测试决定。</summary>
    private sealed class FakeUpdateManager : IUpdateManager
    {
        public string? Available { get; set; } = "0.5.3";

        public string? Pending { get; set; }

        public Exception? ThrowOnCheck { get; set; }

        public Exception? ThrowOnDownload { get; set; }

        /// <summary>自定义检查过程（如用 TaskCompletionSource 挂起，确定性地测试并发去重）。</summary>
        public Func<Task<string?>>? Check { get; set; }

        /// <summary>下载时依次报的进度；null = 直接成功（不报进度）。</summary>
        public Action<Action<int>>? Download { get; set; }

        private int _checkCalls;
        private int _downloadCalls;
        private int _restartCalls;

        public int CheckCalls => Volatile.Read(ref _checkCalls);

        public int DownloadCalls => Volatile.Read(ref _downloadCalls);

        public int RestartCalls => Volatile.Read(ref _restartCalls);

        public string? CurrentVersion => "0.5.2";

        public string? PendingRestartVersion => Pending;

        public Task<string?> CheckForUpdateAsync()
        {
            Interlocked.Increment(ref _checkCalls);
            if (Check is { } custom) return custom();
            if (ThrowOnCheck is { } e) return Task.FromException<string?>(e);
            return Task.FromResult(Available);
        }

        public Task DownloadAsync(Action<int> progress, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _downloadCalls);
            if (ThrowOnDownload is { } e) return Task.FromException(e);
            Download?.Invoke(progress);
            return Task.CompletedTask;
        }

        public void RestartToApply()
        {
            Interlocked.Increment(ref _restartCalls);
            RestartCalled.TrySetResult(true);
        }

        public TaskCompletionSource<bool> RestartCalled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    private static UpdateCoordinator Make(IUpdateManager? manager, FakeBackgroundScheduler? timers = null) =>
        new(manager, manager?.CurrentVersion ?? "0.5.2", timers ?? new FakeBackgroundScheduler());

    /// <summary>等到状态变成期望值（事件驱动，不轮询睡眠）。</summary>
    private static async Task<UpdateStatus> WaitFor(UpdateCoordinator coordinator, UpdateState state)
    {
        var current = coordinator.Status;
        if (current.State == state) return current;

        var matched = new TaskCompletionSource<UpdateStatus>(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnChanged()
        {
            var status = coordinator.Status;
            if (status.State == state) matched.TrySetResult(status);
        }

        coordinator.Changed += OnChanged;
        try
        {
            // 订阅后再读一次，避免状态刚好在订阅之前切过去而丢掉信号。
            current = coordinator.Status;
            if (current.State == state) return current;
            return await matched.Task.WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (TimeoutException)
        {
            Assert.Fail($"state stayed {coordinator.Status.State}, wanted {state}");
            return coordinator.Status;
        }
        finally
        {
            coordinator.Changed -= OnChanged;
        }
    }

    [Fact]
    public async Task TestCheckUpToDateGoesFromCheckingToUpToDate()
    {
        var manager = new FakeUpdateManager { Available = null };
        using var coordinator = Make(manager);

        Assert.Equal(UpdateState.Idle, coordinator.Status.State);
        Assert.Equal("0.5.2", coordinator.Status.CurrentVersion);

        var status = await RunToEnd(coordinator, UpdateState.UpToDate);
        Assert.Equal(UpdateState.UpToDate, status.State);
        Assert.Null(status.Version);
        Assert.NotNull(status.LastCheckedAt);
        Assert.Equal(1, manager.CheckCalls);
        Assert.Equal(0, manager.DownloadCalls);
        Assert.False(coordinator.HasReadyUpdate);
    }

    [Fact]
    public async Task TestAvailableUpdateDownloadsAndBecomesReady()
    {
        var manager = new FakeUpdateManager { Available = "0.5.3" };
        var seen = new List<UpdateStatus>();
        using var coordinator = Make(manager);
        coordinator.Changed += () =>
        {
            lock (seen) seen.Add(coordinator.Status);
        };

        var status = await RunToEnd(coordinator);

        Assert.Equal(UpdateState.Ready, status.State);
        Assert.Equal("0.5.3", status.Version);
        Assert.Equal(100, status.Progress);
        Assert.Equal(1, manager.DownloadCalls);
        Assert.True(coordinator.HasReadyUpdate);

        // 状态是按顺序走过来的：Checking → Downloading → Ready（界面据此画进度、再换成按钮）。
        List<UpdateStatus> snapshot;
        lock (seen) snapshot = [.. seen];
        Assert.Contains(snapshot, s => s.State == UpdateState.Checking);
        Assert.Contains(snapshot, s => s.State == UpdateState.Downloading);
        Assert.Equal(UpdateState.Ready, snapshot[^1].State);
    }

    [Fact]
    public async Task TestDownloadProgressIsReportedToTheUi()
    {
        var manager = new FakeUpdateManager
        {
            Download = progress =>
            {
                progress(10);
                progress(42);
                progress(100);
            },
        };
        var progressSeen = new List<int>();
        using var coordinator = Make(manager);
        coordinator.Changed += () =>
        {
            var current = coordinator.Status;
            if (current.State == UpdateState.Downloading)
            {
                lock (progressSeen) progressSeen.Add(current.Progress);
            }
        };

        var status = await RunToEnd(coordinator);

        Assert.Equal(UpdateState.Ready, status.State);
        List<int> snapshot;
        lock (progressSeen) snapshot = [.. progressSeen];
        Assert.Contains(42, snapshot);
        Assert.Contains(snapshot, p => p is > 0 and < 100);
    }

    [Fact]
    public async Task TestCheckFailureIsShortAndRetryable()
    {
        var manager = new FakeUpdateManager
        {
            ThrowOnCheck = new InvalidOperationException(
                "System.Net.Http.HttpRequestException: No such host is known.\n  at Velopack.Sources.GithubSource..."),
        };
        using var coordinator = Make(manager);

        var status = await RunToEnd(coordinator, UpdateState.Failed);

        Assert.Equal(UpdateState.Failed, status.State);
        Assert.NotNull(status.Error);
        // 一句短消息（换行压平、长度受限），界面上不会撑爆卡片。
        Assert.DoesNotContain('\n', status.Error!);
        Assert.True(status.Error!.Length <= 120, status.Error);
        Assert.True(UpdateStatusText.ButtonEnabled(status));
        Assert.Equal("Check for updates", UpdateStatusText.Button(status));

        // 再点一次照样能检查（失败不是死状态）。
        manager.ThrowOnCheck = null;
        manager.Available = null;
        var retried = await RunToEnd(coordinator, UpdateState.UpToDate);
        Assert.Equal(UpdateState.UpToDate, retried.State);
        Assert.Equal(2, manager.CheckCalls);
    }

    [Fact]
    public async Task TestDownloadFailureIsFailedNotReady()
    {
        var manager = new FakeUpdateManager { ThrowOnDownload = new IOException("The response ended prematurely.") };
        using var coordinator = Make(manager);

        var status = await RunToEnd(coordinator, UpdateState.Failed);

        Assert.Equal(UpdateState.Failed, status.State);
        Assert.False(coordinator.HasReadyUpdate);
        Assert.Equal(0, manager.RestartCalls);
    }

    /// <summary>并发点两次（定时器 + 用户按钮）只会跑一次，两个 Task 是同一个。</summary>
    [Fact]
    public async Task TestConcurrentChecksDoNotOverlap()
    {
        var started = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var gate = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var manager = new FakeUpdateManager
        {
            Check = () =>
            {
                started.TrySetResult(true);
                return gate.Task;
            },
        };
        using var coordinator = Make(manager);

        var a = coordinator.CheckNowAsync();
        await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var b = coordinator.CheckNowAsync();

        Assert.Same(a, b);
        gate.SetResult(null);
        await Task.WhenAll(a, b);
        Assert.Equal(UpdateState.UpToDate, coordinator.Status.State);
        Assert.Equal(1, manager.CheckCalls);
    }

    [Fact]
    public async Task TestRestartToUpdateCallsTheManager()
    {
        var manager = new FakeUpdateManager { Available = "0.5.3" };
        using var coordinator = Make(manager);
        await RunToEnd(coordinator);

        coordinator.RestartToUpdate();
        await manager.RestartCalled.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(1, manager.RestartCalls);
    }

    /// <summary>上次已经下载好、但用户没重启：直接进 Ready，面板上立刻能点「Restart to update」。</summary>
    [Fact]
    public void TestPendingRestartStartsInReady()
    {
        var manager = new FakeUpdateManager { Pending = "0.5.4" };
        using var coordinator = Make(manager);

        Assert.Equal(UpdateState.Ready, coordinator.Status.State);
        Assert.Equal("0.5.4", coordinator.Status.Version);
        Assert.True(coordinator.HasReadyUpdate);
    }

    /// <summary>不是 Velopack 装的（开发运行 / 便携版 / --snapshot）：不检查、不下载，按钮禁用。</summary>
    [Fact]
    public void TestNotInstalledNeverChecks()
    {
        var timers = new FakeBackgroundScheduler();
        using var coordinator = Make(null, timers);

        var status = coordinator.Status;
        Assert.Equal(UpdateState.NotInstalled, status.State);
        Assert.Equal("0.5.2", status.CurrentVersion);
        Assert.False(status.CanCheck);
        Assert.False(UpdateStatusText.ButtonEnabled(status));
        Assert.Equal("Updates are only available in the installed version",
            UpdateStatusText.Description(status, "en"));

        // 定时器 / 按钮都不该真的跑起来。
        coordinator.Start();
        Assert.Empty(timers.Entries);
        Assert.True(coordinator.CheckNowAsync().IsCompleted);
        Assert.False(coordinator.HasReadyUpdate);
    }

    /// <summary>启动 30 秒后检查一次，之后每 6 小时（和原来的后台策略一致）。</summary>
    [Fact]
    public async Task TestStartKeepsTheScheduledBackgroundCheck()
    {
        var timers = new FakeBackgroundScheduler();
        var manager = new FakeUpdateManager { Available = null };
        using var coordinator = Make(manager, timers);

        var completions = 0;
        var secondDone = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        coordinator.Changed += () =>
        {
            if (coordinator.Status.State == UpdateState.UpToDate && Interlocked.Increment(ref completions) >= 2)
            {
                secondDone.TrySetResult(true);
            }
        };

        coordinator.Start();
        var first = Assert.Single(timers.Entries);
        Assert.False(first.IsPeriodic);
        Assert.Equal(UpdatePolicy.InitialDelay, first.Delay);

        first.Fire();
        await WaitFor(coordinator, UpdateState.UpToDate);

        var periodic = timers.Periodic;
        Assert.NotNull(periodic);
        Assert.Equal(UpdatePolicy.Interval, periodic!.Interval);

        periodic.Fire();
        await secondDone.Task.WaitAsync(TimeSpan.FromSeconds(10));
        Assert.Equal(2, manager.CheckCalls);
    }

    /// <summary>上一次刚到终态（在 Changed 通知里立刻再触发检查）必须真正跑第二次，不被旧 Task 吃掉。</summary>
    [Fact]
    public async Task TestCheckTriggeredFromCompletionCallbackRunsAgain()
    {
        var manager = new FakeUpdateManager { Available = null };
        using var coordinator = Make(manager);

        Task? second = null;
        var retriggered = 0;
        coordinator.Changed += () =>
        {
            if (coordinator.Status.State == UpdateState.UpToDate && Interlocked.Exchange(ref retriggered, 1) == 0)
            {
                second = coordinator.CheckNowAsync();
            }
        };

        var first = coordinator.CheckNowAsync();
        await first;
        Assert.NotNull(second);
        Assert.NotSame(first, second);
        await second!;
        Assert.Equal(2, manager.CheckCalls);
    }

    /// <summary>跑一次检查到状态稳定（Ready / UpToDate / Failed），返回最终状态。</summary>
    private static async Task<UpdateStatus> RunToEnd(UpdateCoordinator coordinator,
        UpdateState expected = UpdateState.Ready)
    {
        await coordinator.CheckNowAsync();
        return await WaitFor(coordinator, expected);
    }
}
