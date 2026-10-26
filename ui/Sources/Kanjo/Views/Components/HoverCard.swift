import AppKit
import SwiftUI
import KanjoCore

// MARK: - 悬停卡外观与基础组件

/// 悬停卡的外观：实底 + 材质、细描边、柔和阴影、圆角 10。
struct HoverCardChrome: ViewModifier {
    init() {}
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 10, style: .continuous)
        content
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(
                shape.fill(.regularMaterial)
                    .background(shape.fill(Color(nsColor: .windowBackgroundColor).opacity(0.85)))
            )
            .overlay(shape.strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.18), radius: 10, y: 4)
    }
}

extension View {
    /// 附加悬停卡标准外观（材质、描边、阴影）。
    func hoverCard() -> some View { modifier(HoverCardChrome()) }
}

/// 悬停卡里的细进度条：浅底轨 + 彩色填充。
struct QuotaBar: View {
    let fraction: Double
    let color: Color
    var height: CGFloat = 4

    init(fraction: Double, color: Color, height: CGFloat = 4) {
        self.fraction = fraction
        self.color = color
        self.height = height
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                if fraction > 0 {
                    Capsule().fill(color).frame(width: max(height, geo.size.width * min(fraction, 1)))
                }
            }
        }
        .frame(height: height)
    }
}

// MARK: - 悬停卡宿主与 PreferenceKey

struct HoverCardPayload: Equatable {
    let id: String
    let anchor: Anchor<CGRect>
    let content: AnyView

    public static func == (lhs: HoverCardPayload, rhs: HoverCardPayload) -> Bool {
        lhs.id == rhs.id
    }
}

struct HoverCardPreferenceKey: PreferenceKey {
    public static var defaultValue: HoverCardPayload? = nil
    public static func reduce(value: inout HoverCardPayload?, nextValue: () -> HoverCardPayload?) {
        if let next = nextValue() {
            value = next
        }
    }
}

struct PinnedHoverIdKey: EnvironmentKey {
    public static let defaultValue: String? = nil
}

extension EnvironmentValues {
    var pinnedHoverId: String? {
        get { self[PinnedHoverIdKey.self] }
        set { self[PinnedHoverIdKey.self] = newValue }
    }
}

/// 悬停卡修饰器：悬停 0.35s 后激活，将锚点位置与卡片内容传递给顶层宿主。
private struct HoverCardModifier<CardContent: View>: ViewModifier {
    let id: String?
    let isPinned: Bool
    let cardContent: () -> CardContent

    @Environment(\.pinnedHoverId) private var envPinnedId
    @State private var isShowing = false
    @State private var hoverTask: Task<Void, Never>?

    private var effectivePinned: Bool {
        if isPinned { return true }
        if let id, let envPinnedId, id == envPinnedId { return true }
        return false
    }

    private var shouldShow: Bool {
        effectivePinned || isShowing
    }

    func body(content: Content) -> some View {
        content
            .onHover { hovering in
                hoverTask?.cancel()
                if hovering {
                    hoverTask = Task { @MainActor in
                        try? await Task.sleep(nanoseconds: 350_000_000)
                        if !Task.isCancelled {
                            withAnimation(.easeOut(duration: 0.12)) {
                                isShowing = true
                            }
                        }
                    }
                } else {
                    withAnimation(.easeIn(duration: 0.08)) {
                        isShowing = false
                    }
                }
            }
            .anchorPreference(key: HoverCardPreferenceKey.self, value: .bounds) { anchor in
                guard shouldShow else { return nil }
                return HoverCardPayload(
                    id: id ?? UUID().uuidString,
                    anchor: anchor,
                    content: AnyView(cardContent())
                )
            }
    }
}

extension View {
    /// 注册一个富文本彩色悬停卡。
    func hoverCard<Content: View>(
        id: String? = nil,
        isPinned: Bool = false,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        modifier(HoverCardModifier(id: id, isPinned: isPinned, cardContent: content))
    }

