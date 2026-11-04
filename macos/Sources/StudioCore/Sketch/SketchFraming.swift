import Foundation

/// The frame of an exported sketch (engine/framing.py): the square canvas it was drawn on, the shape of the original
/// photo, or cropped to its strokes. A frame changes the SVG's viewBox, width and height – and the backgrounds that
/// filled the canvas – only; the strokes stay vectors. A canvas the photo was stretched onto is stretched back by
/// moving the points vertically (the stroke widths stay).
public enum SketchFraming {
    public enum Mode: String, Sendable, CaseIterable {
        case square, photo, content
    }

    /// framing.DEFAULT_MARGIN: the free space around the strokes ("content"), as a share of their longer side
    public static let defaultMargin = 0.05
    /// framing.FRAME_KEY: where a run's config.json keeps its photo frame (from 3.0 on)
    public static let frameKey = "photo_frame"

    /// Where the photo lies on a method's square canvas: its aspect (W / H) and its rect in canvas units of 0…1
    /// (beyond that when the canvas shows only a part of the photo).
    public struct PhotoFrame: Sendable, Equatable {
        public let aspect: Double
        public let rect: [Double]

        public init(aspect: Double, rect: [Double]) {
            self.aspect = aspect
            self.rect = rect
        }

        init?(_ json: JSONValue?) {
            guard let o = json?.objectValue, let aspect = o["aspect"]?.doubleValue, aspect != 0,
                  let rect = o["rect"]?.arrayValue?.compactMap(\.doubleValue), rect.count == 4
            else { return nil }
            self.init(aspect: aspect, rect: rect)
        }
    }

    /// A new frame for the sketches of a run: `box` is the new viewBox; with `yScale` ≠ 1 the points are first
    /// moved vertically by that factor around `originY`.
    public struct Framing: Sendable, Equatable {
        public let box: [Double]
        public var yScale = 1.0
        public var originY = 0.0

        public var aspect: Double { box[2] / max(box[3], 1e-9) }

        /// Framing.apply
        public func apply(_ svg: String) -> String {
            let all = SketchEditing.elements(svg)
            guard let root = all.first else { return svg }
            let (vx, vy, vw, vh) = SketchFraming.viewBox(root.tag)
            let (bx, by, bw, bh) = (box[0], box[1], box[2], box[3])
            var out = ""
            var index = svg.startIndex
            func replace(_ element: SketchEditing.Element, with tag: SketchExport.StartTag) {
                out += svg[index..<element.start] + tag.text
                index = element.tagEnd
            }
            // the root: the new viewBox, as large in user units as before
            var top = root.tag
            let digits = (top.value("width") ?? "").filter { $0.isNumber || $0 == "." }
            let px = (digits.isEmpty ? vw : Double(digits) ?? .nan) / vw
            let scale = px.isFinite ? px : 1
            top.set("viewBox", "\(fmt(bx)) \(fmt(by)) \(fmt(bw)) \(fmt(bh))")
            top.set("width", fmt(bw * scale))
            top.set("height", fmt(bh * scale))
            replace(root, with: top)
            for element in all.dropFirst() {
                var tag = element.tag
                if tag.name == "path", abs(yScale - 1) > 1e-6, let d = tag.value("d"),
                   let scaled = SketchFraming.scaledD(d, originY: originY, factor: yScale)
                {
                    tag.set("d", scaled)
                } else if tag.name == "rect", SketchFraming.covers(tag, vx, vy, vw, vh) {
                    for (key, value) in [("x", bx), ("y", by), ("width", bw), ("height", bh)] { tag.set(key, fmt(value)) }
                } else {
                    continue
                }
                replace(element, with: tag)
            }
            return out + svg[index...]
        }

        func fmt(_ v: Double) -> String { SketchEditing.decimal(v, 3, zero: true) }
    }

    /// framing._view_box: the viewBox (when its size is positive), else 0, 0 and the width and height's numbers.
    static func viewBox(_ root: SketchExport.StartTag) -> (Double, Double, Double, Double) {
        if let box = root.value("viewBox")?.trimmingCharacters(in: .whitespacesAndNewlines), !box.isEmpty {
            let values = box.split(whereSeparator: { $0.isWhitespace || $0 == "," }).prefix(4).compactMap { Double($0) }
            if values.count == 4, values[2] > 0, values[3] > 0 { return (values[0], values[1], values[2], values[3]) }
        }
        func number(_ key: String) -> Double {
            let text = (root.value(key) ?? "").trimmingCharacters(in: .whitespaces)
            var digits = ""
            for c in text {
                if c.isNumber || c == "." || (digits.isEmpty && (c == "-" || c == "+")) { digits.append(c) } else { break }
            }
            return Double(digits) ?? 224
        }
        return (0, 0, number("width"), number("height"))
    }

