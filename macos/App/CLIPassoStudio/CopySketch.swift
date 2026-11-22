import AppKit
import StudioApp
import StudioCore
import SwiftUI
import UniformTypeIdentifiers

/// "Copy" of the studio (dialogs.copy_sketch): the sketch on the clipboard with the last export's choices – its
/// colour, width, brush style, background (white for none), frame and paper – as a picture (PNG) and as an SVG, for
/// Word, Keynote, Figma … The PNG and the SVG are made on threads of their own.
enum SketchClipboard {
    static func copy(svg: String, runDir: URL?, model: AppModel) async throws {
        let options = ExportOptions.forClipboard(model.settings)
        let stylist = model.stylist(options.style)
        let copied = try await Task.detached(executorPreference: OwnThreads.shared) {
            let photo = runDir.flatMap { SketchFraming.runFrame(runDir: $0) }
            return try SketchExporter.clipboard(svg, options: options, photo: photo, stylist: stylist)
        }.value
        let item = NSPasteboardItem()
        item.setData(copied.png, forType: .png)
        item.setData(Data(copied.svg.utf8), forType: NSPasteboard.PasteboardType(UTType.svg.identifier))
        let board = NSPasteboard.general
        board.clearContents()
        board.writeObjects([item])
        // (VoiceOver says it; the studio shows a toast)
        NSAccessibility.post(element: NSApp as Any, notification: .announcementRequested,
                             userInfo: [.announcement: model.texts.tr("ui.copied"),
                                        .priority: NSAccessibilityPriorityLevel.medium.rawValue])
    }
}

/// Edit ▸ Copy Sketch (⇧⌘C – ⌘C stays the text fields' copy): the page in front says which sketch.
struct CopySketchAction {
    let run: () -> Void
}

extension FocusedValues {
    @Entry var copySketchAction: CopySketchAction?
}

struct CopySketchCommands: Commands {
    let texts: Texts?
    @FocusedValue(\.copySketchAction) private var action

    var body: some Commands {
        CommandGroup(after: .pasteboard) {
            Button(texts?.tr("ui.mac.copy_sketch") ?? "Copy Sketch") { action?.run() }
                .keyboardShortcut("c", modifiers: [.command, .shift])
                .disabled(action == nil)
        }
    }
}
