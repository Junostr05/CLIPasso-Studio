import AppKit
import ScreenCaptureKit
import StudioApp
import StudioCore
import SwiftUI

/// `--screenshots`: the window of every page in both languages and appearances as PNG files – as the window server
/// shows it, with its Liquid Glass (ScreenCaptureKit with the app's own windows: no screen-recording permission
/// needed). Where that fails the window draws itself instead, and the log says so once: the view hierarchy does not
/// draw the glass (the sidebar and the toolbar's buttons stay empty).
@MainActor
enum ScreenshotMode {
    static var options: ScreenshotOptions?
    private static var toldDrawn = false

    struct CaptureError: Error, CustomStringConvertible {
        let description: String
    }

    static func run(_ options: ScreenshotOptions, model: AppModel, show: @escaping (Page) -> Void) async {
        let sample = Bundle.main.resourceURL?.appending(path: "engine/clipasso_studio/resources/samples/camel.png")
        if let sample, FileManager.default.fileExists(atPath: sample.path) { model.studio.image = sample }
        let deadline = ContinuousClock.now + .seconds(180)
        while model.engineStatus != .ready, ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }
        await model.gallery.refresh()
        if let result = model.gallery.items.first { model.studio.open(result) }  // (the studio with a sketch to edit)
        NSApp.activate()  // (a window in front draws its selection and its main button as in use, not greyed)
        NSApp.windows.first { $0.isVisible }?.makeKeyAndOrderFront(nil)
        var written = 0
        for shot in options.shots(pages: Page.allCases.map(\.rawValue)) {
            try? model.setLanguage(shot.language)
            model.setAppearance(shot.appearance)
            show(Page(rawValue: shot.page) ?? .studio)
            try? await Task.sleep(for: .milliseconds(1500))  // (laid out, images and sketches loaded)
            if await capture(to: shot.file) { written += 1 }
        }
        print("screenshots: \(written) written to \(options.output.path)")
        NSApp.terminate(nil)
    }

    /// The front window with its title bar.
    static func capture(to url: URL) async -> Bool {
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }) else { return false }
        do {
            let png = try await composited(windowID: CGWindowID(window.windowNumber))
            return (try? png.write(to: url, options: .atomic)) != nil
        } catch {
            if !toldDrawn {
                print("screenshots: ScreenCaptureKit failed (\(error)) – the window draws itself, without its glass")
                toldDrawn = true
            }
            return drawn(window, to: url)
        }
    }

    /// The window as the window server composites it, as PNG.
    nonisolated static func composited(windowID: CGWindowID) async throws -> Data {
        let content = try await SCShareableContent.currentProcess
        guard let shared = content.windows.first(where: { $0.windowID == windowID }) else {
            throw CaptureError(description: "window \(windowID) is not among the app's own")
        }
        let filter = SCContentFilter(desktopIndependentWindow: shared)
        let configuration = SCStreamConfiguration()
        configuration.width = Int(filter.contentRect.width * CGFloat(filter.pointPixelScale))
        configuration.height = Int(filter.contentRect.height * CGFloat(filter.pointPixelScale))
        configuration.showsCursor = false
        configuration.ignoreShadowsSingleWindow = true
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
        return try SketchRenderer.pngData(image)
    }

    /// The window as its view hierarchy draws itself (no glass).
    static func drawn(_ window: NSWindow, to url: URL) -> Bool {
        guard let content = window.contentView else { return false }
        let view = content.superview ?? content
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else { return false }
        return (try? data.write(to: url, options: .atomic)) != nil
    }
}
