import Foundation
import Testing
@testable import StudioCore

/// A SceneSketch matrix exported as the studio exports it: every cell as SVG and PNG and the overview sheet in one ZIP
/// file – which the system's unzip reads back, entry for entry.
@Suite struct MatrixExportTests {
    static func job() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "zip-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let job = dir.appending(path: "scenesketch_matrix", directoryHint: .isDirectory)
        try FileManager.default.copyItem(at: Fixtures.url("jobs/scenesketch_matrix"), to: job)
        return job
    }

    /// The system's unzip with `arguments`, its output.
    static func unzip(_ arguments: [String]) throws -> Data {
        let process = Process()
        process.executableURL = URL(filePath: "/usr/bin/unzip")
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        #expect(process.terminationStatus == 0, "unzip \(arguments)")
        return data
    }

    @Test func crc32() {
        #expect(ZipWriter.crc32(Data("123456789".utf8)) == 0xCBF4_3926 && ZipWriter.crc32(Data()) == 0)
    }

    @Test func aZipTheSystemReads() throws {
        var zip = ZipWriter()
        let long = String(repeating: "Strich für Strich ", count: 200)
        zip.add("klein.txt", text: "ä")
        zip.add("Ordner/lang.txt", text: long)  // (deflated: much smaller)
        let url = FileManager.default.temporaryDirectory.appending(path: "zip-\(UUID().uuidString).zip")
        defer { try? FileManager.default.removeItem(at: url) }
        let data = zip.finished()
        try data.write(to: url)
        #expect(data.count < long.utf8.count)
        #expect(try Self.unzip(["-p", url.path, "klein.txt"]) == Data("ä".utf8))
        #expect(try Self.unzip(["-p", url.path, "Ordner/lang.txt"]) == Data(long.utf8))
        #expect(try Self.unzip(["-t", url.path]).count > 0)
    }

    #if canImport(CoreGraphics) && canImport(CoreText) && canImport(ImageIO)
        @Test func theMatrixOfAJob() throws {
            let job = try Self.job()
            defer { try? FileManager.default.removeItem(at: job.deletingLastPathComponent()) }
            var options = ExportOptions()
            options.size = 128
            let cells = MatrixExport.cells(jobDir: job, options: options)
            #expect(cells.map(\.cell) == [800, 804] && MatrixExport.name(804) == "L8_level4")
            var progress: [[Int]] = []
            let data = try MatrixExport.zip(jobDir: job, options: options) { progress.append([$0, $1]) }
            #expect(progress == [[1, 2], [2, 2], [0, 0]])
            let url = job.deletingLastPathComponent().appending(path: "matrix.zip")
            try data.write(to: url)
            let listing = String(decoding: try Self.unzip(["-Z1", url.path]), as: UTF8.self)
            #expect(listing.split(separator: "\n").map(String.init)
                == ["L8_level0.svg", "L8_level0.png", "L8_level4.svg", "L8_level4.png", "matrix.svg", "matrix.png"])
            let svg = String(decoding: try Self.unzip(["-p", url.path, "L8_level0.svg"]), as: UTF8.self)
            #expect(svg == SketchExport.restyleSVG(cells[0].svg, background: options.background))
            let sheet = String(decoding: try Self.unzip(["-p", url.path, "matrix.svg"]), as: UTF8.self)
            #expect(sheet == SketchFormats.matrixSheet(cells, background: options.background))
            let image = try MatrixExport.sheetImage(cells, options: options)
            #expect(image.width == 326 && image.height == 530)  // (one layer, two levels; 128 px: the sheet's own size)
        }

        @Test func aJobWithoutSketches() throws {
            let empty = FileManager.default.temporaryDirectory.appending(path: "none-\(UUID().uuidString)")
            #expect(throws: ExportError(code: "export_no_sketches")) {
                try MatrixExport.zip(jobDir: empty, options: ExportOptions())
            }
        }
    #endif
}
