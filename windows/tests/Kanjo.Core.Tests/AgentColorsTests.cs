using Xunit;

namespace Kanjo.Core.Tests;

public sealed class AgentColorsTests : KanjoTestCase
{
    private readonly record struct Lab(double L, double A, double B);

    private static Lab SrgbToLab(uint hex)
    {
        var r = (double)((hex >> 16) & 0xFF) / 255.0;
        var g = (double)((hex >> 8) & 0xFF) / 255.0;
        var b = (double)(hex & 0xFF) / 255.0;

        static double InvGamma(double c) => c <= 0.04045 ? c / 12.92 : Math.Pow((c + 0.055) / 1.055, 2.4);

        var rL = InvGamma(r);
        var gL = InvGamma(g);
        var bL = InvGamma(b);

        var x = rL * 0.4124564 + gL * 0.3575761 + bL * 0.1804375;
        var y = rL * 0.2126729 + gL * 0.7151522 + bL * 0.0721750;
        var z = rL * 0.0193339 + gL * 0.1191920 + bL * 0.9503041;

        // D65 reference white
        const double xn = 0.95047;
        const double yn = 1.00000;
        const double zn = 1.08883;

        const double delta = 6.0 / 29.0;
        var delta3 = delta * delta * delta;

        double F(double t) => t > delta3 ? Math.Cbrt(t) : (t / (3.0 * delta * delta)) + (4.0 / 29.0);

        var fx = F(x / xn);
        var fy = F(y / yn);
        var fz = F(z / zn);

        return new Lab(116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz));
    }

    private static double Ciede2000(Lab c1, Lab c2, double kL = 1.0, double kC = 1.0, double kH = 1.0)
    {
        var (l1, a1, b1) = (c1.L, c1.A, c1.B);
        var (l2, a2, b2) = (c2.L, c2.A, c2.B);

        var c1V = Math.Sqrt(a1 * a1 + b1 * b1);
        var c2V = Math.Sqrt(a2 * a2 + b2 * b2);
        var cBar = (c1V + c2V) / 2.0;

        var cBar7 = Math.Pow(cBar, 7.0);
        var g = 0.5 * (1.0 - Math.Sqrt(cBar7 / (cBar7 + Math.Pow(25.0, 7.0))));

        var a1Prime = (1.0 + g) * a1;
        var a2Prime = (1.0 + g) * a2;

        var c1Prime = Math.Sqrt(a1Prime * a1Prime + b1 * b1);
        var c2Prime = Math.Sqrt(a2Prime * a2Prime + b2 * b2);

        static double HueAngle(double b, double aPrime)
        {
            if (b == 0.0 && aPrime == 0.0) return 0.0;
            var deg = Math.Atan2(b, aPrime) * 180.0 / Math.PI;
            return deg >= 0 ? deg : deg + 360.0;
        }

        var h1Prime = HueAngle(b1, a1Prime);
        var h2Prime = HueAngle(b2, a2Prime);

        var deltaLPrime = l2 - l1;
        var deltaCPrime = c2Prime - c1Prime;

        double deltaHPrimeAngle;
        if (c1Prime * c2Prime == 0.0) deltaHPrimeAngle = 0.0;
        else if (Math.Abs(h2Prime - h1Prime) <= 180.0) deltaHPrimeAngle = h2Prime - h1Prime;
        else if (h2Prime - h1Prime > 180.0) deltaHPrimeAngle = h2Prime - h1Prime - 360.0;
        else deltaHPrimeAngle = h2Prime - h1Prime + 360.0;

        var deltaHPrime = 2.0 * Math.Sqrt(c1Prime * c2Prime) * Math.Sin(deltaHPrimeAngle / 2.0 * Math.PI / 180.0);

        var lBarPrime = (l1 + l2) / 2.0;
        var cBarPrime = (c1Prime + c2Prime) / 2.0;

        double hBarPrime;
        if (c1Prime * c2Prime == 0.0) hBarPrime = h1Prime + h2Prime;
        else if (Math.Abs(h1Prime - h2Prime) <= 180.0) hBarPrime = (h1Prime + h2Prime) / 2.0;
        else if (h1Prime + h2Prime < 360.0) hBarPrime = (h1Prime + h2Prime + 360.0) / 2.0;
        else hBarPrime = (h1Prime + h2Prime - 360.0) / 2.0;

        const double degToRad = Math.PI / 180.0;
        var t = 1.0 - 0.17 * Math.Cos((hBarPrime - 30.0) * degToRad)
                    + 0.24 * Math.Cos(2.0 * hBarPrime * degToRad)
                    + 0.32 * Math.Cos((3.0 * hBarPrime + 6.0) * degToRad)
                    - 0.20 * Math.Cos((4.0 * hBarPrime - 63.0) * degToRad);

        var deltaTheta = 30.0 * Math.Exp(-Math.Pow((hBarPrime - 275.0) / 25.0, 2.0));
        var cBarPrime7 = Math.Pow(cBarPrime, 7.0);
        var rC = 2.0 * Math.Sqrt(cBarPrime7 / (cBarPrime7 + Math.Pow(25.0, 7.0)));
        var sL = 1.0 + 0.015 * Math.Pow(lBarPrime - 50.0, 2.0) / Math.Sqrt(20.0 + Math.Pow(lBarPrime - 50.0, 2.0));
        var sC = 1.0 + 0.045 * cBarPrime;
        var sH = 1.0 + 0.015 * cBarPrime * t;
        var rT = -Math.Sin(2.0 * deltaTheta * degToRad) * rC;

        var termL = deltaLPrime / (kL * sL);
        var termC = deltaCPrime / (kC * sC);
        var termH = deltaHPrime / (kH * sH);

        return Math.Sqrt(termL * termL + termC * termC + termH * termH + rT * termC * termH);
    }

    /// <summary>Tier-1 agents 两两距离必须 ≥ 12；涉及 tier-2 的 ≥ 8。</summary>
    private static readonly HashSet<string> Tier1 =
    [
        "antigravity", "claude", "codex", "commandcode", "copilot", "grok", "grok_bot", "kimicode",
        "minimax", "musecode", "opencode", "pi", "qodercli", "qodercli_cn", "qoderwork", "qwen",
        "workbuddy", "workbuddy_ai", "zcode",
    ];

    [Fact]
    public void TestLightColorsPairwiseCiede2000()
    {
        var entries = AgentColors.All.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToList();
        for (var i = 0; i < entries.Count; i++)
        {
            for (var j = i + 1; j < entries.Count; j++)
            {
                var (k1, p1) = entries[i];
                var (k2, p2) = entries[j];
                var de = Ciede2000(SrgbToLab(p1.Light), SrgbToLab(p2.Light));
                var minDelta = Tier1.Contains(k1) && Tier1.Contains(k2) ? 12.0 : 8.0;
                Assert.True(de >= minDelta,
                    $"Light CIEDE2000 between {k1} (#{p1.Light:X6}) and {k2} (#{p2.Light:X6}) must be >= {minDelta}, got {de}");
            }
        }
    }

    [Fact]
    public void TestLightColorsVsNeutralCiede2000()
    {
        var neutralLab = SrgbToLab(AgentColors.NeutralLight);
        foreach (var (agent, pair) in AgentColors.All)
        {
            var de = Ciede2000(SrgbToLab(pair.Light), neutralLab);
            Assert.True(de >= 20.0,
                $"Light CIEDE2000 between {agent} (#{pair.Light:X6}) and neutral light (#{AgentColors.NeutralLight:X6}) must be >= 20, got {de}");
        }
    }

    [Fact]
    public void TestDarkColorsPairwiseCiede2000()
    {
        var entries = AgentColors.All.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToList();
        for (var i = 0; i < entries.Count; i++)
        {
            for (var j = i + 1; j < entries.Count; j++)
            {
                var (k1, p1) = entries[i];
                var (k2, p2) = entries[j];
                var de = Ciede2000(SrgbToLab(p1.Dark), SrgbToLab(p2.Dark));
                var minDelta = Tier1.Contains(k1) && Tier1.Contains(k2) ? 12.0 : 8.0;
                Assert.True(de >= minDelta,
                    $"Dark CIEDE2000 between {k1} (#{p1.Dark:X6}) and {k2} (#{p2.Dark:X6}) must be >= {minDelta}, got {de}");
            }
        }
    }

    [Fact]
    public void TestDarkColorsVsNeutralCiede2000()
    {
        var neutralLab = SrgbToLab(AgentColors.NeutralDark);
        foreach (var (agent, pair) in AgentColors.All)
        {
            var de = Ciede2000(SrgbToLab(pair.Dark), neutralLab);
            Assert.True(de >= 20.0,
                $"Dark CIEDE2000 between {agent} (#{pair.Dark:X6}) and neutral dark (#{AgentColors.NeutralDark:X6}) must be >= 20, got {de}");
        }
    }

    [Fact]
    public void TestUnknownAgentFallsBackToNeutral()
    {
        Assert.Equal(AgentColors.Neutral, AgentColors.Pair("not-an-agent"));
        Assert.Equal("not-an-agent", AgentColors.Label("not-an-agent"));
        Assert.Equal("Claude Code", AgentColors.Label("claude"));
    }
}
