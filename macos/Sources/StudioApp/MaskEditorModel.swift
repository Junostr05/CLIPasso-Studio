import Foundation
import Observation
import StudioCore

/// The mask editor (mask_edit.MaskEditDialog with its MaskCanvas): the image with the background veiled; a click
/// takes a part away or brings one in (Teile wählen), the brush adds or removes (Hinzufügen, Entfernen); 30 steps
/// back and forth; back to the model's mask. "Use this mask" keeps it – or, when it is the model's again, removes
/// the user's.
@Observable
public final class MaskEditorModel: Identifiable {
    public enum Tool: String, CaseIterable, Sendable {
        case part, add, erase
    }

    public let width: Int
    public let height: Int
    /// the image the mask is of (nil: none – then nothing can be kept)
    public let image: URL?
    public private(set) var mask: MaskPlane
    /// counts the changes (the view draws its veil anew for each)
    public private(set) var version = 0
    public var tool = Tool.part
    /// the brush's diameter in points of the screen (the studio starts at 40)
    public var brush = 40.0
    /// the last click found nothing to take or add
    public private(set) var missed = false
    /// the model's mask (probability over the threshold)
    let auto: MaskPlane
    /// what a click outside the mask may bring in: the model's less sure parts (≥ CANDIDATE) and the mask itself
    let candidate: MaskPlane
    /// the image (at most 1600 pixels, as the studio shows it) – the picture under the mask and the magic wand's;
    /// nil until it is read, or when it cannot be
    public var photo: MaskPhoto?
    @ObservationIgnored private var undoStack: [Data] = []
    @ObservationIgnored private var redoStack: [Data] = []
    public private(set) var canUndo = false
    public private(set) var canRedo = false

    /// The editor of `mask` (the user's or the model's), `probability` the model's (nil: none – then the model's
    /// mask is the one given and nothing is a candidate).
    public init(mask: MaskPlane, probability: [Float]?, threshold: Float, image: URL? = nil) {
        width = mask.width
        height = mask.height
        self.image = image
        self.mask = mask
        if let probability, probability.count == mask.values.count {
            auto = MaskPlane(width: width, height: height, values: probability.map { $0 >= threshold })
            candidate = MaskPlane(width: width, height: height,
                                  values: zip(probability, mask.values).map { $0 >= MaskEditing.candidate || $1 })
        } else {
            auto = mask
            candidate = mask
        }
    }

    /// The share of the image the object covers (0 … 1).
    public var share: Double {
        mask.values.isEmpty ? 0 : Double(mask.values.lazy.filter { $0 }.count) / Double(mask.values.count)
    }

    /// The mask is the model's again.
    public var isAuto: Bool { mask == auto }

    /// Teile wählen: a click at image position (x, y); false when it found nothing to change.
    @discardableResult
    public func click(x: Double, y: Double) -> Bool {
        guard let made = MaskEditing.partClick(mask, candidate: candidate, photo: photo, x: x, y: y) else {
            missed = true
            return false
        }
        set(made)
        return true
    }

    /// The brush pressed at (x, y): one dab (`radius` in image pixels) – a step back undoes the whole stroke.
    public func beginStroke(x: Double, y: Double, radius: Double) {
        snapshot()
        MaskEditing.dab(&mask, x: x, y: y, r: radius, value: tool == .add)
        changed()
    }

    /// The brush moved on from `a` to `b` while pressed.
    public func continueStroke(from a: (x: Double, y: Double), to b: (x: Double, y: Double), radius: Double) {
        MaskEditing.line(&mask, from: a, to: b, r: radius, value: tool == .add)
        changed()
    }

    public func undo() {
        guard let last = undoStack.popLast() else { return }
        redoStack.append(Self.pack(mask))
        mask = Self.unpack(last, width: width, height: height)
        changed()
    }

    public func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(Self.pack(mask))
        mask = Self.unpack(next, width: width, height: height)
        changed()
    }

    /// Automatische Maske: back to the model's (a step back returns).
    public func reset() {
        set(auto)
    }

    private func set(_ next: MaskPlane) {
        snapshot()
        mask = next
        changed()
    }

    private func snapshot() {
        undoStack.append(Self.pack(mask))
        if undoStack.count > MaskEditing.undoSteps { undoStack.removeFirst(undoStack.count - MaskEditing.undoSteps) }
        redoStack.removeAll()
    }

    private func changed() {
        missed = false
        version += 1
        (canUndo, canRedo) = (!undoStack.isEmpty, !redoStack.isEmpty)
    }

    /// np.packbits: eight pixels a byte (a step back of a 24-megapixel mask: 3 MB).
    static func pack(_ mask: MaskPlane) -> Data {
        var out = Data(count: (mask.values.count + 7) / 8)
        for (i, on) in mask.values.enumerated() where on { out[i / 8] |= 0x80 >> UInt8(i % 8) }
        return out
    }

    static func unpack(_ data: Data, width: Int, height: Int) -> MaskPlane {
        let values = (0 ..< width * height).map { data[$0 / 8] & (0x80 >> UInt8($0 % 8)) != 0 }
        return MaskPlane(width: width, height: height, values: values)
    }
}

