import Foundation
@testable import StudioCore

/// The test data made by the Python side (`tools/make_mac_fixtures.py`), never by hand.
enum Fixtures {
    static var root: URL {
        guard let url = Bundle.module.url(forResource: "Fixtures", withExtension: nil) else {
            fatalError("the Fixtures folder is missing from the test bundle")
        }
        return url
    }

    static func url(_ relative: String) -> URL {
        root.appending(path: relative)
    }

    static func data(_ relative: String) throws -> Data {
        try Data(contentsOf: url(relative))
    }

    static func json(_ relative: String) throws -> JSONValue {
        try PyJSON.parse(data(relative))
    }
}
