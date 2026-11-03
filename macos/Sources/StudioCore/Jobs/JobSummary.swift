import Foundation

/// What a job folder says about its job (JobFolder.summaryJSON) – the same dictionary as Python's `jobs.job_summary`,
/// with typed accessors for what the app shows.
public struct JobSummary: Sendable, Hashable {
    public let jobDir: URL
    public let json: JSONObject

    public var target: String { json["target"]?.stringValue ?? "" }
    public var created: String { json["created"]?.stringValue ?? "" }
    public var settings: JSONObject { json["settings"]?.objectValue ?? [:] }
    public var method: String {
        json["method"]?.stringValue ?? settings["method"]?.stringValue ?? "clipasso"
    }
    public var clipScore: Double? { json["clip_score"]?.doubleValue }
    public var bestSVG: String { json["best_svg"]?.stringValue ?? "" }
    public var bestRun: String { json["best_run"]?.stringValue ?? "" }
    public var runs: [JSONObject] { json["runs"]?.arrayValue?.compactMap(\.objectValue) ?? [] }
    /// running · interrupted · cancelled · failed · done (nil for a job of CLIPasso Studio 2.x)
    public var state: String? { json["state"]?.stringValue }
    public var progress: (done: Int, total: Int)? {
        guard let p = json["progress"]?.arrayValue, p.count == 2, let done = p[0].intValue, let total = p[1].intValue
        else { return nil }
        return (done, total)
    }
    public var seconds: Double { json["seconds"]?.doubleValue ?? 0 }

    // the user's own data (meta.json)
    public var favourite: Bool { json["favourite"]?.truthy ?? false }
    public var title: String { json["title"]?.stringValue ?? "" }
    public var notes: String { json["notes"]?.stringValue ?? "" }
    public var tags: [String] { json["tags"]?.arrayValue?.compactMap(\.stringValue) ?? [] }
    public var albums: [String] { json["albums"]?.arrayValue?.compactMap(\.stringValue) ?? [] }
    public var ratings: [String: Int] {
        var out: [String: Int] = [:]
        for (run, value) in json["ratings"]?.objectValue ?? [:] {
            out[run] = value.intValue
        }
        return out
    }

    public static func == (lhs: JobSummary, rhs: JobSummary) -> Bool {
        lhs.jobDir == rhs.jobDir && lhs.json == rhs.json
    }

    public func hash(into hasher: inout Hasher) {
        hasher.combine(jobDir)
        hasher.combine(json)
    }
}
