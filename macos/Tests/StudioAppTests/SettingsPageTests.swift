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

    /// Answers with `body` and `status`.
    struct Fixed: HTTPTransport {
        let status: Int
        let body: String

        func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
            let data = Data(body.utf8)
            return HTTPResponse(status: status, length: Int64(data.count), contentType: "application/json",
                                body: AsyncThrowingStream { $0.yield(data); $0.finish() })
        }
    }

    /// *Check now*: whatever the settings and a skipped version say – newer (announced, with its notes), the newest
    /// already, or no answer; the switch for the search at the start.
    @Test func checkNow() async throws {
        let store = try AppModelTests.store(language: "de", ["check_updates": false, "skipped_version": "v9.0.0"])
        let release = Self.mac.replacingOccurrences(of: #""draft": false"#, with: #""draft": false, "body": "Neu: alles""#)
        var model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store,
                                 transport: Fixed(status: 200, body: release))
        #expect(model.updateState == .idle && model.updateMessage.isEmpty && !model.checksForUpdates)
        await model.checkUpdateNow(current: "4.3.0")
        #expect(model.updateState == .found && model.latest?.notes == "Neu: alles" && model.update?.version == "v9.0.0")
        #expect(model.updateMessage == "Version 9.0.0 ist verfügbar.")
        await model.checkUpdateNow(current: "9.0.0")
        #expect(model.updateState == .current && model.latest == nil)
        #expect(model.updateMessage == "Du hast die neueste Version (\(model.version)).")
        model.setChecksForUpdates(true)
        #expect(model.checksForUpdates && store.load()["check_updates"] == true)

        model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store,
                             transport: Fixed(status: 503, body: "busy"))
        await model.checkUpdateNow(current: "4.3.0")
        #expect(model.updateState == .failed && model.latest == nil && model.update == nil)
        #expect(model.updateMessage.hasPrefix("Konnte nicht nach Updates suchen"))
    }

    /// The updates from the phone: the version, the search and what it found – installing is done on the Mac by hand
    /// (mode "none", the page's hint the Mac app's own), and the switch among the app's settings.
    @Test func fromThePhone() async throws {
        let store = try AppModelTests.store(language: "de")
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store, transport: Answer())
        func ask(_ action: String, _ data: JSONObject = [:]) async -> JSONObject? {
            PhoneRemoteTests.json(await model.phoneAnswer(action, data, payload: nil))
        }
        var state = try #require(await ask("get_update"))
        #expect(state["phase"] == "idle" && state["mode"] == "none" && state["can_install"] == false)
        #expect(state["version"] == .string(model.version) && state["latest"] == "")
        await model.checkUpdateNow(current: "4.3.0")
        state = try #require(await ask("get_update"))
        #expect(state["phase"] == "found" && state["latest"] == "9.0.0" && state["error"] == "")
        #expect(await ask("get_studio")?["update"] == "found")
        let install = await ask("do_install_update", ["_pin_ok": true])
        #expect(install?["ok"] == false && install?["error"] == .string(model.texts.tr("ui.mac.phone.update_not_here")))
        #expect(await ask("do_cancel_update") == ["ok": false])
        #expect(await ask("do_check_update") == ["ok": true])  // (the search runs on its own)

        let settings = try #require(await ask("get_app_settings")?["settings"]?.arrayValue)
        let updates = try #require(settings.compactMap(\.objectValue).first { $0["key"] == "check_updates" })
        #expect(updates["kind"] == "bool" && updates["value"] == true)
        #expect(updates["label"] == "Beim Start nach einer neuen Version suchen")
        #expect(await ask("do_app_setting", ["key": "check_updates", "value": false]) == ["ok": true])
        #expect(!model.checksForUpdates && store.load()["check_updates"] == false)
    }

    @Test func offWhenTheSettingsSaySo() async throws {
        let store = try AppModelTests.store(language: "en", ["check_updates": false])
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: store, transport: Answer())
        await model.checkForUpdate(current: "4.3.0")
        #expect(model.update == nil)
    }
}
