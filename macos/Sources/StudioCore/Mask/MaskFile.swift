#if canImport(ImageIO)
    import CoreGraphics
    import Foundation
    import ImageIO

    /// The engine's mask pictures: the model's probability as the mask cache keeps it (masking._write_cached: a 16-bit
    /// grey PNG, 65535 the object for sure) and the user's edited mask (an 8-bit grey PNG, white the object).
    public enum MaskFile {
        public struct ReadError: Error, CustomStringConvertible, Sendable {
            public let description: String

            public init(description: String) {
                self.description = description
            }
        }

        /// The values 0 … 1, row after row, as masking reads them (in float: the 16 bits / 65535, the 8 bits / 255) –
        /// the picture's bytes themselves, not drawn (drawing would manage their colour).
        public static func read(_ url: URL) throws -> (width: Int, height: Int, values: [Float]) {
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
            else { throw ReadError(description: "no picture at \(url.path)") }
            let bits = image.bitsPerComponent
            guard image.bitsPerPixel == bits, bits == 8 || bits == 16, let data = image.dataProvider?.data as Data?
            else { throw ReadError(description: "\(url.lastPathComponent) is no 8- or 16-bit grey picture") }
            let (w, h, row) = (image.width, image.height, image.bytesPerRow)
            let little = image.bitmapInfo.contains(.byteOrder16Little)  // (else big-endian: Core Graphics' own)
            var values = [Float](repeating: 0, count: w * h)
            data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
                for y in 0 ..< h {
                    for x in 0 ..< w {
                        if bits == 8 {
                            values[y * w + x] = Float(raw[y * row + x]) / 255
                        } else {
                            let (a, b) = (UInt16(raw[y * row + 2 * x]), UInt16(raw[y * row + 2 * x + 1]))
                            values[y * w + x] = Float(little ? b << 8 | a : a << 8 | b) / 65535
                        }
                    }
                }
            }
            return (w, h, values)
        }
    }
#endif
