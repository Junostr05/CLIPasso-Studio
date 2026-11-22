import Foundation
import StudioCore

/// The gallery's results in the studio's brush style (thumbs.sketch_thumbnail): the engine draws a result's sketch
/// in canvas_style once; the drawing is kept beside settings.json (cache/thumbs, by the file, its time and size and
/// the style) and in memory, so the gallery asks again only for what changed. Plain, or without the engine: the
/// sketch as it is.
public extension AppModel {
    /// A result's sketch as the gallery shows it.
    func gallerySketch(_ url: URL) async -> Sketch? {
        let style = canvasStyle, stylist = stylist(canvasStyle)
        let cache = store.url.deletingLastPathComponent().appending(path: "cache/thumbs", directoryHint: .isDirectory)
        let key = Self.thumbnailKey(url, style: style)
        if let key, let hit = thumbnails.object(forKey: key as NSString) { return hit.sketch }
        let sketch = await Task.detached(executorPreference: OwnThreads.shared) { () -> Sketch? in
            guard let svg = try? String(contentsOf: url, encoding: .utf8) else { return nil }
            guard !stylist.isPlain, let key else { return try? SketchSVG.parse(svg) }
            let file = cache.appending(path: Sha256.hex(Data(key.utf8)) + ".svg")
            if let kept = try? String(contentsOf: file, encoding: .utf8), let sketch = try? SketchSVG.parse(kept) {
                return sketch
            }
            guard let styled = try? stylist(svg) else { return try? SketchSVG.parse(svg) }  // (no engine: plain)
            try? FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            try? Data(styled.utf8).write(to: file, options: .atomic)
            return try? SketchSVG.parse(styled)
        }.value
        if let key, let sketch { thumbnails.setObject(ThumbnailBox(sketch), forKey: key as NSString) }
        return sketch
    }

    /// (the file, its time in ns and size, the style) – nil when the file is not there.
    nonisolated static func thumbnailKey(_ url: URL, style: String) -> String? {
        guard let stamp = FolderWatch.stamp(url.path) else { return nil }
        return "\(url.path)|\(stamp[1])|\(stamp[0])|\(style)"
    }
}

/// A sketch kept in the thumbnails' memory cache (NSCache keeps objects).
final class ThumbnailBox: NSObject, @unchecked Sendable {
    let sketch: Sketch
    init(_ sketch: Sketch) {
        self.sketch = sketch
    }
}
