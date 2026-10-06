import AppKit
import Foundation
import Sparkle

/// The one place Sparkle is spoken to.
///
/// Sparkle keeps doing all of the actual work: fetching the appcast, comparing versions,
/// downloading, verifying the EdDSA signature, installing, and restarting. Nothing here
/// re-implements any of it, and there is no second scheduler — this adapter exists only to
/// translate Sparkle's callbacks into `UpdateEvent`s and to route user-initiated checks into
/// the standard update window.
///
/// The gentle reminder is Sparkle's own mechanism, not a custom one. Declaring
/// `supportsGentleScheduledUpdateReminders` and declining to let the standard user driver
/// show a scheduled update means a background check that finds a new version produces no
/// window, no focus steal, and no interruption to somebody who is mid-set; it produces one
/// dot on the menu bar icon. A check the user asked for still goes to the standard Sparkle UI
/// unchanged, which is the only moment an update window is appropriate.
///
/// The user's own update-check preferences are never written. `automaticallyChecksForUpdates`
/// and `automaticallyDownloadsUpdates` are read by Sparkle from the user's defaults, and this
/// class only ever reads them; setting either at launch would silently override a choice the
/// user made on purpose.
@MainActor
final class UpdateCoordinator: NSObject {
    let model: UpdateStateModel

    /// Called on the main thread whenever the visible state changed.
    var onStateChange: ((UpdateState) -> Void)?

    /// Asked, just before Sparkle restarts the app, to note the device that was connected.
    /// `targetBuild` is the `CFBundleVersion` of the item Sparkle is about to install, straight
    /// from the appcast, so the shell can stamp the note with the build the upgraded bundle is
    /// expected to report. The given completion must be invoked once the work is done or has
    /// definitively failed; the coordinator also enforces its own deadline so a stuck note can
    /// never wedge the install the user already approved.
    var onRelaunchPreparing: ((_ targetBuild: String, _ done: @escaping () -> Void) -> Void)?

    /// Called on the main thread when a preparation that had already started turned out not to
    /// be happening after all — the user put the update off, or the attempt failed. Whatever
    /// the shell wrote in the meantime has to go.
    var onRelaunchAbandoned: (() -> Void)?

    /// The user's deliberate request to look at updates. Always answered with the standard
    /// Sparkle window, whether or not anything is known to be pending.
    var onUserRequestedCheck: ((UpdateActionController) -> Void)?

    private var controller: UpdateActionController?
    private var startupError: Error?

    /// The menu item's action target. Set by the shell so the context menu can keep using
    /// Sparkle's own `checkForUpdates:` and its own `canCheckForUpdates` validation.
    var updaterController: UpdateActionController? { controller }

    private let relaunchPreparationDeadline: TimeInterval

    /// Whether Sparkle has asked us to prepare and has not yet been told the update is off.
    ///
    /// This is the only fact that may protect the post-update marker across a quit. Sparkle
    /// does not terminate the app behind our back — `SPUUserDriver.h:233` says a quit event is
    /// sent to the running application before the install, so `applicationShouldTerminate`
    /// really does run during an update, and a marker cleared there would be lost every time.
    /// Nothing about it may be inferred from "the app is quitting", only from this flag.
    private(set) var isRelaunchImminent = false

    /// Bumped on every new preparation attempt and on every cancellation or failure, so a
    /// slow answer from the backend cannot write a marker for an update that is no longer
    /// happening.
    private(set) var relaunchPreparationToken = 0

    /// The build the in-flight update is installing, empty when no preparation is running.
    private(set) var pendingTargetBuild = ""

    init(currentVersion: String, relaunchPreparationDeadline: TimeInterval = 3) {
        self.model = UpdateStateModel(currentVersion: currentVersion)
        self.relaunchPreparationDeadline = relaunchPreparationDeadline
        super.init()
    }

    var state: UpdateState { model.state }

