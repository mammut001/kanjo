import Foundation

/// by_agent 里花费最多的 agent 及其占比；没有正花费时为 nil。
public func dominantAgent(_ byAgent: [AgentCost]) -> (agent: String, label: String, share: Double)? {
    let total = byAgent.reduce(0) { $0 + max($1.cost, 0) }
    guard total > 0, let top = byAgent.max(by: { $0.cost < $1.cost }), top.cost > 0 else { return nil }
    return (top.agent, top.label, top.cost / total)
}
