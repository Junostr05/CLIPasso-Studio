import Foundation
import StudioCore

/// The animation export of the app (export_animation / export_drawing): GIF and MP4 drawn and written here, WebP's
/// frames drawn here and written by the engine with Pillow (ImageIO only reads WebP). The work runs off the main
/// actor; cancelling the calling task stops it between frames and leaves no file.
public extension AppModel {
    /// The animation in `url`; returns its number of frames. `progress` hears (frames drawn, frames), and (0, 0)
    /// while the engine writes a WebP.
    func exportAnimation(_ job: AnimationJob, to url: URL,
                         progress: @escaping @Sendable (Int, Int) -> Void = { _, _ in }) async throws -> Int
    {
        switch job.format {
        case .gif:
            return try kept(url, try await detached { try AnimationExporter.gif(job, to: url, progress: progress) })
        case .mp4:
            return try kept(url, try await detached { try await AnimationExporter.mp4(job, to: url, progress: progress) })
        case .webp:
            guard let engine else {
                throw EngineFailure(code: "engine_gone", message: "the engine is not running")
            }
            let folder = FileManager.default.temporaryDirectory.appending(path: "webp-\(UUID().uuidString)",
                                                                           directoryHint: .isDirectory)
            defer { try? FileManager.default.removeItem(at: folder) }
            let durations = try await detached { try AnimationExporter.pngFrames(job, to: folder, progress: progress) }
            try Task.checkCancellation()
            progress(0, 0)
            let frames = (0 ..< durations.count).map {
                JSONValue.string(folder.appending(path: String(format: "frame_%05d.png", $0)).path)
            }
            let background: JSONValue = job.options.background.flatMap { SketchSVG.color($0) }
                .map { .array([.int($0.r), .int($0.g), .int($0.b)]) } ?? .null
            do {
                _ = try await engine.request("encode_webp", ["frames": .array(frames),
                                                             "durations": .array(durations.map { .double($0) }),
                                                             "dest": .string(url.path), "background": background],
                                             timeout: .seconds(3600))
            } catch {
                try? FileManager.default.removeItem(at: url)
                throw error
            }
            if Task.isCancelled {  // (written before the cancel arrived: nothing half-wanted is kept)
                try? FileManager.default.removeItem(at: url)
                throw CancellationError()
            }
            return durations.count
        }
    }

    /// The file written – unless the cancel came after the last frame: then nothing half-wanted is kept either.
    private func kept(_ url: URL, _ count: Int) throws -> Int {
        guard Task.isCancelled else { return count }
        try? FileManager.default.removeItem(at: url)
        throw CancellationError()
    }

    /// Work off the main actor – on threads of its own, not the cooperative pool – that stops when the calling task
    /// is cancelled.
    private func detached<T: Sendable>(_ work: @escaping @Sendable () async throws -> T) async throws -> T {
        let task = Task.detached(executorPreference: OwnThreads.shared, operation: work)
        return try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
    }
}
