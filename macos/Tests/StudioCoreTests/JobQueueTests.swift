import Foundation
import Testing
@testable import StudioCore

/// A stand-in for the engine: it notes the requests, answers them, and sends the events a test gives it.
actor FakeEngine: EngineControlling {
    nonisolated let events: AsyncStream<EngineEvent>
    private let sink: AsyncStream<EngineEvent>.Continuation
    private(set) var requests: [(op: String, args: JSONObject)] = []
    private var started = 0
    let root: URL
    /// send the new job's first event before answering "start" (the answer and the events can arrive in either order)
    var eventsBeforeAnswer = false

    func setEventsBeforeAnswer(_ on: Bool) { eventsBeforeAnswer = on }

    init(root: URL) {
        self.root = root
        (events, sink) = AsyncStream<EngineEvent>.makeStream()
    }

    func request(_ op: String, _ args: JSONObject, timeout: Duration) async throws -> JSONValue {
        requests.append((op, args))
        switch op {
        case "start":
            started += 1
            let dir = args["resume_dir"]?.stringValue ?? root.appending(path: "job\(started)").path
            try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            try Data(#"{"status": "running", "seeds": [0]}"#.utf8).write(to: URL(filePath: dir).appending(path: "job_state.json"))
            if eventsBeforeAnswer {
                sink.yield(EngineEvent(kind: "job_start", job: "j\(started)", data: ["seeds": [0, 1000]]))
                try await Task.sleep(for: .milliseconds(50))  // the event reaches the queue first
            }
            return ["job": .string("j\(started)"), "job_dir": .string(dir)]
        case "pause": return ["paused": true]
        case "resume", "cancel": return ["paused": false]
        default: throw EngineFailure(code: "unknown_op", message: op)
        }
    }

    func emit(_ kind: String, job: String = "j1", _ data: JSONObject = [:]) {
        sink.yield(EngineEvent(kind: kind, job: job, data: data))
    }

    func ops() -> [String] { requests.map(\.op) }
}

@Suite struct JobQueueTests {
    static func setUp() throws -> (FakeEngine, JobQueue, URL) {
        let root = FileManager.default.temporaryDirectory.appending(path: "queue-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let engine = FakeEngine(root: root)
        return (engine, JobQueue(engine: engine, outputRoot: root.appending(path: "out")), root)
    }

    static let settings: JSONObject = ["method": "clipasso", "num_sketches": 1]

    /// Wait until the queue's snapshot satisfies `condition` (the events reach the queue asynchronously).
    static func until(_ queue: JobQueue, _ what: String = "",
                      _ condition: @Sendable (QueueSnapshot) -> Bool) async throws -> QueueSnapshot
    {
        let deadline = ContinuousClock.now + .seconds(60)  // (a guard against a hang, far above any stall)
        while ContinuousClock.now < deadline {
            let snapshot = await queue.snapshot()
            if condition(snapshot) { return snapshot }
            try await Task.sleep(for: .milliseconds(5))
        }
        Issue.record("timed out waiting for \(what)")
        return await queue.snapshot()
    }

    @Test func runsInOrderAndStartsNextByItself() async throws {
        let (engine, queue, root) = try Self.setUp()
        let a = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = await queue.add(target: root.appending(path: "b.png"), settings: Self.settings)
        _ = try await Self.until(queue, "a running") { $0.jobs.first?.status == .running }
        var starts = await engine.requests.filter { $0.op == "start" }
        #expect(starts.count == 1 && starts[0].args["target"] == .string(root.appending(path: "a.png").path))
        #expect(starts[0].args["output_root"] == .string(root.appending(path: "out").path))
        #expect(starts[0].args["settings"] == .object(Self.settings))
        await engine.emit("job_done", ["best_svg": "x_best.svg"])
        let snap = try await Self.until(queue, "b running") { $0.jobs.count == 2 && $0.jobs[1].status == .running }
        #expect(snap.jobs[0].id == a && snap.jobs[0].status == .done && snap.jobs[0].bestSVG == "x_best.svg")
        starts = await engine.requests.filter { $0.op == "start" }
        #expect(starts.count == 2 && starts[1].args["target"] == .string(root.appending(path: "b.png").path))
        await engine.emit("job_done", job: "j2")
        let end = try await Self.until(queue, "finished") { $0.finished != nil }
        #expect(end.finished == .nothing && end.jobs.allSatisfy { $0.status == .done })
    }

    @Test func autoStartOffWaits() async throws {
        let (engine, queue, root) = try Self.setUp()
        await queue.setAutoStart(false)
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        try await Task.sleep(for: .milliseconds(100))
        #expect(await engine.ops().isEmpty)
        try await queue.startNext()
        #expect(await engine.ops() == ["start"])
        #expect(await queue.snapshot().jobs[0].status == .running)
    }

    @Test func progressAndEta() async throws {
        let (engine, queue, root) = try Self.setUp()
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = try await Self.until(queue) { $0.jobs.first?.status == .running }
        await engine.emit("job_start", ["seeds": [0, 1000]])
        await engine.emit("iteration", ["seed": 0, "it": 49, "total": 100, "eta": 12.5])
        var snap = try await Self.until(queue, "progress") { $0.jobs[0].progress == 0.25 }
        #expect(snap.jobs[0].eta == 12.5)
        await engine.emit("seed_done", ["seed": 0])
        snap = try await Self.until(queue, "a sketch done") { $0.jobs[0].progress == 0.5 }
        #expect(snap.jobs[0].seeds == [0, 1000])
    }

    @Test func aFirstEventBeforeTheStartAnswerIsKept() async throws {
        let (engine, queue, root) = try Self.setUp()
        await engine.setEventsBeforeAnswer(true)
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        let snap = try await Self.until(queue, "seeds") { $0.jobs.first?.seeds == [0, 1000] }
        #expect(snap.jobs[0].engineJob == "j1")
    }

    @Test func liveSVGPerSeed() async throws {
        let (engine, queue, root) = try Self.setUp()
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = try await Self.until(queue) { $0.jobs.first?.status == .running }
        await engine.emit("preview", ["seed": 0, "it": 5, "svg": "<svg>0</svg>"])
        await engine.emit("preview", ["seed": 1000, "it": 5, "svg": "<svg>1000</svg>"])
        await engine.emit("preview", job: "j9", ["seed": 0, "svg": "<svg>other job</svg>"])  // not this one's
        let snap = try await Self.until(queue, "previews") { $0.jobs[0].liveSVG.count == 2 }
        #expect(snap.jobs[0].liveSVG == [0: "<svg>0</svg>", 1000: "<svg>1000</svg>"])
    }

    @Test func pauseResumeCancel() async throws {
        let (engine, queue, root) = try Self.setUp()
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = try await Self.until(queue) { $0.jobs.first?.status == .running }
        try await queue.pause()
        #expect(await queue.snapshot().jobs[0].status == .paused)
        try await queue.resume()
        #expect(await queue.snapshot().jobs[0].status == .running)
        try await queue.cancel()
        #expect(await engine.ops() == ["start", "pause", "resume", "cancel"])
        let jobDir = root.appending(path: "job1")
        try JobFolder.setStatus(at: jobDir, "cancelled")  // as finish_job does for a cancelled job
        await engine.emit("job_done", ["job_dir": .string(jobDir.path)])
        let snap = try await Self.until(queue, "cancelled") { $0.jobs[0].status == .cancelled }
        #expect(snap.finished == nil)  // stopped by the user: nothing happens "when done"
    }

    @Test func failedJobKeepsItsMessage() async throws {
        let (engine, queue, root) = try Self.setUp()
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = try await Self.until(queue) { $0.jobs.first?.status == .running }
        await engine.emit("error", ["message": "out of memory", "oom": true])
        await engine.emit("job_failed", [:])
        let snap = try await Self.until(queue, "failed") { $0.jobs[0].status == .failed }
        #expect(snap.jobs[0].message == "out of memory")
    }

    @Test func crashMarksInterruptedAndCanContinue() async throws {
        let (engine, queue, root) = try Self.setUp()
        await queue.setAutoStart(false)
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        try await queue.startNext()
        await engine.emit("engine_exit", job: "", ["code": 9, "crashed": true])
        let snap = try await Self.until(queue, "interrupted") { $0.jobs[0].status == .interrupted }
        let jobDir = try #require(snap.jobs[0].jobDir)
        #expect(JobFolder.readState(at: jobDir)?["status"] == .string("interrupted"))
        #expect(snap.finished == nil)
        let again = await queue.addContinuation(jobDir: jobDir, target: root.appending(path: "a.png"),
                                                settings: Self.settings)
        try await queue.startNext()
        let start = try #require(await engine.requests.last)
        #expect(start.op == "start" && start.args["resume_dir"] == .string(jobDir.path))
        #expect(await queue.snapshot().jobs.first { $0.id == again }?.status == .running)
    }

    @Test func finishedOnlyWhenEmptiedByItself() async throws {
        let (engine, queue, root) = try Self.setUp()
        await queue.setWhenDone(.sleep)
        _ = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        _ = try await Self.until(queue) { $0.jobs.first?.status == .running }
        await engine.emit("job_done", [:])
        let snap = try await Self.until(queue, "finished") { $0.finished != nil }
        #expect(snap.finished == .sleep)
    }

    @Test func removeAndMove() async throws {
        let (_, queue, root) = try Self.setUp()
        await queue.setAutoStart(false)
        let a = await queue.add(target: root.appending(path: "a.png"), settings: Self.settings)
        let b = await queue.add(target: root.appending(path: "b.png"), settings: Self.settings)
        let c = await queue.add(target: root.appending(path: "c.png"), settings: Self.settings)
        await queue.move(c, to: 0)
        #expect(await queue.snapshot().jobs.map(\.id) == [c, a, b])
        await queue.remove(a)
        #expect(await queue.snapshot().jobs.map(\.id) == [c, b])
    }
}
