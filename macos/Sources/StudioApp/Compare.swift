import Foundation
import Observation
import StudioCore

/// The compare page (gui/pages/compare.py): the studio's picture sketched with several methods, the latest result of
/// each for this picture side by side, the one CLIP finds most similar marked.
@Observable
public final class CompareModel {
    /// compare.ORDER: the fastest first, so the first results come early
    public nonisolated static let order = ["swiftsketch", "clipasso", "controlsketch", "scenesketch"]

    /// the methods to compare (SceneSketch is off at first: it is for scenes and takes much longer)
    public var chosen: Set<String>
    /// the studio's settings of each method – else its preset "standard"
    public var useStudio = false

    public init(methods: [String]) {
        chosen = Set(methods.filter { $0 != "scenesketch" })
    }

    /// One method's column: its latest result for the picture and its job in the queue.
    public struct Entry: Sendable, Hashable, Identifiable {
        public enum State: String, Sendable { case none, done, running, queued }
        public var id: String { method }
        public let method: String
        public let state: State
        public let progress: Double
        public let item: GalleryItem?
        public let best: Bool

        public var score: Double? { item?.score }
        public var seconds: Double { item?.seconds ?? 0 }
        public var strokes: Int { item?.strokes ?? 0 }
    }
}

public extension AppModel {
    /// compare.overview / refresh: every method's latest result for `image` (newest first by its date) and its job
    /// waiting or running; the best is the highest CLIP score when more than one has a score.
    func compareOverview(_ image: URL?) -> [CompareModel.Entry] {
        let path = image.map { $0.standardizedFileURL.path }
        var latest: [String: GalleryItem] = [:]
        if let path {
            let finished = gallery.everything.filter {
                ($0.state == nil || $0.state == "done") && !$0.summary.target.isEmpty
                    && URL(filePath: $0.summary.target).standardizedFileURL.path == path
            }
            for item in finished.sorted(by: { $0.created > $1.created }) where latest[item.method] == nil {
                latest[item.method] = item
            }
        }
        var active: [String: QueuedJob] = [:]
        if let path {
            for job in queueSnapshot?.jobs ?? [] where [.queued, .running, .paused].contains(job.status)
                && job.target.standardizedFileURL.path == path
            {
                let method = job.settings["method"]?.stringValue ?? schema.defaultMethod
                if active[method] == nil { active[method] = job }
            }
        }
        let scored = schema.methods.compactMap { m in latest[m]?.score.map { (m, $0) } }
        var best: String?  // (the first of the highest, in the methods' order)
        if scored.count > 1 {
            best = scored.reduce(scored[0]) { $1.1 > $0.1 ? $1 : $0 }.0
        }
        return schema.methods.map { method in
            let job = active[method]
            let state: CompareModel.Entry.State = job.map { $0.isActive ? .running : .queued }
                ?? (latest[method] != nil ? .done : .none)
            return CompareModel.Entry(method: method, state: state, progress: job?.progress ?? 0, item: latest[method],
                                      best: method == best)
        }
    }

    /// compare._settings: the studio's settings of the method, or its preset "standard" on the studio's device.
    func compareSettings(_ method: String, useStudio: Bool) -> JSONObject {
        if useStudio { return studio.settings(for: method) }
        guard let m = schema.method(method) else { return ["method": .string(method)] }
        var out = m.applyPreset("standard", to: m.start)
        if let device = studio.settings["device"] { out["device"] = device }
        out["method"] = .string(method)
        return out
    }

    /// What the compare asks before it starts (compare.start): without a GPU (neither CUDA nor Apple's), whether
    /// ControlSketch should still be queued and whether SceneSketch should use its preset "fast" – the keys of the
    /// questions (ui.compare.cpu_warning, ui.compare.scene_cpu_warning).
    func compareQuestions(_ methods: Set<String>, useStudio: Bool) async -> [String] {
        guard let engine, let devices = try? await engine.request("devices", timeout: .seconds(30)).objectValue,
              !(devices["cuda"]?.truthy ?? false), !(devices["mps"]?.truthy ?? false)
        else { return [] }
        var asks: [String] = []
        if methods.contains("controlsketch") { asks.append("controlsketch_cpu") }
        if methods.contains("scenesketch"), !useStudio { asks.append("scene_fast") }
        return asks
    }

    /// The settings of each method chosen, the fastest first.
    func compareJobs(_ chosen: Set<String>, useStudio: Bool) -> [(method: String, settings: JSONObject)] {
        CompareModel.order.filter { chosen.contains($0) && schema.method($0) != nil }
            .map { ($0, compareSettings($0, useStudio: useStudio)) }
    }

