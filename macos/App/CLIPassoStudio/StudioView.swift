import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// The studio: on the left the steps (image, method, preset with its parameters), in the middle the sketch – live
/// while it is computed – and below the job bar. The column and the canvas are content; only the job bar's controls
/// float above it as glass (system button styles in one container).
struct StudioView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 0) {
            StepsColumn()
                .frame(width: Spacing.leftColumn)
            Divider()
            CanvasArea()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .safeAreaBar(edge: .bottom) {
            JobBar()
                .padding(.horizontal, Spacing.spaceL)
                .padding(.vertical, Spacing.spaceM)
        }
        .navigationTitle(model.texts.tr("nav.studio"))
    }
}

// MARK: - the steps

private struct StepsColumn: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.spaceXl) {
                Step(number: 1, title: model.texts.tr("ui.step.image")) { ImageStep() }
                Step(number: 2, title: model.texts.tr("ui.step.method")) { MethodStep() }
                Step(number: 3, title: model.texts.tr("ui.step.preset")) { PresetStep() }
            }
            .padding(Spacing.columnPadding)
        }
        .scrollContentBackground(.hidden)
    }
}

private struct Step<Content: View>: View {
    let number: Int
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.spaceS) {
            Text(verbatim: "\(number) · \(title)")
                .font(.headline)
                .accessibilityAddTraits(.isHeader)
            content
        }
    }
}

private struct ImageStep: View {
    @Environment(AppModel.self) private var model
    @State private var importing = false
    @State private var preview: NSImage?
    @State private var targeted = false

