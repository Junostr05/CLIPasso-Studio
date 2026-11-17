import Foundation
import Testing
@testable import StudioCore
#if canImport(CoreGraphics)
    import CoreGraphics
    import ImageIO
#endif

/// The exports of a sketch with the studio's choices (dialogs.ExportDialog, gui/export.py): kept under the studio's
/// keys, the strokes restyled, the frame applied – the background filling it – and PNG and PDF of the frame's shape.
@Suite(.onOwnThreads) struct SketchExporterTests {
    static func sketch(_ name: String) throws -> String { String(decoding: try Fixtures.data(name), as: UTF8.self) }

    @Test func theLastChoicesUnderTheStudiosKeys() {
        let home = URL(filePath: "/tmp")
        var settings = AppSettings(data: [:], defaultOutputDir: home)
        let fresh = ExportOptions(settings: settings, format: .png)
        #expect(fresh.background == "#FFFFFF" && fresh.stroke == "#000000" && fresh.frame == .square && fresh.size == 1024)
        #expect(ExportOptions(settings: settings, format: .svg).background == nil)  // (an SVG: transparent at first)
        settings["export_background"] = "transparent"
        #expect(ExportOptions(settings: settings, format: .gif).background == "#FFFFFF")  // (GIF, MP4: never)
        #expect(ExportOptions(settings: settings, format: .webp).background == nil && ExportOptions.Format.webp.title == "WebP")
        #expect(ExportOptions(settings: settings, format: .mp4).size == 512 && ExportOptions.Format.png.animation == nil)
        #expect(ExportOptions(settings: settings, format: .html).background == "#FFFFFF")  // (a web page: never)
        #expect(ExportOptions(settings: settings, format: .matrix).size == 1024)
        #expect(ExportOptions.Format.svg1.fileExtension == "svg" && ExportOptions.Format.svg1.suffix == "_1layer")
        #expect(ExportOptions.Format.lottie.fileExtension == "json" && ExportOptions.Format.matrix.fileExtension == "zip")
        #expect(ExportOptions.Format.pictures + ExportOptions.Format.animations == ExportOptions.Format.allCases)
        settings["export_background"] = nil
        var chosen = fresh
        chosen.stroke = "#336699"
        chosen.widthScale = 2.5
        chosen.background = nil
        chosen.frame = .content
        chosen.margin = 12
        chosen.pdfWidth = 21
        chosen.remember(in: &settings, format: .pdf)
        #expect(settings["export_background"] == "transparent" && settings["export_frame"] == "content")
        #expect(settings["export_margin"] == 12 && settings["export_pdf_width"] == 21.0 && settings["export_last_format"] == "pdf")
        let again = ExportOptions(settings: settings, format: .pdf)
        #expect(again.stroke == "#336699" && again.widthScale == 2.5 && again.background == nil && again.frame == .content)
        #expect(again.margin == 12 && again.pdfWidth == 21)
        var plotter = again
        plotter.background = "#123456"
        plotter.frame = .square
        plotter.remember(in: &settings, format: .svg1)  // (the plotter's SVG: no background to keep)
        #expect(settings["export_background"] == "transparent" && settings["export_frame"] == "square")
        plotter.frame = .content
        plotter.remember(in: &settings, format: .matrix)  // (the matrix: no frame to keep)
        #expect(settings["export_background"] == "#123456" && settings["export_frame"] == "square")
        settings["export_width"] = 50  // (out of range: clamped as the dialog's field clamps)
        #expect(ExportOptions(settings: settings, format: .svg).widthScale == 10)
    }

    /// The SVG: one colour, the widths scaled, cropped to the strokes – its background filling the new frame.
    @Test func anSVGCroppedToItsStrokes() throws {
        var options = ExportOptions()
        options.stroke = "#336699"
        options.widthScale = 2
        options.background = "#101010"
        options.frame = .content
        options.margin = 50
        let out = SketchExporter.svg(try Self.sketch("svg/lines.svg"), options: options)
        let root = try #require(SketchEditing.elements(out).first?.tag)
        let box = try #require(root.value("viewBox"))
        let background = try #require(SketchEditing.elements(out).first { $0.tag.name == "rect" }?.tag)
        #expect(["x", "y", "width", "height"].map { background.value($0) ?? "" }.joined(separator: " ") == box)
        let parsed = try SketchSVG.parse(out)
        #expect(parsed.strokes.allSatisfy { $0.color == RGB(0x33, 0x66, 0x99) } && parsed.background == "#101010")
        #expect(SketchExport.restyleSVG(try Self.sketch("svg/lines.svg")).contains(#"stroke-width="1.5""#))
        #expect(out.contains(#"stroke-width="3""#))  // 1.5 × 2
        options.frame = .photo
        #expect(SketchExporter.svg(try Self.sketch("svg/lines.svg"), options: options).contains(#"viewBox="0 0 224 224""#))
    }

