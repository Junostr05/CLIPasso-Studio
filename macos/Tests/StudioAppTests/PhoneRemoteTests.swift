import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The phone remote in the app (PhoneLink): its texts as the studio gives them to the page, the access code and the
/// PIN (made once, kept in the secret store – never in settings.json), the page on and off as the settings say, and
/// what the phone sends reaching the studio.
@Suite(.serialized) struct PhoneRemoteTests {
    static func model(language: String = "de", _ more: JSONObject = [:]) throws -> (AppModel, MemorySecrets) {
        let secrets = MemorySecrets()
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: language, more), secrets: secrets)
        return (model, secrets)
    }

    @Test(arguments: ["de", "en"])
    func thePagesTextsLikeTheStudio(_ lang: String) throws {
        let cases = try #require(try PyJSON.parse(Data(contentsOf: SelfTestTests.fixtures
                .appending(path: "remote/remote.json"))).objectValue)
        let want = try #require(cases["texts"]?.objectValue?[lang]?.objectValue)
        let (model, _) = try Self.model(language: lang)
        let made = model.phoneTexts()
        let missing = want.keys.filter { made[$0] == nil }, extra = made.keys.filter { want[$0] == nil }
        #expect(missing.isEmpty && extra.isEmpty, "missing \(missing), extra \(extra)")
        for (key, value) in want where made[key] != value {
            Issue.record("\(key): \(made[key].map { "\($0)" } ?? "–") instead of \(value)")
        }
    }

    @Test func theCodeAndThePin() throws {
        let (model, secrets) = try Self.model()
        let keys = model.phone.keys
        let token = keys.token()
        #expect(token.count == 24 && keys.token() == token && secrets.get("remote_token") == token)  // (made once)
        let pin = keys.pin()
        #expect(RemoteAccess.validPin(pin) && keys.pin() == pin)
        #expect(!model.phone.setPin("12345") && keys.pin() == pin)  // (not six digits: the PIN stays)
        #expect(model.phone.setPin(" 424242 ") && keys.pin() == "424242")
        model.phone.newToken()
        #expect(keys.token() != token)
        // never in the settings file
        let file = try String(contentsOf: model.store.url, encoding: .utf8)
        #expect(!file.contains(keys.token()) && !file.contains("424242"))
    }

    @Test func thePageOnAndOff() async throws {
        let (model, _) = try Self.model(["remote_port": 0, "remote_tailscale": false])
        let off = await model.applyPhoneSettings()
        #expect(off == "" && !model.phone.running)  // (off: nothing runs)
        await model.setPhoneOn(true)
        #expect(model.phone.running && model.phone.port > 0 && model.phone.error.isEmpty)
        let base = "http://127.0.0.1:\(model.phone.port)"
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieAcceptPolicy = .never
        config.httpShouldSetCookies = false
        let session = URLSession(configuration: config)
        // the QR code's address signs in (here the redirect is followed: the page itself comes back)
        var request = URLRequest(url: URL(string: model.phone.url(address: "127.0.0.1"))!)
        let (page, response) = try await session.data(for: request)
        #expect((response as? HTTPURLResponse)?.statusCode == 200)
        let html = String(decoding: page, as: UTF8.self)
        #expect(html.contains("login.js") || html.contains(model.phone.keys.token()))
        // a picture for the studio
        let png = try Data(contentsOf: SelfTestTests.fixtures.appending(path: "mask/small.png"))
        request = URLRequest(url: URL(string: base + "/api/upload")!)
        request.httpMethod = "POST"
        request.httpBody = png
        request.setValue(model.phone.keys.token(), forHTTPHeaderField: "X-Access")
        request.setValue("studio", forHTTPHeaderField: "X-Target")
        request.setValue("Strand.png", forHTTPHeaderField: "X-Filename")
        let (_, uploaded) = try await session.data(for: request)
        #expect((uploaded as? HTTPURLResponse)?.statusCode == 200)
        #expect(model.studio.image?.lastPathComponent.hasSuffix("_Strand.png") == true)
        #expect(model.studio.image?.path.contains("/\(RemoteAccess.uploadDir)/") == true)
        // the status the page reads
        request = URLRequest(url: URL(string: base + "/api/status")!)
        request.setValue("\(RemoteAccess.cookie)=\(model.phone.keys.token())", forHTTPHeaderField: "Cookie")
        let (status, _) = try await session.data(for: request)
        let state = try #require(try PyJSON.parse(status).objectValue)
        #expect(state["busy"] == false && state["queue"] == 0 && state["version"] != nil)
        await model.setPhoneOn(false)
        #expect(!model.phone.running)
        await #expect(throws: (any Error).self) { _ = try await session.data(from: URL(string: base + "/")!) }
    }

    static func json(_ answer: RemoteAnswer) -> JSONObject? {
        if case .json(let value) = answer { return value.objectValue }
        return nil
    }

    @Test func theStudioFromThePhone() async throws {
        let (model, _) = try Self.model()
        var answer = Self.json(await model.phoneAnswer("do_method", ["method": "swiftsketch"], payload: nil))
        #expect(answer == ["ok": true] && model.studio.method == "swiftsketch")
        answer = Self.json(await model.phoneAnswer("do_method", ["method": "nope"], payload: nil))
        #expect(answer == ["ok": false, "error": "unknown method"])
        let schema = Self.json(await model.phoneAnswer("get_schema", [:], payload: nil))
        #expect(schema?["method"] == "swiftsketch" && schema?["groups"]?.arrayValue?.isEmpty == false)
        let param = try #require(model.studio.methodSchema?.params.first { $0.kind == .int })
        answer = Self.json(await model.phoneAnswer("do_set", ["key": .string(param.key), "value": "abc"], payload: nil))
        #expect(answer?["ok"] == false && answer?["error"] == .string(model.texts.tr("ui.phone.page.bad_value")))
        let wanted = Int(param.minimum ?? 1)
        answer = Self.json(await model.phoneAnswer("do_set", ["key": .string(param.key), "value": .string(" \(wanted) ")],
                                                   payload: nil))
        #expect(answer == ["ok": true] && model.studio.settings[param.key] == .int(wanted))
        answer = Self.json(await model.phoneAnswer("do_set", ["key": "nope", "value": 1], payload: nil))
        #expect(answer == ["ok": false, "error": "unknown setting"])
        answer = Self.json(await model.phoneAnswer("do_preset", ["preset": "fast"], payload: nil))
        #expect(answer == ["ok": true] && model.studio.preset == "fast")
        answer = Self.json(await model.phoneAnswer("do_start", [:], payload: nil))  // (no picture yet)
        #expect(answer == ["ok": false, "error": .string(model.texts.tr("ui.phone.page.no_picture"))])
        model.studio.image = SelfTestTests.fixtures.appending(path: "mask/small.png")
        guard case .bytes(let jpeg, let type, _) = await model.phoneAnswer("file_input", [:], payload: nil) else {
            return Issue.record("no picture")
        }
        #expect(type == "image/jpeg" && jpeg.starts(with: [0xFF, 0xD8]))
        answer = Self.json(await model.phoneAnswer("do_style", ["style": "charcoal", "paper": "kraft"], payload: nil))
        #expect(answer == ["ok": true] && model.settings["canvas_style"] == "charcoal"
            && model.settings["canvas_paper"] == "kraft")
    }

    @Test func aPortInUse() async throws {
        let (first, _) = try Self.model(["remote_port": 0])
        await first.setPhoneOn(true)
        let taken = first.phone.port
        let (second, _) = try Self.model(["remote_port": .int(taken)])
        await second.setPhoneOn(true)
        #expect(!second.phone.running && second.phone.error.contains("\(taken)"))  // (ui.phone.port_busy)
        await first.setPhoneOn(false)
    }
}
