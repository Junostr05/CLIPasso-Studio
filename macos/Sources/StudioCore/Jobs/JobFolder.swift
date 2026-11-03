import Foundation

/// A job folder, read and written exactly as engine/jobs.py does, so results move between the Windows app and the Mac
/// app (and their backups) as they are:
///
/// - read: `job.json`, `job_state.json`, `meta.json`, `<run>/result.json`, `edited.svg`, `input/`
/// - written: only `meta.json` (the user's own data: `metaKeys`) and the status in `job_state.json` – each atomically
///   (a `.tmp` file renamed), in the JSON style Python writes them.
public enum JobFolder {
    public static let summaryFile = "job.json"
    public static let stateFile = "job_state.json"
    public static let metaFile = "meta.json"
    public static let resultFile = "result.json"
    public static let editedFile = "edited.svg"
    public static let inputDir = "input"
    public static let initSVG = "init.svg"
    /// The user's data about a job – kept when the job is continued (jobs.META_KEYS).
    public static let metaKeys = ["favourite", "title", "notes", "tags", "albums", "ratings"]
    /// The fields of a sketch's result.json (jobs.SeedResult) and the defaults of the optional ones.
    static let resultFields = ["seed", "run_name", "run_dir", "best_loss", "best_iter", "iterations_done", "best_svg",
                               "status"]
    static let resultDefaults: [(String, JSONValue)] = [("method", "clipasso"), ("clip_score", nil),
                                                        ("seconds", 0.0), ("pruned", false)]
    /// The statuses of a job that can be continued (with work left).
    public static let continuable: Set<String> = ["running", "interrupted", "cancelled", "failed"]

    public struct UnknownMetaKey: Error, CustomStringConvertible, Sendable {
        public let key: String
        public var description: String { "\(key) is not one of the job's own data (\(JobFolder.metaKeys))" }
    }

    // MARK: - reading

    static func readObject(_ url: URL) -> JSONObject? {
        guard let data = try? Data(contentsOf: url), let value = try? PyJSON.parse(data) else { return nil }
        return value.objectValue
    }

    /// jobs.read_state: what the job computes and whether it still runs.
    public static func readState(at jobDir: URL) -> JSONObject? {
        guard var state = readObject(jobDir.appending(path: stateFile)) else { return nil }
        if var settings = state["settings"]?.objectValue {
            if settings["mask_model"] == nil { settings["mask_model"] = "u2net" }  // jobs from before 2.4
            if settings["frame_object"] == nil { settings["frame_object"] = false }
            if case .string(let svg)? = settings["path_svg"] {
                settings["path_svg"] = .string(rebase(svg, jobDir: jobDir))
            }
            state["settings"] = .object(settings)
        }
        return state
    }

    /// jobs.read_meta: the user's data (other keys are left out); empty when there is none or it is damaged.
    public static func readMeta(at jobDir: URL) -> JSONObject {
        guard let meta = readObject(jobDir.appending(path: metaFile)) else { return [:] }
        return JSONObject(meta.filter { metaKeys.contains($0.key) }.map { ($0.key, $0.value) })
    }

