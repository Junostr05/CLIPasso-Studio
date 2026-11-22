import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The compare page (gui/pages/compare.py): the studio's picture, the methods to compare and whether the studio's
/// settings are used; below it every method's latest result for this picture side by side – its sketch, CLIP score,
/// time and strokes, the best marked –, and the verdict. Content: cards on the page, no glass.
struct CompareView: View {
    @Environment(AppModel.self) private var model
    let goStudio: () -> Void
    @State private var compare: CompareModel?
    @State private var asks: [String] = []
    @State private var answers: [String: Bool] = [:]
    @State private var queued: Int?

    var body: some View {
        let t = model.texts
        Group {
            if let compare, model.studio.image != nil {
                content(compare)
            } else {
                ContentUnavailableView {
                    Label(t.tr("ui.compare.empty_title"), systemImage: "square.split.2x1")
                } description: {
                    Text(t.tr("ui.compare.empty"))
                } actions: {
                    Button(t.tr("ui.empty.to_studio"), action: goStudio)
                }
            }
        }
        .navigationTitle(t.tr("ui.compare.title"))
        .navigationSubtitle(t.tr("ui.compare.subtitle"))
        .task {
            if compare == nil { compare = CompareModel(methods: model.schema.methods) }
            await model.gallery.refresh()
        }
        .alert(asks.first.map { t.tr($0 == "controlsketch_cpu" ? "ui.compare.cpu_warning" : "ui.compare.scene_cpu_warning") }
               ?? "", isPresented: Binding(get: { !asks.isEmpty }, set: { _ in })) {
            Button(t.tr("ui.mac.yes")) { answer(true) }
            Button(t.tr("ui.mac.no")) { answer(false) }
        }
        .alert(t.tr("ui.compare.queued", ["n": "\(queued ?? 0)"]), isPresented: Binding(
            get: { (queued ?? 0) > 0 }, set: { if !$0 { queued = nil } })) {}
    }

    private func content(_ compare: CompareModel) -> some View {
        let t = model.texts
        let entries = model.compareOverview(model.studio.image)
        return ScrollView {
            VStack(alignment: .leading, spacing: Spacing.spaceL) {
                setup(compare)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: Spacing.spaceL)],
                          spacing: Spacing.spaceL) {
                    ForEach(entries) { CompareCard(entry: $0) }
                }
                Text(verdict(entries)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            .padding(Spacing.spaceL)
        }
        .accessibilityLabel(t.tr("ui.compare.title"))
    }

    private func setup(_ compare: CompareModel) -> some View {
        @Bindable var compare = compare
        let t = model.texts
        return HStack(alignment: .center, spacing: Spacing.spaceL) {
            if let image = model.studio.image, let picture = NSImage(contentsOf: image) {
                Image(nsImage: picture).resizable().scaledToFit().frame(width: 84, height: 84)
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                Text(verbatim: model.studio.image?.lastPathComponent ?? "").font(.headline)
                Text(t.tr("ui.compare.image_hint")).font(.caption).foregroundStyle(.secondary)
                // (the methods as boxes to tick, each name whole; in two rows where one is too narrow)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: Spacing.spaceL) { methodBoxes(compare, model.schema.methods) }
                    VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                        HStack(spacing: Spacing.spaceL) { methodBoxes(compare, Array(model.schema.methods.prefix(2))) }
                        HStack(spacing: Spacing.spaceL) { methodBoxes(compare, Array(model.schema.methods.dropFirst(2))) }
                    }
                }
                .padding(.top, Spacing.spaceXs)
                Toggle(t.tr("ui.compare.use_studio"), isOn: $compare.useStudio)
                    .toggleStyle(.checkbox)
                    .help(t.tr("ui.compare.use_studio_tip"))
            }
            Spacer(minLength: Spacing.spaceM)
            Button(t.tr("ui.compare.start"), systemImage: "play.fill") { start(compare) }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .fixedSize()
                .disabled(compare.chosen.isEmpty || model.engine == nil)
        }
        .padding(Spacing.spaceL)
        .background(CompareCard.surface)
    }

    @ViewBuilder
    private func methodBoxes(_ compare: CompareModel, _ methods: [String]) -> some View {
        ForEach(methods, id: \.self) { method in
            Toggle(model.schema.method(method)?.name ?? method, isOn: Binding(
                get: { compare.chosen.contains(method) },
                set: { if $0 { compare.chosen.insert(method) } else { compare.chosen.remove(method) } }))
                .toggleStyle(.checkbox)
                .fixedSize()
                .help(model.texts.tr("method.\(method).tagline"))
        }
    }

    private func verdict(_ entries: [CompareModel.Entry]) -> String {
        guard let best = entries.first(where: \.best), let score = best.score else {
            return model.texts.tr("ui.compare.verdict_none")
        }
        return model.texts.tr("ui.compare.verdict", ["method": model.schema.method(best.method)?.name ?? best.method,
                                                     "score": model.texts.number(score)])
    }

    /// compare.start: the questions first (without a GPU), then the jobs.
    private func start(_ compare: CompareModel) {
        Task {
            answers = [:]
            asks = await model.compareQuestions(compare.chosen, useStudio: compare.useStudio)
            if asks.isEmpty { queued = await model.startCompare(compare) }
        }
    }

    private func answer(_ yes: Bool) {
        guard let key = asks.first, let compare else { return }
        answers[key] = yes
        asks.removeFirst()
        if asks.isEmpty {
            let given = answers
            Task { queued = await model.startCompare(compare, answers: given) }
        }
    }
}

