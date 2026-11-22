import Foundation

/// An error reading or writing a ZIP file.
public struct ZipError: Error, CustomStringConvertible, Sendable {
    public let description: String
}

/// A ZIP file written entry by entry to the disk (Python's zipfile with allowZip64): files of any size – an entry,
/// an offset or a count beyond the classic limits gets its ZIP64 fields –, deflated where asked and small enough to
/// pack in memory, stored otherwise; names in UTF-8.
public final class ZipFileWriter {
    /// larger entries are stored, not deflated (they are packed in memory)
    public static let deflateLimit = 64 << 20
    private let handle: FileHandle
    private var offset: UInt64 = 0
    private var directory = Data()
    private var count = 0
    /// sizes and offsets from here on get ZIP64 fields (0xFFFFFFFF; lower only to test them)
    private let limit: UInt64

    public init(_ url: URL, zip64From limit: UInt64 = 0xFFFF_FFFF) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
            throw ZipError(description: "cannot write \(url.path)")
        }
        handle = try FileHandle(forWritingTo: url)
        self.limit = limit
    }

    /// A file of the disk, deflated unless `store` (or too large) – read twice when stored (its CRC, then its
    /// bytes), never whole in memory then.
    public func add(file: URL, name: String, store: Bool) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        let size = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
        let date = attributes[.modificationDate] as? Date ?? Date()
        if !store, size <= UInt64(Self.deflateLimit) {
            try add(data: Data(contentsOf: file), name: name, store: false, date: date)
            return
        }
        let reader = try FileHandle(forReadingFrom: file)
        defer { try? reader.close() }
        var crc: UInt32 = 0xFFFF_FFFF
        var total: UInt64 = 0
        while let chunk = try reader.read(upToCount: 1 << 20), !chunk.isEmpty {
            crc = ZipWriter.update(crc, chunk)
            total += UInt64(chunk.count)
        }
        try reader.seek(toOffset: 0)
        try header(name: name, method: 0, crc: crc ^ 0xFFFF_FFFF, packed: total, size: total, date: date)
        var left = total
        while left > 0, let chunk = try reader.read(upToCount: Int(min(left, 1 << 20))), !chunk.isEmpty {
            try write(chunk)
            left -= UInt64(chunk.count)
        }
        if left > 0 { throw ZipError(description: "\(file.path) became shorter while it was packed") }
    }

    /// Bytes of memory (a JSON text …), deflated unless `store`.
    public func add(data: Data, name: String, store: Bool = false, date: Date = Date()) throws {
        let crc = ZipWriter.crc32(data)
        let packed = store ? nil : ZipWriter.deflated(data).flatMap { $0.count < data.count ? $0 : nil }
        try header(name: name, method: packed == nil ? 0 : 8, crc: crc, packed: UInt64(packed?.count ?? data.count),
                       size: UInt64(data.count), date: date)
        try write(packed ?? data)
    }

    /// The local header (with ZIP64 sizes when they need it) and the entry's central record, kept for the end.
    private func header(name: String, method: Int, crc: UInt32, packed: UInt64, size: UInt64, date: Date) throws {
        let start = offset
        let nameData = Data(name.utf8)
        let flags = name.allSatisfy(\.isASCII) ? 0 : 0x800
        let (dosTime, dosDate) = Self.dos(date)
        let bigSizes = size >= limit || packed >= limit
        let bigOffset = start >= limit
        let version = bigSizes || bigOffset ? 45 : 20

        var local = Data()
        Self.le32(0x0403_4B50, &local)
        Self.le16(version, &local)
        Self.le16(flags, &local)
        Self.le16(method, &local)
        Self.le16(dosTime, &local)
        Self.le16(dosDate, &local)
        Self.le32(crc, &local)
        var localExtra = Data()
        if bigSizes {
            Self.le32(0xFFFF_FFFF, &local)
            Self.le32(0xFFFF_FFFF, &local)
            Self.le16(1, &localExtra)
            Self.le16(16, &localExtra)
            Self.le64(size, &localExtra)
            Self.le64(packed, &localExtra)
        } else {
            Self.le32(UInt32(packed), &local)
            Self.le32(UInt32(size), &local)
        }
        Self.le16(nameData.count, &local)
        Self.le16(localExtra.count, &local)
        local.append(nameData)
        local.append(localExtra)
        try write(local)

        var extra = Data()
        var fields = Data()
        if bigSizes {
            Self.le64(size, &fields)
            Self.le64(packed, &fields)
        }
        if bigOffset { Self.le64(start, &fields) }
        if !fields.isEmpty {
            Self.le16(1, &extra)
            Self.le16(fields.count, &extra)
            extra.append(fields)
        }
        Self.le32(0x0201_4B50, &directory)
        Self.le16(3 << 8 | version, &directory)  // (made by: Unix, for the file mode below)
        Self.le16(version, &directory)
        Self.le16(flags, &directory)
        Self.le16(method, &directory)
        Self.le16(dosTime, &directory)
        Self.le16(dosDate, &directory)
        Self.le32(crc, &directory)
        Self.le32(bigSizes ? 0xFFFF_FFFF : UInt32(packed), &directory)
        Self.le32(bigSizes ? 0xFFFF_FFFF : UInt32(size), &directory)
        Self.le16(nameData.count, &directory)
        Self.le16(extra.count, &directory)
        Self.le16(0, &directory)  // comment
        Self.le16(0, &directory)  // disk
        Self.le16(0, &directory)  // internal attributes
        Self.le32(0o100644 << 16, &directory)  // a file, rw-r--r--
        Self.le32(bigOffset ? 0xFFFF_FFFF : UInt32(start), &directory)
        directory.append(nameData)
        directory.append(extra)
        count += 1
    }

    /// The central directory and its end (with the ZIP64 end when the archive needs it); the file is closed.
    public func finish() throws {
        let start = offset
        try write(directory)
        let size = UInt64(directory.count)
        let big = count >= min(0xFFFF, Int(clamping: limit)) || start >= limit || size >= limit
        var end = Data()
        if big {
            let zip64End = offset
            Self.le32(0x0606_4B50, &end)
            Self.le64(44, &end)
            Self.le16(45, &end)
            Self.le16(45, &end)
            Self.le32(0, &end)
            Self.le32(0, &end)
            Self.le64(UInt64(count), &end)
            Self.le64(UInt64(count), &end)
            Self.le64(size, &end)
            Self.le64(start, &end)
            Self.le32(0x0706_4B50, &end)
            Self.le32(0, &end)
            Self.le64(zip64End, &end)
            Self.le32(1, &end)
        }
        Self.le32(0x0605_4B50, &end)
        Self.le16(0, &end)
        Self.le16(0, &end)
        Self.le16(big ? 0xFFFF : count, &end)
        Self.le16(big ? 0xFFFF : count, &end)
        Self.le32(big ? 0xFFFF_FFFF : UInt32(size), &end)
        Self.le32(big ? 0xFFFF_FFFF : UInt32(start), &end)
        Self.le16(0, &end)
        try write(end)
        try handle.close()
    }

    /// Stops without finishing (the caller removes the file).
    public func abandon() {
        try? handle.close()
    }

    private func write(_ data: Data) throws {
        try handle.write(contentsOf: data)
        offset += UInt64(data.count)
    }

    /// The MS-DOS time and date ZIP keeps (local time, 2-second steps, from 1980).
    static func dos(_ date: Date) -> (time: Int, date: Int) {
        let c = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        let year = max(1980, min(2107, c.year ?? 1980))
        return ((c.hour ?? 0) << 11 | (c.minute ?? 0) << 5 | (c.second ?? 0) / 2,
                (year - 1980) << 9 | (c.month ?? 1) << 5 | (c.day ?? 1))
    }

    static func le16(_ v: Int, _ data: inout Data) {
        withUnsafeBytes(of: UInt16(truncatingIfNeeded: v).littleEndian) { data.append(contentsOf: $0) }
    }

    static func le32(_ v: UInt32, _ data: inout Data) {
        withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) }
    }

    static func le64(_ v: UInt64, _ data: inout Data) {
        withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) }
    }
}

