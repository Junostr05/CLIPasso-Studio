import Foundation

/// How the engine is started again after a crash: after `delays[attempt - 1]` (the last one for later attempts) –
/// and not at all once `maxCrashes` crashes came within `window`.
public struct RestartPolicy: Sendable, Hashable {
    public var delays: [Duration]
    public var maxCrashes: Int
    public var window: Duration

    public init(delays: [Duration], maxCrashes: Int, window: Duration) {
        self.delays = delays.isEmpty ? [.seconds(1)] : delays
        self.maxCrashes = maxCrashes
        self.window = window
    }

    /// 1, 2, 4, 8, 16, 30 s; three crashes within two minutes: it stays down and the app says why.
    public static let standard = RestartPolicy(delays: [1, 2, 4, 8, 16, 30].map { .seconds($0) }, maxCrashes: 3,
                                               window: .seconds(120))

    public func delay(attempt: Int) -> Duration {
        delays[min(max(attempt, 1), delays.count) - 1]
    }
}
