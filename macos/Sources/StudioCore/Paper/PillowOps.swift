import Foundation

/// A picture of one channel, row by row (y down, as Pillow's and numpy's).
struct Plane<Value> {
    var width: Int
    var height: Int
    var values: [Value]

    init(width: Int, height: Int, values: [Value]) {
        (self.width, self.height, self.values) = (width, height, values)
    }

    init(width: Int, height: Int, fill: Value) {
        self.init(width: width, height: height, values: [Value](repeating: fill, count: width * height))
    }

    subscript(x: Int, y: Int) -> Value {
        get { values[y * width + x] }
        set { values[y * width + x] = newValue }
    }
}

extension Plane: Sendable where Value: Sendable {}

/// The steps of Pillow (13) that gui/paper.py takes, done the way Pillow's C code does them, so that the pictures are
/// the same: resizing a float picture with the bicubic filter (Resample.c), the Gaussian blur of a grey picture as
/// three box blurs in fixed point (BoxBlur.c) and lines one or more pixels wide (Draw.c).
enum Pillow {
    // ------------------------------------------------------------------------------------------- resize

    /// bicubic_filter (a = -0.5), support 2.
    static func bicubic(_ x: Double) -> Double {
        let a = -0.5
        let x = abs(x)
        if x < 1 { return ((a + 2) * x - (a + 3)) * x * x + 1 }
        if x < 2 { return (((x - 5) * x + 8) * x - 4) * a }
        return 0
    }

    /// precompute_coeffs: for every output pixel the first input pixel and the normalised weights.
    static func coefficients(inSize: Int, outSize: Int) -> [(first: Int, weights: [Double])] {
        let scale = Double(Float(inSize) - Float(0)) / Double(outSize)
        let filterscale = max(scale, 1)
        let support = 2 * filterscale
        let inverse = 1 / filterscale
        return (0 ..< outSize).map { xx in
            let center = 0 + (Double(xx) + 0.5) * scale
            let first = max(Int(center - support + 0.5), 0)
            let last = min(Int(center + support + 0.5), inSize)
            var weights = (0 ..< max(last - first, 0)).map { bicubic((Double($0 + first) - center + 0.5) * inverse) }
            var total = 0.0
            for w in weights { total += w }
            if total != 0 { weights = weights.map { $0 / total } }
            return (first, weights)
        }
    }

    /// Image.resize((w, h), BICUBIC) of a float ("F") picture: the horizontal pass first unless the height shrinks
    /// more than twice as much as the width (ImagingResampleInner), each sum in double, stored as float.
    static func resize(_ plane: Plane<Float>, width w: Int, height h: Int) -> Plane<Float> {
        let needHorizontal = w != plane.width
        let needVertical = h != plane.height
        let horizontalFirst = !((plane.height - h) > 0 && (plane.height - h) > (plane.width - w) * 2)
        var out = plane
        if horizontalFirst {
            if needHorizontal { out = horizontal(out, to: w) }
            if needVertical { out = vertical(out, to: h) }
        } else {
            if needVertical { out = vertical(out, to: h) }
            if needHorizontal { out = horizontal(out, to: w) }
        }
        return out
    }

    static func horizontal(_ plane: Plane<Float>, to w: Int) -> Plane<Float> {
        let kernels = coefficients(inSize: plane.width, outSize: w)
        var out = Plane<Float>(width: w, height: plane.height, fill: 0)
        for y in 0 ..< plane.height {
            let row = y * plane.width
            for (xx, kernel) in kernels.enumerated() {
                var sum = 0.0
                for (i, weight) in kernel.weights.enumerated() {
                    sum += Double(plane.values[row + kernel.first + i]) * weight
                }
                out.values[y * w + xx] = Float(sum)
            }
        }
        return out
    }

    static func vertical(_ plane: Plane<Float>, to h: Int) -> Plane<Float> {
        let kernels = coefficients(inSize: plane.height, outSize: h)
        var out = Plane<Float>(width: plane.width, height: h, fill: 0)
        for (yy, kernel) in kernels.enumerated() {
            for x in 0 ..< plane.width {
                var sum = 0.0
                for (i, weight) in kernel.weights.enumerated() {
                    sum += Double(plane.values[(kernel.first + i) * plane.width + x]) * weight
                }
                out.values[yy * plane.width + x] = Float(sum)
            }
        }
        return out
    }

    // --------------------------------------------------------------------------------------------- blur

