import Foundation
import Synchronization
import Testing
@testable import StudioApp
import StudioCore

/// Serves one file; with `stall`, only its first half – then it waits until the download is cancelled.
final class OneFileTransport: HTTPTransport {
    let data: Data
    let stall: Bool
    let opened = Mutex(0)

    init(_ data: Data, stall: Bool = false) {
        self.data = data
        self.stall = stall
    }

    func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
        opened.withLock { $0 += 1 }
        let rest = data.dropFirst(Int(offset))
        let stall = self.stall
        let body = AsyncThrowingStream<Data, any Error> { continuation in
            let task = Task {
                if stall {
                    continuation.yield(Data(rest.prefix(rest.count / 2)))
                    try? await Task.sleep(for: .seconds(3600))
                    continuation.finish(throwing: CancellationError())
                } else {
                    continuation.yield(Data(rest))
                    continuation.finish()
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
        return HTTPResponse(status: offset > 0 ? 206 : 200, length: Int64(rest.count),
                            contentType: "application/octet-stream", body: body)
    }
}

/// A job that needs a model which is not there: asked first (with its size), downloaded, converted by the engine,
/// then started – and a cancelled download stays for the next time.
@Suite(.serialized) struct ModelFlowTests {
    static let payload = Data((0..<200_000).map { UInt8(truncatingIfNeeded: $0 &* 31 &+ 7) })

    /// The resources with a catalog of one small model ("tiny") and the stand-in engine that needs it.
    static func setup(_ transport: any HTTPTransport) throws -> (AppModel, URL) {
        let dir = FileManager.default.temporaryDirectory.appending(path: "flow-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let catalog: JSONValue = ["format": 1, "partial_dir": ".partial", "groups": [[
            "id": "basic", "title": "ui.models.group.basic", "hint": "ui.models.group_hint.basic",
        ]], "models": [[
            "key": "tiny", "name": "Tiny", "group": "basic", "filename": "tiny/tiny.pt",
            "urls": ["https://models.invalid/tiny.pt"],
            "sha256": .string(Sha256.hex(payload)), "download_size": .int(payload.count), "stored_size_mb": 1,
            "kind": "clip", "mac_bundled": false, "extra": [:],
        ]]]
        let models = dir.appending(path: "models.json")
        try Data(PyJSON.dump(catalog).utf8).write(to: models)
        let base = AppModelTests.resources(engine: SelfTestTests.fake(["needs", "tiny",
                                                                       SelfTestTests.fixtures.appending(path: "jobs/done_clipasso").path]))
        let resources = AppResources(i18n: base.i18n, schema: base.schema, models: models, engine: base.engine)
        let modelsDir = dir.appending(path: "Modelle", directoryHint: .isDirectory)
        let store = try AppModelTests.store(language: "de", ["models_dir": .string(modelsDir.path),
                                                             "output_dir": .string(dir.appending(path: "out").path)])
        let model = try AppModel(resources: resources, store: store, transport: transport)
        return (model, modelsDir)
    }

    static func wait(_ what: String, _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(30)
        while !condition() {
            guard ContinuousClock.now < deadline else {
                Issue.record("timed out waiting for \(what)")
                return
            }
            try await Task.sleep(for: .milliseconds(20))
        }
    }

    @Test func missingModelsAskThenStart() async throws {
        let (model, modelsDir) = try Self.setup(OneFileTransport(Self.payload))
        await model.startEngine()
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()
        #expect(model.models.stage == .asking(["tiny"]))
        #expect(model.queueSnapshot?.jobs.isEmpty ?? true)  // nothing started yet
        #expect(model.models.question(model.texts).contains("Tiny"))  // the names and the size, as the studio asks
        model.confirmDownload()
        try await Self.wait("the download") { model.models.stage == .idle }
        model.cancelDownload()  // (what the sheet's binding does when it closes by itself – no cancel then)
        #expect(FileManager.default.fileExists(atPath: modelsDir.appending(path: "tiny/tiny.pt").path))  // converted
        try await Self.wait("the job") { model.studio.live.status == .done }
        await model.stopEngine()
    }

