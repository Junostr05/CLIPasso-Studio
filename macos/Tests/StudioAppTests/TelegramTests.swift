import Foundation
import Synchronization
import Testing
@testable import StudioApp
@testable import StudioCore

/// Telegram as the Bot API answers (here a stand-in that keeps every call): the token checked, the bot's name, the
/// chat of the first /start, messages with and without a picture – and no error carrying the token.
nonisolated final class FakeTelegram: TelegramTransport, Sendable {
    struct Call: Sendable, Equatable {
        let method: String
        let fields: [String: String]
        let photo: Bool
    }

    /// the calls so far, the updates the bot has (as JSON), whether the network is down
    private let state = Mutex<(calls: [Call], updates: Data, down: Bool)>(([], Data("[]".utf8), false))
    static let token = "123456:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789_-"

    init(updates: [[String: Any]] = []) {
        let data = (try? JSONSerialization.data(withJSONObject: updates)) ?? Data("[]".utf8)
        state.withLock { $0.updates = data }
    }

    var calls: [Call] { state.withLock { $0.calls } }
    func goDown() { state.withLock { $0.down = true } }
    func setUpdates(_ updates: [[String: Any]]) {
        let data = (try? JSONSerialization.data(withJSONObject: updates)) ?? Data("[]".utf8)
        state.withLock { $0.updates = data }
    }

    func post(_ url: URL, body: Data, contentType: String, timeout: Double) async throws -> (status: Int, data: Data) {
        let method = url.lastPathComponent
        let token = url.deletingLastPathComponent().lastPathComponent
        var fields: [String: String] = [:]
        let photo = contentType.hasPrefix("multipart/")
        if photo {
            let text = String(decoding: body, as: UTF8.self)
            for part in text.components(separatedBy: "Content-Disposition: form-data; name=\"").dropFirst() {
                guard let end = part.firstIndex(of: "\""), !part.hasPrefix("photo") else { continue }
                let name = String(part[..<end])
                let value = part.components(separatedBy: "\r\n\r\n").dropFirst().first?
                    .components(separatedBy: "\r\n").first ?? ""
                fields[name] = value
            }
        } else {
            for pair in String(decoding: body, as: UTF8.self).split(separator: "&") {
                let kv = pair.split(separator: "=", maxSplits: 1).map {
                    String($0).replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? String($0)
                }
                fields[kv[0]] = kv.count > 1 ? kv[1] : ""
            }
        }
        let (down, kept): (Bool, Data) = state.withLock { s in
            s.calls.append(Call(method: method, fields: fields, photo: photo))
            return (s.down, s.updates)
        }
        let updates = (try? JSONSerialization.jsonObject(with: kept) as? [[String: Any]]) ?? []
        if down { throw URLError(.notConnectedToInternet) }
        guard token == "bot" + Self.token else {
            return (401, Data(#"{"ok":false,"error_code":401,"description":"Unauthorized"}"#.utf8))
        }
        let result: Any
        switch method {
        case "getMe": result = ["id": 42, "is_bot": true, "username": "SkizzenBot"]
        case "getUpdates":
            let offset = Int(fields["offset"] ?? "") ?? 0
            result = updates.filter { ($0["update_id"] as? Int ?? 0) >= offset }
        case "sendMessage", "sendPhoto": result = ["message_id": 1]
        default: return (404, Data(#"{"ok":false,"description":"Not Found"}"#.utf8))
        }
        return (200, try JSONSerialization.data(withJSONObject: ["ok": true, "result": result]))
    }
}

@Suite struct TelegramTests {
    @Test func theToken() {
        #expect(Telegram.validToken(FakeTelegram.token) && Telegram.validToken(" \(FakeTelegram.token)\n"))
        #expect(!Telegram.validToken("1234:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789"))  // (too few digits)
        #expect(!Telegram.validToken("123456:short") && !Telegram.validToken("") && !Telegram.validToken("123456"))
        #expect(!Telegram.validToken("123456:ABCdefGHIjklMNOpqrSTUvwxYZ01234567 9"))
    }

    @Test func minutesAndForms() {
        #expect(Telegram.minutes(0) == "0:00" && Telegram.minutes(65.4) == "1:05" && Telegram.minutes(3725) == "1:02:05")
        #expect(String(decoding: Telegram.formEncoded([("text", "Kamel ✓ fertig"), ("a&b", "1=2")]), as: UTF8.self)
            == "text=Kamel+%E2%9C%93+fertig&a%26b=1%3D2")
        let (body, type) = Telegram.multipart([("chat_id", "7")], file: "photo", name: "sketch.png", data: Data([1, 2]),
                                              mime: "image/png", boundary: "B")
        #expect(type == "multipart/form-data; boundary=B")
        #expect(body == Data("--B\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n7\r\n".utf8)
            + Data("--B\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"sketch.png\"\r\nContent-Type: image/png\r\n\r\n".utf8)
            + Data([1, 2]) + Data("\r\n--B--\r\n".utf8))
    }

    @Test func aBot() async throws {
        let updates: [[String: Any]] = [
            ["update_id": 10, "message": ["text": "hallo", "chat": ["id": 5, "first_name": "Eva"]]],
            ["update_id": 11, "message": ["text": "/start", "chat": ["id": 77, "first_name": "Jürgen"]]],
        ]
        let fake = FakeTelegram(updates: updates)
        let bot = Telegram.Bot(token: FakeTelegram.token, transport: fake)
        #expect(try await bot.name() == "SkizzenBot")
        let chat = try #require(try await bot.findChat(seconds: 5))
        #expect(chat.id == "77" && chat.name == "Jürgen")
        #expect(fake.calls.last == FakeTelegram.Call(method: "getUpdates", fields: ["offset": "12", "timeout": "0"], photo: false))
        #expect(fake.calls[1].fields["allowed_updates"] == "[\"message\"]")
        try await bot.send(chat: "77", text: "fertig")
        try await bot.send(chat: "77", text: String(repeating: "x", count: 2000), png: Data([0x89, 0x50]))
        let sent = fake.calls.suffix(2)
        #expect(sent.first == FakeTelegram.Call(method: "sendMessage", fields: ["chat_id": "77", "text": "fertig"], photo: false))
        #expect(sent.last?.method == "sendPhoto" && sent.last?.photo == true && sent.last?.fields["caption"]?.count == 1024)
        // nobody sends /start: nil after the time; cancelled: nil at once
        let quiet = Telegram.Bot(token: FakeTelegram.token, transport: FakeTelegram())
        #expect(try await quiet.findChat(seconds: 1.5) == nil)
        #expect(try await quiet.findChat(seconds: 60, cancelled: { true }) == nil)
    }

    @Test func failuresWithoutTheToken() async throws {
        let wrong = Telegram.Bot(token: "999999:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789_-", transport: FakeTelegram())
        await #expect(throws: Telegram.Failure("Unauthorized")) { try await wrong.name() }
        let invalid = Telegram.Bot(token: "nope", transport: FakeTelegram())
        await #expect(throws: Telegram.Failure("invalid bot token")) { try await invalid.name() }
        let fake = FakeTelegram()
        fake.goDown()
        let bot = Telegram.Bot(token: FakeTelegram.token, transport: fake)
        do {
            _ = try await bot.name()
            Issue.record("no failure")
        } catch {
            let text = String(describing: error)
            #expect(text.hasPrefix("network: ") && !text.contains(FakeTelegram.token))
        }
    }
}

/// Telegram in the app: the token in the Keychain (here memory), "Connect" waiting for /start, the chat and the bot
/// kept in settings.json as on Windows – the token never –, the messages one after the other.
@Suite(.serialized) struct TelegramAppTests {
    static func model(_ fake: FakeTelegram, secrets: MemorySecrets = MemorySecrets(),
                      store: SettingsStore? = nil) throws -> AppModel
    {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: store ?? AppModelTests.store(language: "de"), secrets: secrets, telegram: fake)
        model.telegramConnectSeconds = 3
        return model
    }

    /// Waits until the messages sent so far are out.
    static func sent(_ model: AppModel) async {
        await model.telegram.outbox?.value
    }

    @Test func connectingTheBot() async throws {
        let fake = FakeTelegram(updates: [["update_id": 3, "message": ["text": "/start", "chat": ["id": 9, "first_name": "Eva"]]]])
        let secrets = MemorySecrets()
        let store = try AppModelTests.store(language: "de")
        let model = try Self.model(fake, secrets: secrets, store: store)
        let t = model.texts
        model.refreshTelegramStatus()
        #expect(model.telegram.status == t.tr("ui.telegram.not_connected") && !model.telegramConfigured)
        model.setTelegramToken("123:abc")
        await model.connectTelegram()
        #expect(model.telegram.status == t.tr("ui.telegram.bad_token") && fake.calls.isEmpty)
        model.setTelegramToken(" \(FakeTelegram.token) ")
        #expect(secrets.get("telegram_token") == FakeTelegram.token && model.telegramToken == FakeTelegram.token)
        await model.connectTelegram()
        #expect(model.settings["telegram_chat"] == "9" && model.settings["telegram_bot"] == "SkizzenBot")
        #expect(model.settings["telegram_on"] == true && model.telegramConfigured && !model.telegram.connecting)
        #expect(model.telegram.status == t.tr("ui.telegram.connected", ["bot": "@SkizzenBot"]))
        await Self.sent(model)
        #expect(fake.calls.last == FakeTelegram.Call(method: "sendMessage", fields: ["chat_id": "9", "text": t.tr("ui.telegram.hello")],
                                         photo: false))
        model.telegramTest()
        await Self.sent(model)
        #expect(fake.calls.last?.fields["text"] == t.tr("ui.telegram.test") && model.telegram.sent == 2)
        // the token stays out of settings.json (the chat and the bot are there, as on Windows)
        let written = try String(contentsOf: store.url, encoding: .utf8)
        #expect(!written.contains(FakeTelegram.token) && written.contains("SkizzenBot"))
        // a new token: the old chat and bot go
        model.setTelegramToken("654321:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789_-")
        #expect(model.settings["telegram_chat"] == "" && !model.telegramConfigured)
        // nobody sends /start; a message that cannot go is counted, not thrown
        let quiet = try Self.model(FakeTelegram())
        quiet.telegramConnectSeconds = 1.5
        quiet.setTelegramToken(FakeTelegram.token)
        await quiet.connectTelegram()
        #expect(quiet.telegram.status == quiet.texts.tr("ui.telegram.no_start") && quiet.settings["telegram_chat"] == "")
    }

    @Test func aMessageAfterEachJob() async throws {
        let fake = FakeTelegram(updates: [["update_id": 1, "message": ["text": "/start", "chat": ["id": 5]]]])
        let model = try Self.model(fake)
        let t = model.texts
        let job = FileManager.default.temporaryDirectory.appending(path: "telegram-\(UUID().uuidString)")
        try FileManager.default.copyItem(at: SelfTestTests.fixtures.appending(path: "jobs/done_clipasso"), to: job)
        var done = QueuedJob(target: URL(filePath: "/Bilder/Kamel.png"), settings: ["method": "clipasso"])
        done.status = .done
        done.jobDir = job
        #expect(!model.telegramJobFinished(done))  // (not set up)
        model.setTelegramToken(FakeTelegram.token)
        await model.connectTelegram()
        await Self.sent(model)
        let before = fake.calls.count
        #expect(model.telegramJobFinished(done))
        try await ModelFlowTests.wait("the picture") { fake.calls.count > before }
        await Self.sent(model)
        let summary = try #require(JobFolder.summary(at: job))
        let text = t.tr("ui.telegram.msg_done", ["name": "Kamel.png", "method": model.schema.method("clipasso")?.name ?? "",
                                                 "time": Telegram.minutes(summary.seconds), "score": "–"])
        #expect(fake.calls.last == FakeTelegram.Call(method: "sendPhoto", fields: ["chat_id": "5", "caption": text], photo: true))
        model.setTelegramOption("photo", false)
        model.telegramJobFinished(done)
        await Self.sent(model)
        #expect(fake.calls.last == FakeTelegram.Call(method: "sendMessage", fields: ["chat_id": "5", "text": text], photo: false))
        var failed = done
        failed.status = .failed
        failed.message = "MPS backend out of memory"
        model.telegramJobFinished(failed)
        await Self.sent(model)
        #expect(fake.calls.last?.fields["text"] == t.tr("ui.telegram.msg_failed", [
            "name": "Kamel.png", "method": model.schema.method("clipasso")?.name ?? "", "error": "MPS backend out of memory"]))
        model.setTelegramOption("failed", false)
        #expect(!model.telegramJobFinished(failed))
        var cancelled = done
        cancelled.status = .cancelled
        #expect(!model.telegramJobFinished(cancelled))
        fake.goDown()
        model.telegramTest()
        await Self.sent(model)
        #expect(model.telegram.failed == 1 && !model.telegram.lastError.contains(FakeTelegram.token))
    }
}
