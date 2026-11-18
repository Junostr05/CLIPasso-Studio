import Foundation
import Synchronization

#if canImport(Darwin)
    import Darwin
#elseif canImport(Glibc)
    import Glibc
#endif

/// Who may use the phone page and how (gui/remote.py): only addresses of the home network – the tailnet's when that
/// is switched on –, the access code of the QR code, the six-digit PIN for signing in without it, and the limits of
/// the server.
public enum RemoteAccess {
    public static let defaultPort = 8765
    /// MAX_UPLOAD: a picture from the phone, at most
    public static let maxUpload = 25 * 1024 * 1024
    /// MAX_JSON: a request's body, at most
    public static let maxJSON = 64 * 1024
    /// EVENT_STREAMS: open event streams at most (one per phone tab; the oldest goes)
    public static let eventStreams = 8
    /// EVENT_PING: seconds until a quiet stream gets a sign of life
    public static let eventPing = 15.0
    /// CALL_TIMEOUT: seconds the server waits for the app's answer
    public static let callTimeout = 20.0
    public static let cookie = "cs_access"
    /// COOKIE_AGE: the longest browsers keep a cookie (renewed on every visit)
    public static let cookieAge = 400 * 24 * 3600
    public static let pinDigits = 6
    /// the methods an upload may ask for
    public static let methods = ["clipasso", "swiftsketch", "controlsketch", "scenesketch"]
    /// UPLOAD_DIR: the phone's pictures, in the output folder
    public static let uploadDir = "_remote"
    public static let pageCSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
        + "font-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
    public static let svgCSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    /// FONTS: the studio's Inter, the only files under /fonts/
    public static let fonts = ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"]
    public static let fontCache = "public, max-age=604800"

    /// secrets.token_urlsafe(18): 18 random bytes, base64 for URLs without padding.
    public static func newToken() -> String {
        var generator = SystemRandomNumberGenerator()
        let bytes = (0 ..< 18).map { _ in UInt8.random(in: .min ... .max, using: &generator) }
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    /// A new PIN: six random digits.
    public static func newPin() -> String {
        var generator = SystemRandomNumberGenerator()
        let n = Int.random(in: 0 ..< 1_000_000, using: &generator)
        return String(format: "%06d", n)
    }

    public static func validPin(_ text: String) -> Bool {
        text.count == pinDigits && text.allSatisfy { $0.isASCII && $0.isNumber }
    }

    /// Two secrets alike, in a time that does not tell where they differ (hmac.compare_digest).
    public static func same(_ a: String, _ b: String) -> Bool {
        let (x, y) = (Array(a.utf8), Array(b.utf8))
        var diff = x.count ^ y.count
        for i in 0 ..< max(x.count, y.count) {
            diff |= Int((i < x.count ? x[i] : 0) ^ (i < y.count ? y[i] : 0))
        }
        return diff == 0
    }

    // MARK: - addresses

    /// allowed_client: the home network – private, link-local and loopback addresses as Python's ipaddress names
    /// them (an IPv4 address in IPv6 as itself) – and, when `tailscale`, the tailnet's 100.64.0.0/10.
    public static func allowedClient(_ ip: String, tailscale: Bool = false) -> Bool {
        let bare = String(ip.split(separator: "%", maxSplits: 1, omittingEmptySubsequences: false).first ?? "")
        if let v4 = ipv4(bare) { return allowed(v4: v4, tailscale: tailscale) }
        guard let v6 = ipv6(bare) else { return false }
        if v6[0 ..< 10].allSatisfy({ $0 == 0 }), v6[10] == 0xFF, v6[11] == 0xFF {  // (::ffff:a.b.c.d)
            return allowed(v4: Array(v6[12 ..< 16]), tailscale: tailscale)
        }
        return private6(v6)  // (loopback ::1 and link-local fe80::/10 are private, too)
    }

    static func allowed(v4: [UInt8], tailscale: Bool) -> Bool {
        if private4(v4) { return true }  // (loopback and link-local are private, too)
        return tailscale && inside(v4, network: [100, 64], bits: 10)
    }

    /// _IPv4Constants._private_networks, less its exceptions
    static let private4Networks: [([UInt8], Int)] = [
        ([0], 8), ([10], 8), ([127], 8), ([169, 254], 16), ([172, 16], 12), ([192, 0, 0], 24), ([192, 0, 0, 170], 31),
        ([192, 0, 2], 24), ([192, 168], 16), ([198, 18], 15), ([198, 51, 100], 24), ([203, 0, 113], 24), ([240], 4),
        ([255, 255, 255, 255], 32),
    ]
    static let private4Exceptions: [([UInt8], Int)] = [([192, 0, 0, 9], 32), ([192, 0, 0, 10], 32)]

    /// _IPv6Constants._private_networks, less its exceptions
    static let private6Networks: [([UInt8], Int)] = [
        (v6("::1"), 128), (v6("::"), 128), (v6("::ffff:0:0"), 96), (v6("64:ff9b:1::"), 48), (v6("100::"), 64),
        (v6("2001::"), 23), (v6("2001:db8::"), 32), (v6("2002::"), 16), (v6("3fff::"), 20), (v6("fc00::"), 7),
        (v6("fe80::"), 10),
    ]
    static let private6Exceptions: [([UInt8], Int)] = [
        (v6("2001:1::1"), 128), (v6("2001:1::2"), 128), (v6("2001:3::"), 32), (v6("2001:4:112::"), 48),
        (v6("2001:20::"), 28), (v6("2001:30::"), 28),
    ]

    static func private4(_ a: [UInt8]) -> Bool {
        private4Networks.contains { inside(a, network: $0.0, bits: $0.1) }
            && !private4Exceptions.contains { inside(a, network: $0.0, bits: $0.1) }
    }

    static func private6(_ a: [UInt8]) -> Bool {
        private6Networks.contains { inside(a, network: $0.0, bits: $0.1) }
            && !private6Exceptions.contains { inside(a, network: $0.0, bits: $0.1) }
    }

    private static func v6(_ text: String) -> [UInt8] { ipv6(text) ?? [] }

    /// Whether the first `bits` of `address` are those of `network` (its missing bytes 0).
    static func inside(_ address: [UInt8], network: [UInt8], bits: Int) -> Bool {
        for i in 0 ..< (bits + 7) / 8 {
            let mask: UInt8 = bits - i * 8 >= 8 ? 0xFF : ~(0xFF >> UInt8(bits - i * 8))
            let n = i < network.count ? network[i] : 0
            guard i < address.count, address[i] & mask == n & mask else { return false }
        }
        return true
    }

    /// IPv4Address: four decimal parts 0 … 255 of at most three ASCII digits, no leading zero.
    static func ipv4(_ text: String) -> [UInt8]? {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return nil }
        var out: [UInt8] = []
        for part in parts {
            guard !part.isEmpty, part.count <= 3, part.allSatisfy({ $0.isASCII && $0.isNumber }),
                  part.count == 1 || part.first != "0", let n = Int(part), n <= 255
            else { return nil }
            out.append(UInt8(n))
        }
        return out
    }

