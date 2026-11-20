import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The queue page's state on JobQueue: the order, removing, starting by itself and "when done".
@Suite struct QueueModelTests {
    @Test func reorderAndWhenDone() async throws {
        let engine = RecordingEngine()
        let queue = JobQueue(engine: engine, outputRoot: URL(filePath: "/tmp/out"))
        let model = QueueModel(queue: queue)
        await model.setAutoStart(false)
        #expect(model.snapshot.autoStart == false)
        var ids: [QueuedJob.ID] = []
        for name in ["a.png", "b.png", "c.png"] {
            ids.append(await queue.add(target: URL(filePath: "/Bilder/\(name)"), settings: ["method": "clipasso"]))
        }
        await model.reload()
        #expect(model.jobs.map(\.target.lastPathComponent) == ["a.png", "b.png", "c.png"])
        await model.move(ids[2], by: -1)
        #expect(model.jobs.map(\.target.lastPathComponent) == ["a.png", "c.png", "b.png"])
        await model.move(ids[0], by: -1)  // (the first stays first)
        #expect(model.jobs.first?.id == ids[0])
        await model.remove(ids[1])
        #expect(model.jobs.map(\.target.lastPathComponent) == ["a.png", "c.png"])
        #expect(await engine.requests.isEmpty)  // nothing started by itself
        await model.setWhenDone(.sleep)
        #expect(model.whenDone == .sleep)
        await model.setAutoStart(true)  // now the first one starts
        #expect(await engine.requests.contains { $0.op == "start" })
        #expect(model.jobs.first?.status == .running)
    }
}

/// The gallery page's state on GalleryIndex: search, filters and the order bound to the view, favourites written.
@Suite struct GalleryModelTests {
    static func folder() throws -> URL {
        let out = FileManager.default.temporaryDirectory.appending(path: "gallery-\(UUID().uuidString)")
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs"), to: out)
        return out
    }

    @Test func searchFiltersSort() async throws {
        let root = try Self.folder()
        let schema = try ParamSchema.load(SelfTestTests.fixtures.appending(path: "schema.json"))
        let gallery = GalleryModel(root: root, schema: schema)
        await gallery.refresh()
        let texts = try Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"), language: "en")
        let all = gallery.items.count
        #expect(all >= 4 && gallery.countText(texts) == "\(all) results in the output folder")
        gallery.query.method = "swiftsketch"
        #expect(gallery.items.allSatisfy { $0.method == "swiftsketch" } && gallery.items.count < all)
        #expect(gallery.countText(texts) == "\(gallery.items.count) of \(all) results")
        gallery.query = GalleryQuery()
        let first = try #require(gallery.items.first)
        gallery.query.text = String(first.name.prefix(3))
        #expect(gallery.items.contains(first))
        gallery.query = GalleryQuery(sort: .score)
        let scores = gallery.items.compactMap(\.score)
        #expect(scores == scores.sorted(by: >))
        // a favourite is written to meta.json and found by the filter
        let target = try #require(gallery.items.last)
        await gallery.setFavourite(target, true)
        gallery.query = GalleryQuery(favouritesOnly: true)
        #expect(gallery.items.map(\.id).contains(target.id))
        #expect(JobFolder.readMeta(at: target.jobDir)["favourite"] == true)
        await gallery.rename(target, "Kamel am Abend")
        #expect(gallery.items.first { $0.id == target.id }?.summary.title == "Kamel am Abend")
    }
}
