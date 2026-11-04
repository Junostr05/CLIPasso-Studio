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
            switch page ?? .studio {
            case .studio: StudioView()
            case .queue: QueueView()
            case .gallery: GalleryView()
            case .models: ModelsView()
            case let other: PageView(page: other)
            }
        }
        // the models a job or the Models page asked for (one sheet for the window)
        .sheet(isPresented: Binding(get: { model.models.stage != .idle },
                                    set: { if !$0 { model.cancelDownload() } })) {
            ModelSheet()
                .environment(model)
        }
    }
}

/// A page – the first release fills them one after the other (docs/macos/phase2-app-plan.md).
struct PageView: View {
    @Environment(AppModel.self) private var model
    let page: Page

    var body: some View {
        VStack(spacing: Spacing.spaceL) {
            ContentUnavailableView(model.texts.tr(page.titleKey), systemImage: page.symbol)
            if !model.engineStatusText.isEmpty {
                Text(verbatim: model.engineStatusText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: Spacing.readingWidth)
                    .padding(.bottom, Spacing.spaceXl)
            }
        }
        .navigationTitle(model.texts.tr(page.titleKey))
    }
}
