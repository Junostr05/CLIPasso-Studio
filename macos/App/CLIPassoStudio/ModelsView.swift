import StudioApp
import StudioCore
import SwiftUI

/// The Models page (gui/pages/other_pages.py ModelsPage): the models in the groups the engine exports, each with its
/// purpose, size and state – *Download* when it is missing, *Remove* (after a question) when it was downloaded;
/// BlazeFace comes with the app. Content: a plain list.
struct ModelsView: View {
    @Environment(AppModel.self) private var model
    @State private var removing: String?

    var body: some View {
        let catalog = model.catalog
        List {
            ForEach(catalog.groups) { group in
                let specs = catalog.models.filter { $0.group == group.id }
                if !specs.isEmpty {
                    Section {
                        ForEach(specs) { ModelRow(spec: $0, removing: $removing) }
                    } header: {
                        Text(model.texts.tr(group.title))
                    } footer: {
                        if model.texts.has(group.hint) {
                            Text(model.texts.tr(group.hint)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            Section {
                Text(model.texts.tr("ui.models.location", ["path": model.modelsDir.path]))
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .confirmationDialog(model.texts.tr("ui.models.remove_q"),
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            presenting: removing) { key in
            Button(model.texts.tr("ui.models.remove"), role: .destructive) {
                try? model.removeModel(key)
            }
            Button(model.texts.tr("ui.cancel"), role: .cancel) {}
        }
        .navigationTitle(model.texts.tr("ui.models.title"))
    }
}

private struct ModelRow: View {
    @Environment(AppModel.self) private var model
    let spec: ModelSpec
    @Binding var removing: String?

    var body: some View {
        let state = model.modelState(spec.key)
        HStack(alignment: .firstTextBaseline, spacing: Spacing.spaceM) {
            VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                Text(verbatim: spec.name).font(.headline)
                Text(purpose).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Text(verbatim: model.texts.size(Double(spec.storedSizeMB)))
                .monospacedDigit()
                .foregroundStyle(.secondary)
            switch state {
            case .included:
                Text(model.texts.tr("ui.models.bundled")).foregroundStyle(.secondary)
            case .installed:
                Button(model.texts.tr("ui.models.remove")) { removing = spec.key }
            case .missing:
                Button(model.texts.tr("ui.download")) { model.downloadModels([spec.key]) }
                    .disabled(model.engineStatus != .ready || model.models.stage != .idle)
            }
        }
        .padding(.vertical, Spacing.spaceXs)
        .accessibilityElement(children: .combine)
        .accessibilityValue(Text(model.texts.tr(state == .missing ? "ui.models.not_installed"
                : state == .included ? "ui.models.bundled" : "ui.models.installed")))
    }

    private var purpose: String {
        var params: [String: String] = [:]
        for (name, key) in spec.purposeParams {
            params[name] = model.texts.tr(key)
        }
        return model.texts.tr(spec.purpose, params)
    }
}
