import Foundation
import Synchronization
import Testing
@testable import StudioCore

/// The gallery finds, searches, filters and sorts results as the studio's gallery does (gui/pages/gallery.py), and
/// reads a finished job again only when one of its files changed.
@Suite struct GalleryIndexTests {
    let schema: ParamSchema

    init() throws {
        schema = try ParamSchema.load(Fixtures.url("schema.json"))
    }

    func names(_ items: [GalleryItem]) -> [String] { items.map(\.jobDir.lastPathComponent) }

    @Test func scanFindsFixtureJobs() async throws {
        let jobs = try JobFolderTests.copyOfJobs()
        try FileManager.default.createDirectory(at: jobs.appending(path: "not a job"), withIntermediateDirectories: true)
        try Data("x".utf8).write(to: jobs.appending(path: "a file.txt"))
        let index = GalleryIndex(root: jobs, schema: schema)
        let items = await index.refresh()
        #expect(Set(names(items)) == ["done_clipasso", "interrupted_swiftsketch", "scenesketch_matrix",
                                      "windows_paths", "old_2x"])
        let byName = Dictionary(uniqueKeysWithValues: items.map { ($0.jobDir.lastPathComponent, $0) })
        #expect(byName["done_clipasso"]?.name == "Kamel am Abend – Skizze ✏️")
        #expect(byName["interrupted_swiftsketch"]?.name == "Giraffe")  // no title: the image's name
        #expect(byName["windows_paths"]?.name == "Giraffe – von Jürgens PC")
        #expect(byName["interrupted_swiftsketch"]?.strokes == 32 && byName["done_clipasso"]?.strokes == 16)
        #expect(byName["interrupted_swiftsketch"]?.score == 28.75)
        #expect(byName["done_clipasso"]?.bestSketch?.lastPathComponent == "edited.svg")
    }

    @Test(arguments: [
        ("wüste", ["done_clipasso"]),
        ("SwiftSketch", ["interrupted_swiftsketch"]),
        ("swiftsketch giraffe", ["interrupted_swiftsketch"]),
        ("jürgens", ["windows_paths"]),
        ("scenesketch_matrix", ["scenesketch_matrix"]),
        ("kamel   abend", ["done_clipasso"]),
        ("album „tiere“", ["done_clipasso"]),  // (the notes: "Für das Album „Tiere“")
        ("zebra", []),
        ("", ["done_clipasso", "interrupted_swiftsketch", "old_2x", "scenesketch_matrix", "windows_paths"]),
    ])
    func searchLikeTheQtGallery(text: String, found: [String]) async throws {
        let index = GalleryIndex(root: try JobFolderTests.copyOfJobs(), schema: schema)
        _ = await index.refresh()
        let items = await index.items(GalleryQuery(text: text, sort: .name))
        #expect(Set(names(items)) == Set(found))
    }

    @Test func filters() async throws {
        let index = GalleryIndex(root: try JobFolderTests.copyOfJobs(), schema: schema)
        _ = await index.refresh()
        #expect(Set(names(await index.items(GalleryQuery(method: "clipasso")))) ==
            ["done_clipasso", "windows_paths", "old_2x"])
        #expect(Set(names(await index.items(GalleryQuery(favouritesOnly: true)))) == ["done_clipasso", "old_2x"])
        #expect(names(await index.items(GalleryQuery(tag: "Windows"))) == ["windows_paths"])
        #expect(names(await index.items(GalleryQuery(album: "Tiere"))) == ["done_clipasso"])
        #expect(await index.tags() == ["Tier", "Windows", "Wüste"])
        #expect(await index.albums() == ["Tiere"])
    }

    /// Job folders with the given created time, score, seconds and strokes (only job.json).
    static func makeJobs(_ specs: [(name: String, created: String, score: Double?, seconds: Double, strokes: Int)])
        throws -> URL
    {
        let root = FileManager.default.temporaryDirectory.appending(path: "gallery-\(UUID().uuidString)")
        for spec in specs {
            let dir = root.appending(path: spec.name)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let summary: JSONValue = [
                "target": .string("/Users/studio/Pictures/\(spec.name).png"), "created": .string(spec.created),
                "settings": ["method": "clipasso", "num_paths": .int(spec.strokes)], "method": "clipasso",
                "clip_score": spec.score.map(JSONValue.double) ?? .null, "seconds": .double(spec.seconds),
                "best_svg": "", "best_run": "", "runs": [],
            ]
            try Data(PyJSON.dump(summary, indent: 2).utf8).write(to: dir.appending(path: "job.json"))
        }
        return root
    }

    @Test func sortOrders() async throws {
        let root = try Self.makeJobs([
            ("b", "2026-01-02 10:00:00", 30.5, 12, 32), ("a", "2026-01-03 09:00:00", nil, 50, 8),
            ("C", "2026-01-01 08:00:00", 31.25, 12, 64), ("d", "2026-01-02 10:00:00", 30.5, 3, 16),
        ])
        let index = GalleryIndex(root: root, schema: schema)
        _ = await index.refresh()
        func order(_ sort: GallerySort) async -> [String] { names(await index.items(GalleryQuery(sort: sort))) }
        // (as Python's stable sort: equal keys keep the order of the folders' names, by code point: C a b d)
        #expect(await order(.newest) == ["a", "b", "d", "C"])
        #expect(await order(.oldest) == ["C", "b", "d", "a"])
        #expect(await order(.score) == ["C", "b", "d", "a"])  // a has no score: last
        #expect(await order(.duration) == ["a", "C", "b", "d"])
        #expect(await order(.strokes) == ["a", "d", "b", "C"])
        #expect(await order(.name) == ["a", "b", "C", "d"])  // without regard to case
    }

    @Test func secondRefreshReadsOnlyChanged() async throws {
        let specs = (0..<2000).map { (name: String(format: "job%04d", $0), created: "2026-01-01 00:00:00",
                                      score: Double?.none, seconds: 1.0, strokes: 16) }
        let root = try Self.makeJobs(specs)
        let unfinished = root.appending(path: "running")
        try FileManager.default.createDirectory(at: unfinished, withIntermediateDirectories: true)
        try Data(#"{"target": "/x/a.png", "settings": {}, "seeds": [0], "status": "running"}"#.utf8)
            .write(to: unfinished.appending(path: "job_state.json"))
        let reads = Mutex(0)
        let index = GalleryIndex(root: root, schema: schema) { dir in
            reads.withLock { $0 += 1 }
            return JobFolder.summary(at: dir)
        }
        #expect(await index.refresh().count == 2001)
        #expect(reads.withLock { $0 } == 2001)
        _ = await index.refresh()
        #expect(reads.withLock { $0 } == 2002)  // only the unfinished one (its sketches come one by one)
        try await Task.sleep(for: .milliseconds(20))
        _ = try JobFolder.writeMeta(at: root.appending(path: "job0007"), [("favourite", true)])
        _ = await index.refresh()
        #expect(reads.withLock { $0 } == 2004)
        try FileManager.default.removeItem(at: root.appending(path: "job0008"))
        #expect(await index.refresh().count == 2000)
    }

    @Test func settersWriteMeta() async throws {
        let jobs = try JobFolderTests.copyOfJobs()
        let index = GalleryIndex(root: jobs, schema: schema)
        _ = await index.refresh()
        let done = jobs.appending(path: "done_clipasso")
        try await index.setFavourite(done, false)
        try await index.setTitle(done, "  ")  // empty: the image's name again
        try await index.setTags(done, ["Abend"])
        try await index.setNotes(done, "Neu")
        try await index.setAlbums(done, [])
        let item = try #require(await index.items(GalleryQuery()).first { $0.jobDir == done })
        #expect(!item.favourite && item.name == "Kamel" && item.tags == ["Abend"] && item.notes == "Neu")
        #expect(item.albums.isEmpty)
        #expect(JobFolder.readMeta(at: done)["favourite"] == .bool(false))  // (a false favourite stays written)
        #expect(JobFolder.readMeta(at: done)["albums"] == nil && JobFolder.readMeta(at: done)["title"] == nil)
    }
}
