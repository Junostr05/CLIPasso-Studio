import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The studio's edit bar (edit_bar.py): the saved steps of a sketch, and Simplify – the least important strokes go
/// first, in the order the engine measured (here the fake engine's: the later strokes count more).
@Suite(.serialized) struct EditBarTests {
    static func svg(_ n: Int) -> String {
        let paths = (0 ..< n).map { i in
            "<path d=\"M\(10 + i * 10) 10 L\(10 + i * 10) 90\" stroke=\"black\" stroke-width=\"2\" fill=\"none\"/>"
        }
        return "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\" viewBox=\"0 0 100 100\">"
            + paths.joined() + "</svg>"
    }

    /// A run's folder with its sketch (`strokes`) and saved steps of 1, 2, 3 strokes at iterations 0, 10, 2.
    static func run(_ name: String = "Lauf ä", strokes: Int = 4) throws -> URL {
        let run = FileManager.default.temporaryDirectory.appending(path: "editbar-\(UUID().uuidString)/\(name)")
        let logs = run.appending(path: "svg_logs")
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        try Data(svg(strokes).utf8).write(to: run.appending(path: "best_iter.svg"))
        for (iteration, n) in [(0, 1), (10, 3), (2, 2)] {
            try Data(svg(n).utf8).write(to: logs.appending(path: "svg_iter\(iteration).svg"))
        }
        return run
    }

    @Test func theSavedSteps() throws {
        let texts = try Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"), language: "de")
        let editor = try #require(SketchEditor.load(runDir: try Self.run()))
        let frames = SketchAnimation.steps(runDir: editor.runDir, uptoBest: false)
        let bar = try #require(EditBarModel(steps: frames, current: editor.svg))
        #expect(bar.range == 0 ... 2 && bar.value == 2 && bar.preview == Self.svg(3))  // (the last step first)
        #expect(bar.info(texts) == texts.tr("ui.edit_bar.step", ["n": "3", "total": "3", "it": "10"]))
        bar.value = 0
        #expect(bar.preview == Self.svg(1) && bar.canApply && bar.sliderEnabled)
        bar.value = 99
        #expect(bar.value == 2)
        bar.value = 1
        editor.take(bar.preview)
        #expect(editor.svg == Self.svg(2) && editor.isEdited && editor.canUndo)
        editor.take(editor.svg)  // (the same: no step)
        editor.undo()
        #expect(editor.svg == Self.svg(4) && !editor.isEdited)
        #expect(EditBarModel(steps: Array(frames.prefix(1)), current: editor.svg) == nil)
        #expect(EditBarModel.iteration(URL(filePath: "/x/svg_iter12.svg")) == 12)
        #expect(EditBarModel.iteration(URL(filePath: "/x/best_iter.svg")) == -1)
    }

    @Test func simplify() throws {
        let texts = try Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"), language: "de")
        let svg = Self.svg(4)
        let bar = EditBarModel(simplify: svg, order: nil)
        #expect(bar.measuring && !bar.sliderEnabled && !bar.canApply && bar.value == 4)
        #expect(bar.note(texts) == texts.tr("ui.edit_bar.measuring"))
        bar.measured([3, 0, 2, 1])
        #expect(!bar.measuring && bar.sliderEnabled && !bar.canApply && bar.preview == svg)
        bar.value = 2  // (the two least important go: 3 and 0)
        #expect(bar.canApply && bar.preview == SketchEditing.removeStrokes(svg, [3, 0]))
        #expect(bar.info(texts) == texts.tr("ui.edit_bar.strokes", ["n": "2", "total": "4"]))
        #expect(bar.kept(0) == SketchEditing.removeStrokes(svg, [0, 1, 2, 3]) && bar.kept(4) == svg)
        bar.measured([0, 1])  // (another sketch's order: none)
        #expect(bar.order == nil && bar.preview == svg)
        bar.measured(nil, problem: "RuntimeError: no CLIP")
        #expect(!bar.measuring && bar.note(texts) == texts.tr("ui.edit_bar.measure_failed", ["error": "RuntimeError: no CLIP"]))
    }

    /// The engine measures in a process of its own and says when it is done; the order is read again then – and
    /// straight away the next time. A measuring that fails says why.
    @Test func measuredByTheEngine() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de"))
        await model.startEngine()
        let editor = try #require(SketchEditor.load(runDir: try Self.run()))
        let bar = model.openSimplify(editor)
        try await ModelFlowTests.wait("the measuring") { !bar.measuring }
        #expect(bar.order == [0, 1, 2, 3] && model.importanceState?.status == "ready")
        bar.value = 3
        editor.take(bar.preview)
        #expect(editor.svg == SketchEditing.removeStrokes(Self.svg(4), [0]))
        let again = await model.importanceOrder(runDir: editor.runDir, svg: editor.svg)
        #expect(try again.get() == [0, 1, 2, 3])  // (the fake engine's: measured once)
        let failing = try #require(SketchEditor.load(runDir: try Self.run("fails")))
        let broken = model.openSimplify(failing)
        try await ModelFlowTests.wait("the failure") { !broken.measuring }
        #expect(broken.problem == "RuntimeError: no CLIP" && model.importanceState?.status == "failed")
        #expect(model.openSteps(editor)?.frames.count == 3)
        await model.stopEngine()
    }
}
