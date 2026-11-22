import Foundation
import Observation
import StudioCore

/// Below the studio's canvas (widgets/edit_bar.py): a slider over the saved steps of a sketch ("Zwischenstände": take
/// one as the result) or over its strokes ("Vereinfachen": the least important ones go first). It only previews –
/// "Übernehmen" takes the sketch shown as one step of the editor (undo brings the sketch back; the original stays).
@Observable
public final class EditBarModel {
    public enum Mode: Sendable { case history, simplify }

    public let mode: Mode
    /// the sketch when the bar opened (simplify works on it; history shows it when a step cannot be read)
    public let svg: String
    /// history: the saved steps (svg_logs/svg_iter<i>.svg), in their order
    public let frames: [URL]
    /// simplify: the strokes from the least to the most important (nil: still being measured, or failed)
    public private(set) var order: [Int]?
    /// simplify: why measuring went wrong ("" when it did not)
    public private(set) var problem = ""
    /// the slider: the step's index (history) or the strokes kept (simplify)
    public var value: Int {
        didSet {
            let clamped = min(max(value, range.lowerBound), range.upperBound)
            if clamped != value { value = clamped } else if value != oldValue { refresh() }
        }
    }
    /// the sketch the bar shows
    public private(set) var preview: String

    /// History over `frames`, the last one shown first; nil with fewer than two steps (edit_bar.open_history).
    public init?(steps frames: [URL], current: String) {
        guard frames.count >= 2 else { return nil }
        mode = .history
        self.frames = frames
        svg = current
        value = frames.count - 1
        preview = current
        refresh()
    }

    /// Simplify `svg`: all strokes kept; `order` nil while it is measured (edit_bar.open_simplify).
    public init(simplify svg: String, order: [Int]?) {
        mode = .simplify
        frames = []
        self.svg = svg
        value = max(SketchEditing.count(svg), 1)
        preview = svg
        measured(order)
    }

    /// edit_bar.set_importance: the order measured (one that does not fit the sketch counts as none), or why not.
    public func measured(_ order: [Int]?, problem: String = "") {
        guard mode == .simplify else { return }
        self.order = order?.count == strokeCount ? order : nil
        self.problem = problem
        refresh()
    }

    public var strokeCount: Int { SketchEditing.count(svg) }

    public var range: ClosedRange<Int> {
        mode == .history ? 0 ... frames.count - 1 : 1 ... max(strokeCount, 1)
    }

    /// simplify: still being measured (no order, nothing went wrong)
    public var measuring: Bool { mode == .simplify && order == nil && problem.isEmpty }

    public var sliderEnabled: Bool { mode == .history || (order != nil && strokeCount > 1) }

    /// "Übernehmen": a step always; simplified only with fewer strokes than there are.
    public var canApply: Bool { mode == .history || (order != nil && value < range.upperBound) }

    /// edit_bar.kept_svg: the sketch with only its `keep` most important strokes.
    public func kept(_ keep: Int) -> String {
        guard let order else { return svg }
        let drop = order.prefix(max(0, order.count - keep))
        return drop.isEmpty ? svg : SketchEditing.removeStrokes(svg, Set(drop))
    }

    /// The bar's title.
    public func title(_ texts: Texts) -> String {
        texts.tr(mode == .history ? "ui.edit_bar.history" : "ui.edit_bar.simplify")
    }

    /// The line beside the title: the step and its iteration, or the strokes kept.
    public func info(_ texts: Texts) -> String {
        switch mode {
        case .history:
            texts.tr("ui.edit_bar.step", ["n": "\(value + 1)", "total": "\(frames.count)",
                                          "it": "\(max(Self.iteration(frames[value]), 0))"])
        case .simplify:
            texts.tr("ui.edit_bar.strokes", ["n": "\(value)", "total": "\(range.upperBound)"])
        }
    }

    /// The line below the slider.
    public func note(_ texts: Texts) -> String {
        switch mode {
        case .history: return texts.tr("ui.edit_bar.history_note")
        case .simplify:
            if !problem.isEmpty { return texts.tr("ui.edit_bar.measure_failed", ["error": problem]) }
            return texts.tr(order != nil ? "ui.edit_bar.simplify_note" : "ui.edit_bar.measuring")
        }
    }

    /// The button that takes the sketch shown.
    public func applyLabel(_ texts: Texts) -> String {
        texts.tr(mode == .history ? "ui.edit_bar.take" : "ui.edit_bar.apply")
    }

    /// _iter_of: the iteration in a step's name (svg_iter<i>.svg; -1 when it has none).
    public nonisolated static func iteration(_ url: URL) -> Int {
        let name = url.lastPathComponent
        guard name.hasPrefix("svg_iter"), name.hasSuffix(".svg") else { return -1 }
        let digits = name.dropFirst(8).dropLast(4)
        return !digits.isEmpty && digits.allSatisfy({ $0.isASCII && $0.isNumber }) ? Int(digits) ?? -1 : -1
    }

    private func refresh() {
        switch mode {
        case .history:
            preview = (try? String(contentsOf: frames[value], encoding: .utf8)) ?? svg
        case .simplify:
            preview = kept(value)
        }
    }
}
