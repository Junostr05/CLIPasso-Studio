import StudioApp
import StudioCore
import SwiftUI

/// The window app – or, with `--self-test`, the check of a built app without a window (SelfTest); with
/// `--screenshots` the window app draws its pages into files and ends (ScreenshotMode).
@main
@MainActor
enum Launcher {
    static func main() {
        let arguments = CommandLine.arguments
        if ScreenshotOptions.requested(in: arguments) {
            do {
                ScreenshotMode.options = try ScreenshotOptions(arguments: arguments)
            } catch {
                print(error)
                exit(2)
            }
        }
        guard SelfTest.Options.requested(in: arguments) else {
            CLIPassoStudioApp.main()
            return
        }
        Task { @MainActor in
            do {
                let options = try SelfTest.Options(arguments: arguments)
                let outcome = await SelfTest.run(options, resources: .current())
                print(outcome.lines.joined(separator: "\n"))
                exit(outcome.ok ? 0 : 1)
            } catch {
                print(error)
                exit(2)
            }
        }
        dispatchMain()
    }
}

struct CLIPassoStudioApp: App {
    @State private var model: AppModel?
    @State private var problem: String?

    init() {
        do {
            let store = try ScreenshotMode.options?.store() ?? .standard()  // (screenshots: settings of their own)
            _model = State(initialValue: try AppModel(resources: .current(), store: store))
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
        .defaultSize(width: 1280, height: 820)
    }
}
