import Foundation
import StudioCore

#if canImport(ImageIO)
    import CoreGraphics
    import ImageIO
#endif

/// The mask and the detail brush from the phone (PhoneApi: file_mask, do_mask_*, file_details, set_details,
/// do_clear_details, do_face): the same steps as the editors in the window – the mask touched up in a session of its
/// own that keeps nothing until "Save", the detail map painted on the phone and kept by the engine.
public extension AppModel {
    /// The answers of R6a; nil: not one of them.
    func phonePaintAnswer(_ action: String, _ data: JSONObject, payload: Data?) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let notReady = texts.tr("ui.phone.page.mask_not_ready")
        switch action {
        // ---------------------------------------------------------------- the mask
        case "file_mask":
            guard let image = studio.image, mask.state == .ready || mask.state == .edited, !mask.object.isEmpty else {
                return no(notReady)
            }
            let plane = MaskPlane(width: mask.width, height: mask.height, values: mask.object)
            guard let jpeg = await phoneMaskPicture(image, plane) else { return no(notReady) }
            return .bytes(jpeg, type: "image/jpeg", name: nil)
        case "do_mask_begin":
            guard let image = studio.image, let editor = maskEditor() else { return no(notReady) }
            phone.maskSession = (image, editor, 0)
            Task {  // (the magic wand's photo, as the window's editor reads it)
                let photo = await Task.detached(executorPreference: OwnThreads.shared) {
                    AppModel.editorPhoto(image)
                }.value
                if phone.maskSession?.editor === editor { editor.photo = photo }
            }
            return .json(.object((["ok": true] as JSONObject).merging(phoneMaskInfo())))
        case "do_mask_edit":
            guard let session = phone.maskSession, session.image == studio.image else { return no(notReady) }
            let editor = session.editor
            let (w, h) = (Double(editor.width), Double(editor.height))
            switch data["op"]?.stringValue ?? "" {
            case "undo": editor.undo()
            case "redo": editor.redo()
            case "reset": editor.reset()
            case "part":
                guard let x = data["x"].flatMap(PhoneStudio.float), let y = data["y"].flatMap(PhoneStudio.float) else {
                    return no(texts.tr("ui.phone.page.failed"))
                }
                guard editor.click(x: x * w, y: y * h) else { return no(texts.tr("ui.mask_edit.nothing_here")) }
            case let op where op == "add" || op == "erase":
                let size = data["size"].flatMap(PhoneStudio.float) ?? 0.04
                let r = max(1, min(0.25, size) * w / 2)
                let points: [(x: Double, y: Double)] = (data["points"]?.arrayValue ?? []).prefix(2000).compactMap { p in
                    guard let xy = p.arrayValue, xy.count >= 2, let x = PhoneStudio.float(xy[0]),
                          let y = PhoneStudio.float(xy[1])
                    else { return nil }
                    return (x * w, y * h)
                }
                guard let first = points.first else { return no(texts.tr("ui.phone.page.failed")) }
                editor.tool = op == "add" ? .add : .erase
                editor.beginStroke(x: first.x, y: first.y, radius: r)
                for (a, b) in zip(points, points.dropFirst()) { editor.continueStroke(from: a, to: b, radius: r) }
            default:
                return no("unknown edit")
            }
            phone.maskSession?.rev += 1
            return .json(.object((["ok": true] as JSONObject).merging(phoneMaskInfo())))
        case "file_mask_edit":
            guard let session = phone.maskSession, session.image == studio.image,
                  let jpeg = await phoneMaskPicture(session.image, session.editor.mask)
            else { return no(notReady) }
            return .bytes(jpeg, type: "image/jpeg", name: nil)
        case "do_mask_save":
            guard let session = phone.maskSession, session.image == studio.image else { return no(notReady) }
            guard session.editor.share > 0 else { return no(texts.tr("ui.mask_edit.empty")) }
            do {
                try await applyMask(session.editor)
            } catch {
                return no(String(describing: error))
            }
            phone.maskSession = nil
            return .json(["ok": true])
        case "do_mask_cancel":
            phone.maskSession = nil
            return .json(["ok": true])
        // ---------------------------------------------------------------- the detail brush
        case "file_details":
            guard let image = studio.image, let engine else { return no(texts.tr("ui.phone.page.no_picture")) }
            guard let answer = try? await engine.request("phone_detail", ["image": .string(image.path),
                                                                          "side": .int(PhoneStudio.inputSide)]),
                  let path = answer.objectValue?["map"]?.stringValue
            else { return no(texts.tr("ui.phone.page.failed")) }
            defer { try? FileManager.default.removeItem(atPath: path) }
            guard let png = try? Data(contentsOf: URL(filePath: path)) else { return no(texts.tr("ui.phone.page.failed")) }
            return .bytes(png, type: "image/png", name: nil)
        case "set_details":
            guard let image = studio.image, let engine, let png = payload else {
                return no(texts.tr("ui.phone.page.no_picture"))
            }
            let file = FileManager.default.temporaryDirectory.appending(path: "phone-detail-\(UUID().uuidString).png")
            defer { try? FileManager.default.removeItem(at: file) }
            do {
                try png.write(to: file)
                _ = try await engine.request("save_detail", ["image": .string(image.path), "map": .string(file.path)])
            } catch {
                return no(String(describing: error))
            }
            await phoneDetailsChanged()
            return .json(["ok": true])
        case "do_clear_details":
            if let image = studio.image, let engine {
                _ = try? await engine.request("remove_detail", ["image": .string(image.path)])
            }
            await phoneDetailsChanged()
            return .json(["ok": true])
        case "do_face":
            guard studio.image != nil else { return no(texts.tr("ui.phone.page.no_picture")) }
            guard modelState("blazeface") != .missing else {
                return no(texts.tr("ui.phone.page.models_missing", ["size": "0.4"]))
            }
            Task { await phoneFindFaces() }
            return .json(["ok": true, "busy": true])
        default:
            return nil
        }
    }

    /// _mask_info: how much the object covers, whether a step back and forth is there, the edit's count.
    private func phoneMaskInfo() -> JSONObject {
        guard let session = phone.maskSession else { return [:] }
        let e = session.editor
        return ["share": .double((e.share * 10000).rounded(.toNearestOrEven) / 10000), "undo": .bool(e.canUndo),
                "redo": .bool(e.canRedo), "rev": .int(session.rev)]
    }

    /// The detail map changed: the page shows it again (and whether one is kept).
    func phoneDetailsChanged() async {
        phone.detailsRev += 1
        phone.detailsHas = await hasDetails()
        phone.detailsImage = studio.image
        phone.changed()
    }

    /// do_face: the faces found in the background and laid over the kept map – then the phone hears what came of it.
    private func phoneFindFaces() async {
        do {
            guard let editor = try await detailEditor() else { return }
            switch await findFaces(editor) {
            case .found:
                try await applyDetails(editor)
                phone.say(texts.tr("ui.phone.page.face_found"))
            case .none: phone.say(texts.tr("ui.detail.no_face"))
            case .missingModel: phone.say(texts.tr("ui.phone.page.models_missing", ["size": "0.4"]))
            case .failed(let why): phone.say(why)
            }
        } catch {
            phone.say(String(describing: error))
        }
        await phoneDetailsChanged()
    }

    /// _mask_picture: the studio's picture (at most 900 px) with the mask over it – the left-out part veiled in the
    /// surface colour, the object outlined in the accent, as the window shows it – as JPEG.
    func phoneMaskPicture(_ image: URL, _ mask: MaskPlane) async -> Data? {
        #if canImport(ImageIO)
            let palette = settings.theme == "light" ? Palette.light : Palette.dark
            let veil = SketchSVG.color(palette.surface2) ?? RGB(240, 240, 236)
            let edge = SketchSVG.color(palette.accent) ?? RGB(60, 110, 240)
            let side = PhoneStudio.inputSide
            return await Task.detached(executorPreference: OwnThreads.shared) { () -> Data? in
                guard let source = CGImageSourceCreateWithURL(image as CFURL, nil),
                      let photo = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                          kCGImageSourceCreateThumbnailFromImageAlways: true,
                          kCGImageSourceCreateThumbnailWithTransform: true, kCGImageSourceThumbnailMaxPixelSize: side,
                      ] as CFDictionary),
                      let over = MaskPictures.overlay(mask.values, width: mask.width, height: mask.height,
                                                      veil: (UInt8(veil.r), UInt8(veil.g), UInt8(veil.b), 215),
                                                      edge: (UInt8(edge.r), UInt8(edge.g), UInt8(edge.b), 255),
                                                      maxSide: side),
                      let space = CGColorSpace(name: CGColorSpace.sRGB),
                      let context = CGContext(data: nil, width: photo.width, height: photo.height, bitsPerComponent: 8,
                                              bytesPerRow: 0, space: space,
                                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
                else { return nil }
                let rect = CGRect(x: 0, y: 0, width: photo.width, height: photo.height)
                context.interpolationQuality = .high
                context.draw(photo, in: rect)
                context.draw(over, in: rect)
                guard let composed = context.makeImage() else { return nil }
                let out = NSMutableData()
                guard let destination = CGImageDestinationCreateWithData(out, "public.jpeg" as CFString, 1, nil) else {
                    return nil
                }
                CGImageDestinationAddImage(destination, composed, [kCGImageDestinationLossyCompressionQuality: 0.85]
                    as CFDictionary)
                return CGImageDestinationFinalize(destination) ? out as Data : nil
            }.value
        #else
            return nil
        #endif
    }
}
