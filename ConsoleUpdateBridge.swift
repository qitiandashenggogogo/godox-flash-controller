import Foundation
import WebKit

/// The console's only route to the native update action.
///
/// Two things travel across this bridge, both in the page's main world and both refused by
/// `UpdateBridgePolicy` unless they come from the top-level document of the console origin
/// the shell is currently serving: the current update state, pushed in, and a request to start
/// the standard update flow, pushed out. Nothing else is accepted, and the handler never
/// trusts a name, a payload, or a remembered origin to decide that.
///
/// A plain browser session has no such handler and no push, so the console shows no native
/// button there — the entry is inert markup that only the shell ever reveals.
final class ConsoleUpdateBridge: NSObject, WKScriptMessageHandler {
    /// Injected by the shell. Returns the console origin right now, or nil while the backend
    /// is not serving. Read on every message rather than cached, because a backend restart
    /// moves the port and an old origin must stop being trusted immediately.
    var currentBaseURL: (() -> URL?)

    /// Called on the main thread when the console's own update button was pressed.
    var onActionRequested: (() -> Void)?

    /// Called on the main thread when a freshly loaded console asked what the update status
    /// is. A reload creates a new document that has never been told anything, so this is the
    /// path that keeps the entry correct after a refresh or a backend restart.
    var onStateRequested: (() -> Void)?

    private weak var webView: WKWebView?
    private(set) var isConsoleReady = false

    /// The origin this bridge is willing to talk to, learned from the last navigation that
    /// finished at the console. Nothing is pushed before one has, and the address is compared
    /// against the web view's own current URL on every push, so a navigation away from the
    /// console turns the push off again instead of injecting state into whatever is there now.
    private var trustedConsoleURL: URL?

    /// Whether the web view is currently showing the console origin at all.
    var isShowingTrustedConsole: Bool {
        UpdateBridgePolicy.isTrustedConsoleURL(webView?.url, trusted: currentBaseURL())
    }

    private static let stateSink = "__godoxApplyUpdateState"

    init(webView: WKWebView, currentBaseURL: @escaping () -> URL?) {
        self.webView = webView
        self.currentBaseURL = currentBaseURL
        super.init()
        let controller = webView.configuration.userContentController
        controller.add(self, name: UpdateBridgePolicy.stateRequestMessageName)
        controller.add(self, name: UpdateBridgePolicy.actionMessageName)
    }

    /// A navigation has begun, so whatever document was there is going away and the new one
    /// knows nothing. Ready goes false here — not at the end — because the outgoing document
    /// must not be able to ask for or receive anything on behalf of the incoming one.
    func consoleWillStartLoading() {
        isConsoleReady = false
    }

    /// The navigation finished: this is the point at which a fresh document needs the current
    /// state, because a reload creates a brand new page that has never been told anything.
    /// Re-sending here is what keeps a reloaded console from showing a stale or missing entry.
    ///
    /// Trust is re-derived here rather than remembered: only a finished navigation that is
    /// itself at the console origin makes the bridge ready. A page that finished loading
    /// somewhere else leaves it closed, which is why a stray `stateRequest` can never become
    /// the only thing that reveals the button.
    @discardableResult
    func consoleDidFinishLoading() -> Bool {
        guard let webView = webView else {
            isConsoleReady = false
            trustedConsoleURL = nil
            return false
        }
        guard let finished = webView.url,
              UpdateBridgePolicy.isTrustedConsoleURL(finished, trusted: currentBaseURL()) else {
            isConsoleReady = false
            trustedConsoleURL = nil
            return false
        }
        trustedConsoleURL = finished
        isConsoleReady = true
        return true
    }

    /// Sends the current state into the console. Safe to call before the page exists: the
    /// call is simply dropped, and the matching `consoleDidFinishLoading` re-sends it.
    ///
    /// Two independent gates, both of which must be open: the bridge must have finished a
    /// navigation at the console origin, and the web view must still be *on* that origin right
    /// now. A refresh that has started but not finished is not pushed into, and neither is a
    /// document that has navigated away.
    func push(_ state: UpdateState, currentVersion: String) {
        guard isConsoleReady, isShowingTrustedConsole, let webView = webView else { return }
        let payload: [String: Any] = [
            "available": state.latestVersion != nil,
            "actionable": state.isUpdateActionable,
            "currentVersion": currentVersion,
            "latestVersion": state.latestVersion ?? "",
            "indicatorVisible": state.showsIndicator,
            "title": state.consoleEntryTitle ?? "",
            "accessibleLabel": state.consoleEntryAccessibleLabel ?? ""
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("if (window.\(Self.stateSink)) { window.\(Self.stateSink)(\(json)); }")
    }

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let webView = webView, message.webView === webView else { return }
        guard UpdateBridgePolicy.acceptsMessageName(message.name) else { return }
        let frame = message.frameInfo
        let origin = frame.securityOrigin
        guard UpdateBridgePolicy.acceptsMessage(
            isMainFrame: frame.isMainFrame,
            originProtocol: origin.protocol,
            originHost: origin.host,
            originPort: origin.port,
            currentBaseURL: currentBaseURL()
        ) else { return }
        // Both accepted messages are requests, not commands carrying arguments: the native
        // side owns the state, so there is nothing a page could usefully pass in.
        switch message.name {
        case UpdateBridgePolicy.actionMessageName:
            onActionRequested?()
        case UpdateBridgePolicy.stateRequestMessageName:
            onStateRequested?()
        default:
            break
        }
    }
}
