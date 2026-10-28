import Charts
import KanjoCore
import SwiftUI
import UIKit

struct ProjectDetailView: View {
    let project: Project
    let report: UsageReport
    @State private var range: TimeRange

    init(project: Project, report: UsageReport, range: TimeRange) {
        self.project = project
        self.report = report
        _range = State(initialValue: range)
    }

    private var currency: String { report.currency }

    private var filtered: FilteredProject {
        RangeEngine.filter(project, range: RangeEngine.spec(range, report: report),
                           fallbackAgent: OverviewView.fallbackAgent(project))
    }

    var body: some View {
        let result = filtered
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                header(result)
                tokensSection(result)
                agentsSection(result)
                modelsSection
                dayChartSection(result)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func header(_ result: FilteredProject) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(project.name)
                .font(.title2.weight(.semibold))
                .lineLimit(2)
            RangeSegmentedPicker(selection: $range)
            HStack(alignment: .bottom, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(Fmt.money(result.cost, currency: currency))
                            .font(.system(size: 46, weight: .semibold, design: .rounded))
                            .monospacedDigit()
                            .lineLimit(1)
                            .minimumScaleFactor(0.55)
                        if let note = report.costNoteDisplayText {
                            Image(systemName: "info.circle")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                                .accessibilityLabel(note)
                        }
                    }
                    Text(sessionSummary(result))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 3) {
                    Text(L10n.tr("project.last_8_weeks"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    ProjectHeatStrip(weeks: project.heatWeeks(endingOn: report.heatEndDate))
                }
                .padding(.bottom, 4)
            }
        }
    }

    private func sessionSummary(_ result: FilteredProject) -> String {
        guard result.firstActive != nil || result.sessions > 0 else {
            return L10n.tr("project.no_usage_range")
        }
        if result.sessions == 1 {
            return L10n.tr("overview.count.session.singular", result.sessions)
        }
        return L10n.tr("overview.count.session.plural", result.sessions)
    }

    /// 全量范围显示按类型的拆分；其他范围只有 total（和 Mac 一样给一句说明）。
    private func tokensSection(_ result: FilteredProject) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                SectionHeader(title: L10n.tr("project.section.tokens"))
                Spacer(minLength: 8)
                Text(L10n.tr("project.tokens_total", Fmt.tokens(result.tokens)))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
            VStack(alignment: .leading, spacing: 12) {
                if range == .all {
                    tokenBar(project.tokens)
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(spacing: 12) {
                            tokenMetric(L10n.tr("project.token.input"), project.tokens.input,
                                        IOSPalette.tokenInput)
                            tokenMetric(L10n.tr("project.token.output"), project.tokens.output,
                                        IOSPalette.tokenOutput)
                            tokenMetric(L10n.tr("project.token.thinking"), project.tokens.thinking, nil)
                        }
                        HStack(spacing: 12) {
                            tokenMetric(L10n.tr("project.token.cache_read"), project.tokens.cacheRead,
                                        IOSPalette.tokenCacheRead)
                            tokenMetric(L10n.tr("project.token.cache_write"), project.tokens.cacheWrite,
                                        IOSPalette.tokenCacheWrite)
                            Spacer(minLength: 0)
                        }
                    }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(Fmt.tokens(result.tokens))
                            .font(.system(size: 15, weight: .medium, design: .rounded).monospacedDigit())
                        Text(L10n.tr("project.breakdown_all_only"))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(14)
            .kanjoCard()
        }
    }

    private func tokenBar(_ tokens: Tokens) -> some View {
        let parts: [(tokens: Int, color: Color)] = [
            (tokens.input, IOSPalette.tokenInput),
            (tokens.output, IOSPalette.tokenOutput),
            (tokens.cacheRead, IOSPalette.tokenCacheRead),
            (tokens.cacheWrite, IOSPalette.tokenCacheWrite),
        ]
        let visible = parts.filter { $0.tokens > 0 }
        let total = max(visible.reduce(0) { $0 + $1.tokens }, 1)
        return GeometryReader { geo in
            let available = max(geo.size.width - CGFloat(max(visible.count - 1, 0)), 0)
            HStack(spacing: 1) {
                ForEach(Array(visible.enumerated()), id: \.offset) { _, part in
                    Rectangle()
                        .fill(part.color)
                        .frame(width: max(available * CGFloat(part.tokens) / CGFloat(total), 2))
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: 4)
    }

    private func tokenMetric(_ label: String, _ value: Int, _ color: Color?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                if let color {
                    Circle().fill(color).frame(width: 6, height: 6)
                } else {
                    Circle().strokeBorder(Color.secondary, lineWidth: 1).frame(width: 6, height: 6)
                }
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Text(Fmt.tokens(value))
                .font(.system(size: 14, weight: .medium, design: .rounded).monospacedDigit())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func agentsSection(_ result: FilteredProject) -> some View {
        let maxCost = result.byAgent.map(\.cost).max() ?? 0
        let shares = SubscriptionValue.shares(project: project.id, report: report)
        return VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L10n.tr("project.section.by_agent"))
            VStack(alignment: .leading, spacing: 14) {
                if result.byAgent.isEmpty {
                    Text(L10n.tr("project.no_usage_range"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                ForEach(result.byAgent) { agent in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            AgentDot(agent: agent.agent, size: 8)
                            Text(agent.label)
                                .font(.subheadline)
                                .lineLimit(1)
                                .layoutPriority(3)
                            Spacer(minLength: 6)
                            Text(agentDetail(agent, result: result))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .monospacedDigit()
                                .lineLimit(1)
                                .minimumScaleFactor(0.75)
                                .layoutPriority(1)
                            Text(Fmt.money(agent.cost, currency: currency))
                                .font(.subheadline.weight(.medium))
                                .monospacedDigit()
                                .lineLimit(1)
                                .layoutPriority(2)
                        }
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Color.primary.opacity(0.06))
                                Capsule()
                                    .fill(IOSPalette.agent(agent.agent))
                                    .frame(width: max(2, geo.size.width * CGFloat(maxCost > 0 ? agent.cost / maxCost : 0)))
                            }
                        }
                        .frame(height: 8)
                    }
                }
                if !shares.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(shares) { share in
                            Text(L10n.tr("project.cycle_share", Self.shareText(share.share), share.planLabel))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .padding(.top, 1)
                }
            }
            .padding(14)
            .kanjoCard()
        }
    }

    private func agentDetail(_ agent: AgentCost, result: FilteredProject) -> String {
        let percent = Fmt.percent(result.cost > 0 ? agent.cost / result.cost : 0)
        if agent.sessions > 0 {
            return L10n.tr("project.agent_detail", agent.sessions, Fmt.tokens(agent.tokens.total), percent)
        }
        return L10n.tr("project.agent_detail_no_sessions", Fmt.tokens(agent.tokens.total), percent)
    }

    private static func shareText(_ share: Double) -> String {
        share == 0 ? "0%" : Fmt.percent(share)
    }

    private var modelsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                SectionHeader(title: L10n.tr("project.section.by_model"))
                Text(L10n.tr("timerange.all.long"))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            VStack(spacing: 0) {
                if project.byModel.isEmpty {
                    Text(L10n.tr("overview.models.no_usage_range"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                }
                ForEach(Array(project.byModel.enumerated()), id: \.element.id) { index, model in
                    if index > 0 {
                        Divider().padding(.leading, 14)
                    }
                    ModelRowView(model: model, currency: currency)
                }
            }
            .kanjoCard()
        }
    }

    private func dayChartSection(_ result: FilteredProject) -> some View {
        let points = result.byDay.compactMap { day -> DayPoint? in
            guard let date = ReportDates.parseDay(day.day) else { return nil }
            return DayPoint(id: day.day, date: date, cost: day.cost)
        }
        return VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L10n.tr("project.section.by_day"))
            VStack {
                if points.isEmpty {
                    Text(L10n.tr("chart.no_data"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Chart(points) { point in
                        BarMark(
                            x: .value(L10n.tr("chart.day"), point.date),
                            y: .value(L10n.tr("chart.cost"), point.cost)
                        )
                        .foregroundStyle(IOSPalette.agent(dominantKey(result)))
                        .cornerRadius(2)
                    }
                    .chartXAxis {
                        AxisMarks(values: .automatic(desiredCount: 5)) { _ in
                            AxisGridLine()
                            AxisTick()
                            AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                        }
                    }
                    .chartYAxis {
                        AxisMarks(position: .leading)
                    }
                    .frame(height: 180)
                }
            }
            .padding(14)
            .kanjoCard()
        }
    }

    private func dominantKey(_ result: FilteredProject) -> String {
        dominantAgent(result.byAgent)?.agent ?? result.byAgent.first?.agent ?? "unknown"
    }
}

private struct DayPoint: Identifiable {
    let id: String
    let date: Date
    let cost: Double
}
