import AppKit
import PDFKit
import StudioApp
import StudioCore
import SwiftUI

/// A sketch to print: its SVG as it is now (the touched-up one, from the studio) or its file (from the gallery), the
/// run it belongs to (for the photo's shape) and the caption under it.
nonisolated struct PrintEntry: Sendable {
    let svg: String?
    let file: URL?
    let runDir: URL?
    let caption: String

    /// A result of the gallery: its best sketch (the touched-up one if there is one), named as in the gallery.
    @MainActor static func best(of item: GalleryItem) -> PrintEntry? {
        guard let file = item.bestSketch else { return nil }
        return PrintEntry(svg: nil, file: file, runDir: ExportSource.bestRun(of: item), caption: item.name)
    }

    /// The sketch read and its run's frame (off the main actor: a gallery's files).
    nonisolated func item() -> PrintItem? {
        guard let svg = svg ?? file.flatMap({ try? String(contentsOf: $0, encoding: .utf8) }) else { return nil }
        return PrintItem(svg: svg, caption: caption, photo: runDir.flatMap { SketchFraming.runFrame(runDir: $0) })
    }
}

/// What to print: the sketches in their order and the PDF's name when the layout has no heading.
struct PrintRequest: Identifiable {
    let id = UUID()
    let entries: [PrintEntry]
    let name: String
}

/// "Print …" of the File menu (⌘P): what the page in front prints – the studio's sketch, the gallery's results.
struct PrintAction {
    let run: () -> Void
}

extension FocusedValues {
    @Entry var printAction: PrintAction?
}

/// File ▸ Drucken … (⌘P) in place of the system's print items: the page in front says what it prints.
struct PrintCommands: Commands {
    let texts: Texts?
    @FocusedValue(\.printAction) private var action

    var body: some Commands {
        CommandGroup(replacing: .printItem) {
            Button(texts?.tr("ui.print.button") ?? "Print …") { action?.run() }
                .keyboardShortcut("p", modifiers: .command)
                .disabled(action == nil)
        }
    }
}

