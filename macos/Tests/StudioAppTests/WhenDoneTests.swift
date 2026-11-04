import Foundation
import Synchronization
import Testing
@testable import StudioApp
import StudioCore

final class FakePower: PowerActions {
    let done = Mutex<[WhenDone]>([])

    func perform(_ action: WhenDone) -> Bool {
        done.withLock { $0.append(action) }
        return true
    }
}

/// "When done": after the queue ran out by itself the Mac sleeps or shuts down – after a countdown that can be
/// cancelled or cut short, once (gui/main_window._queue_done and dialogs.CountdownDialog).
@Suite(.serialized) struct WhenDoneTests {
    static let texts = try! Texts(directory: AppModelTests.repo.appending(path: "clipasso_studio/resources/i18n"),
                                  language: "de")

    @Test func countsDownThenActs() async throws {
        let power = FakePower()
        let countdown = WhenDoneCountdown(action: .sleep, seconds: 3, tick: .milliseconds(20), power: power)
        #expect(countdown.text(Self.texts) == "Der Mac geht in 3 s in den Ruhezustand.")
        countdown.start()
        // (only a guard against a hang: the countdown ticks on the main actor, which the tests running alongside
        // share – a deadline near a stall of theirs ended the wait before the last tick)
        let deadline = ContinuousClock.now + .seconds(60)
        while !countdown.finished, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        #expect(countdown.left == 0 && countdown.seconds == 3 && power.done.withLock { $0 } == [.sleep])
        countdown.now()  // (once only)
        #expect(power.done.withLock { $0 } == [.sleep])
    }

    @Test func cancelledNothingHappens() async throws {
        let power = FakePower()
        let countdown = WhenDoneCountdown(action: .shutdown, seconds: 2, tick: .milliseconds(20), power: power)
        countdown.start()
        countdown.cancel()
        try await Task.sleep(for: .milliseconds(120))
        #expect(power.done.withLock { $0 }.isEmpty && countdown.finished)
    }

    @Test func nowCutsItShort() {
        let power = FakePower()
        let countdown = WhenDoneCountdown(action: .shutdown, seconds: 60, tick: .seconds(1), power: power)
        countdown.start()
        countdown.now()
        #expect(power.done.withLock { $0 } == [.shutdown])
    }

    /// The app starts the countdown when the queue reports it ran out with an action chosen – once: the choice goes
    /// back to "nothing".
    @Test func theQueueRunningOutStartsIt() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let power = FakePower()
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "en"), power: power,
                                 whenDoneTiming: (seconds: 2, tick: .milliseconds(20)))
        await model.startEngine()
        await model.queuePage?.setWhenDone(.sleep)
        model.studio.image = URL(filePath: "/Bilder/Kamel.png")
        await model.startSketch()
        let deadline = ContinuousClock.now + .seconds(30)
        while power.done.withLock({ $0 }).isEmpty, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(power.done.withLock { $0 } == [.sleep])
        #expect(model.queuePage?.whenDone == .nothing)  // once
        await model.stopEngine()
    }
}
