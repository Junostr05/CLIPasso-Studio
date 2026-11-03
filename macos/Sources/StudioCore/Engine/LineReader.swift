import Foundation

/// Splits a stream of bytes into lines (`\n`, a `\r` before it dropped), however long a line is.
struct LineReader {
    private var buffer: [UInt8] = []
    private var scanned = 0  // bytes of the buffer known to hold no new line

    mutating func append(_ data: Data) -> [Data] {
        buffer.append(contentsOf: data)
        var lines: [Data] = []
        var start = 0
        var from = scanned
        while let nl = buffer[from...].firstIndex(of: 0x0A) {
            var end = nl
            if end > start, buffer[end - 1] == 0x0D { end -= 1 }
            lines.append(Data(buffer[start..<end]))
            start = nl + 1
            from = start
        }
        if start > 0 { buffer.removeFirst(start) }
        scanned = buffer.count
        return lines
    }
}

/// The last lines the engine wrote to stderr, for the diagnosis – a line that may hold a secret is left out.
struct LogTail {
    static let secrets = ["telegram_token", "remote_token", "remote_pin"]
    let capacity: Int
    private(set) var lines: [String] = []
    private var partial = ""

    init(capacity: Int) {
        self.capacity = capacity
    }

    mutating func append(_ data: Data) {
        let text = partial + String(decoding: data, as: UTF8.self)
        var parts = text.components(separatedBy: "\n")
        partial = parts.removeLast()
        for line in parts {
            let clean = line.hasSuffix("\r") ? String(line.dropLast()) : line
            let hidden = Self.secrets.contains { clean.localizedCaseInsensitiveContains($0) }
            lines.append(hidden ? "[a line that may hold a secret was left out]" : clean)
        }
        if lines.count > capacity { lines.removeFirst(lines.count - capacity) }
    }
}
