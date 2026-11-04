import Foundation

/// The SVG export of a sketch as the studio makes it (gui/export.restyle_svg): every `<path>` in one stroke colour,
/// its width times a factor (written as Python's `f"{w:.4g}"`), and a background behind it – a `<rect data-bg="1">`
/// as the first element (an earlier one of those is removed first). The rest of the file stays as it is.
public enum SketchExport {
    public static func restyleSVG(_ svg: String, strokeColor: String? = nil, widthScale: Double = 1.0,
                                  background: String? = nil) -> String
    {
        var out = ""
        out.reserveCapacity(svg.utf8.count + 128)
        var depth = 0
        var skipping: Int?  // the depth of a removed element that has content
        var index = svg.startIndex
        func copy(until end: String) {
            let rest = svg[index...]
            let stop = rest.range(of: end).map(\.upperBound) ?? svg.endIndex
            if skipping == nil { out += svg[index..<stop] }
            index = stop
        }
        while index < svg.endIndex {
            guard let open = svg[index...].firstIndex(of: "<") else {
                if skipping == nil { out += svg[index...] }
                break
            }
            if skipping == nil { out += svg[index..<open] }
            index = open
            let rest = svg[index...]
            if rest.hasPrefix("<!--") { copy(until: "-->"); continue }
            if rest.hasPrefix("<?") { copy(until: "?>"); continue }
            if rest.hasPrefix("<![CDATA[") { copy(until: "]]>"); continue }
            if rest.hasPrefix("<!") { copy(until: ">"); continue }
            let close = tagEnd(svg, from: index)
            let tag = String(svg[index..<close])
            index = close
            if tag.hasPrefix("</") {
                depth -= 1
                if let level = skipping {
                    if depth == level { skipping = nil }
                    continue
                }
                out += tag
                continue
            }
            let empty = tag.hasSuffix("/>")
            var element = StartTag(tag)
            if skipping != nil {
                if !empty { depth += 1 }
                continue
            }
            if depth == 1, element.name == "rect", element.value("data-bg") == "1" {
                if !empty { skipping = depth; depth += 1 }
                continue
            }
            if element.name == "path" {
                if let strokeColor { element.set("stroke", strokeColor) }
                if widthScale != 1.0, let w = Double((element.value("stroke-width") ?? "1")
                    .trimmingCharacters(in: .whitespaces))
                {
                    element.set("stroke-width", pythonG4(w * widthScale))
                }
                out += element.text
            } else {
                out += tag
            }
            if depth == 0, element.name == "svg", let background {
                let box = canvasBox(viewBox: element.value("viewBox"), width: element.value("width"),
                                    height: element.value("height"))
                out += "<rect \(box) fill=\"\(escape(background))\" data-bg=\"1\" />"
            }
            if !empty { depth += 1 }
        }
        return out
    }

    /// The attributes that make the background as big as the whole canvas (export._canvas_box): x, y, width and
    /// height of the viewBox, else of the width and height – Qt's SVG renderer reads width="100%" on a rect as 100
    /// user units, so the studio gives numbers; "100%" only when there are none.
    static func canvasBox(viewBox: String?, width: String?, height: String?) -> String {
        let parts = (viewBox ?? "").replacingOccurrences(of: ",", with: " ").split(whereSeparator: \.isWhitespace)
        var box = parts.count == 4 ? parts.compactMap { Double($0) } : []
        if box.count != 4, let w = width.flatMap({ Double($0) }), let h = height.flatMap({ Double($0) }) {
            box = [0, 0, w, h]
        }
        guard box.count == 4 else { return "width=\"100%\" height=\"100%\"" }
        let g = box.map { pythonG($0) }
        return "x=\"\(g[0])\" y=\"\(g[1])\" width=\"\(g[2])\" height=\"\(g[3])\""
    }

    /// Python's `f"{value:g}"`.
    static func pythonG(_ value: Double) -> String {
        if value.isNaN { return "nan" }
        if value.isInfinite { return value < 0 ? "-inf" : "inf" }
        return String(format: "%g", value)
    }

