import Foundation

/// The animations of a sketch as the studio makes them (gui/export.py): the drawing process – the saved steps of a
/// run one after another – or the finished sketch drawn stroke by stroke, as GIF, WebP or MP4. This is the plan of
/// them: which drawn frames an animation shows and how long, and the lengths the export dialog starts from.
public enum SketchAnimation {
    public enum Format: String, Sendable, CaseIterable {
        case gif, webp, mp4
    }

    /// what an animation shows (export_anim_mode)
    public enum Mode: String, Sendable, CaseIterable {
        /// the saved steps of the run (svg_logs)
        case process
        /// the finished sketch drawn stroke by stroke
        case strokes
    }

    public static let mp4FPS = 30
    /// GIF / WebP: browsers slow shorter GIF frame delays down to 100 ms
    public static let minFrameMS = 20
    public static let maxFrames = 5000
    /// the drawn frames wait in memory (1 byte per pixel) until they are encoded
    public static let maxFrameBytes = 800_000_000
    /// palette steps from the background to the stroke colour (anti-aliased edges)
    public static let inkLevels = 8
    /// drawn frames per second of the stroke-by-stroke timeline
    public static let drawStepsPerSecond = 50

    /// every_step_length: seconds of a "drawing process" that shows each of its `n` saved steps once (as fast as
    /// the format allows: 50 frames a second for GIF / WebP, 30 for MP4).
    public static func everyStepLength(_ n: Int, format: Format) -> Double {
        let perFrame = format == .mp4 ? 1.0 / Double(mp4FPS) : Double(minFrameMS) / 1000
        return Python.round(Double(max(n, 1)) * perFrame + 0.049, digits: 1)
    }

    /// dialogs.default_animation_length: seconds for the drawing process – like the old 20 fps, 2 – 10 s.
    public static func defaultProcessLength(_ frames: Int) -> Double {
        (min(10, max(2, Double(frames) / 20)) * 2).rounded(.toNearestOrEven) / 2
    }

    /// default_drawing_length: seconds for a stroke-by-stroke drawing – about a quarter second per stroke,
    /// 2 – 12 s; a sketch of a single line (`line`: its length in canvas widths) about 0.6 s per canvas width.
    public static func defaultDrawingLength(strokes: Int, line: Double = 0) -> Double {
        let seconds = strokes == 1 && line > 0 ? line * 0.6 : Double(strokes) * 0.25
        return (min(12, max(2, seconds)) * 2).rounded(.toNearestOrEven) / 2
    }

    /// animation_plan: which of the `n` drawn frames an animation shows, and how long (ms) each one stays. The
    /// drawing takes `length` seconds (default n / fps) and the final sketch stays `hold` seconds longer. GIF and
    /// WebP show each drawn frame for length / n – below 20 ms per frame the frames are thinned out; MP4 plays at
    /// 30 fps and repeats or skips drawn frames to fill the length.
    public static func plan(_ n: Int, length: Double? = nil, fps: Double = 20, hold: Double = 1, format: Format,
                            size: Int = 512) -> (frames: [Int], durations: [Double])
    {
        guard n > 0 else { return ([], []) }
        let length = length.map { max($0, 0.1) } ?? Double(n) / max(fps, 1e-3)
        let hold = max(hold, 0)
        if format == .mp4 {
            let count = max(1, Int((length * Double(mp4FPS)).rounded(.toNearestOrEven)))
            var frames = (0 ..< count).map { max(0, ($0 + 1) * n / count - 1) }
            frames += Array(repeating: n - 1, count: Int((hold * Double(mp4FPS)).rounded(.toNearestOrEven)))
            return (frames, Array(repeating: 1000.0 / Double(mp4FPS), count: frames.count))
        }
        let limit = min(Int(Python.floorDivide(length * 1000, Double(minFrameMS))), maxFrames,
                        maxFrameBytes / max(size * size, 1))
        let k = max(1, min(n, limit))
        let frames = k > 1 ? (0 ..< k).map { Int((Double($0 * (n - 1)) / Double(k - 1)).rounded(.toNearestOrEven)) }
            : [n - 1]
        let step = format == .gif ? 10 : 1  // (GIF keeps delays in 1/100 s)
        let ends = (0 ..< k).map { i in
            Int((length * 1000 * Double(i + 1) / Double(k) / Double(step)).rounded(.toNearestOrEven)) * step
        }
        var durations = zip([0] + ends.dropLast(), ends).map { Double(max(step, $1 - $0)) }
        durations[durations.count - 1] += Double(Int((hold * 1000 / Double(step)).rounded(.toNearestOrEven)) * step)
        return (frames, durations)
    }

