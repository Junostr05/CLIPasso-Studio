import Foundation

/// Lottie (bodymovin JSON) of a sketch, as export.lottie writes it: one shape layer per stroke whose trim path grows
/// along it in the drawing's order and timing, plain strokes (Lottie has no brush styles), the background colour or
/// the paper (an embedded picture) below. The numbers keep Python's kinds (whole numbers stay whole), so the JSON is
/// the studio's to the character.
public extension SketchFormats {
    static let lottieFPS = 30
    /// px: the longer side of the composition
    static let lottieSize = 512

    private static func still(_ value: JSONValue) -> JSONValue { ["a": 0, "k": value] }

    private static func transform(shapeGroup: Bool = false) -> JSONValue {
        if shapeGroup {
            return ["ty": "tr", "p": still([0, 0]), "a": still([0, 0]), "s": still([100, 100]), "r": still(0),
                    "o": still(100), "sk": still(0), "sa": still(0)]
        }
        return ["o": still(100), "r": still(0), "p": still([0, 0, 0]), "a": still([0, 0, 0]), "s": still([100, 100, 100])]
    }

    /// QColor(name) as the studio reads it: "#rgb", "#rrggbb" or an SVG colour name – anything else (rgb()) is not a
    /// colour to it.
    internal static func qColor(_ name: String) -> RGB? {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard trimmed.hasPrefix("#") || trimmed.allSatisfy(\.isLetter) else { return nil }
        return SketchSVG.color(trimmed)
    }

    /// _lottie_rgb: red, green, blue (0 … 1, four places) and 1.
    private static func rgb(_ name: String) -> JSONValue {
        let c = qColor(name) ?? RGB(0, 0, 0)
        func unit(_ v: Int) -> JSONValue { .double(Python.round(Double(v) / 255, digits: 4)) }
        return [unit(c.r), unit(c.g), unit(c.b), 1]
    }

    /// A number as Python keeps it: a whole number (Int) stays whole when rounded, a float stays a float.
    private enum Number {
        case int(Int)
        case double(Double)

        func minus(_ other: Number) -> Number {
            switch (self, other) {
            case (.int(let a), .int(let b)): .int(a - b)
            default: .double(value - other.value)
            }
        }

        var value: Double {
            switch self {
            case .int(let i): Double(i)
            case .double(let d): d
            }
        }

        /// round(x, 3)
        var rounded: JSONValue {
            switch self {
            case .int(let i): .int(i)
            case .double(let d): .double(Python.round(d, digits: 3))
            }
        }
    }

    /// lottie_paths: the sub-paths of path data as Lottie shapes – vertices (moved by -x0, -y0, scaled) with their in
    /// and out tangents; quadratic curves become cubic ones.
    static func lottiePaths(_ d: String, x0: Double = 0, y0: Double = 0, scale: Double = 1) -> [JSONValue] {
        guard let subpaths = try? SketchSVG.parsePath(d) else { return [] }
        func pt(_ p: SketchPoint) -> [Double] { [(p.x - x0) * scale, (p.y - y0) * scale] }
        let zero: [Number] = [.int(0), .int(0)]
        func diff(_ a: [Double], _ b: [Double]) -> [Number] { [.double(a[0] - b[0]), .double(a[1] - b[1])] }
        var out: [JSONValue] = []
        for sub in subpaths {
            var v: [[Number]] = [], ins: [[Number]] = [], outs: [[Number]] = []
            for segment in sub.segments {
                let pts = segment.map(pt)
                let (p0, p3) = (pts[0], pts[pts.count - 1])
                let c1: [Double], c2: [Double]
                if pts.count == 2 {
                    (c1, c2) = (p0, p3)
                } else if pts.count == 3 {
                    let q = pts[1]
                    c1 = [p0[0] + 2.0 / 3 * (q[0] - p0[0]), p0[1] + 2.0 / 3 * (q[1] - p0[1])]
                    c2 = [p3[0] + 2.0 / 3 * (q[0] - p3[0]), p3[1] + 2.0 / 3 * (q[1] - p3[1])]
                } else {
                    (c1, c2) = (pts[1], pts[2])
                }
                if v.isEmpty {
                    v.append(p0.map { .double($0) })
                    ins.append(zero)
                    outs.append(zero)
                }
                outs[outs.count - 1] = diff(c1, p0)
                v.append(p3.map { .double($0) })
                ins.append(diff(c2, p3))
                outs.append(zero)
            }
            if sub.closed, v.count > 2, abs(v[0][0].value - v[v.count - 1][0].value) < 1e-6,
               abs(v[0][1].value - v[v.count - 1][1].value) < 1e-6
            {
                let closing = ins.removeLast()
                ins[0] = closing
                v.removeLast()
                outs.removeLast()
            }
            guard v.count >= 2 else { continue }
            func rounded(_ points: [[Number]]) -> JSONValue { .array(points.map { .array($0.map(\.rounded)) }) }
            out.append(["ty": "sh", "ks": still(["i": rounded(ins), "o": rounded(outs), "v": rounded(v),
                                                 "c": .bool(sub.closed)])])
        }
        return out
    }

