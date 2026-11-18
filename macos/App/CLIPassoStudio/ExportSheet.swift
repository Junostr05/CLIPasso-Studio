import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// What an export writes: a sketch as it is now (touched up or not), the run it belongs to (for the photo's shape),
/// the name its file gets – and its job: SceneSketch offers the scene in two layers and the whole matrix as well.
struct ExportSource: Identifiable {
    let id = UUID()
    let svg: String
    let runDir: URL?
    let name: String
    var jobDir: URL?
    /// the job's method ("scenesketch" …)
    var method = ""
    /// the job's runs
    var runs = 0

    /// A result of the gallery: its best sketch (the touched-up one if there is one) and that run's folder.
    static func best(of item: GalleryItem) -> ExportSource? {
        guard let url = item.bestSketch, let svg = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        return ExportSource(svg: svg, runDir: bestRun(of: item), name: item.name, jobDir: item.jobDir, method: item.method,
                            runs: item.summary.runs.count)
    }

    /// The folder of a result's best run.
    static func bestRun(of item: GalleryItem) -> URL? {
        let run = item.summary.runs.first { $0["run_name"]?.stringValue == item.summary.bestRun }?["run_dir"]?.stringValue
        return run.map { URL(filePath: $0, directoryHint: .isDirectory) }
    }

    var isScene: Bool { method == "scenesketch" }

    /// The formats the sheet lists (studio.py: the layered SVG and the matrix for SceneSketch only).
    var formats: [ExportOptions.Format] {
        ExportOptions.Format.allCases.filter { isScene || ($0 != .svglayers && $0 != .matrix) }
    }

    /// _matrix_exportable: a SceneSketch job of more than one cell, with its job.json.
    var matrixReady: Bool {
        guard isScene, runs > 1, let jobDir else { return false }
        return FileManager.default.fileExists(atPath: jobDir.appending(path: "job.json").path)
    }

    /// The strokes in the file (_stroke_count: its paths).
    var paths: Int { svg.components(separatedBy: "<path").count - 1 }
}

