import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// Touching up the mask (mask_edit.MaskEditDialog): a click takes a part away or brings in a candidate part, the
/// brush paints, 30 steps back and forth, back to the model's mask – and "Use this mask" has the engine keep the
/// user's mask, or remove it when it is the model's again; the studio then shows what the engine keeps.
@Suite(.serialized) struct MaskEditorTests {
    /// 6 × 2: a part of two pixels top left, one bottom right; (3, 0) a candidate (the model less sure).
    static func editor() -> MaskEditorModel {
        let on: Set = [0, 1, 10, 11]
        let probability: [Float] = (0 ..< 12).map { on.contains($0) ? 0.9 : $0 == 3 ? 0.2 : 0 }
        let mask = MaskPlane(width: 6, height: 2, values: (0 ..< 12).map { on.contains($0) })
        return MaskEditorModel(mask: mask, probability: probability, threshold: 0.5)
    }

    static func on(_ editor: MaskEditorModel) -> [Int] {
        editor.mask.values.indices.filter { editor.mask.values[$0] }
    }

    @Test func clicksTheBrushAndStepsBack() {
        let editor = Self.editor()
        #expect(editor.isAuto && !editor.canUndo && editor.share == 4.0 / 12)
        #expect(editor.click(x: 0.5, y: 0.5))  // (the part under the click goes)
        #expect(Self.on(editor) == [10, 11] && !editor.isAuto && editor.canUndo)
        #expect(editor.click(x: 3.5, y: 0.2))  // (the candidate comes in – only it, not what was grown around it)
        #expect(Self.on(editor) == [3, 10, 11])
        #expect(!editor.click(x: 2.5, y: 1.5) && editor.missed)  // (neither mask nor candidate, no photo: no wand)
        #expect(!editor.click(x: -1, y: 0))
        editor.undo()
        #expect(Self.on(editor) == [10, 11] && editor.canRedo && !editor.missed)
        editor.redo()
        #expect(Self.on(editor) == [3, 10, 11] && !editor.canRedo)
        editor.tool = .erase
        editor.beginStroke(x: 4, y: 1, radius: 0.5)
        #expect(Self.on(editor) == [3, 11])
        editor.continueStroke(from: (4, 1), to: (5, 1), radius: 0.5)
        #expect(Self.on(editor) == [3])
        editor.undo()  // (the whole stroke)
        #expect(Self.on(editor) == [3, 10, 11])
        editor.reset()
        #expect(editor.isAuto && Self.on(editor) == [0, 1, 10, 11])
        editor.undo()
        #expect(Self.on(editor) == [3, 10, 11])
    }

    @Test func thirtyStepsBack() {
        let editor = Self.editor()
        editor.tool = .add
        for i in 0 ..< 35 { editor.beginStroke(x: Double(i % 6), y: Double(i / 6 % 2), radius: 0.4) }
        var back = 0
        while editor.canUndo {
            editor.undo()
            back += 1
        }
        #expect(back == MaskEditing.undoSteps)
    }

    @Test func packedEightToAByte() {
        let mask = MaskPlane(width: 13, height: 1, values: (0 ..< 13).map { $0 % 3 == 0 || $0 == 12 })
        let packed = MaskEditorModel.pack(mask)
        #expect(packed.count == 2 && packed[0] == 0b1001_0010)
        #expect(MaskEditorModel.unpack(packed, width: 13, height: 1) == mask)
    }

    #if canImport(ImageIO)
    @Test func keptByTheEngineAndRemovedAgain() async throws {
        let engine = SelfTestTests.fake(["mask", StudioMaskTests.probability.path])
        let model = try AppModel(resources: AppModelTests.resources(engine: engine), store: AppModelTests.store(language: "de"))
        await model.startEngine()
        model.studio.image = SelfTestTests.fixtures.appending(path: "mask/small.png")
        model.studio.selectMethod("swiftsketch")
        model.studio.set("mask_object", to: true)
        await model.updateMask()
        for _ in 0 ..< 200 where model.mask.state != .ready { try await Task.sleep(for: .milliseconds(20)) }
        #expect(model.mask.state == .ready)

        let editor = try #require(model.maskEditor())
        #expect(editor.isAuto && editor.image == model.studio.image)
        let first = try #require(editor.mask.values.firstIndex(of: true))
        editor.tool = .erase
        editor.beginStroke(x: Double(first % editor.width) + 0.5, y: Double(first / editor.width) + 0.5, radius: 2)
        let mine = editor.mask.values
        #expect(mine.filter { $0 }.count < 384)
        try await model.applyMask(editor)
        for _ in 0 ..< 200 where model.mask.state != .edited { try await Task.sleep(for: .milliseconds(20)) }
        #expect(model.mask.state == .edited && model.mask.object == mine)  // (the user's mask, as painted)

        for _ in 0 ..< 200 where model.mask.probability == nil { try await Task.sleep(for: .milliseconds(20)) }
        let again = try #require(model.maskEditor())
        #expect(!again.isAuto && again.mask.values == mine)
        again.reset()
        try await model.applyMask(again)  // (the model's mask again: the user's is removed)
        for _ in 0 ..< 200 where model.mask.state != .ready { try await Task.sleep(for: .milliseconds(20)) }
        #expect(model.mask.state == .ready && model.mask.object.filter { $0 }.count == 384)
        await model.stopEngine()
    }
    #endif
}
