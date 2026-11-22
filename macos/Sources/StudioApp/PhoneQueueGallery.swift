import Foundation
import StudioCore

/// The queue and the results from the phone (PhoneApi: get_queue … do_retry, get_results … do_delete), on the Mac
/// app's queue and gallery. A job is known to the page by a number of its own (PhoneRemote.number).
public extension AppModel {
    /// RESULTS_MAX: the newest results a list by place ("i") reaches
    static let phoneResultsMax = 40

    /// The answers of R5; nil: not one of them.
    func phoneQueueAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let ok: RemoteAnswer = .json(["ok": true])
        let changed = texts.tr("ui.phone.page.list_changed")
        switch action {
        // ---------------------------------------------------------------- the queue
        case "get_queue":
            return .json(.object(phoneQueue()))
        case "do_queue_options":
            if let on = data["auto_start"] { await queuePage?.setAutoStart(on.truthy) }
            if let action = data["done_action"]?.stringValue.flatMap(WhenDone.init(rawValue:)) {
                await queuePage?.setWhenDone(action)
            }
            return ok
        case "do_run_next", "do_move":
            guard let job = phoneJob(data), job.status == .queued else { return no(changed) }
            let jobs = queueSnapshot?.jobs ?? []
            let index: Int
            if action == "do_run_next" {  // (to the front: behind the running ones before it)
                let mine = jobs.firstIndex { $0.id == job.id } ?? 0
                index = jobs.prefix(mine).filter(\.isActive).count
            } else {
                guard let i = data["index"].flatMap({ PhoneStudio.int($0) }) else {
                    return no(texts.tr("ui.phone.page.bad_value"))
                }
                index = i
            }
            await queuePage?.move(job.id, to: index)
            return ok
        case "do_load_job":
            guard let job = phoneJob(data) else { return no(changed) }
            guard FileManager.default.fileExists(atPath: job.target.path) else {
                return no(texts.tr("ui.phone.page.no_picture"))
            }
            studio.image = job.target
            studio.adopt(job.settings)
            return ok
        case "do_retry":
            guard let job = phoneJob(data), [.failed, .cancelled, .interrupted].contains(job.status), let queuePage
            else { return no(changed) }
            await queuePage.retry(job)
            return ok
        case "do_remove":
            guard let n = data["id"].flatMap({ PhoneStudio.int($0) }) else { return no("unknown job") }
            if let id = phone.job(n) { await queuePage?.remove(id) }
            return ok
        case "do_clear_queue":
            let before = queuePage?.jobs.count ?? 0
            await queuePage?.removeFinished()
            return .json(["ok": true, "removed": .int(before - (queuePage?.jobs.count ?? 0))])
        case "do_live":
            guard queueSnapshot?.jobs.contains(where: \.isActive) == true else {
                return no(texts.tr("ui.phone.page.no_live"))
            }
            studio.showLive()
            return ok
        case "do_continue":
            guard let result = studio.result, let summary = JobFolder.summary(at: result.jobDir),
                  JobFolder.canContinue(summary), let queue
            else { return no(texts.tr("ui.phone.page.cannot_continue")) }
            await queue.addContinuation(jobDir: result.jobDir, target: URL(filePath: summary.target),
                                        settings: summary.settings)
            return ok
        // ---------------------------------------------------------------- the results
        case "get_results":
            await gallery.refresh()
            return .json(.object(phoneResults(data)))
        case "file_result":
            guard let item = phoneResult(data, byPlace: data["i"] != nil || data["d"] == nil),
                  let sketch = item.bestSketch, let svg = try? String(contentsOf: sketch, encoding: .utf8)
            else { return no(texts.tr("ui.phone.page.no_sketch")) }
            let shaped = SketchFraming.stretchedForDisplay(svg, stretch: canvasStretch(runDir: Self.bestRunDir(item)))
            return .bytes(Data(shaped.utf8), type: "image/svg+xml", name: nil)
        case "do_open":
            guard let item = phoneResult(data) else { return no(changed) }
            studio.open(item)
            return ok
        case "do_fav":
            guard let item = phoneResult(data) else { return no(changed) }
            await gallery.setFavourite(item, data["value"]?.truthy ?? false)
            return ok
        case "do_info":
            guard let item = phoneResult(data) else { return no(changed) }
            var tags: [String]
            if let text = data["tags"]?.stringValue {
                tags = text.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
            } else {
                tags = (data["tags"]?.arrayValue ?? []).map(PhoneStudio.pyStr)
            }
            tags = Array(tags.map { String($0.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40)) }
                .filter { !$0.isEmpty }.prefix(30))
            do {
                try await gallery.setInfo(item, title: String(PhoneStudio.pyStr(data["title"] ?? "").prefix(120)),
                                          tags: tags, notes: String(PhoneStudio.pyStr(data["notes"] ?? "").prefix(4000)))
            } catch {
                return no(String(describing: error))
            }
            return ok
        case "do_album":
            return await phoneAlbum(data)
        case "do_continue_result":
            guard let item = phoneResult(data) else { return no(changed) }
            guard item.canContinue else { return no(texts.tr("ui.resume.nothing")) }
            await queuePage?.continueJob(item)
            return ok
        case "do_delete":
            guard let item = phoneResult(data) else { return no(changed) }
            let name = item.jobDir.lastPathComponent
            if phoneActiveDirs().contains(item.jobDir.standardizedFileURL.path) {
                return no(texts.tr("ui.gallery.delete_active", ["name": name]))
            }
            do {
                try FileManager.default.trashItem(at: item.jobDir, resultingItemURL: nil)
            } catch {
                return no(texts.tr("ui.phone.page.not_deleted", ["name": name]))
            }
            await gallery.refresh()
            return ok
        default:
            return nil
        }
    }

    // MARK: - the queue

    /// get_queue: the jobs with what they change of their method's defaults, the queue's own switches.
    func phoneQueue() -> JSONObject {
        let jobs = queueSnapshot?.jobs ?? []
        let t = texts
        func shown(_ v: JSONValue) -> String {
            if case .bool(let b) = v { return t.tr(b ? "ui.on" : "ui.off") }
            return PhoneStudio.pyStr(v)
        }
        let out: [JSONValue] = jobs.map { j in
            let method = j.settings["method"]?.stringValue ?? "clipasso"
            let m = schema.method(method)
            var changes: [JSONValue] = []
            for (key, standard) in m?.defaults ?? [:] {
                let value = j.settings[key] ?? .null
                guard !Condition.pyEquals(value, standard) else { continue }
                let label = m?.param(key)?.text.label ?? "param.\(key).label"
                changes.append(["name": .string(t.tr(label)), "value": .string(shown(value)),
                                "default": .string(shown(standard))])
            }
            return ["id": .int(phone.number(j.id)), "name": .string(j.target.lastPathComponent),
                    "status": .string(j.status.rawValue), "method": .string(m?.name ?? method),
                    "progress": .double((j.progress * 1000).rounded(.toNearestOrEven) / 1000),
                    "changes": .array(changes), "message": .string(j.status == .failed ? j.message : ""),
                    "can_load": .bool(FileManager.default.fileExists(atPath: j.target.path))]
        }
        let running = jobs.first { $0.isActive }
        return ["jobs": .array(out), "auto_start": .bool(queueSnapshot?.autoStart ?? true),
                "remaining": .string(running?.eta.map { PhoneRemote.eta($0) } ?? ""),
                "done_action": .string(queuePage?.whenDone.rawValue ?? "nothing"),
                "done_actions": .array(WhenDone.allCases.map {
                    ["key": .string($0.rawValue), "name": .string(texts.tr("ui.queue.done_\($0.rawValue)"))]
                })]
    }

    /// The job of the number the page sent (nil: none – the list changed meanwhile).
    func phoneJob(_ data: JSONObject) -> QueuedJob? {
        guard let n = data["id"].flatMap({ PhoneStudio.int($0) }), let id = phone.job(n) else { return nil }
        return queueSnapshot?.jobs.first { $0.id == id }
    }

    /// The folders of the jobs the queue works on (never deleted from the phone).
    func phoneActiveDirs() -> Set<String> {
        Set((queueSnapshot?.jobs ?? []).filter(\.isActive).compactMap { $0.jobDir?.standardizedFileURL.path })
    }

    // MARK: - the results

    /// Every result with a sketch, the newest first (_all_results).
    func phoneAllResults() -> [GalleryItem] {
        GalleryQuery(sort: .newest).sorted(gallery.everything.filter {
            $0.bestSketch.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        })
    }

    /// _result: a result by its folder's name – or by its place among the newest, its name checked.
    func phoneResult(_ data: JSONObject, byPlace: Bool? = nil) -> GalleryItem? {
        let all = phoneAllResults()
        let name = data["dir"]?.stringValue ?? data["d"]?.stringValue ?? ""
        if !(byPlace ?? (data["i"] != nil)) {
            return name.isEmpty ? nil : all.first { $0.jobDir.lastPathComponent == name }
        }
        let newest = Array(all.prefix(Self.phoneResultsMax))
        guard let i = data["i"].flatMap({ PhoneStudio.int($0) }), newest.indices.contains(i) else { return nil }
        if !name.isEmpty, newest[i].jobDir.lastPathComponent != name { return nil }
        return newest[i]
    }

    /// get_results: a page of the results, searched and filtered, with the albums, tags, sorts and methods.
    func phoneResults(_ data: JSONObject) -> JSONObject {
        let items = phoneAllResults()
        let q = PhoneStudio.pyStr(data["q"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let method = PhoneStudio.pyStr(data["method"] ?? ""), album = PhoneStudio.pyStr(data["album"] ?? "")
        let tag = PhoneStudio.pyStr(data["tag"] ?? "")
        let fav = ["1", "true"].contains(PhoneStudio.pyStr(data["fav"] ?? ""))
        let kept = items.filter { it in
            (method.isEmpty || it.method == method) && (!fav || it.favourite)
                && (album.isEmpty || it.albums.contains(album)) && (tag.isEmpty || it.tags.contains(tag))
                && (q.isEmpty || ([it.name, it.notes] + it.tags).joined(separator: " ").lowercased().contains(q))
        }
        let sort = GallerySort(rawValue: PhoneStudio.pyStr(data["sort"] ?? "newest")) ?? .newest
        let shown = GalleryQuery(sort: sort).sorted(kept)
        let offset = max(0, data["offset"].flatMap { PhoneStudio.int($0) } ?? 0)
        let limit = min(100, max(1, data["limit"].flatMap { PhoneStudio.int($0) } ?? Self.phoneResultsMax))
        let active = phoneActiveDirs()
        let page = shown.dropFirst(offset).prefix(limit)
        let results: [JSONValue] = page.enumerated().map { k, it in
            ["i": .int(offset + k), "name": .string(it.name), "method": .string(it.methodName),
             "created": .string(it.created), "method_key": .string(it.method),
             "score": it.score.map { .double(($0 * 10).rounded(.toNearestOrEven) / 10) } ?? .null,
             "fav": .bool(it.favourite), "albums": .array(it.albums.map(JSONValue.string)),
             "dir": .string(it.jobDir.lastPathComponent), "title": .string(it.summary.title),
             "tags": .array(it.tags.map(JSONValue.string)), "notes": .string(it.notes),
             "can_continue": .bool(it.canContinue && !active.contains(it.jobDir.standardizedFileURL.path))]
        }
        return ["results": .array(results), "total": .int(shown.count), "offset": .int(offset),
                "albums": .array(phoneAlbumNames(items).map(JSONValue.string)),
                "tags": .array(Set(items.flatMap(\.tags)).sorted { $0.lowercased() < $1.lowercased() }
                    .map(JSONValue.string)),
                "sorts": .array(GallerySort.allCases.map {
                    ["key": .string($0.rawValue), "name": .string(texts.tr("ui.gallery.sort_\($0.rawValue)"))]
                }),
                "methods": .array(schema.methods.map {
                    ["key": .string($0), "name": .string(schema.method($0)?.name ?? $0)]
                })]
    }

    // MARK: - albums (gui/albums.py)

    /// albums.clean: white space as single spaces, at most 60 characters.
    nonisolated static func albumName(_ text: String) -> String {
        String(text.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(60))
    }

    /// albums.names: the albums the app keeps in their order, then those only found in the results.
    func phoneAlbumNames(_ items: [GalleryItem]) -> [String] {
        let stored = (settings["albums"]?.arrayValue ?? []).compactMap(\.stringValue).map(Self.albumName)
            .filter { !$0.isEmpty }
        let seen = Set(stored.map { $0.lowercased() })
        let extra = Set(items.flatMap(\.albums).filter { !seen.contains($0.lowercased()) })
            .sorted { $0.lowercased() < $1.lowercased() }
        return stored + extra
    }

    private func storeAlbums(_ names: [String]) {
        var unique: [String] = []
        for name in names where !unique.contains(name) { unique.append(name) }
        _ = updateSettings { $0["albums"] = .array(unique.map(JSONValue.string)) }
    }

    /// do_album: new (with results or empty), add, remove, rename, delete (the results stay).
    func phoneAlbum(_ data: JSONObject) async -> RemoteAnswer {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        let op = data["op"]?.stringValue ?? ""
        var name = Self.albumName(PhoneStudio.pyStr(data["name"] ?? ""))
        guard !name.isEmpty else { return no(texts.tr("ui.phone.page.album_name")) }
        var chosen: [GalleryItem] = []
        for dir in (data["dirs"]?.arrayValue ?? []).prefix(500) {
            guard let item = phoneResult(["dir": dir]) else { return no(texts.tr("ui.phone.page.list_changed")) }
            chosen.append(item)
        }
        let members = phoneAllResults().filter { $0.albums.contains(name) }
        let stored = (settings["albums"]?.arrayValue ?? []).compactMap(\.stringValue)
        do {
            switch op {
            case "new", "add":
                storeAlbums(stored + [name])
                for item in chosen where !item.albums.contains(name) {
                    try await gallery.setAlbums(item, item.albums + [name])
                }
            case "remove":
                for item in chosen where item.albums.contains(name) {
                    try await gallery.setAlbums(item, item.albums.filter { $0 != name })
                }
            case "rename":
                let new = Self.albumName(PhoneStudio.pyStr(data["new"] ?? ""))
                if !new.isEmpty, new != name {
                    for item in members {
                        var albums: [String] = []
                        for album in item.albums.map({ $0 == name ? new : $0 }) where !albums.contains(album) {
                            albums.append(album)
                        }
                        try await gallery.setAlbums(item, albums)
                    }
                    storeAlbums(stored.map { $0 == name ? new : $0 })
                    name = new
                }
            case "delete":
                for item in members { try await gallery.setAlbums(item, item.albums.filter { $0 != name }) }
                storeAlbums(stored.filter { $0 != name })
            default:
                return no("unknown album action")
            }
        } catch {
            return no(String(describing: error))
        }
        await gallery.refresh()
        return .json(["ok": true, "name": .string(name)])
    }
}
