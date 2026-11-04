import Foundation
import Observation
import StudioCore

/// The studio page: the image, the method, its preset and settings – kept as gui/widgets/param_panel.py keeps them:
/// every method its own settings (from its start, settings_schema.start_settings), a preset sets its values, after a
/// change the preset whose values all match is shown (nil: own values) – and the job it started (`live`).
@Observable
public final class StudioModel {
    public let schema: ParamSchema
    public var image: URL?
    public private(set) var method: String
    public private(set) var preset: String?
    public private(set) var settings: JSONObject
    /// The job the studio started: what changes many times a second, in an object of its own.
    public let live = LiveJob()
    @ObservationIgnored private var perMethod: [String: JSONObject] = [:]

    public init(schema: ParamSchema) {
        self.schema = schema
        let method = schema.method(schema.defaultMethod) ?? schema.methods.lazy.compactMap { schema.method($0) }.first
        self.method = method?.id ?? schema.defaultMethod
        let start = method?.start ?? [:]
        settings = start
        preset = method?.matchingPreset(start)
    }

    public var methodSchema: MethodSchema? { schema.method(method) }

    public func selectMethod(_ id: String) {
        guard id != method, let next = schema.method(id) else { return }
        perMethod[method] = settings
        method = id
        settings = perMethod[id] ?? next.start
        preset = next.matchingPreset(settings)
    }

    public func applyPreset(_ name: String) {
        guard let m = methodSchema, m.presets[name] != nil else { return }
        settings = m.applyPreset(name, to: settings)
        preset = name
    }

    /// One parameter changed (taken as the parameter takes it); a key the method does not have is ignored.
    public func set(_ key: String, to value: JSONValue) {
        guard let m = methodSchema, let param = m.param(key) else { return }
        settings[key] = m.clamp(param, value)
        preset = m.matchingPreset(settings)
    }

    /// Back to the method's start (the studio's Reset).
    public func reset() {
        guard let m = methodSchema else { return }
        settings = m.start
        preset = m.matchingPreset(settings)
    }

    public func isEnabled(_ key: String) -> Bool {
        guard let m = methodSchema, let param = m.param(key) else { return false }
        return m.isEnabled(param, in: settings)
    }

    public var strokes: Int { methodSchema?.numStrokes(settings) ?? 0 }

    /// What a job gets: the settings with their method.
    public var jobSettings: JSONObject {
        var out = settings
        out["method"] = .string(method)
        return out
    }

    public var canStart: Bool { image != nil && !live.isActive }

    /// Put the job into the queue (it starts at once when nothing runs); nil without an image or while one runs.
    @discardableResult
    public func start(on queue: JobQueue) async -> QueuedJob.ID? {
        guard canStart, let image else { return nil }
        let settings = jobSettings
        live.begin()
        let id = await queue.add(target: image, settings: settings)
        live.jobID = id
        live.update(from: await queue.snapshot())
        return id
    }

    /// What VoiceOver says about the canvas.
    public func canvasLabel(_ texts: Texts, sketch: Sketch?) -> String {
        guard let sketch, let image else { return texts.tr("ui.canvas_placeholder") }
        return texts.tr("ui.mac.canvas_label", ["image": image.lastPathComponent, "strokes": "\(sketch.strokes.count)"])
    }
}

/// One item's latest sketch of a job.
public struct SeedSketch: Sendable, Hashable, Identifiable {
    public var id: Int { seed }
    public let seed: Int
    public let svg: String
}

/// The running job of the studio as the queue reports it: status, progress, time left, the sketch under way.
@Observable
public final class LiveJob {
    public internal(set) var jobID: QueuedJob.ID?
    public private(set) var status: QueuedJob.Status?
    public private(set) var progress: Double = 0
    public private(set) var eta: Double?
    /// the newest sketch of the item being computed (SVG)
    public private(set) var liveSVG: String?
    /// the job's best sketch when it is done (a file)
    public private(set) var bestSVG: String?
    /// every item's latest sketch so far, in the job's order (seed, SVG)
    public private(set) var sketches: [SeedSketch] = []
    public private(set) var jobDir: URL?
    public private(set) var message = ""
    @ObservationIgnored private var starting = false

    public init() {}

    public var isActive: Bool {
        starting || status == .queued || status == .running || status == .paused
    }

    func begin() {
        starting = true
        jobID = nil
        status = nil
        progress = 0
        eta = nil
        liveSVG = nil
        bestSVG = nil
        sketches = []
        jobDir = nil
        message = ""
    }

    /// Take over what the queue says about this job (only what changed, so views redraw only for that).
    public func update(from snapshot: QueueSnapshot) {
        guard let id = jobID, let job = snapshot.jobs.first(where: { $0.id == id }) else { return }
        starting = false
        if status != job.status { status = job.status }
        let p = job.progress
        if progress != p { progress = p }
        if eta != job.eta { eta = job.eta }
        let underWay = job.seeds.first { (job.seedProgress[$0] ?? 0) < 1 && job.liveSVG[$0] != nil }
            ?? job.seeds.last { job.liveSVG[$0] != nil }
        let svg = underWay.flatMap { job.liveSVG[$0] }
        if let svg, liveSVG != svg { liveSVG = svg }
        let all = job.seeds.compactMap { seed in job.liveSVG[seed].map { SeedSketch(seed: seed, svg: $0) } }
        if sketches != all { sketches = all }
        if bestSVG != job.bestSVG { bestSVG = job.bestSVG }
        if jobDir != job.jobDir { jobDir = job.jobDir }
        if message != job.message { message = job.message }
    }
}
