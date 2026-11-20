import Foundation

/// Editing the strokes of a finished sketch as the studio does it (gui/strokes.py: the eraser and the pen). A stroke
/// is a `<path>` element of the SVG, numbered in document order. The file's text is changed only where a stroke goes
/// or comes – every other element, comment and spacing stays as it was written.
public enum SketchEditing {
    /// strokes.FIXED_ATTR: a stroke drawn by hand, kept as it is when CLIPasso continues the sketch
    public static let fixedAttribute = "data-fixed"
    /// strokes.HIGHLIGHT: the stroke under the eraser
    public static let highlight = "#EF4444"
    /// brush.sample's points per segment in StrokeIndex
    public static let samplesPerSegment = 12
    /// strokes.PEN_TOLERANCE: how much a drawn stroke is simplified, as a share of the sketch's size
    static let penTolerance = 0.004

    // MARK: - the elements of the text

    /// An element of the SVG text: its start tag and where the element ends.
    struct Element {
        var tag: SketchExport.StartTag
        let start: String.Index
        let tagEnd: String.Index
        /// after the element (its closing tag, or the start tag when it closes itself)
        var end: String.Index
        /// where its closing tag starts (nil: it closes itself)
        var closeStart: String.Index?
        let parent: Int?
    }

    static func elements(_ svg: String) -> [Element] {
        var out: [Element] = []
        var open: [Int] = []
        var index = svg.startIndex
        while let lt = svg[index...].firstIndex(of: "<") {
            let rest = svg[lt...]
            let skip: String? = rest.hasPrefix("<!--") ? "-->" : rest.hasPrefix("<?") ? "?>"
                : rest.hasPrefix("<![CDATA[") ? "]]>" : rest.hasPrefix("<!") ? ">" : nil
            if let skip {
                index = rest.range(of: skip).map(\.upperBound) ?? svg.endIndex
                continue
            }
            let close = SketchExport.tagEnd(svg, from: lt)
            let text = String(svg[lt..<close])
            index = close
            if text.hasPrefix("</") {
                if let top = open.popLast() {
                    out[top].closeStart = lt
                    out[top].end = close
                }
                continue
            }
            out.append(Element(tag: SketchExport.StartTag(text), start: lt, tagEnd: close, end: close, closeStart: nil,
                               parent: open.last))
            if !text.hasSuffix("/>") { open.append(out.count - 1) }
        }
        return out
    }

    static func paths(_ elements: [Element]) -> [Element] { elements.filter { $0.tag.name == "path" } }

    // MARK: - reading

    public static func count(_ svg: String) -> Int { paths(elements(svg)).count }

    /// strokes.fixed_count: the strokes drawn by hand.
    public static func fixedCount(_ svg: String) -> Int {
        paths(elements(svg)).filter { ["1", "true"].contains($0.tag.value(fixedAttribute) ?? "") }.count
    }

    /// strokes.view_box: the viewBox (x, y, width, height), else 0, 0 and the width and height in numbers.
    public static func viewBox(_ svg: String) -> (x: Double, y: Double, width: Double, height: Double) {
        let root = elements(svg).first?.tag
        if let box = root?.value("viewBox")?.trimmingCharacters(in: .whitespacesAndNewlines), !box.isEmpty {
            let values = box.split(whereSeparator: { $0.isWhitespace || $0 == "," }).prefix(4).compactMap { Double($0) }
            if values.count == 4 { return (values[0], values[1], values[2], values[3]) }
        }
        func size(_ key: String) -> Double {
            let digits = (root?.value(key) ?? "224").filter { $0.isNumber || $0 == "." }
            return digits.isEmpty ? 224 : Double(digits) ?? 224
        }
        return (0, 0, size("width"), size("height"))
    }

    /// brush.sample: points along each subpath of path data – `perSegment` per segment (straight ones too), one
    /// shared where segments meet, near-duplicates (1e-6) dropped; subpaths of fewer than two points are left out.
    public static func sample(_ d: String, perSegment: Int = samplesPerSegment) -> [[SketchPoint]] {
        guard let subpaths = try? SketchSVG.parsePath(d) else { return [] }
        var out: [[SketchPoint]] = []
        for sub in subpaths {
            var points: [SketchPoint] = []
            for segment in sub.segments {
                let start = points.isEmpty ? 0 : 1
                for i in start..<perSegment {
                    points.append(bezier(segment, Double(i) / Double(perSegment - 1)))
                }
            }
            var kept = points.isEmpty ? [] : [points[0]]
            for p in points.dropFirst() where abs(p.x - kept[kept.count - 1].x) > 1e-6
                || abs(p.y - kept[kept.count - 1].y) > 1e-6
            {
                kept.append(p)
            }
            if kept.count >= 2 { out.append(kept) }
        }
        return out
    }

