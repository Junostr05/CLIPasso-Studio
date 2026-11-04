import Foundation
import Observation
import StudioCore

/// The queue page (gui/pages/other_pages.py QueuePage) on the engine's JobQueue: its jobs as last reported, moving
/// and removing them, starting the next one by itself and what happens when the queue ran out.
@Observable
public final class QueueModel {
    public private(set) var snapshot = QueueSnapshot(jobs: [], finished: nil, autoStart: true)
    public private(set) var whenDone: WhenDone = .nothing
    @ObservationIgnored let queue: JobQueue

    public init(queue: JobQueue) {
        self.queue = queue
    }

    public var jobs: [QueuedJob] { snapshot.jobs }

    func apply(_ snapshot: QueueSnapshot) {
        if self.snapshot != snapshot { self.snapshot = snapshot }
    }

    public func reload() async {
        apply(await queue.snapshot())
        whenDone = await queue.whenDone
    }

    /// One place up (-1) or down (+1) – the studio's arrows (dragging gives the place itself).
    public func move(_ id: QueuedJob.ID, by step: Int) async {
        guard let at = jobs.firstIndex(where: { $0.id == id }) else { return }
        await move(id, to: max(0, min(jobs.count - 1, at + step)))
    }

    public func move(_ id: QueuedJob.ID, to index: Int) async {
        await queue.move(id, to: index)
        await reload()
    }

    public func remove(_ id: QueuedJob.ID) async {
        await queue.remove(id)
        await reload()
    }

    /// *Remove finished*: the done, failed and cancelled jobs leave the list.
    public func removeFinished() async {
        for job in jobs where [.done, .failed, .cancelled].contains(job.status) {
            await queue.remove(job.id)
        }
        await reload()
    }

    public func setAutoStart(_ on: Bool) async {
        await queue.setAutoStart(on)
        await reload()
    }

    public func setWhenDone(_ action: WhenDone) async {
        await queue.setWhenDone(action)
        await reload()
    }

    /// *Continue* an interrupted or cancelled job of the gallery in its folder.
    public func continueJob(_ item: GalleryItem) async {
        await queue.addContinuation(jobDir: item.jobDir, target: URL(filePath: item.summary.target),
                                    settings: item.summary.settings)
        await reload()
    }
}

/// The gallery page on GalleryIndex: the results of the output folder, searched, filtered and sorted as the query
/// says (the view binds to it), favourites and titles written to meta.json.
@Observable
public final class GalleryModel {
    public var query = GalleryQuery() {
        didSet { apply() }
    }

    public private(set) var items: [GalleryItem] = []
    public private(set) var total = 0
    public private(set) var tags: [String] = []
    public private(set) var albums: [String] = []
    @ObservationIgnored private var all: [GalleryItem] = []
    @ObservationIgnored private let index: GalleryIndex
    public let root: URL

    public init(root: URL, schema: ParamSchema?) {
        self.root = root
        index = GalleryIndex(root: root, schema: schema)
    }

    /// Read the output folder again (only what changed).
    public func refresh() async {
        all = await index.refresh()
        tags = await index.tags()
        albums = await index.albums()
        apply()
    }

    private func apply() {
        total = all.count
        items = query.sorted(all.filter(query.includes))
    }

    /// "12 results in the output folder" or, filtered, "3 of 12 results".
    public func countText(_ texts: Texts) -> String {
        items.count == total ? texts.tr("ui.gallery.count", ["n": "\(total)"])
            : texts.tr("ui.gallery.count_shown", ["n": "\(items.count)", "total": "\(total)"])
    }

    public func setFavourite(_ item: GalleryItem, _ on: Bool) async {
        try? await index.setFavourite(item.jobDir, on)
        await refresh()
    }

    public func rename(_ item: GalleryItem, _ title: String) async {
        try? await index.setTitle(item.jobDir, title)
        await refresh()
    }
}
