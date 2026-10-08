import Foundation

/// What the shell is allowed to claim about updates, and the exact rules for turning that
/// into what the user sees.
///
/// Everything here is a pure value transformation: no Sparkle types, no AppKit, no I/O, no
/// timers. The menu bar dot, the context menu item and the console button are all derived
/// from the same `UpdateState`, so those three surfaces cannot disagree with each other.
///
/// A state can only become `.available` by being handed a version string that came out of
/// a real update check, so there is no code path that lights the dot for a version nobody
/// published. Conversely, "up to date" is only ever reached by an explicit "checked and
/// found nothing" event, never by inference, so a deferred or failed update can never be
/// silently reported as installed.
enum UpdateAvailability: Equatable {
    /// No check has produced a verdict yet. Nothing is claimed in either direction.
    case unchecked
    /// The most recent completed check found nothing newer than what is running.
    case upToDate
    /// A real check found a newer version. This is the only state that lights the dot.
    case available(version: String)
    /// The user put the update off, or Sparkle deferred it. A newer version is still known,
    /// so the entry points keep working, but the dot is gone: nothing new was just discovered.
    case later(version: String)
    /// Download / signature verification / install is under way; Sparkle shows its own UI.
    case installing(version: String)
    /// The last attempt failed. No version claim is made and no dot is shown.
    case failed
}

/// Events the updater layer reports, in the shell's own vocabulary.
///
/// Sparkle's own types never reach the state model, so the model can be driven directly by
/// tests and the adapter that maps Sparkle callbacks onto these cases stays small enough to
/// read in one sitting.
enum UpdateEvent: Equatable {
    case started(currentVersion: String)
    /// Sparkle found a genuinely newer version; `version` is the string it read from the feed.
    /// Also used when Sparkle re-reminds about a version the user put off, which is the one
    /// moment a deferred update legitimately becomes a live reminder again.
    case updateFound(version: String)
    /// A real check completed and found nothing newer than what is running.
    case noUpdateFound
    case choiceMade(UserUpdateChoice)
    /// Sparkle is about to close its update session (dismissed, skipped, cancelled, or an error).
    case sessionWillFinish
    case aborted
    /// Sparkle is relaunching the app. Everything learned before this is about a bundle that
    /// is being replaced, so it is dropped rather than carried into the new process.
    case relaunching
}

/// The user's decision, named without depending on `SPUUserUpdateChoice`.
enum UserUpdateChoice: Equatable {
    case install
    case later
    case skip
    case cancel
}

struct UpdateState: Equatable {
    let currentVersion: String
    let availability: UpdateAvailability

    /// The newest version this process actually knows about, or nil when there is none.
    ///
    /// Survives "later" and "installing" on purpose: the console and menu entry points
    /// stay available for the rest of the session, which is what makes putting an update off
    /// reversible without ever claiming the update already happened.
    var latestVersion: String? {
        switch availability {
        case .available(let version), .later(let version), .installing(let version):
            return version
        case .unchecked, .upToDate, .failed:
            return nil
        }
    }

    /// Only a live discovery lights the dot. Deferred, installing and failed states must not,
    /// or the dot would keep claiming "new version" after the user already dealt with it.
    var showsIndicator: Bool {
        if case .available = availability { return true }
        return false
    }

    /// True when the user can be sent into the standard Sparkle update flow.
    var isUpdateActionable: Bool { latestVersion != nil }

    /// What VoiceOver reads and what the tooltip shows. The discovered version is named here
    /// so the reminder is useful without sight.
    var accessibilityDescription: String {
        switch availability {
        case .available(let version):
            return "发现新版 v\(version)"
        case .later(let version), .installing(let version):
            return "有可用新版 v\(version)"
        case .unchecked:
            return "引闪控制台 v\(currentVersion)，尚未检查更新"
        case .upToDate:
            return "引闪控制台，已是最新版 v\(currentVersion)"
        case .failed:
            return "引闪控制台 v\(currentVersion)，上次检查未成功"
        }
    }

    /// The context menu item. Without a known version it stays the original plain action, so
    /// the menu is identical to before whenever there is nothing to update to.
    var menuItemTitle: String {
        guard let latest = latestVersion else { return "检查更新…" }
        return "更新到 v\(latest)…"
    }

    /// The console button label, or nil when there is nothing to offer.
    var consoleEntryTitle: String? {
        guard let latest = latestVersion else { return nil }
        return "更新到 v\(latest)"
    }

    var consoleEntryAccessibleLabel: String? {
        guard let latest = latestVersion else { return nil }
        return "更新到 v\(latest)"
    }
}

/// The whole update lifecycle as one reducer.
///
/// Kept separate from the Sparkle adapter and from AppKit on purpose: the dot's behaviour is
/// the part most likely to be got wrong, and here it is decided by a function that can be
/// exercised without a network, a feed, a window or a menu bar.
final class UpdateStateModel {
    private(set) var state: UpdateState

    /// Called after every event with the new state and whether anything visible changed.
    var onChange: ((UpdateState, Bool) -> Void)?

    init(currentVersion: String) {
        state = UpdateState(currentVersion: currentVersion, availability: .unchecked)
    }

    var latestVersion: String? { state.latestVersion }
    var showsIndicator: Bool { state.showsIndicator }

    @discardableResult
    func apply(_ event: UpdateEvent) -> Bool {
        let before = state
        state = UpdateState(currentVersion: before.currentVersion, availability: reduced(before.availability, event))
        let changed = state != before
        if changed { onChange?(state, true) }
        return changed
    }

    private func reduced(_ availability: UpdateAvailability, _ event: UpdateEvent) -> UpdateAvailability {
        switch event {
        case .started:
            return .unchecked
        case .updateFound(let version):
            return .available(version: version)
        case .noUpdateFound:
            // Only a real "nothing newer" result clears the dot this way. A version that is
            // merely deferred is not up to date, and saying so would be a false claim.
            return .upToDate
        case .choiceMade(let choice):
            switch choice {
            case .install:
                return availability.latestVersion.map { UpdateAvailability.installing(version: $0) } ?? .failed
            case .later:
                return availability.latestVersion.map { UpdateAvailability.later(version: $0) } ?? .failed
            case .skip, .cancel:
                // Sparkle will not remind again for a skipped version, so the dot is
                // dropped, but the version stays known and the entry points keep working.
                return availability.latestVersion.map { UpdateAvailability.later(version: $0) } ?? .failed
            }
        case .sessionWillFinish:
            // Covers a session closed without any choice being reported (the window's close
            // button) and sessions closed by an error. Either way the reminder is over.
            switch availability {
            case .available(let version), .later(let version):
                return .later(version: version)
            case .installing(let version):
                return .installing(version: version)
            case .unchecked, .upToDate, .failed:
                return availability
            }
        case .aborted:
            return .failed
        case .relaunching:
            // The new process re-reads its own bundle and re-checks; carrying this discovery
            // over would describe a bundle that no longer exists.
            return .unchecked
        }
    }
}

private extension UpdateAvailability {
    var latestVersion: String? {
        switch self {
        case .available(let version), .later(let version), .installing(let version):
            return version
        case .unchecked, .upToDate, .failed:
            return nil
        }
    }
}
