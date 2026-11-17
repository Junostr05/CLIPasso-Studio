import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// What an export writes: a sketch as it is now (touched up or not), the run it belongs to (for the photo's shape)
/// and the name its file gets.
struct ExportSource: Identifiable {
    let id = UUID()
    let svg: String
    let runDir: URL?
    let name: String

    /// A result of the gallery: its best sketch (the touched-up one if there is one) and that run's folder.
    static func best(of item: GalleryItem) -> ExportSource? {
        guard let url = item.bestSketch, let svg = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        return ExportSource(svg: svg, runDir: bestRun(of: item), name: item.name)
    }

    /// The folder of a result's best run.
    static func bestRun(of item: GalleryItem) -> URL? {
        let run = item.summary.runs.first { $0["run_name"]?.stringValue == item.summary.bestRun }?["run_dir"]?.stringValue
        return run.map { URL(filePath: $0, directoryHint: .isDirectory) }
    }
}

/// The export of a sketch (dialogs.ExportDialog): SVG, PNG or PDF – or an animation, GIF, MP4 or WebP – with the
/// stroke colour and width, the background (or none) and the paper, the frame – square, the photo's shape (when it is
/// known), cropped to the strokes with a margin – the size or the PDF's width, and for an animation what it shows (the
/// drawing process of the run or the sketch stroke by stroke), how long the drawing takes and how long the finished
/// sketch stays. It starts from the last export's choices (of this app or the studio) and keeps them for the next one.
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
    @State private var work: Task<Void, Never>?
    @State private var done = 0
    @State private var total = 0

    init(source: ExportSource, settings: AppSettings) {
        self.source = source
        let last = ExportOptions.Format(rawValue: settings["export_last_format"]?.stringValue ?? "") ?? .png
        _format = State(initialValue: last)
        _options = State(initialValue: ExportOptions(settings: settings, format: last))
        _mode = State(initialValue: SketchAnimation.Mode(rawValue: settings["export_anim_mode"]?.stringValue ?? "") ?? .process)
    }

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.export_title", ["fmt": format.title])).font(.title2.bold())
            Form {
                Section {
                    Picker(t.tr("ui.mac.export.format"), selection: $format) {
                        ForEach(ExportOptions.Format.allCases, id: \.self) { Text(verbatim: $0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Text(t.tr("ui.export_desc.\(format.rawValue)")).font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if format.animation != nil { animationSection(t) }
                Section {
                    ColorPicker(t.tr("ui.stroke_color"), selection: color(\.stroke), supportsOpacity: false)
                    Stepper(value: $options.widthScale, in: 0.1...10, step: 0.1) {
                        LabeledContent(t.tr("ui.stroke_width_scale"), value: String(format: "%.1f ×", options.widthScale))
                    }
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
                Section {
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
                    if format == .png || format.animation != nil {
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
                    .disabled(work != nil)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 480)
        .onChange(of: format) { _, new in
            if !new.allowsTransparent, options.background == nil { options.background = "#FFFFFF" }
            if new.animation != nil, options.size == 1024 { options.size = 512 }
            if new == .png, options.size == 512 { options.size = 1024 }
        }
        .onChange(of: mode) { length = defaultLength }
        .task {
            let (run, svg) = (source.runDir, source.svg)
            let found = await Task.detached { () -> (SketchFraming.PhotoFrame?, Int, Drawing) in
                (run.flatMap { SketchFraming.runFrame(runDir: $0) }, run.map { SketchAnimation.steps(runDir: $0).count } ?? 0,
                 Drawing(svg: svg, keepOrder: true))
            }.value
            photo = found.0
            if photo == nil, options.frame == .photo { options.frame = .square }
            steps = found.1
            drawing = (found.2.strokeCount, SketchAnimation.defaultDrawingLength(strokes: found.2.strokeCount, line: found.2.line))
            if steps < 2 { mode = .strokes }  // (one saved step is no process to show)
            length = defaultLength
        }
    }

    /// The animation's choices: the drawing process or stroke by stroke, the drawing's length (or one frame for
    /// every saved step), how long the sketch stays, and what that makes.
    @ViewBuilder private func animationSection(_ t: Texts) -> some View {
        Section {
            Picker(t.tr("ui.export_mode.label"), selection: $mode) {
                ForEach(SketchAnimation.Mode.allCases, id: \.self) { Text(t.tr("ui.export_mode.\($0.rawValue)")).tag($0) }
            }
            .help(t.tr("ui.export_mode.tip"))
            .disabled(steps < 2)
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
        mode == .strokes ? drawing.length : SketchAnimation.defaultProcessLength(steps)
    }

    /// _update_timing: the frame rate, the number of frames and the whole length.
    private func timing(_ t: Texts) -> String {
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

    private func phase(_ t: Texts) -> String {
        total > 0 && done < total ? t.tr("ui.export_rendering") : t.tr("ui.export_encoding", ["fmt": format.title])
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
        case .svg: .svg
        case .png: .png
        case .pdf: .pdf
        case .gif: .gif
        case .mp4: .mpeg4Movie
        case .webp: .webP
        }
    }

    /// ExportDialog._save: where (the last export's folder first), then the file – drawn off the main actor – and the
    /// choices kept.
    private func save() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [Self.contentType(format)]
        panel.nameFieldStringValue = "\(source.name).\(format.rawValue)"
        if let dir = model.settings["export_dir"]?.stringValue, !dir.isEmpty {
            panel.directoryURL = URL(filePath: dir, directoryHint: .isDirectory)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let (svg, options, photo, format, mode) = (source.svg, self.options, self.photo, self.format, self.mode)
        let title = url.deletingPathExtension().lastPathComponent
        problem = ""
        (done, total) = (0, 0)
        work = Task {
            defer { work = nil }
            do {
                if let animation = format.animation {
                    let job = AnimationJob(mode: mode, format: animation, options: options, length: length, hold: hold,
                                           svg: svg, runDir: source.runDir, photo: photo)
                    let (stream, progress) = AsyncStream.makeStream(of: (Int, Int).self)
                    let watch = Task { for await (a, b) in stream { (done, total) = (a, b) } }
                    defer { watch.cancel() }
                    _ = try await model.exportAnimation(job, to: url) { progress.yield(($0, $1)) }
                    progress.finish()
                } else {
                    let data = try await Task.detached(executorPreference: OwnThreads.shared) { () throws -> Data in
                        switch format {
                        case .png: try SketchExporter.png(svg, options: options, photo: photo)
                        case .pdf: try SketchExporter.pdf(svg, options: options, photo: photo, title: title)
                        default: Data(SketchExporter.svg(svg, options: options, photo: photo).utf8)
                        }
                    }.value
                    try data.write(to: url, options: .atomic)
                }
                model.updateSettings {
                    options.remember(in: &$0, format: format)
                    if format.animation != nil, steps > 1 { $0["export_anim_mode"] = .string(mode.rawValue) }
                    $0["export_dir"] = .string(url.deletingLastPathComponent().path)
                }
                dismiss()
            } catch is CancellationError {
                dismiss()
            } catch let error as AnimationError {
                problem = model.texts.tr("ui.err.\(error.code)")
            } catch {
                problem = String(describing: error)
            }
        }
    }
}
