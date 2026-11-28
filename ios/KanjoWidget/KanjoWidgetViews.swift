import Foundation
import KanjoCore
import SwiftUI
import WidgetKit

// MARK: - 画廊用的 family 覆盖

/// `\.widgetFamily` 在 App 进程里是只读的。DEBUG 画廊用这个键把真实 family 传进同一份视图；
/// 小组件扩展不设置它，视图继续读系统的 `widgetFamily`。
struct KanjoWidgetFamilyOverrideKey: EnvironmentKey {
    static let defaultValue: WidgetFamily? = nil
}

extension EnvironmentValues {
    var kanjoWidgetFamilyOverride: WidgetFamily? {
        get { self[KanjoWidgetFamilyOverrideKey.self] }
        set { self[KanjoWidgetFamilyOverrideKey.self] = newValue }
    }
}

// MARK: - 时间线条目（视图和 Provider 共用；DEBUG 画廊也编译这份文件）

struct KanjoWidgetEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot?
    let selectedAgentID: String?
    let isPreview: Bool

    init(
        date: Date,
        snapshot: WidgetSnapshot?,
        selectedAgentID: String? = nil,
        isPreview: Bool = false
    ) {
        self.date = date
        self.snapshot = snapshot
        self.selectedAgentID = selectedAgentID
        self.isPreview = isPreview
    }

    /// 实际展示的单个 agent：用户显式选了就用用户选的；没选则用固定优先级里的默认 agent。
    var resolvedAgent: String? {
        if let selectedAgentID, !selectedAgentID.isEmpty {
            return selectedAgentID
        }
        return snapshot?.defaultQuotaAgent(now: date)
    }

    /// 中尺寸额度小组件最多展示两个 agent：先放主选 agent，再按同一优先级补一个有额度数据的 agent。
    var resolvedMediumQuotaAgents: [String] {
        guard let snapshot else { return [] }
        let available = snapshot.quotaAgents(now: date)
        if let selectedAgentID, !selectedAgentID.isEmpty {
            var list = [selectedAgentID]
            for candidate in available where candidate != selectedAgentID {
                list.append(candidate)
                if list.count >= 2 { break }
            }
            return list
        }
        return Array(available.prefix(2))
    }

    static func preview(now: Date = Date(), selectedAgentID: String? = nil) -> KanjoWidgetEntry {
        WidgetSnapshotCache.applySharedLanguagePreference()
        let sample = BundledSampleSnapshotSource().loadWidgetSnapshot(now: now)
        return KanjoWidgetEntry(
            date: now,
            snapshot: sample,
            selectedAgentID: selectedAgentID,
            isPreview: true
        )
    }
}

// MARK: - 状态与格式化辅助

enum WidgetFormatting {
    private static let clockFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    /// 正常显示 "10:42 更新" / "Updated 10:42"；超过 2 小时显示 "3 小时前" / "3h ago"。
    static func statusText(snapshot: WidgetSnapshot, now: Date) -> String {
        guard let generated = snapshot.generatedDate else { return "" }
        if snapshot.isStale(now: now) {
            let elapsed = max(0, now.timeIntervalSince(generated))
            let hours = max(2, Int((elapsed / 3600).rounded(.down)))
            if hours >= 48 {
                return L10n.tr("ios.widget.days_ago", hours / 24)
            }
            return L10n.tr("ios.widget.hours_ago", hours)
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.currentLanguage)
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = snapshot.resolvedTimezone
        f.dateFormat = "HH:mm"
        let clock = f.string(from: generated)
        return L10n.tr("ios.widget.updated_at", clock)
    }

