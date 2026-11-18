import Foundation

/// What the app answers to the phone (PhoneApi.handle): JSON, bytes (a picture, an SVG – `name`: as a download), or a
/// large file sent from the disk (an export).
public enum RemoteAnswer: Sendable {
    case json(JSONValue)
    case bytes(Data, type: String, name: String?)
    case file(URL, type: String, name: String)
}

/// The app behind the phone page (RemoteBridge): its answers to the page's requests, the state of the running job
/// for /api/status, the live sketch, the texts of the page, the buttons of the job and the pictures sent to the queue.
public protocol RemoteApp: Sendable {
    /// `action`: "get_…", "file_…", "do_…", "set_image" or "set_details"; `payload`: the PNG of set_details.
    func answer(_ action: String, _ data: JSONObject, payload: Data?) async throws -> RemoteAnswer
    func status() async -> JSONObject
    func preview() async -> String
    func texts() async -> JSONObject
    /// "pause", "resume" or "cancel"
    func command(_ name: String) async
    /// A picture from the phone for the queue (sketched right away with `method`).
    func upload(_ file: URL, method: String) async
    /// A picture the app can open (HEIC from an iPhone, too).
    func isPicture(_ file: URL) -> Bool
}

/// The access code and the PIN as they are now, and whether the tailnet may connect.
public struct RemoteSecrets: Sendable {
    public let token: @Sendable () -> String
    public let pin: @Sendable () -> String
    public let tailscale: @Sendable () -> Bool

    public init(token: @escaping @Sendable () -> String, pin: @escaping @Sendable () -> String,
                tailscale: @escaping @Sendable () -> Bool)
    {
        (self.token, self.pin, self.tailscale) = (token, pin, tailscale)
    }
}

/// The phone server's ways (remote._Handler): who may come in, what needs the access code (as a cookie, and for
/// changes also as the header X-Access), which files are public, and how the app's answers are sent.
public final class RemoteRouter: Sendable {
    /// PIN_ACTIONS: actions that need the PIN once more
    public static let pinActions = ["install_update"]
    static let staticFiles = ["phone.js": "text/javascript; charset=utf-8"]
    static let publicFiles = ["phone.css": "text/css; charset=utf-8", "login.js": "text/javascript; charset=utf-8"]
    static let pictureTypes = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"]

    public let app: any RemoteApp
    public let page: RemotePage
    public let secrets: RemoteSecrets
    public let events = RemoteEvents()
    public let pins: PinGuard
    /// where the phone's pictures go
    public let uploadDir: URL
    /// the app's icon (icon.png, favicon.ico) and the studio's fonts folder
    public let iconFile: URL
    public let fontsDir: URL
    /// seconds the app has to answer (CALL_TIMEOUT)
    public let callTimeout: Double
    let clock: @Sendable () -> Double

    public init(app: any RemoteApp, page: RemotePage, secrets: RemoteSecrets, uploadDir: URL, iconFile: URL,
                fontsDir: URL, callTimeout: Double = RemoteAccess.callTimeout,
                clock: @escaping @Sendable () -> Double = { Date().timeIntervalSince1970 })
    {
        self.app = app
        self.page = page
        self.secrets = secrets
        pins = PinGuard(pin: secrets.pin)
        self.uploadDir = uploadDir
        self.iconFile = iconFile
        self.fontsDir = fontsDir
        self.callTimeout = callTimeout
        self.clock = clock
    }

    /// How much of a request's body is read (0: none): uploads and the detail map up to 25 MB, an action 64 KB, the
    /// PIN 1 KB.
    public func bodyLimit(method: String, path: String) -> Int {
        guard method == "POST" else { return 0 }
        switch path {
        case "/api/upload", "/api/details": return RemoteAccess.maxUpload
        case "/api/do": return RemoteAccess.maxJSON
        case "/login": return 1024
        default: return 0
        }
    }

    // MARK: - answers

