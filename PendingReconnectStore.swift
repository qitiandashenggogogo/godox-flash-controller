import Foundation

/// A one-shot note written only when a real update relaunch is imminent, naming the exact
/// device that was connected at that moment.
///
/// It exists because a Sparkle relaunch replaces and restarts the bundle, and the new process
/// comes up with no device attached. Restoring the same address is convenient; scanning for
/// some other device would be a guess, and a test fire would be an action the user never
/// asked for, so neither happens here.
///
/// The note records *which two builds* the upgrade went between, and when. Without that, a
/// note left behind by an update that never actually installed — a cancelled authorisation, a
/// failed download, a quit that happened first — would reconnect the device on some ordinary
/// launch days later, which is an action nobody asked for and cannot be explained afterwards.
///
/// The note is deliberately its own file next to the backend lock rather than part of the
/// user configuration: consuming it deletes it, and that must never cost the user a setting.
final class PendingReconnectStore {
    static let fileName = "pending-reconnect-after-update.json"

    /// How long a note may sit unconsumed before it is treated as history rather than as
    /// "the upgrade that just happened". An update the user installed and then restarted at
    /// their own pace hours later still gets its restore; anything older is not honoured.
    static let maximumAge: TimeInterval = 60 * 60 * 12

    /// The exact device that was connected, plus the two builds and the time, written together
    /// or not at all. `recordedAt` is a machine-readable instant, kept alongside a human
    /// readable one so a note can be read without a decoder.
    struct Note: Equatable {
        let address: String
        /// The build that was running when the note was written.
        let sourceBuild: String
        /// The build this note expects the upgraded bundle to report.
        let targetBuild: String
        let recordedAt: Date

        var isPlausible: Bool {
            PendingReconnectStore.isPlausibleDeviceAddress(address)
                && !sourceBuild.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !targetBuild.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private let directory: URL
    private let fileManager: FileManager
    private let now: () -> Date
    private let maximumAge: TimeInterval

    init(directory: URL,
         fileManager: FileManager = .default,
         now: @escaping () -> Date = Date.init,
         maximumAge: TimeInterval = PendingReconnectStore.maximumAge) {
        self.directory = directory
        self.fileManager = fileManager
        self.now = now
        self.maximumAge = maximumAge
    }

    private var fileURL: URL { directory.appendingPathComponent(Self.fileName) }

    /// The directory the shell and its backend share, so this note lives exactly where the
    /// rest of this installation's runtime state lives and nowhere the user edits by hand.
    static func defaultDirectory(environment: [String: String] = ProcessInfo.processInfo.environment) -> URL {
        if let configured = environment["GODOX_CONTROLLER_STATE_DIR"], !configured.isEmpty {
            return URL(fileURLWithPath: configured, isDirectory: true)
        }
        let home = environment["HOME"].map { URL(fileURLWithPath: $0) }
            ?? URL(fileURLWithPath: NSHomeDirectory())
        return home.appendingPathComponent("Library/Application Support/Godox Controller", isDirectory: true)
    }

    /// Whether a usable note is waiting. Used to tell "restoring after the update we just
    /// installed" from an ordinary launch, which must never connect by itself.
    var hasPendingRestore: Bool { readNote() != nil }

    /// Records the device to reconnect to after the update restarts. Only called from the
    /// updater's pre-relaunch path, never on a normal quit.
    ///
    /// A blank or implausible address is refused rather than stored, so a bad value can never
    /// turn into a connection attempt against an unknown target.
    @discardableResult
    func record(address: String, sourceBuild: String, targetBuild: String) -> Bool {
        let note = Note(address: address.trimmingCharacters(in: .whitespacesAndNewlines),
                        sourceBuild: sourceBuild,
                        targetBuild: targetBuild,
                        recordedAt: now())
        guard note.isPlausible else { return false }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let formatter = ISO8601DateFormatter()
            let payload: [String: Any] = [
                "address": note.address,
                "source_build": note.sourceBuild,
                "target_build": note.targetBuild,
                "recorded_at": formatter.string(from: note.recordedAt),
                "recorded_at_local": formatter.string(from: note.recordedAt)
            ]
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            let temporary = directory.appendingPathComponent("." + Self.fileName + "." + String(getpid()) + ".tmp")
            try data.write(to: temporary, options: .atomic)
            _ = try fileManager.replaceItemAt(fileURL, withItemAt: temporary)
            return true
        } catch {
            // A note that cannot be written only costs the convenience of reconnecting.
            return false
        }
    }

    /// Reads the note and deletes it in one step, so the restore happens at most once no
    /// matter how many times the app is launched afterwards.
    ///
    /// The note is only honoured when this bundle really is the upgrade the note was written
    /// for: the running build must equal the target, must differ from the source (an unchanged
    /// build means no upgrade happened, whatever the note claims) and the note must still be
    /// fresh. A note that fails any of those is deleted rather than kept, so it cannot come
    /// back on some later launch.
    func consume(currentBuild: String, at instant: Date? = nil) -> Note? {
        guard let note = readNote() else { return nil }
        clear()
        guard Self.noteIsHonourable(note, currentBuild: currentBuild, now: instant ?? now(), maximumAge: maximumAge)
        else { return nil }
        return note
    }