    /// 紧凑角落时间（小组件宽度受限时使用）：正常显示 "10:42"，过期显示 "3h ago"。
    static func compactStatusText(snapshot: WidgetSnapshot, now: Date) -> String {
        guard let generated = snapshot.generatedDate else { return "" }
        if snapshot.isStale(now: now) {
            let elapsed = max(0, now.timeIntervalSince(generated))
            let hours = max(2, Int((elapsed / 3600).rounded(.down)))
            if hours >= 48 {
                return L10n.tr("ios.widget.days_ago", hours / 24)
            }
            return L10n.tr("ios.widget.hours_ago", hours)
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = snapshot.resolvedTimezone
        f.dateFormat = "HH:mm"
        return f.string(from: generated)
    }

    static func todayAmountText(snapshot: WidgetSnapshot, now: Date) -> String {
        guard let today = snapshot.todayCost(now: now) else { return "—" }
        return Fmt.money(today, currency: snapshot.currency)
    }

    static func yesterdayComparison(
        snapshot: WidgetSnapshot,
        now: Date,
        includeLabel: Bool
    ) -> (text: String, symbol: String?)? {
        guard let today = snapshot.todayCost(now: now) else { return nil }
        let yesterday = snapshot.yesterdayCost(now: now)
        let diff = today - yesterday
        let deltaText: String
        let arrow: String?
        if abs(diff) < 0.005 {
            deltaText = Fmt.money(0, currency: snapshot.currency)
            arrow = nil
        } else if diff > 0 {
            deltaText = "↑ " + Fmt.money(diff, currency: snapshot.currency)
            arrow = "↑"
        } else {
            deltaText = "↓ " + Fmt.money(abs(diff), currency: snapshot.currency)
            arrow = "↓"
        }
        if includeLabel {
            return (L10n.tr("ios.widget.vs_yesterday", deltaText), arrow)
        }
        return (deltaText, arrow)
    }

    static func quotaTint(for percent: Double, agent: String) -> Color {
        switch SubscriptionValue.level(percent) {
        case .normal: return IOSPalette.agent(agent)
        case .warning: return IOSPalette.quotaWarn
        case .critical: return IOSPalette.bad
        }
    }

    /// 重置时刻，不倒计时。5 小时窗口只显示本地时刻（“Resets 02:12” / “02:12 重置” / “Réinit. 02:12”），
    /// 周窗口再加应用语言的缩写星期（“Resets Tue 08:40” / “周二 08:40 重置” / “Réinit. mar. 08:40”）。
    /// 时刻用 `Text(date, style: .time)`，跟随系统 12/24 小时制和本地时区，文本不变，不用为它刷新时间线。
    static func resetClockText(_ date: Date, weekly: Bool) -> Text {
        let time = Text(date, style: .time)
        guard weekly else { return time }
        return Text(abbreviatedWeekday(date) + " ") + time
    }

    static func resetsAtText(_ date: Date, weekly: Bool) -> Text {
        let token = "\u{FFFC}"
        let formatted = L10n.tr("ios.widget.resets_at", token)
        let parts = formatted.components(separatedBy: token)
        let prefix = parts.first ?? ""
        let suffix = parts.dropFirst().joined()
        return Text(prefix) + resetClockText(date, weekly: weekly) + Text(suffix)
    }

    /// 缩写星期跟应用语言走（Tue / 周二 / mar.），和旁边的“Resets / 重置 / Réinit.”一致。
    /// 时区用本机，和 `Text(date, style: .time)` 的本地时刻对得上。
    private static func abbreviatedWeekday(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: L10n.currentLanguage)
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = .current
        formatter.setLocalizedDateFormatFromTemplate("EEE")
        return formatter.string(from: date)
    }
}

// MARK: - 未同步空状态

