import Foundation

/// 账号套餐写入的待办队列。同一账号只保留最后一次选择，账号之间按首次入队的顺序写。
public struct WriteQueue: Equatable, Sendable {
    public struct Write: Equatable, Sendable {
        public let email: String
        public let plan: String?
        public init(email: String, plan: String?) {
            self.email = email
            self.plan = plan
        }
    }

    private var queue: [Write] = []

    public init() {}

    public var isEmpty: Bool { queue.isEmpty }

    /// 还有写入排队的账号。
    public var emails: Set<String> { Set(queue.map(\.email)) }

    public mutating func enqueue(_ write: Write) {
        queue.append(write)
    }

    public mutating func dequeueAllAndCoalesce() -> [Write] {
        var order: [String] = []
        var latest: [String: Write] = [:]
        for write in queue {
            if latest[write.email] == nil { order.append(write.email) }
            latest[write.email] = write
        }
        queue = []
        return order.compactMap { latest[$0] }
    }
}
