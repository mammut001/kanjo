import SwiftUI

// Liquid Glass 封装：所有 macOS 26 的玻璃 API 只在这个文件里出现 #available 分支。
// 低于 macOS 26 时回退到原来的 Material / 卡片底色样式，视图代码不需要关心系统版本。

/// 一块玻璃面（卡片、胶囊、横幅）。
///
/// 可读性优先：带文字的面一律用 `.regular`（不用高透明的 `.clear`）；
/// 需要强调状态（警告 / 错误）时用 `.regular.tint(...)` 给玻璃上色，而不是把文字直接压在透明玻璃上。
struct GlassSurface: ViewModifier {
    enum Shape { case rounded(CGFloat), capsule }

    var shape: Shape = .rounded(12)
    /// 给玻璃上色（macOS 26）；低版本把它当作实心底色。
    var tint: Color? = nil
    /// 低版本的底色；nil = 原来的卡片底色 controlBackgroundColor。
    var fallbackFill: Color? = nil
    /// 描边：状态色描边（比如对账失败的红框）在两个分支都画。
    var stroke: Color? = nil
    var interactive = false

    func body(content: Content) -> some View {
        switch shape {
        case .rounded(let r): apply(content, RoundedRectangle(cornerRadius: r, style: .continuous))
        case .capsule: apply(content, Capsule(style: .continuous))
        }
    }

    @ViewBuilder
    private func apply<S: InsettableShape>(_ content: Content, _ s: S) -> some View {
        if #available(macOS 26, *) {
            content
                .glassEffect(glass, in: s)
                .overlay { if let stroke { s.strokeBorder(stroke, lineWidth: 1) } }
        } else {
            content
                .background(s.fill(fallbackFill ?? tint ?? Color(nsColor: .controlBackgroundColor)))
                .overlay(s.strokeBorder(stroke ?? Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    @available(macOS 26, *)
    private var glass: Glass {
        var g = Glass.regular
        if let tint { g = g.tint(tint) }
        if interactive { g = g.interactive() }
        return g
    }
}

extension View {
    func glassSurface(cornerRadius: CGFloat = 12, tint: Color? = nil, fallbackFill: Color? = nil,
                      stroke: Color? = nil, interactive: Bool = false) -> some View {
        modifier(GlassSurface(shape: .rounded(cornerRadius), tint: tint, fallbackFill: fallbackFill,
                              stroke: stroke, interactive: interactive))
    }

    func glassCapsule(tint: Color? = nil, fallbackFill: Color? = nil, stroke: Color? = nil) -> some View {
        modifier(GlassSurface(shape: .capsule, tint: tint, fallbackFill: fallbackFill, stroke: stroke))
    }

    /// 刷新 / 设置 / 退出 / 返回等按钮：macOS 26 用 `.glass`，低版本 `.bordered`。
    @ViewBuilder
    func glassButtonStyle(prominent: Bool = false) -> some View {
        if #available(macOS 26, *) {
            if prominent { buttonStyle(.glassProminent) } else { buttonStyle(.glass) }
        } else {
            if prominent { buttonStyle(.borderedProminent) } else { buttonStyle(.bordered) }
        }
    }
}

/// 把相邻的玻璃面放进同一个 `GlassEffectContainer`：一起采样背景、靠近时融合。
/// 低版本直接透传内容。
struct GlassGroup<Content: View>: View {
    var spacing: CGFloat? = nil
    @ViewBuilder var content: () -> Content

    init(spacing: CGFloat? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.spacing = spacing
        self.content = content
    }

    var body: some View {
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
    }
}

/// 列表行的按钮样式：悬停高亮、按下变深并轻微缩小。不用玻璃（行已经在玻璃卡片里，避免玻璃叠玻璃）。
struct RowButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 8

    func makeBody(configuration: Configuration) -> some View {
        RowBody(configuration: configuration, cornerRadius: cornerRadius)
    }

    private struct RowBody: View {
        let configuration: ButtonStyleConfiguration
        let cornerRadius: CGFloat
        @State private var hover = false

        var body: some View {
            configuration.label
                .background(
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .fill(Color.accentColor.opacity(configuration.isPressed ? 0.22 : hover ? 0.11 : 0))
                )
                .scaleEffect(configuration.isPressed ? 0.985 : 1)
                .animation(.easeOut(duration: 0.12), value: hover)
                .animation(.easeOut(duration: 0.08), value: configuration.isPressed)
                .onHover { hover = $0 }
        }
    }
}
