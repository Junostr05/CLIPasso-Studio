import Foundation
import StudioCore

/// Where the app finds its parts: the texts, the exported schema and model list, and how the engine starts. In the
/// app they are in `Contents/Resources` (put there by macos/scripts/make_app.sh); while developing they can come from
/// the repository (`CLIPASSO_DEV_REPO`).
public struct AppResources: Sendable {
    public let i18n: URL
    public let schema: URL
    public let models: URL
    /// nil: no engine found (the app says so and does not compute)
    public let engine: EngineLaunch?
    /// the models that come with the app (BlazeFace)
    public let bundledModels: URL?

    public init(i18n: URL, schema: URL, models: URL, engine: EngineLaunch?, bundledModels: URL? = nil) {
        self.i18n = i18n
        self.schema = schema
        self.models = models
        self.engine = engine
        self.bundledModels = bundledModels
    }

    /// The app's own Python (`Resources/python`) runs the engine (`Resources/engine`) with a clean environment:
    /// nothing of the user's Python settings, no secrets; the models that come with the app (BlazeFace) are in
    /// `Resources/models`, the downloaded ones where the settings say (added by AppModel.engineLaunch). Python never
    /// writes into the signed app (its code is compiled when the app is built).
    public static func bundled(resources: URL) -> AppResources {
        var environment = ["PYTHONPATH": resources.appending(path: "engine").path, "PYTHONNOUSERSITE": "1",
                           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
                           "PYTORCH_ENABLE_MPS_FALLBACK": "1", "CLIPASSO_MODELS_DIR": resources.appending(path: "models").path,
                           "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"]
        if let home = ProcessInfo.processInfo.environment["HOME"] { environment["HOME"] = home }
        let engine = EngineLaunch(executable: resources.appending(path: "python/bin/python3"),
                                  arguments: ["-s", "-m", "clipasso_studio.headless"], environment: environment,
                                  workingDirectory: resources)
        return AppResources(i18n: resources.appending(path: "i18n"), schema: resources.appending(path: "schema.json"),
                            models: resources.appending(path: "models.json"), engine: engine,
                            bundledModels: resources.appending(path: "models", directoryHint: .isDirectory))
    }

    /// The app's parts: from the bundle – or, with `CLIPASSO_DEV_REPO` set to the repository, from there (python3 of
    /// the system with the repository's engine; schema and models from the test fixtures).
    public static func current(bundle: Bundle = .main,
                               environment: [String: String] = ProcessInfo.processInfo.environment) -> AppResources
    {
        if let repo = environment["CLIPASSO_DEV_REPO"].map({ URL(filePath: $0) }) {
            let fixtures = repo.appending(path: "macos/Tests/StudioCoreTests/Fixtures")
            let engine = EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                                      arguments: ["python3", "-m", "clipasso_studio.headless"],
                                      environment: ["PYTHONPATH": repo.path, "PATH": environment["PATH"] ?? "/usr/bin:/bin",
                                                    "HOME": environment["HOME"] ?? "", "PYTORCH_ENABLE_MPS_FALLBACK": "1"],
                                      workingDirectory: repo)
            return AppResources(i18n: repo.appending(path: "clipasso_studio/resources/i18n"),
                                schema: fixtures.appending(path: "schema.json"),
                                models: fixtures.appending(path: "models.json"), engine: engine,
                                bundledModels: repo.appending(path: "models", directoryHint: .isDirectory))
        }
        return bundled(resources: bundle.resourceURL ?? bundle.bundleURL)
    }
}
