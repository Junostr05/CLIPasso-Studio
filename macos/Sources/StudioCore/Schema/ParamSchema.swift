import Foundation

/// Every parameter of the four methods, their rules, groups and presets – read from schema.json, which the Python
/// side exports from settings_schema.py (`python -m clipasso_studio.headless --export-schema`). Nothing of it is
/// written down a second time in Swift.
public struct ParamSchema: Sendable {
    public let format: Int
    public let methods: [String]
    public let defaultMethod: String
    public let devices: [String]
    private let byID: [String: MethodSchema]

    public struct FormatError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    public static func load(_ url: URL) throws -> ParamSchema {
        try ParamSchema(json: PyJSON.parse(Data(contentsOf: url)))
    }

    public init(json: JSONValue) throws {
        guard let o = json.objectValue, o["format"]?.intValue == 1 else {
            throw FormatError(description: "not a schema of format 1")
        }
        format = 1
        methods = o["methods"]?.arrayValue?.compactMap(\.stringValue) ?? []
        defaultMethod = o["default_method"]?.stringValue ?? methods.first ?? ""
        devices = o["devices"]?.arrayValue?.compactMap(\.stringValue) ?? []
        var byID: [String: MethodSchema] = [:]
        for id in methods {
            guard let m = o["method"]?.objectValue?[id]?.objectValue else {
                throw FormatError(description: "the method \(id) is missing")
            }
            byID[id] = try MethodSchema(id: id, json: m)
        }
        self.byID = byID
    }

    public func method(_ id: String) -> MethodSchema? {
        byID[id]
    }
}

/// How many strokes a job's sketches have (settings_schema.num_strokes): `fixed`, 1 with `oneLine` on, or the value
/// of `key`.
public struct StrokesRule: Sendable, Hashable {
    public let key: String?
    public let fixed: Int?
    public let oneLine: String?
}

public struct ParamText: Sendable, Hashable {
    public let label: String
    public let help: String?
    /// choice value (as text) → text key
    public let choices: [String: String]
}

public struct Param: Sendable, Identifiable, Hashable {
    public enum Kind: String, Sendable {
        case int, float, bool, choice, text, path, layers, flags
    }

    public var id: String { key }
    public let key: String
    public let kind: Kind
    public let `default`: JSONValue
    public let group: String
    public let cli: String?
    public let minimum: Double?
    public let maximum: Double?
    public let step: Double?
    public let decimals: Int
    public let choices: [JSONValue]
    public let advanced: Bool
    public let hidden: Bool
    public let enabledIf: Condition?
    public let text: ParamText

    init(json o: JSONObject) throws {
        guard let key = o["key"]?.stringValue, let kindName = o["kind"]?.stringValue,
              let kind = Kind(rawValue: kindName)
        else { throw ParamSchema.FormatError(description: "a parameter without key or kind") }
        self.key = key
        self.kind = kind
        self.default = o["default"] ?? .null
        group = o["group"]?.stringValue ?? ""
        cli = o["cli"]?.stringValue
        minimum = o["min"]?.doubleValue
        maximum = o["max"]?.doubleValue
        step = o["step"]?.doubleValue
        decimals = o["decimals"]?.intValue ?? 2
        choices = o["choices"]?.arrayValue ?? []
        advanced = o["advanced"]?.boolValue ?? true
        hidden = o["hidden"]?.boolValue ?? false
        if let rule = o["enabled_if"], !rule.isNull {
            enabledIf = try Condition(json: rule)
        } else {
            enabledIf = nil
        }
        let t = o["text"]?.objectValue ?? [:]
        var choiceText: [String: String] = [:]
        for (value, textKey) in t["choices"]?.objectValue ?? [:] {
            choiceText[value] = textKey.stringValue
        }
        text = ParamText(label: t["label"]?.stringValue ?? key, help: t["help"]?.stringValue, choices: choiceText)
    }
}

public struct MethodSchema: Sendable {
    public let id: String
    public let name: String
    public let icon: String
    /// tagline / desc / speed → text key
    public let text: [String: String]
    public let groups: [String]
    public let groupText: [String: String]
    public let presets: [String: JSONObject]
    public let presetOrder: [String]
    public let presetText: [String: String]
    public let defaults: JSONObject
    public let params: [Param]
    public let strokes: StrokesRule
    private let byKey: [String: Int]

