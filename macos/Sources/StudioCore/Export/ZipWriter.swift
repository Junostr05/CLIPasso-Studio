import Foundation

/// A ZIP file written in memory (Python's zipfile with ZIP_DEFLATED): each entry deflated where that makes it
/// smaller (stored otherwise), its name in UTF-8.
public struct ZipWriter {
    private var body = Data()
    private var directory = Data()
    private var count = 0

    public init() {}

    /// CRC-32 (IEEE 802.3), as zip and zlib compute it.
    static let table: [UInt32] = (0 ..< 256).map { n in
        var c = UInt32(n)
        for _ in 0 ..< 8 { c = c & 1 != 0 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    public static func crc32(_ data: Data) -> UInt32 {
        var c: UInt32 = 0xFFFF_FFFF
        for byte in data { c = table[Int((c ^ UInt32(byte)) & 0xFF)] ^ (c >> 8) }
        return c ^ 0xFFFF_FFFF
    }

    static func deflated(_ data: Data) -> Data? {
        #if canImport(Darwin)
            return try? (data as NSData).compressed(using: .zlib) as Data  // (raw DEFLATE, as ZIP wants it)
        #else
            return nil
        #endif
    }

    private static func le16(_ v: Int, into data: inout Data) {
        withUnsafeBytes(of: UInt16(truncatingIfNeeded: v).littleEndian) { data.append(contentsOf: $0) }
    }

    private static func le32(_ v: UInt32, into data: inout Data) {
        withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) }
    }

    /// An entry `name` with `content`.
    public mutating func add(_ name: String, _ content: Data) {
        let packed = Self.deflated(content).flatMap { $0.count < content.count ? $0 : nil }
        let method = packed == nil ? 0 : 8
        let stored = packed ?? content
        let nameBytes = Data(name.utf8)
        // version 2.0, UTF-8 names, the method, 1980-01-01 00:00 (the files carry no dates), the sizes
        var common = Data()
        for v in [20, 0x0800, method, 0, 0x21] { Self.le16(v, into: &common) }
        Self.le32(Self.crc32(content), into: &common)
        Self.le32(UInt32(stored.count), into: &common)
        Self.le32(UInt32(content.count), into: &common)
        Self.le16(nameBytes.count, into: &common)
        Self.le16(0, into: &common)
        let offset = UInt32(body.count)
        Self.le32(0x0403_4B50, into: &body)
        body.append(common)
        body.append(nameBytes)
        body.append(stored)
        Self.le32(0x0201_4B50, into: &directory)
        Self.le16(20, into: &directory)
        directory.append(common)
        for v in [0, 0, 0] { Self.le16(v, into: &directory) }  // (comment, disk, internal attributes)
        Self.le32(0, into: &directory)
        Self.le32(offset, into: &directory)
        directory.append(nameBytes)
        count += 1
    }

    public mutating func add(_ name: String, text: String) { add(name, Data(text.utf8)) }

    /// The ZIP file: the entries, their directory and its end.
    public func finished() -> Data {
        var out = body
        out.append(directory)
        Self.le32(0x0605_4B50, into: &out)
        for v in [0, 0, count, count] { Self.le16(v, into: &out) }
        Self.le32(UInt32(directory.count), into: &out)
        Self.le32(UInt32(body.count), into: &out)
        Self.le16(0, into: &out)
        return out
    }
}
