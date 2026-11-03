import Foundation

#if canImport(FoundationXML)
    import FoundationXML
#endif

public struct SketchPoint: Sendable, Hashable, CustomStringConvertible {
    public var x: Double
    public var y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }

    public var description: String { "(\(x), \(y))" }
}

public struct RGB: Sendable, Hashable {
    public var r: Int, g: Int, b: Int

    public init(_ r: Int, _ g: Int, _ b: Int) {
        (self.r, self.g, self.b) = (r, g, b)
    }

    public init(_ values: [Int]) {
        self.init(values.count > 0 ? values[0] : 0, values.count > 1 ? values[1] : 0, values.count > 2 ? values[2] : 0)
    }
}

/// One segment of a stroke after its start (or the previous segment's end): a line (its end), a quadratic Bézier
/// (control, end) or a cubic one (two controls, end).
public struct SketchSegment: Sendable, Hashable {
    public let kind: String  // line · quad · cubic
    public let points: [SketchPoint]
}

public struct SketchStroke: Sendable, Hashable {
    public var start: SketchPoint
    public var segments: [SketchSegment]
    public var closed: Bool
    public var color: RGB
    public var opacity: Double
    public var width: Double
    /// drawn by hand in the studio (data-fixed): stays as it is
    public var fixed: Bool
}

public struct Sketch: Sendable, Hashable {
    public var width: Int
    public var height: Int
    public var background: String?
    public var strokes: [SketchStroke]
}

/// Reads the sketches the engine writes (engine/svg_io.py: best_iter.svg, edited.svg, the live preview) as
/// svg_io.load_svg reads them: `<path>`, `<line>`, `<polyline>`, `<polygon>`, colours as `rgb()` or `#hex`, the
/// opacity, the width and the viewBox; path data as engine/svg_path.py parses it (arcs become cubic Béziers).
public enum SketchSVG {
    public struct ParseError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    public struct Subpath: Sendable, Hashable {
        /// every segment with its start point first (2 points: a line, 3: quadratic, 4: cubic)
        public let segments: [[SketchPoint]]
        public let closed: Bool
    }

    // MARK: - path data (svg_path.parse_path_d)