    /// framing._covers: a rect that fills the whole canvas – a background.
    static func covers(_ rect: SketchExport.StartTag, _ vx: Double, _ vy: Double, _ vw: Double, _ vh: Double) -> Bool {
        let x = rect.value("x"), y = rect.value("y"), w = rect.value("width"), h = rect.value("height")
        if w == "100%", h == "100%", ["0", "0%"].contains(x ?? "0"), ["0", "0%"].contains(y ?? "0") { return true }
        func number(_ s: String?, _ fallback: Double?) -> Double? {
            guard let s else { return fallback }
            return Double(s.trimmingCharacters(in: .whitespaces))
        }
        guard let nx = number(x, 0), let ny = number(y, 0), let nw = number(w, nil), let nh = number(h, nil) else {
            return false
        }
        return zip([nx, ny, nw, nh], [vx, vy, vw, vh]).allSatisfy { abs($0 - $1) < 1e-6 }
    }

    /// framing.content_box: (x0, y0, x1, y1) of all strokes (their control points, plus half their width).
    public static func contentBox(_ svg: String) -> [Double]? {
        var box: [Double]?
        for path in SketchEditing.paths(SketchEditing.elements(svg)) {
            let raw = (path.tag.value("stroke-width") ?? "").trimmingCharacters(in: .whitespaces)
            guard let width = raw.isEmpty ? 1 : Double(raw), let subpaths = try? SketchSVG.parsePath(path.tag.value("d") ?? "")
            else { continue }
            let half = width / 2
            for sub in subpaths {
                for segment in sub.segments {
                    for p in segment {
                        let b = [p.x - half, p.y - half, p.x + half, p.y + half]
                        box = box.map { [min($0[0], b[0]), min($0[1], b[1]), max($0[2], b[2]), max($0[3], b[3])] } ?? b
                    }
                }
            }
        }
        return box
    }

    /// framing._scaled_d: path data with every y moved by `factor` around `originY` (nil: data it cannot read).
    static func scaledD(_ d: String, originY: Double, factor: Double) -> String? {
        guard let subpaths = try? SketchSVG.parsePath(d) else { return nil }
        func f(_ v: Double) -> String { SketchEditing.decimal(v, 3, zero: true) }
        func y(_ v: Double) -> String { f(originY + (v - originY) * factor) }
        var parts: [String] = []
        for sub in subpaths {
            guard let first = sub.segments.first?.first else { continue }
            parts.append("M \(f(first.x)) \(y(first.y))")
            for segment in sub.segments {
                let command: String
                switch segment.count {
                case 2: command = "L"
                case 3: command = "Q"
                case 4: command = "C"
                default: continue
                }
                parts.append(command + " " + segment.dropFirst().map { "\(f($0.x)) \(y($0.y))" }.joined(separator: " "))
            }
            if sub.closed { parts.append("Z") }
        }
        return parts.joined(separator: " ")
    }

    /// framing.make_framing: the frame for `mode` (nil for "square": nothing changes; for "photo" without the run's
    /// `frame`; for "content" without strokes).
    public static func make(_ svg: String, mode: Mode, frame: PhotoFrame? = nil, margin: Double = defaultMargin)
        -> Framing?
    {
        guard let root = SketchEditing.elements(svg).first else { return nil }
        let (vx, vy, vw, vh) = viewBox(root.tag)
        switch mode {
        case .square:
            return nil
        case .content:
            guard let b = contentBox(svg) else { return nil }
            let pad = max(margin, 0) * max(b[2] - b[0], b[3] - b[1])
            return Framing(box: [b[0] - pad, b[1] - pad, b[2] - b[0] + 2 * pad, b[3] - b[1] + 2 * pad])
        case .photo:
            guard let frame else { return nil }
            let (x0, y0, x1, y1) = (frame.rect[0], frame.rect[1], frame.rect[2], frame.rect[3])
            let left = vx + x0 * vw, top = vy + y0 * vh
            let width = (x1 - x0) * vw, height = (y1 - y0) * vh
            let wanted = width / max(frame.aspect, 1e-9)  // (the height the photo's shape asks for)
            let factor = wanted / max(height, 1e-9)
            if abs(factor - 1) < 1e-3 { return Framing(box: [left, top, width, height]) }  // the same scale both ways
            return Framing(box: [left, top, width, wanted], yScale: factor, originY: top)
        }
    }

    // MARK: - where the photo lies on the canvas

    /// framing.fix_scale_pad: (side, x, y, w, h) of the image centred on a square with `margin` px.
    static func fixScalePad(width: Int, height: Int, margin: Int = 10) -> [Int] {
        let side = max(width, height) + 2 * margin
        return [side, side / 2 - width / 2, side / 2 - height / 2, width, height]
    }

