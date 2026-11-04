import Foundation

/// The print layout (gui/print_layout.py): sketches on pages – A5 … a poster, upright or turned – one per page or many
/// as a contact sheet, with a margin, a heading, a signature and captions, in a stroke colour on a background. The
/// last choices are kept under the studio's keys (print_page, print_landscape, print_margin, print_per_page,
/// print_signature, print_captions), so the Mac app and the studio start from the last print of either.
public struct PrintLayout: Sendable, Equatable {
    public enum Page: String, Sendable, CaseIterable {
        case a5, a4, a3, letter, poster

        /// Width and height upright, in mm (as QPageSize gives them).
        public var mm: (width: Double, height: Double) {
            switch self {
            case .a5: (148, 210)
            case .a4: (210, 297)
            case .a3: (297, 420)
            case .letter: (215.9, 279.4)
            case .poster: (500, 700)
            }
        }
    }

    /// The choices of "per page" (PER_PAGE).
    public static let perPageChoices = [1, 2, 4, 6, 9, 12, 16, 20]
    /// the space between the cells of a contact sheet, in mm
    public static let gapMM = 6.0
    /// (columns, rows) of the choices (GRIDS)
    static let grids: [Int: (Int, Int)] = [1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 12: (3, 4), 16: (4, 4),
                                           20: (4, 5)]

    public var page = Page.a4
    public var landscape = false
    /// the free space around the page's contents, in mm (0 … 60)
    public var marginMM = 15.0
    public var perPage = 1
    /// the heading above the sketches ("": none)
    public var title = ""
    /// written at the foot of the page, on the right ("": none)
    public var signature = ""
    /// the names under the sketches
    public var captions = false
    /// nil: the sketches' own colours
    public var stroke: String?
    public var widthScale = 1.0
    /// nil or "transparent": none
    public var background: String?
    public var frame = SketchFraming.Mode.square
    public var frameMargin = SketchFraming.defaultMargin

    public init() {}

    /// PrintDialog: the last print's choices for `count` sketches (one per page for a single sketch, else the last
    /// number, at first 6), the stroke colour, the background (white instead of none: paper is never transparent)
    /// and the frame of the last export.
    public init(settings: AppSettings, count: Int) {
        // (a value the dialog's lists do not have selects their first entry, as QComboBox.findData gives -1)
        page = Page(rawValue: settings["print_page"]?.stringValue ?? "a4") ?? Page.allCases[0]
        landscape = settings["print_landscape"]?.truthy ?? false
        let perPage = count > 1 ? settings["print_per_page"]?.intValue ?? 6 : 1
        self.perPage = Self.perPageChoices.contains(perPage) ? perPage : Self.perPageChoices[0]
        let margin = settings["print_margin"].map { $0.truthy ? $0.doubleValue ?? $0.stringValue.flatMap(Double.init) ?? 0 : 0 }
        marginMM = min(60, max(0, margin ?? 15))
        signature = settings["print_signature"]?.stringValue ?? ""
        captions = settings["print_captions"]?.truthy ?? false
        let stroke = settings["export_stroke"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 } ?? "#000000"
        self.stroke = stroke.lowercased() == "#000000" ? nil : stroke
        let background = settings["export_background"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 } ?? "#FFFFFF"
        self.background = background == "transparent" ? "#FFFFFF" : background
        frame = SketchFraming.Mode(rawValue: settings["export_frame"]?.stringValue ?? "") ?? .square
    }

    /// PrintDialog._remember: the page's choices kept for the next print (the number per page only from a print of
    /// several sketches).
    public func remember(in settings: inout AppSettings, count: Int) {
        settings["print_page"] = .string(page.rawValue)
        settings["print_landscape"] = .bool(landscape)
        settings["print_margin"] = .double(marginMM)
        settings["print_signature"] = .string(signature)
        settings["print_captions"] = .bool(captions)
        if count > 1 { settings["print_per_page"] = .int(perPage) }
    }

    /// page_mm: width and height of the page in mm (turned for landscape).
    public var pageMM: (width: Double, height: Double) {
        let (w, h) = page.mm
        return landscape ? (max(w, h), min(w, h)) : (min(w, h), max(w, h))
    }

    /// Columns and rows of a page with `perPage` sketches (more columns on a landscape page).
    public static func grid(_ perPage: Int, landscape: Bool = false) -> (cols: Int, rows: Int) {
        let (cols, rows) = grids[perPage] ?? {
            let cols = Int(Double(perPage).squareRoot().rounded(.up))
            return (cols, Int((Double(perPage) / Double(cols)).rounded(.up)))
        }()
        return landscape && rows > cols ? (rows, cols) : (cols, rows)
    }

    public var grid: (cols: Int, rows: Int) { Self.grid(perPage, landscape: landscape) }

    /// The number of pages for `n` sketches.
    public func pageCount(_ n: Int) -> Int {
        n > 0 ? max(1, Int((Double(n) / Double(max(perPage, 1))).rounded(.up))) : 0
    }

