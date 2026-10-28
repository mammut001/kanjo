import KanjoCore
import SwiftUI

struct RootView: View {
    var store: SnapshotStore
    @AppStorage(SettingsKeys.appLanguage, store: AppDefaults.store) private var language = AppLanguage.system.rawValue

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Kanjo")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        LanguageMenu(language: $language)
                    }
                }
        }
        .id(language)
        .task { await store.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch store.state {
        case .loading:
            VStack(spacing: 10) {
                ProgressView()
                Text(L10n.tr("ios.loading"))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            ContentUnavailableView {
                Label(L10n.tr("ios.empty.title"), systemImage: "icloud.slash")
            } description: {
                VStack(spacing: 8) {
                    Text(L10n.tr("ios.empty.body"))
                    if let code = store.accountCode {
                        Text(L10n.tr("ios.empty.account", code))
                            .font(.footnote)
                    }
                }
            } actions: {
                Button(L10n.tr("common.retry")) {
                    Task { await store.load() }
                }
            }
        case .failed(let message):
            ContentUnavailableView {
                Label(L10n.tr("ios.error.title"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            } actions: {
                Button(L10n.tr("common.retry")) {
                    Task { await store.load() }
                }
            }
        case .loaded(let report):
            OverviewView(report: report, deviceName: store.deviceName, accountCode: store.accountCode)
                .refreshable { await store.refresh() }
        }
    }
}