    /// Images added on the queue page that need a missing model: asked first, as for the studio's job; after the
    /// download they are queued (and the studio's own job is not started) – after a cancel nothing is.
    @Test func queuePageImagesWaitForTheirModels() async throws {
        let (model, _) = try Self.setup(OneFileTransport(Self.payload))
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        model.studio.image = URL(filePath: "/Bilder/Studio.png")
        let images = [URL(filePath: "/Bilder/a.png"), URL(filePath: "/Bilder/b.png")]
        #expect(await model.addToQueue(images) == 0)
        #expect(model.models.stage == .asking(["tiny"]) && (model.queueSnapshot?.jobs.isEmpty ?? true))
        model.cancelDownload()
        #expect(model.models.stage == .idle)
        #expect(await model.addToQueue(images) == 0)  // asked again
        await model.downloadMissingAndStart()
        #expect(model.models.stage == .idle)
        #expect(model.queueSnapshot?.jobs.map(\.target.lastPathComponent) == ["a.png", "b.png"])
        #expect(model.studio.live.jobID == nil)  // not the studio's image
        await model.stopEngine()
    }

    @Test func cancelKeepsPartial() async throws {
        let (model, modelsDir) = try Self.setup(OneFileTransport(Self.payload, stall: true))
        await model.startEngine()
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()
        model.confirmDownload()
        try await Self.wait("half of the file") {
            if case .downloading(_, let done, _) = model.models.stage { return done > 0 }
            return false
        }
        model.cancelDownload()
        try await Self.wait("the cancel") { model.models.stage == .idle }
        let part = modelsDir.appending(path: ".partial/tiny.part")
        let size = (try? FileManager.default.attributesOfItem(atPath: part.path)[.size] as? Int) ?? 0
        #expect(size > 0 && size < Self.payload.count)  // what came so far stays for the next time
        #expect(model.queueSnapshot?.jobs.isEmpty ?? true)
        await model.stopEngine()
    }

    @Test func theModelsPage() async throws {
        let (model, _) = try Self.setup(OneFileTransport(Self.payload))
        await model.startEngine()
        #expect(model.modelState("tiny") == .missing)
        model.downloadModels(["tiny"])
        #expect(model.models.stage == .asking(["tiny"]))
        await model.downloadMissingAndStart()
        #expect(model.models.stage == .idle && model.modelState("tiny") == .installed)
        #expect(model.queueSnapshot?.jobs.isEmpty ?? true)  // a download from the Models page starts no job
        try model.removeModel("tiny")
        #expect(model.modelState("tiny") == .missing)
        await model.stopEngine()
    }

    /// The models from the phone (phone_api 3.8): what the studio's settings need, by task, downloaded on the phone's
    /// request as the window downloads them (no job follows), removed – and the language, the one app setting the
    /// Mac app has yet.
    @Test func theModelsFromThePhone() async throws {
        let (model, modelsDir) = try Self.setup(OneFileTransport(Self.payload))
        await model.startEngine()
        func ask(_ action: String, _ data: JSONObject = [:]) async -> JSONObject? {
            PhoneRemoteTests.json(await model.phoneAnswer(action, data, payload: nil))
        }
        var studio = try #require(await ask("get_studio"))
        #expect(studio["missing"] == ["Tiny"] && studio["missing_mb"] == 0 && studio["download"] == .null)  // (0.2 MB)
        let methods = studio["methods"]?.arrayValue?.compactMap(\.objectValue) ?? []
        #expect(methods.filter { $0["missing"]?.truthy == true }.map { $0["key"]?.stringValue } == [model.studio.method])

        let page = try #require(await ask("get_models"))
        let group = try #require(page["groups"]?.arrayValue?.first?.objectValue)
        let tiny = try #require(group["models"]?.arrayValue?.first?.objectValue)
        #expect(group["name"] == "Grundmodelle" && tiny["key"] == "tiny" && tiny["mb"] == 1)
        #expect(tiny["available"] == false && tiny["used"] == true && tiny["bundled"] == false)
        let role = try #require(page["roles"]?.arrayValue?.first?.objectValue)
        #expect(role["category"] == "Maske" && role["key"] == "mask_model" && role["models"] == ["Tiny"])
        #expect(role["missing"] == ["tiny"] && role["enabled"] == true)
        let choices = role["choices"]?.arrayValue?.compactMap(\.objectValue) ?? []
        #expect(choices.map { $0["value"]?.stringValue } == ["birefnet", "u2net"])
        #expect(choices.map { $0["experimental"]?.truthy } == [false, true])
        #expect(choices.allSatisfy { ($0["label"]?.stringValue ?? "").isEmpty == false })
        #expect(page["download"] == .null)

        #expect(await ask("do_remove_model", ["key": "tiny"])?["error"] == "Ging nicht.")  // (not there)
        #expect(await ask("do_download_models") == ["ok": true, "count": 1])
        let again = await ask("do_download_models", ["keys": ["tiny"]])?["error"]
        #expect(again == "Es läuft schon ein Download." || again == "Es fehlen keine Modelle.")
        try await Self.wait("the download") { model.modelState("tiny") == .installed && model.models.stage == .idle }
        let state = try #require(await ask("get_models")?["download"]?.objectValue)
        #expect(state["status"] == "done" && state["count"] == 1 && state["error"] == "")
        #expect(model.queueSnapshot?.jobs.isEmpty ?? true)  // no job follows
        studio = try #require(await ask("get_studio"))
        #expect(studio["missing"] == [] && studio["download"]?.objectValue?["status"] == "done")
        #expect(await ask("do_download_models")?["error"] == "Es fehlen keine Modelle.")

        #expect(await ask("do_remove_model", ["key": "nope"])?["error"] == "Ging nicht.")
        #expect(await ask("do_remove_model", ["key": "tiny"]) == ["ok": true])
        #expect(model.modelState("tiny") == .missing)
        #expect(!FileManager.default.fileExists(atPath: modelsDir.appending(path: "tiny/tiny.pt").path))

        let settings = try #require(await ask("get_app_settings")?["settings"]?.arrayValue?.first?.objectValue)
        #expect(settings["key"] == "language" && settings["kind"] == "choice" && settings["value"] == "de")
        let languages = settings["choices"]?.arrayValue?.compactMap { $0.objectValue?["value"] } ?? []
        #expect(languages == ["auto", "de", "en"])
        #expect(await ask("do_app_setting", ["key": "notify", "value": true])?["error"] == "Ging nicht.")
        #expect(await ask("do_app_setting", ["key": "language", "value": "fr"])?["error"] == "Ging nicht.")
        #expect(await ask("do_app_setting", ["key": "language", "value": "en"]) == ["ok": true])
        #expect(model.texts.language == "en" && model.settings.language == "en")
        await model.stopEngine()
    }

