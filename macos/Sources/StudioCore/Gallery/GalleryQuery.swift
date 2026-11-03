import Foundation

/// The gallery's orders (gui/pages/gallery.py `SORTS`).
public enum GallerySort: String, Sendable, CaseIterable {
    case newest, oldest, score, duration, strokes, name
}

/// What the gallery shows: the words of the search, the method (nil: all), only favourites, a tag, an album, the order.
public struct GalleryQuery: Sendable, Hashable {
    public var text: String
    public var method: String?
    public var favouritesOnly: Bool
    public var tag: String?
    public var album: String?
    public var sort: GallerySort

    public init(text: String = "", method: String? = nil, favouritesOnly: Bool = false, tag: String? = nil,
                album: String? = nil, sort: GallerySort = .newest)
    {
        self.text = text
        self.method = method
        self.favouritesOnly = favouritesOnly
        self.tag = tag
        self.album = album
        self.sort = sort
    }

    /// The search's words in lower case (Python's `text.lower().split()`).
    public var words: [String] {
        text.lowercased().split(whereSeparator: \.isWhitespace).map(String.init)
    }

    public func includes(_ item: GalleryItem) -> Bool {
        item.matches(words) && (method == nil || item.method == method) && (!favouritesOnly || item.favourite)
            && (tag.map { item.tags.contains($0) } ?? true) && (album.map { item.albums.contains($0) } ?? true)
    }

    /// gallery.sort_items: a stable sort, the reverse orders too (as Python's `sort(reverse=True)`: equal keys keep
    /// their order).
    public func sorted(_ items: [GalleryItem]) -> [GalleryItem] {
        func stable<K: Comparable>(_ key: (GalleryItem) -> K, descending: Bool) -> [GalleryItem] {
            items.enumerated().sorted { a, b in
                let ka = key(a.element), kb = key(b.element)
                if ka != kb { return descending ? ka > kb : ka < kb }
                return a.offset < b.offset
            }.map(\.element)
        }
        switch sort {
        case .newest: return stable({ $0.created }, descending: true)
        case .oldest: return stable({ $0.created }, descending: false)
        case .score: return stable({ ScoreKey(has: $0.score != nil, value: $0.score ?? 0) }, descending: true)
        case .duration: return stable({ $0.seconds }, descending: true)
        case .strokes: return stable({ $0.strokes }, descending: false)
        case .name: return stable({ $0.name.lowercased() }, descending: false)
        }
    }
}

/// (score is not None, score or 0.0)
private struct ScoreKey: Comparable {
    let has: Bool
    let value: Double

    static func < (a: ScoreKey, b: ScoreKey) -> Bool {
        a.has != b.has ? !a.has : a.value < b.value
    }
}
