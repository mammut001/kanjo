namespace Kanjo.Core;

public readonly record struct AgentColorPair(uint Light, uint Dark);

/// <summary>纯数据：每个 agent 的 light / dark 颜色定义（16 进制 RGB）。逐条对应 Mac 版。</summary>
public static class AgentColors
{
    public const uint NeutralLight = 0x9A9A9A;
    public const uint NeutralDark = 0x6E6E73;
    public static readonly AgentColorPair Neutral = new(NeutralLight, NeutralDark);

    public static readonly AgentColorPair Claude = new(0xD97757, 0xE8926F);
    public static readonly AgentColorPair Codex = new(0x3E79D6, 0x6FA0F0);
    public static readonly AgentColorPair Antigravity = new(0x7A6AD8, 0x9B8DF0);
    public static readonly AgentColorPair Grok = new(0x0C7E86, 0x1DB8C3);
    public static readonly AgentColorPair Minimax = new(0xD63A8A, 0xF06595);
    public static readonly AgentColorPair Qwen = new(0x082DFF, 0x486DFC);
    public static readonly AgentColorPair Commandcode = new(0x2E1B9C, 0x6741D9);
    public static readonly AgentColorPair Opencode = new(0xB08A1E, 0xDEB135);
    public static readonly AgentColorPair Copilot = new(0x1F883D, 0x3FB950);
    public static readonly AgentColorPair Pi = new(0xC41E3A, 0xE63946);
    public static readonly AgentColorPair Workbuddy = new(0xB662CA, 0xD684E8);
    public static readonly AgentColorPair WorkbuddyAi = new(0x005E52, 0x277C6F);
    public static readonly AgentColorPair GrokBot = new(0xDC3C00, 0xFF6318);
    public static readonly AgentColorPair Qoderwork = new(0x823D44, 0xA05C61);
    public static readonly AgentColorPair Qodercli = new(0x6E7F15, 0x8F9D3D);
    public static readonly AgentColorPair QodercliCn = new(0x872B83, 0xA64EA0);
    public static readonly AgentColorPair Zcode = new(0x3C5A31, 0x5A774F);
    public static readonly AgentColorPair Kimicode = new(0x985C26, 0xB97B47);
    public static readonly AgentColorPair Musecode = new(0xC77C80, 0xE89DA0);
    public static readonly AgentColorPair Codebuddy = new(0x00A097, 0x00D5C0);
    public static readonly AgentColorPair QoderIde = new(0x248BB2, 0x48BFFC);
    public static readonly AgentColorPair Hermes = new(0xA2A600, 0xBDC000);
    public static readonly AgentColorPair Openclaw = new(0xA8005C, 0xC21E64);
    public static readonly AgentColorPair Devin = new(0x006694, 0x1A98C2);
    public static readonly AgentColorPair Mimocode = new(0xC27C38, 0xE28C00);
    public static readonly AgentColorPair PrimeAgent = new(0x8F32D0, 0x7C6AB8);
    public static readonly AgentColorPair Omp = new(0x005462, 0x589094);
    public static readonly AgentColorPair DeepseekHarness = new(0x0044A0, 0x1056B8);
    public static readonly AgentColorPair Qwenwork = new(0x00A06B, 0x20C58A);

    public static readonly IReadOnlyDictionary<string, AgentColorPair> All =
        new Dictionary<string, AgentColorPair>(StringComparer.Ordinal)
        {
            ["claude"] = Claude,
            ["codex"] = Codex,
            ["antigravity"] = Antigravity,
            ["grok"] = Grok,
            ["minimax"] = Minimax,
            ["qwen"] = Qwen,
            ["commandcode"] = Commandcode,
            ["opencode"] = Opencode,
            ["copilot"] = Copilot,
            ["pi"] = Pi,
            ["workbuddy"] = Workbuddy,
            ["workbuddy_ai"] = WorkbuddyAi,
            ["grok_bot"] = GrokBot,
            ["qoderwork"] = Qoderwork,
            ["qodercli"] = Qodercli,
            ["qodercli_cn"] = QodercliCn,
            ["zcode"] = Zcode,
            ["kimicode"] = Kimicode,
            ["musecode"] = Musecode,
            ["codebuddy"] = Codebuddy,
            ["qoder_ide"] = QoderIde,
            ["hermes"] = Hermes,
            ["openclaw"] = Openclaw,
            ["devin"] = Devin,
            ["mimocode"] = Mimocode,
            ["prime_agent"] = PrimeAgent,
            ["omp"] = Omp,
            ["deepseek_harness"] = DeepseekHarness,
            ["qwenwork"] = Qwenwork,
        };

    public static AgentColorPair Pair(string agent) => All.TryGetValue(agent, out var pair) ? pair : Neutral;

