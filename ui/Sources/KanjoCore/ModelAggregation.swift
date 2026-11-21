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
        }
        // 两种范围共用的分配逻辑：非 All 时分项目会话与桶会话；All 时项目用 by_model 精确值，只分桶会话。
        do {
            // 采用最大余额法（Hamilton-Hare）按比例分配整数 token，保证分配后之和严格等于 targetTokens
            func apportion(total: Int, weights: [Double]) -> [Int] {
                guard !weights.isEmpty else { return [] }
                guard total > 0 else { return Array(repeating: 0, count: weights.count) }
                let sumW = weights.reduce(0.0, +)
                let normalizedWeights: [Double]
                if sumW > 0 {
                    normalizedWeights = weights.map { $0 / sumW }
                } else {
                    let eq = 1.0 / Double(weights.count)
                    normalizedWeights = Array(repeating: eq, count: weights.count)
                }

                let quotas = normalizedWeights.map { Double(total) * $0 }
                var integers = quotas.map { Int(floor($0)) }
                var remainders = quotas.enumerated().map { (index: $0.offset, remainder: $0.element - Double(integers[$0.offset])) }
                let currentSum = integers.reduce(0, +)
                let leftover = total - currentSum

                remainders.sort { a, b in
                    if abs(a.remainder - b.remainder) > 1e-9 {
                        return a.remainder > b.remainder
                    }
                    return a.index < b.index
                }

                for i in 0..<min(leftover, remainders.count) {
                    integers[remainders[i].index] += 1
                }
                return integers
            }

            // 将项目或桶在当前范围内的 cost 与 tokens 按会话的范围内份额分配到各个会话
            func processGroup(sessions: [Session], targetCost: Double, targetTokens: Int) {
                guard !sessions.isEmpty else { return }
                guard targetCost > 0 || targetTokens > 0 else { return }

                var rawCosts: [Double] = []
                var rawTokens: [Double] = []

                for s in sessions {
                    let (c, t) = report.spec.inRangeCostAndTokens(for: s)
                    rawCosts.append(c)
                    rawTokens.append(Double(t))
                }

                let sumRawCosts = rawCosts.reduce(0.0, +)
                let sessionCosts: [Double]
                if sumRawCosts > 0 {
                    sessionCosts = rawCosts.map { targetCost * ($0 / sumRawCosts) }
                } else {
                    let eq = targetCost / Double(sessions.count)
                    sessionCosts = Array(repeating: eq, count: sessions.count)
                }

                let sessionTokenTotals = apportion(total: targetTokens, weights: rawTokens)

                for (idx, s) in sessions.enumerated() {
                    guard !s.models.isEmpty else { continue }
                    let sCost = sessionCosts[idx]
                    let sTotalTokens = sessionTokenTotals[idx]
                    guard sCost > 0 || sTotalTokens > 0 else { continue }

                    let origInp = Double(s.tokens.input)
                    let origOut = Double(s.tokens.output)
                    let origCr = Double(s.tokens.cacheRead)
                    let origCw = Double(s.tokens.cacheWrite)
                    let origSum = origInp + origOut + origCr + origCw

                    let splitFields: [Int]
                    if origSum > 0 {
                        splitFields = apportion(total: sTotalTokens, weights: [origInp, origOut, origCr, origCw])
                    } else {
                        splitFields = [0, 0, 0, 0]
                    }

                    let scaledThinking: Int
                    if s.tokens.total > 0 {
                        scaledThinking = Int(round(Double(s.tokens.thinking) * (Double(sTotalTokens) / Double(s.tokens.total))))
                    } else {
                        scaledThinking = 0
                    }

                    let sScaledTokens = Tokens(
                        input: splitFields[0],
                        output: splitFields[1],
                        cacheRead: splitFields[2],
                        cacheWrite: splitFields[3],
                        thinking: scaledThinking,
                        total: sTotalTokens
                    )

                    let count = s.models.count
                    if count == 1 {
                        let model = s.models[0]
                        let key = "\(s.agent)/\(model)"
                        if let existing = map[key] {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: existing.cost + sCost,
                                tokens: existing.tokens + sScaledTokens,
                                estimated: existing.estimated
                            )
                        } else {
                            map[key] = ModelCost(
                                model: model,
                                agent: s.agent,
                                cost: sCost,
                                tokens: sScaledTokens,
                                estimated: false
                            )
                        }
                    } else {
                        let shareCost = sCost / Double(count)
                        for (i, model) in s.models.enumerated() {
                            func splitField(_ value: Int) -> Int {
                                let base = value / count
                                let rem = value % count
                                return i == 0 ? base + rem : base
                            }

                            let splitInp = splitField(sScaledTokens.input)
                            let splitOut = splitField(sScaledTokens.output)
                            let splitCr = splitField(sScaledTokens.cacheRead)
                            let splitCw = splitField(sScaledTokens.cacheWrite)
                            let splitTh = splitField(sScaledTokens.thinking)
                            let splitTotal: Int
                            if sScaledTokens.input + sScaledTokens.output + sScaledTokens.cacheRead + sScaledTokens.cacheWrite > 0 {
                                splitTotal = splitInp + splitOut + splitCr + splitCw
                            } else {
                                splitTotal = splitField(sScaledTokens.total)
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

            for fp in report.projects where !report.spec.isAll {
                // 按 (项目, agent) 分配：每个 agent 只分它自己在范围内的花费与 token；
                // 没有范围内会话的 agent（或 byAgent 缺失）留下的余量才按旧办法摊到项目全部会话上。
                var restCost = fp.cost
                var restTokens = fp.tokens
                for a in fp.byAgent {
                    let own = fp.sessionsDetail.filter { $0.agent == a.agent }
                    guard !own.isEmpty else { continue }
                    processGroup(sessions: own, targetCost: a.cost, targetTokens: a.tokens.total)
                    restCost -= a.cost
                    restTokens -= a.tokens.total
                }
                processGroup(sessions: fp.sessionsDetail, targetCost: restCost > 1e-9 ? restCost : 0,
                             targetTokens: max(0, restTokens))
            }
            processGroup(sessions: report.unattributed.sessionsDetail, targetCost: report.unattributed.cost, targetTokens: report.unattributed.tokens)
            processGroup(sessions: report.excluded.sessionsDetail, targetCost: report.excluded.cost, targetTokens: report.excluded.tokens)
        }

        // 按总 token 数降序排列；相等时按花费降序，再按模型名称升序
        return map.values.filter { $0.tokens.total > 0 || $0.cost > 0 }.sorted { a, b in
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
