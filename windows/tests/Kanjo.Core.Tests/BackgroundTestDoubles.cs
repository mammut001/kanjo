using Kanjo.Core;

namespace Kanjo.Core.Tests;

/// <summary>假后台计时器：记录安排了什么，由测试手动触发。绝不使用真实时钟。</summary>
public sealed class FakeBackgroundScheduler : IBackgroundScheduler
{
    public sealed class Entry : IBackgroundTimer
    {
        public Entry(TimeSpan delay, Action callback, bool periodic)
        {
            Delay = delay;
            Interval = delay;
            Callback = callback;
            IsPeriodic = periodic;
        }

        public TimeSpan Delay { get; }

        public TimeSpan Interval { get; }

        public Action Callback { get; }

        public bool IsPeriodic { get; }

        public bool IsActive { get; private set; } = true;

        public bool WasCancelled { get; private set; }

        public int FireCount { get; private set; }

        public bool IsPending => !WasCancelled && (IsPeriodic || FireCount == 0);

        /// <summary>触发一次（一次性计时器触发后自动失效）。</summary>
        public void Fire()
        {
            if (WasCancelled) return;
            FireCount++;
            if (!IsPeriodic) IsActive = false;
            Callback();
        }

        public void Dispose()
        {
            if (!IsActive) return;
            IsActive = false;
            WasCancelled = true;
        }
    }

    private readonly List<Entry> _entries = [];

    public IReadOnlyList<Entry> Entries
    {
        get { lock (_entries) return [.. _entries]; }
    }

    public Entry? LastPending
    {
        get { lock (_entries) return _entries.LastOrDefault(e => e.IsPending); }
    }

    public Entry? Periodic => Entries.LastOrDefault(e => e.IsPeriodic && e.IsActive);

    public IBackgroundTimer ScheduleOnce(TimeSpan delay, Action callback)
    {
        var entry = new Entry(delay, callback, periodic: false);
        lock (_entries) _entries.Add(entry);
        return entry;
    }

    public IBackgroundTimer SchedulePeriodic(TimeSpan interval, Action callback)
    {
        var entry = new Entry(interval, callback, periodic: true);
        lock (_entries) _entries.Add(entry);
        return entry;
    }
}

/// <summary>假日志监听器：手动注入一个「文件变了」事件。</summary>
public sealed class FakeLogWatcherFactory : ILogWatcherFactory
{
    public sealed class Watcher : ILogWatcher
    {
        public Watcher(IReadOnlyList<string> paths, Action onEvent)
        {
            Paths = paths;
            OnEvent = onEvent;
        }

        public IReadOnlyList<string> Paths { get; }

        public Action OnEvent { get; }

        public bool IsActive { get; private set; } = true;

        public void Dispose() => IsActive = false;
    }

    private readonly List<Watcher> _watchers = [];

    /// <summary>下一次 Start 要过滤掉的目录（模拟「目录还不存在」）。</summary>
    public HashSet<string> Missing { get; } = new(StringComparer.OrdinalIgnoreCase);

    public IReadOnlyList<Watcher> Created
    {
        get { lock (_watchers) return [.. _watchers]; }
    }

    public Watcher? Current
    {
        get { lock (_watchers) return _watchers.LastOrDefault(w => w.IsActive); }
    }

    public ILogWatcher? Start(IReadOnlyList<string> paths, Action onEvent)
    {
        var existing = paths.Where(p => !Missing.Contains(p)).ToList();
        if (existing.Count == 0) return null;
        var watcher = new Watcher(existing, onEvent);
        lock (_watchers) _watchers.Add(watcher);
        return watcher;
    }

    public void RaiseFileEvent() => Current?.OnEvent();
}

/// <summary>假电源事件源：手动触发睡眠 / 唤醒 / 节电模式。</summary>
public sealed class FakePowerMonitor : IPowerMonitor
{
    public bool IsStarted { get; private set; }

    public bool IsLowPowerMode { get; private set; }

    public event EventHandler? WillSuspend;

    public event EventHandler? DidResume;

    public event EventHandler<LowPowerModeEventArgs>? LowPowerModeChanged;

    public void Start() => IsStarted = true;

    public void RaiseSuspend() => WillSuspend?.Invoke(this, EventArgs.Empty);

    public void RaiseResume() => DidResume?.Invoke(this, EventArgs.Empty);

    public void RaiseLowPowerMode(bool enabled)
    {
        IsLowPowerMode = enabled;
        LowPowerModeChanged?.Invoke(this, new LowPowerModeEventArgs(enabled));
    }

    public void Dispose() => IsStarted = false;
}

/// <summary>假 CLI 运行器：记录发布 / 家庭上报的参数，返回预设结果。</summary>
public sealed class FakeReportRunner : IReportCommandRunner
{
    public sealed record Call(string Kind, IReadOnlyList<string> Arguments, string? Token);

    private readonly List<Call> _calls = [];

    public IReadOnlyList<Call> Calls
    {
        get { lock (_calls) return [.. _calls]; }
    }

    public CliResult PublishResult { get; set; } = new(0, "{\"status\":\"pushed\"}", "", false, "python");
    public CliResult FamilyResult { get; set; } = new(0, "{\"status\":\"sent\"}", "", false, "python");

    public Exception? ThrowOnPublish { get; set; }
    public Exception? ThrowOnFamily { get; set; }

    public CliResult RunPublishUsage(string repo, string file, string branch)
    {
        lock (_calls)
        {
            _calls.Add(new Call("publish-usage",
                CliRunner.PublishUsageArguments(repo, file, branch), null));
        }
        if (ThrowOnPublish is { } e) throw e;
        return PublishResult;
    }

    public CliResult RunFamilyReport(string url, string? memberLabel, string token)
    {
        lock (_calls)
        {
            _calls.Add(new Call("report-family",
                CliRunner.ReportFamilyArguments(url, memberLabel), token));
        }
        if (ThrowOnFamily is { } e) throw e;
        return FamilyResult;
    }
}
