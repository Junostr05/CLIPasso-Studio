import Foundation
import Testing
@testable import StudioApp
@testable import StudioCore

/// The app for an AI (MCP): off until switched on, then on 127.0.0.1 with the token from the Keychain; its tools do
/// what the window does – the picture, the method and settings, a sketch started and waited for, the results, the
/// sketch as SVG and PNG, an export, the hardware report –, and a new token shuts the old one out.
@Suite(.serialized) struct MCPToolsTests {
    static func json(_ result: MCPResult) -> JSONObject? {
        guard case .text(let text) = result.content.first else { return nil }
        return (try? PyJSON.parse(Data(text.utf8)))?.objectValue
    }

    static func post(port: Int, token: String, _ body: String) async throws -> (Int, JSONObject?) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/mcp")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = Data(body.utf8)
        let (data, response) = try await URLSession.shared.data(for: request)
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, (try? PyJSON.parse(data))?.objectValue)
    }

    @Test func anAIUsesTheApp() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let out = FileManager.default.temporaryDirectory.appending(path: "mcp-\(UUID().uuidString)")
        let secrets = MemorySecrets()
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "en", ["output_dir": .string(out.path)]),
                                 secrets: secrets)
        await model.startEngine()
        #expect(!model.mcp.running && model.mcp.port == 0)  // (off until switched on)

        // the tools, called as the server calls them
        let status = try #require(Self.json(await model.mcpCall("get_status", [:])))
        #expect(status["engine"] != nil && status["studio"]?.objectValue?["image"] == .null)
        let methods = try #require(await model.mcpCall("list_methods", [:]).content.first)
        guard case .text(let methodsText) = methods,
              let list = try PyJSON.parse(Data(methodsText.utf8)).arrayValue
        else { Issue.record("no methods"); return }
        #expect(list.compactMap { $0.objectValue?["key"]?.stringValue } == model.schema.methods)
        let settings = list.first?.objectValue?["settings"]?.arrayValue ?? []
        #expect(!settings.isEmpty && settings.allSatisfy { $0.objectValue?["kind"]?.stringValue != "path" })

        #expect(await model.mcpCall("start_sketch", [:]).isError)  // (no picture yet)
        #expect(await model.mcpCall("set_image", ["path": "/nowhere/x.png"]).isError)
        #expect(await model.mcpCall("set_image", ["path": "relative.png"]).isError)
        let picture = out.appending(path: "Kamel.png")
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "crop/input.png"), to: picture)
        #expect(!(await model.mcpCall("set_image", ["path": .string(picture.path)]).isError))
        #expect(model.studio.image?.path == picture.path)

        #expect(await model.mcpCall("configure", ["method": "nope"]).isError)
        #expect(await model.mcpCall("configure", ["preset": "nope"]).isError)
        let configured = try #require(Self.json(await model.mcpCall("configure", ["settings": ["bogus": 1]])))
        #expect(configured["unknown"] == ["bogus"] && configured["method"] == .string(model.studio.method))

        // a sketch, waited for
        let finished = try #require(Self.json(await model.mcpCall("start_sketch", ["wait": true, "timeout_seconds": 60])))
        #expect(finished["status"] == "done" && finished["result"]?.stringValue?.isEmpty == false)
        #expect(Self.json(await model.mcpCall("get_job", [:]))?["status"] == "done")

        let results = try #require(await model.mcpCall("list_results", ["limit": 5]).content.first)
        guard case .text(let resultsText) = results,
              let found = try PyJSON.parse(Data(resultsText.utf8)).arrayValue, let first = found.first?.objectValue
        else { Issue.record("no results"); return }
        let name = try #require(first["result"]?.stringValue)
        #expect(first["method"] != nil && first["best_sketch"] != .null)

        let svg = await model.mcpCall("get_sketch", ["result": .string(name)])
        guard case .text(let text) = svg.content.first else { Issue.record("no SVG"); return }
        #expect(!svg.isError && text.contains("<svg"))
        #expect(await model.mcpCall("get_sketch", ["result": "no-such-result"]).isError)
        let png = await model.mcpCall("get_sketch", ["result": .string(name), "format": "png", "size": 128])
        guard case .image(let data, "image/png") = png.content.first else { Issue.record("no PNG"); return }
        #expect(data.starts(with: [0x89, 0x50, 0x4E, 0x47]))

        let file = out.appending(path: "export/the sketch.pdf")
        #expect(await model.mcpCall("export_sketch", ["result": .string(name), "format": "gif",
                                                      "path": .string(file.path)]).isError)
        #expect(await model.mcpCall("export_sketch", ["format": "pdf", "path": "relative.pdf"]).isError)
        let written = await model.mcpCall("export_sketch", ["result": .string(name), "format": "pdf",
                                                            "path": .string(file.path)])
        #expect(!written.isError)
        #expect(try Data(contentsOf: file).starts(with: Array("%PDF".utf8)))

        #expect(Self.json(await model.mcpCall("open_result", ["result": .string(name)]))?["opened"] == .string(name))
        #expect(Self.json(await model.mcpCall("get_hardware_report", [:])) == ["measured": false])
        #expect(await model.mcpCall("whatever", [:]).isError)

        // the server: on 127.0.0.1, with the token from the Keychain
        let port = 41000 + Int.random(in: 0 ..< 5000)
        await model.setMCP(true, port: port)
        #expect(model.mcp.running && model.mcp.port == port && model.mcp.error.isEmpty)
        let token = try #require(secrets.get("mcp_token"))
        #expect(token.count >= 16 && model.mcpCommand.contains("--scope user")
            && model.mcpCommand.contains("http://127.0.0.1:\(port)/mcp")
            && model.mcpCommand.contains("Bearer \(token)"))
        #expect(model.settings.description.contains(token) == false)  // (the token is no setting)
        let (code, listed) = try await Self.post(port: port, token: token, #"{"jsonrpc":"2.0","id":1,"method":"tools/list"}"#)
        #expect(code == 200)
        let names = listed?["result"]?.objectValue?["tools"]?.arrayValue?.compactMap { $0.objectValue?["name"]?.stringValue }
        #expect(names == AppModel.mcpTools.map(\.name) && names?.contains("run_hardware_test") == true)
        let (called, answer) = try await Self.post(port: port, token: token,
                                                   #"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_job"}}"#)
        #expect(called == 200 && answer?["result"]?.objectValue?["isError"] == false)

        // a new token: the old one is shut out
        await model.newMCPToken()
        let newToken = try #require(secrets.get("mcp_token"))
        #expect(newToken != token && model.mcp.running)
        #expect(try await Self.post(port: port, token: token, #"{"jsonrpc":"2.0","id":3,"method":"ping"}"#).0 == 401)
        #expect(try await Self.post(port: port, token: newToken, #"{"jsonrpc":"2.0","id":3,"method":"ping"}"#).0 == 200)

        await model.setMCP(false)
        #expect(!model.mcp.running && model.settings["mcp_on"] == false)
        await model.stopEngine()
    }
}
