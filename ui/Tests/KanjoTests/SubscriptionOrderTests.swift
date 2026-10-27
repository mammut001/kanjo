import XCTest
@testable import KanjoCore

final class SubscriptionOrderTests: KanjoTestCase {
    private func row(agent: String, usage: Double = 10.0) -> SubscriptionRow {
        SubscriptionRow(
            agent: agent,
            planLabel: agent.capitalized,
            monthlyPriceUsd: 20.0,
            usage: usage,
            multiplier: 0.5,
            extraUsageEnabled: false
        )
    }

    /// apply with empty order = default
    func testApplyWithEmptyOrderReturnsDefault() {
        let rows = [row(agent: "claude", usage: 100), row(agent: "codex", usage: 50), row(agent: "grok", usage: 20)]
        let ordered = SubscriptionOrder.apply(order: [], to: rows)
        XCTAssertEqual(ordered.map(\.agent), ["claude", "codex", "grok"])
        XCTAssertEqual(ordered, rows)
    }

    /// partial order: agents in saved order first; agents not in saved order keep default order
    func testApplyPartialOrder() {
        let rows = [
            row(agent: "claude", usage: 100),
            row(agent: "codex", usage: 50),
            row(agent: "grok", usage: 30),
            row(agent: "minimax", usage: 10),
        ]
        let ordered = SubscriptionOrder.apply(order: ["grok", "claude"], to: rows)
        XCTAssertEqual(ordered.map(\.agent), ["grok", "claude", "codex", "minimax"])
    }

    /// unknown agent ignored
    func testApplyUnknownAgentIgnored() {
        let rows = [row(agent: "claude"), row(agent: "codex"), row(agent: "grok")]
        let ordered = SubscriptionOrder.apply(order: ["unknown-agent", "grok", "nonexistent"], to: rows)
        XCTAssertEqual(ordered.map(\.agent), ["grok", "claude", "codex"])
    }

    /// move semantics: dropping row A on row B moves A to B's position
    func testMoveSemantics() {
        let initial = ["claude", "codex", "grok", "minimax"]

        // Move later item to earlier item's position
        let movedUp = SubscriptionOrder.move(from: "minimax", to: "codex", in: initial)
        XCTAssertEqual(movedUp, ["claude", "minimax", "codex", "grok"])

        // Move earlier item to later item's position
        let movedDown = SubscriptionOrder.move(from: "claude", to: "grok", in: initial)
        XCTAssertEqual(movedDown, ["codex", "grok", "claude", "minimax"])

        // Moving to same position returns list unchanged
        let unchanged = SubscriptionOrder.move(from: "claude", to: "claude", in: initial)
        XCTAssertEqual(unchanged, initial)

        // Non-existent source or target returns list unchanged
        XCTAssertEqual(SubscriptionOrder.move(from: "ghost", to: "claude", in: initial), initial)
        XCTAssertEqual(SubscriptionOrder.move(from: "claude", to: "ghost", in: initial), initial)

        // SubscriptionRow move overload
        let rows = [row(agent: "claude"), row(agent: "codex"), row(agent: "grok"), row(agent: "minimax")]
        let movedRows = SubscriptionOrder.move(from: "minimax", to: "claude", in: rows)
        XCTAssertEqual(movedRows.map(\.agent), ["minimax", "claude", "codex", "grok"])
    }

    /// parse/serialize round trip
    func testParseAndSerializeRoundTrip() {
        let empty = SubscriptionOrder.parse("")
        XCTAssertEqual(empty, [])
        XCTAssertEqual(SubscriptionOrder.serialize([]), "")

        let whitespace = SubscriptionOrder.parse("  claude , codex , , grok  ")
        XCTAssertEqual(whitespace, ["claude", "codex", "grok"])

        let original = ["claude", "codex", "grok", "minimax"]
        let serialized = SubscriptionOrder.serialize(original)
        XCTAssertEqual(serialized, "claude,codex,grok,minimax")
        let parsed = SubscriptionOrder.parse(serialized)
        XCTAssertEqual(parsed, original)

        // Duplicates are deduplicated while preserving order
        let deduplicated = SubscriptionOrder.parse("claude,codex,claude,grok")
        XCTAssertEqual(deduplicated, ["claude", "codex", "grok"])
    }

    /// collapse helper visible(rows, expanded:, limit: 3) returns 3 or all
    func testCollapseHelperVisible() {
        let rows = [
            row(agent: "a"),
            row(agent: "b"),
            row(agent: "c"),
            row(agent: "d"),
            row(agent: "e"),
        ]

        // When collapsed (expanded = false), returns limit (3) rows
        let collapsed = SubscriptionOrder.visible(rows, expanded: false, limit: 3)
        XCTAssertEqual(collapsed.count, 3)
        XCTAssertEqual(collapsed.map(\.agent), ["a", "b", "c"])

        // Default limit is 3
        let defaultCollapsed = SubscriptionOrder.visible(rows, expanded: false)
        XCTAssertEqual(defaultCollapsed.count, 3)
        XCTAssertEqual(defaultCollapsed.map(\.agent), ["a", "b", "c"])

        // When expanded (expanded = true), returns all rows
        let expanded = SubscriptionOrder.visible(rows, expanded: true, limit: 3)
        XCTAssertEqual(expanded.count, 5)
        XCTAssertEqual(expanded.map(\.agent), ["a", "b", "c", "d", "e"])

        // Rows count <= limit returns all rows even when collapsed
        let shortRows = [row(agent: "a"), row(agent: "b")]
        XCTAssertEqual(SubscriptionOrder.visible(shortRows, expanded: false, limit: 3).count, 2)
        XCTAssertEqual(SubscriptionOrder.visible(shortRows, expanded: true, limit: 3).count, 2)

        // Empty rows returns empty
        let emptyRows: [SubscriptionRow] = []
        XCTAssertEqual(SubscriptionOrder.visible(emptyRows, expanded: false, limit: 3), [])
        XCTAssertEqual(SubscriptionOrder.visible(emptyRows, expanded: true, limit: 3), [])
    }
}
