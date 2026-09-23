import AppKit
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var window: NSWindow?
    private var webView: WKWebView?
    private var serverProcess: Process?

    static let port = 8765
    static let localUrl = "http://127.0.0.1:8765/"
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
            button.title = "⚡ X3 Pro"
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        ensureServerRunning()
        setupFloatingWindow()

        // Auto show on first launch
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self] in
            self?.showWindowUnderStatusItem()
        }
    }

    func ensureServerRunning() {
        if !isServerHealthy() {
            startServer()
        }
    }

    func isServerHealthy() -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
        p.arguments = ["--noproxy", "*", "--max-time", "1", "-s", Self.localUrl + "api/health"]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = Pipe()
        do {
            try p.run()
            p.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let response = String(data: data, encoding: .utf8) ?? ""
            return p.terminationStatus == 0 && response.contains("\"app\":\"godox-controller\"")
        } catch {
            return false
        }
    }

    func startServer() {
        let p = Process()
        if let backend = Self.bundledBackendURL {
            p.executableURL = backend
            p.currentDirectoryURL = backend.deletingLastPathComponent()
        } else {
            let venvPython = Self.workDir + "/.venv/bin/python"
            p.executableURL = URL(fileURLWithPath: venvPython)
            p.arguments = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(Self.port)]
            p.currentDirectoryURL = URL(fileURLWithPath: Self.workDir)
        }
        do {
            try p.run()
            serverProcess = p
        } catch {
            print("Failed to start uvicorn: \(error)")
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
        win.title = "神牛 X3 Pro 桌面控制台"
        win.level = .floating // Always stay on top over Capture One
        win.delegate = self

        let config = WKWebViewConfiguration()
        let wv = WKWebView(frame: win.contentView?.bounds ?? rect, configuration: config)
        wv.autoresizingMask = [.width, .height]
        win.contentView?.addSubview(wv)

        self.window = win
        self.webView = wv
        showLoadingPage()
        loadConsoleWhenReady()
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

    func loadConsoleWhenReady(attempt: Int = 0) {
        if isServerHealthy(), let url = URL(string: Self.localUrl) {
            webView?.load(URLRequest(url: url))
            return
        }

        // 打包版首次启动需要解包并初始化 BLE 运行时；在其完成前保留加载页，避免白屏。
        if attempt < 60 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                self?.loadConsoleWhenReady(attempt: attempt + 1)
            }
            return
        }

        let errorHtml = """
        <!doctype html><meta charset=\"utf-8\"><style>body{margin:0;display:grid;place-items:center;height:100vh;background:#0d0f12;color:#f0f3f6;font-family:-apple-system,system-ui}main{text-align:center}button{margin-top:16px;padding:8px 14px;border:0;border-radius:6px;background:#e58e26;color:#000;font-weight:600}</style><main><strong>控制台服务尚未启动</strong><p>请稍候后在菜单栏选择“刷新控制面板”。</p></main>
        """
        webView?.loadHTMLString(errorHtml, baseURL: nil)
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
        let titleItem = NSMenuItem(title: "神牛 X3 Pro 控制台 (127.0.0.1:8765)", action: nil, keyEquivalent: "")
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

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "退出控制台", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil // Reset back to toggle on left click
    }

    @objc func openBrowserAction() {
        if let url = URL(string: Self.localUrl) {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func reloadAction() {
        showLoadingPage()
        loadConsoleWhenReady()
    }

    @objc func testFireAction() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
        p.arguments = ["--noproxy", "*", "-s", "-X", "POST", Self.localUrl + "api/test_fire"]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = Pipe()
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try p.run()
                p.waitUntilExit()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let response = String(data: data, encoding: .utf8) ?? ""
                let success = response.contains("\"success\":true")
                let title = success ? "引闪器已确认试闪指令" : "试闪失败"
                let detail = success ? "请观察实体闪光灯是否触发。" : "请确认引闪器已连接、在蓝牙范围内后重试。"
                DispatchQueue.main.async {
                    let alert = NSAlert()
                    alert.messageText = title
                    alert.informativeText = detail
                    alert.addButton(withTitle: "好")
                    alert.runModal()
                }
            } catch {
                DispatchQueue.main.async {
                    let alert = NSAlert(error: error)
                    alert.runModal()
                }
            }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        serverProcess?.terminate()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
