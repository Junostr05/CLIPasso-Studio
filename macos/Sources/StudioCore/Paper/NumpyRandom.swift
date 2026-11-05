import Foundation

/// numpy's random numbers as `numpy.random.default_rng(seed)` draws them – SeedSequence, PCG64 and the samplers the
/// paper textures use (gui/paper.py): `standard_normal` and `normal` (the ziggurat), `uniform` and `integers` below
/// 2³² (what `choice` of a short list draws) – the very same numbers for the same seed, so a paper of the Mac app is
/// the paper of the studio.
public struct NumpyRandom: Sendable {
    var state: UInt128
    var inc: UInt128
    /// the upper half of the last 64 bits, kept for the next 32-bit draw (pcg64_next32)
    var spare: UInt32?

    static let multiplier = UInt128(2_549_297_995_355_413_924) << 64 | UInt128(4_865_540_595_714_422_341)

    /// `default_rng(seed)` for a seed of non-negative integers below 2³² (each is one word of the entropy).
    public init(seed: [UInt32]) {
        let words = SeedSequence(entropy: seed).generateState64(4)
        let initState = UInt128(words[0]) << 64 | UInt128(words[1])
        let initSeq = UInt128(words[2]) << 64 | UInt128(words[3])
        state = 0
        inc = initSeq << 1 | 1  // (pcg_setseq_128_srandom_r)
        step()
        state &+= initState
        step()
    }

    mutating func step() {
        state = state &* Self.multiplier &+ inc
    }

    /// pcg64_next64: the next state, its XSL-RR output.
    public mutating func nextUInt64() -> UInt64 {
        step()
        let value = UInt64(truncatingIfNeeded: state >> 64) ^ UInt64(truncatingIfNeeded: state)
        let rot = UInt64(truncatingIfNeeded: state >> 122)
        return value >> rot | value << ((0 &- rot) & 63)
    }

    /// pcg64_next32: the lower half of 64 new bits, the upper half the next time.
    public mutating func nextUInt32() -> UInt32 {
        if let spare {
            self.spare = nil
            return spare
        }
        let next = nextUInt64()
        spare = UInt32(truncatingIfNeeded: next >> 32)
        return UInt32(truncatingIfNeeded: next)
    }

    /// uint64_to_double: 53 random bits in [0, 1).
    public mutating func nextDouble() -> Double {
        Double(nextUInt64() >> 11) * (1.0 / 9_007_199_254_740_992.0)
    }

    /// random_standard_normal: the ziggurat of 256 layers.
    public mutating func standardNormal() -> Double {
        while true {
            var r = nextUInt64()
            let idx = Int(r & 0xFF)
            r >>= 8
            let sign = r & 0x1
            let rabs = (r >> 1) & 0x000F_FFFF_FFFF_FFFF
            var x = Double(rabs) * Self.wi[idx]
            if sign & 0x1 != 0 { x = -x }
            if rabs < Self.ki[idx] { return x }  // (99.3 % of the time)
            if idx == 0 {
                while true {  // (the tail beyond r)
                    let xx = -Self.zigguratInvR * log1p(-nextDouble())
                    let yy = -log1p(-nextDouble())
                    if yy + yy > xx * xx {
                        return (rabs >> 8) & 0x1 != 0 ? -(Self.zigguratR + xx) : Self.zigguratR + xx
                    }
                }
            } else if (Self.fi[idx - 1] - Self.fi[idx]) * nextDouble() + Self.fi[idx] < exp(-0.5 * x * x) {
                return x
            }
        }
    }

    /// Generator.normal(loc, scale).
    public mutating func normal(_ loc: Double = 0, _ scale: Double = 1) -> Double {
        loc + scale * standardNormal()
    }

    /// Generator.uniform(low, high).
    public mutating func uniform(_ low: Double, _ high: Double) -> Double {
        low + (high - low) * nextDouble()
    }

    /// Generator.integers(0, n) for 1 ≤ n < 2³² (buffered_bounded_lemire_uint32) – `choice` of a list of n draws this.
    public mutating func integer(below n: UInt32) -> UInt32 {
        let rng = n &- 1
        guard rng > 0 else { return 0 }
        let excl = UInt64(n)
        var m = UInt64(nextUInt32()) * excl
        var leftover = UInt32(truncatingIfNeeded: m)
        if leftover < n {
            let threshold = (UInt32.max - rng) % n
            while leftover < threshold {
                m = UInt64(nextUInt32()) * excl
                leftover = UInt32(truncatingIfNeeded: m)
            }
        }
        return UInt32(truncatingIfNeeded: m >> 32)
    }

    /// Generator.choice of a short list (with replacement, equal chances).
    public mutating func choice<T>(_ items: [T]) -> T {
        items[Int(integer(below: UInt32(items.count)))]
    }
}

/// numpy.random.SeedSequence (without spawn keys): the entropy hashed into a pool of four words, and the words a
/// bit generator is seeded with.
struct SeedSequence {
    static let initA: UInt32 = 0x43B0_D7E5, multA: UInt32 = 0x931E_8875
    static let initB: UInt32 = 0x8B51_F9DD, multB: UInt32 = 0x58F3_8DED
    static let mixL: UInt32 = 0xCA01_F9DD, mixR: UInt32 = 0x4973_F715

    var pool = [UInt32](repeating: 0, count: 4)

    init(entropy: [UInt32]) {
        let entropy = entropy.isEmpty ? [0] : entropy
        var hashConst = Self.initA
        func hashmix(_ value: UInt32) -> UInt32 {
            var value = value ^ hashConst
            hashConst = hashConst &* Self.multA
            value = value &* hashConst
            return value ^ value >> 16
        }
        func mix(_ x: UInt32, _ y: UInt32) -> UInt32 {
            let result = Self.mixL &* x &- Self.mixR &* y
            return result ^ result >> 16
        }
        for i in pool.indices {
            pool[i] = hashmix(i < entropy.count ? entropy[i] : 0)
        }
        for src in pool.indices {
            for dst in pool.indices where src != dst {
                pool[dst] = mix(pool[dst], hashmix(pool[src]))
            }
        }
        for src in pool.count ..< max(pool.count, entropy.count) {
            for dst in pool.indices {
                pool[dst] = mix(pool[dst], hashmix(entropy[src]))
            }
        }
    }

    /// generate_state(n, uint64): 2n words from the pool, read in pairs (little-endian: the first is the lower).
    func generateState64(_ n: Int) -> [UInt64] {
        var hashConst = Self.initB
        var words: [UInt32] = []
        for i in 0 ..< 2 * n {
            var value = pool[i % pool.count] ^ hashConst
            hashConst = hashConst &* Self.multB
            value = value &* hashConst
            words.append(value ^ value >> 16)
        }
        return stride(from: 0, to: words.count, by: 2).map { UInt64(words[$0]) | UInt64(words[$0 + 1]) << 32 }
    }
}
