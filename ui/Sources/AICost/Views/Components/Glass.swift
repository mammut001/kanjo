import SwiftUI

// Liquid Glass 封装：所有 macOS 26 的玻璃 API 只在这个文件里出现 #available 分支。
// 玻璃只用在面板底栏上；内容区的分组只靠间距和一层淡底色（见 Primitives.groupedBackground）。
// 低于 macOS 26 时回退为一层淡底色，视图代码不需要关心系统版本。

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

/// 列表行的按钮样式：悬停一层中性高亮，按下略深。行铺满分组宽度，圆角由分组裁切。
struct RowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        RowBody(configuration: configuration)
    }

    private struct RowBody: View {
        let configuration: ButtonStyleConfiguration
        @State private var hover = false

        var body: some View {
            configuration.label
                .background(Rectangle().fill(configuration.isPressed ? AgentPalette.rowPressed
                                             : hover ? AgentPalette.rowHover : Color.clear))
                .animation(.easeOut(duration: 0.1), value: hover)
                .onHover { hover = $0 }
        }
    }
}

/// 底栏里的图标按钮：无底，悬停出现圆形淡底。
struct IconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        IconBody(configuration: configuration)
    }

    private struct IconBody: View {
        let configuration: ButtonStyleConfiguration
        @Environment(\.isEnabled) private var enabled
        @State private var hover = false

        var body: some View {
            configuration.label
                .font(.system(size: 12.5, weight: .regular))
                .foregroundStyle(.secondary)
                .frame(width: 26, height: 26)
                .background(Circle().fill(configuration.isPressed ? AgentPalette.rowPressed
                                          : hover && enabled ? AgentPalette.rowHover : Color.clear))
                .contentShape(Circle())
                .opacity(enabled ? 1 : 0.45)
                .onHover { hover = $0 }
        }
    }
}
