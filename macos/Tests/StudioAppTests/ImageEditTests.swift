import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The image editor's result and the phone's crop (do_crop): a copy in "_edited", turned, mirrored and cut as asked,
/// taken into the studio – too small or wrong values refused with the phone's texts.
@Suite(.serialized) struct ImageEditTests {
    #if canImport(ImageIO) && canImport(CoreGraphics)
        @Test func cropFromThePhone() async throws {
            let dir = FileManager.default.temporaryDirectory.appending(path: "edit-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                     store: AppModelTests.store(language: "de", ["output_dir": .string(dir.path)]))
            #expect(await model.phoneCrop([:]) == model.texts.tr("ui.phone.page.no_picture"))
            var bytes = [UInt8]()
            for y in 0 ..< 30 {
                for x in 0 ..< 40 { bytes += [UInt8(x * 6), UInt8(y * 8), UInt8((x + y) % 7 * 30), 255] }
            }
            let picture = PixelImage(width: 40, height: 30, bytes: bytes)
            let source = dir.appending(path: "Kamel.png")
            try #require(picture.png()).write(to: source)
            model.studio.image = source

            #expect(await model.phoneCrop(["rotate": 45]) == model.texts.tr("ui.phone.page.bad_value"))
            #expect(await model.phoneCrop(["rotate": "x"]) == model.texts.tr("ui.phone.page.bad_value"))
            #expect(await model.phoneCrop(["w": 0.3]) == model.texts.tr("ui.phone.page.crop_small"))  // (12 px)
            #expect(model.studio.image == source)

            #expect(await model.phoneCrop(["rotate": 90, "flip": true, "x": 0.1, "y": 0, "w": 0.6, "h": 1]) == nil)
            let made = try #require(model.studio.image)
            #expect(made.deletingLastPathComponent().lastPathComponent == "_edited"
                && made.lastPathComponent.hasPrefix("Kamel-edited-") && made.pathExtension == "png")
            let want = picture.applying([90, 0]).cropped(x: 3, y: 0, width: 18, height: 40)
            #expect(PixelImage.read(made) == want)
            #expect(FileManager.default.fileExists(atPath: source.path))  // (the original stays)

            // the window's editor: a frame of its own
            var frame = CropFrame(width: 40, height: 30)
            frame.setAspect(1)
            frame.rotate(-90)
            let saved = try #require(await model.saveEditedImage(source, frame: frame,
                                                                 now: Date(timeIntervalSince1970: 0)))
            #expect(PixelImage.read(saved)?.width == 30 && PixelImage.read(saved)?.height == 30)
            #expect(model.studio.image == saved)
        }
    #endif

    @Test func theFilesName() throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de"))
        let file = model.editedImageFile(for: URL(filePath: "/Bilder/Bär.jpeg"))
        #expect(file.deletingLastPathComponent().path == model.settings.outputDir.appending(path: "_edited").path)
        #expect(file.lastPathComponent.hasPrefix("Bär-edited-") && file.lastPathComponent.count == "Bär-edited-".count + 19)
    }
}
