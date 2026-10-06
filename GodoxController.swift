import AppKit
import Foundation
import WebKit
import CoreBluetooth
import Sparkle

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var window: NSWindow?
    private var webView: WKWebView?
    private let backend = BackendSupervisor()
    // 用于在 Swift 进程内预热 CoreBluetooth，让 macOS 把 BLE 权限归属到 .app Bundle，
    // 而不是落到后端 Python 进程上；后端 bleak 调用才能拿到「点了允许」之后真正可用的状态。
    private var bluetoothWarmer: CBCentralManager?
    private let updaterController = SPUStandardUpdaterController(
        startingUpdater: true,
        updaterDelegate: nil,
        userDriverDelegate: nil
    )

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

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "⚡ 神牛引闪器"
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        // 预热 CoreBluetooth：让 macOS 把 BLE 权限落到当前 .app Bundle，
        // 否则 Python 后端的 bleak 调用会在系统层断链（弹窗能弹但 allow 不生效）。
        warmUpCoreBluetooth()

        backend.onReady = { [weak self] url in self?.webView?.load(URLRequest(url: url)) }
        backend.onFailure = { [weak self] detail in self?.showErrorPage(detail) }
        setupFloatingWindow()
        ensureServerRunning()

        // Auto show on first launch
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            self?.showWindowUnderStatusItem()
        }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        // 应用切到前台时再次确认 CoreBluetooth 已被激活；如果用户此前点了「不允许」，
        // 这里重新触发一次给系统再一次机会绑定权限归属。
        if bluetoothWarmer == nil {
            warmUpCoreBluetooth()
        }
    }

    private func warmUpCoreBluetooth() {
        // 只持有一个 nil-delegate 的 manager；目的就是让 CoreBluetooth 初始化 + 系统把它
        // 绑定到当前 .app 的 Bundle ID。真正的扫描 / 连接由后端 bleak 走 CoreBluetooth 完成。
        if bluetoothWarmer == nil {
            bluetoothWarmer = CBCentralManager(delegate: nil, queue: nil)
        }
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

        let updateItem = NSMenuItem(
            title: "检查更新…",
            action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)),
            keyEquivalent: "u"
        )
        updateItem.target = updaterController
        menu.addItem(updateItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "退出控制台", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil // Reset back to toggle on left click
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
        DispatchQueue.main.async {
            self.backend.shutdown { sender.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
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
