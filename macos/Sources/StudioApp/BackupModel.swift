import Foundation
import StudioCore

/// Backup & move in the app (gui/backup_ui.py): what a backup would hold, writing one, putting one back.
public extension AppModel {
    /// The queue's entries as settings.json keeps them (controller.QueuedJob.to_json): waiting, failed, cancelled.
    var backupQueueItems: [JSONObject] {
        (queueSnapshot?.jobs ?? []).filter { [.queued, .failed, .cancelled, .interrupted].contains($0.status) }.map { job in
            var item: JSONObject = ["target": .string(job.target.path), "settings": .object(job.settings)]
            if let resume = job.resumeDir { item["resume_dir"] = .string(resume.path) }
            if [.failed, .cancelled].contains(job.status) {
                item["status"] = .string(job.status.rawValue)
                item["job_dir"] = .string(job.jobDir?.path ?? "")
                item["message"] = .string(job.message)
            }
            return item
        }
    }

    /// sizes: the gallery's results and bytes, the queue's pictures and the downloaded models (bytes).
    func backupSizes() async -> (jobs: Int, gallery: Int64, queue: Int, models: Int64) {
        let out = settings.outputDir, models = modelsDir
        let queue = backupQueueItems.count
        return await Task.detached {
            let entries = Backup.resultEntries(out)
            let gallery = entries.reduce(Int64(0)) { sum, name in
                sum + Backup.files(out.appending(path: name)).reduce(0) { $0 + Backup.size($1.0) }
            }
            let modelBytes = Backup.files(models).filter { !$0.1.hasPrefix(".partial") }.reduce(Int64(0)) {
                $0 + Backup.size($1.0)
            }
            return (entries.filter { !$0.hasPrefix("_") }.count, gallery, queue, modelBytes)
        }.value
    }

    /// create: the backup written to `url` off the main actor; `progress` hears (done, all) in bytes.
    func createBackup(to url: URL, includeModels: Bool,
                      progress: @escaping @Sendable (Int64, Int64) -> Void = { _, _ in }) async throws
    {
        let data = settings.data, queue = backupQueueItems, out = settings.outputDir, models = modelsDir
        let version = version
        let work = Task.detached {
            _ = try Backup.create(url, settings: data, queue: queue, outputDir: out, modelsDir: models,
                                  includeModels: includeModels, version: version, progress: progress)
        }
        try await withTaskCancellationHandler { try await work.value } onCancel: { work.cancel() }
    }

    /// restore: the chosen parts put back – the settings saved (the language at once), the gallery read again, the
    /// queue's entries added (failed or cancelled ones as such, not started: "Try again" is theirs), the models
    /// counted again. Refused
    /// while a job runs (ui.backup.busy).
    func restoreBackup(from url: URL, parts: Set<String>,
                       progress: @escaping @Sendable (Int64, Int64) -> Void = { _, _ in }) async throws -> Backup.Report
    {
        if queueSnapshot?.jobs.contains(where: \.isActive) ?? false {
            throw Backup.Failure(description: texts.tr("ui.backup.busy"))
        }
        let data = settings.data
        let known = backupQueueItems.map { ($0["target"]?.stringValue ?? "", $0["settings"]?.objectValue ?? [:]) }
        let out = settings.outputDir, modelsFolder = modelsDir
        let inputs = store.url.deletingLastPathComponent().appending(path: "restored_inputs", directoryHint: .isDirectory)
        let work = Task.detached { () throws -> (Backup.Report, JSONObject) in
            var changed = data
            let report = try Backup.restore(url, parts: parts, settings: &changed, outputDir: out, modelsDir: modelsFolder,
                                            inputsDir: inputs, known: known, progress: progress)
            return (report, changed)
        }
        let (report, changed) = try await withTaskCancellationHandler { try await work.value } onCancel: { work.cancel() }
        if report.settings {
            updateSettings { s in
                for (key, value) in changed { s[key] = value }
            }
            try? setLanguage(settings.language)
        }
        if let queue {
            for item in report.queue {
                guard let target = item["target"]?.stringValue, let s = item["settings"]?.objectValue else { continue }
                let resume = item["resume_dir"]?.stringValue.flatMap { $0.isEmpty ? nil : URL(filePath: $0) }
                if let status = item["status"]?.stringValue {  // (failed or cancelled: kept as such, not started)
                    let dir = item["job_dir"]?.stringValue.flatMap { $0.isEmpty ? nil : URL(filePath: $0) }
                    await queue.addEnded(target: URL(filePath: target), settings: s,
                                         status: QueuedJob.Status(rawValue: status) ?? .failed, jobDir: dir,
                                         message: item["message"]?.stringValue ?? "", resumeDir: resume)
                } else if let resume = item["resume_dir"]?.stringValue, !resume.isEmpty {
                    await queue.addContinuation(jobDir: URL(filePath: resume), target: URL(filePath: target), settings: s)
                } else {
                    _ = await queue.add(target: URL(filePath: target), settings: s)
                }
            }
            apply(await queue.snapshot())
        }
        await gallery.refresh()
        models.revision += 1
        return report
    }
}
