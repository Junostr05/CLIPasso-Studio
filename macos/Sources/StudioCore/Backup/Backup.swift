import Foundation

/// Backup & move (gui/backup.py): everything of the app in one ".clipbackup" file (a ZIP) – the settings, the queue
/// with its input pictures, the gallery (every job folder with its sketches, albums, names and notes) and, if
/// wanted, the downloaded models – and putting it back on this or another computer, Mac or Windows.
///
/// On restoring, the folders of this computer stay (output folder, model folder …); paths in the queue are moved to
/// them, jobs that are already there are skipped (the same folder name), as are models of the same size. The paths
/// a job saved are moved, too (rewrite_paths).
public enum Backup {
    public static let fileExtension = "clipbackup"
    public static let format = 1
    public static let app = "CLIPasso Studio"
    static let manifestName = "manifest.json"
    static let settingsName = "settings.json"
    static let gallery = "gallery/"
    static let queueInputs = "queue_inputs/"
    static let models = "models/"
    public static let parts = ["settings", "queue", "gallery", "models"]
    /// settings of this computer: never taken over from a backup
    public static let localKeys: Set<String> = [
        "output_dir", "models_dir", "geometry", "gpu_runtime", "gpu_runtime_dismissed", "settings_version",
        "last_version", "skipped_version", "queue", "ui_scale", "watch_folder", "watch_export_dir", "export_dir",
        "batch_export_dir",
    ]
    /// never in a backup file
    public static let secretKeys: Set<String> = ["telegram_token", "telegram_chat", "telegram_bot", "remote_token",
                                                 "remote_pin"]
    /// already compressed: stored as they are (faster)
    static let stored: Set<String> = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".pt", ".pth", ".safetensors",
                                      ".bin", ".onnx", ".zip", ".heic", ".avif"]
    /// storage.INPUT_DIRS: images made in the app, in the output folder
    static let inputDirs: Set<String> = ["_pasted", "_edited", "_webcam", "_continued"]

    public struct Failure: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    /// What a restore did.
    public struct Report: Sendable, Equatable {
        public var settings = false
        /// the queue's entries to add (as settings.json keeps them)
        public var queue: [JSONObject] = []
        public var jobs = 0
        public var skippedJobs = 0
        public var models = 0
    }

    /// storage.result_entries: what moves with the output folder – job folders and the app's image folders, nothing
    /// else (the output folder may hold other files of the user).
    public static func resultEntries(_ root: URL) -> [String] {
        let names = ((try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []).sorted()
        return names.filter { name in
            var isDir: ObjCBool = false
            let path = root.appending(path: name).path
            guard FileManager.default.fileExists(atPath: path, isDirectory: &isDir), isDir.boolValue else {
                return false
            }
            return inputDirs.contains(name) || FileManager.default.fileExists(atPath: path + "/job.json")
                || FileManager.default.fileExists(atPath: path + "/job_state.json")
        }
    }

    /// storage.relocated: `path` below the folder `old` → the same place below `new`.
    public static func relocated(_ path: String, old: String, new: String) -> String {
        guard !path.isEmpty, !old.isEmpty else { return path }
        let base = old.hasSuffix("/") && old.count > 1 ? String(old.dropLast()) : old
        if path == base { return new + "/." }  // (os.path.join(new, "."))
        guard path.hasPrefix(base + "/") else { return path }
        let rest = String(path.dropFirst(base.count + 1))
        return new.hasSuffix("/") ? new + rest : new + "/" + rest
    }

    /// (file, name in the ZIP with "/") of every file below `folder`, sorted by that name.
    public static func files(_ folder: URL) -> [(URL, String)] {
        let manager = FileManager.default
        return ((try? manager.subpathsOfDirectory(atPath: folder.path)) ?? []).sorted().compactMap { rel in
            let url = folder.appending(path: rel)
            let type = (try? manager.attributesOfItem(atPath: url.path))?[.type] as? FileAttributeType
            return type == .typeRegular ? (url, rel) : nil
        }
    }

    public static func size(_ url: URL) -> Int64 {
        ((try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber)?.int64Value ?? 0
    }

    /// _inside: `path` below the folder (not the folder itself).
    static func inside(_ path: String, _ folder: String) -> Bool {
        !folder.isEmpty && path.hasPrefix(folder.hasSuffix("/") ? folder : folder + "/")
    }

    static func timestamp(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.string(from: date)
    }

    /// create: the backup written to `dest`; its manifest. `queue`: the queue's entries as settings.json keeps them
    /// (a picture from outside the output folder travels with the backup). `progress(done, all)` in bytes;
    /// cancelling the task stops it and removes the unfinished file.
    public static func create(_ dest: URL, settings: JSONObject, queue: [JSONObject], outputDir: URL, modelsDir: URL,
                              includeModels: Bool, version: String, now: Date = Date(),
                              progress: (Int64, Int64) -> Void = { _, _ in }) throws -> JSONObject
    {
        let out = outputDir.path
        var todo: [(URL, String)] = []
        let entries = resultEntries(outputDir)
        for name in entries {
            todo += files(outputDir.appending(path: name)).map { ($0.0, "\(gallery)\(name)/\($0.1)") }
        }
        var items: [JSONObject] = []
        for (i, entry) in queue.enumerated() {
            var item = entry
            let target = entry["target"]?.stringValue ?? ""
            var isDir: ObjCBool = false
            if !target.isEmpty, FileManager.default.fileExists(atPath: target, isDirectory: &isDir), !isDir.boolValue,
               !inside(target, out)  // (a picture from elsewhere: it travels with the backup)
            {
                let arc = queueInputs + String(format: "%03d_", i) + (target as NSString).lastPathComponent
                todo.append((URL(filePath: target), arc))
                item["backup_target"] = .string(arc)
            }
            items.append(item)
        }
        if includeModels {
            todo += files(modelsDir).filter { !$0.1.hasPrefix(".partial") }.map { ($0.0, models + $0.1) }
        }
        let total = todo.reduce(Int64(0)) { $0 + size($1.0) }
        var kept = JSONObject(settings.filter { !secretKeys.contains($0.key) }.map { ($0.key, $0.value) })
        kept["queue"] = .array(items.map(JSONValue.object))
        let manifest: JSONObject = [
            "format": .int(format), "app": .string(app), "version": .string(version),
            "created": .string(timestamp(now)), "output_dir": .string(out), "models_dir": .string(modelsDir.path),
            "jobs": .int(entries.filter { !$0.hasPrefix("_") }.count), "queue": .int(items.count),
            "models": .bool(includeModels), "bytes": .int(Int(total)),
        ]
        let zip = try ZipFileWriter(dest)
        do {
            try zip.add(data: Data(PyJSON.dump(.object(manifest), indent: 2).utf8), name: manifestName)
            try zip.add(data: Data(PyJSON.dump(.object(kept), indent: 2).utf8), name: settingsName)
            var done: Int64 = 0
            for (file, arc) in todo {
                try Task.checkCancellation()
                guard FileManager.default.fileExists(atPath: file.path) else { continue }  // (removed meanwhile)
                let ext = "." + file.pathExtension.lowercased()
                try zip.add(file: file, name: arc, store: stored.contains(ext))
                done += size(file)
                progress(done, total)
            }
            try zip.finish()
        } catch {
            zip.abandon()
            try? FileManager.default.removeItem(at: dest)
            throw error
        }
        return manifest
    }

    /// read_manifest: the manifest of a backup file, with "gallery_names" and "has_models".
    public static func readManifest(_ url: URL) throws -> JSONObject {
        let reader: ZipFileReader
        var manifest: JSONObject
        do {
            reader = try ZipFileReader(url)
            guard let entry = reader.entry(manifestName),
                  let o = try PyJSON.parse(reader.data(entry)).objectValue
            else { throw Failure(description: "no manifest") }
            manifest = o
        } catch {
            throw Failure(description: "not a \(app) backup: \(error)")
        }
        if (manifest["format"]?.intValue ?? 0) > format {
            throw Failure(description: "this backup was made by a newer version of the app")
        }
        let names = Set(reader.entries.map(\.name).filter { $0.hasPrefix(gallery) }.map {
            String($0.dropFirst(gallery.count).split(separator: "/", omittingEmptySubsequences: false).first ?? "")
        })
        manifest["gallery_names"] = .array(names.sorted().map(JSONValue.string))
        manifest["has_models"] = .bool(reader.entries.contains { $0.name.hasPrefix(models) })
        return manifest
    }

    /// _safe_target: `root/rel` – nil when `rel` would leave `root` (a damaged or crafted file).
    static func safeTarget(_ root: URL, _ rel: String) -> URL? {
        let base = root.standardizedFileURL.path
        let dest = URL(filePath: base).appending(path: rel).standardizedFileURL
        return dest.path == base || dest.path.hasPrefix(base.hasSuffix("/") ? base : base + "/") ? dest : nil
    }

    /// rewrite_paths: the absolute paths a job saved (job.json, its state, the runs' config.json) moved from below
    /// `old` to below `new`; the number of files changed.
    @discardableResult
    public static func rewritePaths(_ folder: URL, old: String, new: String) -> Int {
        guard !old.isEmpty, old != new else { return 0 }
        func fix(_ v: JSONValue) -> JSONValue {
            switch v {
            case .string(let s): return .string(s.hasPrefix("/") ? relocated(s, old: old, new: new) : s)
            case .array(let a): return .array(a.map(fix))
            case .object(let o): return .object(JSONObject(o.map { ($0.key, fix($0.value)) }))
            default: return v
            }
        }
        var changed = 0
        for (file, _) in files(folder) where file.pathExtension == "json" {
            guard let data = try? Data(contentsOf: file), let json = try? PyJSON.parse(data) else { continue }
            let moved = fix(json)
            guard moved != json else { continue }
            try? JobFolder.writeAtomically(PyJSON.dump(moved, indent: 2), to: file)
            changed += 1
        }
        return changed
    }

    /// restore: the `parts` of a backup put back. The settings change in `settings` (the caller saves them); the
    /// queue's entries are only returned (the caller adds them – not those `known` already: (target, settings)).
    public static func restore(_ url: URL, parts: Set<String> = Set(Backup.parts), settings: inout JSONObject,
                               outputDir: URL, modelsDir: URL, inputsDir: URL, known: [(String, JSONObject)] = [],
                               progress: (Int64, Int64) -> Void = { _, _ in }) throws -> Report
    {
        let manifest = try readManifest(url)
        let reader = try ZipFileReader(url)
        let out = outputDir.path
        let oldOut = manifest["output_dir"]?.stringValue ?? ""
        var report = Report()
        let total = reader.entries.reduce(Int64(0)) { $0 + Int64($1.size) }
        var done: Int64 = 0
        func tick(_ entry: ZipFileReader.Entry) throws {
            done += Int64(entry.size)
            progress(done, total)
            try Task.checkCancellation()
        }
        guard let savedEntry = reader.entry(settingsName),
              let saved = try PyJSON.parse(reader.data(savedEntry)).objectValue
        else { throw Failure(description: "the backup has no settings") }
        if parts.contains("settings") {
            for (key, value) in saved where !localKeys.contains(key) && !secretKeys.contains(key) {
                settings[key] = value
            }
            settings["recent_images"] = .array((saved["recent_images"]?.arrayValue ?? []).map {
                .string(relocated($0.stringValue ?? "", old: oldOut, new: out))
            })
            settings["last_image"] = .string(relocated(saved["last_image"]?.stringValue ?? "", old: oldOut, new: out))
            report.settings = true
        }
        let existing = Set((try? FileManager.default.contentsOfDirectory(atPath: out)) ?? [])
        if parts.contains("gallery") {
            try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
            var skipped = Set<String>()
            for entry in reader.entries where entry.name.hasPrefix(gallery) && !entry.isDirectory {
                let rel = String(entry.name.dropFirst(gallery.count))
                let job = String(rel.split(separator: "/", omittingEmptySubsequences: false).first ?? "")
                if existing.contains(job), !job.hasPrefix("_") {
                    skipped.insert(job)  // the same job is here already
                    continue
                }
                guard let dest = safeTarget(outputDir, rel),
                      !(job.hasPrefix("_") && FileManager.default.fileExists(atPath: dest.path))
                else { continue }
                try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(),
                                                        withIntermediateDirectories: true)
                try reader.extract(entry, to: dest)
                try tick(entry)
            }
            let names = (manifest["gallery_names"]?.arrayValue ?? []).compactMap(\.stringValue)
            let restored = Set(names.filter { !$0.hasPrefix("_") }).subtracting(skipped)
            for name in restored {
                rewritePaths(outputDir.appending(path: name), old: oldOut, new: out)
            }
            (report.jobs, report.skippedJobs) = (restored.count, skipped.count)
        }
        if parts.contains("queue") {
            var seen = known
            for case let .object(original) in saved["queue"]?.arrayValue ?? [] {
                guard let target = original["target"], target.truthy else { continue }
                var item = original
                let arc = item["backup_target"]?.stringValue ?? ""
                item["backup_target"] = nil
                if !arc.isEmpty, let entry = reader.entry(arc) {
                    try FileManager.default.createDirectory(at: inputsDir, withIntermediateDirectories: true)
                    let dest = inputsDir.appending(path: (arc as NSString).lastPathComponent)
                    if !FileManager.default.fileExists(atPath: dest.path) {
                        try reader.extract(entry, to: dest)
                    }
                    item["target"] = .string(dest.path)
                } else {
                    item["target"] = .string(relocated(PhoneStudio.pyStr(target), old: oldOut, new: out))
                }
                for key in ["job_dir", "resume_dir"] {
                    if let value = item[key]?.stringValue, !value.isEmpty {
                        item[key] = .string(relocated(value, old: oldOut, new: out))
                    }
                }
                if var s = item["settings"]?.objectValue, let svg = s["path_svg"]?.stringValue, !svg.isEmpty {
                    s["path_svg"] = .string(relocated(svg, old: oldOut, new: out))
                    item["settings"] = .object(s)
                }
                let key = (item["target"]?.stringValue ?? "", item["settings"]?.objectValue ?? [:])
                if !seen.contains(where: { $0.0 == key.0 && $0.1 == key.1 }) {
                    seen.append(key)
                    report.queue.append(item)
                }
            }
        }
        if parts.contains("models"), manifest["has_models"]?.truthy ?? false {
            for entry in reader.entries where entry.name.hasPrefix(models) && !entry.isDirectory {
                guard let dest = safeTarget(modelsDir, String(entry.name.dropFirst(models.count))) else { continue }
                if FileManager.default.fileExists(atPath: dest.path), size(dest) == Int64(entry.size) { continue }
                try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(),
                                                        withIntermediateDirectories: true)
                let part = dest.appendingPathExtension("part")
                try reader.extract(entry, to: part)
                try? FileManager.default.removeItem(at: dest)
                try FileManager.default.moveItem(at: part, to: dest)
                report.models += 1
                try tick(entry)
            }
        }
        return report
    }

    /// default_name: "CLIPassoStudio-<date>.clipbackup".
    public static func defaultName(_ now: Date = Date()) -> String {
        "CLIPassoStudio-\(String(timestamp(now).prefix(10))).\(fileExtension)"
    }
}
