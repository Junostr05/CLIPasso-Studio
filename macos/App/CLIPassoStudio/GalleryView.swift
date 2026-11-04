import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// The gallery page: every result of the output folder as a sketch on paper, searched (toolbar search field),
/// filtered and sorted from the toolbar; a result's menu opens it in the studio, marks it, renames it, exports it as
/// SVG or PNG, shows it in the Finder or continues it. Content: a grid, no glass.
struct GalleryView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var gallery = model.gallery
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: Spacing.spaceL)], spacing: Spacing.spaceL) {
                ForEach(gallery.items) { GalleryCell(item: $0) }
            }
            .padding(Spacing.spaceL)
        }
        .overlay {
            if gallery.items.isEmpty {
                if gallery.total == 0 {
                    ContentUnavailableView(model.texts.tr("ui.gallery.empty_title"), systemImage: "square.grid.2x2",
                                           description: Text(model.texts.tr("ui.gallery.empty_how")))
                } else {
                    ContentUnavailableView {
                        Label(model.texts.tr("ui.gallery.empty_match_title"), systemImage: "magnifyingglass")
                    } description: {
                        Text(model.texts.tr("ui.gallery.empty_match"))
                    } actions: {
                        Button(model.texts.tr("ui.gallery.empty_reset")) { gallery.query = GalleryQuery() }
                    }
                }
            }
        }
        .searchable(text: $gallery.query.text, prompt: model.texts.tr("ui.gallery.search"))
        .toolbar {
            ToolbarItemGroup {
                Picker(model.texts.tr("ui.gallery.method"), selection: $gallery.query.method) {
                    Text(model.texts.tr("ui.gallery.all")).tag(String?.none)
                    ForEach(model.schema.methods, id: \.self) { id in
                        Text(verbatim: model.schema.method(id)?.name ?? id).tag(String?.some(id))
                    }
                }
                if !gallery.tags.isEmpty {
                    Picker(model.texts.tr("ui.gallery.tag"), selection: $gallery.query.tag) {
                        Text(model.texts.tr("ui.gallery.all")).tag(String?.none)
                        ForEach(gallery.tags, id: \.self) { Text(verbatim: $0).tag(String?.some($0)) }
                    }
                }
                Toggle(model.texts.tr("ui.gallery.favourites"), systemImage: "star", isOn: $gallery.query.favouritesOnly)
                    .help(model.texts.tr("ui.gallery.favourites_tip"))
                Picker(selection: $gallery.query.sort) {
                    ForEach(GallerySort.allCases, id: \.self) { sort in
                        Text(model.texts.tr("ui.gallery.sort_\(sort.rawValue)")).tag(sort)
                    }
                } label: {
                    Label(model.texts.tr("ui.gallery.sort_newest"), systemImage: "arrow.up.arrow.down")
                }
            }
        }
        .navigationTitle(model.texts.tr("ui.gallery.title"))
        .navigationSubtitle(gallery.countText(model.texts))
        .task { await gallery.refresh() }
    }
}

private struct GalleryCell: View {
    @Environment(AppModel.self) private var model
    let item: GalleryItem
    @State private var sketch: Sketch?
    @State private var renaming = false
    @State private var title = ""

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.spaceXs) {
            SketchView(sketch: sketch, label: model.texts.tr("ui.mac.canvas_label", [
                "image": item.name, "strokes": "\(sketch?.strokes.count ?? item.strokes)"]))
                .aspectRatio(1, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: Radius.card))
                .overlay(alignment: .topTrailing) {
                    if item.favourite {
                        Image(systemName: "star.fill")
                            .foregroundStyle(.yellow)
                            .padding(Spacing.spaceS)
                            .accessibilityLabel(Text(model.texts.tr("ui.gallery.favourite")))
                    }
                }
            Text(verbatim: item.name).font(.headline).lineLimit(1)
            Text(model.texts.tr("ui.gallery.meta", ["strokes": "\(item.strokes)", "date": item.created]))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { open() }  // (as the studio's gallery: a double-click continues in the studio)
        .contextMenu { menu }
        // keyboard and VoiceOver reach every result: focus, Return opens it, the menu's actions by name
        .focusable()
        .onKeyPress(.return) {
            open()
            return .handled
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { open() }
        .accessibilityAction(named: Text(model.texts.tr(item.favourite ? "ui.gallery.unfavourite" : "ui.gallery.favourite"))) {
            Task { await model.gallery.setFavourite(item, !item.favourite) }
        }
        .accessibilityAction(named: Text(model.texts.tr("ui.gallery.show_folder"))) {
            NSWorkspace.shared.activateFileViewerSelecting([item.jobDir])
        }
        .alert(model.texts.tr("ui.gallery.info_name"), isPresented: $renaming) {
            TextField(model.texts.tr("ui.gallery.info_name"), text: $title)
            Button(model.texts.tr("ui.cancel"), role: .cancel) {}
            Button("OK") { Task { await model.gallery.rename(item, title) } }
        }
        .task(id: item.bestSketch) {
            guard let url = item.bestSketch else { return }
            sketch = await Task.detached {
                (try? String(contentsOf: url, encoding: .utf8)).flatMap { try? SketchSVG.parse($0) }
            }.value
        }
    }

    @ViewBuilder private var menu: some View {
        Button(model.texts.tr("ui.gallery.open")) { open() }
        Button(model.texts.tr(item.favourite ? "ui.gallery.unfavourite" : "ui.gallery.favourite")) {
            Task { await model.gallery.setFavourite(item, !item.favourite) }
        }
        Button(model.texts.tr("ui.albums.rename")) {
            title = item.summary.title
            renaming = true
        }
        Divider()
        Button("SVG …") { export(.svg) }
        Button("PNG …") { export(.png) }
        Button(model.texts.tr("ui.gallery.show_folder")) {
            NSWorkspace.shared.activateFileViewerSelecting([item.jobDir])
        }
        if JobFolder.canContinue(item.summary), let page = model.queuePage {
            Divider()
            Button(model.texts.tr("ui.continue")) { Task { await page.continueJob(item) } }
        }
    }

    /// The result back in the studio: its image, its method and its sketches (to touch up).
    private func open() {
        model.studio.open(item)
    }

    /// export.export_svg / export_png (the plain style; PNG 1024 px on white).
    private func export(_ type: UTType) {
        guard let source = item.bestSketch, let svg = try? String(contentsOf: source, encoding: .utf8) else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [type]
        panel.nameFieldStringValue = "\(item.name).\(type == .png ? "png" : "svg")"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if type == .png {
            try? SketchRenderer.exportPNG(svg: svg, size: 1024).write(to: url, options: .atomic)
        } else {
            try? Data(SketchExport.restyleSVG(svg).utf8).write(to: url, options: .atomic)
        }
    }
}
