import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The system section of the settings page (gui/pages SettingsPage's "System"): the diagnostics copied or saved, a
/// problem reported on GitHub. Content: a section of the grouped form.
struct SystemSettings: View {
    @Environment(AppModel.self) private var model
    @State private var copied = false
    @State private var reporting: String?

    var body: some View {
        let t = model.texts
        Section(t.tr("ui.settings.system")) {
            HStack {
                Button(t.tr(copied ? "ui.diag.copied" : "ui.diag.copy")) {
                    Task {
                        let text = await model.diagnostics()
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(text, forType: .string)
                        copied = true
                        try? await Task.sleep(for: .seconds(2.5))
                        copied = false
                    }
                }
                Button(t.tr("ui.diag.save")) {
                    let panel = NSSavePanel()
                    panel.nameFieldStringValue = AppModel.diagnosticsFileName()
                    panel.allowedContentTypes = [.plainText]
                    guard panel.runModal() == .OK, let url = panel.url else { return }
                    Task { try? Data(await model.diagnostics().utf8).write(to: url) }
                }
                Button(t.tr("ui.report.button")) {
                    Task { reporting = await model.diagnostics() }
                }
                .help(t.tr("ui.report.tip"))
            }
            .help(t.tr("ui.diag.tip"))
        }
        .sheet(isPresented: Binding(get: { reporting != nil }, set: { if !$0 { reporting = nil } })) {
            if let reporting { ReportSheet(diagnostics: reporting, version: model.version) }
        }
    }
}

/// The prepared issue (report.ReportDialog): its title and text to check and change, *Copy*, *Report on GitHub*
/// (opened in the browser; the full text also goes to the clipboard).
struct ReportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var title: String
    @State private var text: String
    @State private var note = ""

    init(message: String = "", traceback: String = "", diagnostics: String, version: String) {
        _title = State(initialValue: ProblemReport.title(message, version: version))
        _text = State(initialValue: ProblemReport.body(message, traceback: traceback, diagnostics: diagnostics))
    }

    var body: some View {
        let t = model.texts
        VStack(alignment: .leading, spacing: Spacing.spaceM) {
            Text(t.tr("ui.report.title")).font(.title2)
            Text(t.tr("ui.report.desc")).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField(t.tr("ui.report.title"), text: $title)
            TextEditor(text: $text)
                .font(.system(.body, design: .monospaced))
                .frame(minHeight: 280)
            if !note.isEmpty { Text(verbatim: note).font(.callout).foregroundStyle(.secondary) }
            HStack {
                Button(t.tr("ui.report.copy")) {
                    copy("\(title)\n\n\(text)")
                    note = t.tr("ui.report.copied")
                }
                Spacer()
                Button(t.tr("ui.cancel"), role: .cancel) { dismiss() }
                Button(t.tr("ui.report.send")) {
                    copy(text)
                    let made = ProblemReport.url(title: title, body: text)
                    if let url = URL(string: made.url) { NSWorkspace.shared.open(url) }
                    note = t.tr(made.cut ? "ui.report.cut" : "ui.report.opened")
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(Spacing.spaceL)
        .frame(width: 640)
    }

    private func copy(_ string: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(string, forType: .string)
    }
}
