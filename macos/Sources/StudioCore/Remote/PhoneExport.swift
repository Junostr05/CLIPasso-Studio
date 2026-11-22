import Foundation

/// The export from the phone (gui/export_jobs.py): the formats, which option applies to which, what an export starts
/// with after the last ones (the settings, shared with the window's export sheet), what the phone's options become –
/// made safe – and what is remembered for the next export.
public enum PhoneExport {
    public static let formats = ["png", "svg", "svg1", "svglayers", "pdf", "gif", "mp4", "webp", "svganim", "lottie",
                                 "html", "matrix"]
    static let animations = ["gif", "mp4", "webp"]
    static let drawn = ["svganim", "lottie", "html"]
    static let transparentOK = ["svg", "svglayers", "png", "webp", "matrix", "svganim", "pdf", "lottie"]
    /// MAX_SIZE: px from the phone (the window's sheet goes further)
    public static let maxSize = 4096
    public static let contentTypes = [
        "png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf", "gif": "image/gif", "mp4": "video/mp4",
        "webp": "image/webp", "json": "application/json", "html": "application/octet-stream", "zip": "application/zip",
    ]
    /// framing.MODES
    static let frames = ["square", "photo", "content"]

    /// What the sketch offers for the animations (export_jobs.info).
    public struct Sketch: Sendable {
        public var processFrames: Int
        public var strokes: Int
        public var drawLength: Double
        public var processLength: Double
        public var photoFrame: Bool

        public init(processFrames: Int, strokes: Int, drawLength: Double, processLength: Double, photoFrame: Bool) {
            (self.processFrames, self.strokes, self.drawLength) = (processFrames, strokes, drawLength)
            (self.processLength, self.photoFrame) = (processLength, photoFrame)
        }

        public var json: JSONObject {
            ["process_frames": .int(processFrames), "strokes": .int(strokes), "draw_length": .double(drawLength),
             "process_length": .double(processLength), "photo_frame": .bool(photoFrame)]
        }
    }

    public static func fileExtension(_ fmt: String) -> String {
        ["svg1": "svg", "svglayers": "svg", "matrix": "zip", "svganim": "svg", "lottie": "json", "html": "html"][fmt]
            ?? fmt
    }

    public static func suffix(_ fmt: String) -> String {
        ["svg1": "_1layer", "svglayers": "_layers", "matrix": "_matrix", "svganim": "_animated"][fmt] ?? ""
    }

    public static func title(_ fmt: String, texts: Texts) -> String {
        switch fmt {
        case "svg1": texts.tr("ui.export_svg1")
        case "svglayers": texts.tr("ui.export_svglayers")
        case "webp": "WebP"
        case "matrix": texts.tr("ui.export_matrix")
        case "svganim": texts.tr("ui.export_svganim")
        case "lottie": "Lottie"
        case "html": texts.tr("ui.export_html")
        default: fmt.uppercased()
        }
    }

    /// applies: which options the format has.
    public static func applies(_ fmt: String, processFrames: Int = 0) -> JSONObject {
        let timed = animations.contains(fmt) || drawn.contains(fmt)
        return [
            "stroke": true, "width": true, "style": .bool(!["svg1", "lottie"].contains(fmt)),
            "background": .bool(fmt != "svg1"), "transparent": .bool(transparentOK.contains(fmt)),
            "paper": .bool(fmt != "svg1"), "frame": .bool(fmt != "matrix"),
            "size": .bool(!["svg", "svg1", "svglayers", "svganim", "pdf", "lottie", "html"].contains(fmt)),
            "width_cm": .bool(fmt == "pdf"), "mode": .bool(animations.contains(fmt) && processFrames > 1),
            "length": .bool(timed), "hold": .bool(timed),
        ]
    }

    /// The value when it is there and `ok` – else none (not JSON's null: a JSONValue takes nil as a literal, so
    /// "? $0 : nil" would make one).
    static func when(_ value: JSONValue?, _ ok: (JSONValue) -> Bool) -> JSONValue? {
        guard let value, ok(value) else { return nil }
        return value
    }

    /// _number: float(value), else the fallback.
    static func number(_ value: JSONValue?, _ fallback: Double) -> Double {
        value.flatMap(PhoneStudio.pyFloat) ?? fallback
    }

    /// _colour: #RRGGBB (or "transparent" where it may be), else the fallback.
    static func colour(_ value: JSONValue?, _ fallback: String, transparent: Bool = false) -> String {
        let text: String = {
            guard let value, value.truthy else { return "" }
            return PhoneStudio.pyStr(value).trimmingCharacters(in: .whitespacesAndNewlines)
        }()
        if transparent, text == "transparent" { return text }
        let hex = text.dropFirst()
        if text.count == 7, text.first == "#", hex.allSatisfy({ $0.isHexDigit && $0.isASCII }) { return text }
        return fallback
    }

