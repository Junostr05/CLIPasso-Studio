import Foundation
import StudioCore

/// Touching up the shown sketch from the phone (phone_api 3.8): the studio's eraser and pen, undo, redo, back to the
/// original, Simplify and the saved steps – the same steps as in the window, kept with the sketch.
public extension AppModel {
    /// phone_api.ERASE_REACH: the eraser on the phone hits this far (of the sketch's width) from a stroke
    nonisolated static let phoneEraseReach = 0.02
    /// phone_api.EDIT_POINTS: at most this many points of one stroke of the pen or the eraser
    nonisolated static let phoneEditPoints = 2000

    /// The sketch being touched up and its run's seed (nil: nothing to edit, e.g. while it is being drawn).
    private func phoneEditable() -> (seed: Int, editor: SketchEditor)? {
        guard let result = studio.result, let editor = result.editor,
              let run = result.runs.first(where: { $0.name == result.selected })
        else { return nil }
        return (run.seed, editor)
    }

    /// _edit_state: what the eraser, the pen, Simplify and the saved steps can do with the shown sketch.
    func phoneEditState() -> JSONValue {
        guard let editable = phoneEditable() else { return .null }
        let (seed, editor) = editable
        let svg = editor.svg
        let n = SketchEditing.count(svg)
        let simplify = importanceState.flatMap { $0.svg == svg ? $0.status : nil } ?? "none"
        let out: JSONObject = [
            "seed": .int(seed), "strokes": .int(n), "fixed": .int(SketchEditing.fixedCount(svg)),
            "can_erase": .bool(n > 1), "undo": .bool(editor.canUndo), "redo": .bool(editor.canRedo),
            "edited": .bool(editor.isEdited),
            // (continuing a sketch with CLIPasso is not in the Mac app yet: its box stays hidden)
            "can_continue": false, "continue": ["new": 4, "iterations": 501],
            "simplify": .string(simplify), "rev": .int(abs(svg.hashValue) % 10_000_000_000),
        ]
        return .object(out)
    }

    /// _points: the phone's points (0 … 1 of the sketch's width and height) in the sketch's own coordinates.
    nonisolated static func phonePoints(_ data: JSONObject, svg: String) -> [SketchPoint] {
        let box = SketchEditing.viewBox(svg)
        return (data["points"]?.arrayValue ?? []).prefix(phoneEditPoints).compactMap { p in
            guard let pair = p.arrayValue, pair.count >= 2, let x = pair[0].doubleValue, let y = pair[1].doubleValue,
                  (0 ... 1).contains(x), (0 ... 1).contains(y)
            else { return nil }
            return SketchPoint(x: box.x + x * box.width, y: box.y + y * box.height)
        }
    }

    /// The sketch as the phone shows it (_styled): the studio's background and brush style.
    private func phoneStyled(_ svg: String) async -> RemoteAnswer {
        let look = phoneLook()
        let stylist = stylist(look.style)
        let made = await Task.detached(executorPreference: OwnThreads.shared) { () -> String in
            let out = SketchExport.restyleSVG(svg, background: look.background)
            return (try? stylist(out)) ?? out
        }.value
        return .bytes(Data(made.utf8), type: "image/svg+xml", name: nil)
    }

    /// The strokes in their order of importance as measured for the sketch (nil: not measured).
    private func phoneOrder(_ editor: SketchEditor) async -> [Int]? {
        guard let engine,
              let answer = try? await engine.request("importance", ["run_dir": .string(editor.runDir.path)]),
              let order = Self.importanceOrder(answer), order.count == SketchEditing.count(editor.svg)
        else { return nil }
        return order
    }

    /// _kept: the sketch with only its `keep` most important strokes.
    private func phoneKept(_ editor: SketchEditor, _ data: JSONObject) async -> String? {
        guard let order = await phoneOrder(editor) else { return nil }
        let bar = EditBarModel(simplify: editor.svg, order: order)
        return bar.kept(max(1, data["keep"].flatMap { PhoneStudio.int($0) } ?? 1))
    }

