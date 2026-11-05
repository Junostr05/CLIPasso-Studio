import Foundation

/// A paper under a sketch (gui/paper.py): a texture grown from seeded noise – fine drawing paper, cold-pressed
/// watercolour paper, brown kraft with fibres, woven linen or a wiped blackboard – the background colour of the
/// export (or the kind's own) and a vignette. "none" without a vignette is the plain background as before, so it is
/// no paper at all (nil). The texture is worked out at a size of its own (768 px for the longer side, at most 1600)
/// with its features in units of that size, so a preview and an export of any size look alike – the very pixels the
/// studio makes (numpy's random numbers, Pillow's filters).
public struct Paper: Sendable, Equatable {
    public enum Kind: String, Sendable, CaseIterable {
        case none, drawing, watercolor, kraft, linen, blackboard
    }

    public var kind: Kind
    /// 0 … 1
    public var vignette: Double

    public static let colours: [Kind: String] = [.none: "#FFFFFF", .drawing: "#FBFAF6", .watercolor: "#FAF7F0",
                                                 .kraft: "#C9A97C", .linen: "#EFE9DD", .blackboard: "#2C3A33"]
    /// px: feature sizes are given for a texture of this size
    static let reference = 768
    /// px: larger pictures get the texture scaled up
    static let maxSide = 1600
    /// the vignette of the preview's "Vignette" switch
    public static let vignetteSwitch = 0.35
    /// a paper darker than this (luminance 0 … 1) gets light strokes in the preview
    public static let dark = 0.42
    public static let lightStroke = "#F2F2EC"

    public init(kind: Kind, vignette: Double = 0) {
        (self.kind, self.vignette) = (kind, vignette)
    }

    /// normalize: valid values; nil for no paper (the plain colour, no vignette).
    public static func normalize(kind: String?, vignette: JSONValue? = nil) -> Paper? {
        let kind = Kind(rawValue: kind.flatMap { $0.isEmpty ? nil : $0 } ?? "none") ?? Kind.none
        let v: Double = switch vignette {
        case .int(let i): Double(i)
        case .double(let d): d
        case .string(let s): Double(s.trimmingCharacters(in: .whitespaces)) ?? 0
        case .bool(let b): b ? 1 : 0
        default: 0
        }
        let clamped = v.isNaN ? 0 : min(max(v, 0), 1)
        return kind == .none && clamped <= 0 ? nil : Paper(kind: kind, vignette: clamped)
    }

    /// normalize of a stored paper ({"kind", "vignette"}).
    public static func normalize(_ json: JSONValue?) -> Paper? {
        guard let object = json?.objectValue, !object.isEmpty else { return nil }
        return normalize(kind: object["kind"]?.stringValue, vignette: object["vignette"])
    }

    /// The paper of the export settings (export_paper, export_vignette).
    public static func of(_ settings: AppSettings) -> Paper? {
        normalize(kind: settings["export_paper"]?.stringValue, vignette: settings["export_vignette"])
    }

    /// color_of: the background colour if there is one, else the kind's own colour.
    public static func colour(of paper: Paper?, background: String? = nil) -> String {
        if let background, background != "transparent", rgb(background) != nil { return background }
        return colours[paper?.kind ?? Kind.none] ?? "#FFFFFF"
    }

    /// paper._rgb: "#RRGGBB" or "#RGB", the "#" may be left out.
    public static func rgb(_ colour: String) -> (r: UInt8, g: UInt8, b: UInt8)? {
        var hex = colour.trimmingCharacters(in: .whitespacesAndNewlines)
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6 || hex.count == 3, hex.allSatisfy(\.isHexDigit) else { return nil }
        if hex.count == 3 { hex = hex.map { "\($0)\($0)" }.joined() }
        let v = Int(hex, radix: 16) ?? 0
        return (UInt8(v >> 16 & 0xFF), UInt8(v >> 8 & 0xFF), UInt8(v & 0xFF))
    }

    /// is_dark: darker than `dark` in luminance.
    public static func isDark(_ colour: String) -> Bool {
        guard let (r, g, b) = rgb(colour) else { return false }
        return 0.2126 * Double(r) / 255 + 0.7152 * Double(g) / 255 + 0.0722 * Double(b) / 255 < dark
    }
}

