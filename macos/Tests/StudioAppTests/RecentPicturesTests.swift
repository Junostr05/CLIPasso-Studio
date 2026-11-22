import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The studio's recent pictures and samples: a picture chosen heads the list and is the last one, the start opens it
/// again (or the camel), samples and pictures that are gone never stay in the list.
@Suite(.serialized) struct RecentPicturesTests {
    @Test func rememberedAndRestored() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: "recent-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let a = dir.appending(path: "Kamel.png"), b = dir.appending(path: "Zebra.png")
        for url in [a, b] { try Data([1]).write(to: url) }
        let store = try AppModelTests.store(language: "de")
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store)
        #expect(model.samplePictures.map(\.lastPathComponent).contains("camel.png"))
        model.studio.image = a
        model.studio.image = b
        model.studio.image = a
        #expect(model.recentPictures == [a, b] && store.load()["last_image"] == .string(a.path))
        model.studio.image = try #require(model.samplePictures.first)  // (a sample: not in the list)
        model.studio.image = URL(filePath: "/nicht/da.png")  // (not there: nothing)
        #expect(model.recentPictures == [a, b])
        try FileManager.default.removeItem(at: b)
        #expect(model.recentPictures == [a])

        let again = try AppModel(resources: AppModelTests.resources(engine: nil), store: store)
        again.restoreLastImage()
        #expect(again.studio.image?.lastPathComponent == model.samplePictures.first?.lastPathComponent)  // (the last)
        let fresh = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        fresh.restoreLastImage()
        #expect(fresh.studio.image?.lastPathComponent == "camel.png")
    }
}
