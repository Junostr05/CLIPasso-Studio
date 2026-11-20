import Foundation
import Observation
import StudioCore

/// What the Mac does when the queue ran out (gui/power.py on Windows): sleep or shut down.
public protocol PowerActions: Sendable {
    /// false when it could not be done
    func perform(_ action: WhenDone) -> Bool
}

/// Sleep with `pmset sleepnow`; shut down through System Events (macOS asks once whether the app may).
public struct MacPower: PowerActions {
    public init() {}

    public func perform(_ action: WhenDone) -> Bool {
        let (tool, arguments): (String, [String])
        switch action {
        case .nothing: return false
        case .sleep: (tool, arguments) = ("/usr/bin/pmset", ["sleepnow"])
        case .shutdown: (tool, arguments) = ("/usr/bin/osascript", ["-e", "tell application \"System Events\" to shut down"])
        }
        let process = Process()
        process.executableURL = URL(filePath: tool)
        process.arguments = arguments
        do {
            try process.run()
            return true
        } catch {
            return false
        }
    }
}

/// The countdown before the action (dialogs.CountdownDialog: 60 s, *Sleep now* / *Shut down now*, Cancel).
@Observable
public final class WhenDoneCountdown {
    public let action: WhenDone
    /// how long the countdown is in all
    public let seconds: Int
    public private(set) var left: Int
    /// acted or cancelled – it never acts again
    public private(set) var finished = false
    @ObservationIgnored private let tick: Duration
    @ObservationIgnored private let power: any PowerActions
    @ObservationIgnored private var task: Task<Void, Never>?

    public init(action: WhenDone, seconds: Int = 60, tick: Duration = .seconds(1),
                power: any PowerActions = MacPower())
    {
        self.action = action
        self.seconds = seconds
        left = seconds
        self.tick = tick
        self.power = power
    }

    public func start() {
        guard task == nil, !finished else { return }
        task = Task { [weak self] in
            while let self, self.left > 0 {
                try? await Task.sleep(for: self.tick)
                guard !Task.isCancelled, !self.finished else { return }
                self.left -= 1
            }
            self?.now()
        }
    }

    /// *Sleep now* / *Shut down now* – or the end of the countdown.
    public func now() {
        guard !finished else { return }
        finished = true
        task?.cancel()
        _ = power.perform(action)
    }

    public func cancel() {
        finished = true
        task?.cancel()
    }

    public func text(_ texts: Texts) -> String {
        texts.tr("ui.mac.queue.done_text_\(action.rawValue)", ["s": "\(left)"])
    }
}
