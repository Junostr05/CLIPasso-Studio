import Foundation
import ImageIO
import Testing
@testable import StudioApp
import StudioCore

/// The app's animation export: GIF and MP4 written here off the main actor, WebP by the engine (Pillow) from the
/// frames drawn here; a cancelled export leaves no file.
@Suite(.serialized) struct AnimationExportTests {
    static func job(_ format: SketchAnimation.Format, length: Double = 1, size: Int = 64) throws -> AnimationJob {
        var options = ExportOptions()
        options.size = size
        options.background = "#FFFFFF"
        let svg = String(decoding: try Data(contentsOf: AppModelTests.repo
                .appending(path: "macos/Tests/StudioCoreTests/Fixtures/animation/drawing.svg")), as: UTF8.self)
        return AnimationJob(mode: .strokes, format: format, options: options, length: length, hold: 0.5, svg: svg,
                            runDir: nil)
    }

    static func file(_ ext: String) -> URL {
        FileManager.default.temporaryDirectory.appending(path: "anim-\(UUID().uuidString).\(ext)")
    }

    @Test func gifAndMP4() async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let gif = Self.file("gif"), mp4 = Self.file("mp4")
        defer { for url in [gif, mp4] { try? FileManager.default.removeItem(at: url) } }
        let counted = Counter()
        let frames = try await model.exportAnimation(try Self.job(.gif), to: gif) { done, _ in counted.add(done) }
        let source = try #require(CGImageSourceCreateWithURL(gif as CFURL, nil))
        #expect(CGImageSourceGetCount(source) == frames && counted.last == frames)
        #expect(try await model.exportAnimation(try Self.job(.mp4, size: 100), to: mp4) == 45)
        #expect(FileManager.default.fileExists(atPath: mp4.path))
    }

    /// The cancel comes while the export is under way – after the first frame, and after the last one, before the
    /// GIF is written: the export stops and leaves no file. (The frame waits for the cancel, so the test does not
    /// hang on the machine's speed.)
    @Test(arguments: [false, true]) func aCancelledExportLeavesNoFile(atTheEnd: Bool) async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let gif = Self.file("gif")
        defer { try? FileManager.default.removeItem(at: gif) }
        let gate = Gate()
        let task = Task {
            try await model.exportAnimation(try Self.job(.gif, length: 2), to: gif) { done, total in
                if done == (atTheEnd ? total : 1) { gate.arrive() }
            }
        }
        while !gate.arrived { try await Task.sleep(for: .milliseconds(10)) }
        task.cancel()
        gate.open()
        await #expect(throws: CancellationError.self) { try await task.value }
        #expect(!FileManager.default.fileExists(atPath: gif.path))
    }

    @Test func webpWithoutTheEngine() async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        await #expect(throws: EngineFailure.self) { try await model.exportAnimation(try Self.job(.webp), to: Self.file("webp")) }
    }

    /// The engine writes the WebP from the frames drawn here (and their folder goes again).
    @Test func webpByTheEngine() async throws {
        let launch = AppModelTests.realEngine()  // (the tests' Python: it has Pillow)
        let model = try AppModel(resources: AppModelTests.resources(engine: launch), store: AppModelTests.store(language: "en"))
        await model.startEngine()
        #expect(model.engineStatus == .ready)
        let webp = Self.file("webp")
        defer { try? FileManager.default.removeItem(at: webp) }
        var job = try Self.job(.webp, length: 0.5)
        job.options.background = nil  // (WebP keeps a transparent background)
        let frames = try await model.exportAnimation(job, to: webp)
        let source = try #require(CGImageSourceCreateWithURL(webp as CFURL, nil))
        #expect(CGImageSourceGetCount(source) == frames)
        await model.stopEngine()
    }
}

/// The brush styles of the exports: the engine draws a sketch in a style (op "stylize") for an export's thread; plain,
/// and a style the schema does not list, ask no one.
@Suite(.serialized) struct BrushStyleTests {
    @Test func theEngineDrawsAStyle() async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: AppModelTests.realEngine()),
                                 store: AppModelTests.store(language: "en"))
        #expect(model.brushStyles.first == "plain" && model.brushStyles.contains("charcoal"))
        #expect(model.stylist("plain").isPlain && model.stylist("glitter").isPlain)
        #expect(model.stylist("neon").recolours && !model.stylist("charcoal").recolours)
        await model.startEngine()
        #expect(model.engineStatus == .ready)
        let svg = String(decoding: try Data(contentsOf: AppModelTests.repo
                .appending(path: "macos/Tests/StudioCoreTests/Fixtures/svg/lines.svg")), as: UTF8.self)
        let stylist = model.stylist("charcoal")
        let styled = try await Task.detached(executorPreference: OwnThreads.shared) { try stylist([svg, svg]) }.value
        #expect(styled.count == 2 && styled[0] == styled[1] && styled[0].contains("stroke-dasharray"))
        #expect(try SketchSVG.parse(styled[0]).strokes.count > SketchSVG.parse(svg).strokes.count)  // (grain)
        await model.stopEngine()
    }
}

/// A frame that waits until the test has cancelled the export (at most half a minute).
nonisolated final class Gate: @unchecked Sendable {
    private let lock = NSLock()
    private var reached = false
    private let opened = DispatchSemaphore(value: 0)

    func arrive() {
        lock.withLock { reached = true }
        _ = opened.wait(timeout: .now() + 30)
    }

    var arrived: Bool { lock.withLock { reached } }
    func open() { opened.signal() }
}

/// The progress an export reported, from any thread.
nonisolated final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func add(_ done: Int) { lock.withLock { value = done } }
    var last: Int { lock.withLock { value } }
}
