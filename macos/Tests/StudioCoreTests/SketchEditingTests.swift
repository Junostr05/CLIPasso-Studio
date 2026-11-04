import Foundation
import Testing
@testable import StudioCore

/// The eraser and the pen change a sketch as gui/strokes.py does – checked against what Python made of the same
/// sketches (Fixtures/edit/strokes.json, made by tools/make_mac_fixtures.py): the strokes hit, removed, drawn and freed.
@Suite struct SketchEditingTests {
    struct Case {
        let name: String, svg: String, fixture: JSONObject
    }

    static func cases() throws -> [Case] {
        try #require(Fixtures.json("edit/strokes.json").arrayValue).map {
            let o = $0.objectValue ?? [:]
            let name = o["svg"]?.stringValue ?? ""
            return Case(name: name, svg: String(decoding: try Fixtures.data(name), as: UTF8.self), fixture: o)
        }
    }

    static func points(_ value: JSONValue?) -> [SketchPoint] {
        (value?.arrayValue ?? []).map {
            let xy = $0.arrayValue ?? []
            return SketchPoint(x: xy.first?.doubleValue ?? .nan, y: xy.dropFirst().first?.doubleValue ?? .nan)
        }
    }

    /// The attributes of the last stroke of a sketch, as written.
    static func lastStroke(_ svg: String) -> [String: String] {
        guard let tag = SketchEditing.paths(SketchEditing.elements(svg)).last?.tag else { return [:] }
        var out: [String: String] = [:]
        for key in ["d", "stroke-width", "stroke", "fill", SketchEditing.fixedAttribute] { out[key] = tag.value(key) }
        return out
    }

    @Test func readsLikePython() throws {
        let all = try Self.cases()
        #expect(all.count == 5)
        for c in all {
            #expect(SketchEditing.count(c.svg) == c.fixture["count"]?.intValue, "\(c.name)")
            #expect(SketchEditing.fixedCount(c.svg) == c.fixture["fixed"]?.intValue, "\(c.name)")
            let box = SketchEditing.viewBox(c.svg)
            #expect([box.x, box.y, box.width, box.height] == c.fixture["view_box"]?.arrayValue?.compactMap(\.doubleValue),
                    "\(c.name)")
        }
    }

    /// brush.sample: the same points (to the last bit – the same formulas in the same order).
    @Test func samplesLikePython() throws {
        for c in try Self.cases() {
            let ds = SketchEditing.paths(SketchEditing.elements(c.svg)).map { $0.tag.value("d") ?? "" }
            let python = (c.fixture["samples"]?.arrayValue ?? []).map { ($0.arrayValue ?? []).map(Self.points) }
            #expect(ds.map { SketchEditing.sample($0) } == python, "\(c.name)")
        }
    }

    @Test func hitsLikePython() throws {
        for c in try Self.cases() {
            let index = SketchEditing.StrokeIndex(svg: c.svg)
            let hits = c.fixture["hits"]?.arrayValue ?? []
            #expect(hits.count > 100)
            for h in hits.compactMap(\.objectValue) {
                let x = h["x"]?.doubleValue ?? 0, y = h["y"]?.doubleValue ?? 0, t = h["tolerance"]?.doubleValue ?? 0
                #expect(index.hit(x: x, y: y, tolerance: t) == h["index"]?.intValue, "\(c.name) at \(x), \(y) ± \(t)")
            }
        }
    }

    @Test func removesLikePython() throws {
        for c in try Self.cases() {
            for r in (c.fixture["removes"]?.arrayValue ?? []).compactMap(\.objectValue) {
                let drop = Set((r["indices"]?.arrayValue ?? []).compactMap(\.intValue))
                let swift = SketchEditing.removeStrokes(c.svg, drop)
                let python = r["output"]?.stringValue ?? ""
                #expect(try SketchSVG.parse(swift) == SketchSVG.parse(python), "\(c.name) without \(drop)")
                #expect(SketchEditing.count(swift) == SketchEditing.count(python), "\(c.name) without \(drop)")
            }
        }
    }

    /// The pen: the same path data (simplified, smoothed, written with 3 decimals), width and mark as Python writes.
    @Test func drawsLikePython() throws {
        for c in try Self.cases() {
            for a in (c.fixture["appends"]?.arrayValue ?? []).compactMap(\.objectValue) {
                let width = a["width"]?.doubleValue
                let fixed = a["fixed"]?.boolValue ?? true
                let swift = SketchEditing.appendStroke(c.svg, points: Self.points(a["points"]), width: width, fixed: fixed)
                let python = a["output"]?.stringValue ?? ""
                let what = "\(c.name) + \(a["points"]?.arrayValue?.count ?? 0) points"
                #expect(SketchEditing.count(swift) == SketchEditing.count(python), "\(what)")
                #expect(Self.lastStroke(swift) == Self.lastStroke(python), "\(what)")
                #expect(try SketchSVG.parse(swift) == SketchSVG.parse(python), "\(what)")
            }
        }
    }

    @Test func freedLikePython() throws {
        for c in try Self.cases() {
            let python = c.fixture["unfixed"]?.stringValue ?? ""
            let swift = SketchEditing.unfix(c.svg)
            #expect(SketchEditing.fixedCount(swift) == 0 && SketchEditing.count(swift) == SketchEditing.count(python))
            #expect(try SketchSVG.parse(swift) == SketchSVG.parse(python), "\(c.name)")
        }
    }

    /// The rest of the file stays as it was written – the comment of odd.svg too (ElementTree drops it).
    @Test func theRestOfTheFileStays() throws {
        let odd = String(decoding: try Fixtures.data("edit/odd.svg"), as: UTF8.self)
        let without = SketchEditing.removeStrokes(odd, [1])
        #expect(without.contains("<!-- a comment -->") && !without.contains("<title>"))  // (the stroke with its content)
        #expect(SketchEditing.removeStrokes(odd, [7]) == odd && SketchEditing.removeStrokes(odd, []) == odd)
        #expect(SketchEditing.unfix(odd).replacingOccurrences(of: " data-fixed=\"true\"", with: "") == odd)
        let empty = #"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" />"#
        let drawn = SketchEditing.appendStroke(empty, points: [SketchPoint(x: 1, y: 1), SketchPoint(x: 9, y: 2)])
        #expect(drawn.hasPrefix(#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M 1 1 C"#))
        #expect(drawn.hasSuffix("</svg>") && SketchEditing.count(drawn) == 1)
        #expect(SketchEditing.appendStroke(empty, points: [SketchPoint(x: 1, y: 1)]) == empty)  // (one point: no stroke)
    }

    @Test func numbersAsPythonWritesThem() {
        #expect(SketchEditing.decimal(1.5, 3, zero: false) == "1.5" && SketchEditing.decimal(2, 3, zero: false) == "2")
        #expect(SketchEditing.decimal(100, 3, zero: true) == "100" && SketchEditing.decimal(-0.0001, 3, zero: true) == "0")
        #expect(SketchEditing.decimal(33.33333, 3, zero: true) == "33.333" && SketchEditing.decimal(0.0005, 3, zero: true) == "0.001")
    }
}
