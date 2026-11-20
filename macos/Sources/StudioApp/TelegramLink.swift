import Foundation
import Observation
import StudioCore
import Synchronization

/// Telegram in the settings and after each job (phone_ui's Telegram box, telegram.Notifier): the line that says how
/// it stands, "Connect" waiting for /start, and the messages – sent one after the other, so a slow network never holds
/// the app up.
@Observable
public final class TelegramLink {
    /// the line under the settings (ui.telegram.*)
    public internal(set) var status = ""
    public internal(set) var connecting = false
    /// counts the messages sent and failed (the tests wait for them)
    public internal(set) var sent = 0
    public internal(set) var failed = 0
    /// the last error of a message ("" when none)
    public internal(set) var lastError = ""
    @ObservationIgnored let cancel = TelegramCancel()
    /// the messages wait here, the one before goes first
    @ObservationIgnored var outbox: Task<Void, Never>?

    public init() {}
}

/// "Connect" given up – read by the waiting for /start.
public nonisolated final class TelegramCancel: Sendable {
    private let flag = Mutex(false)
    public init() {}
    public func set(_ on: Bool) { flag.withLock { $0 = on } }
    public var isSet: Bool { flag.withLock { $0 } }
}

public extension AppModel {
    /// The bot's token: in the Keychain of this Mac, never in settings.json (Windows keeps it in its settings file).
    var telegramToken: String { phone.keys.store.get("telegram_token") ?? "" }

    /// A new token: the chat and the bot of the old one go (phone_ui._token_changed).
    func setTelegramToken(_ token: String) {
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t != telegramToken else { return }
        phone.keys.store.set("telegram_token", t)
        _ = updateSettings {
            $0["telegram_chat"] = ""
            $0["telegram_bot"] = ""
        }
        refreshTelegramStatus()
    }

    /// telegram.configured: on, a token and a chat.
    var telegramConfigured: Bool {
        (settings["telegram_on"]?.truthy ?? false) && Telegram.validToken(telegramToken)
            && !(settings["telegram_chat"]?.stringValue ?? "").isEmpty
    }

    /// Telegram on or off (the box shows "Connect" and the choices only when on).
    func setTelegram(_ on: Bool) {
        _ = updateSettings { $0["telegram_on"] = .bool(on) }
        refreshTelegramStatus()
    }

    /// telegram_done, telegram_failed, telegram_photo (each on at first).
    func telegramOption(_ key: String) -> Bool { settings["telegram_\(key)"]?.truthy ?? true }

    func setTelegramOption(_ key: String, _ on: Bool) {
        guard ["done", "failed", "photo"].contains(key) else { return }
        _ = updateSettings { $0["telegram_\(key)"] = .bool(on) }
    }

    /// The line under the settings when nothing is under way: connected with the bot, or not yet.
    func refreshTelegramStatus() {
        guard !telegram.connecting else { return }
        let bot = settings["telegram_bot"]?.stringValue ?? "", chat = settings["telegram_chat"]?.stringValue ?? ""
        telegram.status = !bot.isEmpty && !chat.isEmpty ? texts.tr("ui.telegram.connected", ["bot": "@\(bot)"])
            : texts.tr("ui.telegram.not_connected")
    }

    private var bot: Telegram.Bot { Telegram.Bot(token: telegramToken, transport: telegramTransport, api: telegramAPI) }

    /// phone_ui.connect_telegram: the token checked, then waiting for /start (CONNECT_SECONDS); the chat and the bot
    /// are kept, Telegram is on and the bot says hello.
    func connectTelegram() async {
        guard !telegram.connecting else { return }
        guard Telegram.validToken(telegramToken) else {
            telegram.status = texts.tr("ui.telegram.bad_token")
            return
        }
        telegram.connecting = true
        telegram.cancel.set(false)
        defer {
            telegram.connecting = false
        }
        telegram.status = texts.tr("ui.telegram.checking")
        let bot = bot
        do {
            let name = try await bot.name()
            telegram.status = texts.tr("ui.telegram.send_start", ["bot": "@\(name)",
                                                                  "seconds": "\(Telegram.connectSeconds)"])
            let cancel = telegram.cancel
            guard let chat = try await bot.findChat(seconds: telegramConnectSeconds,
                                                    cancelled: { cancel.isSet })
            else {
                telegram.status = texts.tr("ui.telegram.no_start")
                return
            }
            _ = updateSettings {
                $0["telegram_chat"] = .string(chat.id)
                $0["telegram_bot"] = .string(name)
                $0["telegram_on"] = true
            }
            telegram.status = texts.tr("ui.telegram.connected", ["bot": "@\(name)"])
            telegramMessage(texts.tr("ui.telegram.hello"))
        } catch {
            telegram.status = texts.tr("ui.telegram.failed", ["error": String(describing: error)])
        }
    }

