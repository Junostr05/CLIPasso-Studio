import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// A SceneSketch cell computed again: asked first for the later levels, the cell removed by the engine, the job
/// queued to continue in its folder, the result read again – and not twice while it waits.
@Suite(.serialized) struct SceneCellRerunTests {
    @Test func aCellAgain() async throws {
        let jobs = FileManager.default.temporaryDirectory.appending(path: "rerun-\(UUID().uuidString)")
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs"), to: jobs)
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["echo"])),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(jobs.path)]))
        await model.startEngine()
        await model.queuePage?.setAutoStart(false)
        await model.gallery.refresh()
        let item = try #require(model.gallery.items.first { $0.jobDir.lastPathComponent == "scenesketch_matrix" })
        model.studio.open(item)
        let result = try #require(model.studio.result)
        #expect(result.run(cell: 804) != nil && result.run(cell: 800) != nil)
        #expect(await model.sceneCellLater(804) == [])
        #expect(await model.sceneCellLater(899) == nil)  // (no such cell)

        #expect(await model.rerunSceneCell(804) == 1)
        let queued = try #require(model.queueSnapshot?.jobs.first)
        #expect(queued.resumeDir?.lastPathComponent == "scenesketch_matrix" && queued.status == .queued)
        #expect(model.studio.result?.run(cell: 804) == nil && model.studio.result?.run(cell: 800) != nil)
        #expect(await model.rerunSceneCell(800) == nil)  // (the job waits in the queue already)
        // the phone
        #expect(PhoneRemoteTests.json(await model.phoneAnswer("do_rerun_cell", ["cell": 800], payload: nil))?["ok"]
            == false)
        await model.stopEngine()
    }
}
