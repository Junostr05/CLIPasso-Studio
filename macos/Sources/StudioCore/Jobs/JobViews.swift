import Foundation

/// The views of a job besides its sketch (pages/studio.py's canvas modes): the photo as the method used it (for the
/// photo / sketch divider), the attention map of the shown sketch, the object mask, the condition (ControlSketch) or
/// the background (SceneSketch). A finished job has them as files (studio._load_job); a running one sends them as
/// events (input, attention, condition), kept with its QueuedJob.
public enum JobViews {
    /// VIEWS: the canvas's modes besides the sketch, in their order
    public static let kinds = ["compare", "attention", "mask", "condition"]

    /// The modes a method has (studio._method_changed): no attention for SwiftSketch, a condition only for
    /// ControlSketch and SceneSketch (its background).
    public static func kinds(for method: String) -> [String] {
        kinds.filter { kind in
            switch kind {
            case "attention": method != "swiftsketch"
            case "condition": ["controlsketch", "scenesketch"].contains(method)
            default: true
            }
        }
    }

    /// _load_job: the views' files of a finished job – `run` the shown sketch's run (its attention map).
    public static func files(jobDir: URL, summary: JobSummary, run: URL?) -> [String: URL] {
        let manager = FileManager.default
        func there(_ url: URL) -> URL? { manager.fileExists(atPath: url.path) ? url : nil }
        let scene = summary.method == "scenesketch"
        var out: [String: URL] = [:]
        let runs = summary.runs.compactMap { r -> (name: String, dir: URL)? in
            guard let dir = r["run_dir"]?.stringValue, !dir.isEmpty else { return nil }
            return (r["run_name"]?.stringValue ?? "", URL(filePath: dir, directoryHint: .isDirectory))
        }
        for r in runs {  // (each run in turn: the last one's mask and condition stay, as on the canvas)
            let names = ((try? manager.contentsOfDirectory(atPath: r.dir.path)) ?? []).sorted()
            var condition = names.first { $0.hasSuffix("_condition.png") }.map { r.dir.appending(path: $0) }
            if scene, let background = there(jobDir.appending(path: "background.png")) { condition = background }
            if let condition { out["condition"] = condition }
            if let mask = there(r.dir.appending(path: "mask.png")) ?? there(jobDir.appending(path: "mask.png")) {
                out["mask"] = mask
            }
        }
        // the photo as the method used it (masked, framed, padded): of the best run first
        let ordered = runs.sorted { ($0.name != summary.bestRun ? 1 : 0) < ($1.name != summary.bestRun ? 1 : 0) }
        if let input = ordered.lazy.compactMap({ there($0.dir.appending(path: "input.png")) }).first {
            out["compare"] = input
        }
        if let run {
            var attention = run.appending(path: "attention_map.png")
            if scene, !manager.fileExists(atPath: attention.path) { attention = sceneAttention(jobDir, run) }
            if let attention = there(attention) { out["attention"] = attention }
        }
        return out
    }

    /// _scene_attention: a SceneSketch cell's attention map lies in the run of its background part (also when the
    /// job folder has moved since).
    static func sceneAttention(_ jobDir: URL, _ cell: URL) -> URL {
        guard let data = try? Data(contentsOf: cell.appending(path: "config.json")),
              let run = (try? PyJSON.parse(data))?.objectValue?["background_run"]?.stringValue
        else { return cell.appending(path: "attention_map.png") }
        let path = URL(filePath: run).appending(path: "attention_map.png")
        if FileManager.default.fileExists(atPath: path.path) { return path }
        let parts = run.split(separator: "/").map(String.init)
        guard let i = parts.firstIndex(of: "runs") else { return path }
        return parts[i...].reduce(jobDir) { $0.appending(path: $1) }.appending(path: "attention_map.png")
    }
}
