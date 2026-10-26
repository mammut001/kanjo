import Foundation

/// 模型聚合工具：纯函数，负责聚合报告或项目中的模型用量。
public enum ModelAggregation {
    /// 聚合当前范围下的所有模型，按总 token 数降序排列。
    public static func aggregate(in report: FilteredReport) -> [ModelCost] {
        aggregate(projects: report.projects, isAll: report.spec.isAll)
    }

    /// 聚合过滤后的项目列表。
    public static func aggregate(projects: [FilteredProject], isAll: Bool) -> [ModelCost] {
        var map: [String: ModelCost] = [:]

        for fp in projects {
            // 范围过滤：非 All 模式下跳过无用量的项目
            if !isAll && !fp.hasUsage {
                continue
            }

            // 确定该项目在范围内活跃的模型集合
            let activeModels: Set<String>? = {
                guard !isAll else { return nil }
                let modelsInSessions = Set(fp.sessionsDetail.flatMap(\.models))
                return modelsInSessions.isEmpty ? nil : modelsInSessions
            }()

            if !fp.project.byModel.isEmpty {
                for m in fp.project.byModel {
                    if let active = activeModels, !active.contains(m.model) {
                        continue
                    }
                    let key = m.id
                    if let existing = map[key] {
                        map[key] = ModelCost(
                            model: m.model,
                            agent: m.agent,
                            cost: existing.cost + m.cost,
                            tokens: existing.tokens + m.tokens,
                            estimated: existing.estimated || m.estimated
                        )
                    } else {
                        map[key] = m
                    }
                }
            } else if !fp.sessionsDetail.isEmpty {
                // 如果项目未提供 byModel，从活跃会话中汇总模型（容错回退）
                for s in fp.sessionsDetail {
                    guard !s.models.isEmpty else { continue }
                    let count = s.models.count
                    let shareTokens = Tokens(
                        input: s.tokens.input / count,
                        output: s.tokens.output / count,
                        cacheRead: s.tokens.cacheRead / count,
                        cacheWrite: s.tokens.cacheWrite / count,
                        thinking: s.tokens.thinking / count,
                        total: s.tokens.total / count
                    )
                    let shareCost = s.cost / Double(count)
                    for model in s.models {
                        let key = "\(s.agent)/\(model)"
                        if let existing = map[key] {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: existing.cost + shareCost,
                                tokens: existing.tokens + shareTokens,
                                estimated: existing.estimated
                            )
                        } else {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: shareCost,
                                tokens: shareTokens,
                                estimated: false
                            )
                        }
                    }
                }
            }
        }

        // 按总 token 数降序排列；相等时按花费降序，再按模型名称升序
        return map.values.sorted { a, b in
            if a.tokens.total != b.tokens.total {
                return a.tokens.total > b.tokens.total
            }
            if a.cost != b.cost {
                return a.cost > b.cost
            }
            return a.model < b.model
        }
    }

    /// 聚合原始项目列表（等同于 All 范围）。
    public static func aggregate(_ projects: [Project]) -> [ModelCost] {
        let fps = projects.map { p in
            FilteredProject(
                project: p,
                cost: p.cost,
                tokens: p.tokens.total,
                sessions: p.sessions,
                byAgent: p.byAgent,
                byDay: p.byDay,
                sessionsDetail: p.sessionsDetail,
                firstActive: p.firstActive,
                lastActive: p.lastActive
            )
        }
        return aggregate(projects: fps, isAll: true)
    }

    /// 聚合全量使用报告（等同于 All 范围）。
    public static func aggregate(_ report: UsageReport) -> [ModelCost] {
        aggregate(report.projects)
    }
}

extension FilteredReport {
    /// 聚合当前范围下的所有模型用量。
    public var aggregatedModels: [ModelCost] {
        ModelAggregation.aggregate(in: self)
    }

    public func aggregateModels() -> [ModelCost] {
        ModelAggregation.aggregate(in: self)
    }
}

extension RangeEngine {
    /// 聚合当前范围下的所有模型用量。
    public static func aggregateModels(in report: FilteredReport) -> [ModelCost] {
        ModelAggregation.aggregate(in: report)
    }

    public static func aggregateModels(projects: [FilteredProject], isAll: Bool) -> [ModelCost] {
        ModelAggregation.aggregate(projects: projects, isAll: isAll)
    }
}
