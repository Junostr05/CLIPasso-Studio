import Foundation
import Observation
import StudioCore

/// The hardware test (engine/device_bench.py): each method once on the CPU and once on the Apple GPU on this Mac –
/// the time per step and the quality, judged by the same CLIP on the CPU –, then "auto" computes each method on the
/// device measured better here (the queue's autoDevices). Kept in the settings (mac_device_bench, the Mac's own key).
@Observable
public final class HardwareTest {
    public enum State: Equatable, Sendable {
        case idle
        case running(done: Int, total: Int)
        case failed(String)
    }

    public internal(set) var state = State.idle
    /// the rows measured so far in this run (method, device, sec_per_iter, cpu_clip_score, error …)
    public internal(set) var rows: [JSONObject] = []
    @ObservationIgnored var waiter: CheckedContinuation<EngineEvent, Never>?

    public init() {}

    public var running: Bool {
        if case .running = state { return true }
        return false
    }
}

public extension AppModel {
    /// The settings' key of the last hardware test.
    nonisolated static let hardwareKey = "mac_device_bench"
    /// The methods a hardware test measures unless told otherwise (the diffusion ones take long without their GPU).
    nonisolated static let hardwareMethods = ["clipasso", "swiftsketch", "controlsketch", "scenesketch"]

    /// The last hardware test: {date, iterations, rows, recommended {method: {device, speedup, reason …}}}.
    var hardwareReport: JSONObject? { settings[Self.hardwareKey]?.objectValue }

    /// Per method the device "auto" computes on, from the last hardware test.
    var autoDevices: [String: String] {
        var out: [String: String] = [:]
        for (method, entry) in hardwareReport?["recommended"]?.objectValue ?? [:] {
            if let device = entry.objectValue?["device"]?.stringValue { out[method] = device }
        }
        return out
    }

    struct HardwareFailure: Error, CustomStringConvertible {
        public let description: String
    }

    /// Runs the hardware test: not while a job runs (they would measure each other) – the queue waits meanwhile and
    /// starts again afterwards. The report, kept in the settings; "auto" follows it from the next job on.
    @discardableResult
    func runHardwareTest(methods: [String]? = nil, iterations: Int = 40) async -> Result<JSONObject, HardwareFailure> {
        guard let engine, let queue else { return .failure(HardwareFailure(description: "the engine is not running")) }
        guard !hardware.running else { return .failure(HardwareFailure(description: "the hardware test runs already")) }
        guard !(queueSnapshot?.jobs.contains { $0.isActive } ?? false) else {
            return .failure(HardwareFailure(description: texts.tr("ui.mac.hw.busy")))
        }
        let chosen = (methods ?? Self.hardwareMethods).filter { schema.method($0) != nil }
        guard let image = samplePictures.first(where: { $0.lastPathComponent.hasPrefix("camel") }) ?? samplePictures.first
            ?? studio.image
        else { return .failure(HardwareFailure(description: "no picture to measure with")) }
        let wasAuto = await queue.snapshot().autoStart
        await queue.setAutoStart(false)
        await queue.begin()  // (its notices bring the rows)
        hardware.rows = []
        hardware.state = .running(done: 0, total: chosen.count * 2)
        defer { Task { await queue.setAutoStart(wasAuto) } }
        do {
            _ = try await engine.request("device_bench", ["methods": .array(chosen.map(JSONValue.string)),
                                                          "iters": .int(iterations), "image": .string(image.path)])
        } catch {
            hardware.state = .failed(String(describing: error))
            return .failure(HardwareFailure(description: String(describing: error)))
        }
        let end = await withCheckedContinuation { hardware.waiter = $0 }
        guard end.kind == "bench_done" else {
            let why = end.data["message"]?.stringValue ?? end.kind
            hardware.state = .failed(why)
            return .failure(HardwareFailure(description: why))
        }
        var report = end.data
        report["date"] = .string(ISO8601DateFormatter().string(from: Date()))
        report["iterations"] = .int(iterations)
        report["image"] = .string(image.lastPathComponent)
        _ = updateSettings { $0[Self.hardwareKey] = .object(report) }
        await queue.setAutoDevices(autoDevices)
        hardware.state = .idle
        return .success(report)
    }

    /// A notice of the hardware test: a row (progress) or its end (to the run waiting for it).
    internal func hardwareNotice(_ event: EngineEvent) {
        switch event.kind {
        case "bench_row":
            hardware.rows.append(event.data)
            if case .running(_, let total) = hardware.state {
                hardware.state = .running(done: hardware.rows.count, total: total)
            }
        default:
            hardware.waiter?.resume(returning: event)
            hardware.waiter = nil
        }
    }
}
