import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The gallery's large view (gallery_viewer.GalleryViewer): one result as large as the sheet allows – ←/→ go
/// through the results, a pinch or +/− zooms, dragging moves the zoomed sketch, a double click or 0 fits it again,
/// the slideshow (Space) goes on by itself. Content: a sheet with the sketch and a bar below.
struct GalleryViewer: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State var viewer: ViewerModel
    @State private var zoom: CGFloat = 1
    @State private var pinch: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var dragged: CGSize = .zero
    @FocusState private var focused: Bool

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                    Text(verbatim: viewer.current?.name ?? t.tr("ui.viewer.none")).font(.title2)
                    if let item = viewer.current {
                        Text(verbatim: ViewerModel.describe(item, texts: t)).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Text(verbatim: viewer.position).foregroundStyle(.tertiary).monospacedDigit()
            }
            GeometryReader { _ in
                let sketch = viewer.svg.flatMap { try? SketchSVG.parse($0) }
                ZStack {
                    if viewer.current != nil, sketch == nil {
                        Text(t.tr("ui.viewer.missing")).foregroundStyle(.secondary)
                    }
                    SketchView(sketch: sketch, label: viewer.current?.name ?? "")
                        .scaleEffect(zoom * pinch)
                        .offset(x: offset.width + dragged.width, y: offset.height + dragged.height)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .clipped()
                .gesture(MagnifyGesture()
                    .onChanged { pinch = $0.magnification }
                    .onEnded { _ in
                        zoom = min(16, max(1, zoom * pinch))
                        pinch = 1
                        if zoom == 1 { offset = .zero }
                    })
                .simultaneousGesture(DragGesture()
                    .onChanged { if zoom > 1 { dragged = $0.translation } }
                    .onEnded { _ in
                        offset.width += dragged.width
                        offset.height += dragged.height
                        dragged = .zero
                    })
                .onTapGesture(count: 2) { zoom > 1 ? fit() : zoomBy(2) }
                .help(t.tr("ui.viewer.zoom_tip"))
            }
            HStack(spacing: Spacing.spaceS) {
                Button { viewer.previous() } label: { Image(systemName: "chevron.left") }
                    .help(t.tr("ui.viewer.previous"))
                    .accessibilityLabel(t.tr("ui.viewer.previous"))
                Button { viewer.setSlideshow(!viewer.playing) } label: {
                    Label(t.tr(viewer.playing ? "ui.viewer.pause" : "ui.viewer.slideshow"),
                          systemImage: viewer.playing ? "pause.fill" : "play.fill")
                }
                .help(t.tr("ui.viewer.slideshow_tip"))
                .disabled(viewer.items.count < 2)
                Picker(t.tr("ui.viewer.slideshow"), selection: $viewer.interval) {
                    ForEach(ViewerModel.intervals, id: \.self) { Text(verbatim: "\($0) s").tag($0) }
                }
                .labelsHidden()
                .fixedSize()
                .help(t.tr("ui.viewer.interval_tip"))
                Button { viewer.next() } label: { Image(systemName: "chevron.right") }
                    .help(t.tr("ui.viewer.next"))
                    .accessibilityLabel(t.tr("ui.viewer.next"))
                Spacer()
                Text(verbatim: zoom > 1 ? "\(Int((zoom * 100).rounded())) %" : t.tr("ui.viewer.fitted"))
                    .foregroundStyle(.secondary).monospacedDigit()
                Button(t.tr("ui.viewer.fit")) { fit() }
                Button(t.tr("ui.gallery.open")) {
                    if let item = viewer.current {
                        model.studio.open(item)
                        dismiss()
                    }
                }
                .disabled(viewer.current == nil)
                Button(t.tr("ui.viewer.close")) { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(Spacing.spaceL)
        .frame(minWidth: 640, idealWidth: 1000, minHeight: 520, idealHeight: 760)
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onAppear { focused = true }
        .onDisappear { viewer.setSlideshow(false) }
        .onChange(of: viewer.index) { fit() }
        .onKeyPress(keys: [.leftArrow, .pageUp]) { _ in viewer.previous(); return .handled }
        .onKeyPress(keys: [.rightArrow, .pageDown]) { _ in viewer.next(); return .handled }
        .onKeyPress(.space) { viewer.setSlideshow(!viewer.playing); return .handled }
        .onKeyPress(.home) { viewer.show(0); return .handled }
        .onKeyPress(.end) { viewer.show(viewer.items.count - 1); return .handled }
        .onKeyPress(characters: CharacterSet(charactersIn: "+=-0")) { press in
            switch press.characters {
            case "+", "=": zoomBy(1.25)
            case "-": zoomBy(0.8)
            default: fit()
            }
            return .handled
        }
    }

    private func zoomBy(_ factor: CGFloat) {
        zoom = min(16, max(1, zoom * factor))
        if zoom == 1 { offset = .zero }
    }

    private func fit() {
        (zoom, pinch, offset, dragged) = (1, 1, .zero, .zero)
    }
}
