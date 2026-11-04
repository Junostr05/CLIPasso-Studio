import StudioApp
import StudioCore
import SwiftUI

/// The tool on a finished sketch (studio.py: the eraser and the pen; one at a time).
enum EditTool: Equatable {
    case none, eraser, pen
}

/// A finished job on the studio's canvas: its sketch, which can be touched up with the tools above it, and below it
/// the job's other sketches to choose from (studio.py, canvas.py).
struct ResultCanvas: View {
    @Environment(AppModel.self) private var model
    let result: StudioResult
    @State private var tool = EditTool.none

    var body: some View {
        ZStack {
            if let editor = result.editor {
                EditableSketch(editor: editor, tool: tool)
                    .padding(Spacing.spaceXl)
            } else {
                Text(model.texts.tr("ui.canvas_placeholder"))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: Spacing.readingWidth)
            }
        }
        .overlay(alignment: .top) {
            if let editor = result.editor {
                EditTools(editor: editor, tool: $tool)
                    .padding(.top, Spacing.spaceS)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if result.runs.count > 1 { ResultSketches(result: result) }
        }
        .onChange(of: result.editor?.canErase ?? false) { _, can in
            if !can, tool == .eraser { tool = .none }
        }
    }
}

/// The sketch to touch up (canvas.py): with the eraser the stroke under the pointer turns red and goes on a click –
/// dragged over strokes, it takes each one (one step back for the press); with the pen a drag draws a stroke of one's
/// own. Content: the paper and its strokes; the red stroke and the line being drawn are drawn over them.
struct EditableSketch: View {
    @Environment(AppModel.self) private var model
    let editor: SketchEditor
    let tool: EditTool
    @State private var sketch: Sketch?
    @State private var index: SketchEditing.StrokeIndex?
    @State private var box = (x: 0.0, y: 0.0, width: 1.0, height: 1.0)
    @State private var hover: Int?
    @State private var drawn: [CGPoint] = []
    @State private var pressed = false

    /// canvas.ERASER_REACH_PX: how close the pointer has to be to a stroke, in points of the screen
    static let reach: CGFloat = 6

