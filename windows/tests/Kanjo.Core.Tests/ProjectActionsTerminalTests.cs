using Kanjo.App.Views;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>「Open in Terminal」：项目路径只能当工作目录传，不能拼进 PowerShell 脚本或 wt 的命令行。</summary>
public sealed class ProjectActionsTerminalTests : KanjoTestCase
{
    [Theory]
    [InlineData(@"C:\p\x’;Start-Process calc;’")]
    [InlineData(@"C:\p\Bob’s app")]
    [InlineData(@"C:\src\notes;calc")]
    [InlineData(@"C:\p\it's")]
    public void TestPathIsPassedAsWorkingDirectoryOnly(string path)
    {
        foreach (var hasWindowsTerminal in new[] { true, false })
        {
            var command = ProjectActions.TerminalCommand(path, hasWindowsTerminal);
            Assert.Equal(hasWindowsTerminal ? "wt.exe" : "powershell.exe", command.File);
            Assert.Equal(path, command.WorkingDirectory);
            Assert.DoesNotContain(command.Arguments, arg => arg.Contains(path, StringComparison.Ordinal));
            Assert.DoesNotContain(command.Arguments, arg => arg.Contains(';'));
            Assert.DoesNotContain("-Command", command.Arguments);
        }
    }

    [Fact]
    public void TestOpenInTerminalLaunchesInProjectDirectory()
    {
        var launched = new List<ProjectActions.LaunchRequest>();
        ProjectActions.LaunchRequestOverride = launched.Add;
        try
        {
            ProjectActions.OpenInTerminal(@"C:\p\a;b");
        }
        finally
        {
            ProjectActions.LaunchRequestOverride = null;
        }
        var request = Assert.Single(launched);
        Assert.Equal(@"C:\p\a;b", request.WorkingDirectory);
        Assert.DoesNotContain(request.Arguments, arg => arg.Contains(@"C:\p\a;b", StringComparison.Ordinal));
    }
}
