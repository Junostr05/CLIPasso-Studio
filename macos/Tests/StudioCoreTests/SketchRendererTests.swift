#if canImport(CoreGraphics)
    import CoreGraphics
    import Foundation
    import ImageIO
    import Testing
    @testable import StudioCore

    /// Core Graphics draws a sketch as Qt does in the studio's PNG export: compared pixel by pixel with the PNGs Qt
    /// drew of the same sketches (Fixtures/export/render, made by tools/make_mac_fixtures.py). Antialiasing differs a
    /// little between the two; no stroke may be missing.
    @Suite struct SketchRendererTests {
        struct Pixels {
            let width: Int, height: Int
            let bytes: [UInt8]  // RGBA

            init(_ image: CGImage) throws {
                width = image.width
                height = image.height
                var buffer = [UInt8](repeating: 0, count: width * height * 4)
                let space = image.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
                let drawn: Bool = buffer.withUnsafeMutableBytes { raw in
                    guard let context = CGContext(data: raw.baseAddress, width: image.width, height: image.height,
                                                  bitsPerComponent: 8, bytesPerRow: image.width * 4,
                                                  space: space.model == .rgb ? space : CGColorSpace(name: CGColorSpace.sRGB)!,
                                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
                    else { return false }
                    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
                    return true
                }
                try #require(drawn)
                bytes = buffer
            }

            func at(_ x: Int, _ y: Int) -> [Int] {
                let i = (y * width + x) * 4
                return [Int(bytes[i]), Int(bytes[i + 1]), Int(bytes[i + 2])]
            }
        }

        static func decode(_ data: Data) throws -> CGImage {
            let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
            return try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
        }

        static func distance(_ a: [Int], _ b: [Int]) -> Int { zip(a, b).map { abs($0 - $1) }.max() ?? 0 }

        @Test(arguments: ["lines", "cubic", "closed_bg"])
        func pngLikeQt(_ name: String) throws {
            let svg = String(decoding: try Fixtures.data("svg/\(name).svg"), as: UTF8.self)
            let qt = try Pixels(Self.decode(Fixtures.data("export/render/\(name).png")))
            let mine = try Pixels(Self.decode(SketchRenderer.exportPNG(svg: svg, size: 256)))
            #expect(mine.width == qt.width && mine.height == qt.height)
            // on average within 2 % per channel
            var total = 0
            for i in stride(from: 0, to: qt.bytes.count, by: 4) {
                for c in 0..<3 { total += abs(Int(qt.bytes[i + c]) - Int(mine.bytes[i + c])) }
            }
            let mean = Double(total) / Double(qt.width * qt.height * 3)
            #expect(mean <= 0.02 * 255, "\(name): mean difference \(mean)")
            // every clearly drawn pixel of Qt's is drawn here too (at it or a neighbour)
            let paper = qt.at(0, 0)
            var ink = 0, missing = 0
            for y in 0..<qt.height {
                for x in 0..<qt.width where Self.distance(qt.at(x, y), paper) > 102 {
                    ink += 1
                    let near = (max(0, y - 1)...min(qt.height - 1, y + 1)).contains { yy in
                        (max(0, x - 1)...min(qt.width - 1, x + 1)).contains { Self.distance(mine.at($0, yy), paper) > 38 }
                    }
                    if !near { missing += 1 }
                }
            }
            #expect(ink > 100, "\(name): Qt drew only \(ink) ink pixels")
            #expect(Double(missing) <= 0.005 * Double(ink), "\(name): \(missing) of \(ink) drawn pixels are missing")
        }

        @Test func sizeKeepsTheShape() throws {
            let wide = Sketch(width: 400, height: 100, background: nil, strokes: [])
            let w = SketchRenderer.size(of: wide, longSide: 1024)
            #expect(w.width == 1024 && w.height == 256)
            let tall = Sketch(width: 224, height: 300, background: nil, strokes: [])
            let t = SketchRenderer.size(of: tall, longSide: 300)
            #expect(t.width == 224 && t.height == 300)
            let odd = Sketch(width: 3, height: 2, background: nil, strokes: [])
            let o = SketchRenderer.size(of: odd, longSide: 5)
            #expect(o.width == 5 && o.height == 3)  // 3.33 → 3 (Python's round)
        }

        @Test func transparentWithoutBackground() throws {
            let svg = String(decoding: try Fixtures.data("svg/lines.svg"), as: UTF8.self)
            let image = try Self.decode(SketchRenderer.exportPNG(svg: svg, size: 64, background: nil))
            let px = try Pixels(image)
            #expect(px.bytes[3] == 0)  // the corner: no paper
        }
    }
#endif