    var body: some View {
        GeometryReader { geometry in
            let paper = Self.paper(for: sketch, in: geometry.size)
            ZStack {
                SketchView(sketch: sketch, label: model.studio.canvasLabel(model.texts, sketch: sketch))
                Canvas { context, _ in
                    drawOverlay(in: &context, paper: paper)
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
            .onContinuousHover { phase in
                switch phase {
                case .active(let point): hover = tool == .eraser ? hit(point, paper: paper) : nil
                case .ended: hover = nil
                }
            }
            .gesture(DragGesture(minimumDistance: 0).onChanged { drag in
                changed(drag.location, paper: paper)  // (without a tool: nothing)
            }.onEnded { _ in
                ended(paper: paper)
            })
        }
        .onChange(of: editor.svg, initial: true) { _, svg in refresh(svg) }
        .onChange(of: tool) {
            hover = nil
            drawn = []
        }
    }

    /// Where the paper is in a view of `size`: the sketch scaled to fit with its shape kept (as SketchView draws it).
    static func paper(for sketch: Sketch?, in size: CGSize) -> CGRect {
        guard let sketch, sketch.width > 0, sketch.height > 0 else { return .zero }
        let scale = min(size.width / CGFloat(sketch.width), size.height / CGFloat(sketch.height))
        let (w, h) = (CGFloat(sketch.width) * scale, CGFloat(sketch.height) * scale)
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    /// The sketch, its strokes for the hit test and its viewBox – again after each change (an erased stroke changes
    /// the numbers of those after it, so the next hit of the same drag needs the new ones at once).
    private func refresh(_ svg: String) {
        sketch = try? SketchSVG.parse(svg)
        index = SketchEditing.StrokeIndex(svg: svg)
        box = SketchEditing.viewBox(svg)
    }

    /// canvas.to_sketch: a point of the view in the sketch's coordinates (its viewBox).
    private func toSketch(_ p: CGPoint, paper: CGRect) -> SketchPoint {
        SketchPoint(x: box.x + Double((p.x - paper.minX) / max(paper.width, 1)) * box.width,
                    y: box.y + Double((p.y - paper.minY) / max(paper.height, 1)) * box.height)
    }

    private func toView(_ p: SketchPoint, paper: CGRect) -> CGPoint {
        CGPoint(x: paper.minX + CGFloat((p.x - box.x) / box.width) * paper.width,
                y: paper.minY + CGFloat((p.y - box.y) / box.height) * paper.height)
    }

    /// canvas.stroke_at: the stroke under a point of the view (nil: none, or outside the paper).
    private func hit(_ point: CGPoint, paper: CGRect) -> Int? {
        guard let index, paper.contains(point) else { return nil }
        let s = toSketch(point, paper: paper)
        return index.hit(x: s.x, y: s.y, tolerance: Double(Self.reach / max(paper.width, 1)) * box.width)
    }

    private func changed(_ point: CGPoint, paper: CGRect) {
        switch tool {
        case .none: return
        case .eraser:
            if !pressed {
                pressed = true
                editor.beginErase()
            }
            if let stroke = hit(point, paper: paper) {
                editor.erase(stroke)
                refresh(editor.svg)
            }
            hover = hit(point, paper: paper)
        case .pen:
            if !pressed {
                guard paper.contains(point) else { return }  // (a stroke starts on the paper)
                pressed = true
                drawn = [point]
            } else if let last = drawn.last, abs(point.x - last.x) + abs(point.y - last.y) >= 1.5 {
                drawn.append(point)
            }
        }
    }

    private func ended(paper: CGRect) {
        defer { pressed = false }
        guard pressed else { return }
        switch tool {
        case .none: return
        case .eraser: editor.endErase()
        case .pen:
            let points = drawn.map { toSketch($0, paper: paper) }
            drawn = []
            if points.count > 1 { editor.draw(points) }
        }
    }

    private func drawOverlay(in context: inout GraphicsContext, paper: CGRect) {
        if let hover, let index, hover < index.count {
            let width = CGFloat(index.widths[hover]) * paper.width / CGFloat(box.width)
            for line in index.lines[hover] {
                var path = Path()
                path.addLines(line.map { toView($0, paper: paper) })
                context.stroke(path, with: .color(Color(hex: SketchEditing.highlight)),
                               style: StrokeStyle(lineWidth: max(width, 1.5), lineCap: .round, lineJoin: .round))
            }
        }
        if drawn.count > 1 {
            var path = Path()
            path.addLines(drawn)
            context.stroke(path, with: .color(.black), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        }
    }
}

/// The tools over the finished sketch (studio.py's edit row): eraser and pen – the one in use tinted – undo, redo and
/// back to the sketch as it was drawn. Functional layer: glass, in one container.
struct EditTools: View {
    @Environment(AppModel.self) private var model
    let editor: SketchEditor
    @Binding var tool: EditTool

    var body: some View {
        GlassEffectContainer(spacing: Spacing.spaceS) {
            HStack(spacing: Spacing.spaceS) {
                toggle(.eraser, "ui.mac.edit.eraser", "eraser", help: "ui.eraser.tip")
                    .disabled(!editor.canErase)
                toggle(.pen, "ui.mac.edit.pen", "pencil.line", help: "ui.pen.tip")
                action("ui.mac.edit.undo", "arrow.uturn.backward", enabled: editor.canUndo) { editor.undo() }
                    .keyboardShortcut("z", modifiers: .command)
                action("ui.mac.edit.redo", "arrow.uturn.forward", enabled: editor.canRedo) { editor.redo() }
                    .keyboardShortcut("z", modifiers: [.command, .shift])
                action("ui.eraser.revert", "arrow.counterclockwise", enabled: editor.isEdited) { editor.revert() }
            }
        }
    }

    @ViewBuilder
    private func toggle(_ which: EditTool, _ name: String, _ symbol: String, help: String) -> some View {
        let on = tool == which
        let button = Button(model.texts.tr(name), systemImage: symbol) { tool = on ? .none : which }
            .labelStyle(.iconOnly)
            .help(model.texts.tr(help))
            .accessibilityAddTraits(on ? .isSelected : [])
        if on {
            button.buttonStyle(.glassProminent)  // (the tool in use)
        } else {
            button.buttonStyle(.glass)
        }
    }

    private func action(_ name: String, _ symbol: String, enabled: Bool, _ run: @escaping () -> Void) -> some View {
        Button(model.texts.tr(name), systemImage: symbol, action: run)
            .labelStyle(.iconOnly)
            .help(model.texts.tr(name))
            .buttonStyle(.glass)
            .disabled(!enabled)
    }
}

/// The job's sketches below the canvas (ui.step.sketches): the one shown is marked; a click shows another to touch up.
/// Content: small sketches on paper.
struct ResultSketches: View {
    @Environment(AppModel.self) private var model
    let result: StudioResult
    @State private var parsed: [String: Sketch] = [:]

    var body: some View {
        let selected = result.selected
        let shown = result.editor?.svg
        VStack(alignment: .leading, spacing: Spacing.spaceXs) {
            Text(model.texts.tr("ui.step.sketches")).font(.caption).foregroundStyle(.secondary)
                .accessibilityAddTraits(.isHeader)
            ScrollView(.horizontal) {
                HStack(spacing: Spacing.spaceS) {
                    ForEach(Array(result.runs.enumerated()), id: \.element.id) { number, run in
                        let name = model.texts.tr("ui.mac.edit.sketch", ["n": "\(number + 1)"])
                        Button {
                            result.select(run.name)
                        } label: {
                            SketchView(sketch: parsed[run.name], label: name)
                                .frame(width: 88, height: 88)
                                .clipShape(RoundedRectangle(cornerRadius: Radius.control))
                                .overlay {
                                    RoundedRectangle(cornerRadius: Radius.control)
                                        .strokeBorder(run.name == selected ? Color.accentColor : .clear, lineWidth: 2)
                                }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(Text(verbatim: name))
                        .accessibilityAddTraits(run.name == selected ? .isSelected : [])
                    }
                }
            }
        }
        .padding(.horizontal, Spacing.spaceXl)
        .padding(.bottom, Spacing.spaceS)
        .task(id: [shown ?? ""] + result.runs.map(\.name)) {
            let runs = result.runs
            let current = (selected, shown)
            parsed = await Task.detached { () -> [String: Sketch] in
                var out: [String: Sketch] = [:]
                for run in runs {
                    let svg = run.name == current.0 ? current.1 : ResultSketches.file(run.runDir)
                    out[run.name] = svg.flatMap { try? SketchSVG.parse($0) }
                }
                return out
            }.value
        }
    }

    /// jobs.sketch_file: the run's sketch as it is shown and exported – the touched-up one if there is one.
    nonisolated static func file(_ runDir: URL) -> String? {
        for name in [JobFolder.editedFile, "best_iter.svg"] {
            if let text = try? String(contentsOf: runDir.appending(path: name), encoding: .utf8) { return text }
        }
        return nil
    }
}
