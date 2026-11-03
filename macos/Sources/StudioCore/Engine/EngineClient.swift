import Foundation

/// The engine process (`python -m clipasso_studio.headless`): started, asked in JSON lines, listened to – and
/// started again after a crash (RestartPolicy). Requests wait for their answer (by id); events go to `events` in the
/// order the engine wrote them. When the process ends, open requests fail with `engine_gone` and an `engine_exit`
/// event says whether it crashed – a job it ran can be continued from its folder.
public actor EngineClient: EngineControlling {
    public nonisolated let events: AsyncStream<EngineEvent>
    private let sink: AsyncStream<EngineEvent>.Continuation
    public let launch: EngineLaunch
    public let policy: RestartPolicy
    public private(set) var state: EngineState = .stopped

    private struct Running {
        let process: Process
        let stdin: FileHandle
        let generation: Int
        var reader: LineReader = LineReader()
        var outEnded = false
        var exitCode: Int32?
    }

    private enum Chunk: Sendable {
        case out(Data), err(Data), outEnd, exit(Int32)
    }

    private var running: Running?
    private var generation = 0
    private var nextID = 0
    private var pending: [Int: CheckedContinuation<JSONValue, any Error>] = [:]
    private var crashes: [ContinuousClock.Instant] = []
    private var log = LogTail(capacity: 2000)
    private var stopping = false

    private static let ignoreBrokenPipe: Void = {
        signal(SIGPIPE, SIG_IGN)  // a write to an engine that just ended fails instead of ending this process
    }()

    public init(launch: EngineLaunch, policy: RestartPolicy = .standard) {
        _ = Self.ignoreBrokenPipe
        self.launch = launch
        self.policy = policy
        (events, sink) = AsyncStream<EngineEvent>.makeStream()
    }

    public var processIdentifier: Int32? { running?.process.processIdentifier }

    public func stderrTail() -> [String] { log.lines }

    // MARK: - starting and stopping

    /// Start the engine and greet it: it must speak this package's protocol.
    public func start(timeout: Duration = .seconds(120)) async throws {
        stopping = false
        crashes = []
        state = .starting
        do {
            try launchProcess()
            try await handshake(timeout: timeout)
        } catch {
            state = .failed(String(describing: error))
            throw error
        }
    }

    private func handshake(timeout: Duration) async throws {
        let hello = try await send("hello", [:], timeout: timeout)
        let version = hello.objectValue?["protocol"]?.intValue
        guard version == StudioCore.protocolVersion else {
            throw EngineFailure(code: "protocol", message: "the engine speaks protocol "
                + (version.map(String.init) ?? "?") + ", not \(StudioCore.protocolVersion)")
        }
        state = .running
    }

    private func launchProcess() throws {
        generation += 1
        let gen = generation
        let process = Process()
        process.executableURL = launch.executable
        process.arguments = launch.arguments
        if let environment = launch.environment { process.environment = environment }
        if let dir = launch.workingDirectory { process.currentDirectoryURL = dir }
        let input = Pipe(), output = Pipe(), errors = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
        let (chunks, feed) = AsyncStream<Chunk>.makeStream()
        output.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                feed.yield(.outEnd)
            } else {
                feed.yield(.out(data))
            }
        }
        errors.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil } else { feed.yield(.err(data)) }
        }
        process.terminationHandler = { p in
            feed.yield(.exit(p.terminationStatus))
        }
        try process.run()
        running = Running(process: process, stdin: input.fileHandleForWriting, generation: gen)
        Task { [weak self] in
            for await chunk in chunks {
                guard let self else { return }
                if await self.handle(chunk, generation: gen) { break }
            }
            feed.finish()
        }
    }

    /// Stop the engine: `shutdown` (its job is marked interrupted), then SIGTERM after 5 s, SIGKILL after 5 more.
    public func stop() async {
        stopping = true
        guard let current = running else {
            state = .stopped
            return
        }
        if current.process.isRunning {
            _ = try? await send("shutdown", [:], timeout: .seconds(5))
            try? current.stdin.close()
            if !(await waitForExit(current.process, .seconds(5))) {
                current.process.terminate()
                if !(await waitForExit(current.process, .seconds(5))) {
                    kill(current.process.processIdentifier, SIGKILL)
                }
            }
        }
        let deadline = ContinuousClock.now + .seconds(5)
        while running?.generation == current.generation, ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(10))
        }
        running = nil
        state = .stopped
    }

    private func waitForExit(_ process: Process, _ limit: Duration) async -> Bool {
        let deadline = ContinuousClock.now + limit
        while process.isRunning, ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(20))
        }
        return !process.isRunning
    }

    /// Wait until the engine runs (after a start or a restart); fails when it stopped or gave up.
    public func waitUntilRunning(timeout: Duration) async throws {
        let deadline = ContinuousClock.now + timeout
        while true {
            switch state {
            case .running: return
            case .failed(let why): throw EngineFailure(code: "engine_failed", message: why)
            case .stopped: throw EngineFailure(code: "engine_gone", message: "the engine is stopped")
            case .starting, .restarting: break
            }
            guard ContinuousClock.now < deadline else {
                throw EngineFailure(code: "timeout", message: "the engine did not start in time")
            }
            try await Task.sleep(for: .milliseconds(20))
        }
    }

    // MARK: - requests

    public func request(_ op: String, _ args: JSONObject = [:], timeout: Duration = .seconds(120)) async throws
        -> JSONValue
    {
        guard state == .running else {
            throw EngineFailure(code: "engine_gone", message: "the engine is not running (\(state))")
        }
        return try await send(op, args, timeout: timeout)
    }

    private func send(_ op: String, _ args: JSONObject, timeout: Duration) async throws -> JSONValue {
        guard let current = running, current.process.isRunning else {
            throw EngineFailure(code: "engine_gone", message: "the engine is not running")
        }
        nextID += 1
        let id = nextID
        let line = PyJSON.dump(["id": .int(id), "op": .string(op), "args": .object(args)]) + "\n"
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<JSONValue, any Error>) in
            pending[id] = continuation
            do {
                try current.stdin.write(contentsOf: Data(line.utf8))
            } catch {
                pending[id] = nil
                continuation.resume(throwing: EngineFailure(code: "engine_gone", message: "could not write: \(error)"))
                return
            }
            Task { [weak self] in
                try? await Task.sleep(for: timeout)
                await self?.timeOut(id, op)
            }
        }
    }

    private func timeOut(_ id: Int, _ op: String) {
        pending.removeValue(forKey: id)?.resume(throwing: EngineFailure(code: "timeout",
                                                                        message: "no answer to \(op) in time"))
    }

    // MARK: - what the engine writes

    /// Returns true when this process is over (its stream can end).
    private func handle(_ chunk: Chunk, generation gen: Int) -> Bool {
        guard var current = running, current.generation == gen else { return true }
        switch chunk {
        case .out(let data):
            let lines = current.reader.append(data)
            running = current
            for line in lines {
                received(line)
            }
            return false
        case .err(let data):
            log.append(data)
            return false
        case .outEnd:
            current.outEnded = true
        case .exit(let code):
            current.exitCode = code
        }
        running = current
        guard current.outEnded, let code = current.exitCode else { return false }
        ended(code)
        return true
    }

    private func received(_ line: Data) {
        guard !line.isEmpty else { return }
        guard let value = try? PyJSON.parse(line), let o = value.objectValue else {
            garbage(line)
            return
        }
        if let kind = o["event"]?.stringValue {
            sink.yield(EngineEvent(kind: kind, job: o["job"]?.stringValue, data: o["data"]?.objectValue ?? [:]))
        } else if let ok = o["ok"]?.boolValue {
            guard let id = o["id"]?.intValue, let continuation = pending.removeValue(forKey: id) else {
                log.append(Data("an answer to no open request: \(String(decoding: line.prefix(500), as: UTF8.self))\n".utf8))
                return
            }
            if ok {
                continuation.resume(returning: o["result"] ?? .null)
            } else {
                let error = o["error"]?.objectValue ?? [:]
                continuation.resume(throwing: EngineFailure(code: error["code"]?.stringValue ?? "error",
                                                            message: error["message"]?.stringValue ?? ""))
            }
        } else {
            garbage(line)
        }
    }

    private func garbage(_ line: Data) {
        let text = String(decoding: line.prefix(200), as: UTF8.self)
        log.append(Data("not the protocol: \(text)\n".utf8))
        sink.yield(EngineEvent(kind: "engine_garbage", data: ["line": .string(text)]))
    }

    private func ended(_ code: Int32) {
        running = nil
        for (_, continuation) in pending {
            continuation.resume(throwing: EngineFailure(code: "engine_gone", message: "the engine ended (exit code \(code))"))
        }
        pending = [:]
        let crashed = !stopping
        sink.yield(EngineEvent(kind: "engine_exit", data: ["code": .int(Int(code)), "crashed": .bool(crashed)]))
        guard crashed else {
            state = .stopped
            return
        }
        let now = ContinuousClock.now
        crashes = crashes.filter { now - $0 < policy.window } + [now]
        if crashes.count >= policy.maxCrashes {
            state = .failed("the engine ended \(crashes.count) times within \(policy.window) – last exit code \(code)")
            return
        }
        let attempt = crashes.count
        state = .restarting(attempt: attempt)
        let delay = policy.delay(attempt: attempt)
        Task { [weak self] in
            try? await Task.sleep(for: delay)
            await self?.restart(attempt: attempt)
        }
    }

    private func restart(attempt: Int) async {
        guard !stopping, state == .restarting(attempt: attempt) else { return }
        do {
            try launchProcess()
            try await handshake(timeout: .seconds(120))
        } catch {
            if running == nil, case .restarting = state {
                return  // it ended again: ended() decided what comes next
            }
            state = .failed("the engine could not be started again: \(error)")
        }
    }
}
