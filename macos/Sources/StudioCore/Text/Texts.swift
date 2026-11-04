import Foundation

/// The interface texts in German and English – the studio's own (clipasso_studio/resources/i18n/de.json, en.json),
/// read as gui/i18n.py reads them: a key missing in the language falls back to English, then to the key itself;
/// placeholders are filled like Python's `str.format` (a text with a placeholder that is not given stays as it is).
public struct Texts: Sendable {
    public static let languages = ["de", "en"]
    /// Each language in its own words (gui/i18n.py LANGUAGES).
    public static let names = ["de": "Deutsch", "en": "English"]
    public let language: String
    private let table: [String: String]
    private let english: [String: String]

    public struct LoadError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    public init(directory: URL, language: String) throws {
        func load(_ code: String) throws -> [String: String] {
            let url = directory.appending(path: "\(code).json")
            guard let object = try PyJSON.parse(Data(contentsOf: url)).objectValue else {
                throw LoadError(description: "\(url.path) is not a text table")
            }
            var out: [String: String] = [:]
            for (key, value) in object {
                out[key] = value.stringValue
            }
            return out
        }
        let code = Self.languages.contains(language) ? language : "en"
        self.language = code
        english = try load("en")
        table = code == "en" ? english : try load(code)
    }

    /// The setting ("auto", "de", "en") → the language: "auto" (or anything unknown) is the first supported language of
    /// the system's preferred ones, else English (i18n.resolve / system_language).
    public static func resolve(_ setting: String, preferred: [String] = Locale.preferredLanguages) -> String {
        if languages.contains(setting) { return setting }
        for tag in preferred {
            let code = tag.replacingOccurrences(of: "_", with: "-").split(separator: "-").first.map { $0.lowercased() }
            if let code, languages.contains(code) { return code }
        }
        return "en"
    }

    public func has(_ key: String) -> Bool {
        table[key] != nil || english[key] != nil
    }

    public func tr(_ key: String, _ params: [String: String] = [:]) -> String {
        let text = table[key] ?? english[key] ?? key
        return params.isEmpty ? text : format(text, params)
    }

    /// Python's `text.format(**params)` for `{name}` placeholders and `{{` / `}}`; on a missing name the text as it is.
    public func format(_ text: String, _ params: [String: String]) -> String {
        var out = ""
        var i = text.startIndex
        while i < text.endIndex {
            let c = text[i]
            let next = text.index(after: i)
            if c == "{", next < text.endIndex, text[next] == "{" {
                out.append("{")
                i = text.index(after: next)
            } else if c == "}", next < text.endIndex, text[next] == "}" {
                out.append("}")
                i = text.index(after: next)
            } else if c == "{" {
                guard let close = text[next...].firstIndex(of: "}") else { return text }
                guard let value = params[String(text[next..<close])] else { return text }
                out += value
                i = text.index(after: close)
            } else {
                out.append(c)
                i = next
            }
        }
        return out
    }

    /// i18n.number: `decimals` places with the language's decimal mark ("29,4" in German).
    public func number(_ value: Double, decimals: Int = 1) -> String {
        let text = String(format: "%.\(decimals)f", value)
        return language == "de" ? text.replacingOccurrences(of: ".", with: ",") : text
    }

    /// i18n.size: "650 MB", "1,2 GB".
    public func size(_ mb: Double) -> String {
        mb >= 1000 ? "\(number(mb / 1000)) GB" : String(format: "%.0f MB", mb)
    }
}