    public static readonly IReadOnlyDictionary<string, string> DefaultLabels =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["claude"] = "Claude Code",
            ["antigravity"] = "Antigravity CLI",
            ["codex"] = "Codex CLI",
            ["grok"] = "Grok CLI",
            ["qwen"] = "Qwen Code",
            ["commandcode"] = "Command Code",
            ["minimax"] = "MiniMax",
            ["opencode"] = "OpenCode",
            ["copilot"] = "Copilot CLI",
            ["pi"] = "Pi",
            ["workbuddy"] = "WorkBuddy",
            ["workbuddy_ai"] = "WorkBuddy Intl.",
            ["grok_bot"] = "Grok Bot",
            ["qoderwork"] = "QoderWork",
            ["qodercli"] = "Qoder CLI",
            ["qodercli_cn"] = "Qoder CN",
            ["zcode"] = "ZCode",
            ["kimicode"] = "Kimi Code",
            ["musecode"] = "Muse Code",
            ["codebuddy"] = "CodeBuddy",
            ["qoder_ide"] = "Qoder IDE",
            ["hermes"] = "Hermes",
            ["openclaw"] = "OpenClaw",
            ["devin"] = "Devin",
            ["mimocode"] = "MiMo Code",
            ["prime_agent"] = "Prime Agent",
            ["omp"] = "OMP",
            ["deepseek_harness"] = "DeepSeek Harness",
            ["qwenwork"] = "QwenWork",
        };

    public static string Label(string agent) =>
        DefaultLabels.TryGetValue(agent, out var label) ? label : agent;

    /// <summary>RGB → #RRGGBB。</summary>
    public static string Hex(uint rgb) => $"#{rgb:X6}";
}

/// <summary>by_agent 里花费最多的 agent 及其占比；没有正花费时为 null。</summary>
public static class DominantAgent
{
    public static (string Agent, string Label, double Share)? Of(IReadOnlyList<AgentCost> byAgent)
    {
        var total = byAgent.Sum(a => Math.Max(a.Cost, 0));
        if (!(total > 0)) return null;
        AgentCost? top = null;
        foreach (var a in byAgent)
        {
            if (top is null || a.Cost > top.Cost) top = a;
        }
        if (top is null || !(top.Cost > 0)) return null;
        return (top.Agent, top.Label, top.Cost / total);
    }
}

/// <summary>契约第 2 节的不变量：totals == sum(projects) + unattributed + excluded。</summary>
public sealed record Reconciliation
{
    public sealed record Line(double Reported, double Summed, double Tolerance)
    {
        public double Diff => Reported - Summed;
        public bool Ok => Math.Abs(Diff) <= Tolerance;
    }

    /// <summary>金额误差容忍 0.01（契约）；token / 会话是整数，必须相等。</summary>
    public const double CostTolerance = 0.01;

    public Line Cost { get; }
    public Line Tokens { get; }
    public Line Sessions { get; }
    public double ProjectsCost { get; }
    public double UnattributedCost { get; }
    public double ExcludedCost { get; }

    public bool Ok => Cost.Ok && Tokens.Ok && Sessions.Ok;

    public Reconciliation(UsageReport r)
    {
        var pCost = r.Projects.Sum(p => p.Cost);
        var pTok = r.Projects.Sum(p => p.Tokens.Total);
        var pSess = r.Projects.Sum(p => p.Sessions);
        var u = r.Buckets.Unattributed;
        var e = r.Buckets.Excluded;
        ProjectsCost = pCost;
        UnattributedCost = u.Cost;
        ExcludedCost = e.Cost;
        Cost = new Line(r.Totals.Cost, pCost + u.Cost + e.Cost, CostTolerance);
        Tokens = new Line(r.Totals.Tokens.Total, pTok + u.Tokens.Total + e.Tokens.Total, 0);
        Sessions = new Line(r.Totals.Sessions, pSess + u.Sessions + e.Sessions, 0);
    }
}

/// <summary>attribution 取值的解释（CONTRACT.md 第 5 节），用作 tooltip。</summary>
public static class AttributionInfo
{
    public static readonly IReadOnlyList<string> AllKnown =
        ["dominant", "split", "cwd", "scratchpad", "override", "none", "excluded"];

    public static string Explanation(string value, double threshold)
    {
        var pct = (int)Math.Round(threshold * 100, MidpointRounding.AwayFromZero) + "%";
        return value switch
        {
            "dominant" => L10n.TrL(null, "attribution.dominant", pct),
            "split" => L10n.TrL(null, "attribution.split", pct),
            "cwd" => L10n.Tr("attribution.cwd"),
            "scratchpad" => L10n.Tr("attribution.scratchpad"),
            "override" => L10n.Tr("attribution.override"),
            "none" => L10n.Tr("attribution.none"),
            "excluded" => L10n.Tr("attribution.excluded"),
            _ => L10n.TrL(null, "attribution.unknown", value),
        };
    }
}
