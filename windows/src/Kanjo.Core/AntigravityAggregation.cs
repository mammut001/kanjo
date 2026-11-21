namespace Kanjo.Core;

public sealed record AntigravityAccountAggregation(
    string Plan,
    string PlanLabel,
    double MonthlyPriceUsd,
    int AccountsPriced);

/// <summary>多账号 Antigravity 套餐合计（镜像 cli/kanjo/subscriptions.py）。</summary>
public static class AntigravityAggregation
{
    public static string NormalizedPlanKey(string? key)
    {
        var trimmed = key?.Trim() ?? "";
        return trimmed.Equals("none", StringComparison.OrdinalIgnoreCase) ? "" : trimmed;
    }

    public static AntigravityAccountAggregation? Aggregate(IReadOnlyList<AntigravityAccount> accounts)
    {
        var counts = new Dictionary<string, int>(StringComparer.Ordinal);
        var maxPrice = new Dictionary<string, double>(StringComparer.Ordinal);
        var distinctKeys = new HashSet<string>(StringComparer.Ordinal);
        var totalPrice = 0.0;
        var pricedCount = 0;

        foreach (var acc in accounts)
        {
            if (acc.Plan is not { } plan) continue;
            var key = NormalizedPlanKey(plan.Plan);
            if (key.Length == 0) continue;
            pricedCount++;
            distinctKeys.Add(plan.Plan);
            var label = plan.PlanLabel;
            var price = plan.MonthlyPriceUsd ?? 0.0;
            totalPrice += price;
            counts[label] = counts.GetValueOrDefault(label) + 1;
            maxPrice[label] = Math.Max(maxPrice.GetValueOrDefault(label), price);
        }

        if (pricedCount == 0) return null;

        var orderedLabels = counts.Keys.OrderByDescending(a => maxPrice.GetValueOrDefault(a))
            .ThenBy(a => a, StringComparer.Ordinal)
            .ToList();
        var parts = orderedLabels.Select(label =>
        {
            var count = counts[label];
            return count > 1 ? $"{label} ×{count}" : label;
        });

        return new AntigravityAccountAggregation(
            distinctKeys.Count == 1 ? distinctKeys.First() : "multi",
            string.Join(" + ", parts),
            Math.Round(totalPrice, 4),
            pricedCount);
    }

    public static IReadOnlyList<AntigravityAccount> ApplyPending(
        IReadOnlyList<AntigravityAccount> accounts,
        IReadOnlyDictionary<string, string> pending,
        IReadOnlyList<KnownPlan> knownPlans)
    {
        if (pending.Count == 0) return accounts;
        return accounts.Select(acc =>
        {
            if (!TryPending(pending, acc.Email, out var raw)) return acc;
            var key = NormalizedPlanKey(raw);
            if (key.Length == 0) return acc with { Plan = null };
            if (acc.Plan is { } current && current.Plan == key) return acc;
            if (knownPlans.FirstOrDefault(p => p.Key == key) is { } known)
            {
                return acc with
                {
                    Plan = new AntigravityAccountPlan(known.Key, known.Label, known.MonthlyPriceUsd),
                };
            }
            return acc with { Plan = new AntigravityAccountPlan(key, key, null) };
        }).ToList();
    }

    /// <summary>
    /// 新报告到达后仍需保留的 pending：报告已显示所选套餐的账号去掉；
    /// <paramref name="busy"/> 里的账号（还有写入排队或正在写）一律保留，免得旧报告把较新的选择冲掉。
    /// pending / busy 可能是小写 key（CLI 规范），账号邮箱大小写不一，按小写比对。
    /// </summary>
    public static Dictionary<string, string> RemainingPending(
        IReadOnlyDictionary<string, string> pending,
        IReadOnlyList<AntigravityAccount> accounts,
        IReadOnlySet<string>? busy = null)
    {
        if (pending.Count == 0) return new Dictionary<string, string>(pending, StringComparer.Ordinal);
        var remaining = new Dictionary<string, string>(pending, StringComparer.Ordinal);
        var busySet = busy ?? new HashSet<string>(StringComparer.Ordinal);
        foreach (var acc in accounts)
        {
            var normEmail = acc.Email.ToLowerInvariant();
            if (busySet.Contains(normEmail) || busySet.Contains(acc.Email)) continue;
            if (!TryPending(pending, acc.Email, out var wanted)) continue;
            if (NormalizedPlanKey(acc.Plan?.Plan) == NormalizedPlanKey(wanted))
            {
                remaining.Remove(normEmail);
                remaining.Remove(acc.Email);
            }
        }
        return remaining;
    }

    private static bool TryPending(IReadOnlyDictionary<string, string> pending, string email, out string value)
    {
        if (pending.TryGetValue(email, out value!)) return true;
        var lower = email.ToLowerInvariant();
        if (!lower.Equals(email, StringComparison.Ordinal) && pending.TryGetValue(lower, out value!))
        {
            return true;
        }
        value = "";
        return false;
    }
}