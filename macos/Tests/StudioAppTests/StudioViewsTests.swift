import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The canvas's views besides the sketch: sent by the engine while a job runs (input, attention), found in a
/// finished job's folder (input.png, attention_map.png, mask.png, *_condition.png; SceneSketch: background.png and
/// the background run's attention), by method; and on the phone.
@Suite(.serialized) struct StudioViewsTests {
    @Test func fromTheEnginesEvents() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let out = FileManager.default.temporaryDirectory.appending(path: "views-\(UUID().uuidString)")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(out.path)]))
        await model.startEngine()
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()
        try await ModelFlowTests.wait("the job") { model.studio.live.status == .done }
        let job = try #require(model.queueSnapshot?.jobs.first)
        #expect(job.views["compare"]?.starts(with: [0x89, 0x50]) == true && job.views["mask"] != nil)
        #expect(job.attention[1000] != nil)
        #expect(model.studio.live.views.keys.sorted() == ["compare", "mask"] && model.studio.live.attention != nil)
        await model.stopEngine()
    }

    @Test func fromAFinishedJobsFolder() async throws {
        let jobs = FileManager.default.temporaryDirectory.appending(path: "views-\(UUID().uuidString)")
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs"), to: jobs)
        let job = jobs.appending(path: "done_clipasso")
        let summary = try #require(JobFolder.summary(at: job))
        let runs = summary.runs.compactMap { $0["run_dir"]?.stringValue }.map { URL(filePath: $0) }
        let png = try Data(contentsOf: SelfTestTests.fixtures.appending(path: "crop/input.png"))
        let best = try #require(runs.first { $0.lastPathComponent == summary.bestRun } ?? runs.first)
        try png.write(to: best.appending(path: "input.png"))
        try png.write(to: best.appending(path: "attention_map.png"))
        try png.write(to: job.appending(path: "mask.png"))
        try png.write(to: runs.last!.appending(path: "seed_condition.png"))
        let files = JobViews.files(jobDir: job, summary: summary, run: best)
        #expect(files["compare"]?.lastPathComponent == "input.png" && files["attention"] != nil)
        #expect(files["mask"]?.path == job.appending(path: "mask.png").path)
        #expect(files["condition"]?.lastPathComponent == "seed_condition.png")
        #expect(JobViews.kinds(for: "swiftsketch") == ["compare", "mask"])
        #expect(JobViews.kinds(for: "scenesketch") == JobViews.kinds)
        #expect(JobViews.kinds(for: "clipasso") == ["compare", "attention", "mask"])

        // in the studio and on the phone
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(jobs.path)]))
        await model.gallery.refresh()
        model.studio.open(try #require(model.gallery.items.first { $0.jobDir.lastPathComponent == "done_clipasso" }))
        #expect(model.studioViews == ["compare", "attention", "mask"])  // (no condition for CLIPasso)
        let state = try #require(PhoneRemoteTests.json(await model.phoneAnswer("get_studio", [:], payload: nil)))
        #expect(state["views"]?.objectValue?.count == 3)
        guard case .bytes(let view, let type, _) = await model.phoneAnswer("file_view", ["kind": "mask"], payload: nil)
        else { Issue.record("no view"); return }
        #expect(type == "image/png" && view.starts(with: [0x89, 0x50]))
        #expect(PhoneRemoteTests.json(await model.phoneAnswer("file_view", ["kind": "condition"], payload: nil))?["ok"]
            == false)
    }
}
