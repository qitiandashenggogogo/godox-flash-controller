import Foundation

/// Drives the pure update core from Python so the dot lifecycle, the console bridge policy and
/// the post-update restore rule can be exercised against the shipping code rather than a
/// re-implementation of it. Compiled from the production sources with no AppKit and no
/// Sparkle, which is the point: none of what is tested here needs a window, a menu bar, a
/// network or a feed, and a change that quietly moved that boundary would fail the build.
@main
struct UpdateCoreHarness {
    static func main() {
        let directory = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : NSTemporaryDirectory()
        let model = UpdateStateModel(currentVersion: "1.6.1")
        let store = PendingReconnectStore(directory: URL(fileURLWithPath: directory, isDirectory: true))

        func emit(_ payload: [String: Any]) {
            let data = try! JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            FileHandle.standardOutput.write(data + Data([10]))
        }

        func describe(_ state: UpdateState) -> [String: Any] {
            [
                "availability": String(describing: state.availability),
                "showsIndicator": state.showsIndicator,
                "latestVersion": state.latestVersion ?? NSNull(),
                "isUpdateActionable": state.isUpdateActionable,
                "menuItemTitle": state.menuItemTitle,
                "consoleEntryTitle": state.consoleEntryTitle ?? NSNull(),
                "consoleEntryAccessibleLabel": state.consoleEntryAccessibleLabel ?? NSNull(),
                "accessibilityDescription": state.accessibilityDescription,
                "currentVersion": state.currentVersion
            ]
        }

        func event(_ name: String) -> UpdateEvent? {
            switch name {
            case "started": return .started(currentVersion: "1.6.1")
            case "updateFound": return .updateFound(version: "1.6.2")
            case "noUpdateFound": return .noUpdateFound
            case "install": return .choiceMade(.install)
            case "later": return .choiceMade(.later)
            case "skip": return .choiceMade(.skip)
            case "cancel": return .choiceMade(.cancel)
            case "sessionWillFinish": return .sessionWillFinish
            case "aborted": return .aborted
            case "relaunching": return .relaunching
            default: return nil
            }
        }

        while let line = readLine() {
            let parts = line.split(separator: " ", omittingEmptySubsequences: false).map(String.init)
            guard let command = parts.first else { continue }

            switch command {
            case "names":
                emit([
                    "event": "names",
                    "stateRequest": UpdateBridgePolicy.stateRequestMessageName,
                    "action": UpdateBridgePolicy.actionMessageName,
                    "allowedHost": UpdateBridgePolicy.allowedHost,
                    "stateSink": "__godoxApplyUpdateState"
                ])

            case "state":
                // state <event> [event...]
                var changes: [Bool] = []
                for name in parts.dropFirst() {
                    guard let step = event(name) else { emit(["event": "error", "detail": "unknown event " + name]); break }
                    changes.append(model.apply(step))
                }
                emit(["event": "state", "state": describe(model.state), "changed": changes])

            case "reset":
                _ = model.apply(.relaunching)
                emit(["event": "state", "state": describe(model.state)])

            case "bridge":
                // bridge <mainFrame 0|1> <protocol|-> <host|-> <port|-> <baseURL|->
                guard parts.count == 6 else { emit(["event": "error", "detail": "bridge needs 5 arguments"]); break }
                let base = parts[5] == "-" ? nil : URL(string: parts[5])
                let accepted = UpdateBridgePolicy.acceptsMessage(
                    isMainFrame: parts[1] == "1",
                    originProtocol: parts[2] == "-" ? nil : parts[2],
                    originHost: parts[3] == "-" ? nil : parts[3],
                    originPort: Int(parts[4]) ?? -1,
                    currentBaseURL: base
                )
                emit(["event": "bridge", "accepted": accepted])

            case "bridgeName":
                guard parts.count == 2 else { emit(["event": "error", "detail": "bridgeName needs 1 argument"]); break }
                emit(["event": "bridgeName", "accepted": UpdateBridgePolicy.acceptsMessageName(parts[1])])

            case "trustedURL":
                // trustedURL <candidate|-> <trusted|->
                guard parts.count == 3 else { emit(["event": "error", "detail": "trustedURL needs 2 arguments"]); break }
                emit(["event": "trustedURL", "accepted": UpdateBridgePolicy.isTrustedConsoleURL(
                    parts[1] == "-" ? nil : URL(string: parts[1]),
                    trusted: parts[2] == "-" ? nil : URL(string: parts[2]))])

            case "record":
                // record <address> [sourceBuild] [targetBuild]
                guard parts.count >= 2 else { emit(["event": "error", "detail": "record needs 1 argument"]); break }
                let source = parts.count > 2 ? parts[2] : "7"
                let target = parts.count > 3 ? parts[3] : "8"
                emit(["event": "record", "recorded": store.record(address: parts[1], sourceBuild: source, targetBuild: target)])

            case "plausible":
                guard parts.count == 2 else { emit(["event": "error", "detail": "plausible needs 1 argument"]); break }
                emit(["event": "plausible", "accepted": PendingReconnectStore.isPlausibleDeviceAddress(parts[1])])

            case "hasPending":
                emit(["event": "hasPending", "value": store.hasPendingRestore])

            case "consume":
                emit(["event": "consume", "value": store.consume(currentBuild: parts.count > 1 ? parts[1] : "8")?.address ?? NSNull()])

            case "clear":
                store.clear()
                emit(["event": "clear", "value": store.hasPendingRestore])

            case "restorePlan":
                // restorePlan <1|0 backendReady> [currentBuild] [now] — each call is a separate launch
                let plan = PostUpdateRestorePlan()
                let backendReady = parts.count > 1 && parts[1] == "1"
                let currentBuild = parts.count > 2 ? parts[2] : "8"
                var instant: Date? = nil
                if parts.count > 3, let seconds = Double(parts[3]) {
                    instant = Date(timeIntervalSince1970: seconds)
                }
                let value = plan.addressToReconnect(store: store,
                                                   currentBuild: currentBuild,
                                                   backendIsReady: backendReady,
                                                   now: instant)
                emit(["event": "restorePlan", "value": value ?? NSNull(), "refusal": plan.lastRefusal ?? NSNull()])

            case "honourable":
                // honourable <source> <target> <currentBuild> <nowEpoch> <ageSeconds>
                guard parts.count == 6 else { emit(["event": "error", "detail": "honourable needs 5 arguments"]); break }
                let note = PendingReconnectStore.Note(address: "AA:BB:CC:DD:EE:FF",
                                                      sourceBuild: parts[1],
                                                      targetBuild: parts[2],
                                                      recordedAt: Date(timeIntervalSince1970: Double(parts[4]) ?? 0))
                let age = Double(parts[5]) ?? 0
                emit(["event": "honourable",
                      "accepted": PendingReconnectStore.noteIsHonourable(
                        note,
                        currentBuild: parts[3],
                        now: Date(timeIntervalSince1970: (Double(parts[4]) ?? 0) + age),
                        maximumAge: PendingReconnectStore.maximumAge)])

            default:
                emit(["event": "error", "detail": "unknown command " + command])
            }
        }
    }
}
