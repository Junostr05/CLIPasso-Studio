import Foundation
import Testing
@testable import StudioCore

/// The problem report as gui/report.py prepares it (Fixtures/report.json): the home folder made "~", the issue's
/// title and text, its address whole or cut to the limit.
@Suite struct ProblemReportTests {
    @Test func likeTheStudio() throws {
        let cases = try #require(Fixtures.json("report.json").objectValue)
        let home = try #require(cases["home"]?.stringValue)
        for c in cases["anonymize"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            #expect(ProblemReport.anonymize(c["text"]?.stringValue ?? "", homes: [home]) == c["out"]?.stringValue)
        }
        for c in cases["bodies"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            let message = c["message"]?.stringValue ?? ""
            #expect(ProblemReport.title(message, version: "9.9.9") == c["title"]?.stringValue)
            #expect(ProblemReport.body(message, traceback: c["traceback"]?.stringValue ?? "",
                                       diagnostics: c["diagnostics"]?.stringValue ?? "", homes: [home])
                == c["body"]?.stringValue)
        }
        for c in cases["urls"]?.arrayValue?.compactMap(\.objectValue) ?? [] {
            let made = ProblemReport.url(title: c["title"]?.stringValue ?? "", body: c["body"]?.stringValue ?? "",
                                         limit: c["limit"]?.intValue ?? 0)
            #expect(made.url == c["url"]?.stringValue && made.cut == (c["cut"] == true), "limit \(c["limit"] ?? 0)")
        }
    }
}
