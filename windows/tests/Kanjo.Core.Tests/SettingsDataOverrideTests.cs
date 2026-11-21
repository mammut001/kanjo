using Avalonia.Controls;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 设置页的 `--data` 警告：截图模式只能露文件名，不能把开发机的目录写进公开截图；
/// 正常运行时仍然显示完整路径。
/// </summary>
public sealed class SettingsDataOverrideTests : KanjoTestCase
{
    private static AppServices NewServices(string dataPath)
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        L10n.Store = settings;
        L10n.ResetCache();
        // --snapshot 让设置页不要去跑 CLI 预热档位表；页面自己的 snapshot 参数决定文案。
        return new AppServices(settings, ["--snapshot", "--data", dataPath], TempDir());
    }

    private static string WarningText(SettingsPage page)
    {
        TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
        Dispatcher.UIThread.RunJobs();
        var bar = page.GetVisualDescendants().OfType<InfoBar>().Single();
        return string.Join("\n", bar.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text));
    }

    [Fact]
    public void TestSnapshotWarningShowsOnlyFileName()
    {
        OnUi(() =>
        {
            var directory = TempDir();
            var dataPath = Path.Combine(directory, "sample.json");
            File.WriteAllText(dataPath, "{}");
            var page = new SettingsPage(NewServices(dataPath), null, null, snapshot: true, onBack: () => { });

            var text = WarningText(page);

            Assert.Contains("sample.json", text);
            Assert.DoesNotContain(directory, text);
        });
    }

    [Fact]
    public void TestNormalWarningKeepsFullPath()
    {
        OnUi(() =>
        {
            var directory = TempDir();
            var dataPath = Path.Combine(directory, "sample.json");
            File.WriteAllText(dataPath, "{}");
            var page = new SettingsPage(NewServices(dataPath), null, null, snapshot: false, onBack: () => { });

            var text = WarningText(page);

            Assert.Contains(dataPath, text);
        });
    }
}