    /// 注册纯文本悬停卡，无缝替代系统 .help / helpIfPresent。
    @ViewBuilder
    func hoverTip(
        _ text: String?,
        id: String? = nil,
        isPinned: Bool = false
    ) -> some View {
        if let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            self.hoverCard(id: id, isPinned: isPinned) {
                PlainHoverCard(text: text)
            }
            .accessibilityLabel(text)
        } else {
            self
        }
    }
}

/// 顶层悬停卡宿主：根据 PreferenceKey 计算位置并浮动展示，防止被子视图截断。
struct HoverCardOverlayHost: View {
    let payload: HoverCardPayload?
    let containerSize: CGSize

    init(payload: HoverCardPayload?, containerSize: CGSize) {
        self.payload = payload
        self.containerSize = containerSize
    }

    var body: some View {
        if let payload {
            GeometryReader { rootGeo in
                let anchorRect = rootGeo[payload.anchor]
                if anchorRect.intersects(CGRect(origin: .zero, size: containerSize)) {
                    HoverCardPresenter(
                        anchorRect: anchorRect,
                        containerSize: containerSize,
                        content: payload.content
                    )
                    .id(payload.id)
                }
            }
            .allowsHitTesting(false)
        }
    }
}

private struct HoverCardPresenter: View {
    let anchorRect: CGRect
    let containerSize: CGSize
    let content: AnyView
    @State private var cardSize: CGSize = .zero

    var body: some View {
        let origin = HoverCardLayout.origin(
            anchor: anchorRect,
            cardSize: cardSize,
            container: containerSize,
            inset: 16,
            gap: 4
        )
        content
            .frame(maxWidth: 300)
            .fixedSize(horizontal: false, vertical: true)
            .background(
                GeometryReader { c in
                    Color.clear
                        .onAppear { cardSize = c.size }
                        .onChange(of: c.size) { cardSize = $0 }
                }
            )
            .position(
                x: origin.x + max(cardSize.width, 1) / 2,
                y: origin.y + max(cardSize.height, 1) / 2
            )
            .opacity(cardSize == .zero ? 0 : 1)
            .transition(.opacity)
    }
}

// MARK: - 纯文本悬停卡

struct PlainHoverCard: View {
    let text: String

    init(text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.system(size: 11))
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .hoverCard()
    }
}

// MARK: - 彩色富文本悬停卡组件

/// 额度卡：agent 色点 + 档位名做标题；每个窗口一行：细进度条、右对齐百分比、重置时间。
struct QuotaCard: View {
    let agent: String
    let planLabel: String
    let rows: [QuotaRow]

    init(agent: String, planLabel: String, rows: [QuotaRow]) {
        self.agent = agent
        self.planLabel = planLabel
        self.rows = rows
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 6) {
                AgentDot(agent: agent, size: 7)
                Text(planLabel).font(.system(size: 12, weight: .semibold)).lineLimit(1)
            }
            ForEach(rows) { r in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(r.title).font(.system(size: 11, weight: .medium))
                        Spacer(minLength: 8)
                        Text(r.percent.map { "\(Int($0.rounded()))%" } ?? "—")
                            .font(.system(size: 11.5, weight: .semibold, design: .rounded))
                            .monospacedDigit()
                            .foregroundStyle(r.percent == nil ? AnyShapeStyle(.tertiary) : AnyShapeStyle(.primary))
                    }
                    QuotaBar(fraction: (r.percent ?? 0) / 100, color: barColor(r.percent))
                    Text(r.detail)
                        .font(.system(size: 10))
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .monospacedDigit()
        .hoverCard()
    }

    private func barColor(_ pct: Double?) -> Color {
        switch SubscriptionValue.level(pct) {
        case .normal: return AgentPalette.color(for: agent)
        case .warning: return AgentPalette.quotaWarn
        case .critical: return AgentPalette.bad
        }
    }
}