    /// Creates and starts the updater. Called from `applicationDidFinishLaunching` rather than
    /// from `init`, because Sparkle needs a launched application before it schedules anything.
    func start() {
        guard controller == nil else { return }
        do {
            controller = try UpdateActionController(updaterDelegate: self, userDriverDelegate: self)
        } catch {
            startupError = error
            if model.apply(.aborted) { onStateChange?(model.state) }
            return
        }
        model.apply(.started(currentVersion: model.state.currentVersion))
    }

    /// The console's update button, and the context menu item when a version is known.
    ///
    /// This is the only way this class ever starts a check, and it is only ever called because
    /// the user asked. Background scheduling stays entirely with Sparkle.
    func userRequestedUpdate() {
        guard let controller = controller else {
            if let error = startupError { NSAlert(error: error).runModal() }
            return
        }
        onUserRequestedCheck?(controller)
    }

    // MARK: - Sparkle events

    /// The one rule for every "there is nothing to install" report Sparkle can send.
    ///
    /// Three of its callbacks mean that (`updaterDidNotFindUpdate:`, `updaterDidNotFindUpdate:error:`
    /// and `didAbortWithError:` carrying `SUNoUpdateError`). Only the reasons that say the user
    /// is genuinely on the newest build may become `.noUpdateFound`; "the feed has something
    /// this Mac cannot install" and "we were not told why" both fall through to `.aborted`, so
    /// a missing reason can never quietly upgrade itself into a claim of being current.
    static nonisolated func noUpdateEvent(forNoUpdateError error: Error) -> UpdateEvent {
        let info = (error as NSError).userInfo
        let rawReason = (info[SPUNoUpdateFoundReasonKey] as? NSNumber)?.int32Value
            ?? (info[SPUNoUpdateFoundReasonKey] as? SPUNoUpdateFoundReason)?.rawValue
        guard let rawReason = rawReason, let reason = SPUNoUpdateFoundReason(rawValue: rawReason) else {
            return .aborted
        }
        switch reason {
        case .onLatestVersion, .onNewerThanLatestVersion:
            // `.onNewerThanLatestVersion` is the user running a build newer than anything the
            // feed publishes, which is still "nothing newer for you".
            return .noUpdateFound
        case .systemIsTooOld, .systemIsTooNew, .hardwareDoesNotSupportARM64, .unknown:
            return .aborted
        @unknown default:
            return .aborted
        }
    }

    /// Any event that proves the relaunch is not going to happen. Used to invalidate a pending
    /// preparation and to release the marker before a later ordinary quit.
    static func isCancellation(of event: UpdateEvent) -> Bool {
        switch event {
        case .aborted: return true
        case .choiceMade(.install): return false
        case .choiceMade: return true
        default: return false
        }
    }

    private nonisolated func record(_ event: UpdateEvent) {
        // Sparkle's updater and user driver both document main-thread callbacks, and the
        // controller is main-actor bound. One hop makes that a guarantee rather than a
        // convention, and it costs nothing when the caller was already on the main thread.
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            if Self.isCancellation(of: event) {
                let wasImminent = self.isRelaunchImminent
                self.isRelaunchImminent = false
                self.pendingTargetBuild = ""
                self.relaunchPreparationToken &+= 1
                // A preparation that was in flight when the update fell over left a note that
                // will never be spent by an upgrade. The shell is told so it can delete it
                // now rather than leaving it to sit there until the next quit.
                if wasImminent { self.onRelaunchAbandoned?() }
            }
            if self.model.apply(event) { self.onStateChange?(self.model.state) }
        }
    }

    /// Marks the state stale and then gives the shell a bounded chance to finish preparing
    /// before Sparkle restarts the app. `prepare` is the install handler Sparkle is waiting on.
    private nonisolated func prepareThenRelaunch(targetBuild: String, _ prepare: @escaping () -> Void) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else {
                prepare()
                return
            }
            if self.model.apply(.relaunching) { self.onStateChange?(self.model.state) }
            guard let onRelaunchPreparing = self.onRelaunchPreparing else {
                prepare()
                return
            }
            self.isRelaunchImminent = true
            self.pendingTargetBuild = targetBuild
            self.relaunchPreparationToken &+= 1
            let attemptToken = self.relaunchPreparationToken
            var finished = false
            let done: () -> Void = {
                guard !finished else { return }
                finished = true
                guard self.isRelaunchImminent, self.relaunchPreparationToken == attemptToken else { return }
                // A late status response after the deadline must not recreate a marker.
                self.relaunchPreparationToken &+= 1
                prepare()
            }
            onRelaunchPreparing(targetBuild, done)
            // A note that never answers must not hold the install the user already approved
            // hostage, so the deadline releases Sparkle even if the shell is stuck.
            DispatchQueue.main.asyncAfter(deadline: .now() + self.relaunchPreparationDeadline) { done() }
        }
    }
}

