import AppKit
import SwiftUI

/// agent 身份色：固定分配，颜色跟着 agent 走，不跟名次走。
/// 已知 agent 用固定色；未知 key 按名字哈希落到后备色槽。
enum AgentPalette {
    private static let known: [String: (UInt32, UInt32)] = [
        "claude": (0xEB6834, 0xD95926),       // orange
        "antigravity": (0x2A78D6, 0x3987E5),  // blue
        "codex": (0x1BAF7A, 0x199E70),        // aqua
    ]
    private static let fallback: [(UInt32, UInt32)] = [
        (0xEDA100, 0xC98500),  // yellow
        (0xE87BA4, 0xD55181),  // magenta
        (0x008300, 0x008300),  // green
        (0x6250D6, 0x9085E9),  // violet
        (0xE34948, 0xE66767),  // red
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

    static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return nsColor(isDark ? dark : light)
        })
    }

    private static func nsColor(_ hex: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }

    static let tokenInput = dynamic(light: 0x2A78D6, dark: 0x3987E5)
    static let tokenOutput = dynamic(light: 0xEB6834, dark: 0xD95926)
    // 深色玻璃上原来的 0x1C5CAB 几乎看不见，改成更亮的浅蓝（仍与 tokenInput 区分得开）。
    static let tokenCacheRead = dynamic(light: 0x7FB0EC, dark: 0x8DC0F7)
    static let tokenCacheWrite = dynamic(light: 0x6250D6, dark: 0x9085E9)
    static let bad = dynamic(light: 0xB3261E, dark: 0xFF7B7B)  // 加深 / 提亮：染红玻璃上也要 ≥4.5:1
    static let warnFill = dynamic(light: 0xFDECC8, dark: 0x3D2E0A)
    static let warnInk = dynamic(light: 0x6B4A00, dark: 0xF7D48A)
    static let badFill = dynamic(light: 0xFBE3E3, dark: 0x3D1717)
    /// 对账通过的绿字：系统绿在浅色玻璃上对比度不够，用更深的绿。
    static let good = dynamic(light: 0x1E7A3A, dark: 0x5FD37E)

    // 玻璃背景上的图表色：比 accentColor.opacity(0.7) 更实，浅色用深蓝、深色用亮蓝。
    static let chartBar = dynamic(light: 0x2468C8, dark: 0x5BA4F5)
    static let chartBarHover = dynamic(light: 0x0F4A9E, dark: 0xA8D0FF)
    /// 横向条 / 堆叠条的底轨：玻璃会提亮背景，原来 0.07 的灰在浅色下看不出来。
    static let track = Color.primary.opacity(0.12)

    // 横幅玻璃的着色（半透明，玻璃仍可见，文字用 warnInk / bad）。
    static let warnTint = dynamic(light: 0xF5B83D, dark: 0xB07A10).opacity(0.30)
    static let badTint = dynamic(light: 0xE5484D, dark: 0xC0383C).opacity(0.18)
}