/// 马赛克方块的悬停卡：标题行（色点 + 名字 + 金额），下面一行总 token；
/// 每个 agent（「+N more」块则是每个项目）一行：色点、名字、金额 · token，下方按占比的彩色细条。
struct MosaicHoverCard: View {
    let tile: MosaicView.Tile
    let currency: String

    init(tile: MosaicView.Tile, currency: String) {
        self.tile = tile
        self.currency = currency
    }

    private struct Line: Identifiable {
        let id: String, label: String, color: Color, cost: Double, tokens: Int
    }

    var body: some View {
        let lines = self.lines
        let peak = max(lines.map(\.cost).max() ?? 0, 0)
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(tile.color).frame(width: 7, height: 7)
                    Text(title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    Text(Fmt.money(tile.cost, currency: currency))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                }
                Text(L10n.tr("overview.tokens_count", Fmt.tokens(totalTokens)))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 13)
            }
            ForEach(lines.prefix(6)) { l in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Circle().fill(l.color).frame(width: 6, height: 6)
                        Text(l.label).font(.system(size: 11)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(Fmt.money(l.cost, currency: currency))
                            .font(.system(size: 11, weight: .medium, design: .rounded))
                        Text(L10n.tr("overview.tokens_count", Fmt.tokens(l.tokens)))
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .frame(minWidth: 62, alignment: .trailing)
                    }
                    QuotaBar(fraction: peak > 0 ? l.cost / peak : 0, color: l.color, height: 3)
                        .padding(.leading, 12)
                }
            }
            if lines.count > 6 {
                Text("+\(lines.count - 6)").font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
        .monospacedDigit()
        .hoverCard()
    }

    private var title: String {
        switch tile.kind {
        case .project(let p): return p.name
        case .more(let ps): return L10n.tr("mosaic.more.format", ps.count)
        }
    }

    private var totalTokens: Int {
        switch tile.kind {
        case .project(let p): return p.tokens.total
        case .more(let ps): return ps.reduce(0) { $0 + $1.tokens.total }
        }
    }

    private var lines: [Line] {
        let raw: [Line]
        switch tile.kind {
        case .project(let p):
            raw = p.byAgent.filter { $0.cost > 0 || $0.tokens.total > 0 }.map {
                Line(id: $0.agent, label: $0.label, color: AgentPalette.color(for: $0.agent),
                     cost: $0.cost, tokens: $0.tokens.total)
            }
        case .more(let ps):
            raw = ps.map { Line(id: $0.id, label: $0.name, color: ProjectTint.color(of: $0),
                                cost: $0.cost, tokens: $0.tokens.total) }
        }
        return raw.sorted { $0.cost != $1.cost ? $0.cost > $1.cost : $0.label < $1.label }
    }
}

/// Agent 列表悬停卡（用于 AgentDots、HeatStripView、DayChart 等）：
/// 标题行（总金额 + 总 token），下方各 Agent 的色点、名字、金额、token 与占比细条。
struct AgentRowsHoverCard: View {
    let title: String
    var titleDotColor: Color? = nil
    let cost: Double
    let tokens: Int
    let currency: String
    let rows: [HoverCardRowItem]
    var subtitle: String? = nil

