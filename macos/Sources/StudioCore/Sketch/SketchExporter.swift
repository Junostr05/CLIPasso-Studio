import Foundation

/// The choices of an export (dialogs.ExportDialog), kept in the settings under the studio's keys – export_stroke,
/// export_width, export_background ("transparent" or a colour), export_frame, export_margin, export_pdf_width – so the
/// Mac app and the studio start from the last export of either.
public struct ExportOptions: Sendable, Equatable {
    /// The formats of the export dialog (export_center.GROUPS): pictures, then animations.
    public enum Format: String, Sendable, CaseIterable {
        case svg, png, pdf, svg1, svglayers, matrix, gif, mp4, webp, svganim, lottie, html

        public static let pictures: [Format] = [.svg, .png, .pdf, .svg1, .svglayers, .matrix]
        public static let animations: [Format] = [.gif, .mp4, .webp, .svganim, .lottie, .html]

        /// the animation drawn here frame by frame (nil: not one)
        public var animation: SketchAnimation.Format? { SketchAnimation.Format(rawValue: rawValue) }

        /// the finished strokes drawn one by one in a browser or an app (DRAWN)
        public var drawnElsewhere: Bool { self == .svganim || self == .lottie || self == .html }

        /// the file's extension (EXTENSIONS)
        public var fileExtension: String {
            switch self {
            case .svg1, .svglayers, .svganim: "svg"
            case .matrix: "zip"
            case .lottie: "json"
            default: rawValue
            }
        }

        /// added to the file's name ("_1layer", …)
        public var suffix: String {
            switch self {
            case .svg1: "_1layer"
            case .svglayers: "_layers"
            case .matrix: "_matrix"
            case .svganim: "_animated"
            default: ""
            }
        }

        /// a transparent background is possible (GIF, MP4 and a web page: white instead)
        public var allowsTransparent: Bool { ![.gif, .mp4, .html].contains(self) }

        /// transparent unless a background was chosen before
        var transparentAtFirst: Bool { [.svg, .svglayers, .svganim, .lottie].contains(self) }

        /// a picture's longer side to choose (not for SVG, PDF, Lottie, a web page)
        public var hasSize: Bool { [.png, .matrix, .gif, .mp4, .webp].contains(self) }

        /// its name in the dialog's heading where it is the format's own (texts: the others)
        public var title: String { self == .webp ? "WebP" : self == .lottie ? "Lottie" : rawValue.uppercased() }
    }

    public var stroke = "#000000"
    /// the brush style (brush.STYLES; the engine draws it – Stylist)
    public var style = "plain"
    /// the strokes' width times this (0.1 … 10)
    public var widthScale = 1.0
    /// nil: transparent
    public var background: String?
    public var frame = SketchFraming.Mode.square
    /// the free space around the strokes when cropped to them, in percent (0 … 50)
    public var margin = 5
    /// a PNG's longer side in pixels (64 … 8192)
    public var size = 1024
    /// a PDF's width in cm (2 … 200)
    public var pdfWidth = 15.0
    /// the paper under the strokes (nil: the plain background)
    public var paper: Paper?

    public init() {}

    /// The colour the strokes get – none for black: as the studio's dialog, the sketch then keeps its own colours.
    public var strokeColour: String? { stroke.lowercased() == "#000000" ? nil : stroke }

    /// The last choices (the dialog's defaults where there are none: a white background for PNG and PDF, none for SVG).
    public init(settings: AppSettings, format: Format) {
        if let s = settings["export_stroke"]?.stringValue, !s.isEmpty { stroke = s }
        widthScale = min(10, max(0.1, settings["export_width"]?.doubleValue ?? 1))
        let bg = settings["export_background"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 }
            ?? (format.transparentAtFirst ? "transparent" : "#FFFFFF")
        background = bg == "transparent" ? (format.allowsTransparent ? nil : "#FFFFFF") : bg
        frame = SketchFraming.Mode(rawValue: settings["export_frame"]?.stringValue ?? "") ?? .square
        margin = min(50, max(0, settings["export_margin"]?.intValue ?? 5))
        size = format == .png || format == .matrix ? 1024 : 512
        pdfWidth = min(200, max(2, settings["export_pdf_width"]?.doubleValue ?? 15))
        paper = Paper.of(settings)
        if let s = settings["export_style"]?.stringValue, !s.isEmpty { style = s }
    }

