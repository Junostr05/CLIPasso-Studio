import Foundation

/// The studio's other formats of a sketch (gui/export.py, gui/scene_layers.py), written as text as Python writes them:
/// one path in one layer for plotters and cutters, a SceneSketch cell in two layers, the SVG that draws itself in a
/// browser and its web page, Lottie, and the overview sheet of a SceneSketch matrix.
public enum SketchFormats {
    static let inkscape = "http://www.inkscape.org/namespaces/inkscape"

    // ------------------------------------------------------------------------------------------- plotter

    /// single_layer_svg: every stroke as a sub-path of one path in one layer ("Strokes"), no background – plotter
    /// and cutter software (Cricut, Silhouette, laser tools) imports it as one layer.
    public static func singleLayer(_ svg: String, strokeColor: String? = nil, widthScale: Double = 1) -> String {
        let elements = SketchEditing.elements(svg)
        let root = elements.first?.tag
        var ds: [String] = []
        var widths: [Double] = []
        for element in elements where element.tag.name == "path" {
            let d = (element.tag.value("d") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !d.isEmpty else { continue }
            ds.append(d)
            if let w = Double((element.tag.value("stroke-width") ?? "1").trimmingCharacters(in: .whitespaces)) {
                widths.append(w)
            }
        }
        let width = (widths.isEmpty ? 1 : widths.sorted()[widths.count / 2]) * widthScale
        let w = root?.value("width") ?? "224", h = root?.value("height") ?? "224"
        let view = root?.value("viewBox").flatMap { $0.isEmpty ? nil : $0 } ?? "0 0 \(w) \(h)"
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="\(inkscape)" version="1.1" \
        width="\(w)" height="\(h)" viewBox="\(view)">
          <g id="strokes" inkscape:groupmode="layer" inkscape:label="Strokes">
            <path d="\(ds.joined(separator: " "))" fill="none" stroke="\(strokeColor ?? "#000000")" \
        stroke-width="\(SketchExport.pythonG4(width))" stroke-linecap="round" stroke-linejoin="round"/>
          </g>
        </svg>

        """
    }

    // -------------------------------------------------------------------------------------------- layers

    /// scene_layers.object_strokes: the d of every object stroke of a SceneSketch cell (object.svg), nil when it has
    /// no object layer.
    public static func objectStrokes(runDir: URL?) -> Set<String>? {
        guard let runDir, let text = try? String(contentsOf: runDir.appending(path: "object.svg"), encoding: .utf8)
        else { return nil }
        let ds = Set(SketchEditing.elements(text).filter { $0.tag.name == "path" }
            .map { ($0.tag.value("d") ?? "").trimmingCharacters(in: .whitespacesAndNewlines) }).subtracting([""])
        return ds.isEmpty ? nil : ds
    }

    /// scene_layers.layered: the strokes in two layers (groups Inkscape and Illustrator open as layers), the
    /// background below the object; without an object layer every stroke is in the background layer.
    public static func layered(_ svg: String, objects: Set<String>?,
                               labels: (background: String, object: String) = ("Background", "Object")) -> String
    {
        let elements = SketchEditing.elements(svg)
        guard let root = elements.first else { return svg }
        let paths = elements.filter { $0.tag.name == "path" }
        var groups = (background: "", object: "")
        for p in paths {
            let text = String(svg[p.start ..< p.end])
            if objects?.contains((p.tag.value("d") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)) == true {
                groups.object += text
            } else {
                groups.background += text
            }
        }
        func group(_ id: String, _ label: String, _ body: String) -> String {
            #"<g id="\#(id)" inkscape:groupmode="layer" inkscape:label="\#(SketchExport.escape(label))">\#(body)</g>"#
        }
        let layers = group("background", labels.background, groups.background) + group("object", labels.object, groups.object)
        // the paths go; the layers stand where the first one stood (or at the end of the root)
        let at = paths.first?.start ?? root.closeStart ?? svg.endIndex
        var out = ""
        var index = root.tagEnd
        var tag = root.tag
        if tag.value("xmlns:inkscape") == nil { tag.set("xmlns:inkscape", inkscape) }
        out += String(svg[svg.startIndex ..< root.start]) + tag.text
        for p in paths {
            out += String(svg[index ..< p.start])
            if p.start == at { out += layers }
            index = p.end
        }
        if paths.isEmpty {
            out += String(svg[index ..< at]) + layers
            index = at
        }
        return out + String(svg[index...])
    }

    // --------------------------------------------------------------------------------- animated SVG

    /// animated_svg: an SVG that draws itself in a browser (CSS, repeating) – every stroke uncovered by a mask whose
    /// centre line grows along it, drawn in the brush style; the background colour or the paper below.
    public static func animatedSVG(_ svg: String, length: Double? = nil, hold: Double = 1, strokeColor: String? = nil,
                                   widthScale: Double = 1, background: String? = nil, keepOrder: Bool = false,
                                   paper: Paper? = nil, stylist: Stylist = .plain) throws -> String
    {
        let drawing = Drawing(svg: svg, keepOrder: keepOrder)
        let n = drawing.strokeCount
        let length = length.map { max($0, 0.1) } ?? SketchAnimation.defaultDrawingLength(strokes: n, line: drawing.line)
        let cycle = length + max(hold, 0)
        // (each stroke on its own in the style – all of them in one request)
        let ones = try stylist((0 ..< n).map {
            SketchExport.restyleSVG(drawing.head + drawing.strokes[$0].xml + "</svg>", strokeColor: strokeColor,
                                    widthScale: widthScale)
        })
        var css = "", defs = "", body = ""
        for i in 0 ..< n {
            let stroke = drawing.strokes[i]
            let one = ones[i]
            let styled = SketchEditing.elements(one).filter { $0.parent == 0 && $0.tag.name != "rect" }
                .map { String(one[$0.start ..< $0.end]) }.joined()
            let (a, b) = drawing.spans[i]
            let start = a / drawing.total * length / cycle * 100, end = b / drawing.total * length / cycle * 100
            let s = String(format: "%.3f", start), e = String(format: "%.3f", end), c = String(format: "%.3f", cycle)
            css += "@keyframes d\(i){0%,\(s)%{stroke-dashoffset:1}\(e)%,100%{stroke-dashoffset:0}}"
                + ".d\(i){animation:d\(i) \(c)s linear infinite}"
            let width = (Python.float(stroke.attributes.first { $0.name == "stroke-width" }?.value ?? "1") ?? 1)
                * widthScale
            defs += #"<mask id="m\#(i)" maskUnits="userSpaceOnUse"><path class="d\#(i)" d="\#(drawing.centreline(i))" "#
                + ##"fill="none" stroke="#fff" stroke-width="\##(String(format: "%.3g", 4 * width + 2))" "##
                + #"stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1 1" "#
                + #"stroke-dashoffset="1"/></mask>"#
            body += #"<g mask="url(#m\#(i))">\#(styled)</g>"#
        }
        let ground = background.map { #"<rect width="100%" height="100%" fill="\#($0)"/>"# } ?? ""
        var out = drawing.head + "<style>" + css + "</style><defs>" + defs + "</defs>" + ground + body + "</svg>"
        out = out.replacingOccurrences(of: #" xmlns(:ns\d+)?="http://www.w3.org/2000/svg""#, with: "",
                                       options: .regularExpression)
        if let first = out.range(of: "<svg ") {
            out.replaceSubrange(first, with: #"<svg xmlns="http://www.w3.org/2000/svg" "#)
        }
        #if canImport(ImageIO)
            return PaperPicture.svgWithPaper(out, paper: paper, background: background)
        #else
            return out
        #endif
    }

    /// web_page: a page of its own (no other files) that shows an SVG drawing itself, with a button to draw it again.
    public static func webPage(_ animated: String, title: String = "Sketch", background: String? = nil) -> String {
        let bg = background.flatMap { qColor($0) }.map { String(format: "#%02x%02x%02x", $0.r, $0.g, $0.b) }
            ?? "#ffffff"
        let (fg, button) = Paper.isDark(bg) ? ("#e8e8e8", "rgba(255,255,255,.12)") : ("#333333", "rgba(0,0,0,.06)")
        let svg = animated.replacingOccurrences(of: #"<\?xml[^>]*\?>"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let escaped = title.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#x27;")
        return """
        <!doctype html>
        <html lang="en">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>\(escaped)</title>
        <style>
        html, body { margin: 0; height: 100%; background: \(bg); color: \(fg); font-family: system-ui, sans-serif; }
        body { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
        main { width: min(92vw, 86vh); }
        main svg { display: block; width: 100%; height: auto; }
        button { border: 0; border-radius: 999px; padding: 8px 18px; background: \(button); color: inherit; font: inherit;
                 cursor: pointer; }
        </style>
        </head>
        <body>
        <main>\(svg)</main>
        <button type="button" onclick="const s = document.querySelector('main svg'); s.replaceWith(s.cloneNode(true));"
         title="Draw again">&#8635;</button>
        </body>
        </html>

        """
    }

    // ---------------------------------------------------------------------------------------- matrix

    /// The value of `name="…"` in a start tag (its first match, as Python's re.search).
    static func attribute(_ name: String, in tag: String, pattern: String) -> String? {
        guard let found = tag.range(of: "\(name)=\"\(pattern)", options: .regularExpression) else { return nil }
        return String(tag[found].dropFirst(name.count + 2)).replacingOccurrences(of: "\"", with: "")
    }

    /// _nested_svg: an SVG document as a nested <svg> element at (x, y) of the given size.
    static func nested(_ svg: String, x: Double, y: Double, size: Double) -> String {
        let text = svg.replacingOccurrences(of: #"<\?xml[^>]*\?>"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let head = text.range(of: #"^<svg\b[^>]*>"#, options: .regularExpression) else { return "" }
        let start = String(text[head])
        let box: String
        if let view = attribute("viewBox", in: start, pattern: #"[^"]+"#) {
            box = view
        } else {
            let w = attribute("width", in: start, pattern: #"[\d.]+"#) ?? "224"
            let h = attribute("height", in: start, pattern: #"[\d.]+"#) ?? "224"
            box = "0 0 \(w) \(h)"
        }
        let end = text.range(of: "</svg>", options: .backwards)?.lowerBound ?? text.index(before: text.endIndex)
        let inner = head.upperBound <= end ? text[head.upperBound ..< end] : ""
        let g = SketchExport.pythonG
        return #"<svg x="\#(g(x))" y="\#(g(y))" width="\#(g(size))" height="\#(g(size))" viewBox="\#(box)">"#
            + inner + "</svg>"
    }

    /// matrix_sheet_svg: the overview of a SceneSketch matrix – one column per fidelity layer, one row per
    /// simplicity level (the cells computed, in their order).
    public static func matrixSheet(_ cells: [(cell: Int, svg: String)], cell: Int = 224, gap: Int = 16,
                                   textColor: String = "#555555", background: String? = "#FFFFFF") -> String
    {
        let layers = Set(cells.map { $0.cell / 100 }).sorted(), levels = Set(cells.map { $0.cell % 100 }).sorted()
        let (side, head) = (70, 34)
        let width = side + layers.count * (cell + gap) + gap, height = head + levels.count * (cell + gap) + gap
        var parts = [#"<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="\#(width)" height="\#(height)" "#
            + #"viewBox="0 0 \#(width) \#(height)">"#]
        if let background { parts.append(#"<rect width="100%" height="100%" fill="\#(background)"/>"#) }
        let font = #"font-family="sans-serif" font-size="16" fill="\#(textColor)""#
        let g = SketchExport.pythonG
        for (col, layer) in layers.enumerated() {
            let x = side + gap + col * (cell + gap)
            parts.append(#"<text x="\#(g(Double(x) + Double(cell) / 2))" y="\#(head - 10)" text-anchor="middle" "#
                + #"\#(font)>L\#(layer)</text>"#)
        }
        for (row, level) in levels.enumerated() {
            let y = head + gap + row * (cell + gap)
            parts.append(#"<text x="\#(side - 8)" y="\#(g(Double(y) + Double(cell) / 2 + 6))" text-anchor="end" "#
                + #"\#(font)>\#(level)</text>"#)
        }
        for (c, svg) in cells {
            let col = layers.firstIndex(of: c / 100) ?? 0, row = levels.firstIndex(of: c % 100) ?? 0
            parts.append(nested(svg, x: Double(side + gap + col * (cell + gap)), y: Double(head + gap + row * (cell + gap)),
                                size: Double(cell)))
        }
        parts.append("</svg>")
        return parts.joined(separator: "\n")
    }
}
