import SwiftUI
import AICostCore

struct OverviewView: View {
    let report: UsageReport
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
        ScrollView {
            // 一个容器包住所有卡片：共享采样；卡片间距 10 > 容器 spacing，所以卡片各自独立不粘连。
            GlassGroup(spacing: 6) {
                VStack(alignment: .leading, spacing: 10) {
                    stats
                    projectsSection
                    bucketsSection
                    ReconciliationView(report: report)
                    Text("Generated \(Fmt.timestamp(report.generatedAt)) · schema v\(report.schemaVersion)")
                        .font(.system(size: 9.5)).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .center)
                }
                .padding(10)
            }
        }
    }

    private var stats: some View {
        let t = report.totals
        // 四块玻璃在外层 GlassGroup 里（一起采样、一起过渡）。间距 8 > 容器 spacing 6，所以不粘连：
        // 实测让它们融合会在缝隙处拉出「颈部」并把卡片挤得高低不齐，数字反而难对齐。
        return Grid(horizontalSpacing: 8, verticalSpacing: 8) {
            GridRow {
                StatTile(label: "Total cost", value: Fmt.money(t.cost, currency: cur),
                         sub: "\(Fmt.day(t.firstActive)) – \(Fmt.day(t.lastActive))")
                StatTile(label: "Total tokens", value: Fmt.tokens(t.tokens.total),
                         sub: "\(Fmt.tokens(t.tokens.cacheRead)) cache read")
            }
            GridRow {
                StatTile(label: "Projects", value: "\(report.projects.count)")
                StatTile(label: "Sessions", value: "\(t.sessions)",
                         sub: report.buckets.parseFailed.sessions > 0 ? "+\(report.buckets.parseFailed.sessions) failed to parse" : nil)
            }
        }
    }

    private var projectsSection: some View {
        SectionCard("Projects") {
            Legend(agents: agents)
        } content: {
            if report.projects.isEmpty {
                Text("No projects.").font(.system(size: 11)).foregroundStyle(.secondary)
            }
            // 契约要求 CLI 已按 cost 降序；这里再排一次以防万一。
            let sorted = report.projects.sorted { $0.cost > $1.cost }
            VStack(spacing: 2) {
                ForEach(Array(sorted.enumerated()), id: \.element.id) { i, p in
                    if i > 0 { Divider().padding(.horizontal, 6) }
                    ProjectRow(project: p, currency: cur) { onSelect(.project(p.id)) }
                }
            }
            .padding(.horizontal, -6)
        }
    }

    private var bucketsSection: some View {
        let b = report.buckets
        return SectionCard("Not in any project") {
            VStack(spacing: 2) {
                BucketRow(name: "Unattributed",
                          desc: "No file signal and no cwd/scratchpad that maps to a project",
                          sessions: b.unattributed.sessions,
                          value: Fmt.money(b.unattributed.cost, currency: cur),
                          action: b.unattributed.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.unattributed)) })
                Divider().padding(.horizontal, 6)
                BucketRow(name: "Excluded",
                          desc: "Matched an exclude path in your config",
                          sessions: b.excluded.sessions,
                          value: Fmt.money(b.excluded.cost, currency: cur),
                          action: b.excluded.sessionsDetail.isEmpty ? nil : { onSelect(.bucket(.excluded)) })
                Divider().padding(.horizontal, 6)
                ParseFailedRow(bucket: b.parseFailed)
            }
            .padding(.horizontal, -6)
        }
    }
}

