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
            Issue.record("no picture"); return
        }
        #expect(type == "image/jpeg" && jpeg.starts(with: [0xFF, 0xD8]))
        answer = Self.json(await model.phoneAnswer("do_style", ["style": "charcoal", "paper": "kraft"], payload: nil))
        #expect(answer == ["ok": true] && model.settings["canvas_style"] == "charcoal"
            && model.settings["canvas_paper"] == "kraft")
    }

    @Test func theStudiosStateAndItsSketch() async throws {
        let (model, _) = try Self.model()
        let cases = try #require(try PyJSON.parse(Data(contentsOf: SelfTestTests.fixtures
                .appending(path: "phone/studio.json"))).objectValue)
        let keys = (cases["studio_keys"]?.arrayValue ?? []).compactMap(\.stringValue)
        let state = try #require(Self.json(await model.phoneAnswer("get_studio", [:], payload: nil)))
        #expect(state.keys == keys)  // (every field the page reads, in the studio's order)
        #expect(state["image"] == .null && state["seeds"] == [] && state["shown"] == .null)
        model.studio.image = SelfTestTests.fixtures.appending(path: "mask/small.png")
        let image = try #require(Self.json(await model.phoneAnswer("get_studio", [:], payload: nil))?["image"]?
            .objectValue)
        #expect(image["name"] == "small.png" && image["size"]?.stringValue?.contains("×") == true)
        // no sketch yet
        let none = Self.json(await model.phoneAnswer("file_sketch", [:], payload: nil))
        #expect(none == ["ok": false, "error": .string(model.texts.tr("ui.phone.page.no_sketch"))])
        #expect(Self.json(await model.phoneAnswer("do_select", ["seed": "x"], payload: nil))
            == ["ok": false, "error": "unknown sketch"])
        // the pictures to choose from: the samples of the studio
        let images = try #require(Self.json(await model.phoneAnswer("get_images", [:], payload: nil)))
        #expect((images["samples"]?.arrayValue?.count ?? 0) >= 5 && images["recent"] == [])
        #expect(Self.json(await model.phoneAnswer("do_image", ["src": "sample", "i": 0], payload: nil)) == ["ok": true])
        #expect(model.studio.image?.path.contains("samples") == true)
        #expect(Self.json(await model.phoneAnswer("do_image", ["src": "nope", "i": 0], payload: nil))
            == ["ok": false, "error": "unknown source"])
    }

    @Test func theResultsFromThePhone() async throws {
        let out = try GalleryModelTests.folder()
        let (model, _) = try Self.model(["output_dir": .string(out.path)])
        let first = try #require(Self.json(await model.phoneAnswer("get_results", [:], payload: nil)))
        let results = (first["results"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(results.count >= 3 && first["total"] == .int(results.count) && first["offset"] == 0)
        #expect(first["sorts"]?.arrayValue?.count == 6 && first["methods"]?.arrayValue?.count == 4)
        // (a result that is no favourite and in no album yet – the fixtures have some that are)
        let one = try #require(results.first { $0["fav"] == false && $0["albums"] == [] })
        let dir = try #require(one["dir"])
        #expect(one["name"]?.stringValue?.isEmpty == false && one["i"]?.intValue != nil)
        // favourite, info, albums
        #expect(Self.json(await model.phoneAnswer("do_fav", ["dir": dir, "value": true], payload: nil)) == ["ok": true])
        #expect(Self.json(await model.phoneAnswer("do_info", ["dir": dir, "title": "Zebra", "tags": " Streifen, Savanne ,",
                                                             "notes": "am Wasserloch"], payload: nil)) == ["ok": true])
        #expect(Self.json(await model.phoneAnswer("do_album", ["op": "new", "name": "  Urlaub  2026 ", "dirs": [dir]],
                                                  payload: nil)) == ["ok": true, "name": "Urlaub 2026"])
        var shown = try #require(Self.json(await model.phoneAnswer("get_results", ["album": "Urlaub 2026", "fav": "1"],
                                                                   payload: nil)))
        var item = try #require(shown["results"]?.arrayValue?.first?.objectValue)
        #expect(shown["total"] == 1 && item["dir"] == dir && item["title"] == "Zebra" && item["fav"] == true)
        #expect(item["notes"] == "am Wasserloch" && item["tags"] == ["Streifen", "Savanne"])
        #expect(item["albums"] == ["Urlaub 2026"])
        let albums = (shown["albums"]?.arrayValue ?? []).compactMap(\.stringValue)
        let tags = (shown["tags"]?.arrayValue ?? []).compactMap(\.stringValue)
        #expect(albums.first == "Urlaub 2026" && albums.contains("Tiere"))  // (the app's own first, then the found)
        #expect(tags.contains("Savanne") && tags == tags.sorted { $0.lowercased() < $1.lowercased() })
        _ = await model.phoneAnswer("do_album", ["op": "rename", "name": "Urlaub 2026", "new": "Reise"], payload: nil)
        shown = try #require(Self.json(await model.phoneAnswer("get_results", ["album": "Reise"], payload: nil)))
        #expect(shown["total"] == 1)
        _ = await model.phoneAnswer("do_album", ["op": "delete", "name": "Reise"], payload: nil)
        shown = try #require(Self.json(await model.phoneAnswer("get_results", ["q": "wasserloch"], payload: nil)))
        item = try #require(shown["results"]?.arrayValue?.first?.objectValue)
        #expect(shown["total"] == 1 && item["albums"] == [])
        #expect(!(shown["albums"]?.arrayValue ?? []).contains("Reise"))
        #expect(Self.json(await model.phoneAnswer("do_album", ["op": "new", "name": "  "], payload: nil))?["ok"] == false)
        // its sketch, and in the studio
        guard case .bytes(let svg, let type, _) = await model.phoneAnswer("file_result", ["d": dir], payload: nil) else {
            Issue.record("no sketch"); return
        }
        #expect(type == "image/svg+xml" && String(decoding: svg, as: UTF8.self).contains("<svg"))
        #expect(Self.json(await model.phoneAnswer("do_open", ["dir": dir], payload: nil)) == ["ok": true])
        #expect(model.studio.result?.jobDir.lastPathComponent == dir.stringValue)
        #expect(Self.json(await model.phoneAnswer("do_open", ["dir": "gone"], payload: nil))
            == ["ok": false, "error": .string(model.texts.tr("ui.phone.page.list_changed"))])
        // the shown sketch exported from the phone (the CLIPasso result of the fixtures): its formats, then an SVG
        // in the background, downloaded
        #expect(Self.json(await model.phoneAnswer("do_open", ["dir": "done_clipasso"], payload: nil)) == ["ok": true])
        let info = try #require(Self.json(await model.phoneAnswer("get_export_info", [:], payload: nil)))
        let formats = (info["formats"]?.arrayValue ?? []).compactMap { $0.objectValue?["fmt"]?.stringValue }
        #expect(info["ok"] == true && formats.contains("svg") && formats.contains("gif") && !formats.contains("matrix"))
        let started = try #require(Self.json(await model.phoneAnswer("do_export", [
            "fmt": "svg", "options": ["stroke": "#336699", "background": "transparent", "frame": "content"]],
                                                                     payload: nil)))
        let id = try #require(started["id"])
        #expect(started["ok"] == true && started["name"]?.stringValue?.hasSuffix(".svg") == true)
        var state: JSONObject = [:]
        for _ in 0 ..< 250 {
            state = Self.json(await model.phoneAnswer("get_export", ["id": id], payload: nil)) ?? [:]
            if state["status"] != "running" { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(state["status"] == "done" && (state["size"]?.intValue ?? 0) > 0, "\(state)")
        guard case .file(let file, "image/svg+xml", let name) = await model.phoneAnswer("file_export", ["id": id],
                                                                                         payload: nil)
        else { Issue.record("no file"); return }
        #expect(name == started["name"]?.stringValue)
        #expect((try String(contentsOf: file, encoding: .utf8)).contains("#336699"))
        #expect(model.settings["export_stroke"] == "#336699" && model.settings["export_last_format"] == "svg")
        #expect(Self.json(await model.phoneAnswer("get_export", ["id": "nope"], payload: nil))?["ok"] == false)
        #expect(Self.json(await model.phoneAnswer("do_export", ["fmt": "nope"], payload: nil))
            == ["ok": false, "error": "unknown format"])
        // the queue without an engine: empty, with its switches
        let queue = try #require(Self.json(await model.phoneAnswer("get_queue", [:], payload: nil)))
        #expect(queue["jobs"] == [] && queue["auto_start"] == true && queue["done_actions"]?.arrayValue?.count == 3)
    }

    #if canImport(ImageIO)
    @Test func theMaskAndTheDetailsFromThePhone() async throws {
        let engine = SelfTestTests.fake(["mask", StudioMaskTests.probability.path])
        let secrets = MemorySecrets()
        let model = try AppModel(resources: AppModelTests.resources(engine: engine),
                                 store: AppModelTests.store(language: "de"), secrets: secrets)
        await model.startEngine()
        let notReady = Self.json(await model.phoneAnswer("do_mask_begin", [:], payload: nil))
        #expect(notReady == ["ok": false, "error": .string(model.texts.tr("ui.phone.page.mask_not_ready"))])
        model.studio.image = SelfTestTests.fixtures.appending(path: "mask/small.png")
        model.studio.selectMethod("swiftsketch")
        model.studio.set("mask_object", to: true)
        await model.updateMask()
        for _ in 0 ..< 200 where model.mask.state != .ready { try await Task.sleep(for: .milliseconds(20)) }
        guard case .bytes(let shown, "image/jpeg", _) = await model.phoneAnswer("file_mask", [:], payload: nil) else {
            Issue.record("no mask picture"); return
        }
        #expect(shown.starts(with: [0xFF, 0xD8]))
        let begun = try #require(Self.json(await model.phoneAnswer("do_mask_begin", [:], payload: nil)))
        #expect(begun["ok"] == true && begun["undo"] == false && begun["rev"] == 0)
        let share = begun["share"]?.doubleValue ?? 0
        // the brush erases a stroke across the picture (places 0 … 1, the brush a share of its width)
        let erased = try #require(Self.json(await model.phoneAnswer("do_mask_edit", [
            "op": "erase", "size": 0.2, "points": [[0.0, 0.5], [1.0, 0.5]]], payload: nil)))
        #expect(erased["ok"] == true && erased["undo"] == true && erased["rev"] == 1)
        #expect((erased["share"]?.doubleValue ?? 1) < share)
        let undone = try #require(Self.json(await model.phoneAnswer("do_mask_edit", ["op": "undo"], payload: nil)))
        #expect(undone["share"]?.doubleValue == share && undone["redo"] == true)
        _ = await model.phoneAnswer("do_mask_edit", ["op": "redo"], payload: nil)
        #expect(Self.json(await model.phoneAnswer("do_mask_edit", ["op": "nope"], payload: nil))
            == ["ok": false, "error": "unknown edit"])
        guard case .bytes(_, "image/jpeg", _) = await model.phoneAnswer("file_mask_edit", [:], payload: nil) else {
            Issue.record("no picture of the edit"); return
        }
        #expect(Self.json(await model.phoneAnswer("do_mask_save", [:], payload: nil)) == ["ok": true])
        for _ in 0 ..< 200 where model.mask.state != .edited { try await Task.sleep(for: .milliseconds(20)) }
        #expect(model.mask.state == .edited)  // (the user's mask, kept by the engine)
        #expect(Self.json(await model.phoneAnswer("do_mask_edit", ["op": "undo"], payload: nil))?["ok"] == false)
        // the detail map: painted on the phone, kept, removed
        let png = try Data(contentsOf: SelfTestTests.fixtures.appending(path: "mask/small.png"))
        #expect(Self.json(await model.phoneAnswer("set_details", [:], payload: png)) == ["ok": true])
        #expect(Self.json(await model.phoneAnswer("get_studio", [:], payload: nil))?["details"]?.objectValue?["rev"] == 1)
        await model.stopEngine()
    }
    #endif

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
