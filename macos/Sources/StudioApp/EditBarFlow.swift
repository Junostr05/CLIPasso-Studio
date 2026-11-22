import Foundation
import StudioCore

/// The studio's edit bar with the engine: the saved steps are read here; what each stroke adds is measured by the
/// engine in a process of its own (op "importance", as the Windows studio's --importance), once per sketch.
public extension AppModel {
    /// studio.open_history: the saved steps of the sketch being touched up (nil: it has none – ui.edit_bar.no_steps).
    func openSteps(_ editor: SketchEditor) -> EditBarModel? {
        EditBarModel(steps: SketchAnimation.steps(runDir: editor.runDir, uptoBest: false), current: editor.svg)
    }

    /// studio.open_simplify: the bar at once, the order when it is measured (or known already).
    func openSimplify(_ editor: SketchEditor) -> EditBarModel {
        let bar = EditBarModel(simplify: editor.svg, order: nil)
        let (run, svg) = (editor.runDir, editor.svg)
        Task {
            switch await importanceOrder(runDir: run, svg: svg) {
            case .success(let order): bar.measured(order)
            case .failure(let failure): bar.measured(nil, problem: failure.description)
            }
        }
        return bar
    }

    struct MeasureFailure: Error, CustomStringConvertible {
        public let description: String
    }

    /// The strokes of the run's sketch from the least to the most important – read, or measured first.
    func importanceOrder(runDir: URL, svg: String) async -> Result<[Int], MeasureFailure> {
        guard let engine, let queue else { return .failure(MeasureFailure(description: "the engine is not running")) }
        await queue.begin()  // (its notices bring "importance_ready")
        let key = runDir.path
        importanceArrived[key] = nil
        importanceState = (svg, "measuring")
        func done(_ result: Result<[Int], MeasureFailure>) -> Result<[Int], MeasureFailure> {
            if importanceState?.svg == svg {
                if case .success = result { importanceState = (svg, "ready") } else { importanceState = (svg, "failed") }
            }
            return result
        }
        let answer: JSONValue
        do {
            answer = try await engine.request("importance", ["run_dir": .string(key), "compute": .bool(true)])
        } catch {
            return done(.failure(MeasureFailure(description: String(describing: error))))
        }
        if let order = Self.importanceOrder(answer) { return done(.success(order)) }
        let event: EngineEvent
        if let arrived = importanceArrived.removeValue(forKey: key) {
            event = arrived
        } else {
            event = await withCheckedContinuation { importanceWaiters[key] = $0 }
        }
        guard event.kind == "importance_ready" else {
            return done(.failure(MeasureFailure(description: event.data["message"]?.stringValue ?? "")))
        }
        let measured = try? await engine.request("importance", ["run_dir": .string(key)])
        guard let order = measured.flatMap(Self.importanceOrder) else {
            return done(.failure(MeasureFailure(description: texts.tr("ui.edit_bar.exit_code", ["code": "1"]))))
        }
        return done(.success(order))
    }

    /// The order of an answer of op "importance" (nil: not measured).
    nonisolated static func importanceOrder(_ answer: JSONValue) -> [Int]? {
        answer.objectValue?["order"]?.arrayValue.map { $0.compactMap(\.intValue) }
    }

    /// A measuring's notice: to the bar waiting for it, or kept until it waits.
    internal func importanceNotice(_ event: EngineEvent) {
        guard let run = event.data["image"]?.stringValue else { return }
        if let waiter = importanceWaiters.removeValue(forKey: run) {
            waiter.resume(returning: event)
        } else {
            importanceArrived[run] = event
        }
    }
}