    /// The saved steps (all of them, or up to the best: the time lapse).
    private func phoneFrames(_ editor: SketchEditor, lapse: Bool) -> [URL] {
        SketchAnimation.steps(runDir: editor.runDir, uptoBest: lapse)
    }

    /// The phone's actions on the shown sketch; nil: not one of them.
    internal func phoneEditAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let editActions = ["do_edit", "do_simplify_measure", "file_simplified", "do_simplify_apply", "get_steps",
                           "file_step", "do_take_step"]
        guard editActions.contains(action) else { return nil }
        guard let editable = phoneEditable() else { return no(texts.tr("ui.phone.page.edit_none")) }
        let (seed, editor) = editable
        defer { phone.changed() }
        switch action {
        case "do_edit":
            let op = data["op"]?.stringValue ?? ""
            switch op {
            case "undo": editor.undo()
            case "redo": editor.redo()
            case "revert": editor.revert()
            case "pen":
                let points = Self.phonePoints(data, svg: editor.svg)
                guard points.count >= 2 else { return no(texts.tr("ui.phone.page.edit_too_short")) }
                let before = editor.svg
                editor.draw(points)
                return .json(["ok": true, "changed": .bool(editor.svg != before)])
            case "erase":
                guard editor.canErase else { return no(texts.tr("ui.phone.page.edit_one_line")) }
                let points = Self.phonePoints(data, svg: editor.svg)
                let reach = Self.phoneEraseReach * SketchEditing.viewBox(editor.svg).width
                editor.beginErase()
                var erased = 0
                var index: SketchEditing.StrokeIndex?
                for p in points {
                    let strokes = index ?? SketchEditing.StrokeIndex(svg: editor.svg)
                    index = strokes
                    if let hit = strokes.hit(x: p.x, y: p.y, tolerance: reach), strokes.count > 1 {
                        editor.erase(hit)
                        erased += 1
                        index = nil  // (the strokes are counted anew)
                    }
                }
                editor.endErase()
                return .json(["ok": true, "erased": .int(erased)])
            default:
                return no("unknown edit")
            }
            return .json(["ok": true])
        case "do_simplify_measure":  // (measured once per sketch, by the engine in a process of its own)
            if await phoneOrder(editor) != nil {
                importanceState = (editor.svg, "ready")
                return .json(["ok": true, "ready": true])
            }
            if let state = importanceState, state.svg == editor.svg, state.status == "measuring" {
                return .json(["ok": true, "ready": false])
            }
            let (run, svg) = (editor.runDir, editor.svg)
            importanceState = (svg, "measuring")
            Task {
                _ = await importanceOrder(runDir: run, svg: svg)
                phone.changed()
            }
            return .json(["ok": true, "ready": false])
        case "file_simplified":
            guard let kept = await phoneKept(editor, data) else { return no(texts.tr("ui.edit_bar.measuring")) }
            return await phoneStyled(kept)
        case "do_simplify_apply":
            guard let kept = await phoneKept(editor, data) else { return no(texts.tr("ui.edit_bar.measuring")) }
            editor.take(kept)
            return .json(["ok": true])
        case "get_steps":
            return .json(["ok": true, "seed": .int(seed), "count": .int(phoneFrames(editor, lapse: false).count),
                          "lapse": .int(phoneFrames(editor, lapse: true).count)])
        case "file_step", "do_take_step":
            let frames = phoneFrames(editor, lapse: action == "file_step" && data["lapse"] == "1")
            guard let i = data["i"].flatMap({ PhoneStudio.int($0) }), frames.indices.contains(i),
                  let svg = try? String(contentsOf: frames[i], encoding: .utf8)
            else { return no(texts.tr("ui.edit_bar.no_steps")) }
            if action == "file_step" { return await phoneStyled(svg) }
            editor.take(svg)
            return .json(["ok": true])
        default:
            return nil
        }
    }
}
