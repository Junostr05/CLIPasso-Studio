import Foundation

/// A mask (true: the object), row after row.
public struct MaskPlane: Sendable, Equatable {
    public var width: Int
    public var height: Int
    public var values: [Bool]

    public init(width: Int, height: Int, values: [Bool]) {
        (self.width, self.height, self.values) = (width, height, values)
    }

    public init(width: Int, height: Int) {
        self.init(width: width, height: height, values: [Bool](repeating: false, count: width * height))
    }

    public subscript(x: Int, y: Int) -> Bool {
        get { values[y * width + x] }
        set { values[y * width + x] = newValue }
    }

    var plane: Plane<Bool> { Plane(width: width, height: height, values: values) }
}

/// The photo the magic wand looks at (any size – it is shrunk for the wand anyway; the studio gives it at most 1600
/// pixels): RGB bytes, row after row.
public struct MaskPhoto: Sendable {
    public let width: Int
    public let height: Int
    public let rgb: [UInt8]

    public init?(width: Int, height: Int, rgb: [UInt8]) {
        guard width > 0, height > 0, rgb.count == width * height * 3 else { return nil }
        (self.width, self.height, self.rgb) = (width, height, rgb)
    }
}

/// Touching up the object mask as the studio does it (gui/mask_edit.py): a click on a part – inside the mask the
/// part under it goes; outside, the part of the candidates (what the mask model was less sure about) comes in, or
/// where the model saw nothing the magic wand's area of similar colours – and the brush, dabs and lines. The parts
/// and the wand are found on a copy of at most 512 pixels and scaled back (one pixel grown), as there.
public enum MaskEditing {
    /// mask_edit.CANDIDATE: the probability from which a part the mask left out can be added with a click
    public static let candidate: Float = 0.15
    /// PICK_SIDE: parts are found on a copy of at most this size
    public static let pickSide = 512
    /// WAND_TOLERANCE: the magic wand's summed RGB difference to the clicked colour
    public static let wandTolerance = 54
    /// UNDO_STEPS
    public static let undoSteps = 30

    /// part_click: a click at image position (x, y) – the new mask, nil when there is nothing to change. `photo` is
    /// the image for the magic wand; nil: no wand.
    public static func partClick(_ mask: MaskPlane, candidate: MaskPlane, photo: MaskPhoto?, x: Double, y: Double)
        -> MaskPlane?
    {
        let (xi, yi) = (Int(x.rounded(.towardZero)), Int(y.rounded(.towardZero)))
        guard xi >= 0, yi >= 0, xi < mask.width, yi < mask.height else { return nil }  // (int(-0.5) is 0)
        var out = mask
        if mask[xi, yi] {
            let part = component(mask, xi, yi)
            for i in out.values.indices where part.values[i] { out.values[i] = false }
            return out
        }
        if candidate[xi, yi] {
            let part = component(candidate, xi, yi)
            for i in out.values.indices where part.values[i] && candidate.values[i] { out.values[i] = true }
            return out
        }
        guard let photo else { return nil }
        let area = wand(photo, width: mask.width, height: mask.height, x: xi, y: yi)
        for i in out.values.indices where area.values[i] { out.values[i] = true }
        return out
    }

    /// dab: a disc of radius `r` at image position (x, y).
    public static func dab(_ mask: inout MaskPlane, x: Double, y: Double, r: Double, value: Bool) {
        let x0 = max(0, Int((x - r).rounded(.towardZero))), x1 = min(mask.width, Int((x + r).rounded(.towardZero)) + 1)
        let y0 = max(0, Int((y - r).rounded(.towardZero))), y1 = min(mask.height, Int((y + r).rounded(.towardZero)) + 1)
        guard x0 < x1, y0 < y1 else { return }
        for yy in y0 ..< y1 {
            for xx in x0 ..< x1 {
                let (dx, dy) = (Double(xx) - x, Double(yy) - y)
                if dx * dx + dy * dy <= r * r { mask[xx, yy] = value }
            }
        }
    }

    /// line: dabs along a line, half a radius apart (the first at a step from `a`).
    public static func line(_ mask: inout MaskPlane, from a: (x: Double, y: Double), to b: (x: Double, y: Double),
                            r: Double, value: Bool)
    {
        let step = max(1, r / 2)
        let n = max(1, Int((hypot(b.x - a.x, b.y - a.y) / step).rounded(.towardZero)))
        for i in 1 ... n {
            let t = Double(i) / Double(n)
            dab(&mask, x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, r: r, value: value)
        }
    }

    // ------------------------------------------------------------------------------- parts and the wand

    /// The size of the copy parts are found on (Python's round).
    static func pickSize(_ width: Int, _ height: Int) -> (width: Int, height: Int, factor: Double) {
        let f = min(1, Double(pickSide) / Double(max(width, height)))
        return (max(1, Int((Double(width) * f).rounded(.toNearestOrEven))),
                max(1, Int((Double(height) * f).rounded(.toNearestOrEven))), f)
    }

    /// Image.resize(…, NEAREST): the source pixel of each column and row, its position stepped on (Pillow's affine
    /// transform adds the step for every pixel, rounding as it goes).
    static func nearest<Value>(_ plane: Plane<Value>, width w: Int, height h: Int) -> Plane<Value> {
        func indices(_ count: Int, _ size: Int) -> [Int] {
            let step = Double(size) / Double(count)
            var at = step * 0.5, out: [Int] = []
            out.reserveCapacity(count)
            for _ in 0 ..< count {
                out.append(min(size - 1, Int(at)))
                at += step
            }
            return out
        }
        let (xs, ys) = (indices(w, plane.width), indices(h, plane.height))
        var values: [Value] = []
        values.reserveCapacity(w * h)
        for y in ys {
            for x in xs { values.append(plane.values[y * plane.width + x]) }
        }
        return Plane(width: w, height: h, values: values)
    }

