import Foundation
import StudioCore

/// The image editor's result (image_edit.ImageEditDialog.apply, phone_api.do_crop): the picture turned, mirrored and
/// cropped, saved as a new file in the output folder's "_edited" – the original stays – and taken into the studio.
public extension AppModel {
    /// "<stem>-edited-<yyyyMMdd-HHmmss>.png" in the output folder's "_edited".
    func editedImageFile(for source: URL, now: Date = Date()) -> URL {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        let stem = source.deletingPathExtension().lastPathComponent
        return settings.outputDir.appending(path: "_edited", directoryHint: .isDirectory)
            .appending(path: "\(stem)-edited-\(f.string(from: now)).png")
    }

    #if canImport(ImageIO) && canImport(CoreGraphics)
        /// apply: the picture with the frame's steps done and its frame cut out, saved; it becomes the studio's
        /// picture. Nil when the picture cannot be read or written.
        @discardableResult
        func saveEditedImage(_ source: URL, frame: CropFrame, now: Date = Date()) async -> URL? {
            let file = editedImageFile(for: source, now: now)
            let rect = frame.crop.pixels, steps = frame.steps
            let saved = await Task.detached { () -> Bool in
                guard let picture = PixelImage.read(source) else { return false }
                let edited = picture.applying(steps).cropped(x: rect.x, y: rect.y, width: rect.width,
                                                             height: rect.height)
                guard let png = edited.png() else { return false }
                try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(),
                                                         withIntermediateDirectories: true)
                return (try? png.write(to: file)) != nil
            }.value
            guard saved else { return nil }
            studio.image = file
            return file
        }

        /// do_crop: the studio's picture turned (`rotate`: 0, 90, 180, 270, clockwise), mirrored (`flip`) and cut to
        /// the normalised rectangle of the turned picture – nil and the phone's text when it cannot be done.
        func phoneCrop(_ data: JSONObject) async -> String? {
            guard let image = studio.image, FileManager.default.fileExists(atPath: image.path) else {
                return texts.tr("ui.phone.page.no_picture")
            }
            func value(_ key: String, _ fallback: Double) -> Double? {
                guard let v = data[key] else { return fallback }
                return PhoneStudio.float(v).map { min(1, max(0, $0)) }
            }
            // int(data.get("rotate") or 0) % 360 – Python's modulo, never negative
            let given = data["rotate"].flatMap { $0.truthy ? PhoneStudio.int($0) : 0 } ?? 0
            let turn = ((given % 360) + 360) % 360
            guard data["rotate"].map({ !$0.truthy || PhoneStudio.int($0) != nil }) ?? true,
                  let x = value("x", 0), let y = value("y", 0), let w = value("w", 1), let h = value("h", 1),
                  [0, 90, 180, 270].contains(turn)
            else { return texts.tr("ui.phone.page.bad_value") }
            guard let picture = await Task.detached(operation: { PixelImage.read(image) }).value else {
                return texts.tr("ui.phone.page.no_picture")
            }
            var frame = CropFrame(width: picture.width, height: picture.height)
            switch turn {
            case 90: frame.rotate(90)
            case 180: frame.rotate(90); frame.rotate(90)
            case 270: frame.rotate(-90)
            default: break
            }
            if data["flip"]?.truthy ?? false { frame.flip() }
            // QRect(round(x · W), …).intersected(the picture): Python's round, half to even
            let (fw, fh) = (frame.width, frame.height)
            let r = { (v: Double) in (v).rounded(.toNearestOrEven) }
            let (left, top) = (max(0, r(x * fw)), max(0, r(y * fh)))
            let (right, bottom) = (min(fw, r(x * fw) + r(w * fw)), min(fh, r(y * fh) + r(h * fh)))
            guard right - left >= CropFrame.minSide, bottom - top >= CropFrame.minSide else {
                return texts.tr("ui.phone.page.crop_small")
            }
            frame.crop = CropRect(left, top, right - left, bottom - top)
            return await saveEditedImage(image, frame: frame) == nil ? texts.tr("ui.phone.page.failed") : nil
        }
    #endif
}
