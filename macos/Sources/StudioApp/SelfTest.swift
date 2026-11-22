import Foundation
import StudioCore

/// `CLIPassoStudio --self-test IMAGE OUTPUT [--models DIR] [--iterations N]`: the app starts its engine as it always
/// does, computes a small CLIPasso job of IMAGE into OUTPUT and checks the sketch it made – so a built .app is known to
/// work (its own Python, PyTorch, the engine, the models). It keeps its settings in OUTPUT, never in the user's.
public enum SelfTest {
    public struct UsageError: Error, CustomStringConvertible {
        public let description: String
    }

    public struct Options: Sendable {
        public static let flag = "--self-test"
        public static let usage = "CLIPassoStudio --self-test IMAGE OUTPUT [--models DIR] [--iterations N]"
        public var image: URL
        public var output: URL
        public var modelsDir: URL?
        public var iterations = 5

        public static func requested(in arguments: [String]) -> Bool {
            arguments.dropFirst().contains(flag)
        }

        public init(arguments: [String]) throws {
            guard let start = arguments.firstIndex(of: Self.flag) else { throw UsageError(description: Self.usage) }
            var rest = Array(arguments[arguments.index(after: start)...])
            var positional: [String] = []
            var models: URL?
            var iterations = 5
            while !rest.isEmpty {
                let item = rest.removeFirst()
                switch item {
                case "--models":
                    guard !rest.isEmpty else { throw UsageError(description: Self.usage) }
                    models = URL(filePath: rest.removeFirst(), directoryHint: .isDirectory)
                case "--iterations":
                    guard !rest.isEmpty, let n = Int(rest.removeFirst()), n > 0 else {
                        throw UsageError(description: Self.usage)
                    }
                    iterations = n
                default:
                    positional.append(item)
                }
            }
            guard positional.count == 2 else { throw UsageError(description: Self.usage) }
            image = URL(filePath: positional[0])
            output = URL(filePath: positional[1], directoryHint: .isDirectory)
            modelsDir = models
            self.iterations = iterations
        }
    }

    public struct Outcome: Sendable {
        public var ok: Bool
        public var lines: [String]
    }

    public static func run(_ options: Options, resources: AppResources,
                           timeout: Duration = .seconds(1800)) async -> Outcome
    {
        var lines: [String] = []
        func fail(_ text: String) -> Outcome {
            lines.append("FAILED: \(text)")
            return Outcome(ok: false, lines: lines)
        }
        let store = SettingsStore(url: options.output.appending(path: "settings.json"), home: options.output)
        var settings = store.load()
        settings.language = "en"
        settings.modelsDir = options.modelsDir
        do {
            try store.save(settings)
        } catch {
            return fail("could not write \(store.url.path): \(error)")
        }
        let model: AppModel
        do {
            model = try AppModel(resources: resources, store: store)
        } catch {
            return fail("the app's own files: \(error)")
        }
        let started = ContinuousClock.now
        await model.startEngine()
        guard model.engineStatus == .ready, let engine = model.engine else {
            return fail(model.engineStatusText)
        }
        lines.append("engine ready after \(started.duration(to: .now)) · models in \(model.modelsDir.path)")
        let result = await compute(options, engine: engine, timeout: timeout)
        let log = await engine.stderrTail().suffix(40)
        await engine.stop()
        switch result {
        case .failure(let problem):
            lines += log.map { "engine: \($0)" }  // what it wrote last (lines naming a secret are never kept)
            return fail(problem.description)
        case .success(let line):
            lines.append(line)
        }
        lines.append("total \(started.duration(to: .now))")
        return Outcome(ok: true, lines: lines)
    }

    private struct Problem: Error, CustomStringConvertible {
        let description: String
    }

    /// The job on the running engine → one line about its sketch.
    private static func compute(_ options: Options, engine: EngineClient, timeout: Duration) async
        -> Result<String, Problem>
    {
        let job: JSONObject = ["method": "clipasso", "num_iter": .int(options.iterations), "num_sketches": 1,
                               "mask_object": false]
        let jobDir: String
        do {
            let answer = try await engine.request("start", ["target": .string(options.image.path),
                                                            "settings": .object(job),
                                                            "output_root": .string(options.output.path)])
            jobDir = answer.objectValue?["job_dir"]?.stringValue ?? ""
        } catch {
            return .failure(Problem(description: "start: \(error)"))
        }
        // the job's end – or nothing, when the time is up
        let (end, iterations) = await withTaskGroup(of: (EngineEvent?, Int).self) { group in
            group.addTask {
                var count = 0
                for await event in engine.events {
                    if event.kind == "iteration" { count += 1 }
                    if ["job_done", "job_failed", "job_ended", "engine_exit"].contains(event.kind) {
                        return (event, count)
                    }
                }
                return (nil, count)
            }
            group.addTask {
                try? await Task.sleep(for: timeout)
                return (nil, 0)
            }
            let first = await group.next() ?? (nil, 0)
            group.cancelAll()
            return first
        }
        guard let end else { return .failure(Problem(description: "no end of the job within \(timeout)")) }
        guard end.kind == "job_done" else {
            let message = end.data["message"]?.stringValue ?? PyJSON.dump(.object(end.data))
            return .failure(Problem(description: "\(end.kind): \(message)"))
        }
        let folder = URL(filePath: end.data["job_dir"]?.stringValue ?? jobDir, directoryHint: .isDirectory)
        guard let summary = JobFolder.summary(at: folder), let best = JobFolder.bestSketch(summary) else {
            return .failure(Problem(description: "no finished sketch in \(folder.path)"))
        }
        do {
            let sketch = try SketchSVG.parse(String(decoding: Data(contentsOf: best), as: UTF8.self))
            guard !sketch.strokes.isEmpty else {
                return .failure(Problem(description: "the sketch \(best.lastPathComponent) has no strokes"))
            }
            let score = summary.clipScore.map { String(format: "%.1f", $0) } ?? "–"
            return .success("job done: \(iterations) iterations seen · \(sketch.strokes.count) strokes · CLIP score "
                + "\(score) · \(best.lastPathComponent)")
        } catch {
            return .failure(Problem(description: "the sketch \(best.path): \(error)"))
        }
    }
}
