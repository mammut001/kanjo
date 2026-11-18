import AppKit
import SwiftUI
import KanjoCore

// MARK: - 侧边浮卡通道与控制器

/// 侧边浮卡专用 PreferenceKey：将面板内触发的详情卡路由到独立浮动窗口，不再覆盖列表。
struct SideCardPreferenceKey: PreferenceKey {
    static var defaultValue: HoverCardPayload? = nil

    static func reduce(value: inout HoverCardPayload?, nextValue: () -> HoverCardPayload?) {
        guard let next = nextValue() else { return }
        // 若已有固定卡片，不让非固定悬停抢占它。
        if let current = value, current.isPinned && !next.isPinned {
            return
        }
        value = next
    }
}

/// 挂在主面板顶层的桥接视图：把 `SideCardPreferenceKey` 和主窗口 / 滚动事件同步给 `SideCardController`。
struct SideCardHostBridge: NSViewRepresentable {
    let payload: HoverCardPayload?
    let appearance: AppAppearance

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> BridgeNSView {
        let view = BridgeNSView(frame: .zero)
        view.onWindowChanged = { [weak coordinator = context.coordinator] window in
            coordinator?.attach(to: window)
            SideCardController.shared.syncFromBridge()
        }
        return view
    }

    func updateNSView(_ nsView: BridgeNSView, context: Context) {
        context.coordinator.attach(to: nsView.window)
        SideCardController.shared.updatePendingState(
            payload: payload,
            panelWindow: nsView.window,
            appearance: appearance
        )
    }

    static func dismantleNSView(_ nsView: BridgeNSView, coordinator: Coordinator) {
        coordinator.detach()
    }

    final class BridgeNSView: NSView {
        var onWindowChanged: ((NSWindow?) -> Void)?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            onWindowChanged?(window)
        }
    }

    final class Coordinator: NSObject {
        private weak var observedWindow: NSWindow?
        private var observers: [NSObjectProtocol] = []

        func attach(to window: NSWindow?) {
            guard observedWindow !== window else { return }
            detach()
            guard let window else { return }
            observedWindow = window

            let nc = NotificationCenter.default
            let reposition: () -> Void = {
                DispatchQueue.main.async {
                    SideCardController.shared.reposition()
                }
            }
            let close: () -> Void = {
                DispatchQueue.main.async {
                    SideCardController.shared.closeAndDismiss()
                }
            }

            observers = [
                nc.addObserver(forName: NSWindow.didMoveNotification, object: window, queue: .main) { _ in reposition() },
                nc.addObserver(forName: NSWindow.didResizeNotification, object: window, queue: .main) { _ in reposition() },
                nc.addObserver(forName: NSWindow.didChangeScreenNotification, object: window, queue: .main) { _ in reposition() },
                nc.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: .main) { _ in close() },
                nc.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: window, queue: .main) { [weak window] _ in
                    if let window, !window.isVisible {
                        close()
                    }
                },
                nc.addObserver(forName: NSView.boundsDidChangeNotification, object: nil, queue: .main) { [weak window] note in
                    guard let window,
                          let clip = note.object as? NSClipView,
                          clip.window === window else { return }
                    reposition()
                },
                nc.addObserver(forName: NSScrollView.didLiveScrollNotification, object: nil, queue: .main) { [weak window] note in
                    guard let window,
                          let sv = note.object as? NSScrollView,
                          sv.window === window else { return }
                    reposition()
                },
                nc.addObserver(forName: NSScrollView.didEndLiveScrollNotification, object: nil, queue: .main) { [weak window] note in
                    guard let window,
                          let sv = note.object as? NSScrollView,
                          sv.window === window else { return }
                    reposition()
                },
            ]
        }

        func detach() {
            let nc = NotificationCenter.default
            for o in observers { nc.removeObserver(o) }
            observers.removeAll()
            observedWindow = nil
        }

        deinit { detach() }
    }
}

// MARK: - 侧边浮卡窗口与生命周期管理

/// 管理主面板旁边的单一无边框非激活 `NSPanel`。
@MainActor
final class SideCardController {
    static let shared = SideCardController()
    static let cardWidth: CGFloat = 340

