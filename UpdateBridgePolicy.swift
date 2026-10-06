import Foundation

/// Decides whether a message from inside the console web view is allowed to drive the
/// native update action.
///
/// This is a pure function of the frame facts, with no WebKit types in the signature, so the
/// exact same rules the shipping handler applies can be driven by tests without a web view.
/// The handler in `ConsoleUpdateBridge.swift` does nothing but unpack `WKMessage` into these
/// arguments and call this — there is no second, laxer copy of the rule anywhere.
///
/// The bar is deliberately narrow: the console is served from a loopback origin that the
/// shell itself starts, so the only legitimate caller is the top-level document of exactly
/// that origin. An iframe, a subframe, a different loopback port (a stale backend from a
/// previous launch), and a remote origin are all rejected. Without this, any page the user
/// happened to open in that web view could install a signed update.
enum UpdateBridgePolicy {
    /// The loopback host the shell's own backend is always bound to.
    static let allowedHost = "127.0.0.1"

    /// Message name a page uses to ask for the current update state.
    static let stateRequestMessageName = "godoxUpdateStateRequest"

    /// Message name a page uses to ask the shell to start the standard update flow.
    static let actionMessageName = "godoxUpdateAction"

    /// Whether a frame may drive the native update action at all.
    ///
    /// - Parameters:
    ///   - isMainFrame: `WKFrameInfo.isMainFrame`. Subframes (including same-origin iframes)
    ///     are refused even when the origin matches, because a page that embeds content must
    ///     not be able to borrow the shell's authority.
    ///   - originProtocol: the frame's security origin scheme; must be `http`.
    ///   - originHost: the frame's security origin host; must be this loopback address.
    ///   - originPort: the frame's security origin port; must equal the current backend's.
    ///   - currentBaseURL: the URL the shell currently believes is its own console, or nil
    ///     when the backend is not ready. A message is never accepted on the strength of a
    ///     remembered origin.
    static func acceptsMessage(
        isMainFrame: Bool,
        originProtocol: String?,
        originHost: String?,
        originPort: Int,
        currentBaseURL: URL?
    ) -> Bool {
        guard isMainFrame, let base = currentBaseURL else { return false }
        guard let scheme = base.scheme?.lowercased(), scheme == "http" else { return false }
        guard let host = base.host?.lowercased(), host == allowedHost else { return false }
        let port = base.port ?? 80
        guard port > 0 else { return false }
        guard originProtocol?.lowercased() == "http" else { return false }
        guard originHost?.lowercased() == host else { return false }
        return originPort == port
    }

    /// Whether a URL is the console origin, and nothing else.
    ///
    /// Used to decide whether it is safe to hand the page anything at all. Scheme, host and
    /// port must all match: a page the user navigated to, an iframe, a document from a
    /// different loopback port left over from a previous backend, and the console served over
    /// anything but loopback HTTP are each refused before a single byte is injected.
    static func isTrustedConsoleURL(_ candidate: URL?, trusted: URL?) -> Bool {
        guard let candidate = candidate, let trusted = trusted else { return false }
        guard let scheme = candidate.scheme?.lowercased(), scheme == "http" else { return false }
        guard let trustedScheme = trusted.scheme?.lowercased(), trustedScheme == "http" else { return false }
        guard let host = candidate.host?.lowercased(), host == allowedHost else { return false }
        guard let trustedHost = trusted.host?.lowercased(), trustedHost == host else { return false }
        let candidatePort = candidate.port ?? 80
        let trustedPort = trusted.port ?? 80
        guard candidatePort > 0, candidatePort == trustedPort else { return false }
        return true
    }

    /// Whether a message name is one the page is allowed to send. Unknown names are refused
    /// rather than ignored, so a future typo fails closed.
    static func acceptsMessageName(_ name: String) -> Bool {
        name == stateRequestMessageName || name == actionMessageName
    }
}