    /// An IPv6 address's 16 bytes (inet_pton; nil: none).
    static func ipv6(_ text: String) -> [UInt8]? {
        guard !text.isEmpty, text.allSatisfy({ $0.isASCII && !$0.isWhitespace }) else { return nil }
        var raw = in6_addr()
        guard inet_pton(AF_INET6, text, &raw) == 1 else { return nil }
        return withUnsafeBytes(of: &raw) { Array($0) }
    }
}

/// _PinGuard: the brakes on guessing the PIN – five wrong ones from an address, then it waits 30 s, doubled each
/// further round up to an hour; twenty wrong ones from all addresses within ten minutes, and nobody may try for ten
/// minutes. Times are seconds of a clock the caller gives (the server: now).
public final class PinGuard: Sendable {
    public static let tries = 5
    public static let wait = 30
    public static let waitMax = 3600
    public static let global = 20
    public static let window = 600.0

    private struct State {
        /// address → (wrong PINs, rounds, locked until)
        var perIP: [String: (wrong: Int, rounds: Int, until: Double)] = [:]
        var recent: [Double] = []
        var allLockedUntil = 0.0
    }

    private let state = Mutex(State())
    private let pin: @Sendable () -> String

    /// `pin`: the PIN as it is now.
    public init(pin: @escaping @Sendable () -> String) {
        self.pin = pin
    }

    /// Seconds before `ip` may try again.
    public func wait(_ ip: String, now: Double) -> Int {
        let until = state.withLock { max($0.allLockedUntil, $0.perIP[ip]?.until ?? 0) }
        return max(0, Int(until - now + 0.999))
    }

    /// (the right PIN, seconds to wait before the next try).
    public func check(_ ip: String, _ given: String, now: Double) -> (ok: Bool, wait: Int) {
        let waiting = wait(ip, now: now)
        if waiting > 0 { return (false, waiting) }
        if RemoteAccess.validPin(given), RemoteAccess.same(given, pin()) {
            state.withLock { _ = $0.perIP.removeValue(forKey: ip) }
            return (true, 0)
        }
        state.withLock { s in
            var entry = s.perIP[ip] ?? (0, 0, 0)
            entry.wrong += 1
            if entry.wrong >= Self.tries {
                entry.wrong = 0
                entry.rounds += 1
                entry.until = now + Double(min(Self.waitMax, Self.wait << min(entry.rounds - 1, 20)))
            }
            s.perIP[ip] = entry
            s.recent = s.recent.filter { now - $0 < Self.window } + [now]
            if s.recent.count >= Self.global {
                s.allLockedUntil = now + Self.window
                s.recent = []
            }
        }
        return (false, wait(ip, now: now))
    }
}
