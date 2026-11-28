import KanjoCore
import SwiftUI
import WidgetKit

/// W1: 今天（主屏小 / 中）
struct KanjoTodayWidget: Widget {
    let kind = "KanjoTodayWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: KanjoStaticTimelineProvider()) { entry in
            TodayWidgetView(entry: entry)
        }
        .configurationDisplayName(L10n.tr("ios.widget.today.name"))
        .description(L10n.tr("ios.widget.today.desc"))
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

/// W2: 额度（主屏小 / 中，支持选 Agent）
struct KanjoQuotaWidget: Widget {
    let kind = "KanjoQuotaWidget"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: kind,
            intent: SelectQuotaAgentIntent.self,
            provider: KanjoQuotaIntentTimelineProvider()
        ) { entry in
            QuotaWidgetView(entry: entry)
        }
        .configurationDisplayName(L10n.tr("ios.widget.quota.name"))
        .description(L10n.tr("ios.widget.quota.desc"))
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

/// W3: 额度圆环（锁屏圆形，支持选 Agent）
struct KanjoQuotaRingWidget: Widget {
    let kind = "KanjoQuotaRingWidget"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: kind,
            intent: SelectQuotaAgentIntent.self,
            provider: KanjoQuotaIntentTimelineProvider()
        ) { entry in
            QuotaRingWidgetView(entry: entry)
        }
        .configurationDisplayName(L10n.tr("ios.widget.quota_ring.name"))
        .description(L10n.tr("ios.widget.quota_ring.desc"))
        .supportedFamilies([.accessoryCircular])
    }
}

/// W4: 今天 + 5 小时（锁屏矩形，支持选 Agent）
struct KanjoTodayQuotaWidget: Widget {
    let kind = "KanjoTodayQuotaWidget"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: kind,
            intent: SelectQuotaAgentIntent.self,
            provider: KanjoQuotaIntentTimelineProvider()
        ) { entry in
            TodayQuotaRectangularWidgetView(entry: entry)
        }
        .configurationDisplayName(L10n.tr("ios.widget.today_quota.name"))
        .description(L10n.tr("ios.widget.today_quota.desc"))
        .supportedFamilies([.accessoryRectangular])
    }
}

/// W5: 一行（锁屏时钟上方）
struct KanjoInlineWidget: Widget {
    let kind = "KanjoInlineWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: KanjoStaticTimelineProvider()) { entry in
            TodayInlineWidgetView(entry: entry)
        }
        .configurationDisplayName(L10n.tr("ios.widget.inline.name"))
        .description(L10n.tr("ios.widget.inline.desc"))
        .supportedFamilies([.accessoryInline])
    }
}

@main
struct KanjoWidgetBundle: WidgetBundle {
    init() {
        WidgetSnapshotCache.applySharedLanguagePreference()
    }

    var body: some Widget {
        KanjoTodayWidget()
        KanjoQuotaWidget()
        KanjoQuotaRingWidget()
        KanjoTodayQuotaWidget()
        KanjoInlineWidget()
    }
}
