import Foundation
import Testing
@testable import StudioCore
#if canImport(CoreGraphics)
    import CoreGraphics
#endif

/// The print layout as gui/print_layout.py lays out its pages – checked against what Python worked out
/// (Fixtures/export/print.json): the pages' sizes, the grids, where the heading, footer, captions and sketches go –
/// the choices kept under the studio's keys, and the pages drawn as a PDF and a preview.
@Suite struct PrintLayoutTests {
    static func box(_ value: JSONValue?) -> [Double]? {
        guard let value, !value.isNull else { return nil }
        return value.arrayValue?.compactMap(\.doubleValue)
    }

    static func numbers(_ box: PageBox?) -> [Double]? { box.map { [$0.x, $0.y, $0.width, $0.height] } }

    static func layout(_ object: JSONObject) -> PrintLayout {
        var layout = PrintLayout()
        layout.page = PrintLayout.Page(rawValue: object["page"]?.stringValue ?? "a4") ?? .a4
        layout.landscape = object["landscape"]?.truthy ?? false
        layout.perPage = object["per_page"]?.intValue ?? 1
        layout.marginMM = object["margin_mm"]?.doubleValue ?? 15
        layout.title = object["title"]?.stringValue ?? ""
        layout.signature = object["signature"]?.stringValue ?? ""
        layout.captions = object["captions"]?.truthy ?? false
        return layout
    }

