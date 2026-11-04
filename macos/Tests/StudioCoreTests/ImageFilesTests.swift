import Foundation
import Testing
@testable import StudioCore

/// The images of a folder or a drop are those the studio takes (gui/drop.py): the folder of Fixtures/image_files.json
/// is made here as Python made it, and what is found in it is compared with what Python found.
@Suite struct ImageFilesTests {
    static func strings(_ value: JSONValue?) -> [String] { value?.arrayValue?.compactMap(\.stringValue) ?? [] }

    @Test func likeTheStudio() throws {
        let fixture = try #require(Fixtures.json("image_files.json").objectValue)
        let root = FileManager.default.temporaryDirectory
            .appending(path: "images-\(UUID().uuidString)/Bilder", directoryHint: .isDirectory)
        for entry in Self.strings(fixture["tree"]) {
            let url = root.appending(path: entry)
            if entry.hasSuffix("/") {
                try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            } else {
                try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                try Data().write(to: url)
            }
        }
        let prefix = root.path + "/"
        func relative(_ urls: [URL]) -> [String] { urls.map { String($0.path.dropFirst(prefix.count)) } }
        #expect(relative(ImageFiles.inFolder(root)) == Self.strings(fixture["flat"]))
        #expect(relative(ImageFiles.inFolder(root, recursive: true)) == Self.strings(fixture["recursive"]))
        let drop = Self.strings(fixture["drop"]).map { root.appending(path: $0) }
        #expect(relative(ImageFiles.dropped(drop)) == Self.strings(fixture["dropped"]))
        #expect(ImageFiles.inFolder(root.appending(path: "CLIPasso Studio/Kamel_job"), recursive: true).isEmpty)
        // (the Mac stored "ä-Bild.png" decomposed – Foundation names files so – and it still sorts after "Z.webp")
        #expect(ImageFiles.hasSubfolders(root) && ImageFiles.hasSubfolders(root.appending(path: "Urlaub")))
        #expect(!ImageFiles.hasSubfolders(root.appending(path: "Leer")) && !ImageFiles.hasSubfolders(root.appending(path: "urlaub2")))
    }

    @Test func extensionsInAnyCase() {
        #expect(ImageFiles.isImage("Kamel.PNG") && ImageFiles.isImage("x.heic") && ImageFiles.isImage(".versteckt.jpg"))
        #expect(!ImageFiles.isImage("Notiz.txt") && !ImageFiles.isImage("png"))
    }
}
