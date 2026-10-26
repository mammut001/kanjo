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

    /// 当文本非空时附加悬停卡提示（兼容旧调用，已迁移为 hoverTip）。
    @ViewBuilder
    func helpIfPresent(_ text: String?) -> some View {
        self.hoverTip(text)
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
            .hoverTip(help)
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
/// tooltip 列出全部 agent 和花费、token。
struct AgentDots: View {
    let agents: [AgentCost]
    var currency: String = "USD"
    var size: CGFloat = 6
    var id: String? = nil

    var body: some View {
        let used = agents.filter { $0.sessions > 0 || $0.cost > 0 || $0.tokens.total > 0 }.sorted { $0.cost > $1.cost }
        if !used.isEmpty {
            let helpText = TooltipBuilder.agentLines(agents: used, currency: currency).joined(separator: "\n")
            let totalCost = used.reduce(0.0) { $0 + $1.cost }
            let totalTokens = used.reduce(0) { $0 + $1.tokens.total }
            let rows = HoverCardRowBuilder.agentRows(agents: used.map { ($0.agent, $0.label, $0.cost, $0.tokens.total) })
            HStack(spacing: 3) {
                ForEach(used.prefix(3)) { a in AgentDot(agent: a.agent, size: size) }
            }
            .hoverCard(id: id) {
                AgentRowsHoverCard(
                    title: L10n.tr("project.section.by_agent"),
                    cost: totalCost,
                    tokens: totalTokens,
                    currency: currency,
                    rows: rows
                )
            }
            .accessibilityLabel(helpText)
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
    var help: String? = nil
    var card: (() -> AnyView)? = nil

    @ViewBuilder
    var body: some View {
        let content = VStack(alignment: .leading, spacing: 5) {
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

        if let card {
            content.hoverCard { card() }
        } else {
            content.hoverTip(help)
        }
    }
}

/// 自动折行的流式布局（按从左到右填充，放不下则折到下一行）。
struct FlowLayout: Layout {
    var spacing: CGFloat
    var lineSpacing: CGFloat

    init(spacing: CGFloat = 8, lineSpacing: CGFloat = 4) {
        self.spacing = spacing
        self.lineSpacing = lineSpacing
    }

    struct Row {
        var elements: [(subview: LayoutSubview, size: CGSize)] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    struct Cache {
        var lastWidth: CGFloat?
        var rows: [Row] = []
        var size: CGSize = .zero
    }

    func makeCache(subviews: Subviews) -> Cache {
        Cache()
    }

    func updateCache(_ cache: inout Cache, subviews: Subviews) {
        cache = Cache()
    }

    private func arrange(width: CGFloat?, subviews: Subviews) -> (rows: [Row], size: CGSize) {
        let maxWidth = width.flatMap { $0.isFinite ? $0 : nil } ?? .infinity
        var rows: [Row] = []
        var currentRow = Row()

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            let proposedWidth = currentRow.elements.isEmpty
                ? size.width
                : currentRow.width + spacing + size.width

            if !currentRow.elements.isEmpty && proposedWidth > maxWidth + 0.5 {
                rows.append(currentRow)
                currentRow = Row(elements: [(subview, size)], width: size.width, height: size.height)
            } else {
                currentRow.elements.append((subview, size))
                currentRow.width = proposedWidth
                currentRow.height = max(currentRow.height, size.height)
            }
        }
        if !currentRow.elements.isEmpty {
            rows.append(currentRow)
        }

        if rows.isEmpty {
            return ([], .zero)
        }
        let maxRowWidth = rows.map(\.width).max() ?? 0
        let totalSpacing = CGFloat(rows.count - 1) * lineSpacing
        let totalHeight = rows.map(\.height).reduce(0, +) + totalSpacing
        return (rows, CGSize(width: maxRowWidth, height: totalHeight))
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        let result = arrange(width: proposal.width, subviews: subviews)
        cache.lastWidth = proposal.width
        cache.rows = result.rows
        cache.size = result.size
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        let rows: [Row]
        if let last = cache.lastWidth, abs(last - bounds.width) < 1.0, !cache.rows.isEmpty {
            rows = cache.rows
        } else {
            rows = arrange(width: bounds.width, subviews: subviews).rows
        }

        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for item in row.elements {
                let yOffset = (row.height - item.size.height) / 2
                item.subview.place(
                    at: CGPoint(x: x, y: y + yOffset),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(item.size)
                )
                x += item.size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }
}

/// agent 图例：每个 agent 显示色点 + 名称，使用流式折行，按花费降序排列。
struct Legend: View {
    struct Item: Identifiable {
        let key: String
        let label: String
        var cost: Double = 0
        var tokens: Int = 0
        var id: String { key }

        init(key: String, label: String, cost: Double = 0, tokens: Int = 0) {
            self.key = key
            self.label = label
            self.cost = cost
            self.tokens = tokens
        }
    }

    let agents: [Item]
    var currency: String = "USD"

    init(agents: [(key: String, label: String)], currency: String = "USD") {
        self.agents = agents.map { Item(key: $0.key, label: $0.label) }
        self.currency = currency
    }

    init(items: [Item], currency: String = "USD") {
        self.agents = items
        self.currency = currency
    }

    var body: some View {
        FlowLayout(spacing: 9, lineSpacing: 4) {
            ForEach(Array(agents.enumerated()), id: \.element.id) { idx, a in
                HStack(spacing: 4) {
                    AgentDot(agent: a.key, size: 6)
                    Text(a.label)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .hoverCard(id: idx == 0 ? "overview:hover:legend" : "overview:hover:legend:\(a.key)") {
                    AgentRowsHoverCard(
                        title: a.label,
                        titleDotColor: AgentPalette.color(for: a.key),
                        cost: a.cost,
                        tokens: a.tokens,
                        currency: currency,
                        rows: [HoverCardRowItem(id: a.key, label: a.label, cost: a.cost, tokens: a.tokens, fraction: 1.0)]
                    )
                }
                .accessibilityHint(helpText(for: a))
            }
        }
    }

    private func helpText(for a: Item) -> String {
        if a.cost > 0 || a.tokens > 0 {
            return TooltipBuilder.agentLine(label: a.label, cost: a.cost, tokens: a.tokens, currency: currency)
        }
        return a.label
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
