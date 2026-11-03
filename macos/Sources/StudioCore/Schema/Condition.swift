import Foundation

/// A parameter's rule "enabled when …", read from schema.json. It decides as `clipasso_studio/conditions.py` does,
/// with Python's comparisons (1 == 1.0 == True) and truth (`bool()`).
public indirect enum Condition: Sendable, Hashable {
    case on(String)
    case off(String)
    case eq(String, JSONValue, default: JSONValue?)
    case ne(String, JSONValue, default: JSONValue?)
    case gt(String, Double)
    case has(String, String)
    case all([Condition])
    case any([Condition])

    public struct FormatError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    public init(json: JSONValue) throws(FormatError) {
        guard let o = json.objectValue, let op = o["op"]?.stringValue else {
            throw FormatError(description: "a rule is an object with an op: \(PyJSON.dump(json))")
        }
        func key() throws(FormatError) -> String {
            guard let k = o["key"]?.stringValue else { throw FormatError(description: "\(op) needs a key") }
            return k
        }
        func value() throws(FormatError) -> JSONValue {
            guard let v = o["value"] else { throw FormatError(description: "\(op) needs a value") }
            return v
        }
        func parts() throws(FormatError) -> [Condition] {
            guard let items = o["of"]?.arrayValue else { throw FormatError(description: "\(op) needs of") }
            var out: [Condition] = []
            for item in items {
                out.append(try Condition(json: item))
            }
            return out
        }
        switch op {
        case "on": self = .on(try key())
        case "off": self = .off(try key())
        case "eq": self = .eq(try key(), try value(), default: o["default"])
        case "ne": self = .ne(try key(), try value(), default: o["default"])
        case "gt":
            guard let n = try value().doubleValue else { throw FormatError(description: "gt needs a number") }
            self = .gt(try key(), n)
        case "has":
            guard let flag = try value().stringValue else { throw FormatError(description: "has needs a text") }
            self = .has(try key(), flag)
        case "all": self = .all(try parts())
        case "any": self = .any(try parts())
        default: throw FormatError(description: "unknown op \(op)")
        }
    }

    public func evaluate(_ settings: JSONObject) -> Bool {
        switch self {
        case .on(let key): settings[key]?.truthy ?? false
        case .off(let key): !(settings[key]?.truthy ?? false)
        case .eq(let key, let value, let fallback): Self.pyEquals(settings[key] ?? fallback ?? .null, value)
        case .ne(let key, let value, let fallback): !Self.pyEquals(settings[key] ?? fallback ?? .null, value)
        case .gt(let key, let n): Self.pyFloat(settings[key]) > n
        case .has(let key, let flag): Self.pyStr(settings[key] ?? .string("")).contains(flag)
        case .all(let rules): rules.allSatisfy { $0.evaluate(settings) }
        case .any(let rules): rules.contains { $0.evaluate(settings) }
        }
    }

    /// Python's `==`: numbers (and booleans, which are numbers there) compare by value.
    static func pyEquals(_ a: JSONValue, _ b: JSONValue) -> Bool {
        func number(_ v: JSONValue) -> Double? {
            switch v {
            case .bool(let b): b ? 1 : 0
            case .int(let i): Double(i)
            case .double(let d): d
            default: nil
            }
        }
        if let x = number(a), let y = number(b) { return x == y }
        return a == b
    }

    /// `float(value or 0)`; a text that is no number counts as 0 (Python would raise).
    static func pyFloat(_ value: JSONValue?) -> Double {
        guard let value, value.truthy else { return 0 }
        switch value {
        case .bool(let b): return b ? 1 : 0
        case .int(let i): return Double(i)
        case .double(let d): return d
        case .string(let s): return Double(s.trimmingCharacters(in: .whitespaces)) ?? 0
        default: return 0
        }
    }

    /// Python's `str(value)` for the values settings hold.
    static func pyStr(_ value: JSONValue) -> String {
        switch value {
        case .null: "None"
        case .bool(let b): b ? "True" : "False"
        case .int(let i): String(i)
        case .double(let d): PyJSON.pythonRepr(d)
        case .string(let s): s
        default: PyJSON.dump(value)
        }
    }
}
