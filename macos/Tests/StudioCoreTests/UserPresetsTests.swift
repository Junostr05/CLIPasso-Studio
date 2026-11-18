import Foundation
import Testing
@testable import StudioCore

/// The user's own presets as gui/user_presets.py keeps them (Fixtures/user_presets.json): which of the stored ones
/// remain, what saving and deleting keep, which the settings match, and that only the last 100 are kept.
@Suite struct UserPresetsTests {
    @Test func likeTheStudio() throws {
        let schema = try ParamSchema.load(Fixtures.url("schema.json"))
        let cases = try #require(Fixtures.json("user_presets.json").objectValue)
        var stored = try #require(cases["stored"])
        let all = UserPresets.all(stored, schema: schema).map(\.json)
        #expect(all == cases["all"]?.arrayValue)
        for op in cases["ops"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            let name = op["name"] ?? .null
            if op["op"] == "save" {
                let saved = UserPresets.save(name, op["arg"]?.objectValue ?? [:], in: stored, schema: schema)
                if op["result"] == "error" {
                    #expect(saved == nil, "\(name)")
                } else {
                    #expect(saved?.saved.json == op["result"], "\(name)")
                    stored = saved?.stored ?? stored
                }
            } else {
                let kept = UserPresets.delete(name.stringValue ?? "", method: op["arg"]?.stringValue ?? "", in: stored,
                                              schema: schema)
                #expect((kept != nil) == (op["result"] == true), "\(name)")
                stored = kept ?? stored
            }
            #expect(stored == op["stored"], "after \(op["op"] ?? "") \(name)")
        }
        for m in cases["matching"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            #expect(UserPresets.matching(m["settings"]?.objectValue ?? [:], in: stored, schema: schema)
                == m["name"]?.stringValue)
        }
    }

    @Test func theLastHundred() throws {
        let schema = try ParamSchema.load(Fixtures.url("schema.json"))
        let cases = try #require(Fixtures.json("user_presets.json").objectValue)
        let start = try #require(schema.method("clipasso")?.start)
        let many: JSONValue = .array((0 ..< 100).map {
            ["name": .string("P\($0)"), "method": "clipasso", "settings": .object(start)]
        })
        let saved = try #require(UserPresets.save("Hundertundeins", start, in: many, schema: schema))
        let names = saved.stored.arrayValue?.compactMap { $0.objectValue?["name"]?.stringValue } ?? []
        #expect(.array(names.map(JSONValue.string)) == cases["trimmed"])
    }
}
