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

// MARK: - the page as text (its Copy button)

public extension AppModel {
    /// "CPU", "Apple GPU", "NVIDIA GPU" (in the app's language).
    func deviceName(_ device: String) -> String {
        let kind = device.split(separator: ":").first.map(String.init) ?? device
        let key = "ui.mac.analysis.\(kind)"
        return texts.has(key) ? texts.tr(key) : device
    }

    /// Why "Automatic" computes a method where it does.
    func placementReason(_ reason: MethodPlacement.Reason) -> String {
        switch reason {
        case .hardwareTest(let date): texts.tr("ui.mac.analysis.reason.test", ["date": Self.shortDate(date)])
        case .engineDefault: texts.tr("ui.mac.analysis.reason.default")
        case .noGPU: texts.tr("ui.mac.analysis.reason.no_gpu")
        case .cpuDefault: texts.tr("ui.mac.analysis.reason.cpu")
        }
    }

    /// An ISO date as "22.11.2026, 13:05" (as the system writes it); the text itself when it is none.
    nonisolated static func shortDate(_ iso: String) -> String {
        let parser = ISO8601DateFormatter()
        guard let date = parser.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.dateStyle = .medium
        out.timeStyle = .short
        return out.string(from: date)
    }

    /// Seconds as "3,21 s" or "1:05" (a minute and more).
    func analysisSeconds(_ value: Double) -> String {
        value >= 60 ? PhoneRemote.eta(value) : "\(texts.number(value, decimals: value < 10 ? 2 : 1)) s"
    }

    /// Bytes as "7,2 GB" (or MB below a gigabyte).
    func analysisBytes(_ count: Int64) -> String {
        let value = Double(count)
        return value >= 1e9 ? "\(texts.number(value / 1e9, decimals: 1)) GB" : "\(texts.number(value / 1e6, decimals: 0)) MB"
    }

    /// The Analysis page as text – everything it shows, for the clipboard (a bug report, a message).
    func analysisText() -> String {
        let t = texts
        var lines = ["CLIPasso Studio – \(t.tr("ui.mac.analysis.title")) – \(Self.shortDate(ISO8601DateFormatter().string(from: Date())))", ""]
        func row(_ key: String, _ value: String) { lines.append("\(t.tr(key)): \(value)") }

        let mac = macFacts
        lines.append("[\(t.tr("ui.mac.analysis.mac"))]")
        row("ui.mac.analysis.chip", mac["cpu"]?.stringValue ?? "–")
        row("ui.mac.analysis.cores", "\(mac["cores"]?.intValue ?? 0)")
        row("ui.mac.analysis.memory", analysisBytes(Int64(mac["memory_bytes"]?.intValue ?? 0)))
        row("ui.mac.analysis.macos", mac["macos"]?.stringValue ?? "–")
        lines.append("")

        lines.append("[\(t.tr("ui.mac.analysis.engine"))]")
        if let facts = analysis.facts {
            row("ui.mac.analysis.version", "\(facts["engine"]?.stringValue ?? version) · \(facts["build"]?.stringValue ?? "–")")
            row("ui.mac.analysis.torch", facts["torch"]?.stringValue ?? "–")
            let gpu = facts["mps"]?.truthy ?? false
            row("ui.mac.analysis.gpu", t.tr(gpu ? "ui.mac.analysis.gpu_yes" : "ui.mac.analysis.gpu_no"))
            if gpu, let linear = facts["linear"]?.stringValue {
                row("ui.mac.analysis.linear",
                    t.has("ui.mac.analysis.linear.\(linear)") ? t.tr("ui.mac.analysis.linear.\(linear)") : linear)
            }
            if gpu, let drawn = facts["draw_on_mps"]?.stringValue { row("ui.mac.analysis.draw_on", deviceName(drawn)) }
            row("ui.mac.analysis.threads", "\(facts["threads"]?.intValue ?? 0)")
        } else {
            lines.append(t.tr("ui.mac.analysis.engine_waiting"))
        }
        lines.append("")

        lines.append("[\(t.tr("ui.mac.analysis.auto"))]")
        for placement in methodPlacements() {
            let name = schema.method(placement.method)?.name ?? placement.method
            lines.append("\(name): \(deviceName(placement.device)) – \(placementReason(placement.reason))")
        }
        if hardwareReportStale { lines.append(t.tr("ui.mac.hw.stale")) }
        lines.append("")

        guard let job = analysis.job, let dir = analysis.jobDir else {
            lines.append("[\(t.tr("ui.mac.analysis.job"))]")
            lines.append(t.tr("ui.mac.analysis.job_none"))
            return lines.joined(separator: "\n") + "\n"
        }
        let state = t.tr(job.finished ? "ui.mac.analysis.finished" : "ui.mac.analysis.running",
                         ["time": Self.shortDate(job.updated)])
        lines.append("[\(t.tr("ui.mac.analysis.job")) · \(schema.method(job.method)?.name ?? job.method) · "
            + "\(dir.lastPathComponent)] \(state)")
        row("ui.mac.analysis.device", deviceName(job.device))
        row("ui.mac.analysis.iterations", "\(job.iterations)")
        if let per = job.perIteration {
            row("ui.mac.analysis.per_iteration",
                t.tr("ui.mac.hw.per_step", ["seconds": t.number(per, decimals: per < 0.1 ? 3 : 2)]))
        }
        if job.workers > 1 { row("ui.mac.analysis.workers", "\(job.workers)") }
        lines.append("")

        lines.append("[\(t.tr("ui.mac.analysis.parts"))]")
        let total = max(job.seconds, 0.001)
        func part(_ name: String, _ devices: [String], _ seconds: Double) {
            let on = devices.isEmpty ? "" : devices.map(deviceName).joined(separator: " + ") + " · "
            lines.append("\(name): \(on)\(t.number(seconds / total * 100, decimals: 0)) % · \(analysisSeconds(seconds))")
        }
        for p in job.parts where p.calls > 0 {
            part(t.tr("ui.mac.analysis.part.\(p.key)"), p.devices, p.seconds)
        }
        part(t.tr("ui.mac.analysis.part.rest"), [], job.restInSteps)
        part(t.tr("ui.mac.analysis.part.outside"), [], job.outsideSteps)
        row("ui.mac.analysis.total", analysisSeconds(job.seconds))
        lines.append("")
        row("ui.mac.analysis.fallbacks",
            job.fallbacks.isEmpty ? t.tr("ui.mac.analysis.fallbacks_none") : job.fallbacks.joined(separator: ", "))
        if job.peakMemory > 0 { row("ui.mac.analysis.peak_memory", analysisBytes(job.peakMemory)) }
        if job.gpuMemory > 0 { row("ui.mac.analysis.gpu_memory", analysisBytes(job.gpuMemory)) }
        return lines.joined(separator: "\n") + "\n"
    }
}
