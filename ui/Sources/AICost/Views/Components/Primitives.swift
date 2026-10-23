import SwiftUI
import AICostCore

// 版式常量：整个面板只用这几档字号，层级靠字号 / 字重 / 次要色，不靠边框。
enum Metrics {
    static let pagePadding: CGFloat = 14
    static let sectionSpacing: CGFloat = 18
    static let rowInset: CGFloat = 10
    static let groupRadius: CGFloat = 10
}

/// 一节：小号全大写标题 + 一层淡底的内容组。`inset` 为 true 时内容自带内边距（图表、数字），
/// 为 false 时由行自己负责内边距（列表）。
struct PanelSection<Content: View, Trailing: View>: View {
    let title: String
    var inset: Bool
    @ViewBuilder var trailing: () -> Trailing
    @ViewBuilder var content: () -> Content

    init(_ title: String, inset: Bool = false,
         @ViewBuilder trailing: @escaping () -> Trailing = { EmptyView() },
         @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.inset = inset
        self.trailing = trailing
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                SectionTitle(title)
                Spacer(minLength: 8)
                trailing()
            }
            .padding(.horizontal, Metrics.rowInset)
            VStack(alignment: .leading, spacing: inset ? 8 : 0) {
                content()
            }
            .padding(inset ? Metrics.rowInset : 0)
            .groupedBackground()
        }
    }
}

struct SectionTitle: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.5)
            .foregroundStyle(.secondary)
    }
}

extension View {
    /// 分组的唯一视觉手段：一层很淡的底色，没有描边。
    func groupedBackground() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Metrics.groupRadius, style: .continuous)
                .fill(AgentPalette.groupFill))
            .clipShape(RoundedRectangle(cornerRadius: Metrics.groupRadius, style: .continuous))
    }
}

/// 组内行与行之间的缩进 hairline。
struct RowDivider: View {
    var body: some View {
        Divider().opacity(0.6).padding(.leading, Metrics.rowInset)
    }
}

/// 状态块（schema 警告 / 刷新失败 / 对账失败 / 设置里的 --data 提示）：只在出问题时出现，淡色填充 + 状态色文字。
struct StatusBlock<Content: View>: View {
    enum Kind { case warn, bad }
    let kind: Kind
    let icon: String
    @ViewBuilder var content: () -> Content

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: icon)
            VStack(alignment: .leading, spacing: 3) { content() }
            Spacer(minLength: 0)
        }
        .font(.system(size: 10.5, weight: .medium))
        .foregroundStyle(kind == .bad ? AgentPalette.bad : AgentPalette.warnInk)
        .padding(.horizontal, 10).padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(kind == .bad ? AgentPalette.badFill : AgentPalette.warnFill))
    }
}

/// cost_note：一行小字 + info 图标，次要色。原文、不可隐藏。
struct CostNote: View {
    let text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Image(systemName: "info.circle")
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.secondary)
    }
}

/// 大号金额：圆体 + 等宽数字。
struct HeroAmount: View {
    let value: String
    var size: CGFloat = 34
    var body: some View {
        Text(value)
            .font(.system(size: size, weight: .semibold, design: .rounded).monospacedDigit())
            .foregroundStyle(.primary)
            .lineLimit(1).minimumScaleFactor(0.6)
            .textSelection(.enabled)
    }
}

/// hero 下方的次要数字：值 + 标签，无边框。
struct MinorStat: View {
    let value: String
    let label: String
    var help: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value)
                .font(.system(size: 15, weight: .semibold, design: .rounded).monospacedDigit())
                .lineLimit(1).minimumScaleFactor(0.7)
            Text(label).font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .help(help ?? "")
    }
}

struct Badge: View {
    enum Style { case neutral, warn, bad }
    let text: String
    var style: Style = .neutral
    var help: String? = nil

    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .medium))
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
        case .neutral: return Color.primary.opacity(0.07)
        case .warn: return AgentPalette.warnFill
        case .bad: return AgentPalette.badFill
        }
    }
}

struct AgentDot: View {
    let agent: String
    var size: CGFloat = 6
    var body: some View {
        Circle().fill(AgentPalette.color(for: agent)).frame(width: size, height: size)
    }
}

/// 按 agent 分段的细条。整条长度 = `fraction`（占可用宽度的比例，例如该项目 / 最大项目），
/// 条内各段按 cost 占比；没有底轨，长度本身就是信息。
struct StackedBar: View {
    let segments: [AgentCost]
    var fraction: Double = 1
    var height: CGFloat = 3

