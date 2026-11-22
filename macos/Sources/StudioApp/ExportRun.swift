import Foundation
import StudioCore

/// An export as the window's sheet and the phone make it: the sketch, where it comes from, the format and its options.
public struct ExportRequest: Sendable {
    public var format: ExportOptions.Format
    public var svg: String
    public var runDir: URL?
    /// the job (the SceneSketch matrix)
    public var jobDir: URL?
    public var photo: SketchFraming.PhotoFrame?
    public var options: ExportOptions
    public var mode: SketchAnimation.Mode
    public var length: Double
    public var hold: Double
    /// the file's name without its extension (a PDF's title, a web page's)
    public var title: String
    /// the scene's two layers' names
    public var labels: (String, String)
    public var stylist: Stylist

    public init(format: ExportOptions.Format, svg: String, runDir: URL?, jobDir: URL?,
                photo: SketchFraming.PhotoFrame?, options: ExportOptions, mode: SketchAnimation.Mode, length: Double,
                hold: Double, title: String, labels: (String, String), stylist: Stylist)
    {
        (self.format, self.svg, self.runDir, self.jobDir, self.photo) = (format, svg, runDir, jobDir, photo)
        (self.options, self.mode, self.length, self.hold) = (options, mode, length, hold)
        (self.title, self.labels, self.stylist) = (title, labels, stylist)
    }
}

#if canImport(ImageIO) && canImport(CoreText)
    public extension AppModel {
        /// ExportDialog._save's work: the file in `url` – an animation drawn frame by frame, or a picture or a text
        /// made off the main actor. Cancelling the calling task leaves no half file. `progress` hears (done, total).
        func runExport(_ r: ExportRequest, to url: URL,
                       progress: @escaping @Sendable (Int, Int) -> Void = { _, _ in }) async throws
        {
            if let animation = r.format.animation {
                let job = AnimationJob(mode: r.mode, format: animation, options: r.options, length: r.length,
                                       hold: r.hold, svg: r.svg, runDir: r.runDir, photo: r.photo, stylist: r.stylist)
                _ = try await exportAnimation(job, to: url, progress: progress)
                return
            }
            let data = try await Self.offMain { () throws -> Data in
                switch r.format {
                case .png:
                    return try SketchExporter.png(r.svg, options: r.options, photo: r.photo, stylist: r.stylist)
                case .pdf:
                    return try SketchExporter.pdf(r.svg, options: r.options, photo: r.photo, title: r.title,
                                                  stylist: r.stylist)
                case .matrix:
                    guard let jobDir = r.jobDir else { throw ExportError(code: "export_no_sketches") }
                    return try MatrixExport.zip(jobDir: jobDir, options: r.options, stylist: r.stylist) {
                        progress($0, $1)
                    }
                default:
                    let text = try SketchExporter.text(r.svg, format: r.format, options: r.options, photo: r.photo,
                                                       runDir: r.runDir, length: r.length, hold: r.hold, name: r.title,
                                                       labels: r.labels, stylist: r.stylist)
                    return Data(text.utf8)
                }
            }
            try Task.checkCancellation()  // (made before the cancel arrived: nothing half-wanted is kept)
            try data.write(to: url, options: .atomic)
        }

        /// Work on threads of its own (the cooperative pool stays free) that stops when the calling task is cancelled.
        nonisolated static func offMain<T: Sendable>(_ work: @escaping @Sendable () throws -> T) async throws -> T {
            let task = Task.detached(executorPreference: OwnThreads.shared) { try work() }
            return try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
        }
    }
#endif
