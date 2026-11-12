using Xunit;

namespace Kanjo.Core.Tests;

public sealed class KnownPlanTests : KanjoTestCase
{
    [Fact]
    public void TestDecodeKnownPlansJson()
    {
        const string json = """
        {
          "claude": [
            { "key": "max_20x", "label": "Claude Max 20x", "monthly_price_usd": 200.0 },
            { "key": "pro", "label": "Claude Pro", "monthly_price_usd": 20.0 }
          ],
          "grok": [
            { "key": "supergrok", "label": "SuperGrok", "monthly_price_usd": 30.0 },
            { "key": "premium_plus", "label": "X Premium+", "monthly_price_usd": null }
          ]
        }
        """;

        var decoded = ReportDecoder.DecodeKnownPlans(System.Text.Encoding.UTF8.GetBytes(json));
        Assert.Equal(["claude", "grok"], decoded.Keys.OrderBy(k => k, StringComparer.Ordinal).ToArray());

        var claudePlans = decoded["claude"];
        Assert.Equal(2, claudePlans.Count);
        Assert.Equal("max_20x", claudePlans[0].Id);
        Assert.Equal("max_20x", claudePlans[0].Key);
        Assert.Equal("Claude Max 20x", claudePlans[0].Label);
        Assert.Equal(200.0, claudePlans[0].MonthlyPriceUsd);

        Assert.Equal("pro", claudePlans[1].Key);
        Assert.Equal("Claude Pro", claudePlans[1].Label);
        Assert.Equal(20.0, claudePlans[1].MonthlyPriceUsd);

        var grokPlans = decoded["grok"];
        Assert.Equal(2, grokPlans.Count);
        Assert.Equal("supergrok", grokPlans[0].Key);
        Assert.Equal(30.0, grokPlans[0].MonthlyPriceUsd);
        Assert.Equal("premium_plus", grokPlans[1].Key);
        Assert.Equal("X Premium+", grokPlans[1].Label);
        Assert.Null(grokPlans[1].MonthlyPriceUsd);
    }

    [Fact]
    public void TestHelperListPriceDecidesNilMonthlyPrice()
    {
        var plan = new KnownPlan("plus", "ChatGPT Plus", 20.0);

        // User leaves price at list price: MonthlyPriceUsd should be nil (not saved to overrides)
        var fieldsExact = SubscriptionPlanHelper.FieldsToSave("plus", 20.0, 15, plan);
        Assert.Equal(new SaveFields("plus", null, 15), fieldsExact);

        // Nil entered price on known priced plan defaults to list price -> nil override
        var fieldsNil = SubscriptionPlanHelper.FieldsToSave("plus", null, 1, plan);
        Assert.Equal(new SaveFields("plus", null, 1), fieldsNil);

        // Decimal list price (e.g. Google AI Pro $19.99)
        var ultraPlan = new KnownPlan("google_ai_pro", "Google AI Pro", 19.99);
        var fieldsDecimal = SubscriptionPlanHelper.FieldsToSave("google_ai_pro", 19.99, 8, ultraPlan);
        Assert.Equal(new SaveFields("google_ai_pro", null, 8), fieldsDecimal);
    }

    [Fact]
    public void TestHelperOverridePriceSavesEnteredPrice()
    {
        var plan = new KnownPlan("plus", "ChatGPT Plus", 20.0);

        // User overrides list price 20.0 with 15.0
        var fieldsOverride = SubscriptionPlanHelper.FieldsToSave("plus", 15.0, 8, plan);
        Assert.Equal(new SaveFields("plus", 15.0, 8), fieldsOverride);

        // Known plan without list price -> price must be saved
        var unpricedPlan = new KnownPlan("premium_plus", "X Premium+", null);
        var fieldsUnpriced = SubscriptionPlanHelper.FieldsToSave("premium_plus", 25.0, 10, unpricedPlan);
        Assert.Equal(new SaveFields("premium_plus", 25.0, 10), fieldsUnpriced);
    }

    [Fact]
    public void TestHelperCustomPlanAlwaysSavesPrice()
    {
        // Custom plan (nil knownPlan)
        var fieldsCustom = SubscriptionPlanHelper.FieldsToSave("custom_enterprise_plan", 150.0, 28, null);
        Assert.Equal(new SaveFields("custom_enterprise_plan", 150.0, 28), fieldsCustom);

        // Custom plan with whitespace
        var fieldsWhitespace = SubscriptionPlanHelper.FieldsToSave("  my plan  ", true, 12.0, null, 5);
        Assert.Equal(new SaveFields("my plan", 12.0, 5), fieldsWhitespace);

        // Passing knownPlans list with isCustom = true ignores matches
        var plans = new[] { new KnownPlan("plus", "ChatGPT Plus", 20.0) };
        var fieldsCustomFlag = SubscriptionPlanHelper.FieldsToSave("plus", true, 20.0, 8, plans);
        Assert.Equal(new SaveFields("plus", 20.0, 8), fieldsCustomFlag);
    }

    [Fact]
    public void TestHelperLookupFromKnownPlansList()
    {
        var plans = new[]
        {
            new KnownPlan("pro", "Claude Pro", 20.0),
            new KnownPlan("max_5x", "Claude Max 5x", 100.0),
        };

        // List price match
        var listResult = SubscriptionPlanHelper.FieldsToSave("pro", false, 20.0, 14, plans);
        Assert.Equal(new SaveFields("pro", null, 14), listResult);

        // Override price match
        var overrideResult = SubscriptionPlanHelper.FieldsToSave("max_5x", false, 80.0, 14, plans);
        Assert.Equal(new SaveFields("max_5x", 80.0, 14), overrideResult);

        // Unknown plan in list treated as custom
        var unknownResult = SubscriptionPlanHelper.FieldsToSave("unknown_tier", false, 45.0, 14, plans);
        Assert.Equal(new SaveFields("unknown_tier", 45.0, 14), unknownResult);
    }

    [Fact]
    public void TestFallbackPlansCoverKnownAgents()
    {
        Assert.Equal(3, KnownPlan.FallbackPlans["claude"].Count);
        Assert.Equal("Claude Max 5x", KnownPlan.FallbackPlans["claude"][1].Label);
        Assert.Null(KnownPlan.FallbackPlans["commandcode"][2].MonthlyPriceUsd);
        Assert.DoesNotContain("future_agent", KnownPlan.FallbackPlans.Keys);
    }
}
