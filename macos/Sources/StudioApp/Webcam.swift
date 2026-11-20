import Foundation
import Observation
import StudioCore

/// A photo from the Mac's camera as the studio's picture (dialogs.WebcamDialog): a live picture, the camera to use,
/// mirrored if wished (webcam_mirror, as in the studio's settings), a countdown of three seconds, then the picture is
/// kept in the output folder's _webcam and used in the studio. The camera itself is the window's (AVFoundation).
@Observable
public final class WebcamModel {
    /// WebcamDialog.COUNTDOWN
    public static let countdownSeconds = 3

    /// the seconds left before the picture is taken (0: no countdown)
    public private(set) var left = 0
    /// for the tests: how a second passes
    @ObservationIgnored var sleep: @Sendable () async throws -> Void = { try await Task.sleep(for: .seconds(1)) }

    public init() {}

    /// _start_countdown / _tick: 3, 2, 1 – then true (the picture is to be taken); false when it was cancelled.
    public func countdown() async -> Bool {
        left = Self.countdownSeconds
        defer { left = 0 }
        while left > 0 {
            do { try await sleep() } catch { return false }
            left -= 1
        }
        return true
    }

    /// take: webcam-<date>.png in `folder`, -2, -3 … when it is there already.
    public nonisolated static func photoURL(in folder: URL, at date: Date = Date(),
                                            exists: (URL) -> Bool = { FileManager.default.fileExists(atPath: $0.path) })
        -> URL
    {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyyMMdd-HHmmss"
        let stamp = format.string(from: date)
        var url = folder.appending(path: "webcam-\(stamp).png")
        var n = 1
        while exists(url) {
            n += 1
            url = folder.appending(path: "webcam-\(stamp)-\(n).png")
        }
        return url
    }
}

public extension AppModel {
    /// webcam_mirror (on at first): the picture as in a mirror, as people expect to see themselves.
    var webcamMirror: Bool { settings["webcam_mirror"]?.truthy ?? true }

    func setWebcamMirror(_ on: Bool) {
        _ = updateSettings { $0["webcam_mirror"] = .bool(on) }
    }

    /// Where the photos go: the output folder's _webcam.
    var webcamFolder: URL { settings.outputDir.appending(path: "_webcam", directoryHint: .isDirectory) }

    #if canImport(ImageIO) && canImport(CoreGraphics)
        /// The camera's picture kept (mirrored if wished) and used as the studio's picture; its file.
        @discardableResult
        func useWebcamPhoto(_ picture: PixelImage) throws -> URL {
            let image = webcamMirror ? picture.mirrored() : picture
            guard let png = image.png() else { throw CocoaError(.fileWriteUnknown) }
            try FileManager.default.createDirectory(at: webcamFolder, withIntermediateDirectories: true)
            let url = WebcamModel.photoURL(in: webcamFolder)
            try png.write(to: url, options: .withoutOverwriting)
            studio.image = url
            return url
        }
    #endif
}
