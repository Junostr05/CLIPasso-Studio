import Foundation

/// How the engine process is started: in the app the bundled Python with `-m clipasso_studio.headless`.
public struct EngineLaunch: Sendable, Hashable {
    public var executable: URL
    public var arguments: [String]
    /// nil: this process's environment
    public var environment: [String: String]?
    public var workingDirectory: URL?

    public init(executable: URL, arguments: [String], environment: [String: String]? = nil,
                workingDirectory: URL? = nil)
    {
        self.executable = executable
        self.arguments = arguments
        self.environment = environment
        self.workingDirectory = workingDirectory
    }
}

/// An event of the engine – the engine's own (`iteration`, `preview`, `seed_done`, `job_done` …, fields as in
/// engine/pipeline.py) or one of this client's: `engine_exit` {code, crashed} when the process ended, `engine_garbage`
/// {line} for a line that was not the protocol.
public struct EngineEvent: Sendable, Hashable {
    public let kind: String
    public let job: String?
    public let data: JSONObject

    public init(kind: String, job: String? = nil, data: JSONObject = [:]) {
        self.kind = kind
        self.job = job
        self.data = data
    }
}

/// A request that did not succeed: the engine's own codes (`busy`, `no_job`, `not_found`, `bad_request`, …) or this
/// client's (`engine_gone`, `timeout`, `protocol`).
public struct EngineFailure: Error, Sendable, Hashable, CustomStringConvertible {
    public let code: String
    public let message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }

    public var description: String { "\(code): \(message)" }
}

public enum EngineState: Sendable, Hashable {
    case stopped
    case starting
    case running
    /// after a crash, waiting to start again (the attempt within the policy's window)
    case restarting(attempt: Int)
    /// too many crashes, or it could not be started
    case failed(String)
}

/// What a job queue needs of the engine (EngineClient; a fake in tests).
public protocol EngineControlling: Actor {
    nonisolated var events: AsyncStream<EngineEvent> { get }
    func request(_ op: String, _ args: JSONObject, timeout: Duration) async throws -> JSONValue
}

extension EngineControlling {
    public func request(_ op: String, _ args: JSONObject = [:]) async throws -> JSONValue {
        try await request(op, args, timeout: .seconds(120))
    }
}
