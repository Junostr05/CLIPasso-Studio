import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// "Continue with CLIPasso" with the real engine (gui/continuing.py): what the dialog shows, the start values the
/// phone uses without asking, and the job – prepared in the output folder's _continued, queued with the studio's
/// CLIPasso settings and the sketch as its start.
@Suite(.serialized) struct ContinueSketchTests {
    @Test func aSketchContinuedWithCLIPasso() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let root = FileManager.default.temporaryDirectory.appending(path: "continue-\(UUID().uuidString)")
        let job = root.appending(path: "done_clipasso"), out = root.appending(path: "Ergebnisse")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: done, to: job)
        let model = try AppModel(resources: AppModelTests.resources(engine: AppModelTests.realEngine()),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(out.path)]))
        await model.startEngine()
        #expect(model.engineStatus == .ready)
        await model.queuePage?.setAutoStart(false)
        model.studio.reload(job)
        let editor = try #require(model.studio.result?.editor)
        let before = try #require(await model.continueInfo(editor))
        #expect(before.strokes == 2 && !before.canContinue)  // (no input.png yet)
        #expect(before.new == ContinueInfo.startNew && before.iterations == ContinueInfo.startIterations)
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "crop/input.png"),
                                         to: editor.runDir.appending(path: "input.png"))
        editor.draw([SketchPoint(x: 20, y: 20), SketchPoint(x: 80, y: 120), SketchPoint(x: 150, y: 60)])
        let info = try #require(await model.continueInfo(editor))
        #expect(info.canContinue && info.strokes == 3 && info.fixed == 1)
        #expect(model.phoneEditState().objectValue?["can_continue"] == true)
        model.studio.set("num_sketches", to: 2)
        let queued = try await model.continueSketch(editor, new: 3, iterations: 101, keep: true)
        #expect(!queued)
        let added = try #require(model.queueSnapshot?.jobs.last)
        #expect(added.target.deletingLastPathComponent().deletingLastPathComponent().lastPathComponent == "_continued")
        #expect(added.target.path.hasPrefix(out.path) && FileManager.default.fileExists(atPath: added.target.path))
        #expect(added.settings["method"] == "clipasso" && added.settings["num_paths"] == 6)
        #expect(added.settings["num_iter"] == 101 && added.settings["num_sketches"] == 1)
        let start = try #require(added.settings["path_svg"]?.stringValue)
        #expect(SketchEditing.fixedCount(try String(contentsOf: URL(filePath: start), encoding: .utf8)) == 1)
        await model.stopEngine()
    }
}
