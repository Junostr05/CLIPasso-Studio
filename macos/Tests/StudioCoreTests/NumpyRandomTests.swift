import Foundation
import Testing
@testable import StudioCore

/// numpy's random numbers in Swift – checked against what numpy drew for the same seeds (Fixtures/paper/random.json):
/// the raw 64-bit numbers of PCG64 seeded by SeedSequence, 30 000 standard normals (the ziggurat with its tail) and
/// the draws of the paper's fibres one after another (uniform, a choice of two – 32 bits –, normal), bit for bit.
@Suite struct NumpyRandomTests {
    /// FNV-1a (64 bit) over the numbers' IEEE bits, 8 bytes each, little-endian (make_mac_fixtures._bits_hash).
    static func bitsHash(_ values: [Double]) -> String {
        var h: UInt64 = 0xCBF2_9CE4_8422_2325
        for v in values {
            var bits = v.bitPattern
            for _ in 0 ..< 8 {
                h = (h ^ (bits & 0xFF)) &* 0x0000_0100_0000_01B3
                bits >>= 8
            }
        }
        return hex(h)
    }

    static func hex(_ v: UInt64) -> String {
        let digits = String(v, radix: 16)
        return String(repeating: "0", count: 16 - digits.count) + digits
    }

    static func numbers(_ value: JSONValue?) -> [Double] { (value?.arrayValue ?? []).compactMap(\.doubleValue) }

    @Test func drawsWhatNumpyDraws() throws {
        let cases = try #require(Fixtures.json("paper/random.json").arrayValue).compactMap(\.objectValue)
        #expect(cases.count == 9)
        for c in cases {
            let seed = (c["seed"]?.arrayValue ?? []).compactMap(\.intValue).map { UInt32($0) }
            var rng = NumpyRandom(seed: seed)
            let raw = (0 ..< 8).map { _ in Self.hex(rng.nextUInt64()) }
            #expect(raw == (c["raw"]?.arrayValue ?? []).compactMap(\.stringValue), "\(seed)")

            rng = NumpyRandom(seed: seed)
            let normals = (0 ..< 30000).map { _ in rng.standardNormal() }
            #expect(Array(normals.prefix(12)) == Self.numbers(c["normals_first"]), "\(seed)")
            #expect(Self.bitsHash(normals) == c["normals_hash"]?.stringValue, "\(seed)")

            rng = NumpyRandom(seed: seed)
            var fibres: [Double] = []
            for _ in 0 ..< 300 {  // (in gui/paper._fibers' order)
                fibres += [rng.uniform(0, 300), rng.uniform(0, 200), rng.uniform(0, .pi), rng.uniform(6, 26),
                           rng.uniform(-0.4, 0.4), Double(rng.choice([-1, 1])), rng.uniform(64, 127), rng.normal(0, 1)]
            }
            let first = (c["fibres_first"]?.arrayValue ?? []).flatMap { Self.numbers($0) }
            #expect(Array(fibres.prefix(16)) == first, "\(seed)")
            #expect(Self.bitsHash(fibres) == c["fibres_hash"]?.stringValue, "\(seed)")
        }
    }

    @Test func aChoiceTakesHalfOfSixtyFourBits() {
        var a = NumpyRandom(seed: [7, 2])
        var b = a
        let wide = b.nextUInt64()
        #expect(a.nextUInt32() == UInt32(truncatingIfNeeded: wide) && a.nextUInt32() == UInt32(truncatingIfNeeded: wide >> 32))
        #expect(a.nextUInt64() == b.nextUInt64())  // (the 64-bit draws go on from the same place)
    }
}
