import AppIntents
import Foundation
import KanjoCore

struct QuotaAgentEntity: AppEntity, Identifiable, Hashable {
    static var typeDisplayRepresentation: TypeDisplayRepresentation {
        // 与参数标题共用 "Agent" 这一条，翻译在扩展的 Localizable.strings。
        TypeDisplayRepresentation(name: "Agent")
    }

    static var defaultQuery = QuotaAgentEntityQuery()

    var id: String
    var title: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)")
    }

    static func entity(for agent: String) -> QuotaAgentEntity {
        QuotaAgentEntity(id: agent, title: AgentColors.label(for: agent))
    }
}

struct QuotaAgentEntityQuery: EntityStringQuery {
    func entities(for identifiers: [QuotaAgentEntity.ID]) async throws -> [QuotaAgentEntity] {
        WidgetSnapshotCache.applySharedLanguagePreference()
        return identifiers.map { QuotaAgentEntity.entity(for: $0) }
    }

    func entities(matching string: String) async throws -> [QuotaAgentEntity] {
        let all = try await suggestedEntities()
        let query = string.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !query.isEmpty else { return all }
        return all.filter {
            $0.id.lowercased().contains(query) || $0.title.lowercased().contains(query)
        }
    }

    func suggestedEntities() async throws -> [QuotaAgentEntity] {
        WidgetSnapshotCache.applySharedLanguagePreference()
        return availableQuotaAgents().map { QuotaAgentEntity.entity(for: $0) }
    }

    func defaultResult() async -> QuotaAgentEntity? {
        WidgetSnapshotCache.applySharedLanguagePreference()
        guard let first = availableQuotaAgents().first else { return nil }
        return QuotaAgentEntity.entity(for: first)
    }

    private func availableQuotaAgents() -> [String] {
        // 只提供真实缓存里有额度的 agent。库预览没有选择时仍走示例快照的默认 agent。
        WidgetSnapshotCache.read()?.quotaAgents() ?? []
    }
}

struct SelectQuotaAgentIntent: WidgetConfigurationIntent {
    // App Intents 从小组件扩展自己的 bundle 查这些文案，不走 KanjoCore。
    // 见 KanjoWidget/{en,zh-Hans,fr}.lproj/Localizable.strings。
    static var title: LocalizedStringResource = "Select Agent"
    static var description = IntentDescription("Choose which AI agent's quota to display.")

    @Parameter(title: "Agent")
    var agent: QuotaAgentEntity?

    init() {}

    init(agent: QuotaAgentEntity?) {
        self.agent = agent
    }

    func resolvedAgent(in snapshot: WidgetSnapshot?, now: Date = Date()) -> String? {
        if let explicit = agent?.id, !explicit.isEmpty {
            return explicit
        }
        return snapshot?.defaultQuotaAgent(now: now)
    }
}
