import Foundation

/// JSON read and written the way Python's `json` module does it, so the files of a job folder look the same whichever
/// app wrote them:
///
/// - `dump(value)` is `json.dumps(value, ensure_ascii=False)`, `dump(value, indent: 2)` is
///   `json.dumps(value, indent=2, ensure_ascii=False)` – byte for byte, floats as Python's `repr` writes them.
/// - `parse` keeps the order of an object's keys and tells whole numbers (`int`) from floats, and reads the
///   `NaN` / `Infinity` / `-Infinity` that `json.dump` writes by default.
public enum PyJSON {
    public struct ParseError: Error, CustomStringConvertible, Sendable {
        public let message: String
        public let offset: Int
        public var description: String { "JSON: \(message) at byte \(offset)" }
    }

    // MARK: - reading

    public static func parse(_ data: Data) throws(ParseError) -> JSONValue {
        var parser = Parser(bytes: [UInt8](data))
        parser.skipSpace()
        let value = try parser.value(depth: 0)
        parser.skipSpace()
        guard parser.atEnd else { throw parser.fail("extra data") }
        return value
    }

    private struct Parser {
        let bytes: [UInt8]
        var at = 0
        static let maxDepth = 512

        var atEnd: Bool { at >= bytes.count }

        func fail(_ message: String) -> ParseError { ParseError(message: message, offset: at) }

        mutating func skipSpace() {
            while at < bytes.count, [0x20, 0x09, 0x0A, 0x0D].contains(bytes[at]) {
                at += 1
            }
        }

        mutating func expect(_ word: String) throws(ParseError) {
            for byte in word.utf8 {
                guard at < bytes.count, bytes[at] == byte else { throw fail("expected \(word)") }
                at += 1
            }
        }

        mutating func value(depth: Int) throws(ParseError) -> JSONValue {
            guard depth < Self.maxDepth else { throw fail("nested too deep") }
            guard at < bytes.count else { throw fail("unexpected end") }
            switch bytes[at] {
            case UInt8(ascii: "{"): return try object(depth: depth)
            case UInt8(ascii: "["): return try array(depth: depth)
            case UInt8(ascii: "\""): return .string(try string())
            case UInt8(ascii: "t"): try expect("true"); return .bool(true)
            case UInt8(ascii: "f"): try expect("false"); return .bool(false)
            case UInt8(ascii: "n"): try expect("null"); return .null
            case UInt8(ascii: "N"): try expect("NaN"); return .double(.nan)
            case UInt8(ascii: "I"): try expect("Infinity"); return .double(.infinity)
            default: return try number()
            }
        }

        mutating func object(depth: Int) throws(ParseError) -> JSONValue {
            at += 1
            var out = JSONObject()
            skipSpace()
            if at < bytes.count, bytes[at] == UInt8(ascii: "}") {
                at += 1
                return .object(out)
            }
            while true {
                skipSpace()
                guard at < bytes.count, bytes[at] == UInt8(ascii: "\"") else { throw fail("expected a key") }
                let key = try string()
                skipSpace()
                guard at < bytes.count, bytes[at] == UInt8(ascii: ":") else { throw fail("expected ':'") }
                at += 1
                skipSpace()
                out[key] = try value(depth: depth + 1)
                skipSpace()
                guard at < bytes.count else { throw fail("unexpected end") }
                if bytes[at] == UInt8(ascii: ",") {
                    at += 1
                    continue
                }
                guard bytes[at] == UInt8(ascii: "}") else { throw fail("expected ',' or '}'") }
                at += 1
                return .object(out)
            }
        }

        mutating func array(depth: Int) throws(ParseError) -> JSONValue {
            at += 1
            var out: [JSONValue] = []
            skipSpace()
            if at < bytes.count, bytes[at] == UInt8(ascii: "]") {
                at += 1
                return .array(out)
            }
            while true {
                skipSpace()
                out.append(try value(depth: depth + 1))
                skipSpace()
                guard at < bytes.count else { throw fail("unexpected end") }
                if bytes[at] == UInt8(ascii: ",") {
                    at += 1
                    continue
                }
                guard bytes[at] == UInt8(ascii: "]") else { throw fail("expected ',' or ']'") }
                at += 1
                return .array(out)
            }
        }

