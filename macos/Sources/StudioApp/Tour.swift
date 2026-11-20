import Foundation
import Observation
import StudioCore

/// The first-start guide (gui/tour.py): a short tour that dims the window except one part at a time and explains it –
/// shown once after a new installation (tour_done, as in the studio's settings), again from the Help menu.
@Observable
public final class TourModel {
    /// One step: its texts (ui.tour.<key>.*), the page it shows, the parts of the window it points at.
    public struct Step: Sendable, Hashable {
        public let key: String
        public let page: String
    }

    /// tour.STEPS, with the Mac app's pages (models and settings are in the sidebar).
    public static let steps: [Step] = [
        Step(key: "methods", page: "studio"), Step(key: "input", page: "studio"), Step(key: "params", page: "studio"),
        Step(key: "start", page: "studio"), Step(key: "result", page: "studio"), Step(key: "gallery", page: "gallery"),
        Step(key: "models", page: "models"),
    ]

    /// the step shown (nil: the guide is closed)
    public private(set) var index: Int?

    public init() {}

    public var step: Step? { index.map { Self.steps[$0] } }
    public var isLast: Bool { index == Self.steps.count - 1 }

    public func start() { index = 0 }

    /// Weiter: the next step – after the last one the guide is done (true).
    @discardableResult
    public func next() -> Bool {
        guard let index else { return false }
        guard index + 1 < Self.steps.count else {
            self.index = nil
            return true
        }
        self.index = index + 1
        return false
    }

    public func back() {
        if let index, index > 0 { self.index = index - 1 }
    }

    public func close() { index = nil }

    /// "Schritt 2 von 7".
    public func position(_ texts: Texts) -> String {
        texts.tr("ui.tour.step", ["n": "\((index ?? 0) + 1)", "total": "\(Self.steps.count)"])
    }

    public func title(_ texts: Texts) -> String {
        step.map { texts.tr("ui.tour.\($0.key).title") } ?? ""
    }

    /// The step's text – the Mac's own where its keys or places differ (ui.mac.tour.<key>.text).
    public func text(_ texts: Texts) -> String {
        guard let step else { return "" }
        let mac = "ui.mac.tour.\(step.key).text"
        return texts.tr(texts.has(mac) ? mac : "ui.tour.\(step.key).text")
    }
}

public extension AppModel {
    /// main_window.maybe_show_tour: once, after a new installation.
    func maybeShowTour() {
        guard !(settings["tour_done"]?.truthy ?? false) else { return }
        tour.start()
    }

    /// _tour_finished: done or skipped, it is not shown by itself again.
    func tourFinished() {
        tour.close()
        _ = updateSettings { $0["tour_done"] = true }
    }
}
