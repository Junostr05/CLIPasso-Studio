import Foundation

/// A file of a Hugging Face model (model_store.HFFile).
public struct HFFile: Sendable, Hashable {
    public let remote: String
    public let local: String
    public let size: Int64?
    public let fp16: Bool
    public let prefix: String

    public init(remote: String, local: String, size: Int64?, fp16: Bool, prefix: String) {
        self.remote = remote
        self.local = local
        self.size = size
        self.fp16 = fp16
        self.prefix = prefix
    }
}

/// A model the engine can use (model_store.ModelSpec, from models.json).
public struct ModelSpec: Sendable, Hashable, Identifiable {
    public var id: String { key }
    public let key: String
    /// as the studio names it (methods_ui.model_display_name)
    public let name: String
    /// its group on the Models page (export.mac_group) and what it is for: a text key with the text keys of its
    /// placeholders
    public let group: String
    public let purpose: String
    public let purposeParams: [String: String]
    /// relative to a models folder; for a Hugging Face model its manifest.json
    public let filename: String
    public let urls: [String]
    public let sha256: String?
    public let downloadSize: Int64
    public let storedSizeMB: Int
    public let kind: String
    public let macBundled: Bool
    public let repo: String?
    public let revision: String?
    public let files: [HFFile]
    public let experimental: Bool
    /// "benchmark" for the measurement's judge (model_store's extra purpose)
    public let usage: String?

    public init(key: String, filename: String, urls: [String], sha256: String?, downloadSize: Int64, storedSizeMB: Int,
                kind: String, macBundled: Bool = false, repo: String? = nil, revision: String? = nil,
                files: [HFFile] = [], experimental: Bool = false, purpose: String? = nil, name: String? = nil,
                group: String = "", purposeText: String = "", purposeParams: [String: String] = [:])
    {
        self.key = key
        self.name = name ?? key
        self.group = group
        self.purpose = purposeText
        self.purposeParams = purposeParams
        self.filename = filename
        self.urls = urls
        self.sha256 = sha256
        self.downloadSize = downloadSize
        self.storedSizeMB = storedSizeMB
        self.kind = kind
        self.macBundled = macBundled
        self.repo = repo
        self.revision = revision
        self.files = files
        self.experimental = experimental
        usage = purpose
    }
}

/// A group of the Models page with its title and hint (text keys).
public struct ModelGroup: Sendable, Hashable, Identifiable {
    public let id: String
    public let title: String
    public let hint: String
}

/// Every model of the engine, read from models.json (exported from engine/model_store.py).
public struct ModelCatalog: Sendable {
    public let models: [ModelSpec]
    public let partialDir: String
    /// the groups of the Models page, in order
    public let groups: [ModelGroup]
    private let byKey: [String: ModelSpec]