    /// brush._bezier: the point at `t` of a segment (its start first; 2 points a line, 3 quadratic, 4 cubic).
    static func bezier(_ seg: [SketchPoint], _ t: Double) -> SketchPoint {
        let u = 1 - t
        switch seg.count {
        case 2:
            return SketchPoint(x: seg[0].x + (seg[1].x - seg[0].x) * t, y: seg[0].y + (seg[1].y - seg[0].y) * t)
        case 3:
            return SketchPoint(x: u * u * seg[0].x + 2 * u * t * seg[1].x + t * t * seg[2].x,
                               y: u * u * seg[0].y + 2 * u * t * seg[1].y + t * t * seg[2].y)
        default:
            let a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, e = t * t * t
            return SketchPoint(x: a * seg[0].x + b * seg[1].x + c * seg[2].x + e * seg[3].x,
                               y: a * seg[0].y + b * seg[1].y + c * seg[2].y + e * seg[3].y)
        }
    }

    /// strokes.StrokeIndex: the strokes as polylines, for the eraser's hit test.
    public struct StrokeIndex: Sendable {
        public let lines: [[[SketchPoint]]]
        public let widths: [Double]

        public init(svg: String) {
            let found = SketchEditing.paths(SketchEditing.elements(svg))
            lines = found.map { SketchEditing.sample($0.tag.value("d") ?? "") }
            widths = found.map { path in
                let raw = (path.tag.value("stroke-width") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                return raw.isEmpty ? 1 : Double(raw) ?? 1
            }
        }

        public var count: Int { lines.count }

        /// The stroke nearest to (x, y) within `tolerance` and half its width, or nil – in the sketch's coordinates.
        public func hit(x: Double, y: Double, tolerance: Double) -> Int? {
            var best: Int?
            var bestDistance = Double.infinity
            for (i, subpaths) in lines.enumerated() {
                let reach = tolerance + widths[i] / 2
                for points in subpaths {
                    for (a, b) in zip(points, points.dropFirst()) {
                        let d = SketchEditing.distance(x, y, a, b)
                        if d < bestDistance, d <= reach {
                            best = i
                            bestDistance = d
                        }
                    }
                }
            }
            return best
        }
    }

    static func distance(_ px: Double, _ py: Double, _ a: SketchPoint, _ b: SketchPoint) -> Double {
        let dx = b.x - a.x, dy = b.y - a.y
        let length2 = dx * dx + dy * dy
        let t = length2 == 0 ? 0 : max(0, min(1, ((px - a.x) * dx + (py - a.y) * dy) / length2))
        return hypot(px - (a.x + t * dx), py - (a.y + t * dy))
    }

    // MARK: - changing

    /// strokes.remove_strokes: the sketch without the strokes `indices` (numbers that are no stroke are ignored).
    public static func removeStrokes(_ svg: String, _ indices: Set<Int>) -> String {
        let gone = paths(elements(svg)).enumerated().filter { indices.contains($0.offset) }.map { $0.element.start..<$0.element.end }
        guard !gone.isEmpty else { return svg }
        var out = ""
        var index = svg.startIndex
        for range in gone {
            out += svg[index..<range.lowerBound]
            index = range.upperBound
        }
        return out + svg[index...]
    }

    /// strokes.unfix: every stroke free again (CLIPasso may move all of them).
    public static func unfix(_ svg: String) -> String {
        var out = ""
        var index = svg.startIndex
        for path in paths(elements(svg)) where path.tag.value(fixedAttribute) != nil {
            var tag = path.tag
            tag.remove(fixedAttribute)
            out += svg[index..<path.start] + tag.text
            index = path.tagEnd
        }
        return out + svg[index...]
    }

