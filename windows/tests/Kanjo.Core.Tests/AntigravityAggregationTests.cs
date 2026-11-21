using Xunit;

namespace Kanjo.Core.Tests;

public sealed class AntigravityAggregationTests : KanjoTestCase
{
    private static AntigravityAccount Account(string email, AntigravityAccountPlan? plan) =>
        new(email, 0, 0, 0, null, false, plan, null);

    [Fact]
    public void TestAggregateMultiAccountPlans()
    {
        var accounts = new[]
        {
            Account("a@test.com",
                new AntigravityAccountPlan("pro", "Pro", 20)),
            Account("b@test.com",
                new AntigravityAccountPlan("pro", "Pro", 20)),
            Account("c@test.com",
                new AntigravityAccountPlan("ultra", "Ultra", 200)),
        };
        var agg = AntigravityAggregation.Aggregate(accounts);
        Assert.NotNull(agg);
        Assert.Equal("multi", agg.Plan);
        Assert.Equal("Ultra + Pro ×2", agg.PlanLabel);
        Assert.Equal(240, agg.MonthlyPriceUsd);
        Assert.Equal(3, agg.AccountsPriced);
    }

    [Fact]
    public void TestApplyPendingTargetsCorrectEmail()
    {
        var accounts = new[]
        {
            Account("alex@example.com", new AntigravityAccountPlan("google_ai_ultra", "Ultra", 250)),
            Account("bob+work@example.com", new AntigravityAccountPlan("google_ai_pro", "Pro", 20)),
        };
        var known = KnownPlan.FallbackPlans["antigravity"];
        var pending = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["bob+work@example.com"] = "google_ai_ultra",
        };
        var applied = AntigravityAggregation.ApplyPending(accounts, pending, known);
        Assert.Equal("google_ai_ultra", applied[0].Plan?.Plan);
        Assert.Equal("google_ai_ultra", applied[1].Plan?.Plan);
    }

    [Fact]
    public void TestRemainingPendingClearsWhenPendingKeyIsLowercase()
    {
        var accounts = new[]
        {
            Account("Alice.Doe@gmail.com", new AntigravityAccountPlan("google_ai_pro", "Pro", 20)),
        };
        var pending = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["alice.doe@gmail.com"] = "google_ai_pro",
        };
        var remaining = AntigravityAggregation.RemainingPending(pending, accounts);
        Assert.Empty(remaining);
    }

    [Fact]
    public void TestApplyPendingMatchesLowercasePendingKey()
    {
        var accounts = new[]
        {
            Account("First.Last+tag@Company.co.uk",
                new AntigravityAccountPlan("google_ai_pro", "Pro", 20)),
        };
        var known = KnownPlan.FallbackPlans["antigravity"];
        var pending = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["first.last+tag@company.co.uk"] = "google_ai_ultra",
        };
        var applied = AntigravityAggregation.ApplyPending(accounts, pending, known);
        Assert.Equal("google_ai_ultra", applied[0].Plan?.Plan);
    }
}