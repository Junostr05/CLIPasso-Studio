import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// Touching up the shown sketch from the phone (phone_api 3.8): the edit state the page reads, the eraser and the pen
/// (one step back each), Simplify measured by the engine, the saved steps – one taken as the result.
@Suite(.serialized) struct PhoneEditTests {
    @Test func theShownSketchFromThePhone() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let job = FileManager.default.temporaryDirectory.appending(path: "phone-edit-\(UUID().uuidString)/done_clipasso")
        try FileManager.default.createDirectory(at: job.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: done, to: job)
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de"))
        await model.startEngine()
        func ask(_ action: String, _ data: JSONObject = [:]) async -> JSONObject? {
            PhoneRemoteTests.json(await model.phoneAnswer(action, data, payload: nil))
        }
        let t = model.texts
        #expect(model.phoneEditState() == .null)
        #expect(await ask("do_edit", ["op": "undo"]) == ["ok": false, "error": .string(t.tr("ui.phone.page.edit_none"))])

        model.studio.reload(job)
        let editor = try #require(model.studio.result?.editor)
        let original = editor.svg
        var state = try #require(model.phoneEditState().objectValue)
        #expect(state["seed"] == 1000 && state["strokes"] == 2 && state["can_erase"] == true && state["undo"] == false)
        #expect(state["simplify"] == "none" && state["can_continue"] == false)
        #expect(model.phoneStudio()["edit"] == .object(state))

        // the pen: a stroke of its own; the eraser: the stroke under the finger (10,20 → 200.5,30.25 of 224)
        let pen = await ask("do_edit", ["op": "pen", "points": [[0.1, 0.5], [0.5, 0.6], [0.9, 0.5]]])
        #expect(pen == ["ok": true, "changed": true] && SketchEditing.count(editor.svg) == 3)
        #expect(await ask("do_edit", ["op": "pen", "points": [[0.1, 0.5]]])?["ok"] == false)
        _ = await ask("do_edit", ["op": "undo"])
        #expect(editor.svg == original)
        let erased = await ask("do_edit", ["op": "erase", "points": [[.double(105.0 / 224), .double(25.1 / 224)]]])
        #expect(erased == ["ok": true, "erased": 1] && SketchEditing.count(editor.svg) == 1)
        #expect(await ask("do_edit", ["op": "erase", "points": [[0.5, 0.5]]])?["error"]
            == .string(t.tr("ui.phone.page.edit_one_line")))
        _ = await ask("do_edit", ["op": "revert"])  // (back to the sketch as drawn: the fixture's was touched up)
        let drawn = try #require(editor.original)
        #expect(drawn != original && editor.svg == drawn && !editor.isEdited)
        #expect(model.phoneEditState().objectValue?["redo"] == false)

        // Simplify: measured by the engine (the fake one: the later strokes count more), then kept and taken
        #expect(await ask("file_simplified", ["keep": 1])?["error"] == .string(t.tr("ui.edit_bar.measuring")))
        #expect(await ask("do_simplify_measure") == ["ok": true, "ready": false])
        try await ModelFlowTests.wait("the measuring") { model.importanceState?.status == "ready" }
        state = try #require(model.phoneEditState().objectValue)
        #expect(state["simplify"] == "ready")
        #expect(await ask("do_simplify_measure") == ["ok": true, "ready": true])
        guard case .bytes(let simplified, "image/svg+xml", _) = await model.phoneAnswer("file_simplified", ["keep": "1"],
                                                                                         payload: nil)
        else { Issue.record("no simplified sketch"); return }
        #expect(String(decoding: simplified, as: UTF8.self).contains("<svg"))
        #expect(await ask("do_simplify_apply", ["keep": 1]) == ["ok": true])
        #expect(editor.svg == SketchEditing.removeStrokes(drawn, [0]) && editor.canUndo)
        editor.undo()

        // the saved steps
        let logs = editor.runDir.appending(path: "svg_logs")
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        try Data(EditBarTests.svg(1).utf8).write(to: logs.appending(path: "svg_iter0.svg"))
        try Data(EditBarTests.svg(3).utf8).write(to: logs.appending(path: "svg_iter10.svg"))
        #expect(await ask("get_steps") == ["ok": true, "seed": 1000, "count": 2, "lapse": 2])
        guard case .bytes(_, "image/svg+xml", _) = await model.phoneAnswer("file_step", ["i": "1", "lapse": "1"],
                                                                            payload: nil)
        else { Issue.record("no step"); return }
        #expect(await ask("file_step", ["i": "7"])?["error"] == .string(t.tr("ui.edit_bar.no_steps")))
        #expect(await ask("do_take_step", ["i": 0]) == ["ok": true])
        #expect(editor.svg == EditBarTests.svg(1) && editor.isEdited)
        await model.stopEngine()
    }
}
