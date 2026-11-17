import Foundation

/// The finished strokes of a sketch drawn one after another, like by hand (export.Drawing): `frame(t)` is the SVG at
/// progress t (0 … 1) – the strokes before it complete, the current one up to its share. The strokes go along a
/// short route (the longest first, then always the nearest stroke end, drawn from that end) or in the order of the
/// SVG; between two strokes the pen lifts for a quarter of the mean stroke length.
public struct Drawing: Sendable {
    struct Stroke: Sendable {
        var subs: [[SketchPoint]]
        /// the attributes but d, in their order (ElementTree's attrib)
        var attributes: [(name: String, value: String)]
        /// the stroke as written
        var xml: String
        var length: Double
    }

    /// brush.SAMPLES_PER_SEGMENT
    static let samplesPerSegment = 16
    /// the time between two strokes, as a share of the mean stroke length
    static let penLift = 0.25

    /// the SVG's start tag (its own attributes, the SVG namespace)
    public let head: String
    let strokes: [Stroke]
    /// where each stroke starts and ends on the timeline
    public let spans: [(start: Double, end: Double)]
    public let total: Double
    /// a sketch of one line: its length in canvas widths (0 for more strokes)
    public let line: Double

    public var strokeCount: Int { strokes.count }

    public init(svg: String, keepOrder: Bool = false) {
        let elements = SketchEditing.elements(svg)
        let own = (elements.first?.tag.attributes ?? []).filter { !$0.name.contains(":") && $0.name != "xmlns" }
        head = #"<svg xmlns="http://www.w3.org/2000/svg" "# + own.map { #"\#($0.name)="\#($0.value)""# }
            .joined(separator: " ") + ">"
        var strokes: [Stroke] = []
        for element in elements where element.tag.name == "path" {
            let subs = SketchEditing.sample(element.tag.value("d") ?? "", perSegment: Self.samplesPerSegment)
            guard !subs.isEmpty else { continue }
            let attributes = element.tag.attributes.filter { $0.name != "d" && !$0.name.contains(":") && $0.name != "xmlns" }
            strokes.append(Stroke(subs: subs, attributes: attributes, xml: String(svg[element.start ..< element.end]),
                                  length: Python.sum(subs.map(Self.length))))
        }
        self.strokes = keepOrder ? strokes : Self.route(strokes)
        let mean = Python.sum(self.strokes.map(\.length)) / Double(max(self.strokes.count, 1))
        let lift = Self.penLift * mean
        var spans: [(Double, Double)] = []
        var t = 0.0
        for stroke in self.strokes {
            spans.append((t, t + stroke.length))
            t += stroke.length + lift
        }
        self.spans = spans
        total = max(t - lift, 1e-9)
        line = self.strokes.count == 1 ? total / max(SketchEditing.viewBox(svg).width, 1e-9) : 0
    }

    static func length(_ points: [SketchPoint]) -> Double {
        Python.sum(zip(points, points.dropFirst()).map { Python.hypot($1.x - $0.x, $1.y - $0.y) })
    }

    /// _route: the longest stroke first, then always the nearest stroke end (drawn from that end).
    static func route(_ strokes: [Stroke]) -> [Stroke] {
        guard var first = strokes.indices.first else { return [] }
        for i in strokes.indices where strokes[i].length > strokes[first].length { first = i }
        var left = strokes
        var route = [left.remove(at: first)]
        var pen = route[0].subs[route[0].subs.count - 1].last!
        while !left.isEmpty {
            var best = 0, bestDistance = Double.infinity, reverse = false, found = false
            for (i, stroke) in left.enumerated() {
                let a = stroke.subs[0][0], b = stroke.subs[stroke.subs.count - 1].last!
                let ends = [(Python.hypot(a.x - pen.x, a.y - pen.y), false), (Python.hypot(b.x - pen.x, b.y - pen.y), true)]
                for (d, r) in ends where !found || d < bestDistance
                {
                    (best, bestDistance, reverse, found) = (i, d, r, true)
                }
            }
            var next = left.remove(at: best)
            if reverse { next.subs = next.subs.reversed().map { $0.reversed() } }
            route.append(next)
            pen = next.subs[next.subs.count - 1].last!
        }
        return route
    }

    static func format(_ points: [SketchPoint]) -> String {
        "M " + points.map { String(format: "%.2f %.2f", $0.x, $0.y) }.joined(separator: " L ")
    }

    /// centreline: the path data of stroke `i` in its drawing direction (sampled).
    public func centreline(_ i: Int) -> String {
        strokes[i].subs.map(Self.format).joined(separator: " ")
    }

    /// _partial: the first `distance` of a stroke as a path of its points.
    static func partial(_ stroke: Stroke, _ distance: Double) -> String {
        var parts: [String] = []
        var left = distance
        for points in stroke.subs {
            if left <= 0 { break }
            var out = [points[0]]
            for (a, b) in zip(points, points.dropFirst()) {
                let segment = Python.hypot(b.x - a.x, b.y - a.y)
                if segment >= left {
                    let f = segment != 0 ? left / segment : 0
                    out.append(SketchPoint(x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f))
                    left = 0
                    break
                }
                out.append(b)
                left -= segment
            }
            if out.count >= 2 { parts.append(format(out)) }
        }
        guard !parts.isEmpty else { return "" }
        let attributes = stroke.attributes.map { #"\#($0.name)="\#($0.value)""# }.joined(separator: " ")
        return #"<path d="\#(parts.joined(separator: " "))" \#(attributes) />"#
    }

    /// The SVG at progress `t` (0 … 1).
    public func frame(_ t: Double) -> String {
        let now = max(0, min(1, t)) * total
        var body = ""
        for (stroke, span) in zip(strokes, spans) {
            if now >= span.end {
                body += stroke.xml
            } else {
                if now > span.start { body += Self.partial(stroke, now - span.start) }
                break
            }
        }
        return head + body + "</svg>"
    }
}
