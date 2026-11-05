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

/// The export of a sketch (dialogs.ExportDialog): SVG, PNG or PDF with the stroke colour and width, the background
/// (or none) and the paper, the frame – square, the photo's shape (when it is known), cropped to the strokes with a
/// margin – and the PNG's size or the PDF's width. It starts from the last export's choices (of this app or the studio) and keeps
/// them for the next one.
struct ExportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let source: ExportSource
    @State private var format: ExportOptions.Format
    @State private var options: ExportOptions
    @State private var photo: SketchFraming.PhotoFrame?
    @State private var saving = false
    @State private var problem = ""

    init(source: ExportSource, settings: AppSettings) {
        self.source = source
        let last = ExportOptions.Format(rawValue: settings["export_last_format"]?.stringValue ?? "") ?? .png
        _format = State(initialValue: last)
        _options = State(initialValue: ExportOptions(settings: settings, format: last))
    }

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.export_title", ["fmt": format.rawValue.uppercased()])).font(.title2.bold())
            Form {
                Section {
                    Picker(t.tr("ui.mac.export.format"), selection: $format) {
                        ForEach(ExportOptions.Format.allCases, id: \.self) { Text(verbatim: $0.rawValue.uppercased()).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Text(t.tr("ui.export_desc.\(format.rawValue)")).font(.callout).foregroundStyle(.secondary)
                }
                Section {
                    ColorPicker(t.tr("ui.stroke_color"), selection: color(\.stroke), supportsOpacity: false)
                    Stepper(value: $options.widthScale, in: 0.1...10, step: 0.1) {
                        LabeledContent(t.tr("ui.stroke_width_scale"), value: String(format: "%.1f ×", options.widthScale))
                    }
                    Toggle(t.tr("ui.transparent"), isOn: Binding(get: { options.background == nil },
                                                               set: { setBackground($0 ? nil : "#FFFFFF") }))
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
                    if format == .png {
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
            if !problem.isEmpty {
                Text(verbatim: problem).font(.callout).foregroundStyle(Color(hex: Palette.light.danger))
            }
            HStack {
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(t.tr("ui.save_as"), systemImage: "square.and.arrow.down") { Task { await save() } }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(saving)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 460)
        .task {
            let run = source.runDir
            photo = await Task.detached { run.flatMap { SketchFraming.runFrame(runDir: $0) } }.value
            if photo == nil, options.frame == .photo { options.frame = .square }
        }
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

    /// ExportDialog._save: where (the last export's folder first), then the file – drawn off the main actor – and the
    /// choices kept.
    private func save() async {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [format == .svg ? .svg : format == .png ? .png : .pdf]
        panel.nameFieldStringValue = "\(source.name).\(format.rawValue)"
        if let dir = model.settings["export_dir"]?.stringValue, !dir.isEmpty {
            panel.directoryURL = URL(filePath: dir, directoryHint: .isDirectory)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        saving = true
        defer { saving = false }
        let (svg, options, photo, format) = (source.svg, self.options, self.photo, self.format)
        let title = url.deletingPathExtension().lastPathComponent
        do {
            let data = try await Task.detached { () throws -> Data in
                switch format {
                case .svg: Data(SketchExporter.svg(svg, options: options, photo: photo).utf8)
                case .png: try SketchExporter.png(svg, options: options, photo: photo)
                case .pdf: try SketchExporter.pdf(svg, options: options, photo: photo, title: title)
                }
            }.value
            try data.write(to: url, options: .atomic)
            model.updateSettings {
                options.remember(in: &$0, format: format)
                $0["export_dir"] = .string(url.deletingLastPathComponent().path)
            }
            dismiss()
        } catch {
            problem = String(describing: error)
        }
    }
}