    /// The choices ⌘C copies with (dialogs.copy_sketch): the last export's, 1024 pixels, white for a transparent
    /// background (many programs paste transparency as black).
    public static func forClipboard(_ settings: AppSettings) -> ExportOptions {
        var options = ExportOptions(settings: settings, format: .png)
        options.size = 1024
        if options.background == nil { options.background = "#FFFFFF" }
        return options
    }

    /// ExportDialog._save: the choices kept for the next export (the plotter's SVG has no background or paper, the
    /// matrix no frame).
    public func remember(in settings: inout AppSettings, format: Format) {
        settings["export_stroke"] = .string(stroke)
        settings["export_width"] = .double(widthScale)
        settings["export_style"] = .string(style)  // (kept also where the format draws plain lines)
        if format != .svg1 {
            settings["export_background"] = .string(background ?? "transparent")
            Paper.remember(paper, in: &settings)
        }
        if format != .matrix {
            settings["export_frame"] = .string(frame.rawValue)
            settings["export_margin"] = .int(margin)
        }
        if format == .pdf { settings["export_pdf_width"] = .double(pdfWidth) }
        settings["export_last_format"] = .string(format.rawValue)
    }
}

/// A sketch as the studio exports it (gui/export.py): its strokes in one colour and width, the frame chosen, and the
/// background – in an SVG as a rect behind the strokes, in a PNG and a PDF as the picture's ground – or the paper,
/// in the background's colour (in an SVG an embedded JPEG).
public enum SketchExporter {
    /// export.framing_for: the frame (measured on the sketch as drawn); nil for "square" or when it is not known.
    public static func framing(_ svg: String, _ options: ExportOptions, photo: SketchFraming.PhotoFrame?)
        -> SketchFraming.Framing?
    {
        SketchFraming.make(svg, mode: options.frame, frame: photo, margin: Double(options.margin) / 100)
    }

    /// export.export_svg: restyled, framed, drawn in the brush style, then the paper.
    public static func svg(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil,
                           stylist: Stylist = .plain) throws -> String
    {
        let restyled = SketchExport.restyleSVG(svg, strokeColor: options.strokeColour, widthScale: options.widthScale,
                                               background: options.background)
        let framed = try stylist(framing(svg, options, photo: photo)?.apply(restyled) ?? restyled)
        #if canImport(ImageIO)
            return PaperPicture.svgWithPaper(framed, paper: options.paper, background: options.background)
        #else
            return framed
        #endif
    }

    /// The text formats of a sketch as the studio writes them: SVG, the plotter's one-layer SVG, the SceneSketch cell
    /// in two layers (`labels`; its run's object.svg tells them apart), the SVG that draws itself, Lottie and the web
    /// page (named `name`) – framed first; a ControlSketch run's strokes drawn in their order. The brush style for
    /// all but the plotter's SVG and Lottie (they stay plain lines).
    public static func text(_ svg: String, format: ExportOptions.Format, options: ExportOptions,
                            photo: SketchFraming.PhotoFrame? = nil, runDir: URL? = nil, length: Double? = nil,
                            hold: Double = 1, name: String = "sketch", labels: (String, String) = ("Background", "Object"),
                            stylist: Stylist = .plain) throws -> String
    {
        let framed = framing(svg, options, photo: photo)?.apply(svg) ?? svg
        let keep = runDir.map { SketchAnimation.method(runDir: $0) == "controlsketch" } ?? false
        func animated() throws -> String {
            try SketchFormats.animatedSVG(framed, length: length, hold: hold, strokeColor: options.strokeColour,
                                          widthScale: options.widthScale, background: options.background,
                                          keepOrder: keep, paper: options.paper, stylist: stylist)
        }
        switch format {
        case .svg1:
            return SketchFormats.singleLayer(framed, strokeColor: options.strokeColour, widthScale: options.widthScale)
        case .svglayers:
            let layered = SketchFormats.layered(svg, objects: SketchFormats.objectStrokes(runDir: runDir), labels: labels)
            return try self.svg(layered, options: options, photo: photo, stylist: stylist)
        case .svganim:
            return try animated()
        case .lottie:
            return PyJSON.dump(SketchFormats.lottie(framed, length: length, hold: hold, strokeColor: options.strokeColour,
                                                    widthScale: options.widthScale, background: options.background,
                                                    keepOrder: keep, paper: options.paper, name: name),
                               asciiOnly: true, compact: true)  // (json.dump: ensure_ascii)
        case .html:
            let page = options.paper != nil ? Paper.colour(of: options.paper, background: options.background) : options.background
            return SketchFormats.webPage(try animated(), title: name, background: page)
        default:
            return try self.svg(svg, options: options, photo: photo, stylist: stylist)
        }
    }

