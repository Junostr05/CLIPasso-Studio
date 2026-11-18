import Foundation

/// The studio as the phone page sees it (gui/phone_api.py): a method's parameters with their texts (get_schema) and
/// what a value from the phone becomes (settings_schema.coerce – nil where Python refuses it: the phone hears
/// ui.phone.page.bad_value).
public enum PhoneStudio {
    /// INPUT_SIDE: the picture as the phone sees it (and paints the detail map on)
    public static let inputSide = 900

    /// get_schema: the groups of the method's parameters (not paths, not hidden ones) with label, help, limits and
    /// choices, and its presets.
    public static func schema(_ method: MethodSchema, texts: Texts) -> JSONObject {
        var groups: [(key: String, params: [JSONValue])] = []
        for p in method.params where p.kind != .path && !p.hidden {
            var item: JSONObject = [
                "key": .string(p.key), "kind": .string(p.kind.rawValue),
                "label": .string(texts.has(p.text.label) ? texts.tr(p.text.label) : p.key),
                "help": .string(p.text.help.map { texts.has($0) ? texts.tr($0) : "" } ?? ""),
                "advanced": .bool(p.advanced), "min": number(p.minimum), "max": number(p.maximum),
                "step": number(p.step), "decimals": .int(p.decimals),
            ]
            if p.kind == .choice || p.kind == .flags {
                item["choices"] = .array(p.choices.map { value in
                    let key = p.text.choices[pyStr(value)]
                    return .object(["value": value,
                                    "label": .string(key.map { texts.has($0) ? texts.tr($0) : pyStr(value) } ?? pyStr(value))])
                })
            }
            if let i = groups.firstIndex(where: { $0.key == p.group }) {
                groups[i].params.append(.object(item))
            } else {
                groups.append((p.group, [.object(item)]))
            }
        }
        return [
            "method": .string(method.id),
            "groups": .array(groups.map { g in
                .object(["key": .string(g.key),
                         "label": .string(texts.has("group.\(g.key)") ? texts.tr("group.\(g.key)") : g.key),
                         "params": .array(g.params)])
            }),
            "presets": .array(method.presetOrder.filter { method.presets[$0] != nil }.map {
                .object(["key": .string($0), "label": .string(texts.tr("ui.preset.\($0)"))])
            }),
        ]
    }

    /// A limit as JSON (null: none; whole numbers as Python's ints would be – the page reads them as numbers).
    static func number(_ value: Double?) -> JSONValue {
        guard let value else { return .null }
        return value == value.rounded() && abs(value) < 1e15 ? .int(Int(value)) : .double(value)
    }

    // MARK: - settings_schema.coerce

    /// A raw value from the phone in the parameter's type – as Python converts it, limits included; nil where Python
    /// raises (TypeError, ValueError).
    public static func coerce(_ p: Param, _ value: JSONValue) -> JSONValue? {
        switch p.kind {
        case .bool:
            if case .string(let s) = value {
                return .bool(["1", "true", "yes", "on"].contains(s.trimmingCharacters(in: .whitespacesAndNewlines)
                        .lowercased()))
            }
            return .bool(value.truthy)
        case .int:
            guard let f = pyFloat(value), f.isFinite, abs(f) < 9.2e18 else { return nil }
            var n = Int(f)  // (int(float(value)): toward zero)
            if let lo = p.minimum, Double(n) < lo { n = Int(lo) }
            if let hi = p.maximum, Double(n) > hi { n = Int(hi) }
            return .int(n)
        case .float:
            guard var f = pyFloat(value) else { return nil }
            if let lo = p.minimum, f < lo { f = lo }
            if let hi = p.maximum, f > hi { f = hi }
            return .double(f)
        case .choice:
            let wanted: JSONValue
            if case .int? = p.choices.first {
                guard let i = pyInt(value) else { return nil }
                wanted = .int(i)
            } else {
                wanted = .string(pyStr(value))
            }
            return p.choices.contains(wanted) ? wanted : nil
        case .flags:
            let parts = Set(pyStr(value).replacingOccurrences(of: ",", with: "_").split(separator: "_").map(String.init))
            let kept = p.choices.compactMap(\.stringValue).filter { parts.contains($0) }
            return .string(kept.isEmpty ? "none" : kept.joined(separator: "_"))
        case .layers:
            return value  // (not from the phone: the studio's own field)
        case .text, .path:
            if value == .null || pyStr(value).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return .string("none")
            }
            return .string(pyStr(value))
        }
    }

    /// float(value): numbers and booleans; text as Python reads it (white space around it, "_" between digits,
    /// inf and nan); nil where Python refuses.
    static func pyFloat(_ value: JSONValue) -> Double? {
        switch value {
        case .bool(let b): return b ? 1 : 0
        case .int(let i): return Double(i)
        case .double(let d): return d
        case .string(let s):
            var t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty, t.unicodeScalars.allSatisfy({ $0.isASCII }) else { return nil }
            if t.contains("_") {  // (only single underscores between digits)
                let chars = Array(t)
                for (i, c) in chars.enumerated() where c == "_" {
                    guard i > 0, i < chars.count - 1, chars[i - 1].isNumber, chars[i + 1].isNumber else { return nil }
                }
                t = t.replacingOccurrences(of: "_", with: "")
            }
            let lower = t.lowercased()
            let body = lower.hasPrefix("+") || lower.hasPrefix("-") ? String(lower.dropFirst()) : lower
            if ["inf", "infinity", "nan"].contains(body) { return Double(lower.replacingOccurrences(of: "infinity", with: "inf")) }
            guard body.allSatisfy({ $0.isNumber || $0 == "." || $0 == "e" || $0 == "+" || $0 == "-" }),
                  body.first?.isNumber == true || body.first == "."
            else { return nil }
            return Double(t)
        default:
            return nil
        }
    }

    /// int(value): whole numbers, floats toward zero, booleans; text only of digits (with sign, white space, "_").
    static func pyInt(_ value: JSONValue) -> Int? {
        switch value {
        case .bool(let b): return b ? 1 : 0
        case .int(let i): return i
        case .double(let d): return d.isFinite && abs(d) < 9.2e18 ? Int(d) : nil
        case .string(let s):
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            let digits = t.hasPrefix("+") || t.hasPrefix("-") ? String(t.dropFirst()) : t
            guard !digits.isEmpty, digits.first != "_", digits.last != "_", !digits.contains("__"),
                  digits.allSatisfy({ ($0.isASCII && $0.isNumber) || $0 == "_" })
            else { return nil }
            return Int(t.replacingOccurrences(of: "_", with: ""))
        default:
            return nil
        }
    }

    /// str(value) as Python writes it.
    public static func pyStr(_ value: JSONValue) -> String {
        if case .string(let s) = value { return s }
        return pyRepr(value)
    }

    static func pyRepr(_ value: JSONValue) -> String {
        switch value {
        case .null: return "None"
        case .bool(let b): return b ? "True" : "False"
        case .int(let i): return String(i)
        case .double(let d): return PyJSON.pythonRepr(d)
        case .string(let s):
            let quote = s.contains("'") && !s.contains("\"") ? "\"" : "'"
            var body = s.replacingOccurrences(of: "\\", with: "\\\\")
            if quote == "'" { body = body.replacingOccurrences(of: "'", with: "\\'") }
            return quote + body.replacingOccurrences(of: "\n", with: "\\n") + quote
        case .array(let items): return "[" + items.map(pyRepr).joined(separator: ", ") + "]"
        case .object(let o): return "{" + o.map { "\(pyRepr(.string($0.key))): \(pyRepr($0.value))" }.joined(separator: ", ") + "}"
        }
    }
}
