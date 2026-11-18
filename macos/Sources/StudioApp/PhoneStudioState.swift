import Foundation
import StudioCore

#if canImport(ImageIO)
    import ImageIO
#endif

/// The studio as the phone page reads it (PhoneApi.get_studio and its neighbours), from the Mac app's state. What the
/// Mac app does not have yet answers as the studio does when there is nothing of it (no hints, no history, no
/// download running, …).
public extension AppModel {
    /// get_studio: everything the page shows of the studio.
    /// `models`: the engine's model_roles for the studio's settings (what is missing).
    func phoneStudio(models roles: JSONObject? = nil) -> JSONObject {
        let missing = roles?["missing"]?.arrayValue?.compactMap(\.stringValue) ?? []
        let missingMB = Double(missing.reduce(0) { $0 + (catalog.spec($1)?.downloadSize ?? 0) }) / 1e6
        let byMethod = roles?["methods"]?.objectValue ?? [:]
        let method = studio.method
        let values = studio.settings
        let params = (studio.methodSchema?.params ?? []).filter { $0.kind != .path && !$0.hidden }
        let jobs = queueSnapshot?.jobs ?? []
        let job = jobs.first { $0.isActive }
        let seeds = phoneSeeds()
        let shown = phoneShownSeed()
        var image: JSONValue = .null
        if let url = studio.image, let size = Self.pixelSize(url) {
            let stamp = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
            image = ["name": .string(url.lastPathComponent), "size": .string("\(size.width)×\(size.height)"),
                     "rev": .string(String(format: "%.0f", stamp?.timeIntervalSince1970 ?? 0)
                         + "-\(abs(url.path.hashValue) % 100_000_000)")]
        }
        let canvas = settings
        return [
            "method": .string(method),
            "methods": .array(RemoteAccess.methods.filter { schema.method($0) != nil }.map {
                ["key": .string($0), "name": .string(schema.method($0)?.name ?? $0),
                 "missing": .bool(byMethod[$0]?.truthy ?? false)]
            }),
            "missing": .array(missing.map { .string(models.name($0)) }),
            "missing_mb": .int(Int(missingMB.rounded(.toNearestOrEven))),
            "preset": .string(studio.preset ?? ""), "user_preset": "", "user_presets": [],
            "settings": .object(JSONObject(params.map { ($0.key, values[$0.key] ?? .null) })),
            "enabled": .object(JSONObject(params.map { ($0.key, .bool(studio.isEnabled($0.key))) })),
            "estimate": "",
            "image": image,
            "details": ["has": .bool(phoneDetailsKept()), "used": .bool(["clipasso", "controlsketch"].contains(method)),
                        "rev": .int(phone.detailsRev)],
            "busy": .bool(job != nil),
            "paused": .bool(job?.status == .paused),
            "running_here": .bool(job != nil && job?.id == studio.live.jobID),
            "running": job.map { j in
                let m = j.settings["method"]?.stringValue ?? "clipasso"
                return ["name": .string(j.target.lastPathComponent), "progress": .double(Self.round4(j.progress)),
                        "method": .string(schema.method(m)?.name ?? m)]
            } ?? .null,
            "queue": .int(jobs.filter { $0.status == .queued }.count),
            "status": .string(studio.live.message),
            "progress": .double(Self.round4(studio.live.progress)),
            "stats": [],
            "view": .string(studio.result?.jobDir.lastPathComponent ?? studio.live.jobDir?.lastPathComponent ?? ""),
            "seeds": .array(seeds.map { s in
                ["seed": .int(s.seed), "caption": .string(s.caption), "best": .bool(s.best), "rev": .int(s.rev)]
            }),
            "shown": shown.map(JSONValue.int) ?? .null,
            "live_rev": .int(shown.flatMap { seed in seeds.first { $0.seed == seed }?.rev } ?? 0),
            "can_continue": false,
            "rating": .null, "can_rate": false,
            "taste": ["up": 0, "down": 0, "need": 0],
            "style": .string(canvas["canvas_style"]?.stringValue ?? "plain"),
            "paper": .string(canvas["canvas_paper"]?.stringValue ?? "none"),
            "note": phone.note.isEmpty ? .null : ["id": .int(phone.noteID), "text": .string(phone.note)],
            "scene": .null, "download": phoneDownloadState(),
            "mask": phoneMask(),
            "edit": .null, "views": [:], "hints": [],
            "vignette": .bool(canvas["canvas_vignette"]?.truthy ?? false),
            "history_n": 0,
            "paper_color": .string(canvas["canvas_paper_color"]?.stringValue ?? ""),
            "version": .string(version),
            "lang": .string(texts.language),
            "theme": .string(canvas.theme),
            "update": .null,
        ]
    }

