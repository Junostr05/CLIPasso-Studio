import Foundation
import Testing
@testable import StudioCore

/// The plan of the studio's animations and its stroke-by-stroke drawing – checked against what gui/export.py worked
/// out (Fixtures/animation/animation.json): the frames shown and their durations, the lengths the dialog starts from,
/// the drawing's route, timeline, centre lines and its SVG at points of the timeline.
@Suite(.onOwnThreads) struct AnimationTests {
    static func numbers(_ value: JSONValue?) -> [Double] { (value?.arrayValue ?? []).compactMap(\.doubleValue) }

    static func close(_ a: [Double], _ b: [Double], _ tolerance: Double = 1e-9) -> Bool {
        a.count == b.count && zip(a, b).allSatisfy { abs($0 - $1) <= tolerance * max(1, abs($1)) }
    }

    @Test func plansLikePython() throws {
        let fixture = try #require(Fixtures.json("animation/animation.json").objectValue)
        let plans = (fixture["plans"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(plans.count == 17)
        for p in plans {
            let n = p["n"]?.intValue ?? 0
            let format = try #require(SketchAnimation.Format(rawValue: p["format"]?.stringValue ?? ""))
            let plan = SketchAnimation.plan(n, length: p["length"]?.doubleValue, fps: p["fps"]?.doubleValue ?? 20,
                                      hold: p["hold"]?.doubleValue ?? 1, format: format, size: p["size"]?.intValue ?? 512)
            let what = "\(n) \(String(describing: p["length"])) \(format)"
            #expect(plan.frames.count == p["count"]?.intValue, "\(what)")
            let ends = { (a: [Double]) in a.count > 120 ? Array(a.prefix(60) + a.suffix(60)) : a }
            #expect(ends(plan.frames.map(Double.init)) == Self.numbers(p["frames"]), "\(what)")
            #expect(Self.close(ends(plan.durations), Self.numbers(p["durations"])), "\(what)")
            #expect(plan.frames.reduce(0, +) == p["sum_frames"]?.intValue, "\(what)")
            #expect(Self.close([plan.durations.reduce(0, +)], [p["sum_durations"]?.doubleValue ?? -1]), "\(what)")
        }
    }

    /// Python's arithmetic where it is not the plain one: sum() compensated (3.12), math.hypot computed by CPython
    /// (it differs from the system's in about one call of 300 – these three from the studio's Python), float()
    /// reading a number with white space around it.
    @Test func pythonsArithmetic() {
        #expect(Python.sum(Array(repeating: 0.1, count: 10)) == 1.0)  // (a plain loop: 0.9999999999999999)
        #expect(Python.sum([]) == 0 && Python.sum([1e100, 1.0, -1e100]) == 1.0)
        #expect(Python.hypot(3, 4) == 5 && Python.hypot(0, -0.0) == 0 && Python.hypot(-.infinity, .nan) == .infinity)
        #expect(Python.hypot(0x1.4359555b23c04p+6, 0x1.9762307c1d75cp+5) == 0x1.7e287fb4048aep+6)
        #expect(Python.hypot(0x1.2108fd59b43a3p+8, 0x1.f8068b07ed650p+7) == 0x1.7f792766cbc10p+8)
        #expect(Python.hypot(0x1.22ff1b65b5b4fp+7, 0x1.09c1b217ae5f7p+7) == 0x1.8a1697e58f076p+7)
        #expect(Python.hypot(5e-324, 5e-324) == 5e-324 && Python.hypot(1e308, 1e308) == 1.4142135623730951e308)
        #expect(Python.float(" 4 ") == 4 && Python.float("\n2.5\t") == 2.5 && Python.float("4px") == nil)
    }

    @Test func lengthsLikePython() throws {
        let lengths = try #require(Fixtures.json("animation/animation.json").objectValue?["lengths"]?.objectValue)
        for c in (lengths["every_step"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            let format = try #require(SketchAnimation.Format(rawValue: c[1].stringValue ?? ""))
            #expect(SketchAnimation.everyStepLength(c[0].intValue ?? 0, format: format) == c[2].doubleValue, "\(c)")
        }
        for c in (lengths["drawing"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            #expect(SketchAnimation.defaultDrawingLength(strokes: c[0].intValue ?? 0, line: c[1].doubleValue ?? 0)
                == c[2].doubleValue, "\(c)")
        }
        for c in (lengths["process"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            #expect(SketchAnimation.defaultProcessLength(c[0].intValue ?? 0) == c[1].doubleValue, "\(c)")
        }
    }

    @Test func drawingsLikePython() throws {
        let fixture = try #require(Fixtures.json("animation/animation.json").objectValue)
        let drawings = (fixture["drawings"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(drawings.count == 10)
        for d in drawings {
            let name = d["svg"]?.stringValue ?? ""
            let keep = d["keep_order"]?.truthy ?? false
            let drawing = Drawing(svg: String(decoding: try Fixtures.data(name), as: UTF8.self), keepOrder: keep)
            let what = "\(name) \(keep)"
            #expect(drawing.head == d["head"]?.stringValue, "\(what)")
            #expect(Self.close([drawing.total, drawing.line], [d["total"]?.doubleValue ?? -1, d["line"]?.doubleValue ?? -1]),
                    "\(what)")
            #expect(Self.close(drawing.spans.flatMap { [$0.start, $0.end] },
                               (d["spans"]?.arrayValue ?? []).flatMap { Self.numbers($0) }), "\(what)")
            let starts = (0 ..< drawing.strokeCount).flatMap { [drawing.strokes[$0].subs[0][0].x, drawing.strokes[$0].subs[0][0].y] }
            #expect(Self.close(starts, (d["starts"]?.arrayValue ?? []).flatMap { Self.numbers($0) }), "\(what)")
            #expect((0 ..< drawing.strokeCount).map(drawing.centreline)
                == (d["centrelines"]?.arrayValue ?? []).compactMap(\.stringValue), "\(what)")
            for f in (d["frames"]?.arrayValue ?? []).compactMap(\.arrayValue) {
                let t = f[0].doubleValue ?? 0
                let python = f[1].stringValue ?? ""
                let swift = drawing.frame(t)
                #expect(swift.hasPrefix(drawing.head) && swift.hasSuffix("</svg>"))
                #expect((try? SketchSVG.parse(swift)) == (try? SketchSVG.parse(python)), "\(what) at \(t)")
                #expect(swift.components(separatedBy: "<path").count == python.components(separatedBy: "<path").count,
                        "\(what) at \(t)")
            }
        }
    }

    /// animation_frames: the saved steps in the order of their numbers, up to the best one (all when none is up
    /// to it).
    @Test func theStepsOfARun() throws {
        let run = FileManager.default.temporaryDirectory.appending(path: "run-\(UUID().uuidString)")
        let logs = run.appending(path: "svg_logs")
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: run) }
        for name in ["svg_iter10.svg", "svg_iter2.svg", "svg_iter0.svg", "svg_iter.svg", "notes.txt", "svg_iter7.png"] {
            try Data("<svg/>".utf8).write(to: logs.appending(path: name))
        }
        #expect(SketchAnimation.steps(runDir: run).map(\.lastPathComponent) == ["svg_iter0.svg", "svg_iter2.svg", "svg_iter10.svg"])
        try Data(#"{"best_iter": 2, "method": "scenesketch"}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(SketchAnimation.steps(runDir: run).map(\.lastPathComponent) == ["svg_iter0.svg", "svg_iter2.svg"])
        #expect(SketchAnimation.steps(runDir: run, uptoBest: false).count == 3 && SketchAnimation.method(runDir: run) == "scenesketch")
        try Data(#"{"best_iter": -1}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(SketchAnimation.steps(runDir: run).count == 3 && SketchAnimation.method(runDir: run) == "clipasso")
    }
}