    /// "Connect" given up (the window closed).
    func cancelTelegramConnect() {
        telegram.cancel.set(true)
    }

    /// "Send a test message".
    func telegramTest() {
        guard telegramConfigured else { return }
        telegramMessage(texts.tr("ui.telegram.test"))
        telegram.status = texts.tr("ui.telegram.test_sent")
    }

    /// Notifier.message: into the outbox (behind the ones before); nothing without a token and a chat.
    func telegramMessage(_ text: String, png: Data? = nil) {
        let chat = settings["telegram_chat"]?.stringValue ?? ""
        guard Telegram.validToken(telegramToken), !chat.isEmpty else { return }
        let bot = bot, before = telegram.outbox, link = telegram
        link.outbox = Task {
            await before?.value
            do {
                try await bot.send(chat: chat, text: text, png: png)
                link.sent += 1
            } catch {
                link.failed += 1
                link.lastError = String(describing: error)
            }
        }
    }

    /// Notifier.job_finished: a message for a job done or failed – if Telegram is on and wanted for this outcome;
    /// a finished one with its best sketch as a picture (in the export's style and paper).
    @discardableResult
    func telegramJobFinished(_ job: QueuedJob) -> Bool {
        guard telegramConfigured, job.status == .done || job.status == .failed,
              telegramOption(job.status == .done ? "done" : "failed")
        else { return false }
        let summary = job.jobDir.flatMap { JobFolder.summary(at: $0) }
        let method = summary?.method ?? job.settings["method"]?.stringValue ?? "clipasso"
        let methodName = schema.method(method)?.name ?? method
        let name = job.target.lastPathComponent
        guard job.status == .done else {
            let error = String((job.message.isEmpty ? job.status.rawValue : job.message).prefix(300))
            telegramMessage(texts.tr("ui.telegram.msg_failed", ["name": name, "method": methodName, "error": error]))
            return true
        }
        let score = summary?.clipScore ?? summary?.runs.compactMap { $0["clip_score"]?.doubleValue }.max()
        let text = texts.tr("ui.telegram.msg_done", [
            "name": name, "method": methodName, "time": Telegram.minutes(summary?.seconds ?? 0),
            "score": score.map { texts.number($0) } ?? "–",
        ])
        guard telegramOption("photo"), let summary, let sketch = JobFolder.bestSketch(summary) else {
            telegramMessage(text)
            return true
        }
        var options = ExportOptions.forClipboard(settings)
        options.size = Telegram.photoSize
        options.frame = .square  // (telegram.sketch_png: the sketch as it is)
        let stylist = stylist(options.style)
        Task {
            #if canImport(CoreGraphics)
                let png = try? await Task.detached(executorPreference: OwnThreads.shared) {
                    try SketchExporter.png(try String(contentsOf: sketch, encoding: .utf8), options: options,
                                           stylist: stylist)
                }.value
            #else
                let png: Data? = nil
            #endif
            telegramMessage(text, png: png)  // (a sketch that cannot be drawn: the text still goes)
        }
        return true
    }

    /// The jobs that ended since the last report: their messages.
    internal func telegramAfter(_ snapshot: QueueSnapshot, before: QueueSnapshot?) {
        guard let before, telegramConfigured else { return }
        let was = Dictionary(before.jobs.map { ($0.id, $0.status) }, uniquingKeysWith: { a, _ in a })
        for job in snapshot.jobs {
            guard let old = was[job.id], ![.done, .failed, .cancelled].contains(old),
                  job.status == .done || job.status == .failed
            else { continue }
            telegramJobFinished(job)
        }
    }
}