/// The textures of gui/paper.py, step by step as there: float32 numbers, numpy's random numbers, Pillow's resize,
/// blur and lines.
enum PaperTexture {
    /// _noise: smooth value noise with features about `cell` px apart (unit variance).
    static func noise(_ rng: inout NumpyRandom, _ h: Int, _ w: Int, _ cell: Double) -> Plane<Float> {
        let gh = max(2, Int(Double(h) / max(cell, 1)) + 2), gw = max(2, Int(Double(w) / max(cell, 1)) + 2)
        let grid = Plane(width: gw, height: gh, values: (0 ..< gw * gh).map { _ in Float(rng.standardNormal()) })
        let out = Pillow.resize(grid, width: w, height: h)
        let scale = Numpy.std(out.values) + Float(1e-6)
        return Plane(width: w, height: h, values: out.values.map { $0 / scale })
    }

    /// _shade: light from the upper left on a height field (the paper's bumps), unit variance.
    static func shade(_ height: Plane<Float>) -> Plane<Float> {
        let (gy, gx) = Numpy.gradient(height)
        let shade = zip(gx.values, gy.values).map { -($0 + $1) }
        let scale = Numpy.std(shade) + Float(1e-6)
        return Plane(width: height.width, height: height.height, values: shade.map { $0 / scale })
    }

    /// _fibers: short darker and lighter fibres, blurred (-1 … 1).
    static func fibres(_ rng: inout NumpyRandom, _ h: Int, _ w: Int, _ s: Double, count: Int,
                       length: (Double, Double)) -> Plane<Float>
    {
        var layer = Plane<UInt8>(width: w, height: h, fill: 128)
        let width = max(1, Int((0.8 * s).rounded(.toNearestOrEven)))
        for _ in 0 ..< count {
            let x = rng.uniform(0, Double(w)), y = rng.uniform(0, Double(h))
            let a = rng.uniform(0, .pi)
            let n = rng.uniform(length.0, length.1) * s
            let bend = rng.uniform(-0.4, 0.4)
            let points = (0 ..< 6).map { k -> (Double, Double) in
                let t = Double(k) / 5
                let angle = a + bend * t
                return (x + cos(angle) * n * t, y + sin(angle) * n * t)
            }
            let sign = Double(rng.choice([-1, 1]))
            let ink = UInt8(Int(128 + sign * rng.uniform(64, 127)))
            Pillow.line(&layer, points: points, ink: ink, width: width)
        }
        let blurred = Pillow.gaussianBlur(layer, radius: 0.6 * s)
        return Plane(width: w, height: h, values: blurred.values.map { (Float($0) - 128) / 127 })
    }

    static func combine(_ terms: [(Float, Plane<Float>)]) -> Plane<Float> {
        var out = terms[0].1
        out.values = out.values.map { terms[0].0 * $0 }
        for (factor, plane) in terms.dropFirst() {
            for i in out.values.indices { out.values[i] = out.values[i] + factor * plane.values[i] }
        }
        return out
    }

