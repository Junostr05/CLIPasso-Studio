import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// Backup & move on the settings page (gui/backup_ui.py): *Create backup …* and *Restore backup …*, each in a sheet
/// with its progress. Content: a section of the grouped form.
struct BackupSettings: View {
    @Environment(AppModel.self) private var model
    @State private var creating = false
    @State private var restoring: (url: URL, manifest: JSONObject)?
    @State private var problem: String?

    static let type = UTType(filenameExtension: Backup.fileExtension) ?? .zip

    var body: some View {
        let t = model.texts
        Section {
            Text(t.tr("ui.backup.desc")).foregroundStyle(.secondary)
            HStack {
                Button(t.tr("ui.backup.button")) { creating = true }
                    .help(t.tr("ui.backup.tip"))
                Button(t.tr("ui.backup.restore_button")) { chooseBackup() }
                    .help(t.tr("ui.backup.restore_tip"))
            }
            if let problem {
                Text(verbatim: problem).foregroundStyle(.secondary)
            }
        } header: {
            Text(t.tr("ui.mac.backup"))
        }
        .sheet(isPresented: $creating) { CreateBackupSheet() }
        .sheet(isPresented: Binding(get: { restoring != nil }, set: { if !$0 { restoring = nil } })) {
            if let restoring { RestoreBackupSheet(url: restoring.url, manifest: restoring.manifest) }
        }
    }

    private func chooseBackup() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [Self.type]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            restoring = (url, try Backup.readManifest(url))
            problem = nil
        } catch {
            problem = String(describing: error)
        }
    }
}

/// The progress of a backup being written or put back, and what came of it.
private struct Progress: View {
    let done: Int64
    let total: Int64

    var body: some View {
        ProgressView(value: total > 0 ? Double(done) / Double(total) : 0)
    }
}

/// *Create backup*: what it will hold, the models if wanted, *Save backup …*.
private struct CreateBackupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var sizes: (jobs: Int, gallery: Int64, queue: Int, models: Int64)?
    @State private var withModels = false
    @State private var running: Task<Void, Never>?
    @State private var progress: (Int64, Int64) = (0, 0)
    @State private var result: String?

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.backup.title")).font(.title2)
            Text(t.tr("ui.backup.desc")).fixedSize(horizontal: false, vertical: true)
            if let sizes {
                Text(t.tr("ui.backup.contents", ["jobs": String(sizes.jobs),
                                                 "gallery": t.size(Double(sizes.gallery) / 1e6),
                                                 "queue": String(sizes.queue)]))
                    .foregroundStyle(.secondary)
                Toggle(t.tr("ui.backup.with_models", ["size": t.size(Double(sizes.models) / 1e6)]), isOn: $withModels)
                    .help(t.tr("ui.backup.with_models_tip"))
                    .disabled(running != nil)
            } else {
                ProgressView().controlSize(.small)
            }
            if running != nil { Progress(done: progress.0, total: progress.1) }
            if let result { Text(verbatim: result).foregroundStyle(.secondary) }
            HStack {
                Spacer()
                Button(t.tr(running == nil ? (result == nil ? "ui.cancel" : "ui.close") : "ui.cancel"),
                       role: .cancel) {
                    running?.cancel()
                    dismiss()
                }
                Button(t.tr("ui.backup.save")) { save() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(sizes == nil || running != nil)
            }
        }
        .padding(Spacing.spaceL)
        .frame(width: 480)
        .task { sizes = await model.backupSizes() }
    }

    private func save() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [BackupSettings.type]
        panel.nameFieldStringValue = Backup.defaultName()
        guard panel.runModal() == .OK, let url = panel.url else { return }
        result = nil
        running = Task {
            do {
                try await model.createBackup(to: url, includeModels: withModels) { done, total in
                    Task { @MainActor in progress = (done, total) }
                }
                result = url.lastPathComponent
            } catch is CancellationError {
                result = nil
            } catch {
                result = String(describing: error)
            }
            running = nil
        }
    }
}

/// *Restore backup*: what it holds and from when, which parts come back, *Restore*.
private struct RestoreBackupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let url: URL
    let manifest: JSONObject
    @State private var parts: Set<String> = ["settings", "queue", "gallery", "models"]
    @State private var running: Task<Void, Never>?
    @State private var progress: (Int64, Int64) = (0, 0)
    @State private var result: String?

    var body: some View {
        let t = model.texts
        let jobs = (manifest["gallery_names"]?.arrayValue ?? []).filter { $0.stringValue?.hasPrefix("_") == false }.count
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.backup.restore_title")).font(.title2)
            Text(t.tr("ui.backup.restore_desc", ["created": manifest["created"]?.stringValue ?? "?",
                                                 "version": manifest["version"]?.stringValue ?? "?"]))
            part("settings", t.tr("ui.backup.part_settings"))
            part("queue", t.tr("ui.backup.part_queue_n", ["n": String(manifest["queue"]?.intValue ?? 0)]))
            part("gallery", t.tr("ui.backup.part_gallery_n", ["n": String(jobs)]))
            if manifest["has_models"]?.truthy ?? false { part("models", t.tr("ui.backup.part_models")) }
            Text(t.tr("ui.backup.restore_note")).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if running != nil { Progress(done: progress.0, total: progress.1) }
            if let result { Text(verbatim: result).fixedSize(horizontal: false, vertical: true) }
            HStack {
                Spacer()
                Button(t.tr(result == nil ? "ui.cancel" : "ui.close"), role: .cancel) {
                    running?.cancel()
                    dismiss()
                }
                Button(t.tr("ui.backup.restore")) { restore() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(parts.isEmpty || running != nil || result != nil)
            }
        }
        .padding(Spacing.spaceL)
        .frame(width: 480)
    }

    private func part(_ key: String, _ label: String) -> some View {
        Toggle(label, isOn: Binding(get: { parts.contains(key) },
                                    set: { if $0 { parts.insert(key) } else { parts.remove(key) } }))
            .toggleStyle(.checkbox)
            .disabled(running != nil || result != nil)
    }

    private func restore() {
        running = Task {
            do {
                let report = try await model.restoreBackup(from: url, parts: parts) { done, total in
                    Task { @MainActor in progress = (done, total) }
                }
                result = model.texts.tr("ui.backup.restored", [
                    "jobs": String(report.jobs), "skipped": String(report.skippedJobs),
                    "queue": String(report.queue.count), "models": String(report.models),
                ])
            } catch is CancellationError {
                result = nil
            } catch {
                result = String(describing: error)
            }
            running = nil
        }
    }
}
