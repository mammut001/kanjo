using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 设置页的纯逻辑：订阅编辑表单的校验与字段计算、agent 列表顺序、家庭范围文案、
/// Windows 专属文案覆盖、凭据存储的假实现。
/// </summary>
public sealed class SettingsValidationTests : KanjoTestCase
{
    private static readonly IReadOnlyList<KnownPlan> ClaudePlans = KnownPlan.FallbackPlans["claude"];

    [Fact]
    public void TestPlanIsRequired()
    {
        var (fields, error) = SubscriptionPlanForm.Validate(SubscriptionPlanForm.OtherPlanTag, "   ", "",
            hasKnownPlans: false, null, 1);
        Assert.Null(fields);
        Assert.Equal("Plan name is required.", error);
    }

    [Fact]
    public void TestPriceIsRequiredWhenPlanHasNoListPrice()
    {
        var (fields, error) = SubscriptionPlanForm.Validate(SubscriptionPlanForm.OtherPlanTag, "provider", "",
            hasKnownPlans: false, null, 1);
        Assert.Null(fields);
        Assert.Equal("Price is required for this plan.", error);
    }

    [Fact]
    public void TestInvalidPriceIsRejected()
    {
        foreach (var bad in new[] { "-1", "abc", "NaN", "Infinity", "1,5" })
        {
            var (fields, error) = SubscriptionPlanForm.Validate(SubscriptionPlanForm.OtherPlanTag, "claude", bad,
                hasKnownPlans: false, null, 5);
            Assert.Null(fields);
            Assert.Equal("Price must be a non-negative number.", error);
        }
    }

    [Fact]
    public void TestKnownPlanKeepsListPriceWhenUnchanged()
    {
        // 选中的已知档位标价 $100，输入框空着 → 用标价，且不写月费覆盖（null）。
        var (fields, error) = SubscriptionPlanForm.Validate("max_5x", "", "", hasKnownPlans: true, ClaudePlans, 12);
        Assert.Null(error);
        Assert.NotNull(fields);
        Assert.Equal("max_5x", fields!.Plan);
        Assert.Null(fields.MonthlyPriceUsd);
        Assert.Equal(12, fields.AnchorDay);
    }

    [Fact]
    public void TestKnownPlanSavesOverrideWhenPriceDiffers()
    {
        var (fields, error) = SubscriptionPlanForm.Validate("max_5x", "", "125", hasKnownPlans: true,
            ClaudePlans, 3);
        Assert.Null(error);
        Assert.Equal(125, fields!.MonthlyPriceUsd);
    }

    [Fact]
    public void TestCustomPlanAlwaysSavesEnteredPrice()
    {
        var (fields, error) = SubscriptionPlanForm.Validate(SubscriptionPlanForm.OtherPlanTag, "  team-seat  ",
            "42.5", hasKnownPlans: true, ClaudePlans, 28);
        Assert.Null(error);
        Assert.Equal("team-seat", fields!.Plan);
        Assert.Equal(42.5, fields.MonthlyPriceUsd);
        Assert.Equal(28, fields.AnchorDay);
    }

    [Fact]
    public void TestDayIsDroppedWhenOutOfRange()
    {
        var (fields, _) = SubscriptionPlanForm.Validate("max_5x", "", "", hasKnownPlans: true, ClaudePlans, 0);
        Assert.Null(fields!.AnchorDay);
        var (fields2, _) = SubscriptionPlanForm.Validate("max_5x", "", "", hasKnownPlans: true, ClaudePlans, 29);
        Assert.Null(fields2!.AnchorDay);
    }

    [Fact]
    public void TestFormatPriceDropsTrailingZero()
    {
        Assert.Equal("100", SubscriptionPlanForm.FormatPrice(100.0));
        Assert.Equal("19.99", SubscriptionPlanForm.FormatPrice(19.99));
    }

    [Fact]
    public void TestMenuLabelIncludesPrice()
    {
        Assert.Equal("Claude Max 5x · $100/mo", SubscriptionPlanForm.MenuLabel(ClaudePlans.First(p => p.Key == "max_5x")));
        Assert.Equal("Command Code Pro",
            SubscriptionPlanForm.MenuLabel(KnownPlan.FallbackPlans["commandcode"].First(p => p.Key == "pro")));
    }