    private static let token = try! NSRegularExpression(
        pattern: #"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"#)
    private static let argumentCount: [Character: Int] = ["M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4,
                                                          "T": 2, "A": 7, "Z": 0]

    public static func parsePath(_ d: String) throws -> [Subpath] {
        let tokens = token.matches(in: d, range: NSRange(d.startIndex..., in: d)).compactMap {
            Range($0.range, in: d).map { String(d[$0]) }
        }
        var i = 0
        var cmd: Character?
        var cur = SketchPoint(x: 0, y: 0)
        var start = cur
        var lastControl: SketchPoint?
        var lastCmd: Character?
        var subpaths: [Subpath] = []
        var segments: [[SketchPoint]] = []
        var closed = false

        func flush() {
            if !segments.isEmpty { subpaths.append(Subpath(segments: segments, closed: closed)) }
            segments = []
            closed = false
        }

        while i < tokens.count {
            let tok = tokens[i]
            if let c = tok.first, tok.count == 1, c.isLetter {
                cmd = c
                i += 1
                if c == "Z" || c == "z" {
                    if !segments.isEmpty {
                        if cur != start { segments.append([cur, start]) }
                        closed = true
                        flush()
                    }
                    cur = start
                    lastControl = nil
                    lastCmd = "Z"
                    continue
                }
            } else if cmd == nil {
                throw ParseError(description: "path data must start with a command: \(d.prefix(40))")
            }
            guard let command = cmd, let n = argumentCount[Character(command.uppercased())] else { break }
            guard i + n <= tokens.count else { break }
            let args = tokens[i..<(i + n)].compactMap(Double.init)
            guard args.count == n else { break }
            i += n
            let rel = command.isLowercase
            let up = Character(command.uppercased())
            let ox = rel ? cur.x : 0, oy = rel ? cur.y : 0
            func at(_ k: Int) -> SketchPoint { SketchPoint(x: ox + args[k], y: oy + args[k + 1]) }
            func reflected(_ kinds: String) -> SketchPoint {
                if let lastCmd, kinds.contains(lastCmd), let c = lastControl {
                    return SketchPoint(x: 2 * cur.x - c.x, y: 2 * cur.y - c.y)
                }
                return cur
            }
            switch up {
            case "M":
                flush()
                cur = at(0)
                start = cur
                cmd = rel ? "l" : "L"  // further pairs are implicit line-tos
                lastControl = nil
            case "L":
                let p = at(0)
                segments.append([cur, p])
                (cur, lastControl) = (p, nil)
            case "H":
                let p = SketchPoint(x: (rel ? cur.x : 0) + args[0], y: cur.y)
                segments.append([cur, p])
                (cur, lastControl) = (p, nil)
            case "V":
                let p = SketchPoint(x: cur.x, y: (rel ? cur.y : 0) + args[0])
                segments.append([cur, p])
                (cur, lastControl) = (p, nil)
            case "C":
                let (c1, c2, p) = (at(0), at(2), at(4))
                segments.append([cur, c1, c2, p])
                (cur, lastControl) = (p, c2)
            case "S":
                let c1 = reflected("CcSs")
                let (c2, p) = (at(0), at(2))
                segments.append([cur, c1, c2, p])
                (cur, lastControl) = (p, c2)
            case "Q":
                let (c, p) = (at(0), at(2))
                segments.append([cur, c, p])
                (cur, lastControl) = (p, c)
            case "T":
                let c = reflected("QqTt")
                let p = at(0)
                segments.append([cur, c, p])
                (cur, lastControl) = (p, c)
            case "A":
                let p = at(5)
                segments += arcToCubics(cur, args[0], args[1], args[2], args[3] != 0, args[4] != 0, p)
                (cur, lastControl) = (p, nil)
            default:
                break
            }
            lastCmd = cmd
        }
        flush()
        return subpaths
    }

    /// svg_path._arc_to_cubics: an arc in endpoint form as cubic segments (SVG spec F.6).
    static func arcToCubics(_ p0: SketchPoint, _ rxIn: Double, _ ryIn: Double, _ phiDeg: Double, _ largeArc: Bool,
                            _ sweep: Bool, _ p1: SketchPoint) -> [[SketchPoint]]
    {
        if rxIn == 0 || ryIn == 0 || (p0.x == p1.x && p0.y == p1.y) { return [[p0, p1]] }
        var rx = abs(rxIn), ry = abs(ryIn)
        let phi = phiDeg.truncatingRemainder(dividingBy: 360) * .pi / 180
        let phiPositive = phi < 0 ? phi + 2 * .pi : phi  // (Python's % gives a value ≥ 0)
        let cosP = cos(phiPositive), sinP = sin(phiPositive)
        let dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2
        let x1p = cosP * dx + sinP * dy
        let y1p = -sinP * dx + cosP * dy
        let lam = (x1p / rx) * (x1p / rx) + (y1p / ry) * (y1p / ry)
        if lam > 1 {
            let s = lam.squareRoot()
            rx *= s
            ry *= s
        }
        let num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
        let den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
        var coef = den != 0 ? max(num / den, 0).squareRoot() : 0
        if largeArc == sweep { coef = -coef }
        let cxp = coef * rx * y1p / ry
        let cyp = -coef * ry * x1p / rx
        let cx = cosP * cxp - sinP * cyp + (p0.x + p1.x) / 2
        let cy = sinP * cxp + cosP * cyp + (p0.y + p1.y) / 2
        func angle(_ ux: Double, _ uy: Double, _ vx: Double, _ vy: Double) -> Double {
            atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        }
        let theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        var dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
        if !sweep, dtheta > 0 { dtheta -= 2 * .pi } else if sweep, dtheta < 0 { dtheta += 2 * .pi }
        let n = max(Int((abs(dtheta) / (.pi / 2) - 1e-9).rounded(.up)), 1)
        let delta = dtheta / Double(n)
        let t = 4.0 / 3.0 * tan(delta / 4)
        func point(_ th: Double) -> SketchPoint {
            let x = rx * cos(th), y = ry * sin(th)
            return SketchPoint(x: cosP * x - sinP * y + cx, y: sinP * x + cosP * y + cy)
        }
        func deriv(_ th: Double) -> SketchPoint {
            let x = -rx * sin(th), y = ry * cos(th)
            return SketchPoint(x: cosP * x - sinP * y, y: sinP * x + cosP * y)
        }
        var segments: [[SketchPoint]] = []
        var th = theta1
        var from = p0
        for k in 0..<n {
            let th2 = th + delta
            let end = k == n - 1 ? p1 : point(th2)
            let d1 = deriv(th), d2 = deriv(th2)
            let c1 = SketchPoint(x: from.x + t * d1.x, y: from.y + t * d1.y)
            let c2 = SketchPoint(x: end.x - t * d2.x, y: end.y - t * d2.y)
            segments.append([from, c1, c2, end])
            from = end
            th = th2
        }
        return segments
    }

    // MARK: - the SVG file (svg_io.load_svg)

    private final class Collector: NSObject, XMLParserDelegate {
        var elements: [(name: String, attributes: [String: String])] = []

        func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                    qualifiedName qName: String?, attributes: [String: String] = [:])
        {
            let local = elementName.split(separator: ":").last.map(String.init) ?? elementName
            elements.append((local, attributes))
        }
    }

    private static func number(_ text: String?) -> Double? {
        guard let text else { return nil }
        let match = token.firstMatch(in: text, range: NSRange(text.startIndex..., in: text))
        return match.flatMap { Range($0.range, in: text) }.flatMap { Double(text[$0]) }
    }