#if canImport(ImageIO)
    import CoreGraphics
    import ImageIO
    import UniformTypeIdentifiers

    public extension AppModel {
        /// The editor of the studio's mask (nil without one – or without the model's probability, as the studio).
        func maskEditor() -> MaskEditorModel? {
            guard mask.state == .ready || mask.state == .edited, !mask.object.isEmpty,
                  let probability = mask.probability
            else { return nil }
            let plane = MaskPlane(width: mask.width, height: mask.height, values: mask.object)
            return MaskEditorModel(mask: plane, probability: probability, threshold: mask.threshold,
                                   image: mask.asked?.image)
        }

        /// The studio's photo of the editor: the image upright (as the engine reads it), at most `side` pixels.
        nonisolated static func editorPhoto(_ url: URL, side: Int = 1600) -> MaskPhoto? {
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let pixelWidth = properties[kCGImagePropertyPixelWidth] as? Int,
                  let pixelHeight = properties[kCGImagePropertyPixelHeight] as? Int,
                  let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                      kCGImageSourceCreateThumbnailFromImageAlways: true,
                      kCGImageSourceCreateThumbnailWithTransform: true,
                      kCGImageSourceThumbnailMaxPixelSize: min(side, max(pixelWidth, pixelHeight)),  // (never larger)
                  ] as CFDictionary),
                  let space = CGColorSpace(name: CGColorSpace.sRGB)
            else { return nil }
            let (width, height) = (image.width, image.height)
            var rgba = [UInt8](repeating: 0, count: width * height * 4)
            let drawn: Bool = rgba.withUnsafeMutableBytes { raw in
                guard let context = CGContext(data: raw.baseAddress, width: width, height: height, bitsPerComponent: 8,
                                              bytesPerRow: width * 4, space: space,
                                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
                else { return false }
                context.interpolationQuality = .high
                context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
                return true
            }
            guard drawn else { return nil }
            var rgb = [UInt8](repeating: 0, count: width * height * 3)
            for i in 0 ..< width * height {
                (rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]) = (rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2])
            }
            return MaskPhoto(width: width, height: height, rgb: rgb)
        }

        /// Diese Maske verwenden: the engine keeps the user's mask (by the image's content) – or removes it when the
        /// mask is the model's again; then the studio shows it.
        func applyMask(_ editor: MaskEditorModel) async throws {
            guard let image = editor.image else { return }
            guard let engine else { throw EngineFailure(code: "engine_gone", message: "the engine is not running") }
            if editor.isAuto {
                _ = try await engine.request("remove_mask", ["image": .string(image.path)])
            } else {
                let file = FileManager.default.temporaryDirectory.appending(path: "mask-\(UUID().uuidString).png")
                defer { try? FileManager.default.removeItem(at: file) }
                let plane = editor.mask
                try await Task.detached(executorPreference: OwnThreads.shared) {
                    try AppModel.writeMask(plane, to: file)
                }.value
                _ = try await engine.request("save_mask", ["image": .string(image.path), "mask": .string(file.path)])
            }
            await reloadMask()
        }

        /// The mask as an 8-bit grey PNG (white the object), as the engine reads a painted one.
        nonisolated static func writeMask(_ mask: MaskPlane, to url: URL) throws {
            try writeGrey(mask.values.map { $0 ? 255 : 0 }, width: mask.width, height: mask.height, to: url)
        }
    }

    /// The mask's pictures for the screen, made off the main actor.
    public nonisolated enum MaskPictures {
        /// mask_view.overlay: the background under `veil`, the object's edge in `edge`, `maxSide` pixels at most.
        public static func overlay(_ object: [Bool], width: Int, height: Int, veil: MaskOverlay.Colour,
                                   edge: MaskOverlay.Colour, maxSide: Int) -> CGImage?
        {
            guard !object.isEmpty else { return nil }
            let made = MaskOverlay.rgba(object, width: width, height: height, veil: veil, edge: edge, maxSide: maxSide)
            guard let provider = CGDataProvider(data: Data(made.pixels) as CFData),
                  let space = CGColorSpace(name: CGColorSpace.sRGB)
            else { return nil }
            return CGImage(width: made.width, height: made.height, bitsPerComponent: 8, bitsPerPixel: 32,
                           bytesPerRow: made.width * 4, space: space,
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue), provider: provider,
                           decode: nil, shouldInterpolate: true, intent: .defaultIntent)
        }

        /// RGBA pixels (not premultiplied) as a picture.
        public static func rgba(_ pixels: [UInt8], width: Int, height: Int) -> CGImage? {
            guard width > 0, height > 0, pixels.count == width * height * 4,
                  let provider = CGDataProvider(data: Data(pixels) as CFData),
                  let space = CGColorSpace(name: CGColorSpace.sRGB)
            else { return nil }
            return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                           bytesPerRow: width * 4, space: space,
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue), provider: provider,
                           decode: nil, shouldInterpolate: true, intent: .defaultIntent)
        }

        /// The editor's photo as a picture.
        public static func photo(_ photo: MaskPhoto) -> CGImage? {
            guard let provider = CGDataProvider(data: Data(photo.rgb) as CFData),
                  let space = CGColorSpace(name: CGColorSpace.sRGB)
            else { return nil }
            return CGImage(width: photo.width, height: photo.height, bitsPerComponent: 8, bitsPerPixel: 24,
                           bytesPerRow: photo.width * 3, space: space,
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue), provider: provider,
                           decode: nil, shouldInterpolate: true, intent: .defaultIntent)
        }
    }
#endif