struct WidgetEmptySyncView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Circle()
                    .fill(IOSPalette.agent("claude"))
                    .frame(width: 8, height: 8)
                Text("Kanjo")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            Text(L10n.tr("ios.widget.setup_sync"))
                .font(.footnote.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

// MARK: - 按天热力条（色相沿用 App HeatStrip / AgentColors，按天按 agent 份额分段）

struct WidgetDailyHeatStrip: View {
    let days: [WidgetDayCost]
    var isStale: Bool = false
    var barHeight: CGFloat = 22
    var cornerRadius: CGFloat = 3
    var spacing: CGFloat = 3

    @Environment(\.widgetRenderingMode) private var renderingMode

    /// 着色 / 活力模式下不能用自定义色。最低非零档也要明显，不能再是近乎看不见的一抹。
    private static let accentOpacities: [Double] = [0.18, 0.62, 0.78, 0.9, 1]

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        let peak = days.map(\.cost).max() ?? 0
        HStack(spacing: spacing) {
            ForEach(days) { day in
                dayCell(day, level: HeatStrip.level(day.cost, max: peak))
                    .frame(maxWidth: .infinity)
                    .frame(height: barHeight)
            }
        }
        .opacity(isStale ? 0.55 : 1.0)
    }

    @ViewBuilder
    private func dayCell(_ day: WidgetDayCost, level: Int) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        if level == 0 {
            shape.fill(rendersInFullColor ? IOSPalette.heatZero : Color.primary.opacity(Self.accentOpacities[0]))
        } else if !rendersInFullColor {
            let opacityIndex = min(max(level, 1), Self.accentOpacities.count - 1)
            shape
                .fill(Color.primary.opacity(Self.accentOpacities[opacityIndex]))
                .widgetAccentable()
        } else {
            let segments = agentSegments(for: day)
            if segments.isEmpty {
                shape.fill(IOSPalette.heatLevelColor(agent: "claude", level: level))
            } else {
                let cumulative = segments.indices.map { idx in
                    segments[0...idx].reduce(0.0) { $0 + $1.share }
                }
                GeometryReader { geo in
                    ZStack(alignment: .top) {
                        ForEach(segments.indices.reversed(), id: \.self) { index in
                            Rectangle()
                                .fill(IOSPalette.heatLevelColor(agent: segments[index].agent, level: level))
                                .frame(
                                    height: index == segments.count - 1
                                        ? geo.size.height
                                        : LayoutMath.segmentHeight(available: geo.size.height, share: cumulative[index])
                                )
                        }
                    }
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .top)
                    .clipShape(shape)
                }
            }
        }
    }

    /// 和 App 热力条一样按 agent 份额纵向分段。没有 `by_agent` 时整格落到 Claude 的色相上，避免空拆分被画成灰。
    private func agentSegments(for day: WidgetDayCost) -> [(agent: String, share: Double)] {
        let byAgent = (day.byAgent?.isEmpty == false) ? day.byAgent! : ["claude": day.cost]
        let weekLike = WeekCost(start: .distantPast, cost: day.cost, byAgent: byAgent)
        return HeatStrip.segments(weekLike)
    }
}

// MARK: - W1: 今天（主屏小 / 中）

