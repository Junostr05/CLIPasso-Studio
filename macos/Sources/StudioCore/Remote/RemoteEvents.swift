import Foundation

/// What the open phone pages are told (RemoteBridge's event streams): a revision counted up on every change; each page
/// listens on a stream of its own, at most eight of them (the oldest ends, e.g. that of a phone gone to sleep); when
/// the server stops, every stream ends.
public actor RemoteEvents {
    public struct Stream: Sendable, Hashable {
        let id = UUID()
    }

    public private(set) var revision = 0
    private var open: [Stream] = []
    private var waiting: [Stream: (rev: Int, done: CheckedContinuation<Int?, Never>)] = [:]
    private var timers: [Stream: Task<Void, Never>] = [:]

    public init() {}

    /// How many streams are open.
    public var streams: Int { open.count }

    /// Something a page shows has changed.
    public func changed() {
        revision += 1
        for stream in Array(waiting.keys) { finish(stream, with: revision) }
    }

    /// A new stream; with too many open, the oldest ends.
    public func listen() -> Stream {
        let me = Stream()
        open.append(me)
        while open.count > RemoteAccess.eventStreams {
            let oldest = open.removeFirst()
            finish(oldest, with: nil)
        }
        return me
    }

    public func unlisten(_ stream: Stream) {
        open.removeAll { $0 == stream }
        finish(stream, with: nil)
    }

    /// The revision once it differs from `rev` (`rev` itself after `timeout` seconds); nil: the stream ended.
    public func waitChange(_ stream: Stream, since rev: Int, timeout: Double) async -> Int? {
        guard open.contains(stream) else { return nil }
        if revision != rev { return revision }
        return await withCheckedContinuation { continuation in
            waiting[stream] = (rev, continuation)
            timers[stream] = Task { [weak self] in
                try? await Task.sleep(for: .seconds(timeout))
                guard !Task.isCancelled else { return }
                await self?.timedOut(stream)
            }
        }
    }

    /// The server stops: every stream ends.
    public func endStreams() {
        let all = open
        open = []
        for stream in all { finish(stream, with: nil) }
        for stream in Array(waiting.keys) { finish(stream, with: nil) }
    }

    private func timedOut(_ stream: Stream) {
        guard let wait = waiting[stream] else { return }
        finish(stream, with: open.contains(stream) ? wait.rev : nil)
    }

    private func finish(_ stream: Stream, with value: Int?) {
        timers.removeValue(forKey: stream)?.cancel()
        waiting.removeValue(forKey: stream)?.done.resume(returning: value)
    }
}
