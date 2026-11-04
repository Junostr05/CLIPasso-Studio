import Foundation
import Observation
import StudioCore

/// Touching up a finished sketch in the studio (studio.py: the eraser, the pen, undo, redo, back to the original).
/// The sketch as it was drawn (best_iter.svg) stays; the touched-up one is edited.svg in the run's folder – written
/// after each change and removed again when the sketch is the original once more (studio._save_edit). One step back
/// per press of the eraser, however many strokes it took, and per stroke of the pen.
@Observable
public final class SketchEditor {
    public let runDir: URL
    /// the sketch as it is now (SVG)
    public private(set) var svg: String
    public private(set) var canUndo = false
    public private(set) var canRedo = false
    /// edited.svg is there: the sketch is not the one drawn
    public private(set) var isEdited: Bool
    /// what went wrong writing edited.svg ("" when nothing did)
    public private(set) var problem = ""
    @ObservationIgnored private var undoStack: [String] = [] { didSet { canUndo = !undoStack.isEmpty } }
    @ObservationIgnored private var redoStack: [String] = [] { didSet { canRedo = !redoStack.isEmpty } }
    /// during a press of the eraser: whether it took a stroke yet
    @ObservationIgnored private var erasing: Bool?

    static let originalFile = "best_iter.svg"

    /// The run's sketch – the touched-up one if there is one; nil without a finished sketch (studio._editable_seed).
    public static func load(runDir: URL) -> SketchEditor? {
        guard let drawn = try? String(contentsOf: runDir.appending(path: originalFile), encoding: .utf8) else { return nil }
        let edited = try? String(contentsOf: runDir.appending(path: JobFolder.editedFile), encoding: .utf8)
        return SketchEditor(runDir: runDir, svg: edited ?? drawn, isEdited: edited != nil)
    }

    init(runDir: URL, svg: String, isEdited: Bool) {
        self.runDir = runDir
        self.svg = svg
        self.isEdited = isEdited
    }

    /// The sketch as it was drawn (read again each time, as the studio does).
    public var original: String? {
        try? String(contentsOf: runDir.appending(path: Self.originalFile), encoding: .utf8)
    }

    public var strokeCount: Int { SketchEditing.count(svg) }

    /// A sketch of one line has nothing to erase but the whole drawing.
    public var canErase: Bool { strokeCount > 1 }

    // MARK: - the eraser

    public func beginErase() {
        erasing = false
    }

    /// The stroke `index` goes (while the eraser is pressed: dragged over strokes, it takes several).
    public func erase(_ index: Int) {
        guard let took = erasing else { return }
        let next = SketchEditing.removeStrokes(svg, [index])
        guard next != svg else { return }
        if !took {
            undoStack.append(svg)
            redoStack = []
            erasing = true
        }
        svg = next
    }

    /// The press is over: saved when it took a stroke (a click beside every stroke is no step).
    public func endErase() {
        if erasing == true { save() }
        erasing = nil
    }

    // MARK: - the pen, undo, redo, the original

    /// A stroke drawn through `points` (the sketch's coordinates), kept where it is when CLIPasso continues.
    public func draw(_ points: [SketchPoint]) {
        let next = SketchEditing.appendStroke(svg, points: points)
        if next != svg { change(to: next) }
    }

    public func undo() {
        guard let last = undoStack.popLast() else { return }
        redoStack.append(svg)
        svg = last
        save()
    }

    public func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(svg)
        svg = next
        save()
    }

    /// Back to the sketch as it was drawn – a step that can be undone.
    public func revert() {
        guard let original, original != svg else { return }
        change(to: original)
    }

    private func change(to next: String) {
        undoStack.append(svg)
        redoStack = []
        svg = next
        save()
    }

    /// studio._save_edit: edited.svg written, or removed when the sketch is the original again.
    private func save() {
        let edited = runDir.appending(path: JobFolder.editedFile)
        do {
            if svg == original {
                if FileManager.default.fileExists(atPath: edited.path) { try FileManager.default.removeItem(at: edited) }
            } else {
                try JobFolder.writeAtomically(svg, to: edited)
            }
            problem = ""
        } catch {
            problem = String(describing: error)
        }
        isEdited = FileManager.default.fileExists(atPath: edited.path)
    }
}

/// A finished job shown in the studio: its sketches, one per run of its job.json, and the one shown – the best, or the
/// one chosen – which can be touched up. Each run keeps its own steps back while the job is shown.
@Observable
public final class StudioResult {
    public struct Run: Sendable, Hashable, Identifiable {
        public var id: String { name }
        public let name: String
        public let seed: Int
        public let runDir: URL
    }

    public let jobDir: URL
    public let runs: [Run]
    /// the run job.json calls the best
    public let bestRun: String
    public private(set) var selected: String
    /// the shown run's sketch (nil: it has no finished sketch)
    public private(set) var editor: SketchEditor?
    @ObservationIgnored private var editors: [String: SketchEditor] = [:]

    /// nil for a folder without a job or without runs.
    public init?(jobDir: URL) {
        guard let summary = JobFolder.summary(at: jobDir) else { return nil }
        let runs = summary.runs.compactMap { run -> Run? in
            guard let name = run["run_name"]?.stringValue, let dir = run["run_dir"]?.stringValue, !dir.isEmpty else {
                return nil
            }
            return Run(name: name, seed: run["seed"]?.intValue ?? 0, runDir: URL(filePath: dir, directoryHint: .isDirectory))
        }
        guard let first = runs.first else { return nil }
        self.jobDir = jobDir
        self.runs = runs
        bestRun = summary.bestRun
        selected = runs.contains { $0.name == summary.bestRun } ? summary.bestRun : first.name
        select(selected)
    }

    public func select(_ name: String) {
        guard let run = runs.first(where: { $0.name == name }) else { return }
        selected = name
        if editors[name] == nil { editors[name] = SketchEditor.load(runDir: run.runDir) }
        editor = editors[name]
    }
}
