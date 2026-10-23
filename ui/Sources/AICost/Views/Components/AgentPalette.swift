import AppKit
import SwiftUI

/// 全部颜色在这里定义。原则：
/// - 文字只用系统语义色（.primary / .secondary），这里的颜色只给色块、细条、图表用；
/// - agent 色是低饱和的「土色」，浅深两套，颜色跟着 agent 走，不跟名次走；
/// - 状态色（警告 / 错误）只在真的出问题时出现。
enum AgentPalette {
    private static let known: [String: (UInt32, UInt32)] = [
        "claude": (0xC27A5E, 0xD4917A),       // terracotta
        "codex": (0x6C84A6, 0x8EA4C6),        // slate blue
        "antigravity": (0x7F9B78, 0x98B492),  // sage
    ]
    private static let fallback: [(UInt32, UInt32)] = [
        (0xB89A5B, 0xCDB27A),  // ochre
        (0xA67D96, 0xBF9AB1),  // mauve
        (0x6E9897, 0x8DB4B3),  // teal grey
        (0x8B85B5, 0xA7A1CE),  // lavender
        (0xB9787A, 0xCF9497),  // rose
    ]

    static func color(for agent: String) -> Color {
        let pair: (UInt32, UInt32)
        if let k = known[agent] {
            pair = k
        } else {
            var h: UInt32 = 5381
            for b in agent.utf8 { h = (h &* 33) &+ UInt32(b) }
            pair = fallback[Int(h % UInt32(fallback.count))]
        }
        return dynamic(light: pair.0, dark: pair.1)
    }

    static func dynamic(light: UInt32, dark: UInt32, lightAlpha: CGFloat = 1, darkAlpha: CGFloat = 1) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return nsColor(isDark ? dark : light, alpha: isDark ? darkAlpha : lightAlpha)
        })
    }

    private static func nsColor(_ hex: UInt32, alpha: CGFloat) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }

    // Token 构成：input / output 借用 agent 的两种主色，cache 用更浅更安静的色（它通常占绝大部分）。
    static let tokenInput = dynamic(light: 0x6C84A6, dark: 0x8EA4C6)
    static let tokenOutput = dynamic(light: 0xC27A5E, dark: 0xD4917A)
    static let tokenCacheRead = dynamic(light: 0xB7C3D4, dark: 0x5E6C83)
    static let tokenCacheWrite = dynamic(light: 0x9A93C2, dark: 0xA39DCB)

    // 图表：中性的石板色，悬停时加深（浅色）/ 提亮（深色）。
    static let chartBar = dynamic(light: 0x8796B0, dark: 0x7E8EAA)
    static let chartBarHover = dynamic(light: 0x4F607F, dark: 0xC3CFE4)

    // 分组底色：一层很淡的填充，替代卡片描边。
    static let groupFill = dynamic(light: 0x000000, dark: 0xFFFFFF, lightAlpha: 0.04, darkAlpha: 0.06)
    static let rowHover = Color.primary.opacity(0.06)
    static let rowPressed = Color.primary.opacity(0.11)

    // 状态色。
    static let good = dynamic(light: 0x2E7D4A, dark: 0x74C98F)
    static let bad = dynamic(light: 0xB3261E, dark: 0xFF8A80)
    static let badFill = dynamic(light: 0xE5484D, dark: 0xE5484D, lightAlpha: 0.10, darkAlpha: 0.18)
    static let warnInk = dynamic(light: 0x6E5512, dark: 0xE8CF94)
    static let warnFill = dynamic(light: 0xD9A53A, dark: 0xD9A53A, lightAlpha: 0.16, darkAlpha: 0.18)
}
