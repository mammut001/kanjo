using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>共享 .strings 里带显式序号（%1$@ / %2$@）的模板，Windows 也要按调用方的参数顺序填。</summary>
public sealed class LocalizationArgumentOrderTests : KanjoTestCase
{
    [Fact]
    public void CycleShareChineseUsesPercentThenPlanArguments()
    {
        Assert.Equal("此仓库：占本账期 Claude Max 5x 用量的 37%",
            Kanjo.Core.L10n.TrL("zh-Hans", "project.cycle_share", "37%", "Claude Max 5x"));
        Assert.Equal("This repo: 37% of your Claude Max 5x usage this cycle",
            Kanjo.Core.L10n.TrL("en", "project.cycle_share", "37%", "Claude Max 5x"));
    }
}
