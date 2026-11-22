import Foundation
import Testing
@testable import StudioCore

/// The MCP server's protocol: JSON-RPC 2.0 posted to /mcp with the bearer token – initialize (the version asked for
/// when it is known), ping, tools/list, tools/call (text and pictures, an error as isError), notifications without an
/// answer, batches, and the refusals (no token, a foreign page, another path or method, broken JSON).
@Suite struct MCPServerTests {
    static let token = "mcp-0123456789abcdefghij"

    static func router() -> MCPRouter {
        let tools = [MCPTool(name: "echo", description: "says it back",
                             inputSchema: ["type": "object", "properties": ["say": ["type": "string"]]]),
                     MCPTool(name: "picture", description: "a picture"),
                     MCPTool(name: "broken", description: "fails")]
        return MCPRouter(token: { token }, tools: tools, version: "9.9", instructions: "be kind") { name, arguments in
            switch name {
            case "echo": return .json(["said": arguments["say"] ?? .null])
            case "picture": return MCPResult([.image(Data([1, 2, 3]), mime: "image/png")])
            default: return .error("it broke")
            }
        }
    }

    static func post(_ router: MCPRouter, _ body: String, token: String? = MCPServerTests.token,
                     origin: String? = nil, method: String = "POST", path: String = "/mcp") async -> (Int, Data)
    {
        var headers: [String: String] = ["content-type": "application/json"]
        if let token { headers["authorization"] = "Bearer \(token)" }
        if let origin { headers["origin"] = origin }
        let reply = await router.respond(RemoteRequest(method: method, target: path, headers: headers,
                                                       body: Data(body.utf8)))
        guard case .full(let status, _, let data) = reply else { return (0, Data()) }
        return (status, data)
    }

    static func call(_ router: MCPRouter, _ body: String) async throws -> JSONObject {
        let (status, data) = await post(router, body)
        #expect(status == 200)
        return try #require(try PyJSON.parse(data).objectValue)
    }

    @Test func theHandshakeAndTheTools() async throws {
        let r = Self.router()
        var answer = try await Self.call(r, #"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}"#)
        let result = try #require(answer["result"]?.objectValue)
        #expect(answer["id"] == 1 && result["protocolVersion"] == "2025-03-26")
        #expect(result["serverInfo"] == ["name": "clipasso-studio", "version": "9.9"])
        #expect(result["capabilities"]?.objectValue?["tools"] != nil && result["instructions"] == "be kind")
        answer = try await Self.call(r, #"{"jsonrpc":"2.0","id":"a","method":"initialize","params":{"protocolVersion":"1999-01-01"}}"#)
        #expect(answer["result"]?.objectValue?["protocolVersion"] == .string(MCPRouter.versions[0]))

        // a notification: accepted, no answer
        #expect(await Self.post(r, #"{"jsonrpc":"2.0","method":"notifications/initialized"}"#).0 == 202)
        #expect(try await Self.call(r, #"{"jsonrpc":"2.0","id":2,"method":"ping"}"#)["result"] == [:])

        let tools = try #require(try await Self.call(r, #"{"jsonrpc":"2.0","id":3,"method":"tools/list"}"#)["result"]?
            .objectValue?["tools"]?.arrayValue)
        #expect(tools.compactMap { $0.objectValue?["name"]?.stringValue } == ["echo", "picture", "broken"])
        #expect(tools[0].objectValue?["inputSchema"]?.objectValue?["type"] == "object")

        var called = try await Self.call(r, #"{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"echo","arguments":{"say":"hallo"}}}"#)
        var content = try #require(called["result"]?.objectValue)
        #expect(content["isError"] == false)
        let text = try #require(content["content"]?.arrayValue?.first?.objectValue)
        #expect(text["type"] == "text")
        #expect(try PyJSON.parse(Data((text["text"]?.stringValue ?? "").utf8)) == ["said": "hallo"])

        called = try await Self.call(r, #"{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"picture"}}"#)
        content = try #require(called["result"]?.objectValue)
        #expect(content["content"]?.arrayValue?.first == ["type": "image", "data": "AQID", "mimeType": "image/png"])

        called = try await Self.call(r, #"{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"broken"}}"#)
        #expect(called["result"]?.objectValue?["isError"] == true)

        called = try await Self.call(r, #"{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"nope"}}"#)
        #expect(called["error"]?.objectValue?["code"] == -32602)
        called = try await Self.call(r, #"{"jsonrpc":"2.0","id":8,"method":"resources/list"}"#)
        #expect(called["error"]?.objectValue?["code"] == -32601)
        called = try await Self.call(r, #"{"id":9,"method":"ping"}"#)
        #expect(called["error"]?.objectValue?["code"] == -32600 && called["id"] == 9)
    }

    @Test func aBatch() async throws {
        let (status, data) = await Self.post(Self.router(), #"[{"jsonrpc":"2.0","id":1,"method":"ping"},{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":2,"method":"ping"}]"#)
        #expect(status == 200)
        let answers = try #require(try PyJSON.parse(data).arrayValue)
        #expect(answers.compactMap { $0.objectValue?["id"] } == [1, 2])
        #expect(await Self.post(Self.router(), #"[{"jsonrpc":"2.0","method":"notifications/initialized"}]"#).0 == 202)
    }

    @Test func theRefusals() async throws {
        let r = Self.router()
        let ping = #"{"jsonrpc":"2.0","id":1,"method":"ping"}"#
        #expect(await Self.post(r, ping, token: nil).0 == 401)
        #expect(await Self.post(r, ping, token: "mcp-0123456789abcdefghiX").0 == 401)
        #expect(await Self.post(r, ping, token: "short").0 == 401)
        #expect(await Self.post(r, ping, origin: "https://evil.example").0 == 403)
        #expect(await Self.post(r, ping, origin: "http://localhost:6274").0 == 200)
        #expect(await Self.post(r, ping, origin: "http://127.0.0.1").0 == 200)
        #expect(await Self.post(r, ping, path: "/").0 == 404)
        #expect(await Self.post(r, ping, method: "GET").0 == 405)
        let (status, data) = await Self.post(r, "{not json")
        #expect(status == 200 && (try? PyJSON.parse(data))?.objectValue?["error"]?.objectValue?["code"] == -32700)
        #expect(r.bodyLimit(method: "POST", path: "/mcp") == 4 * 1024 * 1024 && r.bodyLimit(method: "GET", path: "/") == 0)
        #expect(MCPRouter.same("abc", "abc") && !MCPRouter.same("abc", "abd") && !MCPRouter.same("abc", "abcd"))
    }

    #if canImport(Network)
        /// Over a real connection on 127.0.0.1, as Claude Code talks to it.
        @Test func overTheNetwork() async throws {
            let server = try RemoteServer(router: Self.router(), port: 0, host: "127.0.0.1")
            let port = try await server.start()
            defer { Task { await server.stop() } }
            var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/mcp")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("application/json, text/event-stream", forHTTPHeaderField: "Accept")
            request.setValue("Bearer \(Self.token)", forHTTPHeaderField: "Authorization")
            request.httpBody = Data(#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"say":"über"}}}"#.utf8)
            let (data, response) = try await URLSession.shared.data(for: request)
            #expect((response as? HTTPURLResponse)?.statusCode == 200)
            #expect((response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type") == "application/json")
            let text = try PyJSON.parse(data).objectValue?["result"]?.objectValue?["content"]?.arrayValue?.first?
                .objectValue?["text"]?.stringValue
            #expect(try PyJSON.parse(Data((text ?? "").utf8)) == ["said": "über"])
        }
    #endif
}
