import Foundation
import StudioCore

/// SceneSketch: a cell of the shown job's matrix computed again with a new start (studio.rerun_scene_cell) – and
/// the later levels of its layer, which start from it; the job continues in the queue, the other cells stay.
public extension AppModel {
    /// The later levels a rerun of `cell` computes again too (the question before); nil when it cannot be rerun.
    func sceneCellLater(_ cell: Int) async -> [Int]? {
        guard let result = studio.result, canRerun(cell, in: result), let engine else { return nil }
        let answer = try? await engine.request("rerun_cell", ["job_dir": .string(result.jobDir.path),
                                                               "cell": .int(cell), "dry": true])
        return answer?.objectValue?["later"]?.arrayValue?.compactMap(\.intValue)
    }

    /// The rerun: the engine removes the cell and the later levels, the job is queued to continue, the shown result
    /// read again; the cells removed (nil when it cannot be done).
    @discardableResult
    func rerunSceneCell(_ cell: Int) async -> Int? {
        guard let result = studio.result, canRerun(cell, in: result), let engine, let queue,
              let state = JobFolder.readState(at: result.jobDir)
        else { return nil }
        guard let answer = try? await engine.request("rerun_cell", ["job_dir": .string(result.jobDir.path),
                                                                     "cell": .int(cell)]),
              let removed = answer.objectValue?["removed"]?.arrayValue
        else { return nil }
        // (continue_job: its input – the picture, or the copy in the job's folder – with the job's own settings)
        let given = state["target"]?.stringValue ?? ""
        let target = FileManager.default.fileExists(atPath: given) ? URL(filePath: given)
            : JobFolder.savedInput(jobDir: result.jobDir, target: given) ?? URL(filePath: given)
        await queue.addContinuation(jobDir: result.jobDir, target: target,
                                    settings: state["settings"]?.objectValue ?? [:])
        apply(await queue.snapshot())
        studio.reload(result.jobDir)
        return removed.count
    }

    /// _can_choose_best: a finished cell of a job that is not running or waiting.
    private func canRerun(_ cell: Int, in result: StudioResult) -> Bool {
        guard result.method == "scenesketch", result.run(cell: cell) != nil else { return false }
        let path = result.jobDir.standardizedFileURL.path
        let busy = (queueSnapshot?.jobs ?? []).contains { job in
            [.queued, .running, .paused].contains(job.status)
                && [job.resumeDir, job.jobDir].contains { $0?.standardizedFileURL.path == path }
        }
        return !busy
    }
}