    /// _mask_state: whether the run uses a mask, whether it is there, the line under the picture.
    private func phoneMask() -> JSONValue {
        let used = studio.isEnabled("mask_model") && studio.image != nil
        let ready = used && (mask.state == .ready || mask.state == .edited)
        return ["used": .bool(used), "ready": .bool(ready),
                "text": .string(used ? mask.status(texts, name: modelName(mask.model)) : "")]
    }

    /// Whether a detail map is kept for the studio's picture – asked of the engine again when the picture changed.
    private func phoneDetailsKept() -> Bool {
        if phone.detailsImage != studio.image {
            phone.detailsImage = studio.image
            phone.detailsHas = false
            Task { await phoneDetailsChanged() }
        }
        return phone.detailsHas
    }

    /// A sketch of the studio the phone can choose: the finished job's runs, else the running job's items.
    struct PhoneSeed {
        let seed: Int
        let caption: String
        let best: Bool
        let rev: Int
        /// the run's folder (finished) or its SVG (running)
        let runDir: URL?
        let svg: String?
    }

    func phoneSeeds() -> [PhoneSeed] {
        if let result = studio.result {
            return result.runs.map { run in
                let stamp = (try? FileManager.default.attributesOfItem(atPath: run.runDir.path))?[.modificationDate]
                    as? Date
                return PhoneSeed(seed: run.seed, caption: run.name, best: run.name == result.bestRun,
                                 rev: abs("\(run.runDir.path)\(stamp?.timeIntervalSince1970 ?? 0)".hashValue) % 10_000_000_000,
                                 runDir: run.runDir, svg: nil)
            }
        }
        return studio.live.sketches.map {
            PhoneSeed(seed: $0.seed, caption: "", best: false, rev: abs($0.svg.hashValue) % 10_000_000_000, runDir: nil,
                      svg: $0.svg)
        }
    }

    /// The sketch shown: the one chosen of the finished job, else the item being computed.
    func phoneShownSeed() -> Int? {
        if let result = studio.result { return result.runs.first { $0.name == result.selected }?.seed }
        return studio.live.sketches.last?.seed
    }

    /// _seed_svg: the sketch of `seed` (nil: the shown one); nil when there is none.
    func phoneSketch(_ seed: Int?) -> String? {
        let wanted = seed ?? phoneShownSeed()
        guard let item = phoneSeeds().first(where: { $0.seed == wanted }) else { return nil }
        if let svg = item.svg { return svg }
        guard let dir = item.runDir else { return nil }
        return SketchEditor.load(runDir: dir)?.svg
    }

    /// The studio's look of a sketch (_look): its brush style, its paper and the background colour.
    func phoneLook() -> (style: String, paper: Paper?, background: String) {
        let style = settings["canvas_style"]?.stringValue ?? "plain"
        let paper = Paper.normalize(kind: settings["canvas_paper"]?.stringValue,
                                    vignette: .double(settings["canvas_vignette"]?.truthy == true ? 0.35 : 0))
        let colour = settings["canvas_paper_color"]?.stringValue ?? ""
        let background = paper != nil || !colour.isEmpty ? Paper.colour(of: paper, background: colour.isEmpty ? nil : colour)
            : "#FFFFFF"
        return (schema.brushStyles.contains(style) ? style : "plain", paper, background)
    }

