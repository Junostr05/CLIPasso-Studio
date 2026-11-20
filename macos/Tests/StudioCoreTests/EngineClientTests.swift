import Foundation
import Testing
@testable import StudioCore

/// The engine process as the Mac app runs it: started, asked, listened to – and started again after a crash.
@Suite(.serialized) struct EngineClientTests {
    static var repoRoot: URL {
        URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    static func fake(_ mode: String, _ n: Int = 0) -> EngineLaunch {
        let script = Bundle.module.url(forResource: "fake_engine", withExtension: "py")!
        return EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                            arguments: ["python3", script.path, mode, String(n)])
    }

    static let quick = RestartPolicy(delays: [.milliseconds(20)], maxCrashes: 3, window: .seconds(120))

    @Test func helloAndRequest() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        #expect(await engine.state == .running)
        let answer = try await engine.request("ping", ["x": 1])
        #expect(answer == ["op": "ping", "args": ["x": 1]])
        await engine.stop()
        #expect(await engine.state == .stopped)
    }

    @Test func engineErrorsComeBackAsFailures() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        await #expect(throws: EngineFailure(code: "busy", message: "a job is already running")) {
            try await engine.request("fail")
        }
        await engine.stop()
    }

    @Test func eventsArriveInOrder() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        let answer = try await engine.request("events", ["n": 500])
        #expect(answer == ["sent": 500])
        var seen: [Int] = []
        for await event in engine.events {
            if event.kind == "iteration", let it = event.data["it"]?.intValue { seen.append(it) }
            if seen.count == 500 { break }
        }
        #expect(seen == Array(0..<500))
        await engine.stop()
    }

    @Test func garbageLineIsReportedNotFatal() async throws {
        let engine = EngineClient(launch: Self.fake("garbage"))
        try await engine.start()
        #expect(try await engine.request("ping") == ["op": "ping", "args": [:]])
        var garbage: EngineEvent?
        for await event in engine.events where event.kind == "engine_garbage" {
            garbage = event
            break
        }
        #expect(garbage?.data["line"] == "this is not json")
        await engine.stop()
    }

    @Test func hugeLineArrivesWhole() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        let answer = try await engine.request("huge")
        #expect(answer.objectValue?["blob"]?.stringValue?.count == 8 * 1024 * 1024)
        await engine.stop()
    }

    @Test func aRequestTimesOut() async throws {
        let engine = EngineClient(launch: Self.fake("slow"))
        await #expect(throws: EngineFailure.self) { try await engine.start(timeout: .milliseconds(300)) }
        await engine.stop()
    }

    @Test func anotherProtocolIsRefused() async throws {
        let engine = EngineClient(launch: Self.fake("protocol2"))
        await #expect(throws: EngineFailure(code: "protocol", message: "the engine speaks protocol 2, not 1")) {
            try await engine.start()
        }
        await engine.stop()
    }

    @Test func crashEndsPendingRequestsAndRestarts() async throws {
        let engine = EngineClient(launch: Self.fake("crash_after", 2), policy: Self.quick)
        try await engine.start()  // hello: 1
        _ = try await engine.request("ping")  // 2
        await #expect(throws: EngineFailure.self) { try await engine.request("ping") }  // the engine ends
        var exit: EngineEvent?
        for await event in engine.events where event.kind == "engine_exit" {
            exit = event
            break
        }
        #expect(exit?.data["code"] == .int(3) && exit?.data["crashed"] == .bool(true))
        try await engine.waitUntilRunning(timeout: .seconds(20))
        #expect(try await engine.request("ping") == ["op": "ping", "args": [:]])  // the new one
        await engine.stop()
    }

    @Test func threeCrashesIn120sFail() async throws {
        let engine = EngineClient(launch: Self.fake("crash_after", 1), policy: Self.quick)
        try await engine.start()
        for _ in 0..<3 {
            _ = try? await engine.request("ping")
            try? await engine.waitUntilRunning(timeout: .seconds(20))
        }
        var state = await engine.state
        let deadline = ContinuousClock.now + .seconds(20)
        while case .restarting = state, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(50))
            state = await engine.state
        }
        guard case .failed = state else {
            Issue.record("still \(state) after three crashes")
            return
        }
        await engine.stop()
    }

    @Test func startingTwiceKeepsOneProcess() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        let pid = try #require(await engine.processIdentifier)
        await #expect(throws: EngineFailure(code: "already_running", message: "the engine already runs")) {
            try await engine.start()
        }
        let after = await engine.processIdentifier
        let state = await engine.state
        #expect(after == pid && kill(pid, 0) == 0 && state == .running)
        await engine.stop()
    }

    @Test func stopEndsTheProcess() async throws {
        let engine = EngineClient(launch: Self.fake("echo"))
        try await engine.start()
        let pid = try #require(await engine.processIdentifier)
        await engine.stop()
        #expect(kill(pid, 0) != 0)  // gone
        await #expect(throws: EngineFailure.self) { try await engine.request("ping") }
    }

    @Test func secretsNeverReachTheLog() async throws {
        let engine = EngineClient(launch: Self.fake("stderr_secret"))
        try await engine.start()
        _ = try await engine.request("ping")
        try await Task.sleep(for: .milliseconds(200))
        let tail = await engine.stderrTail()
        #expect(tail.contains("a normal log line"))
        #expect(!tail.joined().contains("SECRET123"))
        await engine.stop()
    }

    @Test func realHeadlessHello() async throws {
        let launch = EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                                  arguments: ["python3", "-m", "clipasso_studio.headless"],
                                  environment: ["PYTHONPATH": Self.repoRoot.path, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"],
                                  workingDirectory: Self.repoRoot)
        let engine = EngineClient(launch: launch)
        try await engine.start()
        let schema = try await engine.request("schema")
        #expect(schema.objectValue?["format"] == .int(1))
        await engine.stop()
    }
}
