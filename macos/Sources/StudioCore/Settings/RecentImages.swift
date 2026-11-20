import Foundation

/// The studio's "recent" pictures (pages/studio.StudioPage._remember_recent): the picture chosen first, an older
/// entry of the same path dropped, at most 12 – the bundled samples never (by their folder's beginning, as the
/// studio tests it).
public enum RecentImages {
    public static let maximum = 12

    /// os.path.abspath of an absolute path: "//", "." and ".." taken out.
    public static func normalized(_ path: String) -> String {
        var parts: [Substring] = []
        for part in path.split(separator: "/", omittingEmptySubsequences: true) {
            switch part {
            case ".": continue
            case "..": if !parts.isEmpty { parts.removeLast() }
            default: parts.append(part)
            }
        }
        return "/" + parts.joined(separator: "/")
    }

    /// The list with `path` first; nil when it is one of the samples (nothing changes).
    public static func remember(_ path: String, in list: [String], samples: String) -> [String]? {
        if !samples.isEmpty, normalized(path).hasPrefix(normalized(samples)) { return nil }
        let key = normalized(path)
        let rest = list.filter { normalized($0) != key }
        return [path] + rest.prefix(maximum - 1)
    }
}
