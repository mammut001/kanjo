import KanjoCore
import SwiftUI
import UIKit

/// iOS 侧的动态颜色：agent 颜色仍来自 KanjoCore.AgentColors（与 macOS 同一张表），
/// 这里只负责把 16 进制 RGB 变成随浅色 / 深色外观切换的 UIColor。
enum IOSPalette {
    static func agent(_ key: String) -> Color {
        let pair = AgentColors.pair(for: key)
        return dynamic(light: pair.light, dark: pair.dark)
    }

    static let neutral = dynamic(light: AgentColors.neutral.light, dark: AgentColors.neutral.dark)
    static let chartBar = dynamic(light: 0x8796B0, dark: 0x7E8EAA)
    static let good = dynamic(light: 0x2E7D4A, dark: 0x74C98F)
    static let bad = dynamic(light: 0xB3261E, dark: 0xFF8A80)
    static let quotaWarn = dynamic(light: 0xD08A12, dark: 0xF0B248)
    static let pin = dynamic(light: 0xC2861A, dark: 0xE8B44F)

    static func dynamic(light: UInt32, dark: UInt32, lightAlpha: CGFloat = 1, darkAlpha: CGFloat = 1) -> Color {
        Color(uiColor: UIColor { traits in
            let isDark = traits.userInterfaceStyle == .dark
            return uiColor(isDark ? dark : light, alpha: isDark ? darkAlpha : lightAlpha)
        })
    }

    private static func uiColor(_ hex: UInt32, alpha: CGFloat) -> UIColor {
        UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: alpha)
    }
}
