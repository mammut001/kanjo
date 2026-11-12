using Xunit;

namespace Kanjo.Core.Tests;

public sealed class ConfigCommandTests : KanjoTestCase
{
    private const string DefaultCommand = "python.exe -m kanjo export";

    [Fact]
    public void TestArguments()
    {
        Assert.Equal(["config", "set", "subscriptions.codex.anchor_day", "8"],
            ConfigCommand.Arguments("codex", 8));
        Assert.Equal(["config", "unset", "subscriptions.claude.anchor_day"],
            ConfigCommand.Arguments("claude", null));
        foreach (var day in new[] { 1, 28 })
        {
            Assert.Equal(day.ToString(), ConfigCommand.Arguments("claude", day)[^1]);
        }
        foreach (var day in new[] { 0, 29 })
        {
            Assert.Throws<DataSourceError>(() => ConfigCommand.Arguments("codex", day));
        }
        foreach (var agent in new[] { "", "codex; touch /tmp/x", "codex.plan" })
        {
            Assert.Throws<DataSourceError>(() => ConfigCommand.Arguments(agent, 8));
        }
    }

    [Fact]
    public void TestDerivationPreservesLaunchCommandAndPrefix()
    {
        Assert.Equal("python.exe -m kanjo config set subscriptions.codex.anchor_day 8",
            ConfigCommand.Command(DefaultCommand, ConfigCommand.Arguments("codex", 8)));
        Assert.Equal("python.exe -m kanjo config unset subscriptions.claude.anchor_day",
            ConfigCommand.Command(DefaultCommand, ConfigCommand.Arguments("claude", null)));

        const string prefix = @"C:\Kanjo\python\python.exe -m kanjo ";
        Assert.Equal(prefix + "config set subscriptions.codex.anchor_day 8",
            ConfigCommand.Command(prefix + "export", ConfigCommand.Arguments("codex", 8)));
        Assert.Equal(@"C:\Kanjo\kanjo config unset subscriptions.claude.anchor_day",
            ConfigCommand.Command("  C:\\Kanjo\\kanjo export  \n", ConfigCommand.Arguments("claude", null)));
    }

    [Fact]
    public void TestRejectsCommandsWithoutFinalExportSubcommand()
    {
        foreach (var command in new[]
                 {
                     "", "export", "python.exe -m kanjo", "kanjo", "kanjo re-export", "kanjo export --output report.json",
                 })
        {
            Assert.Throws<DataSourceError>(() =>
                ConfigCommand.Command(command, ConfigCommand.Arguments("codex", 8)));
        }
    }

    [Fact]
    public void TestFieldArgumentsForArbitraryAgents()
    {
        foreach (var agent in new[]
                 { "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "custom_agent" })
        {
            Assert.Equal(["config", "set", $"subscriptions.{agent}.plan", "pro"],
                ConfigCommand.FieldArguments(agent, "plan", "pro"));
            Assert.Equal(["config", "set", $"subscriptions.{agent}.monthly_price_usd", "20"],
                ConfigCommand.FieldArguments(agent, "monthly_price_usd", "20"));
            Assert.Equal(["config", "unset", $"subscriptions.{agent}.plan"],
                ConfigCommand.FieldArguments(agent, "plan", null));
        }
        Assert.Throws<DataSourceError>(() => ConfigCommand.FieldArguments("grok", "invalid_field", "x"));
        Assert.Throws<DataSourceError>(() => ConfigCommand.FieldArguments("bad;agent", "plan", "x"));
    }

    [Fact]
    public void TestQuotaResetArguments()
    {
        Assert.Equal(["config", "set", "quota_windows.claude.weekly_reset", "tue 05:00"],
            ConfigCommand.QuotaResetArguments("claude", "tue 05:00"));
        Assert.Equal(["config", "unset", "quota_windows.grok.weekly_reset"],
            ConfigCommand.QuotaResetArguments("grok", null));
        Assert.Equal(["config", "unset", "quota_windows.antigravity.weekly_reset"],
            ConfigCommand.QuotaResetArguments("antigravity", "  "));
        foreach (var agent in new[]
                 { "grok", "copilot", "minimax", "qwen", "commandcode", "opencode", "custom_agent" })
        {
            Assert.Equal(["config", "set", $"quota_windows.{agent}.weekly_reset", "mon 09:00"],
                ConfigCommand.QuotaResetArguments(agent, "mon 09:00"));
        }
        foreach (var agent in new[] { "", "bad;agent", "agent with spaces" })
        {
            Assert.Throws<DataSourceError>(() => ConfigCommand.QuotaResetArguments(agent, "tue 05:00"));
        }
    }

    [Fact]
    public void TestPlansCommand()
    {
        Assert.Equal(["config", "plans", "--json"], ConfigCommand.PlansArguments());
        Assert.Equal("python.exe -m kanjo config plans --json",
            ConfigCommand.Command(DefaultCommand, ConfigCommand.PlansArguments()));
    }

    [Fact]
    public void TestFamilyScopeArguments()
    {
        Assert.Equal(["config", "set", "family.since", "2026-11-09"], ConfigCommand.FamilySinceArguments("2026-11-09"));
        Assert.Equal(["config", "unset", "family.since"], ConfigCommand.FamilySinceArguments(null));
        Assert.Equal(["config", "unset", "family.since"], ConfigCommand.FamilySinceArguments("  "));

        Assert.Equal(["config", "set", "family.agents", "all"], ConfigCommand.FamilyAgentsArguments("all"));
        Assert.Equal(["config", "set", "family.agents", "antigravity"], ConfigCommand.FamilyAgentsArguments("antigravity"));
        Assert.Equal(["config", "unset", "family.agents"], ConfigCommand.FamilyAgentsArguments(null));
        Assert.Equal(["config", "unset", "family.agents"], ConfigCommand.FamilyAgentsArguments("   "));
    }
}
