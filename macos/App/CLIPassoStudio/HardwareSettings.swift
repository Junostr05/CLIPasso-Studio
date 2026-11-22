import StudioApp
import StudioCore
import SwiftUI

/// The hardware test in the settings: what it measures, the methods to measure, the button – and the last result per
/// method (the CPU's and the Apple GPU's time per step, how much faster, and where "Automatic" computes now).
struct HardwareSettings: View {
    @Environment(AppModel.self) private var model
    @State private var chosen: Set<String> = Set(AppModel.hardwareMethods)
    @State private var problem = ""

    var body: some View {
        let t = model.texts
        let hardware = model.hardware
        Section {
            Text(t.tr("ui.mac.hw.desc")).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Spacing.spaceM) {
                ForEach(AppModel.hardwareMethods.filter { model.schema.method($0) != nil }, id: \.self) { method in
                    Toggle(model.schema.method(method)?.name ?? method, isOn: Binding(
                        get: { chosen.contains(method) },
                        set: { if $0 { chosen.insert(method) } else { chosen.remove(method) } }))
                        .toggleStyle(.checkbox)
                        .fixedSize()
                }
            }
            HStack {
                if case .running(let done, let total) = hardware.state {
                    ProgressView(value: Double(done), total: Double(max(total, 1))).frame(maxWidth: 220)
                    Text(t.tr("ui.mac.hw.running", ["done": "\(done)", "total": "\(total)"]))
                        .foregroundStyle(.secondary).monospacedDigit()
                }
                Spacer()
                Button(t.tr("ui.mac.hw.run"), systemImage: "gauge.with.dots.needle.67percent") { run() }
                    .disabled(hardware.running || chosen.isEmpty || model.engine == nil)
            }
            if !problem.isEmpty {
                Text(verbatim: problem).font(.callout).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            report
        } header: {
            Text(t.tr("ui.mac.hw.title"))
        }
    }

    @ViewBuilder private var report: some View {
        let t = model.texts
        if let report = model.hardwareReport, let recommended = report["recommended"]?.objectValue {
            Text(t.tr("ui.mac.hw.when", ["date": Self.date(report["date"]?.stringValue ?? "")]))
                .font(.caption).foregroundStyle(.secondary)
            if model.hardwareReportStale {
                Label(t.tr("ui.mac.hw.stale"), systemImage: "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
            Grid(alignment: .leading, horizontalSpacing: Spacing.spaceL, verticalSpacing: Spacing.spaceXs) {
                GridRow {
                    ForEach(["method", "cpu", "gpu", "speedup", "auto"], id: \.self) {
                        Text(t.tr("ui.mac.hw.\($0)")).font(.caption.bold()).foregroundStyle(.secondary)
                    }
                }
                ForEach(recommended.keys, id: \.self) { method in
                    let entry = recommended[method]?.objectValue ?? [:]
                    GridRow {
                        Text(verbatim: model.schema.method(method)?.name ?? method)
                        Text(verbatim: Self.seconds(entry["cpu_seconds"], t)).monospacedDigit()
                        Text(verbatim: Self.seconds(entry["gpu_seconds"], t)).monospacedDigit()
                        Text(verbatim: entry["speedup"]?.doubleValue.map { "\(t.number($0))×" } ?? "–").monospacedDigit()
                        Label {
                            Text(verbatim: (entry["device"]?.stringValue == "mps" ? t.tr("ui.mac.hw.gpu") : t.tr("ui.mac.hw.cpu"))
                                + " · " + Self.reason(entry["reason"]?.stringValue ?? "", t))
                        } icon: {
                            Image(systemName: entry["device"]?.stringValue == "mps" ? "bolt.fill" : "cpu")
                        }
                    }
                }
            }
        } else {
            Text(t.tr("ui.mac.hw.never")).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func run() {
        problem = ""
        let methods = AppModel.hardwareMethods.filter(chosen.contains)
        Task {
            if case .failure(let why) = await model.runHardwareTest(methods: methods) {
                problem = model.texts.tr("ui.mac.hw.failed", ["error": why.description])
            }
        }
    }

    static func seconds(_ value: JSONValue?, _ t: Texts) -> String {
        guard let s = value?.doubleValue else { return "–" }
        return t.tr("ui.mac.hw.per_step", ["seconds": t.number(s, decimals: s < 0.1 ? 3 : 2)])
    }

    static func reason(_ reason: String, _ t: Texts) -> String {
        if ["faster", "slower", "worse", "nan", "unavailable"].contains(reason) { return t.tr("ui.mac.hw.reason.\(reason)") }
        return t.tr("ui.mac.hw.reason.other", ["why": reason])
    }

    static func date(_ iso: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: iso) else { return iso }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}
