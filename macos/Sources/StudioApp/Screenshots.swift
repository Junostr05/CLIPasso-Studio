import Foundation
import StudioCore

/// `CLIPassoStudio --screenshots OUT [--results DIR]`: the window of every page in German and English, dark and
/// light, as PNG files in OUT – for the design and accessibility review of a build (the CI). The app keeps its
/// settings in OUT; with `--results` the gallery shows that output folder.
public struct ScreenshotOptions: Sendable {
    public static let flag = "--screenshots"
    public static let usage = "CLIPassoStudio --screenshots OUT [--results DIR]"
    public static let languages = ["de", "en"]
    public static let appearances: [AppModel.Appearance] = [.dark, .light]

    public var output: URL
    public var results: URL?

    public struct Shot: Sendable, Hashable {
        public let language: String
        public let appearance: AppModel.Appearance
        public let page: String
        public let file: URL
    }

    public static func requested(in arguments: [String]) -> Bool {
        arguments.dropFirst().contains(flag)
    }

    public init(arguments: [String]) throws {
        guard let at = arguments.firstIndex(of: Self.flag), at + 1 < arguments.count,
              !arguments[at + 1].hasPrefix("--")
        else { throw SelfTest.UsageError(description: Self.usage) }
        output = URL(filePath: arguments[at + 1], directoryHint: .isDirectory)
        if let r = arguments.firstIndex(of: "--results") {
            guard r + 1 < arguments.count else { throw SelfTest.UsageError(description: Self.usage) }
            results = URL(filePath: arguments[r + 1], directoryHint: .isDirectory)
        }
    }

    /// Every page in every language and appearance: OUT/<page>-<language>-<appearance>.png
    public func shots(pages: [String]) -> [Shot] {
        Self.languages.flatMap { language in
            Self.appearances.flatMap { appearance in
                pages.map { page in
                    Shot(language: language, appearance: appearance, page: page,
                         file: output.appending(path: "\(page)-\(language)-\(appearance.rawValue).png"))
                }
            }
        }
    }

    /// The settings of the screenshots: in OUT, the gallery on `results`; the exports and prints on watercolour
    /// paper with a vignette (so the print sheet shows a paper).
    public func store() throws -> SettingsStore {
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let store = SettingsStore(url: output.appending(path: "settings.json"), home: output)
        var settings = store.load()
        if let results { settings.outputDir = results }
        settings["export_paper"] = "watercolor"
        settings["export_vignette"] = 30
        settings["export_background"] = .string(Paper.colours[.watercolor] ?? "#FFFFFF")
        try store.save(settings)
        return store
    }
}
