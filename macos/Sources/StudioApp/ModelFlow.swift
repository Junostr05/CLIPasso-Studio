import Foundation
import Observation
import StudioCore

/// The models a job needs that are not there yet (gui: the studio's check before a start and
/// dialogs.ModelDownloadDialog): asked for with their names and size, then downloaded with progress and converted by
/// the engine; a cancelled download stays for the next time.
@Observable
public final class ModelFlow {
    public enum Stage: Equatable, Sendable {
        case idle
        /// the missing models, waiting for *Download* or *Cancel*
        case asking([String])
        case downloading(key: String, done: Int64, total: Int64)
        case converting(String)
        /// what went wrong, as the window says it
        case failed(String)
    }

    public internal(set) var stage: Stage = .idle
    let catalog: ModelCatalog

    init(catalog: ModelCatalog) {
        self.catalog = catalog
    }

    public func name(_ key: String) -> String { catalog.spec(key)?.name ?? key }

    /// "Required: CLIP RN101, U²-Net (about 545 MB). …" (ui.download_models_desc)
    public func question(_ texts: Texts) -> String {
        guard case .asking(let keys) = stage else { return "" }
        let total = keys.reduce(0.0) { $0 + Double(catalog.spec($1)?.downloadSize ?? 0) } / 1e6
        return texts.tr("ui.download_models_desc", ["names": keys.map(name).joined(separator: ", "),
                                                    "mb": String(format: "%.0f", total)])
    }

    /// The progress of the download under way, 0 … 1 (nil: none runs).
    public var fraction: Double? {
        guard case .downloading(_, let done, let total) = stage, total > 0 else { return nil }
        return min(1, Double(done) / Double(total))
    }

    func progress(_ key: String, _ done: Int64, _ total: Int64) {
        guard case .downloading(let current, let before, _) = stage, current == key, done >= before else { return }
        stage = .downloading(key: key, done: done, total: total)
    }
}