    /// Python's `f"{value:.4g}"`.
    static func pythonG4(_ value: Double) -> String {
        if value.isNaN { return "nan" }
        if value.isInfinite { return value < 0 ? "-inf" : "inf" }
        return String(format: "%.4g", value)
    }

    static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }

    /// The index after the `>` that ends the tag at `start` (quotes respected).
    static func tagEnd(_ text: String, from start: String.Index) -> String.Index {
        var quote: Character?
        var i = text.index(after: start)
        while i < text.endIndex {
            let c = text[i]
            if let q = quote {
                if c == q { quote = nil }
            } else if c == "\"" || c == "'" {
                quote = c
            } else if c == ">" {
                return text.index(after: i)
            }
            i = text.index(after: i)
        }
        return text.endIndex
    }

    /// A start tag with its attributes as written (quotes and spacing kept); changed ones are set in place, new ones
    /// added at the end (as ElementTree's `set` does).
    struct StartTag {
        struct Attribute {
            var name: String
            var raw: String  // the value as written (still escaped)
            var quote: Character
        }

        var name = ""
        private var head = ""  // "<name" and the spacing up to the first attribute
        private var parts: [(space: String, attribute: Attribute)] = []
        private var tail = ""  // spacing and ">" or "/>"
        private var changed = false
        private let original: String

        init(_ tag: String) {
            original = tag
            let chars = Array(tag)
            var i = 1
            while i < chars.count, !chars[i].isWhitespace, chars[i] != ">", chars[i] != "/" { i += 1 }
            name = String(chars[1..<i])
            if let colon = name.lastIndex(of: ":") { name = String(name[name.index(after: colon)...]) }
            head = String(chars[0..<i])
            while i < chars.count {
                var j = i
                while j < chars.count, chars[j].isWhitespace { j += 1 }
                let space = String(chars[i..<j])
                guard j < chars.count, chars[j] != ">", chars[j] != "/" else {
                    tail = String(chars[i...])
                    return
                }
                var k = j
                while k < chars.count, chars[k] != "=", !chars[k].isWhitespace, chars[k] != ">" { k += 1 }
                let attrName = String(chars[j..<k])
                while k < chars.count, chars[k].isWhitespace || chars[k] == "=" { k += 1 }
                guard k < chars.count, chars[k] == "\"" || chars[k] == "'" else {
                    tail = String(chars[i...])  // (not well-formed: kept as it is)
                    return
                }
                let quote = chars[k]
                var m = k + 1
                while m < chars.count, chars[m] != quote { m += 1 }
                parts.append((space, Attribute(name: attrName, raw: String(chars[(k + 1)..<min(m, chars.count)]),
                                               quote: quote)))
                i = min(m + 1, chars.count)
            }
        }

        /// The tag's name as written, with its namespace prefix ("svg:path").
        var qualifiedName: String { String(head.dropFirst()) }

        func value(_ key: String) -> String? {
            parts.first { $0.attribute.name == key }.map { unescape($0.attribute.raw) }
        }

        /// ElementTree's `attrib.pop(key, None)`.
        mutating func remove(_ key: String) {
            guard let at = parts.firstIndex(where: { $0.attribute.name == key }) else { return }
            parts.remove(at: at)
            changed = true
        }

        mutating func set(_ key: String, _ value: String) {
            changed = true
            if let at = parts.firstIndex(where: { $0.attribute.name == key }) {
                parts[at].attribute.raw = SketchExport.escape(value)
                parts[at].attribute.quote = "\""
            } else {
                parts.append((" ", Attribute(name: key, raw: SketchExport.escape(value), quote: "\"")))
            }
        }

        var text: String {
            guard changed else { return original }
            var out = head
            for (space, a) in parts {
                out += "\(space)\(a.name)=\(a.quote)\(a.raw)\(a.quote)"
            }
            return out + tail
        }

        private func unescape(_ raw: String) -> String {
            raw.replacingOccurrences(of: "&quot;", with: "\"").replacingOccurrences(of: "&apos;", with: "'")
                .replacingOccurrences(of: "&lt;", with: "<").replacingOccurrences(of: "&gt;", with: ">")
                .replacingOccurrences(of: "&amp;", with: "&")
        }
    }
}