    [Fact]
    public void TestSelectionRoundTripsKnownAndCustomPlans()
    {
        var sub = new Subscription("max_5x", "Claude Max 5x", 100, "2026-10-01", "2026-11-01", 5,
            "subscription_cycle", false, "detected", null);
        var (key, custom) = SubscriptionPlanForm.SyncSelection(sub, ClaudePlans);
        Assert.Equal("max_5x", key);
        Assert.Equal("", custom);

        var customSub = sub with { Plan = "weird-plan", PlanLabel = "Weird Plan" };
        var (customKey, customText) = SubscriptionPlanForm.SyncSelection(customSub, ClaudePlans);
        Assert.Equal(SubscriptionPlanForm.OtherPlanTag, customKey);
        Assert.Equal("weird-plan", customText);

        var noPlans = SubscriptionPlanForm.SyncSelection(null, []);
        Assert.Equal(SubscriptionPlanForm.OtherPlanTag, noPlans.PlanKey);
    }

    [Fact]
    public void TestPriceForSelectionFollowsPlan()
    {
        Assert.Equal("100", SubscriptionPlanForm.PriceForSelection("max_5x", null, ClaudePlans));
        Assert.Equal("", SubscriptionPlanForm.PriceForSelection(SubscriptionPlanForm.OtherPlanTag, null, ClaudePlans));
    }

    [Fact]
    public void TestSaveArgumentsOrderMatchesMac()
    {
        // 价格 → 档位 → （未给价格时清覆盖）→ 续费日
        var args = ConfigDataSource.SubscriptionArguments("claude", "max_5x", 100, 5);
        Assert.Equal(3, args.Count);
        Assert.Equal(["config", "set", "subscriptions.claude.monthly_price_usd", "100"], args[0]);
        Assert.Equal(["config", "set", "subscriptions.claude.plan", "max_5x"], args[1]);
        Assert.Equal(["config", "set", "subscriptions.claude.anchor_day", "5"], args[2]);

        var noPrice = ConfigDataSource.SubscriptionArguments("claude", "max_5x", null, null);
        Assert.Equal(2, noPrice.Count);
        Assert.Equal(["config", "unset", "subscriptions.claude.monthly_price_usd"], noPrice[1]);
    }

    [Fact]
    public void TestSubscriptionAgentListOrder()
    {
        var report = LoadFixture();
        var agents = SettingsAgentList.SubscriptionAgents(report);
        // 前面是报告里出现且有订阅的 agent（按花费降序）：claude, codex, antigravity ...
        Assert.Equal("claude", agents[0]);
        Assert.Equal("codex", agents[1]);
        Assert.Contains("copilot", agents);
        // 固定顺序里的 agent 都在后面补齐。
        Assert.Contains("qwenwork", agents);
        Assert.Equal(agents.Count, agents.Distinct(StringComparer.Ordinal).Count());
    }

    [Fact]
    public void TestSubscriptionAgentListAppendsEditingAgent()
    {
        var report = LoadFixture();
        var agents = SettingsAgentList.SubscriptionAgents(report, "brand-new");
        Assert.Equal("brand-new", agents[^1]);
    }

    [Fact]
    public void TestQuotaAgentListOnlyIncludesSubscribedOrQuotaAgents()
    {
        var report = LoadFixture();
        var agents = SettingsAgentList.QuotaAgents(report);
        Assert.All(agents, a => Assert.True(
            report.Subscriptions?.ContainsKey(a) == true || report.QuotaWindows?.ContainsKey(a) == true));
        Assert.Contains("claude", agents);
        Assert.DoesNotContain("opencode", agents);
    }

    [Fact]
    public void TestFamilyScopeText()
    {
        Assert.Equal("Antigravity only", FamilyScopeText.Make(null));
        Assert.Equal("All agents", FamilyScopeText.Make(new FamilyConfig(null, new RoList<string>(["all"]))));
        Assert.Equal("All agents · Since 2026-10-01",
            FamilyScopeText.Make(new FamilyConfig("2026-10-01", new RoList<string>(["all"]))));
        Assert.Equal("Antigravity only",
            FamilyScopeText.Make(new FamilyConfig(null, new RoList<string>(["antigravity"]))));
    }

