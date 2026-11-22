import Foundation
import Testing
@testable import StudioCore

/// The studio's "recent" pictures as pages/studio.py keeps them (Fixtures/recent.json).
@Suite struct RecentImagesTests {
    @Test func likeTheStudio() throws {
        for c in try #require(Fixtures.json("recent.json").arrayValue).compactMap(\.objectValue) {
            let before = (c["before"]?.arrayValue ?? []).compactMap(\.stringValue)
            let after = (c["after"]?.arrayValue ?? []).compactMap(\.stringValue)
            let path = c["path"]?.stringValue ?? ""
            #expect((RecentImages.remember(path, in: before, samples: "/App/samples") ?? before) == after, "\(path)")
        }
        #expect(RecentImages.normalized("/a/./b//c/../d") == "/a/b/d")
    }
}
