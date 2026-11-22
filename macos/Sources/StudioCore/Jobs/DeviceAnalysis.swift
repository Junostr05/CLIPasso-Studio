import Foundation

/// What a job computed where (engine/device_analysis.py): the workers' `analysis/worker-<n>.json` in the job folder
/// added up – per part of a step (drawing, CLIP, a method's model, backward, optimiser) its time, calls and devices,
/// the time spent optimising and the rest (loading, preparing, saving), the operations PyTorch computed on the CPU
/// in place of the Apple GPU, the memory.
public struct DeviceAnalysis: Sendable, Equatable {
    public struct Part: Sendable, Equatable, Identifiable {
        public let key: String
        public var seconds: Double
        public var calls: Int
        public var devices: [String]
        public var id: String { key }
    }

    /// the parts in their order (engine/device_analysis.PARTS)
    public static let partOrder = ["draw", "clip", "model", "backward", "optimizer"]

    public var workers = 0
    public var method = ""
    public var device = ""
    /// where strokes on the device are drawn ("cpu" for the Apple GPU)
    public var drawDevice = ""
    /// how the linear layer computes on the Apple GPU (native, matmul, view, wrong)
    public var linear = ""
    public var torch = ""
    public var threads = 0
    public var started = ""
    public var updated = ""
    public var finished = false
    /// the workers' time added up, and of that the time optimising
    public var seconds = 0.0
    public var optimizing = 0.0
    public var iterations = 0
    public var parts: [Part] = []
    public var fallbacks: [String] = []
    public var peakMemory: Int64 = 0
    public var gpuMemory: Int64 = 0

    public init() {}

    /// the parts' time added up
    public var measured: Double { parts.reduce(0) { $0 + $1.seconds } }
    /// the time of the steps outside the parts (the method's own work, Python)
    public var restInSteps: Double { max(0, optimizing - measured) }
    /// the time before and after optimising (loading models, preparing, saving)
    public var outsideSteps: Double { max(0, seconds - max(optimizing, measured)) }
    /// seconds per iteration (nil before the first)
    public var perIteration: Double? { iterations > 0 && optimizing > 0 ? optimizing / Double(iterations) : nil }

    /// The analysis of a job folder (nil: none – a job of an older engine, or one that has not begun).
    public static func read(jobDir: URL) -> DeviceAnalysis? {
        let folder = jobDir.appending(path: "analysis")
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else { return nil }
        let reports = names.filter { $0.hasPrefix("worker-") && $0.hasSuffix(".json") }.sorted().compactMap {
            (try? Data(contentsOf: folder.appending(path: $0))).flatMap { try? PyJSON.parse($0) }?.objectValue
        }
        guard let first = reports.first else { return nil }
        var out = DeviceAnalysis()
        out.workers = reports.count
        out.method = first["method"]?.stringValue ?? ""
        out.device = first["device"]?.stringValue ?? ""
        out.drawDevice = first["draw_device"]?.stringValue ?? ""
        out.linear = first["linear"]?.stringValue ?? ""
        out.torch = first["torch"]?.stringValue ?? ""
        out.threads = first["threads"]?.intValue ?? 0
        out.started = reports.compactMap { $0["started"]?.stringValue }.min() ?? ""
        out.updated = reports.compactMap { $0["updated"]?.stringValue }.max() ?? ""
        out.finished = reports.allSatisfy { $0["finished"]?.truthy ?? false }
        var parts: [String: Part] = [:]
        var devices: [String: Set<String>] = [:]
        for r in reports {
            out.seconds += r["seconds"]?.doubleValue ?? 0
            out.optimizing += r["optimizing_seconds"]?.doubleValue ?? 0
            out.iterations += r["iterations"]?.intValue ?? 0
            for p in r["parts"]?.arrayValue ?? [] {
                guard let o = p.objectValue, let key = o["key"]?.stringValue else { continue }
                var part = parts[key] ?? Part(key: key, seconds: 0, calls: 0, devices: [])
                part.seconds += o["seconds"]?.doubleValue ?? 0
                part.calls += o["calls"]?.intValue ?? 0
                parts[key] = part
                devices[key, default: []].formUnion(o["devices"]?.arrayValue?.compactMap(\.stringValue) ?? [])
            }
            out.fallbacks += r["fallbacks"]?.arrayValue?.compactMap(\.stringValue) ?? []
            let memory = r["memory"]?.objectValue ?? [:]
            out.peakMemory = max(out.peakMemory, Int64(memory["rss_peak"]?.doubleValue ?? 0))
            out.gpuMemory = max(out.gpuMemory, Int64(memory["mps_driver"]?.doubleValue ?? 0))
        }
        let keys = partOrder + parts.keys.filter { !partOrder.contains($0) }.sorted()
        out.parts = keys.compactMap { key in
            parts[key].map { Part(key: key, seconds: $0.seconds, calls: $0.calls, devices: devices[key]?.sorted() ?? []) }
        }
        out.fallbacks = Array(Set(out.fallbacks)).sorted()
        return out
    }

    /// As JSON (the MCP tool get_analysis).
    public var json: JSONObject {
        [
            "workers": .int(workers), "method": .string(method), "device": .string(device),
            "draw_device": .string(drawDevice), "linear": .string(linear), "torch": .string(torch),
            "threads": .int(threads), "started": .string(started), "updated": .string(updated),
            "finished": .bool(finished), "seconds": .double(seconds), "optimizing_seconds": .double(optimizing),
            "iterations": .int(iterations),
            "seconds_per_iteration": perIteration.map(JSONValue.double) ?? .null,
            "parts": .array(parts.map { p -> JSONValue in
                ["key": .string(p.key), "seconds": .double(p.seconds), "calls": .int(p.calls),
                 "devices": .array(p.devices.map(JSONValue.string))]
            }),
            "rest_in_steps_seconds": .double(restInSteps), "outside_steps_seconds": .double(outsideSteps),
            "cpu_fallbacks": .array(fallbacks.map(JSONValue.string)),
            "peak_memory_bytes": .int(Int(peakMemory)), "gpu_memory_bytes": .int(Int(gpuMemory)),
        ]
    }
}
