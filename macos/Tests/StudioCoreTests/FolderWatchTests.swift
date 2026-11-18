import Foundation
import Testing
@testable import StudioCore

/// The watched folder's bookkeeping (gui/watch.py): its settings, an image queued only once it stays unchanged
/// for two seconds and never twice, the remembered state, the exported files' names and the "done" folder.
@Suite struct FolderWatchTests {
    static func folder() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "watch-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test func theSettings() throws {
        var settings = AppSettings(data: [:], defaultOutputDir: URL(filePath: "/tmp"))
        var config = FolderWatch.Config(settings)
        #expect(!config.enabled && config.preset == "studio" && config.formats == ["png"] && !config.moveDone)
        let dir = try Self.folder()
        settings["watch_enabled"] = true
        settings["watch_folder"] = .string(dir.path)
        settings["watch_formats"] = ["pdf", "gif", "svg1"]
        settings["watch_preset"] = ""
        config = FolderWatch.Config(settings)
        #expect(config.active && config.formats == ["pdf", "svg1"] && config.preset == "studio")
        #expect(config.exportFolder.path == dir.appending(path: "sketches").path)
        settings["watch_formats"] = ["gif"]
        settings["watch_export_dir"] = "/Skizzen"
        config = FolderWatch.Config(settings)
        #expect(config.formats == ["png"] && config.exportFolder.path == "/Skizzen")
        settings["watch_folder"] = .string(dir.appending(path: "nope").path)
        #expect(!FolderWatch.Config(settings).active)
    }

    @Test func queuedOnceItStaysTheSame() throws {
        let dir = try Self.folder()
        let image = dir.appending(path: "Kamel.png")
        try Data([1, 2, 3]).write(to: image)
        try Data([1]).write(to: dir.appending(path: "notes.txt"))
        try Data().write(to: dir.appending(path: "leer.jpg"))  // (empty: still being written)
        var watch = FolderWatch()
        watch.scan(dir, waiting: [], now: 0)
        #expect(watch.hasPending && watch.ready(now: 1).isEmpty)  // (not two seconds yet)
        try Data([1, 2, 3, 4]).write(to: image)  // written again: waits anew
        #expect(watch.ready(now: 2.5).isEmpty)
        let ready = watch.ready(now: 4.6)
        #expect(ready.map(\.url.lastPathComponent) == ["Kamel.png"] && ready.first?.stamp.first == 4)
        for item in ready { watch.handled(item.url, stamp: item.stamp) }
        watch.scan(dir, waiting: [], now: 5)
        #expect(watch.ready(now: 10).isEmpty)  // handled: not again (the empty one still waits)

        let file = dir.appending(path: "state/watch_state.json")
        watch.save(file)
        var again = FolderWatch.load(file)
        again.scan(dir, waiting: [], now: 0)
        #expect(again.ready(now: 3).isEmpty && again.state == watch.state)  // (after a restart, too)
        try Data([9, 9]).write(to: image)  // a new picture of the same name: sketched again
        again.scan(dir, waiting: [], now: 4)
        let renewed = again.ready(now: 7)
        #expect(renewed.map(\.url.lastPathComponent) == ["Kamel.png"])
        for item in renewed { again.handled(item.url, stamp: item.stamp) }
        let gone = dir.appending(path: "Zebra.png")
        try Data([1]).write(to: gone)
        again.scan(dir, waiting: [gone.path], now: 8)  // (queued already)
        #expect(again.ready(now: 11).isEmpty)
    }

    @Test func theStateAsWatchPyWritesIt() throws {
        let dir = try Self.folder()
        let file = dir.appending(path: "watch_state.json")
        var watch = FolderWatch()
        watch.handled(URL(filePath: "/Bilder/Bär.png"), stamp: [12, 1_700_000_000_123_456_789])
        watch.save(file)
        let text = try String(contentsOf: file, encoding: .utf8)
        #expect(text == "{\n \"/Bilder/B\\u00e4r.png\": [\n  12,\n  1700000000123456789\n ]\n}")  // (json.dump, indent=1)
        #expect(FolderWatch.load(file).state == watch.state)
    }

    @Test func theFilesNames() throws {
        let dir = try Self.folder()
        let png = FolderWatch.exportFile(target: "/Bilder/Kamel.jpg", method: "clipasso", format: "png", in: dir)
        #expect(png.lastPathComponent == "Kamel_clipasso.png")
        try Data().write(to: png)
        #expect(FolderWatch.exportFile(target: "/Bilder/Kamel.jpg", method: "clipasso", format: "png", in: dir)
            .lastPathComponent == "Kamel_clipasso_2.png")
        #expect(FolderWatch.exportFile(target: "Kamel.jpg", method: "swiftsketch", format: "svg1", in: dir)
            .lastPathComponent == "Kamel_swiftsketch_1layer.svg")

        let image = dir.appending(path: "Kamel.jpg")
        try Data([1]).write(to: image)
        #expect(FolderWatch.moveDone(image)?.path == dir.appending(path: "done/Kamel.jpg").path)
        try Data([2]).write(to: image)
        #expect(FolderWatch.moveDone(image)?.lastPathComponent == "Kamel-2.jpg")
        #expect(FolderWatch.moveDone(image) == nil)  // (gone)
    }
}