    /// _reversed_shape: the same Lottie path drawn from its other end.
    private static func reversedShape(_ shape: JSONValue) -> JSONValue {
        guard let k = shape.objectValue?["ks"]?.objectValue?["k"]?.objectValue else { return shape }
        func backwards(_ key: String) -> JSONValue { .array((k[key]?.arrayValue ?? []).reversed()) }
        return ["ty": "sh", "ks": still(["i": backwards("o"), "o": backwards("i"), "v": backwards("v"), "c": k["c"] ?? false])]
    }

    private static func point(_ shape: JSONValue, last: Bool) -> [Double] {
        let v = shape.objectValue?["ks"]?.objectValue?["k"]?.objectValue?["v"]?.arrayValue ?? []
        return ((last ? v.last : v.first)?.arrayValue ?? []).compactMap(\.doubleValue)
    }

    /// lottie: the composition (`size` px for the longer side, 30 frames a second).
    static func lottie(_ svg: String, length: Double? = nil, hold: Double = 1, strokeColor: String? = nil,
                       widthScale: Double = 1, background: String? = nil, keepOrder: Bool = false, paper: Paper? = nil,
                       name: String = "sketch", size: Int = lottieSize) -> JSONValue
    {
        let drawing = Drawing(svg: svg, keepOrder: keepOrder)
        let n = drawing.strokeCount
        let length = length.map { max($0, 0.1) } ?? SketchAnimation.defaultDrawingLength(strokes: n, line: drawing.line)
        let total = length + max(hold, 0)
        let op = max(1, Int((total * Double(lottieFPS)).rounded(.toNearestOrEven)))
        let box = SketchEditing.viewBox(svg)
        let scale = Double(size) / max(box.width, box.height, 1e-9)
        let w = max(1, Int((box.width * scale).rounded(.toNearestOrEven)))
        let h = max(1, Int((box.height * scale).rounded(.toNearestOrEven)))
        var layers: [JSONValue] = [], assets: [JSONValue] = []
        for i in 0 ..< n {
            let stroke = drawing.strokes[i]
            let (a, b) = drawing.spans[i]
            let d = stroke.xml.range(of: #"\sd="([^"]*)""#, options: .regularExpression).map {
                String(stroke.xml[$0].drop { $0 != "\"" }.dropFirst().dropLast())
            }
            var shapes = lottiePaths(d ?? drawing.centreline(i), x0: box.x, y0: box.y, scale: scale)
            guard !shapes.isEmpty else { continue }
            let first = point(shapes[0], last: false), last = point(shapes[shapes.count - 1], last: true)
            let s0 = stroke.subs[0][0]
            let start = [(s0.x - box.x) * scale, (s0.y - box.y) * scale]
            func dist(_ p: [Double], _ q: [Double]) -> Double { Python.hypot(p[0] - q[0], p[1] - q[1]) }  // (math.dist)
            if dist(start, last) < dist(start, first) - 1e-6 {  // (the route draws this stroke backwards)
                shapes = shapes.reversed().map(reversedShape)
            }
            let attribute = { (key: String) in stroke.attributes.first { $0.name == key }?.value }
            var width: Double, opacity: Double
            if let sw = Python.float(attribute("stroke-width") ?? "1"),
               let so = Python.float(attribute("stroke-opacity") ?? "1")
            {
                (width, opacity) = (sw * widthScale * scale, so * 100)
            } else {
                (width, opacity) = (widthScale * scale, 100)
            }
            let f0 = Python.round(a / drawing.total * length * Double(lottieFPS), digits: 2)
            let f1 = max(Python.round(b / drawing.total * length * Double(lottieFPS), digits: 2), f0 + 0.5)
            let trimEnd: JSONValue = ["a": 1, "k": [["t": .double(f0), "s": [0], "i": ["x": [1], "y": [1]],
                                                     "o": ["x": [0], "y": [0]]], ["t": .double(f1), "s": [100]]]]
            let line: JSONValue = ["ty": "st", "c": still(rgb(strokeColor ?? attribute("stroke") ?? "#000000")),
                                   "o": still(.double(Python.round(opacity, digits: 2))),
                                   "w": still(.double(Python.round(width, digits: 3))), "lc": 2, "lj": 2, "ml": 4,
                                   "nm": "stroke"]
            let trim: JSONValue = ["ty": "tm", "s": still(0), "e": trimEnd, "o": still(0), "m": 2, "nm": "draw"]
            layers.append(["ddd": 0, "ind": .int(i + 1), "ty": 4, "nm": .string("stroke \(i + 1)"), "sr": 1,
                           "ks": transform(), "ao": 0,
                           "shapes": [["ty": "gr", "nm": .string("stroke \(i + 1)"),
                                       "it": .array(shapes + [line, trim, transform(shapeGroup: true)])]],
                           "ip": 0, "op": .int(op), "st": 0, "bm": 0])
        }
        layers.reverse()  // (the first layer is drawn on top: the later strokes over the earlier ones)
        let ind = JSONValue.int(n + 1)
        #if canImport(ImageIO)
            if let paper, let picture = try? PaperPicture.image(paper, width: w, height: h, background: background),
               let jpeg = PaperPicture.jpegData(picture, quality: 0.88)
            {
                assets.append(["id": "paper", "w": .int(w), "h": .int(h), "u": "", "e": 1,
                               "p": .string("data:image/jpeg;base64," + jpeg.base64EncodedString())])
                layers.append(["ddd": 0, "ind": ind, "ty": 2, "nm": "paper", "refId": "paper", "sr": 1, "ks": transform(),
                               "ao": 0, "ip": 0, "op": .int(op), "st": 0, "bm": 0])
                return composition(op: op, w: w, h: h, name: name, assets: assets, layers: layers)
            }
        #endif
        if let background, !background.isEmpty {  // (QColor's name: black when it is no colour)
            let c = qColor(background) ?? RGB(0, 0, 0)
            layers.append(["ddd": 0, "ind": ind, "ty": 1, "nm": "background",
                           "sc": .string(String(format: "#%02x%02x%02x", c.r, c.g, c.b)), "sw": .int(w), "sh": .int(h),
                           "sr": 1, "ks": transform(), "ao": 0, "ip": 0, "op": .int(op), "st": 0, "bm": 0])
        }
        return composition(op: op, w: w, h: h, name: name, assets: assets, layers: layers)
    }

    private static func composition(op: Int, w: Int, h: Int, name: String, assets: [JSONValue], layers: [JSONValue])
        -> JSONValue
    {
        ["v": "5.7.4", "fr": .int(lottieFPS), "ip": 0, "op": .int(op), "w": .int(w), "h": .int(h), "nm": .string(name),
         "ddd": 0, "assets": .array(assets), "layers": .array(layers), "markers": []]
    }
}
