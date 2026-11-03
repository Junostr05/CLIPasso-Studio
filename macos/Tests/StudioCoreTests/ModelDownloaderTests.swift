import Foundation
import Synchronization
import Testing
@testable import StudioCore

/// A stand-in for HTTP: serves the bytes of its routes, with or without range requests, and can drop a connection.
final class FakeTransport: HTTPTransport {
    struct Route: Sendable {
        var data: Data
        var contentType = "application/octet-stream"
        var honoursRange = true
        /// per attempt: after how many bytes the connection drops (nil: it does not)
        var dropAfter: [Int?] = []
    }

    let routes: Mutex<[String: Route]>
    let requests = Mutex<[(url: String, offset: Int64)]>([])

    init(_ routes: [String: Route]) {
        self.routes = Mutex(routes)
    }

    struct Dropped: Error {}

    func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
        let attempt = requests.withLock { list in
            list.append((url.absoluteString, offset))
            return list.filter { $0.url == url.absoluteString }.count - 1
        }
        guard let route = routes.withLock({ $0[url.absoluteString] }) else {
            return HTTPResponse(status: 404, length: 0, contentType: "text/plain",
                                body: AsyncThrowingStream { $0.finish() })
        }
        let start = route.honoursRange ? Int(offset) : 0
        let rest = route.data.dropFirst(start)
        let drop = attempt < route.dropAfter.count ? route.dropAfter[attempt] : nil
        let body = AsyncThrowingStream<Data, any Error> { continuation in
            var sent = 0
            for chunk in stride(from: rest.startIndex, to: rest.endIndex, by: 65536) {
                var piece = Data(rest[chunk..<min(chunk + 65536, rest.endIndex)])
                if let drop, sent + piece.count > drop {
                    piece = piece.prefix(drop - sent)
                    continuation.yield(piece)
                    continuation.finish(throwing: Dropped())
                    return
                }
                continuation.yield(piece)
                sent += piece.count
            }
            continuation.finish()
        }
        let status = offset > 0 && route.honoursRange ? 206 : 200
        return HTTPResponse(status: status, length: Int64(rest.count), contentType: route.contentType, body: body)
    }
}

@Suite struct ModelDownloaderTests {
    static func bytes(_ n: Int, seed: Int = 1) -> Data {
        Data((0..<n).map { UInt8(($0 * 7 + $0 / 251 + seed) % 256) })
    }

    static func root() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appending(path: "models-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    static func single(_ data: Data, urls: [String], key: String = "test:single") -> ModelSpec {
        ModelSpec(key: key, filename: "test/single.pt", urls: urls, sha256: Sha256.hex(data),
                  downloadSize: Int64(data.count), storedSizeMB: 1, kind: "blazeface")
    }

    static func downloader(_ specs: [ModelSpec], _ root: URL, _ transport: some HTTPTransport,
                           free: Int64? = nil) -> ModelDownloader
    {
        ModelDownloader(catalog: ModelCatalog(models: specs), root: root, transport: transport,
                        freeSpace: { _ in free }, retryDelay: { _ in .milliseconds(1) })
    }

    @Test func sha256KnownValues() {
        #expect(Sha256.hex(Data()) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        #expect(Sha256.hex(Data("abc".utf8)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        #expect(Sha256.hex(Data(repeating: 0x61, count: 1_000_000))
            == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
        var h = Sha256()
        for part in ["a", "bc"] { h.update(Data(part.utf8)) }
        #expect(h.finalize() == Sha256.hex(Data("abc".utf8)))
    }

    @Test func catalogMatchesModelsJSON() throws {
        let catalog = try ModelCatalog.load(Fixtures.url("models.json"))
        let rn101 = try #require(catalog.spec("clip:RN101"))
        #expect(rn101.filename == "clip/RN101.pt" && rn101.sha256?.count == 64 && rn101.urls.count == 2)
        #expect(catalog.models.filter(\.macBundled).map(\.key) == ["blazeface"])
        let birefnet = try #require(catalog.spec("birefnet"))
        #expect(birefnet.kind == "hf" && birefnet.repo == "ZhengPeng7/BiRefNet" && birefnet.files.count == 1)
        #expect(birefnet.files[0].fp16 && birefnet.files[0].size == 444_473_596)
        #expect(ModelCatalog.safeName("clip:ViT-B/32") == "clip_ViT-B_32")
        let root = try Self.root()
        #expect(catalog.spaceNeeded("clip:RN101", root: root) == rn101.downloadSize + 290 * 1_000_000)
    }