    /// strokes.append_stroke: the sketch with a stroke drawn through `points` (the sketch's coordinates): simplified
    /// (Ramer–Douglas–Peucker), smoothed into cubic Béziers (Catmull–Rom), as wide as the middle one of the sketch's
    /// strokes unless `width` is given, round, black – `fixed`: marked to stay as it is when CLIPasso continues the
    /// sketch. Appended to the group of the sketch's last stroke; unchanged when fewer than two points remain.
    public static func appendStroke(_ svg: String, points: [SketchPoint], width: Double? = nil, fixed: Bool = true)
        -> String
    {
        let all = elements(svg)
        let found = paths(all)
        let box = viewBox(svg)
        let kept = simplify(points, tolerance: penTolerance * max(box.width, box.height))
        guard kept.count >= 2, let root = all.first else { return svg }
        let strokeWidth = width ?? {
            let widths = found.compactMap { path -> Double? in
                let raw = (path.tag.value("stroke-width") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                return raw.isEmpty ? 1 : Double(raw)
            }.sorted()
            return widths.isEmpty ? 1.5 * max(box.width, box.height) / 224 : widths[widths.count / 2]
        }()
        var attributes = [("d", bezierD(catmullRomBezier(kept))), ("fill", "none"), ("stroke", "rgb(0, 0, 0)"),
                          ("stroke-opacity", "1"), ("stroke-width", decimal(strokeWidth, 3, zero: false)),
                          ("stroke-linecap", "round"), ("stroke-linejoin", "round")]
        if fixed { attributes.append((fixedAttribute, "1")) }
        let model = found.last ?? root
        let prefix = model.tag.qualifiedName.split(separator: ":").dropLast().map { $0 + ":" }.joined()
        let element = "<\(prefix)path "
            + attributes.map { "\($0.0)=\"\(SketchExport.escape($0.1))\"" }.joined(separator: " ") + " />"
        let parent = found.last.flatMap { $0.parent }.map { all[$0] } ?? root
        if let at = parent.closeStart {
            return String(svg[..<at]) + element + String(svg[at...])
        }
        // (a root that closes itself: it gets a closing tag)
        var opened = String(svg[parent.start..<parent.tagEnd].dropLast(2))  // (without its "/>")
        while opened.last?.isWhitespace == true { opened.removeLast() }
        return String(svg[..<parent.start]) + opened + ">" + element + "</\(parent.tag.qualifiedName)>"
            + String(svg[parent.tagEnd...])
    }

    // MARK: - curves (clipasso_studio/curves.py)

    /// curves.simplify: Ramer–Douglas–Peucker – the points that keep the polyline within `tolerance`.
    static func simplify(_ points: [SketchPoint], tolerance: Double) -> [SketchPoint] {
        var unique: [SketchPoint] = []
        for p in points where unique.last != p { unique.append(p) }
        guard unique.count >= 3 else { return unique }
        var keep = [Bool](repeating: false, count: unique.count)
        keep[0] = true
        keep[unique.count - 1] = true
        var stack = [(0, unique.count - 1)]
        while let (a, b) = stack.popLast() {
            let (pa, pb) = (unique[a], unique[b])
            let dx = pb.x - pa.x, dy = pb.y - pa.y
            let length = hypot(dx, dy)
            var best = -1.0
            var index = -1
            for i in (a + 1)..<b {
                let p = unique[i]
                let d = length == 0 ? hypot(p.x - pa.x, p.y - pa.y)
                    : abs(dy * p.x - dx * p.y + pb.x * pa.y - pb.y * pa.x) / length
                if d > best {
                    best = d
                    index = i
                }
            }
            if index >= 0, best > tolerance {
                keep[index] = true
                stack += [(a, index), (index, b)]
            }
        }
        return zip(unique, keep).filter(\.1).map(\.0)
    }

    /// curves.catmull_rom_bezier: cubic segments (p0, c1, c2, p1) of the Catmull–Rom spline through the points (it
    /// passes through each; the ends are clamped).
    static func catmullRomBezier(_ points: [SketchPoint]) -> [(SketchPoint, SketchPoint, SketchPoint, SketchPoint)] {
        guard points.count >= 2 else { return [] }
        return (0..<(points.count - 1)).map { i in
            let p0 = points[max(i - 1, 0)], p1 = points[i], p2 = points[i + 1], p3 = points[min(i + 2, points.count - 1)]
            let c1 = SketchPoint(x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6)
            let c2 = SketchPoint(x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6)
            return (p1, c1, c2, p2)
        }
    }

    /// curves.bezier_d: the path data of connected cubic segments, numbers with up to `digits` decimals.
    static func bezierD(_ segments: [(SketchPoint, SketchPoint, SketchPoint, SketchPoint)], digits: Int = 3) -> String {
        guard let first = segments.first else { return "" }
        func f(_ v: Double) -> String { decimal(v, digits, zero: true) }
        var parts = ["M \(f(first.0.x)) \(f(first.0.y))"]
        for (_, c1, c2, p) in segments {
            parts.append("C \(f(c1.x)) \(f(c1.y)) \(f(c2.x)) \(f(c2.y)) \(f(p.x)) \(f(p.y))")
        }
        return parts.joined(separator: " ")
    }

    /// Python's `f"{v:.{digits}f}".rstrip("0").rstrip(".")` – with `zero`, "-0" and "" become "0" (bezier_d's f).
    static func decimal(_ value: Double, _ digits: Int, zero: Bool) -> String {
        var text = String(format: "%.\(digits)f", value)
        if text.contains(".") {
            while text.hasSuffix("0") { text.removeLast() }
            if text.hasSuffix(".") { text.removeLast() }
        }
        return zero && (text == "-0" || text.isEmpty) ? "0" : text
    }
}
