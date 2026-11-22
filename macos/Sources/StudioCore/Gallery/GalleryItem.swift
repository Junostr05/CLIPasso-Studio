import Foundation

/// One result of the gallery – what the studio's gallery shows of a job (gui/pages/gallery.py `GalleryItem`).
public struct GalleryItem: Sendable, Identifiable, Hashable {
    public var id: String { jobDir.path }
    public let jobDir: URL
    public let summary: JobSummary
    /// The method's name ("SwiftSketch") from the schema, for the search.
    public let methodName: String
    public let strokes: Int

    public var method: String { summary.method }

    /// The title – or the image's file name without its extension.
    public var name: String {
        let title = summary.title.trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty { return title }
        let target = summary.target.isEmpty ? jobDir.lastPathComponent : fileName(summary.target)
        return stem(target)
    }

    public var favourite: Bool { summary.favourite }
    public var tags: [String] { summary.tags }
    public var notes: String { summary.notes }
    public var albums: [String] { summary.albums }
    public var created: String { summary.created }
    public var state: String? { summary.state }

    /// The CLIP score of the job – or the best of its sketches.
    public var score: Double? {
        if let s = summary.clipScore { return s }
        return summary.runs.compactMap { $0["clip_score"]?.doubleValue }.max()
    }

    public var seconds: Double {
        if summary.seconds != 0 { return summary.seconds }
        return summary.runs.reduce(0) { $0 + ($1["seconds"]?.doubleValue ?? 0) }
    }

    public var bestSketch: URL? { JobFolder.bestSketch(summary) }
    public var canContinue: Bool { JobFolder.canContinue(summary) }

    /// All words of the search (in lower case) occur in the name, the folder's name, the image's file name, the
    /// method, its name, the tags and the notes.
    public func matches(_ words: [String]) -> Bool {
        let hay = [name, jobDir.lastPathComponent, fileName(summary.target), method, methodName,
                   tags.joined(separator: " "), notes].joined(separator: " ").lowercased()
        return words.allSatisfy { hay.contains($0) }
    }
}

/// os.path.splitext(name)[0]: without the last extension ("a.tar.gz" → "a.tar"; ".hidden" stays).
func stem(_ name: String) -> String {
    guard let dot = name.lastIndex(of: "."), dot != name.startIndex,
          name[..<dot].contains(where: { $0 != "." })
    else { return name }
    return String(name[..<dot])
}