    /// The models the jobs need that are not there (in the order first needed).
    func compareMissing(_ jobs: [(method: String, settings: JSONObject)]) async -> [String] {
        guard let engine else { return [] }
        var missing: [String] = []
        for job in jobs {
            if let answer = try? await engine.request("required_models", ["settings": .object(job.settings)]) {
                for key in answer.objectValue?["missing"]?.arrayValue?.compactMap(\.stringValue) ?? []
                where !missing.contains(key) { missing.append(key) }
            }
        }
        return missing
    }

    /// enqueue_compare: the studio's picture with each method – after the answers to the questions (`answers`: key →
    /// yes: no ControlSketch on "no", SceneSketch's preset "fast" on "yes"). The number of jobs queued.
    func queueCompare(_ jobs: [(method: String, settings: JSONObject)], answers: [String: Bool]) async -> Int {
        guard let image = studio.image, let queue else { return 0 }
        var queued = 0
        for var job in jobs {
            if job.method == "controlsketch", answers["controlsketch_cpu"] == false { continue }
            if job.method == "scenesketch", answers["scene_fast"] == true, let m = schema.method("scenesketch") {
                job.settings = m.applyPreset("fast", to: job.settings)
            }
            await queue.add(target: image, settings: job.settings)
            queued += 1
        }
        apply(await queue.snapshot())
        return queued
    }

    /// compare.start: missing models are asked for first in the window (then nothing is queued); the number of jobs
    /// queued.
    @discardableResult
    func startCompare(_ compare: CompareModel, answers: [String: Bool] = [:]) async -> Int {
        guard studio.image != nil, queue != nil, engine != nil else { return 0 }
        let jobs = compareJobs(compare.chosen, useStudio: compare.useStudio)
        let missing = await compareMissing(jobs)
        guard missing.isEmpty else {
            models.startsJob = false
            models.stage = .asking(missing.sorted())
            return 0
        }
        return await queueCompare(jobs, answers: answers)
    }

    /// The phone's compare (get_compare, do_compare): every method's column as the phone page reads it; the jobs
    /// started as on the PC – the questions and the missing models come back to be answered there.
    internal func phoneCompareAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let image = studio.image.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil }
        switch action {
        case "get_compare":
            let entries = compareOverview(image)
            var methods: [JSONValue] = []
            for e in entries {
                var row = JSONObject()
                row["key"] = .string(e.method)
                row["name"] = .string(schema.method(e.method)?.name ?? e.method)
                row["default"] = .bool(e.method != "scenesketch")
                row["best"] = .bool(e.best)
                row["time"] = .string(e.seconds > 0 ? PhoneRemote.eta(e.seconds) : "")
                row["state"] = .string(e.state.rawValue)
                row["progress"] = .double((e.progress * 1000).rounded() / 1000)
                row["dir"] = .string(e.item?.jobDir.lastPathComponent ?? "")
                if let score = e.score { row["score"] = .double(score) } else { row["score"] = .null }
                row["seconds"] = .double(e.seconds)
                row["strokes"] = .int(e.strokes)
                row["created"] = .string(String((e.item?.created ?? "").prefix(16)))
                methods.append(.object(row))
            }
            let out: JSONObject = ["ok": true, "image": .string(image?.lastPathComponent ?? ""), "methods": .array(methods)]
            return .json(.object(out))
        case "do_compare":
            guard image != nil else { return no(texts.tr("ui.phone.page.no_picture")) }
            let wanted = Set((data["methods"]?.arrayValue ?? []).compactMap(\.stringValue))
            let use = data["use_studio"]?.truthy ?? false
            let jobs = compareJobs(wanted, useStudio: use)
            let missing = await compareMissing(jobs)
            if !missing.isEmpty {
                let mb = Double(missing.reduce(0) { $0 + (catalog.spec($1)?.downloadSize ?? 0) }) / 1e6
                return .json(["ok": false, "missing": .array(missing.map(JSONValue.string)),
                              "error": .string(texts.tr("ui.phone.page.models_missing",
                                                        ["size": String(format: "%.0f", mb)]))])
            }
            var asks: [JSONValue] = []
            var answers: [String: Bool] = [:]
            for key in await compareQuestions(Set(jobs.map(\.method)), useStudio: use) {
                if let given = data[key], given != .null {
                    answers[key] = given.truthy
                } else {
                    asks.append(["key": .string(key), "text": .string(texts.tr(
                        key == "controlsketch_cpu" ? "ui.compare.cpu_warning" : "ui.compare.scene_cpu_warning"))])
                }
            }
            if !asks.isEmpty { return .json(["ok": false, "asks": .array(asks)]) }
            let queued = await queueCompare(jobs, answers: answers)
            guard queued > 0 else { return no(texts.tr("ui.phone.page.compare_none")) }
            return .json(["ok": true, "queued": .int(queued)])
        default:
            return nil
        }
    }
}