    /// The sketches split onto pages, in their order.
    public func pages<Item>(_ items: [Item]) -> [ArraySlice<Item>] {
        let n = max(perPage, 1)
        return stride(from: 0, to: items.count, by: n).map { items[$0 ..< min($0 + n, items.count)] }
    }

    /// text_colour: the heading's, footer's and captions' colour – light on a dark background, else dark grey.
    public var textColour: String {
        let ground = background ?? "#FFFFFF"
        return Self.isDark(ground == "transparent" ? "#FFFFFF" : ground) ? "#E8E8E2" : "#3A3A3A"
    }

    /// paper.is_dark: a colour ("#RRGGBB" or "#RGB", the "#" may be left out) darker than 0.42 in luminance.
    public static func isDark(_ colour: String) -> Bool {
        var hex = colour.trimmingCharacters(in: .whitespacesAndNewlines)
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6 || hex.count == 3, hex.allSatisfy(\.isHexDigit) else { return false }
        if hex.count == 3 { hex = hex.map { "\($0)\($0)" }.joined() }
        let value = Int(hex, radix: 16) ?? 0
        let (r, g, b) = (Double(value >> 16 & 0xFF) / 255, Double(value >> 8 & 0xFF) / 255, Double(value & 0xFF) / 255)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.42
    }
}

/// A rectangle of a page: from the top left, y downwards (as Qt's QRectF).
public struct PageBox: Sendable, Equatable {
    public var x, y, width, height: Double

    public init(_ x: Double, _ y: Double, _ width: Double, _ height: Double) {
        (self.x, self.y, self.width, self.height) = (x, y, width, height)
    }

    public var midX: Double { x + width / 2 }
    public var midY: Double { y + height / 2 }
}

/// Where the parts of a page go (print_layout.PageBoxes), in the units of the page's size: the heading and the
/// footer (signature on the right, the page number on the left) with their font sizes, and per sketch its caption
/// (nil without) and the sketch fitted to its shape (nil when it could not be read).
public struct PageBoxes: Sendable, Equatable {
    public var title: PageBox?
    public var titleSize: Int
    public var footer: PageBox?
    public var smallSize: Int
    public var captions: [PageBox?]
    public var sketches: [PageBox?]
}

public extension PrintLayout {
    /// page_boxes: the page's layout – the margin, the heading on top, the footer below, the grid of cells in between
    /// (a gap between them on a contact sheet), a caption at the foot of a cell and the sketch (`aspects`: width /
    /// height of each) as large as it fits, centred. Sizes are given in mm of the page, so a PDF in points and a
    /// preview in pixels get the same picture.
    func boxes(width: Double, height: Double, captions: [String], aspects: [Double?], pages: Int = 1) -> PageBoxes {
        func round(_ v: Double) -> Int { Int(v.rounded(.toNearestOrEven)) }  // (Python's round)
        let wMM = pageMM.width
        let mm = width / wMM
        let m = marginMM * mm
        var (x, y, w, h) = (m, m, width - m - m, height - m - m)  // (QRectF.adjusted(m, m, -m, -m))
        let titleSize = max(1, round(min(9, wMM / 24) * mm))
        var titleBox: PageBox?
        if !title.isEmpty {
            titleBox = PageBox(x, y, w, Double(titleSize) * 1.6)
            let diff = Double(titleSize) * 1.6 + 3 * mm  // (setTop: the bottom stays)
            (y, h) = (y + diff, h - diff)
        }
        let small = max(1, round(min(4, wMM / 50) * mm))
        var footer: PageBox?
        if !signature.isEmpty || pages > 1 {
            footer = PageBox(x, y + h - Double(small) * 1.8, w, Double(small) * 1.8)
            h = (y + h - Double(small) * 1.8 - 3 * mm) - y  // (setBottom)
        }
        let (cols, rows) = grid
        let gap = perPage > 1 ? Self.gapMM * mm : 0
        let cellW = (w - gap * Double(cols - 1)) / Double(cols)
        let cellH = (h - gap * Double(rows - 1)) / Double(rows)
        var captionBoxes: [PageBox?] = []
        var sketchBoxes: [PageBox?] = []
        for (k, aspect) in aspects.prefix(cols * rows).enumerated() {
            let (c, r) = (k % cols, k / cols)
            let (cx, cy, cw) = (x + Double(c) * (cellW + gap), y + Double(r) * (cellH + gap), cellW)
            var ch = cellH
            var caption: PageBox?
            if self.captions, k < captions.count, !captions[k].isEmpty {
                caption = PageBox(cx, cy + ch - Double(small) * 1.6, cw, Double(small) * 1.6)
                ch = (cy + ch - Double(small) * 1.6 - 1.5 * mm) - cy
            }
            captionBoxes.append(caption)
            guard let aspect else {
                sketchBoxes.append(nil)
                continue
            }
            let sw = min(cw, ch * aspect)
            let sh = sw / aspect
            sketchBoxes.append(PageBox(cx + cw / 2 - sw / 2, cy + ch / 2 - sh / 2, sw, sh))
        }
        return PageBoxes(title: titleBox, titleSize: titleSize, footer: footer, smallSize: small, captions: captionBoxes,
                         sketches: sketchBoxes)
    }
}
