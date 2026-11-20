import Foundation
import Observation
import StudioCore

/// The gallery's large view (gui/gallery_viewer.GalleryViewer): one result at a time, the arrow keys going through
/// the results shown, a slideshow going on by itself (a step by hand gives the next one a full interval).
@Observable
public final class ViewerModel {
    /// INTERVALS: seconds a result stays in the slideshow
    public static let intervals = [2, 3, 5, 10]

    /// the results with a sketch file, in the gallery's order
    public let items: [GalleryItem]
    public private(set) var index: Int
    /// the shown result's sketch (nil: none, or its file is gone)
    public private(set) var svg: String?
    public private(set) var playing = false
    public var interval = 3 {
        didSet { if playing { restart() } }
    }
    @ObservationIgnored private var ticker: Task<Void, Never>?
    /// for the tests: how a slideshow waits
    @ObservationIgnored var sleep: @Sendable (Int) async throws -> Void = { try await Task.sleep(for: .seconds($0)) }

    /// two marked results to compare on top of each other (empty: none)
    public let pair: [GalleryItem]
    public private(set) var comparing = false
    /// the pair's sketches while comparing
    public private(set) var pairSVG: (String?, String?) = (nil, nil)

    public init(items: [GalleryItem], index: Int = 0, pair: [GalleryItem] = []) {
        let shown = items.filter { $0.bestSketch.map { FileManager.default.fileExists(atPath: $0.path) } ?? false }
        let wanted = index < items.count ? items[index] : nil
        self.items = shown
        self.index = wanted.flatMap { w in shown.firstIndex { $0.id == w.id } } ?? 0
        self.pair = pair.count >= 2 ? Array(pair.prefix(2)) : []
        load()
    }

    /// set_compare: the two marked results on top of each other (the slideshow stops; going through stops too).
    public func setCompare(_ on: Bool) {
        comparing = on && pair.count == 2
        if comparing {
            setSlideshow(false)
            pairSVG = (Self.read(pair[0]), Self.read(pair[1]))
        }
    }

    static func read(_ item: GalleryItem) -> String? {
        item.bestSketch.flatMap { try? String(contentsOf: $0, encoding: .utf8) }
    }

    deinit {
        ticker?.cancel()
    }

    public var current: GalleryItem? { items.isEmpty ? nil : items[index] }

    /// "3 / 12"
    public var position: String { items.isEmpty ? "" : "\(index + 1) / \(items.count)" }

    public func show(_ i: Int) {
        guard !items.isEmpty else { return }
        index = min(max(i, 0), items.count - 1)
        load()
        if playing { restart() }  // (a step by hand: the next one a full interval later)
    }

    /// The next result; after the last the first again in a slideshow (or with `wrap`).
    public func next(wrap: Bool = false) {
        guard !items.isEmpty, !comparing else { return }
        if index + 1 < items.count {
            show(index + 1)
        } else if wrap || playing {
            show(0)
        }
    }

    /// The one before; before the first the last in a slideshow.
    public func previous() {
        guard !items.isEmpty, !comparing else { return }
        if index > 0 {
            show(index - 1)
        } else if playing {
            show(items.count - 1)
        }
    }

    /// set_slideshow: on only with more than one result.
    public func setSlideshow(_ on: Bool) {
        playing = on && items.count > 1 && !comparing
        ticker?.cancel()
        ticker = nil
        if playing { restart() }
    }

    private func restart() {
        ticker?.cancel()
        let seconds = interval, sleep = sleep
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                do { try await sleep(seconds) } catch { return }
                guard let self, !Task.isCancelled else { return }
                let at = index
                index = at + 1 < items.count ? at + 1 : 0
                load()
            }
        }
    }

    private func load() {
        svg = current?.bestSketch.flatMap { try? String(contentsOf: $0, encoding: .utf8) }
    }

    /// describe: method · score · strokes · time · date of a result (one line).
    public static func describe(_ item: GalleryItem, texts: Texts) -> String {
        var parts = [item.methodName]
        if let score = item.score { parts.append("CLIP \(texts.number(score))") }
        if item.strokes > 1 { parts.append(texts.tr("ui.viewer.strokes", ["n": String(item.strokes)])) }
        let seconds = Int(item.seconds.rounded())
        if seconds > 0 {
            parts.append(seconds >= 60 ? String(format: "%d:%02d min", seconds / 60, seconds % 60) : "\(seconds) s")
        }
        if !item.created.isEmpty {
            parts.append(String(item.created.prefix(16)).replacingOccurrences(of: "T", with: " "))
        }
        return parts.joined(separator: " · ")
    }
}
