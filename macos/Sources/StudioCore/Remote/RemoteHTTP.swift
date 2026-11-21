import Foundation

/// A request to the phone server, as BaseHTTPRequestHandler reads it: the method, the path as sent (not decoded),
/// the query, the headers (names in lower case) and the body when one was read.
public struct RemoteRequest: Sendable {
    public var method: String
    /// the path without the query, as sent (urlparse(...).path)
    public var path: String
    /// parse_qs: the first value of each key; pairs without a value are left out
    public var query: [String: String]
    public var headers: [String: String]
    /// the body (nil: none, or it was not read – too large or not wanted for this path)
    public var body: Data?
    /// the Content-Length the client gave (0: none or not a number)
    public var length: Int
    /// the client's address
    public var client: String

    public init(method: String, target: String, headers: [String: String] = [:], body: Data? = nil,
                client: String = "127.0.0.1")
    {
        self.method = method
        let (path, query) = RemoteHTTP.split(target)
        self.path = path
        self.query = RemoteHTTP.parseQuery(query)
        var lower: [String: String] = [:]
        for (k, v) in headers { lower[k.lowercased()] = v }
        self.headers = lower
        self.body = body
        length = max(0, Int(lower["content-length"] ?? "") ?? 0)
        self.client = client
    }

    public func header(_ name: String) -> String? { headers[name.lowercased()] }
}

/// What the server answers: a whole answer, a file sent in pieces from the disk, or an event stream.
public enum RemoteReply: Sendable {
    case full(status: Int, headers: [(String, String)], body: Data)
    case file(headers: [(String, String)], url: URL, size: Int)
    case events
}

/// What answers the requests of a RemoteServer: the phone page's router, or the MCP server's.
public protocol HTTPResponder: Sendable {
    /// the server-sent events of a stream (the phone page's "changed")
    var events: RemoteEvents { get }
    /// the largest body read for a request (0: none)
    func bodyLimit(method: String, path: String) -> Int
    func respond(_ request: RemoteRequest) async -> RemoteReply
}

extension RemoteRouter: HTTPResponder {}

public enum RemoteHTTP {
    /// The reason phrase of a status (http.server's).
    public static func reason(_ status: Int) -> String {
        switch status {
        case 200: "OK"
        case 303: "See Other"
        case 400: "Bad Request"
        case 403: "Forbidden"
        case 404: "Not Found"
        case 413: "Request Entity Too Large"
        case 415: "Unsupported Media Type"
        case 429: "Too Many Requests"
        case 431: "Request Header Fields Too Large"
        case 500: "Internal Server Error"
        case 503: "Service Unavailable"
        default: "Status"
        }
    }

    /// The head of an answer (status line and headers, the blank line after them).
    public static func head(status: Int, headers: [(String, String)]) -> Data {
        var text = "HTTP/1.1 \(status) \(reason(status))\r\nServer: CLIPassoStudio\r\nConnection: close\r\n"
        for (k, v) in headers where !v.contains("\r") && !v.contains("\n") { text += "\(k): \(v)\r\n" }
        return Data((text + "\r\n").utf8)
    }

    /// A request's head: the request line and the headers (nil: not one).
    public static func parseHead(_ data: Data) -> (method: String, target: String, headers: [String: String])? {
        guard let text = String(data: data, encoding: .isoLatin1) else { return nil }
        var lines = text.components(separatedBy: "\r\n")
        guard !lines.isEmpty else { return nil }
        let first = lines.removeFirst().split(separator: " ", omittingEmptySubsequences: true)
        guard first.count == 3, first[2].hasPrefix("HTTP/") else { return nil }
        var headers: [String: String] = [:]
        for line in lines where !line.isEmpty {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let name = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            // (header values as UTF-8, as the phone sends a file's name percent-encoded anyway)
            let utf8 = String(decoding: value.unicodeScalars.map { UInt8(truncatingIfNeeded: $0.value) }, as: UTF8.self)
            if headers[name] == nil { headers[name] = utf8 }  // (the first, as email.message's get)
        }
        return (String(first[0]), String(first[1]), headers)
    }

    /// The path and the query of a request target.
    static func split(_ target: String) -> (String, String) {
        var t = Substring(target)
        if let hash = t.firstIndex(of: "#") { t = t[..<hash] }
        guard let q = t.firstIndex(of: "?") else { return (String(t), "") }
        return (String(t[..<q]), String(t[t.index(after: q)...]))
    }

    /// urllib.parse.parse_qs (first values; blank values and pairs without "=" left out; "+" is a space).
    static func parseQuery(_ query: String) -> [String: String] {
        var out: [String: String] = [:]
        for pair in query.split(separator: "&", omittingEmptySubsequences: true) {
            let parts = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2, !parts[1].isEmpty else { continue }
            let key = unquote(parts[0].replacingOccurrences(of: "+", with: " "))
            if out[key] == nil { out[key] = unquote(parts[1].replacingOccurrences(of: "+", with: " ")) }
        }
        return out
    }

    /// urllib.parse.unquote: %XX as bytes, read as UTF-8 (a broken sequence replaced); a % without two hex digits
    /// stays as it is.
    public static func unquote(_ text: String) -> String {
        guard text.contains("%") else { return text }
        var bytes: [UInt8] = []
        let utf8 = Array(text.utf8)
        var i = 0
        while i < utf8.count {
            if utf8[i] == 0x25, i + 2 < utf8.count, let h = hex(utf8[i + 1]), let l = hex(utf8[i + 2]) {
                bytes.append(h << 4 | l)
                i += 3
            } else {
                bytes.append(utf8[i])
                i += 1
            }
        }
        return String(decoding: bytes, as: UTF8.self)
    }

    private static func hex(_ c: UInt8) -> UInt8? {
        switch c {
        case 0x30 ... 0x39: c - 0x30
        case 0x41 ... 0x46: c - 0x41 + 10
        case 0x61 ... 0x66: c - 0x61 + 10
        default: nil
        }
    }

    /// SimpleCookie's value of `name` in a Cookie header (nil: none).
    static func cookie(_ header: String?, _ name: String) -> String? {
        for part in (header ?? "").split(separator: ";") {
            let kv = part.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard kv.count == 2, kv[0].trimmingCharacters(in: .whitespaces) == name else { continue }
            var value = kv[1].trimmingCharacters(in: .whitespaces)
            if value.count >= 2, value.hasPrefix("\""), value.hasSuffix("\"") {
                value = String(value.dropFirst().dropLast())
            }
            return value
        }
        return nil
    }

    /// os.path.splitext of a file name: the extension from the last dot, when something else than dots is before it.
    static func splitext(_ name: String) -> (stem: String, ext: String) {
        guard let dot = name.lastIndex(of: "."), name[..<dot].contains(where: { $0 != "." }) else { return (name, "") }
        return (String(name[..<dot]), String(name[dot...]))
    }

    /// str.isalnum of one code point (letters of every script, every kind of digit).
    static func isAlnum(_ s: Unicode.Scalar) -> Bool {
        switch s.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter: true
        default: s.properties.numericType != nil
        }
    }
}
