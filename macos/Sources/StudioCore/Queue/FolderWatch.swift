import Foundation
#if canImport(Darwin)
    import Darwin
#elseif canImport(Glibc)
    import Glibc
#endif

/// The watched folder (gui/watch.py): images saved into a chosen folder are sketched by themselves and exported. A
/// new image counts once its size and time have not changed for `stable` seconds (a copy or a camera upload may
/// still be writing it); the images handled are remembered (watch_state.json beside settings.json), so a restart
/// does not sketch them again. This is its bookkeeping – the app's FolderWatcher drives it with its clock.
public struct FolderWatch: Sendable {
    public static let stateFile = "watch_state.json"
    public static let stable = 2.0
    /// seconds between two looks without a change notification (network drives, some sync tools)
    public static let poll = 10.0
    public static let doneDir = "done"
    public static let exportDir = "sketches"
    public static let formats = ["svg", "svg1", "png", "pdf"]

    /// watch.config: the settings of the watched folder.
    public struct Config: Sendable, Equatable {
        public var enabled: Bool
        public var folder: String
        /// "studio" or a preset file
        public var preset: String
        public var formats: [String]
        public var exportDir: String
        public var moveDone: Bool

        public init(_ settings: AppSettings) {
            enabled = settings["watch_enabled"]?.truthy ?? false
            folder = settings["watch_folder"]?.stringValue ?? ""
            preset = settings["watch_preset"].flatMap { $0.truthy ? $0.stringValue : nil } ?? "studio"
            let wanted = (settings["watch_formats"]?.truthy ?? false)
                ? settings["watch_formats"]?.arrayValue?.compactMap(\.stringValue) ?? [] : ["png"]
            let known = wanted.filter { FolderWatch.formats.contains($0) }
            formats = known.isEmpty ? ["png"] : known
            exportDir = settings["watch_export_dir"]?.stringValue ?? ""
            moveDone = settings["watch_move_done"]?.truthy ?? false
        }

        /// on, and the folder is there
        public var active: Bool {
            var isDir: ObjCBool = false
            return enabled && !folder.isEmpty && FileManager.default.fileExists(atPath: folder, isDirectory: &isDir)
                && isDir.boolValue
        }

        /// where the sketches go: the chosen folder, else the watched folder's "sketches"
        public var exportFolder: URL {
            exportDir.isEmpty ? URL(filePath: folder).appending(path: FolderWatch.exportDir, directoryHint: .isDirectory)
                : URL(filePath: exportDir, directoryHint: .isDirectory)
        }
    }

    private struct Pending: Sendable {
        let path: String
        let stamp: [Int]
        let since: Double
    }

    /// path → [size, mtime in ns] of every image handled (as watch_state.json keeps it). The paths are strings as
    /// the folder lists its names (os.listdir) – not URL.path, which takes an "ä" apart.
    public private(set) var state: [String: [Int]]
    private var pending: [String: Pending] = [:]

    public init(state: [String: [Int]] = [:]) {
        self.state = state
    }

    public var hasPending: Bool { !pending.isEmpty }

    /// [size, mtime in ns] of a file (os.stat's st_size and st_mtime_ns); nil when it is not one.
    public static func stamp(_ path: String) -> [Int]? {
        var st = stat()
        guard stat(path, &st) == 0, (st.st_mode & S_IFMT) == S_IFREG else { return nil }
        #if canImport(Darwin)
            let time = st.st_mtimespec
        #else
            let time = st.st_mtim
        #endif
        return [Int(st.st_size), Int(time.tv_sec) * 1_000_000_000 + Int(time.tv_nsec)]
    }

    /// os.path.join of the watched folder and a name it lists.
    public static func join(_ folder: String, _ name: String) -> String {
        folder.hasSuffix("/") ? folder + name : folder + "/" + name
    }

