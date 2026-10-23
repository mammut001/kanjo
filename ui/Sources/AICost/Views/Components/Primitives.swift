import SwiftUI
import AICostCore

/// 带标题的分组卡片。
struct SectionCard<Content: View, Trailing: View>: View {
    let title: String
    @ViewBuilder var trailing: () -> Trailing
    @ViewBuilder var content: () -> Content

    init(_ title: String, @ViewBuilder trailing: @escaping () -> Trailing = { EmptyView() },
         @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.trailing = trailing
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.system(size: 12, weight: .semibold))
                Spacer(minLength: 8)
                trailing()
            }
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassSurface(cornerRadius: 14)
    }
}

/// 总览顶部的数字卡片：圆体 + 等宽数字，放在玻璃上。
struct StatTile: View {
    let label: String
    let value: String
    var sub: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary)
            Text(value)
                .font(.system(size: 19, weight: .semibold, design: .rounded).monospacedDigit())
                .foregroundStyle(.primary)
                .lineLimit(1).minimumScaleFactor(0.6)
            if let sub {
                Text(sub).font(.system(size: 9.5).monospacedDigit()).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .frame(maxWidth: .infinity, minHeight: 64, maxHeight: .infinity, alignment: .topLeading)
        .glassSurface(cornerRadius: 16)
    }
}

struct Badge: View {
    enum Style { case neutral, warn, bad }
    let text: String
    var style: Style = .neutral
    var help: String? = nil

    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .semibold))
            .padding(.horizontal, 5).padding(.vertical, 1)
            .foregroundStyle(fg)
            .background(Capsule().fill(bg))
            .help(help ?? "")
    }

    private var fg: Color {
        switch style {
        case .neutral: return .secondary
        case .warn: return AgentPalette.warnInk
        case .bad: return AgentPalette.bad
        }
    }
    private var bg: Color {
        switch style {
        case .neutral: return Color.primary.opacity(0.10)
        case .warn: return AgentPalette.warnFill
        case .bad: return AgentPalette.badFill
        }
    }
}

struct AgentDot: View {
    let agent: String
    var size: CGFloat = 7
    var body: some View {
        Circle().fill(AgentPalette.color(for: agent)).frame(width: size, height: size)
    }
}

/// 按 agent 分色的堆叠条，宽度按 cost 占比；段与段之间留 2pt 缝。
struct StackedBar: View {
    let segments: [AgentCost]
    var height: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            let total = max(segments.reduce(0) { $0 + $1.cost }, 0)
            let visible = segments.filter { $0.cost > 0 }
            let gaps = CGFloat(max(visible.count - 1, 0)) * 2
            let avail = max(geo.size.width - gaps, 0)
            HStack(spacing: 2) {
                if total <= 0 {
                    Capsule().fill(AgentPalette.track)
                } else {
                    ForEach(visible) { s in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(AgentPalette.color(for: s.agent))
                            .frame(width: max(avail * CGFloat(s.cost / total), 2))
                            .help("\(s.label): \(Fmt.money(s.cost)) (\(Fmt.percent(s.cost / total)))")
                    }
                }
            }
        }
        .frame(height: height)
        .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}

/// 一行横向条：标签 + 条 + 数值。
struct HBarRow: View {
    let label: String
    let color: Color
    let fraction: Double
    let value: String
    var detail: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Circle().fill(color).frame(width: 7, height: 7)
                Text(label).font(.system(size: 11.5))
                Spacer(minLength: 6)
                if let detail { Text(detail).font(.system(size: 10)).foregroundStyle(.secondary) }
                Text(value).font(.system(size: 11.5, weight: .medium)).monospacedDigit()
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3).fill(AgentPalette.track)
                    RoundedRectangle(cornerRadius: 3).fill(color)
                        .frame(width: max(geo.size.width * CGFloat(min(max(fraction, 0), 1)), 2))
                }
            }
            .frame(height: 7)
        }
    }
}

struct Legend: View {
    let agents: [(key: String, label: String)]
    var body: some View {
        HStack(spacing: 10) {
            ForEach(agents, id: \.key) { a in
                HStack(spacing: 4) {
                    AgentDot(agent: a.key)
                    Text(a.label).font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
        }
    }
}
