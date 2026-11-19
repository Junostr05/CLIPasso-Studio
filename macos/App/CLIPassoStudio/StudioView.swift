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
    @Environment(\.colorScheme) private var scheme
    @State private var importing = false
    /// the image editor (crop, turn, mirror)
    @State private var cropping = false
    @State private var preview: NSImage?
    @State private var targeted = false
    /// the object mask over the image (mask_view.overlay)
    @State private var overlay: CGImage?
    /// the mask being touched up
    @State private var editing: MaskEditorModel?
    /// the detail map being painted, whether the engine keeps one for the image, what became of the last
    @State private var detailing: DetailEditorModel?
    @State private var hasDetails = false
    @State private var detailNote = ""

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
                        .overlay {
                            if let overlay, model.showsMask {
                                Image(decorative: overlay, scale: 1).resizable().scaledToFit()
                            }
                        }
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
            maskRow
            HStack(spacing: Spacing.spaceS) {
                Button(model.texts.tr(studio.image == nil ? "ui.step.open" : "ui.step.change"), systemImage: "folder") {
                    importing = true
                }
                .fileImporter(isPresented: $importing, allowedContentTypes: [.image]) { result in
                    if case .success(let url) = result { studio.image = url }
                }
                Button(model.texts.tr("ui.edit_image.button"), systemImage: "crop") { cropping = true }
                    .labelStyle(.iconOnly)
                    .help(model.texts.tr("ui.edit_image.tip"))
                    .disabled(studio.image == nil)
                Button(model.texts.tr("ui.detail.title"), systemImage: "sparkles") { openDetails() }
                    .labelStyle(.iconOnly)
                    .help(detailTip)
                    .disabled(studio.image == nil || !engineReady)
            }
            if !detailNote.isEmpty {
                Text(verbatim: detailNote).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
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
        .task(id: maskKey) { await model.updateMask() }
        .sheet(item: $editing) { MaskEditorSheet(editor: $0) }
        .sheet(isPresented: $cropping) {
            if let image = studio.image { ImageEditSheet(source: image) }
        }
        .sheet(item: $detailing) { editor in
            DetailEditorSheet(editor: editor) {
                hasDetails = true
                detailNote = model.texts.tr("ui.detail.saved")
            }
        }
        .task(id: [studio.image?.path ?? "", "\(engineReady)"]) {
            detailNote = ""
            hasDetails = await model.hasDetails()
        }
        .task(id: [model.mask.version, scheme == .dark ? 1 : 0]) {
            overlay = await Self.overlay(model.mask, dark: scheme == .dark)
        }
    }

    private var engineReady: Bool {
        if case .ready = model.engineStatus { return true }
        return false
    }

    /// _update_detail_button: the brush, whether a map is kept for the image, whether the method uses it.
    private var detailTip: String {
        let t = model.texts
        var tip = t.tr("ui.detail.tip")
        if hasDetails { tip += "\n" + t.tr("ui.detail.has") }
        if !["clipasso", "controlsketch"].contains(model.studio.method) { tip += "\n" + t.tr("ui.detail.not_used") }
        return tip
    }

    private func openDetails() {
        detailNote = ""
        Task {
            do {
                detailing = try await model.detailEditor()
            } catch {
                detailNote = String(describing: error)
            }
        }
    }

    /// What decides whether and which mask is asked for: the image, whether the run uses one, its model, the engine.
    private var maskKey: String {
        let studio = model.studio
        var ready = false
        if case .ready = model.engineStatus { ready = true }
        return [studio.image?.path ?? "", studio.method, studio.settings["mask_model"]?.stringValue ?? "",
                "\(studio.isEnabled("mask_model"))", "\(ready)"].joined(separator: "|")
    }

    /// The mask's state under the image (studio.py's mask row): what the engine does, the eye that shows the mask,
    /// back to the model's mask after the user's.
    @ViewBuilder private var maskRow: some View {
        let mask = model.mask
        if mask.state != .off {
            HStack(spacing: Spacing.spaceS) {
                if mask.state == .busy { ProgressView().controlSize(.small) }
                Text(verbatim: mask.status(model.texts, name: model.modelName(mask.model)))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .help(Self.failure(mask.state))
                Spacer()
                Toggle(isOn: Binding(get: { model.showsMask }, set: { model.setShowsMask($0) })) {
                    Label(model.texts.tr("ui.mask.show"), systemImage: "eye")
                }
                .toggleStyle(.button)
                .labelStyle(.iconOnly)
                .help(model.texts.tr("ui.mask.show"))
                .disabled(mask.state != .ready && mask.state != .edited)
                Button(model.texts.tr("ui.mask.edit"), systemImage: "paintbrush") {
                    editing = model.maskEditor()
                }
                .labelStyle(.iconOnly)
                .help(model.texts.tr("ui.mask.edit"))
                .disabled(mask.state != .ready && mask.state != .edited)
                if mask.state == .edited {
                    Button(model.texts.tr("ui.mask.reset"), systemImage: "arrow.uturn.backward") {
                        Task { await model.resetMask() }
                    }
                    .labelStyle(.iconOnly)
                    .help(model.texts.tr("ui.mask.reset"))
                }
            }
        }
    }

    private static func failure(_ state: StudioMask.State) -> String {
        if case .failed(let why) = state { return why }
        return ""
    }

    /// The overlay of the mask (700 pixels at most, as the studio's), off the main actor: the background under the
    /// surface colour, the object outlined in the accent.
    private static func overlay(_ mask: StudioMask, dark: Bool) async -> CGImage? {
        guard !mask.object.isEmpty else { return nil }
        let palette = dark ? Palette.dark : Palette.light
        let veil = SketchSVG.color(palette.surface2) ?? RGB(240, 240, 236)
        let edge = SketchSVG.color(palette.accent) ?? RGB(60, 110, 240)
        let (object, width, height) = (mask.object, mask.width, mask.height)
        return await Task.detached(executorPreference: OwnThreads.shared) { () -> CGImage? in
            MaskPictures.overlay(object, width: width, height: height,
                                 veil: (UInt8(veil.r), UInt8(veil.g), UInt8(veil.b), 215),
                                 edge: (UInt8(edge.r), UInt8(edge.g), UInt8(edge.b), 255), maxSide: 700)
        }.value
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

/// "My presets" (param_panel's menu): the own presets of every method (one of another method switches to it),
/// the current settings kept under a name, one deleted. Content: a menu button with an alert asking for the name.
private struct UserPresetMenu: View {
    @Environment(AppModel.self) private var model
    @State private var naming = false
    @State private var name = ""

    var body: some View {
        let t = model.texts
        let presets = model.userPresets
        let active = model.userPreset
        Menu {
            if presets.isEmpty {
                Text(t.tr("ui.user_presets.none"))
            }
            ForEach(presets, id: \.self) { preset in
                Button(title(preset)) { model.applyUserPreset(preset.name, method: preset.method) }
            }
            Divider()
            Button(t.tr("ui.user_presets.save")) {
                name = active
                naming = true
            }
            if !presets.isEmpty {
                Menu(t.tr("ui.user_presets.delete")) {
                    ForEach(presets, id: \.self) { preset in
                        Button(title(preset), role: .destructive) {
                            model.deleteUserPreset(preset.name, method: preset.method)
                        }
                    }
                }
            }
        } label: {
            Label(active.isEmpty ? t.tr("ui.mac.user_presets") : t.tr("ui.user_presets.active", ["name": active]),
                  systemImage: "bookmark")
        }
        .fixedSize()
        .help(t.tr("ui.user_presets.tip"))
        .alert(t.tr("ui.user_presets.save_title"), isPresented: $naming) {
            TextField(t.tr("ui.user_presets.name"), text: $name)
            Button(t.tr("ui.save")) { model.saveUserPreset(name) }
            Button(t.tr("ui.cancel"), role: .cancel) {}
        } message: {
            Text(t.tr("ui.user_presets.name"))
        }
    }

    /// Its name – with its method's when that is not the studio's.
    private func title(_ preset: UserPresets.Preset) -> String {
        guard preset.method != model.studio.method else { return preset.name }
        return "\(preset.name) · \(model.schema.method(preset.method)?.name ?? preset.method)"
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
                UserPresetMenu()
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

    var body: some View {
        if !model.studio.live.isActive, let result = model.studio.result {
            ResultCanvas(result: result)  // a finished job: its sketches, to touch up
        } else {
            LiveCanvas()
        }
    }
}

/// The sketch of the job under way – or of the last one when it left no result to show.
private struct LiveCanvas: View {
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
        .safeAreaInset(edge: .bottom) {
            if live.sketches.count > 1 { JobSketches(sketches: live.sketches) }
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

/// The job's sketches so far, one per item (ui.step.sketches), small on paper.
private struct JobSketches: View {
    @Environment(AppModel.self) private var model
    let sketches: [SeedSketch]
    @State private var parsed: [Int: Sketch] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.spaceXs) {
            Text(model.texts.tr("ui.step.sketches")).font(.caption).foregroundStyle(.secondary)
                .accessibilityAddTraits(.isHeader)
            ScrollView(.horizontal) {
                HStack(spacing: Spacing.spaceS) {
                    ForEach(sketches) { item in
                        SketchView(sketch: parsed[item.seed], label: model.texts.tr("ui.mac.canvas_label", [
                            "image": model.studio.image?.lastPathComponent ?? "",
                            "strokes": "\(parsed[item.seed]?.strokes.count ?? 0)"]))
                            .frame(width: 88, height: 88)
                            .clipShape(RoundedRectangle(cornerRadius: Radius.control))
                    }
                }
            }
        }
        .padding(.horizontal, Spacing.spaceXl)
        .padding(.bottom, Spacing.spaceS)
        .task(id: sketches) {
            let given = sketches
            let fresh = await Task.detached { () -> [Int: Sketch] in
                var out: [Int: Sketch] = [:]
                for item in given {
                    out[item.seed] = try? SketchSVG.parse(item.svg)
                }
                return out
            }.value
            parsed = fresh
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
