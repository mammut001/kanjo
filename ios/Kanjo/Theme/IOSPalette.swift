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
    static let heatEmpty = Color.primary.opacity(0.08)
    /// 小组件按天热力条里零花费的格子：中性灰，不带色相。
    static let heatZero = dynamic(light: 0xC8C8CD, dark: 0x3A3A3C)

    /// 热力条非零档。色相沿用 `AgentColors`（和 App 热力条同一套）。
    /// 四档饱和度大约是强调色的 0.38 / 0.58 / 0.80 / 1.0，浅色再把低档亮度抬高，深色反过来压暗。
    /// 最低档仍是这个色相的清色，不混白、也不落到灰。零花费不走这里，用 `heatZero`。
    static func heatLevelColor(agent: String, level: Int) -> Color {
        let pair = AgentColors.pair(for: agent)
        let step = min(max(level, 1), HeatStrip.levels - 1)
        return Color(uiColor: UIColor { traits in
            let isDark = traits.userInterfaceStyle == .dark
            let base = uiColor(isDark ? pair.dark : pair.light, alpha: 1)
            if step >= HeatStrip.levels - 1 { return base }
            return rampedHeat(base, step: step, dark: isDark)
        })
    }

    /// 非零档的饱和度比例。最高档直接用强调色本身，不经过这次换算。
    private static let heatSaturationFractions: [CGFloat] = [0.38, 0.58, 0.80, 1]

    /// 浅色：低档在色相上抬亮（封顶 0.94，避免近白）。深色：镜像，低档压到约 0.62× 亮度，且不低于 0.40。
    private static func rampedHeat(_ color: UIColor, step: Int, dark: Bool) -> UIColor {
        var hue: CGFloat = 0
        var saturation: CGFloat = 0
        var brightness: CGFloat = 0
        var alpha: CGFloat = 0
        guard color.getHue(&hue, saturation: &saturation, brightness: &brightness, alpha: &alpha),
              saturation > 0.05 else {
            return color
        }
        let last = heatSaturationFractions.count - 1
        let index = min(max(step - 1, 0), last)
        if index >= last { return color }
        let fraction = heatSaturationFractions[index]
        let t = CGFloat(index) / CGFloat(last)
        let outSaturation = saturation * fraction
        let outBrightness: CGFloat
        if dark {
            let floor = min(brightness, max(0.40, brightness * 0.62))
            outBrightness = floor + (brightness - floor) * t
        } else {
            let ceiling = max(brightness, min(0.94, brightness + (1 - brightness) * 0.55))
            outBrightness = ceiling + (brightness - ceiling) * t
        }
        return UIColor(hue: hue, saturation: outSaturation, brightness: outBrightness, alpha: 1)
    }
    static let tokenInput = dynamic(light: 0x3E79D6, dark: 0x6FA0F0)
    static let tokenOutput = dynamic(light: 0xD97757, dark: 0xE8926F)
    static let tokenCacheRead = dynamic(light: 0xB9CDEE, dark: 0x3D5478)
    static let tokenCacheWrite = dynamic(light: 0x7A6AD8, dark: 0x9B8DF0)

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