    /// animation_frames: the saved steps of a run (svg_logs/svg_iter<i>.svg) in their order – up to its best one.
    public static func steps(runDir: URL, uptoBest: Bool = true) -> [URL] {
        let logs = runDir.appending(path: "svg_logs", directoryHint: .isDirectory)
        let names = (try? FileManager.default.contentsOfDirectory(atPath: logs.path)) ?? []
        func number(_ name: String) -> Int? {
            guard name.hasPrefix("svg_iter"), name.hasSuffix(".svg") else { return nil }
            let digits = name.dropFirst(8).dropLast(4)
            return !digits.isEmpty && digits.allSatisfy(\.isASCII) && digits.allSatisfy(\.isNumber) ? Int(digits) : nil
        }
        var frames = names.compactMap { name in number(name).map { (name, $0) } }
            .sorted { $0.1 < $1.1 }
        if uptoBest, let data = try? Data(contentsOf: runDir.appending(path: "config.json")),
           let config = try? PyJSON.parse(data).objectValue
        {
            let value = config["best_iter"]
            let best = value?.intValue ?? value?.doubleValue.map { Int($0) } ?? value?.stringValue.flatMap { Int($0) }
                ?? 1_000_000_000
            let upto = frames.filter { $0.1 <= best }
            if !upto.isEmpty { frames = upto }
        }
        return frames.map { logs.appending(path: $0.0) }
    }

    /// run_method: the run's method (config.json), "clipasso" when it is not known.
    public static func method(runDir: URL) -> String {
        guard let data = try? Data(contentsOf: runDir.appending(path: "config.json")),
              let method = (try? PyJSON.parse(data))?.objectValue?["method"]?.stringValue, !method.isEmpty
        else { return "clipasso" }
        return method
    }
}

/// Python's number rules where the studio's arithmetic needs them.
enum Python {
    /// round(x, digits): to the nearest decimal of `digits` places of x's exact value, ties to even.
    static func round(_ x: Double, digits: Int) -> Double {
        Double(String(format: "%.\(digits)f", x)) ?? x
    }

    /// a // b of two floats (float_floor_div).
    static func floorDivide(_ a: Double, _ b: Double) -> Double {
        let mod = fmod(a, b)
        var div = (a - mod) / b
        if mod != 0, (b < 0) != (mod < 0) { div -= 1 }
        guard div != 0 else { return a / b < 0 ? -0.0 : 0.0 }
        var floored = div.rounded(.down)
        if div - floored > 0.5 { floored += 1 }
        return floored
    }

    /// sum() of floats: since Python 3.12 compensated (Neumaier) – a plain loop can differ in the last place, and
    /// whether the last stroke is complete at the end of a drawing hangs on that place.
    static func sum(_ values: some Sequence<Double>) -> Double {
        var total = 0.0, c = 0.0
        for x in values {
            let t = total + x
            c += abs(total) >= abs(x) ? (total - t) + x : (x - t) + total
            total = t
        }
        if c != 0, c.isFinite { total += c }
        return total
    }

    /// math.hypot(x, y) as CPython computes it (vector_norm: lossless scaling and squaring, a differential correction)
    /// – the system's hypot may round the last place differently.
    static func hypot(_ x: Double, _ y: Double) -> Double {
        var vec = [abs(x), abs(y)], top = 0.0
        for v in vec where v > top { top = v }
        if top.isInfinite { return top }
        if x.isNaN || y.isNaN { return .nan }
        if top == 0 { return top }
        let exponent = Int(top.exponent) + 1  // (frexp: top = m · 2^e with 0.5 ≤ m < 1)
        if exponent < -1023 {
            let tiny = Double.leastNormalMagnitude
            return tiny * hypot(vec[0] / tiny, vec[1] / tiny)
        }
        let scale = Double(sign: .plus, exponent: -exponent, significand: 1)
        var csum = 1.0, frac1 = 0.0, frac2 = 0.0
        func add(_ z: Double, _ zz: Double) {  // (dl_mul's two parts, then dl_fast_sum into csum)
            let s = csum + z
            frac1 += zz
            frac2 += z - (s - csum)
            csum = s
        }
        for i in vec.indices {
            vec[i] *= scale
            let z = vec[i] * vec[i]
            add(z, (-z).addingProduct(vec[i], vec[i]))
        }
        var h = (csum - 1 + (frac1 + frac2)).squareRoot()
        let z = -h * h
        add(z, (-z).addingProduct(-h, h))
        h += (csum - 1 + (frac1 + frac2)) / (2 * h)
        return h / scale
    }

    /// float(text): Python reads a number with white space around it (" 4 ").
    static func float(_ text: String) -> Double? {
        Double(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}
