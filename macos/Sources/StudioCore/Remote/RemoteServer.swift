#if canImport(Network)
    import Foundation
    @preconcurrency import Network
    import Synchronization

    /// The phone page's web server (remote.RemoteServer) on Network.framework: one request per connection, answered by
    /// the router and closed – an event stream stays open, "changed" when a page should ask again, "ping" on a quiet
    /// stream, until the phone goes away or the server stops.
    public final class RemoteServer: @unchecked Sendable {  // (the listener's state lives on its queue)
        public let router: RemoteRouter
        /// seconds until a quiet stream gets a sign of life (EVENT_PING)
        let ping: Double
        private let listener: NWListener
        private let queue = DispatchQueue(label: "remote")
        private let open = Mutex<[ObjectIdentifier: NWConnection]>([:])

        public struct StartError: Error, CustomStringConvertible {
            public let description: String
        }

        /// The start waiting for the listener (answered once).
        private final class Waiting: Sendable {
            let slot = Mutex<CheckedContinuation<Int, any Error>?>(nil)
        }

        /// A server on `port` (0: any free one), on every address – or only on `host` ("127.0.0.1" in tests).
        public init(router: RemoteRouter, port: Int, host: String? = nil, ping: Double = RemoteAccess.eventPing)
            throws
        {
            self.router = router
            self.ping = ping
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            let nwPort = NWEndpoint.Port(rawValue: UInt16(clamping: port)) ?? .any
            if let host {
                parameters.requiredLocalEndpoint = .hostPort(host: NWEndpoint.Host(host), port: nwPort)
                listener = try NWListener(using: parameters)
            } else {
                listener = try NWListener(using: parameters, on: nwPort)
            }
        }

        /// Starts listening; the port it listens on (or why it cannot – a port in use).
        public func start() async throws -> Int {
            listener.newConnectionHandler = { [weak self] connection in self?.accept(connection) }
            let waiting = Waiting()
            return try await withCheckedThrowingContinuation { (done: CheckedContinuation<Int, any Error>) in
                waiting.slot.withLock { $0 = done }
                listener.stateUpdateHandler = { [listener] state in
                    switch state {
                    case .ready:
                        waiting.slot.withLock { $0.take() }?.resume(returning: Int(listener.port?.rawValue ?? 0))
                    case .failed(let error), .waiting(let error):
                        waiting.slot.withLock { $0.take() }?.resume(throwing: StartError(description: "\(error)"))
                        listener.cancel()
                    default:
                        break
                    }
                }
                listener.start(queue: queue)
            }
        }

        /// Stops: the open event streams end, the connections close.
        public func stop() async {
            listener.cancel()
            await router.events.endStreams()
            let all = open.withLock { all in
                defer { all = [:] }
                return Array(all.values)
            }
            for connection in all { connection.cancel() }
        }

        private func accept(_ connection: NWConnection) {
            let key = ObjectIdentifier(connection)
            open.withLock { $0[key] = connection }
            connection.start(queue: queue)
            Task { [weak self] in
                await self?.serve(connection)
                connection.cancel()
                _ = self?.open.withLock { $0.removeValue(forKey: key) }
            }
        }

        // MARK: - one connection

        private func serve(_ connection: NWConnection) async {
            var buffer = Data()
            var headEnd: Range<Data.Index>?
            while headEnd == nil {
                guard let chunk = await Self.receive(connection) else { return }
                buffer += chunk
                headEnd = buffer.range(of: Data("\r\n\r\n".utf8))
                if headEnd == nil, buffer.count > 64 * 1024 {
                    _ = await Self.send(connection, RemoteHTTP.head(status: 431, headers: [("Content-Length", "0")]))
                    return
                }
            }
            guard let end = headEnd, let head = RemoteHTTP.parseHead(buffer[..<end.lowerBound]) else { return }
            var request = RemoteRequest(method: head.method, target: head.target, headers: head.headers,
                                        client: Self.address(connection))
            let limit = router.bodyLimit(method: request.method, path: request.path)
            if limit > 0, request.length > 0, request.length <= limit {  // (else the router answers without it)
                var body = Data(buffer[end.upperBound...])
                while body.count < request.length {
                    guard let chunk = await Self.receive(connection) else { return }
                    body += chunk
                }
                request.body = body.prefix(request.length)
            }
            let reply = await router.respond(request)
            let headOnly = request.method == "HEAD"
            switch reply {
            case .full(let status, let headers, let body):
                let head = RemoteHTTP.head(status: status, headers: headers)
                _ = await Self.send(connection, head + (headOnly ? Data() : body))
            case .file(let headers, let url, _):
                guard await Self.send(connection, RemoteHTTP.head(status: 200, headers: headers)), !headOnly,
                      let file = try? FileHandle(forReadingFrom: url)
                else { break }
                defer { try? file.close() }
                while let chunk = try? file.read(upToCount: 256 * 1024), !chunk.isEmpty {
                    guard await Self.send(connection, chunk) else { break }
                }
            case .events:
                await events(connection)
            }
            await Self.finish(connection)
        }

        /// Server-sent events: "changed" whenever the page should ask for the studio again, "ping" on a quiet stream.
        private func events(_ connection: NWConnection) async {
            let events = router.events
            let me = await events.listen()
            defer { Task { await events.unlisten(me) } }
            let headers = [("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                           ("X-Accel-Buffering", "no")]
            var rev = await events.revision
            guard await Self.send(connection, RemoteHTTP.head(status: 200, headers: headers)
                + Data("retry: 3000\nevent: changed\ndata: \(rev)\n\n".utf8))
            else { return }
            while let new = await events.waitChange(me, since: rev, timeout: ping) {
                let text = new == rev ? "event: ping\ndata: 0\n\n" : "event: changed\ndata: \(new)\n\n"
                rev = new
                guard await Self.send(connection, Data(text.utf8)) else { return }  // (the phone went away)
            }
        }

        // MARK: - Network.framework, as async

        static func receive(_ connection: NWConnection) async -> Data? {
            await withCheckedContinuation { done in
                connection.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { data, _, _, error in
                    done.resume(returning: error == nil && data?.isEmpty == false ? data : nil)
                }
            }
        }

        static func send(_ connection: NWConnection, _ data: Data) async -> Bool {
            await withCheckedContinuation { done in
                connection.send(content: data, completion: .contentProcessed { error in
                    done.resume(returning: error == nil)
                })
            }
        }

        /// The end of the answer (the connection is closed after it).
        static func finish(_ connection: NWConnection) async {
            await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
                connection.send(content: nil, contentContext: .finalMessage, isComplete: true,
                                completion: .contentProcessed { _ in done.resume() })
            }
        }

        /// The client's address as text ("192.168.1.20", "fe80::1%en0").
        static func address(_ connection: NWConnection) -> String {
            guard case .hostPort(let host, _) = connection.endpoint else { return "" }
            switch host {
            case .ipv4(let a): return "\(a)"
            case .ipv6(let a): return "\(a)"
            case .name(let name, _): return name
            @unknown default: return ""
            }
        }
    }
#endif