    @Test func pagesGridsAndColoursLikePython() throws {
        let fixture = try #require(Fixtures.json("export/print.json").objectValue)
        for s in (fixture["sizes"]?.arrayValue ?? []).compactMap(\.objectValue) {
            var layout = PrintLayout()
            layout.page = try #require(PrintLayout.Page(rawValue: s["page"]?.stringValue ?? ""))
            layout.landscape = s["landscape"]?.truthy ?? false
            let mm = Self.box(s["mm"]) ?? []
            #expect([layout.pageMM.width, layout.pageMM.height] == mm, "\(layout.page) \(layout.landscape)")
        }
        let grids = (fixture["grids"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(grids.count == 24)
        for g in grids {
            let n = g["per_page"]?.intValue ?? 0
            let grid = PrintLayout.grid(n, landscape: g["landscape"]?.truthy ?? false)
            #expect([grid.cols, grid.rows] == (g["grid"]?.arrayValue ?? []).compactMap(\.intValue), "\(n)")
        }
        for c in (fixture["counts"]?.arrayValue ?? []).compactMap(\.objectValue) {
            var layout = PrintLayout()
            layout.perPage = c["per_page"]?.intValue ?? 1
            let n = c["n"]?.intValue ?? 0
            #expect(layout.pageCount(n) == c["pages"]?.intValue, "\(n) / \(layout.perPage)")
            #expect(layout.pages(Array(0 ..< n)).count == layout.pageCount(n))
        }
        for c in (fixture["colours"]?.arrayValue ?? []).compactMap(\.objectValue) {
            var layout = PrintLayout()
            layout.background = c["background"]?.stringValue
            #expect(layout.textColour == c["colour"]?.stringValue, "\(String(describing: layout.background))")
        }
    }

    @Test func boxesLikePython() throws {
        let fixture = try #require(Fixtures.json("export/print.json").objectValue)
        let pages = (fixture["pages"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(pages.count == 27)
        func close(_ a: [Double]?, _ b: [Double]?) -> Bool {
            guard let a, let b else { return a == nil && b == nil }
            return a.count == b.count && zip(a, b).allSatisfy { abs($0 - $1) <= 1e-6 }
        }
        for p in pages {
            let layout = Self.layout(p["layout"]?.objectValue ?? [:])
            let width = p["width"]?.doubleValue ?? 0
            let captions = (p["captions"]?.arrayValue ?? []).compactMap(\.stringValue)
            let aspects = (p["aspects"]?.arrayValue ?? []).map(\.doubleValue)
            let b = layout.boxes(width: width, height: p["height"]?.doubleValue ?? 0, captions: captions, aspects: aspects,
                                 pages: p["pages"]?.intValue ?? 1)
            let what = "\(layout.page) \(layout.perPage) \(width)"
            #expect(b.titleSize == p["title_px"]?.intValue && b.smallSize == p["small_px"]?.intValue, "\(what)")
            #expect(close(Self.numbers(b.title), Self.box(p["title"])), "\(what)")
            #expect(close(Self.numbers(b.footer), Self.box(p["footer"])), "\(what)")
            let pyCaptions = (p["caption_boxes"]?.arrayValue ?? []).map { Self.box($0) }
            let pySketches = (p["sketch_boxes"]?.arrayValue ?? []).map { Self.box($0) }
            #expect(b.captions.count == pyCaptions.count && b.sketches.count == pySketches.count, "\(what)")
            for (swift, python) in zip(b.captions.map(Self.numbers), pyCaptions) {
                #expect(close(swift, python), "\(what)")
            }
            for (swift, python) in zip(b.sketches.map(Self.numbers), pySketches) {
                #expect(close(swift, python), "\(what)")
            }
        }
    }

    @Test func theLastChoicesUnderTheStudiosKeys() {
        var settings = AppSettings(data: [:], defaultOutputDir: URL(filePath: "/tmp"))
        let fresh = PrintLayout(settings: settings, count: 3)
        #expect(fresh.page == .a4 && !fresh.landscape && fresh.perPage == 6 && fresh.marginMM == 15)
        #expect(fresh.stroke == nil && fresh.background == "#FFFFFF" && fresh.frame == .square && !fresh.captions)
        #expect(PrintLayout(settings: settings, count: 1).perPage == 1)  // (one sketch: one per page)
        settings["export_background"] = "transparent"  // (a page is never transparent)
        settings["export_stroke"] = "#336699"
        settings["export_frame"] = "content"
        var chosen = PrintLayout(settings: settings, count: 3)
        #expect(chosen.background == "#FFFFFF" && chosen.stroke == "#336699" && chosen.frame == .content)
        chosen.page = .letter
        chosen.landscape = true
        chosen.perPage = 4
        chosen.marginMM = 0
        chosen.signature = "J."
        chosen.captions = true
        chosen.remember(in: &settings, count: 3)
        #expect(settings["print_page"] == "letter" && settings["print_landscape"] == true && settings["print_per_page"] == 4)
        #expect(settings["print_margin"] == 0.0 && settings["print_signature"] == "J." && settings["print_captions"] == true)
        let again = PrintLayout(settings: settings, count: 3)
        #expect(again.page == .letter && again.landscape && again.perPage == 4 && again.marginMM == 0)
        #expect(again.signature == "J." && again.captions)
        var single = again
        single.perPage = 1
        single.remember(in: &settings, count: 1)
        #expect(settings["print_per_page"] == 4)  // (a single sketch keeps the contact sheet's number)
        settings["print_page"] = "b5"  // (not in the list: its first entry, as the dialog's combo box)
        settings["print_per_page"] = 5
        settings["print_margin"] = 90
        let odd = PrintLayout(settings: settings, count: 2)
        #expect(odd.page == .a5 && odd.perPage == 1 && odd.marginMM == 60)
    }

    #if canImport(CoreGraphics) && canImport(CoreText)
        static func items() throws -> [PrintItem] {
            let names = ["svg/lines.svg", "svg/cubic.svg", "svg/closed_bg.svg", "edit/odd.svg"]
            return try names.map { PrintItem(svg: String(decoding: try Fixtures.data($0), as: UTF8.self), caption: $0) }
                + [PrintItem(svg: "<nope", caption: "unreadable")]
        }

        /// The pixels darker than 150 (Qt's lightness), every second one.
        static func dark(_ image: CGImage) -> Int {
            let (w, h) = (image.width, image.height)
            var pixels = [UInt8](repeating: 0, count: w * h * 4)
            let space = CGColorSpace(name: CGColorSpace.sRGB)!
            pixels.withUnsafeMutableBytes { raw in
                let context = CGContext(data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                        space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            }
            var n = 0
            for y in stride(from: 0, to: h, by: 2) {
                for x in stride(from: 0, to: w, by: 2) {
                    let i = (y * w + x) * 4
                    let rgb = pixels[i ..< i + 3].map(Int.init)
                    if (rgb.max()! + rgb.min()!) / 2 < 150 { n += 1 }
                }
            }
            return n
        }

        @Test func pdfPagesAndPreview() throws {
            var layout = PrintLayout()
            layout.page = .a5
            layout.perPage = 2
            layout.title = "My <sketches>"
            layout.signature = "J. 2026"
            layout.captions = true
            var progress: [[Int]] = []
            let data = try PrintPages.pdf(try Self.items(), layout: layout, title: "Kamele") { progress.append([$0, $1]) }
            #expect(progress == [[1, 3], [2, 3], [3, 3]])
            let document = try #require(CGPDFDocument(CGDataProvider(data: data as CFData)!))
            #expect(document.numberOfPages == 3)
            let media = try #require(document.page(at: 1)?.getBoxRect(.mediaBox))
            #expect(abs(media.width - 148 / 25.4 * 72) < 0.01 && abs(media.height - 210 / 25.4 * 72) < 0.01)
            let preview = try PrintPages.preview(try Self.items(), layout: layout, width: 200)
            #expect(preview.width == 200 && preview.height == 284)  // (200 × 210 / 148, Python's round)
            #expect(Self.dark(preview) > Self.dark(try PrintPages.preview([], layout: layout, width: 200)) + 12)
            let last = try PrintPages.preview(try Self.items(), layout: layout, width: 200, page: 9)  // (the last page)
            #expect(Self.dark(last) < Self.dark(preview))  // (one unreadable sketch: only its caption)
        }

        @Test func aDarkBackgroundGetsLightWriting() throws {
            var layout = PrintLayout()
            layout.background = "#2C3A33"
            layout.title = "Tafel"
            let image = try PrintPages.preview([], layout: layout, width: 120)
            #expect(Self.dark(image) > 120 * image.height / 4 * 9 / 10)  // (the board covers the page)
            #expect(layout.textColour == "#E8E8E2")
        }

        /// On a paper (the export's, as the studio's print dialog takes it): the paper under every page – the board's
        /// dark green, its writing light – one picture for all pages of the PDF.
        @Test func onPaper() throws {
            var settings = AppSettings(data: [:], defaultOutputDir: URL(filePath: "/tmp"))
            settings["export_paper"] = "blackboard"
            settings["export_background"] = "#2C3A33"  // (as the studio keeps a paper: its colour too)
            var layout = PrintLayout(settings: settings, count: 2)
            #expect(layout.paper == Paper(kind: .blackboard) && layout.textColour == "#E8E8E2")
            layout.background = nil  // (the paper's own colour)
            layout.title = "Tafel"
            let image = try PrintPages.preview(try Self.items(), layout: layout, width: 120)
            #expect(Self.dark(image) > 120 * image.height / 4 * 8 / 10)  // (the board covers the page)
            let paper = try #require(try PrintPages.paper(layout, side: PrintPages.pdfPaperSide(layout)))
            #expect(paper.width == 2400 && paper.height == Int((2400 * 297 / 210.0).rounded()))  // (A4 at 600 dpi: 2400)
            layout.paper = nil
            #expect(try PrintPages.paper(layout, side: 600) == nil)
        }

        @Test func aCancelledPrintStopsBetweenPages() async throws {
            let items = try Self.items()
            let result = await Task {
                withUnsafeCurrentTask { $0?.cancel() }
                return try PrintPages.pdf(items, layout: PrintLayout(), title: "x")
            }.result
            #expect(throws: CancellationError.self) { try result.get() }
        }
    #endif
}
