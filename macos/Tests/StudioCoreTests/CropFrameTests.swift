import Foundation
import Testing
@testable import StudioCore

/// The image editor's crop frame and pixels as gui/image_edit.py makes them (Fixtures/crop/crop.json): the aspect
/// fitted, the frame moved and its handles dragged, turned and mirrored with the picture; the pixels of a picture
/// turned, mirrored and cut out like QImage does it.
@Suite struct CropFrameTests {
    static func rect(_ v: JSONValue?) -> CropRect? {
        guard let a = v?.arrayValue?.compactMap(\.doubleValue), a.count == 4 else { return nil }
        return CropRect(a[0], a[1], a[2], a[3])
    }

    static func near(_ a: CropRect, _ b: CropRect?) -> Bool {
        guard let b else { return false }
        return [abs(a.x - b.x), abs(a.y - b.y), abs(a.width - b.width), abs(a.height - b.height)].allSatisfy { $0 < 1e-5 }
    }

    @Test func likeTheStudio() throws {
        let cases = try #require(Fixtures.json("crop/crop.json").objectValue)
        for c in cases["fit"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            let size = c["size"]?.arrayValue?.compactMap(\.intValue) ?? []
            var f = CropFrame(width: size[0], height: size[1], crop: Self.rect(c["crop"]) ?? .null,
                              aspect: c["aspect"]?.doubleValue)
            f.fitAspect()
            #expect(Self.near(f.crop, Self.rect(c["out"])), "fit \(c)")
        }
        for c in cases["drag"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            let start = CropRect(100, 80, 160, 120)
            var f = CropFrame(width: 400, height: 300, crop: start, aspect: c["aspect"]?.doubleValue)
            let p = c["point"]?.arrayValue?.compactMap(\.doubleValue) ?? []
            f.drag(c["handle"]?.stringValue ?? "", to: (p[0], p[1]), from: start, press: (150, 100))
            #expect(Self.near(f.crop, Self.rect(c["out"])), "drag \(c)")
        }
        for c in cases["turn"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            var f = CropFrame(width: 400, height: 300, crop: CropRect(30, 40, 200, 150), aspect: c["aspect"]?.doubleValue)
            for step in c["steps"]?.arrayValue ?? [] {
                if let degrees = step.intValue { f.rotate(degrees) } else { f.flip() }
            }
            let size = c["size"]?.arrayValue?.compactMap(\.intValue) ?? []
            #expect(Self.near(f.crop, Self.rect(c["crop"])) && Int(f.width) == size[0] && Int(f.height) == size[1],
                    "turn \(c)")
            #expect(f.aspect == c["after"]?.doubleValue)
        }
    }

    #if canImport(ImageIO) && canImport(CoreGraphics)
        @Test func thePixels() throws {
            let cases = try #require(Fixtures.json("crop/crop.json").objectValue)
            let input = try #require(PixelImage.read(Fixtures.url("crop/input.png")))
            #expect(input.width == 7 && input.height == 5)
            for c in cases["pictures"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
                let steps = (c["steps"]?.arrayValue ?? []).map { $0.intValue ?? 0 }
                let r = c["crop"]?.arrayValue?.compactMap(\.intValue) ?? []
                let made = input.applying(steps).cropped(x: r[0], y: r[1], width: r[2], height: r[3])
                let want = try #require(PixelImage.read(Fixtures.url("crop/\(c["file"]?.stringValue ?? "")")))
                #expect(made == want, "\(c)")
                // and as a PNG of its own, read again
                let file = FileManager.default.temporaryDirectory.appending(path: "crop-\(UUID().uuidString).png")
                try #require(made.png()).write(to: file)
                #expect(PixelImage.read(file) == want)
            }
        }
    #endif
}
