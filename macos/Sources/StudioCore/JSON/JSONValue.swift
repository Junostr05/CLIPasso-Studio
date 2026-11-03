import Foundation

/// A JSON value as Python's `json` module sees it: whole numbers stay whole (`int`), objects keep the order of their
/// keys (Python dicts do), and `truthy` is Python's `bool()`.
public enum JSONValue: Sendable, Hashable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object(JSONObject)

    /// Python's `bool(value)`: false for null, false, 0, 0.0, "", [] and {} – true for everything else (NaN too).
    public var truthy: Bool {
        switch self {
        case .null: false
        case .bool(let b): b
        case .int(let i): i != 0
        case .double(let d): d != 0 || d.isNaN
        case .string(let s): !s.isEmpty
        case .array(let a): !a.isEmpty
        case .object(let o): !o.isEmpty
        }
    }

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    public var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }

    /// A whole number (also a double without a fractional part, as Python's `int()` of it would be).
    public var intValue: Int? {
        switch self {
        case .int(let i): i
        case .double(let d) where d.isFinite && d.rounded(.towardZero) == d && abs(d) < 9.2e18: Int(d)
        default: nil
        }
    }

    /// A number (an int as a double).
    public var doubleValue: Double? {
        switch self {
        case .int(let i): Double(i)
        case .double(let d): d
        default: nil
        }
    }

    public var arrayValue: [JSONValue]? {
        if case .array(let a) = self { return a }
        return nil
    }

    public var objectValue: JSONObject? {
        if case .object(let o) = self { return o }
        return nil
    }

    public var isNull: Bool {
        if case .null = self { return true }
        return false
    }
}

extension JSONValue: ExpressibleByNilLiteral, ExpressibleByBooleanLiteral, ExpressibleByIntegerLiteral,
    ExpressibleByFloatLiteral, ExpressibleByStringLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral
{
    public init(nilLiteral: ()) { self = .null }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(integerLiteral value: Int) { self = .int(value) }
    public init(floatLiteral value: Double) { self = .double(value) }
    public init(stringLiteral value: String) { self = .string(value) }
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) { self = .object(JSONObject(elements)) }
}

/// A JSON object that keeps the order of its keys like a Python dict: a new key goes to the end, setting an existing
/// key keeps its place. Two objects are equal when they hold the same keys and values, whatever the order (as in
/// Python).
public struct JSONObject: Sendable, Hashable, Sequence, ExpressibleByDictionaryLiteral {
    public private(set) var keys: [String] = []
    private var storage: [String: JSONValue] = [:]

    public init() {}

    /// Later pairs with the same key replace the value and keep the first one's place (Python's `dict(pairs)`).
    public init(_ pairs: [(String, JSONValue)]) {
        for (key, value) in pairs {
            self[key] = value
        }
    }

    public init(dictionaryLiteral elements: (String, JSONValue)...) {
        self.init(elements)
    }

    public subscript(key: String) -> JSONValue? {
        get { storage[key] }
        set {
            if let newValue {
                if storage.updateValue(newValue, forKey: key) == nil {
                    keys.append(key)
                }
            } else if storage.removeValue(forKey: key) != nil {
                keys.removeAll { $0 == key }
            }
        }
    }

    public var count: Int { keys.count }
    public var isEmpty: Bool { keys.isEmpty }

    /// This object with the keys of `other` set on it (Python's `{**self, **other}`).
    public func merging(_ other: JSONObject) -> JSONObject {
        var out = self
        for (key, value) in other {
            out[key] = value
        }
        return out
    }

    public func makeIterator() -> IndexingIterator<[(key: String, value: JSONValue)]> {
        keys.map { (key: $0, value: storage[$0]!) }.makeIterator()
    }

    public static func == (lhs: JSONObject, rhs: JSONObject) -> Bool {
        lhs.storage == rhs.storage
    }

    public func hash(into hasher: inout Hasher) {
        hasher.combine(storage)
    }
}
