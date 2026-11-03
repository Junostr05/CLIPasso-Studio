import StudioApp
import StudioCore
import SwiftUI

@main
struct CLIPassoStudioApp: App {
    @State private var model: AppModel?
    @State private var problem: String?

    init() {
        do {
            _model = State(initialValue: try AppModel(resources: .current(), language: "auto"))
        } catch {
            _problem = State(initialValue: String(describing: error))
        }
    }

    var body: some Scene {
        WindowGroup {
            if let model {
                RootView()
                    .environment(model)
                    .task { await model.startEngine() }
                    .frame(minWidth: 960, minHeight: 640)
            } else {
                // (the app's own files are missing – only when the bundle is broken)
                ContentUnavailableView("CLIPasso Studio", systemImage: "exclamationmark.triangle",
                                       description: Text(verbatim: problem ?? ""))
            }
        }
    }
}
