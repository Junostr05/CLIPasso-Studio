#if canImport(CoreGraphics)
    import CoreGraphics
    import Foundation
    import ImageIO
    import UniformTypeIdentifiers

    /// A sketch drawn with Core Graphics as the studio draws it with Qt (gui/export.svg_to_qimage): every stroke with
    /// round ends and corners, its width and opacity, in sRGB; the sketch's own background first, when it has one.
    public enum SketchRenderer {
        public struct RenderError: Error, CustomStringConvertible, Sendable {
            public let description: String
        }

        /// One stroke as a path in the sketch's pixel space (y down, as in the SVG).
        public static func path(_ stroke: SketchStroke) -> CGPath {
            let path = CGMutablePath()
            path.move(to: CGPoint(x: stroke.start.x, y: stroke.start.y))
            for segment in stroke.segments {
                let p = segment.points.map { CGPoint(x: $0.x, y: $0.y) }
                switch (segment.kind, p.count) {
                case ("quad", 2...): path.addQuadCurve(to: p[1], control: p[0])
                case ("cubic", 3...): path.addCurve(to: p[2], control1: p[0], control2: p[1])
                default: if let end = p.last { path.addLine(to: end) }
                }
            }
            if stroke.closed { path.closeSubpath() }
            return path
        }

        /// The pixel size with the longer side `longSide`, in the sketch's shape (export._dims, Python's round).
        public static func size(of sketch: Sketch, longSide: Int) -> (width: Int, height: Int) {
            let aspect = Double(max(sketch.width, 1)) / Double(max(sketch.height, 1))
            func round(_ v: Double) -> Int { max(1, Int(v.rounded(.toNearestOrEven))) }
            return aspect >= 1 ? (longSide, round(Double(longSide) / aspect)) : (round(Double(longSide) * aspect), longSide)
        }

        static func cgColor(_ c: RGB, alpha: Double = 1) -> CGColor {
            CGColor(srgbRed: CGFloat(c.r) / 255, green: CGFloat(c.g) / 255, blue: CGFloat(c.b) / 255, alpha: CGFloat(alpha))
        }

        /// Draw the sketch into `rect` of a context whose y axis points up (a bitmap context's): the sketch fills the
        /// rect, scaled like the SVG's viewBox.
        public static func draw(_ sketch: Sketch, in context: CGContext, rect: CGRect) {
            context.saveGState()
            context.translateBy(x: rect.minX, y: rect.maxY)
            context.scaleBy(x: rect.width / CGFloat(max(sketch.width, 1)), y: -rect.height / CGFloat(max(sketch.height, 1)))
            if let background = SketchSVG.color(sketch.background) {
                context.setFillColor(cgColor(background))
                context.fill(CGRect(x: 0, y: 0, width: sketch.width, height: sketch.height))
            }
            context.setLineCap(.round)
            context.setLineJoin(.round)
            for stroke in sketch.strokes {
                context.addPath(path(stroke))
                context.setStrokeColor(cgColor(stroke.color, alpha: stroke.opacity))
                context.setLineWidth(CGFloat(stroke.width))
                context.strokePath()
            }
            context.restoreGState()
        }

        /// The sketch as an image with its longer side `longSide`, on `background` (nil: transparent) or on a copy of
        /// `under` (a paper of the image's size).
        public static func image(_ sketch: Sketch, longSide: Int, background: RGB? = RGB(255, 255, 255),
                                 under: CGImage? = nil) throws -> CGImage
        {
            let (width, height) = size(of: sketch, longSide: longSide)
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { throw RenderError(description: "no bitmap of \(width)×\(height)") }
            context.setAllowsAntialiasing(true)
            context.setShouldAntialias(true)
            context.interpolationQuality = .high
            if let under {
                context.draw(under, in: CGRect(x: 0, y: 0, width: width, height: height))
            } else if let background {
                context.setFillColor(cgColor(background))
                context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            }
            draw(sketch, in: context, rect: CGRect(x: 0, y: 0, width: width, height: height))
            guard let image = context.makeImage() else { throw RenderError(description: "the bitmap gave no image") }
            return image
        }

        public static func pngData(_ image: CGImage) throws -> Data {
            let data = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(data as CFMutableData, UTType.png.identifier as CFString,
                                                                     1, nil)
            else { throw RenderError(description: "no PNG writer") }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { throw RenderError(description: "the PNG was not written") }
            return data as Data
        }

        /// export.export_png: the sketch file restyled (SketchExport) and drawn with its longer side `size` on
        /// `background` ("#FFFFFF" as the studio; nil: transparent).
        public static func exportPNG(svg: String, size: Int = 1024, strokeColor: String? = nil, widthScale: Double = 1,
                                     background: String? = "#FFFFFF") throws -> Data
        {
            let restyled = SketchExport.restyleSVG(svg, strokeColor: strokeColor, widthScale: widthScale)
            let sketch = try SketchSVG.parse(restyled)
            return try pngData(image(sketch, longSide: size, background: background.flatMap { SketchSVG.color($0) }))
        }
    }
#endif
