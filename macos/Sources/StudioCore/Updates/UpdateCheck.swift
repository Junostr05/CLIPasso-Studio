import Foundation

/// The newest release of CLIPasso Studio, as gui/updates.py finds it (the latest final release from the GitHub
/// API, versions compared with parse_version) – announced only when it carries a Mac disk image; the app then opens
/// its page (no self-update: the app is not signed).
public enum UpdateCheck {
    public static let api = URL(string: "https://api.github.com/repos/Junostr05/CLIPasso-Studio/releases/latest")!

    public struct Release: Sendable, Hashable {
        public let version: String
        public let page: URL
    }

    public struct CheckError: Error, CustomStringConvertible, Sendable {
        public let description: String
    }

    private static let stages = ["a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2]  // a final release ranks above
    private static let pattern = try! NSRegularExpression(
        pattern: #"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(alpha|beta|rc|a|b)\.?(\d*))?"#,
        options: [.caseInsensitive])

    /// updates.parse_version: "v2.1.0" / "2.1.0b1" / "v2.1.0-beta.1" → comparable numbers.
    public static func parse(_ text: String) -> [Int] {
        let range = NSRange(text.startIndex..., in: text)
        guard let m = pattern.firstMatch(in: text, range: range) else { return [0] }
        func group(_ i: Int) -> String? {
            Range(m.range(at: i), in: text).map { String(text[$0]) }
        }
        let numbers = (1...3).map { Int(group($0) ?? "") ?? 0 }
        let stage = group(4).map { stages[$0.lowercased()] ?? 3 } ?? 3
        return numbers + [stage, Int(group(5) ?? "") ?? 0]
    }

    public static func isNewer(_ latest: String, than current: String) -> Bool {
        parse(current).lexicographicallyPrecedes(parse(latest))  // (tuples compared as Python compares them)
    }

    /// The newest final release when it is newer than `current` and has a Mac disk image; nil otherwise.
    public static func newer(than current: String, transport: any HTTPTransport = URLSessionTransport(),
                             url: URL = api) async throws -> Release?
    {
        let response = try await transport.open(url, offset: 0)
        var data = Data()
        for try await chunk in response.body {
            data.append(chunk)
            if data.count > 2_000_000 { break }
        }
        guard (200..<300).contains(response.status) else {
            throw CheckError(description: "the release list answered \(response.status)")
        }
        guard let o = try PyJSON.parse(data).objectValue, let tag = o["tag_name"]?.stringValue,
              o["draft"]?.truthy != true, o["prerelease"]?.truthy != true
        else { return nil }
        let assets = (o["assets"]?.arrayValue ?? []).compactMap { $0.objectValue?["name"]?.stringValue }
        guard assets.contains(where: { $0.lowercased().hasSuffix("-mac.dmg") }), isNewer(tag, than: current) else {
            return nil
        }
        let page = o["html_url"]?.stringValue.flatMap(URL.init(string:))
            ?? URL(string: "https://github.com/Junostr05/CLIPasso-Studio/releases/latest")!
        return Release(version: tag, page: page)
    }
}
