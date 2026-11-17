import Foundation

/// A SceneSketch matrix as the studio exports it (export.export_matrix_zip): every sketch of the job – the touched-up
/// one where a cell was touched up – as SVG and PNG (L<layer>_level<n>), and the overview sheet matrix.svg /
/// matrix.png, in one ZIP file.
public enum MatrixExport {
    /// The cells of a job (cell number → its sketch restyled), in the order of the job's runs.
    public static func cells(jobDir: URL, options: ExportOptions) -> [(cell: Int, svg: String)] {
        guard let summary = JobFolder.summary(at: jobDir) else { return [] }
        var cells: [(cell: Int, svg: String)] = []
        for run in summary.runs {
            guard let seed = run["seed"]?.intValue ?? run["seed"]?.doubleValue.map({ Int($0) }),
                  let file = JobFolder.sketchFile(runDir: run["run_dir"]?.stringValue.flatMap {
                      $0.isEmpty ? nil : URL(filePath: $0, directoryHint: .isDirectory)
                  }, original: run["best_svg"]?.stringValue ?? ""),
                  let text = try? String(contentsOf: file, encoding: .utf8)
            else { continue }
            let restyled = SketchExport.restyleSVG(text, strokeColor: options.strokeColour, widthScale: options.widthScale)
            if let at = cells.firstIndex(where: { $0.cell == seed }) {
                cells[at].svg = restyled  // (a dict: the later run of a cell wins, in the first's place)
            } else {
                cells.append((seed, restyled))
            }
        }
        return cells
    }

    /// The entry names of a cell.
    public static func name(_ cell: Int) -> String { "L\(cell / 100)_level\(cell % 100)" }
}

#if canImport(CoreGraphics) && canImport(CoreText) && canImport(ImageIO)
    import CoreGraphics
    import CoreText

    public extension MatrixExport {
        /// The ZIP file; `progress` hears (cells written, cells) and (0, 0) while the sheet is drawn. A cancelled
        /// task stops between cells (CancellationError).
        static func zip(jobDir: URL, options: ExportOptions, progress: (Int, Int) -> Void = { _, _ in }) throws -> Data {
            let cells = cells(jobDir: jobDir, options: options)
            guard !cells.isEmpty else { throw ExportError(code: "export_no_sketches") }
            var zip = ZipWriter()
            let ground = options.background.flatMap { SketchSVG.color($0) }
            for (n, (cell, svg)) in cells.sorted(by: { $0.cell < $1.cell }).enumerated() {
                if Task.isCancelled { throw CancellationError() }
                let withBackground = SketchExport.restyleSVG(svg, background: options.background)
                zip.add("\(name(cell)).svg", text: PaperPicture.svgWithPaper(withBackground, paper: options.paper,
                                                                             background: options.background))
                let sketch = try SketchSVG.parse(svg)
                let png: CGImage
                if let paper = options.paper {
                    let (w, h) = SketchRenderer.size(of: sketch, longSide: options.size)
                    let base = try PaperPicture.image(paper, width: w, height: h, background: options.background)
                    png = try SketchRenderer.image(sketch, longSide: options.size, background: nil, under: base)
                } else {
                    png = try SketchRenderer.image(sketch, longSide: options.size, background: ground)
                }
                zip.add("\(name(cell)).png", try SketchRenderer.pngData(png))
                progress(n + 1, cells.count)
            }
            progress(0, 0)
            let sheet = SketchFormats.matrixSheet(cells, background: options.background)
            zip.add("matrix.svg", text: PaperPicture.svgWithPaper(sheet, paper: options.paper, background: options.background))
            zip.add("matrix.png", try SketchRenderer.pngData(sheetImage(cells, options: options)))
            return zip.finished()
        }

        /// matrix.png: the sheet drawn – the cells about as large as the PNGs (1 … 4 times the sheet's 224 px), the
        /// layers above, the levels at the left, on the background or the paper.
        static func sheetImage(_ cells: [(cell: Int, svg: String)], options: ExportOptions, cell: Int = 224,
                               gap: Int = 16) throws -> CGImage
        {
            let layers = Set(cells.map { $0.cell / 100 }).sorted(), levels = Set(cells.map { $0.cell % 100 }).sorted()
            let (side, head) = (70, 34)
            let width = side + layers.count * (cell + gap) + gap, height = head + levels.count * (cell + gap) + gap
            let scale = max(1, min(4, Double(options.size) / 224))
            let (w, h) = (Int(Double(width) * scale), Int(Double(height) * scale))
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: space,
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { throw SketchRenderer.RenderError(description: "no bitmap of \(w)×\(h)") }
            if let paper = options.paper {
                context.draw(try PaperPicture.image(paper, width: w, height: h, background: options.background),
                             in: CGRect(x: 0, y: 0, width: w, height: h))
            } else if let ground = options.background.flatMap({ SketchSVG.color($0) }) {
                context.setFillColor(SketchRenderer.cgColor(ground))
                context.fill(CGRect(x: 0, y: 0, width: w, height: h))
            }
            // (the sheet's units from the top left; Core Graphics from the bottom left)
            func flipped(_ x: Double, _ y: Double, _ size: Double) -> CGRect {
                CGRect(x: x * scale, y: Double(h) - (y + size) * scale, width: size * scale, height: size * scale)
            }
            let font = CTFontCreateWithName("Helvetica" as CFString, 16 * scale, nil)
            let grey = CGColor(srgbRed: 0x55 / 255.0, green: 0x55 / 255.0, blue: 0x55 / 255.0, alpha: 1)
            func label(_ text: String, x: Double, baseline y: Double, centred: Bool) {
                let attributes = [kCTFontAttributeName: font, kCTForegroundColorAttributeName: grey] as CFDictionary
                let line = CTLineCreateWithAttributedString(CFAttributedStringCreate(nil, text as CFString, attributes))
                let width = CTLineGetTypographicBounds(line, nil, nil, nil)
                context.textPosition = CGPoint(x: x * scale - (centred ? width / 2 : width), y: Double(h) - y * scale)
                CTLineDraw(line, context)
            }
            for (col, layer) in layers.enumerated() {
                label("L\(layer)", x: Double(side + gap + col * (cell + gap)) + Double(cell) / 2, baseline: Double(head - 10),
                      centred: true)
            }
            for (row, level) in levels.enumerated() {
                label("\(level)", x: Double(side - 8), baseline: Double(head + gap + row * (cell + gap)) + Double(cell) / 2 + 6,
                      centred: false)
            }
            for (c, svg) in cells {
                guard let sketch = try? SketchSVG.parse(svg),
                      let col = layers.firstIndex(of: c / 100), let row = levels.firstIndex(of: c % 100)
                else { continue }
                // (the cell's viewBox fitted into its square, centred – an SVG's xMidYMid meet)
                let aspect = Double(max(sketch.width, 1)) / Double(max(sketch.height, 1))
                let (cw, ch) = aspect >= 1 ? (Double(cell), Double(cell) / aspect) : (Double(cell) * aspect, Double(cell))
                var rect = flipped(Double(side + gap + col * (cell + gap)), Double(head + gap + row * (cell + gap)), Double(cell))
                rect = rect.insetBy(dx: (Double(cell) - cw) / 2 * scale, dy: (Double(cell) - ch) / 2 * scale)
                SketchRenderer.draw(sketch, in: context, rect: rect)
            }
            guard let image = context.makeImage() else { throw SketchRenderer.RenderError(description: "the sheet gave no image") }
            return image
        }
    }
#endif