// MARK: - SPUUpdaterDelegate

extension UpdateCoordinator: SPUUpdaterDelegate {
    nonisolated func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        record(.updateFound(version: item.displayVersionString))
    }

    /// `SPUUpdaterDelegate.h:202` — the argument-less form. Sparkle only reaches it when the
    /// `error:`-carrying form below is *not* implemented, so it is a fallback, not a second
    /// report of the same check: whoever gets called, exactly one of the two runs.
    nonisolated func updaterDidNotFindUpdate(_ updater: SPUUpdater) {
        record(.noUpdateFound)
    }

    /// `SPUUpdaterDelegate.h:191` — the same news with the reason attached, and the reason is
    /// the whole point: "no valid new update" covers both "you are on the newest one" and "the
    /// feed has something you cannot install". Only the first may ever be reported as up to
    /// date; the second must not be dressed up as a verdict, and an absent or unknown reason
    /// is treated as the second, because guessing "you are current" is the dangerous direction.
    nonisolated func updaterDidNotFindUpdate(_ updater: SPUUpdater, error: Error) {
        record(Self.noUpdateEvent(forNoUpdateError: error))
    }

    /// `SPUUpdaterDelegate.h:455` — `updater:didAbortWithError:`, the updater *and* the error.
    ///
    /// `SUNoUpdateError` is 1001 (`SUErrors.h:41`) and Sparkle delivers it here too, so an
    /// error callback arriving after `updaterDidNotFindUpdate` is the normal shape of a check
    /// that found nothing. Turning that into `.failed` would overwrite a correct up-to-date
    /// with a false failure, so 1001 is mapped onto the same event the other two report.
    nonisolated func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        let nsError = error as NSError
        if nsError.domain == SUSparkleErrorDomain, nsError.code == Int(SUError.noUpdateError.rawValue) {
            record(Self.noUpdateEvent(forNoUpdateError: error))
            return
        }
        if nsError.domain == SUSparkleErrorDomain,
           nsError.code == Int(SUError.installationCanceledError.rawValue) {
            // The user refused to authorise the install. That is a decision, not a malfunction,
            // so it settles like a dismissal instead of claiming the check went wrong.
            record(.choiceMade(.cancel))
            return
        }
        record(.aborted)
    }

    nonisolated func updater(_ updater: SPUUpdater, userDidMake choice: SPUUserUpdateChoice,
                              forUpdate updateItem: SUAppcastItem, state: SPUUserUpdateState) {
        let mapped: UserUpdateChoice
        switch choice {
        case .install: mapped = .install
        case .dismiss: mapped = .later
        case .skip: mapped = .skip
        @unknown default: mapped = .cancel
        }
        record(.choiceMade(mapped))
    }

    nonisolated func updaterWillRelaunchApplication(_ updater: SPUUpdater) {
        record(.relaunching)
    }

    nonisolated func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                             untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        // Sparkle's documented hook for work that must finish before the app restarts. The
        // answer is only ever delivered on the main thread, so asking the shell for the
        // connected device here — while the backend is still alive — is the one point where
        // that is reliable.
        //
        // `item.versionString` is the CFBundleVersion of the very item being installed, which is
        // exactly what the post-update note has to be stamped with.
        prepareThenRelaunch(targetBuild: item.versionString, installHandler)
        return true
    }
}

// MARK: - SPUStandardUserDriverDelegate

