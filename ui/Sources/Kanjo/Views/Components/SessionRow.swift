import SwiftUI
import KanjoCore

struct SessionRow: View {
    let session: Session
    let threshold: Double
    let currency: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Group {
                    if let t = session.title, !t.isEmpty {
                        Text(t)
                    } else {
                        Text(L10n.tr("session.untitled")).foregroundColor(.secondary).italic()
                    }
                }
                .font(.system(size: 12))
                .lineLimit(2)
                .help(session.title ?? "")
                Spacer(minLength: 6)
                Text(Fmt.money(session.cost, currency: currency))
                    .font(.system(size: 12, weight: .medium, design: .rounded)).monospacedDigit()
            }
            HStack(spacing: 5) {
                AgentDot(agent: session.agent, size: 6)
                Text(session.label)
                Text("·")
                Text(Fmt.timestamp(session.started)).monospacedDigit()
                if let b = session.branch {
                    Text("·")
                    Image(systemName: "arrow.triangle.branch").imageScale(.small)
                    Text(b).lineLimit(1).truncationMode(.middle)
                }
            }
            .font(.system(size: 10.5))
            .foregroundStyle(.secondary)

            HStack(spacing: 5) {
                Badge(text: session.attribution,
                      style: session.attribution == "split" ? .warn : .neutral,
                      help: AttributionInfo.explanation(session.attribution, threshold: threshold))
                Text(L10n.tr("session.share", Fmt.percent(session.share)))
                    .help(L10n.tr("session.share_help"))
                if session.subagents > 0 {
                    Text(session.subagents == 1
                         ? L10n.tr("session.subagent.singular", session.subagents)
                         : L10n.tr("session.subagent.plural", session.subagents))
                        .help(L10n.tr("session.subagents_help"))
                }
                Spacer(minLength: 4)
                Text(session.models.joined(separator: ", "))
                    .font(.system(size: 9.5, design: .monospaced))
                    .lineLimit(1).truncationMode(.tail)
                    .help(session.models.joined(separator: ", "))
            }
            .font(.system(size: 10))
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }
}

/// 会话列表：可按 started / cost 排序，默认只展示前 N 条。
struct SessionList: View {
    enum SortKey: String, CaseIterable, Identifiable {
        case started = "Started", cost = "Cost"
        var id: String { rawValue }
        var label: String { self == .started ? L10n.tr("session.sort.started") : L10n.tr("session.sort.cost") }
    }

    let sessions: [Session]
    let threshold: Double
    let currency: String
    @State private var sortKey: SortKey = .started
    @State private var descending = true
    @State private var showAll = false
    private let initialLimit = 25

    private var sorted: [Session] {
        let s: [Session]
        switch sortKey {
        case .started:
            s = sessions.sorted { ($0.startedDate ?? .distantPast) < ($1.startedDate ?? .distantPast) }
        case .cost:
            s = sessions.sorted { $0.cost < $1.cost }
        }
        return descending ? s.reversed() : s
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Picker(L10n.tr("session.sort"), selection: $sortKey) {
                    ForEach(SortKey.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .controlSize(.small)
                .frame(width: 130)
                Button {
                    descending.toggle()
                } label: {
                    Image(systemName: descending ? "arrow.down" : "arrow.up")
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .help(descending ? L10n.tr("session.sort.descending") : L10n.tr("session.sort.ascending"))
                Spacer()
                AttributionLegendButton(threshold: threshold)
            }
            if sessions.isEmpty {
                Text(L10n.tr("session.empty")).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            let list = sorted
            let shown = showAll ? list : Array(list.prefix(initialLimit))
            ForEach(Array(shown.enumerated()), id: \.offset) { i, s in
                if i > 0 { Divider().opacity(0.6) }
                SessionRow(session: s, threshold: threshold, currency: currency)
            }
            if list.count > initialLimit {
                ShowAllButton(expanded: $showAll, total: list.count, noun: L10n.tr("project.noun.sessions"))
                    .padding(.top, 4)
            }
        }
    }
}

/// 「?」按钮：弹出所有 attribution 取值的解释。
struct AttributionLegendButton: View {
    let threshold: Double
    @State private var shown = false

    var body: some View {
        Button {
            shown.toggle()
        } label: {
            Label(L10n.tr("session.attribution_button"), systemImage: "questionmark.circle")
                .font(.system(size: 10.5))
                .foregroundStyle(.secondary)
        }
        .buttonStyle(.borderless)
        .help(L10n.tr("session.attribution_button_help"))
        .popover(isPresented: $shown, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                Text(L10n.tr("session.attribution_popover_title")).font(.system(size: 12, weight: .semibold))
                ForEach(AttributionInfo.allKnown, id: \.self) { v in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(v).font(.system(size: 11, weight: .semibold, design: .monospaced))
                        Text(AttributionInfo.explanation(v, threshold: threshold))
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(12)
            .frame(width: 300)
        }
    }
}
