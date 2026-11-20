// swift-tools-version: 6.2
// The Mac app of CLIPasso Studio.
// - StudioCore: the work behind the window – the engine process, the job queue, the job folders, the gallery, the
//   parameter schema, the model downloads – without AppKit or SwiftUI, so `swift test` runs on Linux as well.
// - StudioApp: the app's @Observable models (main actor), also without SwiftUI – tested on Linux too.
// - CLIPassoStudio: the SwiftUI app itself (macOS only); macos/scripts/make_app.sh puts it into an .app.
import PackageDescription

var products: [Product] = [
    .library(name: "StudioCore", targets: ["StudioCore"]),
    .library(name: "StudioApp", targets: ["StudioApp"]),
]

var targets: [Target] = [
    .target(name: "StudioCore"),
    .target(
        name: "StudioApp",
        dependencies: ["StudioCore"],
        swiftSettings: [.defaultIsolation(MainActor.self)]
    ),
    .testTarget(
        name: "StudioCoreTests",
        dependencies: ["StudioCore"],
        resources: [.copy("Fixtures"), .copy("Support/fake_engine.py"), .copy("Support/range_server.py")]
    ),
    .testTarget(
        name: "StudioAppTests",
        dependencies: ["StudioApp"],
        swiftSettings: [.defaultIsolation(MainActor.self)]
    ),
]

#if os(macOS)
    products.append(.executable(name: "CLIPassoStudio", targets: ["CLIPassoStudio"]))
    targets.append(
        .executableTarget(
            name: "CLIPassoStudio",
            dependencies: ["StudioApp", "StudioCore"],
            path: "App/CLIPassoStudio",
            swiftSettings: [.defaultIsolation(MainActor.self)]
        ))
#endif

let package = Package(
    name: "StudioCore",
    platforms: [.macOS(.v26)],
    products: products,
    targets: targets,
    swiftLanguageModes: [.v6]
)
