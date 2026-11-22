import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// The server for an AI in the settings (MCP): on or off, its port, whether it runs, the line that sets it up in
/// Claude Code (copied with the token, shown without it) and a new token.
struct MCPSettings: View {
    @Environment(AppModel.self) private var model
    @State private var port = ""
    @State private var copied = false

    var body: some View {
        let t = model.texts
        let mcp = model.mcp
        Section {
            Text(t.tr("ui.mac.mcp.desc")).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Toggle(t.tr("ui.mac.mcp.on"), isOn: Binding(
                get: { model.settings["mcp_on"]?.truthy ?? false },
                set: { on in Task { await model.setMCP(on) } }))
            LabeledContent(t.tr("ui.mac.mcp.port")) {
                TextField(t.tr("ui.mac.mcp.port"), text: $port)
                    .labelsHidden()
                    .frame(width: 90)
                    .multilineTextAlignment(.trailing)
                    .monospacedDigit()
                    .onSubmit { submitPort() }
            }
            LabeledContent(t.tr("ui.mac.mcp.state")) {
                if mcp.running {
                    Label(t.tr("ui.mac.mcp.running", ["port": "\(mcp.port)"]), systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else if !mcp.error.isEmpty {
                    Text(verbatim: mcp.error).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                } else {
                    Text(t.tr("ui.mac.mcp.off")).foregroundStyle(.secondary)
                }
            }
            VStack(alignment: .leading, spacing: Spacing.spaceXs) {
                Text(t.tr("ui.mac.mcp.command")).font(.caption).foregroundStyle(.secondary)
                Text(verbatim: shownCommand)
                    .font(.caption.monospaced())
                    .textSelection(.disabled)  // (the token only through the button)
                    .padding(Spacing.spaceS)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: Radius.control).fill(.quaternary))
                HStack {
                    Button(copied ? t.tr("ui.mac.mcp.copied") : t.tr("ui.mac.mcp.copy"),
                           systemImage: copied ? "checkmark" : "doc.on.doc") { copy() }
                    Button(t.tr("ui.mac.mcp.new_token"), systemImage: "key") {
                        Task { await model.newMCPToken() }
                    }
                    .help(t.tr("ui.mac.mcp.new_token_tip"))
                }
            }
            Text(t.tr("ui.mac.mcp.local")).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } header: {
            Text(t.tr("ui.mac.mcp.title"))
        }
        .onAppear { port = "\(model.mcpPort)" }
    }

    /// The command with the token hidden (it is a key to the app).
    private var shownCommand: String {
        let token = model.mcpToken
        return model.mcpCommand.replacingOccurrences(of: token, with: String(repeating: "•", count: 12))
    }

    private func copy() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(model.mcpCommand, forType: .string)
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }

    private func submitPort() {
        guard let value = Int(port.trimmingCharacters(in: .whitespaces)), (1024 ... 65535).contains(value) else {
            port = "\(model.mcpPort)"
            return
        }
        Task { await model.setMCP(model.settings["mcp_on"]?.truthy ?? false, port: value) }
    }
}
