import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The canvas in the photo's shape (CanvasShape): a run's from the photo frame its config.json keeps; the studio's
/// job under way's from its picture and settings (framing.guess_frame) – square where it cannot be known.
@Suite(.serialized) struct CanvasShapeTests {
    @Test func aRunsCanvas() throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let run = FileManager.default.temporaryDirectory.appending(path: "shape-\(UUID().uuidString)/job/run")
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        #expect(model.canvasStretch(runDir: nil) == 1)
        let other = run.deletingLastPathComponent().appending(path: "other")
        try FileManager.default.createDirectory(at: other, withIntermediateDirectories: true)
        #expect(model.canvasStretch(runDir: other) == 1)  // (nothing known: square)
        try Data(#"{"photo_frame": {"aspect": 1.5, "rect": [0, 0, 1, 1]}}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(model.canvasStretch(runDir: run) == 1.5)  // (stretched onto the canvas: shown 3:2 again)
    }

    @Test func theJobUnderWay() async throws {
        let base = FileManager.default.temporaryDirectory.appending(path: "shape-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        let picture = base.appending(path: "Quer.png")
        let wide = PixelImage(width: 300, height: 200, bytes: [UInt8](repeating: 200, count: 300 * 200 * 4))
        try #require(wide.png()).write(to: picture)
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(base.path)]))
        #expect(model.liveStretch == 1)  // (no job)
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        model.studio.image = picture
        model.studio.set("fix_scale", to: false)
        model.studio.set("mask_object", to: false)
        await model.studio.start(on: try #require(model.queue))
        model.apply(await model.queue!.snapshot())
        #expect(abs(model.liveStretch - 1.5) < 1e-9)
        await model.stopEngine()
    }
}
