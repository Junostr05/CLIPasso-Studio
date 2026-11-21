import Foundation
import Observation
import StudioCore

/// The app for an AI (Model Context Protocol): a server on this Mac only (127.0.0.1), with a token from the Keychain,
/// on and off in the settings (mcp_on, mcp_port). Its tools do what the window does – the picture, the method and its
/// settings, a sketch started and followed, the results, a sketch as SVG or PNG, an export – and the hardware test.
@Observable
public final class MCPLink {
    public internal(set) var running = false
    public internal(set) var port = 0
    /// why it does not run ("" when fine)
    public internal(set) var error = ""
    @ObservationIgnored var server: RemoteServer?

    public init() {}
}

public extension AppModel {
    nonisolated static let mcpDefaultPort = 47731

    var mcpPort: Int {
        let port = settings["mcp_port"]?.intValue ?? Self.mcpDefaultPort
        return (1024 ... 65535).contains(port) ? port : Self.mcpDefaultPort
    }

    /// The token an AI sends ("Authorization: Bearer …"); made when first needed, kept in the Keychain.
    var mcpToken: String {
        if let t = phone.keys.store.get("mcp_token"), t.count >= 16 { return t }
        let t = RemoteAccess.newToken()
        phone.keys.store.set("mcp_token", t)
        return t
    }

    /// A new token: the AIs set up with the old one have to be set up again.
    func newMCPToken() async {
        phone.keys.store.set("mcp_token", RemoteAccess.newToken())
        await applyMCPSettings()
    }

    /// The line that sets the server up in Claude Code.
    var mcpCommand: String {
        "claude mcp add --transport http clipasso-studio http://127.0.0.1:\(mcp.port == 0 ? mcpPort : mcp.port)/mcp "
            + "--header \"Authorization: Bearer \(mcpToken)\""
    }

    func setMCP(_ on: Bool, port: Int? = nil) async {
        _ = updateSettings {
            $0["mcp_on"] = .bool(on)
            if let port { $0["mcp_port"] = .int(port) }
        }
        await applyMCPSettings()
    }

    /// Starts or stops the server as the settings say (again after a change of port or token).
    func applyMCPSettings() async {
        if let server = mcp.server {
            await server.stop()
            mcp.server = nil
            mcp.running = false
            mcp.port = 0
        }
        guard settings["mcp_on"]?.truthy ?? false else {
            mcp.error = ""
            return
        }
        #if canImport(Network)
            let token = mcpToken
            let router = MCPRouter(token: { token }, tools: Self.mcpTools, version: version,
                                   instructions: Self.mcpInstructions) { [weak self] name, arguments in
                guard let self else { return .error("the app is closing") }
                return await self.mcpCall(name, arguments)
            }
            do {
                let server = try RemoteServer(router: router, port: mcpPort, host: "127.0.0.1")
                mcp.port = try await server.start()
                mcp.server = server
                mcp.running = true
                mcp.error = ""
            } catch {
                mcp.error = texts.tr("ui.phone.port_busy", ["port": "\(mcpPort)", "error": "\(error)"])
            }
        #else
            mcp.error = "no network here"
        #endif
    }

    nonisolated static let mcpInstructions = """
        CLIPasso Studio turns a photo into a line sketch on this Mac (methods: CLIPasso, SwiftSketch, ControlSketch, \
        SceneSketch). Usual flow: set_image (a picture file) → configure (method, preset, settings) → start_sketch with \
        wait=true → get_sketch (SVG or PNG) or export_sketch. list_methods tells the methods, their presets and \
        settings. run_hardware_test measures the CPU against the Apple GPU per method and lets "auto" use the faster \
        one; get_hardware_report shows the last result. Everything happens in the open window: the user sees it.
        """

