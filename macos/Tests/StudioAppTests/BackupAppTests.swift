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
}
