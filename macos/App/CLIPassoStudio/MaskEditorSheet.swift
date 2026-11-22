import StudioApp
import StudioCore
import SwiftUI

/// Touching up the object mask (mask_edit.MaskEditDialog): the photo with what the run leaves out veiled; a click on a
/// part takes it away or brings one in (Teile wählen), the brush adds or removes; steps back and forth, back to the
/// model's mask; "Use this mask" keeps it. Keys as in the studio: 1 2 3 the tools, [ ] the brush, ⌘Z ⇧⌘Z.
struct MaskEditorSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var scheme
    @Bindable var editor: MaskEditorModel
    @State private var picture: CGImage?
    @State private var overlay: CGImage?
    @State private var hover: CGPoint?
    /// the brush's last position in the image while pressed (nil: not pressed)
    @State private var last: (x: Double, y: Double)?
    @State private var pressed = false
    @State private var saving = false
    @State private var problem = ""

    /// the studio's veil over what the run leaves out (QColor(150, 20, 40, 150))
    static let veil: MaskOverlay.Colour = (150, 20, 40, 150)
    /// the brush's size range (the studio's slider)
    static let brushes = 6.0 ... 160.0

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.mask_edit.title")).font(.title2.bold())
            Text(t.tr("ui.mask_edit.hint")).font(.callout).foregroundStyle(.secondary)
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
                Button(t.tr("ui.mask_edit.apply"), systemImage: "checkmark") { apply() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(saving || editor.share == 0)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(minWidth: 700, idealWidth: 820, minHeight: 600, idealHeight: 720)
        .background { shortcuts }
        .task {
            let url = editor.image
            let photo = await Task.detached(executorPreference: OwnThreads.shared) {
                url.flatMap { AppModel.editorPhoto($0) }
            }.value
            editor.photo = photo
            picture = photo.flatMap { MaskPictures.photo($0) }
        }
        .task(id: [editor.version, scheme == .dark ? 1 : 0]) {
            if overlay != nil {  // (the studio redraws the veil 40 ms after the last change)
                try? await Task.sleep(for: .milliseconds(40))
                if Task.isCancelled { return }
            }
            let accent = SketchSVG.color((scheme == .dark ? Palette.dark : Palette.light).accent) ?? RGB(60, 110, 240)
            let edge: MaskOverlay.Colour = (UInt8(accent.r), UInt8(accent.g), UInt8(accent.b), 255)
            let (object, width, height, veil) = (editor.mask.values, editor.width, editor.height, Self.veil)
            let made = await Task.detached(executorPreference: OwnThreads.shared) {
                MaskPictures.overlay(object, width: width, height: height, veil: veil, edge: edge, maxSide: 1200)
            }.value
            if !Task.isCancelled { overlay = made }
        }
    }

    // ------------------------------------------------------------------------------------------ the canvas

    private var canvas: some View {
        GeometryReader { geometry in
            let view = Self.fit(width: editor.width, height: editor.height, in: geometry.size)
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
                    guard let hover, editor.tool != .part else { return }
                    let r = editor.brush / 2
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
                pressed = false
                last = nil
            })
            .pointerStyle(editor.tool == .part ? .link : nil)
            .pointerVisibility(editor.tool == .part || hover == nil ? .automatic : .hidden)
            .accessibilityElement()
            .accessibilityLabel(Text(model.texts.tr("ui.mask_edit.title")))
            .accessibilityValue(Text(verbatim: info(model.texts)))
        }
    }

    /// MaskCanvas._view: the photo fitted into the canvas, 12 points from its edge.
    static func fit(width: Int, height: Int, in size: CGSize) -> CGRect {
        let m: CGFloat = 12
        guard width > 0, height > 0 else { return .zero }
        let s = max(0, min((size.width - 2 * m) / CGFloat(width), (size.height - 2 * m) / CGFloat(height)))
        let (w, h) = (CGFloat(width) * s, CGFloat(height) * s)
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    /// A press or a move while pressed: the click of Teile wählen, or the brush's dab and then its line.
    private func press(_ point: CGPoint, view: CGRect) {
        hover = point
        guard view.width > 0 else { return }
        let scale = Double(view.width) / Double(editor.width)  // (points of the screen per mask pixel)
        let at = (x: Double(point.x - view.minX) / scale, y: Double(point.y - view.minY) / scale)
        let radius = editor.brush / 2 / scale
        if !pressed {
            pressed = true
            problem = ""
            if editor.tool == .part {
                editor.click(x: at.x, y: at.y)
                return
            }
            editor.beginStroke(x: at.x, y: at.y, radius: radius)
            last = at
        } else if editor.tool != .part, let from = last {
            editor.continueStroke(from: from, to: at, radius: radius)
            last = at
        }
    }

    // --------------------------------------------------------------------------------------------- the tools

    private func tools(_ t: Texts) -> some View {
        HStack(spacing: Spacing.spaceS) {
            Picker(t.tr("ui.mask_edit.title"), selection: $editor.tool) {
                Text(t.tr("ui.mask_edit.tool_part")).tag(MaskEditorModel.Tool.part)
                Text(t.tr("ui.mask_edit.tool_add")).tag(MaskEditorModel.Tool.add)
                Text(t.tr("ui.mask_edit.tool_erase")).tag(MaskEditorModel.Tool.erase)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            Group {
                Text(t.tr("ui.mask_edit.brush")).foregroundStyle(.secondary)
                Slider(value: $editor.brush, in: Self.brushes)
                    .frame(width: 130)
                    .accessibilityLabel(Text(t.tr("ui.mask_edit.brush")))
            }
            .disabled(editor.tool == .part)
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
            Button(t.tr("ui.mask_edit.reset")) { editor.reset() }
                .help(t.tr("ui.mask_edit.reset_tip"))
                .disabled(editor.isAuto)
            Spacer()
        }
    }

    /// The studio's keys without a button of their own: 1 2 3 the tools, [ ] the brush smaller and larger.
    private var shortcuts: some View {
        ZStack {
            Button("1") { editor.tool = .part }.keyboardShortcut("1", modifiers: [])
            Button("2") { editor.tool = .add }.keyboardShortcut("2", modifiers: [])
            Button("3") { editor.tool = .erase }.keyboardShortcut("3", modifiers: [])
            Button("[") { step(-1) }.keyboardShortcut("[", modifiers: [])
            Button("]") { step(1) }.keyboardShortcut("]", modifiers: [])
        }
        .opacity(0)
        .accessibilityHidden(true)
    }

    /// MaskEditDialog._step: a quarter larger or a fifth smaller, and one more point.
    private func step(_ direction: Int) {
        let next = Double(Int(editor.brush * (direction > 0 ? 1.25 : 0.8)) + direction)
        editor.brush = min(Self.brushes.upperBound, max(Self.brushes.lowerBound, next))
    }

    // ------------------------------------------------------------------------------------------ the result

    /// _update_info: how much of the image the object covers – or why a click changed nothing.
    private func info(_ t: Texts) -> String {
        if editor.missed { return t.tr("ui.mask_edit.nothing_here") }
        let share = editor.share
        return share > 0 ? t.tr("ui.mask_edit.share", ["pct": String(format: "%.0f", share * 100)])
            : t.tr("ui.mask_edit.empty")
    }

    private func apply() {
        guard editor.share > 0, !saving else { return }
        saving = true
        Task {
            do {
                try await model.applyMask(editor)
                dismiss()
            } catch {
                problem = String(describing: error)
                saving = false
            }
        }
    }
}
