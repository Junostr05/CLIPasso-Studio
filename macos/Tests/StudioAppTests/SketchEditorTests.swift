import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// Touching up a finished sketch (studio.py's eraser and pen): edited.svg written and removed as the Python studio does
/// it, one step back per press of the eraser and per stroke of the pen, the original kept – and a result's runs, the
/// one shown and the one chosen.
@Suite struct SketchEditorTests {
    /// A copy of the fixture job done_clipasso to work on: three runs, the best one (seed 1000) touched up.
    static func job() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "edit-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let job = dir.appending(path: "done_clipasso", directoryHint: .isDirectory)  // (the name: its paths are rebased)
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs/done_clipasso"), to: job)
        return job
    }

    static func text(_ url: URL) -> String? { try? String(contentsOf: url, encoding: .utf8) }

    @Test func aResultShowsItsBestSketchAsTouchedUp() throws {
        let job = try Self.job()
        let result = try #require(StudioResult(jobDir: job))
        #expect(result.runs.map(\.name) == ["Kamel_16strokes_seed0", "Kamel_16strokes_seed1000", "Kamel_16strokes_seed2000"])
        #expect(result.runs.map(\.seed) == [0, 1000, 2000])
        #expect(result.selected == "Kamel_16strokes_seed1000" && result.bestRun == result.selected)
        let best = job.appending(path: "Kamel_16strokes_seed1000")
        #expect(result.runs[1].runDir.standardizedFileURL.path == best.standardizedFileURL.path)  // (rebased)
        let editor = try #require(result.editor)
        #expect(editor.svg == Self.text(best.appending(path: "edited.svg")) && editor.isEdited)
        #expect(editor.original == Self.text(best.appending(path: "best_iter.svg")))
        #expect(StudioResult(jobDir: job.deletingLastPathComponent()) == nil)  // (no job there)
    }

    @Test func backToTheOriginalAndForth() throws {
        let editor = try #require(StudioResult(jobDir: Self.job())?.editor)
        let edited = editor.runDir.appending(path: "edited.svg")
        let touched = editor.svg
        editor.revert()
        #expect(editor.svg == editor.original && !editor.isEdited)
        #expect(!FileManager.default.fileExists(atPath: edited.path))  // the original again: no edited.svg
        #expect(editor.canUndo && !editor.canRedo)
        editor.revert()  // (it is the original: no step)
        editor.undo()
        #expect(editor.svg == touched && editor.isEdited && Self.text(edited) == touched)
        #expect(!editor.canUndo && editor.canRedo)
        editor.redo()
        #expect(editor.svg == editor.original && !editor.isEdited)
    }

    @Test func aPressOfTheEraserIsOneStep() throws {
        let result = try #require(StudioResult(jobDir: Self.job()))
        result.select("Kamel_16strokes_seed0")
        let editor = try #require(result.editor)
        let drawn = editor.svg
        #expect(editor.strokeCount == 2 && editor.canErase && !editor.isEdited)
        editor.beginErase()
        editor.erase(7)  // (no such stroke)
        editor.endErase()
        #expect(!editor.canUndo && editor.svg == drawn)  // a click beside every stroke is no step
        editor.beginErase()
        editor.erase(1)
        editor.erase(0)  // dragged on over the other one
        editor.endErase()
        #expect(editor.strokeCount == 0 && editor.isEdited)
        #expect(Self.text(editor.runDir.appending(path: "edited.svg")) == editor.svg)
        editor.undo()  // both back in one step
        #expect(editor.svg == drawn && !editor.isEdited && !editor.canUndo)
        editor.erase(0)  // (the eraser is not pressed)
        #expect(editor.svg == drawn)
    }

    @Test func thePenDrawsAStrokeThatStays() throws {
        let result = try #require(StudioResult(jobDir: Self.job()))
        result.select("Kamel_16strokes_seed2000")
        let editor = try #require(result.editor)
        let drawn = editor.svg
        editor.draw([SketchPoint(x: 20, y: 20), SketchPoint(x: 60, y: 90), SketchPoint(x: 120, y: 40)])
        #expect(editor.strokeCount == 3 && SketchEditing.fixedCount(editor.svg) == 1 && editor.isEdited)
        editor.draw([SketchPoint(x: 5, y: 5)])  // (one point: no stroke, no step)
        editor.undo()
        #expect(editor.svg == drawn && !editor.canUndo && editor.canRedo)
        result.select("Kamel_16strokes_seed1000")  // another sketch and back: each keeps its steps
        result.select("Kamel_16strokes_seed2000")
        #expect(result.editor === editor && editor.canRedo)
        result.select("no such run")
        #expect(result.selected == "Kamel_16strokes_seed2000")
    }
}
