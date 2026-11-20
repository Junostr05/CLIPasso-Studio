import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The canvas's modes (studio.py): the sketch, and what the job has besides – photo/sketch, attention, mask,
/// condition (SceneSketch: background) – then the matrix where there is one. Content: a segmented picker.
struct ViewModePicker: View {
    @Environment(AppModel.self) private var model
    @Binding var mode: String
    var matrix = false

    var body: some View {
        let t = model.texts
        let views = model.studioViews
        if !views.isEmpty || matrix {
            Picker(t.tr("ui.mac.result.view"), selection: $mode) {
                Text(t.tr("ui.mode.sketch")).tag("sketch")
                ForEach(views, id: \.self) { kind in
                    Text(t.tr(kind == "condition" && model.viewMethod == "scenesketch" ? "ui.mode.background"
                            : "ui.mode.\(kind)")).tag(kind)
                }
                if matrix { Text(t.tr("ui.mode.matrix")).tag("matrix") }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .onChange(of: views) { _, now in
                if !["sketch", "matrix"].contains(mode), !now.contains(mode) { mode = "sketch" }
            }
        }
    }
}

/// One of the views (not the sketch) fitted into the canvas; "compare" is the photo with the sketch over it up to a
/// divider to drag (the canvas's photo / sketch slider).
struct ViewPicture: View {
    @Environment(AppModel.self) private var model
    /// the views are pictures of the method's canvas: shown in the photo's shape as the sketch is
    @Environment(\.canvasStretch) private var stretch
    let kind: String
    let sketch: Sketch?
    @State private var split: CGFloat = 0.5

    var body: some View {
        let image = model.studioView(kind).flatMap { NSImage(data: $0) }
        GeometryReader { geo in
            let fitted = Self.fit(image.map { CGSize(width: $0.size.width * stretch, height: $0.size.height) } ?? .zero,
                                  in: geo.size)
            ZStack(alignment: .topLeading) {
                if let image {
                    Image(nsImage: image).resizable().interpolation(.high)
                        .frame(width: fitted.width, height: fitted.height).offset(x: fitted.minX, y: fitted.minY)
                }
                if kind == "compare" {
                    SketchView(sketch: sketch, label: "")
                        .frame(width: fitted.width, height: fitted.height).offset(x: fitted.minX, y: fitted.minY)
                        .mask(alignment: .leading) {
                            Rectangle().frame(width: fitted.width * split)
                                .offset(x: fitted.minX).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    Rectangle().fill(.white).frame(width: 2, height: fitted.height)
                        .shadow(radius: 1)
                        .offset(x: fitted.minX + fitted.width * split - 1, y: fitted.minY)
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                guard kind == "compare", fitted.width > 0 else { return }
                split = min(1, max(0, (g.location.x - fitted.minX) / fitted.width))
            })
        }
        .accessibilityLabel(Text(model.texts.tr("ui.mode.\(kind)")))
    }

    static func fit(_ size: CGSize, in box: CGSize) -> CGRect {
        guard size.width > 0, size.height > 0 else { return .zero }
        let s = min(box.width / size.width, box.height / size.height)
        let (w, h) = (size.width * s, size.height * s)
        return CGRect(x: (box.width - w) / 2, y: (box.height - h) / 2, width: w, height: h)
    }
}
