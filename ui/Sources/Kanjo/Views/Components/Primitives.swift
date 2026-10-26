import SwiftUI
import KanjoCore

// 版式常量：整个面板只用这几档字号，层级靠字号 / 字重 / 次要色，不靠边框。
enum Metrics {
    static let pagePadding: CGFloat = 14
    static let sectionSpacing: CGFloat = 18
    static let rowInset: CGFloat = 10
    static let groupRadius: CGFloat = 10
    // 总览：列表行直接放在面板上（没有分组底色）。页边距更窄，行内缩进更大，
    // 这样悬停高亮能铺满行宽，文字仍与 hero 对齐，hairline 从文字起点开始。
    static let flatPagePadding: CGFloat = 8
    static let listInset: CGFloat = 16
    static let rowRadius: CGFloat = 6
}

/// 一节：小号全大写标题 + 内容。默认内容放在一层淡底的分组里；`inset` 为 true 时内容自带内边距（图表、数字），
/// 为 false 时由行自己负责内边距（列表）。`flat` 为 true 时没有分组底色，行直接放在面板上（总览列表）。
struct PanelSection<Content: View, Trailing: View>: View {
    let title: String
    var inset: Bool
    var flat: Bool
    @ViewBuilder var trailing: () -> Trailing
    @ViewBuilder var content: () -> Content

    init(_ title: String, inset: Bool = false, flat: Bool = false,
         @ViewBuilder trailing: @escaping () -> Trailing = { EmptyView() },
         @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.inset = inset
        self.flat = flat
        self.trailing = trailing
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: flat ? 2 : 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                SectionTitle(title)
                Spacer(minLength: 8)
                trailing()
            }
            .padding(.horizontal, flat ? Metrics.listInset : Metrics.rowInset)
            .padding(.bottom, flat ? 2 : 0)
            let inner = VStack(alignment: .leading, spacing: inset ? 8 : 0) {
                content()
            }
            .padding(inset ? Metrics.rowInset : 0)
            if flat {
                inner.frame(maxWidth: .infinity, alignment: .leading)
            } else {
                inner.groupedBackground()
            }
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

/// 行与行之间的缩进 hairline。`trailing` 给直接放在面板上的列表用（两端都与文字对齐）。
struct RowDivider: View {
    var inset: CGFloat = Metrics.rowInset
    var trailing: CGFloat = 0
    var body: some View {
        Divider().opacity(0.6).padding(.leading, inset).padding(.trailing, trailing)
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

/// cost_note：info 图标 + 原文，caption 字号、三级色，可折成多行。原文、不可隐藏。
struct CostNote: View {
    let text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Image(systemName: "info.circle")
            Text(displayText)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.tertiary)
    }

    private var displayText: String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == "API-equivalent cost estimated from public API prices. Not actual subscription spend." {
            return L10n.tr("common.cost_note_default")
        }
        return text
    }
}

/// 大号金额：圆体 + 等宽数字。
struct HeroAmount: View {
    let value: String
    var size: CGFloat = 34
    var color: Color = .primary
    var body: some View {
        Text(value)
            .font(.system(size: size, weight: .semibold, design: .rounded).monospacedDigit())
            .foregroundStyle(color)
            .lineLimit(1).minimumScaleFactor(0.6)
            .textSelection(.enabled)
    }
}

struct Badge: View {
    enum Style { case neutral, good, warn, bad }
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
        case .good: return AgentPalette.good
        case .warn: return AgentPalette.warnInk
        case .bad: return AgentPalette.bad
        }
    }
    private var bg: Color {
        switch style {
        case .neutral: return Color.primary.opacity(0.07)
        case .good: return AgentPalette.goodFill
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

/// 项目用过的 agent：1–3 个色点，按花费降序（契约要求的「能看出用了哪些 agent 的标记」）。
/// tooltip 列出全部 agent 和占比。
struct AgentDots: View {
    let agents: [AgentCost]
    var size: CGFloat = 6

    var body: some View {
        let used = agents.filter { $0.sessions > 0 || $0.cost > 0 }.sorted { $0.cost > $1.cost }
        let total = used.reduce(0) { $0 + $1.cost }
        if !used.isEmpty {
            HStack(spacing: 3) {
                ForEach(used.prefix(3)) { a in AgentDot(agent: a.agent, size: size) }
            }
            .help(used.map { a in
                total > 0 ? "\(a.label) \(Fmt.percent(a.cost / total))" : a.label
            }.joined(separator: " · "))
        }
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

/// agent 图例。放不下全名时用名字的第一个词（"Claude Code" → "Claude"），再放不下只留色点；
/// 绝不截断，全名始终在 tooltip 里。
struct Legend: View {
    let agents: [(key: String, label: String)]
    var body: some View {
        ViewThatFits(in: .horizontal) {
            row { $0 }
            row { String($0.split(separator: " ").first ?? Substring($0)) }
            row { _ in nil }
        }
    }

    private func row(_ name: @escaping (String) -> String?) -> some View {
        HStack(spacing: 9) {
            ForEach(agents, id: \.key) { a in
                HStack(spacing: 4) {
                    AgentDot(agent: a.key, size: 6)
                    if let n = name(a.label) {
                        Text(n).font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
                .help(a.label)
            }
        }
        .lineLimit(1)
        .fixedSize()
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
            Text(expanded ? L10n.tr("common.show_fewer") : L10n.tr("common.show_all", total, noun))
                .font(.system(size: 11))
                .foregroundStyle(Color.accentColor)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// 视图层的短日期：同一年省略年份，今天 / 昨天用相对说法。只用于展示，不改数据。
enum ShortDate {
    private static func templateFormatter(_ template: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = Calendar.current
        f.setLocalizedDateFormatFromTemplate(template)
        return f
    }

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
            ? templateFormatter("MMMd").string(from: d) : Fmt.day(s)
    }

    /// "today" / "yesterday" / day(_:)。
    static func relative(_ s: String?) -> String {
        guard let s, let d = ReportDates.parseDay(s) else { return Fmt.day(s) }
        let cal = Calendar.current
        if cal.isDateInToday(d) { return L10n.tr("common.today") }
        if cal.isDateInYesterday(d) { return L10n.tr("common.yesterday") }
        return day(s)
    }

    /// "Jun 28 – Oct 23, 2026"；跨年时两端都带年份。`compact` 时两端都在今年就连年份也省掉（"Jun 28 – Oct 23"）。
    /// 首尾同一天时只显示单日（`compact` 为 "Oct 23"，否则为 "Oct 23, 2026"）。
    static func range(_ a: String?, _ b: String?, compact: Bool = false) -> String {
        guard let a, let b, let da = ReportDates.parseDay(a), let db = ReportDates.parseDay(b) else {
            return a == b ? Fmt.day(a) : "\(Fmt.day(a)) – \(Fmt.day(b))"
        }
        if da == db {
            return compact ? day(a) : Fmt.day(a)
        }
        let cal = Calendar.current
        let thisYear = cal.component(.year, from: Date())
        let f = templateFormatter("MMMd")
        if compact, cal.component(.year, from: da) == thisYear, cal.component(.year, from: db) == thisYear {
            return "\(f.string(from: da)) – \(f.string(from: db))"
        }
        if cal.component(.year, from: da) == cal.component(.year, from: db) {
            return "\(f.string(from: da)) – \(Fmt.day(b))"
        }
        return "\(Fmt.day(a)) – \(Fmt.day(b))"
    }

    static func clock(_ d: Date) -> String { hourMinute.string(from: d) }
}