    private var panel: SideCardPanel?
    private var containerView: SideCardMouseContainerView?
    private var hostingView: SideCardHostingView<SideCardRootView>?

    private var activePayload: HoverCardPayload?
    private weak var panelWindow: NSWindow?
    private var appearance: AppAppearance = .defaultValue
    private var naturalHeightsById: [String: CGFloat] = [:]
    private var currentMaxHeight: CGFloat? = nil

    private var hoveredRowIds: Set<String> = []
    private var isMouseInsidePanel = false
    private var closeGraceTask: Task<Void, Never>?
    private var scheduledSyncWork: DispatchWorkItem?
    private var escMonitor: Any?
    private var appDeactivateObserver: NSObjectProtocol?

    private init() {
        appDeactivateObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didResignActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.closeAndDismiss()
            }
        }
    }

    deinit {
        if let appDeactivateObserver {
            NotificationCenter.default.removeObserver(appDeactivateObserver)
        }
    }

    // MARK: - 来自 HoverCardModifier 的悬停状态

    func noteRowHoverEntered(id: String) {
        hoveredRowIds.insert(id)
        if activePayload?.id == id {
            closeGraceTask?.cancel()
            closeGraceTask = nil
        }
    }

    func noteRowHoverExited(id: String) {
        hoveredRowIds.remove(id)
        if activePayload?.id == id {
            scheduleHoverClose(delayNs: 200_000_000)
        }
    }

    func noteRowHoverExitedWithoutShowing(id: String) {
        hoveredRowIds.remove(id)
    }

    func noteRowDisappeared(id: String) {
        hoveredRowIds.remove(id)
        if activePayload?.id == id && activePayload?.isPinned != true {
            closeAndDismiss()
        }
    }

    func noteAnchorWindowChanged() {
        if activePayload != nil {
            scheduleSync()
        }
    }

    // MARK: - 来自主面板桥接层的同步

    func updatePendingState(payload: HoverCardPayload?, panelWindow: NSWindow?, appearance: AppAppearance) {
        let previousId = activePayload?.id
        if let previous = activePayload, let next = payload, previous.id != next.id {
            previous.onHoverClosed?()
            naturalHeightsById.removeValue(forKey: previous.id)
        }
        if payload == nil, let previous = activePayload {
            naturalHeightsById.removeValue(forKey: previous.id)
        }

        activePayload = payload
        if let panelWindow {
            self.panelWindow = panelWindow
        }
        self.appearance = appearance

        if previousId != payload?.id {
            currentMaxHeight = nil
        }
        if payload?.isPinned == true {
            closeGraceTask?.cancel()
            closeGraceTask = nil
        }

        scheduleSync()
    }

    func syncFromBridge() {
        if activePayload != nil {
            scheduleSync()
        }
    }

    func reposition() {
        guard activePayload != nil else { return }
        scheduleSync()
    }

    func closeAndDismiss() {
        let previous = activePayload
        hidePanelOnly()
        previous?.onDismiss?()
        previous?.onHoverClosed?()
    }

    private func scheduleSync() {
        scheduledSyncWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            Task { @MainActor [weak self] in
                self?.performSync()
            }
        }
        scheduledSyncWork = work
        DispatchQueue.main.async(execute: work)
    }

    private func performSync() {
        scheduledSyncWork = nil
        guard let payload = activePayload,
              let panelWindow,
              panelWindow.isVisible else {
            hidePanelOnly()
            return
        }

        ensureWindowCreated()
        guard let panel, let hostingView else { return }

        guard let rowScreenRect = screenRowRect(for: payload, in: panelWindow) else {
            // 触发行当前在 ScrollView 可视区外（例如启动自动滚动尚未完成），暂隐窗口但保留状态。
            panel.orderOut(nil)
            return
        }

        let visibleFrame = (panelWindow.screen ?? NSScreen.main)?.visibleFrame
            ?? CGRect(x: 0, y: 0, width: 1440, height: 900)

        let nsAppearance = AppearanceController.nsAppearance(for: appearance)
        panel.appearance = nsAppearance
        hostingView.appearance = nsAppearance

        // 先用已知自然高度（若无则先按无高度限制测一次 fittingSize）算出定位与是否需要内部滚动。
        let initialMaxHeight = currentMaxHeight
        hostingView.rootView = makeRootView(payload: payload, maxHeight: initialMaxHeight)
        hostingView.layoutSubtreeIfNeeded()

        let measuredHeight: CGFloat
        if let recorded = naturalHeightsById[payload.id], recorded > 1 {
            measuredHeight = recorded
        } else {
            let fitting = hostingView.fittingSize
            measuredHeight = max(fitting.height, 1)
        }

        var placement = SideCardPlacement.place(
            panelFrame: panelWindow.frame,
            rowFrame: rowScreenRect,
            cardSize: CGSize(width: Self.cardWidth, height: measuredHeight),
            visibleFrame: visibleFrame
        )

        if placement.maxHeight != currentMaxHeight {
            currentMaxHeight = placement.maxHeight
            hostingView.rootView = makeRootView(payload: payload, maxHeight: placement.maxHeight)
            hostingView.layoutSubtreeIfNeeded()
            if placement.maxHeight == nil {
                let updatedFitting = hostingView.fittingSize
                let h = max(naturalHeightsById[payload.id] ?? updatedFitting.height, 1)
                placement = SideCardPlacement.place(
                    panelFrame: panelWindow.frame,
                    rowFrame: rowScreenRect,
                    cardSize: CGSize(width: Self.cardWidth, height: h),
                    visibleFrame: visibleFrame
                )
            }
        }

        panel.level = NSWindow.Level(rawValue: panelWindow.level.rawValue + 1)
        panel.setFrame(NSRect(origin: placement.origin, size: placement.size), display: true)
        if !panel.isVisible {
            panel.orderFront(nil)
        }
        panel.invalidateShadow()
        installEscMonitorIfNeeded()
    }

    private func makeRootView(payload: HoverCardPayload, maxHeight: CGFloat?) -> SideCardRootView {
        SideCardRootView(
            cardId: payload.id,
            content: payload.content,
            maxHeight: maxHeight,
            appearance: appearance,
            onNaturalSize: { [weak self] size in
                guard let self, self.activePayload?.id == payload.id else { return }
                let old = self.naturalHeightsById[payload.id]
                if old == nil || abs((old ?? 0) - size.height) > 0.5 {
                    self.naturalHeightsById[payload.id] = size.height
                    self.scheduleSync()
                }
            }
        )
    }

    private func ensureWindowCreated() {
        if panel != nil { return }

        let p = SideCardPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.cardWidth, height: 100),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        p.isFloatingPanel = true
        p.becomesKeyOnlyIfNeeded = true
        p.hidesOnDeactivate = !CommandLine.arguments.contains(AppDefaults.windowArgument)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.isMovable = false
        p.collectionBehavior = [.transient, .ignoresCycle, .fullScreenAuxiliary]
        p.animationBehavior = .none

        let root = SideCardRootView(
            cardId: "",
            content: AnyView(EmptyView()),
            maxHeight: nil,
            appearance: appearance,
            onNaturalSize: { _ in }
        )
        let host = SideCardHostingView(rootView: root)
        host.translatesAutoresizingMaskIntoConstraints = true
        host.autoresizingMask = [.width, .height]

        let container = SideCardMouseContainerView(frame: NSRect(x: 0, y: 0, width: Self.cardWidth, height: 100))
        container.autoresizingMask = [.width, .height]
        host.frame = container.bounds
        container.addSubview(host)

        container.onMouseEntered = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isMouseInsidePanel = true
                self.closeGraceTask?.cancel()
                self.closeGraceTask = nil
            }
        }
        container.onMouseExited = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isMouseInsidePanel = false
                if self.activePayload?.isPinned != true {
                    self.scheduleHoverClose(delayNs: 150_000_000)
                }
            }
        }

        p.contentView = container
        self.panel = p
        self.containerView = container
        self.hostingView = host
    }

    private func hidePanelOnly() {
        scheduledSyncWork?.cancel()
        scheduledSyncWork = nil
        closeGraceTask?.cancel()
        closeGraceTask = nil
        removeEscMonitor()
        isMouseInsidePanel = false
        hoveredRowIds.removeAll()
        activePayload = nil
        currentMaxHeight = nil
        panel?.orderOut(nil)
    }

    private func scheduleHoverClose(delayNs: UInt64) {
        closeGraceTask?.cancel()
        let targetId = activePayload?.id
        closeGraceTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: delayNs)
            guard !Task.isCancelled, let self else { return }
            guard let payload = self.activePayload,
                  payload.id == targetId,
                  !payload.isPinned else { return }
            if self.hoveredRowIds.contains(payload.id) || self.isMouseInsidePanel {
                return
            }
            if let panel = self.panel, panel.isVisible, panel.frame.contains(NSEvent.mouseLocation) {
                return
            }
            if NSApp.modalWindow != nil {
                return
            }
            self.closeAndDismiss()
        }
    }

    private func screenRowRect(for payload: HoverCardPayload, in panelWindow: NSWindow) -> CGRect? {
        guard let anchorView = payload.anchorBox.view,
              anchorView.window === panelWindow else {
            return nil
        }
        let rectInWindow = anchorView.convert(anchorView.bounds, to: nil)
        if let clipView = anchorView.enclosingScrollView?.contentView {
            let clipInWindow = clipView.convert(clipView.bounds, to: nil)
            guard rectInWindow.intersects(clipInWindow) else {
                return nil
            }
            return panelWindow.convertToScreen(rectInWindow.intersection(clipInWindow))
        }
        return panelWindow.convertToScreen(rectInWindow)
    }

    private func installEscMonitorIfNeeded() {
        guard escMonitor == nil else { return }
        escMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self,
                  event.keyCode == 53,
                  let panel = self.panel,
                  panel.isVisible else {
                return event
            }
            self.closeAndDismiss()
            return nil
        }
    }

    private func removeEscMonitor() {
        if let escMonitor {
            NSEvent.removeMonitor(escMonitor)
            self.escMonitor = nil
        }
    }
}

