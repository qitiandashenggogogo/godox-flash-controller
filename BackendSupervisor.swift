import Foundation
import Darwin

/// All mutable lifecycle state lives on the main queue; process and network I/O do not.
final class BackendSupervisor {
    enum State { case stopped, starting, ready, stopping, failed }
    struct Ready: Decodable {
        let protocolVersion: Int
        let port: Int
        let instanceId: String
        let nonce: String
        let pid: Int
    }
    private(set) var state: State = .stopped
    private(set) var baseURL: URL?
    private(set) var instanceID: String?
    var onReady: ((URL) -> Void)?
    var onFailure: ((String) -> Void)?
    private var process: Process?
    private var control: Pipe?
    private var generation = 0
    private var healthRevision = 0
    private var diagnostics = ""
    private var healthTask: URLSessionDataTask?
    private var stoppingCompletion: (() -> Void)?
    private var pendingFailure: String?
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2
        config.connectionProxyDictionary = ["HTTPEnable": 0, "HTTPSEnable": 0, "SOCKSEnable": 0]
        return URLSession(configuration: config)
    }()

    /// The .app that owns this shell, or nil for development runs.
    ///
    /// Bundle.main.bundleURL is already the .app itself when launched from one, so it must
    /// not lose another path component: stripping it yields the containing folder, whose
    /// extension is never "app". The bundle URL is passed in so the resolution stays a pure
    /// function the supervisor harness can exercise without a real bundle.
    static func hostAppBundlePath(bundleURL: URL) -> String? {
        let standardized = bundleURL.standardizedFileURL
        guard standardized.pathExtension == "app" else { return nil }
        return standardized.path
    }

    func refresh(executable: URL, arguments: [String], directory: URL) {
        if state == .failed && process?.isRunning == true { return }
        switch state {
        case .starting, .stopping: return
        case .ready:
            if process?.isRunning == true { verify(generation, remaining: 1); return }
        case .stopped, .failed: break
        }
        start(executable: executable, arguments: arguments, directory: directory)
    }

    private func start(executable: URL, arguments: [String], directory: URL) {
        generation += 1
        let current = generation
        let nonce = UUID().uuidString
        state = .starting
        baseURL = nil
        instanceID = nil
        diagnostics = ""
        pendingFailure = nil
        let child = Process()
        let output = Pipe(), errors = Pipe(), input = Pipe()
        child.executableURL = executable
        child.arguments = arguments + ["--managed"]
        child.currentDirectoryURL = directory
        var environment = ProcessInfo.processInfo.environment
        environment["GODOX_STARTUP_NONCE"] = nonce
        environment["PYTHONUNBUFFERED"] = "1"
        // Only ever the real .app, never its parent directory. The backend uses this to
        // report which bundle owns it; it is a diagnostic input, not a trust decision.
        if let hostApp = Self.hostAppBundlePath(bundleURL: Bundle.main.bundleURL) {
            environment["GODOX_APP_BUNDLE_PATH"] = hostApp
        }
        child.environment = environment
        child.standardOutput = output
        child.standardError = errors
        child.standardInput = input
        process = child
        control = input
        child.terminationHandler = { [weak self] child in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                guard let self = self, current == self.generation else { return }
                self.healthTask?.cancel()
                self.baseURL = nil
                self.instanceID = nil
                self.control?.fileHandleForWriting.closeFile()
                self.control = nil
                self.process = nil
                if self.state == .stopping {
                    self.state = .stopped
                    let completion = self.stoppingCompletion
                    self.stoppingCompletion = nil
                    completion?()
                } else {
                    self.state = .failed
                    let cause = self.pendingFailure ?? "控制台后端已退出（状态 " + String(child.terminationStatus) + "）。"
                    self.onFailure?(cause + (self.diagnostics.isEmpty ? "" : String(UnicodeScalar(10)!) + self.diagnostics))
                }
            }
        }
        // Blocking reads stay on separate background queues; stderr is always drained.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            while true {
                let data = errors.fileHandleForReading.availableData
                if data.isEmpty { break }
                let chunk = String(decoding: data, as: UTF8.self)
                DispatchQueue.main.async {
                    guard let self = self, current == self.generation else { return }
                    self.diagnostics = String((self.diagnostics + chunk).suffix(4000))
                }
            }
            errors.fileHandleForReading.closeFile()
        }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var buffer = Data()
            var announced = false
            while true {
                let chunk = output.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                if buffer.count > 16384 {
                    DispatchQueue.main.async { self?.fail("后端就绪信息超过长度限制。", generation: current) }
                    break
                }
                while let end = buffer.firstIndex(of: 10) {
                    let line = Data(buffer[..<end])
                    buffer.removeSubrange(...end)
                    guard !announced else { continue }
                    let prefix = Data("GODOX_READY ".utf8)
                    guard line.starts(with: prefix) else {
                        DispatchQueue.main.async { self?.fail("后端就绪信息格式错误。", generation: current) }
                        announced = true
                        continue
                    }
                    let decoder = JSONDecoder()
                    decoder.keyDecodingStrategy = .convertFromSnakeCase
                    guard let ready = try? decoder.decode(Ready.self, from: line.dropFirst(prefix.count)),
                          ready.protocolVersion == 1, (1...65535).contains(ready.port),
                          ready.nonce == nonce, !ready.instanceId.isEmpty else {
                        DispatchQueue.main.async { self?.fail("后端就绪信息或实例身份无效。", generation: current) }
                        announced = true
                        continue
                    }
                    announced = true
                    DispatchQueue.main.async {
                        guard let self = self, current == self.generation, self.state == .starting else { return }
                        self.baseURL = URL(string: "http://127.0.0.1:" + String(ready.port) + "/")
                        self.instanceID = ready.instanceId
                        self.verify(current, remaining: 5)
                    }
                }
            }
            output.fileHandleForReading.closeFile()
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                try child.run()
                input.fileHandleForReading.closeFile()
                output.fileHandleForWriting.closeFile()
                errors.fileHandleForWriting.closeFile()
            } catch {
                input.fileHandleForReading.closeFile()
                output.fileHandleForWriting.closeFile()
                errors.fileHandleForWriting.closeFile()
                DispatchQueue.main.async {
                    guard let self = self, current == self.generation else { return }
                    self.process = nil
                    self.fail("无法启动控制台后端：" + error.localizedDescription, generation: current)
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self = self, current == self.generation, self.state == .starting else { return }
            self.fail("后端启动超时，请刷新重试。", generation: current)
        }
    }

    private func verify(_ current: Int, remaining: Int) {
        guard current == generation, let url = baseURL, let identity = instanceID else { return }
        healthRevision += 1
        let revision = healthRevision
        healthTask?.cancel()
        healthTask = session.dataTask(with: url.appendingPathComponent("api/health")) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self, current == self.generation, revision == self.healthRevision,
                      self.state == .starting || self.state == .ready else { return }
                let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
                if error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
                   json?["app"] as? String == "godox-controller", json?["instance_id"] as? String == identity,
                   json?["protocol_version"] as? Int == 1, self.process?.isRunning == true {
                    self.state = .ready
                    self.onReady?(url)
                } else if remaining > 1 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                        self.verify(current, remaining: remaining - 1)
                    }
                } else if self.state == .ready {
                    self.onFailure?("无法连接当前控制台后端，请稍后刷新重试。")
                } else {
                    self.fail("后端已启动，但健康检查或实例身份校验失败。", generation: current)
                }
            }
        }
        healthTask?.resume()
    }

    private func fail(_ detail: String, generation current: Int) {
        guard current == generation, state == .starting else { return }
        pendingFailure = detail
        if process?.isRunning == true {
            control?.fileHandleForWriting.closeFile()
            process?.terminate()
            state = .failed
            onFailure?(detail)
            killIfStillRunning(current)
        } else {
            state = .failed
            control?.fileHandleForWriting.closeFile()
            control = nil
            onFailure?(detail)
        }
    }

    private func killIfStillRunning(_ current: Int) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self = self, current == self.generation, let child = self.process, child.isRunning else { return }
            // Only the still-running Process object we launched; never a port owner.
            kill(child.processIdentifier, SIGKILL)
        }
    }

    func shutdown(_ completion: @escaping () -> Void) {
        healthTask?.cancel()
        state = .stopping
        stoppingCompletion = completion
        control?.fileHandleForWriting.closeFile()
        if let child = process, child.isRunning {
            let current = generation
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                guard let self = self, self.generation == current, self.state == .stopping, child.isRunning else { return }
                child.terminate()
            }
            killIfStillRunning(generation)
        } else {
            state = .stopped
            stoppingCompletion = nil
            completion()
        }
    }

    func post(_ path: String, completion: @escaping (Bool) -> Void) {
        guard state == .ready, let url = baseURL, let identity = instanceID else { completion(false); return }
        let current = generation
        var request = URLRequest(url: url.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue(identity, forHTTPHeaderField: "X-Godox-Instance")
        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self, current == self.generation, self.state == .ready,
                      self.instanceID == identity else { return }
                let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
                completion(error == nil && (response as? HTTPURLResponse)?.statusCode == 200 && json?["success"] as? Bool == true)
            }
        }.resume()
    }
}
