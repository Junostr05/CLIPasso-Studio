import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// What the app told the Mac.
final class RecordedSignals: AppSignals {
    var awake: [Bool] = []
    var progress: [Double?] = []
    var notes: [String] = []
    var isActive = false

    func keepAwake(_ on: Bool) {
        if awake.last != on { awake.append(on) }
    }

    func dockProgress(_ fraction: Double?) { progress.append(fraction) }

    func notify(title: String, body: String) { notes.append("\(title): \(body)") }
}

/// While jobs run (controller._keep_awake, main_window's taskbar and _on_job_finished): no sleep while one runs,
/// its progress on the Dock icon, a notification when one ends with the window in the background – each as the
/// settings say.
@Suite(.serialized) struct BehaviourTests {
    static func model(_ more: JSONObject = [:]) throws -> (AppModel, RecordedSignals) {
        let signals = RecordedSignals()
        let model = try AppModel(resources: AppModelTests.resources(engine: nil),
                                 store: AppModelTests.store(language: "de", more), signals: signals)
        return (model, signals)
    }

    static func job(_ name: String, _ status: QueuedJob.Status, progress: Double = 0, message: String = "")
        -> QueuedJob
    {
        var job = QueuedJob(id: ids[name]!, target: URL(filePath: "/Bilder/\(name)"), settings: ["method": "clipasso"])
        job.status = status
        job.seeds = [0]
        job.seedProgress = [0: progress]
        job.message = message
        return job
    }

    static let ids = ["Kamel.png": UUID(), "Zebra.png": UUID()]

    static func snapshot(_ jobs: [QueuedJob]) -> QueueSnapshot {
        QueueSnapshot(jobs: jobs, finished: nil, autoStart: true)
    }

    @Test func whileAJobRuns() throws {
        let (model, signals) = try Self.model()
        #expect(model.isOn("keep_awake") && model.isOn("notify"))  // (on unless turned off)
        model.apply(Self.snapshot([Self.job("Kamel.png", .running, progress: 0.25), Self.job("Zebra.png", .queued)]))
        #expect(signals.awake == [true] && signals.progress.last == 0.25)
        model.apply(Self.snapshot([Self.job("Kamel.png", .done, progress: 1),
                                   Self.job("Zebra.png", .failed, message: "RuntimeError: made up")]))
        #expect(signals.awake == [true, false] && signals.progress.last == .some(nil))
        // (Zebra's run was skipped between the two snapshots: it ended all the same)
        #expect(signals.notes == ["Skizze fertig: „Kamel.png“ ist fertig gezeichnet.",
                                  "Auftrag beendet: RuntimeError: made up"])
        model.apply(Self.snapshot([Self.job("Kamel.png", .done, progress: 1)]))
        #expect(signals.notes.count == 2)  // (once)
    }

    @Test func asTheSettingsSay() throws {
        let (model, signals) = try Self.model(["keep_awake": false, "notify": false])
        model.apply(Self.snapshot([Self.job("Kamel.png", .running, progress: 0.5)]))
        model.apply(Self.snapshot([Self.job("Kamel.png", .done, progress: 1)]))
        #expect(!signals.awake.contains(true) && signals.notes.isEmpty)
        model.setOn("notify", true)
        signals.isActive = true  // the window in front: it shows the end itself
        model.apply(Self.snapshot([Self.job("Kamel.png", .running)]))
        model.setOn("keep_awake", true)
        #expect(signals.awake.last == true && model.store.load()["keep_awake"] == true)
        model.apply(Self.snapshot([Self.job("Kamel.png", .done, progress: 1)]))
        #expect(signals.notes.isEmpty && signals.awake.last == false)
    }
}
