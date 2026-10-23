import SwiftUI
import AICostCore

struct OverviewView: View {
    static let bottomAnchor = "overview-bottom"

    let report: UsageReport
    var scrollAnchor: String? = nil
    let onSelect: (Route) -> Void

    private var cur: String { report.currency }

    /// 报告中出现的所有 agent（按总花费降序），用于图例。
    private var agents: [(key: String, label: String)] {
        var cost: [String: Double] = [:], label: [String: String] = [:]
        for p in report.projects {
            for a in p.byAgent { cost[a.agent, default: 0] += a.cost; label[a.agent] = a.label }
        }
        return cost.sorted { $0.value > $1.value }.map { ($0.key, label[$0.key] ?? $0.key) }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Metrics.sectionSpacing) {
                    hero
                    projectsSection
                    bucketsSection
                    VStack(alignment: .leading, spacing: 8) {
                        ReconciliationView(report: report)
                        Text("Generated \(Fmt.timestamp(report.generatedAt)) · schema v\(report.schemaVersion)")
                            .font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, Metrics.rowInset)
                    .id(Self.bottomAnchor)
                }
                .padding(.horizontal, Metrics.pagePadding)
                .padding(.top, 16).padding(.bottom, 10)
            }
            .task(id: scrollAnchor) {
                guard let a = scrollAnchor else { return }
                try? await Task.sleep(nanoseconds: 300_000_000)
                proxy.scrollTo(a, anchor: .bottom)
            }
        }
    }

    // 唯一的 hero：总金额。日期范围和 cost_note 是它的注脚；三个次要数字排成一行。
    private var hero: some View {
        let t = report.totals
        let failed = report.buckets.parseFailed.sessions
        return VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Total cost").font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                HeroAmount(value: Fmt.money(t.cost, currency: cur))
                Text(ShortDate.range(t.firstActive, t.lastActive))
                    .font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                CostNote(text: report.costNote).padding(.top, 3)
            }
            HStack(alignment: .top, spacing: 12) {
                MinorStat(value: "\(report.projects.count)", label: "Projects")
                MinorStat(value: "\(t.sessions)", label: "Sessions",
                          help: failed > 0 ? "Plus \(failed) log file\(failed == 1 ? "" : "s") that failed to parse (not counted)." : nil)
                MinorStat(value: Fmt.tokens(t.tokens.total), label: "Tokens",
                          help: "\(Fmt.tokens(t.tokens.cacheRead)) of them are cache reads.")
            }
        }
        .padding(.horizontal, Metrics.rowInset)
    }

    private var projectsSection: some View {
        // 契约要求 CLI 已按 cost 降序；这里再排一次以防万一。
        let sorted = report.projects.sorted { $0.cost > $1.cost }
        let maxCost = sorted.first?.cost ?? 0
        return PanelSection("Projects") {
            Legend(agents: agents)
        } content: {
            if sorted.isEmpty {
                Text("No projects.").font(.system(size: 11)).foregroundStyle(.secondary)
                    .padding(Metrics.rowInset)
            }
            ForEach(Array(sorted.enumerated()), id: \.element.id) { i, p in
                if i > 0 { RowDivider() }
                ProjectRow(project: p, currency: cur, fraction: maxCost > 0 ? p.cost / maxCost : 0) {
                    onSelect(.project(p.id))
                }
            }
        }
    }

    private var bucketsSection: some View {
        let b = report.buckets
        return PanelSection("Not in any project") {
            BucketRow(name: "Unattributed",
                      desc: "No file signal, and no cwd or scratchpad that maps to a project",
                      sessions: b.unattributed.sessions,
                      value: Fmt.money(b.unattributed.cost, currency: cur),
                      action: b.unattributed.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.unattributed)) })
            RowDivider()
            BucketRow(name: "Excluded",
                      desc: "Matched an exclude path in your config",
                      sessions: b.excluded.sessions,
                      value: Fmt.money(b.excluded.cost, currency: cur),
                      action: b.excluded.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.excluded)) })
            RowDivider()
            ParseFailedRow(bucket: b.parseFailed)
        }
    }
}

/// 项目行：name 和 cost 同一行；下面一根 3pt 细条，长度 = 该项目 / 最大项目，按 agent 分段；再下面是 meta。
struct ProjectRow: View {
    let project: Project
    let currency: String
    let fraction: Double
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(project.name).font(.system(size: 12.5, weight: .medium)).lineLimit(1)
                    if project.pathMissing {
                        Badge(text: "path missing", style: .warn,
                              help: "None of this project's local paths exist any more.")
                    }
                    if project.remote == nil {
                        Badge(text: "local", help: "No git remote; identified by its absolute path.")
                    }
                    Spacer(minLength: 6)
                    Text(Fmt.money(project.cost, currency: currency))
                        .font(.system(size: 12.5, weight: .medium, design: .rounded).monospacedDigit())
                }
                StackedBar(segments: project.byAgent, fraction: fraction, height: 3)
                Text("\(project.sessions) session\(project.sessions == 1 ? "" : "s") · active \(ShortDate.relative(project.lastActive))")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .help("Last active \(Fmt.day(project.lastActive))")
            }
            .padding(.horizontal, Metrics.rowInset).padding(.vertical, 5)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowButtonStyle())
        .help(project.id)
    }
}

