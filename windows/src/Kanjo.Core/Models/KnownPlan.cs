using System.Text.Json;

namespace Kanjo.Core;

/// <summary>从 `kanjo config plans --json` 读取的已知套餐档位。</summary>
public sealed record KnownPlan(string Key, string Label, double? MonthlyPriceUsd)
{
    public string Id => Key;

    public static KnownPlan Decode(JsonElement e, string path) => new(
        J.String(e, "key", path),
        J.String(e, "label", path),
        J.NumberOrNull(e, "monthly_price_usd", path));

    public static readonly IReadOnlyDictionary<string, IReadOnlyList<KnownPlan>> FallbackPlans =
        new Dictionary<string, IReadOnlyList<KnownPlan>>(StringComparer.Ordinal)
        {
            ["claude"] =
            [
                new KnownPlan("pro", "Claude Pro", 20.0),
                new KnownPlan("max_5x", "Claude Max 5x", 100.0),
                new KnownPlan("max_20x", "Claude Max 20x", 200.0),
            ],
            ["codex"] =
            [
                new KnownPlan("plus", "ChatGPT Plus", 20.0),
                new KnownPlan("pro", "ChatGPT Pro", 200.0),
                new KnownPlan("business", "ChatGPT Business", 30.0),
                new KnownPlan("enterprise", "ChatGPT Enterprise", 60.0),
                new KnownPlan("team", "ChatGPT Team", 25.0),
                new KnownPlan("edu", "ChatGPT Edu", 20.0),
            ],
            ["antigravity"] =
            [
                new KnownPlan("pro", "Antigravity Pro", 20.0),
            ],
            ["grok"] =
            [
                new KnownPlan("supergrok", "SuperGrok", 30.0),
                new KnownPlan("premium_plus", "X Premium+", 16.0),
                new KnownPlan("premium", "X Premium", 8.0),
                new KnownPlan("basic", "X Basic", 3.0),
            ],
            ["copilot"] =
            [
                new KnownPlan("free", "Copilot Free", 0.0),
                new KnownPlan("pro", "Copilot Pro", 10.0),
                new KnownPlan("individual", "Copilot Pro", 10.0),
                new KnownPlan("pro_plus", "Copilot Pro+", 39.0),
                new KnownPlan("business", "Copilot Business", 19.0),
                new KnownPlan("enterprise", "Copilot Enterprise", 39.0),
            ],
            ["minimax"] =
            [
                new KnownPlan("starter", "MiniMax Coding Plan Starter", 10.0),
                new KnownPlan("coding_plan_starter", "MiniMax Coding Plan Starter", 10.0),
                new KnownPlan("plus", "MiniMax Coding Plan Plus", 20.0),
                new KnownPlan("coding_plan_plus", "MiniMax Coding Plan Plus", 20.0),
                new KnownPlan("max", "MiniMax Coding Plan Max", 50.0),
                new KnownPlan("coding_plan_max", "MiniMax Coding Plan Max", 50.0),
            ],
            ["qwen"] =
            [
                new KnownPlan("coding_plan", "Qwen Coding Plan Pro", 50.0),
                new KnownPlan("pro", "Qwen Coding Plan Pro", 50.0),
            ],
            ["commandcode"] =
            [
                new KnownPlan("go", "Command Code Go", 1.0),
                new KnownPlan("goat", "Command Code GOAT", 10.0),
                new KnownPlan("provider", "Command Code Provider", null),
                new KnownPlan("pro", "Command Code Pro", null),
                new KnownPlan("max", "Command Code Max", null),
            ],
            ["opencode"] =
            [
                new KnownPlan("go", "OpenCode Go", 10.0),
            ],
        };
}

public sealed record SaveFields(string Plan, double? MonthlyPriceUsd, int? AnchorDay);

public static class SubscriptionPlanHelper
{
    /// <summary>
    /// 决定保存哪些字段：
    /// - list price: 选中的已知档位有公开标价，且输入的月费等于标价（或未填写），则不写价格覆盖（MonthlyPriceUsd: null），由 CLI 自动使用标价。
    /// - override: 选中的已知档位有标价但用户修改了价格，或者已知档位本身无标价，保存用户输入的月费。
    /// - custom: 自定义档位（Other…），始终保存用户输入的月费。
    /// </summary>
    public static SaveFields FieldsToSave(
        string plan,
        bool isCustom,
        double? enteredPrice,
        double? listPrice,
        int? anchorDay)
    {
        var trimmedPlan = plan.Trim();
        if (isCustom)
        {
            return new SaveFields(trimmedPlan, enteredPrice, anchorDay);
        }
        if (listPrice is not { } list)
        {
            // 已知套餐但无标价，必须保存输入的价格
            return new SaveFields(trimmedPlan, enteredPrice, anchorDay);
        }
        if (enteredPrice is { } entered && Math.Abs(entered - list) >= 0.005)
        {
            // 输入价格与标价不同，保存覆盖
            return new SaveFields(trimmedPlan, entered, anchorDay);
        }
        // 输入价格与标价一致，无需保存月费覆盖
        return new SaveFields(trimmedPlan, null, anchorDay);
    }

    public static SaveFields FieldsToSave(string planKey, double? enteredPrice, int? anchorDay, KnownPlan? knownPlan) =>
        FieldsToSave(planKey, knownPlan is null, enteredPrice, knownPlan?.MonthlyPriceUsd, anchorDay);

    public static SaveFields FieldsToSave(
        string planKey,
        bool isCustom,
        double? enteredPrice,
        int? anchorDay,
        IReadOnlyList<KnownPlan>? knownPlans = null)
    {
        var matching = isCustom ? null : knownPlans?.FirstOrDefault(p => p.Key == planKey);
        return FieldsToSave(planKey, isCustom || matching is null, enteredPrice, matching?.MonthlyPriceUsd, anchorDay);
    }
}