    func send(_ status: Int, _ body: Data, _ type: String, _ extra: [(String, String)] = []) -> RemoteReply {
        var headers: [(String, String)] = [("Content-Type", type), ("Content-Length", "\(body.count)")]
        let cache = extra.first { $0.0 == "Cache-Control" }?.1 ?? "no-store"
        headers += [("Cache-Control", cache), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]
        headers += extra.filter { $0.0 != "Cache-Control" }
        return .full(status: status, headers: headers, body: body)
    }

    func json(_ value: JSONValue, _ status: Int = 200) -> RemoteReply {
        send(status, Data(PyJSON.dump(value, asciiOnly: true).utf8), "application/json; charset=utf-8")
    }

    func failure(_ error: String, _ status: Int) -> RemoteReply {
        json(.object(["ok": false, "error": .string(error)]), status)
    }

    var accessCookie: String {
        "\(RemoteAccess.cookie)=\(secrets.token()); Path=/; HttpOnly; SameSite=Strict; Max-Age=\(RemoteAccess.cookieAge)"
    }

    func authorised(_ request: RemoteRequest, header: Bool = false) -> Bool {
        let given = header ? request.header("X-Access")
            : RemoteHTTP.cookie(request.header("Cookie"), RemoteAccess.cookie)
        guard let given, !given.isEmpty else { return false }
        return RemoteAccess.same(given, secrets.token())
    }

    // MARK: - requests

    /// The answer to a request (HEAD as GET, without the body – the server leaves it out).
    public func respond(_ request: RemoteRequest) async -> RemoteReply {
        guard RemoteAccess.allowedClient(request.client, tailscale: secrets.tailscale()) else {
            return send(403, Data("only from the home network".utf8), "text/plain")
        }
        switch request.method {
        case "GET", "HEAD": return await get(request)
        case "POST": return await post(request)
        default: return failure("not found", 404)
        }
    }

    func get(_ request: RemoteRequest) async -> RemoteReply {
        let path = request.path
        if path == "/" {
            if let given = request.query["t"], RemoteAccess.same(given, secrets.token()) {  // (from the QR code)
                return send(303, Data(), "text/plain", [("Location", "/"), ("Set-Cookie", accessCookie)])
            }
            let texts = await app.texts()
            guard authorised(request) else {  // (no cookie: the PIN instead of the QR code)
                let html = (try? page.login(texts: texts)) ?? ""
                return send(200, Data(html.utf8), "text/html; charset=utf-8",
                            [("Content-Security-Policy", RemoteAccess.pageCSP)])
            }
            let html = (try? page.page(texts: texts, token: secrets.token())) ?? ""
            return send(200, Data(html.utf8), "text/html; charset=utf-8",
                        [("Content-Security-Policy", RemoteAccess.pageCSP), ("Set-Cookie", accessCookie)])
        }
        let name = String(path.drop { $0 == "/" })
        if let type = Self.publicFiles[name], let text = try? page.resource(name) {  // (the PIN page needs them)
            return send(200, Data(text.utf8), type)
        }
        if name == "tokens.css" { return send(200, Data(page.tokensCSS().utf8), "text/css; charset=utf-8") }
        if name.hasPrefix("fonts/"), RemoteAccess.fonts.contains(String(name.dropFirst(6))),
           let font = try? Data(contentsOf: fontsDir.appending(path: String(name.dropFirst(6))))
        {
            return send(200, font, "font/ttf", [("Cache-Control", RemoteAccess.fontCache)])
        }
        if name == "icon.png" || name == "favicon.ico", let icon = try? Data(contentsOf: iconFile) {
            return send(200, icon, "image/png")
        }
        if name == "manifest.webmanifest" { return send(200, page.manifest(), "application/manifest+json") }
        guard authorised(request) else { return failure("no access", 403) }
        if let type = Self.staticFiles[name], let text = try? page.resource(name) {
            return send(200, Data(text.utf8), type)
        }
        let data = JSONObject(request.query.sorted { $0.key < $1.key }.map { ($0.key, JSONValue.string($0.value)) })
        if path.hasPrefix("/api/get/") { return await answer("get_" + Self.last(path), data) }
        if path.hasPrefix("/api/file/") { return await answer("file_" + Self.last(path), data) }
        switch path {
        case "/api/events": return .events
        case "/api/status":
            var state = await app.status()
            state["version"] = .string(page.version)
            let svg = await app.preview()
            state["preview"] = .string(svg.isEmpty ? "" : Self.fingerprint(svg))
            return json(.object(state))
        case "/api/preview.svg":
            let svg = await app.preview()
            let shown = svg.isEmpty ? #"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>"# : svg
            return send(200, Data(shown.utf8), "image/svg+xml", [("Content-Security-Policy", RemoteAccess.svgCSP)])
        default: return failure("not found", 404)
        }
    }

