import Foundation
import Testing
@testable import StudioCore

/// Backup & move (gui/backup.py) – against backup.py itself, run with python3 in a home of its own: what Swift backs
/// up, backup.py puts back exactly as Swift does; what backup.py backs up, Swift puts back as from its own backup.
@Suite(.serialized) struct BackupTests {
    static let repo = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()

    /// A computer: its home, output folder, models, pictures.
    struct Computer {
        let root: URL
        var home: URL { root.appending(path: "home") }
        var out: URL { root.appending(path: "out") }
        var models: URL { root.appending(path: "models") }
        var pictures: URL { root.appending(path: "Bilder") }
        var data: URL { home.appending(path: "Library/Application Support/CLIPassoStudio") }

        init(_ name: String, in base: URL) throws {
            root = base.appending(path: name)
            for dir in [home, out, models, pictures, data] {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            }
        }

        func write(_ text: String, _ rel: String) throws {
            let url = root.appending(path: rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(text.utf8).write(to: url)
        }

        func settings(_ more: JSONObject) throws {
            var s: JSONObject = ["settings_version": 3, "language": "de", "output_dir": .string(out.path),
                                 "tour_done": true]
            for (k, v) in more { s[k] = v }
            try Data(PyJSON.dump(.object(s), indent: 2).utf8).write(to: data.appending(path: "settings.json"))
        }
    }

    /// backup.py with `home` as the user's home: "create DEST" (the manifest) or "restore FILE" (the report).
    static func python(_ computer: Computer, _ mode: String, _ file: URL) throws -> JSONObject {
        let process = Process()
        process.executableURL = URL(filePath: "/usr/bin/env")
        process.arguments = ["python3", "-c", """
        import json, sys
        sys.path.insert(0, sys.argv[1])
        from clipasso_studio.gui import backup
        mode, path = sys.argv[2], sys.argv[3]
        out = backup.create(path, include_models=True) if mode == "create" else backup.restore(path)
        print(json.dumps(out, ensure_ascii=False))
        """, repo.path, mode, file.path]
        process.environment = ProcessInfo.processInfo.environment.merging(
            ["HOME": computer.home.path, "CLIPASSO_DOWNLOADS_DIR": computer.models.path]) { _, new in new }
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        let problem = err.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0, let o = try PyJSON.parse(data).objectValue else {
            throw Backup.Failure(description: String(decoding: problem, as: UTF8.self))
        }
        return o
    }

    /// The source computer: a job whose files name its paths, a picture made in the app, a file and a folder of the
    /// user's own (not backed up), a model and a half download, the queue (one picture from outside), settings with
    /// secrets and settings of this computer.
    static func source(_ base: URL) throws -> (Computer, JSONObject, [JSONObject]) {
        let a = try Computer("A", in: base)
        let job = a.out.appending(path: "Kamel_20260101-120000")
        let run = job.appending(path: "runs/seed_1000")
        try a.write("<svg/>", "out/Kamel_20260101-120000/runs/seed_1000/best_iter.svg")
        try a.write(PyJSON.dump(["target": .string(a.pictures.path + "/Kamel.jpg"),
                                 "best_svg": .string(run.path + "/best_iter.svg"), "method": "clipasso",
                                 "runs": [["run_dir": .string(run.path), "seed": 1000]], "note": "/etc/hosts"],
                                indent: 2), "out/Kamel_20260101-120000/job.json")
        try a.write(PyJSON.dump(["output_dir": .string(run.path), "lr": 1.0], indent: 2),
                    "out/Kamel_20260101-120000/runs/seed_1000/config.json")
        try a.write("png", "out/_pasted/Bär.png")
        try a.write("mine", "out/notizen.txt")
        try a.write("mine", "out/Urlaub/foto.txt")
        try a.write(String(repeating: "w", count: 5000), "models/clip/RN101.pt")
        try a.write("half", "models/.partial/x.part")
        try a.write("jpg", "Bilder/Kamel.jpg")
        let queue: [JSONObject] = [
            ["target": .string(a.pictures.path + "/Kamel.jpg"),
             "settings": ["method": "clipasso", "num_iter": 500, "path_svg": .string(a.out.path + "/_pasted/s.svg")]],
            ["target": .string(a.out.path + "/_pasted/Bär.png"), "settings": ["method": "swiftsketch"],
             "status": "failed", "job_dir": .string(job.path), "message": "Abbruch"],
        ]
        let settings: JSONObject = [
            "language": "de", "telegram_token": "GEHEIM", "remote_pin": "123456", "remote_token": "abc", "watch_folder": "/A/Eingang",
            "recent_images": [.string(a.out.path + "/_pasted/Bär.png"), "/woanders/x.png"],
            "last_image": .string(a.out.path + "/_pasted/Bär.png"), "export_style": "charcoal",
            "user_presets": [["name": "Mein", "method": "clipasso", "settings": [:]]],
        ]
        try a.settings(settings.merging(["queue": .array(queue.map(JSONValue.object))]))
        return (a, settings, queue)
    }

