import Foundation
import Testing
@testable import StudioCore

/// The parameters, their rules ("enabled when …") and the presets come from schema.json, exported by the Python side –
/// and decide exactly what settings_schema.py decides.
@Suite struct ParamSchemaTests {
    let schema: ParamSchema

    init() throws {
        schema = try ParamSchema.load(Fixtures.url("schema.json"))
    }

    @Test func methodsAndDevices() throws {
        #expect(schema.methods == ["clipasso", "swiftsketch", "controlsketch", "scenesketch"])
        #expect(schema.defaultMethod == "clipasso")
        #expect(schema.devices == ["auto", "cpu", "cuda", "mps"])
        let clipasso = try #require(schema.method("clipasso"))
        #expect(clipasso.name == "CLIPasso" && clipasso.presetOrder == ["fast", "standard", "quality"])
        let numPaths = try #require(clipasso.param("num_paths"))
        #expect(numPaths.kind == .int && numPaths.default == .int(16) && numPaths.minimum == 1 && numPaths.maximum == 256)
        #expect(numPaths.text.label == "param.num_paths.label")
        #expect(clipasso.param("device")?.text.choices["mps"] == "param.device.choice.mps")
    }

    @Test func everyConditionMatchesPython() throws {
        let data = try #require(Fixtures.json("conditions.json").objectValue)
        let ruled = try #require(data["ruled"]?.objectValue)
        let cases = try #require(data["cases"]?.arrayValue)
        #expect(cases.count == 800)
        for item in cases {
            let c = try #require(item.objectValue)
            let methodID = try #require(c["method"]?.stringValue)
            let method = try #require(schema.method(methodID))
            let changes = try #require(c["changes"]?.objectValue)
            let settings = method.defaults.merging(changes)
            let keys = try #require(ruled[method.id]?.arrayValue).compactMap(\.stringValue)
            let enabled = try #require(c["enabled"]?.stringValue)
            let got = keys.map { key in method.isEnabled(method.param(key)!, in: settings) ? "1" : "0" }.joined()
            #expect(got == enabled, "\(method.id) \(PyJSON.dump(.object(settings)))")
            #expect(method.numStrokes(settings) == c["num_strokes"]?.intValue)
        }
    }

    @Test func paramsWithoutARuleAreAlwaysEnabled() throws {
        let clipasso = try #require(schema.method("clipasso"))
        let seed = try #require(clipasso.param("seed"))
        #expect(seed.enabledIf == nil && clipasso.isEnabled(seed, in: [:]))
    }

    @Test func presetsAndDefaults() throws {
        for id in schema.methods {
            let method = try #require(schema.method(id))
            #expect(method.defaults["method"] == .string(id))
            for name in method.presetOrder {
                let preset = try #require(method.presets[name])
                let applied = method.applyPreset(name, to: method.defaults)
                for (key, value) in preset {
                    #expect(applied[key] == value)
                }
                #expect(applied.count == method.defaults.count)  // (a preset only sets known keys)
            }
        }
    }

    @Test func clampFollowsCoerce() throws {
        let clipasso = try #require(schema.method("clipasso"))
        let paths = try #require(clipasso.param("num_paths"))
        #expect(clipasso.clamp(paths, .int(300)) == .int(256))
        #expect(clipasso.clamp(paths, .int(0)) == .int(1))
        #expect(clipasso.clamp(paths, .double(3.7)) == .int(3))  // int(float(3.7)) in Python
        #expect(clipasso.clamp(paths, .string("12.9")) == .int(12))
        let width = try #require(clipasso.param("width"))
        #expect(clipasso.clamp(width, .int(50)) == .double(20))
        #expect(clipasso.clamp(width, .double(0.01)) == .double(0.1))
        let device = try #require(clipasso.param("device"))
        #expect(clipasso.clamp(device, .string("mps")) == .string("mps"))
        #expect(clipasso.clamp(device, .string("tpu")) == device.default)  // not a choice: the default
        let points = try #require(clipasso.param("control_points_per_seg"))
        #expect(clipasso.clamp(points, .string("3")) == .int(3))  // int choices
        let mask = try #require(clipasso.param("mask_object"))
        #expect(clipasso.clamp(mask, .string("yes")) == .bool(true) && clipasso.clamp(mask, .int(0)) == .bool(false))
    }

    @Test func conditionsReadTheirJSON() throws {
        let rule = try Condition(json: ["op": "all", "of": [["op": "on", "key": "a"],
                                                               ["op": "eq", "key": "b", "value": "x", "default": "x"]]])
        #expect(rule == .all([.on("a"), .eq("b", .string("x"), default: .string("x"))]))
        #expect(rule.evaluate(["a": .bool(true)]))  // b missing: its default
        #expect(!rule.evaluate(["a": .bool(true), "b": .string("y")]))
        #expect(throws: (any Error).self) { try Condition(json: ["op": "xor", "key": "a"]) }
    }

    @Test func pythonComparisonsInRules() {
        #expect(Condition.eq("n", .int(1), default: nil).evaluate(["n": .double(1)]))  // 1 == 1.0
        #expect(Condition.eq("n", .int(1), default: nil).evaluate(["n": .bool(true)]))  // True == 1
        #expect(Condition.gt("n", 0).evaluate(["n": .string("2")]))  // float("2")
        #expect(!Condition.gt("n", 0).evaluate(["n": .null]))  // float(None or 0)
        #expect(Condition.has("f", "noise").evaluate(["f": .string("affine_noise")]))
        #expect(!Condition.has("f", "noise").evaluate([:]))
    }
}
