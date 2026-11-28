#if DEBUG
import KanjoCore
import SwiftUI
import WidgetKit

/// DEBUG 画廊：`-widgetGallery` 时在 App 里用真实小组件视图按真实 family 尺寸铺开。
/// Release 不编译这份文件（见 Kanjo target 的 `EXCLUDED_SOURCE_FILE_NAMES`），整份内容也包在 `#if DEBUG` 里。
struct WidgetGalleryView: View {
    private let states = WidgetGalleryState.makeAll()

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 28) {
                    ForEach(states) { state in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(state.title)
                                .font(.headline)
                            GalleryFlowLayout(spacing: 16, lineSpacing: 16) {
                                ForEach(WidgetGalleryKind.allCases) { kind in
                                    galleryCard(kind: kind, entry: state.entry)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Widget Gallery")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    @ViewBuilder
    private func galleryCard(kind: WidgetGalleryKind, entry: KanjoWidgetEntry) -> some View {
        let shape = RoundedRectangle(cornerRadius: kind.cornerRadius, style: .continuous)
        VStack(alignment: .leading, spacing: 6) {
            Text(kind.title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            framed(kind: kind, entry: entry)
                .frame(width: kind.canvas.width, height: kind.canvas.height)
                .background(kind.accessory ? Color.black : Color(uiColor: .systemBackground))
                .clipShape(shape)
                .overlay(shape.stroke(Color.primary.opacity(0.15), lineWidth: 1))
        }
        .frame(width: kind.canvas.width, alignment: .leading)
    }

    /// 主屏小组件在系统里有 16pt 内容边距；锁屏 accessory 没有。边距放在画布尺寸里面，背景仍铺满卡片。
    @ViewBuilder
    private func framed(kind: WidgetGalleryKind, entry: KanjoWidgetEntry) -> some View {
        let view = kind.makeView(entry)
            .environment(\.kanjoWidgetFamilyOverride, kind.family)
            .environment(\.widgetRenderingMode, kind.accessory ? .vibrant : .fullColor)
            .padding(kind.contentMargin)
        if kind.accessory {
            view.environment(\.colorScheme, .dark)
        } else {
            view
        }
    }
}

/// 状态行里的卡片换行排，中尺寸不再被横向滚动裁到屏幕外。
private struct GalleryFlowLayout: Layout {
    var spacing: CGFloat = 16
    var lineSpacing: CGFloat = 16

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(maxWidth: proposal.width ?? .greatestFiniteMagnitude, subviews: subviews)
        let height = rows.reduce(CGFloat(0)) { $0 + $1.height }
            + lineSpacing * CGFloat(max(rows.count - 1, 0))
        let width = proposal.width ?? (rows.map(\.width).max() ?? 0)
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = rows(maxWidth: bounds.width, subviews: subviews)
        var y = bounds.minY
        var index = 0
        for row in rows {
            var x = bounds.minX
            for size in row.sizes {
                subviews[index].place(
                    at: CGPoint(x: x, y: y),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(width: size.width, height: size.height)
                )
                x += size.width + spacing
                index += 1
            }
            y += row.height + lineSpacing
        }
    }

    private struct Row {
        var sizes: [CGSize]
        var width: CGFloat
        var height: CGFloat
    }

    private func rows(maxWidth: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var sizes: [CGSize] = []
        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        func flush() {
            guard !sizes.isEmpty else { return }
            rows.append(Row(sizes: sizes, width: rowWidth, height: rowHeight))
            sizes = []
            rowWidth = 0
            rowHeight = 0
        }
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if !sizes.isEmpty, rowWidth + spacing + size.width > maxWidth {
                flush()
            }
            rowWidth = sizes.isEmpty ? size.width : rowWidth + spacing + size.width
            rowHeight = max(rowHeight, size.height)
            sizes.append(size)
        }
        flush()
        return rows
    }
}

private struct WidgetGalleryState: Identifiable {
    let id: String
    let title: String
    let entry: KanjoWidgetEntry

    static func makeAll() -> [WidgetGalleryState] {
        let source = BundledSampleSnapshotSource()
        guard let probe = source.loadWidgetSnapshot() else {
            return [WidgetGalleryState(
                id: "missing",
                title: "Sample snapshot missing",
                entry: KanjoWidgetEntry(date: Date(), snapshot: nil)
            )]
        }
        let zone = probe.resolvedTimezone
        let now = anchor(in: zone)
        guard let base = source.loadWidgetSnapshot(now: now) else {
            return [WidgetGalleryState(
                id: "missing",
                title: "Sample snapshot missing",
                entry: KanjoWidgetEntry(date: now, snapshot: nil)
            )]
        }

        var stale = base
        stale.generatedAt = iso(now.addingTimeInterval(-(WidgetSnapshot.staleThreshold + 90)))

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        var newDay = base
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now) {
            newDay.generatedAt = iso(yesterday)
        }

        var resetPassed = base
        resetPassed.quotaWindows = windowsReset(in: base.quotaWindows, at: now.addingTimeInterval(-120))

        let missingAgent = agentWithoutQuota(in: base)

        return [
            WidgetGalleryState(id: "normal", title: "Normal", entry: entry(base, now: now)),
            WidgetGalleryState(id: "stale", title: "Stale (>2 h)", entry: entry(stale, now: now)),
            WidgetGalleryState(id: "new-day", title: "New day (—)", entry: entry(newDay, now: now)),
            WidgetGalleryState(id: "never", title: "Never synced", entry: entry(nil, now: now)),
            WidgetGalleryState(id: "reset", title: "Quota reset passed", entry: entry(resetPassed, now: now)),
            WidgetGalleryState(
                id: "no-quota",
                title: "Selected agent without quota data (\(missingAgent))",
                entry: entry(base, now: now, agent: missingAgent)
            ),
        ]
    }

    private static func entry(_ snapshot: WidgetSnapshot?, now: Date, agent: String? = nil) -> KanjoWidgetEntry {
        KanjoWidgetEntry(date: now, snapshot: snapshot, selectedAgentID: agent, isPreview: true)
    }

    /// 15:00 in the snapshot zone, so “2 小时前”仍是同一天，跨天状态可以单独把 generatedAt 拨到昨天。
    private static func anchor(in zone: TimeZone) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        var parts = calendar.dateComponents([.year, .month, .day], from: Date())
        parts.hour = 15
        parts.minute = 0
        parts.second = 0
        return calendar.date(from: parts) ?? Date()
    }

    private static func iso(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    private static func windowsReset(in windows: [String: QuotaWindow]?, at past: Date) -> [String: QuotaWindow]? {
        guard var windows else { return nil }
        let stamp = iso(past)
        for key in windows.keys {
            var window = windows[key]!
            window.weeklyResetsAt = stamp
            if window.fiveHourResetsAt != nil || window.fiveHourUsedPercent != nil {
                window.fiveHourResetsAt = stamp
            }
            if var extras = window.extraWindows {
                for index in extras.indices {
                    extras[index].resetsAt = stamp
                }
                window.extraWindows = extras
            }
            windows[key] = window
        }
        return windows
    }

    private static func agentWithoutQuota(in snapshot: WidgetSnapshot) -> String {
        let present = Set((snapshot.quotaWindows ?? [:]).keys)
        let candidates = ["copilot", "opencode", "qwen", "minimax", "commandcode"]
        return candidates.first { !present.contains($0) } ?? "no-quota-agent"
    }
}

private enum WidgetGalleryKind: String, CaseIterable, Identifiable {
    case todaySmall
    case todayMedium
    case quotaSmall
    case quotaMedium
    case ring
    case rectangular
    case inline

    var id: String { rawValue }

    var title: String {
        switch self {
        case .todaySmall: return "Today · small"
        case .todayMedium: return "Today · medium"
        case .quotaSmall: return "Quota · small"
        case .quotaMedium: return "Quota · medium"
        case .ring: return "Ring"
        case .rectangular: return "Rectangular"
        case .inline: return "Inline"
        }
    }

    var family: WidgetFamily {
        switch self {
        case .todaySmall, .quotaSmall: return .systemSmall
        case .todayMedium, .quotaMedium: return .systemMedium
        case .ring: return .accessoryCircular
        case .rectangular: return .accessoryRectangular
        case .inline: return .accessoryInline
        }
    }

    var accessory: Bool {
        switch self {
        case .ring, .rectangular, .inline: return true
        case .todaySmall, .todayMedium, .quotaSmall, .quotaMedium: return false
        }
    }

    /// 和 WidgetKit 一样：主屏小/中 16pt，锁屏 accessory 无边距。
    var contentMargin: CGFloat {
        accessory ? 0 : 16
    }

    /// 393pt 宽 iPhone 的主屏小组件画布，以及锁屏圆形 / 矩形 / 一行的 complication 画布。
    var canvas: CGSize {
        switch family {
        case .systemSmall: return CGSize(width: 158, height: 158)
        case .systemMedium: return CGSize(width: 338, height: 158)
        case .accessoryCircular: return CGSize(width: 76, height: 76)
        case .accessoryRectangular: return CGSize(width: 172, height: 76)
        case .accessoryInline: return CGSize(width: 257, height: 26)
        default: return CGSize(width: 158, height: 158)
        }
    }

    var cornerRadius: CGFloat {
        accessory ? (family == .accessoryInline ? 8 : 16) : 22
    }

    @ViewBuilder
    func makeView(_ entry: KanjoWidgetEntry) -> some View {
        switch self {
        case .todaySmall, .todayMedium:
            TodayWidgetView(entry: entry)
        case .quotaSmall, .quotaMedium:
            QuotaWidgetView(entry: entry)
        case .ring:
            QuotaRingWidgetView(entry: entry)
        case .rectangular:
            TodayQuotaRectangularWidgetView(entry: entry)
        case .inline:
            TodayInlineWidgetView(entry: entry)
        }
    }
}
#endif
