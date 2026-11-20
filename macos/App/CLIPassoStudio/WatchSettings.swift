import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// The watched folder on the settings page (gui/pages SettingsPage's "Watched folder"): on / off, the folder, the
/// settings its images get, the formats, where the sketches go, "done". Content: a section of the grouped form.
struct WatchSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let t = model.texts
        let config = model.watchConfig
        Section {
            Toggle(t.tr("ui.watch.enabled"), isOn: Binding(
                get: { config.enabled }, set: { model.setWatch("watch_enabled", .bool($0)) }))
            LabeledContent(t.tr("ui.watch.folder")) {
                HStack {
                    Text(verbatim: config.folder.isEmpty ? "–" : config.folder)
                        .lineLimit(1).truncationMode(.middle).foregroundStyle(.secondary)
                    Button(t.tr("ui.watch.choose")) {
                        if let url = Self.choose(folder: true, start: config.folder) {
                            model.setWatch("watch_folder", .string(url.path))
                        }
                    }
                }
            }
            Picker(t.tr("ui.watch.preset"), selection: Binding(
                get: { config.preset == "studio" ? "studio" : "file" },
                set: { choice in
                    if choice == "studio" {
                        model.setWatch("watch_preset", "studio")
                    } else if let url = Self.choose(folder: false, start: config.folder) {
                        model.setWatch("watch_preset", .string(url.path))
                    }
                })) {
                Text(t.tr("ui.watch.preset_studio")).tag("studio")
                Text(verbatim: config.preset == "studio" ? t.tr("ui.watch.preset_file")
                    : URL(filePath: config.preset).lastPathComponent).tag("file")
            }
            LabeledContent(t.tr("ui.watch.formats")) {
                HStack {
                    ForEach(FolderWatch.formats, id: \.self) { fmt in
                        Toggle(label(fmt), isOn: Binding(
                            get: { config.formats.contains(fmt) },
                            set: { on in
                                let wanted = FolderWatch.formats.filter {
                                    $0 == fmt ? on : config.formats.contains($0)
                                }
                                model.setWatch("watch_formats", .array(wanted.map(JSONValue.string)))
                            }))
                            .toggleStyle(.checkbox)
                    }
                }
            }
            LabeledContent(t.tr("ui.watch.export_dir")) {
                HStack {
                    Text(verbatim: config.exportDir.isEmpty ? t.tr("ui.watch.export_default") : config.exportDir)
                        .lineLimit(1).truncationMode(.middle).foregroundStyle(.secondary)
                    Button(t.tr("ui.step.change")) {
                        if let url = Self.choose(folder: true, start: config.exportDir) {
                            model.setWatch("watch_export_dir", .string(url.path))
                        }
                    }
                    if !config.exportDir.isEmpty {
                        Button(t.tr("ui.mac.reset")) { model.setWatch("watch_export_dir", "") }
                    }
                }
            }
            Toggle(t.tr("ui.watch.move_done"), isOn: Binding(
                get: { config.moveDone }, set: { model.setWatch("watch_move_done", .bool($0)) }))
            if !model.watchNote.isEmpty {
                Text(verbatim: model.watchNote).font(.callout).foregroundStyle(.secondary)
            }
        } header: {
            Text(t.tr("ui.watch.title"))
        } footer: {
            Text(t.tr("ui.watch.desc")).foregroundStyle(.secondary)
        }
    }

    private func label(_ fmt: String) -> String {
        fmt == "svg1" ? model.texts.tr("ui.export_svg1") : fmt.uppercased()
    }

    /// A folder (or a preset file, JSON) chosen in an open panel; nil when cancelled.
    private static func choose(folder: Bool, start: String) -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = folder
        panel.canChooseFiles = !folder
        panel.canCreateDirectories = folder
        if !folder { panel.allowedContentTypes = [.json] }
        if !start.isEmpty { panel.directoryURL = URL(filePath: start) }
        return panel.runModal() == .OK ? panel.url : nil
    }
}
