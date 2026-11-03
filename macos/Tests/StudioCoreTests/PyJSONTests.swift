import Foundation
import Testing
@testable import StudioCore

/// The JSON of the job folders is read and written the way Python does: keys keep their order, whole numbers stay
/// whole, and what Swift writes is byte for byte what `json.dumps` writes.
@Suite struct PyJSONTests {
    struct Case {
        let value: JSONValue
        let compact: String
        let pretty: String
    }

    static func cases() throws -> [Case] {
        guard case .array(let items) = try Fixtures.json("pyjson.json") else {
            Issue.record("pyjson.json is not a list")
            return []
        }
        return items.compactMap { item in
            guard case .object(let o) = item, let value = o["value"],
                  case .string(let compact)? = o["compact"], case .string(let pretty)? = o["pretty"]
            else { return nil }
            return Case(value: value, compact: compact, pretty: pretty)
        }
    }

    @Test func pyjsonMatchesPython() throws {
        let cases = try Self.cases()
        #expect(cases.count >= 30)
        for c in cases {
            #expect(PyJSON.dump(c.value) == c.compact)
            #expect(PyJSON.dump(c.value, indent: 2) == c.pretty)
            #expect(try PyJSON.parse(Data(c.pretty.utf8)) == c.value)
            #expect(try PyJSON.parse(Data(c.compact.utf8)) == c.value)
        }
    }

    @Test func keysKeepTheirOrder() throws {
        let value = try PyJSON.parse(Data(#"{"b": 1, "a": 2, "ü": {"z": 0, "y": 1}}"#.utf8))
        guard case .object(let o) = value, case .object(let inner)? = o["ü"] else {
            Issue.record("not an object")
            return
        }
        #expect(o.keys == ["b", "a", "ü"] && inner.keys == ["z", "y"])
        #expect(PyJSON.dump(value) == #"{"b": 1, "a": 2, "ü": {"z": 0, "y": 1}}"#)
    }

    @Test func aDuplicateKeyKeepsItsPlaceAndTakesTheLastValue() throws {
        let value = try PyJSON.parse(Data(#"{"a": 1, "b": 2, "a": 3}"#.utf8))  // as Python's json.loads
        #expect(PyJSON.dump(value) == #"{"a": 3, "b": 2}"#)
    }

    @Test func objectsAreEqualWhateverTheOrder() {
        let one: JSONObject = ["a": .int(1), "b": .int(2)]
        let two: JSONObject = ["b": .int(2), "a": .int(1)]
        #expect(one == two && one.hashValue == two.hashValue)
        #expect(JSONValue.int(1) != JSONValue.double(1))
    }

    @Test func pythonsSpecialFloats() throws {
        let value = try PyJSON.parse(Data("[NaN, Infinity, -Infinity]".utf8))  // json.dump writes these by default
        #expect(PyJSON.dump(value) == "[NaN, Infinity, -Infinity]")
    }

    @Test func aWholeNumberTooLargeForIntBecomesADouble() throws {
        #expect(try PyJSON.parse(Data("12345678901234567890".utf8)) == .double(12345678901234567890.0))
    }

    @Test(arguments: [
        "", "[1, 2", "[1, 2,]", #"{"a" 1}"#, #"{"a": 1,}"#, "01", "1 2", #""\x""#, "\"tab\tin string\"",
        #""\ud800""#, "tru", "[]]",
    ])
    func rejectsBrokenJSON(_ text: String) {
        #expect(throws: PyJSON.ParseError.self) { try PyJSON.parse(Data(text.utf8)) }
    }

    @Test func rejectsBrokenUTF8() {
        #expect(throws: PyJSON.ParseError.self) { try PyJSON.parse(Data([0x22, 0xFF, 0x22])) }
    }

    @Test func truthyLikePython() {
        let falsy: [JSONValue] = [.null, .bool(false), .int(0), .double(0), .string(""), .array([]), .object([:])]
        let truthy: [JSONValue] = [.bool(true), .int(-1), .double(.nan), .string("none"), .array([.null]),
                                   .object(["a": .null])]
        #expect(falsy.allSatisfy { !$0.truthy } && truthy.allSatisfy(\.truthy))
    }
}
