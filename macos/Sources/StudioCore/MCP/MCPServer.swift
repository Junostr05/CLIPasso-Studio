import Foundation

/// A tool the MCP server offers: its name, what it does and the JSON Schema of its arguments.
public struct MCPTool: Sendable {
    public let name: String
    public let description: String
    public let inputSchema: JSONValue

    public init(name: String, description: String, inputSchema: JSONValue = ["type": "object", "properties": [:]]) {
        self.name = name
        self.description = description
        self.inputSchema = inputSchema
    }
}

/// What a tool answers: text (JSON as text, mostly) and pictures; an error is an answer with `isError`.
public struct MCPResult: Sendable {
    public enum Content: Sendable {
        case text(String)
        case image(Data, mime: String)
    }

    public var content: [Content]
    public var isError = false

    public init(_ content: [Content], isError: Bool = false) {
        self.content = content
        self.isError = isError
    }

    /// A JSON value as the tool's text.
    public static func json(_ value: JSONValue) -> MCPResult { MCPResult([.text(PyJSON.dump(value, indent: 1))]) }

    public static func error(_ message: String) -> MCPResult { MCPResult([.text(message)], isError: true) }
}

/// The Model Context Protocol over HTTP ("Streamable HTTP", answered as plain JSON – no event stream): JSON-RPC 2.0
/// requests posted to /mcp – initialize, ping, tools/list, tools/call –, a bearer token on every request, and only
/// pages of this computer (an Origin of another host is refused: no DNS rebinding). The tools themselves are the
/// app's (`call`).
public final class MCPRouter: HTTPResponder, Sendable {
    public nonisolated static let path = "/mcp"
    public nonisolated static let versions = ["2025-06-18", "2025-03-26", "2024-11-05"]
    public let events = RemoteEvents()
    let token: @Sendable () -> String
    let tools: [MCPTool]
    let call: @Sendable (String, JSONObject) async -> MCPResult
    let name: String
    let version: String
    let instructions: String

    public init(token: @escaping @Sendable () -> String, tools: [MCPTool], name: String = "clipasso-studio",
                version: String, instructions: String, call: @escaping @Sendable (String, JSONObject) async -> MCPResult)
    {
        self.token = token
        self.tools = tools
        self.name = name
        self.version = version
        self.instructions = instructions
        self.call = call
    }

    public func bodyLimit(method: String, path: String) -> Int {
        method == "POST" && path == Self.path ? 4 * 1024 * 1024 : 0
    }

    public func respond(_ request: RemoteRequest) async -> RemoteReply {
        guard request.path == Self.path else { return Self.plain(404, "not found") }
        if let origin = request.header("origin"), !Self.local(origin) { return Self.plain(403, "foreign origin") }
        guard Self.same(request.header("authorization") ?? "", "Bearer \(token())") else {
            return .full(status: 401, headers: [("WWW-Authenticate", "Bearer"), ("Content-Type", "text/plain"),
                                                ("Content-Length", "13")], body: Data("missing token".utf8))
        }
        guard request.method == "POST" else {
            return .full(status: 405, headers: [("Allow", "POST"), ("Content-Length", "0")], body: Data())
        }
        guard let body = request.body, let message = try? PyJSON.parse(body) else {
            return Self.json(Self.failure(.null, -32700, "parse error"))
        }
        if let batch = message.arrayValue {
            var answers: [JSONValue] = []
            for item in batch {
                if let answer = await handle(item) { answers.append(answer) }
            }
            return answers.isEmpty ? Self.accepted : Self.json(.array(answers))
        }
        guard let answer = await handle(message) else { return Self.accepted }
        return Self.json(answer)
    }

    /// One JSON-RPC message: its answer, or nil for a notification.
    public func handle(_ message: JSONValue) async -> JSONValue? {
        guard let m = message.objectValue, m["jsonrpc"]?.stringValue == "2.0", let method = m["method"]?.stringValue
        else { return Self.failure(message.objectValue?["id"] ?? .null, -32600, "invalid request") }
        guard let id = m["id"] else { return nil }  // (a notification: notifications/initialized …)
        let params = m["params"]?.objectValue ?? [:]
        switch method {
        case "initialize":
            let asked = params["protocolVersion"]?.stringValue ?? ""
            return Self.success(id, [
                "protocolVersion": .string(Self.versions.contains(asked) ? asked : Self.versions[0]),
                "capabilities": ["tools": ["listChanged": false]],
                "serverInfo": ["name": .string(name), "version": .string(version)],
                "instructions": .string(instructions),
            ])
        case "ping":
            return Self.success(id, [:])
        case "tools/list":
            return Self.success(id, ["tools": .array(tools.map { tool -> JSONValue in
                ["name": .string(tool.name), "description": .string(tool.description), "inputSchema": tool.inputSchema]
            })])
        case "tools/call":
            guard let name = params["name"]?.stringValue, tools.contains(where: { $0.name == name }) else {
                return Self.failure(id, -32602, "unknown tool")
            }
            let result = await call(name, params["arguments"]?.objectValue ?? [:])
            return Self.success(id, [
                "content": .array(result.content.map { content -> JSONValue in
                    switch content {
                    case .text(let text):
                        return ["type": "text", "text": .string(text)]
                    case .image(let data, let mime):
                        return ["type": "image", "data": .string(data.base64EncodedString()), "mimeType": .string(mime)]
                    }
                }),
                "isError": .bool(result.isError),
            ])
        default:
            return Self.failure(id, -32601, "method not found: \(method)")
        }
    }

    // MARK: - answers

    static func success(_ id: JSONValue, _ result: JSONObject) -> JSONValue {
        ["jsonrpc": "2.0", "id": id, "result": .object(result)]
    }

    static func failure(_ id: JSONValue, _ code: Int, _ message: String) -> JSONValue {
        ["jsonrpc": "2.0", "id": id, "error": ["code": .int(code), "message": .string(message)]]
    }

    static func json(_ value: JSONValue) -> RemoteReply {
        let body = Data(PyJSON.dump(value).utf8)
        return .full(status: 200, headers: [("Content-Type", "application/json"), ("Content-Length", "\(body.count)"),
                                            ("Cache-Control", "no-store")], body: body)
    }

    static let accepted = RemoteReply.full(status: 202, headers: [("Content-Length", "0")], body: Data())

    static func plain(_ status: Int, _ text: String) -> RemoteReply {
        .full(status: status, headers: [("Content-Type", "text/plain"), ("Content-Length", "\(text.utf8.count)")],
              body: Data(text.utf8))
    }

    /// An Origin of this computer (http(s)://localhost, 127.0.0.1, [::1], with any port).
    static func local(_ origin: String) -> Bool {
        guard let host = URL(string: origin)?.host()?.lowercased() else { return false }
        return ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host)
    }

    /// Compares in the same time whatever the difference (a token is not guessed letter by letter).
    static func same(_ a: String, _ b: String) -> Bool {
        let (x, y) = (Array(a.utf8), Array(b.utf8))
        var diff = x.count ^ y.count
        for i in 0 ..< max(x.count, y.count) {
            diff |= Int((i < x.count ? x[i] : 0) ^ (i < y.count ? y[i] : 0))
        }
        return diff == 0
    }
}