    init(
        title: String,
        titleDotColor: Color? = nil,
        cost: Double,
        tokens: Int,
        currency: String,
        rows: [HoverCardRowItem],
        subtitle: String? = nil
    ) {
        self.title = title
        self.titleDotColor = titleDotColor
        self.cost = cost
        self.tokens = tokens
        self.currency = currency
        self.rows = rows
        self.subtitle = subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if let titleDotColor {
                        Circle().fill(titleDotColor).frame(width: 7, height: 7)
                    }
                    Text(title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    if cost > 0 {
                        Text(Fmt.money(cost, currency: currency))
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                    }
                }
                HStack(spacing: 6) {
                    if tokens > 0 {
                        Text(L10n.tr("overview.tokens_count", Fmt.tokens(tokens)))
                    }
                    if let subtitle {
                        Text(subtitle)
                    }
                }
                .font(.system(size: 10)).foregroundStyle(.secondary)
                .padding(.leading, titleDotColor == nil ? 0 : 13)
            }
            if !rows.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(rows.prefix(6)) { r in
                        let color = AgentPalette.color(for: r.id)
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Circle().fill(color).frame(width: 6, height: 6)
                                Text(r.label).font(.system(size: 11)).lineLimit(1)
                                Spacer(minLength: 8)
                                if r.cost > 0 {
                                    Text(Fmt.money(r.cost, currency: currency))
                                        .font(.system(size: 11, weight: .medium, design: .rounded))
                                }
                                if r.tokens > 0 {
                                    Text(L10n.tr("overview.tokens_count", Fmt.tokens(r.tokens)))
                                        .font(.system(size: 10)).foregroundStyle(.secondary)
                                        .frame(minWidth: 62, alignment: .trailing)
                                }
                            }
                            QuotaBar(fraction: r.fraction, color: color, height: 3)
                                .padding(.leading, 12)
                        }
                    }
                    if rows.count > 6 {
                        Text("+\(rows.count - 6)").font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                }
            }
        }
        .monospacedDigit()
        .hoverCard()
    }
}

/// 模型悬停卡：agent 色点 + 模型名 + 花费；下方展示总 token 及各类 token（input/output/cacheRead/cacheWrite）的构成细条。
struct ModelHoverCard: View {
    let model: String
    let agent: String
    let cost: Double
    let tokens: Tokens
    let currency: String

    init(model: String, agent: String, cost: Double, tokens: Tokens, currency: String) {
        self.model = model
        self.agent = agent
        self.cost = cost
        self.tokens = tokens
        self.currency = currency
    }

    var body: some View {
        let tokenRows = HoverCardRowBuilder.tokenRows(tokens: tokens)
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(AgentPalette.color(for: agent)).frame(width: 7, height: 7)
                    Text(model).font(.system(size: 12, weight: .semibold, design: .monospaced)).lineLimit(1)
                    Spacer(minLength: 8)
                    Text(Fmt.money(cost, currency: currency))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                }
                Text(L10n.tr("overview.tokens_count", Fmt.tokens(tokens.total)))
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.leading, 13)
            }
            if !tokenRows.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(tokenRows, id: \.id) { row in
                        let color = tokenColor(for: row.id)
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Circle().fill(color).frame(width: 6, height: 6)
                                Text(L10n.tr(row.labelKey)).font(.system(size: 11)).lineLimit(1)
                                Spacer(minLength: 8)
                                Text(Fmt.tokens(row.count))
                                    .font(.system(size: 10.5, weight: .medium, design: .rounded))
                                Text(Fmt.percent(row.fraction))
                                    .font(.system(size: 10)).foregroundStyle(.secondary)
                                    .frame(minWidth: 42, alignment: .trailing)
                            }
                            QuotaBar(fraction: row.fraction, color: color, height: 3)
                                .padding(.leading, 12)
                        }
                    }
                }
            }
        }
        .monospacedDigit()
        .hoverCard()
    }

    private func tokenColor(for id: String) -> Color {
        switch id {
        case "input": return AgentPalette.tokenInput
        case "output": return AgentPalette.tokenOutput
        case "cache_read": return AgentPalette.tokenCacheRead
        case "cache_write": return AgentPalette.tokenCacheWrite
        default: return .secondary
        }
    }
}

/// Token 构成悬停卡：四类计费 token 的构成明细（输入、输出、缓存读、缓存写）。
struct TokensBreakdownHoverCard: View {
    let tokens: Tokens
    var highlightedType: String? = nil

    init(tokens: Tokens, highlightedType: String? = nil) {
        self.tokens = tokens
        self.highlightedType = highlightedType
    }