    nonisolated static let mcpTools: [MCPTool] = {
        func schema(_ properties: JSONObject, required: [String] = []) -> JSONValue {
            var out: JSONObject = ["type": "object", "properties": .object(properties)]
            if !required.isEmpty { out["required"] = .array(required.map(JSONValue.string)) }
            return .object(out)
        }
        let result: JSONValue = ["type": "string", "description": "a result's folder name (list_results); none: the studio's"]
        return [
            MCPTool(name: "get_status", description: "The app's state: engine, studio (picture, method, preset, settings), "
                + "the job running, the queue, the devices and the hardware test's choice."),
            MCPTool(name: "list_methods", description: "The methods with their presets and settings (key, kind, default, "
                + "choices or range, label, help)."),
            MCPTool(name: "set_image", description: "Use a picture file (PNG, JPEG, HEIC …) in the studio.",
                    inputSchema: schema(["path": ["type": "string", "description": "absolute path"]], required: ["path"])),
            MCPTool(name: "configure", description: "Choose the method, a preset and/or settings of the studio; unknown "
                + "settings are named in the answer.",
                    inputSchema: schema(["method": ["type": "string"], "preset": ["type": "string"],
                                         "settings": ["type": "object", "description": "key → value (list_methods)"]])),
            MCPTool(name: "start_sketch", description: "Sketch the studio's picture with its settings. With wait=true the "
                + "answer comes when the job is done (at most timeout_seconds).",
                    inputSchema: schema(["wait": ["type": "boolean"], "timeout_seconds": ["type": "integer"]])),
            MCPTool(name: "get_job", description: "The studio's job: status, progress, time left, its folder; and the queue."),
            MCPTool(name: "cancel_job", description: "Cancel the job that runs."),
            MCPTool(name: "list_results", description: "The results in the output folder, newest first.",
                    inputSchema: schema(["limit": ["type": "integer"], "method": ["type": "string"],
                                         "search": ["type": "string"]])),
            MCPTool(name: "get_sketch", description: "A result's best sketch (or the studio's): SVG text, or a PNG picture.",
                    inputSchema: schema(["result": result, "format": ["type": "string", "enum": ["svg", "png"]],
                                         "size": ["type": "integer", "description": "PNG: longer side in pixels"]])),
            MCPTool(name: "export_sketch", description: "Write a result's sketch as SVG, PNG or PDF with the last export's "
                + "choices (colour, style, paper, frame).",
                    inputSchema: schema(["result": result, "format": ["type": "string", "enum": ["svg", "png", "pdf"]],
                                         "path": ["type": "string", "description": "absolute path of the file"]],
                                        required: ["format", "path"])),
            MCPTool(name: "open_result", description: "Show a result in the studio (its picture, method and sketches).",
                    inputSchema: schema(["result": result], required: ["result"])),
            MCPTool(name: "run_hardware_test", description: "Measure each method on the CPU and on the Apple GPU (time per "
                + "step, quality) – minutes; afterwards \"auto\" computes each method on the better device.",
                    inputSchema: schema(["methods": ["type": "array", "items": ["type": "string"]],
                                         "iterations": ["type": "integer"]])),
            MCPTool(name: "get_hardware_report", description: "The last hardware test: per method the times, the speed-up, "
                + "and where \"auto\" computes."),
        ]
    }()

    /// One tool call (on the main actor, as the window acts).
    func mcpCall(_ name: String, _ a: JSONObject) async -> MCPResult {
        switch name {
        case "get_status": return .json(.object(await mcpStatus()))
        case "list_methods": return .json(mcpMethods())
        case "set_image":
            let path = a["path"]?.stringValue ?? ""
            let url = URL(filePath: path)
            guard path.hasPrefix("/"), FileManager.default.fileExists(atPath: path), PhoneRemote.isPicture(url) else {
                return .error("not a picture file: \(path)")
            }
            studio.image = url
            return .json(["image": .string(path)])
        case "configure": return mcpConfigure(a)
        case "start_sketch": return await mcpStart(a)
        case "get_job": return .json(.object(mcpJob()))
        case "cancel_job":
            await cancelJob()
            return .json(.object(mcpJob()))
        case "list_results": return await mcpResults(a)
        case "get_sketch": return await mcpSketch(a)
        case "export_sketch": return await mcpExport(a)
        case "open_result":
            guard let item = await mcpResult(a) else { return .error("no such result") }
            studio.open(item)
            return .json(["opened": .string(item.jobDir.lastPathComponent)])
        case "run_hardware_test":
            let methods = a["methods"]?.arrayValue?.compactMap(\.stringValue)
            let iterations = min(500, max(3, a["iterations"]?.intValue ?? 40))
            switch await runHardwareTest(methods: methods, iterations: iterations) {
            case .success(let report): return .json(.object(report))
            case .failure(let why): return .error(why.description)
            }
        case "get_hardware_report":
            return .json(hardwareReport.map(JSONValue.object) ?? ["measured": false])
        default:
            return .error("unknown tool \(name)")
        }
    }

    // MARK: - the tools

