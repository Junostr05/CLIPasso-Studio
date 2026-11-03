import Foundation

/// The app settings – the Python app's settings.json (gui/app_settings.py): every key it holds is kept, also those
/// the Mac app does not know, in its order; the Mac app reads and changes only its own. Its secrets
/// (`secretKeys`) are never shown: neither the description nor a dump names their values.
public struct AppSettings: Sendable, Equatable, CustomStringConvertible, CustomDebugStringConvertible,
    CustomReflectable
{
    /// The version gui/app_settings.py writes (SETTINGS_VERSION) – this file has its changes.
    public static let version = 3
    /// Keys whose values stay on this computer: never in a log, a backup to share or a diagnosis.
    public static let secretKeys: Set<String> = ["telegram_token", "remote_token", "remote_pin"]

    public private(set) var data: JSONObject
    /// The folder the sketches go to when the settings name none (paths.default_output_dir).
    public let defaultOutputDir: URL

    public init(data: JSONObject = [:], defaultOutputDir: URL) {
        self.data = data
        self.defaultOutputDir = defaultOutputDir
    }

    public subscript(key: String) -> JSONValue? {
        get { data[key] }
        set { data[key] = newValue }
    }

    /// "auto", "de" or "en" (Texts.resolve makes the language of it).
    public var language: String {
        get { data["language"]?.stringValue ?? "auto" }
        set { data["language"] = .string(newValue) }
    }

    /// "dark" or "light".
    public var theme: String {
        get { data["theme"]?.stringValue ?? "dark" }
        set { data["theme"] = .string(newValue) }
    }

    public var outputDir: URL {
        get {
            guard let path = data["output_dir"]?.stringValue, !path.isEmpty else { return defaultOutputDir }
            return URL(filePath: path, directoryHint: .isDirectory)
        }
        set { data["output_dir"] = .string(newValue.path) }
    }

    /// The folder chosen for the downloaded models; nil: the standard one (paths.default_models_dir).
    public var modelsDir: URL? {
        get {
            guard let path = data["models_dir"]?.stringValue, !path.isEmpty else { return nil }
            return URL(filePath: path, directoryHint: .isDirectory)
        }
        set {
            if let newValue {
                data["models_dir"] = .string(newValue.path)
            } else if data["models_dir"] != nil {
                data["models_dir"] = ""
            }
        }
    }

    /// What AppSettings.__init__ changes in a file of an older version, so both apps read it alike: up to 2.0.0 a
    /// stored "de" was the fixed default (→ "auto"); before version 3 the phone remote over Tailscale was off.
    mutating func migrate() {
        let version = data["settings_version"]?.intValue
        if version == nil, data["language"]?.stringValue == "de" {
            data["language"] = "auto"
        }
        if version.map({ $0 < Self.version }) ?? true {
            data["remote_tailscale"] = true
        }
        data["settings_version"] = .int(Self.version)
    }

    /// The file's text: `json.dumps(data, indent=2)` (ensure_ascii as Python's default).
    public var fileText: String {
        PyJSON.dump(.object(data), indent: 2, asciiOnly: true)
    }

    private var shown: JSONObject {
        var out = data
        for key in Self.secretKeys {
            if let value = out[key], value != "" {
                out[key] = "(hidden)"
            }
        }
        return out
    }

    public var description: String { "AppSettings(\(PyJSON.dump(.object(shown))))" }
    public var debugDescription: String { description }
    public var customMirror: Mirror {
        Mirror(self, children: shown.map { (label: $0.key as String?, value: $0.value as Any) })
    }
}

/// Where the settings live and how they are read and written – as gui/app_settings.py and paths.py do it:
/// written to settings.json.tmp and moved over settings.json (an interrupted write never leaves half a file); the
/// settings that loaded fine are copied to settings.json.bak, which is read when settings.json is missing or damaged.
public struct SettingsStore: Sendable {
    public let url: URL
    public let home: URL

    public init(url: URL, home: URL = FileManager.default.homeDirectoryForCurrentUser) {
        self.url = url
        self.home = home
    }

    /// ~/Library/Application Support/CLIPassoStudio/settings.json (paths.app_settings_file on a Mac).
    public static func standard(home: URL = FileManager.default.homeDirectoryForCurrentUser) -> SettingsStore {
        SettingsStore(url: appDataDir(home: home).appending(path: "settings.json"), home: home)
    }

    /// ~/Library/Application Support/CLIPassoStudio (paths.user_data_dir on a Mac).
    public static func appDataDir(home: URL) -> URL {
        home.appending(path: "Library/Application Support/CLIPassoStudio", directoryHint: .isDirectory)
    }

    public var backupURL: URL { url.deletingLastPathComponent().appending(path: url.lastPathComponent + ".bak") }

    /// ~/Library/Application Support/CLIPassoStudio/models (paths.default_models_dir).
    public var defaultModelsDir: URL {
        url.deletingLastPathComponent().appending(path: "models", directoryHint: .isDirectory)
    }

    /// ~/Documents/CLIPasso Studio, or ~/CLIPasso Studio without a Documents folder (paths.default_output_dir).
    public var defaultOutputDir: URL {
        var docs = home.appending(path: "Documents", directoryHint: .isDirectory)
        if !FileManager.default.fileExists(atPath: docs.path) { docs = home }
        return docs.appending(path: "CLIPasso Studio", directoryHint: .isDirectory)
    }

    /// The stored settings (paths.read_settings_file): settings.json, else its backup, else the defaults. Settings
    /// that loaded from settings.json are copied to the backup.
    public func load() -> AppSettings {
        for (index, source) in [url, backupURL].enumerated() {
            guard let bytes = try? Data(contentsOf: source),
                  let object = (try? PyJSON.parse(bytes))?.objectValue
            else { continue }
            var settings = AppSettings(data: object, defaultOutputDir: defaultOutputDir)
            settings.migrate()
            if index == 0 {
                try? Data(settings.fileText.utf8).write(to: backupURL)
            }
            return settings
        }
        return AppSettings(data: ["settings_version": .int(AppSettings.version)], defaultOutputDir: defaultOutputDir)
    }

    public func save(_ settings: AppSettings) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JobFolder.writeAtomically(settings.fileText, to: url)
    }
}
