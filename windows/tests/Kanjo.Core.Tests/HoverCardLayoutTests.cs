using Xunit;

namespace Kanjo.Core.Tests;

public sealed class HoverCardLayoutTests : KanjoTestCase
{
    private static readonly HoverSize Container = new(360, 620);
    private static readonly HoverSize CardSize = new(200, 80);
    private const double Inset = 16;
    private const double Gap = 4;

    [Fact]
    public void TestBelowByDefault()
    {
        // 锚点位于面板上方，下方空间充裕
        var anchor = new HoverRect(30, 50, 100, 30);
        var pt = HoverCardLayout.Origin(anchor, CardSize, Container, Inset, Gap);

        Assert.Equal(30, pt.X);
        Assert.Equal(84, pt.Y); // anchor.MaxY (80) + gap (4)
        Assert.True(pt.X >= Inset);
        Assert.True(pt.X + CardSize.Width <= Container.Width - Inset);
        Assert.True(pt.Y + CardSize.Height <= Container.Height - Inset);
    }

    [Fact]
    public void TestFlipsAboveNearBottom()
    {
        var anchor = new HoverRect(30, 560, 100, 30);
        var pt = HoverCardLayout.Origin(anchor, CardSize, Container, Inset, Gap);
        Assert.Equal(30, pt.X);
        // 下方放不下（590 + 4 + 80 = 674 > 620 - 16），应向上翻转：560 - 4 - 80 = 476
        Assert.Equal(476, pt.Y);
        Assert.True(pt.Y >= Inset);
    }

    [Fact]
    public void TestClampedLeftAndRight()
    {
        var leftAnchor = new HoverRect(5, 100, 50, 20);
        Assert.Equal(Inset, HoverCardLayout.Origin(leftAnchor, CardSize, Container, Inset, Gap).X);

        var rightAnchor = new HoverRect(250, 100, 50, 20);
        var rightPt = HoverCardLayout.Origin(rightAnchor, CardSize, Container, Inset, Gap);
        // 容器宽 360 - 16 - 200 = 144
        Assert.Equal(144, rightPt.X);
        Assert.Equal(Container.Width - Inset, rightPt.X + CardSize.Width);
    }

    [Fact]
    public void TestStaysInsideWhenNeitherFits()
    {
        var smallContainer = new HoverSize(360, 180);
        var tallCard = new HoverSize(200, 100);
        var midAnchor = new HoverRect(30, 40, 100, 100);

        var pt = HoverCardLayout.Origin(midAnchor, tallCard, smallContainer, Inset, Gap);
        Assert.True(pt.Y >= Inset);
        Assert.True(pt.Y + tallCard.Height <= smallContainer.Height - Inset);
    }

    [Fact]
    public void TestHoverCardRowBuilderAgentRows()
    {
        var rawAgents = new (string Agent, string Label, double Cost, long Tokens)[]
        {
            ("cursor", "Cursor", 10.0, 100),
            ("claude", "Claude Code", 30.0, 300),
            ("zero", "Zero Cost", 0.0, 0),
            ("codegpt", "CodeGPT", 20.0, 200),
        };

        var rows = HoverCardRowBuilder.AgentRows(rawAgents);
        Assert.Equal(3, rows.Count);
        Assert.Equal("claude", rows[0].Id);
        Assert.Equal("codegpt", rows[1].Id);
        Assert.Equal("cursor", rows[2].Id);
        Assert.Equal(1.0, rows[0].Fraction, 4);
        Assert.Equal(20.0 / 30.0, rows[1].Fraction, 4);
        Assert.Equal(10.0 / 30.0, rows[2].Fraction, 4);
    }

    [Fact]
    public void TestHoverCardRowBuilderTokenRows()
    {
        var tokens = new Tokens(400, 200, 300, 100, 50, 1000);
        var rows = HoverCardRowBuilder.TokenRows(tokens);

        Assert.Equal(4, rows.Count);
        var inputRow = rows.First(r => r.Id == "input");
        Assert.Equal(400, inputRow.Count);
        Assert.Equal(0.4, inputRow.Fraction, 4);

        var outputRow = rows.First(r => r.Id == "output");
        Assert.Equal(200, outputRow.Count);
        Assert.Equal(0.2, outputRow.Fraction, 4);
    }
}
