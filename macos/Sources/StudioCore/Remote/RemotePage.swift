import Foundation

/// The phone page and what it needs, as gui/remote.py serves them: the page (resources/phone/index.html) with its
/// language, its data – JSON the script reads, so nothing runs inline –, the studio's icons inline and the colours of
/// the browser's bar; the PIN page; the studio's design tokens as CSS; the manifest for the home screen.
public struct RemotePage: Sendable {
    /// the studio's resources/phone folder and its icons folder (Lucide SVGs)
    public let phoneDir: URL
    public let iconsDir: URL
    /// the app's version (in the page's data and tokens.css)
    public let version: String

    public init(phoneDir: URL, iconsDir: URL, version: String) {
        (self.phoneDir, self.iconsDir, self.version) = (phoneDir, iconsDir, version)
    }

    public struct MissingFile: Error, CustomStringConvertible {
        public let description: String
    }

    func resource(_ name: String) throws -> String {
        guard let text = try? String(contentsOf: phoneDir.appending(path: name), encoding: .utf8) else {
            throw MissingFile(description: "no \(name) in \(phoneDir.path)")
        }
        return text
    }

    /// page(texts, access): the phone page with its texts and the access code.
    public func page(texts: JSONObject, token: String) throws -> String {
        let lang = texts["lang"]?.stringValue ?? "en"
        let config: JSONObject = ["token": .string(token), "texts": .object(texts), "lang": .string(lang),
                                  "version": .string(version)]
        return try fill(resource("index.html"), lang: lang, config: config)
    }

    /// login_page: the page for the PIN (no access code in it).
    public func login(texts: JSONObject) throws -> String {
        let lang = texts["lang"]?.stringValue ?? "en"
        return try fill(resource("login.html"), lang: lang, config: ["texts": .object(texts), "lang": .string(lang)])
    }

    /// _fill: the page's language, its data (json.dumps, with <, > and & escaped), its icons, the bar's colours.
    func fill(_ body: String, lang: String, config: JSONObject) throws -> String {
        let data = PyJSON.dump(.object(config), asciiOnly: true)
            .replacingOccurrences(of: "<", with: "\\u003c").replacingOccurrences(of: ">", with: "\\u003e")
            .replacingOccurrences(of: "&", with: "\\u0026")
        var out = ""
        var rest = Substring(body)
        while let start = rest.range(of: "{{icon:") {  // (_ICON: {{icon:name}}, the name of a-z, 0-9 and -)
            out += rest[..<start.lowerBound]
            let after = rest[start.upperBound...]
            let name = after.prefix { $0.isASCII && ($0.isLowercase || $0.isNumber || $0 == "-") }
            if !name.isEmpty, after.dropFirst(name.count).hasPrefix("}}") {
                out += try icon(String(name))
                rest = after.dropFirst(name.count + 2)
            } else {
                out += rest[start]
                rest = after
            }
        }
        out += rest
        return out.replacingOccurrences(of: "{{colour:light}}", with: Palette.light.chrome)
            .replacingOccurrences(of: "{{colour:dark}}", with: Palette.dark.chrome)
            .replacingOccurrences(of: "{{lang}}", with: Self.escapeHTML(lang))
            .replacingOccurrences(of: "{{config}}", with: data)
    }

    /// icon_svg: a Lucide icon inline – without its licence comment and its class, as class "icon", hidden from
    /// screen readers, its white space collapsed.
    public func icon(_ name: String) throws -> String {
        guard var svg = try? String(contentsOf: iconsDir.appending(path: "\(name).svg"), encoding: .utf8),
              let start = svg.range(of: "<svg")
        else { throw MissingFile(description: "no icon \(name)") }
        svg = String(svg[start.lowerBound...])
        if let cls = svg.range(of: #"\s*class="[^"]*""#, options: .regularExpression) { svg.removeSubrange(cls) }
        if let tag = svg.range(of: "<svg") {
            svg.replaceSubrange(tag, with: #"<svg class="icon" aria-hidden="true" focusable="false""#)
        }
        svg = svg.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        svg = svg.replacingOccurrences(of: #">\s+<"#, with: "><", options: .regularExpression)
        return svg.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// theme.tokens_css: the radii and the palettes as CSS variables – light, and dark when the browser asks for it
    /// (unless the page is set to light) or the page is set to dark.
    public func tokensCSS() -> String {
        let radii: [(String, Double)] = [("r-progress", Radius.progress), ("r-segment", Radius.segment),
                                         ("r-control", Radius.control), ("r-bar", Radius.bar),
                                         ("r-card", Radius.card), ("r-large", Radius.large),
                                         ("r-float", Radius.float)]
        func block(_ p: Palette) -> String {
            var lines = PhoneColours.all(p).map { "  --\($0.css): \($0.colour);" }
            lines += ["  --scrim: \(Self.rgba(Palette.dark.chrome, PhoneColours.scrimAlpha));",
                      "  --on-scrim: \(Palette.dark.text);", "  color-scheme: \(p.name);"]
            return lines.joined(separator: "\n")
        }
        let shared = radii.map { "  --\($0.0): \(Int($0.1))px;" }.joined(separator: "\n")
        return "/* CLIPasso Studio \(version) – the studio's design tokens (gui/theme.py, tokens_css) */\n"
            + ":root {\n\(shared)\n\(block(.light))\n}\n"
            + "@media (prefers-color-scheme: dark) {\n:root:not([data-theme=light]) {\n\(block(.dark))\n}\n}\n"
            + ":root[data-theme=dark] {\n\(block(.dark))\n}\n"
    }

    /// manifest: so the page can be put on the home screen like an app.
    public func manifest() -> Data {
        let value: JSONObject = [
            "name": "CLIPasso Studio", "short_name": "CLIPasso", "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": .string(Palette.dark.bg),
            "theme_color": .string(Palette.dark.chrome),
            "icons": [["src": "/icon.png", "sizes": "256x256", "type": "image/png"]],
        ]
        return Data(PyJSON.dump(.object(value), asciiOnly: true).utf8)
    }

    /// _rgba
    static func rgba(_ colour: String, _ alpha: String) -> String {
        let h = Array(colour.drop { $0 == "#" })
        func byte(_ i: Int) -> Int { Int(String(h[i ..< i + 2]), radix: 16) ?? 0 }
        return "rgba(\(byte(0)), \(byte(2)), \(byte(4)), \(alpha))"
    }

    /// html.escape (quote=True)
    static func escapeHTML(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#x27;")
    }
}
