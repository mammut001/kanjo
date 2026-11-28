import Foundation
import KanjoCore
import WidgetKit

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

    /// 实际展示的单个 agent：用户显式选了就用用户选的；没选则取额度数据最新的默认 agent。
    var resolvedAgent: String? {
        if let selectedAgentID, !selectedAgentID.isEmpty {
            return selectedAgentID
        }
        return snapshot?.defaultQuotaAgent(now: date)
    }

    /// 中尺寸额度小组件最多展示两个 agent：先放主选 agent，再补另一个有额度数据的最新 agent。
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

enum KanjoTimelineBuilder {
    static let refreshInterval: TimeInterval = 30 * 60

    static func makeEntries(
        snapshot: WidgetSnapshot?,
        selectedAgentID: String?,
        now: Date = Date()
    ) -> (entries: [KanjoWidgetEntry], reloadDate: Date) {
        let nextRefresh = now.addingTimeInterval(refreshInterval)
        guard let snapshot else {
            let entry = KanjoWidgetEntry(date: now, snapshot: nil, selectedAgentID: selectedAgentID)
            return ([entry], nextRefresh)
        }

        var checkpoints = Set<Date>([now])

        // 1. 所有额度重置时刻各插入一条时间线，重置点一到立刻切为“已重置”。
        for resetDate in snapshot.upcomingResetDates(after: now) {
            checkpoints.insert(resetDate)
        }

        // 2. 快照满 2 小时转为过期状态的时刻。
        if let generatedDate = snapshot.generatedDate {
            let staleTransition = generatedDate.addingTimeInterval(WidgetSnapshot.staleThreshold + 1)
            if staleTransition > now {
                checkpoints.insert(staleTransition)
            }
        }

        // 3. 报告时区下跨入次日零点时，今天花费立刻变为“—”。
        let cal = RangeEngine.calendar(timezone: snapshot.resolvedTimezone)
        let todayStart = cal.startOfDay(for: now)
        if let nextMidnight = cal.date(byAdding: .day, value: 1, to: todayStart), nextMidnight > now {
            checkpoints.insert(nextMidnight)
        }

        let sortedDates = checkpoints.sorted()
        let entries = sortedDates.map { date in
            KanjoWidgetEntry(date: date, snapshot: snapshot, selectedAgentID: selectedAgentID)
        }
        return (entries, nextRefresh)
    }
}

struct KanjoStaticTimelineProvider: TimelineProvider {
    func placeholder(in context: Context) -> KanjoWidgetEntry {
        .preview()
    }

    func getSnapshot(in context: Context, completion: @escaping (KanjoWidgetEntry) -> Void) {
        WidgetSnapshotCache.applySharedLanguagePreference()
        if context.isPreview {
            completion(.preview())
            return
        }
        // 真实主屏不用示例数据顶上；没缓存就走“打开 Kanjo 设置同步”。
        completion(KanjoWidgetEntry(date: Date(), snapshot: WidgetSnapshotCache.read()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<KanjoWidgetEntry>) -> Void) {
        Task {
            let now = Date()
            let snapshot = await WidgetSnapshotCache.fetchOrFallbackToCache()
            let built = KanjoTimelineBuilder.makeEntries(
                snapshot: snapshot,
                selectedAgentID: nil,
                now: now
            )
            completion(Timeline(entries: built.entries, policy: .after(built.reloadDate)))
        }
    }
}

struct KanjoQuotaIntentTimelineProvider: AppIntentTimelineProvider {
    typealias Entry = KanjoWidgetEntry
    typealias Intent = SelectQuotaAgentIntent

    func placeholder(in context: Context) -> KanjoWidgetEntry {
        .preview()
    }

    func snapshot(for configuration: SelectQuotaAgentIntent, in context: Context) async -> KanjoWidgetEntry {
        WidgetSnapshotCache.applySharedLanguagePreference()
        let selected = configuration.agent?.id
        if context.isPreview {
            return .preview(selectedAgentID: selected)
        }
        return KanjoWidgetEntry(date: Date(), snapshot: WidgetSnapshotCache.read(), selectedAgentID: selected)
    }

    func timeline(for configuration: SelectQuotaAgentIntent, in context: Context) async -> Timeline<KanjoWidgetEntry> {
        let now = Date()
        let selected = configuration.agent?.id
        let snapshot = await WidgetSnapshotCache.fetchOrFallbackToCache()
        let built = KanjoTimelineBuilder.makeEntries(
            snapshot: snapshot,
            selectedAgentID: selected,
            now: now
        )
        return Timeline(entries: built.entries, policy: .after(built.reloadDate))
    }
}
