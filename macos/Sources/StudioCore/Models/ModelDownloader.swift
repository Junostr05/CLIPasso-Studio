import Foundation

/// A download that did not succeed: `download_failed` (with what each mirror said), `download_size`, `no_space` – the
/// codes of model_store's UserErrors, so the app shows the same texts (ui.err.<code>).
public struct ModelDownloadError: Error, Sendable, Hashable, CustomStringConvertible {
    public let code: String
    public let message: String
    public let details: String

    public var description: String { "\(code): \(message)" + (details.isEmpty ? "" : "\n\(details)") }
}

/// Downloads a model's raw file(s) into the partial folder exactly where and how engine/model_store.py does –
/// `.partial/<key>.part` with `.partial/<key>.json` ({size, sha256, url}), a Hugging Face model in `.partial/<key>/`
/// with `revision.txt` – so either side continues a download the other began. Resumable (range requests; a server
/// that ignores them is started over), three tries per mirror, the checksum or size checked, a wrong file deleted and
/// the next mirror tried, Google Drive's "can't scan for viruses" page followed, the free space checked first. The
/// engine converts the result (`convert_model`).
public actor ModelDownloader {
    public let catalog: ModelCatalog
    public let root: URL
    private let transport: any HTTPTransport
    private let freeSpace: @Sendable (URL) -> Int64?
    private let retryDelay: @Sendable (Int) -> Duration
    static let spaceMargin = 1.05  // fileops.SPACE_MARGIN
    static let attempts = 3  // per mirror (download_raw)
    static let hfAttempts = 4  // per file (_hf_download)

    public init(catalog: ModelCatalog, root: URL, transport: any HTTPTransport = URLSessionTransport(),
                freeSpace: @escaping @Sendable (URL) -> Int64? = { Disk.freeSpace(at: $0) },
                retryDelay: @escaping @Sendable (Int) -> Duration = { .seconds(min(1 << $0, 8)) })
    {
        self.catalog = catalog
        self.root = root
        self.transport = transport
        self.freeSpace = freeSpace
        self.retryDelay = retryDelay
    }

    /// Download `key`; returns the raw file (or the folder of a Hugging Face model) in the partial folder. A cancel
    /// (the calling task) keeps what came so far for the next time.
    public func download(_ key: String, progress: @escaping @Sendable (Int64, Int64) -> Void) async throws -> URL {
        guard let spec = catalog.spec(key) else {
            throw ModelDownloadError(code: "download_failed", message: "unknown model \(key)", details: "")
        }
        let needed = Int64(Double(catalog.spaceNeeded(key, root: root)) * Self.spaceMargin)
        if let free = freeSpace(root), free < needed {
            throw ModelDownloadError(code: "no_space", message: String(format: "not enough free space in %@: %.1f GB needed, %.1f GB free",
                                                                       root.path, Double(needed) / 1e9, Double(free) / 1e9),
                                     details: "")
        }
        let partial = catalog.partial(root)
        try FileManager.default.createDirectory(at: partial, withIntermediateDirectories: true)
        return spec.kind == "hf" ? try await downloadHF(spec, into: partial, progress)
            : try await downloadFile(spec, into: partial, progress)
    }

    // MARK: - one file (download_raw)

    private func downloadFile(_ spec: ModelSpec, into partial: URL,
                              _ progress: @escaping @Sendable (Int64, Int64) -> Void) async throws -> URL
    {
        let target = partial.appending(path: ModelCatalog.safeName(spec.key) + ".part")
        let meta = partial.appending(path: ModelCatalog.safeName(spec.key) + ".json")
        var errors: [String] = []
        for url in spec.urls {
            let info: JSONObject = ["size": .int(Int(spec.downloadSize)), "sha256": spec.sha256.map(JSONValue.string) ?? .null]
            let saved = (try? PyJSON.parse(Data(contentsOf: meta)))?.objectValue
            if saved?["size"] != info["size"] || saved?["sha256"] != info["sha256"] {  // another file: start over
                try? FileManager.default.removeItem(at: target)
            }
            try Data(PyJSON.dump(.object(info.merging(["url": .string(url)]))).utf8).write(to: meta)
            var failure: String?
            for attempt in 0..<Self.attempts {
                do {
                    try await fetch(url, to: target, progress)
                    failure = nil
                    break
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    failure = "\(error)"
                    if attempt < Self.attempts - 1 { try await Task.sleep(for: retryDelay(attempt)) }
                }
            }
            if let failure {
                errors.append("\(url): \(failure)")
                continue
            }
            progress(0, 0)  // downloaded; checking takes a moment
            let size = fileSize(target)
            if let sha = spec.sha256 {
                let digest = try Sha256.hex(of: target)
                if digest != sha {
                    errors.append("\(url): sha256 mismatch (\(digest))")
                    try? FileManager.default.removeItem(at: target)
                    continue
                }
            } else if abs(size - spec.downloadSize) > 1024 {
                errors.append("\(url): unexpected size \(size)")
                try? FileManager.default.removeItem(at: target)
                continue
            }
            return target
        }
        let details = errors.joined(separator: "\n")
        throw ModelDownloadError(code: "download_failed", message: "Could not download \(spec.key)", details: details)
    }

    private func fileSize(_ url: URL) -> Int64 {
        ((try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber)?.int64Value ?? 0
    }

    struct HTTPStatus: Error, CustomStringConvertible {
        let status: Int
        var description: String { "HTTP \(status)" }
    }

    struct ConnectionLost: Error, CustomStringConvertible {
        let done: Int64, total: Int64
        var description: String { "connection lost after \(done) of \(total) bytes" }
    }

    /// _download_url: stream `url` into `target`, continuing from its size (Google Drive starts over).
    private func fetch(_ url: String, to target: URL, _ progress: @escaping @Sendable (Int64, Int64) -> Void) async throws {
        var offset = FileManager.default.fileExists(atPath: target.path) ? fileSize(target) : 0
        let response: HTTPResponse
        if url.hasPrefix("gdrive:") {
            response = try await GoogleDrive.open(fileID: String(url.dropFirst("gdrive:".count)), transport)
            offset = 0
        } else {
            guard let u = URL(string: url) else { throw HTTPStatus(status: 0) }
            response = try await transport.open(u, offset: offset)
            if offset > 0, response.status == 416 { return }  // nothing left: complete
            if response.status != 206 { offset = 0 }  // the server ignored the range
        }
        guard (200..<300).contains(response.status) else { throw HTTPStatus(status: response.status) }
        if offset == 0 {
            _ = FileManager.default.createFile(atPath: target.path, contents: nil)
        }
        let out = try FileHandle(forWritingTo: target)
        defer { try? out.close() }
        try out.seek(toOffset: UInt64(offset))
        try out.truncate(atOffset: UInt64(offset))
        let total = (response.length ?? 0) + offset
        var done = offset
        for try await chunk in response.body {
            try Task.checkCancellation()
            try out.write(contentsOf: chunk)
            done += Int64(chunk.count)
            progress(done, total)
        }
        if response.length != nil, done < total { throw ConnectionLost(done: done, total: total) }
    }

    // MARK: - a Hugging Face model (download_hf_raw)

    private func downloadHF(_ spec: ModelSpec, into partial: URL,
                            _ progress: @escaping @Sendable (Int64, Int64) -> Void) async throws -> URL
    {
        guard let repo = spec.repo, let revision = spec.revision else {
            throw ModelDownloadError(code: "download_failed", message: "\(spec.key) has no repository", details: "")
        }
        let rawDir = partial.appending(path: ModelCatalog.safeName(spec.key))
        let stamp = rawDir.appending(path: "revision.txt")
        if FileManager.default.fileExists(atPath: rawDir.path),
           (try? String(contentsOf: stamp, encoding: .utf8)) != revision
        {
            try FileManager.default.removeItem(at: rawDir)
        }
        try FileManager.default.createDirectory(at: rawDir, withIntermediateDirectories: true)
        try Data(revision.utf8).write(to: stamp)
        let total = max(spec.files.reduce(Int64(0)) { $0 + ($1.size ?? 0) }, 1)
        var done: Int64 = 0
        for file in spec.files {
            let target = rawDir.appending(path: file.remote)
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: target.path), file.size == nil || fileSize(target) > file.size! {
                try FileManager.default.removeItem(at: target)  // unknown or impossible size: start over
            }
            let base = done
            let url = "https://huggingface.co/\(repo)/resolve/\(revision)/\(file.remote)"
            for attempt in 0..<Self.hfAttempts {
                if let size = file.size, fileSize(target) == size, FileManager.default.fileExists(atPath: target.path) {
                    break
                }
                do {
                    try await fetch(url, to: target) { d, _ in progress(min(base + d, total), total) }
                    break
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    if attempt == Self.hfAttempts - 1 {
                        throw ModelDownloadError(code: "download_failed", message: "Could not download \(spec.key)",
                                                 details: "\(url): \(error)")
                    }
                    try await Task.sleep(for: retryDelay(attempt))
                }
            }
            let size = fileSize(target)
            if let want = file.size, size != want {
                throw ModelDownloadError(code: "download_size",
                                         message: "Could not download \(spec.key): \(file.remote) has \(size) bytes, expected \(want)",
                                         details: file.remote)
            }
            done += file.size ?? size
        }
        progress(0, 0)  // downloaded; the engine converts it
        return rawDir
    }
}

