import Foundation
import StudioCore

/// An export started from the phone (PhoneApi._exports): it runs in the background, the phone asks for its state and
/// then downloads the file; the last few stay to be downloaded.
public final class PhoneExportJob {
    public let id: String
    public let fmt: String
    public let name: String
    public let file: URL
    let started = Date()
    var status = "running"
    var done = 0
    var total = 0
    var error = ""
    var task: Task<Void, Never>?

    init(id: String, fmt: String, name: String, file: URL) {
        (self.id, self.fmt, self.name, self.file) = (id, fmt, name, file)
    }

    var dir: URL { file.deletingLastPathComponent() }
}

#if canImport(ImageIO) && canImport(CoreText)
    public extension AppModel {
        /// export_root: where the phone's exports wait to be downloaded.
        var phoneExportRoot: URL {
            store.url.deletingLastPathComponent().appending(path: "phone_exports", directoryHint: .isDirectory)
        }

        /// _export_source: the shown sketch, its run (the job for the matrix) and the name of its file.
        private func phoneExportSource(_ fmt: String) -> (svg: String, runDir: URL?, jobDir: URL?, name: String)? {
            guard let result = studio.result else { return nil }
            if fmt == "matrix" {
                guard result.method == "scenesketch", result.runs.count > 1 else { return nil }
                return (result.editor?.svg ?? "", nil, result.jobDir, result.jobDir.lastPathComponent)
            }
            guard let run = result.runs.first(where: { $0.name == result.selected }), let svg = result.editor?.svg
            else { return nil }
            return (svg, run.runDir, result.jobDir, run.runDir.lastPathComponent)
        }

        /// export_jobs.info: what the sketch offers for the animations.
        nonisolated static func phoneSketchInfo(_ svg: String, runDir: URL?) -> PhoneExport.Sketch {
            let frames = runDir.map { SketchAnimation.steps(runDir: $0).count } ?? 0
            let drawing = Drawing(svg: svg, keepOrder: true)
            let length = SketchAnimation.defaultDrawingLength(strokes: drawing.strokeCount, line: drawing.line)
            return PhoneExport.Sketch(processFrames: frames, strokes: svg.components(separatedBy: "<path").count - 1,
                                      drawLength: (length * 10).rounded(.toNearestOrEven) / 10,
                                      processLength: SketchAnimation.defaultProcessLength(frames),
                                      photoFrame: runDir.flatMap { SketchFraming.runFrame(runDir: $0) } != nil)
        }

        /// The answers of R6b; nil: not one of them.
        func phoneExportAnswer(_ action: String, _ data: JSONObject) async -> RemoteAnswer? {
            func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
            let gone = texts.tr("ui.phone.page.export_gone")
            switch action {
            case "get_export_info":
                guard let source = phoneExportSource("svg") else { return no(texts.tr("ui.phone.page.no_sketch")) }
                let sketch = Self.phoneSketchInfo(source.svg, runDir: source.runDir)
                let layers = SketchFormats.objectStrokes(runDir: source.runDir) != nil
                let formats = PhoneExport.formats.filter {
                    ($0 != "matrix" || phoneExportSource("matrix") != nil) && ($0 != "svglayers" || layers)
                }
                return .json(["ok": true, "name": .string(source.name), "sketch": .object(sketch.json),
                              "formats": .array(formats.map { f in
                                  ["fmt": .string(f), "title": .string(PhoneExport.title(f, texts: texts)),
                                   "desc": .string(texts.tr("ui.export_desc.\(f)")),
                                   "ext": .string(PhoneExport.fileExtension(f)),
                                   "applies": .object(PhoneExport.applies(f, processFrames: sketch.processFrames)),
                                   "defaults": .object(PhoneExport.defaults(f, sketch: sketch, settings: settings))]
                              }),
                              "styles": .array(schema.brushStyles.map {
                                  ["key": .string($0), "label": .string(texts.tr("ui.brush.\($0)"))]
                              }),
                              "papers": .array(Paper.Kind.allCases.map {
                                  ["key": .string($0.rawValue), "label": .string(texts.tr("ui.paper.\($0.rawValue)"))]
                              }),
                              "frames": .array(["square", "photo", "content"].map {
                                  ["key": .string($0), "label": .string(texts.tr("ui.frame.\($0)")),
                                   "ok": .bool($0 != "photo" || sketch.photoFrame)]
                              }),
                              "last": settings["export_last_format"] ?? "png"])
            case "do_export":
                return await phoneStartExport(data)
            case "get_export":
                guard let e = phone.exports[PhoneStudio.pyStr(data["id"] ?? "")] else { return no(gone) }
                let size = e.status == "done" ? (try? FileManager.default.attributesOfItem(atPath: e.file.path))?[.size]
                    as? Int ?? 0 : 0
                return .json(["ok": true, "status": .string(e.status), "done": .int(e.done), "total": .int(e.total),
                              "name": .string(e.name), "size": .int(size), "error": .string(e.error)])
            case "file_export":
                guard let e = phone.exports[PhoneStudio.pyStr(data["id"] ?? "")], e.status == "done",
                      FileManager.default.fileExists(atPath: e.file.path)
                else { return no(gone) }
                let type = PhoneExport.contentTypes[PhoneExport.fileExtension(e.fmt)] ?? "application/octet-stream"
                return .file(e.file, type: type, name: e.name)
            case "do_cancel_export":
                guard let e = phone.exports[PhoneStudio.pyStr(data["id"] ?? "")] else { return no(gone) }
                e.task?.cancel()
                return .json(["ok": true])
            default:
                return nil
            }
        }

        /// do_export: the shown sketch exported in the background with the phone's options (made safe and kept for the
        /// next export).
        private func phoneStartExport(_ data: JSONObject) async -> RemoteAnswer {
            func no(_ why: String) -> RemoteAnswer { .json(["ok": false, "error": .string(why)]) }
            guard let fmt = data["fmt"]?.stringValue, PhoneExport.formats.contains(fmt),
                  let format = ExportOptions.Format(rawValue: fmt)
            else { return no("unknown format") }
            guard let source = phoneExportSource(fmt) else { return no(texts.tr("ui.phone.page.no_sketch")) }
            if fmt == "svglayers", SketchFormats.objectStrokes(runDir: source.runDir) == nil {
                return no(texts.tr("ui.layer.not_yet"))
            }
            let sketch = source.svg.isEmpty
                ? PhoneExport.Sketch(processFrames: 0, strokes: 0, drawLength: 2, processLength: 2, photoFrame: false)
                : Self.phoneSketchInfo(source.svg, runDir: source.runDir)
            let options = PhoneExport.check(fmt, data["options"], sketch: sketch, settings: settings,
                                            styles: schema.brushStyles)
            _ = updateSettings { PhoneExport.remember(fmt, options, in: &$0) }
            phoneCleanExports()
            let id = (0 ..< 6).map { _ in String(format: "%02x", UInt8.random(in: 0 ... 255)) }.joined()
            let name = "\(source.name)\(PhoneExport.suffix(fmt)).\(PhoneExport.fileExtension(fmt))"
            let folder = phoneExportRoot.appending(path: id, directoryHint: .isDirectory)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            } catch {
                return no(String(describing: error))
            }
            let job = PhoneExportJob(id: id, fmt: fmt, name: name, file: folder.appending(path: name))
            phone.exports[id] = job
            let export = PhoneExport.options(fmt, options)
            let request = ExportRequest(
                format: format, svg: source.svg, runDir: source.runDir, jobDir: source.jobDir,
                photo: source.runDir.flatMap { SketchFraming.runFrame(runDir: $0) }, options: export,
                mode: SketchAnimation.Mode(rawValue: options["mode"]?.stringValue ?? "") ?? .strokes,
                length: options["length"]?.doubleValue ?? 2, hold: options["hold"]?.doubleValue ?? 1,
                title: job.file.deletingPathExtension().lastPathComponent,
                labels: (texts.tr("ui.layer.background"), texts.tr("ui.layer.object")),
                stylist: fmt == "svg1" || fmt == "lottie" ? .plain : stylist(export.style))
            job.task = Task { [weak self, weak job] in
                guard let self, let job else { return }
                let (stream, progress) = AsyncStream.makeStream(of: (Int, Int).self)
                let watch = Task { for await (a, b) in stream { (job.done, job.total) = (a, b) } }
                do {
                    try await runExport(request, to: job.file) { progress.yield(($0, $1)) }
                    job.status = FileManager.default.fileExists(atPath: job.file.path) ? "done" : "failed"
                } catch is CancellationError {
                    job.status = "cancelled"
                } catch let error as ExportError {
                    (job.status, job.error) = ("failed", texts.tr("ui.err.\(error.code)"))
                } catch {
                    (job.status, job.error) = (Task.isCancelled ? "cancelled" : "failed", String(describing: error))
                }
                progress.finish()
                watch.cancel()
                if job.status == "cancelled" { try? FileManager.default.removeItem(at: job.file) }
                phone.changed()
            }
            return .json(["ok": true, "id": .string(id), "name": .string(name)])
        }

        /// _clean_exports: the older exports go (the last three stay to be downloaded), and what an earlier start of
        /// the app left.
        private func phoneCleanExports(keep: Int = 3) {
            let finished = phone.exports.values.filter { $0.status != "running" }.sorted { $0.started < $1.started }
            for e in finished.dropLast(keep) {
                try? FileManager.default.removeItem(at: e.dir)
                phone.exports[e.id] = nil
            }
            let names = (try? FileManager.default.contentsOfDirectory(atPath: phoneExportRoot.path)) ?? []
            for name in names where phone.exports[name] == nil {
                try? FileManager.default.removeItem(at: phoneExportRoot.appending(path: name))
            }
        }
    }
#endif
