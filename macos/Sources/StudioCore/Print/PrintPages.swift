import Foundation

/// A sketch to print: its SVG as it is now (touched up or not), the caption under it and the photo's shape of its run
/// (for the frame "photo").
public struct PrintItem: Sendable {
    public let svg: String
    public let caption: String
    public let photo: SketchFraming.PhotoFrame?

    public init(svg: String, caption: String, photo: SketchFraming.PhotoFrame? = nil) {
        (self.svg, self.caption, self.photo) = (svg, caption, photo)
    }
}

#if canImport(CoreGraphics) && canImport(CoreText)
    import CoreGraphics
    import CoreText

    /// The pages of a print layout drawn with Core Graphics as the studio paints them with Qt (print_layout.paint_page):
    /// the background, the heading (Inter SemiBold), the footer and the captions (Inter), the sketches restyled and
    /// framed – as a PDF of vector pages in points, or one page as a picture for the preview.
    public enum PrintPages {
        public static let pointsPerMM = 72 / 25.4

        /// The page's size in points.
        public static func pageSize(_ layout: PrintLayout) -> CGSize {
            let (w, h) = layout.pageMM
            return CGSize(width: w * pointsPerMM, height: h * pointsPerMM)
        }

        /// print_layout._sketch: the sketch restyled (one colour unless it keeps its own, the widths scaled) and
        /// framed; nil when it cannot be read.
        static func sketch(_ item: PrintItem, _ layout: PrintLayout) -> (sketch: Sketch, aspect: Double)? {
            let restyled = SketchExport.restyleSVG(item.svg, strokeColor: layout.stroke, widthScale: layout.widthScale)
            let framing = SketchFraming.make(item.svg, mode: layout.frame, frame: item.photo, margin: layout.frameMargin)
            let text = framing?.apply(restyled) ?? restyled
            guard let sketch = try? SketchSVG.parse(text) else { return nil }
            let box = SketchEditing.viewBox(text)
            return (sketch, box.width > 0 && box.height > 0 ? box.width / box.height : 1)
        }

        /// paint_page's paper: `side` pixels wide (at most 2400) in the page's shape.
        public static func paper(_ layout: PrintLayout, side: Int) throws -> CGImage? {
            guard let paper = layout.paper else { return nil }
            let (w, h) = layout.pageMM
            let width = min(2400, max(1, side))
            let height = max(1, Int((Double(width) * h / w).rounded(.toNearestOrEven)))  // (Python's round)
            return try PaperPicture.image(paper, width: width, height: height, background: layout.background)
        }

        /// The paper's width in a PDF: Qt's page at 600 dpi is wider than 2400 pixels, so 2400.
        static func pdfPaperSide(_ layout: PrintLayout) -> Int { Int(layout.pageMM.width / 25.4 * 600) }

        /// One page into `context` (y up, the page at 0, 0 of `size`): `items` are this page's sketches, `paper` the
        /// paper under them (PrintPages.paper).
        public static func draw(_ items: ArraySlice<PrintItem>, layout: PrintLayout, page: Int, pages: Int,
                                in context: CGContext, size: CGSize, paper: CGImage? = nil)
        {
            let height = Double(size.height)
            func rect(_ box: PageBox) -> CGRect {  // (from the top left to Core Graphics' bottom left)
                CGRect(x: box.x, y: height - box.y - box.height, width: box.width, height: box.height)
            }
            if let paper {
                context.interpolationQuality = .high
                context.draw(paper, in: CGRect(origin: .zero, size: size))
            } else if let ground = layout.background.flatMap({ $0 == "transparent" ? nil : SketchSVG.color($0) }) {
                context.setFillColor(SketchRenderer.cgColor(ground))
                context.fill(CGRect(origin: .zero, size: size))
            }
            let (cols, rows) = layout.grid
            let shown = Array(items.prefix(cols * rows))
            let sketches = shown.map { sketch($0, layout) }
            let boxes = layout.boxes(width: Double(size.width), height: height, captions: shown.map(\.caption),
                                     aspects: sketches.map { $0?.aspect }, pages: pages)
            let colour = SketchSVG.color(layout.textColour).map { SketchRenderer.cgColor($0) }
                ?? CGColor(srgbRed: 0.23, green: 0.23, blue: 0.23, alpha: 1)
            if let box = boxes.title {
                text(layout.title, in: rect(box), align: .left, font: font(semibold: true, size: boxes.titleSize),
                     colour: colour, context: context)
            }
            let small = font(semibold: false, size: boxes.smallSize)
            if let box = boxes.footer {
                if !layout.signature.isEmpty {
                    text(layout.signature, in: rect(box), align: .right, font: small, colour: colour, context: context)
                }
                if pages > 1 {
                    text("\(page) / \(pages)", in: rect(box), align: .left, font: small, colour: colour, context: context)
                }
            }
            for (k, item) in shown.enumerated() {
                if let box = boxes.captions[k] {
                    text(item.caption, in: rect(box), align: .center, font: small, colour: colour, context: context)
                }
                if let sketch = sketches[k]?.sketch, let box = boxes.sketches[k] {
                    SketchRenderer.draw(sketch, in: context, rect: rect(box))
                }
            }
        }

        /// export_pdf_pages: a PDF of the sketches laid out on pages (vector, in points), titled `title`.
        /// `progress` hears (pages done, pages); a cancelled task stops between pages (CancellationError).
        public static func pdf(_ items: [PrintItem], layout: PrintLayout, title: String,
                               progress: (Int, Int) -> Void = { _, _ in }) throws -> Data
        {
            let chunks = layout.pages(items)
            let size = pageSize(layout)
            var media = CGRect(origin: .zero, size: size)
            let data = NSMutableData()
            let info = [kCGPDFContextTitle: title, kCGPDFContextCreator: "CLIPasso Studio"] as CFDictionary
            guard let consumer = CGDataConsumer(data: data as CFMutableData),
                  let context = CGContext(consumer: consumer, mediaBox: &media, info)
            else { throw SketchRenderer.RenderError(description: "no PDF writer") }
            let ground = try Self.paper(layout, side: pdfPaperSide(layout))  // (one picture for every page)
            for (i, chunk) in chunks.enumerated() {
                if Task.isCancelled {
                    context.closePDF()
                    throw CancellationError()
                }
                context.beginPDFPage(nil)
                draw(chunk, layout: layout, page: i + 1, pages: chunks.count, in: context, size: size, paper: ground)
                context.endPDFPage()
                progress(i + 1, chunks.count)
            }
            context.closePDF()
            return data as Data
        }

        /// preview: page `page` (1 …) as a picture `width` pixels wide, on white.
        public static func preview(_ items: [PrintItem], layout: PrintLayout, width: Int, page: Int = 1) throws -> CGImage {
            let (wMM, hMM) = layout.pageMM
            let height = max(1, Int((Double(width) * hMM / wMM).rounded(.toNearestOrEven)))
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { throw SketchRenderer.RenderError(description: "no bitmap of \(width)×\(height)") }
            let size = CGSize(width: width, height: height)
            context.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
            context.fill(CGRect(origin: .zero, size: size))
            let chunks = layout.pages(items)
            let shown = chunks.isEmpty ? [] : chunks[min(max(page, 1), chunks.count) - 1]
            let ground = try Self.paper(layout, side: width)
            draw(shown, layout: layout, page: min(max(page, 1), max(chunks.count, 1)), pages: max(chunks.count, 1),
                 in: context, size: size, paper: ground)
            guard let image = context.makeImage() else { throw SketchRenderer.RenderError(description: "the bitmap gave no image") }
            return image
        }

        // ------------------------------------------------------------------------------------------------ text

        enum Align { case left, center, right }

        /// Inter (SemiBold for the heading) as the studio prints, the system font where Inter is not installed; `size`
        /// is the em in the page's units (Qt's pixel size).
        static func font(semibold: Bool, size: Int) -> CTFont {
            let name = semibold ? "Inter-SemiBold" : "Inter-Regular"
            let inter = CTFontCreateWithName(name as CFString, CGFloat(size), nil)
            if CTFontCopyPostScriptName(inter) as String == name { return inter }
            return CTFontCreateUIFontForLanguage(semibold ? .emphasizedSystem : .system, CGFloat(size), nil)
                ?? CTFontCreateWithName("Helvetica" as CFString, CGFloat(size), nil)
        }

        /// One line in `rect`, centred vertically on the font's height as Qt's AlignVCenter (cut short with "…"
        /// where it is wider than the rect).
        static func text(_ string: String, in rect: CGRect, align: Align, font: CTFont, colour: CGColor,
                         context: CGContext)
        {
            guard !string.isEmpty, rect.width > 0 else { return }
            let attributes = [kCTFontAttributeName: font, kCTForegroundColorAttributeName: colour] as CFDictionary
            func line(_ s: String) -> CTLine {
                CTLineCreateWithAttributedString(CFAttributedStringCreate(nil, s as CFString, attributes))
            }
            var shown = line(string)
            if CTLineGetTypographicBounds(shown, nil, nil, nil) > Double(rect.width),
               let cut = CTLineCreateTruncatedLine(shown, Double(rect.width), .end, line("…"))
            {
                shown = cut
            }
            var ascent: CGFloat = 0, descent: CGFloat = 0, leading: CGFloat = 0
            let width = CGFloat(CTLineGetTypographicBounds(shown, &ascent, &descent, &leading))
            let x: CGFloat = switch align {
            case .left: rect.minX
            case .center: rect.midX - width / 2
            case .right: rect.maxX - width
            }
            context.saveGState()
            context.textMatrix = .identity
            context.textPosition = CGPoint(x: x, y: rect.midY - (ascent - descent) / 2)
            CTLineDraw(shown, context)
            context.restoreGState()
        }
    }
#endif