    func post(_ request: RemoteRequest) async -> RemoteReply {
        let path = request.path
        if path == "/login" { return login(request) }
        guard authorised(request, header: true) else { return failure("no access", 403) }
        switch path {
        case "/api/pause", "/api/resume", "/api/cancel":
            await app.command(Self.last(path))
            return json(.object(["ok": true]))
        case "/api/upload":
            return await upload(request)
        case "/api/do":
            guard let raw = request.body, let parsed = try? PyJSON.parse(raw), var data = parsed.objectValue,
                  let action = data["action"]?.stringValue
            else { return failure("bad request", 400) }
            data["_pin_ok"] = nil  // (only this server says so)
            if Self.pinActions.contains(action) {  // (once more the PIN, with the brakes of the sign-in)
                let (ok, wait) = pins.check(request.client, data["pin"]?.stringValue ?? "", now: clock())
                guard ok else {
                    return json(.object(["ok": false, "error": "pin", "wait": .int(wait)]), wait > 0 ? 429 : 403)
                }
                data["_pin_ok"] = true
            }
            return await answer("do_" + action, data)
        case "/api/details":
            guard let raw = request.body, raw.starts(with: [0x89, 0x50, 0x4E, 0x47]) else {
                return failure("not a picture", 415)
            }
            return await answer("set_details", [:], payload: raw)
        default:
            return failure("not found", 404)
        }
    }