    /// The files of a folder (relative), the root of the computer written as "<root>".
    static func listing(_ c: Computer) -> [String: String] {
        var out: [String: String] = [:]
        for (url, rel) in Backup.files(c.out) + Backup.files(c.models).map({ ($0.0, "models/" + $0.1) }) {
            out[rel] = (try? String(contentsOf: url, encoding: .utf8))?.replacingOccurrences(of: c.root.path, with: "<root>")
        }
        return out
    }

    /// Swift puts `file` back on a new computer `name` (with a job of the same name there already, to be skipped).
    static func restoreHere(_ file: URL, _ name: String, in base: URL, clash: Bool = false) throws
        -> (Computer, Backup.Report, JSONObject)
    {
        let c = try Computer(name, in: base)
        if clash { try c.write("{}", "out/Kamel_20260101-120000/job.json") }
        var settings: JSONObject = ["output_dir": .string(c.out.path), "language": "en", "watch_folder": "/hier"]
        let report = try Backup.restore(file, settings: &settings, outputDir: c.out, modelsDir: c.models,
                                        inputsDir: c.data.appending(path: "restored_inputs"))
        return (c, report, settings)
    }

    static func normalized(_ report: Backup.Report, _ c: Computer) -> JSONValue {
        let text = PyJSON.dump(.array(report.queue.map(JSONValue.object)))
        return ["settings": .bool(report.settings), "jobs": .int(report.jobs), "skipped_jobs": .int(report.skippedJobs),
                "models": .int(report.models),
                "queue": (try? PyJSON.parse(Data(text.replacingOccurrences(of: c.root.path, with: "<root>").utf8)))
                    ?? .null]
    }