    [Fact]
    public void TestWeeklyResetParsing()
    {
        var quota = new QuotaWindow("2026-10-31T10:40:00Z", 168, 40, null, null, null, "live", null);
        var (weekday, time) = QuotaResetValue.Parse(quota, TimeZoneInfo.Utc);
        Assert.Equal("sat", weekday);
        Assert.Equal("10:40", time);

        var (fallbackDay, fallbackTime) = QuotaResetValue.Parse(null, TimeZoneInfo.Utc);
        Assert.Equal("tue", fallbackDay);
        Assert.Equal("05:00", fallbackTime);
    }

    [Fact]
    public void TestWindowsOnlyStringsOverrideMacTable()
    {
        Assert.True(WindowsL10n.HasOverride("disk.card.move_button"));
        Assert.Equal("Move to Recycle Bin", WindowsL10n.Tr("disk.card.move_button"));
        Assert.Equal("Show in Explorer", WindowsL10n.Tr("context.show_in_explorer"));
        // 没有覆盖的 key 仍然走 Mac 表（英文）。
        Assert.Equal("Settings", WindowsL10n.Tr("settings.title"));
    }

    [Fact]
    public void TestWindowsOnlyStringsLocalized()
    {
        SetLanguage("zh-Hans");
        Assert.Equal("移到回收站", WindowsL10n.Tr("disk.card.move_button"));
        SetLanguage("fr");
        Assert.Equal("Mettre à la corbeille", WindowsL10n.Tr("disk.card.move_button"));
        SetLanguage("en");
    }

    [Fact]
    public void TestInMemoryTokenStorage()
    {
        var storage = new InMemoryFamilyTokenStorage();
        Assert.Equal("KanjoFamilyReport", storage.Target);
        Assert.False(storage.HasToken());
        Assert.Null(storage.LoadToken());
        Assert.True(storage.SaveToken("abc"));
        Assert.True(storage.HasToken());
        Assert.Equal("abc", storage.LoadToken());
        Assert.True(storage.DeleteToken());
        Assert.False(storage.HasToken());
        Assert.Null(storage.LoadToken());
    }

    [Fact]
    public void TestCredentialStorageFallsBackOffWindows()
    {
        var storage = new WindowsCredentialFamilyTokenStorage("KanjoFamilyReport");
        Assert.Equal("KanjoFamilyReport", storage.Target);
        if (!OperatingSystem.IsWindows())
        {
            // 非 Windows 开发运行：内存假实现，绝不碰真实凭据。
            Assert.True(storage.SaveToken("token"));
            Assert.True(storage.HasToken());
            Assert.Equal("token", storage.LoadToken());
            Assert.True(storage.DeleteToken());
            Assert.False(storage.HasToken());
        }
    }

    [Fact]
    public void TestReportActivityExtractsErrorMessage()
    {
        Assert.Null(ReportActivity.ExtractError(null));
        Assert.Null(ReportActivity.ExtractError("{\"status\": \"sent\"}"));
        Assert.Equal("boom",
            ReportActivity.ExtractError("{\"status\": \"error\", \"message\": \"boom\"}"));
        Assert.Equal("boom",
            ReportActivity.ExtractError("{\"status\":\"error\",\"message\":\"boom\"}"));
        // 不是合法 JSON：整段当错误文本（和 Mac 的 lastError 回退一致）。
        const string malformed = "{\"status\": \"error\", \"message\": not json";
        Assert.Equal(malformed, ReportActivity.ExtractError(malformed));
    }

    [Fact]
    public void TestReportActivityPersistsTimestamps()
    {
        var activity = new ReportActivity(Settings, SettingsKeys.PublishLastAttemptAt,
            SettingsKeys.PublishLastSuccessAt, SettingsKeys.PublishLastResult);
        var now = Ts("2026-10-25T10:00:00Z");
        activity.RecordSuccess(now, "{\"status\": \"sent\"}");
        Assert.Equal(now, activity.LastSuccessAt);
        Assert.Null(activity.LastError);
        Assert.Equal("{\"status\": \"sent\"}", activity.LastResult);

        var reloaded = new ReportActivity(Settings, SettingsKeys.PublishLastAttemptAt,
            SettingsKeys.PublishLastSuccessAt, SettingsKeys.PublishLastResult);
        Assert.Equal(now, reloaded.LastSuccessAt);
        Assert.Equal(now, reloaded.LastAttemptAt);
    }
}