/// The print layout (print_dialog.PrintDialog): the page and its orientation, how many sketches per page, the margin,
/// a heading, a signature and the names under the sketches, the stroke colour, the background and the paper – with a
/// preview of the first page – then a PDF (vector pages) or the printer. It starts from the last print's choices (of
/// this app or the studio) and keeps them for the next one.
struct PrintSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let request: PrintRequest
    @State private var layout: PrintLayout
    @State private var items: [PrintItem]?
    @State private var preview: CGImage?
    @State private var work: Task<Data, any Error>?
    @State private var pagesDone = 0
    @State private var problem = ""

    static let previewWidth: CGFloat = 300

    init(request: PrintRequest, settings: AppSettings) {
        self.request = request
        _layout = State(initialValue: PrintLayout(settings: settings, count: request.entries.count))
    }

    private var pages: Int { layout.pageCount(items?.count ?? request.entries.count) }

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.print.title")).font(.title2.bold())
            Text(t.tr("ui.print.desc", ["n": "\(request.entries.count)"]))
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top, spacing: Spacing.spaceL) {
                form(t)
                VStack(spacing: Spacing.spaceS) {
                    page
                    Text(t.tr("ui.print.pages", ["n": "\(pages)"]))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(width: Self.previewWidth)
            }
            if work != nil {
                ProgressView(value: Double(pagesDone), total: Double(max(pages, 1)))
            }
            if !problem.isEmpty {
                Text(verbatim: problem).font(.callout).foregroundStyle(Color(hex: Palette.light.danger))
            }
            HStack {
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { cancel() }
                    .keyboardShortcut(.cancelAction)
                Button(t.tr("ui.print.print"), systemImage: "printer") { Task { await printPages() } }
                    .disabled(items?.isEmpty ?? true || work != nil)
                Button(t.tr("ui.print.save_pdf"), systemImage: "square.and.arrow.down") { Task { await savePDF() } }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(items?.isEmpty ?? true || work != nil)
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 780)
        .task {
            let entries = request.entries
            items = await Task.detached { entries.compactMap { $0.item() } }.value
        }
        .task(id: PreviewID(layout: layout, ready: items != nil)) {
            guard let items else { return }
            try? await Task.sleep(for: .milliseconds(150))  // (typing a heading does not draw for every letter)
            guard !Task.isCancelled else { return }
            let (layout, scale) = (layout, NSScreen.main?.backingScaleFactor ?? 2)
            let width = Int(Self.previewWidth * scale)
            preview = await Task.detached { try? PrintPages.preview(items, layout: layout, width: width) }.value
        }
    }

    private struct PreviewID: Equatable {
        var layout: PrintLayout
        var ready: Bool
    }

    private func form(_ t: Texts) -> some View {
        Form {
            Section {
                Picker(t.tr("ui.print.page_label"), selection: $layout.page) {
                    ForEach(PrintLayout.Page.allCases, id: \.self) { Text(t.tr("ui.print.page.\($0.rawValue)")).tag($0) }
                }
                Picker(t.tr("ui.print.orientation"), selection: $layout.landscape) {
                    Text(t.tr("ui.print.portrait")).tag(false)
                    Text(t.tr("ui.print.landscape")).tag(true)
                }
                .pickerStyle(.segmented)
                Picker(t.tr("ui.print.per_page"), selection: $layout.perPage) {
                    ForEach(PrintLayout.perPageChoices, id: \.self) { Text(t.tr("ui.print.per_page_n", ["n": "\($0)"])).tag($0) }
                }
                Stepper(value: $layout.marginMM, in: 0...60, step: 5) {
                    LabeledContent(t.tr("ui.print.margin"), value: String(format: "%.0f mm", layout.marginMM))
                }
            }
            Section {
                TextField(t.tr("ui.print.heading"), text: $layout.title, prompt: Text(t.tr("ui.print.title_placeholder")))
                TextField(t.tr("ui.print.signature"), text: $layout.signature,
                          prompt: Text(t.tr("ui.print.signature_placeholder")))
                Toggle(t.tr("ui.print.captions"), isOn: $layout.captions)
            }
            Section {
                ColorPicker(t.tr("ui.stroke_color"), selection: stroke, supportsOpacity: false)
                ColorPicker(t.tr("ui.background"), selection: background, supportsOpacity: false)
                PaperChoice(paper: $layout.paper) { kind in colours(kind: kind, background: layout.background) }
            }
        }
        .formStyle(.grouped)
        .disabled(work != nil)
    }

    /// The first page as it will be printed: a sheet of paper (content, no glass) in the page's shape.
    private var page: some View {
        let (w, h) = layout.pageMM
        return ZStack {
            if let preview {
                Image(decorative: preview, scale: CGFloat(preview.width) / Self.previewWidth)
                    .resizable()
                    .interpolation(.high)
            } else {
                Color.white
                ProgressView().controlSize(.small)
            }
        }
        .aspectRatio(w / h, contentMode: .fit)
        .frame(maxWidth: Self.previewWidth, maxHeight: Self.previewWidth * 1.5)
        .overlay { Rectangle().strokeBorder(.separator) }
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        .accessibilityElement()
        .accessibilityLabel(Text(model.texts.tr("ui.print.pages", ["n": "\(pages)"])))
    }

    /// The stroke colour (black: the sketches keep their own colours, as the studio's dialog).
    private var stroke: Binding<Color> {
        Binding(get: { Color(hex: layout.stroke ?? "#000000") },
                set: { let hex = ExportSheet.hex($0)
                    layout.stroke = hex == "#000000" ? nil : hex })
    }

    private var background: Binding<Color> {
        Binding(get: { Color(hex: layout.background ?? "#FFFFFF") },
                set: { colours(kind: nil, background: ExportSheet.hex($0)) })
    }

    /// paper_colours: a paper brings its colour; on a dark background black strokes turn light, and back.
    private func colours(kind: Paper.Kind?, background: String?) {
        let (ground, stroke) = Paper.colours(kind: kind, background: background, stroke: layout.stroke ?? "#000000")
        layout.background = ground
        layout.stroke = stroke.lowercased() == "#000000" ? nil : stroke
    }

    /// The layout as it is printed: heading and signature without spaces around them.
    private var chosen: PrintLayout {
        var chosen = layout
        chosen.title = chosen.title.trimmingCharacters(in: .whitespacesAndNewlines)
        chosen.signature = chosen.signature.trimmingCharacters(in: .whitespacesAndNewlines)
        return chosen
    }

    /// PrintDialog.reject: while a PDF is written, cancel stops it (between pages) and then closes.
    private func cancel() {
        if let work {
            work.cancel()
        } else {
            dismiss()
        }
    }

    /// The pages as a PDF, drawn off the main actor; the progress follows page by page.
    private func pdf(_ layout: PrintLayout, title: String) async throws -> Data {
        let items = items ?? []
        let (stream, progress) = AsyncStream.makeStream(of: Int.self)
        let task = Task.detached { () throws -> Data in
            defer { progress.finish() }
            return try PrintPages.pdf(items, layout: layout, title: title) { done, _ in progress.yield(done) }
        }
        work = task
        pagesDone = 0
        defer { work = nil }
        for await done in stream { pagesDone = done }
        return try await task.value
    }

    /// PrintDialog._save_pdf: where (the last export's folder first, named after the heading), then the pages.
    private func savePDF() async {
        let layout = chosen
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.pdf]
        panel.nameFieldStringValue = "\(layout.title.isEmpty ? request.name : layout.title).pdf"
        if let dir = model.settings["export_dir"]?.stringValue, !dir.isEmpty {
            panel.directoryURL = URL(filePath: dir, directoryHint: .isDirectory)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        remember(layout, exportDir: url.deletingLastPathComponent())
        do {
            let data = try await pdf(layout, title: layout.title.isEmpty ? url.deletingPathExtension().lastPathComponent
                                                                        : layout.title)
            try data.write(to: url, options: .atomic)
            dismiss()
        } catch is CancellationError {
            dismiss()
        } catch {
            problem = String(describing: error)
        }
    }

    /// PrintDialog._print: the pages to the system's print panel – on the page's paper, scaled down only where the
    /// printer's paper is smaller.
    private func printPages() async {
        let layout = chosen
        remember(layout, exportDir: nil)
        do {
            let title = layout.title.isEmpty ? request.name : layout.title
            guard let document = PDFDocument(data: try await pdf(layout, title: title)) else { return }
            let info = (NSPrintInfo.shared.copy() as? NSPrintInfo) ?? NSPrintInfo()
            let (w, h) = layout.page.mm
            info.paperSize = NSSize(width: w * PrintPages.pointsPerMM, height: h * PrintPages.pointsPerMM)
            info.orientation = layout.landscape ? .landscape : .portrait
            (info.topMargin, info.bottomMargin, info.leftMargin, info.rightMargin) = (0, 0, 0, 0)
            guard let operation = document.printOperation(for: info, scalingMode: .pageScaleDownToFit, autoRotate: true)
            else { return }
            operation.jobTitle = title
            if operation.run() { dismiss() }
        } catch is CancellationError {
            dismiss()
        } catch {
            problem = String(describing: error)
        }
    }

    /// PrintDialog._remember (and the folder of a saved PDF for the next export).
    private func remember(_ layout: PrintLayout, exportDir: URL?) {
        let count = request.entries.count
        model.updateSettings {
            layout.remember(in: &$0, count: count)
            if let exportDir { $0["export_dir"] = .string(exportDir.path) }
        }
    }
}
