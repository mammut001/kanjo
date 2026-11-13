using Kanjo.App;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 更新状态值对象本身的小规则：进度夹紧、快照注入、错误消息缩短、版本号来源。
/// 状态机（检查 → 下载 → 就绪 / 失败）在 <see cref="UpdateCoordinatorTests"/> 里。
/// </summary>
public sealed class UpdateStatusTests : KanjoTestCase
{
    [Fact]
    public void TestProgressIsClamped()
    {
        Assert.Equal(0, new UpdateStatus(UpdateState.Downloading, "0.5.3", -20).Progress);
        Assert.Equal(100, new UpdateStatus(UpdateState.Downloading, "0.5.3", 250).Progress);
        Assert.Equal(42, new UpdateStatus(UpdateState.Downloading, "0.5.3", 42).Progress);
    }

    [Fact]
    public void TestBusyAndCheckableStates()
    {
        Assert.True(new UpdateStatus(UpdateState.Checking).IsBusy);
        Assert.True(new UpdateStatus(UpdateState.Downloading, "0.5.3", 10).IsBusy);
        Assert.False(new UpdateStatus(UpdateState.Ready, "0.5.3").IsBusy);
        Assert.True(UpdateStatus.NotInstalled("0.5.2").CurrentVersion == "0.5.2");
        Assert.False(UpdateStatus.NotInstalled("0.5.2").CanCheck);
        Assert.True(new UpdateStatus(UpdateState.Idle).CanCheck);
    }

    /// <summary>错误消息可能带换行和一长串堆栈：界面上只留一句。</summary>
    [Fact]
    public void TestErrorShortening()
    {
        var oneLine = UpdateStatusText.Shorten("first line\nsecond line");
        Assert.Equal("first line second line", oneLine);

        var longText = new string('x', 300);
        var shortened = UpdateStatusText.Shorten(longText);
        Assert.True(shortened.Length <= 120, shortened.Length.ToString());
        Assert.EndsWith("…", shortened, StringComparison.Ordinal);
    }

    /// <summary>截图注入的状态只走 <c>--snapshot</c>：能解析出四种界面状态，非法值返回 null。</summary>
    [Fact]
    public void TestSnapshotStatesParse()
    {
        Assert.Equal(UpdateState.Ready, UpdateSnapshots.Parse("ready", "0.5.2")!.State);
        Assert.Equal("0.5.3", UpdateSnapshots.Parse("ready", "0.5.2")!.Version);
        Assert.Equal(42, UpdateSnapshots.Parse("downloading", "0.5.2")!.Progress);
        Assert.Equal(UpdateState.NotInstalled, UpdateSnapshots.Parse("not-installed", "0.5.2")!.State);
        Assert.Equal(UpdateState.UpToDate, UpdateSnapshots.Parse("up-to-date", "0.5.2")!.State);
        Assert.Null(UpdateSnapshots.Parse("bogus", "0.5.2"));
        Assert.Null(UpdateSnapshots.Parse(null, "0.5.2"));

        // 默认（没传 --snapshot-update）不画横幅。
        Assert.False(UpdateBanner.ShouldShow(UpdateSnapshots.Default("0.5.2"), null));
    }

    [Fact]
    public void TestCurrentVersionComesFromTheBuild()
    {
        // 版本号来自仓库根目录的 VERSION（csproj 写进 InformationalVersion）：三段式、非空。
        var version = AppVersion.Current;
        Assert.Matches(@"^\d+\.\d+\.\d+", version);
        Assert.DoesNotContain('+', version);
        Assert.Equal(version, UpdateService.CreateUnavailable().CurrentVersion);
    }
}