extension UpdateCoordinator: SPUStandardUserDriverDelegate {
    /// Declaring this is what makes the gentle reminder path legal. Returning false from
    /// `standardUserDriverShouldHandleShowingScheduledUpdate` below is what keeps the standard
    /// window closed for background discoveries.
    ///
    /// `SPUStandardUserDriverDelegate.h:102` declares it as `@property (nonatomic, readonly)
    /// BOOL`, so in Swift it is a get-only property and not a `func ... -> Bool`. A method of
    /// that name would satisfy nothing and the delegate probe would report `false`, which is
    /// exactly what it did before this was corrected.
    nonisolated var supportsGentleScheduledUpdateReminders: Bool { true }

    nonisolated func standardUserDriverShouldHandleShowingScheduledUpdate(_ update: SUAppcastItem,
                                                                          andInImmediateFocus immediateFocus: Bool) -> Bool {
        // No side effects here, exactly as Sparkle requires, and no window: the dot is the
        // reminder. `immediateFocus` is irrelevant to us because we never focus anything.
        false
    }

    nonisolated func standardUserDriverWillHandleShowingUpdate(_ handleShowingUpdate: Bool,
                                                               forUpdate update: SUAppcastItem,
                                                               state: SPUUserUpdateState) {
        // A user-initiated check always lets the standard driver show the update, so
        // `handleShowingUpdate` is true there and the window itself is the reminder; the dot
        // has already been lit by `didFindValidUpdate` and needs nothing more.
        //
        // When it is false, this is the gentle reminder firing — including the case of a
        // version the user put off earlier, which Sparkle re-reminds about later. That is the
        // only event that brings a deferred update back, since `didFindValidUpdate` fires once
        // per discovery and the appcast stays cached afterwards.
        guard !handleShowingUpdate else { return }
        record(.updateFound(version: update.displayVersionString))
    }

    nonisolated func standardUserDriverDidReceiveUserAttention(forUpdate update: SUAppcastItem) {
        record(.choiceMade(.cancel))
    }

    nonisolated func standardUserDriverWillFinishUpdateSession() {
        record(.sessionWillFinish)
    }
}


/// Uses Sparkle's standard windows and installer. Only the last confirmation is omitted
/// after the user has explicitly chosen Install in the standard update alert.
@MainActor
final class UpdateActionController {
    let updater: SPUUpdater
    private let userDriver: ConsentedInstallUserDriver

    init(updaterDelegate: SPUUpdaterDelegate, userDriverDelegate: SPUStandardUserDriverDelegate) throws {
        let driver = ConsentedInstallUserDriver(hostBundle: .main, delegate: userDriverDelegate)
        userDriver = driver
        updater = SPUUpdater(hostBundle: .main, applicationBundle: .main, userDriver: driver, delegate: updaterDelegate)
        try updater.start()
    }

    func checkForUpdates(_ sender: Any?) { updater.checkForUpdates() }
}

/// Consent belongs to this update session and is consumed once at the ready stage.
final class UpdateInstallConsent {
    private var approved = false
    func reset() { approved = false }
    func record(_ choice: UserUpdateChoice) { approved = choice == .install }
    func consume() -> Bool {
        let result = approved
        reset()
        return result
    }
}

@MainActor
final class ConsentedInstallUserDriver: SPUStandardUserDriver {
    private let consent = UpdateInstallConsent()

    override func showUpdateFound(with item: SUAppcastItem, state: SPUUserUpdateState,
                                  reply: @escaping (SPUUserUpdateChoice) -> Void) {
        consent.reset()
        super.showUpdateFound(with: item, state: state) { [weak self] choice in
            self?.consent.record(choice == .install ? .install : .cancel)
            reply(choice)
        }
    }

    // Sparkle imports this callback as an async convenience in Swift. Export the official
    // Objective-C protocol selector to implement its callback form without swizzling.
    @objc(showReadyToInstallAndRelaunch:)
    func readyForConsentedInstall(_ reply: @escaping (SPUUserUpdateChoice) -> Void) {
        guard consent.consume() else {
            Task { reply(await super.showReadyToInstallAndRelaunch()) }
            return
        }
        reply(.install)
    }

    override func dismissUpdateInstallation() {
        consent.reset()
        super.dismissUpdateInstallation()
    }
}
