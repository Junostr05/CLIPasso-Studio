import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The object mask of the studio's image: asked for when the run uses one (the mask model's parameter is active),
/// computed by the engine in the background – its "mask_ready" reaches the studio as the queue's notice – and shown
/// as the model's probability over the threshold; no mask when the run uses none.
@Suite(.serialized) struct StudioMaskTests {
    static let probability = SelfTestTests.fixtures.appending(path: "mask/probability.png")

    @Test func theMaskOfTheStudiosImage() async throws {
        let engine = SelfTestTests.fake(["mask", Self.probability.path])
        let model = try AppModel(resources: AppModelTests.resources(engine: engine), store: AppModelTests.store(language: "de"))
        await model.startEngine()
        let image = SelfTestTests.fixtures.appending(path: "mask/small.png")  // (any picture: the engine is a stand-in)
        model.studio.image = image
        model.studio.selectMethod("swiftsketch")
        model.studio.set("mask_object", to: false)
        await model.updateMask()
        #expect(model.mask.state == .off)  // (the run uses no mask)
        model.studio.set("mask_object", to: true)
        #expect(model.studio.isEnabled("mask_model"))
        await model.updateMask()
        try await ModelFlowTests.wait("the mask") { model.mask.state != .busy }
        #expect(model.mask.state == .ready && model.mask.width == 32 && model.mask.height == 24)
        #expect(model.mask.object.filter { $0 }.count == 384)  // (the probability ≥ ½, as masking counts it)
        #expect(model.mask.probability?.count == 32 * 24)
        #expect(model.mask.status(model.texts, name: model.modelName(model.mask.model)).hasPrefix("Maske: "))
        await model.stopEngine()
    }
}
