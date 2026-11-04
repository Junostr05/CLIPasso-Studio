import StudioApp
import StudioCore
import SwiftUI

/// The queue page: the jobs in order (drag or the arrows to move, remove a waiting one), *Start the next job
/// automatically*, *When done* and *Remove finished* in the toolbar. Content: a plain list.
struct QueueView: View {
    @Environment(AppModel.self) private var model

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
                                               description: Text(model.texts.tr("ui.queue.empty")))
                    }
                }
                .toolbar {
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
                .task { await page.reload() }
            } else {
                ContentUnavailableView(model.texts.tr("ui.queue.title"), systemImage: "list.bullet.rectangle",
                                       description: Text(verbatim: model.engineStatusText))
            }
        }
        .navigationTitle(model.texts.tr("ui.queue.title"))
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