    var body: some View {
        let studio = model.studio
        VStack(alignment: .leading, spacing: Spacing.spaceS) {
            ZStack {
                RoundedRectangle(cornerRadius: Radius.card)
                    .fill(Color(nsColor: .controlBackgroundColor))
                RoundedRectangle(cornerRadius: Radius.card)
                    .strokeBorder(targeted ? Color.accentColor : Color(nsColor: .separatorColor),
                                  style: StrokeStyle(lineWidth: targeted ? 2 : 1, dash: preview == nil ? [6, 4] : []))
                if let preview {
                    Image(nsImage: preview)
                        .resizable()
                        .scaledToFit()
                        .padding(Spacing.spaceS)
                        .accessibilityLabel(Text(verbatim: studio.image?.lastPathComponent ?? ""))
                } else {
                    Label(model.texts.tr("ui.drop_title"), systemImage: "photo.badge.plus")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(height: 168)
            .dropDestination(for: URL.self) { urls, _ in
                guard let url = urls.first(where: { $0.isFileURL }) else { return false }
                studio.image = url
                return true
            } isTargeted: { targeted = $0 }
            .onPasteCommand(of: [.fileURL]) { providers in
                _ = providers.first?.loadObject(ofClass: URL.self) { url, _ in
                    guard let url, url.isFileURL else { return }
                    Task { @MainActor in studio.image = url }
                }
            }
            Button(model.texts.tr(studio.image == nil ? "ui.step.open" : "ui.step.change"), systemImage: "folder") {
                importing = true
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.image]) { result in
                if case .success(let url) = result { studio.image = url }
            }
        }
        .task(id: studio.image) {
            guard let url = studio.image else {
                preview = nil
                return
            }
            let data = await Task.detached { try? Data(contentsOf: url) }.value  // (NSImage is not Sendable)
            preview = data.flatMap { NSImage(data: $0) }
        }
    }
}

private struct MethodStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let studio = model.studio
        VStack(spacing: Spacing.spaceS) {
            ForEach(model.schema.methods, id: \.self) { id in
                if let method = model.schema.method(id) {
                    let selected = studio.method == id
                    Button {
                        studio.selectMethod(id)
                    } label: {
                        VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                            Text(verbatim: method.name).font(.headline)
                            if let tagline = method.text["tagline"] {
                                Text(model.texts.tr(tagline)).font(.callout)
                            }
                            if let speed = method.text["speed"] {
                                Text(model.texts.tr(speed)).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(Spacing.spaceM)
                        .background {
                            RoundedRectangle(cornerRadius: Radius.card)
                                .fill(selected ? Color.accentColor.opacity(0.14) : Color(nsColor: .controlBackgroundColor))
                        }
                        .overlay {
                            RoundedRectangle(cornerRadius: Radius.card)
                                .strokeBorder(selected ? Color.accentColor : Color(nsColor: .separatorColor),
                                              lineWidth: selected ? 2 : 1)
                        }
                        .contentShape(RoundedRectangle(cornerRadius: Radius.card))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                }
            }
        }
    }
}

private struct PresetStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let studio = model.studio
        if let method = studio.methodSchema {
            VStack(alignment: .leading, spacing: Spacing.spaceS) {
                Picker(model.texts.tr("ui.step.preset"), selection: Binding(
                    get: { studio.preset ?? "" },
                    set: { studio.applyPreset($0) }
                )) {
                    ForEach(method.presetOrder, id: \.self) { name in
                        Text(model.texts.tr(method.presetText[name] ?? name)).tag(name)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                Text(hint(method: method.id, preset: studio.preset ?? "custom"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                DisclosureGroup(model.texts.tr("ui.step.adjust")) {
                    VStack(alignment: .leading, spacing: Spacing.spaceM) {
                        ForEach(method.groups, id: \.self) { group in
                            let params = method.params.filter { $0.group == group && !$0.hidden }
                            if !params.isEmpty {
                                DisclosureGroup(model.texts.tr(method.groupText[group] ?? group)) {
                                    VStack(alignment: .leading, spacing: Spacing.spaceS) {
                                        ForEach(params) { ParamRow(param: $0) }
                                    }
                                    .padding(.top, Spacing.spaceXs)
                                }
                            }
                        }
                    }
                    .padding(.top, Spacing.spaceS)
                }
            }
        }
    }

    /// param_panel._update_preset_hint: the method's own hint, else the general one.
    private func hint(method: String, preset: String) -> String {
        for key in ["ui.preset_hint.\(method).\(preset)", "ui.preset_hint.\(preset)"] where model.texts.has(key) {
            return model.texts.tr(key)
        }
        return ""
    }
}

/// One parameter, as its kind asks: a switch, a slider with its value, a menu of choices or a text field; greyed out
/// when its rule says so.
private struct ParamRow: View {
    @Environment(AppModel.self) private var model
    let param: Param

    var body: some View {
        let studio = model.studio
        let value = studio.settings[param.key] ?? param.default
        let label = model.texts.tr(param.text.label)
        control(studio: studio, value: value, label: label)
            .disabled(!studio.isEnabled(param.key))
            .help(param.text.help.map { model.texts.tr($0) } ?? "")
    }

    @ViewBuilder
    private func control(studio: StudioModel, value: JSONValue, label: String) -> some View {
        switch param.kind {
        case .bool:
            Toggle(label, isOn: Binding(get: { value.truthy }, set: { studio.set(param.key, to: .bool($0)) }))
        case .int, .float:
            if let lo = param.minimum, let hi = param.maximum, hi > lo {
                let isInt = param.kind == .int
                VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                    HStack {
                        Text(label)
                        Spacer()
                        Text(verbatim: shown(value)).monospacedDigit().foregroundStyle(.secondary)
                    }
                    Slider(value: Binding(
                        get: { value.doubleValue ?? lo },
                        set: { studio.set(param.key, to: isInt ? .int(Int($0.rounded())) : .double($0)) }
                    ), in: lo...hi, step: param.step ?? (isInt ? 1 : (hi - lo) / 100))
                    .accessibilityLabel(Text(label))
                    .accessibilityValue(Text(verbatim: shown(value)))
                }
            } else {
                LabeledContent(label) {
                    TextField(label, value: Binding(
                        get: { value.doubleValue ?? 0 },
                        set: { studio.set(param.key, to: param.kind == .int ? .int(Int($0)) : .double($0)) }
                    ), format: .number)
                    .labelsHidden()
                    .frame(width: 80)
                }
            }
        case .choice:
            Picker(label, selection: Binding(get: { value }, set: { studio.set(param.key, to: $0) })) {
                ForEach(param.choices, id: \.self) { choice in
                    Text(choiceText(choice)).tag(choice)
                }
            }
        case .text:
            TextField(label, text: Binding(get: { value.stringValue ?? "" }, set: { studio.set(param.key, to: .string($0)) }))
        case .path, .layers, .flags:
            LabeledContent(label) {
                Text(verbatim: plain(value)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
        }
    }

    private func shown(_ value: JSONValue) -> String {
        guard let number = value.doubleValue else { return plain(value) }
        return param.kind == .int ? "\(Int(number))" : model.texts.number(number, decimals: max(param.decimals, 1))
    }

    /// The choice as the export names it (its value as Python's str) → its text.
    private func choiceText(_ choice: JSONValue) -> String {
        let raw = plain(choice)
        return param.text.choices[raw].map { model.texts.tr($0) } ?? raw
    }

    private func plain(_ value: JSONValue) -> String {
        switch value {
        case .string(let s): s
        case .int(let i): "\(i)"
        case .double(let d): "\(d)"
        case .bool(let b): b ? "True" : "False"
        default: ""
        }
    }
}

// MARK: - the canvas

private struct CanvasArea: View {
    @Environment(AppModel.self) private var model
    @State private var sketch: Sketch?

    var body: some View {
        let live = model.studio.live
        let source = live.liveSVG ?? live.bestSVG ?? ""
        ZStack {
            if sketch == nil {
                Text(model.texts.tr("ui.canvas_placeholder"))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: Spacing.readingWidth)
            }
            SketchView(sketch: sketch, label: model.studio.canvasLabel(model.texts, sketch: sketch))
                .padding(Spacing.spaceXl)
        }
        .task(id: source) {
            guard !source.isEmpty else {
                sketch = nil
                return
            }
            // the live sketch is SVG text, the finished one a file
            let parsed = await Task.detached { () -> Sketch? in
                let text = source.hasPrefix("<") ? source : (try? String(contentsOfFile: source, encoding: .utf8)) ?? ""
                return try? SketchSVG.parse(text)
            }.value
            if let parsed { sketch = parsed }
        }
    }
}

// MARK: - the job bar

private struct JobBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let live = model.studio.live
        let ready = model.engineStatus == .ready
        GlassEffectContainer(spacing: Spacing.spaceS) {
            HStack(spacing: Spacing.spaceM) {
                if !ready {
                    Text(verbatim: model.engineStatusText)
                        .font(.callout)
                        .lineLimit(2)
                        .padding(.horizontal, Spacing.spaceM)
                        .padding(.vertical, Spacing.spaceS)
                        .glassEffect(.regular, in: .capsule)
                }
                if live.isActive {
                    HStack(spacing: Spacing.spaceS) {
                        ProgressView(value: live.progress)
                            .frame(width: 180)
                        if let eta = live.eta {
                            Text(verbatim: "\(model.texts.tr("ui.stat.eta")) \(Self.time(eta))")
                                .monospacedDigit()
                        }
                    }
                    .padding(.horizontal, Spacing.spaceM)
                    .padding(.vertical, Spacing.spaceS)
                    .glassEffect(.regular, in: .capsule)
                    .accessibilityElement(children: .combine)
                    Button(model.texts.tr(live.status == .paused ? "ui.resume" : "ui.pause"),
                           systemImage: live.status == .paused ? "play.fill" : "pause.fill") {
                        Task { await model.pauseOrResume() }
                    }
                    .buttonStyle(.glass)
                    Button(model.texts.tr("ui.cancel"), systemImage: "stop.fill") {
                        Task { await model.cancelJob() }
                    }
                    .buttonStyle(.glass)
                }
                Button(model.texts.tr("ui.start"), systemImage: "scribble") {
                    Task { await model.startSketch() }
                }
                .buttonStyle(.glassProminent)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!ready || !model.studio.canStart)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }

    /// Seconds as "1:05" or "1:02:05".
    static func time(_ seconds: Double) -> String {
        let s = max(0, Int(seconds.rounded()))
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%d:%02d", s / 60, s % 60)
    }
}