/// A ZIP file read from the disk (Python's zipfile): its entries from the central directory (ZIP64 too), each one
/// read whole or copied to a file – stored or deflated, its CRC checked.
public final class ZipFileReader {
    public struct Entry: Sendable {
        public let name: String
        public let method: Int
        public let crc: UInt32
        public let packedSize: UInt64
        public let size: UInt64
        let localOffset: UInt64
        public var isDirectory: Bool { name.hasSuffix("/") }
    }

    public let entries: [Entry]
    private let handle: FileHandle

    public init(_ url: URL) throws {
        handle = try FileHandle(forReadingFrom: url)
        let length = try handle.seekToEnd()
        let tail = min(length, 65_557)
        try handle.seek(toOffset: length - tail)
        let end = try handle.read(upToCount: Int(tail)) ?? Data()
        guard let at = Self.lastIndex(of: 0x0605_4B50, in: end) else {
            throw ZipError(description: "not a ZIP file")
        }
        var count = UInt64(Self.u16(end, at + 10))
        var size = UInt64(Self.u32(end, at + 12))
        var start = UInt64(Self.u32(end, at + 16))
        if at >= 20, Self.u32(end, at - 20) == 0x0706_4B50 {  // the ZIP64 end's locator
            let zip64End = Self.u64(end, at - 20 + 8)
            try handle.seek(toOffset: zip64End)
            let record = try handle.read(upToCount: 56) ?? Data()
            guard record.count == 56, Self.u32(record, 0) == 0x0606_4B50 else {
                throw ZipError(description: "a damaged ZIP64 end")
            }
            count = Self.u64(record, 32)
            size = Self.u64(record, 40)
            start = Self.u64(record, 48)
        }
        try handle.seek(toOffset: start)
        let directory = try handle.read(upToCount: Int(size)) ?? Data()
        var entries: [Entry] = []
        var p = 0
        for _ in 0 ..< count {
            guard p + 46 <= directory.count, Self.u32(directory, p) == 0x0201_4B50 else {
                throw ZipError(description: "a damaged central directory")
            }
            let flags = Self.u16(directory, p + 8)
            let method = Self.u16(directory, p + 10)
            let crc = Self.u32(directory, p + 16)
            var packed = UInt64(Self.u32(directory, p + 20))
            var plain = UInt64(Self.u32(directory, p + 24))
            let nameLength = Self.u16(directory, p + 28), extraLength = Self.u16(directory, p + 30)
            let commentLength = Self.u16(directory, p + 32)
            var local = UInt64(Self.u32(directory, p + 42))
            let nameData = directory.subdata(in: directory.startIndex + p + 46 ..< directory.startIndex + p + 46
                + nameLength)
            let name = flags & 0x800 != 0 ? String(decoding: nameData, as: UTF8.self)
                : String(data: nameData, encoding: .isoLatin1) ?? ""  // (cp437 for the ASCII names Python writes so)
            var e = p + 46 + nameLength
            let extraEnd = e + extraLength
            while e + 4 <= extraEnd {
                let id = Self.u16(directory, e), length = Self.u16(directory, e + 2)
                if id == 1 {
                    var f = e + 4
                    if plain == 0xFFFF_FFFF { plain = Self.u64(directory, f); f += 8 }
                    if packed == 0xFFFF_FFFF { packed = Self.u64(directory, f); f += 8 }
                    if local == 0xFFFF_FFFF { local = Self.u64(directory, f) }
                }
                e += 4 + length
            }
            entries.append(Entry(name: name, method: method, crc: crc, packedSize: packed, size: plain,
                                 localOffset: local))
            p = extraEnd + commentLength
        }
        self.entries = entries
    }

