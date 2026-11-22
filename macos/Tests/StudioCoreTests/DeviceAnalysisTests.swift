import Foundation
import Testing
@testable import StudioCore

/// What a job computed where (engine/device_analysis.py): the workers' files in analysis/ added up – the parts in
/// their order with their devices, the rest of the steps and the time outside them, per iteration, the operations
/// the CPU computed for the Apple GPU, the memory.
@Suite struct DeviceAnalysisTests {
    static func worker(_ n: Int, seconds: Double, optimizing: Double, iterations: Int, draw: Double, clip: Double,
                       finished: Bool = true, fallbacks: [String] = []) -> String
    {
        """
        {"format": 1, "worker": \(n), "method": "clipasso", "device": "mps", "draw_device": "cpu", "linear": "native",
         "torch": "2.11.0", "threads": 6, "started": "2026-11-22T01:00:0\(n)+01:00", "updated": "2026-11-22T01:05:0\(n)+01:00",
         "finished": \(finished), "seconds": \(seconds), "optimizing_seconds": \(optimizing), "iterations": \(iterations),
         "parts": [{"key": "draw", "seconds": \(draw), "calls": 10, "devices": ["cpu"]},
                   {"key": "clip", "seconds": \(clip), "calls": 20, "devices": ["mps"]},
                   {"key": "backward", "seconds": 1.0, "calls": 10, "devices": ["cpu", "mps"]},
                   {"key": "model", "seconds": 0.0, "calls": 0, "devices": []}],
         "fallbacks": \(fallbacks.map { "\"\($0)\"" }), "memory": {"rss_peak": \(1_000_000 * (n + 1)), "mps_driver": 5000}}
        """
    }

    @Test func theWorkersAddedUp() throws {
        let job = FileManager.default.temporaryDirectory.appending(path: "analysis-\(UUID().uuidString)")
        let folder = job.appending(path: "analysis")
        #expect(DeviceAnalysis.read(jobDir: job) == nil)  // (a job of an older engine: none)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try Data(Self.worker(0, seconds: 10, optimizing: 8, iterations: 40, draw: 0.5, clip: 4).utf8)
            .write(to: folder.appending(path: "worker-0.json"))
        try Data(Self.worker(1, seconds: 12, optimizing: 9, iterations: 50, draw: 0.7, clip: 5, finished: false,
                             fallbacks: ["aten::x"]).utf8).write(to: folder.appending(path: "worker-1.json"))
        try Data("not json".utf8).write(to: folder.appending(path: "worker-2.json.tmp"))  // (being written: left out)

        let a = try #require(DeviceAnalysis.read(jobDir: job))
        #expect(a.workers == 2 && a.method == "clipasso" && a.device == "mps" && a.drawDevice == "cpu")
        #expect(a.seconds == 22 && a.optimizing == 17 && a.iterations == 90 && !a.finished)
        #expect(a.parts.map(\.key) == ["draw", "clip", "backward", "model"])
        #expect(a.parts[0].seconds == 1.2 && a.parts[0].calls == 20 && a.parts[0].devices == ["cpu"])
        #expect(a.parts[2].devices == ["cpu", "mps"])
        #expect(abs(a.measured - (1.2 + 9 + 2)) < 1e-9 && abs(a.restInSteps - (17 - 12.2)) < 1e-9)
        #expect(abs(a.outsideSteps - (22 - 17)) < 1e-9 && abs((a.perIteration ?? 0) - 17.0 / 90) < 1e-9)
        #expect(a.fallbacks == ["aten::x"] && a.peakMemory == 2_000_000 && a.gpuMemory == 5000)
        #expect(a.started == "2026-11-22T01:00:00+01:00" && a.updated == "2026-11-22T01:05:01+01:00")
        let json = a.json
        #expect(json["cpu_fallbacks"] == ["aten::x"] && json["workers"] == 2 && json["parts"]?.arrayValue?.count == 4)
    }
}
