import Foundation
import StudioCore

/// The methods draw on a square canvas made from the photo – stretched onto it unless fix_scale pads it (framing.py).
/// The window shows that canvas in the photo's shape again, so the photo, its views and the sketch on it are not
/// squeezed: how much wider than high it is shown (1: square). Only the view – the files stay as the method wrote
/// them (an export's "photo" frame does the same with the SVG).
public extension AppModel {
    /// A run's canvas, from the photo frame its config.json keeps (or worked out for an older run); kept per run.
    func canvasStretch(runDir: URL?) -> Double {
        guard let runDir else { return 1 }
        let key = runDir.path
        if let known = stretches[key] { return known }
        #if canImport(ImageIO)
            guard let frame = SketchFraming.runFrame(runDir: runDir) else { return 1 }  // (not known yet: asked again)
            stretches[key] = frame.canvasStretch
            return frame.canvasStretch
        #else
            return 1
        #endif
    }

    /// The canvas of the studio's job under way (its config.json may not be written yet): worked out from its picture
    /// and its settings as framing.guess_frame does; square when it cannot be known.
    var liveStretch: Double {
        guard let id = studio.live.jobID, let job = queueSnapshot?.jobs.first(where: { $0.id == id }) else { return 1 }
        let key = "live:\(job.target.path)|\(job.settings.hashValue)"
        if let known = stretches[key] { return known }
        #if canImport(ImageIO)
            let method = job.settings["method"]?.stringValue ?? schema.defaultMethod
            let stretch = SketchFraming.imageSize(job.target).flatMap {
                SketchFraming.guessFrame(method: method, settings: job.settings, width: $0.0, height: $0.1)
            }?.canvasStretch ?? 1
        #else
            let stretch = 1.0
        #endif
        stretches[key] = stretch
        return stretch
    }

    /// The run whose sketch stands for a result (its best run).
    nonisolated static func bestRunDir(_ item: GalleryItem) -> URL? {
        item.summary.runs.first { $0["run_name"]?.stringValue == item.summary.bestRun }?["run_dir"]?.stringValue
            .map { URL(filePath: $0, directoryHint: .isDirectory) }
    }

    /// The canvas of what the studio shows now: the run chosen of the finished job, else the job under way.
    var studioStretch: Double {
        if let result = studio.result, !studio.live.isActive {
            return canvasStretch(runDir: result.runs.first { $0.name == result.selected }?.runDir)
        }
        return liveStretch
    }

    /// The canvas of a sketch the phone asks for: its run's, or the job under way's.
    func phoneStretch(seed: Int?) -> Double {
        let wanted = seed ?? phoneShownSeed()
        guard let item = phoneSeeds().first(where: { $0.seed == wanted }) else { return studioStretch }
        return item.runDir.map { canvasStretch(runDir: $0) } ?? liveStretch
    }
}
