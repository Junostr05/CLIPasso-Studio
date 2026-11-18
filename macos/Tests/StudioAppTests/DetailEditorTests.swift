import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The detail brush (detail_edit.DetailEditDialog): the soft brush of each tool, steps back and forth, all normal
/// again, portrait mode's faces laid over what is painted – and the engine keeping the map with the image; without
/// the face detector its download is asked for.
@Suite(.serialized) struct DetailEditorTests {
    static let image = URL(filePath: "/nowhere/a.png")

    @Test func paintingAndStepsBack() {
        let editor = DetailEditorModel(image: Self.image, map: DetailMap(width: 40, height: 30))
        #expect(editor.brush == 8 && editor.brushes == 6 ... 200)  // (6 % of 40 is less than 8)
        #expect(editor.share.more == 0 && editor.share.less == 0 && !editor.canUndo)
        editor.beginStroke(x: 10, y: 10)
        editor.continueStroke(from: (10, 10), to: (30, 10))
        let painted = editor.map
        #expect(editor.share.more > 0 && editor.share.less == 0 && editor.canUndo)
        editor.tool = .less
        editor.beginStroke(x: 20, y: 25)
        #expect(editor.share.less > 0)
        editor.undo()  // (the whole stroke)
        #expect(editor.map == painted && editor.canRedo)
        editor.redo()
        #expect(editor.share.less > 0 && !editor.canRedo)
        editor.clear()
        #expect(editor.map == DetailMap(width: 40, height: 30))
        editor.undo()
        #expect(editor.share.less > 0)
        editor.faces(nil)
        #expect(editor.noFace)
        var faces = DetailMap(width: 40, height: 30)
        faces.values[0] = 255
        editor.faces(faces)
        #expect(!editor.noFace && editor.map.values[0] == 255 && editor.share.less > 0)  // (over the painted map)
    }

    @Test func theBrushsSizeAndThirtySteps() {
        let editor = DetailEditorModel(image: Self.image, map: DetailMap(width: 1024, height: 700))
        #expect(editor.brush == 61 && editor.brushes == 6 ... 200)
        editor.step(1)
        #expect(editor.brush == 77)
        editor.step(-1)
        #expect(editor.brush == 60)
        for _ in 0 ..< 20 { editor.step(-1) }
        #expect(editor.brush == 6)
        for _ in 0 ..< 35 { editor.beginStroke(x: 500, y: 300) }
        var back = 0
        while editor.canUndo {
            editor.undo()
            back += 1
        }
        #expect(back == DetailEditing.undoSteps)
    }

    #if canImport(ImageIO)
    @Test func keptByTheEngineWithTheFacesFound() async throws {
        let engine = SelfTestTests.fake(["mask", StudioMaskTests.probability.path])
        let model = try AppModel(resources: AppModelTests.resources(engine: engine), store: AppModelTests.store(language: "de"))
        await model.startEngine()
        model.studio.image = SelfTestTests.fixtures.appending(path: "mask/small.png")
        #expect(await !model.hasDetails())
        let editor = try #require(try await model.detailEditor())
        #expect(editor.width == 32 && editor.height == 24 && editor.map == DetailMap(width: 32, height: 24))

        #expect(await model.findFaces(editor) == .missingModel)  // (the stand-in's first answer)
        #expect(model.models.stage == .asking(["blazeface"]))
        model.cancelDownload()
        let found = await model.findFaces(editor)
        guard case .found(let faces) = found else {
            Issue.record("no faces: \(found)")
            return
        }
        #expect(faces.values[0] == 200 && faces.values[31] == 128 && editor.map == faces && !editor.finding)

        try await model.applyDetails(editor)
        #expect(await model.hasDetails())
        let again = try #require(try await model.detailEditor())
        #expect(again.map == faces)  // (the map as it was kept)
        await model.stopEngine()
    }
    #endif
}
