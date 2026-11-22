import Foundation
import Testing
@testable import StudioCore

/// The export from the phone as gui/export_jobs.py has it (Fixtures/phone/export.json, made with its functions): for
/// every format, after three kinds of earlier exports and for a sketch with and without saved steps, the options it
/// has, what it starts with, what six kinds of the phone's options become, and what is remembered.
@Suite struct PhoneExportTests {
    static func cases() throws -> JSONObject { try #require(Fixtures.json("phone/export.json").objectValue) }

    /// Values alike, numbers by value, objects whatever their keys' order.
    static func alike(_ a: JSONValue?, _ b: JSONValue?) -> Bool {
        switch (a, b) {
        case (.int(let x)?, .double(let y)?), (.double(let y)?, .int(let x)?): return Double(x) == y
        case (.object(let x)?, .object(let y)?):
            return Set(x.keys) == Set(y.keys) && x.keys.allSatisfy { alike(x[$0], y[$0]) }
        case (.array(let x)?, .array(let y)?): return x.count == y.count && zip(x, y).allSatisfy { alike($0, $1) }
        default: return a == b
        }
    }

    @Test func likeTheStudio() throws {
        let c = try Self.cases()
        let schema = try ParamSchema.load(Fixtures.url("schema.json"))
        #expect(PhoneExport.formats == c["formats"]?.arrayValue?.compactMap(\.stringValue))
        #expect(PhoneExport.maxSize == c["max_size"]?.intValue)
        for (ext, type) in try #require(c["content_types"]?.objectValue) {
            #expect(PhoneExport.contentTypes[ext] == type.stringValue, "\(ext)")
        }
        let stored = (c["settings"]?.arrayValue ?? []).compactMap(\.objectValue)
        let sketches = (c["sketches"]?.arrayValue ?? []).compactMap(\.objectValue).map {
            PhoneExport.Sketch(processFrames: $0["process_frames"]?.intValue ?? 0, strokes: $0["strokes"]?.intValue ?? 0,
                               drawLength: $0["draw_length"]?.doubleValue ?? 0,
                               processLength: $0["process_length"]?.doubleValue ?? 0,
                               photoFrame: $0["photo_frame"]?.truthy ?? false)
        }
        let raws = c["raw"]?.arrayValue ?? []
        var checked = 0
        for k in (c["cases"]?.arrayValue ?? []).compactMap(\.objectValue) {
            let fmt = k["fmt"]?.stringValue ?? ""
            let settings = AppSettings(data: stored[k["settings"]?.intValue ?? 0], defaultOutputDir: URL(filePath: "/tmp"))
            let sketch = sketches[k["sketch"]?.intValue ?? 0]
            let label = "\(fmt), settings \(k["settings"]?.intValue ?? -1), sketch \(k["sketch"]?.intValue ?? -1)"
            #expect(Self.alike(.object(PhoneExport.applies(fmt, processFrames: sketch.processFrames)), k["applies"]),
                    "applies \(label)")
            let first = PhoneExport.defaults(fmt, sketch: sketch, settings: settings)
            #expect(Self.alike(.object(first), k["defaults"]), "defaults \(label): \(PyJSON.dump(.object(first)))")
            let wants = k["checked"]?.arrayValue ?? []
            for (i, raw) in raws.enumerated() {
                let made = PhoneExport.check(fmt, raw, sketch: sketch, settings: settings, styles: schema.brushStyles)
                #expect(Self.alike(.object(made), wants[i]),
                        "check \(label), raw \(i): \(PyJSON.dump(.object(made))) instead of \(PyJSON.dump(wants[i]))")
                checked += 1
            }
            var after = settings
            let chosen = PhoneExport.check(fmt, raws[3], sketch: sketch, settings: settings, styles: schema.brushStyles)
            PhoneExport.remember(fmt, chosen, in: &after)
            #expect(Self.alike(.object(after.data), k["remembered"]), "remembered \(label)")
        }
        #expect(checked == 72 * 6)
    }

    @Test func theOptionsAsTheExportersTakeThem() {
        let o: JSONObject = ["stroke": "#336699", "width": 2.5, "style": "ink", "background": "transparent",
                             "paper": "kraft", "vignette": 30, "frame": "content", "margin": 12, "size": 800,
                             "width_cm": 20.0]
        let png = PhoneExport.options("png", o)
        #expect(png.stroke == "#336699" && png.widthScale == 2.5 && png.style == "ink" && png.background == nil)
        #expect(png.paper == Paper(kind: .kraft, vignette: 0.3) && png.frame == .content && png.margin == 12)
        #expect(png.size == 800 && png.pdfWidth == 20)
        #expect(PhoneExport.options("svg1", o).paper == nil && PhoneExport.options("lottie", o).style == "plain")
        #expect(PhoneExport.fileExtension("svganim") == "svg" && PhoneExport.suffix("svganim") == "_animated")
        #expect(PhoneExport.fileExtension("matrix") == "zip" && PhoneExport.fileExtension("gif") == "gif")
    }
}