    /// _gaussian_blur_radius: the box radius of one of `passes` box blurs (in float, as Pillow).
    static func boxRadius(_ radius: Float, passes: Int = 3) -> Float {
        let sigma2 = radius * radius / Float(passes)
        let big = Float((12.0 * Double(sigma2) + 1.0).squareRoot())
        let l = Float(((Double(big) - 1.0) / 2.0).rounded(.down))
        var a = (2 * l + 1) * (l * (l + 1) - 3 * sigma2)
        a /= 6 * (sigma2 - (l + 1) * (l + 1))
        return l + a
    }

    /// ImageFilter.GaussianBlur(radius) of a grey ("L") picture: three box blurs along the rows, three along the
    /// columns.
    static func gaussianBlur(_ plane: Plane<UInt8>, radius: Double) -> Plane<UInt8> {
        let r = boxRadius(Float(radius))
        guard r != 0 else { return plane }
        var rows = (0 ..< plane.height).map { Array(plane.values[$0 * plane.width ..< ($0 + 1) * plane.width]) }
        for _ in 0 ..< 3 { rows = rows.map { boxBlur($0, radius: r) } }
        var columns = (0 ..< plane.width).map { x in rows.map { $0[x] } }
        for _ in 0 ..< 3 { columns = columns.map { boxBlur($0, radius: r) } }
        var out = plane
        for (x, column) in columns.enumerated() {
            for (y, v) in column.enumerated() { out.values[y * plane.width + x] = v }
        }
        return out
    }

    /// ImagingLineBoxBlur8 with ImagingHorizontalBoxBlur's weights: a running sum in 32-bit fixed point (wrapping as
    /// C's unsigned arithmetic), the edges repeated outside the line.
    static func boxBlur(_ line: [UInt8], radius floatRadius: Float) -> [UInt8] {
        let radius = Int(floatRadius)
        let ww = UInt32(Float(1 << 24) / (floatRadius * 2 + 1))
        let fw = (UInt32(1 << 24) &- UInt32(radius * 2 + 1) &* ww) / 2
        let n = line.count
        let lastx = n - 1
        let edgeA = min(radius + 1, n)
        let edgeB = max(n - radius - 1, 0)
        func px(_ i: Int) -> UInt32 { UInt32(line[i]) }
        var acc = px(0) &* UInt32(radius + 1)
        for x in 0 ..< max(edgeA - 1, 0) { acc &+= px(x) }
        acc &+= px(lastx) &* UInt32(bitPattern: Int32(radius - edgeA + 1))
        var out = [UInt8](repeating: 0, count: n)
        func step(_ x: Int, _ subtract: Int, _ add: Int, _ left: Int, _ right: Int) {
            acc = acc &+ px(add) &- px(subtract)
            let bulk = acc &* ww &+ (px(left) &+ px(right)) &* fw
            out[x] = UInt8(truncatingIfNeeded: (bulk &+ (1 << 23)) >> 24)
        }
        if edgeA <= edgeB {
            for x in 0 ..< edgeA { step(x, 0, x + radius, 0, x + radius + 1) }
            for x in edgeA ..< edgeB { step(x, x - radius - 1, x + radius, x - radius - 1, x + radius + 1) }
            for x in edgeB ..< n { step(x, x - radius - 1, lastx, x - radius - 1, lastx) }
        } else {
            for x in 0 ..< edgeB { step(x, 0, x + radius, 0, x + radius + 1) }
            for x in edgeB ..< edgeA { step(x, 0, lastx, 0, lastx) }
            for x in edgeA ..< n { step(x, x - radius - 1, lastx, x - radius - 1, lastx) }
        }
        return out
    }

    // ---------------------------------------------------------------------------------------------- draw

    /// ImageDraw.line(points, fill, width) on a grey picture: the points cut to whole pixels (towards zero), then
    /// Bresenham lines and the last point (width 1) or a filled quadrilateral per segment (wider).
    static func line(_ plane: inout Plane<UInt8>, points: [(Double, Double)], ink: UInt8, width: Int) {
        let p = points.map { (Int($0.0), Int($0.1)) }
        guard let last = p.last else { return }
        var canvas = Canvas(plane: plane)
        if width == 1 {
            for (a, b) in zip(p, p.dropFirst()) { canvas.line(a.0, a.1, b.0, b.1, ink) }
            canvas.point(last.0, last.1, ink)
        } else {
            for (a, b) in zip(p, p.dropFirst()) { canvas.wideLine(a.0, a.1, b.0, b.1, ink, width) }
        }
        plane = canvas.plane
    }

    /// Draw.c's ROUND_UP and ROUND_DOWN of a float (half away from zero, half towards zero).
    static func roundUp(_ f: Float) -> Int {
        f >= 0 ? Int((f + 0.5).rounded(.down)) : -Int((abs(f) + 0.5).rounded(.down))
    }

