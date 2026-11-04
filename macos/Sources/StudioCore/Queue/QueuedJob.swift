import Foundation

/// One job of the queue (gui/controller.py `QueuedJob`).
public struct QueuedJob: Sendable, Identifiable, Hashable {
    public enum Status: String, Sendable {
        case queued, running, paused, done, failed, cancelled, interrupted
    }

    public let id: UUID
    public var target: URL
    public var settings: JSONObject
    /// "Continue": the folder of the interrupted job
    public var resumeDir: URL?
    public var status: Status = .queued
    public var jobDir: URL?
    /// the engine's id of the job while it runs ("j3")
    public var engineJob: String?
    /// the job's items (seeds; for SceneSketch its cells), from job_start
    public var seeds: [Int] = []
    public var seedProgress: [Int: Double] = [:]
    /// the latest sketch of every seed while it is computed (SVG)
    public var liveSVG: [Int: String] = [:]
    /// seconds left, as the engine estimates them
    public var eta: Double?
    public var message: String = ""
    public var bestSVG: String?

    public init(id: UUID = UUID(), target: URL, settings: JSONObject, resumeDir: URL? = nil) {
        self.id = id
        self.target = target
        self.settings = settings
        self.resumeDir = resumeDir
    }

    /// 0 … 1 – the mean over the job's items, each (it + 1) / total, a finished one 1.
    public var progress: Double {
        guard !seeds.isEmpty else { return 0 }
        return seeds.reduce(0) { $0 + (seedProgress[$1] ?? 0) } / Double(seeds.count)
    }

    public var isActive: Bool { status == .running || status == .paused }
}

/// What happens when the queue ran out by itself (gui/pages/other_pages.py "when done").
public enum WhenDone: String, Sendable, CaseIterable {
    case nothing, sleep, shutdown
}

public struct QueueSnapshot: Sendable, Hashable {
    public let jobs: [QueuedJob]
    /// set once the last job finished by itself (not cancelled by the user): what is to happen now
    public let finished: WhenDone?
    public let autoStart: Bool

    public init(jobs: [QueuedJob], finished: WhenDone?, autoStart: Bool) {
        self.jobs = jobs
        self.finished = finished
        self.autoStart = autoStart
    }
}
