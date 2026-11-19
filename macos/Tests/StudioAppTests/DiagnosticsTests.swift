import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// The diagnostics: every part there – and never a secret, neither from the settings nor from the engine's log.
@Suite(.serialized) struct DiagnosticsTests {
    @Test func everythingButSecrets() async throws {
        let store = try AppModelTests.store(language: "de", ["telegram_token": "GEHEIM", "remote_pin": "424242",
                                                             "canvas_style": "charcoal"])
        let model = try AppModel(resources: AppModelTests.resources(engine: SelfTestTests.fake(["stderr_secret"])),
                                 store: store)
        await model.startEngine()
        try await Task.sleep(for: .milliseconds(300))  // (its stderr read)
        let text = await model.diagnostics()
        for part in ["[App]", "[System]", "[Engine]", "[Folders]", "[Models]", "[Engine log, last 50 lines]"] {
            #expect(text.contains(part), "\(part)")
        }
        #expect(text.contains("language='de'") && text.contains("canvas_style='charcoal'"))
        #expect(text.contains("Output: \(model.settings.outputDir.path)"))
        #expect(!text.contains("GEHEIM") && !text.contains("424242") && !text.contains("SECRET123"))
        #expect(AppModel.diagnosticsFileName().hasPrefix("clipasso-studio-diagnostics-"))
        // the report: the home folder shortened
        let body = ProblemReport.body("Absturz", diagnostics: "Data: \(NSHomeDirectory())/Library/x")
        #expect(body.contains("Data: ~/Library/x") && !body.contains(NSHomeDirectory() + "/"))
        await model.stopEngine()
    }
}