    static func names(in folder: URL) -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }  // (Python's sorted)
    }

    static func rebaseRun(_ run: JSONObject, jobDir: URL) -> JSONObject {
        var run = run
        for key in ["run_dir", "best_svg"] {
            if case .string(let path)? = run[key] {
                run[key] = .string(rebase(path, jobDir: jobDir))
            }
        }
        return run
    }

    /// jobs.saved_results: the sketches saved in the folder (their result.json, the sketch file there), by seed (the
    /// cell for SceneSketch), in the order of their folders' names.
    public static func savedResults(at jobDir: URL) -> [(seed: Int, result: JSONObject)] {
        var out: [(seed: Int, result: JSONObject)] = []
        for name in names(in: jobDir) {
            guard let raw = readObject(jobDir.appending(path: name).appending(path: resultFile)) else { continue }
            let known = Set(resultFields + resultDefaults.map(\.0))
            guard resultFields.allSatisfy({ raw[$0] != nil }), raw.keys.allSatisfy(known.contains) else {
                continue  // (SeedResult(**data) would fail in Python)
            }
            var result = JSONObject(resultFields.map { ($0, raw[$0]!) })
            for (key, fallback) in resultDefaults {
                result[key] = raw[key] ?? fallback
            }
            result = rebaseRun(result, jobDir: jobDir)
            guard let seed = result["seed"]?.intValue, case .string(let svg)? = result["best_svg"],
                  FileManager.default.fileExists(atPath: svg)
            else { continue }
            out.removeAll { $0.seed == seed }
            out.append((seed, result))
        }
        return out
    }

    static func doneResults(at jobDir: URL) -> [Int: JSONObject] {
        var out: [Int: JSONObject] = [:]
        for (seed, result) in savedResults(at: jobDir) where result["status"] == .string("done") {
            out[seed] = result
        }
        return out
    }

    /// jobs.progress_of: (finished items, all items).
    public static func progress(at jobDir: URL, state: JSONObject? = nil) -> (done: Int, total: Int) {
        let seeds = (state ?? readState(at: jobDir))?["seeds"]?.arrayValue?.compactMap(\.intValue) ?? []
        let done = doneResults(at: jobDir)
        return (seeds.filter { done[$0] != nil }.count, seeds.count)
    }

    /// jobs.job_summary: job.json – or, for a job interrupted before it was finished, the same built from its state
    /// and the sketches finished so far – with `state`, `progress` and the user's data. nil for a folder that is no
    /// job folder.
    public static func summaryJSON(at jobDir: URL) -> JSONObject? {
        var summary = readObject(jobDir.appending(path: summaryFile))
        let state = readState(at: jobDir)
        if summary == nil {
            guard let state else { return nil }
            var results = savedResults(at: jobDir).map(\.result)
            let settings = state["settings"]?.objectValue ?? [:]
            let method = state["method"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 }
                ?? settings["method"]?.stringValue ?? "clipasso"
            var best: JSONObject?
            if !results.isEmpty {
                let kept = results.filter { !($0["pruned"]?.truthy ?? false) }
                results = kept.isEmpty ? results : kept
                let scored = results.filter { !($0["clip_score"]?.isNull ?? true) }
                func score(_ r: JSONObject) -> Double { r["clip_score"]?.doubleValue ?? 0 }
                func loss(_ r: JSONObject) -> Double { r["best_loss"]?.doubleValue ?? .infinity }
                if method != "clipasso", !scored.isEmpty {
                    best = scored.reduce(scored[0]) { score($1) > score($0) ? $1 : $0 }  // (the first of equals)
                } else {
                    best = results.reduce(results[0]) { loss($1) < loss($0) ? $1 : $0 }
                }
            }
            summary = ["target": state["target"] ?? "", "created": state["created"] ?? "",
                       "settings": state["settings"] ?? [:], "method": .string(method),
                       "clip_score": best?["clip_score"] ?? nil, "best_svg": best?["best_svg"] ?? "",
                       "best_run": best?["run_name"] ?? "", "runs": .array(results.map(JSONValue.object))]
        }
        guard var summary else { return nil }
        summary["best_svg"] = .string(rebase(summary["best_svg"]?.stringValue ?? "", jobDir: jobDir))
        if let runs = summary["runs"]?.arrayValue {
            summary["runs"] = .array(runs.map { run in
                run.objectValue.map { .object(rebaseRun($0, jobDir: jobDir)) } ?? run
            })
        }
        if let state {
            summary["state"] = state["status"] ?? "done"
            let p = progress(at: jobDir, state: state)
            summary["progress"] = [.int(p.done), .int(p.total)]
        }
        for (key, value) in readMeta(at: jobDir) {  // (a favourite of version 2.x is still in job.json)
            summary[key] = value
        }
        return summary
    }

    public static func summary(at jobDir: URL) -> JobSummary? {
        summaryJSON(at: jobDir).map { JobSummary(jobDir: jobDir, json: $0) }
    }

    /// jobs.summary_can_continue: interrupted, cancelled or failed with work left.
    public static func canContinue(_ summary: JobSummary) -> Bool {
        guard let state = summary.state, continuable.contains(state), let p = summary.progress else { return false }
        return p.done < p.total
    }

    /// jobs.best_sketch: the best sketch of a job, the touched-up one (edited.svg) if there is one.
    public static func bestSketch(_ summary: JobSummary) -> URL? {
        for run in summary.runs where run["run_name"]?.stringValue == summary.bestRun {
            if let runDir = run["run_dir"]?.stringValue, !runDir.isEmpty {
                let edited = URL(filePath: runDir).appending(path: editedFile)
                if FileManager.default.fileExists(atPath: edited.path) { return edited }
            }
        }
        return summary.bestSVG.isEmpty ? nil : URL(filePath: summary.bestSVG)
    }

    /// jobs.saved_input: the copy of the input image in the folder – `input/<name>`, or `source.<ext>` of CLIPasso
    /// Studio 2.1 and older.
    public static func savedInput(jobDir: URL, target: String) -> URL? {
        let folder = jobDir.appending(path: inputDir)
        let files = names(in: folder).filter { $0 != initSVG }
        let name = fileName(target)
        if files.contains(name) { return folder.appending(path: name) }
        if let first = files.first { return folder.appending(path: first) }
        if let old = names(in: jobDir).first(where: { $0.hasPrefix("source.") }) {
            return jobDir.appending(path: old)
        }
        return nil
    }

    // MARK: - writing

    static func writeAtomically(_ text: String, to url: URL) throws {
        let tmp = url.appendingPathExtension("tmp")
        try Data(text.utf8).write(to: tmp)
        guard rename(tmp.path, url.path) == 0 else {
            let code = errno
            try? FileManager.default.removeItem(at: tmp)
            throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: url.path,
                                                           NSUnderlyingErrorKey: POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO)])
        }
    }

    /// jobs.write_meta: change the user's data of a job – a value of nil (or null) removes it, a key keeps its place
    /// – and return all of it. Written as `json.dump(meta, indent=2, ensure_ascii=False)` writes it.
    @discardableResult
    public static func writeMeta(at jobDir: URL, _ changes: [(String, JSONValue?)]) throws -> JSONObject {
        var meta = readMeta(at: jobDir)
        for (key, value) in changes {
            guard metaKeys.contains(key) else { throw UnknownMetaKey(key: key) }
            meta[key] = (value?.isNull ?? true) ? nil : value
        }
        try writeAtomically(PyJSON.dump(.object(meta), indent: 2), to: jobDir.appending(path: metaFile))
        return meta
    }

    /// The status in job_state.json (jobs.set_status); the rest stays as Python wrote it. A job set running again is
    /// offered again when it is interrupted ("asked" goes).
    public static func setStatus(at jobDir: URL, _ status: String) throws {
        let url = jobDir.appending(path: stateFile)
        guard var state = readObject(url), state["status"]?.stringValue != status else { return }
        state["status"] = .string(status)
        if status == "running" { state["asked"] = nil }
        try writeAtomically(PyJSON.dump(.object(state), indent: 2, asciiOnly: true), to: url)
    }
}