// MARK: - NSPanel 与宿主视图

private final class SideCardPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

private final class SideCardHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

private final class SideCardMouseContainerView: NSView {
    var onMouseEntered: (() -> Void)?
    var onMouseExited: (() -> Void)?
    private var trackingArea: NSTrackingArea?

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseEntered(with event: NSEvent) {
        super.mouseEntered(with: event)
        onMouseEntered?()
    }

    override func mouseExited(with event: NSEvent) {
        super.mouseExited(with: event)
        onMouseExited?()
    }
}

private struct SideCardRootView: View {
    let cardId: String
    let content: AnyView
    let maxHeight: CGFloat?
    let appearance: AppAppearance
    let onNaturalSize: (CGSize) -> Void

    @AppStorage(SettingsKeys.appAppearance, store: AppDefaults.store) private var storedAppearanceRaw = AppAppearance.defaultValue.rawValue

    private var effectiveAppearance: AppAppearance {
        AppAppearance.resolve(storedAppearanceRaw)
    }

    var body: some View {
        let resolved = effectiveAppearance
        content
            .id(cardId)
            .frame(width: SideCardController.cardWidth)
            .fixedSize(horizontal: false, vertical: true)
            .environment(\.hoverCardMaxHeight, maxHeight)
            .environment(\.hoverCardUsesWindowShadow, true)
            .preferredColorScheme(AppearanceController.colorScheme(for: resolved))
            .onPreferenceChange(HoverCardNaturalSizeKey.self) { size in
                if size != .zero {
                    onNaturalSize(size)
                }
            }
            .overlayPreferenceValue(HoverCardPreferenceKey.self) { tipPayload in
                GeometryReader { geo in
                    HoverCardOverlayHost(
                        payload: tipPayload,
                        containerSize: geo.size,
                        footerHeight: 0
                    )
                }
            }
    }
}
