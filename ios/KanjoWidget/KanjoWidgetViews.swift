import Foundation
import KanjoCore
import SwiftUI
import WidgetKit

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

// MARK: - 按天热力条（沿用 App HeatStrip 配色与 5 档透明度）

struct WidgetDailyHeatStrip: View {
    let days: [WidgetDayCost]
    var isStale: Bool = false
    var barHeight: CGFloat = 22
    var cornerRadius: CGFloat = 3
    var spacing: CGFloat = 3

    @Environment(\.widgetRenderingMode) private var renderingMode

    private static let opacities: [Double] = [0, 0.3, 0.52, 0.76, 1]

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
        let opacityIndex = min(max(level, 0), Self.opacities.count - 1)
        if !rendersInFullColor {
            // 锁屏活力渲染与主屏着色模式不保留自定义色，用透明度分档交给系统着色。
            shape
                .fill(Color.primary.opacity(level == 0 ? 0.18 : Self.opacities[opacityIndex]))
                .widgetAccentable(level > 0)
        } else {
            let weekLike = WeekCost(
                start: .distantPast,
                cost: day.cost,
                byAgent: (day.byAgent?.isEmpty == false) ? day.byAgent! : ["claude": day.cost]
            )
            let segments = HeatStrip.segments(weekLike)
            if level == 0 || segments.isEmpty {
                shape.fill(IOSPalette.heatEmpty)
            } else {
                let cumulative = segments.indices.map { idx in
                    segments[0...idx].reduce(0.0) { $0 + $1.share }
                }
                GeometryReader { geo in
                    ZStack(alignment: .top) {
                        ForEach(segments.indices.reversed(), id: \.self) { index in
                            Rectangle()
                                .fill(IOSPalette.agent(segments[index].agent))
                                .frame(
                                    height: index == segments.count - 1
                                        ? geo.size.height
                                        : LayoutMath.segmentHeight(available: geo.size.height, share: cumulative[index])
                                )
                        }
                    }
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .top)
                    .clipShape(shape)
                    .compositingGroup()
                    .opacity(Self.opacities[opacityIndex])
                }
            }
        }
    }
}

// MARK: - W1: 今天（主屏小 / 中）

struct TodayWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetFamily) private var family
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

            Text(amountText)
                .font(.system(size: isMedium ? 34 : 28, weight: .bold, design: .rounded))
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
}

// MARK: - W2: 额度（主屏小 / 中）

struct QuotaWidgetView: View {
    let entry: KanjoWidgetEntry
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode

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
                Text(resetsAt, style: .relative)
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
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
                Text(resetsAt, style: .relative)
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
                    .lineLimit(1)
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
                (Text("\(name) \(windowLabel) \(Int(pct.rounded()))% · ") + Text(resetsAt, style: .relative))
                    .opacity(isStale ? 0.65 : 1.0)
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
