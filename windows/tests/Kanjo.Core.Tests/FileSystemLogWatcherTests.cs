using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 真实的 <see cref="FileSystemLogWatcherFactory"/>（<see cref="FileSystemWatcher"/>）：
/// 只在临时目录里写文件，不碰用户的日志目录。
/// </summary>
public sealed class FileSystemLogWatcherTests : KanjoTestCase
{
    [Fact]
    public void TestMissingDirectoriesProduceNoWatcher()
    {
        var factory = new FileSystemLogWatcherFactory();
        var root = TempDir();
        using var watcher = factory.Start([Path.Combine(root, "nope"), ""], () => { });
        Assert.Null(watcher);
    }

    [Fact]
    public void TestExistingDirectoryIsWatched()
    {
        var factory = new FileSystemLogWatcherFactory();
        var root = TempDir();
        var logs = Path.Combine(root, "logs");
        Directory.CreateDirectory(logs);

        using var watcher = factory.Start([logs, Path.Combine(root, "missing")], () => { });
        Assert.NotNull(watcher);
        Assert.True(watcher!.IsActive);
        Assert.Equal([Path.GetFullPath(logs)], watcher.Paths);
    }

    [Fact]
    public async Task TestFileWriteRaisesEvent()
    {
        var factory = new FileSystemLogWatcherFactory { Coalesce = TimeSpan.FromMilliseconds(30) };
        var logs = TempDir();
        var fired = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var watcher = factory.Start([logs], () => fired.TrySetResult(true));
        Assert.NotNull(watcher);

        File.WriteAllText(Path.Combine(logs, "session.jsonl"), "{\"a\":1}\n");

        // 事件可能合并 / 延迟，最多等 10 秒（不睡眠轮询：直接 await 信号）。
        var completed = await Task.WhenAny(fired.Task, Task.Delay(TimeSpan.FromSeconds(10)));
        Assert.Same(fired.Task, completed);
        Assert.True(await fired.Task);
    }

    [Fact]
    public void TestDisposeStopsEvents()
    {
        var factory = new FileSystemLogWatcherFactory();
        var logs = TempDir();
        var count = 0;
        var watcher = factory.Start([logs], () => Interlocked.Increment(ref count));
        Assert.NotNull(watcher);
        watcher!.Dispose();

        Assert.False(watcher.IsActive);
        File.WriteAllText(Path.Combine(logs, "x.jsonl"), "x");
        Assert.Equal(0, Volatile.Read(ref count));
    }
}