struct ProjectRow: View {
    let project: Project
    let currency: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(project.name).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    if project.pathMissing {
                        Badge(text: "path missing", style: .warn,
                              help: "None of this project's local paths exist any more.")
                    }
                    if project.remote == nil {
                        Badge(text: "local", help: "No git remote; identified by its absolute path.")
                    }
                    Spacer(minLength: 6)
                    Text(Fmt.money(project.cost, currency: currency))
                        .font(.system(size: 12.5, weight: .semibold, design: .rounded).monospacedDigit())
                }
                StackedBar(segments: project.byAgent)
                HStack(spacing: 4) {
                    Text("\(project.sessions) session\(project.sessions == 1 ? "" : "s")")
                    Text("·")
                    Text("last \(Fmt.day(project.lastActive))")
                    Spacer()
                    Image(systemName: "chevron.right").imageScale(.small)
                }
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
            }
            .padding(.vertical, 7).padding(.horizontal, 6)
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
        let row = HStack(alignment: .firstTextBaseline, spacing: 6) {
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(.system(size: 11.5, weight: .medium))
                Text(desc).font(.system(size: 9.5)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 6)
            Text("\(sessions) session\(sessions == 1 ? "" : "s")")
                .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
            Text(value).font(.system(size: 11.5, weight: .semibold)).monospacedDigit()
                .frame(minWidth: 56, alignment: .trailing)
            Image(systemName: "chevron.right").imageScale(.small).foregroundStyle(.secondary)
                .opacity(action == nil ? 0 : 1)
        }
        .padding(.vertical, 5).padding(.horizontal, 6)
        .contentShape(Rectangle())

        if let action {
            Button(action: action) { row }.buttonStyle(RowButtonStyle())
        } else {
            row
        }
    }
}

struct ParseFailedRow: View {
    let bucket: ParseFailedBucket
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("Parse failed").font(.system(size: 11.5, weight: .medium))
                    Text("Log files in a format aicost could not read; cost unknown")
                        .font(.system(size: 9.5)).foregroundStyle(.secondary)
                }
                Spacer(minLength: 6)
                Text("\(bucket.sessions) session\(bucket.sessions == 1 ? "" : "s")")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                Text("—").font(.system(size: 11.5, weight: .semibold))
                    .frame(minWidth: 56, alignment: .trailing)
                    .help("Cost of unparseable logs cannot be computed.")
                Button {
                    expanded.toggle()
                } label: {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right").imageScale(.small)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .opacity(bucket.files.isEmpty ? 0 : 1)
                .disabled(bucket.files.isEmpty)
            }
            if expanded {
                ForEach(bucket.files, id: \.self) { f in
                    Text(f).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.vertical, 5).padding(.horizontal, 6)
    }
}

struct ReconciliationView: View {
    let report: UsageReport

    var body: some View {
        let rec = Reconciliation(report: report)
        let cur = report.currency
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: rec.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                Text(rec.ok ? "Totals reconcile" : "Totals do not reconcile")
                    .font(.system(size: 11.5, weight: .semibold))
            }
            .foregroundStyle(rec.ok ? AgentPalette.good : AgentPalette.bad)

            line(ok: rec.cost.ok,
                 "Total \(Fmt.money(rec.cost.reported, currency: cur)) vs projects \(Fmt.money(rec.projectsCost, currency: cur)) + unattributed \(Fmt.money(rec.unattributedCost, currency: cur)) + excluded \(Fmt.money(rec.excludedCost, currency: cur)) = \(Fmt.money(rec.cost.summed, currency: cur))" + (rec.cost.ok ? "" : " · diff \(signedMoney(rec.cost.diff, cur))"))
            line(ok: rec.tokens.ok,
                 "Tokens \(Fmt.tokens(Int(rec.tokens.reported))) vs sum \(Fmt.tokens(Int(rec.tokens.summed)))" + (rec.tokens.ok ? "" : " · diff \(Int(rec.tokens.diff))"))
            line(ok: rec.sessions.ok,
                 "Sessions \(Int(rec.sessions.reported)) vs sum \(Int(rec.sessions.summed))" + (rec.sessions.ok ? "" : " · diff \(Int(rec.sessions.diff))"))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        // 对不上时：玻璃染红 + 红色描边（低版本：原来的红底红框）。
        .glassSurface(cornerRadius: 14,
                      tint: rec.ok ? nil : AgentPalette.badTint,
                      fallbackFill: rec.ok ? nil : AgentPalette.badFill,
                      stroke: rec.ok ? nil : AgentPalette.bad)
        .help("Invariant from the data contract: totals = sum(projects) + unattributed + excluded (cost tolerance $0.01).")
    }

    private func line(ok: Bool, _ s: String) -> some View {
        Text(s)
            .font(.system(size: 10, weight: ok ? .regular : .semibold))
            .foregroundStyle(ok ? Color.secondary : AgentPalette.bad)
            .monospacedDigit()
            .fixedSize(horizontal: false, vertical: true)
    }

    private func signedMoney(_ v: Double, _ cur: String) -> String {
        (v > 0 ? "+" : "") + Fmt.money(v, currency: cur)
    }
}
