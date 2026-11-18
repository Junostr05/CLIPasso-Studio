import Foundation
import StudioCore

/// The watched folder in the app (watch.FolderWatcher): a look at the folder every 10 s and whenever it changes,
/// every half second while a new image may still be written; the images queued with the studio's settings (or a
/// preset file's), their best sketch exported when the job is done, the image moved into "done" if wanted.
final class FolderWatcher {
    var watch: FolderWatch
    let stateFile: URL
    /// the queued jobs of the folder → their image
    var jobs: [QueuedJob.ID: URL] = [:]
    var loop: Task<Void, Never>?
    /// a change notification came (the folder is looked at at once)
    var poked = false
    #if canImport(Darwin)
        private var source: (any DispatchSourceFileSystemObject)?
    #endif

    init(stateFile: URL) {
        self.stateFile = stateFile
        watch = FolderWatch.load(stateFile)
    }

    /// Notified when the folder's entries change (DispatchSource on the folder; polling covers the rest).
    func follow(_ folder: URL) {
        #if canImport(Darwin)
            let fd = open(folder.path, O_EVTONLY)
            guard fd >= 0 else { return }
            let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write, .rename],
                                                                   queue: .main)
            source.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.poked = true } }
            source.setCancelHandler { close(fd) }
            source.resume()
            self.source = source
        #endif
    }

    func stop() {
        loop?.cancel()
        loop = nil
        #if canImport(Darwin)
            source?.cancel()
            source = nil
        #endif
        watch.forgetPending()
    }
}

public extension AppModel {
    /// The watched folder's settings.
    var watchConfig: FolderWatch.Config { FolderWatch.Config(settings) }

    /// A setting of the watched folder changed (watch_enabled, watch_folder, …): saved, and the watching follows it.
    func setWatch(_ key: String, _ value: JSONValue?) {
        updateSettings { $0[key] = value }
        reconfigureWatch()
    }

    /// reconfigure: follow the settings (folder, on / off) – while the engine runs.
    internal func reconfigureWatch() {
        folderWatcher.stop()
        let config = watchConfig
        guard config.active, queue != nil else { return }
        let folder = URL(filePath: config.folder, directoryHint: .isDirectory)
        folderWatcher.follow(folder)
        folderWatcher.loop = Task { [weak self] in
            var lastScan = -Double.infinity
            while !Task.isCancelled {
                guard let self else { return }
                let now = ProcessInfo.processInfo.systemUptime
                let scan = folderWatcher.poked || now - lastScan >= FolderWatch.poll
                if scan {
                    lastScan = now
                    folderWatcher.poked = false
                }
                await watchTick(now: now, scan: scan)
                try? await Task.sleep(for: .milliseconds(500))
            }
        }
    }

    /// One look: the folder's new images noted (`scan`), the ones that stayed unchanged queued.
    internal func watchTick(now: Double, scan: Bool = true) async {
        let config = watchConfig
        guard config.active, let queue else { return }
        if scan {
            folderWatcher.watch.scan(URL(filePath: config.folder, directoryHint: .isDirectory),
                                     waiting: Set(folderWatcher.jobs.values.map(\.path)), now: now)
        }
        guard folderWatcher.watch.hasPending else { return }
        let ready = folderWatcher.watch.ready(now: now)
        guard !ready.isEmpty else { return }
        for item in ready {
            let id = await queue.add(target: item.url, settings: watchSettings(config))
            folderWatcher.jobs[id] = item.url
            folderWatcher.watch.handled(item.url, stamp: item.stamp)  // (also after a restart: not again)
            folderWatcher.watch.save(folderWatcher.stateFile)
            watchSay(texts.tr("ui.watch.queued", ["name": item.url.lastPathComponent]))
        }
        apply(await queue.snapshot())
    }

    /// _settings: the preset file's settings, else (or when it cannot be read) the studio's.
    private func watchSettings(_ config: FolderWatch.Config) -> JSONObject {
        guard config.preset != "studio" else { return studio.jobSettings }
        let url = URL(filePath: config.preset)
        if let data = try? Data(contentsOf: url), let o = try? PyJSON.parse(data).objectValue,
           let settings = UserPresets.normalize(o, schema: schema)
        {
            return settings
        }
        watchSay(texts.tr("ui.watch.preset_error", ["path": url.lastPathComponent]))
        return studio.jobSettings
    }

    /// A notice of the watched folder: shown on the settings page and on the phone.
    private func watchSay(_ text: String) {
        watchNote = text
        phone.say(text)
    }

    /// _job_finished: a job of the folder ended – done, its best sketch exported in the chosen formats, the image
    /// moved into "done" if wanted.
    internal func watchFinished(_ snapshot: QueueSnapshot) {
        for job in snapshot.jobs where [.done, .failed, .cancelled].contains(job.status) {
            guard let image = folderWatcher.jobs.removeValue(forKey: job.id), job.status == .done,
                  let dir = job.jobDir
            else { continue }
            #if canImport(ImageIO) && canImport(CoreText)
                Task { await watchExport(dir, image: image) }
            #endif
        }
    }

    #if canImport(ImageIO) && canImport(CoreText)
        /// export_batch for one job: `<image>_<method>.<ext>` in the export folder, as the studio exports it
        /// (1024 px, PDF 15 cm wide, the sketch's colours, square).
        internal func watchExport(_ dir: URL, image: URL) async {
            let config = watchConfig
            var written = 0
            if let summary = JobFolder.summary(at: dir), let best = JobFolder.bestSketch(summary),
               let svg = try? String(contentsOf: best, encoding: .utf8)
            {
                let folder = config.exportFolder
                try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                for fmt in config.formats {
                    guard let format = ExportOptions.Format(rawValue: fmt) else { continue }
                    let file = FolderWatch.exportFile(target: summary.target.isEmpty ? dir.path : summary.target,
                                                      method: summary.method, format: fmt, in: folder)
                    let request = ExportRequest(
                        format: format, svg: svg, runDir: nil, jobDir: dir, photo: nil, options: ExportOptions(),
                        mode: .strokes, length: 2, hold: 1, title: file.deletingPathExtension().lastPathComponent,
                        labels: (texts.tr("ui.layer.background"), texts.tr("ui.layer.object")), stylist: .plain)
                    do {
                        try await runExport(request, to: file)
                        written += 1
                    } catch {
                        watchSay(texts.tr("ui.watch.export_error", ["name": image.lastPathComponent,
                                                                     "error": String(describing: error)]))
                    }
                }
            }
            if config.moveDone, FileManager.default.fileExists(atPath: image.path) {
                FolderWatch.moveDone(image)
            }
            watchSay(texts.tr("ui.watch.done", ["name": image.lastPathComponent, "n": String(written)]))
        }
    #endif
}
