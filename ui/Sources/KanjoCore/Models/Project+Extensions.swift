import Foundation

public extension Project {
    func fallbackAgent() -> String {
        dominantAgent(self.byAgent)?.agent ?? self.byAgent.first?.agent ?? "unknown"
    }
}
