import Foundation
import Testing
@testable import StudioCore

/// The phone remote's ground rules as gui/remote.py has them (Fixtures/remote/remote.json, made with its functions):
/// who may connect, the brakes on guessing the PIN, the phone page and the PIN page byte for byte, the design tokens
/// as CSS, the manifest – and the event streams of the open pages.
@Suite struct RemoteTests {
    /// the studio's resources (the page is served from them, not copied)
    static let resources = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().appending(path: "clipasso_studio/resources")

    static func cases() throws -> JSONObject { try #require(Fixtures.json("remote/remote.json").objectValue) }

    static func page(_ version: String) -> RemotePage {
        RemotePage(phoneDir: resources.appending(path: "phone"), iconsDir: resources.appending(path: "icons"),
                   version: version)
    }

    @Test func theNumbersOfTheStudio() throws {
        let c = try #require(try Self.cases()["constants"]?.objectValue)
        #expect(RemoteAccess.defaultPort == c["port"]?.intValue)
        #expect(RemoteAccess.maxUpload == c["max_upload"]?.intValue)
        #expect(RemoteAccess.maxJSON == c["max_json"]?.intValue)
        #expect(RemoteAccess.eventStreams == c["event_streams"]?.intValue)
        #expect(RemoteAccess.eventPing == c["event_ping"]?.doubleValue)
        #expect(RemoteAccess.callTimeout == c["call_timeout"]?.doubleValue)
        #expect(RemoteAccess.pinDigits == c["pin_digits"]?.intValue)
        #expect(PinGuard.tries == c["pin_tries"]?.intValue && PinGuard.wait == c["pin_wait"]?.intValue)
        #expect(PinGuard.waitMax == c["pin_wait_max"]?.intValue && PinGuard.global == c["pin_global"]?.intValue)
        #expect(PinGuard.window == c["pin_window"]?.doubleValue)
        #expect(RemoteAccess.cookie == c["cookie"]?.stringValue && RemoteAccess.cookieAge == c["cookie_age"]?.intValue)
        #expect(RemoteAccess.pageCSP == c["page_csp"]?.stringValue && RemoteAccess.svgCSP == c["svg_csp"]?.stringValue)
        #expect(RemoteAccess.fonts == c["fonts"]?.arrayValue?.compactMap(\.stringValue))
        #expect(RemoteAccess.fontCache == c["font_cache"]?.stringValue)
        #expect(RemoteAccess.methods == c["methods"]?.arrayValue?.compactMap(\.stringValue))
        #expect(RemoteAccess.uploadDir == c["upload_dir"]?.stringValue)
    }

    @Test func onlyTheHomeNetwork() throws {
        let clients = (try Self.cases()["clients"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(clients.count > 100)
        for c in clients {
            let ip = c["ip"]?.stringValue ?? "", tailscale = c["tailscale"]?.truthy ?? false
            #expect(RemoteAccess.allowedClient(ip, tailscale: tailscale) == c["allowed"]?.truthy,
                    "\(ip) (tailnet \(tailscale))")
        }
    }

    @Test func theBrakesOnGuessingThePin() throws {
        let c = try Self.cases()
        let pin = try #require(c["pin"]?.stringValue)
        let guard_ = PinGuard(pin: { pin })
        for (i, t) in (c["tries"]?.arrayValue ?? []).compactMap(\.objectValue).enumerated() {
            let got = guard_.check(t["ip"]?.stringValue ?? "", t["pin"]?.stringValue ?? "",
                                   now: t["now"]?.doubleValue ?? 0)
            #expect(got.ok == t["ok"]?.truthy && got.wait == t["wait"]?.intValue,
                    "try \(i) from \(t["ip"]?.stringValue ?? "") at \(t["now"]?.doubleValue ?? 0): \(got)")
        }
    }

    @Test func secretsAsTheStudioMakesThem() {
        let tokens = (0 ..< 50).map { _ in RemoteAccess.newToken() }
        #expect(Set(tokens).count == 50)
        #expect(tokens.allSatisfy { $0.count == 24 && $0.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber
                || $0 == "-" || $0 == "_") } })
        let pins = (0 ..< 50).map { _ in RemoteAccess.newPin() }
        #expect(pins.allSatisfy(RemoteAccess.validPin))
        #expect(!RemoteAccess.validPin("12345") && !RemoteAccess.validPin("1234567") && !RemoteAccess.validPin("12a456"))
        #expect(!RemoteAccess.validPin("١٢٣٤٥٦"))  // (other digits than ASCII: not a PIN)
        #expect(RemoteAccess.same("abc", "abc") && !RemoteAccess.same("abc", "abd") && !RemoteAccess.same("abc", "ab"))
    }

    @Test(arguments: ["de", "en"])
    func thePagesByteForByte(_ lang: String) throws {
        let c = try Self.cases()
        let page = Self.page(try #require(c["version"]?.stringValue))
        let texts = try #require(c["texts"]?.objectValue?[lang]?.objectValue)
        let want = try String(contentsOf: Fixtures.url("remote/page_\(lang).html"), encoding: .utf8)
        let made = try page.page(texts: texts, token: try #require(c["token"]?.stringValue))
        #expect(made == want, "page_\(lang).html: first difference at \(Self.firstDifference(made, want))")
        let login = try String(contentsOf: Fixtures.url("remote/login_\(lang).html"), encoding: .utf8)
        let madeLogin = try page.login(texts: texts)
        #expect(madeLogin == login, "login_\(lang).html: first difference at \(Self.firstDifference(madeLogin, login))")
        #expect(!madeLogin.contains(c["token"]?.stringValue ?? "?"))
    }

    @Test func iconsTokensAndTheManifest() throws {
        let c = try Self.cases()
        let page = Self.page(try #require(c["version"]?.stringValue))
        for (name, svg) in try #require(c["icons"]?.objectValue) {
            #expect(try page.icon(name) == svg.stringValue, "\(name)")
        }
        let css = try String(contentsOf: Fixtures.url("remote/tokens.css"), encoding: .utf8)
        #expect(page.tokensCSS() == css, "tokens.css: first difference at \(Self.firstDifference(page.tokensCSS(), css))")
        #expect(page.manifest() == (try Data(contentsOf: Fixtures.url("remote/manifest.webmanifest"))))
    }

    @Test func theEventStreams() async throws {
        let events = RemoteEvents()
        let a = await events.listen()
        let rev = await events.revision
        #expect(await events.waitChange(a, since: rev, timeout: 0.05) == rev)  // (nothing changed: the same after the wait)
        Task {
            try await Task.sleep(for: .milliseconds(50))
            await events.changed()
        }
        #expect(await events.waitChange(a, since: rev, timeout: 5) == rev + 1)
        var more: [RemoteEvents.Stream] = []
        for _ in 0 ..< RemoteAccess.eventStreams { more.append(await events.listen()) }
        #expect(await events.waitChange(a, since: await events.revision, timeout: 1) == nil)  // (the oldest ended)
        #expect(await events.streams == RemoteAccess.eventStreams)
        await events.unlisten(more[0])
        #expect(await events.streams == RemoteAccess.eventStreams - 1)
        let second = more[1]
        let waiting = Task { await events.waitChange(second, since: await events.revision, timeout: 10) }
        try await Task.sleep(for: .milliseconds(50))
        await events.endStreams()  // (the server stops: every stream ends, a waiting one too)
        #expect(await waiting.value == nil && (await events.streams) == 0)
        #expect(await events.waitChange(more[2], since: 0, timeout: 1) == nil)
    }

    static func firstDifference(_ a: String, _ b: String) -> String {
        let (x, y) = (Array(a.utf8), Array(b.utf8))
        guard let i = (0 ..< min(x.count, y.count)).first(where: { x[$0] != y[$0] }) else {
            return "the end (\(x.count) and \(y.count) bytes)"
        }
        let near = { (s: [UInt8]) in String(decoding: s[max(0, i - 40) ..< min(s.count, i + 40)], as: UTF8.self) }
        return "byte \(i): …\(near(x))… vs …\(near(y))…"
    }
}
