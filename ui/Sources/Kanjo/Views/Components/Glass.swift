import SwiftUI

// Liquid Glass 封装：所有 macOS 26 的玻璃 API 只在这个文件里出现 #available 分支。
// 玻璃用在三处：面板根背景（PanelBackground）、底栏、总览的马赛克（treemap）方块。
// 低于 macOS 26 时回退为系统材质 / 淡底色 / 实色，视图代码不需要关心系统版本。

/// 面板根背景：macOS 26+ 是一整块 Liquid Glass，13–25 是 `.regularMaterial`。
/// 玻璃画在内容后面（background），内容本身不进玻璃，文字不受 vibrancy 影响。
struct PanelBackground: ViewModifier {
    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content.background(Color.clear.glassEffect(.regular, in: Rectangle()).ignoresSafeArea())
        } else {
            content.background(Rectangle().fill(.regularMaterial).ignoresSafeArea())
        }
    }
}

extension View {
    func panelBackground() -> some View { modifier(PanelBackground()) }
}

struct GlassSurface: ViewModifier {
    var cornerRadius: CGFloat

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        if #available(macOS 26, *) {
            content.glassEffect(.regular, in: shape)
        } else {
            content.background(shape.fill(AgentPalette.groupFill))
        }
    }
}

extension View {
    func glassSurface(cornerRadius: CGFloat = 12) -> some View {
        modifier(GlassSurface(cornerRadius: cornerRadius))
    }
}

/// 马赛克方块的底：macOS 26+ 是有色玻璃（tint = agent 色 90%），低版本是实色填充。
/// 方块不放进 GlassEffectContainer：容器里相邻的玻璃会互相折射，2pt 的缝里会渗进邻块的颜色、边缘发糊；
/// 各自独立渲染时每块都是干净的玻璃边。
struct MosaicTile: ViewModifier {
    var color: Color
    static let cornerRadius: CGFloat = 4
    @Environment(\.self) private var environment

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: Self.cornerRadius, style: .continuous)
        if #available(macOS 26, *) {
            // 玻璃的 tint 不跟随动态 NSColor，先按当前外观解析成静态颜色。
            let resolved = Color(color.resolve(in: environment))
            content.glassEffect(.regular.tint(resolved.opacity(0.9)), in: shape)
        } else {
            content.background(shape.fill(color))
        }
    }
}

/// 叠在马赛克方块上面的一层（在文字下面）。macOS 26+：窗口失焦时玻璃的色调会被系统洗淡，
/// 这一层在失焦时补上 agent 色，保证颜色仍然读得出来；聚焦时只留很薄一层，不盖住玻璃质感。
/// 悬停时再提亮一层。低版本底下已经是实色，只画悬停提亮。
struct MosaicWash: View {
    var color: Color
    var hover: Bool
    @Environment(\.controlActiveState) private var activeState

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: MosaicTile.cornerRadius, style: .continuous)
        let lit = shape.fill(Color.white.opacity(hover ? 0.18 : 0))
        if #available(macOS 26, *) {
            shape.fill(color.opacity(activeState == .inactive ? 0.8 : 0.25)).overlay(lit)
        } else {
            lit
        }
    }
}

extension View {
    func mosaicTile(color: Color) -> some View {
        modifier(MosaicTile(color: color))
    }
}

/// 列表行的按钮样式：悬停一层中性高亮，按下略深。分组里的行圆角由分组裁切（cornerRadius 0）；
/// 直接放在面板上的行（总览列表）自带圆角。
/// `highlighted` 由外部强制高亮（行上叠了悬停按钮时，鼠标在按钮上也保持整行高亮）。
struct RowButtonStyle: ButtonStyle {
    var highlighted = false
    var cornerRadius: CGFloat = 0

    func makeBody(configuration: Configuration) -> some View {
        RowBody(configuration: configuration, highlighted: highlighted, cornerRadius: cornerRadius)
    }

    private struct RowBody: View {
        let configuration: ButtonStyleConfiguration
        let highlighted: Bool
        let cornerRadius: CGFloat
        @State private var hover = false

        var body: some View {
            configuration.label
                .background(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(configuration.isPressed ? AgentPalette.rowPressed
                          : hover || highlighted ? AgentPalette.rowHover : Color.clear))
                .animation(.easeOut(duration: 0.1), value: hover)
                .onHover { hover = $0 }
        }
    }
}

/// 底栏里的图标按钮：无底，悬停出现圆形淡底。`active` 时用强调色，表示当前页。
struct IconButtonStyle: ButtonStyle {
    var active = false

    func makeBody(configuration: Configuration) -> some View {
        IconBody(configuration: configuration, active: active)
    }

    private struct IconBody: View {
        let configuration: ButtonStyleConfiguration
        let active: Bool
        @Environment(\.isEnabled) private var enabled
        @State private var hover = false

        var body: some View {
            configuration.label
                .font(.system(size: 12.5, weight: .regular))
                .foregroundStyle(active ? Color.accentColor : Color.secondary)
                .frame(width: 26, height: 26)
                .background(Circle().fill(configuration.isPressed ? AgentPalette.rowPressed
                                          : (hover && enabled) || active ? AgentPalette.rowHover : Color.clear))
                .contentShape(Circle())
                .opacity(enabled ? 1 : 0.45)
                .onHover { hover = $0 }
        }
    }
}