    var body: some View {
        let tokenRows = HoverCardRowBuilder.tokenRows(tokens: tokens)
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(L10n.tr("project.section.tokens")).font(.system(size: 12, weight: .semibold))
                    Spacer(minLength: 8)
                    Text(Fmt.tokens(tokens.total))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                }
                if tokens.thinking > 0 {
                    Text(L10n.tr("project.token.thinking") + ": " + Fmt.tokens(tokens.thinking))
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
            ForEach(tokenRows, id: \.id) { row in
                let color = tokenColor(for: row.id)
                let isHighlighted = highlightedType == nil || highlightedType == row.id
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Circle().fill(color).frame(width: 6, height: 6)
                        Text(L10n.tr(row.labelKey)).font(.system(size: 11)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(Fmt.tokens(row.count))
                            .font(.system(size: 10.5, weight: .medium, design: .rounded))
                        Text(Fmt.percent(row.fraction))
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .frame(minWidth: 42, alignment: .trailing)
                    }
                    QuotaBar(fraction: row.fraction, color: color, height: 3)
                        .padding(.leading, 12)
                }
                .opacity(isHighlighted ? 1 : 0.45)
            }
        }
        .monospacedDigit()
        .hoverCard()
    }

    private func tokenColor(for id: String) -> Color {
        switch id {
        case "input": return AgentPalette.tokenInput
        case "output": return AgentPalette.tokenOutput
        case "cache_read": return AgentPalette.tokenCacheRead
        case "cache_write": return AgentPalette.tokenCacheWrite
        default: return .secondary
        }
    }
}

/// 订阅价值说明悬停卡：agent 色点 + 档位名，月费、周期用量、倍数说明。
struct SubscriptionValueHoverCard: View {
    let agent: String
    let planLabel: String
    let monthlyPriceUsd: Double?
    let usage: Double
    let multiplier: Double?
    let currency: String

    init(
        agent: String,
        planLabel: String,
        monthlyPriceUsd: Double?,
        usage: Double,
        multiplier: Double?,
        currency: String
    ) {
        self.agent = agent
        self.planLabel = planLabel
        self.monthlyPriceUsd = monthlyPriceUsd
        self.usage = usage
        self.multiplier = multiplier
        self.currency = currency
    }

    var body: some View {
        let price = Fmt.perMonth(monthlyPriceUsd, currency: currency)
        let usageText = Fmt.money(usage, currency: currency)
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                AgentDot(agent: agent, size: 7)
                Text(planLabel).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                Spacer(minLength: 8)
                if let m = multiplier {
                    Text(Fmt.multiple(m))
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(L10n.tr("settings.subscriptions.price"))
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    Spacer()
                    Text(price)
                        .font(.system(size: 10.5, design: .rounded)).monospacedDigit()
                }
                HStack {
                    Text(L10n.tr("overview.cycle_usage"))
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    Spacer()
                    Text(usageText)
                        .font(.system(size: 10.5, design: .rounded)).monospacedDigit()
                }
            }
            if let m = multiplier {
                Text(L10n.tr("overview.sub_help_multiplier", planLabel, price, usageText, Fmt.multiple(m)))
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(L10n.tr("overview.sub_help_unknown", planLabel, usageText))
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .monospacedDigit()
        .hoverCard()
    }
}

/// 对账说明悬停卡：状态图标与明细。
struct ReconciliationHoverCard: View {
    let ok: Bool
    let title: String
    let lines: [(Bool, String)]
    let contract: String

    init(ok: Bool, title: String, lines: [(Bool, String)], contract: String) {
        self.ok = ok
        self.title = title
        self.lines = lines
        self.contract = contract
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundStyle(ok ? AgentPalette.good : AgentPalette.bad)
                    .font(.system(size: 12))
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
            }
            VStack(alignment: .leading, spacing: 3) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Circle()
                            .fill(l.0 ? AgentPalette.good : AgentPalette.bad)
                            .frame(width: 5, height: 5)
                            .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
                        Text(l.1)
                            .font(.system(size: 10.5))
                            .foregroundStyle(l.0 ? .secondary : AgentPalette.bad)
                            .monospacedDigit()
                    }
                }
            }
            if !contract.isEmpty {
                Divider().opacity(0.3)
                Text(contract)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .monospacedDigit()
        .hoverCard()
    }
}