    /// The restyled, framed sketch in its brush style that a PNG or PDF draws (its background is the picture's, not
    /// a rect).
    static func drawn(_ svg: String, _ options: ExportOptions, photo: SketchFraming.PhotoFrame?,
                      stylist: Stylist = .plain) throws -> String
    {
        let restyled = SketchExport.restyleSVG(svg, strokeColor: options.strokeColour, widthScale: options.widthScale)
        return try stylist(framing(svg, options, photo: photo)?.apply(restyled) ?? restyled)
    }
}

#if canImport(CoreGraphics)
    import CoreGraphics

    public extension SketchExporter {
        /// export.export_png: the longer side `options.size` pixels, in the frame's shape, on the background.
        static func png(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil,
                        stylist: Stylist = .plain) throws -> Data
        {
            try png(drawn: drawn(svg, options, photo: photo, stylist: stylist), options: options)
        }

        /// dialogs.copy_sketch / export.sketch_mime: what ⌘C puts on the clipboard – the sketch with the last export's
        /// choices (`options`, ExportOptions.forClipboard) as a PNG and as an SVG with its background or paper, both
        /// of the sketch styled once.
        static func clipboard(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil,
                              stylist: Stylist = .plain) throws -> (png: Data, svg: String)
        {
            let drawn = try drawn(svg, options, photo: photo, stylist: stylist)
            var text = drawn
            if let background = options.background {
                text = SketchExport.restyleSVG(drawn, strokeColor: nil, widthScale: 1, background: background)
            }
            #if canImport(ImageIO)
                text = PaperPicture.svgWithPaper(text, paper: options.paper, background: options.background)
            #endif
            return (try png(drawn: drawn, options: options), text)
        }

        /// A PNG of the sketch restyled, framed and styled.
        private static func png(drawn: String, options: ExportOptions) throws -> Data {
            let sketch = try SketchSVG.parse(drawn)
            let ground = options.background.flatMap { SketchSVG.color($0) }
            guard let paper = options.paper else {
                return try SketchRenderer.pngData(SketchRenderer.image(sketch, longSide: options.size, background: ground))
            }
            let (w, h) = SketchRenderer.size(of: sketch, longSide: options.size)
            let base = try PaperPicture.image(paper, width: w, height: h, background: options.background)
            return try SketchRenderer.pngData(SketchRenderer.image(sketch, longSide: options.size, background: nil, under: base))
        }

        /// export.export_pdf: one vector page `options.pdfWidth` cm wide in the sketch's shape (its viewBox), the
        /// background filled under the strokes – for printing.
        static func pdf(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil, title: String,
                        stylist: Stylist = .plain) throws -> Data
        {
            let text = try drawn(svg, options, photo: photo, stylist: stylist)
            let sketch = try SketchSVG.parse(text)
            let box = SketchEditing.viewBox(text)
            let aspect = box.width > 0 && box.height > 0 ? box.height / box.width : 1
            let width = max(options.pdfWidth, 1) * 10 / 25.4 * 72  // (cm → points)
            var page = CGRect(x: 0, y: 0, width: width, height: width * aspect)
            let data = NSMutableData()
            let info = [kCGPDFContextTitle: title, kCGPDFContextCreator: "CLIPasso Studio"] as CFDictionary
            guard let consumer = CGDataConsumer(data: data as CFMutableData),
                  let context = CGContext(consumer: consumer, mediaBox: &page, info)
            else { throw SketchRenderer.RenderError(description: "no PDF writer") }
            context.beginPDFPage(nil)
            if let paper = options.paper {  // (PDF_PAPER_DPI: 200 dpi, at most 3000 px)
                let wMM = max(options.pdfWidth, 1) * 10
                let scale = min(200 / 25.4, 3000 / max(wMM, wMM * aspect))
                let picture = try PaperPicture.image(paper, width: max(1, Int((wMM * scale).rounded(.toNearestOrEven))),
                                                     height: max(1, Int((wMM * aspect * scale).rounded(.toNearestOrEven))),
                                                     background: options.background)
                context.interpolationQuality = .high
                context.draw(picture, in: page)
            } else if let ground = options.background.flatMap({ SketchSVG.color($0) }) {
                context.setFillColor(SketchRenderer.cgColor(ground))
                context.fill(page)
            }
            SketchRenderer.draw(sketch, in: context, rect: page)
            context.endPDFPage()
            context.closePDF()
            return data as Data
        }
    }
#endif