        mutating func hex4() throws(ParseError) -> UInt32 {
            guard at + 4 <= bytes.count else { throw fail("short \\u escape") }
            var code: UInt32 = 0
            for _ in 0..<4 {
                let b = bytes[at]
                let digit: UInt32
                switch b {
                case 0x30...0x39: digit = UInt32(b - 0x30)
                case 0x41...0x46: digit = UInt32(b - 0x41 + 10)
                case 0x61...0x66: digit = UInt32(b - 0x61 + 10)
                default: throw fail("bad \\u escape")
                }
                code = code * 16 + digit
                at += 1
            }
            return code
        }

        mutating func string() throws(ParseError) -> String {
            at += 1  // the opening quote
            var raw: [UInt8] = []
            while true {
                guard at < bytes.count else { throw fail("unterminated string") }
                let b = bytes[at]
                if b == UInt8(ascii: "\"") {
                    at += 1
                    break
                }
                if b < 0x20 { throw fail("control character in string") }  // (json.loads is strict too)
                if b != UInt8(ascii: "\\") {
                    raw.append(b)
                    at += 1
                    continue
                }
                at += 1
                guard at < bytes.count else { throw fail("unterminated escape") }
                let e = bytes[at]
                at += 1
                switch e {
                case UInt8(ascii: "\""): raw.append(0x22)
                case UInt8(ascii: "\\"): raw.append(0x5C)
                case UInt8(ascii: "/"): raw.append(0x2F)
                case UInt8(ascii: "b"): raw.append(0x08)
                case UInt8(ascii: "f"): raw.append(0x0C)
                case UInt8(ascii: "n"): raw.append(0x0A)
                case UInt8(ascii: "r"): raw.append(0x0D)
                case UInt8(ascii: "t"): raw.append(0x09)
                case UInt8(ascii: "u"):
                    var code = try hex4()
                    if (0xD800...0xDBFF).contains(code) {  // a surrogate pair
                        guard at + 2 <= bytes.count, bytes[at] == UInt8(ascii: "\\"), bytes[at + 1] == UInt8(ascii: "u")
                        else { throw fail("lone surrogate") }
                        at += 2
                        let low = try hex4()
                        guard (0xDC00...0xDFFF).contains(low) else { throw fail("lone surrogate") }
                        code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                    } else if (0xDC00...0xDFFF).contains(code) {
                        throw fail("lone surrogate")
                    }
                    guard let scalar = Unicode.Scalar(code) else { throw fail("bad code point") }
                    raw.append(contentsOf: Array(String(Character(scalar)).utf8))
                default:
                    throw fail("bad escape")
                }
            }
            guard let text = String(validating: raw, as: UTF8.self) else { throw fail("not UTF-8") }
            return text
        }

        mutating func number() throws(ParseError) -> JSONValue {
            let start = at
            if at < bytes.count, bytes[at] == UInt8(ascii: "-") {
                at += 1
                if at < bytes.count, bytes[at] == UInt8(ascii: "I") {
                    try expect("Infinity")
                    return .double(-.infinity)
                }
            }
            func digits(_ p: inout Parser) -> Int {
                let s = p.at
                while p.at < p.bytes.count, (0x30...0x39).contains(p.bytes[p.at]) { p.at += 1 }
                return p.at - s
            }
            let intStart = at
            let intDigits = digits(&self)
            guard intDigits > 0 else { throw fail("expected a value") }
            if intDigits > 1, bytes[intStart] == UInt8(ascii: "0") { throw fail("leading zero") }
            var whole = true
            if at < bytes.count, bytes[at] == UInt8(ascii: ".") {
                whole = false
                at += 1
                guard digits(&self) > 0 else { throw fail("digits expected after '.'") }
            }
            if at < bytes.count, bytes[at] == UInt8(ascii: "e") || bytes[at] == UInt8(ascii: "E") {
                whole = false
                at += 1
                if at < bytes.count, bytes[at] == UInt8(ascii: "+") || bytes[at] == UInt8(ascii: "-") { at += 1 }
                guard digits(&self) > 0 else { throw fail("digits expected in the exponent") }
            }
            let text = String(decoding: bytes[start..<at], as: UTF8.self)
            if whole, let i = Int(text) { return .int(i) }
            guard let d = Double(text) else { throw fail("bad number") }
            return .double(d)  // (a whole number too large for Int, too)
        }
    }

