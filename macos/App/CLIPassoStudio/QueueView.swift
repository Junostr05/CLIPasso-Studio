import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// The queue page: the jobs in order (drag or the arrows to move, remove a waiting one); *Add images*, *Add folder*,
/// *Start the next job automatically*, *When done* and *Remove finished* in the toolbar; images and folders dropped
/// on the list are queued with the studio's settings (other_pages.QueuePage). Content: a plain list.
struct QueueView: View {
    @Environment(AppModel.self) private var model
    @State private var importing = false
    @State private var importKind = ImportKind.images
    @State private var askedFolder: URL?
    @State private var nothingFound = false

    private enum ImportKind { case images, folder }

    var body: some View {
        Group {
            if let page = model.queuePage {
                List {
                    ForEach(page.jobs) { QueueRow(job: $0, page: page) }
                        .onMove { from, to in
                            guard let at = from.first else { return }
                            let id = page.jobs[at].id
                            Task { await page.move(id, to: to > at ? to - 1 : to) }
                        }
                }
                .overlay {
                    if page.jobs.isEmpty {
                        ContentUnavailableView(model.texts.tr("ui.queue.empty_title"), systemImage: "list.bullet.rectangle",
                                               description: Text(model.texts.tr("ui.mac.queue.empty_hint")))  // (the title says it is empty)
                    }
                }
                .dropDestination(for: URL.self) { urls, _ in
                    let images = ImageFiles.dropped(urls)
                    guard !images.isEmpty else {
                        nothingFound = true
                        return false
                    }
                    Task { await model.addToQueue(images) }
                    return true
                }
                .toolbar {
                    ToolbarItemGroup {
                        Button(model.texts.tr("ui.queue.add"), systemImage: "photo.badge.plus") {
                            importKind = .images
                            importing = true
                        }
                        Button(model.texts.tr("ui.queue.add_folder"), systemImage: "folder.badge.plus") {
                            importKind = .folder
                            importing = true
                        }
                        .help(model.texts.tr("ui.queue.add_folder_tip"))
                    }
                    ToolbarItemGroup {
                        Toggle(model.texts.tr("ui.queue.auto"), isOn: Binding(
                            get: { page.snapshot.autoStart },
                            set: { on in Task { await page.setAutoStart(on) } }))
                        Picker(model.texts.tr("ui.queue.when_done"), selection: Binding(
                            get: { page.whenDone },
                            set: { action in Task { await page.setWhenDone(action) } })) {
                            ForEach(WhenDone.allCases, id: \.self) { action in
                                Text(model.texts.tr("ui.queue.done_\(action.rawValue)")).tag(action)
                            }
                        }
                        Button(model.texts.tr("ui.queue.clear"), systemImage: "checkmark.circle") {
                            Task { await page.removeFinished() }
                        }
                    }
                }
                .fileImporter(isPresented: $importing, allowedContentTypes: importKind == .folder ? [.folder] : [.image],
                              allowsMultipleSelection: importKind == .images) { result in
                    guard case .success(let urls) = result, let first = urls.first else { return }
                    switch importKind {
                    case .images: Task { await model.addToQueue(urls.filter { ImageFiles.isImage($0.lastPathComponent) }) }
                    case .folder:
                        if ImageFiles.hasSubfolders(first) { askedFolder = first } else { addFolder(first, recursive: false) }
                    }
                }
                .confirmationDialog(model.texts.tr("ui.queue.subfolders_q"),
                                    isPresented: Binding(get: { askedFolder != nil }, set: { if !$0 { askedFolder = nil } }),
                                    presenting: askedFolder) { folder in
                    Button(model.texts.tr("ui.mac.queue.with_subfolders")) { addFolder(folder, recursive: true) }
                    Button(model.texts.tr("ui.mac.queue.only_folder")) { addFolder(folder, recursive: false) }
                    Button(model.texts.tr("ui.cancel"), role: .cancel) {}
                }
                .alert(model.texts.tr("ui.queue.folder_empty"), isPresented: $nothingFound) {}
                .task { await page.reload() }
            } else {
                ContentUnavailableView(model.texts.tr("ui.queue.title"), systemImage: "list.bullet.rectangle",
                                       description: Text(verbatim: model.engineStatusText))
            }
        }
        .navigationTitle(model.texts.tr("ui.queue.title"))
    }

    /// QueuePage.add_folder: the folder's images (with its subfolders' when asked), read off the main actor.
    private func addFolder(_ folder: URL, recursive: Bool) {
        Task {
            let images = await Task.detached { ImageFiles.inFolder(folder, recursive: recursive) }.value
            guard !images.isEmpty else {
                nothingFound = true
                return
            }
            await model.addToQueue(images)
        }
    }
}

private struct QueueRow: View {
    @Environment(AppModel.self) private var model
    let job: QueuedJob
    let page: QueueModel

    var body: some View {
        HStack(spacing: Spacing.spaceM) {
            VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                Text(verbatim: job.target.lastPathComponent).font(.headline)
                Text(details).font(.callout).foregroundStyle(.secondary)
                if job.isActive {
                    ProgressView(value: job.progress)
                }
            }
            Spacer()
            Text(status).foregroundStyle(.secondary)
            if !job.isActive {
                Button(model.texts.tr("ui.queue.up"), systemImage: "chevron.up") { Task { await page.move(job.id, by: -1) } }
                    .labelStyle(.iconOnly)
                Button(model.texts.tr("ui.queue.down"), systemImage: "chevron.down") { Task { await page.move(job.id, by: 1) } }
                    .labelStyle(.iconOnly)
                Button(model.texts.tr("ui.queue.remove"), systemImage: "xmark") { Task { await page.remove(job.id) } }
                    .labelStyle(.iconOnly)
            }
        }
        .padding(.vertical, Spacing.spaceXs)
        .accessibilityElement(children: .contain)
    }

    private var details: String {
        let method = model.schema.method(job.settings["method"]?.stringValue ?? "")
        return model.texts.tr("ui.queue.details", [
            "strokes": "\(method?.numStrokes(job.settings) ?? 0)",
            "iters": "\(job.settings["num_iter"]?.intValue ?? method?.start["num_iter"]?.intValue ?? 0)",
            "sketches": "\(job.settings["num_sketches"]?.intValue ?? method?.start["num_sketches"]?.intValue ?? 1)",
        ])
    }

    private var status: String {
        switch job.status {
        case .paused: model.texts.tr("ui.status.paused")
        case .failed: model.texts.tr("ui.status.failed")
        default: model.texts.tr("ui.mac.job_status.\(job.status.rawValue)")
        }
    }
}
