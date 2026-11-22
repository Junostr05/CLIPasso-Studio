import Foundation

/// The object mask drawn over the photo (gui/mask_view.overlay): the background – where the mask is 0 – under a
/// veil, the object outlined; at most `maxSide` pixels (a larger mask shrunk as Pillow shrinks it).
public enum MaskOverlay {
    /// An RGBA colour (0 … 255 each).
    public typealias Colour = (r: UInt8, g: UInt8, b: UInt8, a: UInt8)

    /// The overlay's pixels, RGBA (not premultiplied), row after row; `mask` the object, row after row.
    public static func rgba(_ mask: [Bool], width: Int, height: Int, veil: Colour, edge: Colour, maxSide: Int = 900)
        -> (width: Int, height: Int, pixels: [UInt8])
    {
        var m = Plane(width: width, height: height, values: mask)
        let scale = min(1, Double(maxSide) / Double(max(height, width, 1)))
        if scale < 1 {  // (as an 8-bit picture: bilinear, then ≥ 128 is the object)
            let w = max(1, Int((Double(width) * scale).rounded(.toNearestOrEven)))
            let h = max(1, Int((Double(height) * scale).rounded(.toNearestOrEven)))
            let grey = Plane(width: width, height: height, values: mask.map { $0 ? UInt8(255) : 0 })
            let small = Pillow.resizeBilinear(grey, width: w, height: h)
            m = Plane(width: w, height: h, values: small.values.map { $0 >= 128 })
        }
        let (w, h) = (m.width, m.height)
        var pixels = [UInt8](repeating: 0, count: w * h * 4)
        for i in 0 ..< w * h where !m.values[i] {
            (pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2], pixels[i * 4 + 3]) = (veil.r, veil.g, veil.b, veil.a)
        }
        let rim = zip(m.values, erode(m).values).map { $0 && !$1 }
        let reach = max(1, Int((Double(max(h, w)) / 320).rounded(.toNearestOrEven)))
        let outline = dilate(Plane(width: w, height: h, values: rim), reach)
        for i in 0 ..< w * h where outline.values[i] {
            (pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2], pixels[i * 4 + 3]) = (edge.r, edge.g, edge.b, 255)
        }
        return (w, h, pixels)
    }

    /// _erode: a pixel stays where its four neighbours are set too (the picture's edge counts as set).
    static func erode(_ m: Plane<Bool>) -> Plane<Bool> {
        var out = m
        for y in 0 ..< m.height {
            for x in 0 ..< m.width {
                let i = y * m.width + x
                var keep = m.values[i]
                if y > 0 { keep = keep && m.values[i - m.width] }
                if y < m.height - 1 { keep = keep && m.values[i + m.width] }
                if x > 0 { keep = keep && m.values[i - 1] }
                if x < m.width - 1 { keep = keep && m.values[i + 1] }
                out.values[i] = keep
            }
        }
        return out
    }

    /// _dilate: `steps` times, a pixel is set where it or one of its four neighbours is.
    static func dilate(_ m: Plane<Bool>, _ steps: Int) -> Plane<Bool> {
        var out = m
        for _ in 0 ..< steps {
            let last = out
            for y in 0 ..< m.height {
                for x in 0 ..< m.width {
                    let i = y * m.width + x
                    guard !last.values[i] else { continue }
                    var near = y > 0 && last.values[i - m.width]
                    near = near || (y < m.height - 1 && last.values[i + m.width])
                    near = near || (x > 0 && last.values[i - 1])
                    out.values[i] = near || (x < m.width - 1 && last.values[i + 1])
                }
            }
        }
        return out
    }
}
