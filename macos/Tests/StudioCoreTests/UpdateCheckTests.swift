import Foundation
import Testing
@testable import StudioCore

/// Updates are only announced (the user decided: no signing, so no self-update): the newest release as
/// gui/updates.py finds it, newer by the same comparison, and only when it carries a Mac disk image.
@Suite struct UpdateCheckTests {
    @Test func versionsLikePython() throws {
        let cases = try #require(Fixtures.json("versions.json").arrayValue)
        #expect(cases.count == 13)
        for c in cases {
            let o = c.objectValue ?? [:]
            let latest = o["latest"]?.stringValue ?? "", current = o["current"]?.stringValue ?? ""
            #expect(UpdateCheck.parse(latest) == (o["parsed"]?.arrayValue ?? []).compactMap(\.intValue), "\(latest)")
            #expect(UpdateCheck.isNewer(latest, than: current) == o["newer"]?.boolValue, "\(latest) > \(current)")
        }
    }

    struct OneAnswer: HTTPTransport {
        let json: String
        let status: Int

        func open(_ url: URL, offset: Int64) async throws -> HTTPResponse {
            let data = Data(json.utf8)
            return HTTPResponse(status: status, length: Int64(data.count), contentType: "application/json",
                                body: AsyncThrowingStream { $0.yield(data); $0.finish() })
        }
    }

    static func release(_ tag: String, assets: [String], prerelease: Bool = false) -> String {
        let list = assets.map { #"{"name": "\#($0)", "browser_download_url": "https://example.invalid/\#($0)", "size": 1}"# }
        return #"{"tag_name": "\#(tag)", "html_url": "https://github.com/Junostr05/CLIPasso-Studio/releases/tag/\#(tag)", "#
            + #""prerelease": \#(prerelease), "draft": false, "assets": [\#(list.joined(separator: ","))]}"#
    }

    @Test func onlyANewerReleaseWithAMacDiskImage() async throws {
        let mac = Self.release("v4.4.0", assets: ["CLIPassoStudio-CPU-Setup.exe", "CLIPasso-Studio-4.4.0-mac.dmg"])
        let found = try await UpdateCheck.newer(than: "4.3.0", transport: OneAnswer(json: mac, status: 200))
        #expect(found?.version == "v4.4.0" && found?.page.absoluteString.hasSuffix("/tag/v4.4.0") == true)
        // the same release without a Mac build, an older one, a pre-release, an error: nothing to announce
        let windows = Self.release("v4.4.0", assets: ["CLIPassoStudio-CPU-Setup.exe"])
        #expect(try await UpdateCheck.newer(than: "4.3.0", transport: OneAnswer(json: windows, status: 200)) == nil)
        #expect(try await UpdateCheck.newer(than: "4.5.0", transport: OneAnswer(json: mac, status: 200)) == nil)
        let beta = Self.release("v4.4.0b1", assets: ["CLIPasso-Studio-4.4.0b1-mac.dmg"], prerelease: true)
        #expect(try await UpdateCheck.newer(than: "4.3.0", transport: OneAnswer(json: beta, status: 200)) == nil)
        await #expect(throws: (any Error).self) {
            try await UpdateCheck.newer(than: "4.3.0", transport: OneAnswer(json: "{}", status: 403))
        }
    }
}