    /// ImageDraw.floodfill's area: the 4-connected pixels from (x, y) where `inside` holds.
    static func flood(_ inside: Plane<Bool>, _ x: Int, _ y: Int) -> Plane<Bool> {
        var out = Plane(width: inside.width, height: inside.height, fill: false)
        out.values[y * inside.width + x] = true
        var queue = [(x, y)], head = 0
        while head < queue.count {
            let (px, py) = queue[head]
            head += 1
            for (s, t) in [(px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)]
                where s >= 0 && t >= 0 && s < inside.width && t < inside.height
            {
                let i = t * inside.width + s
                if !out.values[i], inside.values[i] {
                    out.values[i] = true
                    queue.append((s, t))
                }
            }
        }
        return out
    }

    /// _grow_and_scale: one pixel grown around the part, scaled to the mask's size.
    static func grownAndScaled(_ part: Plane<Bool>, _ width: Int, _ height: Int) -> MaskPlane {
        let scaled = nearest(MaskOverlay.dilate(part, 1), width: width, height: height)
        return MaskPlane(width: width, height: height, values: scaled.values)
    }

    /// _component: the 4-connected part of `mask` holding (x, y), found on the reduced copy.
    static func component(_ mask: MaskPlane, _ x: Int, _ y: Int) -> MaskPlane {
        let (sw, sh, f) = pickSize(mask.width, mask.height)
        let small = nearest(mask.plane, width: sw, height: sh)
        let (sx, sy) = (min(sw - 1, Int(Double(x) * f)), min(sh - 1, Int(Double(y) * f)))
        guard small.values[sy * sw + sx] else { return MaskPlane(width: mask.width, height: mask.height) }
        return grownAndScaled(flood(small, sx, sy), mask.width, mask.height)
    }

    /// The 3 × 3 median of each colour (ImageFilter.MedianFilter(3): the edge pixels repeated beyond the edge).
    static func median3(_ rgb: [UInt8], width w: Int, height h: Int) -> [UInt8] {
        var out = rgb
        var window = [UInt8](repeating: 0, count: 9)
        for y in 0 ..< h {
            for x in 0 ..< w {
                for c in 0 ..< 3 {
                    var k = 0
                    for dy in -1 ... 1 {
                        let yy = min(h - 1, max(0, y + dy))
                        for dx in -1 ... 1 {
                            let xx = min(w - 1, max(0, x + dx))
                            window[k] = rgb[(yy * w + xx) * 3 + c]
                            k += 1
                        }
                    }
                    window.sort()
                    out[(y * w + x) * 3 + c] = window[4]
                }
            }
        }
        return out
    }

    /// wand: the connected area of colours like the clicked one (at mask position x, y), on a reduced (bilinear),
    /// slightly smoothed (median) copy of the photo – as ImageDraw.floodfill finds it with its tolerance – as a mask
    /// of the mask's size (w × h).
    static func wand(_ photo: MaskPhoto, width w: Int, height h: Int, x: Int, y: Int,
                     tolerance: Int = wandTolerance) -> MaskPlane
    {
        let (sw, sh, f) = pickSize(w, h)
        let (pw, ph, rgb) = (photo.width, photo.height, photo.rgb)
        var channels: [Plane<UInt8>] = []
        for c in 0 ..< 3 {
            var values = [UInt8](repeating: 0, count: pw * ph)
            for i in 0 ..< pw * ph { values[i] = rgb[i * 3 + c] }
            channels.append(Pillow.resizeBilinear(Plane(width: pw, height: ph, values: values), width: sw, height: sh))
        }
        var small = [UInt8](repeating: 0, count: sw * sh * 3)
        for i in 0 ..< sw * sh {
            for c in 0 ..< 3 { small[i * 3 + c] = channels[c].values[i] }
        }
        small = median3(small, width: sw, height: sh)
        let (sx, sy) = (min(sw - 1, Int(Double(x) * f)), min(sh - 1, Int(Double(y) * f)))
        let seed = (0 ..< 3).map { Int(small[(sy * sw + sx) * 3 + $0]) }
        let marker = seed == [255, 0, 255] ? [0, 255, 0] : [255, 0, 255]
        func difference(_ i: Int, _ to: [Int]) -> Int {
            abs(Int(small[i * 3]) - to[0]) + abs(Int(small[i * 3 + 1]) - to[1]) + abs(Int(small[i * 3 + 2]) - to[2])
        }
        var part = Plane(width: sw, height: sh, fill: false)
        // (the marker the fill paints must stand out from the clicked colour, else floodfill paints nothing; a pixel
        // that has the marker's colour already is no change)
        if abs(marker[0] - seed[0]) + abs(marker[1] - seed[1]) + abs(marker[2] - seed[2]) > tolerance {
            let inside = Plane(width: sw, height: sh, values: (0 ..< sw * sh).map { difference($0, seed) <= tolerance })
            part = flood(inside, sx, sy)
            for i in part.values.indices where part.values[i] && difference(i, marker) == 0 { part.values[i] = false }
        }
        part.values[sy * sw + sx] = true
        return grownAndScaled(part, w, h)
    }
}
