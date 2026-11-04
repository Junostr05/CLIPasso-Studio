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
                out += "<rect width=\"100%\" height=\"100%\" fill=\"\(escape(background))\" data-bg=\"1\" />"
            }
            if !empty { depth += 1 }
        }
        return out
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
    private static func tagEnd(_ text: String, from start: String.Index) -> String.Index {
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
    private struct StartTag {
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

        func value(_ key: String) -> String? {
            parts.first { $0.attribute.name == key }.map { unescape($0.attribute.raw) }
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
