import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// `--screenshots`: the window of every page in both languages and appearances, drawn into PNG files (the view
/// hierarchy draws itself – no screen-recording permission needed; materials may look flatter than on screen).
@MainActor
enum ScreenshotMode {
    static var options: ScreenshotOptions?

    static func run(_ options: ScreenshotOptions, model: AppModel, show: @escaping (Page) -> Void) async {
        let sample = Bundle.main.resourceURL?.appending(path: "engine/clipasso_studio/resources/samples/camel.png")
        if let sample, FileManager.default.fileExists(atPath: sample.path) { model.studio.image = sample }
        let deadline = ContinuousClock.now + .seconds(180)
        while model.engineStatus != .ready, ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }
        await model.gallery.refresh()
        var written = 0
        for shot in options.shots(pages: Page.allCases.map(\.rawValue)) {
            try? model.setLanguage(shot.language)
            model.setAppearance(shot.appearance)
            show(Page(rawValue: shot.page) ?? .studio)
            try? await Task.sleep(for: .milliseconds(1500))  // (laid out, images and sketches loaded)
            if capture(to: shot.file) { written += 1 }
        }
        print("screenshots: \(written) written to \(options.output.path)")
        NSApp.terminate(nil)
    }

    /// The front window with its title bar, as it draws itself.
    static func capture(to url: URL) -> Bool {
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }),
              let content = window.contentView
        else { return false }
        let view = content.superview ?? content
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else { return false }
        return (try? data.write(to: url, options: .atomic)) != nil
    }
}
