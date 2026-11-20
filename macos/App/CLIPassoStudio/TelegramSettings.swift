import AppKit
import StudioApp
import StudioCore
import SwiftUI

/// Telegram in the settings (phone_ui's Telegram box): on or off; when on, how to set up the bot, its token (kept in
/// the Keychain), "Connect" and the line that says how it stands, when a message goes and whether with the picture,
/// and a test message.
struct TelegramSettings: View {
    @Environment(AppModel.self) private var model
    @State private var token = ""

    var body: some View {
        let t = model.texts
        let link = model.telegram
        Section {
            Toggle(t.tr("ui.telegram.label"), isOn: Binding(get: { model.settings["telegram_on"]?.truthy ?? false },
                                                            set: { model.setTelegram($0) }))
            if (model.settings["telegram_on"]?.truthy ?? false) || link.connecting {
                Text(Self.help(t.tr("ui.telegram.help"))).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    SecureField(t.tr("ui.telegram.token"), text: $token)
                        .onSubmit { model.setTelegramToken(token) }
                    Button(t.tr("ui.telegram.connect")) {
                        model.setTelegramToken(token)
                        Task { await model.connectTelegram() }
                    }
                    .disabled(link.connecting)
                }
                HStack(spacing: Spacing.spaceS) {
                    if link.connecting { ProgressView().controlSize(.small) }
                    Text(verbatim: link.status).foregroundStyle(.secondary)
                }
                HStack(spacing: Spacing.spaceL) {
                    ForEach(["done", "failed", "photo"], id: \.self) { key in
                        Toggle(t.tr("ui.telegram.on_\(key)"), isOn: Binding(get: { model.telegramOption(key) },
                                                                          set: { model.setTelegramOption(key, $0) }))
                    }
                }
                Button(t.tr("ui.telegram.test_button")) { model.telegramTest() }
                    .disabled(!model.telegramConfigured)
            }
        }
        .onAppear {
            token = model.telegramToken
            model.refreshTelegramStatus()
        }
        .onDisappear { model.cancelTelegramConnect() }
    }

    /// The help with its link to @BotFather (the studio's text is HTML).
    static func help(_ html: String) -> AttributedString {
        let markdown = html.replacingOccurrences(of: "<a href='https://t.me/BotFather'>@BotFather</a>",
                                                 with: "[@BotFather](https://t.me/BotFather)")
        return (try? AttributedString(markdown: markdown)) ?? AttributedString(markdown)
    }
}
