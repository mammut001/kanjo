import AppKit
import Combine
import KanjoCore
import Sparkle

/// 应用内更新（Sparkle 2）。
///
/// Kanjo 是菜单栏应用（`LSUIElement`），自动安装是关的：只有用户接受 Sparkle 的窗口才会装上。
/// 如果不用下面的 gentle reminder 代理，定时检查发现的更新会弹在所有窗口后面、永远不抢焦点
/// —— 这正是 Cool Down Pro 1.0.18 拖了一个月没升级的原因。这里把定时检查发现的更新
/// 变成菜单栏面板里的「Kanjo X 可用 — 更新」一行，点它再把 Sparkle 的窗口带到前台。
///
/// 只有从打包好的 .app 运行、并且 Info.plist 里有真实的 SUFeedURL / SUPublicEDKey 时才启动，
/// 否则（`swift run`、`--snapshot`、`--window`、`--data`）更新相关的一切都不出现。
@MainActor
final class UpdateController: NSObject, ObservableObject {
    static let shared = UpdateController()

    /// 是否真的启动了 Sparkle；false 时设置页没有 Updates 一节，面板里也没有提醒行。
    let isActive: Bool

    @Published private(set) var canCheckForUpdates: Bool = false
    @Published private(set) var isChecking = false
    @Published var automaticallyChecksForUpdates: Bool = false {
        didSet {
            updaterController?.updater.automaticallyChecksForUpdates = automaticallyChecksForUpdates
        }
    }
    @Published private(set) var lastUpdateCheckDate: Date? = nil
    /// 定时检查发现、用户还没看过的更新版本号，驱动面板里的提醒行。
    @Published private(set) var pendingUpdateVersion: String? = nil

    private var updaterController: SPUStandardUpdaterController?
    private var cancellables = Set<AnyCancellable>()

    private override init() {
        isActive = UpdateGate.shouldStartUpdater()
        super.init()
        guard isActive else { return }

        let controller = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: self
        )
        updaterController = controller

        canCheckForUpdates = controller.updater.canCheckForUpdates
        automaticallyChecksForUpdates = controller.updater.automaticallyChecksForUpdates
        lastUpdateCheckDate = controller.updater.lastUpdateCheckDate

        controller.updater.publisher(for: \.canCheckForUpdates)
            .receive(on: RunLoop.main)
            .sink { [weak self] value in
                self?.canCheckForUpdates = value
                self?.isChecking = false
            }
            .store(in: &cancellables)

        controller.updater.publisher(for: \.automaticallyChecksForUpdates)
            .receive(on: RunLoop.main)
            .sink { [weak self] value in
                guard let self, self.automaticallyChecksForUpdates != value else { return }
                self.automaticallyChecksForUpdates = value
            }
            .store(in: &cancellables)

        controller.updater.publisher(for: \.lastUpdateCheckDate)
            .receive(on: RunLoop.main)
            .sink { [weak self] value in self?.lastUpdateCheckDate = value }
            .store(in: &cancellables)
    }

    /// 把 Sparkle 的更新窗口带到前台。定时检查已经找到的更新会被直接拿到前台，
    /// 不会重新检查一次。
    func checkForUpdates() {
        guard let updater = updaterController?.updater else { return }
        isChecking = true
        NSApp.activate(ignoringOtherApps: true)
        updater.checkForUpdates()
        // 一般 canCheckForUpdates 会在检查结束后自己翻回 true；这里只兜底，别让转圈卡住。
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            self?.isChecking = false
        }
    }

    /// 面板提醒行被点：清掉提醒，再把 Sparkle 的窗口带到前台。
    func showPendingUpdate() {
        pendingUpdateVersion = nil
        checkForUpdates()
    }

    var formattedCurrentVersion: String {
        let info = Bundle.main.infoDictionary
        return UpdateFormatting.versionString(
            marketing: info?["CFBundleShortVersionString"] as? String,
            build: info?["CFBundleVersion"] as? String
        )
    }

    var formattedLastCheckDate: String {
        UpdateFormatting.lastCheckDescription(date: lastUpdateCheckDate)
    }

    private func rememberPendingUpdate(_ update: SUAppcastItem) {
        pendingUpdateVersion = update.displayVersionString
        NSApp.activate(ignoringOtherApps: false)
    }

    private func clearPendingUpdate() {
        pendingUpdateVersion = nil
    }
}

extension UpdateController: SPUStandardUserDriverDelegate {
    nonisolated var supportsGentleScheduledUpdateReminders: Bool { true }

    nonisolated func standardUserDriverShouldHandleShowingScheduledUpdate(
        _ update: SUAppcastItem,
        andInImmediateFocus immediateFocus: Bool
    ) -> Bool {
        // 刚启动（或长时间闲置后）Sparkle 会把 app 激活并把窗口做成 key window：保持这样。
        // 其他时机的定时检查只会把窗口放在所有 app 后面，所以交给本控制器，显示成面板里的一行。
        immediateFocus
    }

    nonisolated func standardUserDriverWillHandleShowingUpdate(
        _ handleShowingUpdate: Bool,
        forUpdate update: SUAppcastItem,
        state: SPUUserUpdateState
    ) {
        guard !state.userInitiated, !handleShowingUpdate else { return }
        MainActor.assumeIsolated { rememberPendingUpdate(update) }
    }

    nonisolated func standardUserDriverDidReceiveUserAttention(forUpdate update: SUAppcastItem) {
        MainActor.assumeIsolated { clearPendingUpdate() }
    }

    nonisolated func standardUserDriverWillFinishUpdateSession() {
        MainActor.assumeIsolated { clearPendingUpdate() }
    }
}
