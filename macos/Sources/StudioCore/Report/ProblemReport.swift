import Foundation

/// Report a problem on GitHub (gui/report.py): a prepared issue – the error, its traceback, the diagnostics – that
/// the user sees and can edit first, opened in the browser. Paths with the user's name are shortened to "~"; a text
/// too long for the address is cut there (the full text goes to the clipboard).
public enum ProblemReport {
    public static let newIssue = "https://github.com/Junostr05/CLIPasso-Studio/issues/new"
    /// characters: browsers and GitHub take about 8 KB
    public static let maxURL = 7000
    static let cut = "\n…\n(cut – the full text is in the clipboard)\n"

    /// anonymize: the home folder (with the user's name) as "~", with either kind of slash.
    public static func anonymize(_ text: String, homes: [String]) -> String {
        var out = text
        for home in Set(homes.filter { $0.count > 3 }).sorted(by: { ($0.count, $0) > ($1.count, $1) }) {
            let variants = Set([home, home.replacingOccurrences(of: "\\", with: "/"),
                                home.replacingOccurrences(of: "/", with: "\\")])
            for variant in variants.sorted() {
                out = out.replacingOccurrences(of: variant, with: "~")
            }
        }
        return out
    }

    /// This user's home folder, as Python's Path.home() and expanduser("~") give it.
    public static var homes: [String] {
        [NSHomeDirectory(), FileManager.default.homeDirectoryForCurrentUser.path]
    }

    /// issue_title: "[version] " and the message's first line (at most 100 characters).
    public static func title(_ message: String, version: String) -> String {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let first = trimmed.split(separator: "\n", omittingEmptySubsequences: false).first, !trimmed.isEmpty
        else { return "[\(version)] " }
        return "[\(version)] \(String(String.UnicodeScalarView(first.unicodeScalars.prefix(100))))"
    }

    /// issue_body: what happened, the steps, the traceback and the diagnostics (Markdown), anonymized.
    public static func body(_ message: String, traceback: String = "", diagnostics: String, homes: [String] = homes)
        -> String
    {
        let what = message.trimmingCharacters(in: .whitespacesAndNewlines)
        var parts = ["**What happened?**", what.isEmpty ? "…" : what, "", "**What did you do before?**", "…", ""]
        let trace = traceback.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trace.isEmpty {
            parts += ["<details><summary>Traceback</summary>", "", "```", trace, "```", "</details>", ""]
        }
        parts += ["<details><summary>Diagnostics</summary>", "", "```",
                  diagnostics.trimmingCharacters(in: .whitespacesAndNewlines), "```", "</details>"]
        return anonymize(parts.joined(separator: "\n"), homes: homes) + "\n"
    }

    /// urllib.parse.quote_plus: letters, digits and "_.-~" stay, a space is "+", the rest %XX of its UTF-8.
    static func quotePlus(_ text: String) -> String {
        var out = ""
        for byte in text.utf8 {
            switch byte {
            case UInt8(ascii: "a") ... UInt8(ascii: "z"), UInt8(ascii: "A") ... UInt8(ascii: "Z"),
                 UInt8(ascii: "0") ... UInt8(ascii: "9"), UInt8(ascii: "_"), UInt8(ascii: "."), UInt8(ascii: "-"),
                 UInt8(ascii: "~"):
                out.unicodeScalars.append(Unicode.Scalar(byte))
            case UInt8(ascii: " "):
                out += "+"
            default:
                out += String(format: "%%%02X", byte)
            }
        }
        return out
    }

    /// issue_url: the address of a new issue with this title and text, and whether the text had to be cut (to the
    /// longest start that fits, with a note).
    public static func url(title: String, body: String, limit: Int = maxURL) -> (url: String, cut: Bool) {
        func address(_ b: String) -> String { "\(newIssue)?title=\(quotePlus(title))&body=\(quotePlus(b))" }
        let full = address(body)
        if full.count <= limit { return (full, false) }
        let scalars = Array(body.unicodeScalars)
        func start(_ n: Int) -> String { String(String.UnicodeScalarView(scalars[0 ..< n])) }
        var lo = 0, hi = scalars.count
        while lo < hi {
            let mid = (lo + hi + 1) / 2
            if address(start(mid) + cut).count <= limit { lo = mid } else { hi = mid - 1 }
        }
        return (address(start(lo) + cut), true)
    }
}
