import Foundation

/// The choices of an export (dialogs.ExportDialog), kept in the settings under the studio's keys – export_stroke,
/// export_width, export_background ("transparent" or a colour), export_frame, export_margin, export_pdf_width – so the
/// Mac app and the studio start from the last export of either.
public struct ExportOptions: Sendable, Equatable {
    public enum Format: String, Sendable, CaseIterable {
        case svg, png, pdf
    }

    public var stroke = "#000000"
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
            ?? (format == .svg ? "transparent" : "#FFFFFF")
        background = bg == "transparent" ? nil : bg
        frame = SketchFraming.Mode(rawValue: settings["export_frame"]?.stringValue ?? "") ?? .square
        margin = min(50, max(0, settings["export_margin"]?.intValue ?? 5))
        size = format == .png ? 1024 : 512
        pdfWidth = min(200, max(2, settings["export_pdf_width"]?.doubleValue ?? 15))
        paper = Paper.of(settings)
    }

    /// ExportDialog._save: the choices kept for the next export.
    public func remember(in settings: inout AppSettings, format: Format) {
        settings["export_stroke"] = .string(stroke)
        settings["export_width"] = .double(widthScale)
        settings["export_background"] = .string(background ?? "transparent")
        settings["export_frame"] = .string(frame.rawValue)
        settings["export_margin"] = .int(margin)
        if format == .pdf { settings["export_pdf_width"] = .double(pdfWidth) }
        Paper.remember(paper, in: &settings)
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

    /// export.export_svg (the plain style): restyled, framed, then the paper.
    public static func svg(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil) -> String {
        let restyled = SketchExport.restyleSVG(svg, strokeColor: options.strokeColour, widthScale: options.widthScale,
                                               background: options.background)
        let framed = framing(svg, options, photo: photo)?.apply(restyled) ?? restyled
        #if canImport(ImageIO)
            return PaperPicture.svgWithPaper(framed, paper: options.paper, background: options.background)
        #else
            return framed
        #endif
    }

    /// The restyled, framed sketch a PNG or PDF draws (its background is the picture's, not a rect).
    static func drawn(_ svg: String, _ options: ExportOptions, photo: SketchFraming.PhotoFrame?) -> String {
        let restyled = SketchExport.restyleSVG(svg, strokeColor: options.strokeColour, widthScale: options.widthScale)
        return framing(svg, options, photo: photo)?.apply(restyled) ?? restyled
    }
}

#if canImport(CoreGraphics)
    import CoreGraphics

    public extension SketchExporter {
        /// export.export_png: the longer side `options.size` pixels, in the frame's shape, on the background.
        static func png(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil) throws -> Data {
            let sketch = try SketchSVG.parse(drawn(svg, options, photo: photo))
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
        static func pdf(_ svg: String, options: ExportOptions, photo: SketchFraming.PhotoFrame? = nil, title: String)
            throws -> Data
        {
            let text = drawn(svg, options, photo: photo)
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
