import Foundation
import Observation
import StudioCore

/// The Analysis page (and the MCP tool get_analysis): what this Mac is, which engine it runs, where "Automatic"
/// computes each method and why, and – measured while a job runs – what of a step ran on the CPU and what on the
/// Apple GPU (engine/device_analysis.py).
@Observable
public final class AnalysisModel {
    /// What the engine's device probe said (PyTorch, MPS, the engine's build, the linear layer, MPS_AUTO …).
    public internal(set) var facts: JSONObject?
    /// The job looked at and its analysis (nil: none yet).
    public internal(set) var jobDir: URL?
    public internal(set) var job: DeviceAnalysis?

    public init() {}
}

/// Where "Automatic" computes a method, and why.
public struct MethodPlacement: Sendable, Equatable, Identifiable {
    public enum Reason: Sendable, Equatable {
        /// the hardware test measured it (its date)
        case hardwareTest(String)
        /// the engine's default (measured on a Mac: settings_schema.MPS_AUTO)
        case engineDefault
        /// no Apple GPU (or one that computes wrongly)
        case noGPU
        /// the CPU until the hardware test measured it
        case cpuDefault
    }

    public let method: String
    /// "mps" or "cpu"
    public let device: String
    public let reason: Reason
    public var id: String { method }
}

public extension AppModel {
    /// The facts of the probe and the analysis of the job shown (the running one, else the newest result).
    func refreshAnalysis() async {
        if analysis.facts == nil, let engine, engineStatus == .ready,
           let found = try? await engine.request("devices", timeout: .seconds(20)).objectValue
        {
            analysis.facts = found
        }
        let dir = studio.live.jobDir ?? gallery.everything.max { $0.created < $1.created }?.jobDir
        analysis.jobDir = dir
        let read = dir.map { url in Task.detached { DeviceAnalysis.read(jobDir: url) } }
        analysis.job = await read?.value
    }

    /// Where "Automatic" computes each method (as the queue decides: JobQueue.startSettings, then the engine).
    func methodPlacements() -> [MethodPlacement] {
        let facts = analysis.facts ?? [:]
        let gpu = (facts["mps"]?.truthy ?? false) && facts["linear"]?.stringValue != "wrong"
        let engineDefault = Set(facts["mps_auto"]?.arrayValue?.compactMap(\.stringValue) ?? [])
        let measured = autoDevices
        let date = hardwareReport?["date"]?.stringValue ?? ""
        return schema.methods.map { method in
            if !gpu { return MethodPlacement(method: method, device: "cpu", reason: .noGPU) }
            if let device = measured[method] {
                return MethodPlacement(method: method, device: device, reason: .hardwareTest(date))
            }
            if engineDefault.contains(method) {
                return MethodPlacement(method: method, device: "mps", reason: .engineDefault)
            }
            return MethodPlacement(method: method, device: "cpu", reason: .cpuDefault)
        }
    }

    /// This Mac (as the diagnosis names it).
    var macFacts: JSONObject {
        let info = ProcessInfo.processInfo
        return ["machine": .string(Self.machine), "cpu": .string(Self.cpuName), "cores": .int(info.activeProcessorCount),
                "memory_bytes": .int(Int(info.physicalMemory)),
                "macos": .string(info.operatingSystemVersionString), "app_version": .string(version)]
    }

    /// The MCP tool get_analysis: the Mac, the engine, where "Automatic" computes, and a job's parts by device.
    func mcpAnalysis(_ a: JSONObject) async -> MCPResult {
        await refreshAnalysis()
        var dir = analysis.jobDir
        if let name = a["result"]?.stringValue {
            await gallery.refresh()
            guard let item = gallery.everything.first(where: { $0.jobDir.lastPathComponent == name }) else {
                return .error("no such result")
            }
            dir = item.jobDir
        }
        let job = dir.flatMap { DeviceAnalysis.read(jobDir: $0) }
        let placements = methodPlacements().map { p -> JSONValue in
            let reason: String
            switch p.reason {
            case .hardwareTest(let date): reason = "hardware test \(date)"
            case .engineDefault: reason = "engine default (measured faster on the Apple GPU)"
            case .noGPU: reason = "no usable Apple GPU"
            case .cpuDefault: reason = "CPU until the hardware test measures it"
            }
            return ["method": .string(p.method), "device": .string(p.device), "reason": .string(reason)]
        }
        return .json([
            "mac": .object(macFacts), "engine": .object(analysis.facts ?? [:]),
            "automatic": .array(placements),
            "hardware_test_stale": .bool(hardwareReportStale),  // (measured with another engine: not followed)
            "job": job.map { .object($0.json.merging(["folder": .string(dir?.path ?? "")])) } ?? .null,
            "note": .string("parts: draw = strokes rasterised, clip = CLIP encoders, model = diffusion/network, "
                + "backward = gradients, optimizer = optimiser step; devices: cpu, mps (Apple GPU), cuda"),
        ])
    }
}
