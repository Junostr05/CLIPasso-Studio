import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The tool on a finished sketch (studio.py: the eraser and the pen; one at a time).
enum EditTool: Equatable {
    case none, eraser, pen
}


/// A finished job on the studio's canvas: its sketch, which can be touched up with the tools above it, and below it
/// the job's other sketches to choose from – for SceneSketch the matrix of its cells instead (studio.py, canvas.py).
struct ResultCanvas: View {
    @Environment(AppModel.self) private var model
    let result: StudioResult
    @State private var tool = EditTool.none
    /// the canvas's mode: "sketch", a view of JobViews, or "matrix"
    @State private var view = "sketch"
    @State private var exporting: ExportSource?
    @State private var printing: PrintRequest?
    /// the edit bar below the sketch (saved steps or Simplify; nil: closed)
    @State private var bar: EditBarModel?
    @State private var noSteps = false

    var body: some View {
        ZStack {
            if view == "matrix", let matrix = result.matrix {
                MatrixGrid(result: result, matrix: matrix) { view = "sketch" }
                    .padding(Spacing.spaceXl)
            } else if view != "sketch" {
                ViewPicture(kind: view, sketch: result.editor.flatMap { try? SketchSVG.parse($0.svg) })
                    .padding(Spacing.spaceXl)
            } else if let bar {
                SketchView(sketch: try? SketchSVG.parse(bar.preview),
                           label: model.studio.canvasLabel(model.texts, sketch: try? SketchSVG.parse(bar.preview)))
                    .padding(Spacing.spaceXl)
            } else if let editor = result.editor {
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
            HStack(spacing: Spacing.spaceM) {
                ViewModePicker(mode: $view, matrix: result.matrix != nil)
                if view == "sketch", bar == nil, let editor = result.editor {
                    EditTools(editor: editor, tool: $tool) {
                        exporting = ExportSource(svg: editor.svg, runDir: editor.runDir, name: name, jobDir: result.jobDir,
                                                 method: result.method, runs: result.runs.count)
                    } printSketch: {
                        printing = request(editor)
                    } copySketch: {
                        copy(editor)
                    } steps: {
                        tool = .none
                        bar = model.openSteps(editor)
                        noSteps = bar == nil
                    } simplify: {
                        tool = .none
                        bar = model.openSimplify(editor)
                    }
                }
            }
            .padding(.top, Spacing.spaceS)
        }
        .safeAreaInset(edge: .bottom) {
            if let bar, let editor = result.editor {
                EditBarView(bar: bar) {
                    editor.take(bar.preview)
                    self.bar = nil
                    NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested,
                                         userInfo: [.announcement: model.texts.tr("ui.edit_bar.taken"),
                                                    .priority: NSAccessibilityPriorityLevel.medium.rawValue])
                } close: {
                    self.bar = nil
                }
            } else if result.matrix == nil, result.runs.count > 1 {
                ResultSketches(result: result)
            }
        }
        .alert(model.texts.tr("ui.edit_bar.no_steps"), isPresented: $noSteps) {}
        .onChange(of: view) {
            tool = .none
            bar = nil
        }
        .onChange(of: result.selected) { bar = nil }
        .sheet(item: $exporting) { ExportSheet(source: $0, settings: model.settings) }
        .sheet(item: $printing) { PrintSheet(request: $0, settings: model.settings) }
        .focusedSceneValue(\.printAction, view == "sketch" ? result.editor.map { editor in
            PrintAction { printing = request(editor) }
        } : nil)
        .focusedSceneValue(\.copySketchAction, view == "sketch" ? result.editor.map { editor in
            CopySketchAction { copy(editor) }
        } : nil)
        .onChange(of: result.editor?.canErase ?? false) { _, can in
            if !can, tool == .eraser { tool = .none }
        }
        .onChange(of: ScreenshotMode.requests.printSheet) { _, open in
            printing = open ? result.editor.map(request) : nil
        }
    }

    /// The image's name (the files' names).
    private var name: String { model.studio.image?.deletingPathExtension().lastPathComponent ?? "sketch" }

    /// studio.print_sketch: the sketch as it is now, named after its run.
    /// ⇧⌘C and the toolbar's Copy: the sketch as it is now on the clipboard (a beep when it cannot be made).
    private func copy(_ editor: SketchEditor) {
        let (svg, run) = (editor.svg, editor.runDir)
        Task {
            do {
                try await SketchClipboard.copy(svg: svg, runDir: run, model: model)
            } catch {
                NSSound.beep()
            }
        }
    }

