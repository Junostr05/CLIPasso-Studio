import Foundation
import Testing
@testable import StudioCore

/// The app settings are the Python app's settings.json – the same place, the same keys, the same way of writing –
/// so settings and backups move between the apps; its secrets are never shown.
@Suite struct AppSettingsTests {
    static func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appending(path: "settings-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    @Test func readsAndRewritesWhatPythonWrote() throws {
        let dir = try Self.folder()
        let url = dir.appending(path: "settings.json")
        let python = try Fixtures.data("settings.json")
        try python.write(to: url)
        let store = SettingsStore(url: url)
        let settings = store.load()
        #expect(settings.language == "de" && settings.theme == "light")
        #expect(settings.outputDir.path == "/Users/Jürgen/Documents/CLIPasso Studio")
        #expect(settings.modelsDir == nil)  // "" = the default folder
        #expect(settings["a_key_of_a_newer_version"] == ["x": 1.5])
        #expect(try Data(contentsOf: dir.appending(path: "settings.json.bak")) == python)  // the copy that loaded fine
        try store.save(settings)
        #expect(try Data(contentsOf: url) == python)  // byte for byte as json.dumps(data, indent=2)
        #expect(!FileManager.default.fileExists(atPath: dir.appending(path: "settings.json.tmp").path))
    }

    @Test func changesKeepEverythingElse() throws {
        let url = try Self.folder().appending(path: "settings.json")
        try Fixtures.data("settings.json").write(to: url)
        let store = SettingsStore(url: url)
        var settings = store.load()
        settings.language = "en"
        settings.outputDir = URL(filePath: "/Volumes/Archiv/Skizzen")
        try store.save(settings)
        let again = store.load()
        #expect(again.language == "en" && again.outputDir.path == "/Volumes/Archiv/Skizzen")
        #expect(again["remote_token"] == "made-up-token" && again["queue"]?.arrayValue?.count == 1)
    }

    @Test func aDamagedFileFallsBackToTheBackup() throws {
        let dir = try Self.folder()
        let url = dir.appending(path: "settings.json")
        try Fixtures.data("settings.json").write(to: dir.appending(path: "settings.json.bak"))
        try Data("{\"language\": ".utf8).write(to: url)  // (power lost while writing)
        #expect(SettingsStore(url: url).load().language == "de")
        try FileManager.default.removeItem(at: dir.appending(path: "settings.json.bak"))
        try FileManager.default.removeItem(at: url)
        let fresh = SettingsStore(url: url).load()
        #expect(fresh.language == "auto" && fresh.theme == "dark")  // the Python app's defaults
        #expect(fresh.outputDir.lastPathComponent == "CLIPasso Studio")
    }

    /// AppSettings.__init__ on a file of an older version: a "de" without a version was the old fixed default, and
    /// before version 3 the remote over Tailscale was off by default.
    @Test func olderFilesChangeAsInThePythonApp() throws {
        let url = try Self.folder().appending(path: "settings.json")
        try Data(#"{"language": "de", "remote_tailscale": false}"#.utf8).write(to: url)
        let old = SettingsStore(url: url).load()
        #expect(old.language == "auto" && old["remote_tailscale"] == true && old["settings_version"] == 3)
        try Data(#"{"settings_version": 2, "language": "de", "remote_tailscale": false}"#.utf8).write(to: url)
        let two = SettingsStore(url: url).load()
        #expect(two.language == "de" && two["remote_tailscale"] == true && two["settings_version"] == 3)
    }

    @Test func secretsAreNeverShown() throws {
        let url = try Self.folder().appending(path: "settings.json")
        try Fixtures.data("settings.json").write(to: url)
        let settings = SettingsStore(url: url).load()
        var dumped = ""
        dump(settings, to: &dumped)
        for text in [String(describing: settings), String(reflecting: settings), "\(settings)", dumped] {
            for secret in ["123:made-up", "made-up-token", "000000"] {
                #expect(!text.contains(secret))
            }
            #expect(text.contains("Tiere"))
        }
    }

    @Test func theStandardPlace() {
        let store = SettingsStore.standard(home: URL(filePath: "/Users/studio"))
        #expect(store.url.path == "/Users/studio/Library/Application Support/CLIPassoStudio/settings.json")
    }
}
