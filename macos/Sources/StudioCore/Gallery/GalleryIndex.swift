import Foundation

/// The jobs of the output folder for the gallery. A finished job is read again only when one of its files changed
/// (modification time or size of job.json, job_state.json or meta.json) – like the studio's `ScanCache`; an
/// unfinished one is read every time, its sketches appear one by one.
public actor GalleryIndex {
    public let root: URL
    private let schema: ParamSchema?
    private let read: @Sendable (URL) -> JobSummary?
    private var entries: [String: (stamp: [Stamp?], item: GalleryItem)] = [:]
    private var all: [GalleryItem] = []

    struct Stamp: Equatable {
        let modified: Date
        let size: Int
    }

    public init(root: URL, schema: ParamSchema?,
                read: @escaping @Sendable (URL) -> JobSummary? = { JobFolder.summary(at: $0) })
    {
        self.root = root
        self.schema = schema
        self.read = read
    }

    private static func stamp(_ url: URL) -> Stamp? {
        guard let a = try? FileManager.default.attributesOfItem(atPath: url.path),
              let modified = a[.modificationDate] as? Date, let size = (a[.size] as? NSNumber)?.intValue
        else { return nil }
        return Stamp(modified: modified, size: size)
    }

    /// Scan the folder again; the results in the order of their folders' names.
    @discardableResult
    public func refresh() -> [GalleryItem] {
        var items: [GalleryItem] = []
        var seen: Set<String> = []
        for name in JobFolder.names(in: root) {
            let dir = root.appending(path: name)
            let stamp = [JobFolder.summaryFile, JobFolder.stateFile, JobFolder.metaFile].map {
                Self.stamp(dir.appending(path: $0))
            }
            guard stamp[0] != nil || stamp[1] != nil else { continue }  // no job folder
            seen.insert(dir.path)
            if let cached = entries[dir.path], cached.stamp == stamp, stamp[0] != nil {
                items.append(cached.item)
                continue
            }
            guard let summary = read(dir) else { continue }
            let item = makeItem(dir, summary)
            entries[dir.path] = (stamp, item)
            items.append(item)
        }
        for key in entries.keys where !seen.contains(key) {
            entries[key] = nil
        }
        all = items
        return items
    }

    private func makeItem(_ dir: URL, _ summary: JobSummary) -> GalleryItem {
        let method = schema?.method(summary.method)
        let settings = summary.settings.merging(["method": .string(summary.method)])
        return GalleryItem(jobDir: dir, summary: summary, methodName: method?.name ?? summary.method,
                           strokes: method?.numStrokes(settings) ?? 0)
    }

    /// The results of the last scan that the query includes, in its order.
    public func items(_ query: GalleryQuery) -> [GalleryItem] {
        query.sorted(all.filter(query.includes))
    }

    /// Every tag of the results, sorted.
    public func tags() -> [String] {
        Set(all.flatMap(\.tags)).sorted()
    }

    /// Every album found in the results, sorted (the app's settings keep the albums' own order).
    public func albums() -> [String] {
        Set(all.flatMap(\.albums)).sorted()
    }

    // MARK: - the user's data (meta.json)

    private func change(_ dir: URL, _ changes: [(String, JSONValue?)]) throws {
        try JobFolder.writeMeta(at: dir, changes)
        entries[dir.path] = nil
        if let summary = read(dir) {
            let item = makeItem(dir, summary)
            all = all.map { $0.jobDir.path == dir.path ? item : $0 }
        }
    }

    public func setFavourite(_ dir: URL, _ value: Bool) throws {
        try change(dir, [("favourite", .bool(value))])
    }

    public func setTitle(_ dir: URL, _ title: String) throws {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        try change(dir, [("title", t.isEmpty ? nil : .string(t))])
    }

    public func setNotes(_ dir: URL, _ notes: String) throws {
        try change(dir, [("notes", notes.isEmpty ? nil : .string(notes))])
    }

    public func setTags(_ dir: URL, _ tags: [String]) throws {
        try change(dir, [("tags", tags.isEmpty ? nil : .array(tags.map(JSONValue.string)))])
    }

    public func setAlbums(_ dir: URL, _ albums: [String]) throws {
        try change(dir, [("albums", albums.isEmpty ? nil : .array(albums.map(JSONValue.string)))])
    }
}
