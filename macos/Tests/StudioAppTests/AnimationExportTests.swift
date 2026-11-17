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

    @Test func aCancelledExportLeavesNoFile() async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let gif = Self.file("gif")
        let job = try Self.job(.gif, length: 60, size: 512)  // (3000 drawn steps: long enough to be stopped)
        let started = Counter()
        let task = Task { try await model.exportAnimation(job, to: gif) { done, _ in started.add(done) } }
        while started.last == 0 { try await Task.sleep(for: .milliseconds(10)) }
        task.cancel()
        await #expect(throws: CancellationError.self) { try await task.value }
        #expect(!FileManager.default.fileExists(atPath: gif.path))
    }

    @Test func webpWithoutTheEngine() async throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        await #expect(throws: EngineFailure.self) { try await model.exportAnimation(try Self.job(.webp), to: Self.file("webp")) }
    }

    /// The engine writes the WebP from the frames drawn here (and their folder goes again).
    @Test func webpByTheEngine() async throws {
        let launch = EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                                  arguments: ["python3", "-m", "clipasso_studio.headless"],
                                  // (the Python of the tests first: it has Pillow)
                                  environment: ["PYTHONPATH": AppModelTests.repo.path,
                                                "PATH": (ProcessInfo.processInfo.environment["PATH"] ?? "")
                                                    + ":/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"],
                                  workingDirectory: AppModelTests.repo)
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

/// The progress an export reported, from any thread.
nonisolated final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func add(_ done: Int) { lock.withLock { value = done } }
    var last: Int { lock.withLock { value } }
}
