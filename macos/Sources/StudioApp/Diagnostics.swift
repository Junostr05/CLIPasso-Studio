import Foundation
import StudioCore

/// Diagnostics (gui/diagnostics.py): one text with what a bug report needs – the version, the Mac, what the engine
/// sees, the folders with their free space, the models, the engine's last log lines. In English on purpose: it is
/// read by whoever fixes the bug. Never a secret: no telegram_token, remote_token or remote_pin (the settings shown
/// are named, the engine's log leaves out lines that name them).
public extension AppModel {
    static let diagnosticSettings = ["language", "theme", "canvas_style", "keep_models_loaded", "keep_awake", "notify",
                                     "watch_enabled", "check_updates", "remote_on", "remote_tailscale"]
    static let logLines = 50

    func diagnostics(now: Date = Date()) async -> String {
        var out = ["CLIPasso Studio diagnostics · \(Backup.timestamp(now))", ""]
        let shown = Self.diagnosticSettings.map { "\($0)=\(PhoneStudio.pyRepr(settings[$0] ?? .null))" }
        out += ["[App]", "Version: \(version) (mac)", "Program: \(Bundle.main.bundlePath)",
                "Settings: " + shown.joined(separator: ", "), ""]
        let info = ProcessInfo.processInfo
        out += ["[System]", "OS: macOS \(info.operatingSystemVersionString) · \(Self.machine)",
                "CPU: \(Self.cpuName) · \(info.activeProcessorCount) cores",
                String(format: "RAM: %.1f GB", Double(info.physicalMemory) / 1e9), ""]
        out += ["[Engine]", "Status: \(engineStatusText)"]
        if let engine, engineStatus == .ready,
           let devices = try? await engine.request("devices", timeout: .seconds(10)), let d = devices.objectValue
        {
            out.append("PyTorch \(d["torch"]?.stringValue ?? "?") · MPS \(d["mps"]?.truthy == true ? "yes" : "no")")
        } else {
            out.append("PyTorch: not checked")
        }
        out.append("")
        let data = store.url.deletingLastPathComponent()
        out += ["[Folders]", Self.folderLine("Data", data), Self.folderLine("Output", settings.outputDir),
                Self.folderLine("Models", modelsDir),
                "Bundled models: \(resources.bundledModels?.path ?? "–")", ""]
        let models = catalog.models.compactMap { spec -> String? in
            switch modelState(spec.key) {
            case .missing: nil
            case .included: "\(spec.key) (bundled, ~\(spec.storedSizeMB) MB)"
            case .installed: "\(spec.key) (downloaded, ~\(spec.storedSizeMB) MB)"
            }
        }.sorted()
        out += ["[Models]"] + (models.isEmpty ? ["(none)"] : models) + [""]
        let lines = await engine?.stderrTail().suffix(Self.logLines) ?? []
        out += ["[Engine log, last \(Self.logLines) lines]"] + (lines.isEmpty ? ["(empty)"] : Array(lines))
        return out.joined(separator: "\n") + "\n"
    }

    /// default_file_name: "clipasso-studio-diagnostics-<date>-<time>.txt".
    static func diagnosticsFileName(_ now: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return "clipasso-studio-diagnostics-\(f.string(from: now)).txt"
    }

    nonisolated static func folderLine(_ label: String, _ folder: URL) -> String {
        var probe = folder
        while !FileManager.default.fileExists(atPath: probe.path), probe.path != "/" {
            probe = probe.deletingLastPathComponent()
        }
        let free = (try? probe.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage
        return "\(label): \(folder.path)" + (free.map { String(format: " (%.1f GB free)", Double($0) / 1e9) } ?? "")
    }

    nonisolated static var machine: String {
        var system = utsname()
        uname(&system)
        return withUnsafeBytes(of: &system.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
    }

    nonisolated static var cpuName: String {
        #if canImport(Darwin)
            var size = 0
            sysctlbyname("machdep.cpu.brand_string", nil, &size, nil, 0)
            var bytes = [CChar](repeating: 0, count: max(size, 1))
            sysctlbyname("machdep.cpu.brand_string", &bytes, &size, nil, 0)
            let name = String(decoding: bytes.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
            return name.isEmpty ? machine : name
        #else
            return machine
        #endif
    }
}
