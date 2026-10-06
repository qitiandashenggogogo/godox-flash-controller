#if GODOX_UPDATE_UI_PREVIEW
import AppKit
import Darwin
import Foundation
import WebKit

/// A throwaway shell for looking at the update reminder without touching anything real.
///
/// It exists so the reminder can be seen, clicked and screenshotted on a machine where the
/// real console is connected to a real light. Everything that could reach the outside world
/// is absent, by construction rather than by configuration:
///
///   * no `UpdateCoordinator` is ever created, so Sparkle has no updater, no feed and no
///     network session — the update button here can only ever show what it would do;
///   * no `BackendSupervisor`, so no backend process, no port and no `backend.lock`;
///   * no `CBCentralManager` at any point in the lifecycle, so no Bluetooth warm-up and no
///     TCC prompt — including on activation and including when the bundle is opened without
///     the launch argument;
///   * its own bundle identifier, so it cannot read or write the console's preferences, and
///     the app delegate's terminate path refuses to touch the console's state directory.
///
/// What it *does* reuse is the part under review: the same `StatusItemArtworkController` that
/// draws the menu bar dot, the same `ConsoleUpdateBridge` and `UpdateBridgePolicy` that gate
/// the console button, and the console's own markup served from a throwaway loopback origin —
/// which is what makes the origin checks here the real ones rather than a stand-in.
enum UpdatePreviewEnvironment {
    static let launchArgument = "--preview-update-ui"
    static let demoNewVersion = "1.6.2"

    /// The one strong reference that keeps the whole preview alive.
    ///
    /// Without it `run()`'s local controller is released the moment `present()` returns, and
    /// the object would then survive only by whatever accident of closures happened to capture
    /// it — a retain cycle between the status item's target and the controller, which breaks
    /// the moment anything is made weak. Holding it here states the ownership outright and
    /// keeps the preview window's callbacks alive without depending on that accident.
    private static var controller: PreviewController?

    static var currentVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? "未知版本"
    }

    @MainActor
    static func run() {
        guard controller == nil else { return }
        let preview = PreviewController(currentVersion: currentVersion, demoNewVersion: demoNewVersion)
        controller = preview
        preview.present()
    }
}

@MainActor
private final class PreviewController: NSObject, WKNavigationDelegate {
    private let state: UpdateState
    private var server: LoopbackConsoleServer?
    private var statusItem: NSStatusItem?
    private var window: NSWindow?
    private var bridge: ConsoleUpdateBridge?
    private var artwork: StatusItemArtworkController?

    init(currentVersion: String, demoNewVersion: String) {
        self.state = UpdateState(currentVersion: currentVersion, availability: .available(version: demoNewVersion))
        super.init()
    }

    func present() {
        let server = LoopbackConsoleServer(consolePage: Self.consolePage())
        self.server = server
        guard let baseURL = server.baseURL else {
            NSAlert().messageText = "预览无法启动本机临时服务。"
            NSAlert().runModal()
            return
        }

        let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            // The same owning, appearance-watching artwork controller the shipping app uses,
            // so what is demonstrated here is the real repaint behaviour and not a copy.
            artwork = StatusItemArtworkController(button: button, label: "⚡ 神牛引闪器", initialState: state)
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        self.statusItem = statusItem

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1100, height: 780),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "神牛引闪器 · 更新提醒效果预览"
        window.level = .floating
        window.delegate = self
        // Real container bounds, not `.zero`: a zero-frame web view never lays out or runs
        // script until something else resizes it, so the update entry would never be drawn.
        let webView = WKWebView(frame: window.contentView?.bounds ?? NSRect(x: 0, y: 0, width: 1100, height: 780),
                                 configuration: WKWebViewConfiguration())
        webView.autoresizingMask = [.width, .height]
        window.contentView?.addSubview(webView)
        webView.navigationDelegate = self
        self.window = window

