import KanjoCore
import SwiftUI
import UIKit

struct SectionHeader: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.headline)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct KanjoCard: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(
                Color(uiColor: .secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: 16, style: .continuous)
            )
    }
}

extension View {
    func kanjoCard() -> some View { modifier(KanjoCard()) }
}

struct RangeSegmentedPicker: View {
    @Binding var selection: TimeRange
    private let ranges: [TimeRange] = [.all, .today, .days7, .days30]

    var body: some View {
        Picker(L10n.tr("overview.total_cost"), selection: $selection) {
            ForEach(ranges) { range in
                Text(range.shortLabel).tag(range)
            }
        }
        .pickerStyle(.segmented)
        .labelsHidden()
    }
}

struct AgentDot: View {
    let agent: String
    var size: CGFloat = 8

    var body: some View {
        Circle()
            .fill(IOSPalette.agent(agent))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

struct AgentDots: View {
    let agents: [AgentCost]

    var body: some View {
        HStack(spacing: 3) {
            ForEach(agents.prefix(3)) { agent in
                AgentDot(agent: agent.agent, size: 7)
            }
        }
        .accessibilityHidden(true)
    }
}

struct QuotaBarRow: View {
    let row: QuotaRow

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(row.title)
                Spacer(minLength: 8)
                Text(percentText)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
            .font(.caption)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule()
                        .fill(tint)
                        .frame(width: max(0, geo.size.width * CGFloat((row.percent ?? 0) / 100)))
                }
            }
            .frame(height: 6)

            Text(row.detail)
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
    }

    private var percentText: String {
        guard let percent = row.percent else { return "—" }
        return String(format: "%.0f%%", percent)
    }

    private var tint: Color {
        switch SubscriptionValue.level(row.percent) {
        case .normal: return IOSPalette.good
        case .warning: return IOSPalette.quotaWarn
        case .critical: return IOSPalette.bad
        }
    }
}

struct ProjectRowView: View {
    let project: Project
    let currency: String

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(project.name)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                    AgentDots(agents: project.byAgent)
                }
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Text(Fmt.money(project.cost, currency: currency))
                .font(.subheadline.weight(.semibold))
                .monospacedDigit()
                .lineLimit(1)
            Image(systemName: "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .contentShape(Rectangle())
    }

    private var detail: String {
        let tokens = L10n.tr("overview.tokens_count", Fmt.tokens(project.tokens.total))
        let sessions = project.sessions == 1
            ? L10n.tr("overview.count.session.singular", project.sessions)
            : L10n.tr("overview.count.session.plural", project.sessions)
        return "\(tokens) · \(sessions)"
    }
}

struct ModelRowView: View {
    let model: ModelCost
    let currency: String

    var body: some View {
        HStack(spacing: 8) {
            AgentDot(agent: model.agent, size: 7)
            Text(model.model)
                .font(.system(.subheadline, design: .monospaced))
                .lineLimit(1)
                .truncationMode(.middle)
            if model.estimated {
                Text(L10n.tr("project.estimated"))
                    .font(.caption2)
                    .foregroundStyle(IOSPalette.quotaWarn)
            }
            Spacer(minLength: 8)
            Text(Fmt.tokens(model.tokens.total))
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospacedDigit()
            Text(Fmt.money(model.cost, currency: currency))
                .font(.subheadline.weight(.medium))
                .monospacedDigit()
                .frame(minWidth: 64, alignment: .trailing)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }
}

struct LanguageMenu: View {
    @Binding var language: String

    var body: some View {
        Menu {
            ForEach(AppLanguage.allCases) { item in
                Button {
                    language = item.rawValue
                } label: {
                    if language == item.rawValue {
                        Label(item.displayName, systemImage: "checkmark")
                    } else {
                        Text(item.displayName)
                    }
                }
            }
        } label: {
            Image(systemName: "globe")
        }
        .accessibilityLabel(L10n.tr("ios.language"))
    }
}
