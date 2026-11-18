#if canImport(Network)
    import Foundation
    import Testing
    @testable import StudioCore

    /// The app as the phone server sees it: records what it is asked and answers as PhoneApi does.
    actor FakeRemoteApp: RemoteApp {
        var calls: [(action: String, data: JSONObject, payload: Data?)] = []
        var commands: [String] = []
        var uploads: [(file: URL, method: String)] = []
        var state: JSONObject = ["busy": false, "paused": false, "job": nil, "queue": 0, "last": nil]
        var svg = ""
        var slow = false

        func answer(_ action: String, _ data: JSONObject, payload: Data?) async throws -> RemoteAnswer {
            calls.append((action, data, payload))
            if slow { try await Task.sleep(for: .seconds(10)) }
            switch action {
            case "file_thing": return .bytes(Data("<svg/>".utf8), type: "image/svg+xml", name: "my sketch.svg")
            case "do_bad": return .json(["ok": false, "error": "no"])
            default: return .json(["ok": true, "action": .string(action)])
            }
        }

        func status() -> JSONObject { state }
        func preview() -> String { svg }
        func texts() -> JSONObject { ["pause": "Pause", "lang": "en"] }
        func command(_ name: String) { commands.append(name) }
        func upload(_ file: URL, method: String) { uploads.append((file, method)) }
        nonisolated func isPicture(_ file: URL) -> Bool {
            (try? Data(contentsOf: file))?.starts(with: [0x89, 0x50, 0x4E, 0x47]) ?? false
        }

        func set(state: JSONObject, svg: String) {
            self.state = state
            self.svg = svg
        }

        func setSlow() { slow = true }
    }

    /// The phone server over real connections, as tests/test_phone.py tries the studio's: the page needs the access
    /// code (the PIN page instead, the code from the QR code becomes a cookie), changes need it as a header, uploads
    /// must be pictures, requests reach the app and its answers come back, the event stream – and the PIN.
    @Suite(.serialized) struct RemoteServerTests {
        static let token = "Zugang-0123456789abcdefgh"
        static let pin = "135790"

        final class NoRedirect: NSObject, URLSessionTaskDelegate {
            func urlSession(_ session: URLSession, task: URLSessionTask,
                            willPerformHTTPRedirection response: HTTPURLResponse,
                            newRequest request: URLRequest) async -> URLRequest?
            {
                nil
            }
        }

        struct Running {
            let server: RemoteServer
            let app: FakeRemoteApp
            let base: String
            let uploads: URL
            let session: URLSession

            func get(_ path: String, cookie: String? = nil) async throws -> (Int, HTTPURLResponse, Data) {
                var request = URLRequest(url: URL(string: base + path)!)
                if let cookie { request.setValue(cookie, forHTTPHeaderField: "Cookie") }
                let (data, response) = try await session.data(for: request)
                let http = try #require(response as? HTTPURLResponse)
                return (http.statusCode, http, data)
            }

            func post(_ path: String, _ body: Data = Data(), headers: [String: String] = [:]) async throws
                -> (Int, JSONObject)
            {
                var request = URLRequest(url: URL(string: base + path)!)
                request.httpMethod = "POST"
                request.httpBody = body
                for (k, v) in headers { request.setValue(v, forHTTPHeaderField: k) }
                let (data, response) = try await session.data(for: request)
                let http = try #require(response as? HTTPURLResponse)
                return (http.statusCode, (try? PyJSON.parse(data))?.objectValue ?? [:])
            }

            /// Signed in: the cookie the QR code's address gives.
            func cookie() async throws -> String {
                let (_, response, _) = try await get("/?t=\(RemoteServerTests.token)")
                let set = try #require(response.value(forHTTPHeaderField: "Set-Cookie"))
                return String(set.split(separator: ";")[0])
            }
        }

        static func start(callTimeout: Double = RemoteAccess.callTimeout, ping: Double = RemoteAccess.eventPing)
            async throws -> Running
        {
            let app = FakeRemoteApp()
            let uploads = FileManager.default.temporaryDirectory.appending(path: "remote-\(UUID().uuidString)/up")
            let secrets = RemoteSecrets(token: { token }, pin: { pin }, tailscale: { false })
            let router = RemoteRouter(app: app, page: RemoteTests.page("test"), secrets: secrets, uploadDir: uploads,
                                      iconFile: RemoteTests.resources.appending(path: "app_icon.png"),
                                      fontsDir: RemoteTests.resources.appending(path: "fonts"), callTimeout: callTimeout)
            let server = try RemoteServer(router: router, port: 0, host: "127.0.0.1", ping: ping)
            let port = try await server.start()
            let config = URLSessionConfiguration.ephemeral
            config.httpShouldSetCookies = false
            config.httpCookieAcceptPolicy = .never
            config.httpCookieStorage = nil
            config.timeoutIntervalForRequest = 10
            let session = URLSession(configuration: config, delegate: NoRedirect(), delegateQueue: nil)
            return Running(server: server, app: app, base: "http://127.0.0.1:\(port)", uploads: uploads,
                           session: session)
        }

        static func png() -> Data {
            Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + Data(repeating: 0, count: 32)
        }

        @Test func thePageNeedsTheCode() async throws {
            let r = try await Self.start()
            defer { Task { await r.server.stop() } }
            for path in ["/", "/?t=wrong"] {  // (no sign-in: the PIN page, without the code)
                let (status, response, body) = try await r.get(path)
                let text = String(decoding: body, as: UTF8.self)
                #expect(status == 200 && text.contains("login.js") && !text.contains(Self.token))
                #expect(response.value(forHTTPHeaderField: "Set-Cookie") == nil)
            }
            #expect(try await r.get("/api/status").0 == 403)
            let (status, response, _) = try await r.get("/?t=\(Self.token)")
            #expect(status == 303 && response.value(forHTTPHeaderField: "Location") == "/")
            let set = try #require(response.value(forHTTPHeaderField: "Set-Cookie"))
            #expect(set.contains("HttpOnly") && set.contains("SameSite=Strict"))
            let cookie = String(set.split(separator: ";")[0])
            let (pageStatus, pageResponse, page) = try await r.get("/", cookie: cookie)
            let text = String(decoding: page, as: UTF8.self)
            #expect(pageStatus == 200 && text.contains("CLIPasso Studio") && text.contains(Self.token))
            let csp = pageResponse.value(forHTTPHeaderField: "Content-Security-Policy") ?? ""
            #expect(csp.contains("script-src 'self'"))
            await r.app.set(state: ["busy": true, "job": ["name": "camel.png", "progress": 0.5]],
                            svg: #"<svg xmlns="http://www.w3.org/2000/svg"/>"#)
            let (s, _, body) = try await r.get("/api/status", cookie: cookie)
            let state = try #require(try PyJSON.parse(body).objectValue)
            #expect(s == 200 && state["busy"] == true && state["job"]?.objectValue?["name"] == "camel.png")
            #expect(state["preview"]?.stringValue?.isEmpty == false && state["version"] == "test")
            let (svgStatus, svgResponse, svg) = try await r.get("/api/preview.svg", cookie: cookie)
            #expect(svgStatus == 200 && svgResponse.value(forHTTPHeaderField: "Content-Type") == "image/svg+xml")
            #expect(svg.starts(with: Data("<svg".utf8)))
        }

        @Test func changesNeedTheHeader() async throws {
            let r = try await Self.start()
            defer { Task { await r.server.stop() } }
            #expect(try await r.post("/api/pause").0 == 403)  // (a page elsewhere cannot send this)
            #expect(try await r.post("/api/pause", headers: ["X-Access": "wrong"]).0 == 403)
            let (status, answer) = try await r.post("/api/pause", headers: ["X-Access": Self.token])
            #expect(status == 200 && answer == ["ok": true] && (await r.app.commands) == ["pause"])
            let (up, data) = try await r.post("/api/upload", Self.png(), headers: [
                "X-Access": Self.token, "X-Filename": "my%20dog.png", "X-Method": "swiftsketch"])
            #expect(up == 200 && data["ok"] == true)
            let uploads = await r.app.uploads
            #expect(uploads.count == 1 && uploads.first?.method == "swiftsketch")
            #expect(uploads.first?.file.path.hasPrefix(r.uploads.path) == true)
            #expect(uploads.first?.file.lastPathComponent.hasSuffix("_my dog.png") == true)
            let (bad, badData) = try await r.post("/api/upload", Data("not a picture".utf8),
                                                  headers: ["X-Access": Self.token, "X-Filename": "x.png"])
            #expect(bad == 415 && badData["ok"] == false)
            #expect((try FileManager.default.contentsOfDirectory(atPath: r.uploads.path)).count == 1)
            #expect(try await r.post("/api/upload", Data(), headers: ["X-Access": Self.token]).0 == 413)
        }

        @Test func thePageAndItsFiles() async throws {
            let r = try await Self.start()
            defer { Task { await r.server.stop() } }
            let cookie = try await r.cookie()
            #expect(try await r.get("/phone.js").0 == 403)  // (the style and the icon are for the PIN page, too)
            for (name, kind) in [("phone.js", "javascript"), ("phone.css", "css"), ("icon.png", "png")] {
                let (status, response, data) = try await r.get("/" + name, cookie: cookie)
                #expect(status == 200 && !data.isEmpty, "\(name)")
                #expect(response.value(forHTTPHeaderField: "Content-Type")?.contains(kind) == true, "\(name)")
            }
            for name in ["/phone.css", "/login.js", "/icon.png", "/favicon.ico", "/manifest.webmanifest",
                         "/tokens.css"]
            {
                #expect(try await r.get(name).0 == 200, "\(name) without signing in")
            }
            let (_, cssResponse, css) = try await r.get("/tokens.css")
            #expect(String(decoding: css, as: UTF8.self) == RemoteTests.page("test").tokensCSS())
            #expect(cssResponse.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("text/css") == true)
            for font in RemoteAccess.fonts {
                let (status, response, data) = try await r.get("/fonts/" + font)
                #expect(status == 200 && response.value(forHTTPHeaderField: "Content-Type") == "font/ttf", "\(font)")
                #expect(data.starts(with: [0, 1, 0, 0]) && response.value(forHTTPHeaderField: "Cache-Control")
                    == RemoteAccess.fontCache)
            }
            for bad in ["/fonts/LICENSE-Inter-OFL.txt", "/fonts/../phone.js", "/fonts/Inter-Thin.ttf"] {
                #expect(try await r.get(bad).0 == 403, "\(bad)")  // (not one of the four: like any other path)
            }
            let (head, headers, _) = try await r.get("/", cookie: cookie)
            #expect(head == 200 && headers.value(forHTTPHeaderField: "X-Content-Type-Options") == "nosniff")
            #expect(headers.value(forHTTPHeaderField: "Referrer-Policy") == "no-referrer")
            #expect(headers.value(forHTTPHeaderField: "Cache-Control") == "no-store")
        }

        @Test func requestsGoToTheApp() async throws {
            let r = try await Self.start(callTimeout: 0.5)
            defer { Task { await r.server.stop() } }
            let cookie = try await r.cookie()
            let (status, _, body) = try await r.get("/api/get/studio?x=1", cookie: cookie)
            #expect(status == 200 && (try PyJSON.parse(body).objectValue?["action"]) == "get_studio")
            var last = await r.app.calls.last
            #expect(last?.action == "get_studio" && last?.data == ["x": "1"])
            let (fileStatus, fileResponse, file) = try await r.get("/api/file/thing?seed=3", cookie: cookie)
            #expect(fileStatus == 200 && file == Data("<svg/>".utf8))
            #expect(fileResponse.value(forHTTPHeaderField: "Content-Type") == "image/svg+xml")
            let disposition = fileResponse.value(forHTTPHeaderField: "Content-Disposition") ?? ""
            #expect(disposition.contains("attachment") && disposition.contains("my%20sketch.svg"))
            #expect(try await r.get("/api/get/studio").0 == 403)  // (no cookie)
            let head = ["X-Access": Self.token, "Content-Type": "application/json"]
            let (set, _) = try await r.post("/api/do", Data(#"{"action": "set", "key": "k", "value": 3}"#.utf8),
                                            headers: head)
            last = await r.app.calls.last
            #expect(set == 200 && last?.action == "do_set" && last?.data == ["action": "set", "key": "k", "value": 3])
            #expect(try await r.post("/api/do", Data(#"{"action": "bad"}"#.utf8), headers: head).0 == 400)
            #expect(try await r.post("/api/do", Data(#"{"action": "set"}"#.utf8),
                                     headers: ["Content-Type": "application/json"]).0 == 403)
            #expect(try await r.post("/api/do", Data("not json".utf8), headers: head).0 == 400)
            #expect(try await r.post("/api/do", Data(#"{"action": "../x"}"#.utf8), headers: head).0 == 404)
            // a picture for the studio (not the queue)
            let (studio, _) = try await r.post("/api/upload", Self.png(), headers: [
                "X-Access": Self.token, "X-Target": "studio", "X-Filename": "beach.png"])
            last = await r.app.calls.last
            #expect(studio == 200 && last?.action == "set_image"
                && last?.data["path"]?.stringValue?.hasSuffix("beach.png") == true)
            // the painted detail map
            let (details, _) = try await r.post("/api/details", Self.png(), headers: ["X-Access": Self.token])
            last = await r.app.calls.last
            #expect(details == 200 && last?.action == "set_details")
            #expect(last?.payload?.starts(with: [0x89, 0x50]) == true)
            #expect(try await r.post("/api/details", Data("GIF89a".utf8), headers: ["X-Access": Self.token]).0 == 415)
            // the app does not answer in time: "busy"
            await r.app.setSlow()
            let (busy, _, busyBody) = try await r.get("/api/get/studio", cookie: cookie)
            #expect(busy == 503 && (try PyJSON.parse(busyBody).objectValue?["error"]) == "busy")
        }

        @Test func signingInWithThePin() async throws {
            let r = try await Self.start()
            defer { Task { await r.server.stop() } }
            let (wrong, answer) = try await r.post("/login", Data(#"{"pin": "000000"}"#.utf8))
            #expect(wrong == 403 && answer == ["ok": false, "wait": 0])
            var request = URLRequest(url: URL(string: r.base + "/login")!)
            request.httpMethod = "POST"
            request.httpBody = Data(#"{"pin": "\#(Self.pin)"}"#.utf8)
            let (data, response) = try await r.session.data(for: request)
            let http = try #require(response as? HTTPURLResponse)
            #expect(http.statusCode == 200 && data == Data(#"{"ok": true}"#.utf8))
            let cookie = try #require(http.value(forHTTPHeaderField: "Set-Cookie")).split(separator: ";")[0]
            #expect(try await r.get("/api/status", cookie: String(cookie)).0 == 200)
            for _ in 0 ..< 5 { _ = try await r.post("/login", Data(#"{"pin": "111111"}"#.utf8)) }
            let (braked, wait) = try await r.post("/login", Data(#"{"pin": "\#(Self.pin)"}"#.utf8))
            #expect(braked == 429 && (wait["wait"]?.intValue ?? 0) > 0)  // (even the right PIN waits now)
            // install_update needs the PIN once more – here still braked
            let install = Data(#"{"action": "install_update", "pin": "\#(Self.pin)"}"#.utf8)
            let (update, said) = try await r.post("/api/do", install, headers: ["X-Access": Self.token])
            #expect(update == 429 && said["error"] == "pin")
        }

        @Test func theEventStream() async throws {
            let r = try await Self.start(ping: 0.3)
            #expect(try await r.get("/api/events").0 == 403)  // (signed in only)
            let cookie = try await r.cookie()
            var request = URLRequest(url: URL(string: r.base + "/api/events")!)
            request.setValue(cookie, forHTTPHeaderField: "Cookie")
            let (bytes, response) = try await r.session.bytes(for: request)
            let http = try #require(response as? HTTPURLResponse)
            #expect(http.statusCode == 200
                && http.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("text/event-stream") == true)
            var lines = bytes.lines.makeAsyncIterator()
            func event() async throws -> [String: String] {
                var fields: [String: String] = [:]
                while let line = try await lines.next() {
                    if line.isEmpty { if !fields.isEmpty { return fields } else { continue } }
                    let parts = line.split(separator: ":", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
                    if parts.count == 2 { fields[parts[0]] = parts[1] }
                    if fields["data"] != nil, fields["event"] != nil { return fields }  // (blank lines may not come)
                }
                return fields
            }
            let first = try await event()
            #expect(first["event"] == "changed")
            #expect(try await event()["event"] == "ping")  // (quiet: a sign of life)
            Task {
                try await Task.sleep(for: .milliseconds(50))
                await r.server.router.events.changed()
            }
            var next = try await event()
            while next["event"] == "ping" { next = try await event() }
            #expect(next["event"] == "changed" && Int(next["data"] ?? "") == (Int(first["data"] ?? "") ?? -9) + 1)
            #expect(await r.server.router.events.streams == 1)
            await r.server.stop()  // (the stream ends with the server)
            for _ in 0 ..< 250 {
                if await r.server.router.events.streams == 0 { break }
                try await Task.sleep(for: .milliseconds(20))
            }
            #expect(await r.server.router.events.streams == 0)
        }

        @Test func theRouterAlone() async throws {
            let app = FakeRemoteApp()
            let secrets = RemoteSecrets(token: { Self.token }, pin: { Self.pin }, tailscale: { false })
            let router = RemoteRouter(app: app, page: RemoteTests.page("test"), secrets: secrets,
                                      uploadDir: FileManager.default.temporaryDirectory.appending(path: "r-\(UUID())"),
                                      iconFile: RemoteTests.resources.appending(path: "app_icon.png"),
                                      fontsDir: RemoteTests.resources.appending(path: "fonts"))
            let outside = RemoteRequest(method: "GET", target: "/", client: "8.8.8.8")
            guard case .full(let status, _, _) = await router.respond(outside) else { return Issue.record("no answer") }
            #expect(status == 403)  // (only the home network)
            // too large: answered before the body is read
            let large = RemoteRequest(method: "POST", target: "/api/upload", headers: [
                "X-Access": Self.token, "Content-Length": "\(RemoteAccess.maxUpload + 1)"])
            guard case .full(let tooLarge, _, _) = await router.respond(large) else { return Issue.record("no answer") }
            #expect(tooLarge == 413 && router.bodyLimit(method: "POST", path: "/api/upload") == RemoteAccess.maxUpload)
            #expect(router.bodyLimit(method: "GET", path: "/api/upload") == 0)
            for (name, stem, ext) in [("my dog.png", "my dog", ".png"), (".png", ".png", ""), ("a.b.JPG", "a.b", ".JPG"),
                                      ("..x", "..x", ""), ("x.", "x", "."), ("noext", "noext", "")]
            {
                let split = RemoteHTTP.splitext(name)
                #expect(split.stem == stem && split.ext == ext, "\(name)")
            }
            #expect(RemoteHTTP.unquote("my%20d%C3%B6g%zz") == "my dög%zz")
            #expect(RemoteHTTP.parseQuery("t=abc&x=&y&t=2&s=a+b") == ["t": "abc", "s": "a b"])
            #expect(RemoteHTTP.cookie("a=1; cs_access=\"xyz\"; b=2", "cs_access") == "xyz")
            #expect(RemoteRouter.quote("my sketch ä.svg") == "my%20sketch%20%C3%A4.svg")
        }
    }
#endif
