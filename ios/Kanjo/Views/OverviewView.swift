import KanjoCore
import SwiftUI
import UIKit

struct OverviewView: View {
    let report: UsageReport
    var deviceName: String? = nil
    @State private var range: TimeRange = .all

    private var currency: String { report.currency }

    private var spec: RangeSpec {
        RangeEngine.spec(range, report: report)
    }

    private var filtered: FilteredReport {
        RangeEngine.filtered(report, range: spec, fallbackAgentFor: Self.fallbackAgent)
    }

    static func fallbackAgent(_ project: Project) -> String {
        dominantAgent(project.byAgent)?.agent ?? project.byAgent.first?.agent ?? "unknown"
    }

    var body: some View {
        let result = filtered
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                header(result)
                if !(report.subscriptions ?? [:]).isEmpty {
                    SubscriptionValueSection(report: report)
                }
                let used = result.projects.filter(\.hasUsage)
                if used.contains(where: { $0.cost > 0 }) {
                    ProjectMosaic(projects: used, report: report, range: range, currency: currency)
                }
                projectsSection(result)
                modelsSection(result)
                footer
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 24)
        }
        .background(Color(uiColor: .systemGroupedBackground))
    }

    private func header(_ result: FilteredReport) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(L10n.tr("overview.total_cost"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if let note = report.costNoteDisplayText {
                    Image(systemName: "info.circle")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .accessibilityLabel(note)
                }
            }
            Text(Fmt.money(result.cost, currency: currency))
                .font(.system(size: 46, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.55)
                .accessibilityLabel(L10n.tr("overview.total_cost") + " " + Fmt.money(result.cost, currency: currency))
            RangeSegmentedPicker(selection: $range)
            Text(summary(result))
                .font(.footnote)
                .foregroundStyle(.secondary)
                .monospacedDigit()
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func summary(_ result: FilteredReport) -> String {
        guard result.firstActive != nil else { return L10n.tr("overview.no_usage") }
        let used = result.projects.filter(\.hasUsage)
        let projectText = used.count == 1
            ? L10n.tr("overview.count.project.singular", used.count)
            : L10n.tr("overview.count.project.plural", used.count)
        var parts = [
            Self.dateRange(result.firstActive, result.lastActive),
            projectText,
        ]
        if result.sessions > 0 {
            parts.append(result.sessions == 1
                ? L10n.tr("overview.count.session.singular", result.sessions)
                : L10n.tr("overview.count.session.plural", result.sessions))
        }
        parts.append(L10n.tr("overview.tokens_count", Fmt.tokens(result.tokens)))
        return parts.joined(separator: " · ")
    }

    static func dateRange(_ first: String?, _ last: String?) -> String {
        guard let first else { return "—" }
        guard let last, last != first else { return Fmt.day(first) }
        return "\(Fmt.day(first)) – \(Fmt.day(last))"
    }

    private func projectsSection(_ result: FilteredReport) -> some View {
        let projects = result.projects.filter(\.hasUsage).sorted { $0.cost > $1.cost }
        return VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L10n.tr("ios.projects"))
            VStack(spacing: 0) {
                if projects.isEmpty {
                    Text(L10n.tr("overview.projects.empty"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                }
                ForEach(Array(projects.enumerated()), id: \.element.id) { index, item in
                    if index > 0 {
                        Divider().padding(.leading, 14)
                    }
                    NavigationLink {
                        ProjectDetailView(project: item.project, report: report, range: range)
                    } label: {
                        ProjectRowView(project: item.projected, currency: currency)
                    }
                    .buttonStyle(.plain)
                }
            }
            .kanjoCard()
        }
    }

    private func modelsSection(_ result: FilteredReport) -> some View {
        let models = ModelAggregation.aggregate(in: result)
        let shown = Array(models.prefix(5))
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                SectionHeader(title: L10n.tr("overview.section.by_model"))
                NavigationLink {
                    ByModelView(report: report, range: range)
                } label: {
                    Text(L10n.tr("ios.all_models"))
                        .font(.footnote)
                }
            }
            VStack(spacing: 0) {
                if shown.isEmpty {
                    Text(L10n.tr("overview.models.no_usage_range"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                }
                ForEach(Array(shown.enumerated()), id: \.element.id) { index, model in
                    if index > 0 {
                        Divider().padding(.leading, 14)
                    }
                    ModelRowView(model: model, currency: currency)
                }
            }
            .kanjoCard()
        }
    }

    private var footer: some View {
        Text(footerText)
            .font(.caption2)
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.top, 4)
    }

    private var footerText: String {
        let updated = Fmt.timestamp(report.generatedAt)
        if let deviceName, !deviceName.isEmpty {
            return L10n.tr("ios.updated_device", updated, deviceName)
        }
        return L10n.tr("ios.updated", updated)
    }
}

private struct SubscriptionValueSection: View {
    let report: UsageReport

    var body: some View {
        let rows = SubscriptionValue.rows(of: report)
        let timezone = RangeEngine.timezone(of: report)
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L10n.tr("overview.section.subscription_value"))
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if index > 0 {
                        Divider().padding(.horizontal, 14)
                    }
                    VStack(alignment: .leading, spacing: 9) {
                        HStack(spacing: 7) {
                            AgentDot(agent: row.agent, size: 8)
                            Text(row.planLabel)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                            Spacer(minLength: 8)
                            Text(Fmt.money(row.usage, currency: report.currency))
                                .font(.subheadline.weight(.medium))
                                .monospacedDigit()
                        }
                        HStack(spacing: 4) {
                            Text(Fmt.perMonth(row.monthlyPriceUsd, currency: report.currency))
                            Text("·")
                            Text(Fmt.multiple(row.multiplier))
                            if row.extraUsageEnabled {
                                Text("·")
                                Text(L10n.tr("overview.extra_usage_on"))
                                    .foregroundStyle(IOSPalette.quotaWarn)
                            }
                            Spacer(minLength: 0)
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()

                        let quota = SubscriptionValue.quotaRows(report.quotaWindows?[row.agent], timezone: timezone)
                        if quota.isEmpty {
                            Text(L10n.tr("ios.quota_no_data"))
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        } else {
                            VStack(alignment: .leading, spacing: 8) {
                                ForEach(quota) { item in
                                    QuotaBarRow(row: item, agent: row.agent)
                                }
                            }
                        }
                    }
                    .padding(14)
                }
            }
            .kanjoCard()
            Text(L10n.tr("overview.subscription_value.explanation"))
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