    private func mcpStatus() async -> JSONObject {
        var devices: JSONValue = .null
        if let engine, let answer = try? await engine.request("devices", timeout: .seconds(10)) { devices = answer }
        let params = (studio.methodSchema?.params ?? []).filter { !$0.hidden && $0.kind != .path }
        return [
            "app_version": .string(version), "engine": .string(engineStatusText), "devices": devices,
            "studio": [
                "image": studio.image.map { JSONValue.string($0.path) } ?? .null,
                "method": .string(studio.method), "preset": studio.preset.map(JSONValue.string) ?? .null,
                "settings": .object(JSONObject(params.map { ($0.key, studio.settings[$0.key] ?? .null) })),
                "can_start": .bool(studio.canStart),
            ],
            "job": .object(mcpJob()),
            "auto_devices": .object(JSONObject(autoDevices.map { ($0.key, JSONValue.string($0.value)) })),
        ]
    }

    private func mcpMethods() -> JSONValue {
        .array(schema.methods.compactMap { id -> JSONValue? in
            guard let m = schema.method(id) else { return nil }
            let params = m.params.filter { !$0.hidden && $0.kind != .path }.map { p -> JSONValue in
                var o: JSONObject = ["key": .string(p.key), "kind": .string(p.kind.rawValue), "default": p.default,
                                     "label": .string(texts.has(p.text.label) ? texts.tr(p.text.label) : p.key),
                                     "advanced": .bool(p.advanced)]
                if let help = p.text.help, texts.has(help) { o["help"] = .string(texts.tr(help)) }
                if !p.choices.isEmpty { o["choices"] = .array(p.choices) }
                if let low = p.minimum { o["min"] = .double(low) }
                if let high = p.maximum { o["max"] = .double(high) }
                return .object(o)
            }
            return ["key": .string(id), "name": .string(m.name), "presets": .array(m.presetOrder.map(JSONValue.string)),
                    "settings": .array(params)]
        })
    }

    private func mcpConfigure(_ a: JSONObject) -> MCPResult {
        if let method = a["method"]?.stringValue {
            guard schema.method(method) != nil else { return .error("unknown method \(method)") }
            studio.selectMethod(method)
        }
        if let preset = a["preset"]?.stringValue {
            guard studio.methodSchema?.presets[preset] != nil else { return .error("unknown preset \(preset)") }
            studio.applyPreset(preset)
        }
        var unknown: [JSONValue] = []
        for (key, value) in a["settings"]?.objectValue ?? [:] {
            if studio.methodSchema?.param(key) != nil { studio.set(key, to: value) } else { unknown.append(.string(key)) }
        }
        return .json(["method": .string(studio.method), "preset": studio.preset.map(JSONValue.string) ?? .null,
                      "settings": .object(studio.settings), "unknown": .array(unknown)])
    }

    private func mcpJob() -> JSONObject {
        let live = studio.live
        let jobs = queueSnapshot?.jobs ?? []
        return [
            "status": live.status.map { JSONValue.string($0.rawValue) } ?? .null,
            "progress": .double((live.progress * 1000).rounded() / 1000),
            "seconds_left": live.eta.map(JSONValue.double) ?? .null,
            "message": .string(live.message),
            "result": live.jobDir.map { JSONValue.string($0.lastPathComponent) } ?? .null,
            "folder": live.jobDir.map { JSONValue.string($0.path) } ?? .null,
            "queue": ["waiting": .int(jobs.filter { $0.status == .queued }.count),
                      "running": .int(jobs.filter(\.isActive).count)],
        ]
    }

    private func mcpStart(_ a: JSONObject) async -> MCPResult {
        guard engine != nil else { return .error("the engine is not running") }
        guard studio.image != nil else { return .error("no picture – set_image first") }
        guard studio.canStart else { return .error("a job of the studio runs already") }
        if let engine, let answer = try? await engine.request("required_models", ["settings": .object(studio.jobSettings)]),
           let missing = answer.objectValue?["missing"]?.arrayValue?.compactMap(\.stringValue), !missing.isEmpty
        {
            return .error("models missing (download them on the Models page): \(missing.joined(separator: ", "))")
        }
        await startSketch()
        guard a["wait"]?.truthy ?? false else { return .json(.object(mcpJob())) }
        let limit = Double(min(7200, max(5, a["timeout_seconds"]?.intValue ?? 900)))
        let end = ContinuousClock.now + .seconds(limit)
        while ContinuousClock.now < end {
            if let status = studio.live.status, [.done, .failed, .cancelled, .interrupted].contains(status) { break }
            try? await Task.sleep(for: .milliseconds(500))
        }
        var out = mcpJob()
        if let dir = studio.live.jobDir, let summary = JobFolder.summary(at: dir) {
            out["clip_score"] = summary.clipScore.map(JSONValue.double) ?? .null
            out["best_sketch"] = JobFolder.bestSketch(summary).map { JSONValue.string($0.path) } ?? .null
        }
        return .json(.object(out))
    }

