import StudioApp
import StudioCore
import SwiftUI

/// The detail brush (detail_edit.DetailEditDialog): the photo with the map over it – orange where the sketch gets more
/// detail, blue where less – painted with a soft brush; steps back and forth, all normal again, and portrait mode
/// (Gesicht finden) marking the faces. "Use map" has the engine keep it with the image. Keys as in the studio: 1 2 3
/// the tools, ⌘Z ⇧⌘Z.
struct DetailEditorSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Bindable var editor: DetailEditorModel
    /// after the map was kept
    let saved: () -> Void
    @State private var picture: CGImage?
    @State private var overlay: CGImage?
    @State private var hover: CGPoint?
    /// the brush's last position in the map while pressed (nil: not pressed)
    @State private var last: (x: Double, y: Double)?
    @State private var saving = false
    @State private var problem = ""

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.detail.title")).font(.title2.bold())
            Text(t.tr("ui.detail.hint")).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            canvas
                .frame(minWidth: 420, minHeight: 320)
            tools(t)
            HStack(spacing: Spacing.spaceS) {
                Text(verbatim: problem.isEmpty ? info(t) : problem)
                    .font(.callout)
                    .foregroundStyle(problem.isEmpty ? Color.secondary : Color(hex: Palette.light.danger))
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(t.tr("ui.detail.apply"), systemImage: "checkmark") { apply() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(saving || editor.finding)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(minWidth: 700, idealWidth: 820, minHeight: 600, idealHeight: 720)
        .background { shortcuts }
        .task {
            let url = editor.image
            let photo = await Task.detached(executorPreference: OwnThreads.shared) {
                AppModel.editorPhoto(url, side: DetailEditing.editSide)
            }.value
            picture = photo.flatMap { MaskPictures.photo($0) }
        }
        .task(id: editor.version) {
            let map = editor.map
            let made = await Task.detached(executorPreference: OwnThreads.shared) {
                MaskPictures.rgba(DetailEditing.overlay(map), width: map.width, height: map.height)
            }.value
            if !Task.isCancelled { overlay = made }
        }
        // (portrait mode's detector asked for: the window's own model sheet is behind this one)
        .sheet(isPresented: Binding(get: { model.models.stage != .idle },
                                    set: { if !$0 { model.cancelDownload() } })) {
            ModelSheet()
                .environment(model)
        }
    }

    // ------------------------------------------------------------------------------------------ the canvas

    private var canvas: some View {
        GeometryReader { geometry in
            let view = Self.fit(width: editor.width, height: editor.height, in: geometry.size)
            let scale = view.width / CGFloat(max(editor.width, 1))  // (points of the screen per map pixel)
            ZStack {
                RoundedRectangle(cornerRadius: Radius.card).fill(Color(nsColor: .controlBackgroundColor))
                if let picture {
                    Image(decorative: picture, scale: 1).resizable()
                        .frame(width: view.width, height: view.height)
                        .position(x: view.midX, y: view.midY)
                } else {
                    ProgressView()
                }
                if let overlay {
                    Image(decorative: overlay, scale: 1).resizable()
                        .frame(width: view.width, height: view.height)
                        .position(x: view.midX, y: view.midY)
                }
                Canvas { context, _ in
                    guard let hover else { return }
                    let r = CGFloat(editor.brush) * scale / 2
                    context.stroke(Path(ellipseIn: CGRect(x: hover.x - r, y: hover.y - r, width: 2 * r, height: 2 * r)),
                                   with: .color(.white.opacity(220 / 255)), lineWidth: 1.5)
                    let outer = r + 1.5
                    context.stroke(Path(ellipseIn: CGRect(x: hover.x - outer, y: hover.y - outer, width: 2 * outer,
                                                          height: 2 * outer)),
                                   with: .color(.black.opacity(160 / 255)), lineWidth: 1)
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
            .onContinuousHover { phase in
                switch phase {
                case .active(let point): hover = point
                case .ended: hover = nil
                }
            }
            .gesture(DragGesture(minimumDistance: 0).onChanged { drag in
                press(drag.location, view: view)
            }.onEnded { _ in
                last = nil
            })
            .disabled(editor.finding)
            .accessibilityElement()
            .accessibilityLabel(Text(model.texts.tr("ui.detail.title")))
            .accessibilityValue(Text(verbatim: info(model.texts)))
        }
    }

    /// DetailCanvas._view: the photo fitted into the canvas.
    static func fit(width: Int, height: Int, in size: CGSize) -> CGRect {
        guard width > 0, height > 0 else { return .zero }
        let s = max(0, min(size.width / CGFloat(width), size.height / CGFloat(height)))
        let (w, h) = (CGFloat(width) * s, CGFloat(height) * s)
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    /// A press (one dab) or a move while pressed (a line of dabs).
    private func press(_ point: CGPoint, view: CGRect) {
        hover = point
        guard view.width > 0 else { return }
        let scale = Double(view.width) / Double(editor.width)
        let at = (x: Double(point.x - view.minX) / scale, y: Double(point.y - view.minY) / scale)
        if let from = last {
            editor.continueStroke(from: from, to: at)
        } else {
            problem = ""
            editor.beginStroke(x: at.x, y: at.y)
        }
        last = at
    }

    // --------------------------------------------------------------------------------------------- the tools

    private func tools(_ t: Texts) -> some View {
        HStack(spacing: Spacing.spaceS) {
            Picker(t.tr("ui.detail.title"), selection: $editor.tool) {
                ForEach(DetailEditing.Tool.allCases, id: \.self) { tool in
                    Text(t.tr("ui.detail.tool_\(tool.rawValue)")).tag(tool)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            Text(t.tr("ui.mask_edit.brush")).foregroundStyle(.secondary)
            Slider(value: Binding(get: { Double(editor.brush) }, set: { editor.brush = Int($0.rounded()) }),
                   in: Double(editor.brushes.lowerBound) ... Double(editor.brushes.upperBound))
                .frame(width: 130)
                .accessibilityLabel(Text(t.tr("ui.mask_edit.brush")))
            Button(t.tr("ui.mac.edit.undo"), systemImage: "arrow.uturn.backward") { editor.undo() }
                .labelStyle(.iconOnly)
                .help(t.tr("ui.mac.edit.undo"))
                .keyboardShortcut("z", modifiers: .command)
                .disabled(!editor.canUndo)
            Button(t.tr("ui.mac.edit.redo"), systemImage: "arrow.uturn.forward") { editor.redo() }
                .labelStyle(.iconOnly)
                .help(t.tr("ui.mac.edit.redo"))
                .keyboardShortcut("z", modifiers: [.command, .shift])
                .disabled(!editor.canRedo)
            Button(t.tr("ui.detail.face"), systemImage: "viewfinder") { findFaces() }
                .help(t.tr("ui.detail.face_tip"))
                .disabled(editor.finding)
            if editor.finding { ProgressView().controlSize(.small) }
            Button(t.tr("ui.detail.clear")) { editor.clear() }
            Spacer()
        }
        .disabled(saving)
    }

    /// The studio's tool keys.
    private var shortcuts: some View {
        ZStack {
            Button("1") { editor.tool = .more }.keyboardShortcut("1", modifiers: [])
            Button("2") { editor.tool = .normal }.keyboardShortcut("2", modifiers: [])
            Button("3") { editor.tool = .less }.keyboardShortcut("3", modifiers: [])
        }
        .opacity(0)
        .accessibilityHidden(true)
    }

    // ------------------------------------------------------------------------------------------ the result

    /// _update_info: how much of the image has more and less detail – or that no face was found.
    private func info(_ t: Texts) -> String {
        if editor.noFace { return t.tr("ui.detail.no_face") }
        let share = editor.share
        return t.tr("ui.detail.share", ["more": String(format: "%.0f", share.more * 100),
                                        "less": String(format: "%.0f", share.less * 100)])
    }

    private func findFaces() {
        problem = ""
        Task {
            if case .failed(let why) = await model.findFaces(editor) { problem = why }
        }
    }

    private func apply() {
        guard !saving else { return }
        saving = true
        Task {
            do {
                try await model.applyDetails(editor)
                saved()
                dismiss()
            } catch {
                problem = String(describing: error)
                saving = false
            }
        }
    }
}
