#if canImport(CoreGraphics) && canImport(ImageIO)
    import CoreGraphics
    import Foundation
    import ImageIO
    import Testing
    @testable import StudioCore

    /// The object mask over the photo as the studio draws it (mask_view.overlay) – checked against Qt's overlay of
    /// the same masks (Fixtures/mask: an ellipse with a hole and a speck; the large one shrunk as Pillow shrinks it),
    /// pixel for pixel as object, veil and outline.
    @Suite(.onOwnThreads) struct MaskOverlayTests {
        /// A grey PNG's values, row after row – the decoded bytes themselves (drawing them would manage their colour).
        static func grey(_ name: String) throws -> (width: Int, height: Int, values: [UInt8]) {
            let source = try #require(CGImageSourceCreateWithData(try Fixtures.data(name) as CFData, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            try #require(image.bitsPerPixel == 8 && image.bitsPerComponent == 8, "\(name) is no 8-bit grey picture")
            let data = try #require(image.dataProvider?.data as Data?)
            var values = [UInt8](repeating: 0, count: image.width * image.height)
            for y in 0 ..< image.height {
                for x in 0 ..< image.width { values[y * image.width + x] = data[y * image.bytesPerRow + x] }
            }
            return (image.width, image.height, values)
        }

        @Test(arguments: ["small", "large"])
        func likeTheStudio(_ name: String) throws {
            let cases = try #require(Fixtures.json("mask/overlay.json").arrayValue).compactMap(\.objectValue)
            let c = try #require(cases.first { $0["name"]?.stringValue == name })
            let mask = try Self.grey("mask/\(name).png")
            let expected = try Self.grey("mask/\(name)_overlay.png")
            let out = MaskOverlay.rgba(mask.values.map { $0 >= 128 }, width: mask.width, height: mask.height,
                                       veil: (240, 240, 236, 215), edge: (60, 110, 240, 255),
                                       maxSide: c["max_side"]?.intValue ?? 900)
            #expect(out.width == expected.width && out.height == expected.height)
            let classes = (0 ..< out.width * out.height).map { i -> UInt8 in
                switch out.pixels[i * 4 + 3] {
                case 255: 254
                case 215: 127
                default: 0
                }
            }
            let differing = zip(classes, expected.values).filter { $0 != $1 }.count
            #expect(differing == 0, "\(name): \(differing) pixels differ")
            let first = try #require((0 ..< out.width * out.height).first { out.pixels[$0 * 4 + 3] == 255 })
            #expect(Array(out.pixels[first * 4 ..< first * 4 + 3]) == [60, 110, 240])
        }

        /// Pillow's 8-bit bilinear shrink: the weights in fixed point (22 bits), rounded away from zero, clipped.
        @Test func pillowsFixedPoint() {
            #expect(Pillow.fixed(0.5) == 1 << 21 && Pillow.fixed(-0.25) == -(1 << 20))
            #expect(Pillow.clip8(-5) == 0 && Pillow.clip8(255 << 22) == 255 && Pillow.clip8(7 << 22 + 5) == 7)
            let flat = Plane<UInt8>(width: 8, height: 6, fill: 200)
            let small = Pillow.resizeBilinear(flat, width: 3, height: 2)
            #expect(small.width == 3 && small.height == 2 && small.values.allSatisfy { $0 == 200 })
        }
    }
#endif
