import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// A Telegram message when a job is done or failed (gui/telegram.py): through the user's own bot and the Telegram Bot
/// API. Setting it up: a bot made with @BotFather, its token pasted, "Connect" and /start sent to the bot – the chat
/// is read from the bot's updates. The token stays in the Keychain of this Mac; no error, log or report carries it.
public enum Telegram {
    /// telegram.API: the Bot API's address (a test gives its own)
    public static let api = URL(string: "https://api.telegram.org")!
    /// telegram.TIMEOUT, CONNECT_SECONDS, PHOTO_SIZE
    public static let timeout = 20.0
    public static let connectSeconds = 90
    public static let photoSize = 1024

    /// telegram.valid_token: digits, a colon and at least 30 letters, digits, "_" or "-".
    public static func validToken(_ token: String) -> Bool {
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let colon = t.firstIndex(of: ":") else { return false }
        let id = t[..<colon], key = t[t.index(after: colon)...]
        return id.count >= 5 && id.allSatisfy { $0.isASCII && $0.isNumber }
            && key.count >= 30 && key.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == "-") }
    }

    /// TelegramError: what went wrong – never with the token.
    public struct Failure: Error, CustomStringConvertible, Equatable, Sendable {
        public let description: String
        public init(_ description: String) { self.description = description }
    }

    /// telegram._minutes: "m:ss" or "h:mm:ss".
    public static func minutes(_ seconds: Double) -> String {
        let s = Int((seconds.isFinite ? seconds : 0).rounded(.toNearestOrEven))
        let (h, rest) = (s / 3600, s % 3600)
        return h > 0 ? String(format: "%d:%02d:%02d", h, rest / 60, rest % 60) : String(format: "%d:%02d", rest / 60, rest % 60)
    }

    /// telegram._multipart: the fields and one file as multipart/form-data; the body and its content type.
    static func multipart(_ fields: [(String, String)], file field: String, name: String, data: Data, mime: String,
                          boundary: String = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased())
        -> (Data, String)
    {
        var out = Data()
        for (key, value) in fields {
            out.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)\r\n".utf8))
        }
        out.append(Data(("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"\(name)\"\r\n"
                + "Content-Type: \(mime)\r\n\r\n").utf8))
        out.append(data)
        out.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return (out, "multipart/form-data; boundary=\(boundary)")
    }

    /// application/x-www-form-urlencoded as Python's urlencode writes it.
    static func formEncoded(_ fields: [(String, String)]) -> Data {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        func quote(_ s: String) -> String {
            (s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s).replacingOccurrences(of: "%20", with: "+")
        }
        return Data(fields.map { "\(quote($0.0))=\(quote($0.1))" }.joined(separator: "&").utf8)
    }

    /// One bot: its calls of the Bot API.
    public struct Bot: Sendable {
        public let token: String
        let transport: any TelegramTransport
        let api: URL

        public init(token: String, transport: any TelegramTransport = URLSessionPoster(), api: URL = Telegram.api) {
            self.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
            self.transport = transport
            self.api = api
        }

        /// telegram.call: one Bot API call, its `result`; errors (network ones, too) as Failure – without the token.
        public func call(_ method: String, _ params: [(String, String?)] = [], photo: Data? = nil,
                         timeout: Double = Telegram.timeout) async throws -> JSONValue
        {
            guard Telegram.validToken(token) else { throw Failure("invalid bot token") }
            let url = api.appending(path: "bot\(token)/\(method)")
            let fields = params.compactMap { key, value in value.map { (key, $0) } }
            let (body, type) = photo.map { Telegram.multipart(fields, file: "photo", name: "sketch.png", data: $0,
                                                              mime: "image/png") }
                ?? (Telegram.formEncoded(fields), "application/x-www-form-urlencoded")
            let got: (status: Int, data: Data)
            do {
                got = try await transport.post(url, body: body, contentType: type, timeout: timeout)
            } catch {
                throw Failure("network: \(clean(String(describing: error)))")
            }
            let (status, data) = got
            let answer = try? PyJSON.parse(data).objectValue
            guard let answer else { throw Failure(status == 200 ? "Telegram refused the request" : "HTTP \(status)") }
            guard answer["ok"]?.truthy == true else {
                throw Failure(clean(answer["description"]?.stringValue ?? "Telegram refused the request"))
            }
            return answer["result"] ?? .null
        }

        /// A text without the token (whatever said it).
        private func clean(_ text: String) -> String {
            token.isEmpty ? text : text.replacingOccurrences(of: token, with: "…")
        }

        /// telegram.bot_name: the bot's user name (checks the token).
        public func name() async throws -> String {
            try await call("getMe").objectValue?["username"]?.stringValue ?? ""
        }

        /// telegram.find_chat: waits (long polling) until someone sends the bot /start – (chat id, name); nil after
        /// `seconds` or when cancelled.
        public func findChat(seconds: Double = Double(Telegram.connectSeconds),
                             cancelled: @Sendable () -> Bool = { false }) async throws -> (id: String, name: String)?
        {
            var offset: Int?
            let end = ContinuousClock.now + .seconds(seconds)
            while ContinuousClock.now < end {
                if cancelled() || Task.isCancelled { return nil }
                let left = Int((end - ContinuousClock.now).components.seconds)
                let wait = max(1, min(20, left))
                let updates = try await call("getUpdates", [("timeout", "\(wait)"), ("offset", offset.map(String.init)),
                                                            ("allowed_updates", "[\"message\"]")],
                                             timeout: Double(wait + 10)).arrayValue ?? []
                for update in updates.compactMap(\.objectValue) {
                    offset = (update["update_id"]?.intValue ?? 0) + 1
                    let message = update["message"]?.objectValue ?? [:]
                    let text = (message["text"]?.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    if text.hasPrefix("/start") {
                        let chat = message["chat"]?.objectValue ?? [:]
                        let name = [chat["first_name"], chat["title"], chat["username"]].lazy
                            .compactMap { $0?.stringValue }.first { !$0.isEmpty } ?? ""
                        if let offset { _ = try await call("getUpdates", [("offset", "\(offset)"), ("timeout", "0")]) }
                        let id = chat["id"].map { $0.intValue.map(String.init) ?? $0.stringValue ?? "" } ?? ""
                        return (id, name)
                    }
                }
            }
            return nil
        }

        /// telegram.send: the text, or the picture with the text as its caption.
        public func send(chat: String, text: String, png: Data? = nil) async throws {
            if let png {
                _ = try await call("sendPhoto", [("chat_id", chat), ("caption", String(text.prefix(1024)))], photo: png,
                                   timeout: 60)
            } else {
                _ = try await call("sendMessage", [("chat_id", chat), ("text", String(text.prefix(4096)))])
            }
        }
    }
}

/// How the bot's calls go out: a POST, its status and body (the tests answer as Telegram would).
public protocol TelegramTransport: Sendable {
    func post(_ url: URL, body: Data, contentType: String, timeout: Double) async throws -> (status: Int, data: Data)
}

/// A POST with URLSession.
public struct URLSessionPoster: TelegramTransport {
    public init() {}

    public func post(_ url: URL, body: Data, contentType: String, timeout: Double) async throws -> (status: Int, data: Data) {
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        request.setValue("CLIPassoStudio", forHTTPHeaderField: "User-Agent")
        let session = URLSession(configuration: .ephemeral)
        defer { session.finishTasksAndInvalidate() }
        return try await withCheckedThrowingContinuation { continuation in
            session.dataTask(with: request) { data, response, error in
                if let error {
                    // (an URLError names the address – with the token: only its code goes on)
                    continuation.resume(throwing: Telegram.Failure((error as? URLError).map { "URLError \($0.code.rawValue)" }
                            ?? "the request failed"))
                } else {
                    continuation.resume(returning: ((response as? HTTPURLResponse)?.statusCode ?? 0, data ?? Data()))
                }
            }.resume()
        }
    }
}
