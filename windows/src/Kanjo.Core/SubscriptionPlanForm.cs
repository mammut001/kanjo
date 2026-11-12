using System.Globalization;

namespace Kanjo.Core;

/// <summary>
/// 订阅编辑表单的纯逻辑（对应 SettingsView 里的 <c>SubscriptionSettingsRow</c>）：
/// 选中档位的回填、价格格式化、校验、以及要保存的字段。
/// </summary>
public static class SubscriptionPlanForm
{
    /// <summary>「Other…」在档位菜单里的 tag（和 Mac 的 <c>__custom_other__</c> 一致）。</summary>
    public const string OtherPlanTag = "__custom_other__";

    /// <summary>已知档位的菜单标题：`Claude Max 5x · $100/mo`；没有标价时只写名字。</summary>
    public static string MenuLabel(KnownPlan plan, string currency = "USD") =>
        plan.MonthlyPriceUsd is { } price ? $"{plan.Label} · {Fmt.PerMonth(price, currency)}" : plan.Label;

    /// <summary>价格输入框的初始 / 回填文本：整数不带小数。</summary>
    public static string FormatPrice(double price) =>
        price == Math.Round(price)
            ? ((long)Math.Round(price)).ToString(CultureInfo.InvariantCulture)
            : price.ToString(CultureInfo.InvariantCulture);

    /// <summary>
    /// 打开编辑态时回填：当前档位在已知档位里就选中它，否则用「Other…」+ 自由文本。
    /// </summary>
    public static (string PlanKey, string CustomText) InitialSelection(Subscription? sub, IReadOnlyList<KnownPlan>? plans)
    {
        var list = plans ?? [];
        var current = sub?.Plan ?? "";
        if (current.Length > 0)
        {
            var matching = list.FirstOrDefault(p => p.Key == current)
                           ?? list.FirstOrDefault(p => p.Label == sub?.PlanLabel);
            if (matching is not null) return (matching.Key, "");
            return (OtherPlanTag, current);
        }
        if (list.Count > 0) return (list[0].Key, "");
        return (sub?.Plan ?? OtherPlanTag, sub?.Plan ?? sub?.PlanLabel ?? "");
    }

    /// <summary>显示态切回编辑态时的回填（没有订阅时选第一个已知档位）。</summary>
    public static (string PlanKey, string CustomText) SyncSelection(Subscription? sub, IReadOnlyList<KnownPlan>? plans)
    {
        var list = plans ?? [];
        var current = sub?.Plan ?? "";
        if (current.Length > 0)
        {
            var matching = list.FirstOrDefault(p => p.Key == current)
                           ?? list.FirstOrDefault(p => p.Label == sub?.PlanLabel);
            return matching is not null ? (matching.Key, "") : (OtherPlanTag, current);
        }
        if (list.Count > 0) return (list[0].Key, "");
        return (OtherPlanTag, sub?.PlanLabel ?? "");
    }

    /// <summary>切换档位后价格输入框的内容（Other… 时沿用当前价格）。</summary>
    public static string PriceForSelection(string planKey, Subscription? sub, IReadOnlyList<KnownPlan>? plans)
    {
        if (planKey == OtherPlanTag)
        {
            return sub?.MonthlyPriceUsd is { } current ? FormatPrice(current) : "";
        }
        var matching = (plans ?? []).FirstOrDefault(p => p.Key == planKey);
        return matching?.MonthlyPriceUsd is { } list ? FormatPrice(list) : "";
    }

    /// <summary>校验 + 计算要写入 CLI 的字段。失败时返回错误文案（和 Mac 的 settings.error.* 一致）。</summary>
    public static (SaveFields? Fields, string? Error) Validate(
        string planKey,
        string customText,
        string priceText,
        bool hasKnownPlans,
        IReadOnlyList<KnownPlan>? plans,
        int day)
    {
        var isCustom = !hasKnownPlans || planKey == OtherPlanTag;
        var plan = isCustom ? customText.Trim() : planKey;
        if (plan.Length == 0) return (null, L10n.Tr("settings.error.plan_required"));

        var matching = hasKnownPlans ? (plans ?? []).FirstOrDefault(p => p.Key == planKey) : null;
        var listPrice = isCustom ? null : matching?.MonthlyPriceUsd;
        var priceRaw = priceText.Trim();

        double? entered = null;
        if (priceRaw.Length > 0)
        {
            if (!double.TryParse(priceRaw, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed) ||
                parsed < 0 || double.IsNaN(parsed) || double.IsInfinity(parsed))
            {
                return (null, L10n.Tr("settings.error.invalid_price"));
            }
            entered = parsed;
        }
        else if (listPrice is null)
        {
            return (null, L10n.Tr("settings.error.price_required"));
        }
        else
        {
            entered = listPrice;
        }

        var anchor = day is >= 1 and <= 28 ? day : (int?)null;
        return (SubscriptionPlanHelper.FieldsToSave(plan, isCustom, entered, listPrice, anchor), null);
    }

    /// <summary>保存字段 → 依次要跑的 config 参数（和 ConfigDataSource.setSubscription 一致）。</summary>
    public static IReadOnlyList<IReadOnlyList<string>> SaveArguments(string agent, SaveFields fields) =>
        ConfigDataSource.SubscriptionArguments(agent, fields.Plan, fields.MonthlyPriceUsd, fields.AnchorDay);
}

/// <summary>attribution 取值的解释（CONTRACT.md 第 5 节 + ATTRIBUTION.md 第 4 节），用作悬停提示。</summary>
public static class SessionAttributionInfo
{
    public static readonly IReadOnlyList<string> AllKnown = AttributionInfo.AllKnown;

    public static string Explanation(string value, double threshold, string? language = null)
    {
        var lang = language ?? L10n.CurrentLanguage;
        var pct = ((int)Math.Round(threshold * 100, MidpointRounding.AwayFromZero)).ToString(CultureInfo.InvariantCulture) + "%";
        return value switch
        {
            "dominant" => L10n.TrL(lang, "attribution.dominant", pct),
            "split" => L10n.TrL(lang, "attribution.split", pct),
            "cwd" => L10n.TrL(lang, "attribution.cwd"),
            "scratchpad" => L10n.TrL(lang, "attribution.scratchpad"),
            "override" => L10n.TrL(lang, "attribution.override"),
            "none" => L10n.TrL(lang, "attribution.none"),
            "excluded" => L10n.TrL(lang, "attribution.excluded"),
            _ => L10n.TrL(lang, "attribution.unknown", value),
        };
    }
}
