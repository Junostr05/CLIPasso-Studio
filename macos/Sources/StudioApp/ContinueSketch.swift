import Foundation
import StudioCore

/// "Continue with CLIPasso" (the studio's ContinueDialog, gui/continuing.py): a new CLIPasso job that starts from a
/// finished sketch – its strokes are optimised further (the ones drawn by hand stay where they are, if wished), and
/// new strokes can be added. The engine prepares the job as the studio does; it goes into the queue.
public struct ContinueInfo: Sendable, Equatable {
    /// the sketch's strokes as CLIPasso loads them, and those drawn by hand
    public let strokes: Int
    public let fixed: Int
    /// the sketch's input is there (without it the strokes would not line up)
    public let canContinue: Bool
    /// the dialog's start values
    public let new: Int
    public let iterations: Int

    /// ContinueDialog's ranges
    public static let newRange = 0 ... 128
    public static let iterationRange = 1 ... 20000
    /// continuing.NEW_STROKES / ITERATIONS (the phone's start values without asking the engine; a test checks them)
    public static let startNew = 4
    public static let startIterations = 501
}

public extension AppModel {
    /// What the dialog shows of the sketch (nil without the engine or the sketch).
    func continueInfo(_ editor: SketchEditor) async -> ContinueInfo? {
        guard let engine,
              let o = try? await engine.request("continue_sketch", ["run_dir": .string(editor.runDir.path),
                                                                    "dry": true]).objectValue
        else { return nil }
        return ContinueInfo(strokes: o["strokes"]?.intValue ?? 0, fixed: o["fixed"]?.intValue ?? 0,
                            canContinue: o["can_continue"]?.truthy ?? false,
                            new: o["new"]?.intValue ?? ContinueInfo.startNew,
                            iterations: o["iterations"]?.intValue ?? ContinueInfo.startIterations)
    }

    /// The job that continues the sketch, into the queue (it starts at once when nothing runs); whether it waits
    /// behind another job.
    @discardableResult
    func continueSketch(_ editor: SketchEditor, new: Int, iterations: Int, keep: Bool) async throws -> Bool {
        guard let engine, let queue else { throw EngineFailure(code: "engine_gone", message: "the engine is not running") }
        // (the studio's CLIPasso settings, as all_settings()["clipasso"]: without the method's key)
        let clipasso = JSONObject(studio.settings(for: "clipasso").filter { $0.key != "method" }.map { ($0.key, $0.value) })
        let answer = try await engine.request("continue_sketch", [
            "run_dir": .string(editor.runDir.path),
            "new": .int(min(max(new, ContinueInfo.newRange.lowerBound), ContinueInfo.newRange.upperBound)),
            "iterations": .int(min(max(iterations, ContinueInfo.iterationRange.lowerBound),
                                   ContinueInfo.iterationRange.upperBound)),
            "keep": .bool(keep), "settings": .object(clipasso), "output_dir": .string(settings.outputDir.path),
        ])
        guard let image = answer.objectValue?["image"]?.stringValue,
              let prepared = answer.objectValue?["settings"]?.objectValue
        else { throw EngineFailure(code: "bad_answer", message: "the engine prepared no job") }
        let busy = queueSnapshot?.jobs.contains { $0.isActive } ?? false
        await queue.add(target: URL(filePath: image), settings: prepared)
        apply(await queue.snapshot())
        return busy
    }
}
