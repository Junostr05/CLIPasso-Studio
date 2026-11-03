import Foundation
import Testing
@testable import StudioCore

/// The sketches of the engine (best_iter.svg, edited.svg, the live preview) are read as engine/svg_io.py and
/// engine/svg_path.py read them.
@Suite struct SketchSVGTests {
    static func near(_ a: Double, _ b: Double) -> Bool { abs(a - b) < 1e-4 }

    static func point(_ v: JSONValue?) -> SketchPoint? {
        guard let a = v?.arrayValue, a.count == 2, let x = a[0].doubleValue, let y = a[1].doubleValue else { return nil }
        return SketchPoint(x: x, y: y)
    }

    @Test func pathDataLikePython() throws {
        let cases = try #require(Fixtures.json("paths_expected.json").arrayValue)
        #expect(cases.count == 12)
        for item in cases {
            let c = try #require(item.objectValue)
            let d = try #require(c["d"]?.stringValue)
            let got = try SketchSVG.parsePath(d)
            let want = try #require(c["subpaths"]?.arrayValue)
            #expect(got.count == want.count, "\(d)")
            for (sub, w) in zip(got, want) {
                let wo = try #require(w.objectValue)
                #expect(sub.closed == wo["closed"]?.boolValue, "\(d)")
                let segments = try #require(wo["segments"]?.arrayValue)
                #expect(sub.segments.count == segments.count, "\(d)")
                for (seg, ws) in zip(sub.segments, segments) {
                    let points = try #require(ws.arrayValue).compactMap(Self.point)
                    #expect(seg.count == points.count, "\(d)")
                    for (p, q) in zip(seg, points) {
                        #expect(Self.near(p.x, q.x) && Self.near(p.y, q.y), "\(d): \(p) vs \(q)")
                    }
                }
            }
        }
    }

    @Test func parsesWhatPythonWrites() throws {
        let expected = try #require(Fixtures.json("svg_expected.json").objectValue)
        #expect(expected.count == 3)
        for (name, want) in expected {
            let w = try #require(want.objectValue)
            let text = try String(contentsOf: Fixtures.url("svg/\(name)"), encoding: .utf8)
            let sketch = try SketchSVG.parse(text)
            #expect(sketch.width == w["width"]?.intValue && sketch.height == w["height"]?.intValue, "\(name)")
            #expect(sketch.background == w["background"]?.stringValue, "\(name)")
            let strokes = try #require(w["strokes"]?.arrayValue)
            #expect(sketch.strokes.count == strokes.count, "\(name)")
            for (stroke, ws) in zip(sketch.strokes, strokes) {
                let o = try #require(ws.objectValue)
                #expect(stroke.closed == o["closed"]?.boolValue && stroke.fixed == o["fixed"]?.boolValue, "\(name)")
                #expect(stroke.color == RGB(o["color"]?.arrayValue?.compactMap(\.intValue) ?? []), "\(name)")
                #expect(Self.near(stroke.opacity, o["opacity"]?.doubleValue ?? -1), "\(name)")
                #expect(Self.near(stroke.width, o["width"]?.doubleValue ?? -1), "\(name)")
                let start = try #require(Self.point(o["start"]))
                #expect(Self.near(stroke.start.x, start.x) && Self.near(stroke.start.y, start.y), "\(name)")
                let segments = try #require(o["segments"]?.arrayValue)
                #expect(stroke.segments.count == segments.count, "\(name)")
                for (seg, wseg) in zip(stroke.segments, segments) {
                    let so = try #require(wseg.objectValue)
                    #expect(seg.kind == so["kind"]?.stringValue, "\(name)")
                    let points = try #require(so["points"]?.arrayValue).compactMap(Self.point)
                    #expect(seg.points.count == points.count, "\(name)")
                    for (p, q) in zip(seg.points, points) {
                        #expect(Self.near(p.x, q.x) && Self.near(p.y, q.y), "\(name)")
                    }
                }
            }
        }
    }

    @Test func colours() throws {
        let svg = #"""
        <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M 0 0 L 1 1" stroke="#ff8000"
        stroke-width="2"/><path d="M 0 0 L 1 1" style="stroke: rgb(20%, 100%, 0%); stroke-opacity: 0.5"/></svg>
        """#
        let sketch = try SketchSVG.parse(svg)
        #expect(sketch.strokes.map(\.color) == [RGB(255, 128, 0), RGB(51, 255, 0)])
        #expect(sketch.strokes.map(\.opacity) == [1, 0.5] && sketch.strokes[0].width == 2)
    }

    @Test func rejectsNonSVG() {
        #expect(throws: SketchSVG.ParseError.self) { try SketchSVG.parse("<html><body/></html>") }
        #expect(throws: SketchSVG.ParseError.self) { try SketchSVG.parse("not xml at all <") }
        #expect(throws: SketchSVG.ParseError.self) { try SketchSVG.parsePath("10 10 L 1 1") }  // no command first
    }
}
