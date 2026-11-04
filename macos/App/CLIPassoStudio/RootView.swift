import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The pages of the window, as in the studio's navigation.
enum Page: String, CaseIterable, Identifiable {
    case studio, queue, gallery, models, settings

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .studio: "nav.studio"
        case .queue: "nav.queue"
        case .gallery: "nav.gallery"
        case .models: "ui.models.title"
        case .settings: "ui.settings.title"
        }
    }

    var symbol: String {
        switch self {
        case .studio: "paintbrush.pointed"
        case .queue: "list.bullet.rectangle"
        case .gallery: "square.grid.2x2"
        case .models: "shippingbox"
        case .settings: "gearshape"
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var page: Page? = .studio

    var body: some View {
        NavigationSplitView {
            List(Page.allCases, selection: $page) { item in
                Label(model.texts.tr(item.titleKey), systemImage: item.symbol)
                    .tag(item)
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 260)
        } detail: {
            Group {
                switch page ?? .studio {
                case .studio: StudioView()
                case .queue: QueueView()
                case .gallery: GalleryView()
                case .models: ModelsView()
                case .settings: SettingsView()
                }
            }
            .safeAreaInset(edge: .top) {
                if let update = model.update { UpdateBanner(update: update) }
            }
        }
        .preferredColorScheme(model.appearance == .system ? nil : model.appearance == .dark ? .dark : .light)
        .task {
            if let options = ScreenshotMode.options {
                await ScreenshotMode.run(options, model: model) { page = $0 }
            }
        }
        // the models a job or the Models page asked for (one sheet for the window)
        .sheet(isPresented: Binding(get: { model.models.stage != .idle },
                                    set: { if !$0 { model.cancelDownload() } })) {
            ModelSheet()
                .environment(model)
        }
        // the queue ran out with "when done" chosen
        .sheet(isPresented: Binding(get: { model.countdown.map { !$0.finished } ?? false },
                                    set: { if !$0 { model.countdown?.cancel() } })) {
            if let countdown = model.countdown {
                CountdownSheet(countdown: countdown)
                    .environment(model)
            }
        }
    }
}

/// A newer release with a Mac disk image: its page opens in the browser (the app is not signed, so it does not
/// update itself). Content: a plain banner.
private struct UpdateBanner: View {
    @Environment(AppModel.self) private var model
    let update: UpdateCheck.Release

    var body: some View {
        HStack(spacing: Spacing.spaceM) {
            Image(systemName: "arrow.down.circle").accessibilityHidden(true)
            Text(model.texts.tr("ui.update.available", ["version": update.version, "current": model.version]))
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button(model.texts.tr("ui.update.download")) { NSWorkspace.shared.open(update.page) }
            Button(model.texts.tr("ui.update.skip")) { model.skipUpdate() }
            Button(model.texts.tr("ui.update.later")) { model.dismissUpdate() }
        }
        .padding(.horizontal, Spacing.spaceL)
        .padding(.vertical, Spacing.spaceS)
        .background(Color(nsColor: .controlBackgroundColor))
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }
}
