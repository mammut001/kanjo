using Xunit;

namespace Kanjo.Core.Tests;

public sealed class SubscriptionRenewalDayTests : KanjoTestCase
{
    private static Subscription Sub(int? anchorDay, string cycleSource, string source = "detected") =>
        new("pro", "Pro", 20,
            "2026-01-31T00:00:00Z", "2026-03-01T00:00:00Z",
            anchorDay, cycleSource, false, source, null);

    [Fact]
    public void TestDetectedAnchor31IsNotStepperClamped()
    {
        var s = Sub(31, "subscription_date");
        Assert.True(SubscriptionRenewalDay.IsDetectedHighAnchor(s));
        Assert.False(SubscriptionRenewalDay.AllowsManualStepper(s));
        Assert.Equal(28, SubscriptionRenewalDay.StepperValue(31));
    }

    [Fact]
    public void TestManualAnchor31IsSteppable()
    {
        var s = Sub(31, "manual", "manual");
        Assert.False(SubscriptionRenewalDay.IsDetectedHighAnchor(s));
        Assert.True(SubscriptionRenewalDay.AllowsManualStepper(s));
    }

    [Fact]
    public void TestManualOverrideWithinRange()
    {
        Assert.Equal(15, SubscriptionRenewalDay.StepperValue(15));
        Assert.True(SubscriptionRenewalDay.AllowsManualStepper(Sub(15, "manual", "manual")));
    }

    [Fact]
    public void TestSaveAnchorArgumentsRejectsClampingDetectedDayTo28()
    {
        // Applying the display stepper while a detected day is 31 must not silently write 28.
        var detected = Sub(31, "subscription_date");
        Assert.False(SubscriptionRenewalDay.AllowsManualStepper(detected));
        // Manual override path still accepts 1…28 via ConfigCommand.
        Assert.Equal(["config", "set", "subscriptions.claude.anchor_day", "28"],
            ConfigCommand.Arguments("claude", 28));
    }
}