    /// scan: note the folder's new or changed images (`waiting`: the paths queued already).
    public mutating func scan(_ folder: String, waiting: Set<String>, now: Double) {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: folder) else { return }
        for name in names where ImageFiles.isImage(name) {
            let key = Self.join(folder, name)
            guard let stamp = Self.stamp(key) else { continue }
            if waiting.contains(key) || state[key] == stamp { continue }  // queued, or handled before
            if pending[key]?.stamp != stamp {
                pending[key] = Pending(path: key, stamp: stamp, since: now)
            }
        }
    }

    /// _check_pending: the images that stayed unchanged long enough – to be queued now (and remembered with
    /// `handled`); one that went away is forgotten, one still written waits.
    public mutating func ready(now: Double) -> [(path: String, stamp: [Int])] {
        var out: [(path: String, stamp: [Int])] = []
        for (key, p) in pending.sorted(by: { $0.key < $1.key }) {
            guard let stamp = Self.stamp(p.path) else {
                pending[key] = nil  // gone again
                continue
            }
            if stamp != p.stamp || stamp[0] == 0 {
                pending[key] = Pending(path: p.path, stamp: stamp, since: now)  // still being written
            } else if now - p.since >= Self.stable {
                pending[key] = nil
                out.append((p.path, stamp))
            }
        }
        return out
    }

    /// The image is queued: not again, also after a restart.
    public mutating func handled(_ path: String, stamp: [Int]) {
        state[path] = stamp
    }

    public mutating func forgetPending() {
        pending = [:]
    }

    public static func load(_ file: URL) -> FolderWatch {
        guard let data = try? Data(contentsOf: file), let o = try? PyJSON.parse(data).objectValue else {
            return FolderWatch()
        }
        var state: [String: [Int]] = [:]
        for (key, value) in o {
            if let numbers = value.arrayValue?.compactMap(\.intValue), numbers.count == 2 { state[key] = numbers }
        }
        return FolderWatch(state: state)
    }

    /// _save_state: json.dump(state, indent=1), written whole.
    public func save(_ file: URL) {
        let json = JSONValue.object(JSONObject(state.sorted { $0.key < $1.key }.map {
            ($0.key, .array($0.value.map(JSONValue.int)))
        }))
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JobFolder.writeAtomically(PyJSON.dump(json, indent: 1, asciiOnly: true), to: file)
    }

    /// export_batch's file: `<image>_<method><suffix>.<ext>` in `folder`, "_2", "_3" … when it is there (_unique).
    public static func exportFile(target: String, method: String, format: String, in folder: URL) -> URL {
        let stem = (URL(filePath: target).lastPathComponent as NSString).deletingPathExtension
        let suffix = format == "svg1" ? "_1layer" : ""
        let ext = format == "png" || format == "pdf" ? format : "svg"
        let base = "\(stem)_\(method)\(suffix)"
        var url = folder.appending(path: "\(base).\(ext)")
        var n = 2
        while FileManager.default.fileExists(atPath: url.path) {
            url = folder.appending(path: "\(base)_\(n).\(ext)")
            n += 1
        }
        return url
    }

    /// The finished image moved into "done" beside it ("-2", "-3" … when one of that name is there); nil when it
    /// could not be moved.
    @discardableResult
    public static func moveDone(_ image: URL) -> URL? {
        let done = image.deletingLastPathComponent().appending(path: doneDir, directoryHint: .isDirectory)
        let name = image.lastPathComponent
        let stem = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var dest = done.appending(path: name)
        var n = 1
        while FileManager.default.fileExists(atPath: dest.path) {
            n += 1
            dest = done.appending(path: ext.isEmpty ? "\(stem)-\(n)" : "\(stem)-\(n).\(ext)")
        }
        do {
            try FileManager.default.createDirectory(at: done, withIntermediateDirectories: true)
            try FileManager.default.moveItem(at: image, to: dest)
            return dest
        } catch {
            return nil
        }
    }
}
