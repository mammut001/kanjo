import XCTest
@testable import KanjoCore

final class WriteQueueTests: XCTestCase {
    func testCoalescesToLatestValueInFirstEnqueueOrder() {
        var queue = WriteQueue()
        queue.enqueue(WriteQueue.Write(email: "z@b.com", plan: "pro"))
        queue.enqueue(WriteQueue.Write(email: "a@d.com", plan: "max"))
        queue.enqueue(WriteQueue.Write(email: "m@d.com", plan: nil))
        queue.enqueue(WriteQueue.Write(email: "z@b.com", plan: "ultra"))
        XCTAssertEqual(queue.emails, ["z@b.com", "a@d.com", "m@d.com"])

        XCTAssertEqual(queue.dequeueAllAndCoalesce(), [
            WriteQueue.Write(email: "z@b.com", plan: "ultra"),
            WriteQueue.Write(email: "a@d.com", plan: "max"),
            WriteQueue.Write(email: "m@d.com", plan: nil),
        ])
        XCTAssertTrue(queue.isEmpty)
        XCTAssertEqual(queue.dequeueAllAndCoalesce(), [])
    }

    func testOrderIsStableAcrossManyAccounts() {
        var queue = WriteQueue()
        let emails = (0..<50).map { "user\($0)@example.com" }
        for email in emails { queue.enqueue(WriteQueue.Write(email: email, plan: "a")) }
        for email in emails.reversed() { queue.enqueue(WriteQueue.Write(email: email, plan: "b")) }
        let batch = queue.dequeueAllAndCoalesce()
        XCTAssertEqual(batch.map(\.email), emails)
        XCTAssertTrue(batch.allSatisfy { $0.plan == "b" })
    }
}
