import Foundation
import Testing
@testable import StudioApp
import StudioCore

/// "My presets" in the studio and from the phone: kept in settings.json, chosen (one of another method switches to
/// it; the files on this Mac stay), recognised, deleted.
@Suite(.serialized) struct UserPresetsAppTests {
    @Test func savedChosenDeleted() async throws {
        let (model, _) = try PhoneRemoteTests.model()
        func ask(_ action: String, _ data: JSONObject = [:]) async -> JSONObject? {
            PhoneRemoteTests.json(await model.phoneAnswer(action, data, payload: nil))
        }
        model.studio.set("num_iter", to: 1234)
        #expect(model.userPreset == "" && model.userPresets.isEmpty)
        #expect(model.saveUserPreset("  Mein   Kamel ") == "Mein Kamel" && model.userPreset == "Mein Kamel")
        #expect(model.saveUserPreset(" \t ") == "")
        #expect(model.store.load()[UserPresets.key]?.arrayValue?.count == 1)  // (in settings.json)

        model.studio.set("num_iter", to: 999)
        model.studio.set("path_svg", to: "/Bilder/start.svg")
        #expect(model.userPreset == "")
        #expect(model.applyUserPreset("Mein Kamel"))
        #expect(model.studio.settings["num_iter"] == 1234 && model.studio.settings["path_svg"] == "/Bilder/start.svg")
        #expect(model.userPreset == "Mein Kamel")  // (the start SVG is not part of a preset)

        model.studio.selectMethod("swiftsketch")
        var state = try #require(await ask("get_studio"))
        let name = try #require(model.schema.method("clipasso")?.name)
        #expect(state["user_preset"] == "" && state["user_presets"] == [["name": "Mein Kamel", "method": "clipasso",
                                                                          "method_name": .string(name)]])
        #expect(await ask("do_user_preset", ["name": "Mein Kamel", "method": "clipasso"]) == ["ok": true])
        #expect(model.studio.method == "clipasso" && model.studio.settings["num_iter"] == 1234)
        state = try #require(await ask("get_studio"))
        #expect(state["user_preset"] == "Mein Kamel")

        let gone = model.texts.tr("ui.phone.page.preset_gone")
        #expect(await ask("do_user_preset", ["name": "Mein Kamel", "method": "swiftsketch"])?["error"] == .string(gone))
        #expect(await ask("do_save_preset", ["name": "Langsam"]) == ["ok": true, "name": "Langsam"])
        #expect(await ask("do_save_preset", ["name": " "])?["error"] == .string(model.texts.tr("ui.phone.page.bad_value")))
        #expect(model.userPresets.map(\.name) == ["Mein Kamel", "Langsam"])
        #expect(await ask("do_delete_preset", ["name": "Mein Kamel", "method": "clipasso"]) == ["ok": true])
        #expect(await ask("do_delete_preset", ["name": "Mein Kamel", "method": "clipasso"])?["error"] == .string(gone))
        #expect(model.userPresets.map(\.name) == ["Langsam"] && model.userPreset == "Langsam")
        #expect(!model.deleteUserPreset("nope", method: "clipasso"))
    }
}