    /// svg_io._style_dict: the attributes, with those of `style` on top.
    private static func style(_ attributes: [String: String]) -> [String: String] {
        var out = attributes
        for part in (attributes["style"] ?? "").split(separator: ";") {
            let kv = part.split(separator: ":", maxSplits: 1)
            if kv.count == 2 {
                out[kv[0].trimmingCharacters(in: .whitespaces)] = kv[1].trimmingCharacters(in: .whitespaces)
            }
        }
        return out
    }

    /// svg_io._parse_color, as 0 … 255.
    static func color(_ value: String?) -> RGB? {
        guard let value = value?.trimmingCharacters(in: .whitespaces), value != "none" else { return nil }
        func byte(_ unit: Double) -> Int { Int((min(max(unit, 0), 1) * 255).rounded()) }
        if value.hasPrefix("rgb("), value.hasSuffix(")") {
            let parts = value.dropFirst(4).dropLast().split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            let units = parts.prefix(3).map { p -> Double in
                p.hasSuffix("%") ? (Double(p.dropLast()) ?? 0) / 100 : (Double(p) ?? 0) / 255
            }
            return RGB(units.map(byte))
        }
        if value.hasPrefix("#") {
            var hex = String(value.dropFirst())
            if hex.count == 3 { hex = hex.map { "\($0)\($0)" }.joined() }
            guard hex.count >= 6, let v = Int(hex.prefix(6), radix: 16) else { return RGB(0, 0, 0) }
            return RGB(v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF)
        }
        return RGB(0, 0, 0)
    }

    public static func parse(_ text: String) throws -> Sketch {
        let parser = XMLParser(data: Data(text.utf8))
        let collector = Collector()
        parser.delegate = collector
        guard parser.parse(), let root = collector.elements.first, root.name == "svg" else {
            throw ParseError(description: "not an SVG")
        }
        let viewBox = (root.attributes["viewBox"] ?? "").split(whereSeparator: { $0 == " " || $0 == "," })
            .compactMap { Double($0) }
        let (vx, vy, vw, vh): (Double, Double, Double, Double) = viewBox.count >= 4
            ? (viewBox[0], viewBox[1], viewBox[2], viewBox[3])
            : (0, 0, number(root.attributes["width"]) ?? 224, number(root.attributes["height"]) ?? 224)
        let width = Int((number(root.attributes["width"]) ?? vw).rounded())
        let height = Int((number(root.attributes["height"]) ?? vh).rounded())
        let sx = Double(width) / vw, sy = Double(height) / vh
        var background: String?
        var strokes: [SketchStroke] = []
        for (name, raw) in collector.elements.dropFirst() {
            let attrs = style(raw)
            let d: String
            switch name {
            case "rect":
                if background == nil { background = attrs["fill"] }
                continue
            case "path": d = attrs["d"] ?? ""
            case "line":
                d = "M \(attrs["x1"] ?? "0") \(attrs["y1"] ?? "0") L \(attrs["x2"] ?? "0") \(attrs["y2"] ?? "0")"
            case "polyline", "polygon":
                let nums = token.matches(in: attrs["points"] ?? "", range: NSRange((attrs["points"] ?? "").startIndex..., in: attrs["points"] ?? ""))
                    .compactMap { Range($0.range, in: attrs["points"] ?? "").map { String((attrs["points"] ?? "")[$0]) } }
                guard nums.count >= 4 else { continue }
                let pairs = stride(from: 0, to: nums.count - 1, by: 2).map { "\(nums[$0]) \(nums[$0 + 1])" }
                d = "M " + pairs.joined(separator: " L ") + (name == "polygon" ? " Z" : "")
            default:
                continue
            }
            guard !d.trimmingCharacters(in: .whitespaces).isEmpty else { continue }
            let opacity = (number(attrs["stroke-opacity"]) ?? 1) * (number(attrs["opacity"]) ?? 1)
            let rgb = color(attrs["stroke"] ?? "rgb(0,0,0)") ?? RGB(0, 0, 0)
            let strokeWidth = (number(attrs["stroke-width"]) ?? 1) * (sx + sy) / 2
            let fixed = ["1", "true"].contains(attrs["data-fixed"] ?? "")
            func scaled(_ p: SketchPoint) -> SketchPoint { SketchPoint(x: (p.x - vx) * sx, y: (p.y - vy) * sy) }
            for sub in try parsePath(d) {
                guard let first = sub.segments.first?.first else { continue }
                let segments = sub.segments.map { seg -> SketchSegment in
                    let kind = seg.count == 2 ? "line" : seg.count == 3 ? "quad" : "cubic"
                    return SketchSegment(kind: kind, points: seg.dropFirst().map(scaled))
                }
                strokes.append(SketchStroke(start: scaled(first), segments: segments, closed: sub.closed, color: rgb,
                                            opacity: opacity, width: strokeWidth, fixed: fixed))
            }
        }
        return Sketch(width: width, height: height, background: background, strokes: strokes)
    }
}