    @Test func installedAndUninstall() throws {
        let catalog = try ModelCatalog.load(Fixtures.url("models.json"))
        let root = try Self.root()
        let file = root.appending(path: "clip/RN101.pt")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("x".utf8).write(to: file)
        #expect(catalog.installedURL("clip:RN101", dirs: [root.appending(path: "bundled"), root]) == file)
        try catalog.uninstall("clip:RN101", root: root)
        #expect(catalog.installedURL("clip:RN101", dirs: [root]) == nil)
        let manifest = root.appending(path: "masking/birefnet/manifest.json")
        try FileManager.default.createDirectory(at: manifest.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: manifest)
        try catalog.uninstall("birefnet", root: root)
        #expect(!FileManager.default.fileExists(atPath: manifest.deletingLastPathComponent().path))
    }

    @Test func downloadsAndReportsProgress() async throws {
        let data = Self.bytes(300_000)
        let root = try Self.root()
        let transport = FakeTransport(["https://a/x": .init(data: data)])
        let seen = Mutex<[(Int64, Int64)]>([])
        let raw = try await Self.downloader([Self.single(data, urls: ["https://a/x"])], root, transport)
            .download("test:single") { done, total in seen.withLock { $0.append((done, total)) } }
        #expect(raw == root.appending(path: ".partial/test_single.part"))
        #expect(try Data(contentsOf: raw) == data)
        // every byte counted, then (0, 0): "downloaded, checking" as model_store reports it
        #expect(seen.withLock { $0.contains { $0 == (300_000, 300_000) } && $0.last.map { $0 == (0, 0) } == true })
    }

