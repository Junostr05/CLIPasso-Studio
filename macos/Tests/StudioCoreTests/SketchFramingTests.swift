import Foundation
import Testing
@testable import StudioCore

/// An export's frame as engine/framing.py makes it – checked against what Python made of the same sketches
/// (Fixtures/export/framing.json): the strokes' box, the new viewBox, the points moved, the backgrounds resized.
@Suite(.onOwnThreads) struct SketchFramingTests {
    static func numbers(_ value: JSONValue?) -> [Double]? { value?.arrayValue?.compactMap(\.doubleValue) }

    static func close(_ a: [Double]?, _ b: [Double]?, _ tolerance: Double = 1e-9) -> Bool {
        guard let a, let b else { return a == nil && b == nil }
        return a.count == b.count && zip(a, b).allSatisfy { abs($0 - $1) <= tolerance }
    }

    /// What a frame changes, as written: the root's viewBox, width and height, every stroke's data and every
    /// background's numbers.
    static func written(_ svg: String) -> [String] {
        SketchEditing.elements(svg).compactMap { element in
            let tag = element.tag
            switch tag.name {
            case "svg": return ["viewBox", "width", "height"].map { tag.value($0) ?? "-" }.joined(separator: "|")
            case "path": return tag.value("d")
            case "rect": return ["x", "y", "width", "height"].map { tag.value($0) ?? "-" }.joined(separator: "|")
            default: return nil
            }
        }
    }