struct BucketRow: View {
    let name: String
    let desc: String
    let sessions: Int
    let value: String
    let action: (() -> Void)?

    var body: some View {
        let row = VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(name).font(.system(size: 12))
                Spacer(minLength: 6)
                Text("\(sessions) session\(sessions == 1 ? "" : "s")")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                Text(value).font(.system(size: 12, weight: .medium, design: .rounded)).monospacedDigit()
                    .frame(minWidth: 52, alignment: .trailing)
            }
            Text(desc).font(.system(size: 10)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, Metrics.rowInset).padding(.vertical, 7)
        .contentShape(Rectangle())

        if let action {
            Button(action: action) { row }.buttonStyle(RowButtonStyle()).help("Show these sessions")
        } else {
            row
        }
    }
}

struct ParseFailedRow: View {
    let bucket: ParseFailedBucket
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        HStack(spacing: 4) {
                            Text("Parse failed").font(.system(size: 12))
                            if !bucket.files.isEmpty {
                                Image(systemName: expanded ? "chevron.down" : "chevron.right")
                                    .font(.system(size: 8, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        Spacer(minLength: 6)
                        Text("\(bucket.sessions) session\(bucket.sessions == 1 ? "" : "s")")
                            .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                        Text("—").font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 52, alignment: .trailing)
                            .help("Cost of unparseable logs cannot be computed.")
                    }
                    Text("Log files aicost could not read; cost unknown")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                .padding(.horizontal, Metrics.rowInset).padding(.vertical, 7)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle())
            .disabled(bucket.files.isEmpty)

            if expanded {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(bucket.files, id: \.self) { f in
                        Text(f).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.horizontal, Metrics.rowInset).padding(.bottom, 8)
            }
        }
    }
}

/// 对账：正常时一行绿色小字（明细在 tooltip）；对不上时变成醒目的红色块，逐项列出差异。
struct ReconciliationView: View {
    let report: UsageReport

    var body: some View {
        let rec = Reconciliation(report: report)
        let cur = report.currency
        let lines = [
            (rec.cost.ok, "Total \(Fmt.money(rec.cost.reported, currency: cur)) vs projects \(Fmt.money(rec.projectsCost, currency: cur)) + unattributed \(Fmt.money(rec.unattributedCost, currency: cur)) + excluded \(Fmt.money(rec.excludedCost, currency: cur)) = \(Fmt.money(rec.cost.summed, currency: cur))" + (rec.cost.ok ? "" : " · diff \(signedMoney(rec.cost.diff, cur))")),
            (rec.tokens.ok, "Tokens \(Fmt.tokens(Int(rec.tokens.reported))) vs sum \(Fmt.tokens(Int(rec.tokens.summed)))" + (rec.tokens.ok ? "" : " · diff \(Int(rec.tokens.diff))")),
            (rec.sessions.ok, "Sessions \(Int(rec.sessions.reported)) vs sum \(Int(rec.sessions.summed))" + (rec.sessions.ok ? "" : " · diff \(Int(rec.sessions.diff))")),
        ]
        let contract = "Invariant from the data contract: totals = sum(projects) + unattributed + excluded (cost tolerance $0.01)."

        if rec.ok {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Image(systemName: "checkmark.circle.fill")
                Text("Reconciled: \(Fmt.money(rec.cost.reported, currency: cur)) = projects + unattributed + excluded")
                    .fixedSize(horizontal: false, vertical: true)
            }
            .font(.system(size: 10.5))
            .foregroundStyle(AgentPalette.good)
            .monospacedDigit()
            .help(lines.map(\.1).joined(separator: "\n") + "\n\n" + contract)
        } else {
            StatusBlock(kind: .bad, icon: "exclamationmark.triangle.fill") {
                Text("Totals do not reconcile").font(.system(size: 12, weight: .semibold))
                ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                    Text(l.1)
                        .font(.system(size: 10.5, weight: l.0 ? .regular : .semibold))
                        .foregroundStyle(l.0 ? Color.secondary : AgentPalette.bad)
                        .monospacedDigit()
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .help(contract)
        }
    }

    private func signedMoney(_ v: Double, _ cur: String) -> String {
        (v > 0 ? "+" : "") + Fmt.money(v, currency: cur)
    }
}
