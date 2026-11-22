import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The Analysis page: this Mac, the engine (its build, PyTorch, the Apple GPU and how it computes), where
/// "Automatic" computes each method and why – and, measured while a job computes, where its time goes: each part of a
/// step with the device it ran on (CPU or Apple GPU), what the CPU computed for the GPU, the memory. Refreshed every
/// two seconds while it is shown. Content: a grouped form.
struct AnalysisView: View {
    @Environment(AppModel.self) private var model
    @State private var copied = false

    var body: some View {
        let t = model.texts
        Form {
            macSection
            engineSection
            autoSection
            jobSection
        }
        .formStyle(.grouped)
        .navigationTitle(t.tr("ui.mac.analysis.title"))
        .navigationSubtitle(t.tr("ui.mac.analysis.subtitle"))
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(t.tr(copied ? "ui.mac.analysis.copied" : "ui.mac.analysis.copy"),
                       systemImage: copied ? "checkmark" : "doc.on.doc") { copy() }
                    .help(t.tr("ui.mac.analysis.copy_tip"))
            }
        }
        .task {
            await model.gallery.refresh()
            while !Task.isCancelled {
                await model.refreshAnalysis()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    /// Copy: the page as text (AppModel.analysisText), freshly measured.
    private func copy() {
        Task {
            await model.refreshAnalysis()
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(model.analysisText(), forType: .string)
            copied = true
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }

    // MARK: - the Mac and the engine

    private var macSection: some View {
        let t = model.texts
        let mac = model.macFacts
        return Section(t.tr("ui.mac.analysis.mac")) {
            row(t.tr("ui.mac.analysis.chip"), mac["cpu"]?.stringValue ?? "–")
            row(t.tr("ui.mac.analysis.cores"), "\(mac["cores"]?.intValue ?? 0)")
            row(t.tr("ui.mac.analysis.memory"), model.analysisBytes(Int64(mac["memory_bytes"]?.intValue ?? 0)))
            row(t.tr("ui.mac.analysis.macos"), mac["macos"]?.stringValue ?? "–")
        }
    }

    @ViewBuilder private var engineSection: some View {
        let t = model.texts
        Section(t.tr("ui.mac.analysis.engine")) {
            if let facts = model.analysis.facts {
                row(t.tr("ui.mac.analysis.version"),
                    "\(facts["engine"]?.stringValue ?? model.version) · \(facts["build"]?.stringValue ?? "–")")
                row(t.tr("ui.mac.analysis.torch"), facts["torch"]?.stringValue ?? "–")
                let gpu = facts["mps"]?.truthy ?? false
                LabeledContent(t.tr("ui.mac.analysis.gpu")) {
                    Label(t.tr(gpu ? "ui.mac.analysis.gpu_yes" : "ui.mac.analysis.gpu_no"),
                          systemImage: gpu ? "checkmark.circle.fill" : "xmark.circle")
                        .foregroundStyle(gpu ? .green : .secondary)
                }
                if gpu, let linear = facts["linear"]?.stringValue {
                    LabeledContent(t.tr("ui.mac.analysis.linear")) {
                        Text(t.has("ui.mac.analysis.linear.\(linear)") ? t.tr("ui.mac.analysis.linear.\(linear)") : linear)
                            .foregroundStyle(linear == "wrong" ? .red : .primary)
                    }
                }
                if gpu, let drawn = facts["draw_on_mps"]?.stringValue {
                    LabeledContent(t.tr("ui.mac.analysis.draw_on")) { DeviceBadge(device: drawn) }
                }
                row(t.tr("ui.mac.analysis.threads"), "\(facts["threads"]?.intValue ?? 0)")
            } else {
                Text(t.tr("ui.mac.analysis.engine_waiting")).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - where "Automatic" computes

    private var autoSection: some View {
        let t = model.texts
        return Section {
            ForEach(model.methodPlacements()) { placement in
                LabeledContent {
                    HStack(spacing: Spacing.spaceS) {
                        Text(model.placementReason(placement.reason)).foregroundStyle(.secondary).font(.callout)
                        DeviceBadge(device: placement.device)
                    }
                } label: {
                    Text(verbatim: model.schema.method(placement.method)?.name ?? placement.method)
                }
            }
        } header: {
            Text(t.tr("ui.mac.analysis.auto"))
        } footer: {
            VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                if model.hardwareReportStale {
                    Label(t.tr("ui.mac.hw.stale"), systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.orange)
                }
                Text(t.tr("ui.mac.analysis.auto_note")).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - the job

    @ViewBuilder private var jobSection: some View {
        let t = model.texts
        if let job = model.analysis.job, let dir = model.analysis.jobDir {
            Section {
                LabeledContent(t.tr("ui.mac.analysis.device")) { DeviceBadge(device: job.device) }
                row(t.tr("ui.mac.analysis.iterations"), "\(job.iterations)")
                if let per = job.perIteration {
                    row(t.tr("ui.mac.analysis.per_iteration"), t.tr("ui.mac.hw.per_step", [
                        "seconds": t.number(per, decimals: per < 0.1 ? 3 : 2)]))
                }
                if job.workers > 1 { row(t.tr("ui.mac.analysis.workers"), "\(job.workers)") }
            } header: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(t.tr("ui.mac.analysis.job") + " · " + (model.schema.method(job.method)?.name ?? job.method)
                        + " · " + dir.lastPathComponent)
                    Text(t.tr(job.finished ? "ui.mac.analysis.finished" : "ui.mac.analysis.running",
                              ["time": AppModel.shortDate(job.updated)]))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Section(t.tr("ui.mac.analysis.parts")) {
                let total = max(job.seconds, 0.001)
                ForEach(job.parts.filter { $0.calls > 0 }) { part in
                    PartRow(name: t.tr("ui.mac.analysis.part.\(part.key)"),
                            tip: t.has("ui.mac.analysis.part_tip.\(part.key)") ? t.tr("ui.mac.analysis.part_tip.\(part.key)") : nil,
                            devices: part.devices, seconds: model.analysisSeconds(part.seconds),
                            share: part.seconds / total, texts: t)
                }
                PartRow(name: t.tr("ui.mac.analysis.part.rest"), tip: t.tr("ui.mac.analysis.part_tip.rest"),
                        devices: [], seconds: model.analysisSeconds(job.restInSteps), share: job.restInSteps / total,
                        texts: t)
                PartRow(name: t.tr("ui.mac.analysis.part.outside"), tip: nil, devices: [],
                        seconds: model.analysisSeconds(job.outsideSteps), share: job.outsideSteps / total, texts: t)
                row(t.tr("ui.mac.analysis.total"), model.analysisSeconds(job.seconds))
            }
            Section {
                LabeledContent(t.tr("ui.mac.analysis.fallbacks")) {
                    Text(verbatim: job.fallbacks.isEmpty ? t.tr("ui.mac.analysis.fallbacks_none")
                        : job.fallbacks.joined(separator: ", "))
                        .foregroundStyle(job.fallbacks.isEmpty ? Color.secondary : Color.orange)
                        .textSelection(.enabled)
                }
                if job.peakMemory > 0 { row(t.tr("ui.mac.analysis.peak_memory"), model.analysisBytes(job.peakMemory)) }
                if job.gpuMemory > 0 { row(t.tr("ui.mac.analysis.gpu_memory"), model.analysisBytes(job.gpuMemory)) }
                Button(t.tr("ui.mac.analysis.show_folder"), systemImage: "folder") {
                    NSWorkspace.shared.activateFileViewerSelecting([dir])
                }
            }
        } else {
            Section(t.tr("ui.mac.analysis.job")) {
                Text(t.tr("ui.mac.analysis.job_none")).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        LabeledContent(label) { Text(verbatim: value).monospacedDigit().textSelection(.enabled) }
    }

}

/// One part of a step: its name, the device(s) it ran on, its time and share of the job's time.
private struct PartRow: View {
    let name: String
    let tip: String?
    let devices: [String]
    /// its time, as text
    let seconds: String
    let share: Double
    let texts: Texts

    var body: some View {
        LabeledContent {
            HStack(spacing: Spacing.spaceS) {
                ForEach(devices, id: \.self) { DeviceBadge(device: $0) }
                ProgressView(value: min(1, max(0, share))).frame(width: 90)
                    .accessibilityHidden(true)
                Text(verbatim: "\(texts.number(share * 100, decimals: 0)) %").monospacedDigit()
                    .frame(width: 44, alignment: .trailing)
                Text(verbatim: seconds).monospacedDigit().foregroundStyle(.secondary)
                    .frame(width: 70, alignment: .trailing)
            }
        } label: {
            Text(name).help(tip ?? "")
        }
        .accessibilityElement(children: .combine)
    }
}

/// "CPU", "Apple GPU" or "NVIDIA GPU" as a small badge.
struct DeviceBadge: View {
    @Environment(AppModel.self) private var model
    let device: String

    var body: some View {
        let kind = device.split(separator: ":").first.map(String.init) ?? device
        let gpu = kind == "mps" || kind == "cuda"
        Label(model.deviceName(device), systemImage: gpu ? "bolt.fill" : "cpu")
            .font(.caption.weight(.semibold))
            .padding(.horizontal, Spacing.spaceS)
            .padding(.vertical, 2)
            .background(Capsule().fill(gpu ? Color.green.opacity(0.18) : Color.secondary.opacity(0.15)))
            .foregroundStyle(gpu ? Color.green : Color.primary)
            .fixedSize()
    }
}