/// One method's column (compare.CompareCard): its name and tagline, the best's badge, the sketch, the job's progress,
/// CLIP score, time and strokes, where the result is from; open it in the studio or export it.
struct CompareCard: View {
    @Environment(AppModel.self) private var model
    let entry: CompareModel.Entry
    @State private var sketch: Sketch?
    @State private var exporting: ExportSource?

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceS) {
            HStack {
                Text(verbatim: model.schema.method(entry.method)?.name ?? entry.method).font(.title3.bold())
                Spacer()
                if entry.best {
                    Text(verbatim: "★ " + t.tr("ui.compare.best"))
                        .font(.caption.bold())
                        .padding(.horizontal, Spacing.spaceS).padding(.vertical, 2)
                        .background(Capsule().fill(Color.green.opacity(0.2)))
                }
            }
            Text(t.tr("method.\(entry.method).tagline")).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ZStack {
                RoundedRectangle(cornerRadius: Radius.card).fill(Color(nsColor: .textBackgroundColor).opacity(0.5))
                if sketch != nil {
                    SketchView(sketch: sketch, label: t.tr("ui.mac.canvas_label", [
                        "image": entry.item?.name ?? "", "strokes": "\(sketch?.strokes.count ?? 0)"]))
                        .environment(\.canvasStretch, model.canvasStretch(runDir: entry.item.flatMap { ExportSource.bestRun(of: $0) }))
                } else {
                    Text(t.tr("ui.compare.placeholder")).font(.caption).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center).padding(Spacing.spaceL)
                        .frame(maxWidth: .infinity)
                }
            }
            // (as wide as the card, as high as wide: the sketch large, the note across)
            .frame(maxWidth: .infinity)
            .aspectRatio(1, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: Radius.card))
            if entry.state == .running || entry.state == .queued {
                ProgressView(value: entry.progress).accessibilityLabel(state)
            }
            HStack(spacing: Spacing.spaceL) {
                stat(entry.score.map { t.number($0) } ?? "–", t.tr("ui.stat.score"))
                stat(entry.seconds > 0 ? PhoneRemote.eta(entry.seconds) : "–", t.tr("ui.compare.time"))
                stat(entry.item != nil ? "\(entry.strokes)" : "–", t.tr("ui.compare.strokes"))
            }
            Text(verbatim: state).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: Spacing.spaceS) {
                Button(t.tr("ui.compare.open"), systemImage: "paintbrush.pointed") {
                    if let item = entry.item { model.studio.open(item) }
                }
                .disabled(entry.item == nil)
                Button(t.tr("ui.compare.export"), systemImage: "square.and.arrow.up") {
                    exporting = entry.item.flatMap { ExportSource.best(of: $0) }
                }
                .labelStyle(.iconOnly)
                .help(t.tr("ui.compare.export"))
                .disabled(entry.item?.bestSketch == nil)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .lineLimit(1)
        }
        .padding(Spacing.spaceL)
        .background(Self.surface)
        .accessibilityElement(children: .contain)
        .sheet(item: $exporting) { ExportSheet(source: $0, settings: model.settings) }
        .task(id: "\(entry.item?.bestSketch?.path ?? "")|\(model.canvasStyle)") {
            guard let url = entry.item?.bestSketch else {
                sketch = nil
                return
            }
            sketch = await model.gallerySketch(url)
        }
    }

    /// A card on the page: a surface a step off the window's, with an edge (in both themes).
    static var surface: some View {
        RoundedRectangle(cornerRadius: Radius.card)
            .fill(Color(nsColor: .controlBackgroundColor))
            .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Color(nsColor: .separatorColor)))
    }

    private var state: String {
        let t = model.texts
        switch entry.state {
        case .running: return t.tr("ui.compare.running")
        case .queued: return t.tr("ui.compare.queued_one")
        case .done: return t.tr("ui.compare.from", ["date": String((entry.item?.created ?? "").prefix(16))])
        case .none: return t.tr("ui.compare.none")
        }
    }

    private func stat(_ value: String, _ caption: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(verbatim: value).font(.title3.monospacedDigit())
            Text(caption).font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}
