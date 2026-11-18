import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The watched folder in the app (watch.FolderWatcher): an image saved into it is queued once it stays unchanged,
/// sketched, its best sketch exported as the studio exports it, the image moved into "done" – and not again.
@Suite(.serialized) struct FolderWatcherTests {
    #if canImport(ImageIO) && canImport(CoreText)
        @Test func anImageSketchedAndExported() async throws {
            let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
            let dir = FileManager.default.temporaryDirectory.appending(path: "watched-\(UUID().uuidString)")
            let watched = dir.appending(path: "Eingang", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
            let store = try AppModelTests.store(language: "de", [
                "output_dir": .string(dir.appending(path: "out").path), "watch_enabled": true,
                "watch_folder": .string(watched.path), "watch_formats": ["png", "svg"], "watch_move_done": true,
            ])
            let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                     store: store)
            await model.startEngine()
            #expect(model.folderWatcher.loop != nil)  // (watching, as the settings say)
            model.folderWatcher.stop()  // (the test keeps the clock itself)

            let image = watched.appending(path: "Kamel.png")
            try Data([1, 2, 3]).write(to: image)
            await model.watchTick(now: 0)
            #expect(model.queueSnapshot?.jobs.isEmpty ?? true)  // (it may still be written)
            await model.watchTick(now: 2.5)
            #expect(model.watchNote == "Überwachter Ordner: Kamel.png in die Warteschlange gestellt")
            #expect(model.queueSnapshot?.jobs.map(\.target.lastPathComponent) == ["Kamel.png"])

            try await ModelFlowTests.wait("the export") { model.watchNote.contains("skizziert") }
            #expect(model.watchNote == "Überwachter Ordner: Kamel.png skizziert, 2 Dateien exportiert")
            let jobDir = try #require(model.queueSnapshot?.jobs.first?.jobDir)
            let summary = try #require(JobFolder.summary(at: jobDir))
            let stem = (URL(filePath: summary.target).lastPathComponent as NSString).deletingPathExtension
            let sketches = watched.appending(path: "sketches")
            let names = try FileManager.default.contentsOfDirectory(atPath: sketches.path).sorted()
            #expect(names == ["\(stem)_clipasso.png", "\(stem)_clipasso.svg"])
            let png = try Data(contentsOf: sketches.appending(path: "\(stem)_clipasso.png"))
            #expect(png.starts(with: [0x89, 0x50, 0x4E, 0x47]))
            #expect(!FileManager.default.fileExists(atPath: image.path))
            #expect(FileManager.default.fileExists(atPath: watched.appending(path: "done/Kamel.png").path))

            // remembered beside settings.json: the same picture put back is not sketched again
            let state = store.url.deletingLastPathComponent().appending(path: FolderWatch.stateFile)
            #expect(FolderWatch.load(state).state.keys.contains(FolderWatch.join(watched.path, "Kamel.png")))
            try FileManager.default.moveItem(at: watched.appending(path: "done/Kamel.png"), to: image)
            await model.watchTick(now: 20)
            await model.watchTick(now: 23)
            #expect(model.queueSnapshot?.jobs.count == 1)
            await model.stopEngine()
        }
    #endif

    @Test func offOrWithoutAFolder() async throws {
        let store = try AppModelTests.store(language: "de", ["watch_enabled": true, "watch_folder": "/nicht/da"])
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store)
        #expect(!model.watchConfig.active)
        model.setWatch("watch_enabled", false)
        #expect(store.load()["watch_enabled"] == false && model.folderWatcher.loop == nil)
    }
}
