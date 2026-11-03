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

    @Test func loadsTextsAndSchema() throws {
        let model = try AppModel(resources: Self.resources(engine: nil), language: "de")
        #expect(model.texts.tr("ui.start") == "Skizze erstellen")
        #expect(model.schema.methods.count == 4 && model.catalog.spec("blazeface")?.macBundled == true)
        #expect(model.engineStatus == .starting)
    }

    @Test func startsWithoutEngine() async throws {
        let missing = EngineLaunch(executable: URL(filePath: "/nonexistent/python3"), arguments: [])
        let model = try AppModel(resources: Self.resources(engine: missing), language: "de")
        await model.startEngine()
        guard case .unavailable(let text) = model.engineStatus else {
            Issue.record("expected unavailable, got \(model.engineStatus)")
            return
        }
        #expect(text.hasPrefix("Das Rechenmodul ließ sich nicht starten"))
        await model.stopEngine()
    }

    @Test func noEngineAtAll() async throws {
        let model = try AppModel(resources: Self.resources(engine: nil), language: "en")
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
        let model = try AppModel(resources: Self.resources(engine: launch), language: "en")
        await model.startEngine()
        #expect(model.engineStatus == .ready)
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
        #expect(env["PYTORCH_ENABLE_MPS_FALLBACK"] == "1")
        #expect(!env.keys.contains { $0.lowercased().contains("token") || $0.lowercased().contains("pin") })
    }
}