        // The real bridge, pointed at this throwaway origin. A click still has to survive the
        // same main-frame and same-origin checks it would survive in the shipping app.
        let bridge = ConsoleUpdateBridge(webView: webView) { [weak self] in self?.server?.baseURL }
        bridge.onStateRequested = { [weak self] in self?.pushState() }
        bridge.onActionRequested = { [weak self] in
            self?.showPreviewOnlyNotice(version: self?.state.latestVersion ?? UpdatePreviewEnvironment.demoNewVersion)
        }
        self.bridge = bridge

        webView.load(URLRequest(url: baseURL))
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Pushes the demo state through the real bridge.
    ///
    /// Called both when a page asks and when a navigation finishes. The page's own request
    /// arrives during script evaluation, which is before `didFinish` — so answering only that
    /// request would mean answering into a document that is not ready yet, and answering only
    /// `didFinish` would miss a refresh that never re-asks. Doing both is what makes the entry
    /// reliably appear after a reload.
    private func pushState() {
        bridge?.push(state, currentVersion: state.currentVersion)
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        bridge?.consoleWillStartLoading()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Only a finished navigation at the throwaway console origin may become trusted, and
        // the push goes out immediately afterwards rather than waiting for the page to ask.
        guard bridge?.consoleDidFinishLoading() == true else { return }
        pushState()
        if let path = ProcessInfo.processInfo.environment["GODOX_PREVIEW_SNAPSHOT"], !path.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                webView.takeSnapshot(with: nil) { image, _ in
                    guard let tiff = image?.tiffRepresentation,
                          let bitmap = NSBitmapImageRep(data: tiff),
                          let png = bitmap.representation(using: .png, properties: [:]) else { return }
                    try? png.write(to: URL(fileURLWithPath: path), options: .atomic)
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        bridge?.consoleWillStartLoading()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        bridge?.consoleWillStartLoading()
    }

    // MARK: - Menu bar

    @objc private func statusItemClicked(_ sender: NSStatusBarButton) {
        guard NSApp.currentEvent?.type == .rightMouseUp else {
            toggleWindow()
            return
        }
        showContextMenu(sender)
    }

    /// The preview keeps the same shape as the shipping menu bar item, including the right-click
    /// menu.
    ///
    /// Without it the only way out is ⌘Q on a preview window whose close button merely hides
    /// it, which is exactly how a reviewer ends up with an undismissable menu bar item and no
    /// way to get on with the day. The demo update entry is here for the same reason: the thing
    /// being reviewed has to be clickable.
    private func showContextMenu(_ button: NSStatusBarButton) {
        let menu = NSMenu()
        let titleItem = NSMenuItem(title: "神牛引闪器 · 更新提醒效果预览", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        menu.addItem(titleItem)
        menu.addItem(NSMenuItem.separator())

        let updateItem = NSMenuItem(title: state.menuItemTitle, action: #selector(previewUpdateRequested), keyEquivalent: "u")
        updateItem.target = self
        menu.addItem(updateItem)

        let toggleItem = NSMenuItem(title: window?.isVisible == true ? "隐藏预览窗口" : "显示预览窗口",
                                    action: #selector(toggleWindow), keyEquivalent: "w")
        toggleItem.target = self
        menu.addItem(toggleItem)

        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: "退出效果预览", action: #selector(quitPreview), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        guard let statusItem = statusItem else { return }
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }

    @objc private func previewUpdateRequested() {
        showPreviewOnlyNotice(version: state.latestVersion ?? UpdatePreviewEnvironment.demoNewVersion)
    }

    /// Quits this preview bundle and nothing else. There is no backend and no device here, so
    /// there is nothing to shut down and nothing of the user's that could be touched.
    @objc private func quitPreview() {
        NSApp.terminate(nil)
    }

    @objc private func toggleWindow() {
        guard let window = window else { return }
        if window.isVisible {
            window.orderOut(nil)
        } else {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func showPreviewOnlyNotice(version: String) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "效果预览：这里不会下载或安装任何东西"
        alert.informativeText = """
        正式版里，点“更新到 v\(version)”会打开标准更新窗口；确认安装后自动下载、验证、安装并重启。

        这个预览没有启动更新器，也没有连接任何更新源，所以按钮只走到这一步为止。
        """
        alert.addButton(withTitle: "知道了")
        alert.runModal()
    }

    /// The console's own page, with the same substitutions the backend performs, plus a banner
    /// saying out loud that nothing here is real. The banner is added here rather than in
    /// `index.html`, so no preview wording can reach the product.
    static func consolePage() -> Data {
        guard let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "Console"),
              var page = try? String(contentsOf: url, encoding: .utf8) else { return Data() }
        page = page
            .replacingOccurrences(of: "__GODOX_APP_VERSION__", with: UpdatePreviewEnvironment.currentVersion)
            .replacingOccurrences(of: "__GODOX_INSTANCE_ID__", with: "update-preview")
            .replacingOccurrences(of: "__GODOX_THEME__", with: "system")
            .replacingOccurrences(of: "正在初始化...", with: "效果预览")
        guard let range = page.range(of: "</body>") else { return Data(page.utf8) }
        let banner = """
        <style>body { padding-top: 58px !important; }</style>
        <div id="godoxPreviewBanner" style="position:fixed;left:0;right:0;top:0;z-index:99999;padding:8px 14px;background:#7a4a06;color:#fff8eb;font:13px -apple-system,system-ui;text-align:center">效果预览 · 当前 \(UpdatePreviewEnvironment.currentVersion)，演示新版 \(UpdatePreviewEnvironment.demoNewVersion) · 不会下载或安装任何更新</div>

        """
        page.insert(contentsOf: banner, at: range.lowerBound)
        return Data(page.utf8)
    }
}

/// Closing the preview window hides it, exactly like the console window, so the menu bar item
/// and its right-click menu remain the way out — which is why the quit entry matters.
extension PreviewController: NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }
}

/// Serves one HTML page from an ephemeral loopback port, so the preview can be exercised
/// through the real origin checks instead of a loosened copy of them.
private final class LoopbackConsoleServer {
    private let page: Data
    private var listenDescriptor: Int32 = -1
    private(set) var baseURL: URL?

    init(consolePage: Data) {
        self.page = consolePage
        listen()
    }

    private func listen() {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return }
        var reuse: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0, Darwin.listen(descriptor, 8) == 0 else {
            close(descriptor)
            return
        }
        var actual = sockaddr_in()
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &actual) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
        }
        listenDescriptor = descriptor
        baseURL = URL(string: "http://127.0.0.1:" + String(UInt16(bigEndian: actual.sin_port)) + "/")
        Thread.detachNewThread { [weak self] in self?.serve() }
    }

    private func serve() {
        while listenDescriptor >= 0 {
            let client = accept(listenDescriptor, nil, nil)
            guard client >= 0 else { return }
            Thread.detachNewThread { [weak self] in self?.answer(client) }
        }
    }

    private func answer(_ client: Int32) {
        defer { close(client) }
        var request = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        let terminator = Data("\r\n\r\n".utf8)
        while request.range(of: terminator) == nil, request.count < 65536 {
            let read = recv(client, &buffer, buffer.count, 0)
            guard read > 0 else { break }
            request.append(contentsOf: buffer[0..<read])
        }
        let head = String(decoding: request.prefix(4096), as: UTF8.self)
        let path = head.split(separator: " ", maxSplits: 2).dropFirst().first.map(String.init) ?? "/"
        // Only the console document is served. There is no API here, so a stray call can only
        // ever get an empty page — never a route that pretends to be the backend.
        let isDocument = path == "/" || path.hasPrefix("/?")
        var response = isDocument
            ? "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: \(page.count)\r\nCache-Control: no-store, max-age=0\r\nConnection: close\r\n\r\n"
            : "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        var payload = Data(response.utf8)
        if isDocument { payload.append(page) }
        response = ""
        payload.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let written = send(client, raw.baseAddress!.advanced(by: offset), raw.count - offset, 0)
                guard written > 0 else { return }
                offset += written
            }
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
#endif