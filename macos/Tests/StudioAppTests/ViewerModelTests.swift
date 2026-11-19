import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The large view (gallery_viewer): going through the results with a sketch, the slideshow going on by itself and
/// wrapping round, one result only no slideshow, the line under the name.
@Suite(.serialized) struct ViewerModelTests {
    @Test func throughTheResults() async throws {
        let jobs = FileManager.default.temporaryDirectory.appending(path: "viewer-\(UUID().uuidString)")
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs"), to: jobs)
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de", ["output_dir": .string(jobs.path)]))
        await model.gallery.refresh()
        let all = model.gallery.items
        let viewer = ViewerModel(items: all, index: 0)
        let n = viewer.items.count
        #expect(n >= 2 && viewer.items.allSatisfy { $0.bestSketch != nil })
        #expect(viewer.position == "\(viewer.index + 1) / \(n)" && viewer.svg?.contains("<svg") == true)

        viewer.show(0)
        viewer.previous()
        #expect(viewer.index == 0)  // (no wrapping by hand)
        viewer.show(n - 1)
        viewer.next()
        #expect(viewer.index == n - 1)
        viewer.next(wrap: true)
        #expect(viewer.index == 0 && viewer.position == "1 / \(n)")

        viewer.sleep = { _ in try await Task.sleep(for: .milliseconds(20)) }
        viewer.show(n - 1)
        viewer.setSlideshow(true)
        #expect(viewer.playing)
        try await ModelFlowTests.wait("the slideshow") { viewer.index == 0 }  // (round again after the last)
        viewer.previous()
        #expect(viewer.index == n - 1)  // (in a slideshow: back to the last)
        viewer.setSlideshow(false)
        let stopped = viewer.index
        try await Task.sleep(for: .milliseconds(100))
        #expect(!viewer.playing && viewer.index == stopped)

        let one = ViewerModel(items: [viewer.items[0]])
        one.setSlideshow(true)
        #expect(!one.playing)  // (one result: no slideshow)
        let line = ViewerModel.describe(viewer.items[0], texts: model.texts)
        #expect(line.hasPrefix(viewer.items[0].methodName))
        #expect(ViewerModel(items: []).position.isEmpty)
    }
}
