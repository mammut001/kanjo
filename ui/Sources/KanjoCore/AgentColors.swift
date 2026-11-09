import Foundation

/// 纯数据：每个 agent 的 light / dark 颜色定义（16 进制 RGB UInt32）。
/// 移入 KanjoCore 以便 KanjoTests 能够测试颜色区分度（CIEDE2000）。
public struct AgentColorPair: Equatable, Sendable {
    public let light: UInt32
    public let dark: UInt32

    public init(light: UInt32, dark: UInt32) {
        self.light = light
        self.dark = dark
    }
}

public enum AgentColors {
    public static let neutralLight: UInt32 = 0x9A9A9A
    public static let neutralDark: UInt32 = 0x6E6E73
    public static let neutral = AgentColorPair(light: neutralLight, dark: neutralDark)

    public static let claude = AgentColorPair(light: 0xD97757, dark: 0xE8926F)
    public static let codex = AgentColorPair(light: 0x3E79D6, dark: 0x6FA0F0)
    public static let antigravity = AgentColorPair(light: 0x7A6AD8, dark: 0x9B8DF0)
    public static let grok = AgentColorPair(light: 0x0C7E86, dark: 0x1DB8C3)
    public static let minimax = AgentColorPair(light: 0xD63A8A, dark: 0xF06595)
    public static let qwen = AgentColorPair(light: 0x082DFF, dark: 0x486DFC)
    public static let commandcode = AgentColorPair(light: 0x2E1B9C, dark: 0x6741D9)
    public static let opencode = AgentColorPair(light: 0xB08A1E, dark: 0xDEB135)
    public static let copilot = AgentColorPair(light: 0x1F883D, dark: 0x3FB950)
    public static let pi = AgentColorPair(light: 0xC41E3A, dark: 0xE63946)
    public static let workbuddy = AgentColorPair(light: 0xB662CA, dark: 0xD684E8)
    public static let workbuddy_ai = AgentColorPair(light: 0x005E52, dark: 0x277C6F)
    public static let grok_bot = AgentColorPair(light: 0xDC3C00, dark: 0xFF6318)
    public static let qoderwork = AgentColorPair(light: 0x823D44, dark: 0xA05C61)
    public static let qodercli = AgentColorPair(light: 0x6E7F15, dark: 0x8F9D3D)
    public static let qodercli_cn = AgentColorPair(light: 0x872B83, dark: 0xA64EA0)
    public static let zcode = AgentColorPair(light: 0x3C5A31, dark: 0x5A774F)
    public static let kimicode = AgentColorPair(light: 0x985C26, dark: 0xB97B47)
    public static let musecode = AgentColorPair(light: 0xC77C80, dark: 0xE89DA0)
    public static let codebuddy = AgentColorPair(light: 0x00A097, dark: 0x00D5C0)
    public static let qoder_ide = AgentColorPair(light: 0x248BB2, dark: 0x48BFFC)
    public static let hermes = AgentColorPair(light: 0xA2A600, dark: 0xBDC000)
    public static let openclaw = AgentColorPair(light: 0xA8005C, dark: 0xC21E64)
    public static let devin = AgentColorPair(light: 0x006694, dark: 0x1A98C2)
    public static let mimocode = AgentColorPair(light: 0xC27C38, dark: 0xE28C00)
    public static let prime_agent = AgentColorPair(light: 0x8F32D0, dark: 0x7C6AB8)
    public static let omp = AgentColorPair(light: 0x005462, dark: 0x589094)
    public static let deepseek_harness = AgentColorPair(light: 0x0044A0, dark: 0x1056B8)
    public static let qwenwork = AgentColorPair(light: 0x00A06B, dark: 0x20C58A)

    public static let all: [String: AgentColorPair] = [
        "claude": claude,
        "codex": codex,
        "antigravity": antigravity,
        "grok": grok,
        "minimax": minimax,
        "qwen": qwen,
        "commandcode": commandcode,
        "opencode": opencode,
        "copilot": copilot,
        "pi": pi,
        "workbuddy": workbuddy,
        "workbuddy_ai": workbuddy_ai,
        "grok_bot": grok_bot,
        "qoderwork": qoderwork,
        "qodercli": qodercli,
        "qodercli_cn": qodercli_cn,
        "zcode": zcode,
        "kimicode": kimicode,
        "musecode": musecode,
        "codebuddy": codebuddy,
        "qoder_ide": qoder_ide,
        "hermes": hermes,
        "openclaw": openclaw,
        "devin": devin,
        "mimocode": mimocode,
        "prime_agent": prime_agent,
        "omp": omp,
        "deepseek_harness": deepseek_harness,
        "qwenwork": qwenwork,
    ]

    public static func pair(for agent: String) -> AgentColorPair {
        all[agent] ?? neutral
    }

    public static let defaultLabels: [String: String] = [
        "claude": "Claude Code",
        "antigravity": "Antigravity CLI",
        "codex": "Codex CLI",
        "grok": "Grok CLI",
        "qwen": "Qwen Code",
        "commandcode": "Command Code",
        "minimax": "MiniMax",
        "opencode": "OpenCode",
        "copilot": "Copilot CLI",
        "pi": "Pi",
        "workbuddy": "WorkBuddy",
        "workbuddy_ai": "WorkBuddy Intl.",
        "grok_bot": "Grok Bot",
        "qoderwork": "QoderWork",
        "qodercli": "Qoder CLI",
        "qodercli_cn": "Qoder CN",
        "zcode": "ZCode",
        "kimicode": "Kimi Code",
        "musecode": "Muse Code",
        "codebuddy": "CodeBuddy",
        "qoder_ide": "Qoder IDE",
        "hermes": "Hermes",
        "openclaw": "OpenClaw",
        "devin": "Devin",
        "mimocode": "MiMo Code",
        "prime_agent": "Prime Agent",
        "omp": "OMP",
        "deepseek_harness": "DeepSeek Harness",
        "qwenwork": "QwenWork",
    ]

    public static func label(for agent: String) -> String {
        defaultLabels[agent] ?? agent
    }
}
