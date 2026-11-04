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
    /// The models a job needs that are not there yet.
    public let models: ModelFlow
    /// The results of the output folder.
    public private(set) var gallery: GalleryModel
    /// The queue page (once the engine runs).
    public private(set) var queuePage: QueueModel?
    /// A newer release with a Mac disk image (announced; its page opens on request).
    public private(set) var update: UpdateCheck.Release?
    /// The countdown before the Mac sleeps or shuts down, once the queue ran out with that chosen.
    public private(set) var countdown: WhenDoneCountdown?
    @ObservationIgnored private let power: any PowerActions
    @ObservationIgnored private let whenDoneTiming: (seconds: Int, tick: Duration)
    /// The queue as it was last reported (nil before the engine runs).
    public private(set) var queueSnapshot: QueueSnapshot?
    @ObservationIgnored public private(set) var engine: EngineClient?
    @ObservationIgnored public private(set) var queue: JobQueue?
    @ObservationIgnored private var queueListener: Task<Void, Never>?
    @ObservationIgnored private let transport: any HTTPTransport
    @ObservationIgnored private var download: Task<Void, Never>?
    @ObservationIgnored private let resources: AppResources
    @ObservationIgnored public let store: SettingsStore

    public init(resources: AppResources, store: SettingsStore = .standard(),
                transport: any HTTPTransport = URLSessionTransport(), power: any PowerActions = MacPower(),
                whenDoneTiming: (seconds: Int, tick: Duration) = (60, .seconds(1))) throws
    {
        self.resources = resources
        self.transport = transport
        self.power = power
        self.whenDoneTiming = whenDoneTiming
        self.store = store
        let loaded = store.load()
        settings = loaded
        texts = try Texts(directory: resources.i18n, language: Texts.resolve(loaded.language))
        let schema = try ParamSchema.load(resources.schema)
        self.schema = schema
        let catalog = try ModelCatalog.load(resources.models)
        self.catalog = catalog
        models = ModelFlow(catalog: catalog)
        studio = StudioModel(schema: schema)
        gallery = GalleryModel(root: loaded.outputDir, schema: schema)
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
            queuePage = QueueModel(queue: queue)
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
        let finished = { (s: QueueSnapshot?) in s?.jobs.filter { $0.status == .done }.count ?? 0 }
        let newResult = finished(snapshot) > finished(queueSnapshot)
        let ranOut = snapshot.finished != nil && queueSnapshot?.finished == nil
        queueSnapshot = snapshot
        queuePage?.apply(snapshot)
        if ranOut, let action = snapshot.finished, action != .nothing {
            // once: the choice goes back to "nothing" (as in the studio), then the countdown
            Task { await queuePage?.setWhenDone(.nothing) }
            let countdown = WhenDoneCountdown(action: action, seconds: whenDoneTiming.seconds,
                                              tick: whenDoneTiming.tick, power: power)
            self.countdown = countdown
            countdown.start()
        }
        studio.live.update(from: snapshot)
        studio.showFinishedJob()
        if newResult {
            Task { await gallery.refresh() }  // (a finished job is a new result)
        }
    }

    // MARK: - updates (announced only)

    /// The app's version (the bundle's; "0" while developing).
    public var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
    }

    /// At the start, when the settings allow it (check_updates, as the Python app): a newer release that is not
    /// the one the user skipped.
    public func checkForUpdate(current: String? = nil) async {
        guard settings["check_updates"]?.truthy ?? true else { return }
        guard let found = try? await UpdateCheck.newer(than: current ?? version, transport: transport) else { return }
        if settings["skipped_version"]?.stringValue == found.version { return }
        update = found
    }

    /// *Skip this version* (skipped_version, as the Python app keeps it).
    public func skipUpdate() {
        guard let update else { return }
        updateSettings { $0["skipped_version"] = .string(update.version) }
        self.update = nil
    }

    /// *Remind me next time*.
    public func dismissUpdate() {
        update = nil
    }

    // MARK: - the settings page

    public struct Choice: Identifiable, Hashable, Sendable {
        public let id: String
        public let label: String
    }

    /// Automatic (the system's language), Deutsch, English.
    public var languageChoices: [Choice] {
        let system = Texts.names[Texts.resolve("auto")] ?? "English"
        return [Choice(id: "auto", label: texts.tr("ui.settings.language_auto", ["lang": system]))]
            + Texts.languages.map { Choice(id: $0, label: Texts.names[$0] ?? $0) }
    }

    /// The window's appearance – the settings' "theme" as the Python app keeps it (dark, light or system).
    public enum Appearance: String, CaseIterable, Sendable {
        case system, light, dark
    }

    public var appearance: Appearance { Appearance(rawValue: settings.theme) ?? .dark }

    public func setAppearance(_ appearance: Appearance) {
        updateSettings { $0.theme = appearance.rawValue }
    }

    /// The output folder: new jobs go there, the gallery shows it.
    public func setOutputDir(_ url: URL) async {
        updateSettings { $0.outputDir = url }
        await queue?.setOutputRoot(url)
        gallery = GalleryModel(root: url, schema: schema)
        await gallery.refresh()
    }

    /// The folder of the downloaded models; the engine starts again with it. Refused (the text says why) while a job
    /// runs or waits.
    public func setModelsDir(_ url: URL?) async -> String? {
        let busy = queueSnapshot?.jobs.contains { [.queued, .running, .paused].contains($0.status) } ?? false
        guard !busy, !studio.live.isActive else { return texts.tr("ui.settings.models_busy") }
        updateSettings { $0.modelsDir = url }
        models.revision += 1
        if engine != nil, engineStatus == .ready {
            await stopEngine()
            await startEngine()
        }
        return nil
    }

    // MARK: - the studio's job

    /// *Create sketch*: the studio's image with its settings into the queue (it starts when nothing runs) – first
    /// asking for the models it needs that are not there (`models`).
    public func startSketch() async {
        guard let queue, let engine, studio.canStart else { return }
        var missing: [String] = []
        if let answer = try? await engine.request("required_models", ["settings": .object(studio.jobSettings)]) {
            missing = answer.objectValue?["missing"]?.arrayValue?.compactMap(\.stringValue) ?? []
        }  // (when the engine cannot say, the job itself reports a missing model)
        guard missing.isEmpty else {
            pendingImages = []
            models.startsJob = true
            models.stage = .asking(missing)
            return
        }
        await studio.start(on: queue)
        apply(await queue.snapshot())
    }

    // MARK: - the queue page's own jobs

    /// Images given to the queue page while the models they need are asked for: queued after the download.
    @ObservationIgnored private var pendingImages: [URL] = []

    /// *Add images*, *Add folder* or a drop on the queue page (other_pages.QueuePage.add_paths): every image a job
    /// with the studio's settings, behind the others – first asking for the models they need that are not there, as
    /// *Create sketch* does. The number of jobs queued (0 while the models are asked for).
    @discardableResult
    public func addToQueue(_ images: [URL]) async -> Int {
        guard let queue, let engine, !images.isEmpty else { return 0 }
        let settings = studio.jobSettings
        var missing: [String] = []
        if let answer = try? await engine.request("required_models", ["settings": .object(settings)]) {
            missing = answer.objectValue?["missing"]?.arrayValue?.compactMap(\.stringValue) ?? []
        }
        guard missing.isEmpty else {
            pendingImages = images
            models.startsJob = true
            models.stage = .asking(missing)
            return 0
        }
        for image in images {
            await queue.add(target: image, settings: settings)
        }
        apply(await queue.snapshot())
        return images.count
    }

    /// *Download* in the question: the missing models one after the other, each converted by the engine, then the
    /// job starts.
    public func downloadMissingAndStart() async {
        guard case .asking(let keys) = models.stage, let engine else { return }
        let downloader = ModelDownloader(catalog: catalog, root: modelsDir, transport: transport)
        for key in keys {
            models.stage = .downloading(key: key, done: 0, total: catalog.spec(key)?.downloadSize ?? 0)
            do {
                _ = try await downloader.download(key) { [weak self] done, total in
                    Task { @MainActor in self?.models.progress(key, done, total) }
                }
                try Task.checkCancellation()
                models.stage = .converting(key)
                _ = try await engine.request("convert_model", ["key": .string(key), "dest_root": .string(modelsDir.path)],
                                             timeout: .seconds(3600))
                models.revision += 1
            } catch is CancellationError {
                models.stage = .idle
                return
            } catch {
                models.stage = Task.isCancelled ? .idle : .failed(problem(error, key: key))
                return
            }
        }
        models.stage = .idle
        guard models.startsJob else { return }
        if pendingImages.isEmpty {
            await startSketch()
        } else {
            let images = pendingImages
            pendingImages = []
            await addToQueue(images)
        }
    }

    // MARK: - the Models page

    public enum ModelState: Equatable, Sendable {
        /// comes with the app
        case included
        case installed
        case missing
    }

    public func modelState(_ key: String) -> ModelState {
        _ = models.revision  // (observed: a download or a removal changes it)
        if let bundled = resources.bundledModels, catalog.installedURL(key, dirs: [bundled]) != nil { return .included }
        return catalog.installedURL(key, dirs: [modelsDir]) != nil ? .installed : .missing
    }

    /// *Download* on the Models page: asked as before a job, but no job follows.
    public func downloadModels(_ keys: [String]) {
        guard !keys.isEmpty else { return }
        models.startsJob = false
        models.stage = .asking(keys)
    }

    /// *Remove* on the Models page (after its question): the model's file, or its folder.
    public func removeModel(_ key: String) throws {
        try catalog.uninstall(key, root: modelsDir)
        models.revision += 1
    }

    /// The question's *Download* button.
    public func confirmDownload() {
        download?.cancel()
        download = Task { [weak self] in await self?.downloadMissingAndStart() }
    }

    /// *Cancel* in the question or while downloading: what came so far stays for the next time.
    public func cancelDownload() {
        guard models.stage != .idle else { return }  // (the sheet closing after a finished download is no cancel)
        download?.cancel()
        download = nil
        pendingImages = []
        if case .asking = models.stage { models.stage = .idle }
        if case .failed = models.stage { models.stage = .idle }
    }

    private func problem(_ error: any Error, key: String) -> String {
        let code = (error as? ModelDownloadError)?.code ?? (error as? EngineFailure)?.code ?? ""
        let details = (error as? ModelDownloadError)?.details ?? String(describing: error)
        let textKey = "ui.err.\(code)"
        guard !code.isEmpty, texts.has(textKey) else { return String(describing: error) }
        return texts.tr(textKey, ["model": models.name(key), "name": models.name(key), "details": details])
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
