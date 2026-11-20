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
            let stretch = SketchFraming.runFrame(runDir: runDir)?.canvasStretch ?? 1
        #else
            let stretch = 1.0
        #endif
        stretches[key] = stretch
        return stretch
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
}
