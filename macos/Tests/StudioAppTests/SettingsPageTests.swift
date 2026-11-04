import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The settings page: language, appearance and the two folders, saved at once in settings.json.
@Suite(.serialized) struct SettingsPageTests {
    @Test func languageAndAppearance() throws {
        let store = try AppModelTests.store(language: "de")
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store)
        let choices = model.languageChoices
        #expect(choices.map(\.id) == ["auto", "de", "en"])
        #expect(choices[1].label == "Deutsch" && choices[2].label == "English")
        #expect(choices[0].label.hasPrefix("Automatisch"))  // ui.settings.language_auto in German
        try model.setLanguage("en")
        #expect(model.languageChoices[0].label.hasPrefix("Automatic"))
        #expect(model.appearance == .dark)  // the Python app's default theme
        model.setAppearance(.system)
        #expect(store.load().theme == "system" && model.appearance == .system)
        model.setAppearance(.light)
        #expect(store.load().theme == "light")
    }

    @Test func outputFolderForNewJobsAndTheGallery() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let store = try AppModelTests.store(language: "en")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: store)
        await model.startEngine()
        let elsewhere = FileManager.default.temporaryDirectory.appending(path: "Skizzen \(UUID().uuidString)")
        await model.setOutputDir(elsewhere)
        #expect(store.load().outputDir.path == elsewhere.path && model.gallery.root.path == elsewhere.path)
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()
        let deadline = ContinuousClock.now + .seconds(30)
        while model.studio.live.status != .done, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(model.studio.live.jobDir?.path.hasPrefix(elsewhere.path) == true)
        await model.stopEngine()
    }

    @Test func modelsFolderRestartsTheEngine() async throws {
        let store = try AppModelTests.store(language: "en")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["echo"])), store: store)
        await model.startEngine()
        let before = await model.engine?.processIdentifier
        let folder = FileManager.default.temporaryDirectory.appending(path: "Modelle-\(UUID().uuidString)")
        #expect(await model.setModelsDir(folder) == nil)
        #expect(store.load().modelsDir?.path == folder.path)
        #expect(model.engineLaunch?.environment?["CLIPASSO_DOWNLOADS_DIR"] == folder.path)
        #expect(model.engineStatus == .ready)
        let after = await model.engine?.processIdentifier
        #expect(after != nil && after != before)  // started again with the new folder
        await model.stopEngine()
    }
}

/// The update hint: announced, skipped for good, or not looked for when the settings say so.
@Suite(.serialized) struct UpdateHintTests {
    nonisolated static let mac = #"{"tag_name": "v9.0.0", "html_url": "https://github.com/Junostr05/CLIPasso-Studio/releases/tag/v9.0.0", "prerelease": false, "draft": false, "assets": [{"name": "CLIPasso-Studio-9.0.0-mac.dmg"}]}"#

    struct Answer: HTTPTransport {
        func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
            let data = Data(UpdateHintTests.mac.utf8)
            return HTTPResponse(status: 200, length: Int64(data.count), contentType: "application/json",
                                body: AsyncThrowingStream { $0.yield(data); $0.finish() })
        }
    }

    @Test func announcedThenSkipped() async throws {
        let store = try AppModelTests.store(language: "en")
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store, transport: Answer())
        await model.checkForUpdate(current: "4.3.0")
        #expect(model.update?.version == "v9.0.0")
        #expect(model.texts.tr("ui.update.available", ["version": "v9.0.0", "current": "4.3.0"]).contains("v9.0.0"))
        model.skipUpdate()
        #expect(model.update == nil && store.load()["skipped_version"] == "v9.0.0")
        await model.checkForUpdate(current: "4.3.0")
        #expect(model.update == nil)  // the skipped version is not announced again
    }

    @Test func offWhenTheSettingsSaySo() async throws {
        let store = try AppModelTests.store(language: "en", ["check_updates": false])
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store, transport: Answer())
        await model.checkForUpdate(current: "4.3.0")
        #expect(model.update == nil)
    }
}