    private func mcpResults(_ a: JSONObject) async -> MCPResult {
        await gallery.refresh()
        let words = (a["search"]?.stringValue ?? "").lowercased().split(separator: " ").map(String.init)
        let method = a["method"]?.stringValue
        let items = gallery.everything.filter { (method == nil || $0.method == method) && $0.matches(words) }
            .sorted { $0.created > $1.created }.prefix(min(200, max(1, a["limit"]?.intValue ?? 20)))
        return .json(.array(items.map { item -> JSONValue in
            ["result": .string(item.jobDir.lastPathComponent), "name": .string(item.name), "method": .string(item.method),
             "clip_score": item.score.map(JSONValue.double) ?? .null, "strokes": .int(item.strokes),
             "seconds": .double(item.seconds), "created": .string(item.created), "favourite": .bool(item.favourite),
             "best_sketch": item.bestSketch.map { JSONValue.string($0.path) } ?? .null]
        }))
    }

    /// A result by its folder's name.
    private func mcpResult(_ a: JSONObject) async -> GalleryItem? {
        guard let dir = a["result"]?.stringValue else { return nil }
        await gallery.refresh()
        return gallery.everything.first { $0.jobDir.lastPathComponent == dir }
    }

    /// The sketch asked for: a result's best, else the one shown in the studio (or the job's under way).
    private func mcpSVG(_ a: JSONObject) async -> (svg: String, runDir: URL?)? {
        if a["result"] != nil {
            guard let item = await mcpResult(a), let file = item.bestSketch,
                  let svg = try? String(contentsOf: file, encoding: .utf8)
            else { return nil }
            return (svg, Self.bestRunDir(item))
        }
        if let editor = studio.result?.editor { return (editor.svg, editor.runDir) }
        return studio.live.liveSVG.map { ($0, nil) }
    }

    private func mcpSketch(_ a: JSONObject) async -> MCPResult {
        guard let found = await mcpSVG(a) else { return .error("no such sketch") }
        let svg = found.svg
        guard a["format"]?.stringValue == "png" else { return MCPResult([.text(svg)]) }
        #if canImport(CoreGraphics)
            var options = ExportOptions.forClipboard(settings)
            options.size = min(4096, max(64, a["size"]?.intValue ?? 1024))
            let chosen = options
            let stylist = stylist(chosen.style)
            #if canImport(ImageIO)
                let photo = found.runDir.flatMap { SketchFraming.runFrame(runDir: $0) }
            #else
                let photo: SketchFraming.PhotoFrame? = nil
            #endif
            guard let png = try? await Task.detached(executorPreference: OwnThreads.shared, operation: {
                try SketchExporter.png(svg, options: chosen, photo: photo, stylist: stylist)
            }).value
            else { return .error("the sketch could not be drawn") }
            return MCPResult([.image(png, mime: "image/png")])
        #else
            return .error("no pictures here")
        #endif
    }

    private func mcpExport(_ a: JSONObject) async -> MCPResult {
        let path = a["path"]?.stringValue ?? ""
        guard path.hasPrefix("/") else { return .error("path is an absolute path") }
        guard let format = a["format"]?.stringValue.flatMap(ExportOptions.Format.init(rawValue:)),
              [.svg, .png, .pdf].contains(format)
        else { return .error("format is svg, png or pdf") }
        guard let found = await mcpSVG(a) else { return .error("no such sketch") }
        let svg = found.svg
        let options = ExportOptions(settings: settings, format: format)
        let stylist = stylist(options.style)
        let url = URL(filePath: path)
        #if canImport(ImageIO) && canImport(CoreGraphics)
            let photo = found.runDir.flatMap { SketchFraming.runFrame(runDir: $0) }
            do {
                try await Task.detached(executorPreference: OwnThreads.shared) {
                    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                            withIntermediateDirectories: true)
                    let data: Data
                    switch format {
                    case .png: data = try SketchExporter.png(svg, options: options, photo: photo, stylist: stylist)
                    case .pdf: data = try SketchExporter.pdf(svg, options: options, photo: photo,
                                                             title: url.deletingPathExtension().lastPathComponent,
                                                             stylist: stylist)
                    default: data = Data(try SketchExporter.svg(svg, options: options, photo: photo, stylist: stylist).utf8)
                    }
                    try data.write(to: url, options: .atomic)
                }.value
            } catch {
                return .error("the export did not work: \(error)")
            }
            return .json(["written": .string(path)])
        #else
            return .error("no exports here")
        #endif
    }
}
