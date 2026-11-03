import Foundation
import Observation
import StudioCore

/// The app as a whole: its texts, the parameter schema, the model list, and the engine process with the job queue on
/// it. Views read it from the environment; the engine's work happens in StudioCore's actors.
@Observable
public final class AppModel {
    public enum EngineStatus: Equatable, Sendable {
        case starting
        case ready
        case restarting
        case unavailable(String)
    }

    public private(set) var engineStatus: EngineStatus = .starting
    public private(set) var texts: Texts
    public let schema: ParamSchema
    public let catalog: ModelCatalog
    @ObservationIgnored public private(set) var engine: EngineClient?
    @ObservationIgnored private let resources: AppResources

    public init(resources: AppResources, language: String) throws {
        self.resources = resources
        texts = try Texts(directory: resources.i18n, language: Texts.resolve(language))
        schema = try ParamSchema.load(resources.schema)
        catalog = try ModelCatalog.load(resources.models)
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

    public func setLanguage(_ setting: String) throws {
        texts = try Texts(directory: resources.i18n, language: Texts.resolve(setting))
    }

    /// Start the engine; when it cannot start, the status says why (with what it wrote).
    public func startEngine() async {
        guard let launch = resources.engine else {
            engineStatus = .unavailable(texts.tr("ui.mac.engine_unavailable", ["details": "no engine in the app"]))
            return
        }
        let client = EngineClient(launch: launch)
        engine = client
        engineStatus = .starting
        do {
            try await client.start()
            engineStatus = .ready
        } catch {
            let log = await client.stderrTail().suffix(5).joined(separator: "\n")
            let details = log.isEmpty ? String(describing: error) : "\(error)\n\(log)"
            engineStatus = .unavailable(texts.tr("ui.mac.engine_unavailable", ["details": details]))
        }
    }

    public func stopEngine() async {
        await engine?.stop()
    }
}
