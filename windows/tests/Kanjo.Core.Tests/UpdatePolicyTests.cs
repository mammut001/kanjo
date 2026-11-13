using System.Runtime.InteropServices;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 自动更新策略：什么时候跑、什么时候让 Velopack 在启动时应用更新。
/// 真正的网络 / 安装动作在 Kanjo.App.UpdateService，这里只测判断。
/// </summary>
public sealed class UpdatePolicyTests : KanjoTestCase
{
    private static readonly string[] Tray = [];

    [Fact]
    public void TestRunsWhenInstalledAndReleaseBuild()
    {
        Assert.True(UpdatePolicy.ShouldRun(Tray, isDebugBuild: false, isInstalled: true));
        Assert.True(UpdatePolicy.ShouldRun(["--data", "sample.json"], isDebugBuild: false, isInstalled: true));
    }

    [Fact]
    public void TestDoesNotRunWhenNotInstalled()
    {
        // 开发运行、解压出来的文件夹、便携版：没有 Velopack 的安装目录，更新器无从下手。
        Assert.False(UpdatePolicy.ShouldRun(Tray, isDebugBuild: false, isInstalled: false));
    }

    [Fact]
    public void TestDoesNotRunInDebugBuild()
    {
        Assert.False(UpdatePolicy.ShouldRun(Tray, isDebugBuild: true, isInstalled: true));
    }

    [Fact]
    public void TestDoesNotRunInSnapshotOrWindowMode()
    {
        Assert.False(UpdatePolicy.ShouldRun(["--snapshot", "out.png"], false, true));
        Assert.False(UpdatePolicy.ShouldRun(["--snapshot=out.png", "--route", "overview"], false, true));
        Assert.False(UpdatePolicy.ShouldRun(["--window"], false, true));
        Assert.False(UpdatePolicy.ShouldRun(["--window", "--route", "settings"], false, true));
    }

    [Fact]
    public void TestSnapshotDetection()
    {
        Assert.True(UpdatePolicy.IsDisabledMode(["--snapshot", "a.png"]));
        Assert.True(UpdatePolicy.IsDisabledMode(["--snapshot=a.png"]));
        Assert.True(UpdatePolicy.IsDisabledMode(["--window"]));
        Assert.False(UpdatePolicy.IsDisabledMode([]));
        Assert.False(UpdatePolicy.IsDisabledMode(["--data", "sample.json"]));
        // 值里出现 --snapshot 字样不算：参数必须自己就是开关。
        Assert.False(UpdatePolicy.IsDisabledMode(["--data", "--snapshot.png"]));
    }

    [Fact]
    public void TestAutoApplyOnStartup()
    {
        Assert.True(UpdatePolicy.ShouldAutoApplyOnStartup(Tray, isDebugBuild: false));
        Assert.False(UpdatePolicy.ShouldAutoApplyOnStartup(Tray, isDebugBuild: true));
        Assert.False(UpdatePolicy.ShouldAutoApplyOnStartup(["--snapshot", "a.png"], isDebugBuild: false));
        Assert.False(UpdatePolicy.ShouldAutoApplyOnStartup(["--window"], isDebugBuild: false));
    }

    /// <summary>30 秒后第一次检查，之后每 6 小时；发布源是 GitHub 仓库。</summary>
    [Fact]
    public void TestScheduleConstants()
    {
        Assert.Equal(TimeSpan.FromSeconds(30), UpdatePolicy.InitialDelay);
        Assert.Equal(TimeSpan.FromHours(6), UpdatePolicy.Interval);
        Assert.Equal("https://github.com/mammut001/kanjo", UpdatePolicy.RepositoryUrl);
    }

    /// <summary>每个架构一个通道（和 vpk 的 --channel 一致），互不覆盖。</summary>
    [Fact]
    public void TestChannelFollowsProcessArchitecture()
    {
        Assert.Equal("win-x64", UpdatePolicy.ChannelForArchitecture(Architecture.X64));
        Assert.Equal("win-arm64", UpdatePolicy.ChannelForArchitecture(Architecture.Arm64));

        // 当前进程的通道和它的架构对得上（测试机上就是 win-x64 或 win-arm64）。
        var current = RuntimeInformation.ProcessArchitecture;
        Assert.Equal("win-" + (current == Architecture.Arm64 ? "arm64" : "x64"), UpdatePolicy.CurrentChannel);
    }

    /// <summary>
    /// Debug 构建（测试就是）永远不连 Velopack：<see cref="Kanjo.App.UpdateService.Create"/> 返回的
    /// 是 NotInstalled 的空壳（设置页仍显示版本号、按钮禁用），不联网、不碰 locator。
    /// </summary>
    [Fact]
    public void TestCreateIsInertOutsideRelease()
    {
        foreach (var service in new[]
                 {
                     Kanjo.App.UpdateService.Create([]),
                     Kanjo.App.UpdateService.Create(["--snapshot", "out.png"]),
                     Kanjo.App.UpdateService.Create(["--window"]),
                 })
        {
            Assert.NotNull(service);
            Assert.Equal(UpdateState.NotInstalled, service!.Status.State);
            Assert.False(service.Status.CanCheck);
            Assert.False(service.HasReadyUpdate);
            Assert.False(string.IsNullOrWhiteSpace(service.CurrentVersion));
            service.Dispose();
        }
    }
}
