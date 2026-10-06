import Foundation

@main
struct SupervisorHarness {
    static func main() {
        let backend = BackendSupervisor()
        let executable = URL(fileURLWithPath: CommandLine.arguments[1])
        let directory = URL(fileURLWithPath: CommandLine.arguments[2])
        let arguments = Array(CommandLine.arguments.dropFirst(3))
        func emit(_ payload: [String: Any]) {
            let data = try! JSONSerialization.data(withJSONObject: payload)
            FileHandle.standardOutput.write(data + Data([10]))
        }
        backend.onReady = { url in emit(["event": "ready", "url": url.absoluteString, "instance_id": backend.instanceID!]) }
        backend.onFailure = { detail in emit(["event": "failed", "detail": detail]) }
        func refresh() { backend.refresh(executable: executable, arguments: arguments, directory: directory) }
        DispatchQueue.main.async { refresh() }
        DispatchQueue.global().async {
            while let command = readLine() {
                DispatchQueue.main.async {
                    if command == "refresh" { for _ in 0..<10 { refresh() } }
                    if command == "quit" { backend.shutdown { exit(0) } }
                    if command.hasPrefix("hostapp ") {
                        let candidate = String(command.dropFirst("hostapp ".count))
                        let resolved = BackendSupervisor.hostAppBundlePath(bundleURL: URL(fileURLWithPath: candidate))
                        emit(["event": "host_app_bundle_path", "input": candidate, "value": resolved ?? NSNull()])
                    }
                }
            }
            DispatchQueue.main.async { backend.shutdown { exit(0) } }
        }
        dispatchMain()
    }
}