    @Test func swiftBacksUpPythonPutsBack() throws {
        let base = FileManager.default.temporaryDirectory.appending(path: "backup-\(UUID().uuidString)")
        let (a, settings, queue) = try Self.source(base)
        let file = base.appending(path: Backup.defaultName())
        var stored = settings
        stored["output_dir"] = .string(a.out.path)
        let manifest = try Backup.create(file, settings: stored, queue: queue, outputDir: a.out, modelsDir: a.models,
                                         includeModels: true, version: "4.4.0")
        #expect(manifest["jobs"] == 1 && manifest["queue"] == 2 && manifest["models"] == true)
        let read = try Backup.readManifest(file)
        #expect(read["gallery_names"] == ["Kamel_20260101-120000", "_pasted"] && read["has_models"] == true)
        let zip = try ZipFileReader(file)
        let names = zip.entries.map(\.name)
        #expect(names.contains("queue_inputs/000_Kamel.jpg") && !names.contains { $0.contains("notizen") }
            && !names.contains { $0.contains("Urlaub") || $0.contains(".partial") })
        let kept = try zip.data(try #require(zip.entry("settings.json")))
        let text = String(decoding: kept, as: UTF8.self)
        #expect(!text.contains("GEHEIM") && !text.contains("123456") && !text.contains("remote_token"))

        // backup.py on another computer
        let b = try Computer("B", in: base)
        try b.settings(["language": "en", "watch_folder": "/hier"])
        let python = try Self.python(b, "restore", file)
        let (c, report, after) = try Self.restoreHere(file, "C", in: base)
        #expect(Self.normalized(report, c) == Self.normalized(Backup.Report(
            settings: python["settings"]?.truthy ?? false,
            queue: (python["queue"]?.arrayValue ?? []).compactMap(\.objectValue), jobs: python["jobs"]?.intValue ?? -1,
            skippedJobs: python["skipped_jobs"]?.intValue ?? -1, models: python["models"]?.intValue ?? -1), b))
        #expect(Self.listing(c) == Self.listing(b) && Self.listing(c).count == 5)
        #expect(Self.listing(c)["Kamel_20260101-120000/job.json"]?.contains("<root>/out/Kamel_20260101-120000/runs")
            == true)  // (moved to this computer's output folder)
        #expect(report.queue.first?["target"]?.stringValue?.hasSuffix("restored_inputs/000_Kamel.jpg") == true)
        // the settings: the backup's, but not those of this computer, and no secrets
        #expect(after["export_style"] == "charcoal" && after["language"] == "de" && after["watch_folder"] == "/hier")
        #expect(after["telegram_token"] == nil && after["output_dir"] == .string(c.out.path))
        #expect(after["recent_images"] == [.string(c.out.path + "/_pasted/Bär.png"), "/woanders/x.png"])

        // again: the job is there, the model too – skipped; the queue entries known are not added twice
        let again = try Self.restoreHere(file, "C2", in: base, clash: true)
        #expect(again.1.jobs == 0 && again.1.skippedJobs == 1)
    }

    @Test func pythonBacksUpSwiftPutsBack() throws {
        let base = FileManager.default.temporaryDirectory.appending(path: "backup-\(UUID().uuidString)")
        let (a, settings, queue) = try Self.source(base)
        let fromPython = base.appending(path: "python.clipbackup")
        let manifest = try Self.python(a, "create", fromPython)
        #expect(manifest["jobs"] == 1 && manifest["queue"] == 2 && manifest["output_dir"] == .string(a.out.path))
        let fromSwift = base.appending(path: "swift.clipbackup")
        _ = try Backup.create(fromSwift, settings: settings.merging(["output_dir": .string(a.out.path)]), queue: queue,
                              outputDir: a.out, modelsDir: a.models, includeModels: true, version: "4.4.0")
        let (p, pReport, pSettings) = try Self.restoreHere(fromPython, "P", in: base)
        let (s, sReport, _) = try Self.restoreHere(fromSwift, "S", in: base)
        #expect(Self.normalized(pReport, p) == Self.normalized(sReport, s))
        #expect(Self.listing(p) == Self.listing(s))
        #expect(pSettings["export_style"] == "charcoal" && pSettings["telegram_token"] == nil)
    }

    @Test func relocatedAndSafe() {
        #expect(Backup.relocated("/A/out/x/y.png", old: "/A/out", new: "/B/out") == "/B/out/x/y.png")
        #expect(Backup.relocated("/A/outside.png", old: "/A/out", new: "/B/out") == "/A/outside.png")
        #expect(Backup.relocated("/A/out", old: "/A/out/", new: "/B/out") == "/B/out/.")
        #expect(Backup.relocated("", old: "/A/out", new: "/B") == "")
        let root = URL(filePath: "/B/out")
        #expect(Backup.safeTarget(root, "job/a.svg")?.path == "/B/out/job/a.svg")
        #expect(Backup.safeTarget(root, "../../etc/passwd") == nil)
    }
}