    public init(models: [ModelSpec], partialDir: String = ".partial", groups: [ModelGroup] = []) {
        self.models = models
        self.partialDir = partialDir
        self.groups = groups
        byKey = Dictionary(models.map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
    }

    public static func load(_ url: URL) throws -> ModelCatalog {
        guard let o = try PyJSON.parse(Data(contentsOf: url)).objectValue, o["format"]?.intValue == 1 else {
            throw ModelDownloadError(code: "bad_catalog", message: "not a model list of format 1", details: "")
        }
        let models = (o["models"]?.arrayValue ?? []).compactMap { item -> ModelSpec? in
            guard let m = item.objectValue, let key = m["key"]?.stringValue, let filename = m["filename"]?.stringValue
            else { return nil }
            let extra = m["extra"]?.objectValue ?? [:]
            let files = (extra["files"]?.arrayValue ?? []).compactMap { f -> HFFile? in
                guard let f = f.objectValue, let remote = f["remote"]?.stringValue, let local = f["local"]?.stringValue
                else { return nil }
                return HFFile(remote: remote, local: local, size: f["size"]?.intValue.map(Int64.init),
                              fp16: f["fp16"]?.boolValue ?? false, prefix: f["prefix"]?.stringValue ?? "")
            }
            return ModelSpec(key: key, filename: filename, urls: m["urls"]?.arrayValue?.compactMap(\.stringValue) ?? [],
                             sha256: m["sha256"]?.stringValue, downloadSize: Int64(m["download_size"]?.intValue ?? 0),
                             storedSizeMB: m["stored_size_mb"]?.intValue ?? 0, kind: m["kind"]?.stringValue ?? "",
                             macBundled: m["mac_bundled"]?.boolValue ?? false, repo: extra["repo"]?.stringValue,
                             revision: extra["revision"]?.stringValue, files: files,
                             experimental: extra["experimental"]?.truthy ?? false,
                             purpose: extra["purpose"]?.stringValue, name: m["name"]?.stringValue,
                             group: m["group"]?.stringValue ?? "", purposeText: m["purpose"]?.stringValue ?? "",
                             purposeParams: (m["purpose_params"]?.objectValue ?? [:]).reduce(into: [:]) {
                                 $0[$1.key] = $1.value.stringValue
                             })
        }
        let groups = (o["groups"]?.arrayValue ?? []).compactMap { g -> ModelGroup? in
            guard let g = g.objectValue, let id = g["id"]?.stringValue else { return nil }
            return ModelGroup(id: id, title: g["title"]?.stringValue ?? id, hint: g["hint"]?.stringValue ?? "")
        }
        return ModelCatalog(models: models, partialDir: o["partial_dir"]?.stringValue ?? ".partial", groups: groups)
    }

    public func spec(_ key: String) -> ModelSpec? { byKey[key] }

    /// model_store._safe_name: the key as a file name.
    public static func safeName(_ key: String) -> String {
        var out = ""
        var inRun = false
        for scalar in key.unicodeScalars {
            let ok = (scalar.isASCII && (CharacterSet.alphanumerics.contains(scalar))) || "._-".unicodeScalars.contains(scalar)
            if ok {
                out.unicodeScalars.append(scalar)
                inRun = false
            } else if !inRun {
                out += "_"
                inRun = true
            }
        }
        return out
    }

    /// model_store.find: where an installed model is (the first folder that has it).
    public func installedURL(_ key: String, dirs: [URL]) -> URL? {
        guard let spec = spec(key) else { return nil }
        for dir in dirs {
            let url = dir.appending(path: spec.filename)
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), !isDir.boolValue { return url }
        }
        return nil
    }

    func partial(_ root: URL) -> URL { root.appending(path: partialDir) }

    /// model_store.space_needed: what is left to download, plus the converted model (the download goes only after
    /// the conversion).
    public func spaceNeeded(_ key: String, root: URL) -> Int64 {
        guard let spec = spec(key) else { return 0 }
        let have: Int64
        if spec.kind == "hf" {
            have = Self.folderSize(partial(root).appending(path: Self.safeName(key)))
        } else {
            let part = partial(root).appending(path: Self.safeName(key) + ".part")
            have = (try? FileManager.default.attributesOfItem(atPath: part.path)[.size] as? NSNumber)?.int64Value ?? 0
        }
        return max(spec.downloadSize - have, 0) + Int64(spec.storedSizeMB) * 1_000_000
    }

    static func folderSize(_ url: URL) -> Int64 {
        guard let walker = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey]) else {
            return 0
        }
        var total: Int64 = 0
        for case let file as URL in walker {
            total += Int64((try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return total
    }

    /// model_store.uninstall: the file – or, for a Hugging Face model, its folder.
    public func uninstall(_ key: String, root: URL) throws {
        guard let spec = spec(key) else { return }
        let target = root.appending(path: spec.filename)
        guard FileManager.default.fileExists(atPath: target.path) else { return }
        try FileManager.default.removeItem(at: spec.kind == "hf" ? target.deletingLastPathComponent() : target)
    }
}
