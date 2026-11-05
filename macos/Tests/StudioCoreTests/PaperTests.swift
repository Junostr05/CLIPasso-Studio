import Foundation
import Testing
@testable import StudioCore
#if canImport(CoreGraphics)
    import CoreGraphics
    import ImageIO
#endif

/// The papers of gui/paper.py made in Swift – checked against the pictures Python made (Fixtures/paper/*.png): every
/// kind small and in part of a larger picture, fibres two pixels wide, a texture scaled up beyond 1600 px, a vignette
/// on a colour – and what the settings of a paper come to.
@Suite struct PaperTests {
    @Test func settingsComeToThePapersOfPython() throws {
        let fixture = try #require(Fixtures.json("paper/papers.json").objectValue)
        for c in (fixture["inputs"]?.arrayValue ?? []).compactMap(\.objectValue) {
            let paper = Paper.normalize(c["paper"])
            let expected = c["normalized"]?.objectValue
            #expect(paper?.kind.rawValue == expected?["kind"]?.stringValue, "\(String(describing: c["paper"]))")
            #expect(paper?.vignette == expected?["vignette"]?.doubleValue, "\(String(describing: c["paper"]))")
            #expect(Paper.colour(of: paper) == c["colour"]?.stringValue)
            #expect(Paper.colour(of: paper, background: "#336699") == c["colour_on_blue"]?.stringValue)
        }
        for d in (fixture["dark"]?.arrayValue ?? []).compactMap(\.objectValue) {
            let colour = d["colour"]?.stringValue ?? ""
            #expect(Paper.isDark(colour) == d["dark"]?.truthy, "\(colour)")
        }
    }

    @Test func aBigNoiseGridShrinksAsPillowShrinksIt() {
        // (a cell under a pixel makes the grid two pixels larger than the picture: Pillow then shrinks)
        let kernels = Pillow.coefficients(inSize: 34, outSize: 32)
        #expect(kernels.count == 32 && kernels.allSatisfy { abs($0.weights.reduce(0, +) - 1) < 1e-12 })
        #expect(Pillow.boxRadius(0.6) > 0 && Pillow.boxRadius(0) == 0)
    }

    #if canImport(CoreGraphics)
        /// The picture's RGB bytes, read in its own colour space (nothing converted).
        static func rgb(_ data: Data) throws -> (width: Int, height: Int, bytes: [UInt8]) {
            let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
            let image = try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let (w, h) = (image.width, image.height)
            var rgba = [UInt8](repeating: 0, count: w * h * 4)
            let space = image.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB)!
            rgba.withUnsafeMutableBytes { raw in
                let context = CGContext(data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                        space: space.model == .rgb ? space : CGColorSpace(name: CGColorSpace.sRGB)!,
                                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            }
            var bytes: [UInt8] = []
            bytes.reserveCapacity(w * h * 3)
            for i in 0 ..< w * h { bytes += rgba[i * 4 ..< i * 4 + 3] }
            return (w, h, bytes)
        }

        @Test func picturesLikePython() throws {
            let fixture = try #require(Fixtures.json("paper/papers.json").objectValue)
            let pictures = (fixture["pictures"]?.arrayValue ?? []).compactMap(\.objectValue)
            #expect(pictures.count == 14)
            for p in pictures {
                let name = p["name"]?.stringValue ?? ""
                let size = (p["size"]?.arrayValue ?? []).compactMap(\.intValue)
                let (w, h) = (size[0], size[1])
                var mine = PaperTexture.rgb(Paper.normalize(p["paper"]), width: w, height: h,
                                            background: p["background"]?.stringValue)
                var (mw, mh) = (w, h)
                if let crop = p["crop"]?.arrayValue?.compactMap(\.intValue), crop.count == 4 {
                    let (x0, y0, cw, ch) = (crop[0], crop[1], crop[2], crop[3])
                    var part: [UInt8] = []
                    for y in y0 ..< y0 + ch { part += mine[(y * w + x0) * 3 ..< (y * w + x0 + cw) * 3] }
                    (mine, mw, mh) = (part, cw, ch)
                }
                let python = try Self.rgb(Fixtures.data(p["file"]?.stringValue ?? ""))
                #expect(python.width == mw && python.height == mh, "\(name)")
                guard python.bytes.count == mine.count else { continue }
                let differences = zip(python.bytes, mine).map { abs(Int($0) - Int($1)) }
                let largest = differences.max() ?? 0
                let share = Double(differences.filter { $0 > 0 }.count) / Double(differences.count)
                print("paper \(name): largest difference \(largest), \(String(format: "%.3f", share * 100)) % of channels differ")
                // (numpy's float32 cosine – the woven linen – may be a step away from the system's)
                #expect(largest <= 1 && share <= (name.hasPrefix("linen") ? 0.02 : 0.002),
                        "\(name): largest difference \(largest), \(share * 100) % of channels differ")
            }
        }
    #endif
}
