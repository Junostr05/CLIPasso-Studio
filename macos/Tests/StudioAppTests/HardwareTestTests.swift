import Foundation
import Testing
@testable import StudioApp
@testable import StudioCore

/// The hardware test (CPU against the Apple GPU on this Mac): the rows as they come, the report kept in the settings,
/// and "auto" computing each method on the device measured better – not while a job runs; a failed test says why.
@Suite(.serialized) struct HardwareTestTests {
    @Test func measuredAndFollowed() async throws {
        let done = SelfTestTests.fixtures.appending(path: "jobs/done_clipasso")
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["job", done.path])),
                                 store: AppModelTests.store(language: "de"))
        #expect(model.autoDevices.isEmpty && model.hardwareReport == nil)
        await model.startEngine()
        let queue = try #require(model.queue)
        #expect(await queue.startSettings(["method": "clipasso", "device": "auto"])["device"] == "auto")
        let result = await model.runHardwareTest(methods: ["clipasso", "swiftsketch"], iterations: 10)
        let report = try result.get()
        #expect(model.hardware.rows.count == 4 && model.hardware.state == .idle)
        #expect(report["iterations"] == 10 && report["date"]?.stringValue?.isEmpty == false)
        #expect(model.autoDevices == ["clipasso": "mps", "swiftsketch": "cpu"])
        #expect(model.settings[AppModel.hardwareKey]?.objectValue?["recommended"] != nil)
        // "auto" follows the test; a device chosen by hand stays
        #expect(await queue.startSettings(["method": "clipasso", "device": "auto"])["device"] == "mps")
        #expect(await queue.startSettings(["method": "clipasso"])["device"] == "mps")
        #expect(await queue.startSettings(["method": "swiftsketch", "device": "auto"])["device"] == "cpu")
        #expect(await queue.startSettings(["method": "clipasso", "device": "cpu"])["device"] == "cpu")
        #expect(await queue.snapshot().autoStart)  // (the queue starts by itself again)
        // a test that fails
        if case .failure(let why) = await model.runHardwareTest(methods: ["clipasso"], iterations: 3) {
            #expect(why.description.contains("no MPS"))
            #expect(model.hardware.state == .failed("the hardware test ended (1) no MPS"))
        } else {
            Issue.record("the test did not fail")
        }
        #expect(model.autoDevices == ["clipasso": "mps", "swiftsketch": "cpu"])  // (the last good one stays)
        // measured with another engine (an older build, or one from before builds were kept): no longer followed
        #expect(model.hardwareReport?["build"] == "abc1234 2026-11-22T01:00Z" && !model.hardwareReportStale)
        for old in [JSONValue.string("0ld0ld0 2026-11-20T10:00Z"), .null] {
            _ = model.updateSettings {
                var report = $0[AppModel.hardwareKey]?.objectValue ?? [:]
                report["build"] = old
                $0[AppModel.hardwareKey] = .object(report)
            }
            #expect(model.hardwareReportStale && model.autoDevices.isEmpty)
        }
        _ = model.updateSettings {  // (measured with this engine again)
            var report = $0[AppModel.hardwareKey]?.objectValue ?? [:]
            report["build"] = "abc1234 2026-11-22T01:00Z"
            $0[AppModel.hardwareKey] = .object(report)
        }
        await model.stopEngine()
        // the next start of the engine takes the test over again
        await model.startEngine()
        #expect(await model.queue?.startSettings(["method": "clipasso", "device": "auto"])["device"] == "mps")
        await model.stopEngine()
    }
}
