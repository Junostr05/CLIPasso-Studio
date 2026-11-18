import Foundation

/// The user's own presets (gui/user_presets.py): named settings of a method, kept in the app's settings
/// ("user_presets") – the studio's "My presets" and the phone page use them alike. A preset holds every setting of
/// its method (files on the computer, like a start SVG, and hidden settings are left out); one of another method
/// switches the studio to that method.
public enum UserPresets {
    public static let key = "user_presets"
    public static let maxName = 40
    public static let maxPresets = 100

    public struct Preset: Sendable, Hashable {
        public let name: String
        public let method: String
        /// every setting of the method, with "method"
        public let settings: JSONObject

        public var json: JSONValue {
            ["name": .string(name), "method": .string(method), "settings": .object(settings)]
        }
    }

    /// clean_name: the whitespace made single spaces, at most 40 characters; nil when nothing is left.
    public static func cleanName(_ value: JSONValue?) -> String? {
        let text: String = {
            guard let value, value.truthy else { return "" }
            return PhoneStudio.pyStr(value)
        }()
        let words = text.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        let name = String(String.UnicodeScalarView(words.unicodeScalars.prefix(maxName)))
        return name.isEmpty ? nil : name
    }

    /// _clean_settings: settings_schema.normalize (the method's defaults, the known keys coerced) with the paths and
    /// the hidden settings at their defaults; nil where a value cannot be coerced.
    public static func clean(_ settings: JSONObject, schema: ParamSchema) -> JSONObject? {
        let wanted = settings["method"]?.stringValue ?? ""
        let id = schema.methods.contains(wanted) ? wanted : schema.defaultMethod
        guard let method = schema.method(id) else { return nil }
        var out = JSONObject(method.params.map { ($0.key, $0.default) })
        out["method"] = .string(id)
        for p in method.params {
            guard let value = settings[p.key] else { continue }
            guard let coerced = PhoneStudio.coerce(p, value) else { return nil }
            out[p.key] = coerced
        }
        for p in method.params where p.kind == .path || p.hidden {
            out[p.key] = p.default
        }
        return out
    }

    /// all_presets: the presets the settings hold, in the order they were made (damaged ones and those of a method
    /// this app does not know are left out).
    public static func all(_ stored: JSONValue?, schema: ParamSchema) -> [Preset] {
        (stored?.arrayValue ?? []).compactMap { item in
            guard let o = item.objectValue, let settings = o["settings"]?.objectValue,
                  let method = o["method"]?.stringValue, schema.methods.contains(method),
                  let cleaned = clean(settings.merging(["method": .string(method)]), schema: schema),
                  let name = cleanName(o["name"])
            else { return nil }
            return Preset(name: name, method: method, settings: cleaned)
        }
    }

    public static func find(_ name: String, method: String, in stored: JSONValue?, schema: ParamSchema) -> Preset? {
        all(stored, schema: schema).first { $0.name == name && $0.method == method }
    }

    static func store(_ presets: [Preset]) -> JSONValue {
        .array(presets.suffix(maxPresets).map(\.json))
    }

    /// save: `settings` kept under `name` (a preset of the same name and method is replaced in its place); the
    /// presets to keep and the one saved – nil for a name of nothing but spaces or settings that cannot be kept.
    public static func save(_ name: JSONValue, _ settings: JSONObject, in stored: JSONValue?,
                            schema: ParamSchema) -> (stored: JSONValue, saved: Preset)?
    {
        guard let name = cleanName(name), let cleaned = clean(settings, schema: schema),
              let method = cleaned["method"]?.stringValue
        else { return nil }
        let entry = Preset(name: name, method: method, settings: cleaned)
        var presets = all(stored, schema: schema)
        if let i = presets.firstIndex(where: { $0.name == name && $0.method == method }) {
            presets[i] = entry
        } else {
            presets.append(entry)
        }
        return (store(presets), entry)
    }

    /// delete: the presets to keep – nil when there was no such preset.
    public static func delete(_ name: String, method: String, in stored: JSONValue?, schema: ParamSchema) -> JSONValue? {
        let presets = all(stored, schema: schema)
        let kept = presets.filter { !($0.name == name && $0.method == method) }
        return kept.count == presets.count ? nil : store(kept)
    }

    /// matching: the own preset the settings are equal to ("" when none).
    public static func matching(_ settings: JSONObject, in stored: JSONValue?, schema: ParamSchema) -> String {
        guard let cleaned = clean(settings, schema: schema), let method = cleaned["method"]?.stringValue else {
            return ""
        }
        return all(stored, schema: schema).first { $0.method == method && $0.settings == cleaned }?.name ?? ""
    }
}