    /// defaults: the options an export starts with – the choices of the last export.
    public static func defaults(_ fmt: String, sketch: Sketch, settings: AppSettings) -> JSONObject {
        let stored = when(settings["export_background"]) { $0.truthy }
        var bg = stored ?? .string(["svg", "svglayers", "svganim", "lottie"].contains(fmt) ? "transparent" : "#FFFFFF")
        if bg == "transparent", !transparentOK.contains(fmt) { bg = "#FFFFFF" }
        var frame = settings["export_frame"] ?? "square"
        if !frames.contains(frame.stringValue ?? "\u{0}") || (frame == "photo" && !sketch.photoFrame) { frame = "square" }
        let mode: JSONValue = drawn.contains(fmt) || sketch.processFrames < 2
            ? "strokes" : settings["export_anim_mode"] ?? "process"
        let length = mode == "strokes" || drawn.contains(fmt) ? sketch.drawLength : sketch.processLength
        let stroke = when(settings["export_stroke"]) { $0.truthy }.map(PhoneStudio.pyStr) ?? "#000000"
        return [
            "stroke": .string(stroke), "width": .double(number(settings["export_width"], 1)),
            "style": settings["export_style"] ?? "plain", "background": bg, "paper": settings["export_paper"] ?? "none",
            "vignette": .int(Int(number(settings["export_vignette"], 0))), "frame": frame,
            "margin": .int(Int(number(settings["export_margin"], 5))),
            "size": .int(fmt == "png" || fmt == "matrix" ? 1024 : 512),
            "width_cm": .double(number(settings["export_pdf_width"], 15)), "mode": mode,
            "length": .double(max(0.5, length)), "hold": 1.0,
        ]
    }

    /// check: the options the phone sent, made safe – unknown values fall back to the defaults, numbers are clamped.
    public static func check(_ fmt: String, _ raw: JSONValue?, sketch: Sketch, settings: AppSettings,
                             styles: [String]) -> JSONObject
    {
        let base = defaults(fmt, sketch: sketch, settings: settings)
        let ok = applies(fmt, processFrames: sketch.processFrames)
        let r = raw?.objectValue ?? [:]
        func clamp(_ key: String, _ lo: Double, _ hi: Double) -> Double {
            let fallback = number(base[key], 0)
            return min(hi, max(lo, number(r[key] ?? base[key], fallback)))
        }
        var out = base
        out["stroke"] = .string(colour(r["stroke"], base["stroke"]?.stringValue ?? "#000000"))
        out["width"] = .double(clamp("width", 0.1, 10))
        out["style"] = when(r["style"]) { $0.stringValue.map(styles.contains) == true } ?? base["style"]
        out["background"] = .string(colour(r["background"], base["background"]?.stringValue ?? "#FFFFFF",
                                           transparent: ok["transparent"]?.truthy ?? false))
        out["paper"] = when(r["paper"]) { $0.stringValue.flatMap(Paper.Kind.init(rawValue:)) != nil } ?? base["paper"]
        out["vignette"] = .int(Int(clamp("vignette", 0, 100)))
        let frame = r["frame"]?.stringValue ?? ""
        out["frame"] = .string(frames.contains(frame) && (frame != "photo" || sketch.photoFrame) ? frame : "square")
        out["margin"] = .int(Int(clamp("margin", 0, 50)))
        out["size"] = .int(Int(clamp("size", 64, Double(maxSize))))
        out["width_cm"] = .double(clamp("width_cm", 2, 200))
        let mode = r["mode"]?.stringValue ?? ""
        let modeOK = ok["mode"]?.truthy ?? false
        out["mode"] = modeOK && ["process", "strokes"].contains(mode) ? .string(mode)
            : (modeOK ? base["mode"] ?? "strokes" : "strokes")
        out["length"] = .double(clamp("length", 0.5, 300))
        out["hold"] = .double(clamp("hold", 0, 10))
        return out
    }

    /// remember: the choices kept for the next export (the window's sheet starts with them, too).
    public static func remember(_ fmt: String, _ o: JSONObject, in settings: inout AppSettings) {
        settings["export_last_format"] = .string(fmt)
        settings["export_stroke"] = o["stroke"]
        settings["export_width"] = o["width"]
        if fmt != "svg1" {
            for (key, name) in [("style", "export_style"), ("background", "export_background"),
                                ("paper", "export_paper"), ("vignette", "export_vignette")]
            {
                settings[name] = o[key]
            }
        }
        if fmt != "matrix" {
            settings["export_frame"] = o["frame"]
            settings["export_margin"] = o["margin"]
        }
        if fmt == "pdf" { settings["export_pdf_width"] = o["width_cm"] }
        if animations.contains(fmt) { settings["export_anim_mode"] = o["mode"] }
    }

    /// export_jobs.run's options as the Mac app's exporters take them.
    public static func options(_ fmt: String, _ o: JSONObject) -> ExportOptions {
        var e = ExportOptions()
        e.stroke = o["stroke"]?.stringValue ?? "#000000"
        e.widthScale = o["width"]?.doubleValue ?? 1
        e.style = ["svg1", "lottie"].contains(fmt) ? "plain" : o["style"]?.stringValue ?? "plain"
        let bg = o["background"]?.stringValue ?? "transparent"
        e.background = bg == "transparent" ? nil : bg
        e.paper = fmt == "svg1" ? nil : Paper.normalize(kind: o["paper"]?.stringValue,
                                                         vignette: .double(Double(o["vignette"]?.intValue ?? 0) / 100))
        e.frame = SketchFraming.Mode(rawValue: o["frame"]?.stringValue ?? "") ?? .square
        e.margin = o["margin"]?.intValue ?? 5
        e.size = o["size"]?.intValue ?? 1024
        e.pdfWidth = o["width_cm"]?.doubleValue ?? 15
        return e
    }
}