    static func roundDown(_ f: Float) -> Int {
        f >= 0 ? Int((f - 0.5).rounded(.up)) : -Int((abs(f) - 0.5).rounded(.up))
    }

    static func roundUp(_ f: Double) -> Int {
        f >= 0 ? Int((f + 0.5).rounded(.down)) : -Int((abs(f) + 0.5).rounded(.down))
    }

    static func roundDown(_ f: Double) -> Int {
        f >= 0 ? Int((f - 0.5).rounded(.up)) : -Int((abs(f) - 0.5).rounded(.up))
    }

    struct Edge {
        var xmin, xmax, ymin, ymax, x0, y0: Int
        var dx: Float

        /// add_edge
        init(_ x0: Int, _ y0: Int, _ x1: Int, _ y1: Int) {
            (xmin, xmax) = (min(x0, x1), max(x0, x1))
            (ymin, ymax) = (min(y0, y1), max(y0, y1))
            dx = y0 == y1 ? 0 : Float(x1 - x0) / Float(y1 - y0)
            (self.x0, self.y0) = (x0, y0)
        }

        func x(at y: Int) -> Float { Float(y - y0) * dx + Float(x0) }
    }

    struct Canvas {
        var plane: Plane<UInt8>

        mutating func point(_ x: Int, _ y: Int, _ ink: UInt8) {
            if x >= 0, x < plane.width, y >= 0, y < plane.height { plane[x, y] = ink }
        }

        /// hline8
        mutating func hline(_ x0: Int, _ y: Int, _ x1: Int, _ ink: UInt8) {
            guard y >= 0, y < plane.height else { return }
            var (x0, x1) = (x0, x1)
            if x0 < 0 { x0 = 0 } else if x0 >= plane.width { return }
            if x1 < 0 { return } else if x1 >= plane.width { x1 = plane.width - 1 }
            guard x0 <= x1 else { return }
            for x in x0 ... x1 { plane[x, y] = ink }
        }

        /// line (Bresenham; the end point itself is not drawn)
        mutating func line(_ x0: Int, _ y0: Int, _ x1: Int, _ y1: Int, _ ink: UInt8) {
            var (x0, y0) = (x0, y0)
            var dy = y1 - y0
            let ys: Int
            if dy < 0 {
                (dy, ys) = (-dy, -1)
            } else if dy == 0 {
                if x1 > x0 { hline(x0, y0, x1 - 1, ink) } else if x0 > x1 { hline(x1 + 1, y0, x0, ink) }
                return
            } else {
                ys = 1
            }
            var dx = x1 - x0
            let xs: Int
            if dx < 0 { (dx, xs) = (-dx, -1) } else { xs = 1 }
            if dx == 0 {
                for _ in 0 ..< dy {
                    point(x0, y0, ink)
                    y0 += ys
                }
            } else if dx > dy {
                let n = dx
                dy += dy
                var e = dy - dx
                dx += dx
                for _ in 0 ..< n {
                    point(x0, y0, ink)
                    if e >= 0 {
                        y0 += ys
                        e -= dx
                    }
                    e += dy
                    x0 += xs
                }
            } else {
                let n = dy
                dx += dx
                var e = dx - dy
                dy += dy
                for _ in 0 ..< n {
                    point(x0, y0, ink)
                    if e >= 0 {
                        x0 += xs
                        e -= dy
                    }
                    e += dx
                    y0 += ys
                }
            }
        }

        /// ImagingDrawWideLine: the segment as a quadrilateral `width` pixels across.
        mutating func wideLine(_ x0: Int, _ y0: Int, _ x1: Int, _ y1: Int, _ ink: UInt8, _ width: Int) {
            let (dx, dy) = (x1 - x0, y1 - y0)
            if dx == 0, dy == 0 {
                point(x0, y0, ink)
                return
            }
            let big = hypot(Double(dx), Double(dy))
            let small = Double(width - 1) / 2.0
            let ratioMax = Double(Pillow.roundUp(small)) / big
            let ratioMin = Double(Pillow.roundDown(small)) / big
            let dxmin = Pillow.roundDown(ratioMin * Double(dy)), dxmax = Pillow.roundDown(ratioMax * Double(dy))
            let dymin = Pillow.roundDown(ratioMin * Double(dx)), dymax = Pillow.roundDown(ratioMax * Double(dx))
            let v = [(x0 - dxmin, y0 + dymax), (x1 - dxmin, y1 + dymax), (x1 + dxmax, y1 - dymin), (x0 + dxmax, y0 - dymin)]
            polygon((0 ..< 4).map { Edge(v[$0].0, v[$0].1, v[($0 + 1) % 4].0, v[($0 + 1) % 4].1) }, ink)
        }

