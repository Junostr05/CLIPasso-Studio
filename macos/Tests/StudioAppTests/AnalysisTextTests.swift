import Foundation
import Testing
@testable import StudioApp
@testable import StudioCore

/// The Analysis page as text (its Copy button): the Mac, the engine, where "Automatic" computes and why, and the
/// job's parts with their devices – in the app's language, without a placeholder left.
@Suite(.serialized) struct AnalysisTextTests {
    @Test func everythingOnThePageAsText() throws {
        let model = try AppModel(resources: AppModelTests.resources(engine: nil), store: AppModelTests.store(language: "de"))
        var text = model.analysisText()
        #expect(text.hasPrefix("CLIPasso Studio – Analyse – "))
        #expect(text.contains("[Dieser Mac]") && text.contains("CPU-Kerne: ") && text.contains("Die Engine startet noch."))
        #expect(text.contains("Noch keine Messung"))

        model.analysis.facts = ["torch": "2.11.0", "mps": true, "engine": "4.2.4", "build": "ae61e3e 2026-11-22T12:00Z",
                                "linear": "native", "draw_on_mps": "cpu", "threads": 6,
                                "mps_auto": ["clipasso", "controlsketch", "scenesketch"]]
        var job = DeviceAnalysis()
        job.method = "clipasso"
        job.device = "mps"
        job.finished = true
        job.updated = "2026-11-22T12:05:00+01:00"
        job.seconds = 20
        job.optimizing = 16
        job.iterations = 100
        job.parts = [.init(key: "draw", seconds: 1, calls: 100, devices: ["cpu"]),
                     .init(key: "clip", seconds: 8, calls: 200, devices: ["mps"]),
                     .init(key: "backward", seconds: 5, calls: 100, devices: ["cpu", "mps"]),
                     .init(key: "model", seconds: 0, calls: 0, devices: [])]
        job.peakMemory = 1_700_000_000
        model.analysis.job = job
        model.analysis.jobDir = URL(filePath: "/tmp/Skizzen/camel_20261122-120000")
        text = model.analysisText()
        #expect(text.contains("Version und Build: 4.2.4 · ae61e3e 2026-11-22T12:00Z"))
        #expect(text.contains("Lineare Schicht auf der GPU: rechnet richtig"))
        #expect(text.contains("Striche für die GPU gezeichnet auf: CPU"))
        #expect(text.contains("CLIPasso: Apple-GPU – Standard: auf der GPU schneller gemessen"))
        #expect(text.contains("SwiftSketch: CPU – CPU, bis der Hardwaretest misst"))
        #expect(text.contains("[Auftrag · CLIPasso · camel_20261122-120000] fertig"))
        #expect(text.contains("Gerät des Auftrags: Apple-GPU") && text.contains("Iterationen: 100"))
        #expect(text.contains("Striche zeichnen: CPU · 5 % · 1,00 s"))
        #expect(text.contains("Rückwärts (Gradienten): CPU + Apple-GPU · 25 % · 5,00 s"))
        #expect(!text.contains("Modell der Methode"))  // (not used by the method: left out, as on the page)
        #expect(text.contains("Übriges in den Schritten: 10 % · 2,00 s"))
        #expect(text.contains("Von der CPU statt der GPU gerechnet: nichts") && text.contains("1,7 GB"))
        #expect(!text.contains("{") && !text.contains("ui.mac."))
    }
}
