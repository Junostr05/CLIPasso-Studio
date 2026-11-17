import Foundation
import Testing
@testable import StudioCore

/// The studio's other formats of a sketch written here – checked against what Python wrote of the same sketches
/// (Fixtures/export/formats.json): the plotter's one-layer SVG, the web page and the matrix sheet to the character,
/// Lottie to the character of its JSON, the SVG that draws itself in its CSS and masks, the layered SVG in its strokes
/// and layers.
@Suite(.onOwnThreads) struct SketchFormatsTests {
    static func fixture() throws -> JSONObject { try #require(Fixtures.json("export/formats.json").objectValue) }
    static func sketch(_ name: String) throws -> String { String(decoding: try Fixtures.data(name), as: UTF8.self) }
    static func cases(_ key: String) throws -> [JSONObject] { (try fixture()[key]?.arrayValue ?? []).compactMap(\.objectValue) }

    static func between(_ text: String, _ open: String, _ close: String) -> String {
        guard let a = text.range(of: open), let b = text.range(of: close, range: a.upperBound ..< text.endIndex)
        else { return "" }
        return String(text[a.upperBound ..< b.lowerBound])
    }

    @Test func plotterSVGLikePython() throws {
        let cases = try Self.cases("single")
        #expect(cases.count == 10)
        for c in cases {
            let name = c["svg"]?.stringValue ?? ""
            let out = SketchFormats.singleLayer(try Self.sketch(name), strokeColor: c["stroke"]?.stringValue,
                                                widthScale: c["width"]?.doubleValue ?? 1)
            #expect(out == c["out"]?.stringValue, "\(name)")
        }
    }

    @Test func animatedSVGLikePython() throws {
        let cases = try Self.cases("animated")
        #expect(cases.count == 15)
        for c in cases {
            let name = c["svg"]?.stringValue ?? ""
            let python = c["out"]?.stringValue ?? ""
            let swift = SketchFormats.animatedSVG(try Self.sketch(name), length: c["length"]?.doubleValue,
                                                  hold: c["hold"]?.doubleValue ?? 1, strokeColor: c["stroke"]?.stringValue,
                                                  widthScale: c["width"]?.doubleValue ?? 1,
                                                  background: c["background"]?.stringValue,
                                                  keepOrder: c["keep_order"]?.truthy ?? false)
            let what = "\(name) \(String(describing: c["length"]))"
            #expect(Self.between(swift, "<style>", "</style>") == Self.between(python, "<style>", "</style>"), "\(what)")
            #expect(Self.between(swift, "<defs>", "</defs>") == Self.between(python, "<defs>", "</defs>"), "\(what)")
            #expect(swift.hasPrefix(String(python.prefix { $0 != ">" })), "\(what)")
            #expect(swift.components(separatedBy: "<g mask=").count == python.components(separatedBy: "<g mask=").count)
            #expect(swift.contains(#"<rect width="100%""#) == python.contains(#"<rect width="100%""#), "\(what)")
            #expect((try? SketchSVG.parse(swift)) == (try? SketchSVG.parse(python)), "\(what)")
        }
    }

    /// QColor(name) as Qt reads it (Fixtures/export/qcolor.json): its 148 names, the hex forms – and what is no
    /// colour to it ("nope", rgb(), white space around a hex value), which the web page shows on white.
    @Test func coloursLikeQt() throws {
        let fixture = try #require(Fixtures.json("export/qcolor.json").objectValue)
        let names = try #require(fixture["names"]?.objectValue)
        #expect(names.count == 148 && QtColour.names.count == 148)
        func hex(_ c: RGB?) -> String? { c.map { String(format: "#%02x%02x%02x", $0.r, $0.g, $0.b) } }
        for (name, colour) in names { #expect(hex(QtColour.read(name)) == colour.stringValue, "\(name)") }
        for c in (fixture["cases"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            let text = c[0].stringValue ?? ""
            #expect(hex(QtColour.read(text)) == c[2].stringValue, "\(text)")
            #expect((QtColour.read(text) != nil) == (c[1].truthy), "\(text)")
        }
    }

    @Test func webPagesLikePython() throws {
        let animated = try #require(try Self.cases("animated").first?["out"]?.stringValue)
        for c in try Self.cases("pages") {
            let page = SketchFormats.webPage(animated, title: c["title"]?.stringValue ?? "",
                                             background: c["background"]?.stringValue)
            #expect(page == c["out"]?.stringValue, "\(String(describing: c["title"]))")
        }
    }

    @Test func lottieLikePython() throws {
        let cases = try Self.cases("lottie")
        #expect(cases.count == 10)
        for c in cases {
            let name = c["svg"]?.stringValue ?? ""
            let swift = SketchFormats.lottie(try Self.sketch(name), length: c["length"]?.doubleValue,
                                             hold: c["hold"]?.doubleValue ?? 1, strokeColor: c["stroke"]?.stringValue,
                                             widthScale: c["width"]?.doubleValue ?? 1, background: c["background"]?.stringValue,
                                             keepOrder: c["keep_order"]?.truthy ?? false, name: "Kamel",
                                             size: c["size"]?.intValue ?? 512)
            let python = try #require(c["out"])
            #expect(PyJSON.dump(swift, compact: true) == PyJSON.dump(python, compact: true), "\(name)")
        }
    }

    @Test func layersLikePython() throws {
        let objects = Set(try #require(try Self.fixture()["object"]?.arrayValue).compactMap(\.stringValue))
        for c in try Self.cases("layered") {
            let name = c["svg"]?.stringValue ?? ""
            let withObject = c["object"]?.truthy ?? false
            let python = c["out"]?.stringValue ?? ""
            let swift = SketchFormats.layered(try Self.sketch(name), objects: withObject ? objects : nil,
                                              labels: ("Hintergrund", "Objekt"))
            let what = "\(name) \(withObject)"
            #expect((try? SketchSVG.parse(swift)) == (try? SketchSVG.parse(python)), "\(what)")
            #expect(swift.contains("xmlns:inkscape=") && swift.contains(#"inkscape:label="Hintergrund""#), "\(what)")
            for (open, close) in [(#"<g id="background""#, #"<g id="object""#), (#"<g id="object""#, "</svg>")] {
                let paths = { (text: String) in Self.between(text, open, close).components(separatedBy: "<path").count }
                #expect(paths(swift) == paths(python), "\(what) \(open)")
            }
        }
    }

    @Test func matrixSheetsLikePython() throws {
        for c in try Self.cases("sheets") {
            let cells = (c["cells"]?.objectValue ?? [:]).compactMap { key, value in
                Int(key).flatMap { cell in value.stringValue.map { (cell: cell, svg: $0) } }
            }
            #expect(cells.count == 4)
            let sheet = SketchFormats.matrixSheet(cells, background: c["background"]?.stringValue)
            #expect(sheet == c["out"]?.stringValue)
        }
    }
}
