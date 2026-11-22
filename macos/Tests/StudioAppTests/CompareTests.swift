import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The compare page (compare.py): the latest result of every method for the studio's picture, the best by CLIP
/// score; a compare queues one job per method chosen, the fastest first – after the questions without a GPU.
@Suite(.serialized) struct CompareTests {
    /// An output folder with results for Kamel.png: CLIPasso (0.7, older and newer), SwiftSketch (0.8) – and one of
    /// another picture.
    static func results() throws -> URL {
        let out = FileManager.default.temporaryDirectory.appending(path: "compare-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let made: [(String, String, Double, String, String)] = [
            ("alt", "clipasso", 0.5, "2026-03-01 10:00:00", "/Users/studio/Pictures/Kamel.png"),
            ("neu", "clipasso", 0.7, "2026-03-14 15:09:26", "/Users/studio/Pictures/Kamel.png"),
            ("swift", "swiftsketch", 0.8, "2026-03-12 09:00:00", "/Users/studio/Pictures/Kamel.png"),
            ("giraffe", "swiftsketch", 0.9, "2026-03-13 09:00:00", "/Users/studio/Pictures/Giraffe.png"),
        ]
        for (name, method, score, created, target) in made {
            let dir = out.appending(path: name)
            try FileManager.default.copyItem(at: done, to: dir)
            for name in ["job.json", JobFolder.stateFile] {  // (the summary reads both)
                let file = dir.appending(path: name)
                guard FileManager.default.fileExists(atPath: file.path) else { continue }
                var json = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
                var settings = json["settings"] as? [String: Any] ?? [:]
                settings["method"] = method
                json["settings"] = settings
                json["method"] = method
                json["clip_score"] = score
                json["created"] = created
                json["target"] = target
                try JSONSerialization.data(withJSONObject: json).write(to: file)
            }
        }
        return out
    }

    @Test func theLatestResultOfEveryMethod() async throws {
        let out = try Self.results()
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(out.path)]))
        await model.gallery.refresh()
        #expect(model.compareOverview(nil).allSatisfy { $0.state == .none && $0.item == nil })
        model.studio.image = URL(filePath: "/Users/studio/Pictures/Kamel.png")
        let entries = model.compareOverview(model.studio.image)
        #expect(entries.map(\.method) == model.schema.methods)
        let byMethod = Dictionary(uniqueKeysWithValues: entries.map { ($0.method, $0) })
        #expect(byMethod["clipasso"]?.item?.jobDir.lastPathComponent == "neu" && byMethod["clipasso"]?.state == .done)
        #expect(byMethod["swiftsketch"]?.score == 0.8 && byMethod["swiftsketch"]?.best == true)
        #expect(byMethod["clipasso"]?.best == false && byMethod["controlsketch"]?.state == CompareModel.Entry.State.none)
        model.studio.image = URL(filePath: "/Users/studio/Pictures/Giraffe.png")  // (one score: no best)
        #expect(model.compareOverview(model.studio.image).allSatisfy { !$0.best })
    }

    @Test func theSettings() throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let m = try #require(model.schema.method("clipasso"))
        model.studio.set("num_sketches", to: 2)
        let standard = model.compareSettings("clipasso", useStudio: false)
        var expected = m.applyPreset("standard", to: m.start)
        if let device = model.studio.settings["device"] { expected["device"] = device }
        expected["method"] = "clipasso"
        #expect(standard == expected)
        #expect(model.compareSettings("clipasso", useStudio: true) == model.studio.jobSettings)
        #expect(CompareModel(methods: model.schema.methods).chosen == ["clipasso", "swiftsketch", "controlsketch"])
    }

    /// The fake engine knows no GPU: ControlSketch and SceneSketch are asked about; "no" leaves ControlSketch out,
    /// "yes" gives SceneSketch the preset "fast". The jobs run the fastest first.
    @Test func aCompareQueuesTheMethods() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de"))
        let compare = CompareModel(methods: model.schema.methods)
        #expect(await model.startCompare(compare) == 0)  // (no engine, no picture)
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        compare.chosen.insert("scenesketch")
        #expect(await model.compareQuestions(compare.chosen, useStudio: false) == ["controlsketch_cpu", "scene_fast"])
        #expect(await model.compareQuestions(["clipasso"], useStudio: false).isEmpty)
        #expect(await model.compareQuestions(compare.chosen, useStudio: true) == ["controlsketch_cpu"])
        let n = await model.startCompare(compare, answers: ["controlsketch_cpu": false, "scene_fast": true])
        let jobs = model.queueSnapshot?.jobs ?? []
        #expect(n == 3 && jobs.map { $0.settings["method"]?.stringValue } == ["swiftsketch", "clipasso", "scenesketch"])
        let scene = try #require(model.schema.method("scenesketch"))
        let fast = scene.applyPreset("fast", to: model.compareSettings("scenesketch", useStudio: false))
        #expect(jobs.last?.settings == fast)
        let overview = model.compareOverview(model.studio.image)
        #expect(overview.first { $0.method == "clipasso" }?.state == .queued)
        #expect(overview.first { $0.method == "controlsketch" }?.state == CompareModel.Entry.State.none)
        await model.stopEngine()
    }

    /// get_compare and do_compare (phone_api): the columns with the keys the phone page reads; the questions come
    /// back to be answered there – "no" to ControlSketch without a GPU leaves it out, and with nothing left to
    /// compare it says so.
    @Test func onThePhone() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de"))
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        func ask(_ action: String, _ data: JSONObject = [:]) async -> JSONObject? {
            PhoneRemoteTests.json(await model.phoneAnswer(action, data, payload: nil))
        }
        let t = model.texts
        #expect(await ask("do_compare", ["methods": ["clipasso"]])?["error"] == .string(t.tr("ui.phone.page.no_picture")))
        model.studio.image = SelfTestTests.fixtures.appending(path: "crop/input.png")
        let asked = await ask("do_compare", ["methods": ["clipasso", "controlsketch"]])
        #expect(asked?["ok"] == false && asked?["asks"]?.arrayValue?.count == 1)
        #expect(asked?["asks"]?.arrayValue?.first?.objectValue?["key"] == "controlsketch_cpu")
        #expect(await ask("do_compare", ["methods": ["clipasso", "controlsketch"], "controlsketch_cpu": false])
            == ["ok": true, "queued": 1])
        #expect(await ask("do_compare", ["methods": ["controlsketch"], "controlsketch_cpu": false])?["error"]
            == .string(t.tr("ui.phone.page.compare_none")))
        let shown = try #require(await ask("get_compare"))
        #expect(shown["ok"] == true && shown["image"] == "input.png")
        let rows = (shown["methods"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(rows.map { $0["key"]?.stringValue } == model.schema.methods.map { Optional($0) })
        #expect(Set(rows.first?.keys ?? []) == ["key", "name", "default", "best", "time", "state", "progress", "dir",
                                                "score", "seconds", "strokes", "created"])
        let clipasso = try #require(rows.first { $0["key"] == "clipasso" })
        #expect(clipasso["state"] == "queued" && clipasso["default"] == true && clipasso["score"] == .null)
        #expect(rows.first { $0["key"] == "scenesketch" }?["default"] == false)
        await model.stopEngine()
    }
}
