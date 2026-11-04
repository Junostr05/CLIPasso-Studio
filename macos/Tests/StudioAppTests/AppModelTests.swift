import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The app's model starts the engine – and says so calmly when it cannot.
@Suite(.serialized) struct AppModelTests {
    static let repo = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()

    static func resources(engine: EngineLaunch?) -> AppResources {
        let fixtures = repo.appending(path: "macos/Tests/StudioCoreTests/Fixtures")
        return AppResources(i18n: repo.appending(path: "clipasso_studio/resources/i18n"),
                            schema: fixtures.appending(path: "schema.json"),
                            models: fixtures.appending(path: "models.json"), engine: engine)
    }

    /// A settings file of its own in a new folder, with the language set.
    static func store(language: String, _ more: JSONObject = [:]) throws -> SettingsStore {
        let dir = FileManager.default.temporaryDirectory.appending(path: "app-\(UUID().uuidString)")
        let store = SettingsStore(url: dir.appending(path: "settings.json"), home: dir)
        var settings = store.load()
        settings.language = language
        for (key, value) in more {
            settings[key] = value
        }
        try store.save(settings)
        return store
    }

    @Test func loadsTextsAndSchema() throws {
        let model = try AppModel(resources: Self.resources(engine: nil), store: Self.store(language: "de"))
        #expect(model.texts.tr("ui.start") == "Skizze erstellen")
        #expect(model.schema.methods.count == 4 && model.catalog.spec("blazeface")?.macBundled == true)
        #expect(model.engineStatus == .starting)
    }

    @Test func startsWithoutEngine() async throws {
        let missing = EngineLaunch(executable: URL(filePath: "/nonexistent/python3"), arguments: [])
        let model = try AppModel(resources: Self.resources(engine: missing), store: Self.store(language: "de"))
        await model.startEngine()
        guard case .unavailable(let text) = model.engineStatus else {
            Issue.record("expected unavailable, got \(model.engineStatus)")
            return
        }
        #expect(text.hasPrefix("Das Rechenmodul ließ sich nicht starten"))
        await model.stopEngine()
    }

    @Test func noEngineAtAll() async throws {
        let model = try AppModel(resources: Self.resources(engine: nil), store: Self.store(language: "en"))
        await model.startEngine()
        guard case .unavailable(let text) = model.engineStatus else {
            Issue.record("expected unavailable, got \(model.engineStatus)")
            return
        }
        #expect(text.hasPrefix("The sketch engine could not be started"))
    }

    @Test func readyWithTheRealEngine() async throws {
        let launch = EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                                  arguments: ["python3", "-m", "clipasso_studio.headless"],
                                  environment: ["PYTHONPATH": Self.repo.path,
                                                "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"],
                                  workingDirectory: Self.repo)
        let model = try AppModel(resources: Self.resources(engine: launch), store: Self.store(language: "en"))
        await model.startEngine()
        #expect(model.engineStatus == .ready)
        await model.stopEngine()
    }

    /// The settings decide the language and the folder the engine downloads its models to; a changed language is
    /// saved at once (like AppSettings.set).
    @Test func settingsDecideLanguageAndModelFolder() throws {
        let launch = EngineLaunch(executable: URL(filePath: "/usr/bin/env"), arguments: [], environment: ["PATH": "/usr/bin"])
        let store = try Self.store(language: "de", ["models_dir": "/Volumes/Archiv/Modelle"])
        let model = try AppModel(resources: Self.resources(engine: launch), store: store)
        #expect(model.texts.language == "de")
        #expect(model.engineLaunch?.environment?["CLIPASSO_DOWNLOADS_DIR"] == "/Volumes/Archiv/Modelle")
        #expect(model.engineLaunch?.environment?["PATH"] == "/usr/bin")
        try model.setLanguage("en")
        #expect(model.texts.tr("ui.start") == "Create sketch")
        #expect(store.load().language == "en" && store.load().modelsDir?.path == "/Volumes/Archiv/Modelle")

        let plain = try Self.store(language: "auto")
        let standard = try AppModel(resources: Self.resources(engine: launch), store: plain)
        #expect(standard.modelsDir == plain.defaultModelsDir)  // beside settings.json, as paths.default_models_dir
        #expect(standard.engineLaunch?.environment?["CLIPASSO_DOWNLOADS_DIR"] == standard.modelsDir.path)
    }

    /// The studio's job goes through the queue on the engine; the studio follows it to its end.
    @Test func aStudioJobRunsThroughTheQueue() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let out = FileManager.default.temporaryDirectory.appending(path: "studio-\(UUID().uuidString)")
        let store = try Self.store(language: "en", ["output_dir": .string(out.path)])
        let model = try AppModel(resources: Self.resources(engine: SelfTestTests.fake(["job", done.path])), store: store)
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()  // (no engine yet: nothing happens)
        #expect(model.queueSnapshot == nil)
        await model.startEngine()
        await model.startSketch()
        let deadline = ContinuousClock.now + .seconds(30)
        while model.studio.live.status != .done, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(model.studio.live.status == .done && model.studio.canStart)
        #expect(model.queueSnapshot?.jobs.count == 1)
        #expect(model.studio.live.jobDir?.path.hasPrefix(out.path) == true)  // the output folder of the settings
        #expect(model.queuePage?.jobs.count == 1)
        let deadline2 = ContinuousClock.now + .seconds(60)  // (a guard against a hang, far above any stall)
        while model.gallery.items.isEmpty, ContinuousClock.now < deadline2 {
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(model.gallery.items.count == 1)  // the finished job appears in the gallery
        await model.stopEngine()
    }

    @Test func bundledResourcesLayout() {
        let contents = URL(filePath: "/Applications/CLIPasso Studio.app/Contents")
        let r = AppResources.bundled(resources: contents.appending(path: "Resources"))
        #expect(r.i18n.path.hasSuffix("Contents/Resources/i18n") && r.schema.lastPathComponent == "schema.json")
        let engine = r.engine
        #expect(engine?.executable.path.hasSuffix("Contents/Resources/python/bin/python3") == true)
        #expect(engine?.arguments == ["-s", "-m", "clipasso_studio.headless"])
        let env = engine?.environment ?? [:]
        #expect(env["PYTHONPATH"]?.hasSuffix("Contents/Resources/engine") == true)
        #expect(env["PYTORCH_ENABLE_MPS_FALLBACK"] == "1" && env["PYTHONDONTWRITEBYTECODE"] == "1")
        #expect(env["CLIPASSO_MODELS_DIR"]?.hasSuffix("Contents/Resources/models") == true)  // BlazeFace
        #expect(env["PYTHONHOME"] == nil && env["PYTHONSTARTUP"] == nil)
        #expect(!env.keys.contains { $0.lowercased().contains("token") || $0.lowercased().contains("pin") })
    }
}
