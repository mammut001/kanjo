import AppKit
import SwiftUI
import KanjoCore

/// 全部颜色在这里定义。原则：
/// - 文字只用系统语义色（.primary / .secondary），这里的颜色只给色块、细条、图表用；
/// - 各 agent 有辨识度的颜色（浅深两套，由 KanjoCore.AgentColors 提供），颜色跟着 agent 走，不跟名次走；
///   treemap 方块、热力条、详情页柱状图、agent 色点都用同一组；
/// - 合并的「+N more」和未知 agent 用中性灰；
/// - 状态色（警告 / 错误）只在真的出问题时出现。
enum AgentPalette {
    /// 合并的「+N more」方块、未知 agent、没有花费的项目。
    static let neutral = dynamic(light: AgentColors.neutral.light, dark: AgentColors.neutral.dark)

    static func color(for agent: String) -> Color {
        let pair = AgentColors.pair(for: agent)
        return dynamic(light: pair.light, dark: pair.dark)
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

    // Token 构成：input / output / cache write 借用三个 agent 色，cache read 用更浅更安静的蓝（它通常占绝大部分）。
    static let tokenInput = dynamic(light: 0x3E79D6, dark: 0x6FA0F0)
    static let tokenOutput = dynamic(light: 0xD97757, dark: 0xE8926F)
    static let tokenCacheRead = dynamic(light: 0xB9CDEE, dark: 0x3D5478)
    static let tokenCacheWrite = dynamic(light: 0x7A6AD8, dark: 0x9B8DF0)

    // 图表默认色：中性的石板色（项目详情的 by_day 图改用该项目主力 agent 的颜色）。
    static let chartBar = dynamic(light: 0x8796B0, dark: 0x7E8EAA)

    // 分组底色：一层很淡的填充，替代卡片描边。
    static let groupFill = dynamic(light: 0x000000, dark: 0xFFFFFF, lightAlpha: 0.04, darkAlpha: 0.06)
    static let rowHover = Color.primary.opacity(0.06)
    static let rowPressed = Color.primary.opacity(0.11)

    // 置顶：琥珀色。
    static let pin = dynamic(light: 0xC2861A, dark: 0xE8B44F)
    // 热力条空周的底色。
    static let heatEmpty = Color.primary.opacity(0.08)

    // 状态色。
    static let good = dynamic(light: 0x2E7D4A, dark: 0x74C98F)
    static let goodFill = dynamic(light: 0x2E7D4A, dark: 0x74C98F, lightAlpha: 0.14, darkAlpha: 0.20)
    static let bad = dynamic(light: 0xB3261E, dark: 0xFF8A80)
    static let badFill = dynamic(light: 0xE5484D, dark: 0xE5484D, lightAlpha: 0.10, darkAlpha: 0.18)
    static let warnInk = dynamic(light: 0x6E5512, dark: 0xE8CF94)
    static let warnFill = dynamic(light: 0xD9A53A, dark: 0xD9A53A, lightAlpha: 0.16, darkAlpha: 0.18)
}
