import StudioCore
import SwiftUI

extension Color {
    /// A colour of the studio's palette ("#RRGGBB", Tokens.generated.swift) or of a sketch.
    init(_ c: RGB, opacity: Double = 1) {
        self.init(.sRGB, red: Double(c.r) / 255, green: Double(c.g) / 255, blue: Double(c.b) / 255, opacity: opacity)
    }

    init(hex: String) {
        self.init(rgb(hex) ?? RGB(0, 0, 0))
    }
}

/// A sketch on white paper – in both themes, as in the studio (Palette.paper): its strokes with round ends and
/// corners, width and opacity, scaled into the space it gets with its shape kept. The paths are those the export
/// draws (SketchRenderer.path). Content, never glass.
struct SketchView: View {
    let sketch: Sketch?
    /// What VoiceOver says ("Sketch of Kamel.png, 16 strokes").
    let label: String

    var body: some View {
        Canvas { context, size in
            guard let sketch, sketch.width > 0, sketch.height > 0 else { return }
            let scale = min(size.width / CGFloat(sketch.width), size.height / CGFloat(sketch.height))
            let (w, h) = (CGFloat(sketch.width) * scale, CGFloat(sketch.height) * scale)
            let paper = CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
            context.fill(Path(paper), with: .color(Color(hex: Palette.light.paper)))
            var drawing = context
            drawing.translateBy(x: paper.minX, y: paper.minY)
            drawing.scaleBy(x: scale, y: scale)
            if let background = SketchSVG.color(sketch.background) {
                drawing.fill(Path(CGRect(x: 0, y: 0, width: sketch.width, height: sketch.height)),
                             with: .color(Color(background)))
            }
            for stroke in sketch.strokes {
                drawing.stroke(Path(SketchRenderer.path(stroke)), with: .color(Color(stroke.color, opacity: stroke.opacity)),
                               style: StrokeStyle(lineWidth: stroke.width, lineCap: .round, lineJoin: .round))
            }
        }
        .accessibilityElement()
        .accessibilityLabel(Text(verbatim: label))
        .accessibilityAddTraits(.isImage)
    }
}
