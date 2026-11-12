namespace Kanjo.Core;

/// <summary>
/// 一个正在运行的目录监听器（Mac 的 <c>LogWatcher</c>，Windows 上是 <see cref="FileSystemWatcher"/>）。
/// 只负责「有变化就叫一下」，防抖 / 最小间隔全部交给 <see cref="RefreshScheduler"/>。
/// </summary>
public interface ILogWatcher : IDisposable
{
    /// <summary>实际在监听的目录（不存在的目录已经被滤掉）。</summary>
    IReadOnlyList<string> Paths { get; }

    bool IsActive { get; }
}

/// <summary>按目录列表创建监听器；目录都不存在时返回 null（Mac 的 <c>LogWatcher.start</c> 同样直接返回）。</summary>
public interface ILogWatcherFactory
{
    ILogWatcher? Start(IReadOnlyList<string> paths, Action onEvent);
}

/// <summary>
/// Windows 的日志监听：每个存在的目录一个递归 <see cref="FileSystemWatcher"/>，
/// 只关心写入 / 新建 / 改名 / 删除；任何一个目录报了变化就调用一次回调。
/// 出错（缓冲区溢出、目录被删）时停掉那一个，下一次刷新会按最新路径重建。
/// </summary>
public sealed class FileSystemLogWatcherFactory : ILogWatcherFactory
{
    /// <summary>把变化事件合并到这个间隔里再上报，避免一次写日志触发几十次回调（FSEvents 也是合并的）。</summary>
    public TimeSpan Coalesce { get; init; } = TimeSpan.FromMilliseconds(200);

    public ILogWatcher? Start(IReadOnlyList<string> paths, Action onEvent)
    {
        var existing = paths
            .Where(p => !string.IsNullOrWhiteSpace(p))
            .Select(SafeFullPath)
            .Where(p => p is not null && Directory.Exists(p))
            .Select(p => p!)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (existing.Count == 0) return null;
        return new FileSystemLogWatcher(existing, onEvent, Coalesce);
    }

    private static string? SafeFullPath(string path)
    {
        try
        {
            return Path.GetFullPath(DefaultPaths.ExpandTilde(path));
        }
        catch (Exception)
        {
            return null;
        }
    }
}

internal sealed class FileSystemLogWatcher : ILogWatcher
{
    private readonly List<FileSystemWatcher> _watchers = [];
    private readonly Action _onEvent;
    private readonly object _lock = new();
    private readonly TimeSpan _coalesce;
    private Timer? _coalesceTimer;
    private bool _disposed;

    public FileSystemLogWatcher(IReadOnlyList<string> paths, Action onEvent, TimeSpan coalesce)
    {
        Paths = paths;
        _onEvent = onEvent;
        _coalesce = coalesce;
        foreach (var path in paths)
        {
            try
            {
                var watcher = new FileSystemWatcher(path)
                {
                    IncludeSubdirectories = true,
                    NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.FileName |
                                   NotifyFilters.DirectoryName | NotifyFilters.Size |
                                   NotifyFilters.CreationTime,
                    InternalBufferSize = 64 * 1024,
                    EnableRaisingEvents = true,
                };
                watcher.Changed += OnChanged;
                watcher.Created += OnChanged;
                watcher.Deleted += OnChanged;
                watcher.Renamed += OnRenamed;
                watcher.Error += OnError;
                _watchers.Add(watcher);
            }
            catch (Exception)
            {
                // 没有权限 / 目录刚好消失：跳过这个目录，别的照常。
            }
        }
    }

    public IReadOnlyList<string> Paths { get; }

    public bool IsActive
    {
        get { lock (_lock) return !_disposed && _watchers.Count > 0; }
    }

    private void OnChanged(object sender, FileSystemEventArgs e) => Trigger();

    private void OnRenamed(object sender, RenamedEventArgs e) => Trigger();

    private void OnError(object sender, ErrorEventArgs e)
    {
        // 缓冲区溢出：这个目录的 watcher 已经不可靠了，停掉它；下一次刷新会重建。
        if (sender is not FileSystemWatcher watcher) return;
        lock (_lock)
        {
            if (_disposed) return;
            _watchers.Remove(watcher);
        }
        try
        {
            watcher.EnableRaisingEvents = false;
            watcher.Dispose();
        }
        catch (Exception)
        {
            // 已经没了。
        }
    }

    private void Trigger()
    {
        lock (_lock)
        {
            if (_disposed) return;
            if (_coalesceTimer is null)
            {
                _coalesceTimer = new Timer(_ => Flush(), null, _coalesce, Timeout.InfiniteTimeSpan);
            }
            else
            {
                _coalesceTimer.Change(_coalesce, Timeout.InfiniteTimeSpan);
            }
        }
    }

    private void Flush()
    {
        lock (_lock)
        {
            _coalesceTimer?.Dispose();
            _coalesceTimer = null;
            if (_disposed) return;
        }
        _onEvent();
    }

    public void Dispose()
    {
        List<FileSystemWatcher> watchers;
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            _coalesceTimer?.Dispose();
            _coalesceTimer = null;
            watchers = [.. _watchers];
            _watchers.Clear();
        }
        foreach (var watcher in watchers)
        {
            try
            {
                watcher.EnableRaisingEvents = false;
                watcher.Changed -= OnChanged;
                watcher.Created -= OnChanged;
                watcher.Deleted -= OnChanged;
                watcher.Renamed -= OnRenamed;
                watcher.Error -= OnError;
                watcher.Dispose();
            }
            catch (Exception)
            {
                // 已经释放。
            }
        }
    }
}
