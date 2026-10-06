import AppKit
import Foundation
import WebKit
import CoreBluetooth
import Sparkle

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {
    private var statusItem: NSStatusItem!
    private var window: NSWindow?
    private var webView: WKWebView?
    private let backend = BackendSupervisor()
    #if !GODOX_UPDATE_UI_PREVIEW
    // 用于在 Swift 进程内预热 CoreBluetooth，让 macOS 把 BLE 权限归属到 .app Bundle，
    // 而不是落到后端 Python 进程上；后端 bleak 调用才能拿到「点了允许」之后真正可用的状态。
    private var bluetoothWarmer: CBCentralManager?
    #endif
    private let reconnectStore = PendingReconnectStore(directory: PendingReconnectStore.defaultDirectory())
    private let postUpdateRestore = PostUpdateRestorePlan()
    private var consoleBridge: ConsoleUpdateBridge?
    private var updateCoordinator: UpdateCoordinator?
    /// 菜单栏图标的拥有者：状态变化时只重画一次，外观变化时自己重画，
    /// 因此 AppDelegate 不再自己缓存「画过哪一份状态」。
    private var statusArtwork: StatusItemArtworkController?
    /// 本机真实的构建号，与 CFBundleVersion 同源。marker 用它判断这次启动到底有没有换版本。
    private static var currentBuild: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "0"
    }

    static let workDir: String = {
        if let configured = ProcessInfo.processInfo.environment["GODOX_CONTROLLER_HOME"], !configured.isEmpty {
            return URL(fileURLWithPath: configured).standardizedFileURL.path
        }

        let bundleURL = Bundle.main.bundleURL
        if bundleURL.pathExtension == "app" {
            return bundleURL.deletingLastPathComponent().standardizedFileURL.path
        }

        return URL(fileURLWithPath: CommandLine.arguments[0])
            .deletingLastPathComponent()
            .standardizedFileURL.path
    }()

    static var bundledBackendURL: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let executable = resources.appendingPathComponent("backend/GodoxControllerBackend")
        return FileManager.default.isExecutableFile(atPath: executable.path) ? executable : nil
    }

    /// 本机正在运行的版本。菜单栏提示、控制台入口和更新状态都以它为准，
    /// 与 Info.plist 是同一个来源，不存在第二份版本字符串。
    static var displayVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "未知版本"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        #if GODOX_UPDATE_UI_PREVIEW
        // 预览构建里的每一条生命周期都留在预览里。这里不看参数：即使有人不带
        // --preview-update-ui 打开这个 bundle，也绝不能掉进正式路径去启动后端、
        // 预热蓝牙或创建更新器。
        UpdatePreviewEnvironment.run()
        #else
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
            // Sparkle 必须先于预热与后端启动：它是整个会话里唯一需要应用已完全就绪的东西。
            installUpdateCoordinator()
            statusArtwork = StatusItemArtworkController(
                button: button,
                label: "⚡ 神牛引闪器",
                initialState: updateCoordinator?.state
                    ?? UpdateState(currentVersion: Self.displayVersion, availability: .unchecked)
            )
        }

        // 预热 CoreBluetooth：让 macOS 把 BLE 权限落到当前 .app Bundle，
        // 否则 Python 后端的 bleak 调用会在系统层断链（弹窗能弹但 allow 不生效）。
        warmUpCoreBluetooth()

        backend.onReady = { [weak self] url in self?.consoleBecameReady(at: url) }
        backend.onFailure = { [weak self] detail in self?.showErrorPage(detail) }
        setupFloatingWindow()
        ensureServerRunning()

        // Auto show on first launch
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            self?.showWindowUnderStatusItem()
        }
        #endif
    }

    // MARK: - 更新提醒

    private func installUpdateCoordinator() {
        let coordinator = UpdateCoordinator(currentVersion: Self.displayVersion)
        coordinator.onStateChange = { [weak self] state in self?.renderUpdateState(state) }
        coordinator.onUserRequestedCheck = { controller in controller.checkForUpdates(nil) }
        coordinator.onRelaunchPreparing = { [weak self] targetBuild, done in
            self?.noteConnectedDeviceForPostUpdateRestore(targetBuild: targetBuild, then: done)
        }
        coordinator.onRelaunchAbandoned = { [weak self] in self?.reconnectStore.clear() }
        updateCoordinator = coordinator
        coordinator.start()
    }

    /// 后端就绪：装上控制台桥、推送当前更新状态，并在「这是一次真实更新重启」时
    /// 恢复原设备。恢复只做一次，用完即清，绝不在普通启动时自行连接。
    private func consoleBecameReady(at url: URL) {
        installConsoleBridgeIfNeeded()
        pushUpdateStateToConsole()
        webView?.load(URLRequest(url: url))
        restoreConnectedDeviceAfterUpdateIfNeeded()
    }

    private func installConsoleBridgeIfNeeded() {
        guard consoleBridge == nil, let webView = webView else { return }
        let bridge = ConsoleUpdateBridge(webView: webView) { [weak self] in self?.backend.baseURL }
        bridge.onActionRequested = { [weak self] in self?.updateCoordinator?.userRequestedUpdate() }
        bridge.onStateRequested = { [weak self] in self?.pushUpdateStateToConsole() }
        consoleBridge = bridge
    }

    private func renderUpdateState(_ state: UpdateState) {
        statusArtwork?.update(state)
        pushUpdateStateToConsole()
    }

    private func pushUpdateStateToConsole() {
        guard let state = updateCoordinator?.state else { return }
        consoleBridge?.push(state, currentVersion: state.currentVersion)
    }

    /// 真实更新重启前，记下当时真正连着的那个精确设备地址。新进程启动后用一次即弃。
    ///
    /// `api/status` 的 `device_address` 是一个*记住的*地址：后端启动、失败重连或仅仅重启
    /// 之后它都还在，而 `connected` 才说明此刻真的有链路。所以只有 `connected == true`
    /// 且地址可读时才记；仅仅保存过地址不算连接，记下来等于让下一次升级后去连一个
    /// 从没握过手的地址。
    private func noteConnectedDeviceForPostUpdateRestore(targetBuild: String, then done: @escaping () -> Void) {
        // 快照这一次准备的身份：后台应答回来得慢，而期间更新可能已经失败或被取消，
        // 那一刻迟到的答案不得再写 marker。
        let token = updateCoordinator?.relaunchPreparationToken ?? 0
        backend.get("api/status") { [weak self] json in
            guard let self = self else { return done() }
            guard let coordinator = self.updateCoordinator,
                  coordinator.isRelaunchImminent,
                  coordinator.relaunchPreparationToken == token,
                  coordinator.pendingTargetBuild == targetBuild else { return done() }
            guard self.backend.state == .ready,
                  let address = PendingReconnectStore.connectedAddress(in: json) else { return done() }
            self.reconnectStore.record(address: address,
                                      sourceBuild: Self.currentBuild,
                                      targetBuild: targetBuild)
            done()
        }
    }

    private func restoreConnectedDeviceAfterUpdateIfNeeded() {
        guard let address = postUpdateRestore.addressToReconnect(
            store: reconnectStore,
            currentBuild: Self.currentBuild,
            backendIsReady: backend.state == .ready
        ) else { return }
        // 只连这一个地址：不扫描、不换设备、不试闪。
        backend.connect(address: address) { _ in }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        #if GODOX_UPDATE_UI_PREVIEW
        // 预览构建不碰 CoreBluetooth：这个进程里永远不会有 CBCentralManager，
        // 所以既不会有权限弹窗，也不会把 BLE 授权记到预览的 bundle 上。
        return
        #else
        // 应用切到前台时再次确认 CoreBluetooth 已被激活；如果用户此前点了「不允许」，
        // 这里重新触发一次给系统再一次机会绑定权限归属。
        if bluetoothWarmer == nil {
            warmUpCoreBluetooth()
        }
        #endif
    }

    private func warmUpCoreBluetooth() {
        #if !GODOX_UPDATE_UI_PREVIEW
        // 只持有一个 nil-delegate 的 manager；目的就是让 CoreBluetooth 初始化 + 系统把它
        // 绑定到当前 .app 的 Bundle ID。真正的扫描 / 连接由后端 bleak 走 CoreBluetooth 完成。
        if bluetoothWarmer == nil {
            bluetoothWarmer = CBCentralManager(delegate: nil, queue: nil)
        }
        #endif
    }

    func ensureServerRunning() {
        if let executable = Self.bundledBackendURL {
            backend.refresh(executable: executable, arguments: [], directory: executable.deletingLastPathComponent())
        } else {
            let python = URL(fileURLWithPath: Self.workDir + "/.venv/bin/python")
            backend.refresh(executable: python, arguments: ["-u", Self.workDir + "/app_backend.py"],
                            directory: URL(fileURLWithPath: Self.workDir))
        }
    }

    func setupFloatingWindow() {
        let rect = NSRect(x: 100, y: 100, width: 1100, height: 780)
        let win = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        win.title = "神牛引闪器桌面控制台"
        win.level = .floating // 窗口始终置顶，方便盖在其他工作软件上方
        win.delegate = self

        let config = WKWebViewConfiguration()
        let wv = WKWebView(frame: win.contentView?.bounds ?? rect, configuration: config)
        wv.autoresizingMask = [.width, .height]
        win.contentView?.addSubview(wv)

        self.window = win
        self.webView = wv
        wv.navigationDelegate = self
        showLoadingPage()
    }

    func showLoadingPage() {
        let html = """
        <!doctype html><meta charset=\"utf-8\"><style>
        body{margin:0;display:grid;place-items:center;height:100vh;background:#0d0f12;color:#f0f3f6;font-family:-apple-system,system-ui}
        main{text-align:center}.spinner{width:26px;height:26px;border:3px solid #3d4556;border-top-color:#e58e26;border-radius:50%;margin:0 auto 16px;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
        p{color:#8b949e;font-size:14px}</style><main><div class=\"spinner\"></div><strong>正在启动神牛控制台…</strong><p>正在连接本机服务</p></main>
        """
        webView?.loadHTMLString(html, baseURL: nil)
    }

    func showErrorPage(_ detail: String) {
        let escaped = detail.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
        let html = """
        <!doctype html><meta charset="utf-8"><style>body{margin:0;display:grid;place-items:center;min-height:100vh;background:#0d0f12;color:#f0f3f6;font-family:-apple-system,system-ui}main{max-width:760px;padding:32px}pre{white-space:pre-wrap;color:#aeb8c4;font:14px system-ui}</style><main><h3>控制台服务启动失败</h3><pre>
        """ + escaped + "</pre><p>请在菜单栏选择“刷新控制面板”重试。</p></main>"
        webView?.loadHTMLString(html, baseURL: nil)
    }

    @objc func statusItemClicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp {
            showContextMenu(sender)
        } else {
            toggleWindow()
        }
    }

    func toggleWindow() {
        guard let win = window else { return }
        if win.isVisible {
            win.orderOut(nil)
        } else {
            showWindowUnderStatusItem()
        }
    }

    func showWindowUnderStatusItem() {
        guard let win = window, let button = statusItem.button else { return }

        // Position window neatly right below the menu bar button
        if let buttonWindow = button.window {
            let buttonRectInScreen = buttonWindow.convertToScreen(button.frame)
            let winWidth = win.frame.width
            let winHeight = win.frame.height

            var x = buttonRectInScreen.midX - (winWidth / 2)
            let y = buttonRectInScreen.minY - winHeight - 6

            // Screen boundaries check
            if let screen = NSScreen.main {
                let screenWidth = screen.visibleFrame.maxX
                if x + winWidth > screenWidth {
                    x = screenWidth - winWidth - 16
                }
                if x < 16 { x = 16 }
            }

            win.setFrameOrigin(NSPoint(x: x, y: y))
        }

        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showContextMenu(_ button: NSStatusBarButton) {
        let menu = NSMenu()
        let titleItem = NSMenuItem(title: "神牛引闪器控制台", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        menu.addItem(titleItem)

        menu.addItem(NSMenuItem.separator())

        let openBrowserItem = NSMenuItem(title: "在独立浏览器中打开", action: #selector(openBrowserAction), keyEquivalent: "b")
        openBrowserItem.target = self
        menu.addItem(openBrowserItem)

        let fireItem = NSMenuItem(title: "⚡ 立即试闪 (TEST FIRE)", action: #selector(testFireAction), keyEquivalent: "t")
        fireItem.target = self
        menu.addItem(fireItem)

        let reloadItem = NSMenuItem(title: "刷新控制面板", action: #selector(reloadAction), keyEquivalent: "r")
        reloadItem.target = self
        menu.addItem(reloadItem)

        // 有确定的新版本时，这一条从「检查更新…」变成「更新到 vX…」；
        // 没有时保持原样，行为与以前完全一致。点它仍走 Sparkle 标准窗口。
        let state = updateCoordinator?.state
        let updateItem = NSMenuItem(
            title: state?.menuItemTitle ?? "检查更新…",
            action: #selector(updateRequestedFromMenu),
            keyEquivalent: "u"
        )
        updateItem.target = self
        menu.addItem(updateItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "退出控制台", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil // Reset back to toggle on left click
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        if menuItem.action == #selector(updateRequestedFromMenu) {
            return updateCoordinator?.updaterController?.updater.canCheckForUpdates ?? true
        }
        return true
    }

    @objc func updateRequestedFromMenu() {
        updateCoordinator?.userRequestedUpdate()
    }

    @objc func openBrowserAction() {
        if let url = backend.baseURL, backend.state == .ready {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func reloadAction() {
        if backend.state != .ready { showLoadingPage() }
        ensureServerRunning()
    }

    @objc func testFireAction() {
        backend.post("api/test_fire") { success in
            let alert = NSAlert()
            alert.messageText = success ? "引闪器已确认试闪指令" : "试闪失败"
            alert.informativeText = success ? "请观察实体闪光灯是否触发。" : "请确认控制台服务正常且引闪器已连接，再重试。"
            alert.addButton(withTitle: "好")
            alert.runModal()
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    // 点击窗口外任意位置（切到其他 App、点桌面）后自动收起浮动面板，
    // 菜单栏应用的标准行为；再次点击菜单栏图标可重新唤出。
    func applicationDidResignActive(_ notification: Notification) {
        window?.orderOut(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        #if GODOX_UPDATE_UI_PREVIEW
        // 预览的退出只结束它自己：不碰正式版的状态目录（那里放着真正的更新后恢复记录），
        // 也不去 shutdown 一个从未启动的后端。
        return .terminateNow
        #else
        // Sparkle 不会绕过退出：SPUUserDriver.h:233 明确写着「若应用尚未终止，安装前会向
        // 运行中的应用发送一个 quit event」。所以更新重启时这里一定会被走到，无条件清
        // 记录就是每次都把刚写好的 marker 删掉。判据只能是 updater 真的进入了预重启准备，
        // 而不是「应用要退出了」。
        //
        // 其它一切退出路径——菜单退出、⌘Q、失败或取消之后的退出——都清掉没有生效的
        // marker，免得下一次普通启动被当成更新重启。
        let relaunchImminent = updateCoordinator?.isRelaunchImminent ?? false
        if !relaunchImminent {
            reconnectStore.clear()
        }
        // 无论走哪条路径，后端与蓝牙都要收干净：BLE 由 backend 的断开负责，lock 由
        // 进程退出负责。
        DispatchQueue.main.async {
            self.backend.shutdown { sender.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
        #endif
    }
}

extension AppDelegate: WKNavigationDelegate {
    /// 页面每次加载完成都是一个全新文档：必须重新告知当前更新状态，
    /// 否则刷新或后端重启后，控制台标题旁的更新入口会消失或停在旧状态。
    ///
    /// 只有确实停在控制台来源上的那次完成加载才会推；`didFinish` 本身在别处也返回 true，
    /// 所以这里用 `consoleDidFinishLoading()` 的返回值而不是无脑推送。
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard consoleBridge?.consoleDidFinishLoading() == true else { return }
        pushUpdateStateToConsole()
    }

    /// 导航一开始就把桥关掉：正在离开的文档不得再替即将到来的文档要状态或拿状态。
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        consoleBridge?.consoleWillStartLoading()
    }

    /// 加载失败同样不能让桥留在 ready：那一屏不是控制台。
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        consoleBridge?.consoleWillStartLoading()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        consoleBridge?.consoleWillStartLoading()
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

@main
struct GodoxControllerApplication {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
