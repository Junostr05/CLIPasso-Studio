import Foundation

/// A picture as rows of RGBA bytes, turned, mirrored and cut out exactly as QImage.transformed (by ±90°), mirrored
/// and copy do it – the image editor's pixels, without any resampling.
public struct PixelImage: Sendable, Equatable {
    public let width: Int
    public let height: Int
    /// RGBA, row by row from the top
    public let bytes: [UInt8]

    public init(width: Int, height: Int, bytes: [UInt8]) {
        precondition(bytes.count == width * height * 4)
        (self.width, self.height, self.bytes) = (width, height, bytes)
    }

    private func pixel(_ x: Int, _ y: Int) -> ArraySlice<UInt8> {
        let i = (y * width + x) * 4
        return bytes[i ..< i + 4]
    }

    private static func make(_ width: Int, _ height: Int, _ source: (Int, Int) -> ArraySlice<UInt8>) -> PixelImage {
        var out = [UInt8]()
        out.reserveCapacity(width * height * 4)
        for y in 0 ..< height {
            for x in 0 ..< width { out += source(x, y) }
        }
        return PixelImage(width: width, height: height, bytes: out)
    }

    /// Turned 90° clockwise (`clockwise`) or anticlockwise.
    public func rotated(clockwise: Bool) -> PixelImage {
        Self.make(height, width) { x, y in
            clockwise ? pixel(y, height - 1 - x) : pixel(width - 1 - y, x)
        }
    }

    /// Mirrored left to right.
    public func mirrored() -> PixelImage {
        Self.make(width, height) { x, y in pixel(width - 1 - x, y) }
    }

    /// The steps of a CropFrame (+90, −90, 0 = mirrored) done in order.
    public func applying(_ steps: [Int]) -> PixelImage {
        steps.reduce(self) { image, step in
            step == 0 ? image.mirrored() : image.rotated(clockwise: step > 0)
        }
    }

    /// QImage.copy(rect): the rectangle cut out (only its part inside the picture).
    public func cropped(x: Int, y: Int, width w: Int, height h: Int) -> PixelImage {
        let (l, t) = (max(0, x), max(0, y))
        let (r, b) = (min(width, x + w), min(height, y + h))
        guard r > l, b > t else { return PixelImage(width: 0, height: 0, bytes: []) }
        return Self.make(r - l, b - t) { px, py in pixel(l + px, t + py) }
    }
}

#if canImport(ImageIO) && canImport(CoreGraphics)
    import CoreGraphics
    import ImageIO

    public extension PixelImage {
        /// read_image: a picture file upright (its orientation applied, as the studio reads it), as RGBA bytes.
        static func read(_ url: URL) -> PixelImage? {
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let w = props[kCGImagePropertyPixelWidth] as? Int, let h = props[kCGImagePropertyPixelHeight] as? Int,
                  let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                      kCGImageSourceCreateThumbnailFromImageAlways: true,
                      kCGImageSourceCreateThumbnailWithTransform: true,
                      kCGImageSourceThumbnailMaxPixelSize: max(w, h),
                  ] as CFDictionary)
            else { return nil }
            return from(image)
        }

        static func from(_ image: CGImage) -> PixelImage? {
            let (w, h) = (image.width, image.height)
            var bytes = [UInt8](repeating: 0, count: w * h * 4)
            let drawn = bytes.withUnsafeMutableBytes { buffer -> Bool in
                guard let context = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8,
                                              bytesPerRow: w * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
                else { return false }
                context.interpolationQuality = .none
                context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
                return true
            }
            return drawn ? PixelImage(width: w, height: h, bytes: bytes) : nil
        }

        /// The picture to draw.
        var cgImage: CGImage? {
            guard width > 0, height > 0, let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
            return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
                           space: CGColorSpace(name: CGColorSpace.sRGB)!,
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                           provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
        }

        /// The picture as a PNG file's bytes.
        func png() -> Data? {
            guard let image = cgImage else { return nil }
            let out = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(out, "public.png" as CFString, 1, nil) else {
                return nil
            }
            CGImageDestinationAddImage(destination, image, nil)
            return CGImageDestinationFinalize(destination) ? out as Data : nil
        }
    }
#endif