    deinit {
        try? handle.close()
    }

    public func entry(_ name: String) -> Entry? { entries.first { $0.name == name } }

    /// Where an entry's bytes begin (after its local header).
    private func dataStart(_ entry: Entry) throws -> UInt64 {
        try handle.seek(toOffset: entry.localOffset)
        let local = try handle.read(upToCount: 30) ?? Data()
        guard local.count == 30, Self.u32(local, 0) == 0x0403_4B50 else {
            throw ZipError(description: "a damaged entry \(entry.name)")
        }
        return entry.localOffset + 30 + UInt64(Self.u16(local, 26)) + UInt64(Self.u16(local, 28))
    }

    /// The whole entry.
    public func data(_ entry: Entry) throws -> Data {
        try handle.seek(toOffset: try dataStart(entry))
        let packed = try handle.read(upToCount: Int(entry.packedSize)) ?? Data()
        let out: Data
        switch entry.method {
        case 0: out = packed
        case 8: out = try Self.inflate(packed, size: entry.size)
        default: throw ZipError(description: "\(entry.name): packed in a way this app does not read (\(entry.method))")
        }
        guard out.count == Int(entry.size), ZipWriter.crc32(out) == entry.crc else {
            throw ZipError(description: "\(entry.name) is damaged")
        }
        return out
    }