struct TodayWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetFamily) private var systemFamily
    @Environment(\.kanjoWidgetFamilyOverride) private var familyOverride
    @Environment(\.widgetRenderingMode) private var renderingMode

    private var family: WidgetFamily { familyOverride ?? systemFamily }

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        Group {
            if let snapshot = entry.snapshot {
                content(snapshot: snapshot)
            } else {
                WidgetEmptySyncView()
            }
        }
        .widgetURL(WidgetSnapshotCache.overviewDeepLink)
        .containerBackground(for: .widget) {
            Color(uiColor: .systemBackground)
        }
    }

    @ViewBuilder
    private func content(snapshot: WidgetSnapshot) -> some View {
        let now = entry.date
        let stale = snapshot.isStale(now: now)
        let isMedium = family == .systemMedium
        let heatCount = isMedium ? 14 : 7
        let heatDays = snapshot.recentDays(count: heatCount, now: now)
        let amountText = WidgetFormatting.todayAmountText(snapshot: snapshot, now: now)
        let comparison = WidgetFormatting.yesterdayComparison(
            snapshot: snapshot,
            now: now,
            includeLabel: isMedium
        )

        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(L10n.tr("ios.widget.today_title"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 4)
                Text(isMedium
                     ? WidgetFormatting.statusText(snapshot: snapshot, now: now)
                     : WidgetFormatting.compactStatusText(snapshot: snapshot, now: now))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
            }

            Spacer(minLength: 0)

            if isMedium {
                HStack(alignment: .center, spacing: 12) {
                    amountColumn(
                        amountText: amountText,
                        comparison: comparison,
                        stale: stale,
                        isMedium: true
                    )
                    TodayAgentSplitColumn(snapshot: snapshot, now: now, stale: stale)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                amountColumn(
                    amountText: amountText,
                    comparison: comparison,
                    stale: stale,
                    isMedium: false
                )
            }

            Spacer(minLength: 2)

            WidgetDailyHeatStrip(
                days: heatDays,
                isStale: stale,
                barHeight: isMedium ? 22 : 18,
                cornerRadius: 3,
                spacing: isMedium ? 3.5 : 3
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func amountColumn(
        amountText: String,
        comparison: (text: String, symbol: String?)?,
        stale: Bool,
        isMedium: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(amountText)
                .font(.system(size: isMedium ? 32 : 28, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(stale && rendersInFullColor ? Color.secondary : Color.primary)
                .opacity(stale && !rendersInFullColor ? 0.65 : 1)
                .lineLimit(1)
                .minimumScaleFactor(0.55)
                .widgetAccentable(!rendersInFullColor)

            if let comparison {
                Text(comparison.text)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            } else {
                Text(" ")
                    .font(.caption2)
                    .hidden()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// 中尺寸“今天”的右半：今天按 agent 拆分（最多 3 个，按花费从高到低）。
/// 没有 `by_agent` 时改为近 7 天合计和日均。只显示 agent，不显示项目名。
private struct TodayAgentSplitColumn: View {
    let snapshot: WidgetSnapshot
    let now: Date
    let stale: Bool

    private static let shownAgents = 3
    private static let trailingDays = 7

    var body: some View {
        if let agents = snapshot.todayAgentCosts(now: now) {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(agents.prefix(Self.shownAgents), id: \.agent) { item in
                    HStack(spacing: 4) {
                        Circle()
                            .fill(IOSPalette.agent(item.agent))
                            .frame(width: 7, height: 7)
                        Text(WidgetSnapshot.shortAgentLabel(for: item.agent))
                            .font(.caption2.weight(.medium))
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                        Spacer(minLength: 4)
                        Text(Fmt.money(item.cost, currency: snapshot.currency))
                            .font(.caption2.weight(.semibold))
                            .monospacedDigit()
                            .foregroundStyle(stale ? Color.secondary : Color.primary)
                            .lineLimit(1)
                            .layoutPriority(1)
                    }
                }
            }
        } else {
            let days = snapshot.recentDays(count: Self.trailingDays, now: now)
            let total = days.reduce(0.0) { $0 + ($1.cost.isFinite ? $1.cost : 0) }
            let average = total / Double(Self.trailingDays)
            VStack(alignment: .leading, spacing: 5) {
                fallbackRow(
                    title: L10n.tr("ios.widget.seven_day_total"),
                    value: Fmt.money(total, currency: snapshot.currency)
                )
                fallbackRow(
                    title: L10n.tr("ios.widget.daily_average"),
                    value: Fmt.money(average, currency: snapshot.currency)
                )
            }
        }
    }

    private func fallbackRow(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(value)
                .font(.caption.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(stale ? Color.secondary : Color.primary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
    }
}

// MARK: - W2: 额度（主屏小 / 中）

struct QuotaWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetFamily) private var systemFamily
    @Environment(\.kanjoWidgetFamilyOverride) private var familyOverride
    @Environment(\.widgetRenderingMode) private var renderingMode

    private var family: WidgetFamily { familyOverride ?? systemFamily }

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        Group {
            if let snapshot = entry.snapshot {
                if family == .systemMedium {
                    mediumContent(snapshot: snapshot)
                } else {
                    smallContent(snapshot: snapshot)
                }
            } else {
                WidgetEmptySyncView()
            }
        }
        .widgetURL(WidgetSnapshotCache.overviewDeepLink)
        .containerBackground(for: .widget) {
            Color(uiColor: .systemBackground)
        }
    }

    @ViewBuilder
    private func smallContent(snapshot: WidgetSnapshot) -> some View {
        let now = entry.date
        let stale = snapshot.isStale(now: now)
        let agent = entry.resolvedAgent

        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 5) {
                if let agent {
                    Circle()
                        .fill(IOSPalette.agent(agent))
                        .frame(width: 7, height: 7)
                    Text(WidgetSnapshot.shortAgentLabel(for: agent))
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                } else {
                    Text(L10n.tr("ios.widget.quota.name"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                Text(WidgetFormatting.compactStatusText(snapshot: snapshot, now: now))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
            }

            if let agent,
               let bars = nonEmptyBars(snapshot: snapshot, agent: agent, now: now) {
                Spacer(minLength: 0)
                VStack(alignment: .leading, spacing: 9) {
                    ForEach(bars) { bar in
                        WidgetQuotaBarItemView(
                            bar: bar,
                            agent: agent,
                            isStale: stale,
                            compact: false
                        )
                    }
                }
                Spacer(minLength: 0)
            } else {
                Spacer(minLength: 0)
                Text(L10n.tr("ios.widget.no_quota"))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func mediumContent(snapshot: WidgetSnapshot) -> some View {
        let now = entry.date
        let stale = snapshot.isStale(now: now)
        let amountText = WidgetFormatting.todayAmountText(snapshot: snapshot, now: now)
        let comparison = WidgetFormatting.yesterdayComparison(
            snapshot: snapshot,
            now: now,
            includeLabel: false
        )
        let agents = entry.resolvedMediumQuotaAgents

        HStack(spacing: 14) {
            // 左侧：今天花费
            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.tr("ios.widget.today_title"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)

                Spacer(minLength: 0)

                Text(amountText)
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(stale && rendersInFullColor ? Color.secondary : Color.primary)
                    .opacity(stale && !rendersInFullColor ? 0.65 : 1)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                    .widgetAccentable(!rendersInFullColor)

                if let comparison {
                    Text(comparison.text)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                        .lineLimit(1)
                }

                Spacer(minLength: 0)

                Text(WidgetFormatting.statusText(snapshot: snapshot, now: now))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            .frame(width: 108, alignment: .leading)

            Divider()

            // 右侧：最多两个 agent 的额度
            VStack(alignment: .leading, spacing: 8) {
                if agents.isEmpty {
                    Spacer(minLength: 0)
                    Text(L10n.tr("ios.widget.no_quota"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                } else {
                    ForEach(Array(agents.prefix(2).enumerated()), id: \.element) { index, agent in
                        if index > 0 {
                            Divider()
                        }
                        MediumAgentQuotaSummaryView(
                            snapshot: snapshot,
                            agent: agent,
                            now: now,
                            isStale: stale,
                            singleAgentMode: agents.count == 1
                        )
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private func nonEmptyBars(snapshot: WidgetSnapshot, agent: String, now: Date) -> [WidgetQuotaBar]? {
        let bars = snapshot.quotaBars(for: agent, now: now)
        return bars.isEmpty ? nil : bars
    }
}

private struct MediumAgentQuotaSummaryView: View {
    let snapshot: WidgetSnapshot
    let agent: String
    let now: Date
    let isStale: Bool
    let singleAgentMode: Bool

    var body: some View {
        let bars = snapshot.quotaBars(for: agent, now: now)
        VStack(alignment: .leading, spacing: singleAgentMode ? 8 : 4) {
            HStack(spacing: 5) {
                Circle()
                    .fill(IOSPalette.agent(agent))
                    .frame(width: 6, height: 6)
                Text(WidgetSnapshot.shortAgentLabel(for: agent))
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Spacer(minLength: 0)
            }

            if bars.isEmpty {
                Text(L10n.tr("ios.widget.no_quota"))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else if singleAgentMode {
                ForEach(bars) { bar in
                    WidgetQuotaBarItemView(bar: bar, agent: agent, isStale: isStale, compact: false)
                }
            } else {
                ForEach(bars) { bar in
                    WidgetQuotaBarItemView(bar: bar, agent: agent, isStale: isStale, compact: true)
                }
            }
        }
    }
}

private struct WidgetQuotaBarItemView: View {
    let bar: WidgetQuotaBar
    let agent: String
    let isStale: Bool
    let compact: Bool

    @Environment(\.widgetRenderingMode) private var renderingMode

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    private var windowTitle: String {
        if compact {
            return bar.id == "five_hour"
                ? L10n.tr("ios.widget.five_hour_short")
                : L10n.tr("ios.widget.weekly_short")
        }
        return SubscriptionValue.windowName(hours: bar.windowHours)
    }

    /// 5 小时窗口只写时刻；超过一天的周窗口加上星期。
    private var showsWeekday: Bool { bar.windowHours > 24 }

    var body: some View {
        if compact {
            compactRow
        } else {
            fullRow
        }
    }

    private var fullRow: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(windowTitle)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 4)
                if bar.isReset {
                    Text(L10n.tr("ios.widget.quota_reset"))
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                } else if let pct = bar.usedPercent {
                    Text(String(format: "%.0f%%", pct))
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(isStale ? .secondary : .primary)
                        .monospacedDigit()
                }
            }

            progressBar(height: 5)

            if !bar.isReset, let resetsAt = bar.resetsAt {
                WidgetFormatting.resetsAtText(resetsAt, weekly: showsWeekday)
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
    }

    private var compactRow: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(windowTitle)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 24, alignment: .leading)

                progressBar(height: 4)

                if bar.isReset {
                    Text(L10n.tr("ios.widget.quota_reset"))
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                } else if let pct = bar.usedPercent {
                    Text(String(format: "%.0f%%", pct))
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(isStale ? .secondary : .primary)
                        .monospacedDigit()
                        .frame(width: 28, alignment: .trailing)
                }
            }
            if !bar.isReset, let resetsAt = bar.resetsAt {
                WidgetFormatting.resetsAtText(resetsAt, weekly: showsWeekday)
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
    }

    private func progressBar(height: CGFloat) -> some View {
        let pct = bar.isReset ? 0 : (bar.usedPercent ?? 0)
        let tint: Color = rendersInFullColor
            ? WidgetFormatting.quotaTint(for: pct, agent: agent)
            : .primary
        return GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.15))
                Capsule()
                    .fill(tint)
                    .frame(
                        width: LayoutMath.barWidth(
                            available: geo.size.width,
                            fraction: pct / 100.0,
                            minWidth: 0
                        )
                    )
                    .opacity(isStale ? 0.55 : 1.0)
                    .widgetAccentable(!rendersInFullColor)
            }
        }
        .frame(height: height)
    }
}

// MARK: - W3: 额度圆环（锁屏 accessoryCircular）

struct QuotaRingWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetRenderingMode) private var renderingMode

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        content
            .widgetURL(WidgetSnapshotCache.overviewDeepLink)
            .containerBackground(.fill.tertiary, for: .widget)
    }

    @ViewBuilder
    private var content: some View {
        let now = entry.date
        if entry.snapshot == nil {
            Text(L10n.tr("ios.widget.setup_sync"))
                .font(.system(size: 11, weight: .medium))
                .multilineTextAlignment(.center)
                .minimumScaleFactor(0.4)
                .lineLimit(4)
                .widgetAccentable(!rendersInFullColor)
        } else if let snapshot = entry.snapshot,
                  let agent = entry.resolvedAgent,
                  let weekly = snapshot.weeklyQuotaBar(for: agent, now: now) {
            let stale = snapshot.isStale(now: now)
            if !weekly.isReset, let pct = weekly.usedPercent {
                Gauge(value: min(max(pct, 0), 100), in: 0...100) {
                    Text(WidgetSnapshot.shortAgentLabel(for: agent))
                } currentValueLabel: {
                    Text("\(Int(pct.rounded()))%")
                        .font(.system(.body, design: .rounded).weight(.semibold))
                        .monospacedDigit()
                        .opacity(stale ? 0.6 : 1.0)
                }
                .gaugeStyle(.accessoryCircularCapacity)
                .widgetAccentable(!rendersInFullColor)
            } else {
                Gauge(value: 0, in: 0...100) {
                    Text(WidgetSnapshot.shortAgentLabel(for: agent))
                } currentValueLabel: {
                    Text(L10n.tr("ios.widget.quota_reset"))
                        .font(.system(size: 10, weight: .semibold, design: .rounded))
                        .minimumScaleFactor(0.6)
                        .lineLimit(1)
                }
                .gaugeStyle(.accessoryCircularCapacity)
                .widgetAccentable(!rendersInFullColor)
            }
        } else {
            Text(L10n.tr("ios.widget.no_quota"))
                .font(.system(size: 11, weight: .medium))
                .multilineTextAlignment(.center)
                .minimumScaleFactor(0.4)
                .lineLimit(3)
                .widgetAccentable(!rendersInFullColor)
        }
    }
}

// MARK: - W4: 今天 + 5 小时（锁屏 accessoryRectangular）

struct TodayQuotaRectangularWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetRenderingMode) private var renderingMode

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        Group {
            if let snapshot = entry.snapshot {
                content(snapshot: snapshot)
            } else {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Kanjo")
                        .font(.caption.weight(.semibold))
                    Text(L10n.tr("ios.widget.setup_sync"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .widgetURL(WidgetSnapshotCache.overviewDeepLink)
        .containerBackground(.fill.tertiary, for: .widget)
    }

    @ViewBuilder
    private func content(snapshot: WidgetSnapshot) -> some View {
        let now = entry.date
        let stale = snapshot.isStale(now: now)
        let amountText = WidgetFormatting.todayAmountText(snapshot: snapshot, now: now)

        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(L10n.tr("ios.widget.today_title"))
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                Text(amountText)
                    .font(.system(.headline, design: .rounded).weight(.bold))
                    .monospacedDigit()
                    .opacity(stale ? 0.65 : 1.0)
                    .widgetAccentable(!rendersInFullColor)
                Spacer(minLength: 0)
            }

            quotaLine(snapshot: snapshot, now: now, isStale: stale)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .monospacedDigit()
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func quotaLine(snapshot: WidgetSnapshot, now: Date, isStale: Bool) -> some View {
        if let agent = entry.resolvedAgent,
           let bar = snapshot.fiveHourQuotaBar(for: agent, now: now)
            ?? snapshot.weeklyQuotaBar(for: agent, now: now) {
            let name = WidgetSnapshot.shortAgentLabel(for: agent)
            let windowLabel = bar.id == "five_hour"
                ? L10n.tr("ios.widget.five_hour_short")
                : L10n.tr("ios.widget.weekly_short")
            if bar.isReset {
                Text("\(name) \(windowLabel) · \(L10n.tr("ios.widget.quota_reset"))")
            } else if let pct = bar.usedPercent, let resetsAt = bar.resetsAt {
                (Text("\(name) \(windowLabel) \(Int(pct.rounded()))% · ")
                    + WidgetFormatting.resetClockText(resetsAt, weekly: bar.windowHours > 24))
                    .opacity(isStale ? 0.65 : 1.0)
                    .minimumScaleFactor(0.6)
            } else {
                Text(L10n.tr("ios.widget.no_quota"))
            }
        } else {
            Text(L10n.tr("ios.widget.no_quota"))
        }
    }
}

// MARK: - W5: 一行（锁屏时钟上方 accessoryInline）

struct TodayInlineWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetRenderingMode) private var renderingMode

    private var rendersInFullColor: Bool {
        if case .fullColor = renderingMode { return true }
        return false
    }

    var body: some View {
        Group {
            if let snapshot = entry.snapshot {
                let stale = snapshot.isStale(now: entry.date)
                Text(L10n.tr("ios.widget.inline_today", WidgetFormatting.todayAmountText(snapshot: snapshot, now: entry.date)))
                    .monospacedDigit()
                    .opacity(stale ? 0.65 : 1)
                    .widgetAccentable(!rendersInFullColor)
            } else {
                Text(L10n.tr("ios.widget.setup_sync"))
                    .widgetAccentable(!rendersInFullColor)
            }
        }
        .widgetURL(WidgetSnapshotCache.overviewDeepLink)
        .containerBackground(.fill.tertiary, for: .widget)
    }
}
