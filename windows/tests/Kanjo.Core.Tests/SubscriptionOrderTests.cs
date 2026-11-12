using Xunit;

namespace Kanjo.Core.Tests;

public sealed class SubscriptionOrderTests : KanjoTestCase
{
    private static SubscriptionRow Row(string agent, double usage = 10.0) =>
        new(agent, char.ToUpperInvariant(agent[0]) + agent[1..], 20.0, usage, 0.5, false, null);

    [Fact]
    public void TestApplyWithEmptyOrderReturnsDefault()
    {
        List<SubscriptionRow> rows = [Row("claude", 100), Row("codex", 50), Row("grok", 20)];
        var ordered = SubscriptionOrder.Apply([], rows);
        Assert.Equal(["claude", "codex", "grok"], ordered.Select(r => r.Agent).ToArray());
        Assert.Equal(rows, ordered);
    }

    [Fact]
    public void TestApplyPartialOrder()
    {
        List<SubscriptionRow> rows = [Row("claude", 100), Row("codex", 50), Row("grok", 30), Row("minimax", 10)];
        var ordered = SubscriptionOrder.Apply(["grok", "claude"], rows);
        Assert.Equal(["grok", "claude", "codex", "minimax"], ordered.Select(r => r.Agent).ToArray());
    }

    [Fact]
    public void TestApplyUnknownAgentIgnored()
    {
        List<SubscriptionRow> rows = [Row("claude"), Row("codex"), Row("grok")];
        var ordered = SubscriptionOrder.Apply(["unknown-agent", "grok", "nonexistent"], rows);
        Assert.Equal(["grok", "claude", "codex"], ordered.Select(r => r.Agent).ToArray());
    }

    [Fact]
    public void TestMoveSemantics()
    {
        List<string> initial = ["claude", "codex", "grok", "minimax"];

        Assert.Equal(["claude", "minimax", "codex", "grok"], SubscriptionOrder.Move("minimax", "codex", initial));
        Assert.Equal(["codex", "grok", "claude", "minimax"], SubscriptionOrder.Move("claude", "grok", initial));
        Assert.Equal(initial, SubscriptionOrder.Move("claude", "claude", initial));
        Assert.Equal(initial, SubscriptionOrder.Move("ghost", "claude", initial));
        Assert.Equal(initial, SubscriptionOrder.Move("claude", "ghost", initial));

        List<SubscriptionRow> rows = [Row("claude"), Row("codex"), Row("grok"), Row("minimax")];
        var moved = SubscriptionOrder.Move("minimax", "claude", rows);
        Assert.Equal(["minimax", "claude", "codex", "grok"], moved.Select(r => r.Agent).ToArray());
    }

    [Fact]
    public void TestParseAndSerializeRoundTrip()
    {
        Assert.Empty(SubscriptionOrder.Parse(""));
        Assert.Equal("", SubscriptionOrder.Serialize([]));

        Assert.Equal(["claude", "codex", "grok"], SubscriptionOrder.Parse("  claude , codex , , grok  "));

        List<string> original = ["claude", "codex", "grok", "minimax"];
        var serialized = SubscriptionOrder.Serialize(original);
        Assert.Equal("claude,codex,grok,minimax", serialized);
        Assert.Equal(original, SubscriptionOrder.Parse(serialized));

        Assert.Equal(["claude", "codex", "grok"], SubscriptionOrder.Parse("claude,codex,claude,grok"));
    }

    [Fact]
    public void TestCollapseHelperVisible()
    {
        List<SubscriptionRow> rows = [Row("a"), Row("b"), Row("c"), Row("d"), Row("e")];

        var collapsed = SubscriptionOrder.Visible(rows, false, 3);
        Assert.Equal(3, collapsed.Count);
        Assert.Equal(["a", "b", "c"], collapsed.Select(r => r.Agent).ToArray());

        var defaultCollapsed = SubscriptionOrder.Visible(rows, false);
        Assert.Equal(3, defaultCollapsed.Count);

        var expanded = SubscriptionOrder.Visible(rows, true, 3);
        Assert.Equal(5, expanded.Count);
        Assert.Equal(["a", "b", "c", "d", "e"], expanded.Select(r => r.Agent).ToArray());

        List<SubscriptionRow> shortRows = [Row("a"), Row("b")];
        Assert.Equal(2, SubscriptionOrder.Visible(shortRows, false, 3).Count);
        Assert.Equal(2, SubscriptionOrder.Visible(shortRows, true, 3).Count);

        Assert.Empty(SubscriptionOrder.Visible(new List<SubscriptionRow>(), false, 3));
        Assert.Empty(SubscriptionOrder.Visible(new List<SubscriptionRow>(), true, 3));
    }
}