    /// The whole admission rule, as a function, so it can be checked without a file.
    static func noteIsHonourable(_ note: Note,
                                currentBuild: String,
                                now: Date,
                                maximumAge: TimeInterval) -> Bool {
        guard note.isPlausible else { return false }
        let build = currentBuild.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !build.isEmpty else { return false }
        // This bundle is not the one the update was installing: somebody else's note.
        guard build == note.targetBuild.trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
        // The build did not actually change, so nothing was upgraded and there is nothing to
        // restore. This is the case that stops a stale note from connecting on a normal launch.
        guard build != note.sourceBuild.trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
        let age = now.timeIntervalSince(note.recordedAt)
        guard age >= 0, age <= maximumAge else { return false }
        return true
    }

    /// Removes any note without using it. Called on an ordinary quit, and whenever an update
    /// attempt failed or was cancelled, so a later launch is never treated as an update restore.
    func clear() {
        try? fileManager.removeItem(at: fileURL)
    }

    private func readNote() -> Note? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        guard let address = object["address"] as? String,
              let sourceBuild = object["source_build"] as? String,
              let targetBuild = object["target_build"] as? String,
              let recordedAtText = object["recorded_at"] as? String,
              let recordedAt = ISO8601DateFormatter().date(from: recordedAtText)
        else { return nil }
        let note = Note(address: address.trimmingCharacters(in: .whitespacesAndNewlines),
                        sourceBuild: sourceBuild.trimmingCharacters(in: .whitespacesAndNewlines),
                        targetBuild: targetBuild.trimmingCharacters(in: .whitespacesAndNewlines),
                        recordedAt: recordedAt)
        return note.isPlausible ? note : nil
    }

    /// A remembered address is not proof of a live connection.
    static func connectedAddress(in status: [String: Any]?) -> String? {
        guard status?["connected"] as? Bool == true,
              let address = status?["device_address"] as? String,
              isPlausibleDeviceAddress(address) else { return nil }
        return address.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// CoreBluetooth hands macOS peripherals a UUID, and some stacks a colon- or dash-separated
    /// MAC; nothing else is ever a device address.
    ///
    /// Both forms are matched whole, and a minimum length is required, because "any run of hex
    /// digits" also accepts a single `a` — which is not an address, and would let a corrupted or
    /// hand-edited note become a request to connect to an arbitrary target.
    static func isPlausibleDeviceAddress(_ address: String) -> Bool {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 64 else { return false }

        // Canonical CoreBluetooth UUID: 8-4-4-4-12 hex digits.
        let uuidGroups = [8, 4, 4, 4, 12]
        if isHyphenatedUUID(trimmed, groups: uuidGroups, separator: "-") { return true }
        // Some stacks hand out a 32 digit unseparated UUID.
        if trimmed.count == 32, allHex(trimmed) { return true }

        // MAC: six octets, colon or dash separated. Some stacks report eight, for a
        // Bluetooth device address that includes the two extra bytes; both are accepted, and
        // nothing shorter than six octets ever is.
        let macGroups = [2, 2, 2, 2, 2, 2, 2, 2]
        if trimmed.contains(":"), isHyphenatedUUID(trimmed, groups: [2, 2, 2, 2, 2, 2], separator: ":") { return true }
        if trimmed.contains("-") {
            if isHyphenatedUUID(trimmed, groups: [2, 2, 2, 2, 2, 2], separator: "-") { return true }
            if trimmed.filter({ $0 == "-" }).count == 7,
               isHyphenatedUUID(trimmed, groups: macGroups, separator: "-") { return true }
        }
        return false
    }

    private static func allHex(_ text: String) -> Bool {
        !text.isEmpty && text.allSatisfy { $0.isHexDigit && $0.isASCII }
    }

    private static func isHyphenatedUUID(_ text: String, groups: [Int], separator: Character) -> Bool {
        let parts = text.split(omittingEmptySubsequences: false, whereSeparator: { $0 == separator })
        guard parts.count == groups.count else { return false }
        for (index, part) in parts.enumerated() {
            guard part.count == groups[index] else { return false }
            guard allHex(String(part)) else { return false }
        }
        return true
    }
}

/// The one-shot decision "may this launch reconnect, and to what".
///
/// Separate from the store so the "exactly once, and only for a real update" rule can be
/// exercised directly. A launch with no note never connects. A launch whose bundle does not
/// match the note never connects. A launch where the backend is not up yet leaves the note
/// alone instead of burning it, so a slow start cannot silently cost the user the restore.
/// A second call in the same launch always returns nil.
final class PostUpdateRestorePlan {
    private(set) var hasRestoredThisLaunch = false
    private(set) var lastRefusal: String?

    func addressToReconnect(store: PendingReconnectStore,
                            currentBuild: String,
                            backendIsReady: Bool,
                            now: Date? = nil) -> String? {
        guard !hasRestoredThisLaunch else { lastRefusal = "alreadyRestored"; return nil }
        guard backendIsReady else { lastRefusal = "backendNotReady"; return nil }
        guard store.hasPendingRestore else { lastRefusal = "noNote"; return nil }
        guard let note = store.consume(currentBuild: currentBuild, at: now) else {
            lastRefusal = "noteNotHonourable"
            return nil
        }
        hasRestoredThisLaunch = true
        return note.address
    }
}