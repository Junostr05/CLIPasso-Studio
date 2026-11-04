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
/// draws (SketchRenderer.path). The paper has the studio's rounded corners and its edge (canvas.py: no shadow –
/// surface and edge tell it from the window, which is white too in the light theme). Content, never glass.
struct SketchView: View {
    @Environment(\.colorScheme) private var scheme
    let sketch: Sketch?
    /// What VoiceOver says ("Sketch of Kamel.png, 16 strokes").
    let label: String

    var body: some View {
        let edge = Color(hex: (scheme == .dark ? Palette.dark : Palette.light).border)
        Canvas { context, size in
            guard let sketch, sketch.width > 0, sketch.height > 0 else { return }
            let scale = min(size.width / CGFloat(sketch.width), size.height / CGFloat(sketch.height))
            let (w, h) = (CGFloat(sketch.width) * scale, CGFloat(sketch.height) * scale)
            let paper = CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
            let sheet = Path(roundedRect: paper, cornerRadius: Radius.control)
            context.fill(sheet, with: .color(Color(hex: Palette.light.paper)))
            var drawing = context
            drawing.clip(to: sheet)
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
            context.stroke(Path(roundedRect: paper.insetBy(dx: 0.5, dy: 0.5), cornerRadius: Radius.control),
                           with: .color(edge), lineWidth: 1)  // (the edge, over the strokes that reach it)
        }
        .accessibilityElement()
        .accessibilityLabel(Text(verbatim: label))
        .accessibilityAddTraits(.isImage)
    }
}
