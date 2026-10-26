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
    ]

    public static func label(for agent: String) -> String {
        defaultLabels[agent] ?? agent
    }
}