    @Test func resumesFromPartialFile() async throws {
        let data = Self.bytes(300_000)
        let root = try Self.root()
        let spec = Self.single(data, urls: ["https://a/x"])
        let part = root.appending(path: ".partial/test_single.part")
        try FileManager.default.createDirectory(at: part.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.prefix(100_000).write(to: part)
        let meta: JSONValue = ["size": .int(300_000), "sha256": .string(spec.sha256!), "url": "https://other/x"]
        try Data(PyJSON.dump(meta).utf8).write(to: part.deletingPathExtension().appendingPathExtension("json"))
        let transport = FakeTransport(["https://a/x": .init(data: data)])
        let raw = try await Self.downloader([spec], root, transport).download("test:single") { _, _ in }
        #expect(transport.requests.withLock { $0.map(\.offset) } == [100_000])  // (another mirror's part counts)
        #expect(try Data(contentsOf: raw) == data)
    }

    @Test func restartsWhenRangeIgnored() async throws {
        let data = Self.bytes(200_000)
        let root = try Self.root()
        let spec = Self.single(data, urls: ["https://a/x"])
        let part = root.appending(path: ".partial/test_single.part")
        try FileManager.default.createDirectory(at: part.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.prefix(50_000).write(to: part)
        try Data(PyJSON.dump(["size": 200_000, "sha256": .string(spec.sha256!), "url": "https://a/x"]).utf8)
            .write(to: root.appending(path: ".partial/test_single.json"))
        var route = FakeTransport.Route(data: data)
        route.honoursRange = false
        let raw = try await Self.downloader([spec], root, FakeTransport(["https://a/x": route]))
            .download("test:single") { _, _ in }
        #expect(try Data(contentsOf: raw) == data)  // not appended twice
    }

    @Test func aPartOfAnotherFileStartsOver() async throws {
        let data = Self.bytes(100_000)
        let root = try Self.root()
        let spec = Self.single(data, urls: ["https://a/x"])
        try FileManager.default.createDirectory(at: root.appending(path: ".partial"), withIntermediateDirectories: true)
        try Self.bytes(30_000, seed: 9).write(to: root.appending(path: ".partial/test_single.part"))
        try Data(PyJSON.dump(["size": 5, "sha256": "other", "url": "https://a/x"]).utf8)
            .write(to: root.appending(path: ".partial/test_single.json"))
        let transport = FakeTransport(["https://a/x": .init(data: data)])
        let raw = try await Self.downloader([spec], root, transport).download("test:single") { _, _ in }
        #expect(transport.requests.withLock { $0.map(\.offset) } == [0])
        #expect(try Data(contentsOf: raw) == data)
    }

    @Test func retriesAfterADroppedConnection() async throws {
        let data = Self.bytes(300_000)
        let root = try Self.root()
        var route = FakeTransport.Route(data: data)
        route.dropAfter = [100_000, 50_000]
        let transport = FakeTransport(["https://a/x": route])
        let raw = try await Self.downloader([Self.single(data, urls: ["https://a/x"])], root, transport)
            .download("test:single") { _, _ in }
        #expect(transport.requests.withLock { $0.map(\.offset) } == [0, 100_000, 150_000])
        #expect(try Data(contentsOf: raw) == data)
    }

    @Test func wrongChecksumDeletesAndTriesNextMirror() async throws {
        let data = Self.bytes(100_000)
        let root = try Self.root()
        let transport = FakeTransport(["https://bad/x": .init(data: Self.bytes(100_000, seed: 3)),
                                       "https://good/x": .init(data: data)])
        let raw = try await Self.downloader([Self.single(data, urls: ["https://bad/x", "https://good/x"])], root,
                                            transport).download("test:single") { _, _ in }
        #expect(transport.requests.withLock { $0.map(\.url) } == ["https://bad/x", "https://good/x"])
        #expect(try Data(contentsOf: raw) == data)
    }

    @Test func allMirrorsFail() async throws {
        let root = try Self.root()
        let data = Self.bytes(10)
        await #expect(throws: ModelDownloadError.self) {
            try await Self.downloader([Self.single(data, urls: ["https://none/x"])], root, FakeTransport([:]))
                .download("test:single") { _, _ in }
        }
        do {
            _ = try await Self.downloader([Self.single(data, urls: ["https://none/x"])], root, FakeTransport([:]))
                .download("test:single") { _, _ in }
        } catch let error as ModelDownloadError {
            #expect(error.code == "download_failed" && error.details.contains("https://none/x"))
        }
    }

    @Test func spaceCheck() async throws {
        let data = Self.bytes(100_000)
        let root = try Self.root()
        let transport = FakeTransport(["https://a/x": .init(data: data)])
        do {
            _ = try await Self.downloader([Self.single(data, urls: ["https://a/x"])], root, transport, free: 500_000)
                .download("test:single") { _, _ in }
            Issue.record("no space, but it downloaded")
        } catch let error as ModelDownloadError {
            #expect(error.code == "no_space")  // 100 kB + 1 MB stored, with 5 % margin
        }
        #expect(transport.requests.withLock { $0.isEmpty })
    }

    @Test func hfFilesWithSizes() async throws {
        let weights = Self.bytes(150_000), config = Data("{}".utf8)
        let root = try Self.root()
        let spec = ModelSpec(key: "test:hf", filename: "test/hf/manifest.json", urls: ["https://huggingface.co/org/m"],
                             sha256: nil, downloadSize: 150_000, storedSizeMB: 1, kind: "hf", repo: "org/m",
                             revision: "abc", files: [.init(remote: "w/model.safetensors", local: "model.safetensors",
                                                            size: 150_000, fp16: true, prefix: ""),
                                                      .init(remote: "config.json", local: "config.json", size: nil,
                                                            fp16: false, prefix: "")])
        let base = "https://huggingface.co/org/m/resolve/abc/"
        let transport = FakeTransport([base + "w/model.safetensors": .init(data: weights),
                                       base + "config.json": .init(data: config)])
        let raw = try await Self.downloader([spec], root, transport).download("test:hf") { _, _ in }
        #expect(raw == root.appending(path: ".partial/test_hf"))
        #expect(try String(contentsOf: raw.appending(path: "revision.txt"), encoding: .utf8) == "abc")
        #expect(try Data(contentsOf: raw.appending(path: "w/model.safetensors")) == weights)
        #expect(try Data(contentsOf: raw.appending(path: "config.json")) == config)
        // a file of the wrong size
        let short = FakeTransport([base + "w/model.safetensors": .init(data: weights.prefix(10)),
                                   base + "config.json": .init(data: config)])
        try FileManager.default.removeItem(at: raw)
        do {
            _ = try await Self.downloader([spec], root, short).download("test:hf") { _, _ in }
            Issue.record("a short file was taken")
        } catch let error as ModelDownloadError {
            #expect(error.code == "download_size")
        }
    }

    @Test func gdriveConfirmPage() async throws {
        let data = Self.bytes(120_000)
        let root = try Self.root()
        let page = #"""
        <html><form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
        <input type="hidden" name="id" value="FILE"><input type="hidden" name="export" value="download">
        <input type="hidden" name="confirm" value="t&amp;x"><input type="hidden" name="uuid" value="u1"></form></html>
        """#
        let first = "https://drive.usercontent.google.com/download?id=FILE&export=download"
        let second = "https://drive.usercontent.google.com/download?id=FILE&export=download&confirm=t%26x&uuid=u1"
        let transport = FakeTransport([first: .init(data: Data(page.utf8), contentType: "text/html; charset=utf-8"),
                                       second: .init(data: data)])
        let raw = try await Self.downloader([Self.single(data, urls: ["gdrive:FILE"])], root, transport)
            .download("test:single") { _, _ in }
        #expect(transport.requests.withLock { $0.map(\.url) } == [first, second])
        #expect(try Data(contentsOf: raw) == data)
    }

    @Test func gdriveQuota() async throws {
        let root = try Self.root()
        let first = "https://drive.usercontent.google.com/download?id=FILE&export=download"
        let transport = FakeTransport([first: .init(data: Data("<html>quota</html>".utf8), contentType: "text/html")])
        do {
            _ = try await Self.downloader([Self.single(Self.bytes(5), urls: ["gdrive:FILE"])], root, transport)
                .download("test:single") { _, _ in }
            Issue.record("downloaded a quota page")
        } catch let error as ModelDownloadError {
            #expect(error.code == "download_failed" && error.details.contains("gdrive_quota"))
        }
    }

    @Test func partialLayoutReadableByPython() async throws {
        let data = Self.bytes(100_000)
        let root = try Self.root()
        var route = FakeTransport.Route(data: data)
        route.dropAfter = [1000, 1000, 1000]
        let spec = Self.single(data, urls: ["https://a/x"])
        _ = try? await Self.downloader([spec], root, FakeTransport(["https://a/x": route])).download("test:single") { _, _ in }
        let meta = try String(contentsOf: root.appending(path: ".partial/test_single.json"), encoding: .utf8)
        // json.dumps({"size": …, "sha256": …, "url": …}) of model_store.download_raw
        #expect(meta == #"{"size": 100000, "sha256": "\#(spec.sha256!)", "url": "https://a/x"}"#)
        #expect(try Data(contentsOf: root.appending(path: ".partial/test_single.part")).count == 3000)  // kept
    }

    @Test func realURLSessionWithRangeServer() async throws {
        let script = try #require(Bundle.module.url(forResource: "range_server", withExtension: "py"))
        let server = Process()
        server.executableURL = URL(filePath: "/usr/bin/env")
        server.arguments = ["python3", script.path, "300000"]
        let out = Pipe(), input = Pipe()
        server.standardOutput = out
        server.standardInput = input
        try server.run()
        defer {
            try? input.fileHandleForWriting.close()
            server.terminate()
        }
        var portLine = Data()
        while !portLine.contains(0x0A) {
            portLine.append(out.fileHandleForReading.availableData)
        }
        let port = try #require(Int(String(decoding: portLine, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)))
        let expected = Data((0..<300_000).map { UInt8(($0 * 7 + $0 / 251) % 256) })
        for path in ["file", "norange"] {
            let root = try Self.root()
            let url = "http://127.0.0.1:\(port)/\(path)"
            let spec = Self.single(expected, urls: [url])
            let part = root.appending(path: ".partial/test_single.part")
            try FileManager.default.createDirectory(at: part.deletingLastPathComponent(), withIntermediateDirectories: true)
            try expected.prefix(1000).write(to: part)
            try Data(PyJSON.dump(["size": 300_000, "sha256": .string(spec.sha256!), "url": .string(url)]).utf8)
                .write(to: root.appending(path: ".partial/test_single.json"))
            let raw = try await ModelDownloader(catalog: ModelCatalog(models: [spec]), root: root,
                                                transport: URLSessionTransport(), freeSpace: { _ in nil })
                .download("test:single") { _, _ in }
            #expect(try Data(contentsOf: raw) == expected, "\(path)")
        }
    }
}
