import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// `CLIPassoStudio --self-test`: the app starts its engine as always, computes a small job and checks the sketch –
/// the CI runs it inside the built .app (here a stand-in engine "computes" by copying a finished job).
@Suite(.serialized) struct SelfTestTests {
    static let repo = AppModelTests.repo
    static let fixtures = repo.appending(path: "macos/Tests/StudioCoreTests/Fixtures")

    static func fake(_ arguments: [String]) -> EngineLaunch {
        EngineLaunch(executable: URL(filePath: "/usr/bin/env"),
                     arguments: ["python3", repo.appending(path: "macos/Tests/StudioCoreTests/Support/fake_engine.py").path]
                         + arguments,
                     environment: ["PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"])
    }

    static func output() -> URL {
        FileManager.default.temporaryDirectory.appending(path: "selftest-\(UUID().uuidString)")
    }

    @Test func commandLine() throws {
        let options = try SelfTest.Options(arguments: ["CLIPassoStudio", "--self-test", "/Bilder/Kamel.png", "/tmp/out",
                                                       "--models", "/Volumes/Modelle", "--iterations", "7"])
        #expect(options.image.path == "/Bilder/Kamel.png" && options.output.path == "/tmp/out")
        #expect(options.modelsDir?.path == "/Volumes/Modelle" && options.iterations == 7)
        let plain = try SelfTest.Options(arguments: ["CLIPassoStudio", "--self-test", "a.png", "out"])
        #expect(plain.modelsDir == nil && plain.iterations == 5)
        #expect(throws: SelfTest.UsageError.self) { try SelfTest.Options(arguments: ["CLIPassoStudio", "--self-test"]) }
        #expect(throws: SelfTest.UsageError.self) {
            try SelfTest.Options(arguments: ["x", "--self-test", "a.png", "out", "--iterations", "zero"])
        }
        #expect(SelfTest.Options.requested(in: ["CLIPassoStudio", "--self-test", "a", "b"]))
        #expect(!SelfTest.Options.requested(in: ["CLIPassoStudio", "-NSDocumentRevisionsDebugMode", "YES"]))
    }

    @Test func computesAJob() async throws {
        let out = Self.output()
        let options = try SelfTest.Options(arguments: ["x", "--self-test", "/Bilder/Kamel.png", out.path,
                                                       "--models", "/Volumes/Modelle"])
        let resources = AppModelTests.resources(engine: Self.fake(["job", Self.fixtures.appending(path: "jobs/done_clipasso").path]))
        let outcome = await SelfTest.run(options, resources: resources)
        #expect(outcome.ok, "\(outcome.lines)")
        #expect(outcome.lines.contains { $0.contains("· 2 strokes ·") })  // (the two paths of the fixture sketch)
        #expect(outcome.lines.contains { $0.contains("5 iterations") })
        // its own settings in the output folder (never the user's), with the models folder given
        let settings = SettingsStore(url: out.appending(path: "settings.json")).load()
        #expect(settings.modelsDir?.path == "/Volumes/Modelle")
    }

    @Test func aFailedJobFails() async throws {
        let options = try SelfTest.Options(arguments: ["x", "--self-test", "/Bilder/Kamel.png", Self.output().path])
        let outcome = await SelfTest.run(options, resources: AppModelTests.resources(engine: Self.fake(["job_fails"])))
        #expect(!outcome.ok)
        #expect(outcome.lines.contains { $0.contains("RuntimeError: made up") })
    }

    @Test func noEngineFails() async throws {
        let options = try SelfTest.Options(arguments: ["x", "--self-test", "/Bilder/Kamel.png", Self.output().path])
        let outcome = await SelfTest.run(options, resources: AppModelTests.resources(engine: nil))
        #expect(!outcome.ok && outcome.lines.contains { $0.contains("could not be started") })
    }
}

@Suite struct ScreenshotOptionsTests {
    @Test func commandLineAndShots() throws {
        let options = try ScreenshotOptions(arguments: ["x", "--screenshots", "/tmp/shots", "--results", "/tmp/out"])
        #expect(options.output.path == "/tmp/shots" && options.results?.path == "/tmp/out")
        let shots = options.shots(pages: ["studio", "gallery"])
        #expect(shots.count == 8)  // 2 pages × German, English × dark, light
        #expect(shots.first?.file.lastPathComponent == "studio-de-dark.png")
        #expect(Set(shots.map(\.file)).count == 8)
        #expect(throws: SelfTest.UsageError.self) { try ScreenshotOptions(arguments: ["x", "--screenshots"]) }
        #expect(ScreenshotOptions.requested(in: ["x", "--screenshots", "a"]))
        #expect(!ScreenshotOptions.requested(in: ["x"]))
    }

    @Test func itsOwnSettings() throws {
        let out = FileManager.default.temporaryDirectory.appending(path: "shots-\(UUID().uuidString)")
        let options = try ScreenshotOptions(arguments: ["x", "--screenshots", out.path, "--results", "/Volumes/R"])
        let store = try options.store()
        #expect(store.url.deletingLastPathComponent().path == out.path)
        #expect(store.load().outputDir.path == "/Volumes/R")
    }
}
