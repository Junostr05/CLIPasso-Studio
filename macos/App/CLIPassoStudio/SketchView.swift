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

extension EnvironmentValues {
    /// How much wider than high the method's square canvas is shown so the photo on it has its own shape (CanvasShape;
    /// 1: square) – set by a page for the run it shows, read by the sketches and the views of the canvas.
    @Entry var canvasStretch: Double = 1
}

/// A sketch on white paper – in both themes, as in the studio (Palette.paper): its strokes with round ends and
/// corners, width and opacity, scaled into the space it gets with its shape kept – the canvas in the photo's shape
/// (canvasStretch), the strokes' widths as they are. The paths are those the export draws (SketchRenderer.path). The
/// paper has the studio's rounded corners and its edge (canvas.py: no shadow – surface and edge tell it from the
/// window, which is white too in the light theme). Content, never glass.
struct SketchView: View {
    @Environment(\.colorScheme) private var scheme
    @Environment(\.canvasStretch) private var stretch
    let sketch: Sketch?
    /// What VoiceOver says ("Sketch of Kamel.png, 16 strokes").
    let label: String

    /// Where the paper lies in a space of `size` and how the sketch's units become points across and down.
    static func layout(width: Double, height: Double, stretch: Double, in size: CGSize)
        -> (paper: CGRect, sx: CGFloat, sy: CGFloat)
    {
        guard width > 0, height > 0, size.width > 0, size.height > 0 else { return (.zero, 1, 1) }
        let shown = CGSize(width: width * max(stretch, 0.01), height: height)  // (its shape on the screen)
        let s = min(size.width / shown.width, size.height / shown.height)
        let (w, h) = (shown.width * s, shown.height * s)
        let paper = CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
        return (paper, w / CGFloat(width), h / CGFloat(height))
    }

    var body: some View {
        let edge = Color(hex: (scheme == .dark ? Palette.dark : Palette.light).border)
        Canvas { context, size in
            guard let sketch, sketch.width > 0, sketch.height > 0 else { return }
            let (paper, sx, sy) = Self.layout(width: Double(sketch.width), height: Double(sketch.height), stretch: stretch,
                                               in: size)
            let sheet = Path(roundedRect: paper, cornerRadius: Radius.control)
            context.fill(sheet, with: .color(Color(hex: Palette.light.paper)))
            var drawing = context
            drawing.clip(to: sheet)
            drawing.translateBy(x: paper.minX, y: paper.minY)
            let toScreen = CGAffineTransform(scaleX: sx, y: sy)
            let widths = (sx * sy).squareRoot()  // (a stroke as wide across as down)
            if let background = SketchSVG.color(sketch.background) {
                drawing.fill(Path(CGRect(x: 0, y: 0, width: paper.width, height: paper.height)),
                             with: .color(Color(background)))
            }
            for stroke in sketch.strokes {
                let path = Path(SketchRenderer.path(stroke)).applying(toScreen)
                if let fill = stroke.fill { drawing.fill(path, with: .color(Color(fill, opacity: stroke.fillOpacity))) }
                guard stroke.stroked else { continue }
                drawing.stroke(path, with: .color(Color(stroke.color, opacity: stroke.opacity)),
                               style: StrokeStyle(lineWidth: stroke.width * widths, lineCap: SketchRenderer.lineCap(stroke.cap),
                                                  lineJoin: .round, dash: stroke.dash.map { CGFloat($0) * widths },
                                                  dashPhase: stroke.dashOffset * widths))
            }
            context.stroke(Path(roundedRect: paper.insetBy(dx: 0.5, dy: 0.5), cornerRadius: Radius.control),
                           with: .color(edge), lineWidth: 1)  // (the edge, over the strokes that reach it)
        }
        .accessibilityElement()
        .accessibilityLabel(Text(verbatim: label))
        .accessibilityAddTraits(.isImage)
    }
}
