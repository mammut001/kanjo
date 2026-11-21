using Avalonia.Controls;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Kanjo.App;
using Kanjo.App.Views;
using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>设置页配置写入（额度重置、Antigravity 账号套餐）回归测试。</summary>
public sealed class SettingsConfigTests : KanjoTestCase
{
    private static (AppServices Services, string ConfigLog) NewCliServices()
    {
        var settings = AppSettings.InMemory();
        settings.Set(SettingsKeys.AppLanguage, "en");
        settings.Set(SettingsKeys.SourceKind, "cli");
        L10n.Store = settings;
        L10n.ResetCache();

        var dir = TempDir();
        var log = Path.Combine(dir, "config.log");
        var cli = Path.Combine(dir, "cli");
        Directory.CreateDirectory(Path.Combine(cli, "kanjo"));
        File.WriteAllText(Path.Combine(cli, "kanjo", "__init__.py"), "");
        var python = ConfigPython(dir, log);

        var services = new AppServices(settings, ["--snapshot"], dir,
            new FakeBackgroundScheduler(), new FakeLogWatcherFactory(), new FakePowerMonitor());
        services.Config.Runner = () => new CliRunner
        {
            PythonExecutable = python,
            WorkingDirectory = cli,
        };
        services.LoadQuietly();
        return (services, log);
    }

    private static string ConfigPython(string dir, string log)
    {
        var fixture = FixturePath;
        if (OperatingSystem.IsWindows())
        {
            var cmd = Path.Combine(dir, "python.cmd");
            File.WriteAllText(cmd,
                $"""
                 @echo off
                 if "%~3"=="export" (
                   type "{fixture}"
                   exit /b 0
                 )
                 if "%~3"=="config" (
                   echo %*>>"{log}"
                   echo ok
                   exit /b 0
                 )
                 echo unknown 1>&2
                 exit /b 9
                 """);
            return cmd;
        }

        var sh = Path.Combine(dir, "python");
        File.WriteAllText(sh,
            $"""
             #!/bin/sh
             if [ "$3" = "export" ]; then
               cat "{fixture}"
               exit 0
             fi
             if [ "$3" = "config" ]; then
               echo "$*" >> "{log}"
               echo ok
               exit 0
             fi
             echo unknown >&2
             exit 9
             """);
        File.SetUnixFileMode(sh,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
            UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
        return sh;
    }

    private static int ConfigCallCount(string log) =>
        File.Exists(log) ? File.ReadAllLines(log).Count(l => l.Trim().Length > 0) : 0;

    [Fact]
    public void TestQuotaResetPickerDoesNotWriteUntilApply()
    {
        OnUi(() =>
        {
            var (services, log) = NewCliServices();
            var page = new SettingsPage(services, null, null, snapshot: false, onBack: () => { });
            var window = TestWindows.Show(page, Metrics.PanelWidth, Metrics.PanelHeight);
            Dispatcher.UIThread.RunJobs();

            var row = page.GetVisualDescendants().OfType<QuotaResetRow>().First();
            var weekdayPicker = row.GetVisualDescendants().OfType<ComboBox>().First();
            var before = weekdayPicker.SelectedIndex;
            weekdayPicker.SelectedIndex = before == 0 ? 1 : 0;
            Dispatcher.UIThread.RunJobs();
            Assert.Equal(0, ConfigCallCount(log));

            var apply = row.GetVisualDescendants().OfType<Control>()
                .First(c => c is ContentControl { Content: var t } && Equals(t, L10n.Tr("common.apply")));
            if (apply is Button btn) btn.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
            Dispatcher.UIThread.RunJobs();

            var deadline = DateTime.UtcNow.AddSeconds(5);
            while (DateTime.UtcNow < deadline && ConfigCallCount(log) == 0)
            {
                Thread.Sleep(20);
                Dispatcher.UIThread.RunJobs();
            }
            Assert.Equal(1, ConfigCallCount(log));
            window.Close();
        });
    }

    [Fact]
    public void TestAntigravityAccountPlanUsesSingleConfigKeyArgument()
    {
        var args = ConfigCommand.AntigravityAccountPlanArguments("first.last+tag@company.co.uk", "google_ai_pro");
        Assert.Equal("antigravity_accounts.first.last+tag@company.co.uk.plan", args[2]);
        var cmd = ConfigCommand.Command("python -m kanjo export", args);
        Assert.Contains("'antigravity_accounts.first.last+tag@company.co.uk.plan'", cmd);
    }

    [Fact]
    public void TestAntigravityAccountsDecodeFromSampleFixture()
    {
        var report = LoadFixture();
        var reportAccounts = report.AntigravityAccounts;
        Assert.NotNull(reportAccounts);
        Assert.Equal(3, reportAccounts.Accounts.Count);
        Assert.Equal("alex@example.com", reportAccounts.Current);
        Assert.Equal("google_ai_ultra", reportAccounts.Accounts[0].Plan?.Plan);
    }

    [Fact]
    public void TestAntigravityAccountPlanLowercasesEmail()
    {
        var args = ConfigCommand.AntigravityAccountPlanArguments(
            "Alice.Doe+Work@Gmail.com", "google_ai_pro");
        Assert.Equal("antigravity_accounts.alice.doe+work@gmail.com.plan", args[2]);
    }

    [Fact]
    public void TestAntigravityAccountPickerRoundTripsPerEmail()
    {
        OnUi(() =>
        {
            var (services, log) = NewCliServices();
            File.WriteAllText(log, "");
            services.SetAntigravityAccountPlan("alex@example.com", "google_ai_pro");
            var deadline = DateTime.UtcNow.AddSeconds(5);
            while (DateTime.UtcNow < deadline && ConfigCallCount(log) == 0)
            {
                Thread.Sleep(20);
                Dispatcher.UIThread.RunJobs();
            }
            Assert.Equal(1, ConfigCallCount(log));
            var line = File.ReadAllLines(log)[0];
            Assert.Contains("antigravity_accounts.alex@example.com.plan", line);
            Assert.Contains("google_ai_pro", line);
            Assert.Equal("google_ai_pro", services.PendingAntigravityAccountPlans["alex@example.com"]);
        });
    }
}