    /// framing.photo_frame: `region` (left, top, right, bottom in photo pixels) is the part the method's image shows;
    /// `pad` (side, x, y, w, h) that image on a square (fix_scale) – without it the image is stretched onto the canvas.
    static func photoFrame(width: Int, height: Int, region: [Double]? = nil, pad: [Int]? = nil) -> PhotoFrame {
        let (w, h) = (Double(width), Double(height))
        let part0 = region ?? [0, 0, w, h]
        let inner: [Double]
        if let pad {
            let side = Double(pad[0])
            inner = [Double(pad[1]) / side, Double(pad[2]) / side, Double(pad[1] + pad[3]) / side, Double(pad[2] + pad[4]) / side]
        } else {
            inner = [0, 0, 1, 1]
        }
        let part = [part0[0] / w, part0[1] / h, part0[2] / w, part0[3] / h]
        let sx = (inner[2] - inner[0]) / max(part[2] - part[0], 1e-9)
        let sy = (inner[3] - inner[1]) / max(part[3] - part[1], 1e-9)
        let rect = [inner[0] - part[0] * sx, inner[1] - part[1] * sy, inner[0] + (1 - part[0]) * sx,
                    inner[1] + (1 - part[1]) * sy]
        func round6(_ v: Double) -> Double { (v * 1e6).rounded(.toNearestOrEven) / 1e6 }
        return PhotoFrame(aspect: round6(w / h), rect: rect.map(round6))
    }

    /// framing.guess_frame: the photo frame of a run from before 3.0, from its settings (nil: a small object may have
    /// been zoomed onto, which was not recorded).
    public static func guessFrame(method: String, settings: JSONObject, width: Int, height: Int) -> PhotoFrame? {
        let on = { (key: String) in settings[key]?.truthy ?? false }
        if ["clipasso", "swiftsketch"].contains(method), on("mask_object"), on("frame_object") { return nil }
        if method == "scenesketch" {
            if width == height { return photoFrame(width: width, height: height) }
            if on("fix_scale") {
                let side = max(width, height)
                return photoFrame(width: width, height: height,
                                  pad: [side, (side - width) / 2, (side - height) / 2, width, height])
            }
            let side = min(width, height)
            let left = (width - side) / 2, top = (height - side) / 2
            return photoFrame(width: width, height: height,
                              region: [Double(left), Double(top), Double(left + side), Double(top + side)])
        }
        if on("fix_scale") { return photoFrame(width: width, height: height, pad: fixScalePad(width: width, height: height)) }
        return photoFrame(width: width, height: height)
    }

    /// framing.run_frame: the photo frame a run saved in its config.json – else the one worked out from its job's
    /// settings and the photo's size (`photoSize`: how to measure an image; nil when it cannot be known).
    public static func runFrame(runDir: URL, photoSize: (URL) -> (Int, Int)?) -> PhotoFrame? {
        let config = (try? Data(contentsOf: runDir.appending(path: "config.json"))).flatMap { try? PyJSON.parse($0) }?
            .objectValue ?? [:]
        if let saved = PhotoFrame(config[frameKey]) { return saved }
        let jobDir = runDir.deletingLastPathComponent()
        let state = JobFolder.readState(at: jobDir) ?? [:]
        let settings = state["settings"]?.objectValue ?? config["settings"]?.objectValue ?? [:]
        let method = [state["method"], config["method"]].compactMap { $0?.stringValue }.first { !$0.isEmpty } ?? "clipasso"
        let target = [state["target"], config["target"]].compactMap { $0?.stringValue }.first { !$0.isEmpty } ?? ""
        let image = FileManager.default.fileExists(atPath: target) ? URL(filePath: target)
            : JobFolder.savedInput(jobDir: jobDir, target: target)
        guard let image, let (w, h) = photoSize(image) else { return nil }
        return guessFrame(method: method, settings: settings, width: w, height: h)
    }
}

#if canImport(ImageIO)
    import ImageIO

    public extension SketchFraming {
        /// framing.photo_size: an image's size as it is loaded (EXIF rotation applied), without decoding it.
        static func imageSize(_ url: URL) -> (Int, Int)? {
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let width = properties[kCGImagePropertyPixelWidth] as? Int,
                  let height = properties[kCGImagePropertyPixelHeight] as? Int
            else { return nil }
            let orientation = properties[kCGImagePropertyOrientation] as? Int ?? 1
            return (5...8).contains(orientation) ? (height, width) : (width, height)  // (rotated by 90°)
        }

        /// The run's photo frame, the image measured with ImageIO.
        static func runFrame(runDir: URL) -> PhotoFrame? { runFrame(runDir: runDir, photoSize: imageSize) }
    }
#endif
