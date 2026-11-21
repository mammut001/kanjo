namespace Kanjo.Core;

/// <summary>
/// Manual overrides in overrides.json are limited to 1…28; detected subscription dates may be 29–31.
/// </summary>
public static class SubscriptionRenewalDay
{
    public const int ManualMax = 28;

    /// <summary>Value for the settings stepper (always within the manual override range).</summary>
    public static int StepperValue(int? anchorDay) =>
        Math.Min(ManualMax, Math.Max(1, anchorDay ?? 1));

    /// <summary>
    /// Detected anchors above <see cref="ManualMax"/> follow the real subscription calendar
    /// (e.g. day 31 → Feb 28/29).
    /// </summary>
    public static bool IsDetectedHighAnchor(Subscription sub) =>
        sub.AnchorDay is { } day && day > ManualMax && sub.CycleSource != "manual";

    /// <summary>Applying the stepper would wrongly clamp a detected high anchor down to 28.</summary>
    public static bool AllowsManualStepper(Subscription? sub) =>
        sub is null || !IsDetectedHighAnchor(sub);
}
