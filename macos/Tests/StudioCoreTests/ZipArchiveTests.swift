import Foundation
import Testing
@testable import StudioCore

/// The ZIP files of a backup: what the Swift side writes Python's zipfile reads (ZIP64 fields too), and what
/// zipfile writes the Swift side reads – stored, deflated, names with umlauts, ZIP64 entries, folders.
@Suite struct ZipArchiveTests {
    static func folder() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "zip-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// python3 -c `script` with `arguments`; its standard output.
    static func python(_ script: String, _ arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(filePath: "/usr/bin/env")
        process.arguments = ["python3", "-c", script] + arguments
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        let problem = err.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw ZipError(description: String(decoding: problem, as: UTF8.self))
        }
        return String(decoding: data, as: UTF8.self)
    }

    static let contents: [(name: String, data: Data, store: Bool)] = [
        ("manifest.json", Data("{\n  \"format\": 1,\n  \"app\": \"CLIPasso Studio\"\n}".utf8), false),
        ("gallery/Bär_20260101-120000/sketch.svg", Data(String(repeating: "<path d=\"M 1 2 L 3 4\"/>\n", count: 400).utf8),
         false),
        ("models/clip/RN101.pt", Data((0 ..< 300_000).map { UInt8(truncatingIfNeeded: $0 &* 7 &+ $0 >> 9) }), true),
        ("queue_inputs/000_leer.png", Data(), true),
    ]

    /// Writes the entries (half from memory, half from files) with ZIP64 fields from `limit` on.
    static func write(_ url: URL, limit: UInt64) throws {
        let dir = try folder()
        let zip = try ZipFileWriter(url, zip64From: limit)
        for (i, entry) in contents.enumerated() {
            if i.isMultiple(of: 2) {
                try zip.add(data: entry.data, name: entry.name, store: entry.store)
            } else {
                let file = dir.appending(path: "f\(i)")
                try entry.data.write(to: file)
                try zip.add(file: file, name: entry.name, store: entry.store)
            }
        }
        try zip.finish()
    }

    @Test(arguments: [UInt64(0xFFFF_FFFF), 10])
    func readBackAndByPython(zip64From limit: UInt64) throws {
        let url = try Self.folder().appending(path: "backup.clipbackup")
        try Self.write(url, limit: limit)
        let reader = try ZipFileReader(url)
        #expect(reader.entries.map(\.name) == Self.contents.map(\.name))
        for entry in Self.contents {
            let found = try #require(reader.entry(entry.name))
            #expect(try reader.data(found) == entry.data, "\(entry.name)")
            #expect((found.method == 0) == (entry.store || entry.data.isEmpty), "\(entry.name)")
        }
        let model = try #require(reader.entry("models/clip/RN101.pt"))
        let copy = url.deletingLastPathComponent().appending(path: "RN101.pt")
        var ticks = 0
        try reader.extract(model, to: copy) { ticks += $0 }
        #expect(try Data(contentsOf: copy) == Self.contents[2].data && ticks == 300_000)

        // Python's zipfile: every entry whole and right (testzip), the same bytes
        let listing = try Self.python("""
        import hashlib, json, sys, zipfile
        with zipfile.ZipFile(sys.argv[1]) as z:
            assert z.testzip() is None
            print(json.dumps({i.filename: [hashlib.sha256(z.read(i)).hexdigest(), i.compress_type, i.file_size]
                              for i in z.infolist()}))
        """, [url.path])
        let got = try #require(try PyJSON.parse(Data(listing.utf8)).objectValue)
        for entry in Self.contents {
            let row = got[entry.name]?.arrayValue ?? []
            #expect(row.first?.stringValue == Sha256.hex(entry.data), "\(entry.name)")
            #expect(row.last?.intValue == entry.data.count)
        }
        #expect(got.count == Self.contents.count)
    }

    @Test func whatPythonWrote() throws {
        let url = try Self.folder().appending(path: "python.zip")
        let listing = try Self.python("""
        import json, sys, zipfile
        rows = {}
        with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("settings.json", json.dumps({"language": "de", "name": "Bär"}, indent=2, ensure_ascii=False))
            z.writestr("gallery/Zürich_1/sketch.svg", "<svg>" + "<path/>" * 500 + "</svg>")
            z.writestr("models/a.pt", bytes(range(256)) * 50, compress_type=zipfile.ZIP_STORED)
            z.writestr("gallery/leer/", "")
            with z.open("models/zip64.bin", "w", force_zip64=True) as f:
                f.write(b"ZIP64" * 1000)
            for i in z.infolist():
                rows[i.filename] = i.CRC
        print(json.dumps(rows))
        """, [url.path])
        let crcs = try #require(try PyJSON.parse(Data(listing.utf8)).objectValue)
        let reader = try ZipFileReader(url)
        #expect(reader.entries.map(\.name) == ["settings.json", "gallery/Zürich_1/sketch.svg", "models/a.pt",
                                               "gallery/leer/", "models/zip64.bin"])
        for entry in reader.entries where !entry.isDirectory {
            let data = try reader.data(entry)
            #expect(crcs[entry.name]?.intValue.map { UInt32($0) } == ZipWriter.crc32(data), "\(entry.name)")
        }
        let settings = try reader.data(try #require(reader.entry("settings.json")))
        #expect(try PyJSON.parse(settings).objectValue?["name"] == "Bär")
        #expect(try reader.data(try #require(reader.entry("models/zip64.bin"))).count == 5000)
        #expect(reader.entry("gallery/leer/")?.isDirectory == true)
    }

    @Test func notAZip() throws {
        let url = try Self.folder().appending(path: "nope.clipbackup")
        try Data("not a zip at all".utf8).write(to: url)
        #expect(throws: ZipError.self) { try ZipFileReader(url) }
    }
}
