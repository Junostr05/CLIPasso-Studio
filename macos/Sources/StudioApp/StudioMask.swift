import Foundation
import Observation
import StudioCore

/// The object mask of the studio's image (studio.py: _update_mask_preview, _mask_ready, _set_mask_status): shown over
/// the image whenever the run will use one – the user's edited mask, else the model's, which the engine computes in
/// the background – with what it is doing now.
@Observable
public final class StudioMask {
    public enum State: Equatable, Sendable {
        /// the run uses no mask, or there is no image
        case off
        /// the engine looks for the object
        case busy
        /// the model's mask
        case ready
        /// the user's mask
        case edited
        /// no mask to show (why: for the tooltip)
        case failed(String)
    }

    public private(set) var state = State.off
    /// counts the masks shown (the view draws its overlay anew for each)
    public private(set) var version = 0
    /// the mask model ("birefnet" …)
    public private(set) var model = ""
    /// the object, row after row, at the image's size (empty without a mask)
    public private(set) var object: [Bool] = []
    public private(set) var width = 0
    public private(set) var height = 0
    /// the model's probability (the mask editor's candidates); nil without one
    @ObservationIgnored public private(set) var probability: [Float]?
    /// the probability from which a pixel is the object (masking.OBJECT_THRESHOLD, as the engine says)
    @ObservationIgnored public private(set) var threshold: Float = 0.5
    /// the image and model the mask was asked for
    @ObservationIgnored public private(set) var asked: (image: URL, model: String)?

    public init() {}

    func clear() {
        empty(.off)
        model = ""
        asked = nil
    }

    func begin(image: URL, model: String) {
        empty(.busy)
        self.model = model
        asked = (image, model)
    }

    func fail(_ why: String) {
        empty(.failed(why))
    }

    private func empty(_ next: State) {
        version += 1
        state = next
        object = []
        width = 0
        height = 0
        probability = nil
    }

    func show(object: [Bool], width: Int, height: Int, probability: [Float]?, threshold: Float, edited: Bool) {
        self.threshold = threshold
        self.object = object
        self.width = width
        self.height = height
        self.probability = probability
        state = edited ? .edited : .ready
        version += 1
    }

    /// The status line (ui.mask.*), the model by its name.
    public func status(_ texts: Texts, name: String) -> String {
        switch state {
        case .off: ""
        case .busy: texts.tr("ui.mask.busy")
        case .ready: texts.tr("ui.mask.ready", ["model": name])
        case .edited: texts.tr("ui.mask.edited")
        case .failed: texts.tr("ui.mask.failed")
        }
    }
}

public extension AppModel {
    /// The mask model's name as the Models page shows it.
    func modelName(_ key: String) -> String {
        catalog.models.first { $0.key == key }?.name ?? key
    }

    /// Ask for the mask of the studio's image when the run will use one – the mask model's parameter is active
    /// exactly then (settings_schema.uses_mask) – on a new image, method or setting; the same image and model are
    /// not asked for again.
    func updateMask() async {
        let model = studio.settings["mask_model"]?.stringValue ?? "u2net"
        guard studio.isEnabled("mask_model"), let image = studio.image,
              FileManager.default.fileExists(atPath: image.path)
        else { return mask.clear() }
        if let asked = mask.asked, asked.image == image, asked.model == model, mask.state != .off { return }
        mask.begin(image: image, model: model)
        guard let engine, let queue else { return mask.fail("the engine is not running") }
        await queue.begin()  // (its notices bring "mask_ready")
        let device = studio.settings["device"]?.stringValue ?? "auto"
        do {
            let answer = try await engine.request("mask", ["image": .string(image.path), "model": .string(model),
                                                           "compute": true, "device": .string(device)])
            await showMask(answer, image: image, model: model)
        } catch {
            if mask.asked?.image == image, mask.asked?.model == model { mask.fail(String(describing: error)) }
        }
    }

    /// Back to the model's mask (the studio's reset button): the user's goes.
    func resetMask() async {
        guard let asked = mask.asked, let engine else { return }
        _ = try? await engine.request("remove_mask", ["image": .string(asked.image.path)])
        await reloadMask()
    }

    /// Whether the mask is shown over the image (show_mask, the studio's key).
    var showsMask: Bool { settings["show_mask"]?.truthy ?? true }

    func setShowsMask(_ on: Bool) {
        _ = updateSettings { $0["show_mask"] = .bool(on) }
    }

    /// The edited mask after the user kept or removed one: asked for anew.
    func reloadMask() async {
        mask.clear()
        await updateMask()
    }

    /// An event of no job (the queue's notices): the mask asked for is ready – read it – or could not be made.
    func maskNotice(_ event: EngineEvent) async {
        guard let asked = mask.asked, event.data["image"]?.stringValue == asked.image.path,
              event.data["model"]?.stringValue == asked.model
        else { return }
        if event.kind == "mask_failed" {
            return mask.fail(event.data["message"]?.stringValue ?? "")
        }
        guard event.kind == "mask_ready", let engine else { return }
        do {
            let answer = try await engine.request("mask", ["image": .string(asked.image.path),
                                                           "model": .string(asked.model)])
            await showMask(answer, image: asked.image, model: asked.model)
        } catch {
            mask.fail(String(describing: error))
        }
    }

    /// What the engine knows of the mask: the user's mask over the model's; still computing: busy.
    private func showMask(_ answer: JSONValue, image: URL, model: String) async {
        guard mask.asked?.image == image, mask.asked?.model == model, let o = answer.objectValue else { return }
        let edited = o["edited"]?.stringValue.map { URL(filePath: $0) }
        let probability = o["probability"]?.stringValue.map { URL(filePath: $0) }
        let threshold = Float(o["threshold"]?.doubleValue ?? 0.5)
        guard edited != nil || probability != nil else {
            if o["computing"]?.truthy != true { mask.fail("no mask") }
            return
        }
        #if canImport(ImageIO)
            let read = await Task.detached(executorPreference: OwnThreads.shared) { () -> MaskRead? in
                MaskRead(edited: edited, probability: probability, threshold: threshold)
            }.value
            guard mask.asked?.image == image, mask.asked?.model == model else { return }
            guard let read else { return mask.fail("the mask could not be read") }
            mask.show(object: read.object, width: read.width, height: read.height, probability: read.probability,
                      threshold: threshold, edited: edited != nil)
        #else
            mask.fail("no ImageIO")
        #endif
    }
}

#if canImport(ImageIO)
    /// The mask files read (off the main actor): the user's mask if there is one (≥ ½ the object), else the model's
    /// probability over the threshold.
    nonisolated struct MaskRead: Sendable {
        let object: [Bool]
        let width: Int
        let height: Int
        let probability: [Float]?

        init?(edited: URL?, probability url: URL?, threshold: Float) {
            let prob = url.flatMap { try? MaskFile.read($0) }
            let shown: (values: [Bool], width: Int, height: Int)
            if let edited, let mine = try? MaskFile.read(edited) {
                shown = (mine.values.map { $0 >= 0.5 }, mine.width, mine.height)
            } else if let prob {
                shown = (prob.values.map { $0 >= threshold }, prob.width, prob.height)
            } else {
                return nil
            }
            object = shown.values
            width = shown.width
            height = shown.height
            probability = prob.flatMap { $0.width == shown.width && $0.height == shown.height ? $0.values : nil }
        }
    }
#endif
