import Foundation
import Testing
@testable import StudioCore

/// The studio from the phone as gui/phone_api.py has it (Fixtures/phone/studio.json, made with its functions): every
/// method's parameters as the phone shows them in German and English, and what the phone's raw values become.
@Suite struct PhoneStudioTests {
    static func cases() throws -> JSONObject { try #require(Fixtures.json("phone/studio.json").objectValue) }

    /// JSON alike – numbers by their value (Python's 1 and 1.0 are the same limit for the page).
    static func alike(_ a: JSONValue, _ b: JSONValue) -> Bool {
        switch (a, b) {
        case (.int(let x), .double(let y)), (.double(let y), .int(let x)): return Double(x) == y
        case (.double(let x), .double(let y)): return x == y || (x.isNaN && y.isNaN)
        case (.array(let x), .array(let y)): return x.count == y.count && zip(x, y).allSatisfy { alike($0, $1) }
        case (.object(let x), .object(let y)):
            return Set(x.keys) == Set(y.keys) && x.keys.allSatisfy { alike(x[$0]!, y[$0]!) } && x.keys == y.keys
        default: return a == b
        }
    }

    @Test(arguments: ["de", "en"])
    func theParametersAsThePhoneShowsThem(_ lang: String) throws {
        let schema = try ParamSchema.load(Fixtures.url("schema.json"))
        let texts = try Texts(directory: TextsTests.i18n, language: lang)
        let all = try #require(try Self.cases()["schemas"]?.objectValue)
        for id in schema.methods {
            let want = try #require(all["\(id)_\(lang)"])
            let made = JSONValue.object(PhoneStudio.schema(try #require(schema.method(id)), texts: texts))
            #expect(Self.alike(made, want), "\(id) (\(lang))")
            if !Self.alike(made, want) {  // (where it differs first)
                let a = made.objectValue?["groups"]?.arrayValue ?? [], b = want.objectValue?["groups"]?.arrayValue ?? []
                for (x, y) in zip(a, b) where !Self.alike(x, y) {
                    let px = x.objectValue?["params"]?.arrayValue ?? [], py = y.objectValue?["params"]?.arrayValue ?? []
                    for (u, v) in zip(px, py) where !Self.alike(u, v) {
                        Issue.record("\(PyJSON.dump(u)) instead of \(PyJSON.dump(v))")
                        break
                    }
                }
            }
        }
    }

    @Test func thePhonesValuesAsPythonTakesThem() throws {
        let schema = try ParamSchema.load(Fixtures.url("schema.json"))
        let all = (try Self.cases()["coerce"]?.arrayValue ?? []).compactMap(\.objectValue)
        #expect(all.count > 1000)
        for c in all {
            let method = try #require(schema.method(c["method"]?.stringValue ?? ""))
            let param = try #require(method.param(c["key"]?.stringValue ?? ""))
            let raw = c["raw"] ?? .null
            let made = PhoneStudio.coerce(param, raw)
            if c["ok"]?.truthy == true {
                let want = c["value"] ?? .null
                #expect(made.map { Self.alike($0, want) } == true,
                        "\(method.id).\(param.key) ← \(PyJSON.dump(raw)): \(made.map { PyJSON.dump($0) } ?? "refused") instead of \(PyJSON.dump(want))")
            } else {
                #expect(made == nil, "\(method.id).\(param.key) ← \(PyJSON.dump(raw)): \(made.map { PyJSON.dump($0) } ?? "") instead of refused")
            }
        }
        #expect(PhoneStudio.inputSide == (try Self.cases()["input_side"]?.intValue))
    }
}