    /// texture: the brightness change per pixel (in 0 … 255 units) of the paper `kind` at `w` × `h`.
    static func texture(_ kind: Paper.Kind, width w: Int, height h: Int, seed: UInt32 = 7) -> Plane<Float> {
        guard kind != .none else { return Plane(width: w, height: h, fill: 0) }
        let longer = max(w, h)
        let side = min(longer, Paper.maxSide)
        let gw = max(1, Int((Double(w * side) / Double(longer)).rounded(.toNearestOrEven)))
        let gh = max(1, Int((Double(h * side) / Double(longer)).rounded(.toNearestOrEven)))
        let s = Double(side) / Double(Paper.reference)
        var rng = NumpyRandom(seed: [seed, UInt32(Paper.Kind.allCases.firstIndex(of: kind) ?? 0)])
        var t: Plane<Float>
        switch kind {
        case .drawing:  // fine tooth
            let a = noise(&rng, gh, gw, 2.0 * s)
            let height = combine([(1, a), (0.5, noise(&rng, gh, gw, 6 * s))])
            let shaded = shade(height)
            let fine = noise(&rng, gh, gw, 1.2 * s)
            let broad = noise(&rng, gh, gw, 60 * s)
            t = combine([(2.2, shaded), (2.0, fine), (1.2, broad)])
        case .watercolor:  // cold-pressed: soft bumps
            let a = noise(&rng, gh, gw, 7 * s)
            let b = noise(&rng, gh, gw, 16 * s)
            let c = noise(&rng, gh, gw, 3 * s)
            let shaded = shade(combine([(1, a), (0.6, b), (0.3, c)]))
            t = combine([(6.0, shaded), (2.5, noise(&rng, gh, gw, 80 * s))])
        case .kraft:  // brown, mottled, with fibres
            let a = noise(&rng, gh, gw, 40 * s)
            let b = noise(&rng, gh, gw, 2 * s)
            let count = Int(Double(gw * gh) / (900 * s * s)) + 1
            t = combine([(4.5, a), (3.5, b), (22.0, fibres(&rng, gh, gw, s, count: count, length: (6, 26)))])
        case .linen:  // woven threads
            let p = 4.0 * s
            let rows = (0 ..< Int(Double(gh) / p) + 2).map { _ in Float(rng.normal(0, 1)) }
            let cols = (0 ..< Int(Double(gw) / p) + 2).map { _ in Float(rng.normal(0, 1)) }
            let wobble = noise(&rng, gh, gw, 30 * s).values.map { Float(0.6) * $0 }
            let (twoPi, pf) = (Float(2 * Double.pi), Float(p))
            var threads = Plane<Float>(width: gw, height: gh, fill: 0)
            for y in 0 ..< gh {
                for x in 0 ..< gw {
                    let i = y * gw + x
                    let (fy, fx) = (Float(y), Float(x))
                    let warp = cos(twoPi * (fy + wobble[i]) / pf) * (1 + Float(0.35) * rows[Int(fy / pf)])
                    let weft = cos(twoPi * (fx - wobble[i]) / pf) * (1 + Float(0.35) * cols[Int(fx / pf)])
                    threads.values[i] = warp + weft
                }
            }
            let fine = noise(&rng, gh, gw, 1.5 * s)
            t = combine([(4.0, threads), (2.0, fine), (2.5, noise(&rng, gh, gw, 70 * s))])
        case .blackboard, .none:  // wiped chalk dust
            let a = noise(&rng, gh, gw, 110 * s)
            let b = noise(&rng, gh, gw, 35 * s)
            var wipes = combine([(1, a), (0.5, b)])
            wipes.values = wipes.values.map { max($0, 0) }
            let fine = noise(&rng, gh, gw, 1.2 * s)
            t = combine([(7.0, wipes), (2.2, fine), (1.5, noise(&rng, gh, gw, 6 * s))])
        }
        if gw != w || gh != h { t = Pillow.resize(t, width: w, height: h) }
        return t
    }

    /// _vignette: 1 in the middle, darker towards the corners.
    static func vignette(width w: Int, height h: Int, strength: Double) -> Plane<Float> {
        let c = Float(0.55 * strength)
        let root = Float(0.5.squareRoot())
        var out = Plane<Float>(width: w, height: h, fill: 1)
        for y in 0 ..< h {
            let dy = (Float(y) + 0.5) / Float(h) - 0.5
            for x in 0 ..< w {
                let dx = (Float(x) + 0.5) / Float(w) - 0.5
                let r = (dx * dx + dy * dy).squareRoot() / root
                let edge = min(max((r - 0.35) / 0.65, 0), 1)
                out[x, y] = 1 - c * edge * edge * (3 - 2 * edge)
            }
        }
        return out
    }

    /// image: the paper as RGB bytes (w × h × 3), the colour plus the texture, the vignette over it.
    static func rgb(_ paper: Paper?, width w: Int, height h: Int, background: String? = nil) -> [UInt8] {
        let p = paper ?? Paper(kind: Paper.Kind.none)
        let base = Paper.rgb(Paper.colour(of: p, background: background)) ?? (255, 255, 255)
        let channels = [Float(base.r), Float(base.g), Float(base.b)]
        let t = texture(p.kind, width: w, height: h)
        let v = p.vignette > 0 ? vignette(width: w, height: h, strength: p.vignette) : nil
        var out = [UInt8](repeating: 0, count: w * h * 3)
        for i in 0 ..< w * h {
            for c in 0 ..< 3 {
                var value = channels[c] + t.values[i]
                if let v { value = value * v.values[i] }
                out[i * 3 + c] = UInt8(min(max(value + 0.5, 0), 255))
            }
        }
        return out
    }
}
