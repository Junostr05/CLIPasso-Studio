import Foundation
import Observation
import StudioCore

/// The app as a whole: its settings (the Python app's settings.json), texts, the parameter schema, the model list,
/// and the engine process with the job queue on it. Views read it from the environment; the engine's work happens in
/// StudioCore's actors.
@Observable
public final class AppModel {
    public enum EngineStatus: Equatable, Sendable {
        case starting
        case ready
        case restarting
        case unavailable(String)
    }

    public private(set) var engineStatus: EngineStatus = .starting
    public private(set) var settings: AppSettings
    public private(set) var texts: Texts
    public let schema: ParamSchema
    public let catalog: ModelCatalog
    /// The studio page (its settings and the job it started).
    public let studio: StudioModel
    /// The queue as it was last reported (nil before the engine runs).
    public private(set) var queueSnapshot: QueueSnapshot?
    @ObservationIgnored public private(set) var engine: EngineClient?
    @ObservationIgnored public private(set) var queue: JobQueue?
    @ObservationIgnored private var queueListener: Task<Void, Never>?
    @ObservationIgnored private let resources: AppResources
    @ObservationIgnored public let store: SettingsStore

    public init(resources: AppResources, store: SettingsStore = .standard()) throws {
        self.resources = resources
        self.store = store
        let loaded = store.load()
        settings = loaded
        texts = try Texts(directory: resources.i18n, language: Texts.resolve(loaded.language))
        let schema = try ParamSchema.load(resources.schema)
        self.schema = schema
        catalog = try ModelCatalog.load(resources.models)
        studio = StudioModel(schema: schema)
    }

    /// Change the settings and save them at once (AppSettings.set); false when the file could not be written – the
    /// change still holds until the app ends.
    @discardableResult
    public func updateSettings(_ change: (inout AppSettings) -> Void) -> Bool {
        change(&settings)
        return (try? store.save(settings)) != nil
    }

    /// Where the downloaded models are: the folder chosen in the settings, else beside settings.json.
    public var modelsDir: URL { settings.modelsDir ?? store.defaultModelsDir }

    /// How the engine starts: as the resources say, downloading its models to `modelsDir`.
    var engineLaunch: EngineLaunch? {
        guard var launch = resources.engine else { return nil }
        var environment = launch.environment ?? ProcessInfo.processInfo.environment
        environment["CLIPASSO_DOWNLOADS_DIR"] = modelsDir.path
        launch.environment = environment
        return launch
    }

    /// The status as the window shows it.
    public var engineStatusText: String {
        switch engineStatus {
        case .starting: texts.tr("ui.mac.engine_starting")
        case .restarting: texts.tr("ui.mac.engine_restarting")
        case .ready: ""
        case .unavailable(let text): text
        }
    }

    /// "auto", "de" or "en" – shown at once and saved.
    public func setLanguage(_ setting: String) throws {
        texts = try Texts(directory: resources.i18n, language: Texts.resolve(setting))
        updateSettings { $0.language = setting }
    }

    /// Start the engine; when it cannot start, the status says why (with what it wrote).
    public func startEngine() async {
        guard let launch = engineLaunch else {
            engineStatus = .unavailable(texts.tr("ui.mac.engine_unavailable", ["details": "no engine in the app"]))
            return
        }
        let client = EngineClient(launch: launch)
        engine = client
        engineStatus = .starting
        do {
            try await client.start()
            engineStatus = .ready
            let queue = JobQueue(engine: client, outputRoot: settings.outputDir)
            self.queue = queue
            queueListener = Task { [weak self] in
                for await snapshot in queue.updates {
                    self?.apply(snapshot)
                }
            }
        } catch {
            let log = await client.stderrTail().suffix(5).joined(separator: "\n")
            let details = log.isEmpty ? String(describing: error) : "\(error)\n\(log)"
            engineStatus = .unavailable(texts.tr("ui.mac.engine_unavailable", ["details": details]))
        }
    }

    public func stopEngine() async {
        queueListener?.cancel()
        queueListener = nil
        await engine?.stop()
    }

    private func apply(_ snapshot: QueueSnapshot) {
        queueSnapshot = snapshot
        studio.live.update(from: snapshot)
    }

    // MARK: - the studio's job

    /// *Create sketch*: the studio's image with its settings into the queue (it starts when nothing runs).
    public func startSketch() async {
        guard let queue else { return }
        await studio.start(on: queue)
        apply(await queue.snapshot())
    }

    /// *Pause* / *Resume* of the running job.
    public func pauseOrResume() async {
        guard let queue else { return }
        if studio.live.status == .paused {
            try? await queue.resume()
        } else {
            try? await queue.pause()
        }
        apply(await queue.snapshot())
    }

    /// *Cancel*: the job stops; its best sketch so far is kept.
    public func cancelJob() async {
        guard let queue else { return }
        try? await queue.cancel()
        apply(await queue.snapshot())
    }
}
