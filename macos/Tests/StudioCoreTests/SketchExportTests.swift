import Foundation
import Testing
@testable import StudioCore

/// The SVG export changes a sketch as gui/export.restyle_svg does – checked against what Python wrote for the same
/// sketches and options (Fixtures/export/restyle.json).
@Suite struct SketchExportTests {
    struct Case {
        let svg: String, color: String?, scale: Double, background: String?, python: String
    }

    static func cases() throws -> [Case] {
        try #require(Fixtures.json("export/restyle.json").arrayValue).map {
            let o = $0.objectValue ?? [:]
            return Case(svg: o["svg"]?.stringValue ?? "", color: o["stroke_color"]?.stringValue,
                        scale: o["width_scale"]?.doubleValue ?? 1, background: o["background"]?.stringValue,
                        python: o["output"]?.stringValue ?? "")
        }
    }

    /// The stroke-width values of the paths, in order, as written.
    static func widths(_ svg: String) -> [String] {
        svg.components(separatedBy: "stroke-width=\"").dropFirst().map { String($0.prefix { $0 != "\"" }) }
    }

    static func backgrounds(_ svg: String) -> Int { svg.components(separatedBy: "data-bg=\"1\"").count - 1 }

    /// The background rect as written (nil: none).
    static func backgroundTag(_ svg: String) -> String? {
        guard let end = svg.range(of: "data-bg=\"1\" />"), let start = svg[..<end.lowerBound].range(of: "<rect",
                                                                                                    options: .backwards)
        else { return nil }
        return String(svg[start.lowerBound..<end.upperBound])
    }

    @Test func likePython() throws {
        let all = try Self.cases()
        #expect(all.count == 6)
        for c in all {
            let source = String(decoding: try Fixtures.data("svg/\(c.svg)"), as: UTF8.self)
            let swift = SketchExport.restyleSVG(source, strokeColor: c.color, widthScale: c.scale,
                                                background: c.background)
            #expect(try SketchSVG.parse(swift) == SketchSVG.parse(c.python), "\(c.svg) \(String(describing: c.color))")
            #expect(Self.widths(swift) == Self.widths(c.python), "\(c.svg) × \(c.scale)")
            #expect(Self.backgrounds(swift) == Self.backgrounds(c.python))
            #expect(Self.backgroundTag(swift) == Self.backgroundTag(c.python), "\(c.svg) \(String(describing: c.background))")
        }
    }

    @Test func anEarlierBackgroundIsReplaced() throws {
        let source = String(decoding: try Fixtures.data("svg/lines.svg"), as: UTF8.self)
        let once = SketchExport.restyleSVG(source, background: "#ffffff")
        let twice = SketchExport.restyleSVG(once, background: "#101010")
        #expect(Self.backgrounds(twice) == 1 && twice.contains("fill=\"#101010\"") && !twice.contains("#ffffff"))
        #expect(try SketchSVG.parse(twice).background == "#101010")
        #expect(Self.backgrounds(SketchExport.restyleSVG(twice)) == 0)  // no background: the old one goes too
    }

    @Test func unchangedWithoutOptions() throws {
        let source = String(decoding: try Fixtures.data("svg/cubic.svg"), as: UTF8.self)
        #expect(SketchExport.restyleSVG(source) == source)
    }

    @Test func pathsWithoutWidthAndOddQuoting() throws {
        let svg = #"<svg xmlns="http://www.w3.org/2000/svg" viewBox='0 0 10 10'><!-- a <path> in a comment -->"#
            + #"<path d='M 0 0 L 5 5' stroke='rgb(1, 2, 3)'/><g><path d="M 1 1 L 2 2" stroke-width=" 3 "></path></g></svg>"#
        let out = SketchExport.restyleSVG(svg, strokeColor: "#a&b", widthScale: 2)
        #expect(Self.widths(out) == ["2", "6"])  // a path without a width counts as 1 (restyle_svg's default)
        #expect(out.contains(##"stroke="#a&amp;b""##) && out.contains("<!-- a <path> in a comment -->"))
        #expect(out.components(separatedBy: "stroke=\"#a&amp;b\"").count == 3)
    }

    /// Qt draws a rect of width="100%" as 100 × 100 user units: the background is as big as the viewBox, in numbers.
    @Test func theBackgroundCoversTheViewBox() {
        let svg = #"<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5" viewBox="-2, 1 300.5 200"></svg>"#
        #expect(Self.backgroundTag(SketchExport.restyleSVG(svg, background: "#101010"))
            == #"<rect x="-2" y="1" width="300.5" height="200" fill="#101010" data-bg="1" />"#)
        #expect(SketchExport.canvasBox(viewBox: nil, width: "300", height: "200")
            == #"x="0" y="0" width="300" height="200""#)
        #expect(SketchExport.canvasBox(viewBox: "0 0 1", width: "100%", height: nil) == #"width="100%" height="100%""#)
    }

    @Test func numbersAsPythonWritesThem() {
        #expect(SketchExport.pythonG4(5.625) == "5.625" && SketchExport.pythonG4(0.75) == "0.75")
        #expect(SketchExport.pythonG4(12345) == "1.234e+04" && SketchExport.pythonG4(3) == "3")
        #expect(SketchExport.pythonG4(0.00001234) == "1.234e-05" && SketchExport.pythonG4(.infinity) == "inf")
    }
}
