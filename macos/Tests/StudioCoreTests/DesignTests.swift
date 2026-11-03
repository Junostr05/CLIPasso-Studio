import Foundation
import Testing
@testable import StudioCore

/// The studio's colours (gui/theme.py) reach the Mac app unchanged, and every pair tests/test_theme_contrast.py
/// measures meets its bar there too: text 4.5 : 1, the parts of controls 3 : 1.
@Suite struct DesignTests {
    @Test func theContrastFormula() {
        #expect(abs(contrastRatio("#000000", "#FFFFFF") - 21) < 1e-9)
        #expect(abs(contrastRatio("#777777", "#FFFFFF") - 4.478) < 0.001)
        #expect(contrastRatio("#FFFFFF", "#000000") == contrastRatio("#000000", "#FFFFFF"))
    }

    @Test func everyPairMeetsItsBar() {
        #expect(ContrastPairs.all.count > 100)
        let low = ContrastPairs.all.filter { contrastRatio($0.fg, $0.bg) < $0.minimum }
            .map { "\($0.palette) \($0.what): \(contrastRatio($0.fg, $0.bg))" }
        #expect(low.isEmpty, "\(low)")
    }

    @Test func thePalettesAreTheStudios() {
        #expect(Palette.dark.accent == "#6164F1" && Palette.light.accent == "#4F46E5")
        #expect(Palette.dark.paper == "#FFFFFF" && Palette.light.paper == "#FFFFFF")  // the sketch's paper: white in both
        #expect(Spacing.spaceL == 16 && Radius.card == 10)
        #expect(rgb("#6164F1") == RGB(0x61, 0x64, 0xF1))
    }
}

/// The interface texts come from clipasso_studio/resources/i18n (de.json, en.json) – as the studio shows them.
@Suite struct TextsTests {
    static let i18n = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().appending(path: "clipasso_studio/resources/i18n")

    @Test func germanAndEnglish() throws {
        let de = try Texts(directory: Self.i18n, language: "de")
        let en = try Texts(directory: Self.i18n, language: "en")
        #expect(de.tr("ui.start") == "Skizze erstellen" && en.tr("ui.start") == "Create sketch")
        #expect(de.tr("ui.step.preset") == "Voreinstellung")
        #expect(de.tr("no.such.key") == "no.such.key")
    }

    @Test func placeholdersLikePythonFormat() throws {
        let de = try Texts(directory: Self.i18n, language: "de")
        #expect(de.tr("ui.gallery.state_cancelled", ["done": "2", "total": "5"]) == "Abgebrochen · 2 von 5")
        #expect(de.format("{a} und {b}", ["a": "x"]) == "{a} und {b}")  // a placeholder missing: as it is
        #expect(de.format("{{x}} {a}", ["a": "1"]) == "{x} 1")
    }

    @Test func languageFromTheSetting() {
        #expect(Texts.resolve("de", preferred: ["en-US"]) == "de")
        #expect(Texts.resolve("auto", preferred: ["fr-FR", "de-AT", "en"]) == "de")
        #expect(Texts.resolve("klingon", preferred: ["fr"]) == "en")
    }

    @Test func numbersLikePython() throws {
        let de = try Texts(directory: Self.i18n, language: "de")
        let en = try Texts(directory: Self.i18n, language: "en")
        #expect(de.number(29.43) == "29,4" && en.number(29.43) == "29.4" && de.number(0.25, decimals: 3) == "0,250")
        #expect(de.size(1234) == "1,2 GB" && en.size(1234) == "1.2 GB" && de.size(650) == "650 MB")
    }
}
