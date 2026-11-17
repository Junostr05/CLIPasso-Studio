import Foundation
import Testing
@testable import StudioCore

/// The plan of the studio's animations and its stroke-by-stroke drawing – checked against what gui/export.py worked
/// out (Fixtures/animation/animation.json): the frames shown and their durations, the lengths the dialog starts from,
/// the drawing's route, timeline, centre lines and its SVG at points of the timeline.
@Suite struct AnimationTests {
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
            let format = try #require(Animation.Format(rawValue: p["format"]?.stringValue ?? ""))
            let plan = Animation.plan(n, length: p["length"]?.doubleValue, fps: p["fps"]?.doubleValue ?? 20,
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

    @Test func lengthsLikePython() throws {
        let lengths = try #require(Fixtures.json("animation/animation.json").objectValue?["lengths"]?.objectValue)
        for c in (lengths["every_step"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            let format = try #require(Animation.Format(rawValue: c[1].stringValue ?? ""))
            #expect(Animation.everyStepLength(c[0].intValue ?? 0, format: format) == c[2].doubleValue, "\(c)")
        }
        for c in (lengths["drawing"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            #expect(Animation.defaultDrawingLength(strokes: c[0].intValue ?? 0, line: c[1].doubleValue ?? 0)
                == c[2].doubleValue, "\(c)")
        }
        for c in (lengths["process"]?.arrayValue ?? []).compactMap(\.arrayValue) {
            #expect(Animation.defaultProcessLength(c[0].intValue ?? 0) == c[1].doubleValue, "\(c)")
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
        #expect(Animation.steps(runDir: run).map(\.lastPathComponent) == ["svg_iter0.svg", "svg_iter2.svg", "svg_iter10.svg"])
        try Data(#"{"best_iter": 2, "method": "scenesketch"}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(Animation.steps(runDir: run).map(\.lastPathComponent) == ["svg_iter0.svg", "svg_iter2.svg"])
        #expect(Animation.steps(runDir: run, uptoBest: false).count == 3 && Animation.method(runDir: run) == "scenesketch")
        try Data(#"{"best_iter": -1}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(Animation.steps(runDir: run).count == 3 && Animation.method(runDir: run) == "clipasso")
    }
}