    private func request(_ editor: SketchEditor) -> PrintRequest {
        PrintRequest(entries: [PrintEntry(svg: editor.svg, file: nil, runDir: editor.runDir,
                                          caption: editor.runDir.lastPathComponent)], name: name)
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
    /// the sketch in the canvas's brush style (the engine's; nil: plain) – shown while no tool is in the hand
    @State private var styled: Sketch?
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
                SketchView(sketch: tool == .none ? styled ?? sketch : sketch,
                           label: model.studio.canvasLabel(model.texts, sketch: sketch))
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
        .task(id: [editor.svg, model.canvasStyle]) {
            let stylist = model.stylist(model.canvasStyle)
            guard !stylist.isPlain else {
                styled = nil
                return
            }
            let svg = editor.svg
            let drawn = try? await Task.detached(executorPreference: OwnThreads.shared) {
                try SketchSVG.parse(stylist(svg))
            }.value
            if !Task.isCancelled { styled = drawn }  // (no engine, no answer: the plain sketch)
        }
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
/// back to the sketch as it was drawn, and the export and print of the sketch as it is now. Functional layer: glass, in
/// one container.
struct EditTools: View {
    @Environment(AppModel.self) private var model
    let editor: SketchEditor
    @Binding var tool: EditTool
    let export: () -> Void
    let printSketch: () -> Void
    let copySketch: () -> Void
    /// the edit bar: the saved steps, Simplify
    let steps: () -> Void
    let simplify: () -> Void

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
                action("ui.edit_bar.history", "clock.arrow.circlepath", help: "ui.edit_bar.history_tip", enabled: true,
                       steps)
                Button(model.texts.tr("ui.edit_bar.simplify"), systemImage: "slider.horizontal.3", action: simplify)
                    .labelStyle(.titleAndIcon)  // (with its name: easy to find)
                    .help(model.texts.tr("ui.edit_bar.simplify_tip"))
                    .buttonStyle(.glass)
                    .disabled(!editor.canErase)
                action("ui.export", "square.and.arrow.up", enabled: true, export)
                    .keyboardShortcut("e", modifiers: .command)
                action("ui.print.button", "printer", help: "ui.print.tip", enabled: true, printSketch)  // (⌘P: the menu's)
                action("ui.copy", "doc.on.doc", help: "ui.copy_tip", enabled: true, copySketch)  // (⇧⌘C: the menu's)
                styleMenu
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

    /// The brush style the studio shows its sketches in (studio.set_canvas_style): only the view – the sketch is
    /// touched up and saved plain.
    private var styleMenu: some View {
        Menu {
            Picker(model.texts.tr("ui.brush.label"), selection: Binding(get: { model.canvasStyle },
                                                                         set: { model.setCanvasStyle($0) })) {
                ForEach(model.brushStyles, id: \.self) { Text(model.texts.tr("ui.brush.\($0)")).tag($0) }
            }
            .pickerStyle(.inline)
        } label: {
            Label(model.texts.tr("ui.brush.label"), systemImage: "paintbrush.pointed")
        }
        .labelStyle(.iconOnly)
        .menuStyle(.button)
        .menuIndicator(.hidden)
        .buttonStyle(.glass)
        .help(model.texts.tr("ui.brush.tip"))
    }

    private func action(_ name: String, _ symbol: String, help: String? = nil, enabled: Bool,
                        _ run: @escaping () -> Void) -> some View
    {
        Button(model.texts.tr(name), systemImage: symbol, action: run)
            .labelStyle(.iconOnly)
            .help(model.texts.tr(help ?? name))
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
        .confirmationDialog(model.texts.tr("ui.matrix.rerun"), isPresented: Binding(
            get: { rerun != nil }, set: { if !$0 { rerun = nil } })) {
            Button(model.texts.tr("ui.matrix.rerun")) { if let rerun { doRerun(rerun.cell) } }
            Button(model.texts.tr("ui.cancel"), role: .cancel) {}
        } message: {
            if let rerun {
                let (layer, level) = SceneMatrix.split(rerun.cell)
                Text(model.texts.tr("ui.matrix.rerun_q", ["layer": String(layer), "level": String(level),
                                                          "later": rerun.later.map(String.init).joined(separator: ", ")]))
            }
        }
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

/// SceneSketch's matrix of the job (canvas.MatrixView): one column per fidelity layer, one row per simplicity level,
/// each cell its sketch on paper – the shown one with the accent's edge, the best with the success colour's (as the
/// studio marks them); a cell not computed is an empty frame. A click shows a cell (the one to touch up), a double
/// click opens it as the sketch. Content.
struct MatrixGrid: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var scheme
    let result: StudioResult
    let matrix: SceneMatrix
    let open: () -> Void
    @State private var parsed: [Int: Sketch] = [:]
    /// the cell to compute again, with the later levels it takes along (the question before)
    @State private var rerun: (cell: Int, later: [Int])?
    @State private var note = ""

    static let side: CGFloat = 36  // (room for the levels' numbers)

    /// rerun_scene_cell: asked first when later levels go along.
    private func askRerun(_ cell: Int) {
        Task {
            guard let later = await model.sceneCellLater(cell) else { return NSSound.beep() }
            if later.isEmpty { doRerun(cell) } else { rerun = (cell, later) }
        }
    }

    private func doRerun(_ cell: Int) {
        Task {
            guard let n = await model.rerunSceneCell(cell) else { return NSSound.beep() }
            note = model.texts.tr("ui.matrix.rerun_queued", ["n": String(n)])
        }
    }

    var body: some View {
        let selected = result.selected
        let best = result.bestRun
        let shown = result.editor?.svg
        VStack(spacing: Spacing.spaceS) {
            Text(verbatim: "\(model.texts.tr("ui.matrix.fidelity")) →   \(model.texts.tr("ui.matrix.simplicity")) ↓")
                .font(.caption)
                .foregroundStyle(.secondary)
            if !note.isEmpty { Text(verbatim: note).font(.callout).foregroundStyle(.secondary) }
            GeometryReader { geometry in
                let gap = Spacing.spaceS
                let columns = CGFloat(matrix.layers.count), rows = CGFloat(matrix.levels.count)
                let size = max(24, min((geometry.size.width - Self.side - gap * columns) / columns,
                                       (geometry.size.height - 24 - gap * rows) / rows))
                Grid(horizontalSpacing: gap, verticalSpacing: gap) {
                    GridRow {
                        Color.clear.frame(width: Self.side, height: 1)
                        ForEach(matrix.layers, id: \.self) { layer in
                            Text(verbatim: "L\(layer)").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(matrix.levels, id: \.self) { level in
                        GridRow {
                            Text(verbatim: "\(level)").font(.caption).foregroundStyle(.secondary)
                                .frame(width: Self.side, alignment: .trailing)
                            ForEach(matrix.layers, id: \.self) { layer in
                                cell(layer: layer, level: level, size: size, selected: selected, best: best)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: [shown ?? ""] + result.runs.map(\.name)) {
            let runs = result.runs
            let current = (selected, shown)
            parsed = await Task.detached { () -> [Int: Sketch] in
                var out: [Int: Sketch] = [:]
                for run in runs {
                    let svg = run.name == current.0 ? current.1 : ResultSketches.file(run.runDir)
                    out[run.seed] = svg.flatMap { try? SketchSVG.parse($0) }
                }
                return out
            }.value
        }
    }

    @ViewBuilder
    private func cell(layer: Int, level: Int, size: CGFloat, selected: String, best: String) -> some View {
        let id = SceneMatrix.cell(layer: layer, level: level)
        if let run = result.run(cell: id) {
            let isSelected = run.name == selected, isBest = run.name == best
            let name = model.texts.tr("ui.mac.matrix.cell", ["layer": "\(layer)", "level": "\(level)"])
            let success = Color(hex: (scheme == .dark ? Palette.dark : Palette.light).success)
            Button {
                result.select(run.name)
            } label: {
                SketchView(sketch: parsed[id], label: name)
                    .frame(width: size, height: size)
                    .overlay {
                        RoundedRectangle(cornerRadius: Radius.control)
                            .strokeBorder(isSelected ? Color.accentColor : isBest ? success : .clear, lineWidth: 2)
                    }
            }
            .buttonStyle(.plain)
            .simultaneousGesture(TapGesture(count: 2).onEnded {
                result.select(run.name)
                open()
            })
            .contextMenu {
                Button(model.texts.tr("ui.matrix.rerun"), systemImage: "arrow.clockwise") { askRerun(id) }
            }
            .accessibilityLabel(Text(verbatim: name))
            .accessibilityValue(Text(verbatim: isBest ? model.texts.tr("ui.compare.best") : ""))
            .accessibilityAddTraits(isSelected ? .isSelected : [])
            .accessibilityAction(named: Text(model.texts.tr("ui.mode.sketch"))) {
                result.select(run.name)
                open()
            }
        } else {
            RoundedRectangle(cornerRadius: Radius.control)
                .strokeBorder(.secondary.opacity(0.4), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                .frame(width: size, height: size)
                .accessibilityHidden(true)
        }
    }
}

/// The edit bar (widgets/edit_bar.py): its title and line, Cancel and Take; the slider; the note below it. Content
/// below the canvas: a plain bar, no glass.
struct EditBarView: View {
    @Environment(AppModel.self) private var model
    @Bindable var bar: EditBarModel
    let apply: () -> Void
    let close: () -> Void

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceXs) {
            HStack(spacing: Spacing.spaceM) {
                Text(verbatim: bar.title(t)).font(.headline)
                Text(verbatim: bar.info(t)).foregroundStyle(.secondary).monospacedDigit()
                if bar.measuring { ProgressView().controlSize(.small) }
                Spacer()
                Button(t.tr("ui.cancel"), action: close)
                    .keyboardShortcut(.cancelAction)
                Button(bar.applyLabel(t), systemImage: "checkmark", action: apply)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(!bar.canApply)
            }
            Slider(value: Binding(get: { Double(bar.value) }, set: { bar.value = Int($0.rounded()) }),
                   in: Double(bar.range.lowerBound) ... Double(max(bar.range.upperBound, bar.range.lowerBound + 1)),
                   step: 1)
                .disabled(!bar.sliderEnabled)
                .accessibilityLabel(bar.title(t))
                .accessibilityValue(bar.info(t))
            Text(verbatim: bar.note(t)).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, Spacing.spaceXl)
        .padding(.vertical, Spacing.spaceM)
        .background(.bar)
    }
}
