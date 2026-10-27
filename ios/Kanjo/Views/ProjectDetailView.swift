import Charts
import KanjoCore
import SwiftUI
import UIKit

struct ProjectDetailView: View {
    let project: Project
    let report: UsageReport
    let range: TimeRange

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
                agentsSection(result)
                modelsSection
                dayChartSection(result)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(project.name)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func header(_ result: FilteredProject) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.tr("overview.total_cost"))
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(Fmt.money(result.cost, currency: currency))
                .font(.system(size: 40, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.55)
            Text(summary(result))
                .font(.footnote)
                .foregroundStyle(.secondary)
                .monospacedDigit()
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func summary(_ result: FilteredProject) -> String {
        guard result.firstActive != nil else { return L10n.tr("project.no_usage_range") }
        var parts = [OverviewView.dateRange(result.firstActive, result.lastActive)]
        if result.sessions > 0 {
            parts.append(result.sessions == 1
                ? L10n.tr("overview.count.session.singular", result.sessions)
                : L10n.tr("overview.count.session.plural", result.sessions))
        }
        parts.append(L10n.tr("overview.tokens_count", Fmt.tokens(result.tokens)))
        return parts.joined(separator: " · ")
    }

    private func agentsSection(_ result: FilteredProject) -> some View {
        let maxCost = result.byAgent.map(\.cost).max() ?? 0
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
                        HStack(spacing: 7) {
                            AgentDot(agent: agent.agent, size: 8)
                            Text(agent.label)
                                .font(.subheadline)
                                .lineLimit(1)
                            Spacer(minLength: 8)
                            Text(Fmt.money(agent.cost, currency: currency))
                                .font(.subheadline.weight(.medium))
                                .monospacedDigit()
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
                        Text(agentDetail(agent, result: result))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
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
