import Foundation

/// A detail map (8-bit grey, row after row): 128 normal, 255 more detail, 0 less (engine/details.py).
public struct DetailMap: Sendable, Equatable {
    public var width: Int
    public var height: Int
    public var values: [UInt8]

    public init(width: Int, height: Int, values: [UInt8]) {
        (self.width, self.height, self.values) = (width, height, values)
    }

    /// All normal.
    public init(width: Int, height: Int) {
        self.init(width: width, height: height,
                  values: [UInt8](repeating: DetailEditing.normal, count: width * height))
    }
}

/// Painting the detail map as the studio's detail brush does (gui/detail_edit.py): a round dab with a soft rim moves
/// the map towards the tool's value – more detail (orange), normal, less (blue) – and lines of dabs a quarter brush
/// apart; the canvas shows the map over the photo, the dialog how much of the image is more and less.
public enum DetailEditing {
    public enum Tool: String, CaseIterable, Sendable {
        case more, normal, less

        /// detail_edit.TOOLS
        public var value: UInt8 {
            switch self {
            case .more: 255
            case .normal: DetailEditing.normal
            case .less: 0
            }
        }
    }

    /// details.NORMAL
    public static let normal: UInt8 = 128
    /// EDIT_SIDE: the map is painted at most this large (the engine says the size: Pillow's thumbnail rounds)
    public static let editSide = 1024
    /// UNDO_STEPS
    public static let undoSteps = 30
    /// MORE_RGB, LESS_RGB: the canvas's colours of more and less detail
    public static let moreRGB: (r: UInt8, g: UInt8, b: UInt8) = (255, 140, 0)
    public static let lessRGB: (r: UInt8, g: UInt8, b: UInt8) = (40, 120, 255)

    /// The brush the canvas starts with for a photo of this size (6 % of its longer side, at least 8 pixels).
    public static func startBrush(width: Int, height: Int) -> Int {
        max(8, Int(Double(max(width, height)) * 0.06))
    }

    /// The dialog's slider: from 6 pixels to three start brushes (at least 200).
    public static func brushRange(start: Int) -> ClosedRange<Int> {
        6 ... max(200, start * 3)
    }

    /// DetailCanvas.dab: a round dab of `brush` pixels at map position (x, y), full inside, a soft rim.
    public static func dab(_ map: inout DetailMap, x: Double, y: Double, brush: Int, tool: Tool) {
        let r = Double(brush) / 2
        let x0 = max(Int(x - r - 1), 0), x1 = min(Int(x + r + 2), map.width)
        let y0 = max(Int(y - r - 1), 0), y1 = min(Int(y + r + 2), map.height)
        guard x0 < x1, y0 < y1 else { return }
        let target = Double(tool.value)
        let reach = max(r, 1e-6)
        for yy in y0 ..< y1 {
            let dy = Double(yy) + 0.5 - y
            for xx in x0 ..< x1 {
                let dx = Double(xx) + 0.5 - x
                let d = (dx * dx + dy * dy).squareRoot() / reach
                let a = min(1, max(0, (1 - d) / 0.35))
                guard a > 0 else { continue }
                let i = yy * map.width + xx
                let region = Double(map.values[i])
                map.values[i] = UInt8((region + (target - region) * a).rounded(.toNearestOrEven))
            }
        }
    }

    /// DetailCanvas._line: dabs from `a` (not at it: it has one already) to `b`, a quarter brush apart.
    public static func line(_ map: inout DetailMap, from a: (x: Double, y: Double), to b: (x: Double, y: Double),
                            brush: Int, tool: Tool)
    {
        let dist = hypot(b.x - a.x, b.y - a.y)
        let steps = max(1, Int(dist / max(Double(brush) * 0.25, 1)))
        for k in 1 ... steps {
            dab(&map, x: a.x + (b.x - a.x) * Double(k) / Double(steps),
                y: a.y + (b.y - a.y) * Double(k) / Double(steps), brush: brush, tool: tool)
        }
    }

    /// DetailCanvas._rebuild: the map as the canvas lays it over the photo – RGBA, the colour of more or less
    /// detail, as opaque as far as the map goes (at most 150 of 255); normal is clear.
    public static func overlay(_ map: DetailMap) -> [UInt8] {
        var rgba = [UInt8](repeating: 0, count: map.values.count * 4)
        for (i, m) in map.values.enumerated() where m != normal {
            let v = (Float(m) - Float(normal)) / 127  // (in float32, as numpy)
            let (amount, rgb) = v > 0 ? (min(v, 1), moreRGB) : (min(-v, 1), lessRGB)
            (rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]) = (rgb.r, rgb.g, rgb.b)
            rgba[i * 4 + 3] = UInt8((amount * 150).rounded(.toNearestOrEven))
        }
        return rgba
    }

    /// The dialog's line: the shares of the image with clearly more (> 8 over normal) and less detail, 0 … 1.
    public static func share(_ map: DetailMap) -> (more: Double, less: Double) {
        guard !map.values.isEmpty else { return (0, 0) }
        var (more, less) = (0, 0)
        for m in map.values {
            let v = Int(m) - Int(normal)
            if v > 8 { more += 1 } else if v < -8 { less += 1 }
        }
        return (Double(more) / Double(map.values.count), Double(less) / Double(map.values.count))
    }

    /// find_face's merge: the faces' map over the painted one, the larger value kept.
    public static func merged(_ map: DetailMap, _ faces: DetailMap) -> DetailMap {
        guard map.values.count == faces.values.count else { return map }
        let values = Swift.zip(map.values, faces.values).map { max($0, $1) }
        return DetailMap(width: map.width, height: map.height, values: values)
    }
}
