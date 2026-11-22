import Foundation
import StudioCore

/// The studio's recent pictures and samples (pages/studio.py): every picture chosen heads "recent" (not the bundled
/// samples) and is the last one – the studio starts with it again, or with the camel.
public extension AppModel {
    /// The bundled sample pictures, by name (resources/samples: PNG and JPEG).
    var samplePictures: [URL] {
        guard let dir = resources.web?.appending(path: "samples", directoryHint: .isDirectory),
              let names = try? FileManager.default.contentsOfDirectory(atPath: dir.path)
        else { return [] }
        return names.filter { [".png", ".jpg", ".jpeg"].contains(where: $0.lowercased().hasSuffix) }.sorted()
            .map { dir.appending(path: $0) }
    }

    /// The recent pictures that are still there (the others leave the list).
    var recentPictures: [URL] {
        let saved = (settings["recent_images"]?.arrayValue ?? []).compactMap(\.stringValue)
        return saved.filter { FileManager.default.fileExists(atPath: $0) }.map { URL(filePath: $0) }
    }

    /// _remember_recent and last_image: a picture that is there heads the list and is the last one.
    internal func rememberImage(_ url: URL?) {
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return }
        let samples = resources.web?.appending(path: "samples").path ?? ""
        let saved = (settings["recent_images"]?.arrayValue ?? []).compactMap(\.stringValue)
        let recent = RecentImages.remember(url.path, in: saved.filter { FileManager.default.fileExists(atPath: $0) },
                                           samples: samples)
        updateSettings { s in
            if let recent { s["recent_images"] = .array(recent.map(JSONValue.string)) }
            s["last_image"] = .string(url.path)
        }
    }

    /// At the start (load_state): the last picture, else the camel of the samples.
    func restoreLastImage() {
        guard studio.image == nil else { return }
        if let last = settings["last_image"]?.stringValue, !last.isEmpty, FileManager.default.fileExists(atPath: last) {
            studio.image = URL(filePath: last)
        } else {
            studio.image = samplePictures.first { $0.lastPathComponent == "camel.png" }
        }
    }
}