/// The export of a sketch (export_center.ExportCenter with dialogs.ExportDialog inside): a picture – SVG, PNG, PDF,
/// the plotter's SVG in one layer, a SceneSketch scene in two layers or its whole matrix as a ZIP file – or an
/// animation – GIF, MP4, WebP, or the sketch drawing itself in a browser or an app: animated SVG, Lottie, a web page.
/// The options are the format's: the stroke colour and width, the background (or none) and the paper, the frame –
/// square, the photo's shape (when it is known), cropped to the strokes with a margin – the size or the PDF's width,
/// and for an animation what it shows (the drawing process of the run or the sketch stroke by stroke), how long the
/// drawing takes and how long the finished sketch stays. It starts from the last export's choices (of this app or the
/// studio) and keeps them for the next one.
struct ExportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let source: ExportSource
    @State private var format: ExportOptions.Format
    @State private var options: ExportOptions
    @State private var photo: SketchFraming.PhotoFrame?
    @State private var problem = ""
    // the animation: its choices, what the run and the sketch offer, and the export while it runs
    @State private var mode: SketchAnimation.Mode
    @State private var length = 2.0
    @State private var hold = 1.0
    @State private var steps = 0
    @State private var drawing: (strokes: Int, length: Double) = (0, 2)
    /// the shown cell has its object layer (scene_layers.available)
    @State private var layers = false
    @State private var work: Task<Void, Never>?
    @State private var done = 0
    @State private var total = 0

    init(source: ExportSource, settings: AppSettings) {
        self.source = source
        var last = ExportOptions.Format(rawValue: settings["export_last_format"]?.stringValue ?? "") ?? .png
        if !source.formats.contains(last) || (last == .matrix && !source.matrixReady) { last = .png }
        _format = State(initialValue: last)
        _options = State(initialValue: ExportOptions(settings: settings, format: last))
        _mode = State(initialValue: SketchAnimation.Mode(rawValue: settings["export_anim_mode"]?.stringValue ?? "") ?? .process)
    }

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(heading(t)).font(.title2.bold())
            Form {
                Section {
                    formatPicker(t)
                    Text(t.tr("ui.export_desc.\(format.rawValue)")).font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if format.animation != nil || format.drawnElsewhere { animationSection(t) }
                lookSection(t)
                shapeSection(t)
            }
            .formStyle(.grouped)
            .disabled(work != nil)
            if work != nil {
                VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                    Text(phase(t)).font(.callout).foregroundStyle(.secondary)
                    if total > 0 { ProgressView(value: Double(done), total: Double(total)) } else { ProgressView() }
                }
            }
            if !problem.isEmpty {
                Text(verbatim: problem).font(.callout).foregroundStyle(Color(hex: Palette.light.danger))
            }
            HStack {
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { cancel() }
                    .keyboardShortcut(.cancelAction)
                Button(t.tr("ui.save_as"), systemImage: "square.and.arrow.down") { save() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(work != nil || !available(format))
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 480)
        .onChange(of: format) { old, new in
            if !new.allowsTransparent, options.background == nil { options.background = "#FFFFFF" }
            // (the size the studio starts a format from: 1024 px for pictures, 512 for animations)
            let size = new == .png || new == .matrix ? 1024 : 512
            if new.hasSize, options.size == (size == 1024 ? 512 : 1024) { options.size = size }
            if drawn(old) != drawn(new) { length = defaultLength }
        }
        .onChange(of: mode) { length = defaultLength }
        .task {
            if !model.brushStyles.contains(options.style) { options.style = "plain" }
            let (run, svg) = (source.runDir, source.svg)
            let found = await Task.detached { () -> (SketchFraming.PhotoFrame?, Int, Drawing, Bool) in
                (run.flatMap { SketchFraming.runFrame(runDir: $0) }, run.map { SketchAnimation.steps(runDir: $0).count } ?? 0,
                 Drawing(svg: svg, keepOrder: true), SketchFormats.objectStrokes(runDir: run) != nil)
            }.value
            photo = found.0
            if photo == nil, options.frame == .photo { options.frame = .square }
            steps = found.1
            drawing = (found.2.strokeCount, SketchAnimation.defaultDrawingLength(strokes: found.2.strokeCount, line: found.2.line))
            layers = found.3
            if steps < 2 { mode = .strokes }  // (one saved step is no process to show)
            length = defaultLength
        }
    }

    /// The formats in the export centre's groups – a picture or an animation; what the job cannot give is shown but
    /// cannot be chosen (the scene's layers before the cell's object layer exists, the matrix of a single cell).
    private func formatPicker(_ t: Texts) -> some View {
        Picker(t.tr("ui.mac.export.format"), selection: $format) {
            ForEach(["image", "animation"], id: \.self) { group in
                Section(t.tr("ui.export_center.group_\(group)")) {
                    ForEach(listed(group), id: \.self) { format in
                        Text(verbatim: title(format, t)).tag(format).selectionDisabled(!available(format))
                    }
                }
            }
        }
        .pickerStyle(.menu)
    }

    /// The formats of a group the sheet lists.
    private func listed(_ group: String) -> [ExportOptions.Format] {
        let formats = group == "image" ? ExportOptions.Format.pictures : ExportOptions.Format.animations
        return formats.filter { source.formats.contains($0) }
    }

    /// Whether the format is drawn in the brush style (the plotter's SVG and Lottie stay plain lines).
    private func styled(_ format: ExportOptions.Format) -> Bool { format != .svg1 && format != .lottie }

    /// The strokes and the ground: colour, width, brush style, background or none, the paper (the plotter's SVG:
    /// lines only).
    @ViewBuilder private func lookSection(_ t: Texts) -> some View {
        Section {
            ColorPicker(t.tr("ui.stroke_color"), selection: color(\.stroke), supportsOpacity: false)
            Stepper(value: $options.widthScale, in: 0.1...10, step: 0.1) {
                LabeledContent(t.tr("ui.stroke_width_scale"), value: String(format: "%.1f ×", options.widthScale))
            }
            if styled(format) {
                Picker(t.tr("ui.brush.label"), selection: $options.style) {
                    ForEach(model.brushStyles, id: \.self) { Text(t.tr("ui.brush.\($0)")).tag($0) }
                }
                .help(t.tr("ui.brush.tip"))
            }
            if format != .svg1 {
                if format.allowsTransparent {
                    Toggle(t.tr("ui.transparent"), isOn: Binding(get: { options.background == nil },
                                                               set: { setBackground($0 ? nil : "#FFFFFF") }))
                }
                if options.background != nil {
                    ColorPicker(t.tr("ui.background"), selection: background, supportsOpacity: false)
                }
                PaperChoice(paper: $options.paper) { kind in
                    (options.background, options.stroke) = Paper.colours(kind: kind, background: options.background,
                                                                         stroke: options.stroke)
                }
            }
        }
    }

    /// The picture's shape (not for the matrix: its cells keep theirs), its size or the PDF's width.
    @ViewBuilder private func shapeSection(_ t: Texts) -> some View {
        Section {
            if format != .matrix {
                Picker(t.tr("ui.frame.label"), selection: $options.frame) {
                    ForEach(SketchFraming.Mode.allCases, id: \.self) { mode in
                        Text(t.tr("ui.frame.\(mode.rawValue)")).tag(mode)
                            .selectionDisabled(mode == .photo && photo == nil)  // (the photo's shape is not known)
                    }
                }
                .help(t.tr("ui.frame.tip"))
                if options.frame == .content {
                    Stepper(value: $options.margin, in: 0...50) {
                        LabeledContent(t.tr("ui.frame.margin"), value: "\(options.margin) %")
                    }
                    .help(t.tr("ui.frame.margin_tip"))
                }
            }
            if format.hasSize {
                Stepper(value: $options.size, in: 64...8192, step: 128) {
                    LabeledContent(t.tr("ui.size"), value: "\(options.size) px")
                }
                .help(t.tr("ui.size_longest"))
            }
            if format == .pdf {
                Stepper(value: $options.pdfWidth, in: 2...200, step: 1) {
                    LabeledContent(t.tr("ui.export_pdf_width"), value: String(format: "%.1f cm", options.pdfWidth))
                }
            }
        }
    }

    /// The sheet's heading (the matrix has its own).
    private func heading(_ t: Texts) -> String {
        format == .matrix ? t.tr("ui.export_matrix_title") : t.tr("ui.export_title", ["fmt": title(format, t)])
    }

    /// A format's name as the studio's dialog writes it.
    private func title(_ format: ExportOptions.Format, _ t: Texts) -> String {
        switch format {
        case .svg1: t.tr("ui.export_svg1")
        case .svglayers: t.tr("ui.export_svglayers")
        case .matrix: t.tr("ui.export_matrix")
        case .svganim: t.tr("ui.export_svganim")
        case .html: t.tr("ui.export_html")
        default: format.title
        }
    }

    /// Whether the job can give the format now.
    private func available(_ format: ExportOptions.Format) -> Bool {
        switch format {
        case .svglayers: layers
        case .matrix: source.matrixReady
        default: true
        }
    }

    /// The sketch drawn stroke by stroke (export._drawing): always for the formats drawn in a browser or an app.
    private func drawn(_ format: ExportOptions.Format) -> Bool { format.drawnElsewhere || mode == .strokes }

    /// The animation's choices: the drawing process or stroke by stroke (the formats drawn elsewhere: always the
    /// strokes), the drawing's length (or one frame for every saved step), how long the sketch stays, and what that
    /// makes.
    @ViewBuilder private func animationSection(_ t: Texts) -> some View {
        Section {
            if format.animation != nil {
                Picker(t.tr("ui.export_mode.label"), selection: $mode) {
                    ForEach(SketchAnimation.Mode.allCases, id: \.self) { Text(t.tr("ui.export_mode.\($0.rawValue)")).tag($0) }
                }
                .help(t.tr("ui.export_mode.tip"))
                .disabled(steps < 2)
            }
            Stepper(value: $length, in: 0.5...300, step: 0.5) {
                LabeledContent(t.tr("ui.export_length"), value: String(format: "%.1f s", length))
            }
            if mode == .process, steps > 1, let animation = format.animation {
                Button(t.tr("ui.export_every_step")) {
                    length = min(300, SketchAnimation.everyStepLength(steps, format: animation))
                }
                .help(t.tr("ui.export_every_step_tip"))
            }
            Stepper(value: $hold, in: 0...10, step: 0.5) {
                LabeledContent(t.tr("ui.export_hold"), value: String(format: "%.1f s", hold))
            }
            Text(timing(t)).font(.caption).foregroundStyle(.secondary)
        }
    }

    private var defaultLength: Double {
        drawn(format) ? drawing.length : SketchAnimation.defaultProcessLength(steps)
    }

    /// _update_timing: the frame rate, the number of frames and the whole length – for a drawing in a browser or an
    /// app its strokes and how often it repeats.
    private func timing(_ t: Texts) -> String {
        if format.drawnElsewhere {
            return t.tr("ui.export_timing_svg", ["strokes": "\(source.paths)", "total": String(format: "%.1f", length + hold)])
        }
        guard let animation = format.animation else { return "" }
        let frames = mode == .strokes ? max(2, Int((length * Double(SketchAnimation.drawStepsPerSecond)).rounded(.toNearestOrEven)))
            : steps
        let plan = SketchAnimation.plan(frames, length: length, hold: hold, format: animation, size: options.size)
        guard !plan.frames.isEmpty else { return "" }
        let fps = animation == .mp4 ? Double(SketchAnimation.mp4FPS) : Double(plan.frames.count) / length
        return t.tr("ui.export_timing", ["fps": String(format: fps >= 10 ? "%.0f" : "%.1f", fps),
                                         "frames": "\(plan.frames.count)",
                                         "total": String(format: "%.1f", plan.durations.reduce(0, +) / 1000)])
    }

    /// While the frames are drawn – then while the file is written ("WebP", "GIF", "MP4", "ZIP").
    private func phase(_ t: Texts) -> String {
        let name = format == .webp ? "WebP" : format.fileExtension.uppercased()
        return total > 0 && done < total ? t.tr("ui.export_rendering") : t.tr("ui.export_encoding", ["fmt": name])
    }

    private func color(_ key: WritableKeyPath<ExportOptions, String>) -> Binding<Color> {
        Binding(get: { Color(hex: options[keyPath: key]) }, set: { options[keyPath: key] = Self.hex($0) })
    }

    private var background: Binding<Color> {
        Binding(get: { Color(hex: options.background ?? "#FFFFFF") }, set: { setBackground(Self.hex($0)) })
    }

    /// A new background (nil: transparent) – on a dark one black strokes turn light, and back (paper_colours).
    private func setBackground(_ colour: String?) {
        (options.background, options.stroke) = Paper.colours(kind: nil, background: colour, stroke: options.stroke)
    }

    /// "#RRGGBB" of a colour chosen in the colour panel (in sRGB).
    static func hex(_ color: Color) -> String {
        guard let c = NSColor(color).usingColorSpace(.sRGB) else { return "#000000" }
        func byte(_ v: CGFloat) -> Int { Int((min(max(v, 0), 1) * 255).rounded()) }
        return String(format: "#%02X%02X%02X", byte(c.redComponent), byte(c.greenComponent), byte(c.blueComponent))
    }

    /// ExportDialog.reject: while an export runs, cancel stops it (between frames) and the sheet closes then.
    private func cancel() {
        if let work { work.cancel() } else { dismiss() }
    }

    private static func contentType(_ format: ExportOptions.Format) -> UTType {
        switch format {
        case .svg, .svg1, .svglayers, .svganim: .svg
        case .png: .png
        case .pdf: .pdf
        case .matrix: .zip
        case .gif: .gif
        case .mp4: .mpeg4Movie
        case .webp: .webP
        case .lottie: .json
        case .html: .html
        }
    }

    /// ExportDialog._save: where (the last export's folder first, the name with the format's suffix), then the file –
    /// made off the main actor – and the choices kept.
    private func save() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [Self.contentType(format)]
        panel.nameFieldStringValue = "\(source.name)\(format.suffix).\(format.fileExtension)"
        if let dir = model.settings["export_dir"]?.stringValue, !dir.isEmpty {
            panel.directoryURL = URL(filePath: dir, directoryHint: .isDirectory)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let (svg, options, photo, format, mode) = (source.svg, self.options, self.photo, self.format, self.mode)
        let (runDir, jobDir, length, hold) = (source.runDir, source.jobDir, self.length, self.hold)
        let title = url.deletingPathExtension().lastPathComponent
        let labels = (model.texts.tr("ui.layer.background"), model.texts.tr("ui.layer.object"))
        let stylist = styled(format) ? model.stylist(options.style) : .plain
        problem = ""
        (done, total) = (0, 0)
        work = Task {
            defer { work = nil }
            let (stream, progress) = AsyncStream.makeStream(of: (Int, Int).self)
            let watch = Task { for await (a, b) in stream { (done, total) = (a, b) } }
            defer { watch.cancel() }
            do {
                let request = ExportRequest(format: format, svg: svg, runDir: runDir, jobDir: jobDir, photo: photo,
                                            options: options, mode: mode, length: length, hold: hold, title: title,
                                            labels: labels, stylist: stylist)
                try await model.runExport(request, to: url) { progress.yield(($0, $1)) }
                progress.finish()
                model.updateSettings {
                    options.remember(in: &$0, format: format)
                    if format.animation != nil, steps > 1 { $0["export_anim_mode"] = .string(mode.rawValue) }
                    $0["export_dir"] = .string(url.deletingLastPathComponent().path)
                }
                dismiss()
            } catch is CancellationError {
                dismiss()
            } catch let error as ExportError {
                problem = model.texts.tr("ui.err.\(error.code)")
            } catch {
                problem = String(describing: error)
            }
        }
    }
}