    var body: some View {
        GeometryReader { geo in
            let total = segments.reduce(0) { $0 + $1.cost }
            let visible = segments.filter { $0.cost > 0 }
            let width = max(geo.size.width * CGFloat(min(max(fraction, 0), 1)), 3)
            let gaps = CGFloat(max(visible.count - 1, 0))
            let avail = max(width - gaps, 0)
            HStack(spacing: 1) {
                if total <= 0 {
                    Capsule().fill(Color.primary.opacity(0.1)).frame(width: width)
                } else {
                    ForEach(visible) { s in
                        Rectangle()
                            .fill(AgentPalette.color(for: s.agent))
                            .frame(width: max(avail * CGFloat(s.cost / total), 1))
                            .help("\(s.label): \(Fmt.money(s.cost)) (\(Fmt.percent(s.cost / total)))")
                    }
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: height)
    }
}

/// 一行：色点 + 标签 + 明细 + 数值，下方一根按比例的细条（无底轨）。
struct HBarRow: View {
    let label: String
    let color: Color
    let fraction: Double
    let value: String
    var detail: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Circle().fill(color).frame(width: 6, height: 6).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(label).font(.system(size: 12))
                Spacer(minLength: 6)
                if let detail {
                    Text(detail).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                }
                Text(value).font(.system(size: 12, weight: .medium, design: .rounded)).monospacedDigit()
            }
            GeometryReader { geo in
                Capsule().fill(color)
                    .frame(width: max(geo.size.width * CGFloat(min(max(fraction, 0), 1)), 3))
            }
            .frame(height: 3)
        }
    }
}

struct Legend: View {
    let agents: [(key: String, label: String)]
    var body: some View {
        HStack(spacing: 9) {
            ForEach(agents, id: \.key) { a in
                HStack(spacing: 4) {
                    AgentDot(agent: a.key, size: 6)
                    Text(a.label).font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
        }
        .lineLimit(1)
    }
}

/// 详情页 / 设置页左上角的返回：纯文字按钮，强调色。
struct BackButton: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 2) {
                Image(systemName: "chevron.left").font(.system(size: 11, weight: .semibold))
                Text(title)
            }
            .font(.system(size: 12))
            .foregroundStyle(Color.accentColor)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// 「Show all N …」/「Show fewer」：组内最后一行的文字按钮。
struct ShowAllButton: View {
    @Binding var expanded: Bool
    let total: Int
    let noun: String
    var body: some View {
        Button {
            withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() }
        } label: {
            Text(expanded ? "Show fewer" : "Show all \(total) \(noun)")
                .font(.system(size: 11))
                .foregroundStyle(Color.accentColor)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// 视图层的短日期：同一年省略年份，今天 / 昨天用相对说法。只用于展示，不改数据。
enum ShortDate {
    private static let monthDay: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MMM d"
        return f
    }()
    private static let hourMinute: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    /// "Oct 23"（今年）或 "Oct 23, 2025"。
    static func day(_ s: String?) -> String {
        guard let s, let d = ReportDates.parseDay(s) else { return Fmt.day(s) }
        let cal = Calendar.current
        return cal.component(.year, from: d) == cal.component(.year, from: Date())
            ? monthDay.string(from: d) : Fmt.day(s)
    }

    /// "today" / "yesterday" / day(_:)。
    static func relative(_ s: String?) -> String {
        guard let s, let d = ReportDates.parseDay(s) else { return Fmt.day(s) }
        let cal = Calendar.current
        if cal.isDateInToday(d) { return "today" }
        if cal.isDateInYesterday(d) { return "yesterday" }
        return day(s)
    }

    /// "Jun 28 – Oct 23, 2026"；跨年时两端都带年份。
    static func range(_ a: String?, _ b: String?) -> String {
        guard let a, let b, let da = ReportDates.parseDay(a), let db = ReportDates.parseDay(b) else {
            return "\(Fmt.day(a)) – \(Fmt.day(b))"
        }
        let cal = Calendar.current
        if cal.component(.year, from: da) == cal.component(.year, from: db) {
            return "\(monthDay.string(from: da)) – \(Fmt.day(b))"
        }
        return "\(Fmt.day(a)) – \(Fmt.day(b))"
    }

    static func clock(_ d: Date) -> String { hourMinute.string(from: d) }
}