    /// The other formats through one door: framed first, then written as SketchFormats writes them.
    @Test func theTextFormats() throws {
        let svg = try Self.sketch("animation/drawing.svg")
        var options = ExportOptions()
        #expect(SketchExporter.text(svg, format: .svg1, options: options) == SketchFormats.singleLayer(svg))
        #expect(SketchExporter.text(svg, format: .svg, options: options) == SketchExporter.svg(svg, options: options))
        let page = SketchExporter.text(svg, format: .html, options: options, name: "Kamel")
        #expect(page.hasPrefix("<!doctype html>") && page.contains("<title>Kamel</title>"))
        let text = SketchExporter.text(svg, format: .lottie, options: options, name: "Kätzchen")
        #expect(text.contains(#""nm":"K\u00e4tzchen""#))  // (written as Python writes it: ASCII only)
        let lottie = try PyJSON.parse(Data(text.utf8))
        #expect(lottie.objectValue?["layers"]?.arrayValue?.count == 5)  // (one layer a stroke, no background)
        options.frame = .content
        let framed = SketchExporter.text(svg, format: .svganim, options: options)
        #expect(!framed.contains(#"viewBox="0 0 224 224""#) && framed.contains("@keyframes d4"))
        let layered = SketchExporter.text(svg, format: .svglayers, options: options, labels: ("Hintergrund", "Objekt"))
        #expect(layered.contains(#"inkscape:label="Hintergrund""#) && !layered.contains(#"viewBox="0 0 224 224""#))
    }

    /// Black is no colour (ExportDialog._save): the strokes keep their own.
    @Test func blackKeepsTheSketchsColours() throws {
        let coloured = try Self.sketch("svg/lines.svg")
            .replacingOccurrences(of: #"stroke="rgb(0, 0, 0)""#, with: ##"stroke="#aa3311""##)
        let before = try SketchSVG.parse(coloured).strokes.map(\.color)
        #expect(before.contains(RGB(0xAA, 0x33, 0x11)))
        let options = ExportOptions()
        #expect(options.strokeColour == nil)
        #expect(try SketchSVG.parse(SketchExporter.svg(coloured, options: options)).strokes.map(\.color) == before)
    }

    #if canImport(CoreGraphics)
        @Test func aPNGOfTheFramesShape() throws {
            var options = ExportOptions()
            options.background = "#fff8e7"
            options.frame = .photo
            options.size = 300
            let photo = SketchFraming.PhotoFrame(aspect: 1.5, rect: [0, 0, 1, 1])  // (a landscape stretched onto the canvas)
            let data = try SketchExporter.png(try Self.sketch("svg/cubic.svg"), options: options, photo: photo)
            let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            #expect(image.width == 300 && image.height == 200)
        }

        /// On paper (export_paper, export_vignette in percent): the PNG's ground is the paper, in the background's
        /// colour; the SVG embeds it as a JPEG in place of the background rect.
        @Test func onPaper() throws {
            var settings = AppSettings(data: [:], defaultOutputDir: URL(filePath: "/tmp"))
            settings["export_paper"] = "kraft"
            settings["export_vignette"] = 40
            var options = ExportOptions(settings: settings, format: .png)
            #expect(options.paper == Paper(kind: .kraft, vignette: 0.4))
            options.remember(in: &settings, format: .png)
            #expect(settings["export_paper"] == "kraft" && settings["export_vignette"] == 40)
            options.size = 96
            let data = try SketchExporter.png(try Self.sketch("svg/lines.svg"), options: options)
            let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            #expect(image.width == 96 && image.height == 96)
            let paper = PaperTexture.rgb(options.paper, width: 96, height: 96, background: options.background)
            #expect(Set(stride(from: 0, to: paper.count, by: 3).map { paper[$0] }).count > 3)  // (a texture, not a colour)
            options.background = "#101010"
            let svg = SketchExporter.svg(try Self.sketch("svg/closed_bg.svg"), options: options)
            #expect(svg.contains(#"<image data-bg="1" x="0" y="0" width="224" height="224" preserveAspectRatio="none""#))
            #expect(svg.contains("data:image/jpeg;base64,") && svg.contains("xmlns:xlink"))
            #expect(!svg.contains(#"data-bg="1" />"#))  // (the background rect made way for the paper)
            options.paper = nil
            #expect(!SketchExporter.svg(try Self.sketch("svg/closed_bg.svg"), options: options).contains("<image"))
        }

        @Test func aPDFPageOfTheChosenWidth() throws {
            var options = ExportOptions()
            options.pdfWidth = 21
            options.frame = .content
            let data = try SketchExporter.pdf(try Self.sketch("svg/closed_bg.svg"), options: options, title: "Kamel")
            let document = try #require(CGPDFDocument(CGDataProvider(data: data as CFData)!))
            #expect(document.numberOfPages == 1)
            let page = try #require(document.page(at: 1)?.getBoxRect(.mediaBox))
            #expect(abs(page.width - 21 / 2.54 * 72) < 0.01)  // 21 cm
            let framed = try #require(SketchExporter.framing(try Self.sketch("svg/closed_bg.svg"), options, photo: nil))
            #expect(abs(page.height / page.width - 1 / framed.aspect) < 1e-4)  // the strokes' box (written with 3 decimals)
        }
    #endif
}