    init(id: String, json o: JSONObject) throws {
        self.id = id
        name = o["name"]?.stringValue ?? id
        icon = o["icon"]?.stringValue ?? ""
        text = Self.texts(o["text"])
        groups = o["groups"]?.arrayValue?.compactMap(\.stringValue) ?? []
        groupText = Self.texts(o["group_text"])
        var presets: [String: JSONObject] = [:]
        for (name, values) in o["presets"]?.objectValue ?? [:] {
            presets[name] = values.objectValue ?? [:]
        }
        self.presets = presets
        presetOrder = o["preset_order"]?.arrayValue?.compactMap(\.stringValue) ?? []
        presetText = Self.texts(o["preset_text"])
        defaults = o["defaults"]?.objectValue ?? [:]
        var params: [Param] = []
        for item in o["params"]?.arrayValue ?? [] {
            params.append(try Param(json: item.objectValue ?? [:]))
        }
        self.params = params
        byKey = Dictionary(uniqueKeysWithValues: params.enumerated().map { ($1.key, $0) })
        let s = o["strokes"]?.objectValue ?? [:]
        strokes = StrokesRule(key: s["key"]?.stringValue, fixed: s["fixed"]?.intValue,
                              oneLine: s["one_line"]?.stringValue)
    }

    private static func texts(_ value: JSONValue?) -> [String: String] {
        var out: [String: String] = [:]
        for (key, text) in value?.objectValue ?? [:] {
            out[key] = text.stringValue
        }
        return out
    }

    public func param(_ key: String) -> Param? {
        byKey[key].map { params[$0] }
    }

    public func isEnabled(_ param: Param, in settings: JSONObject) -> Bool {
        param.enabledIf?.evaluate(settings) ?? true
    }

    /// The settings with a preset's values set (settings_schema.apply_preset).
    public func applyPreset(_ name: String, to settings: JSONObject) -> JSONObject {
        settings.merging(presets[name] ?? [:])
    }

    /// A value as the parameter takes it – type and limits as settings_schema.coerce makes them for numbers, true /
    /// false for switches; a choice that is not one of them gives the default.
    public func clamp(_ param: Param, _ value: JSONValue) -> JSONValue {
        switch param.kind {
        case .bool:
            if case .string(let s) = value {
                return .bool(["1", "true", "yes", "on"].contains(s.trimmingCharacters(in: .whitespaces).lowercased()))
            }
            return .bool(value.truthy)
        case .int:
            guard var n = Self.number(value)?.rounded(.towardZero) else { return param.default }
            if let lo = param.minimum { n = max(n, lo.rounded(.towardZero)) }
            if let hi = param.maximum { n = min(n, hi.rounded(.towardZero)) }
            return .int(Int(n))
        case .float:
            guard var n = Self.number(value) else { return param.default }
            if let lo = param.minimum { n = max(n, lo) }
            if let hi = param.maximum { n = min(n, hi) }
            return .double(n)
        case .choice:
            let wanted: JSONValue
            if case .int? = param.choices.first, let i = Self.number(value).map({ Int($0) }) {
                wanted = .int(i)
            } else {
                wanted = value
            }
            return param.choices.contains(wanted) ? wanted : param.default
        case .text, .path, .layers, .flags:
            return value
        }
    }

    private static func number(_ value: JSONValue) -> Double? {
        switch value {
        case .int(let i): Double(i)
        case .double(let d): d.isFinite ? d : nil
        case .bool(let b): b ? 1 : 0
        case .string(let s): Double(s.trimmingCharacters(in: .whitespaces))
        default: nil
        }
    }

    /// settings_schema.num_strokes
    public func numStrokes(_ settings: JSONObject) -> Int {
        if let fixed = strokes.fixed { return fixed }
        if let oneLine = strokes.oneLine, settings[oneLine]?.truthy == true { return 1 }
        guard let key = strokes.key else { return 0 }
        return (settings[key] ?? defaults[key])?.intValue ?? 0
    }
}
