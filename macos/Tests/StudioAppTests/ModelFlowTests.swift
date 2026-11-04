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
        let catalog: JSONValue = ["format": 1, "partial_dir": ".partial", "models": [[
            "key": "tiny", "name": "Tiny", "filename": "tiny/tiny.pt", "urls": ["https://models.invalid/tiny.pt"],
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
        await model.downloadMissingAndStart()
        #expect(model.models.stage == .idle)
        #expect(FileManager.default.fileExists(atPath: modelsDir.appending(path: ".partial/tiny.part").path))
        try await Self.wait("the job") { model.studio.live.status == .done }
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
}
