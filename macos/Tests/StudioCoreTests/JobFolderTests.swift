import Foundation
import Testing
@testable import StudioCore

/// The job folders are read and written exactly as engine/jobs.py does – results move between Windows and Mac.
@Suite struct JobFolderTests {
    /// A copy of the Python-made job folders in a temporary folder (the tests change them).
    static func copyOfJobs() throws -> URL {
        let dest = FileManager.default.temporaryDirectory
            .appending(path: "studiocore-jobs-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dest, withIntermediateDirectories: true)
        let jobs = dest.appending(path: "jobs")
        try FileManager.default.copyItem(at: Fixtures.url("jobs"), to: jobs)
        return jobs
    }

    /// A summary with the copy's folder written as `{jobs}` (as in jobs_expected.json).
    static func placeholder(_ value: JSONValue, root: String) -> JSONValue {
        switch value {
        case .string(let s) where s.hasPrefix(root):
            return .string("{jobs}" + s.dropFirst(root.count).replacingOccurrences(of: "\\", with: "/"))
        case .array(let items):
            return .array(items.map { placeholder($0, root: root) })
        case .object(let o):
            return .object(JSONObject(o.map { ($0.key, placeholder($0.value, root: root)) }))
        default:
            return value
        }
    }

    @Test func summariesMatchPython() throws {
        let jobs = try Self.copyOfJobs()
        let expected = try #require(Fixtures.json("jobs_expected.json").objectValue)
        #expect(expected.count == 5)
        for (name, want) in expected {
            let got = try #require(JobFolder.summaryJSON(at: jobs.appending(path: name)), "\(name)")
            #expect(Self.placeholder(.object(got), root: jobs.path) == want, "\(name)")
        }
    }

    @Test func aFolderWithoutJobFilesHasNoSummary() throws {
        let empty = try Self.copyOfJobs().appending(path: "empty")
        try FileManager.default.createDirectory(at: empty, withIntermediateDirectories: true)
        #expect(JobFolder.summaryJSON(at: empty) == nil)
    }

    @Test func windowsPathsAreRebased() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "windows_paths")
        let windows = #"C:\Users\Jürgen\Documents\CLIPasso Studio\windows_paths\Giraffe_16strokes_seed0\best_iter.svg"#
        #expect(rebase(windows, jobDir: jobDir) == jobDir.path + "/Giraffe_16strokes_seed0/best_iter.svg")
        let mac = "/Users/studio/Documents/CLIPasso Studio/windows_paths/Giraffe_16strokes_seed0_best.svg"
        #expect(rebase(mac, jobDir: jobDir) == jobDir.path + "/Giraffe_16strokes_seed0_best.svg")
        #expect(rebase(#"C:\elsewhere\x.svg"#, jobDir: jobDir) == #"C:\elsewhere\x.svg"#)  // not in the folder
        #expect(rebase("", jobDir: jobDir) == "")
        let here = jobDir.appending(path: "job.json").path
        #expect(rebase(here, jobDir: jobDir) == here)  // exists: as it is
        #expect(rebase(#"C:\x\windows_paths"#, jobDir: jobDir) == jobDir.path)  // the folder itself
    }

    @Test func metaIsRewrittenByteForByte() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "done_clipasso")
        let before = try Data(contentsOf: jobDir.appending(path: "meta.json"))  // written by Python
        _ = try JobFolder.writeMeta(at: jobDir, [])
        #expect(try Data(contentsOf: jobDir.appending(path: "meta.json")) == before)
    }

    @Test func writeMetaKeepsOtherKeysAndRemovesNil() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "done_clipasso")
        let meta = try JobFolder.writeMeta(at: jobDir, [("favourite", nil), ("title", .string("Neu – ✏️")),
                                                        ("tags", ["Tier", "Abend"])])
        #expect(meta["favourite"] == nil && meta["title"] == .string("Neu – ✏️"))
        #expect(meta.keys == ["title", "notes", "tags", "albums", "ratings"])  // places kept, the favourite gone
        #expect(JobFolder.readMeta(at: jobDir) == meta)
        let text = try String(contentsOf: jobDir.appending(path: "meta.json"), encoding: .utf8)
        #expect(text == PyJSON.dump(.object(meta), indent: 2))  // json.dump(…, indent=2, ensure_ascii=False)
        #expect(!FileManager.default.fileExists(atPath: jobDir.appending(path: "meta.json.tmp").path))
        try Self.exportForPython("meta_roundtrip", jobDir: jobDir, meta: meta)
    }

    @Test func writeMetaRejectsOtherKeys() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "done_clipasso")
        #expect(throws: JobFolder.UnknownMetaKey.self) { try JobFolder.writeMeta(at: jobDir, [("colour", "red")]) }
    }

    @Test func readMetaDropsOtherKeysAndCopesWithDamage() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "done_clipasso")
        try Data(#"{"title": "x", "secret": 1}"#.utf8).write(to: jobDir.appending(path: "meta.json"))
        #expect(JobFolder.readMeta(at: jobDir) == ["title": "x"])
        try Data("{broken".utf8).write(to: jobDir.appending(path: "meta.json"))
        #expect(JobFolder.readMeta(at: jobDir).isEmpty)
    }

    @Test func setStatusChangesOnlyTheStatus() throws {
        let jobDir = try Self.copyOfJobs().appending(path: "interrupted_swiftsketch")
        let before = try #require(JobFolder.readState(at: jobDir))
        try JobFolder.setStatus(at: jobDir, "cancelled")
        let after = try #require(JobFolder.readState(at: jobDir))
        #expect(after["status"] == .string("cancelled"))
        var same = after
        same["status"] = before["status"]
        #expect(same == before)
        let text = try String(contentsOf: jobDir.appending(path: "job_state.json"), encoding: .utf8)
        #expect(text == PyJSON.dump(.object(after), indent: 2, asciiOnly: true))  // json.dump(…, indent=2)
        #expect(!FileManager.default.fileExists(atPath: jobDir.appending(path: "job_state.json.tmp").path))
    }

    @Test func continueAndBestSketch() throws {
        let jobs = try Self.copyOfJobs()
        let interrupted = try #require(JobFolder.summary(at: jobs.appending(path: "interrupted_swiftsketch")))
        #expect(interrupted.state == "interrupted" && interrupted.progress?.done == 1 && interrupted.progress?.total == 4)
        #expect(JobFolder.canContinue(interrupted))
        let done = try #require(JobFolder.summary(at: jobs.appending(path: "done_clipasso")))
        #expect(!JobFolder.canContinue(done))
        #expect(done.title == "Kamel am Abend – Skizze ✏️" && done.favourite && done.tags == ["Tier", "Wüste"])
        #expect(done.bestRun == "Kamel_16strokes_seed1000")
        #expect(JobFolder.bestSketch(done)?.lastPathComponent == "edited.svg")  // the touched-up one
        let windows = try #require(JobFolder.summary(at: jobs.appending(path: "windows_paths")))
        #expect(JobFolder.bestSketch(windows)?.path == jobs.path + "/windows_paths/Giraffe_16strokes_seed1000_best.svg")
        let old = try #require(JobFolder.summary(at: jobs.appending(path: "old_2x")))
        #expect(old.favourite && old.state == nil)
    }

    @Test func savedInputFindsTheCopy() throws {
        let jobs = try Self.copyOfJobs()
        #expect(JobFolder.savedInput(jobDir: jobs.appending(path: "done_clipasso"), target: "/x/Kamel.png")?
            .lastPathComponent == "Kamel.png")
        #expect(JobFolder.savedInput(jobDir: jobs.appending(path: "old_2x"), target: "/x/Kamel.png")?
            .lastPathComponent == "source.png")
        #expect(JobFolder.savedInput(jobDir: jobs.appending(path: "windows_paths"),
                                     target: #"C:\Users\Jürgen\Pictures\Giraffe.png"#)?.lastPathComponent == "Giraffe.png")
    }

    /// With STUDIOCORE_EXPORT_DIR set, the meta.json Swift wrote and what Python should read from it are left there
    /// for tools/check_swift_meta.py (the CI job core runs it after swift test).
    static func exportForPython(_ name: String, jobDir: URL, meta: JSONObject) throws {
        guard let root = ProcessInfo.processInfo.environment["STUDIOCORE_EXPORT_DIR"], !root.isEmpty else { return }
        let dest = URL(filePath: root).appending(path: name)
        try FileManager.default.createDirectory(at: dest, withIntermediateDirectories: true)
        try Data(contentsOf: jobDir.appending(path: "meta.json")).write(to: dest.appending(path: "meta.json"))
        try Data(PyJSON.dump(.object(meta)).utf8).write(to: dest.appending(path: "expected.json"))
    }
}