    /// The PIN: right – the cookie, as from the QR code; wrong – try again, with brakes.
    func login(_ request: RemoteRequest) -> RemoteReply {
        let given: String = {
            guard let raw = request.body, let value = try? PyJSON.parse(raw), let o = value.objectValue,
                  let pin = o["pin"]
            else { return "" }
            return pin.stringValue ?? PyJSON.dump(pin)  // (str() of what came: a number too)
        }()
        let (ok, wait) = pins.check(request.client, given, now: clock())
        if ok {
            return send(200, Data(#"{"ok": true}"#.utf8), "application/json; charset=utf-8",
                        [("Set-Cookie", accessCookie)])
        }
        return json(.object(["ok": false, "wait": .int(wait)]), wait > 0 ? 429 : 403)
    }

    /// A picture from the phone: kept in the upload folder under a name of its own, for the queue – or, with
    /// X-Target "studio", as the studio's picture.
    func upload(_ request: RemoteRequest) async -> RemoteReply {
        guard request.length > 0, request.length <= RemoteAccess.maxUpload, let data = request.body else {
            return failure("the picture is empty or larger than 25 MB", 413)
        }
        let wanted = request.header("X-Method") ?? "clipasso"
        let method = RemoteAccess.methods.contains(wanted) ? wanted : "clipasso"
        let given = request.header("X-Filename").flatMap { $0.isEmpty ? nil : $0 } ?? "photo.jpg"
        let name = RemoteHTTP.unquote(given).components(separatedBy: "/").last ?? ""  // (os.path.basename)
        let (stem, ext) = RemoteHTTP.splitext(name)
        var scalars = String.UnicodeScalarView()
        for s in stem.unicodeScalars where scalars.count < 40
            && (RemoteHTTP.isAlnum(s) || s == "-" || s == "_" || s == " ")
        {
            scalars.append(s)
        }
        var kept = String(scalars).trimmingCharacters(in: .whitespaces)
        if kept.isEmpty { kept = "photo" }
        let suffix = Self.pictureTypes.contains(ext.lowercased()) ? ext.lowercased() : ".jpg"
        let format = DateFormatter()  // (time.strftime('%Y%m%d-%H%M%S'): the local time)
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyyMMdd-HHmmss"
        let stamp = format.string(from: Date())
        let dest = uploadDir.appending(path: "\(stamp)_\(kept)\(suffix)")
        do {
            try FileManager.default.createDirectory(at: uploadDir, withIntermediateDirectories: true)
            try data.write(to: dest)
        } catch {
            return failure(String(describing: error), 500)
        }
        guard app.isPicture(dest) else {
            try? FileManager.default.removeItem(at: dest)
            return failure("not a picture", 415)
        }
        if request.header("X-Target") == "studio" {  // (the studio's picture: the phone sets it up)
            return await answer("set_image", ["path": .string(dest.path)])
        }
        await app.upload(dest, method: method)
        return json(.object(["ok": true]))
    }

    /// _answer: the app's answer – JSON (400 when it says ok: false), bytes, or a file from the disk; the app does not
    /// answer in time: 503 "busy"; it fails: 500 with why.
    func answer(_ action: String, _ data: JSONObject, payload: Data? = nil) async -> RemoteReply {
        guard !action.isEmpty, action.unicodeScalars.allSatisfy({ RemoteHTTP.isAlnum($0) || $0 == "_" }) else {
            return failure("not found", 404)
        }
        let app = self.app
        let timeout = callTimeout
        let result = await withTaskGroup(of: Result<RemoteAnswer, any Error>?.self) { group in
            group.addTask {
                do {
                    return .success(try await app.answer(action, data, payload: payload))
                } catch {
                    return .failure(error)
                }
            }
            group.addTask {
                try? await Task.sleep(for: .seconds(timeout))
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
        guard let result else { return failure("busy", 503) }
        switch result {
        case .failure(let error):
            return failure(String(describing: error), 500)
        case .success(.json(let value)):
            if let o = value.objectValue {
                return json(value, o["ok"] == .bool(false) ? 400 : 200)
            }
            return json(.object(["ok": true, "result": value]))
        case .success(.bytes(let bytes, let type, let name)):
            var extra: [(String, String)] = []
            if type == "image/svg+xml" { extra.append(("Content-Security-Policy", RemoteAccess.svgCSP)) }
            if let name, !name.isEmpty { extra.append(("Content-Disposition", Self.attachment(name))) }
            return send(200, bytes, type, extra)
        case .success(.file(let url, let type, let name)):
            guard let size = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? Int else {
                return failure("gone", 404)
            }
            return .file(headers: [("Content-Type", type), ("Content-Length", "\(size)"), ("Cache-Control", "no-store"),
                                   ("X-Content-Type-Options", "nosniff"),
                                   ("Content-Security-Policy", RemoteAccess.svgCSP),
                                   ("Content-Disposition", Self.attachment(name))], url: url, size: size)
        }
    }

    static func attachment(_ name: String) -> String {
        "attachment; filename*=UTF-8''\(quote(name))"
    }

    /// urllib.parse.quote (safe "/"): letters, digits, "_.-~" and "/" as they are, every other byte as %XX.
    static func quote(_ text: String) -> String {
        var out = ""
        for byte in text.utf8 {
            let c = Character(Unicode.Scalar(byte))
            if byte < 0x80, c.isLetter || c.isNumber || "_.-~/".contains(c) {
                out.append(c)
            } else {
                out += String(format: "%%%02X", byte)
            }
        }
        return out
    }

    static func last(_ path: String) -> String {
        String(path.split(separator: "/", omittingEmptySubsequences: false).last ?? "")
    }

    /// A short mark of the live sketch (the page asks for it again when the mark changes).
    static func fingerprint(_ text: String) -> String {
        var hash: UInt64 = 0xCBF2_9CE4_8422_2325
        for byte in text.utf8 { hash = (hash ^ UInt64(byte)) &* 0x100_0000_01B3 }
        return String(hash)
    }
}
