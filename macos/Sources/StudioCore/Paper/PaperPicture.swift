#if canImport(CoreGraphics)
    import CoreGraphics
    import Foundation

    /// A paper as a picture to draw under a sketch (paper.qimage) – and, where ImageIO is, embedded in an SVG as a JPEG
    /// (paper.svg_with_paper).
    public enum PaperPicture {
        /// paper.image as an sRGB picture without alpha.
        public static func image(_ paper: Paper?, width: Int, height: Int, background: String? = nil) throws -> CGImage {
            let bytes = PaperTexture.rgb(paper, width: width, height: height, background: background)
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let provider = CGDataProvider(data: Data(bytes) as CFData),
                  let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 24,
                                      bytesPerRow: width * 3, space: space,
                                      bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                                      provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)
            else { throw SketchRenderer.RenderError(description: "no paper picture of \(width)×\(height)") }
            return image
        }
    }

    #if canImport(ImageIO)
        import ImageIO
        import UniformTypeIdentifiers

        public extension PaperPicture {
            /// px: the longer side of the paper embedded in an SVG (SVG_SIDE)
            static let svgSide = 1200

            /// svg_with_paper: the SVG with the paper as its background picture – an embedded JPEG under the strokes,
            /// covering the viewBox; a former background rectangle goes.
            static func svgWithPaper(_ svg: String, paper: Paper?, background: String?, side: Int = svgSide) -> String {
                guard let paper, let head = svg.range(of: #"<svg\b[^>]*>"#, options: .regularExpression) else { return svg }
                let start = String(svg[head])
                var (x0, y0, vw, vh) = (0.0, 0.0, 224.0, 224.0)
                if let box = attribute("viewBox", in: start, pattern: #"[^"]+"#) {
                    let v = box.replacingOccurrences(of: ",", with: " ").split(separator: " ").compactMap { Double($0) }
                    if v.count == 4 { (x0, y0, vw, vh) = (v[0], v[1], v[2], v[3]) }
                } else {
                    vw = attribute("width", in: start, pattern: #"[\d.]+"#).flatMap(Double.init) ?? 224
                    vh = attribute("height", in: start, pattern: #"[\d.]+"#).flatMap(Double.init) ?? 224
                }
                let scale = Double(side) / max(vw, vh, 1e-6)
                let pw = max(1, Int((vw * scale).rounded(.toNearestOrEven)))
                let ph = max(1, Int((vh * scale).rounded(.toNearestOrEven)))
                guard let picture = try? image(paper, width: pw, height: ph, background: background),
                      let jpeg = jpegData(picture, quality: 0.88)
                else { return svg }
                let href = "data:image/jpeg;base64," + jpeg.base64EncodedString()
                let body = String(svg[head.upperBound...])
                    .replacingOccurrences(of: #"<rect\b[^>]*data-bg="1"[^>]*/>"#, with: "", options: .regularExpression)
                let g = SketchExport.pythonG
                let tag = #"<image data-bg="1" x="\#(g(x0))" y="\#(g(y0))" width="\#(g(vw))" height="\#(g(vh))" "#
                    + #"preserveAspectRatio="none" href="\#(href)" xlink:href="\#(href)"/>"#
                let opening = start.contains("xmlns:xlink")
                    ? start : String(start.dropLast()) + #" xmlns:xlink="http://www.w3.org/1999/xlink">"#
                return String(svg[..<head.lowerBound]) + opening + tag + body
            }

            /// The value of `name="…"` in a start tag (its first match, as Python's re.search).
            internal static func attribute(_ name: String, in tag: String, pattern: String) -> String? {
                guard let found = tag.range(of: "\(name)=\"\(pattern)", options: .regularExpression) else { return nil }
                return String(tag[found].dropFirst(name.count + 2)).replacingOccurrences(of: "\"", with: "")
            }

            static func jpegData(_ image: CGImage, quality: Double) -> Data? {
                let data = NSMutableData()
                guard let destination = CGImageDestinationCreateWithData(data as CFMutableData,
                                                                         UTType.jpeg.identifier as CFString, 1, nil)
                else { return nil }
                CGImageDestinationAddImage(destination, image,
                                           [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
                return CGImageDestinationFinalize(destination) ? data as Data : nil
            }
        }
    #endif
#endif
