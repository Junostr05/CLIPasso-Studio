import Foundation

/// The job queue on the engine process (gui/controller.py `JobController`): one job at a time, in order, the next
/// one started by itself (`autoStart`); pause, resume, cancel; progress, the time left and the live sketches from the
/// engine's events. A job whose engine crashed is marked interrupted – in its folder too – and can be continued.
public actor JobQueue {
    public nonisolated let updates: AsyncStream<QueueSnapshot>
    private let sink: AsyncStream<QueueSnapshot>.Continuation
    private let engine: any EngineControlling
    public let outputRoot: URL
    public private(set) var autoStart = true
    public private(set) var whenDone: WhenDone = .nothing
    private var jobs: [QueuedJob] = []
    private var finished: WhenDone?
    private var stoppedByUser = false
    private var listener: Task<Void, Never>?

    public init(engine: any EngineControlling, outputRoot: URL) {
        self.engine = engine
        self.outputRoot = outputRoot
        (updates, sink) = AsyncStream<QueueSnapshot>.makeStream(bufferingPolicy: .bufferingNewest(1))
    }

    deinit {
        listener?.cancel()
    }

    private func listen() {
        guard listener == nil else { return }
        let events = engine.events
        listener = Task { [weak self] in
            for await event in events {
                await self?.handle(event)
            }
        }
    }

    public func snapshot() -> QueueSnapshot {
        QueueSnapshot(jobs: jobs, finished: finished, autoStart: autoStart)
    }

    private func publish() {
        sink.yield(snapshot())
    }

    private var current: Int? {
        jobs.firstIndex { $0.isActive }
    }

    // MARK: - the list

    @discardableResult
    public func add(target: URL, settings: JSONObject) async -> QueuedJob.ID {
        await append(QueuedJob(target: target, settings: settings))
    }

    /// "Continue" an interrupted or cancelled job in its folder.
    @discardableResult
    public func addContinuation(jobDir: URL, target: URL, settings: JSONObject) async -> QueuedJob.ID {
        await append(QueuedJob(target: target, settings: settings, resumeDir: jobDir))
    }

    private func append(_ job: QueuedJob) async -> QueuedJob.ID {
        listen()
        jobs.append(job)
        finished = nil
        publish()
        if autoStart, current == nil {
            try? await startNext()
        }
        return job.id
    }

    public func remove(_ id: QueuedJob.ID) {
        jobs.removeAll { $0.id == id && !$0.isActive }
        publish()
    }

    public func move(_ id: QueuedJob.ID, to index: Int) {
        guard let from = jobs.firstIndex(where: { $0.id == id }) else { return }
        let job = jobs.remove(at: from)
        jobs.insert(job, at: max(0, min(index, jobs.count)))
        publish()
    }

    public func setAutoStart(_ on: Bool) async {
        autoStart = on
        publish()
        if on, current == nil {
            try? await startNext()
        }
    }

    public func setWhenDone(_ action: WhenDone) {
        whenDone = action
        publish()
    }

    // MARK: - control

    /// Start the first waiting job (nothing when one runs or none waits).
    public func startNext() async throws {
        listen()
        guard current == nil, let i = jobs.firstIndex(where: { $0.status == .queued }) else { return }
        var job = jobs[i]
        var args: JSONObject = ["target": .string(job.target.path), "settings": .object(job.settings),
                                "output_root": .string(outputRoot.path)]
        if let resume = job.resumeDir { args["resume_dir"] = .string(resume.path) }
        job.status = .running
        jobs[i] = job
        stoppedByUser = false
        finished = nil
        publish()
        do {
            let result = try await engine.request("start", args, timeout: .seconds(60))
            guard let k = index(of: job.id) else { return }
            jobs[k].engineJob = result.objectValue?["job"]?.stringValue
            jobs[k].jobDir = result.objectValue?["job_dir"]?.stringValue.map { URL(filePath: $0) }
            publish()
        } catch {
            if let k = index(of: job.id) {
                jobs[k].status = .failed
                jobs[k].message = String(describing: error)
            }
            publish()
            throw error
        }
    }

    private func index(of id: QueuedJob.ID) -> Int? {
        jobs.firstIndex { $0.id == id }
    }

    public func pause() async throws {
        guard let i = current, jobs[i].status == .running else { return }
        _ = try await engine.request("pause", [:], timeout: .seconds(10))
        if let i = current { jobs[i].status = .paused }
        publish()
    }

    public func resume() async throws {
        guard let i = current, jobs[i].status == .paused else { return }
        _ = try await engine.request("resume", [:], timeout: .seconds(10))
        if let i = current { jobs[i].status = .running }
        publish()
    }

    /// Cancel the running job; its best sketch so far is saved (it can be continued).
    public func cancel() async throws {
        guard current != nil else { return }
        stoppedByUser = true
        _ = try await engine.request("cancel", [:], timeout: .seconds(10))
    }

    // MARK: - the engine's events

    private func handle(_ event: EngineEvent) async {
        if event.kind == "engine_exit" {
            engineEnded(crashed: event.data["crashed"]?.truthy ?? true)
            return
        }
        guard let i = current, let eventJob = event.job else { return }
        if jobs[i].engineJob == nil, jobs[i].status == .running {
            jobs[i].engineJob = eventJob  // the job's first event came before the answer to "start"
        }
        guard jobs[i].engineJob == eventJob else { return }
        var job = jobs[i]
        let seed = event.data["seed"]?.intValue
        switch event.kind {
        case "job_start":
            job.seeds = event.data["seeds"]?.arrayValue?.compactMap(\.intValue) ?? job.seeds
            if let dir = event.data["job_dir"]?.stringValue { job.jobDir = URL(filePath: dir) }
        case "iteration":
            if let seed, let it = event.data["it"]?.doubleValue, let total = event.data["total"]?.doubleValue,
               total > 0
            {
                job.seedProgress[seed] = min(1, (it + 1) / total)
            }
            if let eta = event.data["eta"]?.doubleValue { job.eta = eta }
        case "preview":
            if let seed, let svg = event.data["svg"]?.stringValue { job.liveSVG[seed] = svg }
        case "seed_done":
            if let seed { job.seedProgress[seed] = 1 }
        case "error":
            job.message = event.data["message"]?.stringValue ?? job.message
        case "job_done":
            job.bestSVG = event.data["best_svg"]?.stringValue
            let dir = event.data["job_dir"]?.stringValue.map { URL(filePath: $0) } ?? job.jobDir
            let state = dir.flatMap { JobFolder.readState(at: $0)?["status"]?.stringValue }
            job.status = state == "cancelled" ? .cancelled : .done  // (a cancelled job keeps its best sketch)
            job.eta = nil
        case "job_failed":
            job.status = .failed
        case "job_ended":
            job.status = .cancelled
        default:
            break
        }
        jobs[i] = job
        if !job.isActive {
            await jobEnded()
        } else {
            publish()
        }
    }

    private func engineEnded(crashed: Bool) {
        guard let i = current else { return }
        jobs[i].status = .interrupted
        jobs[i].message = crashed ? "the engine ended unexpectedly" : jobs[i].message
        if let dir = jobs[i].jobDir {
            try? JobFolder.setStatus(at: dir, "interrupted")
        }
        publish()
    }

    private func jobEnded() async {
        let byUser = stoppedByUser
        publish()
        if jobs.contains(where: { $0.status == .queued }) {
            if autoStart { try? await startNext() }
        } else if !byUser {
            finished = whenDone
            publish()
        }
    }
}
