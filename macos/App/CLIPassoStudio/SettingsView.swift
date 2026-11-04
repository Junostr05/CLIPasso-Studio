import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The settings page: language and appearance, the output folder and the folder of the downloaded models – saved at
/// once in the settings.json the Python app uses too. Content: a grouped form.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var problem: String?

    var body: some View {
        Form {
            Section(model.texts.tr("ui.settings.appearance")) {
                Picker(model.texts.tr("ui.settings.language"), selection: Binding(
                    get: { model.settings.language },
                    set: { try? model.setLanguage($0) })) {
                    ForEach(model.languageChoices) { Text(verbatim: $0.label).tag($0.id) }
                }
                Picker(model.texts.tr("ui.settings.theme"), selection: Binding(
                    get: { model.appearance },
                    set: { model.setAppearance($0) })) {
                    ForEach(AppModel.Appearance.allCases, id: \.self) { Text(model.texts.tr("ui.theme.\($0.rawValue)")).tag($0) }
                }
                .pickerStyle(.segmented)
            }
            Section(model.texts.tr("ui.settings.files")) {
                FolderRow(title: model.texts.tr("ui.settings.output"), folder: model.settings.outputDir) { url in
                    Task { await model.setOutputDir(url) }
                }
                FolderRow(title: model.texts.tr("ui.settings.models_dir"), folder: model.modelsDir) { url in
                    Task { problem = await model.setModelsDir(url) }
                }
                if let problem {
                    Text(verbatim: problem).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle(model.texts.tr("ui.settings.title"))
    }
}

/// A folder with its path and *Change …* (a folder chooser); *Show* opens it in the Finder.
private struct FolderRow: View {
    @Environment(AppModel.self) private var model
    let title: String
    let folder: URL
    let choose: (URL) -> Void

    var body: some View {
        LabeledContent(title) {
            HStack {
                Text(verbatim: folder.path)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Button(model.texts.tr("ui.step.change")) {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = true
                    panel.canChooseFiles = false
                    panel.canCreateDirectories = true
                    panel.directoryURL = folder
                    if panel.runModal() == .OK, let url = panel.url { choose(url) }
                }
                Button(model.texts.tr("ui.gallery.show_folder")) {
                    try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                    NSWorkspace.shared.activateFileViewerSelecting([folder])
                }
            }
        }
    }
}