    @Test func framesLikePython() throws {
        let fixture = try #require(Fixtures.json("export/framing.json").objectValue)
        let sketches = fixture["sketches"]?.arrayValue?.compactMap(\.objectValue) ?? []
        #expect(sketches.count == 4)
        for s in sketches {
            let name = s["svg"]?.stringValue ?? ""
            let svg = String(decoding: try Fixtures.data(name), as: UTF8.self)
            #expect(Self.close(SketchFraming.contentBox(svg), Self.numbers(s["content_box"])), "\(name)")
            for f in (s["frames"]?.arrayValue ?? []).compactMap(\.objectValue) {
                let mode = try #require(SketchFraming.Mode(rawValue: f["mode"]?.stringValue ?? ""))
                let frame = SketchFraming.PhotoFrame(f["frame"])
                let margin = f["margin"]?.doubleValue ?? 0
                let framing = SketchFraming.make(svg, mode: mode, frame: frame, margin: margin)
                let what = "\(name) \(mode) \(margin) \(String(describing: frame))"
                #expect(Self.close(framing?.box, Self.numbers(f["box"])), "\(what)")
                #expect(framing.map { abs($0.yScale - (f["y_scale"]?.doubleValue ?? .nan)) < 1e-9 } ?? f["y_scale"]?.isNull == true,
                        "\(what)")
                if let framing, let python = f["output"]?.stringValue {
                    let swift = framing.apply(svg)
                    #expect(Self.written(swift) == Self.written(python), "\(what)")
                    #expect(try SketchSVG.parse(swift) == SketchSVG.parse(python), "\(what)")
                }
            }
        }
    }

    @Test func oldRunsTakeTheFrameFromTheirSettings() throws {
        let fixture = try #require(Fixtures.json("export/framing.json").objectValue)
        for g in (fixture["guesses"]?.arrayValue ?? []).compactMap(\.objectValue) {
            let size = (g["size"]?.arrayValue ?? []).compactMap(\.intValue)
            let frame = SketchFraming.guessFrame(method: g["method"]?.stringValue ?? "", settings: g["settings"]?.objectValue ?? [:],
                                                 width: size[0], height: size[1])
            let python = SketchFraming.PhotoFrame(g["frame"])
            #expect((frame == nil) == (python == nil), "\(g)")
            if let frame, let python {
                #expect(abs(frame.aspect - python.aspect) < 1e-6 && Self.close(frame.rect, python.rect, 1e-6), "\(g)")
            }
        }
    }

    /// config.json's frame first; for an old run the one its settings and photo give.
    @Test func aRunsFrame() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: "frame-\(UUID().uuidString)", directoryHint: .isDirectory)
        let run = dir.appending(path: "job/run", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        try Data(#"{"photo_frame": {"aspect": 0.75, "rect": [0.125, 0, 0.875, 1]}}"#.utf8).write(to: run.appending(path: "config.json"))
        #expect(SketchFraming.runFrame(runDir: run) { _ in nil } == SketchFraming.PhotoFrame(aspect: 0.75, rect: [0.125, 0, 0.875, 1]))
        let photo = dir.appending(path: "Kamel.png")
        try Data().write(to: photo)
        try Data(#"{"method": "clipasso", "settings": {"fix_scale": true}}"#.utf8).write(to: run.appending(path: "config.json"))
        try Data(#"{"target": "\#(photo.path)", "settings": {"fix_scale": true}, "method": "clipasso", "status": "done"}"#.utf8)
            .write(to: dir.appending(path: "job/job_state.json"))
        let guessed = SketchFraming.runFrame(runDir: run) { url in url.lastPathComponent == "Kamel.png" ? (300, 200) : nil }
        #expect(guessed == SketchFraming.guessFrame(method: "clipasso", settings: ["fix_scale": true], width: 300, height: 200))
        #expect(SketchFraming.runFrame(runDir: run) { _ in nil } == nil)  // (the photo cannot be measured)
    }

    /// The canvas shown in the photo's shape: stretched onto the square (no fix_scale) → the photo's aspect; padded
    /// (fix_scale) or a square part of the photo → square; the frames as framing.photo_frame writes them.
    @Test func theCanvasInThePhotosShape() {
        #expect(SketchFraming.PhotoFrame(aspect: 4.0 / 3, rect: [0, 0, 1, 1]).canvasStretch == 4.0 / 3)  // (stretched)
        #expect(abs(SketchFraming.PhotoFrame(aspect: 0.75, rect: [0, 0, 1, 1]).canvasStretch - 0.75) < 1e-12)
        // fix_scale: 400 × 300 at (10, 60) on a square of 420 (framing.fix_scale_pad)
        let padded = SketchFraming.PhotoFrame(aspect: 4.0 / 3, rect: [10.0 / 420, 60.0 / 420, 410.0 / 420, 360.0 / 420])
        #expect(abs(padded.canvasStretch - 1) < 1e-9)
        // SceneSketch: the middle square of a 300 × 200 photo (the photo reaches beyond the canvas)
        let cropped = SketchFraming.PhotoFrame(aspect: 1.5, rect: [-0.25, 0, 1.25, 1])
        #expect(abs(cropped.canvasStretch - 1) < 1e-9)
        #expect(SketchFraming.PhotoFrame(aspect: 40, rect: [0, 0, 1, 1]).canvasStretch == 5)
        #expect(SketchFraming.PhotoFrame(aspect: 1.5, rect: [0, 0, 0, 1]).canvasStretch == 1)
    }

    /// The phone's picture of a sketch in the photo's shape: its size stretched, its strokes where they were.
    @Test func aPictureInThePhotosShape() {
        let svg = #"<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224" preserveAspectRatio="xMidYMid"><path d="M0 0 L5 5"/></svg>"#
        let wide = SketchFraming.stretchedForDisplay(svg, stretch: 1.5)
        #expect(wide.contains(#"width="336" height="224" preserveAspectRatio="none""#))
        #expect(!wide.contains(#"width="224""#) && !wide.contains("xMidYMid") && wide.contains(#"viewBox="0 0 224 224""#))
        #expect(wide.contains(#"<path d="M0 0 L5 5"/>"#) && wide.hasPrefix(#"<?xml version="1.0"?><svg"#))
        let tall = SketchFraming.stretchedForDisplay(svg, stretch: 0.5)
        #expect(tall.contains(#"width="224" height="448""#))
        #expect(SketchFraming.stretchedForDisplay(svg, stretch: 1) == svg)
        #expect(SketchFraming.stretchedForDisplay("not a sketch", stretch: 2) == "not a sketch")
    }
}