/// Google Drive: a file larger than about 100 MB answers with a "can't scan this file for viruses" page first; its
/// download form leads to the file (model_store._open_gdrive).
enum GoogleDrive {
    struct Refused: Error, CustomStringConvertible {
        let code: String
        var description: String {
            code == "gdrive_quota"
                ? "gdrive_quota: Google Drive refused the download (daily quota exceeded?) – try again later"
                : "gdrive_no_start: Google Drive did not start the download"
        }
    }

    static func open(fileID: String, _ transport: any HTTPTransport) async throws -> HTTPResponse {
        var url = "https://drive.usercontent.google.com/download?" + urlencode([("id", fileID), ("export", "download")])
        for _ in 0..<3 {
            guard let u = URL(string: url) else { throw Refused(code: "gdrive_no_start") }
            let response = try await transport.open(u, offset: 0)
            guard (response.contentType ?? "").contains("text/html") else { return response }
            var page = Data()
            for try await chunk in response.body {
                page.append(chunk)
                if page.count > 2_000_000 { break }
            }
            let text = String(decoding: page, as: UTF8.self)
            guard let action = firstMatch(#"<form[^>]*id="download-form"[^>]*action="([^"]+)""#, in: text)?.first
            else { throw Refused(code: "gdrive_quota") }
            let fields = allMatches(#"<input type="hidden" name="([^"]+)" value="([^"]*)""#, in: text)
                .map { (unescape($0[0]), unescape($0[1])) }
            url = unescape(action) + "?" + urlencode(fields)
        }
        throw Refused(code: "gdrive_no_start")
    }

    static func firstMatch(_ pattern: String, in text: String) -> [String]? {
        allMatches(pattern, in: text).first
    }

    static func allMatches(_ pattern: String, in text: String) -> [[String]] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(text.startIndex..., in: text)
        return regex.matches(in: text, range: range).map { match in
            (1..<match.numberOfRanges).compactMap { Range(match.range(at: $0), in: text).map { String(text[$0]) } }
        }
    }

    /// html.unescape for what such a page holds.
    static func unescape(_ s: String) -> String {
        var out = s
        for (entity, char) in [("&quot;", "\""), ("&#39;", "'"), ("&#x27;", "'"), ("&lt;", "<"), ("&gt;", ">"),
                               ("&amp;", "&")]
        {
            out = out.replacingOccurrences(of: entity, with: char)
        }
        return out
    }

    /// urllib.parse.urlencode (quote_plus).
    static func urlencode(_ pairs: [(String, String)]) -> String {
        let safe = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~ ")
        func quote(_ s: String) -> String {
            (s.addingPercentEncoding(withAllowedCharacters: safe) ?? s).replacingOccurrences(of: " ", with: "+")
        }
        return pairs.map { quote($0.0) + "=" + quote($0.1) }.joined(separator: "&")
    }
}

/// Free space on the drive of a folder (the nearest one that exists).
public enum Disk {
    public static func freeSpace(at url: URL) -> Int64? {
        var dir = url
        while !FileManager.default.fileExists(atPath: dir.path), dir.pathComponents.count > 1 {
            dir = dir.deletingLastPathComponent()
        }
        #if os(macOS)
            if let free = try? dir.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
                .volumeAvailableCapacityForImportantUsage
            {
                return free
            }
        #endif
        guard let attrs = try? FileManager.default.attributesOfFileSystem(forPath: dir.path),
              let free = attrs[.systemFreeSize] as? NSNumber
        else { return nil }
        return free.int64Value
    }
}