    /// The entry written to `url` – a stored one copied piece by piece; `tick` hears the bytes done.
    public func extract(_ entry: Entry, to url: URL, tick: (Int) throws -> Void = { _ in }) throws {
        guard entry.method == 0 else {
            try data(entry).write(to: url)
            try tick(Int(entry.size))
            return
        }
        try handle.seek(toOffset: try dataStart(entry))
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
            throw ZipError(description: "cannot write \(url.path)")
        }
        let out = try FileHandle(forWritingTo: url)
        defer { try? out.close() }
        var left = entry.size
        var crc: UInt32 = 0xFFFF_FFFF
        while left > 0 {
            guard let chunk = try handle.read(upToCount: Int(min(left, 1 << 20))), !chunk.isEmpty else {
                throw ZipError(description: "\(entry.name) is cut off")
            }
            crc = ZipWriter.update(crc, chunk)
            try out.write(contentsOf: chunk)
            left -= UInt64(chunk.count)
            try tick(chunk.count)
        }
        guard crc ^ 0xFFFF_FFFF == entry.crc else { throw ZipError(description: "\(entry.name) is damaged") }
    }

    static func inflate(_ data: Data, size: UInt64) throws -> Data {
        #if canImport(Darwin)
            if size == 0 { return Data() }
            guard let out = try? (data as NSData).decompressed(using: .zlib) as Data else {
                throw ZipError(description: "cannot unpack")
            }
            return out
        #else
            throw ZipError(description: "deflated entries are read on the Mac only")
        #endif
    }

    static func lastIndex(of signature: UInt32, in data: Data) -> Int? {
        guard data.count >= 22 else { return nil }
        for i in stride(from: data.count - 22, through: 0, by: -1) where u32(data, i) == signature {
            return i
        }
        return nil
    }

    static func u16(_ d: Data, _ i: Int) -> Int {
        Int(d[d.startIndex + i]) | Int(d[d.startIndex + i + 1]) << 8
    }

    static func u32(_ d: Data, _ i: Int) -> UInt32 {
        UInt32(u16(d, i)) | UInt32(u16(d, i + 2)) << 16
    }

    static func u64(_ d: Data, _ i: Int) -> UInt64 {
        UInt64(u32(d, i)) | UInt64(u32(d, i + 4)) << 32
    }
}
