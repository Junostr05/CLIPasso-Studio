import StudioApp
import StudioCore
import SwiftUI

/// The models a job needs that are not there (dialogs.ModelDownloadDialog): their names and size, *Download* and
/// *Cancel*; then the progress. A cancelled download stays for the next time.
struct ModelSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let flow = model.models
        let palette = scheme == .dark ? Palette.dark : Palette.light
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(model.texts.tr("ui.download_models"))
                .font(.title2.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            switch flow.stage {
            case .asking:
                Text(flow.question(model.texts))
                    .fixedSize(horizontal: false, vertical: true)
            case .downloading(let key, _, _):
                Text(model.texts.tr("ui.downloading", ["name": flow.name(key)]))
                ProgressView(value: flow.fraction ?? 0)
            case .converting(let key):
                Text(model.texts.tr("ui.downloading", ["name": flow.name(key)]))
                ProgressView()
                    .progressViewStyle(.linear)
            case .failed(let text):
                Text(verbatim: text)
                    .foregroundStyle(Color(hex: palette.danger_text))  // (measured: AA in both themes)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            case .idle:
                EmptyView()
            }
            HStack {
                Spacer()
                Button(model.texts.tr("ui.cancel"), role: .cancel) {
                    model.cancelDownload()
                }
                .keyboardShortcut(.cancelAction)
                if case .asking = flow.stage {
                    Button(model.texts.tr("ui.download")) {
                        model.confirmDownload()
                    }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(Spacing.spaceXl)
        .frame(width: 440)
    }
}
