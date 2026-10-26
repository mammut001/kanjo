import Foundation

/// 模型聚合工具：纯函数，负责聚合报告或项目中的模型用量。
public enum ModelAggregation {
    /// 聚合当前范围下的所有模型，按总 token 数降序排列。
    /// - All 范围：直接从各项目的 by_model 汇总（精确值）；
    /// - 非 All 范围：仅从范围内的会话（sessionsDetail，已按范围过滤）汇总：
    ///   单模型会话直接计入；多模型会话平均分配（向上取整的余数给首个模型，标记 estimated = true）。
    public static func aggregate(in report: FilteredReport) -> [ModelCost] {
        var map: [String: ModelCost] = [:]

        if report.spec.isAll {
            for fp in report.projects {
                for m in fp.project.byModel {
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
            }
        } else {
            // 与总览 hero 使用完全相同的范围过滤会话集
            let sessions: [Session] = report.projects.flatMap(\.sessionsDetail)
                + report.unattributed.sessionsDetail
                + report.excluded.sessionsDetail

            for s in sessions {
                guard !s.models.isEmpty else { continue }
                let count = s.models.count
                if count == 1 {
                    let model = s.models[0]
                    let key = "\(s.agent)/\(model)"
                    if let existing = map[key] {
                        map[key] = ModelCost(
                            model: model,
                            agent: s.agent,
                            cost: existing.cost + s.cost,
                            tokens: existing.tokens + s.tokens,
                            estimated: existing.estimated
                        )
                    } else {
                        map[key] = ModelCost(
                            model: model,
                            agent: s.agent,
                            cost: s.cost,
                            tokens: s.tokens,
                            estimated: false
                        )
                    }
                } else {
                    let shareCost = s.cost / Double(count)
                    for (i, model) in s.models.enumerated() {
                        func splitField(_ value: Int) -> Int {
                            let base = value / count
                            let rem = value % count
                            return i == 0 ? base + rem : base
                        }

                        let splitInp = splitField(s.tokens.input)
                        let splitOut = splitField(s.tokens.output)
                        let splitCr = splitField(s.tokens.cacheRead)
                        let splitCw = splitField(s.tokens.cacheWrite)
                        let splitTh = splitField(s.tokens.thinking)
                        let splitTotal: Int
                        if s.tokens.input + s.tokens.output + s.tokens.cacheRead + s.tokens.cacheWrite > 0 {
                            splitTotal = splitInp + splitOut + splitCr + splitCw
                        } else {
                            splitTotal = splitField(s.tokens.total)
                        }

                        let shareTokens = Tokens(
                            input: splitInp,
                            output: splitOut,
                            cacheRead: splitCr,
                            cacheWrite: splitCw,
                            thinking: splitTh,
                            total: splitTotal
                        )

                        let key = "\(s.agent)/\(model)"
                        if let existing = map[key] {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: existing.cost + shareCost,
                                tokens: existing.tokens + shareTokens,
                                estimated: true
                            )
                        } else {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: shareCost,
                                tokens: shareTokens,
                                estimated: true
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
}
