namespace Kanjo.Core;

/// <summary>
/// 磁盘报告的独立预取：同一时刻只跑一个扫描，扫描中来的请求排队（强制扫描优先），
/// 和 Mac 版 <c>DiskStore</c> 的行为一致。线程安全；UI 只读属性 + 订阅 <see cref="Changed"/>。
/// </summary>
public sealed class DiskStore
{
    private readonly object _lock = new();
    private readonly Func<bool, (IDiskSource Source, string Description)> _makeSource;
    private readonly DiskReportCache? _cache;

    private DiskReportState _state;
    private string? _error;
    private DateTimeOffset? _lastRefresh;
    private string _sourceDescription = "";
    private IDiskSource? _source;
    private int _generation;
    private bool _running;
    private bool _pending;
    private bool _pendingRescan;

    /// <summary>状态变化（开始 / 结束刷新、错误）。可能在后台线程触发。</summary>
    public event Action? Changed;

    public DiskStore(
        Func<bool, (IDiskSource Source, string Description)> makeSource,
        DiskReportCache? cache = null,
        DiskReport? initial = null)
    {
        _makeSource = makeSource;
        _cache = cache;
        _state = new DiskReportState(initial ?? cache?.Load());
    }

    public DiskReport? Report
    {
        get { lock (_lock) return _state.Report; }
    }

    public bool HasReport => Report is not null;

    public bool IsLoading
    {
        get { lock (_lock) return _state.IsLoading; }
    }

    public bool IsRescanning
    {
        get { lock (_lock) return _state.IsRescanning; }
    }

    public string? Error
    {
        get { lock (_lock) return _error; }
    }

    public DateTimeOffset? LastRefresh
    {
        get { lock (_lock) return _lastRefresh; }
    }

    public string SourceDescription
    {
        get { lock (_lock) return _sourceDescription; }
    }

    public bool IsStale(TimeSpan? maxAge = null, DateTimeOffset? now = null)
    {
        if (Report is not { } report) return true;
        var date = ReportDates.ParseTimestamp(report.ScannedAt ?? report.GeneratedAt);
        if (date is null) return true;
        return (now ?? DateTimeOffset.UtcNow) - date.Value > (maxAge ?? TimeSpan.FromHours(6));
    }

    /// <summary>请求一次刷新。扫描中再请求会排队（<paramref name="rescan"/> 为 true 时排队的也强制重扫）。</summary>
    public void Refresh(bool rescan = false)
    {
        lock (_lock)
        {
            if (_running)
            {
                _pending = true;
                if (rescan) _pendingRescan = true;
                return;
            }
            _running = true;
        }
        _ = Task.Run(() => LoopAsync(rescan));
    }

    /// <summary>同步刷新：跑完（含排队的请求）才返回。截图 / 测试用。</summary>
    public void RefreshBlocking(bool rescan = false)
    {
        lock (_lock)
        {
            if (_running)
            {
                _pending = true;
                if (rescan) _pendingRescan = true;
                return;
            }
            _running = true;
        }
        LoopAsync(rescan).GetAwaiter().GetResult();
    }

    private async Task LoopAsync(bool rescan)
    {
        var force = rescan;
        while (true)
        {
            await RunOnceAsync(force).ConfigureAwait(false);
            lock (_lock)
            {
                if (_pending)
                {
                    force = _pendingRescan;
                    _pending = false;
                    _pendingRescan = false;
                }
                else
                {
                    _running = false;
                    return;
                }
            }
        }
    }

    private async Task RunOnceAsync(bool rescan)
    {
        int generation;
        lock (_lock)
        {
            if (!_state.BeginRefresh()) return;
            generation = _generation;
        }
        Changed?.Invoke();

        DiskReport? loaded = null;
        string? error = null;
        try
        {
            var (source, description) = _makeSource(rescan);
            lock (_lock)
            {
                _source = source;
                _sourceDescription = description;
            }
            var report = await Task.Run(source.Load).ConfigureAwait(false);
            if (CurrentGeneration() == generation)
            {
                loaded = report;
                _cache?.Save(report);
            }
        }
        catch (Exception e)
        {
            if (CurrentGeneration() == generation) error = e.Message;
        }

        lock (_lock)
        {
            if (CurrentGenerationLocked() == generation)
            {
                _error = error;
                _state.FinishRefresh(loaded);
                _lastRefresh = DateTimeOffset.UtcNow;
            }
            else
            {
                _state.FinishRefresh(null);
            }
        }
        Changed?.Invoke();
    }

    private int CurrentGeneration()
    {
        lock (_lock) return _generation;
    }

    private int CurrentGenerationLocked() => _generation;

    /// <summary>清理：先 dry-run（confirmed=false），用户确认后再带 --yes。文件来源会拒绝。</summary>
    public CleanResult Clean(IReadOnlyList<string> ids, string? olderThan, bool confirmed)
    {
        IDiskSource source;
        lock (_lock) source = _source ?? _makeSource(false).Source;
        return source.Clean(ids, olderThan, confirmed);
    }

    /// <summary>设置改动后调用：丢弃正在跑的旧结果，清掉排队请求。</summary>
    public void ApplySettings()
    {
        lock (_lock)
        {
            _generation++;
            _source = null;
            _pending = false;
            _pendingRescan = false;
        }
    }
}
