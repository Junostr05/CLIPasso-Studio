import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// Backup & move in the app: one Mac's results and settings in a backup, put back on another – the gallery read
/// again, the settings taken over (the language at once), this Mac's folders kept.
@Suite(.serialized) struct BackupAppTests {
    @Test func toAnotherMac() async throws {
        let base = FileManager.default.temporaryDirectory.appending(path: "backup-app-\(UUID().uuidString)")
        let outA = base.appending(path: "A/out"), outB = base.appending(path: "B/out")
        try FileManager.default.createDirectory(at: outA, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs/done_clipasso"),
                                         to: outA.appending(path: "done_clipasso"))
        let a = try AppModel(resources: AppModelTests.resources(engine: nil),
                             store: AppModelTests.store(language: "en", ["output_dir": .string(outA.path),
                                                                         "export_style": "charcoal",
                                                                         "telegram_token": "GEHEIM"]))
        let sizes = await a.backupSizes()
        #expect(sizes.jobs == 1 && sizes.gallery > 0 && sizes.queue == 0)
        let file = base.appending(path: Backup.defaultName())
        try await a.createBackup(to: file, includeModels: false)

        let store = try AppModelTests.store(language: "de", ["output_dir": .string(outB.path)])
        let b = try AppModel(resources: AppModelTests.resources(engine: nil), store: store)
        await b.gallery.refresh()
        #expect(b.gallery.everything.isEmpty)
        let report = try await b.restoreBackup(from: file, parts: ["settings", "gallery", "queue"])
        #expect(report.jobs == 1 && report.skippedJobs == 0 && report.settings)
        #expect(b.gallery.everything.map(\.jobDir.lastPathComponent) == ["done_clipasso"])
        #expect(b.settings["export_style"] == "charcoal" && b.texts.language == "en")
        #expect(b.settings.outputDir.path == outB.path && store.load()["telegram_token"] == nil)
        // again: nothing twice
        let again = try await b.restoreBackup(from: file, parts: ["gallery"])
        #expect(again.jobs == 0 && again.skippedJobs == 1)
    }

    /// The queue of a backup: a waiting job is queued (and runs), a failed one comes back failed – not started by
    /// itself – and "Try again" queues it anew.
    @Test func theQueueComesBack() async throws {
        let base = FileManager.default.temporaryDirectory.appending(path: "backup-queue-\(UUID().uuidString)")
        let out = base.appending(path: "out"), pictures = base.appending(path: "Bilder")
        try FileManager.default.createDirectory(at: pictures, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        for name in ["a.png", "b.png"] { try Data([1]).write(to: pictures.appending(path: name)) }
        let settings: JSONObject = ["method": "clipasso", "num_iter": 3]
        let file = base.appending(path: "q.clipbackup")
        _ = try Backup.create(file, settings: [:], queue: [
            ["target": .string(pictures.path + "/a.png"), "settings": .object(settings)],
            ["target": .string(pictures.path + "/b.png"), "settings": .object(settings), "status": "failed",
             "job_dir": "", "message": "RuntimeError: made up"],
        ], outputDir: out, modelsDir: base.appending(path: "models"), includeModels: false, version: "4.4.0")

        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(out.path)]))
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        let report = try await model.restoreBackup(from: file, parts: ["queue"])
        #expect(report.queue.count == 2)
        let jobs = model.queueSnapshot?.jobs ?? []
        #expect(jobs.map(\.target.lastPathComponent).sorted() == ["a.png", "b.png"])
        let failed = try #require(jobs.first { $0.target.lastPathComponent == "b.png" })
        #expect(failed.status == .failed && failed.message == "RuntimeError: made up")
        #expect(jobs.first { $0.target.lastPathComponent == "a.png" }?.status == .queued)
        await model.queuePage?.retry(failed)
        let now = model.queuePage?.jobs ?? []
        #expect(now.filter { $0.target.lastPathComponent == "b.png" }.map(\.status) == [.queued])
        await model.stopEngine()
    }
}
