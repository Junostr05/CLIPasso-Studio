import Foundation
import StudioCore

/// The brush styles of the exports (schema.json's brush_styles, gui/brush.py): the engine draws a sketch in a style
/// and the exports draw what it answers.
public extension AppModel {
    /// The styles the exports offer, "plain" first.
    var brushStyles: [String] { schema.brushStyles }

    /// The style the studio shows its sketches in (canvas_style; plain when the schema does not list it). The
    /// sketch itself stays plain: touched up, saved and exported as it is.
    var canvasStyle: String {
        let style = settings["canvas_style"]?.stringValue ?? "plain"
        return brushStyles.contains(style) ? style : "plain"
    }

    func setCanvasStyle(_ style: String) {
        _ = updateSettings { $0["canvas_style"] = .string(style) }
    }

    /// The stylist of `style` for an export: it asks the engine (op "stylize") – from the export's own thread, which
    /// waits for the answer (never from the main actor). "plain" or a style the engine does not know asks no one.
    func stylist(_ style: String) -> Stylist {
        guard style != "plain", brushStyles.contains(style) else { return .plain }
        let engine = engine
        return Stylist(style: style, recolours: schema.brushRecolouring.contains(style)) { svgs in
            guard let engine else { throw EngineFailure(code: "engine_gone", message: "the engine is not running") }
            let answer = try Waiting.result {
                try await engine.request("stylize", ["svgs": .array(svgs.map { .string($0) }), "style": .string(style)],
                                         timeout: .seconds(600))
            }
            return (answer.objectValue?["svgs"]?.arrayValue ?? []).compactMap(\.stringValue)
        }
    }
}

/// Waiting on a thread of its own (OwnThreads) for async work – the engine's answer – to finish.
nonisolated enum Waiting {
    private nonisolated final class Box<T: Sendable>: @unchecked Sendable {
        var result: Result<T, any Error>?
    }

    static func result<T: Sendable>(_ work: @escaping @Sendable () async throws -> T) throws -> T {
        precondition(!Thread.isMainThread, "waiting for the engine on the main thread would stop the app")
        let box = Box<T>()
        let done = DispatchSemaphore(value: 0)
        Task.detached {
            do {
                box.result = .success(try await work())
            } catch {
                box.result = .failure(error)
            }
            done.signal()
        }
        done.wait()
        return try box.result!.get()
    }
}
