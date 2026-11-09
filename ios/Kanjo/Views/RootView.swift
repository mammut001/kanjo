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
                    ToolbarItem(placement: .topBarLeading) {
                        KanjoAvatarIcon(size: 24)
                    }
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
            ScrollView {
                VStack(spacing: 20) {
                    KanjoAvatarIcon(size: 72)
                        .padding(.top, 24)

                    VStack(spacing: 8) {
                        Text(L10n.tr("ios.empty.title"))
                            .font(.title2.weight(.bold))
                        Text(L10n.tr("ios.empty.body"))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 24)
                    }

                    VStack(alignment: .leading, spacing: 14) {
                        Text(L10n.tr("ios.empty.steps.title"))
                            .font(.headline)
                            .foregroundStyle(.primary)

                        setupStepRow(number: "1", text: L10n.tr("ios.empty.step1"))
                        setupStepRow(number: "2", text: L10n.tr("ios.empty.step2"))
                        setupStepRow(number: "3", text: L10n.tr("ios.empty.step3"))

                        if let code = store.accountCode {
                            Divider()
                            Text(L10n.tr("ios.empty.account", code))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(16)
                    .background(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(Color(uiColor: .secondarySystemGroupedBackground))
                    )
                    .padding(.horizontal, 20)

                    VStack(spacing: 12) {
                        Button {
                            Task { await store.load() }
                        } label: {
                            Text(L10n.tr("common.retry"))
                                .font(.body.weight(.semibold))
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(Color.accentColor, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .foregroundStyle(.white)
                        }

                        Button {
                            Task { await store.loadSample() }
                        } label: {
                            Text(L10n.tr("ios.empty.try_sample"))
                                .font(.body.weight(.medium))
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(Color(uiColor: .tertiarySystemFill), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .foregroundStyle(.primary)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                }
                .padding(.bottom, 32)
            }
            .background(Color(uiColor: .systemGroupedBackground))
        case .failed(let message):
            VStack(spacing: 20) {
                KanjoAvatarIcon(size: 72)
                    .padding(.top, 32)

                VStack(spacing: 8) {
                    Text(L10n.tr("ios.error.title"))
                        .font(.title2.weight(.bold))
                    Text(message)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                }

                VStack(spacing: 12) {
                    Button {
                        Task { await store.load() }
                    } label: {
                        Text(L10n.tr("common.retry"))
                            .font(.body.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(Color.accentColor, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .foregroundStyle(.white)
                    }

                    Button {
                        Task { await store.loadSample() }
                    } label: {
                        Text(L10n.tr("ios.empty.try_sample"))
                            .font(.body.weight(.medium))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(Color(uiColor: .tertiarySystemFill), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .foregroundStyle(.primary)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.top, 8)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: .systemGroupedBackground))
        case .loaded(let report):
            OverviewView(report: report, deviceName: store.deviceName, accountCode: store.accountCode, store: store)
                .refreshable { await store.refresh() }
        }
    }

    private func setupStepRow(number: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 20, height: 20)
                .background(Circle().fill(Color.accentColor))
            Text(text)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