    /// The recent pictures (that are still there) and the samples, as get_images lists them.
    func phoneImages(_ source: String) -> [URL]? {
        switch source {
        case "recent":
            return (settings["recent_images"]?.arrayValue ?? []).compactMap(\.stringValue)
                .filter { FileManager.default.fileExists(atPath: $0) }.map { URL(filePath: $0) }
        case "sample":
            guard let dir = resources.web?.appending(path: "samples"),
                  let names = try? FileManager.default.contentsOfDirectory(atPath: dir.path)
            else { return [] }
            return names.filter { [".png", ".jpg", ".jpeg"].contains(where: $0.lowercased().hasSuffix) }
                .map { dir.appending(path: $0).path }.sorted().map { URL(filePath: $0) }
        default:
            return nil
        }
    }

    /// The studio's answers of R4b: the studio's state, a sketch chosen, a sketch in the studio's look, the pictures
    /// to choose from. nil: not one of them.
    func phoneStudioAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
        func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
        switch action {
        case "get_studio":
            return .json(.object(phoneStudio(models: await phoneModelRoles())))
        case "do_select":
            guard let seed = data["seed"].flatMap({ PhoneStudio.int($0) }) else { return no("unknown sketch") }
            guard let result = studio.result, let run = result.runs.first(where: { $0.seed == seed }) else {
                return no(texts.tr("ui.phone.page.no_sketch"))
            }
            result.select(run.name)
            return .json(["ok": true])
        case "file_sketch":
            let seed = data["seed"].flatMap { $0 == "" ? nil : PhoneStudio.int($0) }
            guard let svg = phoneSketch(seed) else { return no(texts.tr("ui.phone.page.no_sketch")) }
            let look = phoneLook()
            let stylist = stylist(look.style)
            let full = data["full"]?.truthy == true
            let made = await Task.detached(executorPreference: OwnThreads.shared) { () -> String in
                var out = SketchExport.restyleSVG(svg, background: look.background)
                out = (try? stylist(out)) ?? out
                #if canImport(ImageIO)
                    if full, look.paper != nil {
                        out = PaperPicture.svgWithPaper(out, paper: look.paper, background: look.background)
                    }
                #endif
                return out
            }.value
            return .bytes(Data(made.utf8), type: "image/svg+xml", name: nil)
        case "get_images":
            let recent = phoneImages("recent") ?? [], samples = phoneImages("sample") ?? []
            return .json(["recent": .array(recent.enumerated().map {
                              ["i": .int($0.offset), "name": .string($0.element.lastPathComponent)]
                          }),
                          "samples": .array(samples.enumerated().map {
                              ["i": .int($0.offset), "name": .string($0.element.deletingPathExtension().lastPathComponent)]
                          })])
        case "do_image", "file_image":
            guard let list = phoneImages(data["src"]?.stringValue ?? "") else { return no("unknown source") }
            guard let i = data["i"].flatMap({ PhoneStudio.int($0) }), list.indices.contains(i) else {
                return no(texts.tr("ui.phone.page.no_picture"))
            }
            if action == "do_image" {
                studio.image = list[i]
                return .json(["ok": true])
            }
            guard let jpeg = await Self.phoneJPEG(list[i], side: 240) else { return no(texts.tr("ui.phone.page.no_picture")) }
            return .bytes(jpeg, type: "image/jpeg", name: nil)
        default:
            return nil
        }
    }

    nonisolated static func round4(_ x: Double) -> Double { (x * 10000).rounded(.toNearestOrEven) / 10000 }

    /// A picture's size in pixels, upright (nil: no picture).
    nonisolated static func pixelSize(_ url: URL) -> (width: Int, height: Int)? {
        #if canImport(ImageIO)
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let p = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let w = p[kCGImagePropertyPixelWidth] as? Int, let h = p[kCGImagePropertyPixelHeight] as? Int
            else { return nil }
            let turned = [5, 6, 7, 8].contains(p[kCGImagePropertyOrientation] as? Int ?? 1)
            return turned ? (h, w) : (w, h)
        #else
            return nil
        #endif
    }
}