    /// A download from the phone cancelled from the phone: what came so far stays; the phone hears "cancelled".
    @Test func theModelsFromThePhoneCancelled() async throws {
        let (model, modelsDir) = try Self.setup(OneFileTransport(Self.payload, stall: true))
        await model.startEngine()
        #expect(PhoneRemoteTests.json(await model.phoneAnswer("do_download_models", ["keys": ["tiny", "nope"]],
                                                              payload: nil)) == ["ok": true, "count": 1])
        try await Self.wait("half of the file") {
            if case .downloading(_, let done, _) = model.models.stage { return done > 0 }
            return false
        }
        let running = PhoneRemoteTests.json(await model.phoneAnswer("get_models", [:], payload: nil))?["download"]?
            .objectValue
        #expect(running?["status"] == "running" && running?["name"] == "Tiny" && running?["index"] == 1)
        #expect(PhoneRemoteTests.json(await model.phoneAnswer("do_cancel_download", [:], payload: nil)) == ["ok": true])
        try await Self.wait("the cancel") { model.models.stage == .idle }
        let state = PhoneRemoteTests.json(await model.phoneAnswer("get_models", [:], payload: nil))?["download"]?
            .objectValue
        #expect(state?["status"] == "cancelled")
        #expect(FileManager.default.fileExists(atPath: modelsDir.appending(path: ".partial/tiny.part").path))
        await model.stopEngine()
    }

    @Test func groupsAsExported() throws {
        let catalog = try ModelCatalog.load(SelfTestTests.fixtures.appending(path: "models.json"))
        #expect(catalog.groups.map(\.id).prefix(2) == ["bundled", "basic"])
        #expect(catalog.spec("blazeface")?.group == "bundled" && catalog.spec("clip:RN101")?.group == "basic")
        #expect(catalog.spec("clip:RN101")?.purpose == "ui.models.purpose.rn101")
        let depth = try #require(catalog.models.first { $0.key.hasPrefix("controlnet:") })
        #expect(depth.purpose == "ui.models.purpose.controlnet" && depth.purposeParams["condition"]?.hasPrefix("param.") == true)
        #expect(catalog.groups.allSatisfy { $0.title.hasPrefix("ui.models.group.") })
    }

    @Test func includedComesWithTheApp() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: "bundled-\(UUID().uuidString)")
        let face = dir.appending(path: "blazeface/blazeface.pt")
        try FileManager.default.createDirectory(at: face.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([1, 2, 3]).write(to: face)
        let base = AppModelTests.resources(engine: nil)
        let resources = AppResources(i18n: base.i18n, schema: base.schema, models: base.models, engine: nil,
                                     bundledModels: dir)
        let model = try AppModel(resources: resources, store: AppModelTests.store(language: "en"))
        #expect(model.modelState("blazeface") == .included)
        #expect(model.modelState("clip:RN101") == .missing)
    }
}
