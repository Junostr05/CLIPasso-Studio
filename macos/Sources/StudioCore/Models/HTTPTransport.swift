import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// An HTTP answer whose body arrives piece by piece.
public struct HTTPResponse: Sendable {
    public let status: Int
    /// Content-Length (nil when the server does not say)
    public let length: Int64?
    public let contentType: String?
    public let body: AsyncThrowingStream<Data, any Error>

    public init(status: Int, length: Int64?, contentType: String?, body: AsyncThrowingStream<Data, any Error>) {
        self.status = status
        self.length = length
        self.contentType = contentType
        self.body = body
    }
}

/// How the downloader fetches: a GET from `offset` on (a range request when it is not 0).
public protocol HTTPTransport: Sendable {
    func open(_ url: URL, offset: Int64) async throws -> HTTPResponse
}

/// HTTP with URLSession, streamed through its delegate (also on Linux, where URLSession has no async bytes).
public struct URLSessionTransport: HTTPTransport {
    public init() {}

    public func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
        var request = URLRequest(url: url, timeoutInterval: 60)
        request.setValue("CLIPassoStudio", forHTTPHeaderField: "User-Agent")
        if offset > 0 { request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
        let streamer = Streamer()
        let session = URLSession(configuration: .ephemeral, delegate: streamer, delegateQueue: nil)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                streamer.begin(continuation, session: session, task: session.dataTask(with: request))
            }
        } onCancel: {
            session.invalidateAndCancel()
        }
    }
}

/// The delegate of one request: the answer when its header comes, then its body into a stream.
private final class Streamer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var answer: CheckedContinuation<HTTPResponse, any Error>?
    private var body: AsyncThrowingStream<Data, any Error>.Continuation?
    private var session: URLSession?

    func begin(_ continuation: CheckedContinuation<HTTPResponse, any Error>, session: URLSession, task: URLSessionDataTask) {
        lock.withLock {
            answer = continuation
            self.session = session
        }
        task.resume()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void)
    {
        let http = response as? HTTPURLResponse
        let (stream, sink) = AsyncThrowingStream<Data, any Error>.makeStream()
        let continuation = lock.withLock {
            body = sink
            defer { answer = nil }
            return answer
        }
        let length = response.expectedContentLength
        continuation?.resume(returning: HTTPResponse(status: http?.statusCode ?? 0, length: length >= 0 ? length : nil,
                                                     contentType: http?.value(forHTTPHeaderField: "Content-Type"),
                                                     body: stream))
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        _ = lock.withLock { body }?.yield(data)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
        let (continuation, sink) = lock.withLock {
            defer {
                answer = nil
                body = nil
            }
            return (answer, body)
        }
        if let error {
            continuation?.resume(throwing: error)
            sink?.finish(throwing: error)
        } else {
            sink?.finish()
        }
        session.finishTasksAndInvalidate()
    }
}