    // MARK: - writing

    public static func dump(_ value: JSONValue, indent: Int? = nil) -> String {
        var out = ""
        write(value, indent: indent, level: 0, into: &out)
        return out
    }

    private static func write(_ value: JSONValue, indent: Int?, level: Int, into out: inout String) {
        switch value {
        case .null: out += "null"
        case .bool(let b): out += b ? "true" : "false"
        case .int(let i): out += String(i)
        case .double(let d): out += pythonRepr(d)
        case .string(let s): writeString(s, into: &out)
        case .array(let items):
            guard !items.isEmpty else {
                out += "[]"
                return
            }
            out += "["
            for (i, item) in items.enumerated() {
                if i > 0 { out += indent == nil ? ", " : "," }
                newline(indent, level + 1, &out)
                write(item, indent: indent, level: level + 1, into: &out)
            }
            newline(indent, level, &out)
            out += "]"
        case .object(let object):
            guard !object.isEmpty else {
                out += "{}"
                return
            }
            out += "{"
            for (i, (key, item)) in object.enumerated() {
                if i > 0 { out += indent == nil ? ", " : "," }
                newline(indent, level + 1, &out)
                writeString(key, into: &out)
                out += ": "
                write(item, indent: indent, level: level + 1, into: &out)
            }
            newline(indent, level, &out)
            out += "}"
        }
    }

    private static func newline(_ indent: Int?, _ level: Int, _ out: inout String) {
        guard let indent else { return }
        out += "\n" + String(repeating: " ", count: indent * level)
    }

    /// As `json.dumps(…, ensure_ascii=False)`: only `"`, `\` and the control characters are escaped.
    private static func writeString(_ s: String, into out: inout String) {
        out += "\""
        for scalar in s.unicodeScalars {
            switch scalar {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            case let c where c.value < 0x20:
                let hex = String(c.value, radix: 16)
                out += "\\u" + String(repeating: "0", count: 4 - hex.count) + hex
            default:
                out.unicodeScalars.append(scalar)
            }
        }
        out += "\""
    }

    /// A float as Python's `repr` writes it: the shortest digits that read back the same, in plain notation from
    /// 1e-4 up to below 1e16 and as `1e+16` / `1.5e-07` outside.
    static func pythonRepr(_ d: Double) -> String {
        if d.isNaN { return "NaN" }
        if d.isInfinite { return d < 0 ? "-Infinity" : "Infinity" }
        let sign = d.sign == .minus ? "-" : ""
        // the shortest round-trip digits from Swift's own description, then laid out the way Python does
        var text = "\(abs(d))"
        var exponent = 0
        if let e = text.firstIndex(where: { $0 == "e" || $0 == "E" }) {
            exponent = Int(text[text.index(after: e)...]) ?? 0
            text = String(text[..<e])
        }
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        let intPart = String(parts[0])
        let fracPart = parts.count > 1 ? String(parts[1]) : ""
        var digits = intPart + fracPart
        var point = intPart.count + exponent  // where the decimal point is, counted from the first digit
        let leading = digits.prefix { $0 == "0" }.count
        digits.removeFirst(leading)
        point -= leading
        while digits.hasSuffix("0") { digits.removeLast() }
        if digits.isEmpty {  // zero
            return sign + "0.0"
        }
        if point <= -4 || point > 16 {
            let exp = point - 1
            let mantissa = digits.count > 1 ? "\(digits.first!).\(digits.dropFirst())" : digits
            let magnitude = abs(exp)
            return sign + mantissa + "e" + (exp < 0 ? "-" : "+") + (magnitude < 10 ? "0" : "") + String(magnitude)
        }
        if point <= 0 {
            return sign + "0." + String(repeating: "0", count: -point) + digits
        }
        if point >= digits.count {
            return sign + digits + String(repeating: "0", count: point - digits.count) + ".0"
        }
        let cut = digits.index(digits.startIndex, offsetBy: point)
        return sign + digits[..<cut] + "." + digits[cut...]
    }
}
