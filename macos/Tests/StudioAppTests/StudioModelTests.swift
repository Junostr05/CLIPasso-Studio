import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// An engine that answers `start` and keeps what it was sent.
actor RecordingEngine: EngineControlling {
    nonisolated let events: AsyncStream<EngineEvent>
    private let sink: AsyncStream<EngineEvent>.Continuation
    private(set) var requests: [(op: String, args: JSONObject)] = []

    init() {
        (events, sink) = AsyncStream<EngineEvent>.makeStream()
    }

    func request(_ op: String, _ args: JSONObject, timeout: Duration) async throws -> JSONValue {
        requests.append((op, args))
        return op == "start" ? ["job": "j1", "job_dir": .string((args["output_root"]?.stringValue ?? "") + "/job")] : [:]
    }

    func send(_ event: EngineEvent) {
        sink.yield(event)
    }
}

/// The studio's settings behave as gui/widgets/param_panel.py keeps them, and a job gets them as they are.
@Suite(.serialized) struct StudioModelTests {
    static let fixtures = AppModelTests.repo.appending(path: "macos/Tests/StudioCoreTests/Fixtures")

    static func model() throws -> StudioModel {
        StudioModel(schema: try ParamSchema.load(fixtures.appending(path: "schema.json")))
    }

    @Test func settingsFollowPresetAndClamp() throws {
        let studio = try Self.model()
        let clipasso = try #require(studio.schema.method("clipasso"))
        #expect(studio.method == "clipasso" && studio.settings == clipasso.start && studio.preset == "standard")
        studio.applyPreset("fast")
        #expect(studio.preset == "fast")
        for (key, value) in clipasso.presets["fast"] ?? [:] {
            #expect(studio.settings[key] == value)
        }
        let paths = try #require(clipasso.param("num_paths"))
        studio.set("num_paths", to: 100_000)
        #expect(studio.settings["num_paths"] == .int(Int(paths.maximum ?? 0)))
        #expect(studio.preset == nil || studio.preset == clipasso.matchingPreset(studio.settings))
        studio.set("num_paths", to: clipasso.presets["fast"]?["num_paths"] ?? 16)
        #expect(studio.preset == clipasso.matchingPreset(studio.settings))
        studio.set("unknown_key", to: 5)
        #expect(studio.settings["unknown_key"] == nil)  // only the method's parameters
        // every method keeps its own settings
        let changed = studio.settings
        studio.selectMethod("swiftsketch")
        #expect(studio.method == "swiftsketch" && studio.settings == studio.schema.method("swiftsketch")?.start)
        studio.selectMethod("clipasso")
        #expect(studio.settings == changed)
        studio.reset()
        #expect(studio.settings == clipasso.start)
    }

    @Test func rulesGreyOutParameters() throws {
        let studio = try Self.model()
        let clipasso = try #require(studio.schema.method("clipasso"))
        let ruled = try #require(clipasso.params.first { $0.enabledIf != nil })
        #expect(studio.isEnabled(ruled.key) == clipasso.isEnabled(ruled, in: studio.settings))
        #expect(studio.isEnabled("no_such_parameter") == false)
    }

    @Test func startSendsTheSchemaSettings() async throws {
        let studio = try Self.model()
        studio.applyPreset("quality")
        let engine = RecordingEngine()
        let queue = JobQueue(engine: engine, outputRoot: URL(filePath: "/tmp/Skizzen"))
        #expect(studio.canStart == false)  // (no image yet)
        #expect(await studio.start(on: queue) == nil)
        studio.image = URL(filePath: "/Users/studio/Pictures/Kamel.png")
        let id = try #require(await studio.start(on: queue))
        let sent = try #require(await engine.requests.first { $0.op == "start" })
        #expect(sent.args["settings"] == .object(studio.jobSettings))
        #expect(studio.jobSettings["method"] == "clipasso")
        #expect(sent.args["target"] == "/Users/studio/Pictures/Kamel.png")
        studio.live.update(from: await queue.snapshot())
        #expect(studio.live.jobID == id && studio.live.status == .running && studio.canStart == false)
    }

    @Test func umlautPath() async throws {
        let studio = try Self.model()
        let engine = RecordingEngine()
        let queue = JobQueue(engine: engine, outputRoot: URL(filePath: "/Users/Jürgen/Documents/CLIPasso Studio"))
        studio.image = URL(filePath: "/Users/Jürgen/Bilder/Kamel am Abend ä.png")
        _ = try #require(await studio.start(on: queue))
        let sent = try #require(await engine.requests.first { $0.op == "start" })
        #expect(sent.args["target"] == "/Users/Jürgen/Bilder/Kamel am Abend ä.png")  // a path, never %-encoded
        #expect(sent.args["output_root"] == "/Users/Jürgen/Documents/CLIPasso Studio")
    }

    @Test func liveFollowsTheJob() throws {
        let studio = try Self.model()
        var job = QueuedJob(target: URL(filePath: "/a.png"), settings: [:])
        job.status = .running
        job.seeds = [1000, 2000]
        job.seedProgress = [1000: 1, 2000: 0.5]
        job.liveSVG = [1000: "<svg>a</svg>", 2000: "<svg>b</svg>"]
        job.eta = 42
        studio.live.jobID = job.id
        studio.live.update(from: QueueSnapshot(jobs: [job], finished: nil, autoStart: true))
        #expect(studio.live.progress == 0.75 && studio.live.eta == 42)
        #expect(studio.live.liveSVG == "<svg>b</svg>")  // the sketch under way
        #expect(studio.live.sketches == [SeedSketch(seed: 1000, svg: "<svg>a</svg>"),
                                         SeedSketch(seed: 2000, svg: "<svg>b</svg>")])  // every item, in order
        job.status = .done
        job.seedProgress[2000] = 1
        job.bestSVG = "/out/job/best.svg"
        studio.live.update(from: QueueSnapshot(jobs: [job], finished: .nothing, autoStart: true))
        #expect(studio.live.status == .done && studio.live.isActive == false && studio.live.bestSVG == "/out/job/best.svg")
    }

    @Test func canvasAccessibilityLabel() throws {
        let studio = try Self.model()
        let de = try Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"), language: "de")
        #expect(studio.canvasLabel(de, sketch: nil) == de.tr("ui.canvas_placeholder"))
        studio.image = URL(filePath: "/Users/studio/Pictures/Kamel.png")
        let svg = try String(contentsOf: Self.fixtures.appending(path: "svg/lines.svg"), encoding: .utf8)
        let sketch = try SketchSVG.parse(svg)
        #expect(studio.canvasLabel(de, sketch: sketch) == "Skizze von Kamel.png, \(sketch.strokes.count) Striche")
    }
}

/// The value types the window reads in background tasks (the sketch previews are parsed off the main actor) must
/// not belong to the main actor, which is this module's default.
@Suite struct OffTheMainActorTests {
    @Test func seedSketchInABackgroundTask() async {
        let item = SeedSketch(seed: 1000, svg: "<svg/>")
        let read = await Task.detached { (item.seed, item.svg) }.value
        #expect(read.0 == 1000 && read.1 == "<svg/>")
    }
}
