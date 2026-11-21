using System.Text.Json;

namespace Kanjo.Core;

public sealed record AntigravityUnknown(double Tokens, double CostUsd)
{
    public static AntigravityUnknown Decode(JsonElement e, string path) => new(
        J.Number(e, "tokens", path),
        J.Number(e, "cost_usd", path));
}

public sealed record AntigravityAccountPlan(string Plan, string PlanLabel, double? MonthlyPriceUsd)
{
    public static AntigravityAccountPlan Decode(JsonElement e, string path) => new(
        J.String(e, "plan", path),
        J.String(e, "plan_label", path),
        J.NumberOrNull(e, "monthly_price_usd", path));
}

public sealed record AntigravityAccountQuota(string CapturedAt, RoList<ExtraQuotaWindow> Windows)
{
    public static AntigravityAccountQuota Decode(JsonElement e, string path) => new(
        J.String(e, "captured_at", path),
        J.ArrayOrNull(e, "windows", path) is { } w
            ? new RoList<ExtraQuotaWindow>(J.List(w, J.Child(path, "windows"), ExtraQuotaWindow.Decode))
            : RoList<ExtraQuotaWindow>.Empty);
}

public sealed record AntigravityAccount(
    string Email,
    long Tokens,
    double CostUsd,
    long Messages,
    string? LastSeen,
    bool SavedLogin,
    AntigravityAccountPlan? Plan,
    AntigravityAccountQuota? Quota)
{
    public static AntigravityAccount Decode(JsonElement e, string path) => new(
        J.String(e, "email", path),
        J.Long(e, "tokens", path),
        J.Number(e, "cost_usd", path),
        J.LongOrNull(e, "messages", path) ?? 0,
        J.StringOrNull(e, "last_seen", path),
        J.BoolOrNull(e, "saved_login", path) ?? false,
        J.Optional(e, "plan") is { } p ? AntigravityAccountPlan.Decode(p, J.Child(path, "plan")) : null,
        J.Optional(e, "quota") is { } q ? AntigravityAccountQuota.Decode(q, J.Child(path, "quota")) : null);
}

public sealed record AntigravityAccounts(
    string WindowStart,
    string WindowKind,
    string? Current,
    RoList<AntigravityAccount> Accounts,
    AntigravityUnknown Unknown,
    RoList<AntigravityAccountDay>? ByDay)
{
    public static AntigravityAccounts Decode(JsonElement e, string path) => new(
        J.String(e, "window_start", path),
        J.String(e, "window_kind", path),
        J.StringOrNull(e, "current", path),
        J.ArrayOrNull(e, "accounts", path) is { } a
            ? new RoList<AntigravityAccount>(J.List(a, J.Child(path, "accounts"), AntigravityAccount.Decode))
            : RoList<AntigravityAccount>.Empty,
        J.Optional(e, "unknown") is { } u
            ? AntigravityUnknown.Decode(u, J.Child(path, "unknown"))
            : new AntigravityUnknown(0, 0),
        J.ArrayOrNull(e, "by_day", path) is { } d
            ? new RoList<AntigravityAccountDay>(J.List(d, J.Child(path, "by_day"), AntigravityAccountDay.Decode))
            : null);
}

public sealed record AntigravityAccountDay(
    string Day,
    string? Email,
    long Tokens,
    double CostUsd,
    long Messages)
{
    public static AntigravityAccountDay Decode(JsonElement e, string path) => new(
        J.String(e, "day", path),
        J.StringOrNull(e, "email", path),
        J.Long(e, "tokens", path),
        J.Number(e, "cost_usd", path),
        J.LongOrNull(e, "messages", path) ?? 0);
}