        /// polygon_generic (no alpha): a scan line per row, the crossings sorted, filled between pairs.
        mutating func polygon(_ edges: [Edge], _ ink: UInt8) {
            var ymin = plane.height - 1, ymax = 0
            var table: [Edge] = []
            for e in edges {
                ymin = min(ymin, e.ymin)
                ymax = max(ymax, e.ymax)
                if e.ymin == e.ymax {
                    hline(e.xmin, e.ymin, e.xmax, ink)
                    continue
                }
                table.append(e)
            }
            ymin = max(ymin, 0)
            ymax = min(ymax, plane.height)
            guard ymin <= ymax else { return }
            for y in ymin ... ymax {
                var xx: [Float] = []
                for (i, current) in table.enumerated() where y >= current.ymin && y <= current.ymax {
                    xx.append(current.x(at: y))
                    if y == current.ymax, y < ymax {
                        xx.append(xx[xx.count - 1])  // (consistent polygons)
                    } else if y == current.ymin || y == current.ymax, current.dx != 0 {
                        for other in table[..<i] {  // (corners that do not meet)
                            if (y != other.ymin && y != other.ymax) || other.dx == 0 { continue }
                            guard xx[xx.count - 1].rounded() == other.x(at: y).rounded() else { continue }
                            let offset = y == current.ymax ? -1 : 1
                            let adjacent = current.x(at: y + offset)
                            if y + offset >= other.ymin, y + offset <= other.ymax {
                                let adjacentOther = other.x(at: y + offset)
                                let last = xx[xx.count - 1]
                                if last > adjacent + 1, last > adjacentOther + 1 {
                                    xx[xx.count - 1] = max(adjacent, adjacentOther).rounded() + 1
                                } else if last < adjacent - 1, last < adjacentOther - 1 {
                                    xx[xx.count - 1] = min(adjacent, adjacentOther).rounded() - 1
                                }
                                break
                            }
                        }
                    }
                }
                xx.sort()
                for i in stride(from: 1, to: xx.count, by: 2) {
                    hline(Pillow.roundUp(xx[i - 1]), y, Pillow.roundDown(xx[i]), ink)
                }
            }
        }
    }
}

/// The steps of numpy that gui/paper.py takes on float32 pictures, the way numpy does them: the standard deviation
/// (sums in float32, pairwise in blocks of 8 and 128) and the gradient (central differences, one-sided at the edges).
enum Numpy {
    /// pairwise_sum_FLOAT
    static func pairwiseSum(_ a: [Float], _ lo: Int, _ n: Int) -> Float {
        if n < 8 {
            var res: Float = -0.0
            for i in 0 ..< n { res += a[lo + i] }
            return res
        }
        if n <= 128 {
            var r = (0 ..< 8).map { a[lo + $0] }
            var i = 8
            while i < n - n % 8 {
                for j in 0 ..< 8 { r[j] += a[lo + i + j] }
                i += 8
            }
            var res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
            while i < n {
                res += a[lo + i]
                i += 1
            }
            return res
        }
        var n2 = n / 2
        n2 -= n2 % 8
        return pairwiseSum(a, lo, n2) + pairwiseSum(a, lo + n2, n - n2)
    }

    /// ndarray.std() of a float32 array.
    static func std(_ a: [Float]) -> Float {
        guard !a.isEmpty else { return .nan }
        let n = Float(a.count)
        let mean = (0 + pairwiseSum(a, 0, a.count)) / n
        let squares = a.map { ($0 - mean) * ($0 - mean) }
        return ((0 + pairwiseSum(squares, 0, squares.count)) / n).squareRoot()
    }

    /// np.gradient of a float32 picture: (d/dy, d/dx).
    static func gradient(_ p: Plane<Float>) -> (dy: Plane<Float>, dx: Plane<Float>) {
        var gy = Plane<Float>(width: p.width, height: p.height, fill: 0)
        var gx = gy
        guard p.width >= 2, p.height >= 2 else { return (gy, gx) }  // (numpy refuses; the texture stays plain)
        for y in 0 ..< p.height {
            for x in 0 ..< p.width {
                gy[x, y] = y == 0 ? (p[x, 1] - p[x, 0]) / 1
                    : y == p.height - 1 ? (p[x, y] - p[x, y - 1]) / 1 : (p[x, y + 1] - p[x, y - 1]) / 2
                gx[x, y] = x == 0 ? (p[1, y] - p[0, y]) / 1
                    : x == p.width - 1 ? (p[x, y] - p[x - 1, y]) / 1 : (p[x + 1, y] - p[x - 1, y]) / 2
            }
        }
        return (gy, gx)
    }
}
