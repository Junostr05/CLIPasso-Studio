import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The image editor (image_edit.ImageEditDialog): the picture with a crop frame – drag inside to move it, drag its
/// handles to resize it –, an aspect ratio, turned left or right, mirrored, reset; *Use this image* saves a copy in
/// the output folder's "_edited" and takes it into the studio (the original stays). Content: a sheet.
struct ImageEditSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let source: URL
    @State private var original: PixelImage?
    @State private var frame: CropFrame?
    @State private var shown: CGImage?
    @State private var aspectIndex = 0
    @State private var drag: (handle: String, start: CropRect, press: (Double, Double))?
    @State private var failed = false

    static let handle: CGFloat = 9  // HANDLE: the handles' size on the screen
    static let margin: CGFloat = 14

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.edit_image.title")).font(.title2)
            GeometryReader { geo in
                if let frame, let shown {
                    let (view, scale) = Self.place(frame, in: geo.size)
                    ZStack(alignment: .topLeading) {
                        Image(decorative: shown, scale: 1).resizable().interpolation(.high)
                            .frame(width: view.width, height: view.height).offset(x: view.minX, y: view.minY)
                        Canvas { context, _ in draw(frame, view: view, scale: scale, in: &context) }
                    }
                    .contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { g in dragged(g, frame: frame, view: view, scale: scale) }
                        .onEnded { _ in drag = nil })
                } else if failed {
                    Text(t.tr("ui.viewer.missing")).foregroundStyle(.secondary)
                } else {
                    ProgressView()
                }
            }
            .frame(minHeight: 360)
            HStack(spacing: Spacing.spaceS) {
                Picker(t.tr("ui.edit_image.title"), selection: $aspectIndex) {
                    ForEach(CropFrame.aspects.indices, id: \.self) { i in
                        Text(t.tr("ui.edit_image.aspect_\(CropFrame.aspects[i].key)")).tag(i)
                    }
                }
                .labelsHidden().fixedSize()
                .onChange(of: aspectIndex) { _, i in frame?.setAspect(CropFrame.aspects[i].value) }
                Button { turn(-90) } label: { Image(systemName: "rotate.left") }
                    .help(t.tr("ui.edit_image.rotate_left")).accessibilityLabel(t.tr("ui.edit_image.rotate_left"))
                Button { turn(90) } label: { Image(systemName: "rotate.right") }
                    .help(t.tr("ui.edit_image.rotate_right")).accessibilityLabel(t.tr("ui.edit_image.rotate_right"))
                Button { flip() } label: { Image(systemName: "arrow.left.and.right.righttriangle.left.righttriangle.right") }
                    .help(t.tr("ui.edit_image.flip")).accessibilityLabel(t.tr("ui.edit_image.flip"))
                Button(t.tr("ui.edit_image.reset")) { reset() }
                Spacer()
                if let r = frame?.crop.pixels {
                    Text(verbatim: "\(r.width) × \(r.height) px").foregroundStyle(.secondary).monospacedDigit()
                }
            }
            HStack {
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { dismiss() }
                Button(t.tr("ui.edit_image.apply")) {
                    guard let frame else { return }
                    Task {
                        if await model.saveEditedImage(source, frame: frame) != nil { dismiss() } else { failed = true }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(frame == nil)
            }
        }
        .padding(Spacing.spaceL)
        .frame(minWidth: 640, idealWidth: 760, minHeight: 560, idealHeight: 640)
        .task {
            let url = source
            original = await Task.detached { PixelImage.read(url) }.value
            failed = original == nil
            reset()
        }
    }

    /// Where the picture is drawn in the view, and its scale (_view).
    static func place(_ frame: CropFrame, in size: CGSize) -> (CGRect, CGFloat) {
        let s = min((size.width - 2 * margin) / frame.width, (size.height - 2 * margin) / frame.height)
        let (w, h) = (frame.width * s, frame.height * s)
        return (CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h), s)
    }

    static func onScreen(_ r: CropRect, _ view: CGRect, _ s: CGFloat) -> CGRect {
        CGRect(x: view.minX + r.x * s, y: view.minY + r.y * s, width: r.width * s, height: r.height * s)
    }

    /// _handles: the corners (and with a free frame the sides' middles), on the screen.
    static func handles(_ frame: CropFrame, _ view: CGRect, _ s: CGFloat) -> [(String, CGPoint)] {
        let r = onScreen(frame.crop, view, s)
        var out = [("nw", CGPoint(x: r.minX, y: r.minY)), ("ne", CGPoint(x: r.maxX, y: r.minY)),
                   ("sw", CGPoint(x: r.minX, y: r.maxY)), ("se", CGPoint(x: r.maxX, y: r.maxY))]
        if frame.aspect == nil {
            out += [("n", CGPoint(x: r.midX, y: r.minY)), ("s", CGPoint(x: r.midX, y: r.maxY)),
                    ("w", CGPoint(x: r.minX, y: r.midY)), ("e", CGPoint(x: r.maxX, y: r.midY))]
        }
        return out
    }

    private func draw(_ frame: CropFrame, view: CGRect, scale: CGFloat, in context: inout GraphicsContext) {
        let r = Self.onScreen(frame.crop, view, scale)
        var outside = Path(view)
        outside.addRect(r)
        context.fill(outside, with: .color(.black.opacity(0.59)), style: FillStyle(eoFill: true))
        for i in 1 ... 2 {  // rule of thirds
            let x = r.minX + r.width * CGFloat(i) / 3, y = r.minY + r.height * CGFloat(i) / 3
            var lines = Path()
            lines.move(to: CGPoint(x: x, y: r.minY))
            lines.addLine(to: CGPoint(x: x, y: r.maxY))
            lines.move(to: CGPoint(x: r.minX, y: y))
            lines.addLine(to: CGPoint(x: r.maxX, y: y))
            context.stroke(lines, with: .color(.white.opacity(0.43)), lineWidth: 1)
        }
        context.stroke(Path(r), with: .color(.accentColor), lineWidth: 2)
        for (_, p) in Self.handles(frame, view, scale) {
            let box = Path(CGRect(x: p.x - Self.handle / 2, y: p.y - Self.handle / 2, width: Self.handle,
                                  height: Self.handle))
            context.fill(box, with: .color(.white))
            context.stroke(box, with: .color(.accentColor), lineWidth: 2)
        }
    }

    private func dragged(_ g: DragGesture.Value, frame current: CropFrame, view: CGRect, scale: CGFloat) {
        let toImage = { (p: CGPoint) in (Double((p.x - view.minX) / scale), Double((p.y - view.minY) / scale)) }
        if drag == nil {  // _handle_at, where the drag began
            let at = g.startLocation
            let handle = Self.handles(current, view, scale).first {
                abs(at.x - $0.1.x) <= Self.handle && abs(at.y - $0.1.y) <= Self.handle
            }?.0 ?? (Self.onScreen(current.crop, view, scale).contains(at) ? "move" : nil)
            guard let handle else { return }
            drag = (handle, current.crop, toImage(at))
        }
        guard let drag else { return }
        frame?.drag(drag.handle, to: toImage(g.location), from: drag.start, press: drag.press)
    }

    private func turn(_ degrees: Int) {
        frame?.rotate(degrees)
        if let a = frame?.aspect, let i = CropFrame.aspects.firstIndex(where: { $0.value == a }) {
            aspectIndex = i  // (a 4:3 frame turned into 3:4)
        }
        redraw()
    }

    private func flip() {
        frame?.flip()
        redraw()
    }

    private func reset() {
        aspectIndex = 0
        frame = original.map { CropFrame(width: $0.width, height: $0.height) }
        redraw()
    }

    private func redraw() {
        shown = frame.flatMap { original?.applying($0.steps).cgImage }
    }
}
