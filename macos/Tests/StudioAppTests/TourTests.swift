import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The first-start guide (tour.py): its steps and pages, through it and back, shown once – done or skipped, it
/// waits for the Help menu; the Mac's own texts where keys or places differ.
@Suite struct TourTests {
    @Test func throughTheGuide() throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        let tour = model.tour, t = model.texts
        #expect(TourModel.steps.map(\.key) == ["methods", "input", "params", "start", "result", "gallery", "models"])
        #expect(tour.step == nil)
        model.maybeShowTour()
        #expect(tour.index == 0 && tour.position(t) == t.tr("ui.tour.step", ["n": "1", "total": "7"]))
        #expect(tour.title(t) == t.tr("ui.tour.methods.title") && tour.text(t) == t.tr("ui.tour.methods.text"))
        tour.back()
        #expect(tour.index == 0)
        tour.next()
        #expect(tour.step?.key == "input" && tour.text(t) == t.tr("ui.mac.tour.input.text"))
        while !tour.isLast { tour.next() }
        #expect(tour.step == TourModel.Step(key: "models", page: "models"))
        #expect(tour.next() && tour.step == nil)  // (after the last: done)
        model.tourFinished()
        #expect(model.settings["tour_done"] == true)
        model.maybeShowTour()
        #expect(tour.step == nil)  // (once)
        tour.start()  // (Help ▸ Show the guide)
        #expect(tour.index == 0)
        tour.close()
        #expect(tour.step == nil)
    }

    /// Every step has its texts in both languages; the Mac's own name keys the window has (⌘, not Ctrl).
    @Test(arguments: ["de", "en"]) func theTexts(language: String) throws {
        let t = try Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"), language: language)
        let tour = TourModel()
        tour.start()
        repeat {
            let key = try #require(tour.step?.key)
            #expect(t.has("ui.tour.\(key).title") && t.has("ui.tour.\(key).text"))
            #expect(!tour.text(t).contains("Ctrl") && !tour.text(t).contains("Strg"))
        } while !tour.next()
    }
}
